from __future__ import annotations

import argparse
import ctypes
import ipaddress
import json
import mimetypes
import re
import secrets
import socket
import ssl
import threading
import time
import webbrowser
from ctypes import wintypes
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from qa_mission_form import (
    JiraClient,
    JiraError,
    JiraSettings,
    build_create_fields,
    build_mission_data,
    load_rules,
    load_settings,
    normalize_issue_key,
)


APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
TLS_DIR = APP_DIR / "tls.local"
HOST = "0.0.0.0"
DEFAULT_PORT = 8765
MATTERMOST_CONFIG_FILE = APP_DIR / "mattermost_config.local.json"
MATTERMOST_CREDENTIAL_ID = "mattermost-bot"
REDIS_CONFIG_FILE = APP_DIR / "redis_config.local.json"
REDIS_CREDENTIAL_ID = "redis-mapping"
SESSION_COOKIE = "qa_session"
REMEMBER_COOKIE = "qa_remember"
SESSION_TTL_SECONDS = 12 * 60 * 60
REMEMBER_TTL_SECONDS = 30 * 24 * 60 * 60
_sessions: dict[str, dict[str, Any]] = {}
_sessions_lock = threading.Lock()


class AuthenticationError(RuntimeError):
    pass


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialStore:
    PREFIX = "MorrisQAMission/"

    def __init__(self) -> None:
        self.advapi32 = ctypes.WinDLL("Advapi32.dll")
        self.advapi32.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        self.advapi32.CredWriteW.restype = wintypes.BOOL
        self.advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_Credential)),
        ]
        self.advapi32.CredReadW.restype = wintypes.BOOL
        self.advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.advapi32.CredDeleteW.restype = wintypes.BOOL
        self.advapi32.CredFree.argtypes = [ctypes.c_void_p]
        self.advapi32.CredFree.restype = None

    def write(
        self,
        remember_id: str,
        username: str,
        token: str,
        ttl_seconds: int = REMEMBER_TTL_SECONDS,
    ) -> None:
        blob = json.dumps(
            {
                "username": username,
                "token": token,
                "expires_at": time.time() + ttl_seconds,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        if len(blob) > 5000:
            raise ValueError("Token 長度超過 Windows Credential Manager 限制。")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = _Credential()
        credential.Type = 1
        credential.TargetName = self.PREFIX + remember_id
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = 2
        credential.UserName = username
        if not self.advapi32.CredWriteW(ctypes.byref(credential), 0):
            raise ctypes.WinError()

    def read(self, remember_id: str) -> dict[str, str] | None:
        pointer = ctypes.POINTER(_Credential)()
        if not self.advapi32.CredReadW(self.PREFIX + remember_id, 1, 0, ctypes.byref(pointer)):
            return None
        try:
            credential = pointer.contents
            blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            data = json.loads(blob.decode("utf-8"))
            if not isinstance(data, dict):
                return None
            if float(data.get("expires_at", 0)) <= time.time():
                self.delete(remember_id)
                return None
            return {"username": str(data.get("username") or ""), "token": str(data.get("token") or "")}
        finally:
            self.advapi32.CredFree(pointer)

    def delete(self, remember_id: str) -> None:
        self.advapi32.CredDeleteW(self.PREFIX + remember_id, 1, 0)


credential_store = WindowsCredentialStore()


def create_session(username: str, display_name: str, token: str) -> str:
    session_id = secrets.token_urlsafe(32)
    with _sessions_lock:
        _sessions[session_id] = {
            "username": username,
            "display_name": display_name,
            "token": token,
            "expires_at": time.time() + SESSION_TTL_SECONDS,
        }
    return session_id


def read_session(session_id: str) -> dict[str, Any] | None:
    if not session_id:
        return None
    with _sessions_lock:
        session = _sessions.get(session_id)
        if not session:
            return None
        if float(session.get("expires_at", 0)) <= time.time():
            _sessions.pop(session_id, None)
            return None
        session["expires_at"] = time.time() + SESSION_TTL_SECONDS
        return dict(session)


def delete_session(session_id: str) -> None:
    if session_id:
        with _sessions_lock:
            _sessions.pop(session_id, None)


def get_lan_ip() -> str:
    """取得目前預設網路介面的 IPv4，失敗時仍可使用本機網址。"""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 80))
        return str(probe.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def ensure_tls_certificate(lan_ip: str) -> tuple[Path, Path, Path]:
    cert_path = TLS_DIR / "server-cert.pem"
    key_path = TLS_DIR / "server-key.pem"
    ca_path = TLS_DIR / "qa-mission-ca.cer"
    leaf_path = TLS_DIR / "server-cert.cer"
    if cert_path.is_file() and key_path.is_file() and ca_path.is_file() and leaf_path.is_file():
        return cert_path, key_path, ca_path

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    TLS_DIR.mkdir(parents=True, exist_ok=True)
    if cert_path.is_file() and key_path.is_file() and ca_path.is_file():
        existing = x509.load_pem_x509_certificate(cert_path.read_bytes())
        leaf_path.write_bytes(existing.public_bytes(serialization.Encoding.DER))
        return cert_path, key_path, ca_path
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Morris QA Mission Local CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Morris QA Mission")])
    san_names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName(socket.gethostname()),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    if lan_ip != "127.0.0.1":
        san_names.append(x509.IPAddress(ipaddress.ip_address(lan_ip)))
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    leaf_path.write_bytes(server_cert.public_bytes(serialization.Encoding.DER))
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.DER))
    return cert_path, key_path, ca_path


def jira_settings(token: str | None = None) -> JiraSettings:
    settings = load_settings()
    selected_token = str(settings.get("token", "")) if token is None else token
    return JiraSettings(str(settings["base_url"]), selected_token)


def parse_iso_date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"{label}請從日曆選擇有效日期。") from error


def apply_editable_values(
    mission_data: dict[str, Any], payload: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    updated = dict(mission_data)
    editable_values = {
        "summary": ("summary", "摘要"),
        "reporter_id": ("bug_assignee", "BUG 指派人"),
        "test_items": ("test_items", "進測項目"),
        "environment": ("environment", "驗證環境"),
        "version": ("version", "驗證版號"),
        "agent": ("agent", "代理"),
    }
    for mission_key, (payload_key, label) in editable_values.items():
        value = str(payload.get(payload_key) or "").strip()
        if mission_key != "agent" and not value:
            raise ValueError(f"請填入{label}。")
        updated[mission_key] = value

    qa_assignee = str(payload.get("qa_assignee") or "").strip()
    if not qa_assignee:
        raise ValueError("請填入 QA 經辦人。")
    return updated, qa_assignee


def normalize_estimate(value: Any, label: str) -> str:
    estimate = " ".join(str(value or "").strip().lower().split())
    if not estimate:
        raise ValueError(f"請填入{label}。")
    if not re.fullmatch(r"\d+[wdhm](?:\s+\d+[wdhm])*", estimate):
        raise ValueError(f"{label}格式不正確，請使用 1d、4h、30m 或 1d 2h。")
    return estimate


def username_title_name(username: Any) -> str:
    account = str(username or "").strip()
    name = re.sub(r"\d+$", "", account)
    return name or account


def tester_title_name(username: str, testers: Any) -> str:
    for tester in testers or []:
        if not isinstance(tester, dict):
            continue
        if str(tester.get("username") or "").strip() == username:
            configured = str(tester.get("title_name") or "").strip()
            if configured:
                return configured
            break
    return username_title_name(username)


def parse_employee_mattermost_mapping(pairs: Any) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    values = pairs if isinstance(pairs, list) else []
    for index in range(0, len(values) - 1, 2):
        try:
            employee = json.loads(str(values[index + 1]))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(employee, dict):
            continue
        jira_username = str(employee.get("jira") or "").strip()
        mm = employee.get("mm") or {}
        mm_name = str(mm.get("name") or "").strip().lstrip("@") if isinstance(mm, dict) else ""
        user_id = str(mm.get("user_id") or "").strip() if isinstance(mm, dict) else ""
        if jira_username and mm_name:
            mapping[jira_username.casefold()] = {"name": mm_name, "user_id": user_id}
    return mapping


def load_bundled_mattermost_mapping() -> dict[str, dict[str, str]]:
    names = load_rules().get("mattermost_names") or {}
    if not isinstance(names, dict):
        return {}
    return {
        str(jira_username).strip().casefold(): {
            "name": str(mm_name).strip().lstrip("@"),
            "user_id": "",
        }
        for jira_username, mm_name in names.items()
        if str(jira_username).strip() and str(mm_name).strip().lstrip("@")
    }


def load_jira_mattermost_mapping() -> dict[str, dict[str, str]]:
    bundled = load_bundled_mattermost_mapping()
    config = load_redis_config()
    saved = credential_store.read(REDIS_CREDENTIAL_ID)
    if not saved or not saved.get("token"):
        return bundled
    try:
        with RedisClient(
            config["host"],
            config["port"],
            config["db"],
            saved["token"],
            config["username"],
        ) as client:
            pairs = client.command("HGETALL", "employee_data")
        mapping = parse_employee_mattermost_mapping(pairs)
    except RedisError:
        mapping = {}
    return mapping or bundled


def tester_mattermost_name(
    username: str, mapping: dict[str, dict[str, str]]
) -> str:
    employee = mapping.get(username.casefold())
    if not employee or not employee.get("name"):
        raise RedisError(f"Redis 找不到 Jira 帳號 {username} 的 Mattermost 對應。")
    return employee["name"]


def load_mattermost_config() -> dict[str, str]:
    defaults = {
        "base_url": "https://mattermost.example.internal",
        "channel_name": "t",
        "channel_id": "",
        "bot_username": "qa-pepe",
    }
    if not MATTERMOST_CONFIG_FILE.is_file():
        return defaults
    try:
        data = json.loads(MATTERMOST_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    return {**defaults, **{key: str(value or "").strip() for key, value in data.items()}}


def save_mattermost_config(config: dict[str, Any]) -> None:
    safe = {
        "base_url": str(config.get("base_url") or "").strip().rstrip("/"),
        "channel_name": str(config.get("channel_name") or "t").strip(),
        "channel_id": str(config.get("channel_id") or "").strip(),
        "bot_username": str(config.get("bot_username") or "qa-pepe").strip(),
    }
    MATTERMOST_CONFIG_FILE.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_redis_config() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "host": "redis.example.internal",
        "port": 6379,
        "db": 3,
        "username": "",
    }
    if not REDIS_CONFIG_FILE.is_file():
        return defaults
    try:
        data = json.loads(REDIS_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    return {
        "host": str(data.get("host") or defaults["host"]).strip(),
        "port": int(data.get("port") or defaults["port"]),
        "db": int(data.get("db") if data.get("db") is not None else defaults["db"]),
        "username": str(data.get("username") or "").strip(),
    }


def save_redis_config(config: dict[str, Any]) -> None:
    safe = {
        "host": str(config.get("host") or "").strip(),
        "port": int(config.get("port") or 6379),
        "db": int(config.get("db") if config.get("db") is not None else 3),
        "username": str(config.get("username") or "").strip(),
    }
    REDIS_CONFIG_FILE.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class RedisError(RuntimeError):
    pass


class RedisClient:
    def __init__(
        self,
        host: str,
        port: int,
        db: int,
        password: str,
        username: str = "",
        timeout: float = 5,
    ) -> None:
        try:
            self.socket = socket.create_connection((host, port), timeout=timeout)
            self.stream = self.socket.makefile("rb")
            if username:
                self.command("AUTH", username, password)
            else:
                self.command("AUTH", password)
            self.command("SELECT", db)
        except (OSError, RedisError) as error:
            self.close()
            raise RedisError("無法登入 Redis，請確認主機、密碼與 DB。") from error

    def close(self) -> None:
        stream = getattr(self, "stream", None)
        sock = getattr(self, "socket", None)
        if stream:
            stream.close()
        if sock:
            sock.close()
        self.stream = None
        self.socket = None

    def __enter__(self) -> "RedisClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def command(self, *parts: Any) -> Any:
        encoded = [str(part).encode("utf-8") for part in parts]
        request = [f"*{len(encoded)}\r\n".encode("ascii")]
        for part in encoded:
            request.extend([f"${len(part)}\r\n".encode("ascii"), part, b"\r\n"])
        self.socket.sendall(b"".join(request))
        return self._read_response()

    def _read_response(self) -> Any:
        prefix = self.stream.read(1)
        if not prefix:
            raise RedisError("Redis 連線中斷。")
        line = self.stream.readline().rstrip(b"\r\n")
        if prefix == b"+":
            return line.decode("utf-8", errors="replace")
        if prefix == b"-":
            raise RedisError(line.decode("utf-8", errors="replace"))
        if prefix == b":":
            return int(line)
        if prefix == b"$":
            length = int(line)
            if length < 0:
                return None
            data = self.stream.read(length)
            self.stream.read(2)
            return data.decode("utf-8", errors="replace")
        if prefix == b"*":
            length = int(line)
            return [self._read_response() for _ in range(max(length, 0))]
        raise RedisError("Redis 回應格式不正確。")


class MattermostError(RuntimeError):
    pass


class MattermostClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.token = token.strip()
        if not self.base_url or not self.token:
            raise MattermostError("Mattermost 尚未完成設定。")

    def request(self, method: str, path: str, payload: Any = None) -> Any:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "Morris-QA-Mission-Tool/1.0",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as error:
            raise MattermostError(f"Mattermost API 驗證或權限失敗（HTTP {error.code}）。") from error
        except (URLError, TimeoutError) as error:
            raise MattermostError("無法連線 Mattermost。") from error
        return json.loads(raw) if raw else {}

    def find_channel(self, channel_name: str) -> dict[str, Any]:
        target = channel_name.strip().casefold()
        teams = self.request("GET", "/api/v4/users/me/teams")
        matches: list[dict[str, Any]] = []
        for team in teams if isinstance(teams, list) else []:
            team_id = str(team.get("id") or "")
            if not team_id:
                continue
            channels = self.request("GET", f"/api/v4/users/me/teams/{team_id}/channels")
            for channel in channels if isinstance(channels, list) else []:
                names = {
                    str(channel.get("name") or "").strip().casefold(),
                    str(channel.get("display_name") or "").strip().casefold(),
                }
                if target in names:
                    matches.append(channel)
        unique = {str(item.get("id") or ""): item for item in matches if item.get("id")}
        if len(unique) != 1:
            raise MattermostError(
                f"Mattermost 找不到唯一的 {channel_name} 頻道，請確認機器人已加入該頻道。"
            )
        return next(iter(unique.values()))

    def post(self, channel_id: str, message: str) -> dict[str, Any]:
        result = self.request(
            "POST", "/api/v4/posts", {"channel_id": channel_id, "message": message}
        )
        if not isinstance(result, dict) or not result.get("id"):
            raise MattermostError("Mattermost 沒有回傳訊息 ID。")
        return result


def build_mattermost_subtask_message(
    parent_key: str,
    parent_summary: str,
    parent_url: str,
    usernames: list[str],
    jira_mattermost_mapping: dict[str, dict[str, str]],
    deadline: date,
) -> tuple[str, date]:
    mentions = " ".join(
        f"@{tester_mattermost_name(name, jira_mattermost_mapping)}" for name in usernames
    )
    message = "\n".join(
        [
            mentions,
            "",
            parent_summary.strip() or parent_key,
            parent_url,
            "",
            f"※手上項目驗證完可執行此項目請在 {deadline.month}/{deadline.day}下班前完成，如果無法完成請提前告知",
        ]
    )
    return message, deadline


def send_mattermost_subtask_notification(
    parent_issue: dict[str, Any],
    created: list[dict[str, str]],
    deadline: date,
    jira_base_url: str,
) -> dict[str, Any]:
    if not created:
        return {"sent": False, "configured": True}
    saved = credential_store.read(MATTERMOST_CREDENTIAL_ID)
    if not saved or not saved.get("token"):
        return {"sent": False, "configured": False}
    config = load_mattermost_config()
    client = MattermostClient(config["base_url"], saved["token"])
    jira_mattermost_mapping = load_jira_mattermost_mapping()
    missing = [
        item["username"]
        for item in created
        if item["username"].casefold() not in jira_mattermost_mapping
    ]
    if missing:
        raise RedisError("Redis 缺少 Mattermost 對應：" + "、".join(missing))
    channel_id = config.get("channel_id", "")
    if not channel_id:
        channel = client.find_channel(config["channel_name"])
        channel_id = str(channel["id"])
        save_mattermost_config({**config, "channel_id": channel_id})
    parent_key = normalize_issue_key(str(parent_issue.get("key") or ""))
    message, deadline = build_mattermost_subtask_message(
        parent_key,
        str((parent_issue.get("fields") or {}).get("summary") or ""),
        f"{jira_base_url.rstrip('/')}/browse/{parent_key}",
        [item["username"] for item in created],
        jira_mattermost_mapping,
        deadline,
    )
    post = client.post(channel_id, message)
    return {
        "sent": True,
        "configured": True,
        "post_id": str(post["id"]),
        "deadline": deadline.isoformat(),
    }


def get_subtask_metadata(
    metadata: dict[str, Any], project_key: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    for project in metadata.get("projects") or []:
        if str(project.get("key", "")).casefold() != project_key.casefold():
            continue
        for issue_type in project.get("issuetypes") or []:
            if issue_type.get("subtask"):
                project_ref = {"id": str(project["id"])} if project.get("id") else {"key": project_key}
                type_ref = {"id": str(issue_type["id"])} if issue_type.get("id") else {"name": issue_type["name"]}
                return {"project": project_ref, "issuetype": type_ref}, issue_type.get("fields") or {}
    raise ValueError(f"Jira Create 找不到專案 {project_key} 的子任務類型。")


def build_subtask_fields(
    metadata: dict[str, Any], parent_issue: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    parent_key = normalize_issue_key(str(parent_issue.get("key") or ""))
    parent_fields = parent_issue.get("fields") or {}
    project = parent_fields.get("project") or {}
    project_key = str(project.get("key") or "QA")
    if project_key.casefold() != "qa":
        raise ValueError("請輸入 QA 專案的主單號。")

    member_name = str(payload.get("member_name") or "").strip()
    assignee = str(payload.get("assignee") or "").strip()
    if not member_name:
        raise ValueError("請填入測試人員姓名。")
    if not assignee:
        raise ValueError("請填入測試人員 Jira 帳號。")
    original = normalize_estimate(payload.get("original_estimate"), "原始預估時間")
    remaining = normalize_estimate(payload.get("remaining_estimate"), "剩餘時間")
    deadline = parse_iso_date(payload.get("deadline"), "Deadline")

    references, create_fields = get_subtask_metadata(metadata, project_key)
    description = str(parent_fields.get("description") or "").strip()
    fields: dict[str, Any] = {
        **references,
        "parent": {"key": parent_key},
        "summary": f"{str(parent_fields.get('summary') or parent_key).strip()}_{member_name}",
        "description": description or f"由 QA 主單 {parent_key} 建立的子任務",
        "assignee": {"name": assignee},
        "timetracking": {
            "originalEstimate": original,
            "remainingEstimate": remaining,
        },
    }

    copy_values = {
        "duedate": parent_fields.get("duedate"),
        "priority": parent_fields.get("priority"),
        "labels": parent_fields.get("labels"),
        "components": parent_fields.get("components"),
        "fixVersions": parent_fields.get("fixVersions"),
    }
    for field_id, value in copy_values.items():
        if field_id in create_fields and value not in (None, "", []):
            if field_id in {"priority"}:
                value = {"id": str(value["id"])} if value.get("id") else {"name": value.get("name")}
            elif field_id in {"components", "fixVersions"}:
                value = [{"id": str(item["id"])} for item in value if item.get("id")]
            fields[field_id] = value

    for field_id, field_meta in create_fields.items():
        field_name = str(field_meta.get("name") or "").strip().casefold()
        if field_name == "deadline":
            fields[field_id] = deadline.isoformat()
        elif field_name == "start date":
            start_value = parent_fields.get(field_id)
            if start_value:
                fields[field_id] = start_value

    missing_required = [
        str(field_meta.get("name") or field_id)
        for field_id, field_meta in create_fields.items()
        if field_meta.get("required")
        and field_id not in fields
        and not field_meta.get("hasDefaultValue")
    ]
    if missing_required:
        raise ValueError("QA 主單缺少子任務必填欄位：" + "、".join(missing_required))
    return fields


def load_main_issue(
    issue_key_value: Any, settings: JiraSettings | None = None
) -> dict[str, Any]:
    issue_key = normalize_issue_key(str(issue_key_value or ""))
    settings = settings or jira_settings()
    rules = load_rules()
    issue = JiraClient(settings).get_issue(issue_key)
    data = build_mission_data(issue, settings.base_url, rules)
    return {
        "main_issue_key": data["main_issue_key"],
        "main_issue_url": data["main_issue_url"],
        "summary": data["summary"],
        "bug_assignee": data["reporter_id"],
        "qa_assignee": rules.get("assignee", "arsene211"),
        "test_items": data["test_items"],
        "environment": data["environment"],
        "version": data["version"],
        "agent": data["agent"],
    }


def create_qa_mission(
    payload: dict[str, Any], settings: JiraSettings | None = None
) -> dict[str, str]:
    issue_key = normalize_issue_key(str(payload.get("main_issue_key") or ""))
    test_cases = str(payload.get("test_cases") or "").strip()
    epic_link = str(payload.get("epic_link") or "").strip()
    if not test_cases:
        raise ValueError("請填入測試案例。")
    if not epic_link:
        raise ValueError("請選擇 Epic Link。")
    start_date = parse_iso_date(payload.get("start_date"), "Start Date")
    due_date = parse_iso_date(payload.get("due_date"), "到期日")
    if due_date < start_date:
        raise ValueError("到期日不可早於 Start Date。")

    settings = settings or jira_settings()
    rules = load_rules()
    client = JiraClient(settings)
    issue = client.get_issue(issue_key)
    mission_data = build_mission_data(issue, settings.base_url, rules)
    mission_data, qa_assignee = apply_editable_values(mission_data, payload)
    rules = {**rules, "assignee": qa_assignee}

    form_values = {
        "test_cases": test_cases,
        "start_date_api": start_date.isoformat(),
        "due_date_api": due_date.isoformat(),
        "epic_link": epic_link,
    }
    metadata = client.get_create_metadata(rules["project_key"], rules["issue_type"])
    fields, unresolved, missing_required = build_create_fields(
        metadata, mission_data, form_values, rules
    )
    if missing_required:
        raise ValueError("Jira 尚缺少必填欄位：" + "、".join(missing_required))
    if unresolved:
        raise ValueError("Jira Create 找不到欄位：" + "、".join(unresolved))

    result = client.create_issue(fields)
    created_key = str(result.get("key") or "").strip()
    if not created_key:
        raise RuntimeError(f"Jira 沒有回傳新單號：{result}")
    return {
        "key": created_key,
        "url": f"{settings.base_url.rstrip('/')}/browse/{created_key}",
    }


def load_subtask_parent(
    issue_key_value: Any, settings: JiraSettings | None = None
) -> dict[str, Any]:
    issue_key = normalize_issue_key(str(issue_key_value or ""))
    settings = settings or jira_settings()
    issue = JiraClient(settings).get_issue(issue_key)
    fields = issue.get("fields") or {}
    project_key = str((fields.get("project") or {}).get("key") or "")
    if project_key.casefold() != "qa":
        raise ValueError("請輸入 QA 專案的主單號。")
    return {
        "parent_key": issue_key,
        "parent_url": f"{settings.base_url.rstrip('/')}/browse/{issue_key}",
        "summary": str(fields.get("summary") or ""),
        "start_date": fields.get("customfield_10202") or "",
        "due_date": fields.get("duedate") or "",
    }


def create_qa_subtask(
    payload: dict[str, Any], settings: JiraSettings | None = None
) -> dict[str, str]:
    parent_key = normalize_issue_key(str(payload.get("parent_key") or ""))
    settings = settings or jira_settings()
    client = JiraClient(settings)
    parent_issue = client.get_issue(parent_key)
    metadata = client.get_create_metadata("QA", "Sub-task")
    fields = build_subtask_fields(metadata, parent_issue, payload)
    result = client.create_issue(fields)
    created_key = str(result.get("key") or "").strip()
    if not created_key:
        raise RuntimeError(f"Jira 沒有回傳新子任務單號：{result}")
    return {
        "key": created_key,
        "url": f"{settings.base_url.rstrip('/')}/browse/{created_key}",
    }


def validate_selected_members(members: Any, testers: Any) -> list[str]:
    if not isinstance(members, list) or not members:
        raise ValueError("請至少選擇一位測試人員。")
    if len(members) > 30:
        raise ValueError("一次最多建立 30 張子任務。")
    allowed = {
        str(item.get("username") or "").strip()
        for item in testers or []
        if isinstance(item, dict)
    }
    selected = list(dict.fromkeys(str(member or "").strip() for member in members))
    invalid = [member for member in selected if not member or member not in allowed]
    if invalid:
        raise ValueError("測試人員不在清單中：" + "、".join(invalid))
    return selected


def create_qa_subtasks(
    payload: dict[str, Any], settings: JiraSettings | None = None
) -> dict[str, Any]:
    rules = load_rules()
    testers = rules.get("testers", [])
    selected = validate_selected_members(payload.get("members"), testers)
    deadline = parse_iso_date(payload.get("deadline"), "Deadline")

    parent_key = normalize_issue_key(str(payload.get("parent_key") or ""))
    settings = settings or jira_settings()
    client = JiraClient(settings)
    parent_issue = client.get_issue(parent_key)
    metadata = client.get_create_metadata("QA", "Sub-task")

    planned: list[tuple[str, dict[str, Any]]] = []
    for username in selected:
        member_payload = {
            **payload,
            "member_name": tester_title_name(username, testers),
            "assignee": username,
        }
        planned.append((username, build_subtask_fields(metadata, parent_issue, member_payload)))

    created: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for username, fields in planned:
        try:
            result = client.create_issue(fields)
            created_key = str(result.get("key") or "").strip()
            if not created_key:
                raise RuntimeError(f"Jira 沒有回傳新子任務單號：{result}")
            created.append(
                {
                    "username": username,
                    "key": created_key,
                    "url": f"{settings.base_url.rstrip('/')}/browse/{created_key}",
                }
            )
        except Exception as error:
            errors.append({"username": username, "error": str(error)})
    try:
        mattermost = send_mattermost_subtask_notification(
            parent_issue,
            created,
            deadline,
            settings.base_url,
        )
    except Exception as error:
        mattermost = {
            "sent": False,
            "configured": True,
            "error": str(error),
        }
    return {"created": created, "errors": errors, "mattermost": mattermost}


def authenticate_jira_user(username: Any, token: Any) -> tuple[str, str, str]:
    account = str(username or "").strip()
    secret = str(token or "").strip()
    if not account:
        raise AuthenticationError("請輸入 Jira 帳號。")
    if not secret:
        raise AuthenticationError("請輸入 Jira Token。")
    settings = jira_settings(secret)
    try:
        user = JiraClient(settings).get_current_user(timeout=15)
    except JiraError as error:
        raise AuthenticationError(
            "無法使用此 Token 登入 Jira。請確認 Token 正確、尚未過期，且目前可連線到 Jira。"
        ) from error
    jira_name = str(user.get("name") or "").strip()
    jira_key = str(user.get("key") or "").strip()
    display_name = str(user.get("displayName") or jira_name or jira_key or account).strip()
    identities = {value.casefold() for value in (jira_name, jira_key, display_name) if value}
    if account.casefold() not in identities:
        raise AuthenticationError(
            f"此 Token 屬於 {jira_name or display_name or jira_key}，與輸入的 Jira 帳號不一致。"
        )
    return jira_name or account, display_name, secret


def cookie_value(cookie_header: str | None, name: str) -> str:
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header or "")
    except Exception:
        return ""
    morsel = cookie.get(name)
    return morsel.value if morsel else ""


def secure_cookie(name: str, value: str, max_age: int) -> str:
    return (
        f"{name}={value}; Path=/; Max-Age={max_age}; "
        "HttpOnly; SameSite=Strict"
    )


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class QaMissionWebHandler(BaseHTTPRequestHandler):
    server_version = "MorrisQAMission/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(
        self, status: int, payload: dict[str, Any], headers: list[tuple[str, str]] | None = None
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in headers or []:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def current_session(self) -> dict[str, Any] | None:
        session_id = cookie_value(self.headers.get("Cookie"), SESSION_COOKIE)
        return read_session(session_id)

    def require_settings(self) -> JiraSettings:
        session = self.current_session()
        if not session:
            raise AuthenticationError("登入已失效，請重新登入。")
        return jira_settings(str(session["token"]))

    def restore_remembered_session(self) -> tuple[dict[str, Any] | None, str]:
        remember_id = cookie_value(self.headers.get("Cookie"), REMEMBER_COOKIE)
        if not remember_id:
            return None, ""
        saved = credential_store.read(remember_id)
        if not saved:
            return None, ""
        try:
            username, display_name, token = authenticate_jira_user(
                saved.get("username"), saved.get("token")
            )
        except Exception:
            credential_store.delete(remember_id)
            return None, ""
        session_id = create_session(username, display_name, token)
        return read_session(session_id), session_id

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            raise ValueError("請求內容不正確。")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("請求內容必須是 JSON 物件。")
        return data

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/api/session":
            session = self.current_session()
            session_id = ""
            if not session:
                session, session_id = self.restore_remembered_session()
            headers = []
            if session_id:
                headers.append(("Set-Cookie", secure_cookie(SESSION_COOKIE, session_id, SESSION_TTL_SECONDS)))
            if not session:
                self.send_json(200, {"authenticated": False}, headers)
                return
            self.send_json(
                200,
                {
                    "authenticated": True,
                    "username": session["username"],
                    "display_name": session["display_name"],
                },
                headers,
            )
            return
        if path == "/api/config":
            try:
                self.require_settings()
            except AuthenticationError as error:
                self.send_json(401, {"error": str(error)})
                return
            rules = load_rules()
            self.send_json(
                200,
                {
                    "epic_links": rules["epic_links"],
                    "qa_assignee": rules.get("assignee", "arsene211"),
                    "testers": rules.get("testers", []),
                },
            )
            return
        if path == "/api/health":
            self.send_json(200, {"status": "ok"})
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/login":
                username, display_name, token = authenticate_jira_user(
                    payload.get("username"), payload.get("token")
                )
                delete_session(cookie_value(self.headers.get("Cookie"), SESSION_COOKIE))
                previous_remember_id = cookie_value(
                    self.headers.get("Cookie"), REMEMBER_COOKIE
                )
                if previous_remember_id:
                    credential_store.delete(previous_remember_id)
                session_id = create_session(username, display_name, token)
                headers = [
                    ("Set-Cookie", secure_cookie(SESSION_COOKIE, session_id, SESSION_TTL_SECONDS))
                ]
                if bool(payload.get("remember")):
                    remember_id = secrets.token_urlsafe(32)
                    credential_store.write(remember_id, username, token)
                    headers.append(
                        (
                            "Set-Cookie",
                            secure_cookie(REMEMBER_COOKIE, remember_id, REMEMBER_TTL_SECONDS),
                        )
                    )
                else:
                    headers.append(("Set-Cookie", secure_cookie(REMEMBER_COOKIE, "", 0)))
                self.send_json(
                    200,
                    {"username": username, "display_name": display_name},
                    headers,
                )
                return
            if path == "/api/logout":
                delete_session(cookie_value(self.headers.get("Cookie"), SESSION_COOKIE))
                remember_id = cookie_value(self.headers.get("Cookie"), REMEMBER_COOKIE)
                if remember_id:
                    credential_store.delete(remember_id)
                self.send_json(
                    200,
                    {"logged_out": True},
                    [
                        ("Set-Cookie", secure_cookie(SESSION_COOKIE, "", 0)),
                        ("Set-Cookie", secure_cookie(REMEMBER_COOKIE, "", 0)),
                    ],
                )
                return

            settings = self.require_settings()
            if path == "/api/load-main":
                result = load_main_issue(payload.get("issue_key"), settings)
            elif path == "/api/create":
                result = create_qa_mission(payload, settings)
            elif path == "/api/load-subtask-parent":
                result = load_subtask_parent(payload.get("parent_key"), settings)
            elif path == "/api/create-subtask":
                result = create_qa_subtask(payload, settings)
            elif path == "/api/create-subtasks":
                result = create_qa_subtasks(payload, settings)
            else:
                self.send_json(404, {"error": "找不到 API。"})
                return
        except AuthenticationError as error:
            self.send_json(401, {"error": str(error)})
            return
        except Exception as error:
            self.send_json(400, {"error": str(error)})
            return
        self.send_json(200, result)

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (WEB_DIR / relative).resolve()
        if WEB_DIR.resolve() not in target.parents and target != WEB_DIR.resolve():
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Jira QA_Mission 本機網頁工具")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    lan_ip = get_lan_ip()
    local_url = f"http://127.0.0.1:{args.port}"
    lan_url = f"http://{lan_ip}:{args.port}"
    try:
        server = ExclusiveThreadingHTTPServer((args.host, args.port), QaMissionWebHandler)
    except OSError as error:
        if getattr(error, "winerror", None) != 10048:
            raise
        print(f"QA Mission 工具已經在執行：{local_url}")
        print(f"同事可使用內網網址：{lan_url}")
        if not args.no_browser:
            webbrowser.open(local_url)
        return
    print(f"QA Mission 工具已啟動：{local_url}")
    print(f"同事可使用內網網址：{lan_url}")
    print("關閉此視窗即可停止工具。")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(local_url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

import argparse
import json
import mimetypes
import os
import re
import socket
import threading
import time
import webbrowser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request, urlopen

import pandas as pd

from qa_analyzer import (
    CHINESE_MONTHS,
    EXCEL_URL,
    extract_names,
    process_qa_data,
    super_clean_date,
)


APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
JIRA_BUG_DIR = APP_DIR.parent / "05_jirabug" / "Jira_Bug_Report_Tool_v7"
# 完整分享包會把 Token 放在專案根目錄；保留舊路徑相容既有資料夾結構。
LOCAL_JIRA_CONFIG = APP_DIR / "jira_config.local.json"
LEGACY_JIRA_CONFIG = JIRA_BUG_DIR / "jira_config.local.json"
JIRA_CONFIG = LOCAL_JIRA_CONFIG if LOCAL_JIRA_CONFIG.is_file() else LEGACY_JIRA_CONFIG
JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://pmo-jira.qyrc452.com").rstrip("/")
HOST = "0.0.0.0"
DEFAULT_PORT = 8766
PDF_EXPORT_LOCK = threading.Lock()

JIRA_USERS = {
    "arthur734": "arthur",
    "lisa735": "lisa",
    "ralflin460": "ralf",
    "peter210": "peter",
    "arsene211": "arsene",
    "joey209": "joey",
    "rose603": "rose",
    "morris706": "morris",
    "leo296": "leo",
    "mincy295": "mincy",
    "ben654": "ben",
    "lydia736": "lydia",
    "lily265": "lily",
}

JIRA_USER_SUFFIXES = {
    "arthur734": "Arthur",
    "lisa735": "Lisa",
    "ralflin460": "Ralf",
    "peter210": "Peter",
    "arsene211": "Arsene",
    "joey209": "Joey",
    "rose603": "Rose",
    "morris706": "Morris",
    "leo296": "Leo",
    "mincy295": "Mincy",
    "ben654": "Ben",
    "lydia736": "Lydia",
    "lily265": "Lily",
}
TAIPEI_TZ = timezone(timedelta(hours=8))


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


def available_months() -> dict[str, Any]:
    with pd.ExcelFile(EXCEL_URL, engine="openpyxl") as workbook:
        months = sorted(
            sheet_name[:6]
            for sheet_name in workbook.sheet_names
            if re.fullmatch(r"\d{6}\(done\)", sheet_name)
        )
        current = date.today().strftime("%Y%m")
        in_progress = f"進行中({CHINESE_MONTHS[date.today().month]})"
        return {
            "months": months,
            "current_month": current,
            "current_month_has_in_progress": in_progress in workbook.sheet_names,
            "in_progress_sheet": in_progress,
        }


def analyze_month(year: int, month: int) -> dict[str, Any]:
    selected = date(year, month, 1)
    if selected > date.today().replace(day=1):
        raise ValueError("不能選擇未來月份。")

    success, result = process_qa_data(year, month)
    if not success:
        raise ValueError(str(result))

    person_stats = [
        {
            "name": str(row["人員"]),
            "manual": int(row["手動單數"]),
            "automation": int(row["自動化單數"]),
            "total": int(row["合計"]),
        }
        for _, row in result["person_stats"].iterrows()
    ]
    peak_days = [
        {
            "date": str(row["日期字串"]),
            "count": int(row["項目總數"]),
        }
        for _, row in result["top_6"].iterrows()
    ]

    return {
        "month": f"{year:04d}{month:02d}",
        "source_sheets": list(result["source_sheets"]),
        "is_current_month": bool(result["is_current_month"]),
        "total_items": int(result["total_items"]),
        "workdays": int(result["workdays"]),
        "avg_per_day": round(float(result["avg_per_day"]), 2),
        "manual_total": sum(row["manual"] for row in person_stats),
        "automation_total": sum(row["automation"] for row in person_stats),
        "person_stats": person_stats,
        "peak_days": peak_days,
    }


def _normalize_in_progress(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.rename(columns={
        "手動測試": "人員",
        "自動化測試": "自動化",
    }).copy()

    progress_dates = frame.get("進測日期", pd.Series(index=frame.index, dtype=object))
    first_column = frame.iloc[:, 0] if len(frame.columns) else pd.Series(index=frame.index, dtype=object)
    frame["統計日期"] = progress_dates.where(progress_dates.notna(), first_column)

    if "測試項目" in frame.columns:
        frame = frame[frame["測試項目"].astype(str).ne("測試項目")]
    assigned = (
        frame.get("人員", pd.Series(index=frame.index, dtype=object)).notna()
        | frame.get("自動化", pd.Series(index=frame.index, dtype=object)).notna()
    )
    return frame[assigned].copy()


def analyze_task_range(start: date, end: date) -> dict[str, Any]:
    with pd.ExcelFile(EXCEL_URL, engine="openpyxl") as workbook:
        done_sheets = sorted(
            sheet_name
            for sheet_name in workbook.sheet_names
            if re.fullmatch(r"\d{6}\(done\)", sheet_name)
        )
        if not done_sheets:
            raise ValueError("找不到 YYYYMM(done) 工作表。")

        required_months: set[str] = set()
        cursor = start.replace(day=1)
        end_month = end.replace(day=1)
        while cursor <= end_month:
            required_months.add(cursor.strftime("%Y%m"))
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)

        frames: list[pd.DataFrame] = []
        source_sheets: list[str] = []
        for sheet_name in done_sheets:
            if sheet_name[:6] not in required_months:
                continue
            frame = pd.read_excel(workbook, sheet_name=sheet_name)
            if "發測日期" not in frame.columns:
                continue
            frame = frame.copy()
            frame["統計日期"] = frame["發測日期"]
            frames.append(frame)
            source_sheets.append(sheet_name)

        current_first = date.today().replace(day=1)
        range_overlaps_current_month = start <= date.today() and end >= current_first
        in_progress_sheet = f"進行中({CHINESE_MONTHS[date.today().month]})"
        if range_overlaps_current_month and in_progress_sheet in workbook.sheet_names:
            frames.append(_normalize_in_progress(pd.read_excel(workbook, sheet_name=in_progress_sheet)))
            source_sheets.append(in_progress_sheet)

    if not frames:
        return {
            "manual_counts": Counter(),
            "automation_counts": Counter(),
            "daily_counts": Counter(),
            "task_rows": 0,
            "source_sheets": [],
        }

    combined = pd.concat(frames, ignore_index=True, sort=False)
    clean_dates = combined["統計日期"].apply(super_clean_date)
    converted = pd.to_datetime(clean_dates, errors="coerce")
    valid = converted.between(pd.Timestamp(start), pd.Timestamp(end))
    combined = combined[valid].copy()
    combined["統計日期"] = converted[valid]

    manual_counts: Counter[str] = Counter()
    automation_counts: Counter[str] = Counter()
    daily_counts: Counter[str] = Counter()
    for _, row in combined.iterrows():
        manual_names = extract_names(row.get("人員"))
        automation_names = extract_names(row.get("自動化"))
        manual_counts.update(manual_names)
        automation_counts.update(automation_names)
        day = row["統計日期"].strftime("%Y-%m-%d")
        daily_counts[day] += len(manual_names) + len(automation_names)

    return {
        "manual_counts": manual_counts,
        "automation_counts": automation_counts,
        "daily_counts": daily_counts,
        "task_rows": len(combined),
        "source_sheets": source_sheets,
    }


def _jira_token() -> str:
    if not JIRA_CONFIG.is_file():
        raise ValueError("找不到 Jira Token 設定檔。")
    token = str(json.loads(JIRA_CONFIG.read_text(encoding="utf-8")).get("token", "")).strip()
    if not token:
        raise ValueError("Jira 尚未設定 Token。")
    return token


def _jira_get(path: str, params: dict[str, Any], token: str) -> dict[str, Any]:
    url = f"{JIRA_BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    request = Request(url, headers={
        "Accept": "application/json",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Authorization": f"Bearer {token}",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
        ),
    })
    for attempt in range(3):
        try:
            with urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code in {429, 502, 503, 504} and attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
                continue
            body = error.read().decode("utf-8", errors="replace")[-500:]
            raise ValueError(f"Jira API 查詢失敗（HTTP {error.code}）：{body}") from error
        except URLError as error:
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise ValueError(f"Jira API 連線失敗：{error.reason}") from error
    raise ValueError("Jira API 查詢失敗。")


def _jira_search(jql: str, fields: str, token: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    start_at = 0
    while True:
        data = _jira_get("/rest/api/2/search", {
            "jql": jql,
            "startAt": start_at,
            "maxResults": 100,
            "fields": fields,
        }, token)
        current = list(data.get("issues") or [])
        issues.extend(current)
        start_at += len(current)
        if not current or start_at >= int(data.get("total", start_at)):
            return issues


def _jira_user(author: Any) -> str | None:
    if not isinstance(author, dict):
        return None
    keys: set[str] = set()
    for field in ("name", "key", "displayName", "emailAddress", "accountId"):
        value = str(author.get(field, "")).strip().lower()
        if value:
            keys.add(value)
            if "@" in value:
                keys.add(value.split("@", 1)[0])
    return next((user for user in JIRA_USERS if user in keys), None)


def _summary_matches_user(summary: str, user: str) -> bool:
    if user == "arsene211":
        return True
    suffix = JIRA_USER_SUFFIXES.get(user)
    return bool(suffix and re.search(rf"_{re.escape(suffix)}$", summary.strip(), re.IGNORECASE))


def _jira_started_date(value: str) -> date:
    normalized = value.strip().replace("Z", "+00:00")
    normalized = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", normalized)
    return datetime.fromisoformat(normalized).astimezone(TAIPEI_TZ).date()


def analyze_jira_bugs(start: date, end: date) -> dict[str, Any]:
    token = _jira_token()
    users = ", ".join(f'"{user}"' for user in JIRA_USERS)
    jql = (
        'issuetype = "Bug" AND project != "QA" '
        f"AND reporter in ({users}) "
        f'AND created >= "{start.isoformat()}" '
        f'AND created < "{(end + timedelta(days=1)).isoformat()}" ORDER BY key ASC'
    )
    issues = _jira_search(jql, "created,reporter", token)
    bug_counts: Counter[str] = Counter()
    daily_counts: Counter[str] = Counter()
    for issue in issues:
        fields = issue.get("fields") or {}
        user = _jira_user(fields.get("reporter"))
        name = JIRA_USERS.get(user or "")
        if not name:
            continue
        bug_counts[name] += 1
        created = str(fields.get("created", ""))[:10]
        if created:
            daily_counts[created] += 1
    return {"bug_counts": bug_counts, "daily_counts": daily_counts, "bug_total": sum(bug_counts.values())}


def _issue_worklogs(issue: dict[str, Any], token: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issue_key = str(issue.get("key", ""))
    embedded = (issue.get("fields") or {}).get("worklog") or {}
    worklogs: list[dict[str, Any]] = list(embedded.get("worklogs") or [])
    embedded_total = int(embedded.get("total", len(worklogs)))
    if len(worklogs) >= embedded_total:
        return issue, worklogs

    start_at = len(worklogs)
    while issue_key:
        data = _jira_get(f"/rest/api/2/issue/{issue_key}/worklog", {
            "startAt": start_at,
            "maxResults": 100,
        }, token)
        current = list(data.get("worklogs") or [])
        worklogs.extend(current)
        start_at += len(current)
        if not current or start_at >= int(data.get("total", start_at)):
            break
    return issue, worklogs


def analyze_jira_worklogs(start: date, end: date) -> dict[str, Any]:
    token = _jira_token()
    jql = (
        'project = "QA" '
        f'AND worklogDate >= "{start.isoformat()}" '
        f'AND worklogDate <= "{end.isoformat()}" ORDER BY key ASC'
    )
    # Jira search 回應可直接夾帶每張單的 Worklog；大多數單不需要再發第二次 API。
    # 只有 Worklog 數超過 Jira 內嵌上限的單，才會由 _issue_worklogs 補抓剩餘分頁。
    issues = _jira_search(jql, "summary,issuetype,worklog", token)
    seconds_by_user: Counter[str] = Counter()
    daily_seconds: Counter[str] = Counter()
    worker_count = min(max(int(os.environ.get("JIRA_WORKLOG_WORKERS", "8")), 1), 12)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = executor.map(lambda issue: _issue_worklogs(issue, token), issues)
        for issue, worklogs in results:
            summary = str((issue.get("fields") or {}).get("summary", ""))
            for worklog in worklogs:
                started_text = str(worklog.get("started", ""))
                if not started_text:
                    continue
                started = _jira_started_date(started_text)
                if started < start or started > end:
                    continue
                user = _jira_user(worklog.get("author"))
                name = JIRA_USERS.get(user or "")
                if not user or not name or not _summary_matches_user(summary, user):
                    continue
                seconds = int(worklog.get("timeSpentSeconds") or 0)
                seconds_by_user[name] += seconds
                daily_seconds[started.isoformat()] += seconds

    days_by_user = {
        name: round(seconds / (8 * 3600), 2)
        for name, seconds in seconds_by_user.items()
    }
    return {
        "days_by_user": days_by_user,
        "daily_days": {
            day: round(seconds / (8 * 3600), 2)
            for day, seconds in daily_seconds.items()
        },
        "total_seconds": sum(seconds_by_user.values()),
        "total_hours": round(sum(seconds_by_user.values()) / 3600, 2),
        "total_days": round(sum(seconds_by_user.values()) / (8 * 3600), 2),
    }


def analyze_performance(start: date, end: date) -> dict[str, Any]:
    if end < start:
        raise ValueError("結束日期不能早於開始日期。")
    if end > date.today():
        raise ValueError("結束日期不能晚於今天。")
    if (end - start).days > 366:
        raise ValueError("單次統計區間不能超過 366 天。")

    # Jira BUG、Jira Worklog 與 Google Sheets 互不依賴，並行查詢縮短等待時間。
    with ThreadPoolExecutor(max_workers=3) as executor:
        task_future = executor.submit(analyze_task_range, start, end)
        bug_future = executor.submit(analyze_jira_bugs, start, end)
        worklog_future = executor.submit(analyze_jira_worklogs, start, end)
        task_data = task_future.result()
        bug_data = bug_future.result()
        worklog_data = worklog_future.result()

    names = (
        set(JIRA_USERS.values())
        | set(task_data["manual_counts"])
        | set(task_data["automation_counts"])
        | set(worklog_data["days_by_user"])
    )
    members = []
    for name in names:
        manual = int(task_data["manual_counts"][name])
        automation = int(task_data["automation_counts"][name])
        bugs = int(bug_data["bug_counts"][name])
        tasks = manual + automation
        log_days = float(worklog_data["days_by_user"].get(name, 0))
        members.append({
            "name": name,
            "bugs": bugs,
            "manual": manual,
            "automation": automation,
            "tasks": tasks,
            "log_days": round(log_days, 2),
            "log_hours": round(log_days * 8, 2),
            "workload": tasks + bugs,
        })
    members.sort(key=lambda item: (-item["workload"], -item["log_days"], item["name"]))

    daily = []
    current = start
    while current <= end:
        key = current.isoformat()
        daily.append({
            "date": key,
            "bugs": int(bug_data["daily_counts"][key]),
            "tasks": int(task_data["daily_counts"][key]),
            "log_days": float(worklog_data["daily_days"].get(key, 0)),
        })
        current += timedelta(days=1)

    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "bug_total": int(bug_data["bug_total"]),
        "task_total": sum(member["tasks"] for member in members),
        "manual_total": sum(member["manual"] for member in members),
        "automation_total": sum(member["automation"] for member in members),
        "worklog_total_days": float(worklog_data["total_days"]),
        "worklog_total_hours": float(worklog_data["total_hours"]),
        "active_members": sum(
            1 for member in members
            if member["workload"] > 0 or member["log_days"] > 0
        ),
        "task_rows": int(task_data["task_rows"]),
        "members": members,
        "daily": daily,
        "task_source_sheets": task_data["source_sheets"],
    }


def build_report_pdf(year: int, month: int, port: int) -> bytes:
    """以與網頁相同的 screen media 截取完整報告，並儲存為單張長頁 PDF。"""
    selected = date(year, month, 1)
    if selected > date.today().replace(day=1):
        raise ValueError("不能匯出未來月份。")

    chrome_candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    browser_path = next((path for path in chrome_candidates if path.is_file()), None)
    if browser_path is None:
        raise ValueError("找不到 Chrome 或 Edge，無法產生 PDF。")

    try:
        from PIL import Image
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise ValueError("PDF 匯出元件尚未安裝。") from error

    query = urlencode({"pdf_capture": "1", "year": year, "month": month})
    report_url = f"http://127.0.0.1:{port}/?{query}"
    with PDF_EXPORT_LOCK:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(browser_path),
                headless=True,
                args=["--disable-gpu", "--hide-scrollbars"],
            )
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1.25)
                page.goto(report_url, wait_until="domcontentloaded", timeout=30_000)
                ready_element = page.wait_for_selector(
                    "html[data-pdf-ready='true'], html[data-pdf-ready='error']",
                    timeout=180_000,
                )
                if ready_element.get_attribute("data-pdf-ready") != "true":
                    message = page.locator("#performanceStatus").inner_text() or "報告資料讀取失敗。"
                    raise ValueError(message)
                page.evaluate("document.fonts.ready")
                screenshot = page.screenshot(full_page=True, type="png")
            finally:
                browser.close()

    image = Image.open(BytesIO(screenshot)).convert("RGB")
    output = BytesIO()
    image.save(output, format="PDF", resolution=144.0, quality=95)
    return output.getvalue()


class QAAnalyzerHandler(BaseHTTPRequestHandler):
    server_version = "MorrisQAAnalyzer/2.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_pdf(self, body: bytes, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 100_000:
            raise ValueError("請求內容不正確。")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("請求內容必須是 JSON 物件。")
        return payload

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/health":
            self.send_json(200, {"status": "ok"})
            return
        if path == "/api/months":
            try:
                self.send_json(200, available_months())
            except Exception as error:
                self.send_json(400, {"error": f"讀取 Google Sheets 失敗：{error}"})
            return
        if path == "/api/export-pdf":
            try:
                params = dict(item.split("=", 1) for item in parsed.query.split("&") if "=" in item)
                year = int(params.get("year", ""))
                month = int(params.get("month", ""))
                if not 1 <= month <= 12:
                    raise ValueError("月份不正確。")
                body = build_report_pdf(year, month, int(self.server.server_port))
                self.send_pdf(body, f"QA_Department_Report_{year:04d}{month:02d}.pdf")
            except Exception as error:
                self.send_json(400, {"error": str(error)})
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/analyze", "/api/performance"}:
            self.send_json(404, {"error": "找不到 API。"})
            return
        try:
            payload = self.read_json()
            if path == "/api/analyze":
                year = int(payload.get("year"))
                month = int(payload.get("month"))
                result = analyze_month(year, month)
            else:
                start = datetime.strptime(str(payload.get("start_date")), "%Y-%m-%d").date()
                end = datetime.strptime(str(payload.get("end_date")), "%Y-%m-%d").date()
                result = analyze_performance(start, end)
        except Exception as error:
            self.send_json(400, {"error": str(error)})
            return
        self.send_json(200, result)

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (WEB_DIR / relative).resolve()
        web_root = WEB_DIR.resolve()
        if web_root not in target.parents and target != web_root:
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
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(body)


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main() -> None:
    parser = argparse.ArgumentParser(description="QA單號統計本機網頁工具")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    lan_ip = get_lan_ip()
    local_url = f"http://127.0.0.1:{args.port}"
    lan_url = f"http://{lan_ip}:{args.port}"

    try:
        server = ExclusiveThreadingHTTPServer((args.host, args.port), QAAnalyzerHandler)
    except OSError as error:
        if getattr(error, "winerror", None) != 10048:
            raise
        print(f"QA單號統計工具已經在執行：{local_url}")
        print("若要套用內網模式，請先關閉舊的工具視窗，再重新啟動。")
        if not args.no_browser:
            webbrowser.open(local_url)
        return

    print(f"QA單號統計工具已啟動：{local_url}")
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

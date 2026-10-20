from __future__ import annotations

import json
import re
import threading
import tkinter as tk
import webbrowser
from calendar import Calendar
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from queue import Empty, Queue
from tkinter import messagebox, ttk
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


APP_TITLE = "Jira QA_Mission 建立工具"
APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "task_manager_config.local.json"
LEGACY_CONFIG_FILE = APP_DIR.parent / "04_Jira" / "jira_config.local.json"
RULES_FILE = APP_DIR / "qa_mission_rules.json"
ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")
CHINESE_MONTHS = (
    "一月", "二月", "三月", "四月", "五月", "六月",
    "七月", "八月", "九月", "十月", "十一月", "十二月",
)
DATE_PATTERN = re.compile(r"^(\d{1,2})/([^/]+)/([0-9]{2})$")
DEFAULT_FIXED_LINKS = {
    "game": "https://game.example.internal/login?menuId=1",
    "backend": "https://qa-lab.example.internal/",
}


@dataclass(frozen=True)
class JiraSettings:
    base_url: str
    token: str
    api_version: str = "2"


class JiraError(RuntimeError):
    pass


class JiraClient:
    def __init__(self, settings: JiraSettings) -> None:
        token = settings.token.strip()
        if not token:
            raise ValueError("請先填入 Jira token。")
        self.settings = settings
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Morris-QA-Mission-Tool/1.0",
        }

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        url = f"{self.settings.base_url.rstrip('/')}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(url, headers=self.headers, data=body, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise JiraError(format_jira_error(error.code, body)) from error
        except URLError as error:
            raise JiraError(f"無法連線 Jira：{error}") from error
        except TimeoutError as error:
            raise JiraError("連線 Jira 逾時。") from error
        return json.loads(raw) if raw else {}

    def test_connection(self) -> str:
        data = self.get_current_user()
        return data.get("displayName") or data.get("name") or data.get("key") or "UNKNOWN"

    def get_current_user(self, timeout: int = 60) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/rest/api/{self.settings.api_version}/myself",
            timeout=timeout,
        )

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/rest/api/{self.settings.api_version}/issue/{issue_key}",
            {"expand": "names,schema"},
        )

    def get_create_metadata(self, project_key: str, issue_type: str) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/rest/api/{self.settings.api_version}/issue/createmeta",
            {
                "projectKeys": project_key,
                "issuetypeNames": issue_type,
                "expand": "projects.issuetypes.fields",
            },
        )

    def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/rest/api/{self.settings.api_version}/issue",
            payload={"fields": fields},
        )


def format_jira_error(status_code: int, response_text: str) -> str:
    lines = [f"Jira API 失敗（HTTP {status_code}）"]
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        for message in data.get("errorMessages") or []:
            lines.append(f"- {message}")
        for field, message in (data.get("errors") or {}).items():
            lines.append(f"- {field}：{message}")
    if len(lines) == 1 and response_text.strip():
        lines.append(response_text.strip()[:2000])
    return "\n".join(lines)


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default.copy()
    return data if isinstance(data, dict) else default.copy()


def load_settings() -> dict[str, Any]:
    defaults = {"base_url": "https://jira.example.internal", "token": "", "remember_token": False}
    settings = {**defaults, **load_json(CONFIG_FILE, defaults)}
    if not settings.get("token") and LEGACY_CONFIG_FILE.exists():
        settings["token"] = load_json(LEGACY_CONFIG_FILE, {}).get("token", "")
    return settings


def save_settings(base_url: str, token: str, remember_token: bool) -> None:
    data = {
        "base_url": base_url,
        "token": token if remember_token else "",
        "remember_token": remember_token,
    }
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_rules() -> dict[str, Any]:
    defaults = {
        "template_name": "QA_Mission",
        "project_key": "QA",
        "issue_type": "Task",
        "assignee": "arsene211",
        "epic_links": ["HCI-KX", "HCI-LY", "HCI-NW", "HCI-V8", "HCI-VP", "HCI-YL", "後台"],
        "headings": {
            "test_items": "進測項目",
            "environment": "驗證環境",
            "version": "驗證版號",
        },
        "description_boundaries": ["遊戲連結", "後台連結", "V8代理", "YL代理", "代理"],
        "fixed_links": DEFAULT_FIXED_LINKS,
        "environment_agent_map": {
            "YL SIT": "[YL代理] 1(轉帳) 2(單一)",
            "LY SIT": "[LY代理] 1(轉帳) 2(單一)",
            "V8 SIT": "[V8代理] 2(轉帳) 1(單一)",
            "KX SIT": "[KX代理] 7(轉帳) 8(單一)",
            "YL WC": "[YL代理] 72762(轉帳) 800022(轉帳) 800021(單一)",
            "LY UAT": "[LY代理] 201437(轉帳) 201438(單一)",
            "V8 UAT": "[V8代理] 71198(轉帳) 71199(單一)",
            "KX UAT": "[KX代理] 62161(轉帳) 62162(單一)",
            "V8 QA": "[V8代理] 2(轉帳) 1(單一)",
            "YL QA": "[YL代理] 2(轉帳) 1(單一)",
            "LY QA": "[LY代理] 2(轉帳) 1(單一)",
        },
        "epic_link_keys": {
            "HCI-KX": "QA-41",
            "HCI-LY": "QA-44",
            "HCI-NW": "QA-42",
            "HCI-V8": "QA-45",
            "HCI-VP": "QA-1724",
            "HCI-YL": "QA-3782",
            "後台": "QA-8601",
        },
        "field_aliases": {
            "start_date": ["Start Date", "開始日期"],
            "due_date": ["Due Date", "到期日"],
            "epic_link": ["Epic Link", "Epic link"],
        },
    }
    stored = load_json(RULES_FILE, defaults)
    return {
        **defaults,
        **stored,
        "headings": {**defaults["headings"], **stored.get("headings", {})},
        "description_boundaries": stored.get("description_boundaries", defaults["description_boundaries"]),
        "fixed_links": {**DEFAULT_FIXED_LINKS, **stored.get("fixed_links", {})},
        "environment_agent_map": stored.get("environment_agent_map", {}),
        "epic_link_keys": {**defaults["epic_link_keys"], **stored.get("epic_link_keys", {})},
        "field_aliases": {**defaults["field_aliases"], **stored.get("field_aliases", {})},
    }


def normalize_issue_key(value: str) -> str:
    issue_key = value.strip().upper()
    if not ISSUE_KEY_PATTERN.fullmatch(issue_key):
        raise ValueError("主任務單格式不正確，例如 GAME-1234。")
    return issue_key


def _adf_block_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_block_text(item) for item in node)
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "hardBreak":
        return "\n"
    own_text = node.get("text", "")
    return own_text + _adf_block_text(node.get("content", []))


def description_lines(description: Any) -> list[str]:
    """支援 Jira 純文字及 Atlassian Document Format。"""
    if description is None:
        return []
    if isinstance(description, str):
        return [line.strip() for line in description.splitlines() if line.strip()]
    if isinstance(description, dict):
        content = description.get("content")
        if isinstance(content, list):
            lines: list[str] = []
            for block in content:
                text = _adf_block_text(block)
                lines.extend(part.strip() for part in text.splitlines() if part.strip())
            return lines
    text = _adf_block_text(description)
    return [line.strip() for line in text.splitlines() if line.strip()]


def normalize_heading(value: str) -> str:
    normalized = value.strip().lstrip("#*- ").strip()
    normalized = normalized.strip("[]【】()（）").strip()
    return normalized.rstrip(":：").strip()


def match_heading_line(line: str, heading: str) -> tuple[bool, str]:
    text = line.strip().lstrip("#*- ").strip()
    escaped = re.escape(normalize_heading(heading))
    patterns = (
        rf"^[\[【]\s*{escaped}\s*[\]】]\s*[:：]?\s*(.*)$",
        rf"^{escaped}\s*[:：]\s*(.*)$",
        rf"^{escaped}\s*$",
    )
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            inline_value = match.group(1).strip() if match.lastindex else ""
            return True, inline_value
    return False, ""


def extract_section(lines: list[str], heading: str, stop_headings: list[str]) -> str:
    collecting = False
    output: list[str] = []

    for line in lines:
        if not collecting:
            matched, inline_value = match_heading_line(line, heading)
            if matched:
                if inline_value.strip():
                    output.append(inline_value.strip())
                collecting = True
            continue

        if any(match_heading_line(line, stop_heading)[0] for stop_heading in stop_headings):
            break
        output.append(line.strip())

    return "\n".join(value for value in output if value).strip()


def heading_aliases(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def extract_section_aliases(
    lines: list[str], headings: Any, stop_headings: list[str]
) -> str:
    for heading in heading_aliases(headings):
        value = extract_section(lines, heading, stop_headings)
        if value:
            return value
    return ""


def release_number_from_block(block: list[str], test_item_headings: Any) -> int | None:
    if not block:
        return None

    def release_number(value: str) -> int | None:
        normalized = value.strip().strip("*_~ ").strip()
        normalized = normalized.strip("[]【】()（）").strip()
        matched = re.fullmatch(
            r"(?:QA[\s_-]*)?R(\d+)", normalized, flags=re.IGNORECASE
        )
        return int(matched.group(1)) if matched else None

    direct = release_number(block[0])
    if direct:
        return direct
    for heading in heading_aliases(test_item_headings):
        matched, inline_value = match_heading_line(block[0], heading)
        if matched:
            inline = release_number(inline_value)
            if inline:
                return inline
    return None


def select_latest_release_block(
    lines: list[str], summary: str, test_item_headings: Any
) -> list[str]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if re.fullmatch(r"-{3,}", line.strip()):
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    if len(blocks) <= 1:
        return lines

    ranked = [release_number_from_block(block, test_item_headings) for block in blocks]
    available = [rank for rank in ranked if rank is not None]
    if not available:
        for block in blocks:
            if any(
                match_heading_line(line, heading)[0]
                for line in block
                for heading in heading_aliases(test_item_headings)
            ):
                return block
        return lines

    target = max(available)
    return blocks[ranked.index(target)]


def display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        values = [display_value(item) for item in value]
        return ", ".join(item for item in values if item)
    if isinstance(value, dict):
        for key in ("displayName", "name", "value", "key"):
            if value.get(key):
                return str(value[key]).strip()
    return str(value)


def resolve_environment_agents(environment: str, agent_map: dict[str, Any]) -> str:
    normalized_environment = re.sub(r"[-_]+", " ", environment.upper())
    normalized_environment = " ".join(normalized_environment.split())
    matches: list[tuple[int, str]] = []
    seen: set[str] = set()
    for environment_name, agent_value in agent_map.items():
        normalized_name = re.sub(r"[-_]+", " ", str(environment_name).upper())
        normalized_name = " ".join(normalized_name.split())
        position = normalized_environment.find(normalized_name)
        value = str(agent_value).strip()
        if position >= 0 and value and value not in seen:
            matches.append((position, value))
            seen.add(value)
    matches.sort(key=lambda item: item[0])
    return "\n".join(value for _, value in matches)


def build_mission_data(
    issue: dict[str, Any],
    base_url: str,
    rules: dict[str, Any],
) -> dict[str, str]:
    fields = issue.get("fields") or {}
    issue_key = str(issue.get("key") or "")
    headings = rules["headings"]
    lines = description_lines(fields.get("description"))
    lines = select_latest_release_block(
        lines, str(fields.get("summary") or ""), headings["test_items"]
    )

    test_item_headings = heading_aliases(headings["test_items"])
    environment_headings = heading_aliases(headings["environment"])
    version_headings = heading_aliases(headings["version"])

    test_items = extract_section_aliases(
        lines,
        headings["test_items"],
        [*environment_headings, *version_headings],
    )
    environment = extract_section_aliases(
        lines,
        headings["environment"],
        [*version_headings, *test_item_headings],
    )
    version = extract_section_aliases(
        lines,
        headings["version"],
        [*test_item_headings, *environment_headings, *rules.get("description_boundaries", [])],
    )

    reporter = fields.get("reporter") or {}
    reporter_name = display_value(reporter)
    reporter_id = str(reporter.get("accountId") or reporter.get("name") or reporter.get("key") or "")
    agent_map = rules.get("environment_agent_map", {})
    agent = resolve_environment_agents(environment, agent_map)

    return {
        "main_issue_key": issue_key,
        "main_issue_url": f"{base_url.rstrip('/')}/browse/{issue_key}",
        "summary": str(fields.get("summary") or issue_key).strip(),
        "reporter_name": reporter_name,
        "reporter_id": reporter_id,
        "reporter_account_id": str(reporter.get("accountId") or ""),
        "test_items": test_items,
        "environment": environment,
        "version": version,
        "agent": agent,
    }


def format_jira_date(value: date) -> str:
    return f"{value.day}/{CHINESE_MONTHS[value.month - 1]}/{value.year % 100:02d}"


def validate_date(value: str, label: str) -> date:
    text = value.strip()
    match = DATE_PATTERN.fullmatch(text)
    if not match or match.group(2) not in CHINESE_MONTHS:
        raise ValueError(f"{label}請使用日曆選擇日期，例如 5/八月/25。")
    day = int(match.group(1))
    month = CHINESE_MONTHS.index(match.group(2)) + 1
    year = 2000 + int(match.group(3))
    try:
        return date(year, month, day)
    except ValueError as error:
        raise ValueError(f"{label}不是有效日期。") from error


def get_issue_type_metadata(
    metadata: dict[str, Any], project_key: str, issue_type_name: str
) -> tuple[dict[str, str], dict[str, Any]]:
    for project in metadata.get("projects") or []:
        if str(project.get("key", "")).casefold() != project_key.casefold():
            continue
        for issue_type in project.get("issuetypes") or []:
            if str(issue_type.get("name", "")).casefold() == issue_type_name.casefold():
                project_ref = {"id": str(project["id"])} if project.get("id") else {"key": project_key}
                issue_type_ref = (
                    {"id": str(issue_type["id"])}
                    if issue_type.get("id")
                    else {"name": issue_type_name}
                )
                return {"project": project_ref, "issuetype": issue_type_ref}, issue_type.get("fields") or {}
    raise ValueError(f"Jira Create 找不到專案 {project_key} 的 {issue_type_name} 單據類型。")


def find_create_field(create_fields: dict[str, Any], aliases: list[str]) -> tuple[str, dict[str, Any]] | None:
    targets = {alias.strip().casefold() for alias in aliases}
    for field_id, metadata in create_fields.items():
        if str(metadata.get("name", "")).strip().casefold() in targets:
            return field_id, metadata
    return None


def coerce_create_value(value: str, metadata: dict[str, Any]) -> Any:
    schema = metadata.get("schema") or {}
    field_type = schema.get("type")
    allowed_values = metadata.get("allowedValues") or []
    if field_type == "option" or allowed_values:
        target = value.strip().casefold()
        for option in allowed_values:
            candidates = (option.get("value"), option.get("name"), option.get("key"))
            if any(str(candidate).strip().casefold() == target for candidate in candidates if candidate):
                if option.get("id") is not None:
                    return {"id": str(option["id"])}
                return option
    return value


def build_create_fields(
    metadata: dict[str, Any],
    mission_data: dict[str, str],
    form_values: dict[str, str],
    rules: dict[str, Any],
) -> tuple[dict[str, Any], list[str], list[str]]:
    references, create_fields = get_issue_type_metadata(
        metadata, rules["project_key"], rules["issue_type"]
    )
    payload: dict[str, Any] = {
        **references,
        "summary": mission_data["summary"],
        "description": build_qa_mission_description(
            mission_data, form_values, rules.get("fixed_links", DEFAULT_FIXED_LINKS)
        ),
        "duedate": form_values["due_date_api"],
    }
    assignee = str(rules.get("assignee") or "arsene211").strip()
    if assignee:
        payload["assignee"] = {"name": assignee}

    values = {
        "start_date": form_values["start_date_api"],
        "due_date": form_values["due_date_api"],
        "epic_link": rules["epic_link_keys"].get(form_values["epic_link"], form_values["epic_link"]),
    }
    unresolved: list[str] = []
    aliases_by_key = rules["field_aliases"]
    for logical_name, value in values.items():
        found = find_create_field(create_fields, aliases_by_key[logical_name])
        if not found:
            # Due Date is Jira's system field and has already been added as duedate.
            if logical_name != "due_date":
                unresolved.append(" / ".join(aliases_by_key[logical_name]))
            continue
        field_id, field_metadata = found
        payload[field_id] = coerce_create_value(value, field_metadata)

    missing_required = [
        str(field_metadata.get("name") or field_id)
        for field_id, field_metadata in create_fields.items()
        if field_metadata.get("required")
        and field_id not in payload
        and not field_metadata.get("hasDefaultValue")
    ]
    return payload, unresolved, missing_required


def build_qa_mission_description(
    mission_data: dict[str, str],
    form_values: dict[str, str],
    fixed_links: dict[str, str] | None = None,
) -> str:
    links = {**DEFAULT_FIXED_LINKS, **(fixed_links or {})}
    return (
        "【BUG單開立】\n"
        f"{mission_data['main_issue_url']}\n"
        "Bug單 block 關連到"
        f"[{mission_data['main_issue_key']}|{mission_data['main_issue_url']}]"
        f"並指派給 {mission_data['reporter_id']}\n\n"
        "[進測項目]\n"
        f"{mission_data['test_items']}\n\n"
        "[測試案例]\n"
        f"{form_values['test_cases']}\n\n"
        f"[驗證環境] {mission_data['environment']}\n\n"
        f"[驗證版號] {mission_data['version']}\n\n"
        f"[遊戲連結] [{links['game']}]\n"
        f"[後台連結] [{links['backend']}]\n\n"
        f"{mission_data['agent']}"
    )


class CalendarDialog(tk.Toplevel):
    """不依賴外部套件的日期選擇器。"""

    def __init__(self, parent: tk.Misc, target: tk.StringVar, anchor: tk.Widget) -> None:
        super().__init__(parent)
        self.target = target
        try:
            selected = validate_date(target.get(), "日期")
        except ValueError:
            selected = date.today()
        self.year = selected.year
        self.month = selected.month
        self.title("選擇日期")
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.body = ttk.Frame(self, padding=10)
        self.body.pack(fill=tk.BOTH, expand=True)
        self._render()
        self.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height()
        self.geometry(f"+{x}+{y}")
        self.grab_set()

    def _move_month(self, amount: int) -> None:
        index = self.year * 12 + self.month - 1 + amount
        self.year, month_index = divmod(index, 12)
        self.month = month_index + 1
        self._render()

    def _select(self, day: int) -> None:
        self.target.set(format_jira_date(date(self.year, self.month, day)))
        self.destroy()

    def _select_today(self) -> None:
        self.target.set(format_jira_date(date.today()))
        self.destroy()

    def _render(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()

        ttk.Button(self.body, text="‹", width=3, command=lambda: self._move_month(-1)).grid(row=0, column=0)
        ttk.Label(
            self.body,
            text=f"{self.year} 年 {CHINESE_MONTHS[self.month - 1]}",
            font=("Microsoft JhengHei UI", 11, "bold"),
            anchor=tk.CENTER,
        ).grid(row=0, column=1, columnspan=5, sticky=tk.EW)
        ttk.Button(self.body, text="›", width=3, command=lambda: self._move_month(1)).grid(row=0, column=6)

        for column, weekday in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            ttk.Label(self.body, text=weekday, anchor=tk.CENTER).grid(
                row=1, column=column, padx=2, pady=(8, 2), sticky=tk.EW
            )

        weeks = Calendar(firstweekday=0).monthdayscalendar(self.year, self.month)
        for week_index, week in enumerate(weeks):
            for column, day_number in enumerate(week):
                if day_number:
                    ttk.Button(
                        self.body,
                        text=str(day_number),
                        width=3,
                        command=lambda selected_day=day_number: self._select(selected_day),
                    ).grid(row=week_index + 2, column=column, padx=2, pady=2)

        ttk.Button(self.body, text="今天", command=self._select_today).grid(
            row=len(weeks) + 2, column=0, columnspan=7, pady=(8, 0)
        )


class QaMissionApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("940x760")
        self.minsize(840, 680)

        settings = load_settings()
        self.rules = load_rules()
        self.mission_data: dict[str, str] | None = None
        self.base_url_var = tk.StringVar(value=settings["base_url"])
        self.token_var = tk.StringVar(value=settings["token"])
        self.remember_var = tk.BooleanVar(value=bool(settings["remember_token"]))
        self.main_key_var = tk.StringVar()
        self.main_url_var = tk.StringVar()
        self.bug_assignee_var = tk.StringVar()
        self.assignee_var = tk.StringVar(value=self.rules.get("assignee", "arsene211"))
        self.environment_var = tk.StringVar()
        self.version_var = tk.StringVar()
        self.agent_var = tk.StringVar()
        self.start_date_var = tk.StringVar()
        self.due_date_var = tk.StringVar()
        self.epic_var = tk.StringVar()
        self.result_var = tk.StringVar()
        self.created_issue_url = ""
        self.status_var = tk.StringVar(value="請輸入主任務單並讀取資料。")
        self._build_ui()

    def _build_ui(self) -> None:
        canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=canvas.yview)
        root = ttk.Frame(canvas, padding=18)
        root.columnconfigure(0, weight=1)
        canvas.create_window((0, 0), window=root, anchor=tk.NW, tags="content")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        root.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure("content", width=event.width))

        ttk.Label(root, text=APP_TITLE, font=("Microsoft JhengHei UI", 18, "bold")).pack(anchor=tk.W)
        ttk.Label(root, text="專案：QA｜模板：QA_Mission｜Jira 類型：Task｜可直接建立 Jira 單").pack(
            anchor=tk.W, pady=(2, 12)
        )

        connection = ttk.LabelFrame(root, text="Jira 連線", padding=12)
        connection.pack(fill=tk.X, pady=(0, 12))
        connection.columnconfigure(1, weight=1)
        ttk.Label(connection, text="Jira 網址").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        ttk.Entry(connection, textvariable=self.base_url_var).grid(row=0, column=1, sticky=tk.EW, pady=4)
        ttk.Label(connection, text="Token").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        ttk.Entry(connection, textvariable=self.token_var, show="●").grid(row=1, column=1, sticky=tk.EW, pady=4)
        ttk.Checkbutton(connection, text="將 token 記住在本機", variable=self.remember_var).grid(
            row=2, column=1, sticky=tk.W
        )
        ttk.Button(connection, text="測試連線", command=self.test_connection).grid(
            row=0, column=2, rowspan=2, padx=(10, 0)
        )

        source = ttk.LabelFrame(root, text="主任務", padding=12)
        source.pack(fill=tk.X, pady=(0, 12))
        source.columnconfigure(1, weight=1)
        ttk.Label(source, text="主任務單號").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        ttk.Entry(source, textvariable=self.main_key_var).grid(row=0, column=1, sticky=tk.EW, pady=4)
        ttk.Button(source, text="讀取主任務", command=self.load_main_issue).grid(row=0, column=2, padx=(10, 0))

        auto = ttk.LabelFrame(root, text="自動帶入欄位", padding=12)
        auto.pack(fill=tk.X, pady=(0, 12))
        auto.columnconfigure(1, weight=1)
        read_only_fields = [
            ("Bug 單開立網址", self.main_url_var),
            ("BUG 指派人（主任務報告人）", self.bug_assignee_var),
            ("經辦人", self.assignee_var),
            ("驗證環境", self.environment_var),
            ("驗證版號", self.version_var),
            ("代理", self.agent_var),
        ]
        for row, (label, variable) in enumerate(read_only_fields):
            ttk.Label(auto, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 8), pady=4)
            ttk.Entry(auto, textvariable=variable, state="readonly").grid(row=row, column=1, sticky=tk.EW, pady=4)
        ttk.Label(auto, text="進測項目").grid(row=len(read_only_fields), column=0, sticky=tk.NW, padx=(0, 8), pady=4)
        self.test_items_text = tk.Text(auto, height=6, wrap=tk.WORD, state=tk.DISABLED)
        self.test_items_text.grid(row=len(read_only_fields), column=1, sticky=tk.EW, pady=4)

        manual = ttk.LabelFrame(root, text="Jira QA_Mission 手動欄位", padding=12)
        manual.pack(fill=tk.X, pady=(0, 12))
        manual.columnconfigure(1, weight=1)
        ttk.Label(manual, text="測試案例").grid(row=0, column=0, sticky=tk.NW, padx=(0, 8), pady=4)
        self.test_cases_text = tk.Text(manual, height=7, wrap=tk.WORD)
        self.test_cases_text.grid(row=0, column=1, columnspan=3, sticky=tk.EW, pady=4)
        ttk.Label(manual, text="開始日期").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        start_date_frame = ttk.Frame(manual)
        start_date_frame.grid(row=1, column=1, sticky=tk.W, pady=4)
        ttk.Entry(start_date_frame, textvariable=self.start_date_var, width=16, state="readonly").pack(side=tk.LEFT)
        start_button = ttk.Button(start_date_frame, text="選擇日期")
        start_button.configure(command=lambda: CalendarDialog(self, self.start_date_var, start_button))
        start_button.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(manual, text="到期日").grid(row=1, column=2, sticky=tk.W, padx=(14, 8), pady=4)
        due_date_frame = ttk.Frame(manual)
        due_date_frame.grid(row=1, column=3, sticky=tk.W, pady=4)
        ttk.Entry(due_date_frame, textvariable=self.due_date_var, width=16, state="readonly").pack(side=tk.LEFT)
        due_button = ttk.Button(due_date_frame, text="選擇日期")
        due_button.configure(command=lambda: CalendarDialog(self, self.due_date_var, due_button))
        due_button.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(manual, text="Epic Link").grid(row=2, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        epic_combo = ttk.Combobox(
            manual,
            textvariable=self.epic_var,
            values=self.rules["epic_links"],
            state="readonly",
        )
        epic_combo.grid(row=2, column=1, sticky=tk.EW, pady=4)

        ttk.Label(
            manual,
            text="以上內容會分別填入 Jira Create 畫面中的同名欄位，不會合併成描述文字。",
            foreground="#475569",
        ).grid(row=3, column=0, columnspan=4, sticky=tk.W, pady=(8, 0))

        actions = ttk.Frame(root)
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="檢查 Jira 欄位", command=self.validate_jira_fields).pack(side=tk.LEFT)
        self.create_button = ttk.Button(actions, text="建立 QA_Mission", command=self.create_qa_mission)
        self.create_button.pack(side=tk.LEFT, padx=(8, 0))
        self.open_issue_button = ttk.Button(
            actions, text="開啟新 Jira 單", command=self.open_created_issue, state=tk.DISABLED
        )
        self.open_issue_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(root, textvariable=self.result_var, foreground="#166534", wraplength=860).pack(
            anchor=tk.W, pady=(8, 0)
        )
        ttk.Label(root, textvariable=self.status_var, foreground="#1d4ed8").pack(anchor=tk.W, pady=(8, 0))

    def _settings(self) -> JiraSettings:
        return JiraSettings(self.base_url_var.get().strip(), self.token_var.get().strip())

    def _set_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, value)
        widget.configure(state=tk.DISABLED)

    def _run(self, status: str, worker: Any, success: Any) -> None:
        self.status_var.set(status)
        result_queue: Queue[tuple[str, Any]] = Queue()

        def execute() -> None:
            try:
                result = worker()
            except Exception as error:
                result_queue.put(("error", str(error)))
                return
            result_queue.put(("success", result))

        def poll_result() -> None:
            try:
                outcome, value = result_queue.get_nowait()
            except Empty:
                self.after(100, poll_result)
                return
            if outcome == "error":
                self._show_error(value)
            else:
                success(value)

        threading.Thread(target=execute, daemon=True).start()
        self.after(100, poll_result)

    def _show_error(self, error: str) -> None:
        self.create_button.configure(state=tk.NORMAL)
        self.status_var.set("執行失敗。")
        self.result_var.set(error)
        messagebox.showerror("執行失敗", error)

    def test_connection(self) -> None:
        settings = self._settings()
        remember = self.remember_var.get()

        def worker() -> str:
            name = JiraClient(settings).test_connection()
            save_settings(settings.base_url, settings.token, remember)
            return name

        self._run(
            "正在確認 Jira 連線…",
            worker,
            lambda name: self.status_var.set(f"Jira 連線成功：{name}"),
        )

    def load_main_issue(self) -> None:
        try:
            issue_key = normalize_issue_key(self.main_key_var.get())
        except ValueError as error:
            self._show_error(str(error))
            return
        settings = self._settings()

        def worker() -> dict[str, str]:
            issue = JiraClient(settings).get_issue(issue_key)
            return build_mission_data(issue, settings.base_url, self.rules)

        def success(data: dict[str, str]) -> None:
            self.mission_data = data
            self.main_url_var.set(data["main_issue_url"])
            self.bug_assignee_var.set(data["reporter_id"])
            self.assignee_var.set(self.rules.get("assignee", "arsene211"))
            self.environment_var.set(data["environment"])
            self.version_var.set(data["version"])
            self.agent_var.set((data["agent"] or "尚未設定環境對應代理").replace("\n", "；"))
            self._set_text(self.test_items_text, data["test_items"])
            missing = [
                label
                for label, key in (("報告人帳號", "reporter_id"), ("進測項目", "test_items"), ("驗證環境", "environment"), ("驗證版號", "version"))
                if not data[key]
            ]
            if missing:
                self.status_var.set(f"主任務已讀取，但缺少：{', '.join(missing)}")
            else:
                self.status_var.set(f"主任務 {issue_key} 讀取成功。")

        self._run(f"正在讀取主任務 {issue_key}…", worker, success)

    def _form_values(self) -> dict[str, str]:
        if not self.mission_data:
            raise ValueError("請先讀取主任務。")
        if self.mission_data["main_issue_key"] != self.main_key_var.get().strip().upper():
            raise ValueError("主任務單號已變更，請重新讀取。")
        if not self.mission_data.get("reporter_id"):
            raise ValueError("主任務缺少報告人帳號，無法填寫 BUG 指派人。")
        test_cases = self.test_cases_text.get("1.0", tk.END).strip()
        if not test_cases:
            raise ValueError("請填入測試案例。")
        start_date_value = validate_date(self.start_date_var.get(), "開始日期")
        due_date_value = validate_date(self.due_date_var.get(), "到期日")
        if due_date_value < start_date_value:
            raise ValueError("到期日不可早於開始日期。")
        if not self.epic_var.get():
            raise ValueError("請選擇 Epic Link。")

        return {
            "test_cases": test_cases,
            "start_date_display": format_jira_date(start_date_value),
            "due_date_display": format_jira_date(due_date_value),
            "start_date_api": start_date_value.isoformat(),
            "due_date_api": due_date_value.isoformat(),
            "epic_link": self.epic_var.get(),
        }

    def validate_jira_fields(self) -> None:
        try:
            form_values = self._form_values()
        except ValueError as error:
            self._show_error(str(error))
            return

        data = self.mission_data
        assert data is not None
        jira_fields = {
            "Bug 單開立": data["main_issue_url"],
            "BUG 指派人": data["reporter_id"],
            "經辦人": self.rules.get("assignee", "arsene211"),
            "進測項目": data["test_items"],
            "測試案例": form_values["test_cases"],
            "驗證環境": data["environment"],
            "驗證版號": data["version"],
            "代理": data["agent"],
            "開始日期": form_values["start_date_display"],
            "到期日": form_values["due_date_display"],
            "Epic Link": form_values["epic_link"],
        }
        missing_fields = [name for name, value in jira_fields.items() if not value]
        if missing_fields:
            self._show_error(f"以下 Jira 欄位尚未有值：{', '.join(missing_fields)}")
            return
        self.status_var.set("Jira QA_Mission 欄位檢查完成；目前尚未送出 Jira。")

    def create_qa_mission(self) -> None:
        try:
            form_values = self._form_values()
        except ValueError as error:
            self._show_error(str(error))
            return
        assert self.mission_data is not None
        mission_data = self.mission_data.copy()
        settings = self._settings()
        self.create_button.configure(state=tk.DISABLED)
        self.result_var.set("")

        def prepare() -> dict[str, Any]:
            client = JiraClient(settings)
            metadata = client.get_create_metadata(self.rules["project_key"], self.rules["issue_type"])
            fields, unresolved, missing_required = build_create_fields(
                metadata, mission_data, form_values, self.rules
            )
            return {
                "fields": fields,
                "unresolved": unresolved,
                "missing_required": missing_required,
            }

        self._run("正在讀取 Jira Create 欄位…", prepare, lambda prepared: self._confirm_create(prepared, settings))

    def _confirm_create(self, prepared: dict[str, Any], settings: JiraSettings) -> None:
        missing_required = prepared["missing_required"]
        if missing_required:
            self._show_error("Jira 尚缺少必填欄位：\n- " + "\n- ".join(missing_required))
            return

        unresolved = prepared["unresolved"]
        warning = ""
        if unresolved:
            warning = "\n\nCreate 畫面找不到以下欄位，這些欄位不會寫入：\n- " + "\n- ".join(unresolved)
        confirmed = messagebox.askyesno(
            "確認建立 QA_Mission",
            f"即將在 {self.rules['project_key']} 建立一張 {self.rules['issue_type']}：\n"
            f"{prepared['fields'].get('summary', '')}{warning}\n\n是否繼續？",
        )
        if not confirmed:
            self.create_button.configure(state=tk.NORMAL)
            self.status_var.set("已取消建立 Jira 單。")
            return

        def submit() -> dict[str, Any]:
            return JiraClient(settings).create_issue(prepared["fields"])

        self._run("正在建立 QA_Mission…", submit, self._created_successfully)

    def _created_successfully(self, result: dict[str, Any]) -> None:
        self.create_button.configure(state=tk.NORMAL)
        issue_key = str(result.get("key") or "").strip()
        if not issue_key:
            self._show_error(f"Jira 沒有回傳新單號：{result}")
            return
        self.created_issue_url = f"{self.base_url_var.get().strip().rstrip('/')}/browse/{issue_key}"
        self.open_issue_button.configure(state=tk.NORMAL)
        self.result_var.set(f"建立成功：{issue_key}\n{self.created_issue_url}")
        self.status_var.set(f"QA_Mission {issue_key} 建立成功。")
        messagebox.showinfo("建立成功", f"已建立 Jira 單：{issue_key}")

    def open_created_issue(self) -> None:
        if self.created_issue_url:
            webbrowser.open(self.created_issue_url)


if __name__ == "__main__":
    QaMissionApp().mainloop()

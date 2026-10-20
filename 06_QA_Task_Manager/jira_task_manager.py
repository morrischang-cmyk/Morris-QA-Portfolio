from __future__ import annotations

import json
import re
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


APP_TITLE = "Jira QA 任務快速建立工具"
APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "task_manager_config.local.json"
LEGACY_CONFIG_FILE = APP_DIR.parent / "04_Jira" / "jira_config.local.json"
RULES_FILE = APP_DIR / "template_rules.json"
ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")


@dataclass(frozen=True)
class JiraSettings:
    base_url: str
    token: str
    api_version: str = "2"
    auth_mode: str = "bearer"


class JiraError(RuntimeError):
    pass


class JiraClient:
    def __init__(self, settings: JiraSettings) -> None:
        self.settings = settings
        token = settings.token.strip()
        if not token:
            raise ValueError("請先填入 Jira token。")

        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Morris-QA-Task-Manager/1.0",
        }
        if settings.auth_mode == "bearer":
            self.headers["Authorization"] = f"Bearer {token}"
        elif settings.auth_mode == "basic_base64":
            self.headers["Authorization"] = f"Basic {token.removeprefix('Basic ').strip()}"
        else:
            raise ValueError(f"不支援的驗證方式：{settings.auth_mode}")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.settings.base_url.rstrip('/')}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(url, headers=self.headers, data=body, method=method)

        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as error:
            response_text = error.read().decode("utf-8", errors="replace")
            raise JiraError(
                f"Jira API 失敗（HTTP {error.code}）\n{response_text[:1200]}"
            ) from error
        except URLError as error:
            raise JiraError(f"無法連線 Jira：{error}") from error

        return json.loads(raw) if raw else {}

    def test_connection(self) -> str:
        data = self._request("GET", f"/rest/api/{self.settings.api_version}/myself")
        return data.get("displayName") or data.get("name") or data.get("key") or "UNKNOWN"

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/rest/api/{self.settings.api_version}/issue/{issue_key}",
            params={"expand": "names,schema"},
        )

    def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/rest/api/{self.settings.api_version}/issue",
            payload={"fields": fields},
        )


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default.copy()
    return data if isinstance(data, dict) else default.copy()


def load_settings() -> dict[str, Any]:
    defaults = {
        "base_url": "https://jira.example.internal",
        "token": "",
        "api_version": "2",
        "auth_mode": "bearer",
        "remember_token": False,
    }
    settings = load_json(CONFIG_FILE, defaults)
    if not settings.get("token") and LEGACY_CONFIG_FILE.exists():
        legacy = load_json(LEGACY_CONFIG_FILE, {})
        settings["token"] = legacy.get("token", "")
    return {**defaults, **settings}


def save_settings(settings: dict[str, Any], remember_token: bool) -> None:
    payload = {
        "base_url": settings["base_url"],
        "api_version": settings.get("api_version", "2"),
        "auth_mode": settings.get("auth_mode", "bearer"),
        "remember_token": remember_token,
        "token": settings["token"] if remember_token else "",
    }
    CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_rules() -> dict[str, Any]:
    return load_json(
        RULES_FILE,
        {
            "copy_fields": [
                "description",
                "priority",
                "labels",
                "components",
                "fixVersions",
                "versions",
                "environment",
            ],
            "fallback_subtask_issue_type": "Sub-task",
        },
    )


def normalize_issue_key(value: str, label: str) -> str:
    issue_key = value.strip().upper()
    if not ISSUE_KEY_PATTERN.fullmatch(issue_key):
        raise ValueError(f"{label}格式不正確，例如 QA-11097。")
    return issue_key


def parse_members(value: str) -> list[str]:
    members: list[str] = []
    seen: set[str] = set()
    for item in re.split(r"[,，\n]+", value):
        member = " ".join(item.strip().split())
        if member and member.casefold() not in seen:
            members.append(member)
            seen.add(member.casefold())
    if not members:
        raise ValueError("請至少填入一位測試成員。")
    return members


def build_subtask_summary(main_issue_key: str, member: str) -> str:
    return f"{main_issue_key}_{member.strip()}"


def _id_list(values: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"id": str(item["id"])} for item in values if isinstance(item, dict) and item.get("id")]


def normalize_copied_field(field_name: str, value: Any) -> Any:
    if field_name in {"components", "fixVersions", "versions"} and isinstance(value, list):
        return _id_list(value)
    if field_name == "priority" and isinstance(value, dict) and value.get("id"):
        return {"id": str(value["id"])}
    return value


def build_parent_fields(
    template_issue: dict[str, Any],
    summary: str,
    copy_fields: list[str],
) -> dict[str, Any]:
    template_fields = template_issue.get("fields") or {}
    project = template_fields.get("project") or {}
    issue_type = template_fields.get("issuetype") or {}
    if not project.get("id") and not project.get("key"):
        raise ValueError("模板單缺少 project 資訊。")
    if not issue_type.get("id"):
        raise ValueError("模板單缺少 issue type 資訊。")

    fields: dict[str, Any] = {
        "project": {"id": str(project["id"])} if project.get("id") else {"key": project["key"]},
        "issuetype": {"id": str(issue_type["id"])},
        "summary": summary.strip(),
    }
    for field_name in copy_fields:
        value = template_fields.get(field_name)
        if value not in (None, "", []):
            fields[field_name] = normalize_copied_field(field_name, value)
    return fields


def resolve_subtask_issue_type(
    template_issue: dict[str, Any],
    fallback_name: str,
) -> dict[str, str]:
    subtasks = (template_issue.get("fields") or {}).get("subtasks") or []
    for subtask in subtasks:
        issue_type = (subtask.get("fields") or {}).get("issuetype") or {}
        if issue_type.get("id"):
            return {"id": str(issue_type["id"])}
    return {"name": fallback_name}


def build_subtask_fields(
    parent_fields: dict[str, Any],
    qa_issue_key: str,
    main_issue_key: str,
    member: str,
    issue_type: dict[str, str],
) -> dict[str, Any]:
    return {
        "project": parent_fields["project"],
        "issuetype": issue_type,
        "parent": {"key": qa_issue_key},
        "summary": build_subtask_summary(main_issue_key, member),
    }


class TaskManagerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("820x760")
        self.minsize(760, 680)

        settings = load_settings()
        self.base_url_var = tk.StringVar(value=settings["base_url"])
        self.token_var = tk.StringVar(value=settings["token"])
        self.remember_var = tk.BooleanVar(value=bool(settings["remember_token"]))
        self.template_key_var = tk.StringVar(value="QA-11097")
        self.main_key_var = tk.StringVar()
        self.summary_var = tk.StringVar()
        self.status_var = tk.StringVar(value="請先測試 Jira 連線，再載入模板。")
        self.template_issue: dict[str, Any] | None = None
        self.rules = load_rules()

        self._build_ui()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        title = ttk.Label(root, text=APP_TITLE, font=("Microsoft JhengHei UI", 18, "bold"))
        title.grid(row=0, column=0, sticky=tk.W, pady=(0, 12))

        settings = ttk.LabelFrame(root, text="Jira 連線", padding=12)
        settings.grid(row=1, column=0, sticky=tk.EW, pady=(0, 12))
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="Jira 網址").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        ttk.Entry(settings, textvariable=self.base_url_var).grid(row=0, column=1, sticky=tk.EW, pady=4)
        ttk.Label(settings, text="Token").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        ttk.Entry(settings, textvariable=self.token_var, show="●").grid(row=1, column=1, sticky=tk.EW, pady=4)
        ttk.Checkbutton(settings, text="將 token 記住在本機設定檔", variable=self.remember_var).grid(
            row=2, column=1, sticky=tk.W, pady=(4, 0)
        )
        ttk.Button(settings, text="測試連線", command=self.test_connection).grid(row=0, column=2, rowspan=2, padx=(10, 0))

        task = ttk.LabelFrame(root, text="建立 QA 任務", padding=12)
        task.grid(row=2, column=0, sticky=tk.EW, pady=(0, 12))
        task.columnconfigure(1, weight=1)

        fields = [
            ("QA 模板單號", self.template_key_var),
            ("任務主單號", self.main_key_var),
            ("QA 主單摘要", self.summary_var),
        ]
        for row, (label, variable) in enumerate(fields):
            ttk.Label(task, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 8), pady=5)
            ttk.Entry(task, textvariable=variable).grid(row=row, column=1, sticky=tk.EW, pady=5)

        ttk.Button(task, text="載入模板", command=self.load_template).grid(row=0, column=2, padx=(10, 0))
        ttk.Label(task, text="測試成員（逗號或換行分隔）").grid(
            row=3, column=0, sticky=tk.NW, padx=(0, 8), pady=5
        )
        self.members_text = tk.Text(task, height=4, wrap=tk.WORD)
        self.members_text.grid(row=3, column=1, columnspan=2, sticky=tk.EW, pady=5)

        actions = ttk.Frame(task)
        actions.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=(10, 0))
        ttk.Button(actions, text="預覽建立內容", command=self.preview).pack(side=tk.LEFT)
        self.create_button = ttk.Button(actions, text="建立 Jira 主單與子單", command=self.create_issues)
        self.create_button.pack(side=tk.LEFT, padx=(8, 0))

        output = ttk.LabelFrame(root, text="預覽／執行結果", padding=10)
        output.grid(row=3, column=0, sticky=tk.NSEW)
        output.columnconfigure(0, weight=1)
        output.rowconfigure(0, weight=1)
        self.output_text = tk.Text(output, wrap=tk.WORD, state=tk.DISABLED)
        self.output_text.grid(row=0, column=0, sticky=tk.NSEW)
        scrollbar = ttk.Scrollbar(output, orient=tk.VERTICAL, command=self.output_text.yview)
        scrollbar.grid(row=0, column=1, sticky=tk.NS)
        self.output_text.configure(yscrollcommand=scrollbar.set)

        ttk.Label(root, textvariable=self.status_var, foreground="#1d4ed8").grid(
            row=4, column=0, sticky=tk.W, pady=(8, 0)
        )

    def _settings(self) -> JiraSettings:
        return JiraSettings(
            base_url=self.base_url_var.get().strip(),
            token=self.token_var.get().strip(),
        )

    def _write_output(self, text: str) -> None:
        self.output_text.configure(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, text)
        self.output_text.configure(state=tk.DISABLED)

    def _run_worker(self, message: str, worker: Any, on_success: Any) -> None:
        self.status_var.set(message)
        self.create_button.configure(state=tk.DISABLED)

        def run() -> None:
            try:
                result = worker()
            except Exception as error:
                self.after(0, lambda: self._finish_error(str(error)))
                return
            self.after(0, lambda: on_success(result))

        threading.Thread(target=run, daemon=True).start()

    def _finish_error(self, error: str) -> None:
        self.create_button.configure(state=tk.NORMAL)
        self.status_var.set("執行失敗，請查看錯誤訊息。")
        self._write_output(error)
        messagebox.showerror("執行失敗", error)

    def test_connection(self) -> None:
        settings = self._settings()
        remember_token = self.remember_var.get()

        def worker() -> str:
            name = JiraClient(settings).test_connection()
            save_settings(
                {
                    "base_url": settings.base_url,
                    "token": settings.token,
                    "api_version": settings.api_version,
                    "auth_mode": settings.auth_mode,
                },
                remember_token,
            )
            return name

        def success(name: str) -> None:
            self.create_button.configure(state=tk.NORMAL)
            self.status_var.set(f"Jira 連線成功：{name}")
            self._write_output(f"Jira 連線成功\n登入身分：{name}")

        self._run_worker("正在確認 Jira 連線…", worker, success)

    def load_template(self) -> None:
        try:
            template_key = normalize_issue_key(self.template_key_var.get(), "QA 模板單號")
        except ValueError as error:
            self._finish_error(str(error))
            return
        settings = self._settings()

        def worker() -> dict[str, Any]:
            return JiraClient(settings).get_issue(template_key)

        def success(issue: dict[str, Any]) -> None:
            self.template_issue = issue
            self.create_button.configure(state=tk.NORMAL)
            fields = issue.get("fields") or {}
            self.status_var.set(f"模板 {issue.get('key', template_key)} 載入成功。")
            self._write_output(
                "模板載入成功\n"
                f"單號：{issue.get('key', template_key)}\n"
                f"摘要：{fields.get('summary', '')}\n"
                f"單據類型：{(fields.get('issuetype') or {}).get('name', '')}\n"
                f"既有子單數：{len(fields.get('subtasks') or [])}"
            )

        self._run_worker(f"正在讀取模板 {template_key}…", worker, success)

    def _form_values(self) -> tuple[str, str, list[str]]:
        main_key = normalize_issue_key(self.main_key_var.get(), "任務主單號")
        summary = self.summary_var.get().strip()
        if not summary:
            raise ValueError("請填入 QA 主單摘要。")
        members = parse_members(self.members_text.get("1.0", tk.END))
        return main_key, summary, members

    def _ensure_template(self) -> dict[str, Any]:
        if not self.template_issue:
            raise ValueError("請先按「載入模板」。")
        loaded_key = str(self.template_issue.get("key", "")).upper()
        current_key = normalize_issue_key(self.template_key_var.get(), "QA 模板單號")
        if loaded_key != current_key:
            raise ValueError("模板單號已變更，請重新載入模板。")
        return self.template_issue

    def preview(self) -> None:
        try:
            template = self._ensure_template()
            main_key, summary, members = self._form_values()
            parent_fields = build_parent_fields(template, summary, self.rules["copy_fields"])
            issue_type = resolve_subtask_issue_type(
                template, self.rules.get("fallback_subtask_issue_type", "Sub-task")
            )
        except (ValueError, KeyError) as error:
            self._finish_error(str(error))
            return

        lines = [
            "【建立預覽】",
            f"來源模板：{template.get('key')}",
            f"任務主單：{main_key}",
            f"QA 主單摘要：{summary}",
            f"複製欄位：{', '.join(name for name in self.rules['copy_fields'] if name in parent_fields) or '無'}",
            "",
            "【預計建立的 QA 子單】",
        ]
        lines.extend(f"- {build_subtask_summary(main_key, member)}" for member in members)
        lines.append(f"\n子單類型：{issue_type}")
        self._write_output("\n".join(lines))
        self.status_var.set("預覽完成。確認內容後再建立 Jira 單。")

    def create_issues(self) -> None:
        try:
            template = self._ensure_template()
            main_key, summary, members = self._form_values()
            parent_fields = build_parent_fields(template, summary, self.rules["copy_fields"])
            subtask_type = resolve_subtask_issue_type(
                template, self.rules.get("fallback_subtask_issue_type", "Sub-task")
            )
        except (ValueError, KeyError) as error:
            self._finish_error(str(error))
            return

        child_names = "\n".join(build_subtask_summary(main_key, member) for member in members)
        confirmed = messagebox.askyesno(
            "確認建立 Jira 單",
            f"即將建立 1 張 QA 主單及 {len(members)} 張子單：\n\n{child_names}\n\n是否繼續？",
        )
        if not confirmed:
            self.status_var.set("已取消建立。")
            return

        settings = self._settings()

        def worker() -> dict[str, Any]:
            client = JiraClient(settings)
            parent_result = client.create_issue(parent_fields)
            qa_issue_key = parent_result.get("key")
            if not qa_issue_key:
                raise JiraError(f"Jira 未回傳新建 QA 單號：{parent_result}")

            children = []
            for member in members:
                child_fields = build_subtask_fields(
                    parent_fields,
                    qa_issue_key,
                    main_key,
                    member,
                    subtask_type,
                )
                try:
                    result = client.create_issue(child_fields)
                    children.append(
                        {
                            "member": member,
                            "summary": child_fields["summary"],
                            "key": result.get("key", "UNKNOWN"),
                            "status": "created",
                        }
                    )
                except Exception as error:
                    children.append(
                        {
                            "member": member,
                            "summary": child_fields["summary"],
                            "key": "",
                            "status": "failed",
                            "error": str(error),
                        }
                    )
            return {"qa_issue_key": qa_issue_key, "children": children}

        def success(result: dict[str, Any]) -> None:
            self.create_button.configure(state=tk.NORMAL)
            qa_key = result["qa_issue_key"]
            lines = [f"QA 主單建立成功：{qa_key}", "", "子單結果："]
            failed = False
            for child in result["children"]:
                if child["status"] == "created":
                    lines.append(f"✓ {child['summary']} → {child['key']}")
                else:
                    failed = True
                    lines.append(f"✗ {child['summary']} → {child['error']}")
            self._write_output("\n".join(lines))
            if failed:
                self.status_var.set(f"QA 主單 {qa_key} 已建立，但部分子單失敗。")
                messagebox.showwarning("部分完成", f"QA 主單 {qa_key} 已建立，但部分子單失敗，請查看結果。")
            else:
                self.status_var.set(f"完成：{qa_key} 與全部子單均已建立。")
                messagebox.showinfo("建立完成", f"QA 主單 {qa_key} 與全部子單均已建立。")

        self._run_worker("正在建立 Jira QA 主單與子單…", worker, success)


if __name__ == "__main__":
    TaskManagerApp().mainloop()

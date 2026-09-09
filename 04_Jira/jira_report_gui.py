# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk


APP_TITLE = "Jira QA 開單統計工具"
SCRIPT_DIR = Path(__file__).resolve().parent
PS_SCRIPT = SCRIPT_DIR / "jira_report.ps1"
CONFIG_FILE = SCRIPT_DIR / "jira_config.local.json"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

COLORS = {
    "bg": "#f3f7fb",
    "surface": "#ffffff",
    "surface_soft": "#f8fafc",
    "primary": "#0f766e",
    "primary_dark": "#115e59",
    "primary_hover": "#0d9488",
    "accent": "#2563eb",
    "text": "#172033",
    "muted": "#5d6b7b",
    "border": "#d7e0e8",
    "output_bg": "#082f35",
    "output_fg": "#d8f3f0",
}


def friday_to_thursday(reference: date | None = None, week_offset: int = 0) -> tuple[date, date]:
    target = reference or date.today()
    days_since_friday = (target.weekday() - 4) % 7
    start = target - timedelta(days=days_since_friday) + timedelta(days=7 * week_offset)
    return start, start + timedelta(days=6)


def fmt(day: date) -> str:
    return day.isoformat()


def format_week_range(start: date, end: date) -> str:
    return f"{fmt(start)} 到 {fmt(end)}"


def load_config() -> dict[str, str]:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(config: dict[str, str]) -> None:
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_summary_table(text: str) -> str:
    code_block = re.search(r"```+text\s*(.*?)\s*```+", text, flags=re.IGNORECASE | re.DOTALL)
    if code_block:
        return code_block.group(1).strip()

    table_lines = []
    for line in text.splitlines():
        if re.search(r"\b(?:arthur734|joey209|ben654|Total)\b\s*:", line):
            table_lines.append(line.rstrip())
            continue
        if table_lines and re.search(r"\b[a-z][a-z0-9]+\b\s*:", line):
            table_lines.append(line.rstrip())
            continue
        if table_lines:
            break

    return "\n".join(table_lines).strip()


def parse_summary_rows(table: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for account, value in re.findall(r"\b([A-Za-z][A-Za-z0-9]*|Total)\s*:\s*([0-9]+(?:\.[0-9]+)?)", table):
        rows.append((account, value))
    return rows


class JiraReportApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        config = load_config()
        start, end = friday_to_thursday()

        self.title(APP_TITLE)
        self.geometry("1040x720")
        self.minsize(860, 560)
        self.configure(bg=COLORS["bg"])

        self.token_var = tk.StringVar(value=config.get("token") or os.getenv("JIRA_API_TOKEN", ""))
        self.remember_token_var = tk.BooleanVar(value=bool(config.get("token")))
        self.start_var = tk.StringVar(value=fmt(start))
        self.end_var = tk.StringVar(value=fmt(end))
        self.show_token_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value=f"準備好了，目前本週區間：{format_week_range(start, end)}")
        self.range_badge_var = tk.StringVar(value=format_week_range(start, end))
        self.output_hint_var = tk.StringVar(value="結果會顯示在這裡")
        self.summary_total_var = tk.StringVar(value="0")
        self.message_var = tk.StringVar(value="")
        self.latest_raw_output = ""
        self.latest_table_text = ""
        self.result_rows: list[tuple[str, str]] = []
        self.is_running = False

        self._build_ui()
        self._write_intro()

    def _build_ui(self) -> None:
        self._configure_style()

        shell = tk.Frame(self, bg=COLORS["bg"])
        shell.pack(fill=tk.BOTH, expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        self._build_header(shell)
        content = tk.Frame(shell, bg=COLORS["bg"], padx=12, pady=10)
        content.grid(row=1, column=0, sticky=tk.NSEW)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        self._build_settings(content)
        self._build_output(content)

    def _build_header(self, parent: tk.Widget) -> None:
        header = tk.Frame(parent, bg=COLORS["primary_dark"], padx=18, pady=10)
        header.grid(row=0, column=0, sticky=tk.EW)
        header.columnconfigure(0, weight=1)

        tk.Label(
            header,
            text=APP_TITLE,
            bg=COLORS["primary_dark"],
            fg="#ffffff",
            font=("Microsoft JhengHei UI", 17, "bold"),
        ).grid(row=0, column=0, sticky=tk.W)

        tk.Label(
            header,
            text="一鍵抓取當週 Jira Bug 開單數量，排除 QA 專案並依報告人統計。",
            bg=COLORS["primary_dark"],
            fg="#c7f7ef",
            font=("Microsoft JhengHei UI", 10),
        ).grid(row=1, column=0, sticky=tk.W, pady=(1, 0))

        tk.Label(
            header,
            textvariable=self.range_badge_var,
            bg="#134e4a",
            fg="#ccfbf1",
            font=("Microsoft JhengHei UI", 11, "bold"),
            padx=14,
            pady=7,
        ).grid(row=0, column=1, rowspan=2, sticky=tk.E, padx=(18, 0))

    def _build_settings(self, parent: tk.Widget) -> None:
        card = tk.Frame(
            parent,
            bg=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        card.grid(row=0, column=0, sticky=tk.EW, pady=(0, 10))
        card.columnconfigure(1, weight=0)
        card.columnconfigure(2, weight=1)

        self._field_label(card, "Jira Token").grid(row=0, column=0, sticky=tk.W, padx=(0, 10), pady=(0, 8))
        self.token_entry = ttk.Entry(card, textvariable=self.token_var, show="*", width=36)
        self.token_entry.grid(row=0, column=1, sticky=tk.W, pady=(0, 8))

        token_tools = tk.Frame(card, bg=COLORS["surface"])
        token_tools.grid(row=0, column=2, sticky=tk.W, padx=(12, 0), pady=(0, 8))
        ttk.Checkbutton(token_tools, text="記住", variable=self.remember_token_var).pack(side=tk.LEFT)
        ttk.Checkbutton(
            token_tools,
            text="顯示",
            variable=self.show_token_var,
            command=self.toggle_token_visibility,
        ).pack(side=tk.LEFT, padx=(10, 0))

        self._field_label(card, "日期區間").grid(row=1, column=0, sticky=tk.W, padx=(0, 10))
        date_controls = tk.Frame(card, bg=COLORS["surface"])
        date_controls.grid(row=1, column=1, columnspan=2, sticky=tk.W)
        self._field_label(date_controls, "開始").pack(side=tk.LEFT)
        ttk.Entry(date_controls, textvariable=self.start_var, width=12).pack(side=tk.LEFT, padx=(8, 12))
        self._field_label(date_controls, "結束").pack(side=tk.LEFT)
        ttk.Entry(date_controls, textvariable=self.end_var, width=12).pack(side=tk.LEFT, padx=(8, 14))
        ttk.Button(date_controls, text="本週", command=lambda: self.set_week(0), width=8).pack(side=tk.LEFT)
        ttk.Button(date_controls, text="上週", command=lambda: self.set_week(-1), width=8).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(date_controls, text="下週", command=lambda: self.set_week(1), width=8).pack(side=tk.LEFT, padx=(8, 0))

        actions = tk.Frame(card, bg=COLORS["surface"])
        actions.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(10, 0))

        self.run_current_week_button = ttk.Button(
            actions,
            text="抓本週開單數",
            style="Primary.TButton",
            command=self.run_current_week,
        )
        self.run_current_week_button.grid(row=0, column=0, sticky=tk.W)

        self.run_button = ttk.Button(actions, text="依日期統計", command=self.run_report)
        self.run_button.grid(row=0, column=1, padx=(10, 0), sticky=tk.W)
        ttk.Button(actions, text="複製結果", command=self.copy_output).grid(row=0, column=2, padx=(10, 0), sticky=tk.W)
        ttk.Button(actions, text="清空", command=self.clear_output).grid(row=0, column=3, padx=(10, 0), sticky=tk.W)

        tk.Label(
            card,
            textvariable=self.status_var,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Microsoft JhengHei UI", 9),
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(8, 0))

    def _build_output(self, parent: tk.Widget) -> None:
        output_wrap = tk.Frame(
            parent,
            bg=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        output_wrap.grid(row=1, column=0, sticky=tk.NSEW)
        output_wrap.columnconfigure(0, weight=1)
        output_wrap.rowconfigure(1, weight=1)
        output_wrap.rowconfigure(2, weight=0)

        heading = tk.Frame(output_wrap, bg=COLORS["surface"])
        heading.grid(row=0, column=0, sticky=tk.EW, pady=(0, 6))
        heading.columnconfigure(1, weight=1)

        tk.Label(
            heading,
            text="統計結果",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=("Microsoft JhengHei UI", 13, "bold"),
        ).grid(row=0, column=0, sticky=tk.W)

        tk.Label(
            heading,
            textvariable=self.output_hint_var,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Microsoft JhengHei UI", 10),
        ).grid(row=0, column=1, sticky=tk.E, padx=(12, 0))

        result_area = tk.Frame(output_wrap, bg=COLORS["surface"])
        result_area.grid(row=1, column=0, sticky=tk.NSEW)
        result_area.columnconfigure(0, weight=1)
        result_area.rowconfigure(0, weight=1)

        self.cards_canvas = tk.Canvas(
            result_area,
            bg=COLORS["surface"],
            highlightthickness=0,
            bd=0,
        )
        y_scroll = ttk.Scrollbar(result_area, orient=tk.VERTICAL, command=self.cards_canvas.yview)
        self.cards_canvas.configure(yscrollcommand=y_scroll.set)
        self.cards_canvas.grid(row=0, column=0, sticky=tk.NSEW)
        y_scroll.grid(row=0, column=1, sticky=tk.NS)
        self.cards_frame = tk.Frame(self.cards_canvas, bg=COLORS["surface"])
        self.cards_window = self.cards_canvas.create_window((0, 0), window=self.cards_frame, anchor=tk.NW)
        self.cards_frame.bind("<Configure>", self._sync_cards_scrollregion)
        self.cards_canvas.bind("<Configure>", self._on_cards_canvas_resize)

        message_box = tk.Frame(output_wrap, bg=COLORS["surface"], pady=0)
        message_box.grid(row=2, column=0, sticky=tk.EW, pady=(6, 0))
        message_box.columnconfigure(0, weight=1)
        self.message_output = tk.Label(
            message_box,
            anchor=tk.W,
            justify=tk.LEFT,
            font=("Microsoft JhengHei UI", 10),
            bg=COLORS["surface_soft"],
            fg=COLORS["muted"],
            padx=12,
            pady=6,
            textvariable=self.message_var,
        )
        self.message_output.grid(row=0, column=0, sticky=tk.EW)

    def _build_footer(self, parent: tk.Widget) -> None:
        footer = tk.Frame(parent, bg=COLORS["bg"], padx=20, pady=10)
        footer.grid(row=2, column=0, sticky=tk.EW)
        footer.columnconfigure(0, weight=1)

        tk.Label(
            footer,
            text="Token 只會存到本機 jira_config.local.json，不會放進 Git。",
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Microsoft JhengHei UI", 9),
        ).grid(row=0, column=0, sticky=tk.W)

        tk.Label(
            footer,
            textvariable=self.range_badge_var,
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Microsoft JhengHei UI", 9, "bold"),
        ).grid(row=0, column=1, sticky=tk.E)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=("Microsoft JhengHei UI", 10), foreground=COLORS["text"])
        style.configure("TFrame", background=COLORS["surface"])
        style.configure("TLabel", background=COLORS["surface"], foreground=COLORS["text"])
        style.configure("TEntry", fieldbackground="#ffffff", bordercolor=COLORS["border"], padding=5)
        style.configure("TCheckbutton", background=COLORS["surface"], foreground=COLORS["text"])
        style.map("TCheckbutton", background=[("active", COLORS["surface"])])
        style.configure(
            "TButton",
            background="#e6edf3",
            foreground=COLORS["text"],
            bordercolor="#cdd8e2",
            padding=(12, 7),
        )
        style.map(
            "TButton",
            background=[("active", "#dbe7ef"), ("disabled", "#eef2f6")],
            foreground=[("disabled", "#94a3b8")],
        )
        style.configure(
            "Primary.TButton",
            background=COLORS["primary"],
            foreground="#ffffff",
            bordercolor=COLORS["primary_dark"],
            font=("Microsoft JhengHei UI", 11, "bold"),
            padding=(18, 9),
        )
        style.map(
            "Primary.TButton",
            background=[("active", COLORS["primary_hover"]), ("disabled", "#9cc9c5")],
            foreground=[("disabled", "#edfdfa")],
        )
    def _section_label(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=COLORS["surface"],
            fg=COLORS["primary_dark"],
            font=("Microsoft JhengHei UI", 12, "bold"),
        )

    def _field_label(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Microsoft JhengHei UI", 10, "bold"),
        )

    def _write_intro(self) -> None:
        start, end = friday_to_thursday()
        self.set_message(
            "使用方式：\n"
            "1. 貼上 Jira Token，勾選「記住 token」後下次會自動帶入。\n"
            f"2. 主管測試時直接按「抓本週開單數」，會抓 {format_week_range(start, end)}。\n"
            "3. 如需查舊資料，可改日期後按「依日期統計」。\n\n"
            "注意：token 只存到本機 jira_config.local.json，不會放進 Git commit。\n",
        )

    def clear_result_rows(self) -> None:
        for child in self.cards_frame.winfo_children():
            child.destroy()
        self.result_rows = []
        self.cards_canvas.configure(scrollregion=(0, 0, 0, 0))

    def render_result_rows(self, rows: list[tuple[str, str]]) -> None:
        self.result_rows = rows
        self._layout_result_cards()

    def _sync_cards_scrollregion(self, _event: tk.Event | None = None) -> None:
        self.cards_canvas.configure(scrollregion=self.cards_canvas.bbox(tk.ALL))

    def _on_cards_canvas_resize(self, event: tk.Event) -> None:
        self.cards_canvas.itemconfigure(self.cards_window, width=event.width)
        if self.result_rows:
            self._layout_result_cards()

    def _card_columns(self) -> int:
        width = max(self.cards_canvas.winfo_width(), self.winfo_width(), 1)
        if width >= 1040:
            return 4
        if width >= 760:
            return 3
        if width >= 520:
            return 2
        return 1

    def _layout_result_cards(self) -> None:
        for child in self.cards_frame.winfo_children():
            child.destroy()

        for column in range(4):
            self.cards_frame.columnconfigure(column, weight=0, uniform="")

        total_value = "0"
        member_rows = []
        for account, value in self.result_rows:
            if account == "Total":
                total_value = value
            else:
                member_rows.append((account, value))

        self.summary_total_var.set(total_value)

        columns = self._card_columns()
        for column in range(columns):
            self.cards_frame.columnconfigure(column, weight=1, uniform="metric_cards")

        for index, (account, value) in enumerate(member_rows):
            card = self._metric_card(self.cards_frame, account, value)
            card.grid(row=index // columns, column=index % columns, sticky=tk.EW, padx=5, pady=5)

        total_row = (len(member_rows) + columns - 1) // columns
        total_card = self._metric_card(self.cards_frame, "Total", total_value, is_total=True)
        total_card.grid(row=total_row, column=0, columnspan=columns, sticky=tk.EW, padx=5, pady=(8, 5))
        self.cards_frame.update_idletasks()
        self._sync_cards_scrollregion()

    def _metric_card(self, parent: tk.Widget, account: str, value: str, is_total: bool = False) -> tk.Frame:
        bg = "#dcfce7" if is_total else COLORS["surface_soft"]
        border = "#86efac" if is_total else COLORS["border"]
        fg = COLORS["primary_dark"] if is_total else COLORS["text"]
        card = tk.Frame(
            parent,
            bg=bg,
            highlightbackground=border,
            highlightthickness=1,
            padx=14,
            pady=10,
        )
        card.columnconfigure(0, weight=1)

        tk.Label(
            card,
            text=account,
            bg=bg,
            fg=fg,
            anchor=tk.W,
            font=("Microsoft JhengHei UI", 12, "bold" if is_total else "normal"),
        ).grid(row=0, column=0, sticky=tk.EW)
        tk.Label(
            card,
            text=value,
            bg=bg,
            fg=COLORS["primary_dark"],
            anchor=tk.E,
            font=("Microsoft JhengHei UI", 18 if is_total else 16, "bold"),
        ).grid(row=0, column=1, sticky=tk.E, padx=(12, 0))
        return card

    def set_message(self, text: str) -> None:
        message = " ".join(text.strip().splitlines())
        self.message_var.set(message)

    def toggle_token_visibility(self) -> None:
        self.token_entry.configure(show="" if self.show_token_var.get() else "*")

    def set_week(self, offset: int) -> None:
        start, end = friday_to_thursday(week_offset=offset)
        self.start_var.set(fmt(start))
        self.end_var.set(fmt(end))
        self.range_badge_var.set(format_week_range(start, end))
        self.status_var.set(f"已切換區間：{format_week_range(start, end)}")

    def run_current_week(self) -> None:
        self.set_week(0)
        self.run_report()

    def validate_inputs(self) -> bool:
        token = self.token_var.get().strip()
        if not token:
            messagebox.showerror("缺少 Token", "請先貼上 Jira token。")
            return False

        if not PS_SCRIPT.exists():
            messagebox.showerror("找不到腳本", f"找不到 {PS_SCRIPT}")
            return False

        for label, value in (("開始日期", self.start_var.get()), ("結束日期", self.end_var.get())):
            if not DATE_PATTERN.match(value.strip()):
                messagebox.showerror("日期格式錯誤", f"{label} 請使用 YYYY-MM-DD，例如 2026-09-02。")
                return False

        try:
            start = datetime.strptime(self.start_var.get().strip(), "%Y-%m-%d").date()
            end = datetime.strptime(self.end_var.get().strip(), "%Y-%m-%d").date()
        except ValueError:
            messagebox.showerror("日期錯誤", "請確認日期是有效日期。")
            return False

        if end < start:
            messagebox.showerror("日期錯誤", "結束日期不可早於開始日期。")
            return False

        self.range_badge_var.set(format_week_range(start, end))

        return True

    def run_report(self) -> None:
        if self.is_running:
            return
        if not self.validate_inputs():
            return

        self.save_current_config()
        self.is_running = True
        self.set_buttons_state(tk.DISABLED)
        self.latest_raw_output = ""
        self.latest_table_text = ""
        self.summary_total_var.set("...")
        self.clear_result_rows()
        self.output_hint_var.set("統計中")
        self.status_var.set("統計開單數量中，請稍等...")
        self.set_message("正在連線 Jira 並統計 QA 開單數量，完成後會自動更新上方表格。")

        thread = threading.Thread(target=self._run_report_worker, daemon=True)
        thread.start()

    def set_buttons_state(self, state: str) -> None:
        self.run_current_week_button.configure(state=state)
        self.run_button.configure(state=state)

    def save_current_config(self) -> None:
        config = {}

        if self.remember_token_var.get():
            config["token"] = self.token_var.get().strip()

        save_config(config)

    def build_command(self) -> list[str]:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PS_SCRIPT),
            "--start",
            self.start_var.get().strip(),
            "--end",
            self.end_var.get().strip(),
            "--report-mode",
            "bug-count",
            "--bug-issue-type",
            "Bug",
        ]

        return command

    def _run_report_worker(self) -> None:
        env = os.environ.copy()
        env["JIRA_API_TOKEN"] = self.token_var.get().strip()

        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            result = subprocess.run(
                self.build_command(),
                cwd=str(SCRIPT_DIR),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                timeout=600,
            )
        except Exception as exc:
            self.after(0, self._finish_report, f"執行失敗：{exc}", True)
            return

        parts = []
        if result.stdout.strip():
            parts.append(result.stdout.strip())
        if result.stderr.strip():
            parts.append(result.stderr.strip())

        text = "\n\n".join(parts).strip() or "沒有輸出。"
        self.after(0, self._finish_report, text, result.returncode != 0)

    def _finish_report(self, text: str, failed: bool) -> None:
        self.latest_raw_output = text
        self.set_buttons_state(tk.NORMAL)
        self.is_running = False

        if failed:
            self.latest_table_text = ""
            self.summary_total_var.set("0")
            self.clear_result_rows()
            self.output_hint_var.set("查詢失敗")
            self.set_message(text)
            self.status_var.set("執行失敗，請查看下方錯誤訊息。")
            return

        table = extract_summary_table(text)
        rows = parse_summary_rows(table)
        if not table or not rows:
            self.latest_table_text = ""
            self.summary_total_var.set("0")
            self.clear_result_rows()
            self.output_hint_var.set("沒有表格")
            self.set_message(text)
            self.status_var.set("查詢完成，但沒有找到可顯示的統計表格。")
            return

        self.latest_table_text = table
        self.render_result_rows(rows)
        self.output_hint_var.set("已完成")
        self.set_message("統計完成。按「複製結果」會複製乾淨的純文字表格。")
        self.status_var.set("完成，可以複製結果。")

    def copy_output(self) -> None:
        table = self.latest_table_text or extract_summary_table(self.latest_raw_output)
        if not table:
            self.status_var.set("沒有找到開單數量表格可複製。")
            return
        self.clipboard_clear()
        self.clipboard_append(table)
        self.status_var.set("已複製開單數量表格到剪貼簿。")

    def clear_output(self) -> None:
        self.latest_raw_output = ""
        self.latest_table_text = ""
        self.summary_total_var.set("0")
        self.clear_result_rows()
        self.output_hint_var.set("結果已清空")
        self.set_message("結果已清空。可以直接按「抓本週開單數」重新查詢。")
        self.status_var.set("結果已清空。")


if __name__ == "__main__":
    JiraReportApp().mainloop()

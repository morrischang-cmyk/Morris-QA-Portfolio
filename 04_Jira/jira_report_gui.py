# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import messagebox, ttk


SCRIPT_DIR = Path(__file__).resolve().parent
PS_SCRIPT = SCRIPT_DIR / "jira_report.ps1"


def default_friday_to_thursday() -> tuple[str, str]:
    today = date.today()
    days_since_friday = (today.weekday() - 4) % 7
    start = today - timedelta(days=days_since_friday)
    end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()


class JiraReportApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Jira TEST 單時數拉單")
        self.geometry("980x700")
        self.minsize(860, 560)

        self.token_var = tk.StringVar(value=os.getenv("JIRA_API_TOKEN", ""))
        start_text, end_text = default_friday_to_thursday()
        self.start_var = tk.StringVar(value=start_text)
        self.end_var = tk.StringVar(value=end_text)
        self.status_var = tk.StringVar(value="準備好了")

        self._build_ui()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill=tk.BOTH, expand=True)

        form = ttk.Frame(root)
        form.pack(fill=tk.X)

        ttk.Label(form, text="Jira Token").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        token_entry = ttk.Entry(form, textvariable=self.token_var, show="*", width=78)
        token_entry.grid(row=0, column=1, columnspan=5, sticky=tk.EW, pady=4)

        ttk.Label(form, text="Start").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        ttk.Entry(form, textvariable=self.start_var, width=16).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(form, text="End").grid(row=1, column=2, sticky=tk.W, padx=(18, 8), pady=4)
        ttk.Entry(form, textvariable=self.end_var, width=16).grid(row=1, column=3, sticky=tk.W, pady=4)

        self.run_button = ttk.Button(form, text="執行拉單", command=self.run_report)
        self.run_button.grid(row=1, column=4, sticky=tk.E, padx=(18, 0), pady=4)

        copy_button = ttk.Button(form, text="複製結果", command=self.copy_output)
        copy_button.grid(row=1, column=5, sticky=tk.E, padx=(8, 0), pady=4)

        form.columnconfigure(1, weight=1)

        ttk.Label(root, textvariable=self.status_var).pack(anchor=tk.W, pady=(12, 4))

        text_frame = ttk.Frame(root)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.output = tk.Text(
            text_frame,
            wrap=tk.NONE,
            font=("Consolas", 11),
            undo=False,
            borderwidth=1,
            relief=tk.SOLID,
        )
        y_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.output.yview)
        x_scroll = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=self.output.xview)
        self.output.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.output.grid(row=0, column=0, sticky=tk.NSEW)
        y_scroll.grid(row=0, column=1, sticky=tk.NS)
        x_scroll.grid(row=1, column=0, sticky=tk.EW)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

    def run_report(self) -> None:
        token = self.token_var.get().strip()
        if not token:
            messagebox.showerror("缺少 Token", "請先貼上 Jira token。")
            return

        if not PS_SCRIPT.exists():
            messagebox.showerror("找不到腳本", f"找不到 {PS_SCRIPT}")
            return

        self.run_button.configure(state=tk.DISABLED)
        self.status_var.set("拉單中，請稍等...")
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, "正在連線 Jira 並計算時數...\n")

        thread = threading.Thread(target=self._run_report_worker, daemon=True)
        thread.start()

    def _run_report_worker(self) -> None:
        env = os.environ.copy()
        env["JIRA_API_TOKEN"] = self.token_var.get().strip()

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
        ]

        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            result = subprocess.run(
                command,
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

        output_parts = []
        if result.stdout:
            output_parts.append(result.stdout.strip())
        if result.stderr:
            output_parts.append(result.stderr.strip())

        text = "\n\n".join(part for part in output_parts if part)
        if not text:
            text = "沒有輸出。"

        self.after(0, self._finish_report, text, result.returncode != 0)

    def _finish_report(self, text: str, failed: bool) -> None:
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, text)
        self.output.see("1.0")
        self.run_button.configure(state=tk.NORMAL)
        self.status_var.set("執行失敗" if failed else "完成，可以複製結果貼到 Slack")

    def copy_output(self) -> None:
        text = self.output.get("1.0", tk.END).strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("已複製到剪貼簿")


if __name__ == "__main__":
    JiraReportApp().mainloop()

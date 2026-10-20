from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from qa_mission_web import (
    REDIS_CREDENTIAL_ID,
    RedisClient,
    credential_store,
    load_redis_config,
    save_redis_config,
)


TEN_YEARS = 10 * 365 * 24 * 60 * 60


class RedisSetup:
    def __init__(self) -> None:
        config = load_redis_config()
        self.root = tk.Tk()
        self.root.title("Redis 人員對應設定")
        self.root.geometry("540x390")
        self.root.resizable(False, False)
        frame = ttk.Frame(self.root, padding=24)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        self.host = tk.StringVar(value=str(config["host"]))
        self.port = tk.StringVar(value=str(config["port"]))
        self.db = tk.StringVar(value=str(config["db"]))
        self.username = tk.StringVar(value=str(config["username"]))
        self.password = tk.StringVar()
        self.status = tk.StringVar(value="密碼只會儲存在 Windows Credential Manager。")

        fields = [
            ("Redis 主機", self.host, False),
            ("連接埠", self.port, False),
            ("DB", self.db, False),
            ("Redis 帳號（可留空）", self.username, False),
            ("Redis 密碼", self.password, True),
        ]
        for row, (label, variable, secret) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 16), pady=7)
            ttk.Entry(frame, textvariable=variable, show="●" if secret else "").grid(
                row=row, column=1, sticky=tk.EW, pady=7
            )

        self.button = ttk.Button(frame, text="驗證並安全儲存", command=self.save)
        self.button.grid(row=5, column=0, columnspan=2, sticky=tk.EW, pady=(18, 10))
        ttk.Label(frame, textvariable=self.status, wraplength=490).grid(
            row=6, column=0, columnspan=2, sticky=tk.W
        )

    def save(self) -> None:
        try:
            values = {
                "host": self.host.get().strip(),
                "port": int(self.port.get()),
                "db": int(self.db.get()),
                "username": self.username.get().strip(),
                "password": self.password.get(),
            }
        except ValueError:
            messagebox.showerror("格式錯誤", "連接埠與 DB 必須是數字。")
            return
        if not values["host"] or not values["password"]:
            messagebox.showerror("資料不足", "請輸入 Redis 主機與密碼。")
            return
        self.button.state(["disabled"])
        self.status.set("正在驗證 Redis 連線與 DB…")
        threading.Thread(target=self._save_worker, args=(values,), daemon=True).start()

    def _save_worker(self, values: dict[str, object]) -> None:
        try:
            with RedisClient(
                str(values["host"]),
                int(values["port"]),
                int(values["db"]),
                str(values["password"]),
                str(values["username"]),
            ) as client:
                if client.command("PING") != "PONG":
                    raise RuntimeError("Redis PING 沒有回傳 PONG。")
            credential_store.write(
                REDIS_CREDENTIAL_ID,
                str(values["username"]),
                str(values["password"]),
                ttl_seconds=TEN_YEARS,
            )
            save_redis_config(values)
        except Exception as error:
            self.root.after(0, lambda: self._failed(str(error)))
            return
        self.root.after(0, self._succeeded)

    def _failed(self, message: str) -> None:
        self.password.set("")
        self.button.state(["!disabled"])
        self.status.set(message)
        messagebox.showerror("設定失敗", message)

    def _succeeded(self) -> None:
        self.password.set("")
        self.button.state(["!disabled"])
        self.status.set(f"設定完成：已連線 {self.host.get()}，DB {self.db.get()}。")
        messagebox.showinfo("設定完成", "Redis 連線已驗證，密碼已安全儲存。")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    RedisSetup().run()

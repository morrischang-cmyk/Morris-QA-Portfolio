from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from qa_mission_web import (
    MATTERMOST_CREDENTIAL_ID,
    MattermostClient,
    credential_store,
    load_mattermost_config,
    save_mattermost_config,
)


TEN_YEARS = 10 * 365 * 24 * 60 * 60


class MattermostSetup:
    def __init__(self) -> None:
        config = load_mattermost_config()
        self.root = tk.Tk()
        self.root.title("Mattermost 機器人設定")
        self.root.geometry("590x355")
        self.root.resizable(False, False)

        frame = ttk.Frame(self.root, padding=24)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        self.url = tk.StringVar(value=config["base_url"])
        self.channel = tk.StringVar(value=config["channel_name"])
        self.username = tk.StringVar(value=config["bot_username"])
        self.token = tk.StringVar()
        self.status = tk.StringVar(value="Token 只會儲存在 Windows Credential Manager。")

        fields = [
            ("Mattermost 網址", self.url, False),
            ("頻道名稱", self.channel, False),
            ("機器人帳號", self.username, False),
            ("Access Token", self.token, True),
        ]
        for row, (label, variable, secret) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 16), pady=8)
            ttk.Entry(frame, textvariable=variable, show="●" if secret else "").grid(
                row=row, column=1, sticky=tk.EW, pady=8
            )

        self.button = ttk.Button(frame, text="驗證並安全儲存", command=self.save)
        self.button.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(20, 10))
        ttk.Label(frame, textvariable=self.status, wraplength=530).grid(
            row=5, column=0, columnspan=2, sticky=tk.W
        )

    def save(self) -> None:
        values = {
            "base_url": self.url.get().strip().rstrip("/"),
            "channel_name": self.channel.get().strip(),
            "bot_username": self.username.get().strip(),
            "token": self.token.get().strip(),
        }
        if not all(values.values()):
            messagebox.showerror("資料不足", "請填完所有欄位。")
            return
        self.button.state(["disabled"])
        self.status.set("正在驗證機器人 Token 與頻道權限…")
        threading.Thread(target=self._save_worker, args=(values,), daemon=True).start()

    def _save_worker(self, values: dict[str, str]) -> None:
        try:
            client = MattermostClient(values["base_url"], values["token"])
            current_user = client.request("GET", "/api/v4/users/me")
            actual_username = str(current_user.get("username") or "").strip()
            if actual_username.casefold() != values["bot_username"].casefold():
                raise ValueError(
                    f"此 Token 屬於 {actual_username or '未知帳號'}，不是 {values['bot_username']}。"
                )
            channel = client.find_channel(values["channel_name"])
            credential_store.write(
                MATTERMOST_CREDENTIAL_ID,
                actual_username,
                values["token"],
                ttl_seconds=TEN_YEARS,
            )
            save_mattermost_config(
                {
                    "base_url": values["base_url"],
                    "channel_name": values["channel_name"],
                    "channel_id": str(channel["id"]),
                    "bot_username": actual_username,
                }
            )
        except Exception as error:
            self.root.after(0, lambda: self._failed(str(error)))
            return
        self.root.after(0, lambda: self._succeeded(actual_username))

    def _failed(self, message: str) -> None:
        self.token.set("")
        self.button.state(["!disabled"])
        self.status.set(message)
        messagebox.showerror("設定失敗", message)

    def _succeeded(self, actual_username: str) -> None:
        self.token.set("")
        self.username.set(actual_username)
        self.button.state(["!disabled"])
        self.status.set(f"設定完成：{actual_username} 可以發送訊息到 {self.channel.get()}。")
        messagebox.showinfo("設定完成", "Mattermost 機器人已安全儲存並完成頻道驗證。")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    MattermostSetup().run()

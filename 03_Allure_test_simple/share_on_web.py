import os
import sys
import subprocess
import time
import urllib.request
import re
import threading

# 強制 UTF-8 輸出
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def download_cloudflared():
    """下載 Cloudflared 執行檔 (如果不存在)"""
    target = "cloudflared.exe"
    if os.path.exists(target):
        return target
    
    url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    print(f"【系統】正在下載外網轉跳工具 (Cloudflared)...")
    print(f"這可能需要一點時間，請稍候...")
    
    try:
        urllib.request.urlretrieve(url, target)
        print(f"【成功】工具下載完成。")
        return target
    except Exception as e:
        print(f"【錯誤】下載失敗: {e}")
        return None

def run_local_server():
    """確保 host_report.py 在後台執行"""
    print(f"【系統】正在確認本地伺服器狀態...")
    # 嘗試啟動 host_report.py
    # 使用 sys.executable 確保使用同一個 Python 環境
    proc = subprocess.Popen(
        [sys.executable, "host_report.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )
    # 給它一點時間啟動
    time.sleep(3)
    return proc

def start_tunnel(cf_exe):
    """啟動隧道並擷取公開網址"""
    print(f"【系統】正在建立外網隧道...")
    print(f"提示：請確保您的 8000 埠口沒有被其他程式佔用。")
    
    # Cloudflared 的網址會輸出在 stderr
    cmd = [cf_exe, "tunnel", "--url", "http://127.0.0.1:8000"]
    
    # 為了即時捕捉輸出，我們使用 Popen
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace'
    )

    found_url = False
    print("\n" + "="*70)
    print("           Allure 報告【外網分享】啟動中")
    print("="*70)
    print("\n[狀態] 正在等待 Cloudflare 生成隨機網址...")
    
    try:
        for line in process.stdout:
            # 搜尋類似 https://xxx.trycloudflare.com 的字樣
            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
            if match:
                public_url = match.group(0)
                print("\n" + "!"*70)
                print("  🎉 外網連結已生成！請將下方網址傳給同事：")
                print(f"\n  👉  {public_url}  👈")
                print("\n" + "!"*70)
                print("\n[注意] 只要此視窗不關閉，連結就是有效的。")
                print("[注意] 如果您的電腦進入睡眠或關機，連結會失效。")
                print("-" * 70)
                print("以下為即時連線日誌 (同事開啟網址時會跳出訊息):")
                found_url = True
            
            if found_url:
                # 繼續輸出日誌，讓使用者看到有人連進來
                if "GET /" in line or "404" in line:
                    print(line.strip())
                    
    except KeyboardInterrupt:
        print("\n\n【系統】正在關閉隧道與伺服器...")
        process.terminate()

def main():
    # 1. 檢查 host_report.py 是否存在
    if not os.path.exists("host_report.py"):
        print("【錯誤】找不到 host_report.py，請確保您在正確的目錄下。")
        return

    # 2. 下載工具
    cf_exe = download_cloudflared()
    if not cf_exe:
        return

    # 3. 啟動本地伺服器
    server_proc = run_local_server()

    try:
        # 4. 啟動隧道
        start_tunnel(cf_exe)
    finally:
        # 5. 清理程序
        print("【完成】已安全停止。")
        server_proc.terminate()

if __name__ == "__main__":
    main()

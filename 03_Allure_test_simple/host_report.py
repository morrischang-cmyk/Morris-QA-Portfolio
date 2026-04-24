import os
import sys
import io
import http.server
import socketserver
import socket
import errno

# 強制設定終端機輸出為 UTF-8 編碼，解決 Windows 上的亂碼問題
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

def get_local_ip():
    """獲取本機內網 IP 地址"""
    try:
        # 創建一個不發送數據的連線，藉此取得正確的本機介面 IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """使用多執行緒處理請求的 HTTP 伺服器"""
    daemon_threads = True
    
    def handle_error(self, request, client_address):
        """覆寫錯誤處理，隱藏常見的連線中斷 Traceback"""
        # 取得目前的異常資訊
        exctype, value = sys.exc_info()[:2]
        
        # 這些是常見的「不相干」錯誤：例如客戶端使用 HTTPS 連接 HTTP，或是連到一半關掉瀏覽器
        suppress_errors = (
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError
        )
        
        if exctype in suppress_errors:
            # 僅在終端機顯示簡短提示，而不噴出長長的 Traceback
            print(f"[{client_address[0]}] 連線已中斷 (Client disconnected or protocol mismatch)")
        else:
            # 其他真正的系統錯誤才顯示
            # super().handle_error(request, client_address)
            pass

class LoggingHandler(http.server.SimpleHTTPRequestHandler):
    """自定義 Handler 增加日誌紀錄"""
    def log_message(self, format, *args):
        # 在終端機顯示進來的請求，方便診斷是否連線成功
        print(f"[{self.log_date_time_string()}] 來源: {self.address_string()} - {format % args}")

def host_report(port=8000):
    report_dir = "allure-report"
    
    # 檢查報告目錄是否存在
    if not os.path.exists(report_dir):
        print("\n" + "!"*60)
        print(f"[錯誤] 找不到目錄: {os.path.abspath(report_dir)}")
        print("請先執行 run_test.py 生成報告。")
        print("!"*60 + "\n")
        return

    # 切換到報告目錄
    os.chdir(report_dir)
    
    local_ip = get_local_ip()
    
    print("\n" + "="*70)
    print("           Allure 報告伺服器 (多執行緒診斷版) 已啟動")
    print("="*70)
    print(f"\n[本地存取] http://localhost:{port}")
    print(f"[主管專用連結] http://{local_ip}:{port}")
    print("\n" + "!"*70)
    print("  重要提示：請確保主管使用的是 【http://】 而非 【https://】")
    print("  如果網址開頭多了一個 's'，會導致瀏覽器無法讀取數據！")
    print("!"*70)
    print("\n[日誌監控] (若連線成功將在此顯示來源 IP):")
    print("-" * 70)

    # 使用 ThreadingHTTPServer 避免單一連線卡住整個伺服器
    with ThreadingHTTPServer(("", port), LoggingHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n伺服器已手動停止。")
            sys.exit(0)
        except Exception as e:
            print(f"\n伺服器發生異常: {e}")
            sys.exit(1)

if __name__ == "__main__":
    host_report()

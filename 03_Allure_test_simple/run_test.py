import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 強制設定系統輸出編碼為 UTF-8，解決 Windows 終端機亂碼問題
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

def run_api_tests():
    """執行 API 測試並生成報告項目"""
    # 使用腳本所在目錄作為基準路徑
    base_path = Path(__file__).parent.absolute()
    results_dir = base_path / "allure-results"
    report_dir = base_path / "allure-report"
    pytest_config = base_path / "pytest.ini"

    # 確保目錄存在
    results_dir.mkdir(exist_ok=True)
    report_dir.mkdir(exist_ok=True)

    print("開始執行 API 測試...")
    # 使用設定檔執行測試
    cmd_pytest = [
        sys.executable, "-m", "pytest",
        "-c", str(pytest_config) # 指定設定檔
    ]
    test_result = subprocess.run(cmd_pytest).returncode

    if test_result in {0, 1}: # 0: 成功, 1: 有失敗但仍產生報告
        print("測試執行完成，開始生成 Allure 報告...")

        # 創建環境資訊 (可選)
        env_data = {
            "Environment": "Simple Test",
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(results_dir / "environment.properties", "w", encoding="utf-8") as f:
            for key, value in env_data.items():
                f.write(f"{key}={value}\n")

        # 生成 Allure 報告 (單一 HTML 文件)
        # 檢查 allure 是否安裝
        import shutil
        allure_bin = shutil.which("allure")
        if not allure_bin:
            print("\n[錯誤] 找不到 'allure' 指令。")
            print("請確保已安裝 Allure Commandline 並將其加入系統 PATH。")
            print("安裝教學與下載：https://github.com/allure-framework/allure2/releases")
        else:
            cmd_allure = f"allure generate {results_dir} -o {report_dir} --clean --single-file"
            subprocess.run(cmd_allure, shell=True)

        report_file = report_dir / "index.html"
        print("\n-------------------------------------")
        print(f"Allure 報告已生成: {report_file.resolve()}")
        print("-------------------------------------")

    else:
        print(f"測試執行失敗，返回碼: {test_result}")

if __name__ == "__main__":
    run_api_tests()
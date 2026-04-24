# 簡化版 API 測試專案

這個專案展示了一個基於 `pytest` 和 `Allure` 的簡化 API 自動化測試框架。

## 結構

```
.
├── allure-report-simple/   # 生成的 Allure HTML 報告目錄
├── allure-results-simple/  # Allure 原始結果目錄
├── test_case_simple/       # 測試用例目錄
│   └── test_sample_api.py  # 範例 API 測試
├── conftest_simple.py      # Pytest Fixtures 設定
├── pytest_simple.ini       # Pytest 設定檔
├── README_simple.md        # 本說明文件
├── requirements_simple.txt # 專案依賴
└── run_simple_test.py      # 測試執行和報告生成腳本
```

## 如何執行

1.  **安裝依賴**:
    ```bash
    # 建議在虛擬環境中執行
    # python -m venv venv_simple
    # source venv_simple/bin/activate  # Linux/macOS
    # .\venv_simple\Scripts\activate    # Windows

    pip install -r requirements_simple.txt
    ```

2.  **安裝 Allure 命令列工具**:
    請參考 Allure 官方文檔進行安裝：[https://allure.qa/docs/gettingstarted-installation/](https://allure.qa/docs/gettingstarted-installation/)
    確保 `allure` 命令在你的 PATH 中。

3.  **執行測試並生成報告**:
    ```bash
    python run_simple_test.py
    ```

4.  **查看報告**:
    執行完成後，會在 `allure-report-simple` 目錄下生成 `index.html` 文件。用瀏覽器打開即可查看報告。

## 客製化

-   **更改 API Base URL**: 修改 `conftest_simple.py` 中的 `api_base_url` fixture。
-   **添加更多測試**: 在 `test_case_simple` 目錄下創建新的 `test_*.py` 文件或在現有文件中添加 `Test*` 類和 `test_*` 方法。
-   **修改測試目標**: 更新 `test_sample_api.py` 中的 API 端點和斷言。 
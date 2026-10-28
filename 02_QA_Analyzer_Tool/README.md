# QA單號統計工具

本機網頁工具會從 Google Sheets 讀取指定月份的 QA 工作表，分別統計每位人員的手動測試、自動化與合計單數。

網頁整合為單一的「月份部門報告」，可以依選定年份與月份同時查看 Google Sheets 單號、Jira BUG、Worklog、成員工作量與每日趨勢。

## 資料規則

- 歷史月份：讀取 `YYYYMM(done)`。
- 當月：同時讀取 `YYYYMM(done)` 與 `進行中(中文月份)`。
- 進行中工作表只納入已分配手動或自動化人員的列。
- 同一格內有多個名字時，每個名字各計一單。
- 每一列都分別計算，即使內容相同也不會去重。

## 部門績效分析

- BUG 開單數沿用 `05_jirabug/Jira_Bug_Report_Tool_v7` 的規則：`issue type = Bug`、排除 QA 專案、依 reporter 統計。
- Jira Token 只由後端讀取此資料夾的 `jira_config.local.json`，不會傳到瀏覽器。
- 接手任務數來自 Google Sheets 的「人員」與「自動化」欄位。
- Jira QA Worklog 依 Jira 實際 `timeSpentSeconds` 換算並顯示人日：`1d = 8h`、`1w = 5d = 40h`。
- 績效報表每次產生時都重新查詢 Jira 與 Google Sheets，不讀取舊報表或截圖數字。
- 績效分析與月份單號統計一樣選擇「年份＋月份」；當月自動統計到今天，歷史月份統計完整月。
- 報告包含手動／自動化任務類型圓環圖、所有成員工作量占比、每接 1 個任務平均開出的 BUG、發測高峰日、成員比較、每日趨勢與明細表，並可直接儲存成保留網站版面與色彩的 PDF。
- 任務加 BUG 的合計只是工作量參考，不應單獨當作績效分數。
- 月份不可晚於當月。

## 啟動

若取得完整分享 ZIP，先**解壓縮**，開啟裡面的 `QA_Analyzer_Tool` 資料夾，再雙擊 `START_HERE.bat`。第一次啟動若缺少套件，會自動執行 `INSTALL.bat`。請勿在 ZIP 預覽畫面直接開啟批次檔。

若從版本庫取得原始碼，先將 `jira_config.example.json` 複製成 `jira_config.local.json`，填入自己有權限使用的 Jira Token，再執行 `START_HERE.bat`。真正的 Token 檔案已排除版本控制。

啟動視窗必須顯示「QA單號統計工具已啟動」與 `http://127.0.0.1:8766`；如果看到 Python 的 `>>>` 提示，代表網站沒有啟動，請確認使用新版 `START_HERE.bat`。如果顯示安裝失敗，請將視窗截圖給維護者。

也可以在此資料夾手動執行：

```powershell
python qa_analyzer_web.py
```

啟動後視窗會顯示兩個網址：

- 本機使用：`http://127.0.0.1:8766`
- 同事使用：`http://<這台電腦的內網 IP>:8766`

## 內網共用設定

1. 若要讓其他人連上這台電腦開啟的網站，先雙擊 `ALLOW_LAN.bat`。
2. 在 Windows 詢問時允許系統管理員權限。
3. 雙擊 `START_HERE.bat`。
4. 把視窗中的「同事可使用內網網址」傳給同事。

伺服器電腦需要保持開機，且啟動視窗不能關閉。防火牆規則只會開放公司網域與私人網路的 TCP 8766，不開放 Public 網路。

## 安裝依賴

```powershell
python -m pip install -r requirements.txt
```

## 傳給其他電腦修改

- ZIP 內包含完整 Python、HTML、CSS、JavaScript 原始碼，可直接修改。
- 需先安裝 Python 3.10 以上版本，電腦也需有 Chrome 或 Edge，供 PDF 匯出使用。
- 首次安裝需要可使用的 Python 套件下載來源；公司網路若限制 pip，請由 IT 協助安裝。
- `jira_config.local.json` 內含 Jira Token，請只透過公司內部安全管道傳送。
- Google Sheets 資料來源與 Jira 網址、成員對照可在 `qa_analyzer.py`、`qa_analyzer_web.py` 修改。
- 電腦需要能連線至公司 Jira 和 Google Sheets；若公司 Jira 僅允許 VPN 或內網連線，同事也需連上對應網路。

## 專案結構

- `qa_analyzer_web.py`：網頁伺服器、Jira 查詢與 PDF 匯出。
- `qa_analyzer.py`：Google Sheets 資料清理、姓名合併與任務統計；也保留原本的桌面 GUI。
- `web/`：首頁、樣式與圖表互動程式。
- `START_HERE.bat`、`INSTALL.bat`：Windows 啟動與安裝。
- `ALLOW_LAN.bat`：需要讓同事從內網連線時使用。
- `requirements-gui.txt`：只有執行舊版桌面 GUI 時才需要的額外套件。

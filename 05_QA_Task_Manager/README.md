# Jira QA_Mission 建立工具

目前使用 HTTPS 內網網頁介面。`qa_mission_web.py` 提供後端 API 與頁面服務，可讓每位使用者以自己的 Jira 帳號與 Token 登入、讀取主任務、整理 QA_Mission 內容並直接建立 Jira 單。

第一階段目標是從主任務自動準備 QA_Mission 需要的資料，減少人工複製欄位。

## 目前功能

- 輸入主任務單號並從 Jira 讀取資料。
- Bug 單開立網址自動使用主任務網址。
- BUG 單開立網址下方會加入 block 關連說明，關連到主任務並指派給主任務的報告人帳號。
- 每張單都會在代理上方加入固定的遊戲連結及後台連結，並以空行分隔 Description 各區塊。
- 經辦人固定填入 `arsene211`。
- 從主任務 Description 擷取「進測項目」到「驗證環境」之間的內容。
- 驗證環境及驗證版號和進測項目一樣，直接從主任務 Description 的對應區段擷取。
- 測試案例由使用者填寫；開始日期及到期日可從日曆點選，顯示格式如 `5/八月/25`，之後會各自寫入 Jira Create 畫面的同名欄位。
- Epic Link 提供 HCI-KX、HCI-LY、HCI-NW、HCI-V8、HCI-VP、HCI-YL 六個選項。
- 依 `qa_mission_rules.json` 的環境對照表自動帶入代理，並支援同一張主任務包含多個環境。
- 檢查每一個 Jira QA_Mission 欄位是否都有值，不會另外組成一段輸出文字。
- 依 QA_Mission 模板格式寫入 Jira Description。
- 將 Start date、到期日、Epic Link 與經辦人寫入 Jira 的獨立欄位。
- 建立成功後顯示新 Jira 單號及連結；失敗時顯示 Jira 回傳的缺少欄位。
- 可讀取既有 QA 主單，從固定人員清單一次複選多人並各自建立子任務；完整帳號作為 Jira 經辦人，標題後綴會移除尾端數字只保留英文名字，並可共用設定原始預估時間、剩餘時間及 Deadline。
- 子任務建立後可由 Mattermost 機器人通知 T 區測試部，訊息包含被指派人員、QA 主單標題、連結及 Deadline。
- Jira 與 Mattermost 帳號優先從 Redis DB 3 取得；Redis 未設定或連線失敗時會使用專案內建對應。

## 使用方式

1. 點兩下 `啟動_QA任務工具.bat`。
2. 工具會啟動 `http://127.0.0.1:8765` 並自動開啟瀏覽器；CMD 也會顯示同事可使用的內網網址。
3. 使用自己的 Jira 帳號與 Token 登入，再輸入主任務單號並按「讀取主任務」。
4. 確認自動帶入的 BUG 指派人、進測項目、環境、版號及代理。
5. 填入測試案例、從日曆選擇 Start Date 與到期日，並選擇 Epic Link。
6. 按「建立 QA Mission」，確認後會顯示新單號與 Jira 連結。
7. 如需分派工作，在「建立 QA 子任務」讀取 QA 主單，勾選一位或多位測試人員、填入工時與 Deadline 後送出。工時格式可使用 `4h`、`30m` 或 `1d 2h`。

同一個內網的同事可直接開啟 CMD 顯示的內網網址，目前預設連接埠為 `8765`。分享期間請保持這台電腦開機，並保持啟動工具的 CMD 視窗開啟。

## Mattermost 子任務通知

第一次使用請執行 `設定_Mattermost機器人.bat`，在本機視窗輸入 Access Token。Token 只會寫入 Windows Credential Manager，不會寫進專案檔案或回傳到網頁。設定程序會驗證 Token 所屬機器人及 T 區測試部頻道權限。

執行 `設定_Redis人員對應.bat` 可設定 Redis DB 3 的連線密碼。工具會優先從 Redis `employee_data` 的 `jira` 與 `mm` 欄位取得最新對應；沒有本機 Redis 設定或連線失敗時，會改用 `qa_mission_rules.json` 的 `mattermost_names`。

批次建立 QA 子任務後，工具會用成功建立的人員產生 Mattermost 標記，附上 QA 主單標題、連結和完成期限。期限直接使用建立子任務區手動選擇的 Deadline；如果 Jira 子任務建立畫面有同名的 Deadline 欄位，也會同步寫入該欄位。Deadline 與 Jira 到期日彼此獨立，子任務的到期日仍沿用 QA 主單。Mattermost 通知失敗不會回滾或影響已建立的 Jira 子任務。

## 登入與 Token 安全

- Jira API 使用 Bearer Token 驗證，因此工具不收集或保存 Jira 密碼。
- 登入時會呼叫 Jira `/myself` 驗證 Token，並確認 Token 所屬帳號與輸入帳號一致。
- Token 不會回傳網頁、不會放進 Cookie、不會寫入專案設定檔，也不會出現在伺服器紀錄。
- 未勾選「記住登入」時，Token 只保留在後端記憶體，登出或停止工具後失效。
- 勾選「記住登入」時，帳號與 Token 會加密保存在主機目前 Windows 使用者的 Credential Manager，保存期限 30 天；瀏覽器只保存不可預測的識別碼。
- Session Cookie 使用 `HttpOnly`、`Secure`、`SameSite=Strict`，登入頁與 API 僅透過 HTTPS 提供。
- 登出時會清除 Session、瀏覽器 Cookie，以及該瀏覽器對應的 Credential Manager 登入資料。

## 設定

`qa_mission_rules.json` 保存 Epic Link、區段標題及環境與代理的對照。取得實際環境名稱後，將代理填入 `environment_agent_map`。

Jira 網址不顯示在登入頁。每位使用者輸入自己的 Token，後端只在該使用者的安全 Session 中使用。

## 建立方式

工具已依 Jira Create Metadata 確認 QA_Mission 使用 QA 專案的 `Task` 類型。BUG 單開立、進測項目、測試案例、驗證環境、驗證版號及代理會按照模板排版寫入 Description；日期、Epic Link 與經辦人則寫入各自的 Jira 欄位。

QA Mission 與多人子任務都會使用 Jira Create Metadata 對應實際欄位，降低不同 Jira 專案設定造成的欄位錯誤。

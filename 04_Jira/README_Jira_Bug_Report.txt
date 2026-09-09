Jira Bug 統計工具使用說明

使用方式：
1. 解壓縮整個資料夾。
2. 點兩下「啟動_Jira拉單工具.bat」。
3. 第一次使用時貼上 Jira Token，勾選「記住 token」。
4. 按「抓本週開單數」即可統計本週資料。
5. 按「複製結果」可只複製成員統計表格。

目前統計規則：
- 抓 Jira issue type = Bug。
- 排除 project = QA。
- 依 Jira 報告人 reporter 統計。
- 日期區間預設為週五到週四。

注意：
- jira_config.local.json 是本機 token 設定檔，請不要上傳到 Git。
- 若主管電腦沒有 Python，請先安裝 Python 3，並勾選 Add Python to PATH。

import requests
import pandas as pd
from openpyxl.styles import Font, Alignment, PatternFill
from datetime import datetime
import os
import gspread
from google.oauth2.service_account import Credentials

# API 配置
API_CONFIG = {
    "winlose": {
        "url": "http://192.168.37.6:8087/practice_data?key=winlose",
        "sheet_name": "盈利報表",
        "translation": {
            "walletType": "錢包種類",
            "gameEndTime": "帳變時間",
            "account": "會員名稱",
            "opValue": "opValue",
            "gameId": "遊戲編號",
            "gameName": "遊戲類型",
            "roomName": "房間類型",
            "tableId": "桌號",
            "chairId": "座位號",
            "category": "category",
            "language": "語言",
            "currency": "幣別",
            "gameNo": "局號",
            "banker": "莊閒",
            "roomType": "牌局類型",
            "allBet": "總投注",
            "revenue": "抽水",
            "score": "初始金額",
            "cellScore": "有效投住",
            "profit": "盈利金額"
        }
    },
    "usermoney": {
        "url": "http://192.168.37.6:8087/practice_data?key=usermoney",
        "sheet_name": "會員點數明細",
        "translation": {
            "id": "ID",
            "gameUserNO": "局號",
            "orderTime": "時間",
            "playerAccount": "玩家帳號",
            "type": "Type",
            "currency": "幣別",
            "originScore": "帳變前金額",
            "addScore": "帳變金額",
            "newScore": "帳變後金額",
            "ip": "IP",
            "status": "Status",
            "createUser": "操作人",
            "agentAccount": "代理",
            "orderId": "訂單號",
            "channelId": "channelid",
            "orderType": "類型",
            "orderStatus": "狀態",
            "curScore": "帳變前金額",
            "orderIP": "OrderIP",
            "account": "玩家帳號",
            "channelName": "channelname",
            "timezone": "timezone"
        }
    }
}

def fetch_data(url):
    """抓取 API 資料"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        # 根據測試結果，資料在 rows 鍵值下
        if isinstance(data, dict):
            if "rows" in data:
                return data["rows"]
            if "data" in data:
                return data["data"]
        return data
    except Exception as e:
        print(f"抓取資料失敗 ({url}): {e}")
        return []

def translate_and_format(data, mapping):
    """翻譯欄位名稱並整理資料"""
    if not data:
        return pd.DataFrame()
    
    df = pd.DataFrame(data)
    # 只保留定義在翻譯表中的欄位，並重新命名，同時維持定義的順序
    cols_to_keep = [col for col in mapping.keys() if col in df.columns]
    df = df[cols_to_keep].rename(columns=mapping)
    return df

def save_to_excel(dfs_with_names, filename):
    """將多個 DataFrame 存入 Excel 並美化"""
    with pd.ExcelWriter(filename, engine='openpyxl') as writer:
        for df, sheet_name in dfs_with_names:
            if df.empty:
                continue
            
            df.to_excel(writer, index=False, sheet_name=sheet_name)
            
            # 美化樣式
            workbook = writer.book
            worksheet = writer.sheets[sheet_name]
            
            # 設定標題樣式 (粉綠色背景、粗體、置中)
            header_fill = PatternFill(start_color="C6E0B4", end_color="C6E0B4", fill_type="solid")
            header_font = Font(bold=True, size=12)
            alignment = Alignment(horizontal="center", vertical="center")
            
            for cell in worksheet[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = alignment
            
            # 設定內容居中與自動調整欄寬
            for col in worksheet.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    cell.alignment = alignment # 全部居中
                    try:
                        if cell.value:
                            # 處理中文字元長度
                            val_str = str(cell.value)
                            length = sum(2 if ord(char) > 127 else 1 for char in val_str)
                            max_length = max(max_length, length)
                    except:
                        pass
                adjusted_width = (max_length + 4)
                worksheet.column_dimensions[column].width = adjusted_width

def safe_print(msg):
    """安全列印，處理 Windows CP950 編碼問題"""
    try:
        print(msg)
    except UnicodeEncodeError:
        # 如果發生編碼問題，將不支援的字元替換為 ?
        print(msg.encode('cp950', errors='replace').decode('cp950'))

def analyze_kill_games(df):
    """分析追殺局 (K/PTK/T) 的玩家『異常贏錢』比例，並回傳異常局資料"""
    # 定義預設回傳的欄位結構
    columns_map = {
        "gameEndTime": "日期",
        "gameName": "遊戲類型",
        "roomType": "牌局類型",
        "gameNo": "局號",
        "cellScore": "有效投注",
        "profit": "盈利金額",
        "revenue": "抽水",
        "account": "玩家帳號"
    }
    empty_df = pd.DataFrame(columns=columns_map.values())

    if df.empty:
        return empty_df
    
    kill_types = ['K', 'PTK', 'T']
    kill_df = df[df['roomType'].isin(kill_types)].copy()
    
    if kill_df.empty:
        safe_print("【分析】本次資料中無任何追殺局 (K/PTK/T)。")
        return empty_df

    safe_print("-" * 50)
    safe_print("[Kill Game Analysis Report]")
    safe_print(f"Room Types: {kill_types}")
    safe_print(f"Definition of Abnormal: (Profit + Revenue) > (Effective Bet * 1.05)")
    safe_print("-" * 50)

    # 確保數值正確 (處理可能包含逗號的字串)
    for col in ['profit', 'cellScore', 'revenue']:
        if col in kill_df.columns:
            kill_df[col] = kill_df[col].astype(str).str.replace(',', '', regex=False)
            kill_df[col] = pd.to_numeric(kill_df[col], errors='coerce').fillna(0)
    
    # 標記異常局號 ( (盈利 + 抽水) > 有效投注 * 1.05 )
    kill_df['is_abnormal'] = (kill_df['profit'] + kill_df['revenue']) > (kill_df['cellScore'] * 1.05)
    
    abnormal_records = []
    
    for game_name, group in kill_df.groupby('gameName'):
        total_count = len(group)
        abnormal_group = group[group['is_abnormal']]
        abnormal_count = len(abnormal_group)
        abnormal_rate = (abnormal_count / total_count) * 100 if total_count > 0 else 0
        
        status_msg = f"  - Game: {game_name}, Total: {total_count}, Abnormal Win: {abnormal_count}, Rate: {abnormal_rate:.2f}%"
        if abnormal_rate > 5:
            safe_print("!!! ALERT: High Abnormal Win Rate in Kill Game !!!")
            safe_print(f" {status_msg} (> 5%!)")
        else:
            safe_print(status_msg)
            
        if not abnormal_group.empty:
            abnormal_records.append(abnormal_group)

    safe_print("-" * 50)
    
    if abnormal_records:
        # 合併所有異常紀錄
        all_abnormal_df = pd.concat(abnormal_records)
        # 只取存在的欄位
        existing_cols = [c for c in columns_map.keys() if c in all_abnormal_df.columns]
        return all_abnormal_df[existing_cols].rename(columns=columns_map)
    
    return empty_df

def upload_to_gsheet(dfs_with_names, filename):
    """將資料上傳至固定的 Google Sheet 並回傳共享連結"""
    try:
        # 1. 設定固定網址
        SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1eNCPc7DEztwEYm_dxbRSKQzBs2I8HaZ2c8X7K0SXlvM/edit?gid=0#gid=0"
        
        # 2. 設定權限範疇
        SCOPES = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        
        # 3. 載入憑證
        creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
        client = gspread.authorize(creds)
        
        # 4. 開啟試算表
        sh = client.open_by_url(SPREADSHEET_URL)
        
        # 5. 處理工作表
        # 先獲取目前所有的工作表名稱
        existing_worksheets = {ws.title: ws for ws in sh.worksheets()}
        
        for i, (df, sheet_name) in enumerate(dfs_with_names):
            if df.empty:
                continue
            
            # 檢查工作表是否存在
            if sheet_name in existing_worksheets:
                ws = existing_worksheets[sheet_name]
                ws.clear() # 清空舊資料
            else:
                ws = sh.add_worksheet(title=sheet_name, rows="100", cols="20")
            
            # 準備資料
            data = [df.columns.values.tolist()] + df.values.tolist()
            data = [[(str(v) if pd.notnull(v) else "") for v in row] for row in data]
            
            # 一次性更新
            ws.update("A1", data)
            
            # 美化
            ws.format("A1:Z1", {
                "textFormat": {"bold": True},
                "horizontalAlignment": "CENTER",
                "backgroundColor": {"red": 0.77, "green": 0.88, "blue": 0.7}
            })
            
        return SPREADSHEET_URL
        
    except Exception as e:
        safe_print(f"【錯誤】上傳至 Google Sheets 失敗: {e}")
        return None

def main():
    print("【系統】開始抓取 API 資料並轉換...")
    results = []
    abnormal_df = None
    
    for key, config in API_CONFIG.items():
        print(f"【進度】正在處理: {config['sheet_name']}...")
        raw_rows = fetch_data(config["url"])
        
        # 如果是盈利報表，先進行追殺局分析
        if key == "winlose":
            raw_df = pd.DataFrame(raw_rows) if raw_rows else pd.DataFrame()
            abnormal_df = analyze_kill_games(raw_df)
            
        df = translate_and_format(raw_rows, config["translation"])
        if not df.empty:
            results.append((df, config["sheet_name"]))
            print(f"【成功】已載入 {len(df)} 筆資料。")
        else:
            print(f"【警告】{config['sheet_name']} 未抓取到資料。")

    # 只要有進行分析，就強行加入「異常局號」頁籤 (由 analyze_kill_games 回傳適當的 DataFrame)
    if abnormal_df is not None:
        results.append((abnormal_df, "異常局號"))
        print(f"【紀錄】已產出異常局號資料 (共 {len(abnormal_df)} 筆)。")

    if results:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = f"API_資料轉換報表_{timestamp}"
        
        # 產出 Excel
        excel_filename = f"{base_filename}.xlsx"
        print(f"【系統】正在產出 Excel 檔案: {excel_filename}...")
        save_to_excel(results, excel_filename)
        print(f"【完成】Excel 產出成功！路徑: {os.path.abspath(excel_filename)}")
        
        # 上傳至 Google Sheets
        print(f"【系統】正在同步至 Google Sheets...")
        gsheet_url = upload_to_gsheet(results, base_filename)
        if gsheet_url:
            print(f"【成功】Google Sheets 共享連結: {gsheet_url}")
        
    else:
        print("【錯誤】未抓取到任何有效資料，未生成檔案。")

if __name__ == "__main__":
    main()


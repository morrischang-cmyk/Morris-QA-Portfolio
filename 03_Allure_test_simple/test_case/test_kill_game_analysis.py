import sys
import os
import pytest
import allure
import pandas as pd
from io import StringIO

# 將 list.py 所在的目錄加入系統路徑，以便進行匯入
# list.py 路徑: c:\Users\Morris.Chang\Desktop\Python\list.py
python_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../Python"))
if python_dir not in sys.path:
    sys.path.append(python_dir)

try:
    from list import fetch_data, API_CONFIG
except ImportError as e:
    print(f"匯入 list.py 失敗: {e}")
    raise

def pytest_generate_tests(metafunc):
    """
    動態生成測試案例。
    會從 API 抓取資料，並根據每一筆追殺局 (K/PTK/T) 生成一個獨立的測試案例。
    """
    if "game_record" in metafunc.fixturenames:
        winlose_config = API_CONFIG.get("winlose")
        url = winlose_config.get("url")
        
        # 抓取資料
        raw_rows = fetch_data(url)
        if not raw_rows:
            metafunc.parametrize("game_record", [], ids=["NoData"])
            return

        # 轉為 DataFrame 方便過濾
        df = pd.DataFrame(raw_rows)
        
        # 只過濾追殺局類型 (K, PTK, T)
        kill_types = ['K', 'PTK', 'T']
        if 'roomType' in df.columns:
            kill_df = df[df['roomType'].isin(kill_types)].copy()
        else:
            kill_df = pd.DataFrame()

        if kill_df.empty:
            metafunc.parametrize("game_record", [], ids=["NoKillGames"])
            return

        # 將每一列轉回字典列表
        records = kill_df.to_dict('records')
        
        # 使用局號 (gameNo) 作為測試案例的 ID
        ids = [f"局號_{r.get('gameNo', 'Unknown')}" for r in records]
        
        metafunc.parametrize("game_record", records, ids=ids)

@allure.epic("數據分析代碼測試")
@allure.feature("Kill Game 追蹤分析 (單局檢測)")
class TestKillGameAnalysis:

    @allure.story("獨立局號檢測")
    @allure.severity(allure.severity_level.NORMAL)
    def test_kill_game_record(self, game_record):
        """
        針對每一筆局號進行獨立驗證。
        判定邏輯：(Profit + Revenue) > (Effective Bet * 1.05) 則為 FAIL。
        """
        game_no = game_record.get('gameNo', 'Unknown')
        
        # 設定動態標題，讓報告更容易閱讀
        allure.dynamic.title(f"局號單獨檢測: {game_no}")
        allure.dynamic.description(f"""
        檢測局號: {game_no}
        遊戲名稱: {game_record.get('gameName', 'N/A')}
        牌局類型: {game_record.get('roomType', 'N/A')}
        更新時間: {game_record.get('gameEndTime', 'N/A')}
        """)

        # 1. 數據清理與轉換
        try:
            profit = float(str(game_record.get('profit', 0)).replace(',', ''))
            revenue = float(str(game_record.get('revenue', 0)).replace(',', ''))
            cell_score = float(str(game_record.get('cellScore', 0)).replace(',', ''))
        except (ValueError, TypeError):
            pytest.fail(f"局號 {game_no} 數據格式異常，無法轉換為數值")

        # 2. 核心異常判定邏輯
        # 判定標準: (盈利 + 抽水) > (有效投注 * 1.05)
        is_abnormal = (profit + revenue) > (cell_score * 1.05)
        
        # 3. 附加詳細資訊到 Allure
        details = {
            "局號": game_no,
            "有效投注 (cellScore)": cell_score,
            "盈利金額 (profit)": profit,
            "抽水 (revenue)": revenue,
            "判定基準 (1.05倍)": cell_score * 1.05,
            "計算值 (Profit + Revenue)": profit + revenue,
            "檢測結果": "❌ 異常 (FAIL)" if is_abnormal else "✅ 正常 (PASS)"
        }
        allure.attach(
            StringIO(pd.Series(details).to_string()).getvalue(),
            name="檢測數值明細",
            attachment_type=allure.attachment_type.TEXT
        )

        # 4. 根據判定結果觸發 PASS/FAIL
        if is_abnormal:
            # 輔助提示
            logger_msg = f"檢測到異常局號 [{game_no}]: (Profit {profit} + Revenue {revenue}) > (CellScore {cell_score} * 1.05)"
            # 如果有安裝 loguru 可以使用，否則退而求其次
            print(logger_msg) 
            
            pytest.fail(f"局號 {game_no} 判定為異常贏錢 (超出 1.05 倍門檻)")
        else:
            assert True

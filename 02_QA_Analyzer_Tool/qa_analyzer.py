import pandas as pd
import time
import re
import unicodedata
from calendar import monthrange
from collections import Counter
from datetime import date
import numpy as np
try:
    import customtkinter as ctk
    from tkinter import messagebox
except ImportError:
    # The web server only imports the data functions above. The desktop GUI is optional.
    ctk = None
    messagebox = None


# 已確認的同人別名與明顯拼字錯誤，統一轉成正式名稱
NAME_ALIASES = {
    'asher': 'arthur',
    'arsen': 'arsene',
    'peyter': 'peter',
    'ydia': 'lydia',
    'lydua': 'lydia',
    'moeeis': 'morris'
}

SHEET_ID = "1L7pOB-dSV26IE6VJKyfm-IZd1a3bxvri7FChC7xtBSw"
EXCEL_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
CHINESE_MONTHS = {
    1: '一月', 2: '二月', 3: '三月', 4: '四月',
    5: '五月', 6: '六月', 7: '七月', 8: '八月',
    9: '九月', 10: '十月', 11: '十一月', 12: '十二月'
}


# ---------------------------------------------------------
# 1. 核心清洗與運算邏輯 (嚴格日曆工作日版)
# ---------------------------------------------------------
def super_clean_date(text):
    if pd.isna(text): return None
    text = unicodedata.normalize('NFKC', str(text))
    match = re.search(r'(\d{4})\D+(\d{1,2})\D+(\d{1,2})', text)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return None

def extract_names(value):
    """將同一格內的多位人員拆開。
    同一名字在同一格重複出現時，只計算一張單。
    """
    if pd.isna(value):
        return []

    text = unicodedata.normalize('NFKC', str(value)).lower()
    names = [
        NAME_ALIASES.get(name.strip(), name.strip())
        for name in re.split(r'[,，、;；/／\.\s]+', text)
        if name.strip()
    ]
    return list(dict.fromkeys(names))


def process_qa_data(year, month):
    target_sheet = f"{year}{month:02d}(done)"
    start_date = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])
    end_date = min(month_end, date.today())
    is_current_month = (year, month) == (date.today().year, date.today().month)

    try:
        # 依使用者選擇的年月，只讀取對應的 YYYYMM(done) 工作表
        with pd.ExcelFile(EXCEL_URL, engine='openpyxl') as workbook:
            if target_sheet not in workbook.sheet_names:
                available_months = sorted(
                    sheet_name[:6]
                    for sheet_name in workbook.sheet_names
                    if re.fullmatch(r'\d{6}\(done\)', sheet_name)
                )
                return False, (
                    f"找不到工作表 '{target_sheet}'。\n"
                    f"目前可選月份：{', '.join(available_months)}"
                )

            source_sheets = [target_sheet]
            frames = [pd.read_excel(workbook, sheet_name=target_sheet)]

            # 選擇當月時，同時納入「進行中(月份)」工作表
            in_progress_sheet = f"進行中({CHINESE_MONTHS[month]})"
            if is_current_month and in_progress_sheet in workbook.sheet_names:
                in_progress = pd.read_excel(workbook, sheet_name=in_progress_sheet)
                in_progress = in_progress.rename(columns={
                    '進測日期': '發測日期',
                    '手動測試': '人員',
                    '自動化測試': '自動化'
                })

                # 進行中表包含分區標題與空白預留列，只納入已分配人員的實際單據
                if '測試項目' in in_progress.columns:
                    in_progress = in_progress[
                        in_progress['測試項目'].astype(str).ne('測試項目')
                    ]
                assigned_rows = (
                    in_progress.get('人員', pd.Series(index=in_progress.index, dtype=object)).notna()
                    | in_progress.get('自動化', pd.Series(index=in_progress.index, dtype=object)).notna()
                )
                in_progress = in_progress[assigned_rows].copy()
                frames.append(in_progress)
                source_sheets.append(in_progress_sheet)

            df = pd.concat(frames, ignore_index=True, sort=False)
        
        date_col = '發測日期'
        if date_col not in df.columns:
            return False, f"找不到欄位 '{date_col}'，請確認表單格式。"

        required_columns = ['人員', '自動化']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return False, f"找不到欄位：{', '.join(missing_columns)}，請確認表單格式。"

        # 清洗日期供高峰日統計使用；人員統計以整張工作表為準
        clean_dates = df[date_col].apply(super_clean_date)
        converted_dates = pd.to_datetime(clean_dates, errors='coerce')
        df[date_col] = converted_dates

        # 每一列都是一張單；即使內容相同，仍依實際儲存格分別計算
        # 人員每在一列出現一次，就計算負責一張單
        manual_counts = Counter()
        automation_counts = Counter()

        for value in df['人員']:
            manual_counts.update(extract_names(value))

        for value in df['自動化']:
            automation_counts.update(extract_names(value))

        all_names = sorted(
            set(manual_counts) | set(automation_counts),
            key=lambda name: (
                -(manual_counts[name] + automation_counts[name]),
                name
            )
        )
        person_stats = pd.DataFrame([
            {
                '人員': name,
                '手動單數': manual_counts[name],
                '自動化單數': automation_counts[name],
                '合計': manual_counts[name] + automation_counts[name]
            }
            for name in all_names
        ])
        
        # 產能計算 (扣除六日)
        total_items = len(df)
        workdays_count = np.busday_count(start_date, end_date + pd.Timedelta(days=1))
        avg_per_day = total_items / workdays_count if workdays_count > 0 else 0
        
        # 高峰日排行榜（無法解析日期的列不納入排行榜）
        valid_date_df = df[df[date_col].notna()].copy()
        valid_date_df['日期字串'] = valid_date_df[date_col].dt.strftime('%Y-%m-%d')
        daily_stats = valid_date_df.groupby('日期字串').size().reset_index(name='項目總數')
        top_6 = daily_stats.sort_values(by='項目總數', ascending=False).head(6)

        return True, {
            "total_items": total_items,
            "workdays": workdays_count,
            "avg_per_day": avg_per_day,
            "start_date": start_date,
            "end_date": end_date,
            "top_6": top_6,
            "person_stats": person_stats,
            "sheet_name": target_sheet,
            "source_sheets": source_sheets,
            "is_current_month": is_current_month
        }

    except Exception as e:
        return False, f"發生錯誤：{str(e)}"

# ---------------------------------------------------------
# 2. GUI 視窗介面設計
# ---------------------------------------------------------
class QAAnalyzerApp(ctk.CTk if ctk else object):
    def __init__(self):
        if ctk is None:
            raise RuntimeError("Desktop GUI requires customtkinter. Install requirements-gui.txt.")
        super().__init__()

        # 設定視窗基本屬性
        self.title("QA單號統計工具")
        self.geometry("760x820")
        ctk.set_appearance_mode("dark")  # 深色模式
        ctk.set_default_color_theme("blue")

        # --- UI 元件佈局 ---
        # 標題
        self.title_label = ctk.CTkLabel(self, text="📊 QA單號統計工具", font=ctk.CTkFont(size=24, weight="bold"))
        self.title_label.pack(pady=(20, 10))

        # 選擇要讀取的月份工作表
        self.month_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.month_frame.pack(pady=5)

        ctk.CTkLabel(self.month_frame, text="年份：").grid(row=0, column=0, padx=(0, 5))
        self.year_entry = ctk.CTkEntry(self.month_frame, width=100)
        self.year_entry.grid(row=0, column=1, padx=(0, 20))
        self.year_entry.insert(0, str(date.today().year))

        ctk.CTkLabel(self.month_frame, text="月份：").grid(row=0, column=2, padx=(0, 5))
        self.month_combo = ctk.CTkComboBox(
            self.month_frame,
            width=100,
            values=[f"{month:02d}" for month in range(1, 13)],
            state="readonly"
        )
        self.month_combo.grid(row=0, column=3)
        self.month_combo.set(f"{date.today().month:02d}")

        self.month_hint = ctk.CTkLabel(
            self,
            text="例如：2026 年 09 月會讀取 202609(done)",
            text_color="gray"
        )
        self.month_hint.pack(pady=(0, 5))

        # 執行按鈕
        self.run_btn = ctk.CTkButton(self, text="🚀 開始從雲端抓取與分析", font=ctk.CTkFont(size=16), command=self.run_analysis)
        self.run_btn.pack(pady=10)

        # 狀態提示
        self.status_label = ctk.CTkLabel(self, text="準備就緒，請點擊上方按鈕開始。", text_color="gray")
        self.status_label.pack(pady=(0, 10))

        # 產能指標卡片 (Frame)
        self.stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.stats_frame.pack(pady=10, padx=20, fill="x")

        self.lbl_period = ctk.CTkLabel(self.stats_frame, text="選取工作表: --", font=ctk.CTkFont(size=14))
        self.lbl_period.pack(anchor="w", pady=2)
        self.lbl_total = ctk.CTkLabel(self.stats_frame, text="累計發測項目: --", font=ctk.CTkFont(size=14))
        self.lbl_total.pack(anchor="w", pady=2)
        self.lbl_workdays = ctk.CTkLabel(self.stats_frame, text="歷史總工作日: -- (扣除六日)", font=ctk.CTkFont(size=14))
        self.lbl_workdays.pack(anchor="w", pady=2)
        
        # 🌟 已經替換為精準的規格書名詞
        self.lbl_avg = ctk.CTkLabel(self.stats_frame, text="單一日進測平均數量: --", font=ctk.CTkFont(size=20, weight="bold"), text_color="#2ecc71")
        self.lbl_avg.pack(anchor="w", pady=(10, 0))

        # 人員統計與排行榜文字區 (Textbox)
        self.ranking_label = ctk.CTkLabel(self, text="👥 人員負責單數（手動／自動化）", font=ctk.CTkFont(size=16, weight="bold"))
        self.ranking_label.pack(pady=(20, 5))
        
        self.textbox = ctk.CTkTextbox(self, width=700, height=350, font=ctk.CTkFont(family="Consolas", size=14))
        self.textbox.pack(pady=5)
        self.textbox.insert("0.0", "等待分析結果...\n")
        self.textbox.configure(state="disabled")

    # 按下按鈕後執行的動作
    def run_analysis(self):
        try:
            year = int(self.year_entry.get().strip())
            month = int(self.month_combo.get())
            selected_month = date(year, month, 1)
        except (TypeError, ValueError):
            messagebox.showerror("月份錯誤", "請輸入正確年份並選擇月份。")
            return

        if selected_month > date.today().replace(day=1):
            messagebox.showerror("月份錯誤", "不能選擇未來月份。")
            return

        self.run_btn.configure(state="disabled", text="⏳ 正在下載與計算中...")
        self.status_label.configure(text="正在連線至 Google Sheets，這可能需要幾秒鐘...", text_color="yellow")
        self.update()

        start_time = time.time()
        success, result = process_qa_data(year, month)
        
        if success:
            data = result
            # 更新指標卡片
            self.lbl_period.configure(
                text=f"資料來源: {' + '.join(data['source_sheets'])}"
            )
            self.lbl_total.configure(text=f"累計發測項目: {data['total_items']} 個")
            self.lbl_workdays.configure(text=f"歷史總工作日: {data['workdays']} 天 (已扣除週六日)")
            
            # 🌟 更新重點計算結果文字
            self.lbl_avg.configure(text=f"單一日進測平均數量: {data['avg_per_day']:.2f} 個/日")

            # 更新人員負責單數
            self.textbox.configure(state="normal")
            self.textbox.delete("0.0", "end")
            self.textbox.insert("end", f"{'人員':<16} | {'手動單數':>8} | {'自動化單數':>10} | {'合計':>6}\n")
            self.textbox.insert("end", "-"*58 + "\n")

            for _, row in data['person_stats'].iterrows():
                self.textbox.insert(
                    "end",
                    f"{row['人員']:<16} | {int(row['手動單數']):>8} | "
                    f"{int(row['自動化單數']):>10} | {int(row['合計']):>6}\n"
                )

            self.textbox.insert("end", "\n🏆 發測高峰日 TOP 6\n")
            self.textbox.insert("end", f"{'排名':<6} | {'發測日期':<12} | {'當日件數'}\n")
            self.textbox.insert("end", "-"*40 + "\n")

            rank = 1
            for _, row in data['top_6'].iterrows():
                self.textbox.insert("end", f"NO.{rank:<4} | {row['日期字串']:<12} | {int(row['項目總數'])}\n")
                rank += 1
            self.textbox.configure(state="disabled")

            end_time = time.time()
            self.status_label.configure(
                text=f"✅ 分析完成！已讀取 {' + '.join(data['source_sheets'])}，"
                     f"耗時: {end_time - start_time:.2f} 秒",
                text_color="#2ecc71"
            )
        else:
            self.status_label.configure(text="❌ 分析失敗！", text_color="#e74c3c")
            messagebox.showerror("錯誤", result)

        self.run_btn.configure(state="normal", text="🚀 重新執行分析")

if __name__ == "__main__":
    app = QAAnalyzerApp()
    app.mainloop()

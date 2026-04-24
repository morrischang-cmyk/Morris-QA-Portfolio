import pandas as pd
import time
import re
import unicodedata
from datetime import date
import numpy as np
import customtkinter as ctk
from tkinter import messagebox

# ---------------------------------------------------------
# 1. 核心清洗與運算邏輯 (嚴格日曆工作日版)
# 測試
# ---------------------------------------------------------
def super_clean_date(text):
    if pd.isna(text): return None
    text = unicodedata.normalize('NFKC', str(text))
    match = re.search(r'(\d{4})\D+(\d{1,2})\D+(\d{1,2})', text)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return None

def process_qa_data():
    sheet_id = "1L7pOB-dSV26IE6VJKyfm-IZd1a3bxvri7FChC7xtBSw"
    excel_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    target_sheets = ["202511(done)", "202512(done)", "202601(done)", "202602(done)", "202603(done)", "202604(done)"]

    try:
        # 讀取資料
        all_sheets_dict = pd.read_excel(excel_url, sheet_name=target_sheets, engine='openpyxl')
        df_list = [sheet_df for sheet_df in all_sheets_dict.values()]
        df = pd.concat(df_list, ignore_index=True)
        
        date_col = '發測日期'
        if date_col not in df.columns:
            return False, f"找不到欄位 '{date_col}'，請確認表單格式。"

        # 清洗資料
        clean_dates = df[date_col].apply(super_clean_date)
        converted_dates = pd.to_datetime(clean_dates, errors='coerce')
        df = df[converted_dates.notna()].copy()
        df[date_col] = converted_dates[converted_dates.notna()]
        
        # 產能計算 (扣除六日)
        total_items = len(df)
        start_date = date(2025, 11, 1)
        end_date = date.today()
        workdays_count = np.busday_count(start_date, end_date + pd.Timedelta(days=1))
        avg_per_day = total_items / workdays_count if workdays_count > 0 else 0
        
        # 高峰日排行榜
        df['日期字串'] = df[date_col].dt.strftime('%Y-%m-%d')
        daily_stats = df.groupby('日期字串').size().reset_index(name='項目總數')
        top_6 = daily_stats.sort_values(by='項目總數', ascending=False).head(6)

        return True, {
            "total_items": total_items,
            "workdays": workdays_count,
            "avg_per_day": avg_per_day,
            "start_date": start_date,
            "end_date": end_date,
            "top_6": top_6
        }

    except Exception as e:
        return False, f"發生錯誤：{str(e)}"

# ---------------------------------------------------------
# 2. GUI 視窗介面設計
# ---------------------------------------------------------
class QAAnalyzerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # 設定視窗基本屬性
        self.title("QA 產能分析系統 v1.0")
        self.geometry("600x700")
        ctk.set_appearance_mode("dark")  # 深色模式
        ctk.set_default_color_theme("blue")

        # --- UI 元件佈局 ---
        # 標題
        self.title_label = ctk.CTkLabel(self, text="📊 QA 歷史產能分析", font=ctk.CTkFont(size=24, weight="bold"))
        self.title_label.pack(pady=(20, 10))

        # 執行按鈕
        self.run_btn = ctk.CTkButton(self, text="🚀 開始從雲端抓取與分析", font=ctk.CTkFont(size=16), command=self.run_analysis)
        self.run_btn.pack(pady=10)

        # 狀態提示
        self.status_label = ctk.CTkLabel(self, text="準備就緒，請點擊上方按鈕開始。", text_color="gray")
        self.status_label.pack(pady=(0, 10))

        # 產能指標卡片 (Frame)
        self.stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.stats_frame.pack(pady=10, padx=20, fill="x")

        self.lbl_period = ctk.CTkLabel(self.stats_frame, text="計算區間: --", font=ctk.CTkFont(size=14))
        self.lbl_period.pack(anchor="w", pady=2)
        self.lbl_total = ctk.CTkLabel(self.stats_frame, text="累計發測項目: --", font=ctk.CTkFont(size=14))
        self.lbl_total.pack(anchor="w", pady=2)
        self.lbl_workdays = ctk.CTkLabel(self.stats_frame, text="歷史總工作日: -- (扣除六日)", font=ctk.CTkFont(size=14))
        self.lbl_workdays.pack(anchor="w", pady=2)
        
        # 🌟 已經替換為精準的規格書名詞
        self.lbl_avg = ctk.CTkLabel(self.stats_frame, text="單一日進測平均數量: --", font=ctk.CTkFont(size=20, weight="bold"), text_color="#2ecc71")
        self.lbl_avg.pack(anchor="w", pady=(10, 0))

        # 排行榜文字區 (Textbox)
        self.ranking_label = ctk.CTkLabel(self, text="🏆 歷史前 6 大發測高峰日", font=ctk.CTkFont(size=16, weight="bold"))
        self.ranking_label.pack(pady=(20, 5))
        
        self.textbox = ctk.CTkTextbox(self, width=500, height=200, font=ctk.CTkFont(family="Consolas", size=14))
        self.textbox.pack(pady=5)
        self.textbox.insert("0.0", "等待分析結果...\n")
        self.textbox.configure(state="disabled")

    # 按下按鈕後執行的動作
    def run_analysis(self):
        self.run_btn.configure(state="disabled", text="⏳ 正在下載與計算中...")
        self.status_label.configure(text="正在連線至 Google Sheets，這可能需要幾秒鐘...", text_color="yellow")
        self.update()

        start_time = time.time()
        success, result = process_qa_data()
        
        if success:
            data = result
            # 更新指標卡片
            self.lbl_period.configure(text=f"計算區間: {data['start_date']} ~ {data['end_date']}")
            self.lbl_total.configure(text=f"累計發測項目: {data['total_items']} 個")
            self.lbl_workdays.configure(text=f"歷史總工作日: {data['workdays']} 天 (已扣除週六日)")
            
            # 🌟 更新重點計算結果文字
            self.lbl_avg.configure(text=f"單一日進測平均數量: {data['avg_per_day']:.2f} 個/日")

            # 更新排行榜
            self.textbox.configure(state="normal")
            self.textbox.delete("0.0", "end")
            self.textbox.insert("end", f"{'排名':<6} | {'發測日期':<12} | {'當日件數'}\n")
            self.textbox.insert("end", "-"*40 + "\n")
            
            rank = 1
            for _, row in data['top_6'].iterrows():
                self.textbox.insert("end", f"NO.{rank:<4} | {row['日期字串']:<12} | {int(row['項目總數'])}\n")
                rank += 1
            self.textbox.configure(state="disabled")

            end_time = time.time()
            self.status_label.configure(text=f"✅ 分析完成！耗時: {end_time - start_time:.2f} 秒", text_color="#2ecc71")
        else:
            self.status_label.configure(text="❌ 分析失敗！", text_color="#e74c3c")
            messagebox.showerror("錯誤", result)

        self.run_btn.configure(state="normal", text="🚀 重新執行分析")

if __name__ == "__main__":
    app = QAAnalyzerApp()
    app.mainloop()
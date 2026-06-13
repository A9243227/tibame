import fitz  # PyMuPDF
import re
import csv
import os

def find_best_snippet(full_text: str) -> str:
    """
    第一階段：使用「積分制滑動視窗」尋找含金量最高的數據段落
    """
    # 1. 斷句設定：用常見句點切分句子
    sentences = re.split(r'(?<=[。！？])', full_text)
    
    # 2. 正向權重：精準的單位分數給最高
    positive_keywords = {
        "kWh": 5, "轉供": 4, "憑證": 4, "MW": 3, "kW": 3, 
        "度": 2, "張": 2, "實際": 2, "綠電": 1, "再生能源": 1
    }
    
    # 3. 負向權重：重罰未來承諾與無關的環保口號
    negative_keywords = {
        "承諾": -3, "願景": -4, "目標": -3, "2030": -5, "2050": -5, 
        "巴黎協定": -5, "溫室氣體": -2, "碳中和": -2
    }
    
    best_score = -999
    best_snippet = "未找到相關段落"
    window_size = 4 # 每次看 4 個句子
    
    for i in range(len(sentences)):
        window_text = "".join(sentences[i:i+window_size])
        score = 0
        
        # 結算基本單字權重
        for kw, weight in positive_keywords.items():
            if kw in window_text: score += weight
            
        for kw, weight in negative_keywords.items():
            if kw in window_text: score += weight
            
        # 4. 【殺手鐧特徵】：尋找「數字+單位」的緊密結合
        # 抓取如: 113萬920kWh, 107張, 98.7 MW
        if re.search(r'\d+[\d,\.]*\s*(?:萬|千)?\s*(?:kWh|度|張|MW|kW)', window_text, re.IGNORECASE):
            score += 15  # 給予壓倒性的超高分
            
        # 5. 防呆機制：過濾掉氣溫的「攝氏X度」
        if "攝氏" in window_text and "度" in window_text:
            score -= 10
            
        # 紀錄最高分段落
        if score > best_score:
            best_score = score
            best_snippet = window_text
            
    return best_snippet

def extract_esg_data(pdf_path: str, filename: str) -> dict:
    """
    第二階段：解析 PDF、調用探測器，並動態拆解出欄位
    """
    doc = fitz.open(pdf_path)
    full_text = "".join([page.get_text() for page in doc]).replace("\n", "")
    
    # 自動檔名拆解 (解析公司代號與年份)
    parts = filename.replace(".pdf", "").split("_")
    year = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 2024
    company_id = parts[1] if len(parts) > 1 else "Unknown"

    # 取得最高分的黃金段落
    snippet = find_best_snippet(full_text)
            
    # 建立基本資料 Dictionary
    row_data = {
        "company_name": company_id,
        "fiscal_year": year,
        "original_text_snippet": snippet
    }

    # 完全動態拆解欄位 (零寫死)
    if snippet != "未找到相關段落":
        delimiters = r'[、，。及；\s]+'
        chunks = re.split(delimiters, snippet)
        
        for chunk in chunks:
            # 匹配: 欄位名稱(非數字) + 數值(數字、逗號、小數點) + 單位(其餘字元)
            match = re.search(r'^([^\d]+)([\d,\.]+)\s*(.*)$', chunk)
            
            if match:
                raw_field_name = match.group(1).strip()
                value_str = match.group(2).strip()
                unit_str = match.group(3).strip()
                
                # 基礎防呆：排除雜訊或打高空的詞彙變成欄位
                noise_words = ["策略", "營運", "創造", "驗證", "ISO", "成果與規劃", "承諾", "願景", "目標"]
                if len(raw_field_name) < 2 or any(noise in raw_field_name for noise in noise_words):
                    continue
                
                # 將單位合併到欄位名稱中
                field_key = raw_field_name
                if unit_str:
                    field_key = f"{raw_field_name}({unit_str})"
                
                # 清理數值中的千分位逗號
                clean_value = value_str.replace(",", "").rstrip(".")
                
                # 動態寫入 Dictionary，直接變成新欄位
                row_data[field_key] = clean_value

    return row_data

def run_batch_processing(input_folder: str, output_csv: str):
    """
    第三階段：批次處理與 CSV 匯出
    """
    results = []
    all_dynamic_fields = set()
    
    print(f"\n🚀 程式開始啟動，準備掃描資料夾: {os.path.abspath(input_folder)}")
    
    if not os.path.exists(input_folder):
        print(f"❌ 錯誤: 找不到資料夾 '{input_folder}'，請確認資料夾是否存在！")
        return

    pdf_files = [f for f in os.listdir(input_folder) if f.lower().endswith(".pdf")]
    
    if not pdf_files:
        print(f"⚠️ 警告: 在 '{input_folder}' 中找不到任何 PDF 檔案。")
        return
    
    for filename in pdf_files:
        path = os.path.join(input_folder, filename)
        print(f"📄 正在處理: {filename}...")
        
        data_dict = extract_esg_data(path, filename)
        results.append(data_dict)
        
        all_dynamic_fields.update(data_dict.keys())

    # 規劃最終的 CSV 欄位順序
    base_columns = ["company_name", "fiscal_year", "original_text_snippet"]
    dynamic_columns = sorted(list(all_dynamic_fields - set(base_columns)))
    final_headers = base_columns + dynamic_columns

    if results:
        with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
            dict_writer = csv.DictWriter(f, fieldnames=final_headers)
            dict_writer.writeheader()
            dict_writer.writerows(results)
        print(f"✅ 成功！探測器已掃描完畢，資料表已匯出至: {os.path.abspath(output_csv)}\n")

if __name__ == "__main__":
    run_batch_processing(input_folder="./data", output_csv="esg_data_summary.csv")
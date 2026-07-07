import os
import csv
import logging
import re
import math
from typing import List, Dict, Any
from playwright.sync_api import sync_playwright, APIRequestContext
from google.cloud import storage

# 設定基本的 Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TRECCrawler:
    def __init__(self, start_year: int, end_year: int):
        self.start_year = start_year
        self.end_year = end_year
        self.playwright = sync_playwright().start()
        
        # 由於我們採用 Strategy B (純 API 驅動)，我們不需要開啟 Browser
        # 只需要一個 APIRequestContext
        self.request_context: APIRequestContext = self.playwright.request.new_context(
            base_url="https://www.trec.org.tw",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        )
        self.csrf_token = ""

    def _init_session(self):
        """訪問首頁獲取 Cookie 與 CSRF Token"""
        logging.info("初始化 Session，獲取 CSRF Token...")
        response = self.request_context.get("/certification")
        html_content = response.text()
        
        # 使用正則表達式擷取 <meta name="csrf-token" content="...">
        match = re.search(r'<meta name="csrf-token" content="([^"]+)">', html_content)
        if match:
            self.csrf_token = match.group(1)
            logging.info(f"成功取得 CSRF Token: {self.csrf_token[:10]}...")
        else:
            logging.error("無法取得 CSRF Token，API 請求可能會失敗。")

    def _fetch_modal_detail(self, item_id: str, year: str, date: str) -> Dict[str, str]:
        """呼叫 /certification/detail 取得彈出視窗的詳細內容並解析"""
        response = self.request_context.post(
            "/certification/detail",
            headers={
                "X-CSRF-TOKEN": self.csrf_token,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://www.trec.org.tw/certification?year={year}"
            },
            form={
                "id": item_id,
                "year": year,
                "date": date
            }
        )
        
        if not response.ok:
            logging.warning(f"取得詳細資料失敗: {item_id}")
            return {}

        modal_html = response.text()
        
        # 利用正則表達式精準擷取 <label> 與其下方的 <div> 內容
        fields = re.findall(r'<label>(.*?)</label>\s*<div>(.*?)</div>', modal_html, re.DOTALL | re.IGNORECASE)
        
        data = {}
        for key_html, val_html in fields:
            # 清除內部可能包含的 <br/> 等 HTML 標籤
            key = re.sub(r'<[^>]+>', '', key_html).strip()
            val = re.sub(r'<[^>]+>', '', val_html).strip()
            
            # 轉換 &nbsp; 等
            key = key.replace('&nbsp;', ' ')
            val = val.replace('&nbsp;', ' ')
            
            if key:
                data[key] = val
            
        return data

    def process_year(self, year: int) -> List[Dict[str, str]]:
        all_year_data = []
        
        start = 0
        length = 100  # 每次抓 100 筆以減少 Request 數量
        draw = 1
        
        logging.info(f"開始抓取年份 {year} 的資料...")
        
        while True:
            # 建構 DataTables POST Payload
            payload = {
                "draw": str(draw),
                "start": str(start),
                "length": str(length),
                "year": str(year),
                # 其餘可省略或根據需要補齊，通常後端只要有 start, length, draw 即可運作
                # 如果報錯，請將瀏覽器中完整的 columns[...] 參數也加進來
            }
            
            response = self.request_context.post(
                "/certification/data",
                headers={
                    "X-CSRF-TOKEN": self.csrf_token,
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"https://www.trec.org.tw/certification?year={year}"
                },
                form=payload
            )
            
            if not response.ok:
                logging.error(f"API 請求失敗: 狀態碼 {response.status}")
                break
                
            json_data = response.json()
            records_total = json_data.get("recordsFiltered", 0)
            data_list = json_data.get("data", [])
            
            if not data_list:
                break
                
            logging.info(f"年份 {year} - 正在處理第 {start+1} 到 {start+len(data_list)} 筆 (總共 {records_total} 筆)")
            
            # 處理這批資料
            for row in data_list:
                detail_html = row.get("detail", "")
                
                # 從 html string 中萃取 data-case, data-year, data-date
                case_match = re.search(r'data-case="([^"]+)"', detail_html)
                year_match = re.search(r'data-year="([^"]+)"', detail_html)
                date_match = re.search(r'data-date="([^"]+)"', detail_html)
                
                if case_match and year_match and date_match:
                    item_id = case_match.group(1)
                    item_year = year_match.group(1)
                    item_date = date_match.group(1)
                    
                    # 抓取詳細資料
                    detail_data = self._fetch_modal_detail(item_id, item_year, item_date)
                    
                    # 可以將列表中原本的資料與詳細資料合併
                    # row_clean = {k: v for k, v in row.items() if k != 'detail' and not isinstance(v, dict)}
                    # detail_data.update(row_clean)
                    
                    all_year_data.append(detail_data)
                else:
                    # 無法萃取 id，跳過
                    pass
                    
            start += length
            draw += 1
            
            if start >= records_total:
                break
                
        return all_year_data

    def save_to_csv(self, data: List[Dict[str, str]], year: int):
        if not data:
            logging.warning(f"年份 {year} 沒有擷取到任何資料，跳過存檔。")
            return
            
        # 依照使用者指定的順序排列欄位
        desired_order = [
            "單位名稱",
            "發電設備",
            "能源類型",
            "發電設備地址",
            "裝置總容量",
            "發電設備共用單位",
            "證書編號",
            "T-REC 最後憑證發放日期",
            "發電區間",
            "再生能源設備查核報告",
            "再生能源發電量查證報告",
            "已移轉量",
            "剩餘量"
        ]
        
        # 收集資料中所有出現過的 key
        all_keys = set()
        for d in data:
            all_keys.update(d.keys())
            
        # 確保指定的順序優先，其餘沒有在 desired_order 裡面的放後面
        fieldnames = [col for col in desired_order if col in all_keys]
        for col in all_keys:
            if col not in fieldnames:
                fieldnames.append(col)
                
        filename = f"trec_issued_certificate_{year}_raw.csv"
        try:
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)
            logging.info(f"成功儲存 {len(data)} 筆資料至 {filename}")
            
            # 上傳至 GCS
            self._upload_to_gcs(filename, year)
            
            # 刪除本地檔案以節省 Cloud Run 記憶體 (Cloud Run 檔案系統佔用記憶體)
            if os.path.exists(filename):
                os.remove(filename)
                logging.info(f"已刪除本地暫存檔案: {filename}")
                
        except Exception as e:
            logging.error(f"儲存或上傳 CSV 發生錯誤: {e}")

    def _upload_to_gcs(self, local_filename: str, year: int):
        bucket_name = "tibame-bronze"
        destination_blob_name = f"new_raw_data/certified_issued_data/{local_filename}"
        
        try:
            storage_client = storage.Client()
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(destination_blob_name)
            
            blob.upload_from_filename(local_filename)
            logging.info(f"已成功上傳 {local_filename} 至 GCS: gs://{bucket_name}/{destination_blob_name}")
        except Exception as e:
            logging.error(f"上傳檔案至 GCS 時發生錯誤: {e}")

    def close(self):
        logging.info("關閉 Playwright 資源...")
        try:
            self.request_context.dispose()
            self.playwright.stop()
        except Exception as e:
            logging.error(f"關閉資源時發生錯誤: {e}")

def main():
    # 可以在此處直接修改你要爬取的起始與結束年份
    start_year = 2026
    end_year = 2020

    crawler = TRECCrawler(start_year=start_year, end_year=end_year) 
    crawler._init_session()
    
    try:
        step = -1 if crawler.start_year >= crawler.end_year else 1
        for year in range(crawler.start_year, crawler.end_year + step, step):
            logging.info(f"========== 開始爬取年份 {year} ==========")
            data = crawler.process_year(year)
            crawler.save_to_csv(data, year)
            logging.info(f"========== 年份 {year} 爬取完畢 ==========")
    except Exception as e:
        logging.error(f"主迴圈發生未預期的嚴重錯誤: {e}")
    finally:
        crawler.close()

if __name__ == "__main__":
    main()

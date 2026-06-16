import csv
import logging
import time
from typing import List, Dict, Any
from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError as PlaywrightTimeoutError

# 設定基本的 Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TRECCrawler:
    def __init__(self, start_year: int, end_year: int, headless: bool = True):
        self.start_year = start_year
        self.end_year = end_year
        self.playwright = sync_playwright().start()
        self.browser: Browser = self.playwright.chromium.launch(headless=headless)
        self.context = self.browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
        )
        self.page: Page = self.context.new_page()
        self.base_url = "https://www.trec.org.tw/certification?year={year}"

    def navigate_to_year(self, year: int):
        url = self.base_url.format(year=year)
        logging.info(f"導覽至 {url}")
        self.page.goto(url, wait_until='networkidle')
        # 等待主要的表格出現
        try:
            self.page.wait_for_selector('tbody', timeout=15000)
            logging.info("表格已載入")
        except PlaywrightTimeoutError:
            logging.warning(f"年份 {year} 載入表格超時或無資料。")

    def _extract_modal_data(self) -> Dict[str, str]:
        """從已經打開的 modal 中萃取 key-value 資料。"""
        # 等待 Modal 出現並可見
        self.page.wait_for_selector('.ui.modal', state='visible', timeout=10000)
        
        # 確保資料已渲染 (給予微小緩衝時間)
        self.page.wait_for_timeout(500)
        
        # 抓取 Modal 內部的純文字。這裡為了泛用，直接抓取 .content 內的 text 
        # (根據常見的 Semantic UI 結構) 
        # 也可以直接抓取 '.ui.modal' 的 inner_text
        text_content = self.page.locator('.ui.modal .content').inner_text()
        
        data = {}
        # 進行簡易的資料對齊：奇數行為 Key，偶數行為 Value
        lines = [line.strip() for line in text_content.split('\n') if line.strip()]
        for i in range(0, len(lines) - 1, 2):
            key = lines[i]
            value = lines[i+1]
            data[key] = value
            
        # 點擊關閉按鈕
        close_btn = self.page.locator('div.ui.cancel.red.button')
        close_btn.click()
        
        # 等待 Modal 完全隱藏，避免點擊下個按鈕時發生攔截 (Interception)
        self.page.wait_for_selector('.ui.modal', state='hidden', timeout=10000)
        self.page.wait_for_timeout(300) # 給個小緩衝
            
        return data

    def extract_page_data(self) -> List[Dict[str, str]]:
        page_data = []
        
        # 限定抓取 tbody 內的 button
        buttons_locator = self.page.locator('tbody tr td button')
        count = buttons_locator.count()
        logging.info(f"當前頁面找到 {count} 個按鈕。")
        
        for i in range(count):
            try:
                btn = buttons_locator.nth(i)
                btn.scroll_into_view_if_needed()
                btn.click()
                
                # 萃取 Modal 資料
                row_data = self._extract_modal_data()
                page_data.append(row_data)
                
            except Exception as e:
                logging.error(f"點擊或解析第 {i} 個按鈕時發生錯誤: {e}")
                # 例外處理：嘗試強制關閉 Modal 防止卡死後續流程
                try:
                    close_btn = self.page.locator('div.ui.cancel.red.button')
                    if close_btn.is_visible(timeout=2000):
                        close_btn.click()
                        self.page.wait_for_selector('.ui.modal', state='hidden', timeout=5000)
                except:
                    pass

        return page_data

    def process_year(self, year: int) -> List[Dict[str, str]]:
        self.navigate_to_year(year)
        all_year_data = []
        
        page_num = 1
        while True:
            logging.info(f"正在擷取 年份 {year} - 第 {page_num} 頁...")
            data = self.extract_page_data()
            all_year_data.extend(data)
            
            # 檢查下一頁按鈕
            next_btn = self.page.locator('button.next.item.ui.button')
            
            # 如果按鈕不存在
            if next_btn.count() == 0:
                logging.info("找不到下一頁按鈕，該年份擷取結束。")
                break
                
            # 如果按鈕存在但被 disabled
            if next_btn.first.is_disabled():
                logging.info("已達最後一頁 (下一頁按鈕已被禁用)。")
                break
                
            # 點擊下一頁
            try:
                next_btn.first.scroll_into_view_if_needed()
                next_btn.first.click()
                # 等待 tbody 重新載入或網路閒置
                self.page.wait_for_timeout(2000)
                page_num += 1
            except Exception as e:
                logging.error(f"點擊下一頁時發生錯誤: {e}")
                break
                
        return all_year_data

    def save_to_csv(self, data: List[Dict[str, str]], year: int):
        if not data:
            logging.warning(f"年份 {year} 沒有擷取到任何資料，跳過存檔。")
            return
            
        # 收集所有不重複的欄位名稱
        keys = set()
        for d in data:
            keys.update(d.keys())
        fieldnames = list(keys)
            
        filename = f"trec_data_{year}.csv"
        try:
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)
            logging.info(f"成功儲存 {len(data)} 筆資料至 {filename}")
        except Exception as e:
            logging.error(f"儲存 CSV 發生錯誤: {e}")

    def close(self):
        logging.info("關閉瀏覽器與 Playwright 資源...")
        try:
            self.context.close()
            self.browser.close()
            self.playwright.stop()
        except Exception as e:
            logging.error(f"關閉資源時發生錯誤: {e}")

def main():
    # 可以在此處直接修改你要爬取的起始與結束年份
    start_year = 2026
    end_year = 2020

    # 實際部署於 Cloud Run 請設為 True，若在本地除錯可改為 False 觀看畫面
    crawler = TRECCrawler(start_year=start_year, end_year=end_year, headless=False) 
    
    try:
        # 根據設定的年份動態決定遞減或遞增的 range
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

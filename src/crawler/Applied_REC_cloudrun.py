import csv
import time
from datetime import datetime
from typing import List, Dict, Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# 匯入 GCS
from google.cloud import storage

def log_print(level: str, message: str):
    """自訂 Log 函數，確保 flush=True 讓 Cloud Run 即時捕捉 Log"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
    print(f"{now} - {level} - {message}", flush=True)

class TrecCrawler:
    def __init__(self, start_year: int, end_year: int):
        self.start_year = start_year
        self.end_year = end_year
        self.base_url = "https://www.trec.org.tw/certification?year={}"
        self.driver = None
        self.bucket_name = "tibame-bronze"
        self.gcs_prefix = "raw_data/"

    def start_browser(self):
        """初始化並啟動 Selenium Chrome Browser"""
        log_print("INFO", "啟動 Selenium 瀏覽器...")
        options = Options()
        options.add_argument("--headless=new") # 使用新的 Headless 模式
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage") # 避免 Docker 容器記憶體不足
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        # 模擬一般使用者的 User-Agent
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # Selenium 4 自動使用 Selenium Manager 下載與管理 ChromeDriver
        self.driver = webdriver.Chrome(options=options)
        self.driver.set_page_load_timeout(30) # 頁面載入 Timeout 設定

    def close_browser(self):
        """安全關閉瀏覽器資源"""
        log_print("INFO", "關閉瀏覽器...")
        if self.driver:
            self.driver.quit()

    def run(self):
        """爬蟲主流程控制"""
        try:
            self.start_browser()
            
            # 從 start_year 倒序跑到 end_year
            step = -1 if self.start_year >= self.end_year else 1
            end_bound = self.end_year - 1 if step == -1 else self.end_year + 1
            
            for year in range(self.start_year, end_bound, step):
                log_print("INFO", f"開始爬取年份: {year}")
                data = self._scrape_year(year)
                if data:
                    filename = self._save_to_csv(year, data)
                    if filename:
                        self._upload_to_gcs(filename, year)
                else:
                    log_print("WARNING", f"年份 {year} 沒有抓到任何資料。")
                    
        except Exception as e:
            log_print("ERROR", f"執行過程中發生未預期的錯誤: {e}")
        finally:
            self.close_browser()

    def _scrape_year(self, year: int) -> List[Dict[str, Any]]:
        """處理單一年份的導航與分頁邏輯"""
        year_data = []
        url = self.base_url.format(year)
        log_print("INFO", f"前往網址: {url}")
        
        try:
            self.driver.get(url)
            # 等待表格目標按鈕出現在 DOM 中，確保頁面基本載入完成
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr button"))
            )
        except TimeoutException:
            log_print("ERROR", f"年份 {year} 頁面載入失敗或無資料 (Timeout)")
            return year_data
        except Exception as e:
            log_print("ERROR", f"年份 {year} 頁面載入發生錯誤: {e}")
            return year_data
            
        page_num = 1
        while True:
            log_print("INFO", f"正在擷取年份 {year} 的第 {page_num} 頁...")
            
            # 抓取當前頁面的所有資料
            page_data = self._scrape_page_data()
            year_data.extend(page_data)
            
            # 檢查並處理「下一頁」邏輯
            try:
                # 快速確認下一頁按鈕是否存在
                next_btn = WebDriverWait(self.driver, 3).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "button.next.item.ui.button"))
                )
                
                # 確認按鈕是否有 disabled 屬性
                is_disabled = next_btn.get_attribute("disabled") is not None
                if is_disabled:
                    log_print("INFO", f"年份 {year} 已經到達最後一頁 (下一頁按鈕被 disabled)。")
                    break
                
                # 點擊下一頁 (使用 JS 點擊避免被其他元素遮擋，這是 Selenium 常見做法)
                self.driver.execute_script("arguments[0].click();", next_btn)
                
                # 為了避免跟舊資料混淆，等待一段小過渡時間，並等待按鈕再次載入
                time.sleep(1.5)
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr button"))
                )
                page_num += 1
                
            except TimeoutException:
                log_print("INFO", f"年份 {year} 找不到下一頁按鈕，結束擷取。")
                break
            except Exception as e:
                log_print("INFO", f"年份 {year} 沒有更多分頁或無法點擊下一頁: {e}")
                break
                
        return year_data

    def _scrape_page_data(self) -> List[Dict[str, Any]]:
        """處理單一頁面上的資料擷取 (點擊詳情、爬取彈出視窗、關閉彈出視窗)"""
        page_data = []
        
        try:
            # 取得當前頁面列表中的所有按鈕數量
            buttons = self.driver.find_elements(By.CSS_SELECTOR, "tbody tr button")
            count = len(buttons)
            
            for i in range(count):
                try:
                    # 每次都要重新 locate，避免 DOM 變化導致 stale element
                    btn = self.driver.find_elements(By.CSS_SELECTOR, "tbody tr button")[i]
                    # 使用 JS 點擊比較不會有 "element not interactable" 的問題
                    self.driver.execute_script("arguments[0].click();", btn)
                    
                    # 等待 Modal 表單出現並呈現可見狀態
                    modal_selector = "div.scrolling.content div.ui.form"
                    modal = WebDriverWait(self.driver, 8).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, modal_selector))
                    )
                    
                    # 擷取資料
                    record = {}
                    # 從當前可見的 modal 中尋找欄位，避免抓到隱藏的舊 Modal
                    fields = modal.find_elements(By.CSS_SELECTOR, "div.field")
                    
                    for j, field in enumerate(fields):
                        # 擷取 field 內的文字 (可能包含 Label 加上 Value，以換行分隔)
                        field_text = field.text
                        if field_text:
                            # 整理字串：用換行切割，並去除多餘空白
                            parts = [p.strip() for p in field_text.split('\n') if p.strip()]
                            if len(parts) >= 2:
                                key = parts[0]
                                value = " ".join(parts[1:])
                                record[key] = value
                            elif len(parts) == 1:
                                record[f"未知欄位_{j}"] = parts[0]
                                
                    if record:
                        page_data.append(record)
                    
                    # 點擊關閉彈出視窗 (尋找可見的關閉按鈕)
                    close_btns = self.driver.find_elements(By.CSS_SELECTOR, "div.ui.cancel.red.button")
                    for cb in close_btns:
                        if cb.is_displayed():
                            self.driver.execute_script("arguments[0].click();", cb)
                            break
                            
                    # 等待彈出視窗完全消失，避免連續點擊過快導致網頁報錯
                    WebDriverWait(self.driver, 5).until(
                        EC.invisibility_of_element_located((By.CSS_SELECTOR, modal_selector))
                    )
                    # 多等一小段時間確保動畫結束，這在 Selenium 很重要
                    time.sleep(0.5)
                    
                except Exception as e:
                    log_print("WARNING", f"擷取第 {i+1} 筆記錄時發生錯誤: {e}")
                    # 萬一彈出視窗卡住，嘗試強制關閉
                    try:
                        close_btns = self.driver.find_elements(By.CSS_SELECTOR, "div.ui.cancel.red.button")
                        if close_btns:
                            self.driver.execute_script("arguments[0].click();", close_btns[0])
                    except:
                        pass
                    continue
                    
        except Exception as e:
            log_print("ERROR", f"擷取單頁資料時發生錯誤: {e}")
            
        return page_data

    def _save_to_csv(self, year: int, data: List[Dict[str, Any]]) -> str:
        """將擷取到的資料儲存為 CSV 檔案，回傳檔案名稱"""
        if not data:
            return ""
            
        filename = f"trec_data_{year}.csv"
        log_print("INFO", f"準備儲存資料至 {filename} (共 {len(data)} 筆)")
        
        # 取得所有欄位名稱作為 CSV 的 Header
        fieldnames = list(data[0].keys())
        
        try:
            with open(filename, mode='w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)
            log_print("INFO", f"檔案儲存成功: {filename}")
            return filename
        except Exception as e:
            log_print("ERROR", f"儲存 CSV 失敗 ({filename}): {e}")
            return ""

    def _upload_to_gcs(self, source_file_name: str, year: int):
        """將產出的 CSV 上傳至 GCS"""
        destination_blob_name = f"{self.gcs_prefix}{source_file_name}"
        log_print("INFO", f"準備上傳 {source_file_name} 到 GCS 儲存桶 {self.bucket_name} 的 {destination_blob_name} ...")
        try:
            storage_client = storage.Client()
            bucket = storage_client.bucket(self.bucket_name)
            blob = bucket.blob(destination_blob_name)
            
            blob.upload_from_filename(source_file_name)
            log_print("INFO", f"上傳 GCS 成功！GCS 路徑：gs://{self.bucket_name}/{destination_blob_name}")
        except Exception as e:
            log_print("ERROR", f"上傳至 GCS 失敗: {e}")

if __name__ == "__main__":
    # 正式爬取範圍：2026 到 2020
    crawler = TrecCrawler(start_year=2026, end_year=2020)
    crawler.run()

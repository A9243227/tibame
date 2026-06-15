import os
import re
import time
import pandas as pd
import glob
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from google.cloud import storage

class TRECCrawler:
    """T-REC 再生能源憑證爬蟲 - 負責所有網頁操作邏輯"""
    
    def __init__(self, headless=False):
        self.url = "https://www.trec.org.tw/certification"
        self.fieldnames = [
            "出售單位", "發電設備", "能源類型", "憑證發放年份", "已移轉量(MWh)", "剩餘量(MWh)",
            "發電設備地址", "裝置總容量", "發電設備共用單位", "證書編號", "T-REC最後憑證發放日期", 
            "發電區間", "再生能源設備查核報告", "再生能源發電量查證報告", "詳情_已移轉量", "詳情_剩餘量"
        ]
        self._init_driver(headless)

    def _init_driver(self, headless):
        print("啟動瀏覽器...", flush=True)
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")              
            chrome_options.add_argument("--no-sandbox")            
            chrome_options.add_argument("--disable-dev-shm-usage") 
        chrome_options.add_argument("--window-size=1920,1080") 

        self.driver = webdriver.Chrome(options=chrome_options)
        self.wait = WebDriverWait(self.driver, 15)
        self.driver.get(self.url)

    def wait_table_loaded(self):
        """動態等待表格載入完成，確認沒有載入中的提示"""
        self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr")))
        
        def table_ready(d):
            rows = d.find_elements(By.CSS_SELECTOR, "tbody tr")
            if not rows: return False
            for row in rows:
                text = row.text
                if "載入中" in text or "處理中" in text:
                    return False
            # 確認有資料列或是顯示「沒有資料」
            if len(rows[0].find_elements(By.CSS_SELECTOR, "td")) >= 5 or "沒有資料" in rows[0].text:
                return True
            return False

        self.wait.until(table_ready)

    def select_year(self, year):
        """切換至指定年份的分頁"""
        print(f"\n=====\n正在切換至年份： {year}\n=====", flush=True)
        self.wait_table_loaded()
        try:
            xpath = f"//span[contains(text(), '{year}') or text()='{year}']"
            year_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", year_btn)
            year_btn.click()
        except TimeoutException:
            # 備用方案
            year_elements = self.driver.find_elements(By.XPATH, f"//*[text()='{year}']")
            if year_elements:
                self.driver.execute_script("arguments[0].click();", year_elements[0])
        
        # 確保「網頁響應 (表格重載完畢)」之後，才開始硬等待緩衝
        self.wait_table_loaded()
        time.sleep(5)  # 切換年份資料量大，硬等待 5 秒作為緩衝

    def get_total_pages(self):
        """取得當前年份的總頁數"""
        try:
            info_elements = self.wait.until(EC.presence_of_all_elements_located((By.XPATH, "//*[contains(text(), '共') and contains(text(), '筆')]")))
            if info_elements:
                info_text = info_elements[0].text.strip()
                match = re.search(r"共\s*([\d,]+)\s*筆", info_text)
                if match:
                    total_records = int(match.group(1).replace(",", ""))
                    total_pages = (total_records + 9) // 10
                    print(f"➔ 系統偵測成功：總共 {total_records} 筆資料，總計為 {total_pages} 頁。", flush=True)
                    return total_pages
        except Exception:
            pass
        return 1

    def _get_detail_info_with_retry(self, row, max_retries=3):
        """
        [資料完整性防護機制] 
        機制說明：
        - 網路爬蟲在開啟彈窗時，常因為網路瞬斷、網頁渲染延遲而抓取失敗。
        - 若直接跳過 (Yield NULL)，會污染資料湖，導致後續 ETL 清洗發生困難或錯誤。
        - 因此這裡加上 max_retries 變數控制重試次數，若失敗會按下 ESC 清除卡住的畫面後重試。
        - 若重試達到上限仍失敗，會直接拋出 Exception 中斷整支爬蟲，確保「要嘛不產出資料，要嘛產出的資料必須 100% 完整無缺 (Fail Fast)」。
        """
        modal_locator = (By.CSS_SELECTOR, ".ui.modal.active, .modal.active, [class*='modal'][class*='active']")
        
        for attempt in range(1, max_retries + 1):
            detail_info = {k: "" for k in self.fieldnames[6:]}
            try:
                # 尋找並點擊該列的「詳情」按鈕
                detail_btn = row.find_element(By.CSS_SELECTOR, "button.ui.green.button, a.ui.green.button")
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", detail_btn)
                self.wait.until(EC.element_to_be_clickable(detail_btn))
                self.driver.execute_script("arguments[0].click();", detail_btn)
                
                # 動態等待彈窗出現
                modal_element = self.wait.until(EC.visibility_of_element_located(modal_locator))
                time.sleep(2)  # 彈窗出現後硬等待 2 秒，確保後端資料渲染完成
                modal_text = modal_element.text
                
                # 使用正則表達式解析內容
                patterns = {
                    "發電設備地址": r"發電設備地址\s*\n\s*([^\n]+)", "裝置總容量": r"裝置總容量\s*\n\s*([^\n]+)",
                    "發電設備共用單位": r"發電設備共用單位\s*\n\s*([^\n]+)", "證書編號": r"證書編號\s*\n\s*([^\n]+)",
                    "T-REC最後憑證發放日期": r"T-REC\s*最後憑證發放日期\s*\n\s*([^\n]+)", "發電區間": r"發電區間\s*\n\s*([^\n]+)",
                    "再生能源設備查核報告": r"再生能源\s*設備查核報告\s*\n\s*([^\n]+)", "再生能源發電量查證報告": r"再生能源\s*發電量查證報告\s*\n\s*([^\n]+)",
                    "詳情_已移轉量": r"已移轉量\s*\n\s*([^\n]+)", "詳情_剩餘量": r"剩餘量\s*\n\s*([^\n]+)"
                }
                
                for key, pattern in patterns.items():
                    match = re.search(pattern, modal_text)
                    if match: detail_info[key] = match.group(1).strip()

                # 安全關閉彈窗
                closed = False
                for xpath_selector in ["//i[contains(@class, 'close')]", "//*[text()='關閉']", "//button[contains(text(), '關閉') or contains(text(), 'X')]"]:
                    try:
                        close_el = modal_element.find_element(By.XPATH, f".{xpath_selector}")
                        if close_el.is_displayed():
                            self.driver.execute_script("arguments[0].click();", close_el)
                            closed = True
                            break
                    except Exception: 
                        pass
                
                if not closed: 
                    self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                
                # 動態等待彈窗完全消失
                self.wait.until(EC.invisibility_of_element_located(modal_locator))
                time.sleep(1)  # 彈窗關閉後硬等待 1 秒，確保畫面乾淨不重疊
                
                # 成功解析，回傳資料
                return detail_info
                
            except Exception as detail_error:
                print(f" └─ [警告] 詳情彈窗處理異常 (嘗試次數: {attempt}/{max_retries})，已執行重置機制。", flush=True)
                # 發生例外，執行防呆重置：按下 ESC 確保彈窗關閉，清空畫面狀態
                try: 
                    self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    self.wait.until(EC.invisibility_of_element_located(modal_locator))
                except Exception: 
                    pass
                
                # 如果已經達到最大重試次數，直接拋出 Exception 中斷程式
                if attempt == max_retries:
                    raise Exception(f"無法取得詳情資料，已達到最大重試次數({max_retries})，強制中斷以避免 ETL 產生 NULL 錯誤。錯誤內容: {detail_error}")

    def parse_current_page(self, page):
        """解析當前頁面的表格資料與彈窗詳細資訊"""
        print(f"\n========== 正在抓取第 {page} 頁 ==========", flush=True)
        page_data = []
        
        rows = self.driver.find_elements(By.CSS_SELECTOR, "tbody tr")
        row_count = len(rows)

        for i in range(row_count):
            # 每次迴圈重新取得 elements 以避免 StaleElementReferenceException
            current_rows = self.driver.find_elements(By.CSS_SELECTOR, "tbody tr")
            if i >= len(current_rows): break
            row = current_rows[i]
            cols = [td.text.strip() for td in row.find_elements(By.CSS_SELECTOR, "td")]
            
            if not cols or "載入中" in "".join(cols) or "沒有資料" in "".join(cols): continue

            seller_equipment = cols[1]
            energy_type = cols[2]
            certificate_year = cols[3]
            transferred_mwh = cols[4]
            remaining_mwh = cols[5]
            
            lines = [line.strip() for line in seller_equipment.split("\n") if line.strip()]
            seller = lines[0] if len(lines) >= 1 else ""
            equipment = " ".join(lines[1:]) if len(lines) >= 2 else ""

            # 呼叫獨立的重試 Function 抓取詳細資料 (預設重試 3 次)
            detail_info = self._get_detail_info_with_retry(row, max_retries=3)

            data = {
                "出售單位": seller, "發電設備": equipment, "能源類型": energy_type,
                "憑證發放年份": certificate_year, "已移轉量(MWh)": transferred_mwh, "剩餘量(MWh)": remaining_mwh,
                **detail_info
            }
            page_data.append(data)

        return page_data

    def click_next_page(self):
        """點擊下一頁並等待頁碼變更"""
        try:
            next_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button.next.item.ui.button")
            if not next_buttons: return False
            next_button = next_buttons[0]
            if "disabled" in (next_button.get_attribute("class") or ""): return False

            # 取得當前的舊表格列，用來等待它從 DOM 被移除 (staleness)
            old_rows = self.driver.find_elements(By.CSS_SELECTOR, "tbody tr")
            old_first_row = old_rows[0] if old_rows else None

            page_input = self.driver.find_element(By.CSS_SELECTOR, "input.paginate_input")
            old_page_value = page_input.get_attribute("value")
            
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
            self.wait.until(EC.element_to_be_clickable(next_button))
            self.driver.execute_script("arguments[0].click();", next_button)

            # 動態等待頁碼發生變化 (確認網頁已響應)
            self.wait.until(lambda d: d.find_element(By.CSS_SELECTOR, "input.paginate_input").get_attribute("value") != old_page_value)
            
            # 等待舊的表格元素消失 (確保 DOM 已經被更新，不再是上一頁的資料)
            if old_first_row:
                try:
                    self.wait.until(EC.staleness_of(old_first_row))
                except Exception:
                    pass

            # 等待表格內容更新完畢 (確認沒有載入中字眼)
            self.wait_table_loaded()
            time.sleep(1)  # 翻頁後硬等待 1 秒作為伺服器請求節流即可
            return True
        except Exception:
            return False

    def close(self):
        """關閉瀏覽器"""
        if hasattr(self, 'driver'):
            self.driver.quit()


class DataManager:
    """負責處理資料的儲存與雲端上傳"""
    def __init__(self, fieldnames, bucket_name="tibame-bronze", gcs_folder="raw_data"):
        self.fieldnames = fieldnames
        self.bucket_name = bucket_name
        self.gcs_folder = gcs_folder

    def save_csv(self, filename, data):
        if not data: return None
        df = pd.DataFrame(data).reindex(columns=self.fieldnames)
        df.to_csv(filename, index=False, encoding="utf-8-sig")
        print(f"\n[系統通知] 歷史暫存寫入成功：{filename}，累計共 {len(df)} 筆原始資料。", flush=True)
        return filename

    def merge_year_csv(self, all_csv_file):
        print("\n[系統通知] 開始執行全年度數據整合...", flush=True)
        csv_files = glob.glob("已發放憑證紀錄_*.csv")
        csv_files = [file for file in csv_files if "all" not in file]
        if not csv_files: return None
        df_list = [pd.read_csv(file) for file in sorted(csv_files, reverse=True)]
        all_df = pd.concat(df_list, ignore_index=True).drop_duplicates()
        all_df.to_csv(all_csv_file, index=False, encoding="utf-8-sig")
        print(f"======\n任務大功告成！總產出檔案：{all_csv_file}，共計 {len(all_df)} 筆。\n======", flush=True)
        return all_csv_file

    def upload_to_gcs(self, local_file_name):
        """將跑完的 CSV 檔案上傳到 Google Cloud Storage 指定資料夾"""
        try:
            client = storage.Client()
            bucket = client.bucket(self.bucket_name)
            gcs_path = f"{self.gcs_folder}/{local_file_name}"
            blob = bucket.blob(gcs_path)
            blob.upload_from_filename(local_file_name)
            print(f"☁️ 成功上傳 {local_file_name} 至 GCS: gs://{self.bucket_name}/{gcs_path}", flush=True)
        except Exception as e:
            print(f"❌ 雲端上傳失敗: {e}", flush=True)


def main():
    years_to_crawl = [str(year) for year in range(2026, 2016, -1)]
    all_csv_file = "已發放憑證紀錄_all.csv"
    
    crawler = TRECCrawler(headless=True)
    data_manager = DataManager(fieldnames=crawler.fieldnames)

    try:
        crawler.wait_table_loaded()
        for year in years_to_crawl:
            crawler.select_year(year)
            total_pages = crawler.get_total_pages()
            year_data = []
            page = 1
            
            while page <= total_pages:
                crawler.wait_table_loaded()
                page_data = crawler.parse_current_page(page)
                year_data.extend(page_data)
                print(f"進度提示：{year} 年第 {page} / {total_pages} 頁抓取成功。目前累計 {len(year_data)} 筆。", flush=True)

                if page < total_pages:
                    if not crawler.click_next_page():
                        print(f"[警告] 無法翻至第 {page+1} 頁，程式提前中斷暫存。", flush=True)
                        break
                page += 1

            # 存檔並自動上傳該年度的檔案至 GCS
            year_csv_file = f"已發放憑證紀錄_{year}.csv"
            data_manager.save_csv(year_csv_file, year_data)
            data_manager.upload_to_gcs(year_csv_file)

        # 整合所有檔案並上傳終極大表至 GCS
        final_file = data_manager.merge_year_csv(all_csv_file)
        if final_file:
            data_manager.upload_to_gcs(final_file)

    except Exception as e:
        print(f"❌ 執行過程中發生錯誤: {e}", flush=True)
    finally:
        crawler.close()

if __name__ == "__main__":
    main()

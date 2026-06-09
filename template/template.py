"""
爬蟲開發模板 (適用於 Cloud Run Jobs + Cloud Storage)
透過工廠模式 (Factory Pattern) 實作，方便後續擴展不同目標網站的爬蟲。
請搜尋 "TODO" 來找到需要修改的地方
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from google.cloud import storage
import time
import csv
import os
from abc import ABC, abstractmethod

# =====================================================================
# 1. Base Crawler (基礎爬蟲類別)
# =====================================================================
class BaseCrawler(ABC):
    def __init__(self):
        self.driver = None

    def setup_driver(self):
        """建立 Chrome 設定物件 (Cloud Run 環境必備，請勿更動)"""
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")         # 開啟無頭模式
        chrome_options.add_argument("--no-sandbox")           # 繞過作業系統沙盒
        chrome_options.add_argument("--disable-dev-shm-usage") # 避免記憶體不足
        chrome_options.add_argument("--disable-gpu")          # 關閉 GPU 加速
        
        # 指定 Chromium 執行檔的絕對路徑 (Docker 環境)
        chrome_options.binary_location = "/usr/bin/chromium"
        service = Service("/usr/bin/chromedriver")
        
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        return self.driver

    def upload_to_gcs(self, local_csv_filename: str, bucket_name: str, destination_blob_name: str):
        """上傳檔案至 Google Cloud Storage"""
        print("準備將資料上傳至 Cloud Storage...", flush=True)
        try:
            # 初始化 GCS 客戶端 (Cloud Run 環境會自動取得權限)
            storage_client = storage.Client()
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(destination_blob_name)
            
            # 執行上傳
            blob.upload_from_filename(local_csv_filename)
            print(f"成功！檔案已上傳至 gs://{bucket_name}/{destination_blob_name}", flush=True)
        except Exception as e:
            print(f"上傳至 GCS 失敗: {e}", flush=True)
            print("提示: 若在本地端執行，請確認是否設定了 GOOGLE_APPLICATION_CREDENTIALS 環境變數", flush=True)

    @abstractmethod
    def run(self):
        """執行爬蟲的主要流程，由子類別實作"""
        pass


# =====================================================================
# 2. Concrete Crawler (具體爬蟲實作)
# =====================================================================
class TemplateCrawler(BaseCrawler):
    def run(self):
        # 初始化 Driver
        self.setup_driver()
        
        # =====================================================================
        # 2-1. 開啟目標網頁
        # =====================================================================
        # TODO: 修改為你要爬取的目標網址
        target_url = "https://example.com"
        print(f"正在前往目標網頁: {target_url}", flush=True)
        self.driver.get(target_url)
        
        # TODO: 依據網頁載入速度調整等待時間
        time.sleep(5) 
        
        # =====================================================================
        # 2-2. 準備 CSV 檔案寫入
        # =====================================================================
        # TODO: 修改本地暫存的 CSV 檔案名稱 (可不改)
        local_csv_filename = 'data.csv'
        
        csv_file = open(local_csv_filename, mode='w', newline='', encoding='utf-8-sig')
        csv_writer = csv.writer(csv_file)
        
        # TODO: 修改你的 CSV 表頭 (欄位名稱)
        csv_writer.writerow(['欄位1', '欄位2', '欄位3'])
        
        page = 1
        # TODO: 設定測試時的最大頁數，正式上線時可拿掉或設大一點
        max_pages = 1 
        
        try:
            # =====================================================================
            # 2-3. 開始爬取資料迴圈
            # =====================================================================
            while True:
                # ================= 定期重啟瀏覽器機制 (避免記憶體不足) =================
                # 假設設定每 100 頁重啟一次 (page > 1 是為了避免第 1 頁就觸發)
                if page > 1 and (page - 1) % 100 == 0:
                    print(f"\n[記憶體釋放] 已完成 {page-1} 頁，正在重啟瀏覽器以釋放記憶體...", flush=True)
                    self.driver.quit()  # 關閉舊的瀏覽器，記憶體瞬間清空
                    
                    # 重新啟動新的瀏覽器
                    self.setup_driver()
                    self.driver.get(target_url)
                    time.sleep(10) # 等待網站初始載入
                    
                    # 【關鍵】快轉回我們該爬的頁數
                    print(f"正在快轉回第 {page} 頁，這會需要一點時間，請稍候...", flush=True)
                    for _ in range(page - 1):
                        # TODO: 如果你的下一頁按鈕不是這個 XPATH，請記得連同這邊一起修改
                        try:
                            next_btn = self.driver.find_element(By.XPATH, '//*[contains(@class, "next")] | //a[contains(., "下一頁") or contains(., "Next")]')
                            self.driver.execute_script("arguments[0].click();", next_btn)
                            time.sleep(1) # 快速點擊，但給 DOM 一點更新的時間
                        except Exception as e:
                            print(f"快轉時找不到下一頁按鈕: {e}", flush=True)
                            break
                            
                    print(f"快轉完成！準備繼續爬取第 {page} 頁。", flush=True)
                    time.sleep(2) # 確保快轉後的頁面元素已完全載入
                # =====================================================================
                
                print(f"\n================= 正在爬取第 {page} 頁 =================", flush=True)
                
                # TODO: 撰寫你的爬蟲解析邏輯
                # 範例: 抓取列表元素
                # items = self.driver.find_elements(By.CLASS_NAME, "item-class")
                # for item in items:
                #     col1 = item.find_element(By.CLASS_NAME, "col1").text
                #     col2 = item.find_element(By.CLASS_NAME, "col2").text
                #     
                #     # 寫入一筆資料到 CSV
                #     csv_writer.writerow([col1, col2, "固定值"])
                
                # 模擬爬取延遲
                time.sleep(1)
                
                if page >= max_pages:
                    print(f"\n已經爬取 {max_pages} 頁，結束爬取。", flush=True)
                    break
                    
                # TODO: 處理下一頁邏輯
                # try:
                #     next_button = self.driver.find_element(By.XPATH, '//button[@class="next"]')
                #     if "disabled" in next_button.get_attribute("class"):
                #         print("已達最後一頁")
                #         break
                #     next_button.click()
                #     page += 1
                #     time.sleep(3)
                # except Exception as e:
                #     print("找不到下一頁按鈕或發生錯誤，結束迴圈。")
                #     break
                
                # 模板測試保護機制：為避免無限迴圈，此處直接 break，實作時請改為上述分頁邏輯
                break
                
        except Exception as e:
            print(f"爬取過程發生錯誤: {e}", flush=True)
            
        finally:
            print("關閉瀏覽器與檔案...", flush=True)
            if self.driver:
                self.driver.quit()
            csv_file.close()

        # =====================================================================
        # 2-4. 呼叫上傳功能
        # =====================================================================
        # TODO: 確認或修改 Bucket 名稱
        bucket_name = 'tibame-bronze'
        
        # TODO: 設定上傳到雲端後的檔案路徑與名稱
        # 建議加上日期或特定前綴，例如 'raw_data/my_crawler_data.csv'
        destination_blob_name = 'raw_data/your_custom_filename.csv' 
        
        self.upload_to_gcs(local_csv_filename, bucket_name, destination_blob_name)


# =====================================================================
# 3. Crawler Factory (爬蟲工廠)
# =====================================================================
class CrawlerFactory:
    @staticmethod
    def create_crawler(crawler_type: str) -> BaseCrawler:
        """
        根據傳入的類型字串 (crawler_type)，回傳對應的爬蟲實例。
        未來若有新的爬蟲，只需在此處新增對應的判斷式。
        """
        if crawler_type == "template":
            return TemplateCrawler()
        
        # TODO: 新增你的爬蟲類型判斷
        # elif crawler_type == "example_type":
        #     return ExampleCrawler()
        
        else:
            raise ValueError(f"未知的爬蟲類型: {crawler_type}")


# =====================================================================
# 4. 主程式執行入口
# =====================================================================
def main():
    # TODO: 設定你想執行的爬蟲類型
    crawler_type = "template"
    print(f"準備建立並執行爬蟲: {crawler_type}")
    
    try:
        # 透過工廠取得爬蟲實例
        crawler = CrawlerFactory.create_crawler(crawler_type)
        # 執行爬蟲
        crawler.run()
    except Exception as e:
        print(f"執行失敗: {e}")

if __name__ == "__main__":
    main()

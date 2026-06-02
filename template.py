"""
爬蟲開發模板 (適用於 Cloud Run Jobs + Cloud Storage)
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

def main():
    # =====================================================================
    # 1. 建立 Chrome 設定物件 (Cloud Run 環境必備，請勿更動)
    # =====================================================================
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")         # 開啟無頭模式
    chrome_options.add_argument("--no-sandbox")           # 繞過作業系統沙盒
    chrome_options.add_argument("--disable-dev-shm-usage") # 避免記憶體不足
    chrome_options.add_argument("--disable-gpu")          # 關閉 GPU 加速
    
    # 指定 Chromium 執行檔的絕對路徑 (Docker 環境)
    chrome_options.binary_location = "/usr/bin/chromium"
    service = Service("/usr/bin/chromedriver")
    
    # 啟動 WebDriver
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # =====================================================================
    # 2. 開啟目標網頁
    # =====================================================================
    # TODO: 修改為你要爬取的目標網址
    target_url = "https://example.com"
    print(f"正在前往目標網頁: {target_url}", flush=True)
    driver.get(target_url)
    
    # TODO: 依據網頁載入速度調整等待時間
    time.sleep(5) 
    
    # =====================================================================
    # 3. 準備 CSV 檔案寫入
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
        # 4. 開始爬取資料迴圈
        # =====================================================================
        while True:
            print(f"\n================= 正在爬取第 {page} 頁 =================", flush=True)
            
            # TODO: 撰寫你的爬蟲解析邏輯
            # 範例: 抓取列表元素
            # items = driver.find_elements(By.CLASS_NAME, "item-class")
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
            #     next_button = driver.find_element(By.XPATH, '//button[@class="next"]')
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
        driver.quit()
        csv_file.close()

    # =====================================================================
    # 5. 上傳檔案至 Google Cloud Storage
    # =====================================================================
    print("準備將資料上傳至 Cloud Storage...", flush=True)
    try:
        # 初始化 GCS 客戶端 (Cloud Run 環境會自動取得權限)
        storage_client = storage.Client()
        
        # TODO: 確認或修改 Bucket 名稱
        bucket_name = 'tibame-bronze'
        bucket = storage_client.bucket(bucket_name)
        
        # TODO: 設定上傳到雲端後的檔案路徑與名稱
        # 建議加上日期或特定前綴，例如 'raw_data/my_crawler_data.csv'
        destination_blob_name = 'raw_data/your_custom_filename.csv' 
        
        blob = bucket.blob(destination_blob_name)
        
        # 執行上傳
        blob.upload_from_filename(local_csv_filename)
        
        print(f"成功！檔案已上傳至 gs://{bucket_name}/{destination_blob_name}", flush=True)
        
    except Exception as e:
        print(f"上傳至 GCS 失敗: {e}", flush=True)
        print("提示: 若在本地端執行，請確認是否設定了 GOOGLE_APPLICATION_CREDENTIALS 環境變數", flush=True)

if __name__ == "__main__":
    main()
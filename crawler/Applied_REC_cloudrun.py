import csv
import glob
import os
import re
import time
import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from google.cloud import storage

# =========================
# 1. 基本設定與目標網址
# =========================

url = "https://www.trec.org.tw/certification"
years_to_crawl = ["2026"]
all_csv_file = "已發放憑證紀錄_all.csv"

# ☁️ 雲端儲存桶與資料夾設定
BUCKET_NAME = "tibame-bronze"
GCS_FOLDER = "raw_data"

fieldnames = [
    "出售單位", "發電設備", "能源類型", "憑證發放年份", "已移轉量(MWh)", "剩餘量(MWh)",
    "發電設備地址", "裝置總容量", "發電設備共用單位", "證書編號", "T-REC最後憑證發放日期", 
    "發電區間", "再生能源設備查核報告", "再生能源發電量查證報告", "詳情_已移轉量", "詳情_剩餘量"
]

# =========================
# 2. 開啟瀏覽器 (Cloud Run 無頭模式)
# =========================

print("啟動雲端無頭瀏覽器...")
chrome_options = Options()
chrome_options.add_argument("--headless")              # 隱藏視窗
chrome_options.add_argument("--no-sandbox")            # Linux 必須，繞過沙盒限制
chrome_options.add_argument("--disable-dev-shm-usage") # 防止 Docker 記憶體崩潰
chrome_options.add_argument("--window-size=1920,1080") # 確保元素可見

driver = webdriver.Chrome(options=chrome_options)
driver.get(url)
wait = WebDriverWait(driver, 12)  

# =========================
# 3. 雲端上傳模組
# =========================

def upload_to_gcs(local_file_name, bucket_name):
    """將跑完的 CSV 檔案上傳到 Google Cloud Storage 指定資料夾"""
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        # 將檔案存入 raw_data 資料夾內
        gcs_path = f"{GCS_FOLDER}/{local_file_name}"
        blob = bucket.blob(gcs_path)
        blob.upload_from_filename(local_file_name)
        print(f"☁️ 成功上傳 {local_file_name} 至 GCS: gs://{bucket_name}/{gcs_path}")
    except Exception as e:
        print(f"❌ 雲端上傳失敗: {e}")

# =========================
# 4. 爬蟲輔助函數
# =========================

def wait_table_loaded():
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "tbody tr")) > 0)
    wait.until(
        lambda d: any(
            len(row.find_elements(By.CSS_SELECTOR, "td")) >= 5
            and "載入中" not in row.text
            and "處理中" not in row.text
            for row in d.find_elements(By.CSS_SELECTOR, "tbody tr")
        )
    )
    time.sleep(1)

def select_year(year):
    print(f"\n==============================\n正在切換至年份： {year}\n==============================")
    wait_table_loaded()
    try:
        year_btn = wait.until(EC.element_to_be_clickable((By.XPATH, f"//span[contains(text(), '{year}') or text()='{year}']")))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", year_btn)
        time.sleep(1)
        year_btn.click()
    except Exception:
        year_elements = driver.find_elements(By.XPATH, f"//*[text()='{year}']")
        if year_elements:
            driver.execute_script("arguments[0].click();", year_elements[0])
    time.sleep(2)
    wait_table_loaded()

def get_total_pages():
    total_pages = 566  
    try:
        info_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '共') and contains(text(), '筆')]")
        if info_elements:
            info_text = info_elements[0].text.strip()
            match = re.search(r"共\s*([\d,]+)\s*筆", info_text)
            if match:
                total_records = int(match.group(1).replace(",", ""))
                total_pages = (total_records + 9) // 10
                print(f"➔ 系統偵測成功：總共 {total_records} 筆資料，總計為 {total_pages} 頁。")
                return total_pages
    except:
        pass
    return total_pages

def parse_current_page(page):
    rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
    print(f"\n========== 正在抓取第 {page} 頁 ==========")
    page_data = []

    for i in range(len(rows)):
        try:
            current_rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
            if i >= len(current_rows): break
            row = current_rows[i]
            cols = [td.text.strip() for td in row.find_elements(By.CSS_SELECTOR, "td")]
            if not cols or "載入中" in "".join(cols) or "沒有資料" in "".join(cols): continue

            seller_equipment, energy_type, certificate_year, transferred_mwh, remaining_mwh = cols[1], cols[2], cols[3], cols[4], cols[5]
            lines = [line.strip() for line in seller_equipment.split("\n") if line.strip()]
            seller = lines[0] if len(lines) >= 1 else ""
            equipment = " ".join(lines[1:]) if len(lines) >= 2 else ""

            detail_info = {k: "" for k in fieldnames[6:]}

            try:
                detail_btn = row.find_element(By.CSS_SELECTOR, "button.ui.green.button, a.ui.green.button")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", detail_btn)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", detail_btn)
                
                modal_locator = (By.CSS_SELECTOR, ".ui.modal.active, .modal.active, [class*='modal'][class*='active']")
                wait.until(EC.presence_of_element_located(modal_locator))
                time.sleep(1)

                modal_element = driver.find_element(*modal_locator)
                modal_text = modal_element.text
                
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

                closed = False
                for xpath_selector in ["//i[contains(@class, 'close')]", "//*[text()='關閉']", "//button[contains(text(), '關閉') or contains(text(), 'X')]"]:
                    try:
                        close_el = modal_element.find_element(By.XPATH, f".{xpath_selector}")
                        if close_el.is_displayed():
                            driver.execute_script("arguments[0].click();", close_el)
                            closed = True
                            break
                    except: pass
                
                if not closed: driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                time.sleep(1) 
            except Exception as detail_error:
                print(f" └─ 提示：第 {i+1} 列詳情彈窗處理異常，已執行重置機制。")
                try: driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE); time.sleep(0.5)
                except: pass

            data = {
                "出售單位": seller, "發電設備": equipment, "能源類型": energy_type,
                "憑證發放年份": certificate_year, "已移轉量(MWh)": transferred_mwh, "剩餘量(MWh)": remaining_mwh,
                **detail_info
            }
            page_data.append(data)
        except Exception as e:
            print(f"解析第 {i+1} 列數據遭遇未預期錯誤: {e}")
            continue

    return page_data

def click_next_page():
    next_buttons = driver.find_elements(By.CSS_SELECTOR, "button.next.item.ui.button")
    if not next_buttons: return False
    next_button = next_buttons[0]
    if "disabled" in (next_button.get_attribute("class") or ""): return False

    page_input = driver.find_element(By.CSS_SELECTOR, "input.paginate_input")
    old_page_value = page_input.get_attribute("value")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
    time.sleep(0.3)
    driver.execute_script("arguments[0].click();", next_button)

    try:
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, "input.paginate_input").get_attribute("value") != old_page_value)
        time.sleep(0.8)
        return True
    except TimeoutException:
        return False

def save_csv(filename, data):
    if not data: return None
    df = pd.DataFrame(data).reindex(columns=fieldnames)
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"\n[系統通知] 歷史暫存寫入成功：{filename}，累計共 {len(df)} 筆原始資料。")
    return filename

def merge_year_csv():
    print("\n[系統通知] 開始執行全年度數據整合...")
    csv_files = glob.glob("已發放憑證紀錄_*.csv")
    csv_files = [file for file in csv_files if "all" not in file]
    if not csv_files: return None
    df_list = [pd.read_csv(file) for file in sorted(csv_files, reverse=True)]
    all_df = pd.concat(df_list, ignore_index=True).drop_duplicates()
    all_df.to_csv(all_csv_file, index=False, encoding="utf-8-sig")
    print(f"==============================\n任務大功告成！總產出檔案：{all_csv_file}，共計 {len(all_df)} 筆。\n==============================")
    return all_csv_file

# ==================================
# 5. 控制主程式 (無人值守版)
# ==================================

try:
    wait_table_loaded()
    for year in years_to_crawl:
        select_year(year)
        total_pages = get_total_pages()
        year_data = []
        page = 1
        
        while page <= total_pages:
            wait_table_loaded()
            page_data = parse_current_page(page)
            year_data.extend(page_data)
            print(f"進度提示：{year} 年第 {page} / {total_pages} 頁抓取成功。目前累計 {len(year_data)} 筆。")

            if page < total_pages:
                if not click_next_page():
                    print(f"[警告] 無法翻至第 {page+1} 頁，程式提前中斷暫存。")
                    break
            page += 1

        # 存檔並自動上傳該年度的檔案至 GCS
        year_csv_file = f"已發放憑證紀錄_{year}.csv"
        save_csv(year_csv_file, year_data)
        upload_to_gcs(year_csv_file, BUCKET_NAME)

    # 整合所有檔案並上傳終極大表至 GCS
    final_file = merge_year_csv()
    if final_file:
        upload_to_gcs(final_file, BUCKET_NAME)

except Exception as e:
    print(f"❌ 執行過程中發生錯誤: {e}")
finally:
    driver.quit()
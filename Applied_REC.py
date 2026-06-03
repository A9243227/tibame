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

# =========================
# 1. 基本設定與目標網址
# =========================

url = "https://www.trec.org.tw/certification"
years_to_crawl = ["2026"]
all_csv_file = "已發放憑證紀錄_all.csv"

# 完整還原並校對所有原始欄位
fieldnames = [
    "出售單位",
    "發電設備",
    "能源類型",
    "憑證發放年份",
    "已移轉量(MWh)",
    "剩餘量(MWh)",
    # --- 詳情彈出視窗前段欄位 ---
    "發電設備地址",
    "裝置總容量",
    "發電設備共用單位",
    "證書編號",
    "T-REC最後憑證發放日期",
    "發電區間",
    # --- 詳情彈出視窗後段欄位 ---
    "再生能源設備查核報告",
    "再生能源發電量查證報告",
    "詳情_已移轉量",
    "詳情_剩餘量"
]

# =========================
# 2. 開啟瀏覽器
# =========================

driver = webdriver.Chrome()
driver.get(url)
wait = WebDriverWait(driver, 12)  

# =========================
# 3. 等待表格載入完成
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
    time.sleep(2)

# =========================
# 4. 切換憑證發放年份
# =========================

def select_year(year):
    print("\n==============================")
    print(f"正在切換至年份： {year}")
    print("==============================")
    wait_table_loaded()

    try:
        year_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, f"//span[contains(text(), '{year}') or text()='{year}']"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", year_btn)
        time.sleep(0.5)
        year_btn.click()
    except Exception:
        year_elements = driver.find_elements(By.XPATH, f"//*[text()='{year}']")
        if year_elements:
            driver.execute_script("arguments[0].click();", year_elements[0])
    
    time.sleep(2)
    wait_table_loaded()

# =========================
# 5. 精準獲取總頁數
# =========================

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

# ==================================
# 6. 解析目前頁面（精準定位彈窗，修正錯位與漏抓）
# ==================================

def parse_current_page(page):
    rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
    print(f"\n========== 正在抓取第 {page} 頁 ==========")
    
    page_data = []

    for i in range(len(rows)):
        try:
            current_rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
            if i >= len(current_rows):
                break
            row = current_rows[i]
            
            cols = [td.text.strip() for td in row.find_elements(By.CSS_SELECTOR, "td")]
            if not cols or "載入中" in "".join(cols) or "沒有資料" in "".join(cols):
                continue

            # 1. 外層表格基礎資料擷取
            seller_equipment = cols[1]
            energy_type = cols[2]
            certificate_year = cols[3]
            transferred_mwh = cols[4]
            remaining_mwh = cols[5]

            lines = [line.strip() for line in seller_equipment.split("\n") if line.strip()]
            seller = lines[0] if len(lines) >= 1 else ""
            equipment = " ".join(lines[1:]) if len(lines) >= 2 else ""

            # 初始化詳情字典
            detail_info = {
                "發電設備地址": "", "裝置總容量": "", "發電設備共用單位": "",
                "證書編號": "", "T-REC最後憑證發放日期": "", "發電區間": "",
                "再生能源設備查核報告": "", "再生能源發電量查證報告": "",
                "詳情_已移轉量": "", "詳情_剩餘量": ""
            }

            # 2. 點擊詳情並精準解析彈窗
            try:
                detail_btn = row.find_element(By.CSS_SELECTOR, "button.ui.green.button, a.ui.green.button")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", detail_btn)
                time.sleep(0.1)
                driver.execute_script("arguments[0].click();", detail_btn)
                
                # 【修正關鍵1】精準等待彈窗內的容器加載完成，並確保其 active（顯示中）
                modal_locator = (By.CSS_SELECTOR, ".ui.modal.active, .modal.active, [class*='modal'][class*='active']")
                wait.until(EC.presence_of_element_located(modal_locator))
                time.sleep(2)  # 給予足夠的時間讓動畫展開，避免抓到外層表格殘影

                # 【修正關鍵2】限定範圍：只抓取彈窗元素內的文字，完全隔離外層 Table 雜訊！
                modal_element = driver.find_element(*modal_locator)
                modal_text = modal_element.text
                
                # 【修正關鍵3】強化正則表達式，適應 \n 結構並精準匹配
                addr_match = re.search(r"發電設備地址\s*\n\s*([^\n]+)", modal_text)
                cap_match = re.search(r"裝置總容量\s*\n\s*([^\n]+)", modal_text)
                share_match = re.search(r"發電設備共用單位\s*\n\s*([^\n]+)", modal_text)
                no_match = re.search(r"證書編號\s*\n\s*([^\n]+)", modal_text)
                date_match = re.search(r"T-REC\s*最後憑證發放日期\s*\n\s*([^\n]+)", modal_text)
                period_match = re.search(r"發電區間\s*\n\s*([^\n]+)", modal_text)
                
                # 後段報告與詳情數據正則
                check_match = re.search(r"再生能源\s*設備查核報告\s*\n\s*([^\n]+)", modal_text)
                verify_match = re.search(r"再生能源\s*發電量查證報告\s*\n\s*([^\n]+)", modal_text)
                
                # 詳情內的移轉與剩餘量匹配
                detail_trans_match = re.search(r"已移轉量\s*\n\s*([^\n]+)", modal_text)
                detail_rem_match = re.search(r"剩餘量\s*\n\s*([^\n]+)", modal_text)

                if addr_match: detail_info["發電設備地址"] = addr_match.group(1).strip()
                if cap_match: detail_info["裝置總容量"] = cap_match.group(1).strip()
                if share_match: detail_info["發電設備共用單位"] = share_match.group(1).strip()
                if no_match: detail_info["證書編號"] = no_match.group(1).strip()
                if date_match: detail_info["T-REC最後憑證發放日期"] = date_match.group(1).strip()
                if period_match: detail_info["發電區間"] = period_match.group(1).strip()
                if check_match: detail_info["再生能源設備查核報告"] = check_match.group(1).strip()
                if verify_match: detail_info["再生能源發電量查證報告"] = verify_match.group(1).strip()
                if detail_trans_match: detail_info["詳情_已移轉量"] = detail_trans_match.group(1).strip()
                if detail_rem_match: detail_info["詳情_剩餘量"] = detail_rem_match.group(1).strip()

                # 3. 安全關閉機制
                closed = False
                for xpath_selector in ["//i[contains(@class, 'close')]", "//*[text()='關閉']", "//button[contains(text(), '關閉') or contains(text(), 'X')]"]:
                    try:
                        close_el = modal_element.find_element(By.XPATH, f".{xpath_selector}") # 限定在模組內找關閉
                        if close_el.is_displayed():
                            driver.execute_script("arguments[0].click();", close_el)
                            closed = True
                            break
                    except:
                        pass
                
                if not closed:
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                
                time.sleep(1) 

            except Exception as detail_error:
                print(f" └─ 提示：第 {i+1} 列詳情彈窗處理異常，已執行重置機制。原因: {detail_error}")
                try:
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    time.sleep(1)
                except:
                    pass

            # 4. 寫入資料
            data = {
                "出售單位": seller, "發電設備": equipment, "能源類型": energy_type,
                "憑證發放年份": certificate_year, "已移轉量(MWh)": transferred_mwh, "剩餘量(MWh)": remaining_mwh,
                "發電設備地址": detail_info["發電設備地址"], "裝置總容量": detail_info["裝置總容量"],
                "發電設備共用單位": detail_info["發電設備共用單位"], "證書編號": detail_info["證書編號"],
                "T-REC最後憑證發放日期": detail_info["T-REC最後憑證發放日期"], "發電區間": detail_info["發電區間"],
                "再生能源設備查核報告": detail_info["再生能源設備查核報告"], "再生能源發電量查證報告": detail_info["再生能源發電量查證報告"],
                "詳情_已移轉量": detail_info["詳情_已移轉量"], "詳情_剩餘量": detail_info["詳情_剩餘量"]
            }
            page_data.append(data)

        except Exception as e:
            print(f"解析第 {i+1} 列數據遭遇未預期錯誤: {e}")
            continue

    return page_data

# =========================
# 7. 翻頁邏輯
# =========================

def click_next_page():
    next_buttons = driver.find_elements(By.CSS_SELECTOR, "button.next.item.ui.button")
    if not next_buttons:
        return False

    next_button = next_buttons[0]
    class_name = next_button.get_attribute("class") or ""
    if "disabled" in class_name:
        return False

    page_input = driver.find_element(By.CSS_SELECTOR, "input.paginate_input")
    old_page_value = page_input.get_attribute("value")

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
    time.sleep(0.3)
    driver.execute_script("arguments[0].click();", next_button)

    try:
        wait.until(
            lambda d: d.find_element(By.CSS_SELECTOR, "input.paginate_input").get_attribute("value") != old_page_value
        )
        time.sleep(0.8)
        return True
    except TimeoutException:
        return False

# =========================
# 8. 儲存與合併 CSV
# =========================

def save_csv(filename, data):
    if not data:
        return None
    df = pd.DataFrame(data)
    df = df.reindex(columns=fieldnames)
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"\n[系統通知] 歷史暫存寫入成功：{filename}，累計共 {len(df)} 筆原始資料。")
    return df

def merge_year_csv():
    print("\n[系統通知] 開始執行全年度數據整合...")
    csv_files = glob.glob("已發放憑證紀錄_*.csv")
    csv_files = [file for file in csv_files if "all" not in file]
    if not csv_files:
        return
    df_list = [pd.read_csv(file) for file in sorted(csv_files, reverse=True)]
    all_df = pd.concat(df_list, ignore_index=True).drop_duplicates()
    all_df.to_csv(all_csv_file, index=False, encoding="utf-8-sig")
    print(f"==============================\n任務大功告成！總產出檔案：{all_csv_file}，共計 {len(all_df)} 筆。\n==============================")

# ==================================
# 10. 控制主程式 (隨時 Ctrl+C 暫停機制)
# ==================================

wait_table_loaded()

for year in years_to_crawl:
    select_year(year)
    total_pages = get_total_pages()

    year_data = []
    page = 1
    
    while page <= total_pages:
        try:
            wait_table_loaded()
            page_data = parse_current_page(page)
            year_data.extend(page_data)

            print(f"進度提示：{year} 年第 {page} / {total_pages} 頁抓取成功。目前累計 {len(year_data)} 筆。")

            if page < total_pages:
                success = click_next_page()
                if not success:
                    print(f"[警告] 無法翻至第 {page+1} 頁，程式提前中斷暫存。")
                    break
            page += 1

        except KeyboardInterrupt:
            print("\n\n" + "!"*40)
            print("【手動暫停攔截】已為您守住目前進度。")
            print("  [1] 沒問題，繼續往下衝 (直接按 Enter)")
            print("  [2] 幫我把目前爬到的資料存檔，並安全退出程式")
            print("!"*40)
            
            choice = input("請輸入指令 (1 或 2): ").strip()
            if choice == "2":
                print("\n[使用者指令] 收到，準備安全保存資料並關閉...")
                break
            else:
                print("\n[系統通知] 繼續執行爬取任務...\n")
                time.sleep(1)

    year_csv_file = f"已發放憑證紀錄_{year}.csv"
    save_csv(year_csv_file, year_data)

merge_year_csv()
driver.quit()
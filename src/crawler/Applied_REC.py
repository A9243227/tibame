import csv
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

# 【重要設定】起始頁面設為 512
start_page = 512  

# 完整還原並校對所有原始欄位
fieldnames = [
    "出售單位", "發電設備", "能源類型", "憑證發放年份", "已移轉量(MWh)", "剩餘量(MWh)",
    "發電設備地址", "裝置總容量", "發電設備共用單位", "證書編號", "T-REC最後憑證發放日期", "發電區間",
    "再生能源設備查核報告", "再生能源發電量查證報告", "詳情_已移轉量", "詳情_剩餘量"
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
    time.sleep(1.6)

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
        time.sleep(1.6)
        year_btn.click()
    except Exception:
        year_elements = driver.find_elements(By.XPATH, f"//*[text()='{year}']")
        if year_elements:
            driver.execute_script("arguments[0].click();", year_elements[0])
    
    time.sleep(1.6)
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

# =========================
# 6. 跳轉至指定頁面
# =========================
def jump_to_page(target_page):
    print(f"\n[系統通知] 準備跳轉至第 {target_page} 頁...")
    try:
        page_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.paginate_input")))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_input)
        time.sleep(1)
        
        page_input.send_keys(Keys.CONTROL + "a")
        page_input.send_keys(Keys.BACKSPACE)
        time.sleep(0.5)
        
        page_input.send_keys(str(target_page))
        page_input.send_keys(Keys.ENTER)
        
        time.sleep(2)
        wait_table_loaded()
        print(f"➔ 成功跳轉至第 {target_page} 頁！開始作業。")
    except Exception as e:
        print(f"[錯誤] 跳轉頁面失敗，將從目前頁面繼續：{e}")

# ==================================
# 7. 解析目前頁面
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

            seller_equipment = cols[1]
            energy_type = cols[2]
            certificate_year = cols[3]
            transferred_mwh = cols[4]
            remaining_mwh = cols[5]

            lines = [line.strip() for line in seller_equipment.split("\n") if line.strip()]
            seller = lines[0] if len(lines) >= 1 else ""
            equipment = " ".join(lines[1:]) if len(lines) >= 2 else ""

            detail_info = {
                "發電設備地址": "", "裝置總容量": "", "發電設備共用單位": "",
                "證書編號": "", "T-REC最後憑證發放日期": "", "發電區間": "",
                "再生能源設備查核報告": "", "再生能源發電量查證報告": "",
                "詳情_已移轉量": "", "詳情_剩餘量": ""
            }

            try:
                detail_btn = row.find_element(By.CSS_SELECTOR, "button.ui.green.button, a.ui.green.button")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", detail_btn)
                time.sleep(1.6)
                driver.execute_script("arguments[0].click();", detail_btn)
                
                modal_locator = (By.CSS_SELECTOR, ".ui.modal.active, .modal.active, [class*='modal'][class*='active']")
                wait.until(EC.presence_of_element_located(modal_locator))
                time.sleep(1.6) 

                modal_element = driver.find_element(*modal_locator)
                modal_text = modal_element.text
                
                addr_match = re.search(r"發電設備地址\s*\n\s*([^\n]+)", modal_text)
                cap_match = re.search(r"裝置總容量\s*\n\s*([^\n]+)", modal_text)
                share_match = re.search(r"發電設備共用單位\s*\n\s*([^\n]+)", modal_text)
                no_match = re.search(r"證書編號\s*\n\s*([^\n]+)", modal_text)
                date_match = re.search(r"T-REC\s*最後憑證發放日期\s*\n\s*([^\n]+)", modal_text)
                period_match = re.search(r"發電區間\s*\n\s*([^\n]+)", modal_text)
                check_match = re.search(r"再生能源\s*設備查核報告\s*\n\s*([^\n]+)", modal_text)
                verify_match = re.search(r"再生能源\s*發電量查證報告\s*\n\s*([^\n]+)", modal_text)
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

                closed = False
                for xpath_selector in ["//i[contains(@class, 'close')]", "//*[text()='關閉']", "//button[contains(text(), '關閉') or contains(text(), 'X')]"]:
                    try:
                        close_el = modal_element.find_element(By.XPATH, f".{xpath_selector}")
                        if close_el.is_displayed():
                            driver.execute_script("arguments[0].click();", close_el)
                            closed = True
                            break
                    except:
                        pass
                
                if not closed:
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                
                time.sleep(1.6) 

            except Exception as detail_error:
                print(f" └─ 提示：第 {i+1} 列詳情彈窗處理異常，已執行重置機制。原因: {detail_error}")
                try:
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    time.sleep(1.6)
                except:
                    pass

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
# 8. 翻頁邏輯
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
    time.sleep(1.6)
    driver.execute_script("arguments[0].click();", next_button)

    try:
        wait.until(
            lambda d: d.find_element(By.CSS_SELECTOR, "input.paginate_input").get_attribute("value") != old_page_value
        )
        time.sleep(1.6)
        return True
    except TimeoutException:
        return False

# =========================
# 9. 儲存與智能合併 CSV
# =========================

def save_csv(filename, data):
    if not data:
        return None
    df = pd.DataFrame(data)
    df = df.reindex(columns=fieldnames)
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"\n[系統通知] 歷史暫存寫入成功：{filename}，本次累計共 {len(df)} 筆原始資料。")
    return df

def append_to_all_csv(new_df):
    if new_df is None or new_df.empty:
        return
    print(f"\n[系統通知] 準備將本次新抓取的資料，併入總檔：{all_csv_file} ...")
    
    # 檢查總檔是否存在，存在則讀取並合併
    if os.path.exists(all_csv_file):
        all_df = pd.read_csv(all_csv_file)
        print(f"➔ 發現既有總檔，原本已有 {len(all_df)} 筆資料。")
        combined_df = pd.concat([all_df, new_df], ignore_index=True)
    else:
        print("➔ 尚未發現總檔，將直接建立新檔。")
        combined_df = new_df

    # 去除重複資料 (保護機制：避免中斷頁數重疊導致重複)
    before_len = len(combined_df)
    combined_df = combined_df.drop_duplicates()
    after_len = len(combined_df)
    
    if before_len != after_len:
        print(f"➔ 已自動為您剔除 {before_len - after_len} 筆重複資料。")
        
    # 覆寫回總檔
    combined_df.to_csv(all_csv_file, index=False, encoding="utf-8-sig")
    print(f"==============================\n任務大功告成！\n最終總產出檔案：{all_csv_file} \n總筆數已更新為：{len(combined_df)} 筆。\n==============================")


# ==================================
# 10. 控制主程式 (隨時 Ctrl+C 暫停機制)
# ==================================

wait_table_loaded()

for year in years_to_crawl:
    select_year(year)
    total_pages = get_total_pages()

    year_data = []
    page = start_page
    
    if page > 1:
        jump_to_page(page)
    
    while page <= total_pages:
        try:
            wait_table_loaded()
            page_data = parse_current_page(page)
            year_data.extend(page_data)

            print(f"進度提示：{year} 年第 {page} / {total_pages} 頁抓取成功。本次執行已累計 {len(year_data)} 筆。")

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
                time.sleep(1.6)

    # 考量從中斷點繼續，避免覆蓋原先檔案，加上起訖頁數做備份暫存
    year_csv_file = f"已發放憑證紀錄_{year}_p{start_page}_to_p{page-1}.csv"
    new_data_df = save_csv(year_csv_file, year_data)

# 執行最終的智慧合併
append_to_all_csv(new_data_df)
driver.quit() 
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import csv
import io

driver = webdriver.Chrome()
driver.get("https://www.trec.org.tw/certification_trade_situation/direct_supply")

time.sleep(10)

page = 1 
# max_page = 1# 測試先爬 1 頁（10 筆）

# 開啟 CSV 檔案準備寫入 (加上 utf-8-sig 讓 Excel 開啟不亂碼)
csv_file = open('data.csv', mode='w', newline='', encoding='utf-8-sig')
csv_writer = csv.writer(csv_file)
# 寫入表頭
csv_writer.writerow(['公司', '售電業者', '出售單位', '發電設備', '購買者', '成交紀錄'])

while True:
    print(f"\n================= 正在爬取第 {page} 頁 =================")
    
    tags = driver.find_elements(By.CLASS_NAME, "sorting_1")
    detail_buttons = driver.find_elements(By.XPATH, '//button[contains(., "詳情")]')
    
    print("抓到幾筆：", len(tags))
    print("詳情按鈕數量：", len(detail_buttons))
    
    for i in range(len(detail_buttons)):
        print(f"\n========== 第 {page} 頁 - 第 {i + 1} 筆 ==========")
        tag_text = tags[i].text
        print(tag_text)
        
        # 解析「公司」與「售電業者」
        tag_lines = tag_text.split('\n')
        company = tag_lines[0].strip() if len(tag_lines) > 0 else ""
        seller = tag_lines[1].strip() if len(tag_lines) > 1 else ""
        
        # 重新抓取按鈕以防 DOM 更新導致 StaleElementReferenceException
        current_buttons = driver.find_elements(By.XPATH, '//button[contains(., "詳情")]')
        
        # 使用 JavaScript 點擊，避免元素被擋住
        driver.execute_script("arguments[0].click();", current_buttons[i])
        
        # 等待彈出視窗出現 (最多等 10 秒)
        modal = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".ui.modal.active"))
        )
        # 等待裡面的文字載入，稍微停頓一下
        time.sleep(1)
        
        detail_text = modal.text.replace("\n關閉", "").strip()
        
        print("===== 詳細資訊 =====")
        print(detail_text)
        
        # 進行字串解析
        lines = detail_text.split('\n')
        
        sell_unit = ""
        power_equip = ""
        buyer = ""
        records = []
        
        # 逐行尋找對應的標題，下一行就是其內容
        for idx, line in enumerate(lines):
            line_str = line.strip()
            if line_str == "出售單位" and idx + 1 < len(lines):
                sell_unit = lines[idx + 1].strip()
            elif line_str == "發電設備" and idx + 1 < len(lines):
                power_equip = lines[idx + 1].strip()
            elif line_str == "購買者" and idx + 1 < len(lines):
                buyer = lines[idx + 1].strip()
            elif line_str == "成交記錄" or line_str == "成交紀錄":
                # 成交紀錄下方的所有非空白行都是紀錄
                for j in range(idx + 1, len(lines)):
                    record_line = lines[j].strip()
                    if record_line:
                        records.append(record_line)
                break  # 找到成交紀錄後就跳出迴圈，因為這是最後一項
                
        # 寫入 CSV
        if not records:
            # 如果沒有成交紀錄，還是寫入一筆
            csv_writer.writerow([company, seller, sell_unit, power_equip, buyer, ""])
        else:
            # 展開多筆成交紀錄
            for rec in records:
                csv_writer.writerow([company, seller, sell_unit, power_equip, buyer, rec])
                
        # 關閉彈出視窗
        close_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".ui.modal.active .actions .button"))
        )
        driver.execute_script("arguments[0].click();", close_btn)
        
        # 等待視窗消失
        WebDriverWait(driver, 10).until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, ".ui.modal.active"))
        )
        time.sleep(1)
        
    # if page >= max_pages:
    #     print(f"\n已經爬取 {max_pages} 頁，結束程式。")
    #     break
        
    try:
        # 嘗試尋找「下一頁」按鈕，通常帶有 next 或是 下一頁 的文字
        next_button = driver.find_element(By.XPATH, '//*[contains(@class, "next")] | //a[contains(., "下一頁") or contains(., "Next")]')
        
        # 檢查是否無法點擊 (例如 Datatables 的 disabled class)
        button_class = next_button.get_attribute("class") or ""
        if "disabled" in button_class:
            print("\n已經到達最後一頁。")
            break
            
        next_button.click()
        print("\n=> 點擊下一頁，等待資料載入...")
        page += 1
        time.sleep(5)  # 等待下一頁載入
        
    except Exception as e:
        print("\n找不到下一頁按鈕或發生錯誤，結束迴圈。")
        break

print("爬取完成！")
csv_file.close()

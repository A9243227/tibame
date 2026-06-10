from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import csv
import re
import os

# =========================
# 測試設定
# =========================
# 先測試抓 5 頁
# 之後要正式抓全部，把 5 改成 None
TEST_MAX_PAGE = 5


driver = webdriver.Chrome()
wait = WebDriverWait(driver, 20)

driver.get("https://www.trec.org.tw/certification_trade_situation/direct_supply")

time.sleep(5)


csv_file = "trec_direct_supply.csv"

fieldnames = [
    "出售單位",
    "發電設備",
    "購買者",
    "能源類型",
    "供電種類",
    "總移轉量(MWh)",
    "成交日期",
    "成交移轉量(MWh)",
    "成交記錄原文",
]


all_data = []


# =========================
# 函式 1：自動抓總頁數
# =========================
def get_total_pages(driver):
    """
    從網頁文字抓總頁數
    例如畫面上有：1 / 642
    就抓出 642
    """

    body_text = driver.find_element(By.TAG_NAME, "body").text

    match = re.search(r"[／/]\s*(\d+)", body_text)

    if match:
        return int(match.group(1))
    else:
        return None


# =========================
# 函式 2：判斷下一頁按鈕是否不能按
# =========================
def is_next_button_disabled(next_btn):
    """
    如果下一頁按鈕 class 裡面有 disabled
    或者 disabled 屬性存在
    就代表不能再按下一頁
    """

    class_name = next_btn.get_attribute("class") or ""
    disabled_attr = next_btn.get_attribute("disabled")

    if "disabled" in class_name or disabled_attr is not None:
        return True
    else:
        return False


# =========================
# 1. 開始抓資料
# =========================

try:
    total_pages = get_total_pages(driver)

    if total_pages:
        print("網站總頁數：", total_pages)
    else:
        print("抓不到總頁數，改用下一頁按鈕判斷什麼時候停止")

    page = 1

    while True:
        print(f"\n==================== 開始抓第 {page} 頁 ====================")

        # 等表格資料出現
        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "tbody tr")))
        time.sleep(2)

        rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
        detail_buttons = driver.find_elements(By.XPATH, '//button[contains(., "詳情")]')

        print("抓到幾筆：", len(rows))
        print("詳情按鈕數量：", len(detail_buttons))

        for i in range(len(detail_buttons)):
            print(f"\n========== 第 {page} 頁，第 {i + 1} 筆 ==========")

            # 每次重新抓，避免開關彈窗後元素失效
            rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
            detail_buttons = driver.find_elements(
                By.XPATH, '//button[contains(., "詳情")]'
            )

            row = rows[i]
            cols = row.find_elements(By.TAG_NAME, "td")

            # 出售單位 + 發電設備，在同一格裡面，所以要拆開
            seller_device_text = cols[1].text.strip()
            seller_device_lines = seller_device_text.splitlines()

            if len(seller_device_lines) > 0:
                seller_name = seller_device_lines[0]
            else:
                seller_name = ""

            if len(seller_device_lines) > 1:
                generation_device = seller_device_lines[1]
            else:
                generation_device = ""

            buyer = cols[2].text.strip()
            energy_type = cols[3].text.strip()
            supply_type = cols[4].text.strip()
            total_transfer_mwh = cols[5].text.strip()

            print("出售單位")
            print(seller_name)
            print("發電設備")
            print(generation_device)
            print("購買者")
            print(buyer)
            print("能源類型")
            print(energy_type)
            print("供電種類")
            print(supply_type)
            print("移轉量(MWh)")
            print(total_transfer_mwh)

            # 點詳情
            detail_btn = detail_buttons[i]

            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", detail_btn
            )
            time.sleep(1)

            # 用 JavaScript 點擊，比較不容易被畫面遮住
            driver.execute_script("arguments[0].click();", detail_btn)

            # 等彈出視窗出現
            modal = wait.until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, ".ui.modal.active"))
            )

            time.sleep(2)

            detail_text = modal.text.replace("\n關閉", "").strip()

            # 把詳細資訊拆成一行一行
            detail_lines = detail_text.splitlines()

            # 如果沒有成交記錄，就跳過這筆
            if "成交記錄" not in detail_lines:
                print("這筆沒有成交記錄，跳過")
            else:
                # 找到「成交記錄」的位置
                record_index = detail_lines.index("成交記錄")

                # 成交記錄下面的每一行
                trade_records = detail_lines[record_index + 1 :]

                for record in trade_records:
                    print(record)

                    # 解析：
                    # 於 2026-05-13 移轉 36.813 MWh
                    # 於 2026-05-20 移轉 2,732.629 MWh
                    match = re.search(
                        r"於\s*(\d{4}-\d{2}-\d{2})\s*移轉\s*([\d,]+(?:\.\d+)?)\s*MWh",
                        record,
                    )

                    if match:
                        trade_date = match.group(1)

                        # 把 2,732.629 改成 2732.629
                        trade_mwh = match.group(2).replace(",", "")

                        all_data.append(
                            {
                                "出售單位": seller_name,
                                "發電設備": generation_device,
                                "購買者": buyer,
                                "能源類型": energy_type,
                                "供電種類": supply_type,
                                "總移轉量(MWh)": total_transfer_mwh,
                                "成交日期": trade_date,
                                "成交移轉量(MWh)": trade_mwh,
                                "成交記錄原文": record,
                            }
                        )

            # 關閉彈出視窗
            close_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, ".ui.modal.active .actions .button")
                )
            )

            driver.execute_script("arguments[0].click();", close_btn)

            # 等彈窗消失
            wait.until(
                EC.invisibility_of_element_located(
                    (By.CSS_SELECTOR, ".ui.modal.active")
                )
            )

            time.sleep(1)

        # =========================
        # 測試停止條件：先抓 5 頁就停止
        # =========================
        if TEST_MAX_PAGE is not None and page >= TEST_MAX_PAGE:
            print(f"\n測試先抓 {TEST_MAX_PAGE} 頁，停止")
            break

        # =========================
        # 正式停止條件：抓到網站最後一頁
        # =========================
        if total_pages is not None and page >= total_pages:
            print(f"\n已經抓到最後一頁：第 {page} 頁，停止")
            break

        # =========================
        # 按下一頁
        # =========================
        next_btn = driver.find_element(By.CSS_SELECTOR, "button.next.item.ui.button")

        if is_next_button_disabled(next_btn):
            print("\n下一頁按鈕已經不能按，停止")
            break

        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", next_btn
        )
        time.sleep(1)

        driver.execute_script("arguments[0].click();", next_btn)

        time.sleep(5)

        page += 1

finally:
    driver.quit()


# =========================
# 2. 讀取舊 CSV
# =========================

old_data = []

if os.path.exists(csv_file) and os.path.getsize(csv_file) > 0:
    with open(csv_file, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        old_data = list(reader)


print("\n==================== CSV 合併開始 ====================")
print("舊 CSV 原本有", len(old_data), "列")
print("本次新抓到", len(all_data), "列")


# =========================
# 3. 合併舊資料 + 新資料
# =========================
# 這裡用 dict 做「去重複 + 更新」
#
# key 相同 = 同一筆資料
# key 不同 = 新資料
#
# 注意：
# 這裡故意不把「成交移轉量」放進 key
# 因為如果網站之後修正數字，我們希望新數字覆蓋舊數字
# =========================

merged_dict = {}


# 先放舊資料
for row in old_data:
    key = (
        row["出售單位"],
        row["發電設備"],
        row["購買者"],
        row["能源類型"],
        row["供電種類"],
        row["成交日期"],
    )

    merged_dict[key] = row


# 再放本次新抓到的資料
# 如果 key 一樣，新的 row 會覆蓋舊的 row
# 如果 key 不一樣，代表新資料，會新增到最後
for row in all_data:
    key = (
        row["出售單位"],
        row["發電設備"],
        row["購買者"],
        row["能源類型"],
        row["供電種類"],
        row["成交日期"],
    )

    merged_dict[key] = row


# dict 轉回 list
merged_data = list(merged_dict.values())


# =========================
# 4. 重新寫回 CSV
# =========================

with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)

    writer.writeheader()
    writer.writerows(merged_data)


print("\nCSV 更新完成")
print("更新後總共有", len(merged_data), "列")
print("本次避免重複資料數量：", len(old_data) + len(all_data) - len(merged_data))
print("檔案名稱：", csv_file)

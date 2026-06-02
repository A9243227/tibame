from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import time
import csv
import os
import re
import glob
import pandas as pd

# =========================
# 1. 基本設定
# =========================

url = "https://www.trec.org.tw/certification_trade_situation"

# 你想抓哪些年份，就改這裡
# 例如只補抓 2025，就寫 ["2025"]
# 程式最後會把資料夾內所有年度 CSV 合併成 all.csv
years_to_crawl = ["2019"]

all_csv_file = "自用發電設備憑證成交紀錄_all.csv"

fieldnames = [
    "出售單位",
    "發電設備",
    "購買者",
    "能源類型",
    "移轉量(MWh)",
    "憑證發放年份",
    "移轉日期",
]


# =========================
# 2. 開啟瀏覽器
# =========================

driver = webdriver.Chrome()
driver.get(url)

wait = WebDriverWait(driver, 20)


# =========================
# 3. 等待表格載入
# =========================


def wait_table_loaded():
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "tbody tr")) > 0)

    wait.until(
        lambda d: any(
            len(row.find_elements(By.CSS_SELECTOR, "td")) >= 6
            and "載入中" not in row.text
            and "處理中" not in row.text
            for row in d.find_elements(By.CSS_SELECTOR, "tbody tr")
        )
    )

    time.sleep(1)


# =========================
# 4. 選擇憑證發放年份
# =========================


def select_year(year):
    print("\n==============================")
    print("切換年份：", year)
    print("==============================")

    wait_table_loaded()

    # 點開年份下拉選單
    year_dropdown = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#year")))

    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});", year_dropdown
    )

    time.sleep(0.5)
    year_dropdown.click()
    time.sleep(0.5)

    # 點選指定年份
    year_option = wait.until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, f"#year .menu .item[data-value='{year}']")
        )
    )

    year_option.click()

    # 選完年份後，等資料更新
    time.sleep(2)
    wait_table_loaded()

    # 確認目前 hidden input 年份
    try:
        hidden_input = driver.find_element(By.CSS_SELECTOR, "#year input[name='year']")
        current_year = hidden_input.get_attribute("value")
        print("目前年份 value：", current_year)
    except:
        print("沒有讀到 hidden input 年份，但不影響後續抓取")


# =========================
# 5. 取得目前年份總頁數
# =========================


def get_total_pages():
    total_pages = 1

    spans = driver.find_elements(By.CSS_SELECTOR, "span.paginate_of")

    if spans:
        text = spans[0].text.strip()
        print("分頁文字：", text)  # 例如 / 55

        match = re.search(r"/\s*(\d+)", text)

        if match:
            total_pages = int(match.group(1))

    return total_pages


# =========================
# 6. 解析目前頁面
# =========================


def parse_current_page(page):
    rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")

    print(f"\n========== 正在抓第 {page} 頁 ==========")
    print("本頁列數：", len(rows))

    page_data = []

    for row in rows:
        cols = [td.text.strip() for td in row.find_elements(By.CSS_SELECTOR, "td")]

        if not cols:
            continue

        row_text = " ".join(cols)

        if "載入中" in row_text or "沒有資料" in row_text:
            continue

        print("原始欄位：", cols)

        if len(cols) >= 7:
            seller_equipment = cols[1]
            buyer = cols[2]
            energy_type = cols[3]
            transfer_mwh = cols[4]
            certificate_year = cols[5]
            transfer_date = cols[6]

        elif len(cols) >= 6:
            seller_equipment = cols[0]
            buyer = cols[1]
            energy_type = cols[2]
            transfer_mwh = cols[3]
            certificate_year = cols[4]
            transfer_date = cols[5]

        else:
            print("欄位數不足，跳過：", cols)
            continue

        # 拆出售單位 / 發電設備
        lines = [line.strip() for line in seller_equipment.split("\n") if line.strip()]

        if len(lines) >= 2:
            seller = lines[0]
            equipment = " ".join(lines[1:])
        elif len(lines) == 1:
            seller = lines[0]
            equipment = ""
        else:
            seller = ""
            equipment = ""

        data = {
            "出售單位": seller,
            "發電設備": equipment,
            "購買者": buyer,
            "能源類型": energy_type,
            "移轉量(MWh)": transfer_mwh,
            "憑證發放年份": certificate_year,
            "移轉日期": transfer_date,
        }

        page_data.append(data)

    return page_data


# =========================
# 7. 點下一頁
# =========================


def click_next_page():
    next_buttons = driver.find_elements(By.CSS_SELECTOR, "button.next.item.ui.button")

    if not next_buttons:
        print("找不到下一頁按鈕")
        return False

    next_button = next_buttons[0]

    class_name = next_button.get_attribute("class") or ""

    if "disabled" in class_name:
        print("下一頁 disabled，已經最後一頁")
        return False

    page_input = driver.find_element(By.CSS_SELECTOR, "input.paginate_input")
    old_page_value = page_input.get_attribute("value")

    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});", next_button
    )

    time.sleep(0.5)

    driver.execute_script("arguments[0].click();", next_button)

    try:
        wait.until(
            lambda d: d.find_element(
                By.CSS_SELECTOR, "input.paginate_input"
            ).get_attribute("value")
            != old_page_value
        )

        time.sleep(1)
        return True

    except TimeoutException:
        print("按了下一頁，但頁碼沒有變，停止")
        return False


# =========================
# 8. 存年度 CSV
# =========================


def save_csv(filename, data):
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

    print("\nCSV 存檔完成：", filename)
    print("資料筆數：", len(data))
    print("存放位置：", os.path.abspath(filename))


# =========================
# 9. 合併年度 CSV 成 all.csv
# =========================


def merge_year_csv():
    print("\n==============================")
    print("開始合併年度 CSV")
    print("==============================")

    # 只抓年度檔，例如：
    # 自用發電設備憑證成交紀錄_2026.csv
    # 自用發電設備憑證成交紀錄_2025.csv
    csv_files = glob.glob("自用發電設備憑證成交紀錄_*.csv")

    # 排除 all.csv，避免自己合併自己
    csv_files = [file for file in csv_files if "all" not in file]

    if not csv_files:
        print("找不到年度 CSV，無法合併")
        return

    # 排序，讓年份順序比較固定
    csv_files = sorted(csv_files, reverse=True)

    print("準備合併以下檔案：")
    for file in csv_files:
        print(file)

    df_list = []

    for file in csv_files:
        df = pd.read_csv(file)
        df_list.append(df)

    all_df = pd.concat(df_list, ignore_index=True)

    # 去除完全重複資料
    all_df = all_df.drop_duplicates()

    all_df.to_csv(all_csv_file, index=False, encoding="utf-8-sig")

    print("\n==============================")
    print("all.csv 合併完成")
    print("檔名：", all_csv_file)
    print("總資料筆數：", len(all_df))
    print("存放位置：", os.path.abspath(all_csv_file))
    print("==============================")


# =========================
# 10. 開始依年份抓資料
# =========================

wait_table_loaded()

for year in years_to_crawl:
    select_year(year)

    total_pages = get_total_pages()

    print("==============================")
    print(f"{year} 年總頁數：", total_pages)
    print("==============================")

    year_data = []

    for page in range(1, total_pages + 1):
        wait_table_loaded()

        page_data = parse_current_page(page)

        year_data.extend(page_data)

        print(f"{year} 年第 {page} 頁完成")
        print(f"{year} 年目前累積：{len(year_data)} 筆")

        if page < total_pages:
            success = click_next_page()

            if not success:
                print(f"{year} 年無法前往下一頁，提前停止")
                break

    # 每一年單獨存一份
    year_csv_file = f"自用發電設備憑證成交紀錄_{year}.csv"
    save_csv(year_csv_file, year_data)


# =========================
# 11. 用年度 CSV 合併產生 all.csv
# =========================

merge_year_csv()


# =========================
# 12. 關閉瀏覽器
# =========================

driver.quit()

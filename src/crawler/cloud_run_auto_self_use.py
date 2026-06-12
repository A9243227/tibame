"""
T-REC 自用發電設備憑證成交紀錄爬蟲
適用於 Cloud Run Jobs + Selenium + Cloud Storage

這版是把你原本的「自動判斷年份 + 年度 CSV + all.csv 合併」版本，
串接到 Cloud Run 模板裡。

保留 Cloud Run 架構：
1. 使用 /usr/bin/chromium 與 /usr/bin/chromedriver
2. 爬完後輸出 CSV 到本地暫存目錄 /tmp
3. 再上傳到 Google Cloud Storage

可用環境變數：
- GCS_BUCKET：GCS bucket 名稱，預設 tibame-bronze
- GCS_PREFIX：上傳到 bucket 內的資料夾路徑，預設 raw_data/t_rec/self_use_certification_trade
- YEARS_TO_CRAWL：手動指定要抓哪些年份，逗號分隔，例如 2026,2025,2024；不設定則自動判斷
- MAX_PAGES_PER_YEAR：每一年最多抓幾頁，0 代表全部，測試可設 1
- RESTART_EVERY_PAGES：每幾頁重啟瀏覽器釋放記憶體，0 代表不重啟，預設 100
- LOCAL_WORKDIR：本地暫存資料夾，Cloud Run 預設會用 /tmp
"""

# =========================
# 0. 匯入需要用到的套件
# =========================

# Selenium 主套件：用來開啟 Chrome 瀏覽器
from selenium import webdriver

# By：用來指定查找網頁元素的方式，例如 CSS_SELECTOR、XPATH
from selenium.webdriver.common.by import By

# WebDriverWait：用來等待網頁元素出現或變化
from selenium.webdriver.support.ui import WebDriverWait

# EC：expected_conditions，常用來等待某個元素可以被點擊
from selenium.webdriver.support import expected_conditions as EC

# Options / Service：Cloud Run Docker 環境啟動 Chromium / ChromeDriver 需要用
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# TimeoutException：當等待超時時，用來捕捉錯誤，避免程式直接中斷
from selenium.common.exceptions import TimeoutException

# Google Cloud Storage：Cloud Run 跑完後，上傳 CSV 到 GCS
from google.cloud import storage

# time：用來暫停幾秒，讓網頁資料有時間更新
import time

# csv：用來把資料存成 CSV 檔
import csv

# os：用來取得目前檔案路徑、檔名、環境變數
import os

# re：正規表達式，用來從文字中抓年份、頁數
import re

# glob：用來搜尋資料夾裡符合條件的檔案，例如找出所有年度 CSV
import glob

# tempfile：取得系統暫存資料夾；Cloud Run 會是 /tmp，本機測試會自動用本機暫存路徑
import tempfile

# pandas：沿用你原本版本，用來合併多個 CSV，最後產生 all.csv
import pandas as pd

# datetime：用來取得今年是哪一年
from datetime import datetime

# =========================
# 1. 基本設定
# =========================

# 目標網址：T-REC 自用發電設備憑證成交紀錄
TARGET_URL = "https://www.trec.org.tw/certification_trade_situation"

# CSV 檔案名稱的前綴
# 之後年度 CSV 會長這樣：
# 自用發電設備憑證成交紀錄_2026.csv
# 自用發電設備憑證成交紀錄_2025.csv
CSV_PREFIX = "trec_self_generation_transaction_raw"

# 合併後的總表檔名
# 這個檔案每次執行都會重新合併產生
ALL_CSV_FILE = f"{CSV_PREFIX}.csv"

# CSV 欄位名稱
# 這些欄位會出現在每個年度 CSV 和 all.csv
FIELDNAMES = [
    "出售單位",
    "發電設備",
    "購買者",
    "能源類型",
    "移轉量(MWh)",
    "憑證發放年份",
    "移轉日期",
]

# 取得今年年份
# 例如現在是 2026 年，current_year 就會是 "2026"
CURRENT_YEAR = str(datetime.now().year)

# 強制重抓的年份
# 目的：
# 舊年份通常不會再變，所以有 CSV 就不用重抓
# 但今年資料可能每個月更新，所以今年要每次都重新抓
FORCE_RE_CRAWL_YEARS = [CURRENT_YEAR]

# Cloud Run 本地端只有暫存空間，所以 CSV 先寫到 /tmp
# 本機測試時，tempfile.gettempdir() 會自動改成 Windows / Mac 的暫存資料夾
LOCAL_WORKDIR = os.getenv("LOCAL_WORKDIR", tempfile.gettempdir())
os.makedirs(LOCAL_WORKDIR, exist_ok=True)

# GCS 設定
# 你原本 Cloud Run 模板預設 bucket 是 tibame-bronze
GCS_BUCKET = os.getenv("GCS_BUCKET", "tibame-bronze")

# 上傳到 bucket 內的資料夾
# 最後會長得像：
# gs://tibame-bronze/raw_data/t_rec/self_use_certification_trade/自用發電設備憑證成交紀錄_2026.csv
GCS_PREFIX = os.getenv(
    "GCS_PREFIX",
    "raw_data/t_rec/self_use_certification_trade",
).strip("/")

# 手動指定年份：
# 例如 Cloud Run Jobs 環境變數設 YEARS_TO_CRAWL=2026,2025
# 如果沒有設定，就走「自動判斷網站年份 + GCS 已有年度 CSV」邏輯
MANUAL_YEARS_TO_CRAWL = [
    year.strip() for year in os.getenv("YEARS_TO_CRAWL", "").split(",") if year.strip()
]

# 測試用：每一年最多抓幾頁
# 0 代表不限制，也就是抓完整年份
MAX_PAGES_PER_YEAR = int(os.getenv("MAX_PAGES_PER_YEAR", "0"))

# 長時間爬很多頁時，定期重啟瀏覽器釋放記憶體
# 0 代表不重啟
RESTART_EVERY_PAGES = int(os.getenv("RESTART_EVERY_PAGES", "100"))


# =========================
# 2. Cloud Run 專用：建立 Chrome 瀏覽器
# =========================

# 這兩個變數會在 create_driver() 裡面建立
# 後面函式沿用你原本寫法，直接使用 driver / wait

driver = None
wait = None


def create_driver():
    """
    建立 Selenium Chrome 瀏覽器。

    這段是 Cloud Run / Docker 版本的重點：
    1. 使用 headless，因為 Cloud Run 沒有真的螢幕
    2. 指定 /usr/bin/chromium
    3. 指定 /usr/bin/chromedriver

    注意：
    這支在 Windows 直接按 Run，通常會因為找不到 /usr/bin/chromium 失敗。
    真正要跑成功，要在 Docker / Cloud Run Jobs 裡面跑。
    """

    global driver, wait

    chrome_options = Options()

    # Cloud Run 必備：無頭模式，不開啟實體瀏覽器視窗
    chrome_options.add_argument("--headless=new")

    # Cloud Run / Docker 常用設定，避免權限與共享記憶體問題
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")

    # 讓瀏覽器畫面大小固定，避免某些按鈕因 RWD 版面改變而抓不到
    chrome_options.add_argument("--window-size=1920,1080")

    # 指定 Chromium 執行檔的絕對路徑
    chrome_options.binary_location = "/usr/bin/chromium"

    # 指定 ChromeDriver 的絕對路徑
    service = Service("/usr/bin/chromedriver")

    # 啟動 WebDriver
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # 設定最多等待 20 秒
    wait = WebDriverWait(driver, 20)

    return driver


# =========================
# 3. GCS 相關函式
# =========================


def build_gcs_blob_name(filename):
    """
    組出上傳到 GCS 的完整 blob 路徑。

    例如：
    filename = 自用發電設備憑證成交紀錄_2026.csv
    GCS_PREFIX = raw_data/t_rec/self_use_certification_trade

    回傳：
    raw_data/t_rec/self_use_certification_trade/自用發電設備憑證成交紀錄_2026.csv
    """

    if GCS_PREFIX:
        return f"{GCS_PREFIX}/{filename}"
    return filename


def create_storage_client():
    """
    建立 Cloud Storage client。

    在 Cloud Run 裡面，通常會自動使用服務帳號權限。
    如果在本機沒有設定 GOOGLE_APPLICATION_CREDENTIALS，可能會失敗。
    """

    return storage.Client()


def download_existing_year_csv_from_gcs(storage_client):
    """
    從 GCS 下載已經存在的年度 CSV 到本地暫存資料夾。

    為什麼需要這段？
    因為 Cloud Run 每次啟動時，本地 /tmp 幾乎都是空的。
    如果只檢查本機檔案，程式會以為所有年份都沒抓過，然後每次重抓全部年份。

    所以 Cloud Run 版本改成：
    1. 先去 GCS 看之前已經上傳過哪些年度 CSV
    2. 把那些年度 CSV 下載回 /tmp
    3. 再用你原本的 get_existing_years() 判斷哪些年份已經抓過
    """

    print("\n==============================")
    print("開始從 GCS 下載既有年度 CSV")
    print("==============================")
    print("Bucket：", GCS_BUCKET)
    print("Prefix：", GCS_PREFIX)

    bucket = storage_client.bucket(GCS_BUCKET)

    # 如果 GCS_PREFIX 有值，就用這個 prefix 列出檔案
    # 注意：GCS 的 prefix 不等於資料夾，只是物件名稱前綴
    prefix = f"{GCS_PREFIX}/" if GCS_PREFIX else ""

    downloaded_files = []

    for blob in storage_client.list_blobs(GCS_BUCKET, prefix=prefix):
        filename = os.path.basename(blob.name)

        # 只下載年度 CSV
        # 例如：自用發電設備憑證成交紀錄_2026.csv
        # 不下載 all.csv，因為 all.csv 會重新合併產生
        if not filename.startswith(f"{CSV_PREFIX}_"):
            continue

        if filename == ALL_CSV_FILE:
            continue

        if not re.search(r"_(\d{4})\.csv$", filename):
            continue

        local_path = os.path.join(LOCAL_WORKDIR, filename)

        print(f"下載：gs://{GCS_BUCKET}/{blob.name} -> {local_path}")
        blob.download_to_filename(local_path)
        downloaded_files.append(local_path)

    print("已下載年度 CSV 數量：", len(downloaded_files))

    return downloaded_files


def upload_csv_files_to_gcs(storage_client):
    """
    把本次產生或本地暫存裡的年度 CSV 與 all.csv 上傳到 GCS。

    這裡會上傳：
    1. 所有年度 CSV
    2. all.csv

    同名檔案會覆蓋，所以今年資料重抓後會更新 GCS 上的今年 CSV。
    """

    print("\n==============================")
    print("開始上傳 CSV 到 Cloud Storage")
    print("==============================")

    bucket = storage_client.bucket(GCS_BUCKET)

    # 找出本地暫存資料夾裡所有年度 CSV
    csv_files = glob.glob(os.path.join(LOCAL_WORKDIR, f"{CSV_PREFIX}_*.csv"))

    # 加入合併後的總表 CSV
    all_csv_path = os.path.join(LOCAL_WORKDIR, ALL_CSV_FILE)

    if os.path.exists(all_csv_path):
        csv_files.append(all_csv_path)

    if not csv_files:
        print("找不到任何 CSV，沒有檔案可上傳")
        return

    for local_path in sorted(csv_files):
        filename = os.path.basename(local_path)
        destination_blob_name = build_gcs_blob_name(filename)

        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(local_path)

        print(f"已上傳：{local_path}")
        print(f"GCS位置：gs://{GCS_BUCKET}/{destination_blob_name}")

    print("\n全部 CSV 上傳完成")


# =========================
# 4. 等待表格載入完成
# =========================


def wait_table_loaded():
    """
    等待表格資料載入完成。

    為什麼需要這個函式？
    因為這個網站資料不是一打開就立刻完整出現，
    有時候會先出現「載入中」或空表格，
    如果太快抓，可能會抓到錯誤資料。

    這個函式會做兩件事：
    1. 等 tbody tr 出現
    2. 等 tr 裡面真的有 td，而且不是「載入中」或「處理中」
    """

    # 等到表格 tbody 裡至少有一列 tr
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "tbody tr")) > 0)

    # 等到表格裡至少有一列是真正資料
    wait.until(
        lambda d: any(
            len(row.find_elements(By.CSS_SELECTOR, "td")) >= 6
            and "載入中" not in row.text
            and "處理中" not in row.text
            for row in d.find_elements(By.CSS_SELECTOR, "tbody tr")
        )
    )

    # 多等 1 秒，讓畫面穩定
    time.sleep(1)


# =========================
# 5. 自動取得網頁下拉選單裡的所有年份
# =========================


def get_available_years():
    """
    自動從「憑證發放年份」下拉選單抓出所有年份。

    例如網站下拉選單裡有：
    2026
    2025
    2024
    2023

    這個函式會回傳：
    ["2026", "2025", "2024", "2023"]

    這樣你就不用手動寫 years_to_crawl。
    """

    print("\n==============================")
    print("開始讀取網站可選年份")
    print("==============================")

    # 先確保表格已經載入
    wait_table_loaded()

    # 找到年份下拉選單
    year_dropdown = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#year")))

    # 捲動到下拉選單位置，避免元素被遮住或不能點
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});", year_dropdown
    )

    time.sleep(0.5)

    # 點開年份下拉選單
    year_dropdown.click()

    time.sleep(0.5)

    # 找到下拉選單裡所有選項
    year_options = driver.find_elements(By.CSS_SELECTOR, "#year .menu .item")

    years = []

    for option in year_options:
        value = option.get_attribute("data-value")

        # 只保留純數字年份，避免抓到「全部」或其他不是年份的選項
        if value and value.isdigit():
            years.append(value)

    # 去除重複年份，並由大到小排序
    years = sorted(list(set(years)), reverse=True)

    print("網站可選年份：", years)

    # 點 body 關閉下拉選單
    driver.find_element(By.TAG_NAME, "body").click()

    time.sleep(0.5)

    return years


# =========================
# 6. 從本地暫存資料夾判斷哪些年份已經抓過
# =========================


def get_existing_years():
    """
    從本地暫存資料夾裡的年度 CSV 判斷哪些年份已經抓過。

    在 Cloud Run 版本裡，這些檔案通常是剛剛從 GCS 下載回 /tmp 的年度 CSV。

    例如資料夾裡有：
    自用發電設備憑證成交紀錄_2026.csv
    自用發電設備憑證成交紀錄_2025.csv
    自用發電設備憑證成交紀錄_all.csv

    這個函式會回傳：
    ["2026", "2025"]

    注意：all.csv 不算年度檔，所以會排除。
    """

    print("\n==============================")
    print("開始檢查本地暫存資料夾已存在年度 CSV")
    print("==============================")

    csv_files = glob.glob(os.path.join(LOCAL_WORKDIR, f"{CSV_PREFIX}_*.csv"))

    existing_years = []

    for file in csv_files:
        filename = os.path.basename(file)

        # 排除 all.csv
        if filename == ALL_CSV_FILE:
            continue

        match = re.search(r"_(\d{4})\.csv$", filename)

        if match:
            existing_years.append(match.group(1))

    existing_years = sorted(list(set(existing_years)), reverse=True)

    print("本地已存在年份 CSV：", existing_years)

    return existing_years


# =========================
# 7. 決定這次要抓哪些年份
# =========================


def decide_years_to_crawl(available_years, existing_years):
    """
    決定這次要抓哪些年份。

    自動模式邏輯：
    1. 網站有，但 GCS 沒有年度 CSV 的年份，要抓
    2. 今年資料要強制重抓，因為今年資料可能每個月更新
    3. 舊年份如果 GCS 已經有年度 CSV，就跳過

    手動模式邏輯：
    如果有設定 YEARS_TO_CRAWL，就只抓指定年份。
    例如 YEARS_TO_CRAWL=2026,2025
    """

    # 手動指定年份時，優先使用手動設定
    if MANUAL_YEARS_TO_CRAWL:
        years_to_crawl = []

        for year in MANUAL_YEARS_TO_CRAWL:
            if not year.isdigit():
                print(f"忽略非年份設定：{year}")
                continue

            if year not in available_years:
                print(f"警告：{year} 不在網站年份選單中，略過")
                continue

            years_to_crawl.append(year)

        years_to_crawl = sorted(list(set(years_to_crawl)), reverse=True)

        print("\n==============================")
        print("這次使用手動指定年份")
        print("==============================")
        print(years_to_crawl)

        return years_to_crawl

    # 自動判斷要抓哪些年份
    years_to_crawl = []

    # 第一段：抓還沒抓過的年份
    for year in available_years:
        if year not in existing_years:
            years_to_crawl.append(year)

    # 第二段：加入強制重抓年份，也就是今年
    for year in FORCE_RE_CRAWL_YEARS:
        if year in available_years:
            years_to_crawl.append(year)

    years_to_crawl = sorted(list(set(years_to_crawl)), reverse=True)

    print("\n==============================")
    print("這次準備抓取年份")
    print("==============================")
    print(years_to_crawl)

    return years_to_crawl


# =========================
# 8. 選擇指定年份
# =========================


def select_year(year):
    """
    切換網站上的「憑證發放年份」。

    例如傳入 year = "2025"
    程式就會點開年份下拉選單，選擇 2025。

    注意：
    這個網站切換年份時網址不會改變，
    所以不能用網址判斷年份，要用 Selenium 點下拉選單。
    """

    print("\n==============================")
    print("切換年份：", year)
    print("==============================")

    wait_table_loaded()

    year_dropdown = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#year")))

    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});", year_dropdown
    )

    time.sleep(0.5)

    year_dropdown.click()

    time.sleep(0.5)

    year_option = wait.until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, f"#year .menu .item[data-value='{year}']")
        )
    )

    year_option.click()

    # 選完後等待資料更新
    time.sleep(2)

    wait_table_loaded()

    try:
        hidden_input = driver.find_element(By.CSS_SELECTOR, "#year input[name='year']")
        current_year_value = hidden_input.get_attribute("value")

        print("目前年份 value：", current_year_value)

        if current_year_value != year:
            print("警告：目前年份 value 和預期年份不同，請檢查網站元素")

    except Exception:
        print("沒有讀到 hidden input 年份，但不影響後續抓取")


# =========================
# 9. 取得目前年份總頁數
# =========================


def get_total_pages():
    """
    取得目前年份的總頁數。

    分頁 HTML 通常有：
    <span class="paginate_of"> / 4</span>

    所以這個函式會從 "/ 4" 裡面抓出 4。
    """

    total_pages = 1

    spans = driver.find_elements(By.CSS_SELECTOR, "span.paginate_of")

    if spans:
        text = spans[0].text.strip()

        print("分頁文字：", text)

        match = re.search(r"/\s*(\d+)", text)

        if match:
            total_pages = int(match.group(1))

    return total_pages


# =========================
# 10. 解析目前頁面的資料
# =========================


def parse_current_page(year, page):
    """
    抓目前頁面的所有表格資料。

    傳入：
    year：目前正在抓的年份，只是用來印 log
    page：目前正在抓第幾頁，只是用來印 log

    回傳：
    page_data：list，裡面每一筆都是 dict
    """

    rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")

    print(f"\n========== {year} 年，第 {page} 頁 ==========")
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

        # 目前網站通常是：
        # cols[0]：序號
        # cols[1]：出售單位 + 發電設備
        # cols[2]：購買者
        # cols[3]：能源類型
        # cols[4]：移轉量(MWh)
        # cols[5]：憑證發放年份
        # cols[6]：移轉日期
        if len(cols) >= 7:
            seller_equipment = cols[1]
            buyer = cols[2]
            energy_type = cols[3]
            transfer_mwh = cols[4]
            certificate_year = cols[5]
            transfer_date = cols[6]

        # 備用判斷：如果某天網站拿掉序號欄，就使用這個結構
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

        # 拆「出售單位 / 發電設備」
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
# 11. 點下一頁
# =========================


def click_next_page():
    """
    點擊下一頁。

    下一頁按鈕通常是：
    <button class="next item ui button"></button>

    成功換頁：回傳 True
    失敗或已經最後一頁：回傳 False
    """

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

    print("目前頁碼：", old_page_value)

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
# 12. 定期重啟瀏覽器，避免 Cloud Run 記憶體累積
# =========================


def restart_browser_and_return_to_page(year, target_page):
    """
    長時間爬很多頁時，定期重啟瀏覽器釋放記憶體。

    重啟後要做三件事：
    1. 回到目標網址
    2. 重新選擇目前年份
    3. 從第 1 頁一路點下一頁，快轉到 target_page

    這段是延續 Cloud Run 模板裡的「定期重啟瀏覽器」概念。
    """

    global driver, wait

    print("\n==============================")
    print(f"已爬到第 {target_page - 1} 頁，準備重啟瀏覽器釋放記憶體")
    print("==============================")

    try:
        if driver:
            driver.quit()
    except Exception:
        pass

    create_driver()
    driver.get(TARGET_URL)
    time.sleep(5)

    wait_table_loaded()
    select_year(year)

    print(f"正在快轉回 {year} 年第 {target_page} 頁")

    for _ in range(target_page - 1):
        success = click_next_page()
        if not success:
            print("快轉失敗，可能已經沒有下一頁")
            return False

    print(f"快轉完成，準備繼續爬取 {year} 年第 {target_page} 頁")
    return True


# =========================
# 13. 存年度 CSV
# =========================


def save_year_csv(year, data):
    """
    存單一年份的 CSV。

    例如 year = "2026"
    就會存成：
    自用發電設備憑證成交紀錄_2026.csv

    注意：
    這裡使用 open(..., "w")。
    如果同名檔案已經存在，會直接覆蓋。
    這是故意的，因為今年資料每次重抓時，要用最新資料覆蓋舊資料。
    """

    filename = f"{CSV_PREFIX}_{year}.csv"
    local_path = os.path.join(LOCAL_WORKDIR, filename)

    with open(local_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(data)

    print("\nCSV 存檔完成")
    print("年份：", year)
    print("檔名：", filename)
    print("資料筆數：", len(data))
    print("存放位置：", os.path.abspath(local_path))

    return local_path


# =========================
# 14. 合併年度 CSV 成 all.csv
# =========================


def merge_year_csv():
    """
    把所有年度 CSV 合併成 all.csv。

    Cloud Run 版本會合併 LOCAL_WORKDIR 裡的年度 CSV。
    這些檔案包含：
    1. 從 GCS 下載回來的舊年度 CSV
    2. 本次新抓或重抓的年度 CSV

    最後產生：
    自用發電設備憑證成交紀錄_all.csv
    """

    print("\n==============================")
    print("開始合併年度 CSV")
    print("==============================")

    csv_files = glob.glob(os.path.join(LOCAL_WORKDIR, f"{CSV_PREFIX}_*.csv"))

    # 排除 all.csv，避免 all.csv 自己又被拿進來合併，造成重複
    csv_files = [file for file in csv_files if os.path.basename(file) != ALL_CSV_FILE]

    if not csv_files:
        print("找不到年度 CSV，無法合併 all.csv")
        return None

    csv_files = sorted(csv_files, reverse=True)

    print("準備合併以下檔案：")
    for file in csv_files:
        print(file)

    df_list = []

    for file in csv_files:
        df = pd.read_csv(file)
        df_list.append(df)

    all_df = pd.concat(df_list, ignore_index=True)

    # 去除完全重複的資料列
    all_df = all_df.drop_duplicates()

    all_csv_path = os.path.join(LOCAL_WORKDIR, ALL_CSV_FILE)

    all_df.to_csv(all_csv_path, index=False, encoding="utf-8-sig")

    print("\n==============================")
    print("all.csv 合併完成")
    print("==============================")
    print("檔名：", ALL_CSV_FILE)
    print("總資料筆數：", len(all_df))
    print("存放位置：", os.path.abspath(all_csv_path))

    return all_csv_path


# =========================
# 15. 主程式
# =========================


def main():
    """
    主流程：
    1. 建立 GCS client
    2. 先從 GCS 下載既有年度 CSV 到 /tmp
    3. 建立 Cloud Run Selenium 瀏覽器
    4. 讀取網站可選年份
    5. 判斷這次要抓哪些年份
    6. 逐年逐頁爬取
    7. 合併 all.csv
    8. 上傳年度 CSV 與 all.csv 到 GCS
    """

    global driver

    print("\n==============================")
    print("T-REC 自用發電設備憑證成交紀錄爬蟲啟動")
    print("==============================")
    print("本地暫存資料夾：", LOCAL_WORKDIR)
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)
    print("MANUAL_YEARS_TO_CRAWL：", MANUAL_YEARS_TO_CRAWL)
    print("MAX_PAGES_PER_YEAR：", MAX_PAGES_PER_YEAR)
    print("RESTART_EVERY_PAGES：", RESTART_EVERY_PAGES)

    storage_client = create_storage_client()

    # Cloud Run 每次啟動本地檔案可能是空的，先把 GCS 既有年度 CSV 下載回來
    download_existing_year_csv_from_gcs(storage_client)

    try:
        # 建立瀏覽器
        create_driver()

        # 前往目標網址
        print(f"正在前往目標網頁：{TARGET_URL}", flush=True)
        driver.get(TARGET_URL)

        # 先等網頁初始資料載入完成
        wait_table_loaded()

        # 第一步：自動抓網站上有哪些年份
        available_years = get_available_years()

        # 第二步：檢查本地暫存資料夾已經有哪些年度 CSV
        # 這些通常是剛剛從 GCS 下載下來的檔案
        existing_years = get_existing_years()

        # 第三步：決定這次要抓哪些年份
        years_to_crawl = decide_years_to_crawl(available_years, existing_years)

        if not years_to_crawl:
            print("\n所有年份都已經有年度 CSV，本次不需要爬新年份")

        else:
            for year in years_to_crawl:
                # 切換到指定年份
                select_year(year)

                # 取得該年份總頁數
                total_pages = get_total_pages()

                # 測試用：限制每年最多抓幾頁
                if MAX_PAGES_PER_YEAR > 0:
                    total_pages = min(total_pages, MAX_PAGES_PER_YEAR)
                    print(f"測試模式：本年度最多只抓 {MAX_PAGES_PER_YEAR} 頁")

                print("==============================")
                print(f"{year} 年總頁數：", total_pages)
                print("==============================")

                year_data = []

                for page in range(1, total_pages + 1):
                    # Cloud Run 長時間跑很多頁時，定期重啟瀏覽器釋放記憶體
                    if (
                        RESTART_EVERY_PAGES > 0
                        and page > 1
                        and (page - 1) % RESTART_EVERY_PAGES == 0
                    ):
                        success = restart_browser_and_return_to_page(year, page)
                        if not success:
                            print(f"{year} 年重啟後無法回到第 {page} 頁，提前停止")
                            break

                    # 每一頁抓之前，都先確認表格載入完成
                    wait_table_loaded()

                    # 解析目前頁面資料
                    page_data = parse_current_page(year, page)

                    # 把目前頁面資料加入該年份資料
                    year_data.extend(page_data)

                    print(f"{year} 年第 {page} 頁完成")
                    print(f"{year} 年目前累積：{len(year_data)} 筆")

                    # 如果還沒到最後一頁，就點下一頁
                    if page < total_pages:
                        success = click_next_page()

                        if not success:
                            print(f"{year} 年無法前往下一頁，提前停止")
                            break

                # 這一年全部抓完後，存成年度 CSV
                save_year_csv(year, year_data)

        # 不管這次有沒有新抓資料，都重新合併一次 all.csv
        merge_year_csv()

    except Exception as e:
        print("\n爬取過程發生錯誤：", repr(e), flush=True)
        raise

    finally:
        print("\n關閉瀏覽器...", flush=True)
        try:
            if driver:
                driver.quit()
        except Exception:
            pass

    # 爬完與合併後，上傳 CSV 到 GCS
    upload_csv_files_to_gcs(storage_client)

    print("\n==============================")
    print("T-REC 自用發電設備憑證成交紀錄爬蟲完成")
    print("==============================")


if __name__ == "__main__":
    main()

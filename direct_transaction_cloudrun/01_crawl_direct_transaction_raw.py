"""
T-REC 直轉供憑證成交紀錄爬蟲
適用於 Cloud Run Jobs + Selenium + Cloud Storage

重點：
1. 預設只抓 2026 年。
2. 抓完整年份、完整頁數、完整筆數。
3. 每一筆都點「詳情」，解析成交日期與成交移轉量。
4. 成功資料只寫 raw CSV，不寫 status CSV。
5. status CSV 只記錄「目前沒有資料」。
6. failed CSV 只記錄真正爬蟲失敗。
7. 成功資料每 10 頁存一次，並上傳 GCS。
8. 每一年結束一定再存一次，並上傳 GCS。
9. 失敗資料一失敗就存，並上傳 GCS。
10. except 裡會再存一次；finally 主要關閉 browser。
11. 不做 checkpoint；重新從第 1 頁跑；raw 階段保留網站原始資料，不去重複。
12. all_year 不是只存本次年份，而是合併各年份最新年度 raw；更新某一年時，只替換該年份，保留其他年份。
13. failed CSV 使用固定檔名 trec_direct_transaction_raw_failed.csv；每次 01 重新跑會覆蓋舊失敗清單。

可用環境變數：
- GCS_BUCKET：GCS bucket 名稱，例如 clawer-test 或 tibame-bronze
- GCS_PREFIX：上傳到 bucket 內的資料夾，例如 raw_data/t_rec/direct_transaction
- YEARS_TO_CRAWL：指定年份，預設 2026，例如 2026 或 2026,2025
- SAVE_EVERY_PAGES：每幾頁存一次，預設 10
- MAX_PAGES_PER_YEAR：測試用，每年最多抓幾頁，0 代表全部，預設 0
- LOCAL_WORKDIR：本地暫存資料夾，Cloud Run 預設 /tmp
"""

from __future__ import annotations

import csv
import glob
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from google.cloud import storage
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# =========================
# 網站設定
# =========================

START_URL = "https://www.trec.org.tw/certification_trade_situation/direct_supply"


# =========================
# Cloud Run / 執行設定
# =========================

# 預設只抓 2026；如果 Cloud Run 環境變數 YEARS_TO_CRAWL 有設定，就用環境變數。
TARGET_YEARS = [
    year.strip()
    for year in os.getenv("YEARS_TO_CRAWL", "2026").split(",")
    if year.strip()
]

SAVE_EVERY_PAGES = int(os.getenv("SAVE_EVERY_PAGES", "10"))
MAX_PAGES_PER_YEAR = int(os.getenv("MAX_PAGES_PER_YEAR", "0"))
PAGE_SLEEP_SECONDS = int(os.getenv("PAGE_SLEEP_SECONDS", "5"))

RUN_DATE = datetime.now().strftime("%Y%m%d")
RUN_DATE_SHORT = datetime.now().strftime("%m%d")

# Cloud Run 本機檔案要放 /tmp；本機測試時會用系統暫存資料夾。
LOCAL_WORKDIR = os.getenv("LOCAL_WORKDIR", tempfile.gettempdir())
os.makedirs(LOCAL_WORKDIR, exist_ok=True)

# Cloud Storage 設定
GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()
GCS_PREFIX = os.getenv("GCS_PREFIX", "raw_data/t_rec/direct_transaction").strip("/")


# =========================
# CSV 檔案設定
# =========================

RAW_PREFIX = "trec_direct_transaction_raw"

# 檔名設計：
# 1. 年度 raw 使用短日期，避免覆蓋同一年不同日期的原始資料。
#    例如：trec_direct_transaction_raw_2026_0612.csv
#
# 2. all_year 使用固定檔名。
#    例如：trec_direct_transaction_raw_all_year.csv
#
# 3. failed 使用固定檔名。
#    例如：trec_direct_transaction_raw_failed.csv
#    因為 01 每次都是重新從第 1 頁完整跑，failed 只代表「本次失敗清單」。
#    下次重新跑 01 時，新的 failed 會直接覆蓋舊的 failed。
#
# 注意：
# all_year 不是只存「本次抓到的年份」。
# 每次存檔時會重新合併各年份最新年度 raw。
# 例如：
# - 先抓 2026，all_year 會有 2026。
# - 下次抓 2025，all_year 會變成 2026 + 2025。
# - 再次更新 2026，all_year 會變成新版 2026 + 2025，其他年份保留。
ALL_YEARS_RAW_CSV_NAME = f"{RAW_PREFIX}_all_year.csv"
STATUS_CSV_NAME = f"{RAW_PREFIX}_status_{RUN_DATE}.csv"
FAILED_CSV_NAME = f"{RAW_PREFIX}_failed.csv"


def get_year_raw_csv_name(year: str) -> str:
    return f"{RAW_PREFIX}_{year}_{RUN_DATE_SHORT}.csv"


def local_path(filename: str) -> str:
    return os.path.join(LOCAL_WORKDIR, filename)


all_years_raw_csv_file = local_path(ALL_YEARS_RAW_CSV_NAME)
status_csv_file = local_path(STATUS_CSV_NAME)
failed_csv_file = local_path(FAILED_CSV_NAME)

# 成功 raw 資料欄位順序固定
fieldnames = [
    "出售單位",
    "發電設備",
    "購買者",
    "能源類型",
    "供電種類",
    "總移轉量(MWh)",
    "成交日期",
    "成交移轉量(MWh)",
]

# status CSV 只記錄「目前沒有資料」
status_fieldnames = [
    "憑證發放年份",
    "頁數",
    "筆數",
    "狀態",
    "原因",
]

# failed CSV 只記錄真正爬蟲失敗
failed_fieldnames = [
    "憑證發放年份",
    "頁數",
    "筆數",
    "出售單位",
    "發電設備",
    "購買者",
    "原因",
]


# =========================
# 全域資料暫存
# =========================

raw_data: List[Dict[str, str]] = []

status_dict: Dict[Tuple[str, str, str], Dict[str, str]] = {}
failed_data: List[Dict[str, str]] = []

storage_client: Optional[storage.Client] = None
driver: Optional[webdriver.Chrome] = None
wait: Optional[WebDriverWait] = None


# =========================
# Cloud Run 專用：建立 Chrome
# =========================


def create_driver() -> webdriver.Chrome:
    """
    建立 Selenium Chrome 瀏覽器。

    Cloud Run / Docker 內會用：
    - /usr/bin/chromium
    - /usr/bin/chromedriver
    """

    global driver, wait

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-sync")
    chrome_options.add_argument("--metrics-recording-only")
    chrome_options.add_argument("--mute-audio")

    chrome_options.binary_location = "/usr/bin/chromium"
    service = Service("/usr/bin/chromedriver")

    driver = webdriver.Chrome(service=service, options=chrome_options)
    wait = WebDriverWait(driver, 20)
    return driver


# =========================
# GCS 相關函式
# =========================


def build_gcs_blob_name(filename: str) -> str:
    if GCS_PREFIX:
        return f"{GCS_PREFIX}/{filename}"
    return filename


def create_storage_client() -> storage.Client:
    if not GCS_BUCKET:
        raise ValueError(
            "沒有設定 GCS_BUCKET，請在 Cloud Run Job 環境變數設定 GCS_BUCKET"
        )
    return storage.Client()


def is_year_raw_filename(filename: str) -> bool:
    """
    判斷檔案是否是某一年的年度 raw。

    支援兩種格式：
    1. 新版短日期：
       trec_direct_transaction_raw_2026_0612.csv

    2. 舊版完整日期：
       trec_direct_transaction_raw_2026_20260612.csv

    這樣之前已經在 GCS 的舊年度 raw 也可以被拿來合併 all_year。
    """

    if re.fullmatch(rf"{re.escape(RAW_PREFIX)}_20\d{{2}}_\d{{4}}\.csv", filename):
        return True

    if re.fullmatch(rf"{re.escape(RAW_PREFIX)}_20\d{{2}}_\d{{8}}\.csv", filename):
        return True

    return False


def parse_year_raw_filename(filename: str) -> Optional[Tuple[str, str]]:
    """
    從年度 raw 檔名解析出：
    - 資料年份，例如 2026
    - 檔案日期，例如 0612 或 20260612

    回傳：
    ("2026", "0612")
    """

    match = re.fullmatch(
        rf"{re.escape(RAW_PREFIX)}_(20\d{{2}})_(\d{{4}}|\d{{8}})\.csv",
        filename,
    )

    if not match:
        return None

    return match.group(1), match.group(2)


def should_download_output_file(filename: str) -> bool:
    """
    Cloud Run 每次啟動 /tmp 是空的。

    這裡會下載：
    1. all_year 合併檔
    2. 各年份年度 raw

    用途不是 checkpoint，也不是去重複。
    用途是：重新產生 all_year 時，可以保留其他年份資料。

    注意：
    raw_data 本次執行仍然從空的開始。
    不會把舊 raw 載入 raw_data。
    """

    if filename == ALL_YEARS_RAW_CSV_NAME:
        return True

    if is_year_raw_filename(filename):
        return True

    return False


def download_existing_output_files_from_gcs() -> None:
    """
    從 GCS 下載既有年度 raw 到 /tmp。

    目的：
    - 不是 checkpoint
    - 不是去重複
    - 不會把舊資料塞回 raw_data

    只是為了重新產生 all_year 時，可以保留其他年份。
    例如這次只抓 2026，也可以把 GCS 上既有的 2025、2024 年度 raw 下載回來，
    最後 all_year 會合併成新版 2026 + 舊版 2025 + 舊版 2024。
    """

    assert storage_client is not None

    print("\n==============================")
    print("開始從 GCS 下載既有年度 raw")
    print("==============================")
    print("Bucket：", GCS_BUCKET)
    print("Prefix：", GCS_PREFIX)

    prefix = f"{GCS_PREFIX}/" if GCS_PREFIX else ""
    downloaded_count = 0

    for blob in storage_client.list_blobs(GCS_BUCKET, prefix=prefix):
        filename = os.path.basename(blob.name)

        if not should_download_output_file(filename):
            continue

        path = local_path(filename)

        if os.path.exists(path):
            continue

        print(f"下載：gs://{GCS_BUCKET}/{blob.name} -> {path}")
        blob.download_to_filename(path)

        # 盡量保留 GCS blob 的更新時間。
        # 後面選「同一年最新檔」時比較準。
        try:
            if blob.updated is not None:
                updated_ts = blob.updated.timestamp()
                os.utime(path, (updated_ts, updated_ts))
        except Exception:
            pass

        downloaded_count += 1

    print("已下載既有年度 raw 數量：", downloaded_count)


def upload_file_to_gcs(path: str) -> None:
    """
    上傳單一檔案到 GCS。
    """

    if not os.path.exists(path):
        return

    assert storage_client is not None

    filename = os.path.basename(path)
    blob_name = build_gcs_blob_name(filename)
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(path)

    print(f"已上傳：{path}")
    print(f"GCS位置：gs://{GCS_BUCKET}/{blob_name}")


def upload_output_files_to_gcs() -> None:
    """
    上傳目前本地 /tmp 裡的所有本爬蟲 CSV。
    """

    if storage_client is None:
        print("storage_client 尚未建立，略過 GCS 上傳")
        return

    print("\n==============================")
    print("開始上傳 CSV 到 GCS")
    print("==============================")

    candidates = []

    # 固定三份
    candidates.append(all_years_raw_csv_file)
    candidates.append(status_csv_file)
    candidates.append(failed_csv_file)

    # 年度 raw 檔
    candidates.extend(glob.glob(local_path(f"{RAW_PREFIX}_20*.csv")))

    uploaded = set()
    for path in sorted(candidates):
        if path in uploaded:
            continue
        uploaded.add(path)
        upload_file_to_gcs(path)

    print("CSV 上傳流程完成")


# =========================
# CSV / raw 儲存相關函式
# =========================


def clean_company_name(name) -> str:
    """
    清理公司名稱：
    1. 全形括號轉半形括號
    2. 去除前後空白
    3. 去除括號前後多餘空白
    """

    if name is None:
        return ""

    name = str(name).strip()
    name = name.replace("（", "(").replace("）", ")")
    name = re.sub(r"\s*\(\s*", "(", name)
    name = re.sub(r"\s*\)\s*", ")", name)
    return name


def normalize_raw_row(row: Dict[str, str]) -> Dict[str, str]:
    """
    統一 raw row 的格式。
    __year 是程式內部用，不寫入 CSV。
    """

    new_row = dict(row)

    new_row["出售單位"] = clean_company_name(new_row.get("出售單位", ""))
    new_row["發電設備"] = str(new_row.get("發電設備", "")).strip()
    new_row["購買者"] = clean_company_name(new_row.get("購買者", ""))
    new_row["能源類型"] = str(new_row.get("能源類型", "")).strip()
    new_row["供電種類"] = str(new_row.get("供電種類", "")).strip()
    new_row["總移轉量(MWh)"] = (
        str(new_row.get("總移轉量(MWh)", "")).strip().replace(",", "")
    )
    new_row["成交日期"] = str(new_row.get("成交日期", "")).strip()
    new_row["成交移轉量(MWh)"] = (
        str(new_row.get("成交移轉量(MWh)", "")).strip().replace(",", "")
    )

    return new_row


def make_raw_key(row: Dict[str, str]) -> Tuple[str, ...]:
    """
    保留這個函式只是為了未來需要比對資料時使用。

    注意：
    目前 01 raw 階段不會使用這個 key 去重複。
    raw 階段要保留網站原始資料。
    """

    row = normalize_raw_row(row)
    return tuple(row.get(col, "") for col in fieldnames)


def add_raw_row(row: Dict[str, str], counters: Optional[Dict[str, int]] = None) -> bool:
    """
    加入成功 raw 資料。

    注意：
    raw 階段不去重複。
    網站詳情裡解析出幾筆，就 append 幾筆。
    """

    row = normalize_raw_row(row)
    raw_data.append(row)

    if counters is not None:
        counters["raw_count"] = counters.get("raw_count", 0) + 1

    return True


def make_status_key(year, page, row_number) -> Tuple[str, str, str]:
    return (
        str(year).strip(),
        str(page).strip(),
        str(row_number).strip(),
    )


def read_csv_rows(path: str) -> List[Dict[str, str]]:
    if not os.path.exists(path):
        return []

    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_existing_raw_data_from_local_csv() -> None:
    """
    目前 01 不使用這個函式。

    原因：
    raw 階段要保留本次爬到的原始資料，不做 checkpoint、不去重複。
    舊資料只會透過 rebuild_all_year_csv() 合併到 all_year，
    不會塞回 raw_data。
    """

    print("01 raw 階段不載入舊 raw_data，略過 load_existing_raw_data_from_local_csv()")


def save_raw_csv(data: List[Dict[str, str]], csv_file: str) -> None:
    """
    儲存 raw CSV。

    注意：
    raw 階段不去重複。
    data 裡有幾筆，就寫幾筆。
    __year 只是程式內部用，不會寫入 CSV。
    """

    output_data = []

    for row in data:
        row = normalize_raw_row(row)
        output_data.append(row)

    temp_file = csv_file + ".tmp"

    with open(temp_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(output_data)

    os.replace(temp_file, csv_file)

    print("\n========== raw 成功資料已存檔 ==========")
    print("目前 raw 資料列數：", len(output_data))
    print("raw 檔案：", csv_file)


def save_year_raw_csv(data: List[Dict[str, str]], year: str) -> None:
    """
    儲存指定年份的年度 raw。

    檔名格式：
    trec_direct_transaction_raw_2026_0612.csv
    """

    year_data = []

    for row in data:
        if str(row.get("__year", "")) == str(year):
            year_data.append(row)

    year_csv_file = local_path(get_year_raw_csv_name(year))
    save_raw_csv(year_data, year_csv_file)


def find_latest_year_raw_files() -> Dict[str, str]:
    """
    找出每個年份最新的一份年度 raw。

    支援：
    - 新版：trec_direct_transaction_raw_2026_0612.csv
    - 舊版：trec_direct_transaction_raw_2026_20260612.csv

    回傳：
    {
        "2026": "/tmp/trec_direct_transaction_raw_2026_0612.csv",
        "2025": "/tmp/trec_direct_transaction_raw_2025_0612.csv",
    }
    """

    latest_by_year: Dict[str, str] = {}

    candidates = glob.glob(local_path(f"{RAW_PREFIX}_20*.csv"))

    for path in candidates:
        filename = os.path.basename(path)
        parsed = parse_year_raw_filename(filename)

        if parsed is None:
            continue

        year, date_part = parsed

        if year not in latest_by_year:
            latest_by_year[year] = path
            continue

        old_path = latest_by_year[year]
        old_filename = os.path.basename(old_path)
        old_parsed = parse_year_raw_filename(old_filename)

        # 優先用檔案修改時間判斷最新。
        # 如果時間相同，再用檔名日期判斷。
        try:
            new_mtime = os.path.getmtime(path)
            old_mtime = os.path.getmtime(old_path)
        except Exception:
            new_mtime = 0
            old_mtime = 0

        old_date_part = old_parsed[1] if old_parsed else ""

        if (new_mtime, date_part) > (old_mtime, old_date_part):
            latest_by_year[year] = path

    return latest_by_year


def rebuild_all_year_csv() -> None:
    """
    重新產生 all_year 合併 raw。

    這個檔案不是只存本次抓到的年份。
    它會合併「每個年份最新的一份年度 raw」。

    例如：
    - GCS 已有 2025、2024
    - 本次重新抓 2026
    - 則 all_year = 新版 2026 + 既有 2025 + 既有 2024

    這樣下次只更新 2026 時，不會把其他年份覆蓋掉。
    """

    latest_by_year = find_latest_year_raw_files()

    all_rows: List[Dict[str, str]] = []

    for year in sorted(latest_by_year.keys(), reverse=True):
        path = latest_by_year[year]
        print(f"合併年度 raw：{year} -> {path}")

        rows = read_csv_rows(path)

        for row in rows:
            row = normalize_raw_row(row)
            all_rows.append(row)

    temp_file = all_years_raw_csv_file + ".tmp"

    with open(temp_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(all_rows)

    os.replace(temp_file, all_years_raw_csv_file)

    print("\n========== all_year 合併 raw 已重建 ==========")
    print("合併年份數：", len(latest_by_year))
    print("合併後 raw 總列數：", len(all_rows))
    print("all_year 檔案：", all_years_raw_csv_file)


def save_raw_files(
    data: List[Dict[str, str]], current_year: Optional[str] = None
) -> None:
    """
    儲存 raw 檔案。

    設計重點：
    1. 先存本次正在抓的年度 raw。
    2. 再重新合併各年份最新年度 raw，產生 all_year。
    3. 不把舊 raw 塞回 raw_data，因此不會改變「本次從第 1 頁重抓」的邏輯。
    """

    if current_year is not None:
        save_year_raw_csv(data, current_year)

    rebuild_all_year_csv()


def save_status_csv() -> None:
    """
    儲存 status CSV。
    status 只存「目前沒有資料」，不存成功資料。
    """

    status_data = []

    for row in status_dict.values():
        if row.get("狀態", "") == "目前沒有資料":
            status_data.append(row)

    temp_file = status_csv_file + ".tmp"

    with open(temp_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=status_fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(status_data)

    os.replace(temp_file, status_csv_file)

    print("\n========== 無資料狀態已存檔 ==========")
    print("目前沒有資料紀錄筆數：", len(status_data))
    print("status 檔案：", status_csv_file)


def save_failed_csv(force_create_empty: bool = False) -> None:
    """
    儲存真正爬蟲失敗資料。

    force_create_empty=True 時，會建立只有表頭的 failed CSV，
    用來覆蓋 GCS 上可能殘留的舊 failed 檔。
    """

    if len(failed_data) == 0 and not force_create_empty:
        return

    temp_file = failed_csv_file + ".tmp"

    with open(temp_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=failed_fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(failed_data)

    os.replace(temp_file, failed_csv_file)

    print("\n========== 失敗資料已存檔 ==========")
    print("真正失敗筆數：", len(failed_data))
    print("失敗資料檔案：", failed_csv_file)


def save_everything(current_year: Optional[str], upload: bool = True) -> None:
    """
    統一存檔入口。
    """

    save_raw_files(raw_data, current_year)
    save_status_csv()
    save_failed_csv(force_create_empty=True)

    if upload:
        upload_output_files_to_gcs()


# =========================
# status / failed 記錄
# =========================


def record_no_data(year, page, row_number, reason) -> None:
    """
    記錄目前沒有資料。
    這不是爬蟲失敗。
    """

    print("\n========== 目前沒有資料 ==========")
    print("憑證發放年份：", year)
    print("頁數：", page)
    print("筆數：", row_number)
    print("原因：", reason)

    key = make_status_key(year, page, row_number)

    status_dict[key] = {
        "憑證發放年份": year,
        "頁數": page,
        "筆數": row_number,
        "狀態": "目前沒有資料",
        "原因": reason,
    }

    save_status_csv()
    upload_file_to_gcs(status_csv_file)


def record_failed(
    year,
    page,
    row_number,
    seller_name,
    generation_device,
    buyer,
    reason,
) -> None:
    """
    記錄真正爬蟲失敗。
    一失敗就馬上存 failed CSV，並上傳 GCS。
    """

    failed_row = {
        "憑證發放年份": year,
        "頁數": page,
        "筆數": row_number,
        "出售單位": clean_company_name(seller_name),
        "發電設備": generation_device,
        "購買者": clean_company_name(buyer),
        "原因": reason,
    }

    failed_data.append(failed_row)

    print("\n========== 已記錄真正爬蟲失敗 ==========")
    print(failed_row)

    save_failed_csv()
    upload_file_to_gcs(failed_csv_file)


# =========================
# Selenium 網頁操作函式
# =========================


def page_has_no_data(driver_obj: webdriver.Chrome) -> bool:
    try:
        body_text = driver_obj.find_element(By.TAG_NAME, "body").text

        no_data_keywords = [
            "目前沒有資料",
            "查無資料",
            "無資料",
            "沒有資料",
        ]

        for keyword in no_data_keywords:
            if keyword in body_text:
                return True

    except Exception:
        pass

    return False


def wait_table_or_no_data(
    driver_obj: webdriver.Chrome, wait_obj: WebDriverWait
) -> None:
    wait_obj.until(
        lambda d: page_has_no_data(d)
        or len(d.find_elements(By.CSS_SELECTOR, "tbody tr")) > 0
    )


def get_total_pages(driver_obj: webdriver.Chrome) -> Optional[int]:
    """
    精準抓目前年份的總頁數。

    網頁底部分頁 HTML 類似：
    <span class="paginate_of tw:mr-1">/ 642</span>

    流程：
    1. 切換到指定年份後呼叫這個函式。
    2. 直接抓 span.paginate_of。
    3. 讀到像「/ 642」這種文字。
    4. 用正規表示式取出 642。
    5. 回傳整數 642。
    """

    try:
        page_span = driver_obj.find_element(By.CSS_SELECTOR, "span.paginate_of")
        page_text = page_span.text.strip()

        print("分頁總頁數文字：", page_text)

        match = re.search(r"[／/]\s*(\d+)", page_text)

        if match:
            total_pages = int(match.group(1))
            print("解析後總頁數：", total_pages)
            return total_pages

    except Exception as e:
        print("抓 span.paginate_of 總頁數失敗：", e)

    return None


def get_year_dropdown(driver_obj: webdriver.Chrome):
    """
    找到「憑證發放年份」的下拉選單。
    沿用你原本比較寬鬆的抓法，避免 dropdown icon 點不到。
    """

    xpath_list = [
        "//*[normalize-space(text())='憑證發放年份']/following::div[contains(@class, 'dropdown')][1]",
        "//*[contains(normalize-space(text()), '憑證發放年份')]/following::div[contains(@class, 'dropdown')][1]",
    ]

    for xpath in xpath_list:
        elements = driver_obj.find_elements(By.XPATH, xpath)

        for element in elements:
            try:
                if element.is_displayed():
                    return element
            except Exception:
                pass

    dropdowns = driver_obj.find_elements(
        By.CSS_SELECTOR,
        "div.ui.selection.dropdown, div.ui.dropdown",
    )

    for dropdown in dropdowns:
        try:
            dropdown_text = dropdown.text.strip()
            dropdown_html = dropdown.get_attribute("innerHTML") or ""

            if re.search(r"\b20\d{2}\b", dropdown_text + " " + dropdown_html):
                return dropdown
        except Exception:
            pass

    if dropdowns:
        return dropdowns[0]

    raise Exception("找不到憑證發放年份下拉選單")


def open_year_dropdown(driver_obj: webdriver.Chrome, year_dropdown) -> None:
    driver_obj.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});",
        year_dropdown,
    )
    time.sleep(1)

    driver_obj.execute_script("arguments[0].click();", year_dropdown)
    time.sleep(1)

    try:
        driver_obj.execute_script(
            """
            if (window.jQuery && jQuery(arguments[0]).dropdown) {
                jQuery(arguments[0]).dropdown('show');
            }
            """,
            year_dropdown,
        )
        time.sleep(1)
    except Exception:
        pass


def get_all_years(driver_obj: webdriver.Chrome, wait_obj: WebDriverWait) -> List[str]:
    year_dropdown = get_year_dropdown(driver_obj)
    open_year_dropdown(driver_obj, year_dropdown)

    items = year_dropdown.find_elements(By.CSS_SELECTOR, ".menu .item")

    if not items:
        items = driver_obj.find_elements(
            By.CSS_SELECTOR,
            ".visible.menu .item, .menu.transition.visible .item, .menu .item",
        )

    years = []

    for item in items:
        try:
            text = item.text.strip()
            data_value = item.get_attribute("data-value") or ""
            combined_text = text + " " + data_value
            found_years = re.findall(r"\b(20\d{2})\b", combined_text)
            years.extend(found_years)
        except Exception:
            pass

    years = sorted(set(years), reverse=True)

    print("\n==================== 下拉選單抓到的年份 ====================")
    print(years)

    if not years:
        raise Exception("年份下拉選單有打開，但抓不到任何年份")

    try:
        driver_obj.execute_script("document.body.click();")
        time.sleep(1)
    except Exception:
        pass

    return years


def click_year(
    driver_obj: webdriver.Chrome, wait_obj: WebDriverWait, year: str
) -> None:
    print(f"\n========== 切換到憑證發放年份：{year} ==========")

    year_dropdown = get_year_dropdown(driver_obj)
    open_year_dropdown(driver_obj, year_dropdown)

    items = year_dropdown.find_elements(By.CSS_SELECTOR, ".menu .item")

    if not items:
        items = driver_obj.find_elements(
            By.CSS_SELECTOR,
            ".visible.menu .item, .menu.transition.visible .item, .menu .item",
        )

    target_item = None

    for item in items:
        try:
            text = item.text.strip()
            data_value = item.get_attribute("data-value") or ""

            if text == str(year) or data_value == str(year):
                target_item = item
                break
        except Exception:
            pass

    if target_item is None:
        raise Exception(f"下拉選單裡找不到年份：{year}")

    driver_obj.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});",
        target_item,
    )
    time.sleep(1)

    driver_obj.execute_script("arguments[0].click();", target_item)
    time.sleep(PAGE_SLEEP_SECONDS)

    wait_table_or_no_data(driver_obj, wait_obj)

    print(f"已切換年份：{year}")


def is_next_button_disabled(next_btn) -> bool:
    class_name = next_btn.get_attribute("class") or ""
    disabled_attr = next_btn.get_attribute("disabled")

    if "disabled" in class_name or disabled_attr is not None:
        return True

    return False


def close_active_modal_if_exists(driver_obj: webdriver.Chrome) -> None:
    try:
        close_buttons = driver_obj.find_elements(
            By.CSS_SELECTOR,
            ".ui.modal.active .actions .button",
        )

        if close_buttons:
            driver_obj.execute_script("arguments[0].click();", close_buttons[0])
            time.sleep(1)
    except Exception as e:
        print("嘗試關閉殘留彈窗失敗：", e)


def go_to_next_page(
    driver_obj: webdriver.Chrome,
    wait_obj: WebDriverWait,
    year: str,
    current_page: int,
) -> bool:
    try:
        next_btn = wait_obj.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "button.next.item.ui.button")
            )
        )
    except TimeoutException:
        record_failed(
            year=year,
            page=current_page,
            row_number=0,
            seller_name="",
            generation_device="",
            buyer="",
            reason="找不到下一頁按鈕",
        )
        return False

    if is_next_button_disabled(next_btn):
        print(f"年份 {year} 第 {current_page} 頁已經是最後一頁")
        return False

    driver_obj.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});",
        next_btn,
    )
    time.sleep(1)

    driver_obj.execute_script("arguments[0].click();", next_btn)
    time.sleep(PAGE_SLEEP_SECONDS)

    wait_table_or_no_data(driver_obj, wait_obj)

    return True


# =========================
# 爬資料主邏輯
# =========================


def crawl_current_page_all_rows(
    driver_obj: webdriver.Chrome,
    wait_obj: WebDriverWait,
    year: str,
    page: int,
    counters: Dict[str, int],
) -> None:
    """
    抓目前頁面的全部資料列。
    每一筆都會點「詳情」解析成交記錄。
    """

    print(
        f"\n==================== 年份 {year}，開始抓第 {page} 頁全部資料 ===================="
    )

    wait_table_or_no_data(driver_obj, wait_obj)
    time.sleep(2)

    if page_has_no_data(driver_obj):
        print(f"年份 {year} 第 {page} 頁目前沒有資料")
        record_no_data(
            year=year,
            page=page,
            row_number=0,
            reason=f"年份 {year} 第 {page} 頁顯示目前沒有資料",
        )
        return

    rows = driver_obj.find_elements(By.CSS_SELECTOR, "tbody tr")
    row_count = len(rows)

    print("目前頁面資料列數：", row_count)

    if row_count == 0:
        record_no_data(
            year=year,
            page=page,
            row_number=0,
            reason=f"年份 {year} 第 {page} 頁沒有資料列",
        )
        return

    for target_index in range(row_count):
        row_number = target_index + 1

        print(f"\n========== 年份 {year}，第 {page} 頁，第 {row_number} 筆 ==========")

        seller_name = ""
        generation_device = ""
        buyer = ""

        try:
            # 每次重新取得元素，避免 StaleElementReference 問題
            rows = driver_obj.find_elements(By.CSS_SELECTOR, "tbody tr")
            detail_buttons = driver_obj.find_elements(
                By.XPATH,
                '//button[contains(., "詳情")]',
            )

            if target_index >= len(rows):
                record_failed(
                    year=year,
                    page=page,
                    row_number=row_number,
                    seller_name="",
                    generation_device="",
                    buyer="",
                    reason="重新取得資料列時，資料列數不足",
                )
                continue

            if target_index >= len(detail_buttons):
                record_failed(
                    year=year,
                    page=page,
                    row_number=row_number,
                    seller_name="",
                    generation_device="",
                    buyer="",
                    reason="有資料列，但是沒有對應詳情按鈕",
                )
                continue

            row = rows[target_index]
            cols = row.find_elements(By.TAG_NAME, "td")

            if len(cols) < 6:
                record_failed(
                    year=year,
                    page=page,
                    row_number=row_number,
                    seller_name="",
                    generation_device="",
                    buyer="",
                    reason="表格欄位數不足，無法解析列表資料",
                )
                continue

            # 出售單位 + 發電設備在同一格
            seller_device_text = cols[1].text.strip()
            seller_device_lines = seller_device_text.splitlines()

            if len(seller_device_lines) > 0:
                seller_name = clean_company_name(seller_device_lines[0])
            else:
                seller_name = ""

            if len(seller_device_lines) > 1:
                generation_device = seller_device_lines[1].strip()
            else:
                generation_device = ""

            buyer = clean_company_name(cols[2].text.strip())
            energy_type = cols[3].text.strip()
            supply_type = cols[4].text.strip()
            total_transfer_mwh = cols[5].text.strip()

            print("出售單位：", seller_name)
            print("發電設備：", generation_device)
            print("購買者：", buyer)
            print("能源類型：", energy_type)
            print("供電種類：", supply_type)
            print("總移轉量(MWh)：", total_transfer_mwh)

            detail_btn = detail_buttons[target_index]

            driver_obj.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});",
                detail_btn,
            )
            time.sleep(1)

            try:
                driver_obj.execute_script("arguments[0].click();", detail_btn)

                modal = wait_obj.until(
                    EC.visibility_of_element_located(
                        (By.CSS_SELECTOR, ".ui.modal.active")
                    )
                )

                time.sleep(2)
                detail_text = modal.text.replace("\n關閉", "").strip()

            except TimeoutException:
                record_failed(
                    year=year,
                    page=page,
                    row_number=row_number,
                    seller_name=seller_name,
                    generation_device=generation_device,
                    buyer=buyer,
                    reason="詳情彈窗逾時，沒有成功開啟",
                )
                close_active_modal_if_exists(driver_obj)
                continue

            detail_lines = detail_text.splitlines()

            if "成交記錄" not in detail_lines:
                record_failed(
                    year=year,
                    page=page,
                    row_number=row_number,
                    seller_name=seller_name,
                    generation_device=generation_device,
                    buyer=buyer,
                    reason="詳情內沒有成交記錄，無法解析成交資料",
                )

            else:
                record_index = detail_lines.index("成交記錄")
                trade_records = detail_lines[record_index + 1 :]

                parsed_count = 0

                for record in trade_records:
                    record = record.strip()

                    if not record:
                        continue

                    print(record)

                    match = re.search(
                        r"於\s*(\d{4}-\d{2}-\d{2})\s*移轉\s*([\d,]+(?:\.\d+)?)\s*MWh",
                        record,
                    )

                    if match:
                        trade_date = match.group(1)
                        trade_mwh = match.group(2).replace(",", "")

                        new_row = {
                            "__year": year,
                            "出售單位": clean_company_name(seller_name),
                            "發電設備": generation_device,
                            "購買者": clean_company_name(buyer),
                            "能源類型": energy_type,
                            "供電種類": supply_type,
                            "總移轉量(MWh)": total_transfer_mwh,
                            "成交日期": trade_date,
                            "成交移轉量(MWh)": trade_mwh,
                        }

                        was_added = add_raw_row(new_row, counters=counters)

                        if was_added:
                            parsed_count += 1
                            print(
                                "raw 新增一列，目前本次新增 raw 總列數：",
                                counters["raw_count"],
                            )

                    else:
                        record_failed(
                            year=year,
                            page=page,
                            row_number=row_number,
                            seller_name=seller_name,
                            generation_device=generation_device,
                            buyer=buyer,
                            reason=f"成交記錄格式解析失敗：{record}",
                        )

                if parsed_count > 0:
                    print("此筆成功解析成交記錄筆數：", parsed_count)

            # 關閉彈出視窗
            try:
                close_btn = wait_obj.until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, ".ui.modal.active .actions .button")
                    )
                )

                driver_obj.execute_script("arguments[0].click();", close_btn)

                wait_obj.until(
                    EC.invisibility_of_element_located(
                        (By.CSS_SELECTOR, ".ui.modal.active")
                    )
                )

                time.sleep(1)

            except TimeoutException:
                print(
                    f"年份 {year}，第 {page} 頁，第 {row_number} 筆：關閉彈窗逾時，嘗試強制處理"
                )
                close_active_modal_if_exists(driver_obj)

        except Exception as e:
            record_failed(
                year=year,
                page=page,
                row_number=row_number,
                seller_name=seller_name,
                generation_device=generation_device,
                buyer=buyer,
                reason=f"未預期錯誤：{type(e).__name__}，{e}",
            )
            close_active_modal_if_exists(driver_obj)
            continue


def crawl_one_year_full(
    driver_obj: webdriver.Chrome,
    wait_obj: WebDriverWait,
    year: str,
    counters: Dict[str, int],
) -> None:
    """
    抓指定年份的全部頁數、全部資料列。
    """

    click_year(driver_obj, wait_obj, year)

    if page_has_no_data(driver_obj):
        record_no_data(
            year=year,
            page=1,
            row_number=0,
            reason="該年份頁面顯示目前沒有資料",
        )
        return

    total_pages = get_total_pages(driver_obj)

    if total_pages:
        print(f"\n年份 {year} 的網站總頁數：{total_pages}")
    else:
        print(f"\n年份 {year} 抓不到總頁數，會一直按下一頁直到不能按")

    if MAX_PAGES_PER_YEAR > 0 and total_pages:
        total_pages = min(total_pages, MAX_PAGES_PER_YEAR)
        print(f"測試模式：本年度最多只抓 {MAX_PAGES_PER_YEAR} 頁")

    current_page = 1

    while True:
        crawl_current_page_all_rows(
            driver_obj=driver_obj,
            wait_obj=wait_obj,
            year=year,
            page=current_page,
            counters=counters,
        )

        # 每 SAVE_EVERY_PAGES 頁存一次 raw 成功資料，並上傳 GCS
        if SAVE_EVERY_PAGES > 0 and current_page % SAVE_EVERY_PAGES == 0:
            print(
                f"\n========== 已完成第 {current_page} 頁，進行批次存檔與上傳 =========="
            )
            save_everything(current_year=year, upload=True)

        if total_pages and current_page >= total_pages:
            print(f"\n年份 {year} 已抓到最後一頁：第 {current_page} 頁")
            break

        can_next = go_to_next_page(
            driver_obj=driver_obj,
            wait_obj=wait_obj,
            year=year,
            current_page=current_page,
        )

        if not can_next:
            break

        current_page += 1

        if page_has_no_data(driver_obj):
            record_no_data(
                year=year,
                page=current_page,
                row_number=0,
                reason=f"年份 {year} 第 {current_page} 頁顯示目前沒有資料",
            )
            break

    # 每一年結束一定再存一次，並上傳 GCS
    print(f"\n========== 年份 {year} 抓取結束，進行年度最後存檔與上傳 ==========")
    save_everything(current_year=year, upload=True)


# =========================
# 主程式
# =========================


def main() -> int:
    global storage_client, driver, wait

    counters = {
        "raw_count": 0,
    }

    has_error = False
    error_message = ""
    all_years: List[str] = []
    years_to_crawl: List[str] = []
    current_year: Optional[str] = None

    print("\n==============================")
    print("T-REC 直轉供憑證成交紀錄 Cloud Run 爬蟲啟動")
    print("==============================")
    print("START_URL：", START_URL)
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR)
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)
    print("TARGET_YEARS：", TARGET_YEARS)
    print("SAVE_EVERY_PAGES：", SAVE_EVERY_PAGES)
    print("MAX_PAGES_PER_YEAR：", MAX_PAGES_PER_YEAR)
    print("RUN_DATE：", RUN_DATE)
    print("RUN_DATE_SHORT：", RUN_DATE_SHORT)

    try:
        storage_client = create_storage_client()

        # 下載 GCS 上既有的年度 raw。
        # 目的只是為了重建 all_year 時保留其他年份。
        # 注意：不會把舊 raw 載入 raw_data，也不會做 checkpoint。
        download_existing_output_files_from_gcs()
        # load_existing_raw_data_from_local_csv()  # raw 階段不載入舊資料

        driver = create_driver()
        assert wait is not None

        driver.get(START_URL)
        time.sleep(PAGE_SLEEP_SECONDS)

        # 指定抓所有年分
        all_years = get_all_years(driver, wait)

        if not all_years:
            raise Exception("抓不到任何憑證發放年份，請檢查網頁是否有正常載入")

        print("\n==================== 自動偵測到的年份 ====================")
        print(all_years)
        print("網站總共有", len(all_years), "個年份")

        # #指定抓預設年份
        # for target_year in TARGET_YEARS:
        #     if target_year in all_years:
        #         years_to_crawl.append(target_year)
        #     else:
        #         print("網站下拉選單找不到指定年份：", target_year)

        years_to_crawl = all_years

        if not years_to_crawl:
            raise Exception("指定要抓的年份都不存在於網站下拉選單")

        print("\n==================== 本次指定要抓的年份 ====================")
        print(years_to_crawl)

        for year in years_to_crawl:
            current_year = year
            crawl_one_year_full(
                driver_obj=driver,
                wait_obj=wait,
                year=year,
                counters=counters,
            )

        print("\n指定年份 raw 資料都已經跑完")

    except KeyboardInterrupt:
        has_error = True
        error_message = "你手動中斷程式 Ctrl + C"

        print("\n", error_message)
        print("先把目前已抓到的 raw 成功資料、無資料狀態、失敗資料存起來")

        save_everything(current_year=current_year, upload=True)

    except Exception as e:
        has_error = True
        error_message = f"{type(e).__name__}: {e}"

        print("\n程式發生錯誤類型：", type(e).__name__)
        print("程式發生錯誤內容：", e)
        print("先把目前已抓到的 raw 成功資料、無資料狀態、失敗資料存起來")

        try:
            save_everything(current_year=current_year, upload=True)
        except Exception as save_error:
            print("錯誤發生後存檔/上傳又失敗：", repr(save_error))

    finally:
        print("\n關閉瀏覽器...")
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    print("\n==================== 最後存檔與上傳 ====================")

    try:
        save_everything(current_year=current_year, upload=True)
    except Exception as final_save_error:
        has_error = True
        error_message = f"最後存檔/上傳失敗：{repr(final_save_error)}"
        print(error_message)

    print("\n第一階段 raw CSV 更新完成")
    print("網站偵測到年份：", all_years)
    print("本次指定抓取年份：", years_to_crawl)
    print("本次新增 raw 成功資料列數：", counters.get("raw_count", 0))
    print("目前 raw 總資料列數：", len(raw_data))
    print("目前沒有資料紀錄總共有", len(status_dict), "筆")
    print("真正失敗資料筆數：", len(failed_data))
    print("全部年份 raw CSV：", ALL_YEARS_RAW_CSV_NAME)
    print("status CSV：", STATUS_CSV_NAME)
    print("failed CSV：", FAILED_CSV_NAME)

    for year in years_to_crawl:
        print("年度 raw CSV：", get_year_raw_csv_name(year))

    if has_error:
        print(
            "注意：本次程式不是正常跑完，但目前已抓到的 raw 成功資料、無資料狀態、失敗資料已經存入 CSV 並嘗試上傳 GCS"
        )
        print("錯誤摘要：", error_message)
        return 1

    print("本次第一階段 raw 程式正常跑完")
    return 0


if __name__ == "__main__":
    sys.exit(main())

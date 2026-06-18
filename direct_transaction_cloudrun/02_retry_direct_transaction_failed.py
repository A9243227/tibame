"""
02_retry_direct_transaction_failed.py

用途：
Cloud Run Job 版本的「直轉供成交資料 failed retry」。

這支程式會做：
1. 讀取 failed CSV：
   - 預設讀 trec_direct_transaction_raw_failed.csv
   - 如果有設定 FAILED_CSV_FILE，就讀指定檔案
     例如：FAILED_CSV_FILE=trec_direct_transaction_raw_failed_retry.csv
2. 如果 Cloud Run 是單獨跑 02，會先從 GCS 下載需要的 failed/raw CSV。
3. 讀取 failed CSV 裡面的 年份 / 頁數 / 筆數。
4. 用 Selenium 重新打開 T-REC 網頁。
5. 切到指定年份。
6. 直接用頁碼 input 跳到指定頁數，最多嘗試 3 次。
7. 如果 3 次直接跳頁都失敗，就記錄 retry 失敗，不再用下一頁按鈕慢慢翻。
8. 點指定筆數的「詳情」，重新解析成交記錄。
9. retry 成功資料只補回年度 raw。
   不再另外產生 trec_direct_transaction_raw_retry_success.csv。
10. retry 結束後，重新合併各年份最新年度 raw，產生：
   trec_direct_transaction_raw_all_year.csv
11. retry 仍失敗資料會即時覆蓋重建：
   trec_direct_transaction_raw_failed_retry.csv
   這個檔案永遠代表「目前還沒補成功」的資料。
   只要成功一筆，就會從 failed_retry 移除並立刻上傳；
   只要失敗一筆，就會更新 failed_retry 並立刻上傳。

注意：
- 這支是 Cloud Run 用版本。
- 所有檔案都放在 LOCAL_WORKDIR，Cloud Run 預設是 /tmp。
- raw 階段仍然不去重複，成功補回幾筆，就寫幾筆。
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
from typing import Dict, List, Optional, Tuple

from google.cloud import storage
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# =========================
# 網站設定
# =========================

START_URL = "https://www.trec.org.tw/certification_trade_situation/direct_supply"


# =========================
# Cloud Run / 檔案設定
# =========================

RAW_PREFIX = "trec_direct_transaction_raw"

LOCAL_WORKDIR = os.getenv("LOCAL_WORKDIR", tempfile.gettempdir())
os.makedirs(LOCAL_WORKDIR, exist_ok=True)

GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()
GCS_PREFIX = os.getenv("GCS_PREFIX", "raw_data/t_rec/direct_transaction").strip("/")

# 指定要 retry 的 failed 檔。
# 不指定時，預設讀 trec_direct_transaction_raw_failed.csv。
# 第二次、第三次想繼續補 failed_retry 時，請設定：
# FAILED_CSV_FILE=trec_direct_transaction_raw_failed_retry.csv
FAILED_CSV_FILE = os.getenv("FAILED_CSV_FILE", "").strip()

PAGE_SLEEP_SECONDS = int(os.getenv("PAGE_SLEEP_SECONDS", "5"))

# 頁碼 input 直接跳頁最多嘗試幾次。
# 3 次都失敗後，就直接記錄到 failed_retry，不再用下一頁按鈕慢慢翻。
PAGE_JUMP_MAX_RETRIES = int(os.getenv("PAGE_JUMP_MAX_RETRIES", "3"))

RUN_DATE_SHORT = datetime.now().strftime("%m%d")


# =========================
# CSV 檔名
# =========================

ALL_YEARS_RAW_CSV_NAME = f"{RAW_PREFIX}_all_year.csv"
FAILED_CSV_FILENAME = f"{RAW_PREFIX}_failed.csv"
RETRY_FAILED_CSV_FILENAME = f"{RAW_PREFIX}_failed_retry.csv"


def get_year_raw_csv_name(year: str) -> str:
    """
    如果找不到既有年度 raw，就用本次日期建立年度 raw。
    例如：trec_direct_transaction_raw_2026_0612.csv
    """

    return f"{RAW_PREFIX}_{year}_{RUN_DATE_SHORT}.csv"


def local_path(filename: str) -> str:
    return os.path.join(LOCAL_WORKDIR, filename)


ALL_YEARS_RAW_CSV_FILE = local_path(ALL_YEARS_RAW_CSV_NAME)
FAILED_CSV_FILE_DEFAULT = local_path(FAILED_CSV_FILENAME)
RETRY_FAILED_CSV_FILE = local_path(RETRY_FAILED_CSV_FILENAME)


# =========================
# CSV 欄位設定
# =========================

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

failed_fieldnames = [
    "憑證發放年份",
    "頁數",
    "筆數",
    "出售單位",
    "發電設備",
    "購買者",
    "原因",
]


# 目前還沒補成功的資料。
# 注意：
# 這個 list 會即時覆蓋寫入 failed_retry.csv，不是 append 舊資料。
# 02 一開始會先放入所有待 retry 資料；
# 成功一筆就移除一筆，失敗一筆就更新原因並保留。
retry_failed_data: List[Dict[str, str]] = []

# 紀錄本次執行中，哪些 row 在 retry_one_row() 裡真的發生過失敗。
# 用途：如果同一筆資料有部分成交記錄成功、部分解析失敗，
# 就不要把它從 failed_retry.csv 移除。
retry_failed_keys_recorded_this_run = set()

storage_client: Optional[storage.Client] = None


# =========================
# Cloud Run 專用：建立 Chrome 瀏覽器
# =========================


def create_driver() -> webdriver.Chrome:
    """
    建立 Cloud Run / Docker 裡可用的 Selenium Chrome。

    Dockerfile 裡有安裝：
    - chromium
    - chromium-driver
    """

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

    chromium_path = os.getenv("CHROME_BINARY", "/usr/bin/chromium")
    chromedriver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")

    if os.path.exists(chromium_path):
        chrome_options.binary_location = chromium_path

    if os.path.exists(chromedriver_path):
        service = Service(chromedriver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
    else:
        driver = webdriver.Chrome(options=chrome_options)

    return driver


# =========================
# GCS 相關函式
# =========================


def create_storage_client() -> Optional[storage.Client]:
    """
    建立 GCS client。
    """

    if not GCS_BUCKET:
        print("沒有設定 GCS_BUCKET，略過 GCS 下載 / 上傳")
        return None

    return storage.Client()


def build_gcs_blob_name(filename: str) -> str:
    """
    組出 GCS blob 路徑。
    """

    if GCS_PREFIX:
        return f"{GCS_PREFIX}/{filename}"

    return filename


def download_from_gcs_if_missing(filename: str) -> str:
    """
    如果本地 /tmp 沒有檔案，就嘗試從 GCS 下載。
    """

    global storage_client

    local_file = local_path(filename)

    if os.path.exists(local_file):
        print("本地已存在，略過下載：", local_file)
        return local_file

    if storage_client is None:
        print("沒有 GCS client，無法下載：", filename)
        return local_file

    blob_name = build_gcs_blob_name(filename)
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(blob_name)

    if not blob.exists():
        print(f"GCS 找不到檔案，略過下載：gs://{GCS_BUCKET}/{blob_name}")
        return local_file

    print(f"下載：gs://{GCS_BUCKET}/{blob_name} -> {local_file}")
    blob.download_to_filename(local_file)

    try:
        if blob.updated is not None:
            updated_ts = blob.updated.timestamp()
            os.utime(local_file, (updated_ts, updated_ts))
    except Exception:
        pass

    return local_file


def upload_file_to_gcs(local_file: str) -> None:
    """
    上傳單一檔案到 GCS。
    """

    global storage_client

    if storage_client is None:
        return

    if not os.path.exists(local_file):
        return

    filename = os.path.basename(local_file)
    blob_name = build_gcs_blob_name(filename)

    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_file)

    print(f"已上傳：{local_file}")
    print(f"GCS位置：gs://{GCS_BUCKET}/{blob_name}")


def is_year_raw_filename(filename: str) -> bool:
    """
    判斷檔案是否是年度 raw。

    支援：
    - trec_direct_transaction_raw_2026_0612.csv
    - trec_direct_transaction_raw_2026_20260612.csv
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
    """

    match = re.fullmatch(
        rf"{re.escape(RAW_PREFIX)}_(20\d{{2}})_(\d{{4}}|\d{{8}})\.csv",
        filename,
    )

    if not match:
        return None

    return match.group(1), match.group(2)


def download_existing_year_raws_from_gcs() -> None:
    """
    從 GCS 下載既有年度 raw 和 all_year。

    目的：
    - retry 成功時，可以補回該年份最新年度 raw。
    - retry 結束時，可以重建 all_year，保留其他年份。
    """

    global storage_client

    if storage_client is None:
        print("沒有 GCS client，略過下載既有年度 raw")
        return

    print("\n========== 開始從 GCS 下載既有年度 raw ==========")
    print("Bucket：", GCS_BUCKET)
    print("Prefix：", GCS_PREFIX)

    prefix = f"{GCS_PREFIX}/" if GCS_PREFIX else ""
    downloaded_count = 0

    for blob in storage_client.list_blobs(GCS_BUCKET, prefix=prefix):
        filename = os.path.basename(blob.name)

        if filename != ALL_YEARS_RAW_CSV_NAME and not is_year_raw_filename(filename):
            continue

        local_file = local_path(filename)

        if os.path.exists(local_file):
            continue

        print(f"下載：gs://{GCS_BUCKET}/{blob.name} -> {local_file}")
        blob.download_to_filename(local_file)

        try:
            if blob.updated is not None:
                updated_ts = blob.updated.timestamp()
                os.utime(local_file, (updated_ts, updated_ts))
        except Exception:
            pass

        downloaded_count += 1

    print("下載既有年度 raw 數量：", downloaded_count)


def upload_retry_outputs_to_gcs() -> None:
    """
    上傳 retry 相關輸出。

    會上傳：
    - trec_direct_transaction_raw_all_year.csv
    - trec_direct_transaction_raw_YYYY_MMDD.csv
    - trec_direct_transaction_raw_failed_retry.csv

    不再上傳 retry_success，因為這版不產生 retry_success.csv。
    """

    if storage_client is None:
        print("沒有 GCS client，略過上傳")
        return

    print("\n========== 開始上傳 retry 相關 CSV 到 GCS ==========")

    candidates = []
    candidates.append(ALL_YEARS_RAW_CSV_FILE)
    candidates.append(RETRY_FAILED_CSV_FILE)

    candidates.extend(glob.glob(local_path(f"{RAW_PREFIX}_20*.csv")))

    uploaded = set()

    for file in sorted(candidates):
        if file in uploaded:
            continue

        uploaded.add(file)
        upload_file_to_gcs(file)

    print("retry 相關 CSV 上傳完成")


# =========================
# CSV / 資料處理函式
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
    統一 raw row 格式。
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


def read_csv_rows(path: str) -> List[Dict[str, str]]:
    if not os.path.exists(path):
        return []

    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def append_rows_to_csv(
    csv_file: str, rows: List[Dict[str, str]], fieldnames: List[str]
) -> None:
    """
    把 retry 成功的資料 append 到指定年度 raw。

    注意：
    raw 階段仍然不去重複。
    成功幾筆，就補幾筆。
    """

    if not rows:
        return

    file_exists = os.path.exists(csv_file)
    file_is_empty = (not file_exists) or os.path.getsize(csv_file) == 0

    with open(csv_file, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )

        if file_is_empty:
            writer.writeheader()

        normalized_rows = [normalize_raw_row(row) for row in rows]
        writer.writerows(normalized_rows)

    print("\n========== retry 成功資料已補進年度 raw ==========")
    print("補進筆數：", len(rows))
    print("檔案：", csv_file)


def find_latest_year_raw_files() -> Dict[str, str]:
    """
    找出每個年份最新的一份年度 raw。
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
        old_date_part = old_parsed[1] if old_parsed else ""

        try:
            new_mtime = os.path.getmtime(path)
            old_mtime = os.path.getmtime(old_path)
        except Exception:
            new_mtime = 0
            old_mtime = 0

        if (new_mtime, date_part) > (old_mtime, old_date_part):
            latest_by_year[year] = path

    return latest_by_year


def find_latest_year_raw_file(year: str) -> str:
    """
    找出指定年份最新的年度 raw。
    如果找不到，就建立本次日期的年度 raw 檔名。
    """

    latest_by_year = find_latest_year_raw_files()

    if str(year) in latest_by_year:
        return latest_by_year[str(year)]

    return local_path(get_year_raw_csv_name(str(year)))


def rebuild_all_year_csv() -> None:
    """
    重新產生 all_year 合併 raw。

    all_year = 各年份最新年度 raw 的合併檔。
    """

    latest_by_year = find_latest_year_raw_files()

    all_rows: List[Dict[str, str]] = []

    for year in sorted(latest_by_year.keys(), reverse=True):
        path = latest_by_year[year]
        print(f"合併年度 raw：{year} -> {path}")

        rows = read_csv_rows(path)

        for row in rows:
            all_rows.append(normalize_raw_row(row))

    temp_file = ALL_YEARS_RAW_CSV_FILE + ".tmp"

    with open(temp_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(all_rows)

    os.replace(temp_file, ALL_YEARS_RAW_CSV_FILE)

    print("\n========== all_year 合併 raw 已重建 ==========")
    print("合併年份數：", len(latest_by_year))
    print("合併後 raw 總列數：", len(all_rows))
    print("all_year 檔案：", ALL_YEARS_RAW_CSV_FILE)


def save_retry_failed_csv(force_create_empty: bool = True) -> None:
    """
    儲存 retry 後仍然失敗的資料。

    注意：
    這裡是覆蓋重建，不是 append。
    所以 failed_retry.csv 永遠只保存「目前還沒補成功」的資料。

    force_create_empty=True 時，即使沒有失敗資料，
    也會建立只有表頭的 failed_retry.csv。
    這樣可以覆蓋 GCS 上舊的 failed_retry.csv。
    """

    if len(retry_failed_data) == 0 and not force_create_empty:
        return

    temp_file = RETRY_FAILED_CSV_FILE + ".tmp"

    with open(temp_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=failed_fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(retry_failed_data)

    os.replace(temp_file, RETRY_FAILED_CSV_FILE)

    print("\n========== retry 仍失敗資料已存檔 ==========")
    print("retry 仍失敗筆數：", len(retry_failed_data))
    print("檔案：", RETRY_FAILED_CSV_FILE)


def make_retry_failed_key(year, page, row_number) -> Tuple[str, str, str]:
    """
    建立 failed_retry 判斷用 key。
    """

    return (
        str(year).strip(),
        str(page).strip(),
        str(row_number).strip(),
    )


def make_retry_failed_key_from_row(row: Dict[str, str]) -> Tuple[str, str, str]:
    """
    從 failed row 建立 key。
    """

    return make_retry_failed_key(
        row.get("憑證發放年份", ""),
        row.get("頁數", ""),
        row.get("筆數", ""),
    )


def normalize_retry_failed_row(row: Dict[str, str]) -> Dict[str, str]:
    """
    統一 failed_retry row 欄位。
    """

    return {
        "憑證發放年份": str(row.get("憑證發放年份", "")).strip(),
        "頁數": str(row.get("頁數", "")).strip(),
        "筆數": str(row.get("筆數", "")).strip(),
        "出售單位": clean_company_name(row.get("出售單位", "")),
        "發電設備": str(row.get("發電設備", "")).strip(),
        "購買者": clean_company_name(row.get("購買者", "")),
        "原因": str(row.get("原因", "")).strip(),
    }


def save_and_upload_retry_failed_csv() -> None:
    """
    立刻覆蓋寫入 failed_retry.csv，並立刻上傳 GCS。
    """

    save_retry_failed_csv(force_create_empty=True)
    upload_file_to_gcs(RETRY_FAILED_CSV_FILE)


def initialize_retry_failed_data(failed_rows: List[Dict[str, str]]) -> None:
    """
    02 一開始先把所有待 retry 資料放進 retry_failed_data。

    這樣就算 02 中途被取消 / timeout / 容器掛掉，
    failed_retry.csv 也不會只剩已處理失敗的資料，
    尚未處理的資料也會保留在 failed_retry.csv 裡。
    """

    retry_failed_data.clear()
    retry_failed_keys_recorded_this_run.clear()

    seen_keys = set()

    for row in failed_rows:
        normalized_row = normalize_retry_failed_row(row)
        key = make_retry_failed_key_from_row(normalized_row)

        # 年份 / 頁數 / 筆數 不完整的資料無法 retry，略過。
        if not key[0] or not key[1] or not key[2]:
            continue

        if key in seen_keys:
            continue

        seen_keys.add(key)
        retry_failed_data.append(normalized_row)

    print("\n========== 初始化 failed_retry 暫存 ==========")
    print("目前待 retry 筆數：", len(retry_failed_data))

    # 一開始就先寫入 GCS。
    # 這樣即使 02 剛開始就中斷，也不會遺失原本待 retry 清單。
    save_and_upload_retry_failed_csv()


def upsert_retry_failed_row(failed_row: Dict[str, str]) -> None:
    """
    新增或更新 failed_retry row。

    failed_retry.csv 是覆蓋重建，不是 append。
    同一個 年份 + 頁數 + 筆數 只保留一筆，原因會更新成最新失敗原因。
    """

    normalized_row = normalize_retry_failed_row(failed_row)
    key = make_retry_failed_key_from_row(normalized_row)

    retry_failed_keys_recorded_this_run.add(key)

    for index, old_row in enumerate(retry_failed_data):
        if make_retry_failed_key_from_row(old_row) == key:
            retry_failed_data[index] = normalized_row
            break
    else:
        retry_failed_data.append(normalized_row)

    save_and_upload_retry_failed_csv()


def remove_retry_failed_row(year, page, row_number) -> None:
    """
    retry 成功後，立刻從 failed_retry 清單移除該筆資料，並上傳 GCS。
    """

    target_key = make_retry_failed_key(year, page, row_number)
    old_count = len(retry_failed_data)

    retry_failed_data[:] = [
        row
        for row in retry_failed_data
        if make_retry_failed_key_from_row(row) != target_key
    ]

    if len(retry_failed_data) != old_count:
        print("\n========== retry 成功，已從 failed_retry 移除 ==========")
        print("憑證發放年份：", year)
        print("頁數：", page)
        print("筆數：", row_number)
        print("failed_retry 剩餘筆數：", len(retry_failed_data))
        save_and_upload_retry_failed_csv()


def was_retry_failed_recorded_this_run(year, page, row_number) -> bool:
    """
    判斷這筆資料在本次 retry 過程中是否有被記錄失敗。
    """

    key = make_retry_failed_key(year, page, row_number)
    return key in retry_failed_keys_recorded_this_run


def record_retry_failed(
    year,
    page,
    row_number,
    seller_name,
    generation_device,
    buyer,
    reason,
) -> None:
    """
    記錄 retry 後仍然失敗。

    這版會即時：
    1. 更新 retry_failed_data
    2. 覆蓋寫入 trec_direct_transaction_raw_failed_retry.csv
    3. 上傳到 GCS

    所以 02 中途被取消 / timeout 時，failed_retry.csv 仍會保留目前還沒補成功的資料。
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

    print("\n========== retry 仍然失敗，立即更新 failed_retry ==========")
    print(failed_row)

    upsert_retry_failed_row(failed_row)


# =========================
# failed CSV
# =========================


def get_failed_file_for_download() -> Optional[str]:
    """
    取得需要從 GCS 下載的 failed 檔名。
    """

    if FAILED_CSV_FILE:
        if os.path.isabs(FAILED_CSV_FILE):
            return None
        return FAILED_CSV_FILE

    return FAILED_CSV_FILENAME


def find_failed_csv() -> Optional[str]:
    """
    找 failed CSV。

    規則：
    1. 如果有指定 FAILED_CSV_FILE，優先用指定檔案。
       例如：trec_direct_transaction_raw_failed_retry.csv

    2. 沒指定時，固定用：
       trec_direct_transaction_raw_failed.csv

    注意：
    這版不再自動找 failed_YYYYMMDD.csv，
    避免誤讀舊的日期版 failed。
    """

    if FAILED_CSV_FILE:
        if os.path.isabs(FAILED_CSV_FILE):
            candidate = FAILED_CSV_FILE
        else:
            candidate = local_path(FAILED_CSV_FILE)

        if os.path.exists(candidate):
            return candidate

        print("找不到指定 failed CSV：", candidate)
        return None

    if os.path.exists(FAILED_CSV_FILE_DEFAULT):
        return FAILED_CSV_FILE_DEFAULT

    print("找不到 failed CSV：", FAILED_CSV_FILE_DEFAULT)
    print("代表本次爬蟲沒有失敗資料，略過 retry")
    return None


def load_failed_csv(failed_csv_file: Optional[str]) -> List[Dict[str, str]]:
    """
    讀取 failed CSV。
    """

    failed_rows: List[Dict[str, str]] = []

    if failed_csv_file is None:
        return failed_rows

    if not os.path.exists(failed_csv_file):
        print("找不到 failed CSV，略過 retry：", failed_csv_file)
        return failed_rows

    if os.path.getsize(failed_csv_file) == 0:
        print("failed CSV 是空的，不需要 retry")
        return failed_rows

    with open(failed_csv_file, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            failed_rows.append(row)

    print("讀取 failed CSV：", failed_csv_file)
    print("failed 總筆數：", len(failed_rows))

    return failed_rows


def group_failed_rows(
    failed_rows: List[Dict[str, str]],
) -> Dict[Tuple[str, int], List[Dict[str, object]]]:
    """
    依照 年份 + 頁數 分組。
    同一頁的失敗資料一起 retry。
    """

    groups: Dict[Tuple[str, int], List[Dict[str, object]]] = {}

    for row in failed_rows:
        year = str(row.get("憑證發放年份", "")).strip()
        page_text = str(row.get("頁數", "")).strip()
        row_text = str(row.get("筆數", "")).strip()

        if not year or not page_text or not row_text:
            continue

        try:
            page = int(page_text)
            row_number = int(row_text)
        except ValueError:
            continue

        key = (year, page)

        if key not in groups:
            groups[key] = []

        groups[key].append(
            {
                "year": year,
                "page": page,
                "row_number": row_number,
                "old_reason": row.get("原因", ""),
            }
        )

    return groups


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
    例如 span.paginate_of 文字是：/ 642
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


def find_page_input(driver_obj: webdriver.Chrome):
    """
    找頁碼輸入框。

    優先找 span.paginate_of 前面的 input。
    """

    xpath_list = [
        "//span[contains(@class, 'paginate_of')]/preceding::input[1]",
        "//input[contains(@class, 'paginate')]",
        "//input[@type='number']",
    ]

    for xpath in xpath_list:
        elements = driver_obj.find_elements(By.XPATH, xpath)

        for element in elements:
            try:
                if element.is_displayed() and element.is_enabled():
                    return element
            except Exception:
                pass

    css_list = [
        "input.paginate_input",
        "input[class*='paginate']",
        ".pagination input",
        "input[type='number']",
    ]

    for css in css_list:
        elements = driver_obj.find_elements(By.CSS_SELECTOR, css)

        for element in elements:
            try:
                if element.is_displayed() and element.is_enabled():
                    return element
            except Exception:
                pass

    return None


def get_current_page(driver_obj: webdriver.Chrome) -> Optional[int]:
    """
    從頁碼 input 讀目前頁數。
    """

    page_input = find_page_input(driver_obj)

    if page_input is None:
        return None

    try:
        value = (
            page_input.get_attribute("value")
            or page_input.get_attribute("aria-valuenow")
            or page_input.text
            or ""
        )
        value = str(value).strip()

        match = re.search(r"\d+", value)

        if match:
            return int(match.group(0))

    except Exception:
        pass

    return None


def jump_to_target_page_by_input(
    driver_obj: webdriver.Chrome,
    wait_obj: WebDriverWait,
    year: str,
    target_page: int,
) -> bool:
    """
    直接用頁碼 input 跳到指定頁。

    回傳 True：已確認跳到目標頁。
    回傳 False：本次跳頁失敗，交給外層決定是否重試。
    """

    page_input = find_page_input(driver_obj)

    if page_input is None:
        print("找不到頁碼輸入框，無法直接跳頁")
        return False

    try:
        driver_obj.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});",
            page_input,
        )
        time.sleep(1)

        try:
            page_input.clear()
        except Exception:
            pass

        driver_obj.execute_script(
            """
            const el = arguments[0];
            const value = arguments[1];

            el.focus();
            el.value = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            page_input,
            str(target_page),
        )

        time.sleep(0.5)

        page_input.send_keys(Keys.ENTER)
        time.sleep(PAGE_SLEEP_SECONDS)

        wait_table_or_no_data(driver_obj, wait_obj)

        current_page = get_current_page(driver_obj)

        if current_page == target_page:
            print(f"年份 {year} 已直接跳到第 {target_page} 頁")
            return True

        print(f"直接跳頁後讀到目前頁數：{current_page}，目標頁數：{target_page}")
        return False

    except Exception as e:
        print("直接跳頁失敗：", type(e).__name__, e)
        return False


def go_to_target_page(
    driver_obj: webdriver.Chrome,
    wait_obj: WebDriverWait,
    year: str,
    target_page: int,
) -> None:
    """
    前往指定頁。

    只使用頁碼 input 直接跳頁。
    最多嘗試 PAGE_JUMP_MAX_RETRIES 次。
    如果全部失敗，就丟出錯誤，讓該頁 failed rows 寫進 failed_retry。

    注意：
    不再用「下一頁按鈕一路翻」當備援，避免效率太低。
    """

    if page_has_no_data(driver_obj):
        raise Exception(f"年份 {year} 頁面顯示目前沒有資料")

    if target_page <= 1:
        return

    total_pages = get_total_pages(driver_obj)

    if total_pages is not None and target_page > total_pages:
        raise Exception(f"目標頁數 {target_page} 超過網站總頁數 {total_pages}")

    for attempt in range(1, PAGE_JUMP_MAX_RETRIES + 1):
        print(
            f"年份 {year} 嘗試直接跳到第 {target_page} 頁："
            f"第 {attempt}/{PAGE_JUMP_MAX_RETRIES} 次"
        )

        jumped = jump_to_target_page_by_input(
            driver_obj=driver_obj,
            wait_obj=wait_obj,
            year=year,
            target_page=target_page,
        )

        if jumped:
            return

        time.sleep(2)

    raise Exception(
        f"頁碼 input 直接跳頁失敗 {PAGE_JUMP_MAX_RETRIES} 次，"
        f"不再使用下一頁按鈕備援，無法前往第 {target_page} 頁"
    )


def get_year_dropdown(driver_obj: webdriver.Chrome):
    """
    找到「憑證發放年份」的下拉選單。
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
    """
    打開年份 dropdown。
    """

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


def click_year(
    driver_obj: webdriver.Chrome, wait_obj: WebDriverWait, year: str
) -> None:
    """
    打開年份下拉選單，點選指定年份。
    """

    print(f"\n========== retry 切換到憑證發放年份：{year} ==========")

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

    print(f"retry 已切換年份：{year}")


def is_next_button_disabled(next_btn) -> bool:
    class_name = next_btn.get_attribute("class") or ""
    disabled_attr = next_btn.get_attribute("disabled")

    if "disabled" in class_name or disabled_attr is not None:
        return True

    return False


def close_active_modal_if_exists(driver_obj: webdriver.Chrome) -> None:
    """
    如果畫面上還有 active 的彈窗，就嘗試關閉。
    """

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


# =========================
# retry 主邏輯
# =========================


def retry_one_row(
    driver_obj: webdriver.Chrome,
    wait_obj: WebDriverWait,
    year: str,
    page: int,
    row_number: int,
) -> List[Dict[str, str]]:
    """
    補抓指定年份、指定頁數、指定筆數。

    成功可能回傳多筆資料，
    因為一個詳情內可能有多筆成交記錄。
    """

    print(
        f"\n==================== retry 年份 {year}，第 {page} 頁，第 {row_number} 筆 ===================="
    )

    wait_table_or_no_data(driver_obj, wait_obj)
    time.sleep(2)

    if page_has_no_data(driver_obj):
        record_retry_failed(
            year=year,
            page=page,
            row_number=row_number,
            seller_name="",
            generation_device="",
            buyer="",
            reason="retry 時頁面顯示目前沒有資料",
        )
        return []

    rows = driver_obj.find_elements(By.CSS_SELECTOR, "tbody tr")
    detail_buttons = driver_obj.find_elements(By.XPATH, '//button[contains(., "詳情")]')

    target_index = row_number - 1

    if target_index < 0:
        record_retry_failed(
            year=year,
            page=page,
            row_number=row_number,
            seller_name="",
            generation_device="",
            buyer="",
            reason="retry 無法處理筆數 0，這通常是頁面級失敗，不是單筆資料失敗",
        )
        return []

    if target_index >= len(rows):
        record_retry_failed(
            year=year,
            page=page,
            row_number=row_number,
            seller_name="",
            generation_device="",
            buyer="",
            reason=f"retry 時第 {page} 頁只有 {len(rows)} 筆，不足第 {row_number} 筆",
        )
        return []

    if target_index >= len(detail_buttons):
        record_retry_failed(
            year=year,
            page=page,
            row_number=row_number,
            seller_name="",
            generation_device="",
            buyer="",
            reason="retry 時有資料列，但是沒有對應詳情按鈕",
        )
        return []

    seller_name = ""
    generation_device = ""
    buyer = ""

    try:
        row = rows[target_index]
        cols = row.find_elements(By.TAG_NAME, "td")

        if len(cols) < 6:
            record_retry_failed(
                year=year,
                page=page,
                row_number=row_number,
                seller_name="",
                generation_device="",
                buyer="",
                reason="retry 時表格欄位數不足，無法解析列表資料",
            )
            return []

        seller_device_text = cols[1].text.strip()
        seller_device_lines = seller_device_text.splitlines()

        if len(seller_device_lines) > 0:
            seller_name = clean_company_name(seller_device_lines[0])

        if len(seller_device_lines) > 1:
            generation_device = seller_device_lines[1].strip()

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
                EC.visibility_of_element_located((By.CSS_SELECTOR, ".ui.modal.active"))
            )

            time.sleep(2)

            detail_text = modal.text.replace("\n關閉", "").strip()

        except TimeoutException:
            record_retry_failed(
                year=year,
                page=page,
                row_number=row_number,
                seller_name=seller_name,
                generation_device=generation_device,
                buyer=buyer,
                reason="retry 時詳情彈窗逾時，沒有成功開啟",
            )
            close_active_modal_if_exists(driver_obj)
            return []

        detail_lines = detail_text.splitlines()

        if "成交記錄" not in detail_lines:
            record_retry_failed(
                year=year,
                page=page,
                row_number=row_number,
                seller_name=seller_name,
                generation_device=generation_device,
                buyer=buyer,
                reason="retry 時詳情內沒有成交記錄，無法解析成交資料",
            )
            return []

        record_index = detail_lines.index("成交記錄")
        trade_records = detail_lines[record_index + 1 :]

        success_rows: List[Dict[str, str]] = []

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
                    "出售單位": clean_company_name(seller_name),
                    "發電設備": generation_device,
                    "購買者": clean_company_name(buyer),
                    "能源類型": energy_type,
                    "供電種類": supply_type,
                    "總移轉量(MWh)": total_transfer_mwh,
                    "成交日期": trade_date,
                    "成交移轉量(MWh)": trade_mwh,
                }

                success_rows.append(new_row)

            else:
                record_retry_failed(
                    year=year,
                    page=page,
                    row_number=row_number,
                    seller_name=seller_name,
                    generation_device=generation_device,
                    buyer=buyer,
                    reason=f"retry 時成交記錄格式解析失敗：{record}",
                )

        if success_rows:
            print("\n========== retry 抓取成功 ==========")
            print("成功解析成交記錄筆數：", len(success_rows))

        return success_rows

    except Exception as e:
        record_retry_failed(
            year=year,
            page=page,
            row_number=row_number,
            seller_name=seller_name,
            generation_device=generation_device,
            buyer=buyer,
            reason=f"retry 未預期錯誤：{type(e).__name__}，{e}",
        )
        close_active_modal_if_exists(driver_obj)
        return []

    finally:
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

        except Exception:
            close_active_modal_if_exists(driver_obj)


# =========================
# 主程式
# =========================


def main() -> int:
    global storage_client

    print("\n========== 02 retry direct transaction failed 啟動 ==========")
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR)
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)
    print("PAGE_JUMP_MAX_RETRIES：", PAGE_JUMP_MAX_RETRIES)
    print(
        "FAILED_CSV_FILE：",
        FAILED_CSV_FILE if FAILED_CSV_FILE else "(未指定，使用預設 failed.csv)",
    )
    print("ALL_YEARS_RAW_CSV_NAME：", ALL_YEARS_RAW_CSV_NAME)
    print("RETRY_FAILED_CSV_FILENAME：", RETRY_FAILED_CSV_FILENAME)

    storage_client = create_storage_client()

    failed_file_to_download = get_failed_file_for_download()

    if failed_file_to_download:
        download_from_gcs_if_missing(failed_file_to_download)

    download_existing_year_raws_from_gcs()

    failed_csv_file = find_failed_csv()

    if failed_csv_file is None:
        print("\n========== retry 略過 ==========")
        print("沒有 failed CSV，代表沒有失敗資料需要補抓")
        save_retry_failed_csv(force_create_empty=True)
        upload_file_to_gcs(RETRY_FAILED_CSV_FILE)
        return 0

    failed_rows = load_failed_csv(failed_csv_file)

    if not failed_rows:
        print("\n========== retry 略過 ==========")
        print("failed CSV 沒有資料需要補抓")
        save_retry_failed_csv(force_create_empty=True)
        upload_file_to_gcs(RETRY_FAILED_CSV_FILE)
        return 0

    groups = group_failed_rows(failed_rows)

    if not groups:
        print("\n========== retry 略過 ==========")
        print("failed CSV 裡沒有可 retry 的年份 / 頁數 / 筆數")
        save_retry_failed_csv(force_create_empty=True)
        upload_file_to_gcs(RETRY_FAILED_CSV_FILE)
        return 0

    # 一開始先把所有待 retry 資料寫進 failed_retry.csv 並上傳。
    # 後續成功一筆就即時移除，失敗一筆就即時更新原因。
    initialize_retry_failed_data(failed_rows)

    print("\n========== retry 設定 ==========")
    print("failed CSV：", failed_csv_file)
    print("all_year CSV：", ALL_YEARS_RAW_CSV_FILE)
    print("retry 仍失敗 CSV：", RETRY_FAILED_CSV_FILE)
    print("retry 頁面組數：", len(groups))

    driver = None
    total_retry_success_count = 0

    try:
        driver = create_driver()
        wait = WebDriverWait(driver, 20)

        driver.get(START_URL)
        time.sleep(PAGE_SLEEP_SECONDS)

        current_year: Optional[str] = None

        # 依照 年份、頁數排序 retry
        for (year, page), rows in sorted(
            groups.items(), key=lambda x: (x[0][0], x[0][1])
        ):
            print(
                f"\n==================== 開始 retry 年份 {year} 第 {page} 頁，共 {len(rows)} 筆 ===================="
            )

            try:
                # 同一個年份如果連續處理，不用每頁都重新切年份。
                # 但為了避免頁面狀態混亂，年份變更時一定重新切。
                if current_year != year:
                    click_year(driver, wait, year)
                    current_year = year

                go_to_target_page(driver, wait, year, page)

            except Exception as e:
                for item in rows:
                    record_retry_failed(
                        year=year,
                        page=page,
                        row_number=item["row_number"],
                        seller_name="",
                        generation_device="",
                        buyer="",
                        reason=f"retry 無法前往指定頁面：{type(e).__name__}，{e}",
                    )
                continue

            for item in sorted(rows, key=lambda x: x["row_number"]):
                row_number = int(item["row_number"])

                success_rows = retry_one_row(
                    driver_obj=driver,
                    wait_obj=wait,
                    year=year,
                    page=page,
                    row_number=row_number,
                )

                if success_rows:
                    year_raw_csv_file = find_latest_year_raw_file(year)

                    append_rows_to_csv(
                        csv_file=year_raw_csv_file,
                        rows=success_rows,
                        fieldnames=fieldnames,
                    )

                    # retry 成功補回年度 raw 後，立刻上傳年度 raw。
                    # 這樣 02 中途被取消 / timeout 時，已成功補回的 raw 也比較不會遺失。
                    upload_file_to_gcs(year_raw_csv_file)

                    total_retry_success_count += len(success_rows)

                    if was_retry_failed_recorded_this_run(year, page, row_number):
                        print(
                            "這筆 retry 有部分失敗紀錄，保留在 failed_retry.csv：",
                            year,
                            page,
                            row_number,
                        )
                    else:
                        remove_retry_failed_row(year, page, row_number)

        print("\n========== retry 全部完成 ==========")
        print("retry 成功補抓資料筆數：", total_retry_success_count)
        print("retry 仍失敗資料筆數：", len(retry_failed_data))

        rebuild_all_year_csv()
        save_retry_failed_csv(force_create_empty=True)
        upload_retry_outputs_to_gcs()

        if len(retry_failed_data) == 0:
            print("failed_retry.csv 已清空，只保留表頭")
        else:
            print("retry 仍失敗 CSV：", RETRY_FAILED_CSV_FILE)

        print("02 retry 程式正常完成")
        return 0

    except Exception as e:
        print("\nretry 程式發生錯誤：", type(e).__name__, e)
        print("先重建 all_year，並上傳目前已產生的 CSV")

        try:
            rebuild_all_year_csv()
            save_retry_failed_csv(force_create_empty=True)
            upload_retry_outputs_to_gcs()
        except Exception as save_error:
            print("retry 錯誤後存檔/上傳又失敗：", repr(save_error))

        raise

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())

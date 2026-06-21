"""
02_retry_direct_transaction_failed_cloudrun_playwright.py

T-REC 直轉供憑證成交紀錄：Cloud Run Playwright + API failed retry 版

本版用途：
1. 執行於 Cloud Run Job；CSV 暫存於 /tmp，正式保存於 GCS。
2. 使用 Playwright 開首頁取得 Cookie / CSRF Token，再用 data API 與 detail API 補抓失敗資料。
3. 預設讀取 trec_direct_transaction_raw_failed.csv；可設定 FAILED_CSV_FILE 指定 failed_retry.csv 繼續補抓。
4. 筆數 = 0：整頁 data API 失敗，data API 最多重試 3 次；成功後處理本頁每一筆 detail。
5. 筆數 > 0：單筆 detail 失敗，只補該頁指定筆數。
6. detail 成交記錄 <ol></ol> 空白是正常沒有成交記錄，不算失敗、不重試。
7. retry 成功資料立即補進年度 raw、立即上傳 GCS、重建並上傳 all_year。
8. retry 仍失敗資料會立即覆蓋 failed_retry.csv 並上傳 GCS。
9. 02 不改寫 01 的 failed.csv；failed.csv 仍代表本次 01 的失敗清單。

Cloud Run 常用環境變數：
    GCS_BUCKET=tibame-bronze
    GCS_PREFIX=raw_data/t_rec/direct_transaction
    LOCAL_WORKDIR=/tmp
    FAILED_CSV_FILE=trec_direct_transaction_raw_failed.csv
    FAILED_CSV_FILE=trec_direct_transaction_raw_failed_retry.csv
    PAGE_LENGTH=10
    API_TIMEOUT_MS=30000
    DATA_API_RETRY_MAX=3
    DETAIL_API_RETRY_MAX=3
    API_RETRY_SLEEP_SECONDS=3
    HEADLESS=true
"""

from __future__ import annotations

import csv
import glob
import html
import os
import re
import sys
import time
import traceback
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import storage
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# =========================================================
# 1. 基本路徑設定
# =========================================================

# Cloud Run 容器裡的 /tmp 是暫存資料夾。
# Job 結束後不能當永久保存位置，因此重要 CSV 都要上傳到 GCS。
LOCAL_WORKDIR = Path(os.getenv("LOCAL_WORKDIR", "/tmp")).resolve()
LOCAL_WORKDIR.mkdir(parents=True, exist_ok=True)

# Cloud Storage 正式保存位置。
GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()
GCS_PREFIX = os.getenv(
    "GCS_PREFIX",
    "raw_data/t_rec/direct_transaction",
).strip("/")

# =========================================================
# 2. T-REC API 網址設定
# =========================================================

# 首頁網址：Playwright 會先打開它，用來取得 cookie / csrf token。
START_URL = "https://www.trec.org.tw/certification_trade_situation/direct_supply"

# 外層列表 API：用來抓某一年、某一頁的 10 筆列表資料。
DATA_API_URL = (
    "https://www.trec.org.tw/certification_trade_situation/direct_supply/data"
)

# 內層詳情 API：用來抓某一筆的成交日期、成交移轉量。
DETAIL_API_URL = (
    "https://www.trec.org.tw/certification_trade_situation/direct_supply/detail"
)


# =========================================================
# 3. 執行參數設定
# =========================================================

RAW_PREFIX = "trec_direct_transaction_raw"

# 年度 raw 檔案會帶今天日期，例如 trec_direct_transaction_raw_2026_0618.csv
RUN_DATE_SHORT = datetime.now().strftime("%m%d")

# DataTables 預設每頁 10 筆。
PAGE_LENGTH = int(os.getenv("PAGE_LENGTH", "10"))

# API 請求 timeout，單位是毫秒。
API_TIMEOUT_MS = int(os.getenv("API_TIMEOUT_MS", "30000"))

# data API 最多重試幾次。
# 你剛剛要求：整頁 data API 失敗時最多重試 3 次。
DATA_API_RETRY_MAX = int(os.getenv("DATA_API_RETRY_MAX", "3"))

# 每次 data API retry 之間等待幾秒，避免太密集打網站。
API_RETRY_SLEEP_SECONDS = float(os.getenv("API_RETRY_SLEEP_SECONDS", "3"))

# detail API 每一筆最多重試幾次。
# 預設 3 次：第 1 次失敗後，等待後再試第 2、3 次。
# detail 的 <ol></ol> 空白屬於「沒有成交記錄」，不會重試。
DETAIL_API_RETRY_MAX = int(os.getenv("DETAIL_API_RETRY_MAX", "3"))

# 預設無頭模式，不顯示瀏覽器。
# 如果要看畫面：$env:HEADLESS="false"
HEADLESS = os.getenv("HEADLESS", "true").lower() != "false"

# 若 Dockerfile 安裝系統 Chromium（通常是 /usr/bin/chromium），優先使用它。
# 路徑不存在時，改讓 Playwright 使用自己安裝的 Chromium。
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH = os.getenv(
    "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
    "/usr/bin/chromium",
).strip()

# 可指定 retry 哪一個 failed 檔。
# 預設讀 01 產生的 trec_direct_transaction_raw_failed.csv。
# 如果想繼續補 failed_retry：$env:FAILED_CSV_FILE="trec_direct_transaction_raw_failed_retry.csv"
FAILED_CSV_FILE_ENV = os.getenv("FAILED_CSV_FILE", "").strip()


# =========================================================
# 4. CSV 檔案名稱
# =========================================================

ALL_YEARS_RAW_CSV_NAME = f"{RAW_PREFIX}_all_year.csv"
FAILED_CSV_NAME = f"{RAW_PREFIX}_failed.csv"
RETRY_FAILED_CSV_NAME = f"{RAW_PREFIX}_failed_retry.csv"


def get_year_raw_csv_name(year: str) -> str:
    """
    如果找不到既有年度 raw，就用今天日期建立一份年度 raw。
    例如：trec_direct_transaction_raw_2026_0618.csv
    """
    return f"{RAW_PREFIX}_{year}_{RUN_DATE_SHORT}.csv"


def local_path(filename: str) -> Path:
    """
    組成本機 CSV 路徑。
    """
    return LOCAL_WORKDIR / filename


ALL_YEARS_RAW_CSV_FILE = local_path(ALL_YEARS_RAW_CSV_NAME)
FAILED_CSV_FILE_DEFAULT = local_path(FAILED_CSV_NAME)
RETRY_FAILED_CSV_FILE = local_path(RETRY_FAILED_CSV_NAME)


# =========================================================
# 5. CSV 欄位設定
# =========================================================

# 成功 raw 固定 8 欄。
FIELDNAMES = [
    "出售單位",
    "發電設備",
    "購買者",
    "能源類型",
    "供電種類",
    "總移轉量(MWh)",
    "成交日期",
    "成交移轉量(MWh)",
]

# failed / failed_retry 欄位。
FAILED_FIELDNAMES = [
    "憑證發放年份",
    "頁數",
    "筆數",
    "出售單位",
    "發電設備",
    "購買者",
    "原因",
]

# failed_retry.csv 不是 append，而是覆蓋重建。
# 這個 list 代表「目前仍然沒補成功」的資料。
retry_failed_data: List[Dict[str, str]] = []

# 這個 set 用來記錄本次執行中，哪些 key 有被記錄成失敗。
# key = (年份, 頁數, 筆數)
retry_failed_keys_recorded_this_run = set()

# main() 成功建立 GCS client 後才會有值。
storage_client: Optional[storage.Client] = None


# =========================================================
# 6. HTML / 文字清理工具
# =========================================================


class SimpleHTMLTextParser(HTMLParser):
    """
    把 HTML 轉成純文字用的小工具。

    detail API 回傳的是 HTML，不是 JSON。
    所以我們要把 <div>、<label>、<li> 等 HTML 標籤轉成可解析的文字。
    """

    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        # 遇到這些標籤時補換行，避免文字全部黏在一起。
        if tag.lower() in {"div", "br", "p", "li", "label", "ol"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        # 結束標籤也補換行。
        if tag.lower() in {"div", "p", "li", "label", "ol"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        # 真正的文字內容。
        if data:
            self.parts.append(data)


def html_to_text(value: Any) -> str:
    """
    HTML 字串轉純文字。
    """
    if value is None:
        return ""

    # html.unescape 會把 &nbsp;、&amp; 這類 HTML entity 還原。
    value = html.unescape(str(value))

    parser = SimpleHTMLTextParser()
    parser.feed(value)

    text = "".join(parser.parts)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def html_to_lines(value: Any) -> List[str]:
    """
    HTML 轉成一行一行的純文字 list。
    """
    return [line.strip() for line in html_to_text(value).splitlines() if line.strip()]


def clean_company_name(name: Any) -> str:
    """
    清理公司名稱：
    1. 全形括號轉半形括號。
    2. 去掉前後空白。
    3. 去掉括號前後多餘空白。
    """
    if name is None:
        return ""

    name = str(name).strip()
    name = name.replace("（", "(").replace("）", ")")
    name = re.sub(r"\s*\(\s*", "(", name)
    name = re.sub(r"\s*\)\s*", ")", name)
    return name


def clean_number(value: Any) -> str:
    """
    清理數字字串：去空白、去逗號。
    """
    if value is None:
        return ""
    return str(value).strip().replace(",", "")


def normalize_raw_row(row: Dict[str, str]) -> Dict[str, str]:
    """
    統一 raw row 格式。
    只整理格式，不去重複。
    """
    new_row = dict(row)
    new_row["出售單位"] = clean_company_name(new_row.get("出售單位", ""))
    new_row["發電設備"] = str(new_row.get("發電設備", "")).strip()
    new_row["購買者"] = clean_company_name(new_row.get("購買者", ""))
    new_row["能源類型"] = str(new_row.get("能源類型", "")).strip()
    new_row["供電種類"] = str(new_row.get("供電種類", "")).strip()
    new_row["總移轉量(MWh)"] = clean_number(new_row.get("總移轉量(MWh)", ""))
    new_row["成交日期"] = str(new_row.get("成交日期", "")).strip()
    new_row["成交移轉量(MWh)"] = clean_number(new_row.get("成交移轉量(MWh)", ""))
    return new_row


def normalize_failed_row(row: Dict[str, str]) -> Dict[str, str]:
    """
    統一 failed / failed_retry row 格式。
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


def preview_text(text: Optional[str], limit: int = 500) -> str:
    """
    API 失敗時，不要把整份 HTML 全部印出來。
    只取前面一小段，避免終端機爆掉。
    """
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...（後面省略）"


# =========================================================
# 7. GCS 讀寫工具
# =========================================================


def build_gcs_blob_name(filename: str) -> str:
    """組出 bucket 內的 object 名稱。"""
    return f"{GCS_PREFIX}/{filename}" if GCS_PREFIX else filename


def create_storage_client() -> storage.Client:
    """建立 GCS client；Cloud Run service account 必須有 bucket 讀寫權限。"""
    if not GCS_BUCKET:
        raise ValueError(
            "沒有設定 GCS_BUCKET，請在 Cloud Run Job 環境變數設定 bucket 名稱"
        )
    return storage.Client()


def upload_file_to_gcs(path: Path) -> None:
    """上傳 /tmp 中的一個 CSV 到 GCS。"""
    if not path.exists():
        return
    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法上傳 GCS")

    blob_name = build_gcs_blob_name(path.name)
    bucket = storage_client.bucket(GCS_BUCKET)
    bucket.blob(blob_name).upload_from_filename(str(path))

    print(f"已上傳 GCS：{path}")
    print(f"GCS 位置：gs://{GCS_BUCKET}/{blob_name}")


def is_year_raw_filename(filename: str) -> bool:
    """判斷是否為年度 raw；支援 MMDD 與 YYYYMMDD 日期格式。"""
    return bool(
        re.fullmatch(rf"{re.escape(RAW_PREFIX)}_20\d{{2}}_\d{{4}}\.csv", filename)
        or re.fullmatch(rf"{re.escape(RAW_PREFIX)}_20\d{{2}}_\d{{8}}\.csv", filename)
    )


def should_download_from_gcs(filename: str) -> bool:
    """
    02 在 Cloud Run 需要下載：
    - 所有年度 raw：retry 成功後補資料、重建 all_year 時需要。
    - all_year：保留供檢查，最後仍會重建。
    - failed.csv：預設 retry 輸入。
    - failed_retry.csv：可作為下一輪 retry 輸入，並保留仍未解決清單。
    """
    return (
        filename == ALL_YEARS_RAW_CSV_NAME
        or filename == FAILED_CSV_NAME
        or filename == RETRY_FAILED_CSV_NAME
        or is_year_raw_filename(filename)
    )


def download_existing_files_from_gcs() -> None:
    """從 GCS 下載 02 所需 CSV 到 /tmp。"""
    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法下載 GCS")

    prefix = f"{GCS_PREFIX}/" if GCS_PREFIX else ""
    downloaded_count = 0

    print("\n========== 02 從 GCS 下載必要 CSV ==========")
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)

    for blob in storage_client.list_blobs(GCS_BUCKET, prefix=prefix):
        filename = Path(blob.name).name
        if not should_download_from_gcs(filename):
            continue

        destination = local_path(filename)
        # 若 01→02 同一個 Job 串接，/tmp 裡已有本次檔案，就不覆蓋。
        if destination.exists():
            continue

        print(f"下載：gs://{GCS_BUCKET}/{blob.name} -> {destination}")
        blob.download_to_filename(str(destination))

        # 保留 GCS 更新時間，用於判斷同一年最新 raw。
        try:
            if blob.updated is not None:
                timestamp = blob.updated.timestamp()
                os.utime(destination, (timestamp, timestamp))
        except Exception as e:
            print("警告：無法保留 GCS 更新時間：", type(e).__name__, e)

        downloaded_count += 1

    print("已下載檔案數：", downloaded_count)


def upload_changed_raw_and_all_year(year_raw_file: Path) -> None:
    """
    retry 成功就立刻同步年度 raw 與 all_year。
    這樣 Job 中斷時，已補成功的資料也不會只留在 /tmp。
    """
    upload_file_to_gcs(year_raw_file)
    rebuild_all_year_csv()
    upload_file_to_gcs(ALL_YEARS_RAW_CSV_FILE)


# =========================================================
# 7. CSV 讀寫工具
# =========================================================


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    """
    讀 CSV 成 list[dict]。
    """
    if not path.exists():
        return []
    if path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv_atomic(
    path: Path, rows: List[Dict[str, str]], fieldnames: List[str]
) -> None:
    """
    安全寫入 CSV。

    寫法：
    1. 先寫到 .tmp 暫存檔。
    2. 寫完後 os.replace 覆蓋正式檔。

    這樣可以避免寫到一半程式中斷，正式 CSV 壞掉。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = path.with_suffix(path.suffix + ".tmp")

    with temp_file.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    os.replace(temp_file, path)


def append_rows_to_csv(csv_file: Path, rows: List[Dict[str, str]]) -> None:
    """
    retry 成功後，把資料補進指定年份最新年度 raw。

    raw 階段仍不去重複；成功幾列就補幾列。
    Cloud Run /tmp 是暫存，因此補成功後立即同步年度 raw 與 all_year 到 GCS。
    """
    if not rows:
        return

    file_exists = csv_file.exists()
    file_is_empty = (not file_exists) or csv_file.stat().st_size == 0
    csv_file.parent.mkdir(parents=True, exist_ok=True)

    # 新檔案寫 UTF-8 BOM，Excel 開啟中文不亂碼；既有檔案追加時不用再寫 BOM。
    encoding = "utf-8-sig" if file_is_empty else "utf-8"

    with csv_file.open("a", newline="", encoding=encoding) as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        if file_is_empty:
            writer.writeheader()
        writer.writerows([normalize_raw_row(row) for row in rows])

    print("\n========== retry 成功資料已補進年度 raw ==========")
    print("年度 raw：", csv_file)
    print("補進列數：", len(rows))

    upload_changed_raw_and_all_year(csv_file)


# =========================================================
# 8. 年度 raw / all_year 合併工具
# =========================================================


def parse_year_raw_filename(filename: str) -> Optional[Tuple[str, str]]:
    """
    從年度 raw 檔名解析資料年份與日期。

    支援：
    - trec_direct_transaction_raw_2026_0618.csv
    - trec_direct_transaction_raw_2026_20260618.csv
    """
    match = re.fullmatch(
        rf"{re.escape(RAW_PREFIX)}_(20\d{{2}})_(\d{{4}}|\d{{8}})\.csv",
        filename,
    )
    if not match:
        return None
    return match.group(1), match.group(2)


def find_latest_year_raw_files() -> Dict[str, Path]:
    """
    找出每一年最新的一份年度 raw。
    用來重建 all_year。
    """
    latest_by_year: Dict[str, Path] = {}

    for path_text in glob.glob(str(local_path(f"{RAW_PREFIX}_20*.csv"))):
        path = Path(path_text)
        parsed = parse_year_raw_filename(path.name)
        if parsed is None:
            continue

        year, date_part = parsed

        if year not in latest_by_year:
            latest_by_year[year] = path
            continue

        old_path = latest_by_year[year]
        old_parsed = parse_year_raw_filename(old_path.name)
        old_date_part = old_parsed[1] if old_parsed else ""

        # 優先用修改時間判斷最新；修改時間相同時，再用檔名日期判斷。
        if (path.stat().st_mtime, date_part) > (
            old_path.stat().st_mtime,
            old_date_part,
        ):
            latest_by_year[year] = path

    return latest_by_year


def find_latest_year_raw_file(year: str) -> Path:
    """
    找指定年份最新的年度 raw。
    如果找不到，就用今天日期建立新檔名。
    """
    latest_by_year = find_latest_year_raw_files()
    if str(year) in latest_by_year:
        return latest_by_year[str(year)]
    return local_path(get_year_raw_csv_name(str(year)))


def rebuild_all_year_csv() -> None:
    """
    重建 trec_direct_transaction_raw_all_year.csv。

    all_year = 每個年份最新年度 raw 的合併結果。
    """
    latest_by_year = find_latest_year_raw_files()
    all_rows: List[Dict[str, str]] = []

    for year in sorted(latest_by_year.keys(), reverse=True):
        path = latest_by_year[year]
        print(f"合併年度 raw：{year} -> {path}")
        for row in read_csv_rows(path):
            all_rows.append(normalize_raw_row(row))

    write_csv_atomic(ALL_YEARS_RAW_CSV_FILE, all_rows, FIELDNAMES)

    print("\n========== all_year 已重建 ==========")
    print("all_year 檔案：", ALL_YEARS_RAW_CSV_FILE)
    print("all_year 總列數：", len(all_rows))


# =========================================================
# 9. failed_retry 清單工具
# =========================================================


def make_failed_key(year: Any, page: Any, row_number: Any) -> Tuple[str, str, str]:
    """
    failed 判斷用 key。
    同一年、同一頁、同一筆，只保留一筆 failed_retry。
    """
    return str(year).strip(), str(page).strip(), str(row_number).strip()


def make_failed_key_from_row(row: Dict[str, str]) -> Tuple[str, str, str]:
    return make_failed_key(
        row.get("憑證發放年份", ""),
        row.get("頁數", ""),
        row.get("筆數", ""),
    )


def save_retry_failed_csv(force_create_empty: bool = True) -> None:
    """
    覆蓋寫入 failed_retry.csv。

    failed_retry 永遠代表「目前仍然沒補成功」的資料。
    每次清單變動都立即上傳 GCS，避免 Job 中斷時遺失 retry 狀態。
    """
    if not retry_failed_data and not force_create_empty:
        return

    write_csv_atomic(RETRY_FAILED_CSV_FILE, retry_failed_data, FAILED_FIELDNAMES)
    print("failed_retry CSV 已存檔：", RETRY_FAILED_CSV_FILE)
    print("retry 仍失敗筆數：", len(retry_failed_data))

    if storage_client is not None:
        upload_file_to_gcs(RETRY_FAILED_CSV_FILE)


def initialize_retry_failed_data(failed_rows: List[Dict[str, str]]) -> None:
    """
    02 一開始先把 failed.csv 全部放進 retry_failed_data。

    好處：
    如果 02 跑到一半中斷，failed_retry.csv 還會保留尚未補成功的資料。
    """
    retry_failed_data.clear()
    retry_failed_keys_recorded_this_run.clear()

    seen = set()

    for row in failed_rows:
        normalized = normalize_failed_row(row)
        key = make_failed_key_from_row(normalized)

        # 年份 / 頁數 / 筆數 不完整就無法 retry。
        if not key[0] or not key[1] or not key[2]:
            continue

        # 同一筆失敗資料只保留一次。
        if key in seen:
            continue

        seen.add(key)
        retry_failed_data.append(normalized)

    save_retry_failed_csv(force_create_empty=True)


def upsert_retry_failed_row(failed_row: Dict[str, str]) -> None:
    """
    新增或更新 failed_retry row。

    如果同一個 key 已存在，就更新原因。
    如果不存在，就新增。
    """
    normalized = normalize_failed_row(failed_row)
    key = make_failed_key_from_row(normalized)
    retry_failed_keys_recorded_this_run.add(key)

    for index, old_row in enumerate(retry_failed_data):
        if make_failed_key_from_row(old_row) == key:
            retry_failed_data[index] = normalized
            break
    else:
        retry_failed_data.append(normalized)

    save_retry_failed_csv(force_create_empty=True)


def remove_retry_failed_row(year: Any, page: Any, row_number: Any) -> None:
    """
    retry 成功或確認不是失敗後，從 failed_retry 清單移除。
    """
    key = make_failed_key(year, page, row_number)
    old_count = len(retry_failed_data)

    retry_failed_data[:] = [
        row for row in retry_failed_data if make_failed_key_from_row(row) != key
    ]

    if len(retry_failed_data) != old_count:
        print("retry 成功 / 已處理，從 failed_retry 移除：", key)
        save_retry_failed_csv(force_create_empty=True)


def record_retry_failed(
    year: Any,
    page: Any,
    row_number: Any,
    seller_name: str,
    generation_device: str,
    buyer: str,
    reason: str,
) -> None:
    """
    記錄 retry 後仍然失敗。
    """
    failed_row = {
        "憑證發放年份": str(year),
        "頁數": str(page),
        "筆數": str(row_number),
        "出售單位": clean_company_name(seller_name),
        "發電設備": generation_device,
        "購買者": clean_company_name(buyer),
        "原因": reason,
    }

    print("\n========== retry 仍失敗 ==========")
    print(failed_row)
    upsert_retry_failed_row(failed_row)


# =========================================================
# 10. failed CSV 讀取與分組
# =========================================================


def find_failed_csv() -> Optional[Path]:
    """
    找 02 要讀的 failed CSV。

    優先順序：
    1. 環境變數 FAILED_CSV_FILE 指定的檔案。
    2. 預設 trec_direct_transaction_raw_failed.csv。
    """
    if FAILED_CSV_FILE_ENV:
        path = Path(FAILED_CSV_FILE_ENV)
        if not path.is_absolute():
            path = local_path(FAILED_CSV_FILE_ENV)
        if path.exists():
            return path
        print("找不到指定 failed CSV：", path)
        return None

    if FAILED_CSV_FILE_DEFAULT.exists():
        return FAILED_CSV_FILE_DEFAULT

    print("找不到 failed CSV：", FAILED_CSV_FILE_DEFAULT)
    return None


def group_failed_rows(
    failed_rows: List[Dict[str, str]],
) -> Dict[Tuple[str, int], List[Dict[str, Any]]]:
    """
    依照 年份 + 頁數 分組。

    這樣同一頁的失敗資料可以一起處理。
    尤其是「筆數 = 0」的整頁失敗，可以一次補整頁。
    """
    groups: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}

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

        groups.setdefault((year, page), []).append(
            {
                "year": year,
                "page": page,
                "row_number": row_number,
            }
        )

    return groups


# =========================================================
# 11. detail HTML 解析
# =========================================================


def extract_detail_field(detail_html: str, label: str) -> str:
    """
    從 detail HTML 抓欄位。

    例如 label = 出售單位 / 發電設備 / 購買者。
    """
    pattern = rf"<label>\s*{re.escape(label)}\s*</label>\s*<div>(.*?)</div>"
    match = re.search(pattern, detail_html, flags=re.S)
    if not match:
        return ""
    return html_to_text(match.group(1)).strip()


def has_trade_record_section(detail_html: str) -> bool:
    """
    判斷 detail HTML 是否有「成交記錄」區塊。
    """
    return "成交記錄" in html_to_text(detail_html)


def is_trade_record_ol_empty(detail_html: str) -> bool:
    """
    判斷 detail 裡「成交記錄」的 <ol> 是否真的空白。

    True：
        <ol></ol>
        <ol>\n</ol>
        <ol>&nbsp;</ol>

    這代表網站正常回覆，只是沒有成交記錄。
    所以不算失敗，也不需要 retry。

    False：
        找不到 <ol>、<ol> 裡有文字、或結構不是空白。
        這些情況後續會交給 detail retry 判斷。
    """
    pattern = r"<label>\s*成交記錄\s*</label>.*?<ol[^>]*>(.*?)</ol>"
    match = re.search(pattern, detail_html, flags=re.S)

    if not match:
        return False

    # 將 ol 裡的 HTML 轉純文字後判斷是否真的是空白。
    ol_text = html_to_text(match.group(1)).strip()
    return ol_text == ""


def extract_trade_records(detail_html: str) -> List[Tuple[str, str]]:
    """
    從 detail HTML 抓成交記錄。

    格式範例：
    於 2026-04-15 移轉 34.025 MWh
    """
    text = html_to_text(detail_html)

    matches = re.findall(
        r"於\s*(\d{4}-\d{2}-\d{2})\s*移轉\s*([\d,]+(?:\.\d+)?)\s*MWh",
        text,
    )

    return [(trade_date, clean_number(trade_mwh)) for trade_date, trade_mwh in matches]


# =========================================================
# 12. API payload / headers
# =========================================================


def build_data_payload(year: str, page_number: int) -> Dict[str, str]:
    """
    建立外層 data API 的 form payload。

    DataTables 分頁邏輯：
    第 1 頁 start = 0
    第 2 頁 start = 10
    第 3 頁 start = 20
    """
    start = (page_number - 1) * PAGE_LENGTH

    return {
        "draw": str(page_number),
        "columns[0][data]": "DT_RowIndex",
        "columns[0][name]": "DT_RowIndex",
        "columns[0][searchable]": "false",
        "columns[0][orderable]": "false",
        "columns[0][search][value]": "",
        "columns[0][search][regex]": "false",
        "columns[1][data]": "seller_name",
        "columns[1][name]": "seller_name",
        "columns[1][searchable]": "false",
        "columns[1][orderable]": "true",
        "columns[1][search][value]": "",
        "columns[1][search][regex]": "false",
        "columns[2][data]": "buyer_name",
        "columns[2][name]": "buyer_name",
        "columns[2][searchable]": "false",
        "columns[2][orderable]": "true",
        "columns[2][search][value]": "",
        "columns[2][search][regex]": "false",
        "columns[3][data]": "energy",
        "columns[3][name]": "energy",
        "columns[3][searchable]": "false",
        "columns[3][orderable]": "true",
        "columns[3][search][value]": "",
        "columns[3][search][regex]": "false",
        "columns[4][data]": "parallel_type",
        "columns[4][name]": "parallel_type",
        "columns[4][searchable]": "false",
        "columns[4][orderable]": "true",
        "columns[4][search][value]": "",
        "columns[4][search][regex]": "false",
        "columns[5][data]": "power",
        "columns[5][name]": "power",
        "columns[5][searchable]": "false",
        "columns[5][orderable]": "true",
        "columns[5][search][value]": "",
        "columns[5][search][regex]": "false",
        "columns[6][data]": "detail",
        "columns[6][name]": "detail",
        "columns[6][searchable]": "false",
        "columns[6][orderable]": "false",
        "columns[6][search][value]": "",
        "columns[6][search][regex]": "false",
        "order[0][column]": "1",
        "order[0][dir]": "asc",
        "order[0][name]": "seller_name",
        "start": str(start),
        "length": str(PAGE_LENGTH),
        "search[value]": "",
        "search[regex]": "false",
        "year": str(year),
    }


def build_detail_payload(item: Dict[str, Any], year: str) -> Dict[str, str]:
    """
    建立 detail API payload。
    這四個值來自 data API 回傳資料。
    """
    return {
        "case_id": str(item.get("case_id", "")).strip(),
        "year": str(year).strip(),
        "buyer": str(item.get("buyer", "")).strip(),
        "seller": str(item.get("seller", "")).strip(),
    }


def get_csrf_token(page: Any) -> str:
    """
    從首頁 HTML 抓 csrf token。
    如果網站沒有提供，回傳空字串，程式仍會嘗試 API。
    """
    try:
        return (
            page.locator('meta[name="csrf-token"]').get_attribute(
                "content", timeout=3000
            )
            or ""
        )
    except Exception:
        return ""


def build_headers(csrf_token: str, accept: str) -> Dict[str, str]:
    """
    建立 API request headers。

    Cookie 不用手動放。
    Playwright context 打開首頁後，context.request 會沿用同一組 cookie。
    """
    headers = {
        "Accept": accept,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.trec.org.tw",
        "Referer": START_URL,
    }

    if csrf_token:
        headers["X-CSRF-TOKEN"] = csrf_token

    return headers


# =========================================================
# 13. API 呼叫工具
# =========================================================


def fetch_data_api_once(
    context: Any,
    csrf_token: str,
    year: str,
    page: int,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    呼叫 data API 一次。

    回傳：
    - 成功：(data_json, "")
    - 失敗：(None, 失敗原因)
    """
    payload = build_data_payload(year, page)

    try:
        response = context.request.post(
            DATA_API_URL,
            form=payload,
            headers=build_headers(
                csrf_token,
                "application/json, text/javascript, */*; q=0.01",
            ),
            timeout=API_TIMEOUT_MS,
        )

        # 2xx 才代表 HTTP 成功。
        # 不是 2xx 例如：403、419、429、500、503。
        if not response.ok:
            reason = (
                f"data API HTTP 狀態碼不是 2xx，"
                f"status={response.status}，response={preview_text(response.text())}"
            )
            return None, reason

        try:
            return response.json(), ""
        except Exception as e:
            reason = f"data API 回應不是合法 JSON：{type(e).__name__}，{e}"
            return None, reason

    except Exception as e:
        reason = f"data API 請求例外：{type(e).__name__}，{e}"
        return None, reason


def fetch_data_api_with_retry(
    context: Any,
    csrf_token: str,
    year: str,
    page: int,
    max_attempts: int = DATA_API_RETRY_MAX,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    data API retry 包裝。

    用途：
    - 筆數 = 0 的整頁失敗，要對該頁 data API 最多重試 3 次。
    - 筆數 > 0 的單筆失敗，也需要先拿該頁 data API，所以也使用這個 retry。
    """
    last_reason = ""

    for attempt in range(1, max_attempts + 1):
        print(
            f"data API retry：年份 {year} 第 {page} 頁，第 {attempt}/{max_attempts} 次"
        )

        data_json, reason = fetch_data_api_once(
            context=context,
            csrf_token=csrf_token,
            year=year,
            page=page,
        )

        if data_json is not None:
            print(f"data API 成功：年份 {year} 第 {page} 頁")
            return data_json, ""

        last_reason = reason
        print("data API 本次失敗：", reason)

        # 最後一次不用睡。
        if attempt < max_attempts:
            print(f"等待 {API_RETRY_SLEEP_SECONDS} 秒後再試一次...")
            time.sleep(API_RETRY_SLEEP_SECONDS)

    return None, f"data API 連續 {max_attempts} 次失敗。最後原因：{last_reason}"


def fetch_detail_api_once(
    context: Any,
    csrf_token: str,
    item: Dict[str, Any],
    year: str,
) -> Tuple[Optional[str], str]:
    """
    呼叫 detail API 一次。

    detail API 回傳 HTML，不是 JSON。
    這個函式只負責「打一通 API」。
    要不要重試，交給 fetch_detail_api_with_retry()。
    """
    payload = build_detail_payload(item, year)

    try:
        response = context.request.post(
            DETAIL_API_URL,
            form=payload,
            headers=build_headers(csrf_token, "text/html, */*; q=0.01"),
            timeout=API_TIMEOUT_MS,
        )

        if not response.ok:
            reason = (
                f"detail API HTTP 狀態碼不是 2xx，"
                f"status={response.status}，response={preview_text(response.text())}"
            )
            return None, reason

        return response.text(), ""

    except Exception as e:
        reason = f"detail API 請求例外：{type(e).__name__}，{e}"
        return None, reason


def fetch_detail_api_with_retry(
    context: Any,
    csrf_token: str,
    item: Dict[str, Any],
    year: str,
    page: int,
    row_number: int,
    max_attempts: int = DETAIL_API_RETRY_MAX,
) -> Tuple[Optional[str], str]:
    """
    對「單一 detail API」最多重試 max_attempts 次。

    會 retry 的情況：
    1. detail API HTTP 非 2xx，例如 403、419、429、500、503。
    2. timeout、網路錯誤等程式例外。
    3. detail 回 HTML，但找不到「成交記錄」區塊。
    4. detail 有成交記錄內容，但格式不符合「於 YYYY-MM-DD 移轉 xxx MWh」。

    不 retry 的情況：
    - detail 有「成交記錄」區塊，且 <ol></ol> 真的是空白。
      這是「沒有成交記錄」，不是 API 失敗。

    回傳：
    - 成功 / 合法空成交記錄：(detail_html, "")
    - 連續失敗：(None, 最後失敗原因)
    """
    last_reason = ""

    for attempt in range(1, max_attempts + 1):
        print(
            f"detail API retry：年份 {year} 第 {page} 頁第 {row_number} 筆，"
            f"第 {attempt}/{max_attempts} 次"
        )

        detail_html, reason = fetch_detail_api_once(
            context=context,
            csrf_token=csrf_token,
            item=item,
            year=year,
        )

        # API 本身失敗：可重試。
        if detail_html is None:
            last_reason = reason
            print("detail API 本次失敗：", reason)

        # HTML 有回來，但沒有「成交記錄」區塊：可重試。
        elif not has_trade_record_section(detail_html):
            last_reason = "detail HTML 找不到『成交記錄』區塊"
            print("detail HTML 本次異常：", last_reason)

        # HTML 正常、成交記錄 ol 空白：沒有成交紀錄，不是失敗，直接回傳。
        elif is_trade_record_ol_empty(detail_html):
            print("detail API 成功，但成交記錄 <ol></ol> 為空，不需要 retry")
            return detail_html, ""

        # HTML 正常，而且能解析到成交資料：成功，直接回傳。
        elif extract_trade_records(detail_html):
            print(f"detail API 成功：年份 {year} 第 {page} 頁第 {row_number} 筆")
            return detail_html, ""

        # 有成交記錄區塊、ol 不是空，但格式解析不到：可重試。
        else:
            last_reason = (
                "detail HTML 有成交記錄內容，但無法解析成"
                "『於 YYYY-MM-DD 移轉 xxx MWh』格式"
            )
            print("detail HTML 本次解析異常：", last_reason)

        # 最後一次失敗後不用等待。
        if attempt < max_attempts:
            print(f"等待 {API_RETRY_SLEEP_SECONDS} 秒後再試 detail API...")
            time.sleep(API_RETRY_SLEEP_SECONDS)

    return (
        None,
        f"detail API / detail HTML 連續 {max_attempts} 次失敗。最後原因：{last_reason}",
    )


# =========================================================
# 14. data item + detail HTML 組成成功 raw row
# =========================================================


def build_rows_from_item_detail(
    item: Dict[str, Any],
    detail_html: str,
) -> Tuple[str, List[Dict[str, str]]]:
    """
    把 data API 的外層 item + detail API 的 HTML 合併成原本 8 欄。

    回傳狀態：
    - success：有成功解析成交記錄。
    - empty：有成交記錄區塊，但 <ol></ol> 空，這不算失敗。
    - structure_error：找不到成交記錄區塊，這才算結構異常。
    """
    if not has_trade_record_section(detail_html):
        return "structure_error", []

    # <ol></ol> 真正空白：這是正常「沒有成交記錄」。
    if is_trade_record_ol_empty(detail_html):
        return "empty", []

    trade_records = extract_trade_records(detail_html)

    # 有成交記錄內容，但格式解析不到：不是 empty，是 HTML / 格式異常。
    if not trade_records:
        return "structure_error", []

    # detail 裡面的欄位通常比較乾淨，所以優先用 detail。
    seller_name = extract_detail_field(detail_html, "出售單位")
    generation_device = extract_detail_field(detail_html, "發電設備")
    buyer_name = extract_detail_field(detail_html, "購買者")

    # 如果 detail 抓不到，就用 data API 外層資料當備援。
    if not seller_name:
        seller_lines = html_to_lines(item.get("seller_name", ""))
        seller_name = seller_lines[0] if seller_lines else ""
    if not generation_device:
        generation_device = str(item.get("case_name", "")).strip()
    if not buyer_name:
        buyer_name = str(item.get("buyer_name", "")).strip()

    energy_type = str(item.get("energy", "")).strip()
    supply_type = str(item.get("parallel_type", "")).strip()
    total_transfer_mwh = clean_number(item.get("power", ""))

    rows: List[Dict[str, str]] = []

    for trade_date, trade_mwh in trade_records:
        rows.append(
            {
                "出售單位": clean_company_name(seller_name),
                "發電設備": generation_device,
                "購買者": clean_company_name(buyer_name),
                "能源類型": energy_type,
                "供電種類": supply_type,
                "總移轉量(MWh)": total_transfer_mwh,
                "成交日期": trade_date,
                "成交移轉量(MWh)": trade_mwh,
            }
        )

    return "success", rows


def get_item_basic_info(item: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    從 data API item 取基本資料，用於 failed_retry.csv。
    """
    seller_lines = html_to_lines(item.get("seller_name", ""))
    seller_name = seller_lines[0] if seller_lines else ""
    generation_device = str(item.get("case_name", "")).strip()
    buyer = str(item.get("buyer_name", "")).strip()
    return seller_name, generation_device, buyer


# =========================================================
# 15. retry 單筆 detail
# =========================================================


def retry_item_detail(
    context: Any,
    csrf_token: str,
    item: Dict[str, Any],
    year: str,
    page: int,
    row_number: int,
) -> Tuple[str, List[Dict[str, str]]]:
    """
    retry 某一筆 detail。

    回傳狀態：
    - success：有成功 raw rows。
    - empty：detail 成交記錄為空，不算失敗。
    - failed：detail API 或 HTML 結構仍失敗。
    """
    seller_name, generation_device, buyer = get_item_basic_info(item)

    detail_html, detail_reason = fetch_detail_api_with_retry(
        context=context,
        csrf_token=csrf_token,
        item=item,
        year=year,
        page=page,
        row_number=row_number,
        max_attempts=DETAIL_API_RETRY_MAX,
    )

    if detail_html is None:
        record_retry_failed(
            year=year,
            page=page,
            row_number=row_number,
            seller_name=seller_name,
            generation_device=generation_device,
            buyer=buyer,
            reason=f"retry detail API / HTML 連續重試後仍失敗：{detail_reason}",
        )
        return "failed", []

    status, success_rows = build_rows_from_item_detail(item, detail_html)

    if status == "success":
        print(f"第 {row_number} 筆 retry 成功，成交資料列數：{len(success_rows)}")
        return "success", success_rows

    if status == "empty":
        print(f"第 {row_number} 筆 detail 成交記錄為空，不算失敗，略過補 raw")
        return "empty", []

    record_retry_failed(
        year=year,
        page=page,
        row_number=row_number,
        seller_name=seller_name,
        generation_device=generation_device,
        buyer=buyer,
        reason="retry detail HTML 經過重試後仍無法解析成交記錄",
    )
    return "failed", []


# =========================================================
# 16. retry 筆數 > 0 的單筆失敗
# =========================================================


def retry_single_failed_row(
    context: Any,
    csrf_token: str,
    year: str,
    page: int,
    row_number: int,
) -> Tuple[str, List[Dict[str, str]]]:
    """
    處理 failed CSV 裡「筆數 > 0」的資料。

    商業意思：
    - 這不是整頁失敗。
    - 只補這一頁的指定第幾筆。
    """
    print(
        f"\n========== retry 單筆：年份 {year}，第 {page} 頁，第 {row_number} 筆 =========="
    )

    data_json, data_reason = fetch_data_api_with_retry(
        context=context,
        csrf_token=csrf_token,
        year=year,
        page=page,
        max_attempts=DATA_API_RETRY_MAX,
    )

    if data_json is None:
        record_retry_failed(
            year=year,
            page=page,
            row_number=row_number,
            seller_name="",
            generation_device="",
            buyer="",
            reason=f"retry data API 失敗：{data_reason}",
        )
        return "failed", []

    items = data_json.get("data") or []
    target_index = row_number - 1

    if target_index < 0:
        record_retry_failed(
            year, page, row_number, "", "", "", "retry 筆數小於 1，無法補單筆"
        )
        return "failed", []

    if target_index >= len(items):
        record_retry_failed(
            year=year,
            page=page,
            row_number=row_number,
            seller_name="",
            generation_device="",
            buyer="",
            reason=f"retry 第 {page} 頁只有 {len(items)} 筆，不足第 {row_number} 筆",
        )
        return "failed", []

    item = items[target_index]
    return retry_item_detail(context, csrf_token, item, year, page, row_number)


# =========================================================
# 17. retry 筆數 = 0 的整頁失敗
# =========================================================


def retry_whole_failed_page(
    context: Any,
    csrf_token: str,
    year: str,
    page: int,
) -> Tuple[bool, int]:
    """
    處理 failed CSV 裡「筆數 = 0」的資料。

    商業意思：
    - 這代表 01 在該頁還沒拿到外層列表，data API 就失敗。
    - 所以 02 不能只補某一筆。
    - 必須重抓整頁 data API。

    流程：
    1. data API 最多 retry 3 次。
    2. 如果 data API 成功，抓該頁每一筆 detail。
    3. 成功資料補回年度 raw。
    4. detail 仍失敗的單筆，寫入 failed_retry.csv。
    5. 原本的 page,row=0 整頁失敗資料，會從 failed_retry 移除。

    回傳：
    - page_data_success：data API 是否成功。
    - success_row_count：成功補回 raw 的資料列數。
    """
    print(f"\n========== retry 整頁：年份 {year}，第 {page} 頁，筆數 = 0 ==========")

    data_json, data_reason = fetch_data_api_with_retry(
        context=context,
        csrf_token=csrf_token,
        year=year,
        page=page,
        max_attempts=DATA_API_RETRY_MAX,
    )

    if data_json is None:
        # data API 連續 3 次失敗，保留 page,row=0 這筆 failed_retry。
        record_retry_failed(
            year=year,
            page=page,
            row_number=0,
            seller_name="",
            generation_device="",
            buyer="",
            reason=f"整頁 retry data API 失敗：{data_reason}",
        )
        return False, 0

    items = data_json.get("data") or []

    if not items:
        # data API 成功但沒有 data，這對 2026 第 70 頁來說不正常。
        # 因此先保留在 failed_retry，方便人工檢查。
        record_retry_failed(
            year=year,
            page=page,
            row_number=0,
            seller_name="",
            generation_device="",
            buyer="",
            reason="整頁 retry data API 成功，但本頁 data 為空，沒有可補抓資料",
        )
        return False, 0

    print(f"整頁 data API 成功：年份 {year} 第 {page} 頁，本頁外層筆數：{len(items)}")

    page_success_rows: List[Dict[str, str]] = []

    # 逐筆呼叫 detail API。
    for index, item in enumerate(items, start=1):
        row_number = index
        print(
            f"\n--- 整頁 retry detail：年份 {year}，第 {page} 頁，第 {row_number} 筆 ---"
        )

        item_status, item_rows = retry_item_detail(
            context=context,
            csrf_token=csrf_token,
            item=item,
            year=year,
            page=page,
            row_number=row_number,
        )

        if item_status == "success":
            page_success_rows.extend(item_rows)
            # 如果 failed_retry 裡原本也有這一筆單筆失敗，成功後移除。
            remove_retry_failed_row(year, page, row_number)

        elif item_status == "empty":
            # detail <ol></ol> 空的不是失敗。
            # 如果 failed_retry 裡原本有這筆，也移除。
            remove_retry_failed_row(year, page, row_number)

        else:
            # failed 狀態已經在 retry_item_detail 裡寫入 failed_retry。
            pass

    # 整頁成功拿到 data API 後，原本的 page,row=0 失敗已經解決。
    # 即使某幾筆 detail 後來失敗，也會變成 row_number > 0 的單筆 failed_retry。
    remove_retry_failed_row(year, page, 0)

    if page_success_rows:
        year_raw_file = find_latest_year_raw_file(year)
        append_rows_to_csv(year_raw_file, page_success_rows)

    return True, len(page_success_rows)


# =========================================================
# 18. main 主程式
# =========================================================


def main() -> int:
    """Cloud Run 02：GCS 下載 -> API retry -> GCS 即時同步。"""
    global storage_client

    print("\n========== 02 Cloud Run Playwright/API retry 啟動 ==========")
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR)
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)
    print(
        "FAILED_CSV_FILE_ENV：",
        FAILED_CSV_FILE_ENV or "(未指定，使用 trec_direct_transaction_raw_failed.csv)",
    )
    print("DATA_API_RETRY_MAX：", DATA_API_RETRY_MAX)
    print("DETAIL_API_RETRY_MAX：", DETAIL_API_RETRY_MAX)
    print("API_RETRY_SLEEP_SECONDS：", API_RETRY_SLEEP_SECONDS)
    print("API_TIMEOUT_MS：", API_TIMEOUT_MS)
    print("HEADLESS：", HEADLESS)
    print(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH：",
        PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH or "(使用 Playwright 內建 Chromium)",
    )

    total_success_rows = 0

    try:
        # 1. /tmp 是新暫存區；先下載必要輸入與年度 raw。
        storage_client = create_storage_client()
        download_existing_files_from_gcs()

        # 2. 預設讀 failed.csv；若指定 FAILED_CSV_FILE=failed_retry.csv，則讀未解決 retry 清單。
        failed_csv = find_failed_csv()
        if failed_csv is None:
            print("找不到 retry 來源 failed CSV，結束 02；不改寫既有 failed_retry.csv")
            return 0

        failed_rows = read_csv_rows(failed_csv)
        if not failed_rows:
            print(
                "retry 來源 failed CSV 只有表頭或沒有資料，結束 02；不改寫既有 failed_retry.csv"
            )
            return 0

        groups = group_failed_rows(failed_rows)
        if not groups:
            print("failed CSV 裡沒有可 retry 的年份 / 頁數 / 筆數，結束 02")
            return 0

        # 3. 建立本次 failed_retry 工作清單；成功就從清單移除。
        initialize_retry_failed_data(failed_rows)

        # 4. 用 Playwright 開首頁取得 Cookie / CSRF，再直接呼叫 API retry。
        with sync_playwright() as playwright:
            browser_launch_options: Dict[str, Any] = {"headless": HEADLESS}
            if (
                PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
                and Path(PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH).exists()
            ):
                browser_launch_options["executable_path"] = (
                    PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
                )

            browser = playwright.chromium.launch(**browser_launch_options)
            context = browser.new_context(
                locale="zh-TW",
                viewport={"width": 1920, "height": 1080},
            )

            try:
                page_obj = context.new_page()
                print("\n打開首頁，取得 Cookie / CSRF Token...")
                page_obj.goto(START_URL, wait_until="domcontentloaded", timeout=60000)

                try:
                    page_obj.wait_for_load_state("networkidle", timeout=15000)
                except PlaywrightTimeoutError:
                    print("networkidle 等待逾時，但頁面可能已可用，繼續執行")

                csrf_token = get_csrf_token(page_obj)
                if csrf_token:
                    print("已取得 CSRF Token")
                else:
                    print("警告：沒有取得 CSRF Token，仍會嘗試 retry API")

                # 5. 依「年份 + 頁數」處理；年份倒序、頁數正序。
                for (year, page_number), rows in sorted(
                    groups.items(),
                    key=lambda item: (-int(item[0][0]), item[0][1]),
                ):
                    print("\n" + "=" * 80)
                    print(
                        f"開始 retry 年份 {year} 第 {page_number} 頁，"
                        f"共 {len(rows)} 筆 failed"
                    )
                    print("=" * 80)

                    page_level_failed = [
                        row for row in rows if int(row["row_number"]) == 0
                    ]
                    single_failed = [row for row in rows if int(row["row_number"]) > 0]

                    # page,row=0：整頁 data API 曾失敗。成功後會處理該頁全部 detail。
                    if page_level_failed:
                        page_success, page_success_count = retry_whole_failed_page(
                            context=context,
                            csrf_token=csrf_token,
                            year=year,
                            page=page_number,
                        )
                        total_success_rows += page_success_count

                        if page_success:
                            print(
                                f"年份 {year} 第 {page_number} 頁整頁 retry 已完成，"
                                "同頁單筆 failed 不重複處理"
                            )
                        else:
                            print(
                                f"年份 {year} 第 {page_number} 頁整頁 retry 仍失敗，"
                                "同頁單筆 failed 暫不重複處理"
                            )
                        continue

                    # 沒有 page,row=0 時，只 retry 失敗的指定筆數。
                    for row in sorted(
                        single_failed,
                        key=lambda value: int(value["row_number"]),
                    ):
                        row_number = int(row["row_number"])

                        row_status, success_rows = retry_single_failed_row(
                            context=context,
                            csrf_token=csrf_token,
                            year=year,
                            page=page_number,
                            row_number=row_number,
                        )

                        if row_status == "success":
                            year_raw_file = find_latest_year_raw_file(year)
                            append_rows_to_csv(year_raw_file, success_rows)
                            total_success_rows += len(success_rows)
                            remove_retry_failed_row(year, page_number, row_number)

                        elif row_status == "empty":
                            # <ol></ol> 是正常無成交紀錄；不再留在 failed_retry。
                            remove_retry_failed_row(year, page_number, row_number)

                        # failed 已經由 record_retry_failed() 即時存檔並上傳。

            finally:
                context.close()
                browser.close()

        # 6. 全部 retry 結束後再完整同步一次。
        rebuild_all_year_csv()
        upload_file_to_gcs(ALL_YEARS_RAW_CSV_FILE)
        save_retry_failed_csv(force_create_empty=True)

        print("\n========== 02 Cloud Run retry 完成 ==========")
        print("retry 成功補回資料列數：", total_success_rows)
        print("retry 仍失敗筆數：", len(retry_failed_data))
        print("all_year CSV：", ALL_YEARS_RAW_CSV_FILE)
        print("failed_retry CSV：", RETRY_FAILED_CSV_FILE)
        return 0

    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，嘗試保存 02 目前結果")
        try:
            if storage_client is not None:
                rebuild_all_year_csv()
                upload_file_to_gcs(ALL_YEARS_RAW_CSV_FILE)
                save_retry_failed_csv(force_create_empty=True)
        except Exception as save_error:
            print("中斷後保存失敗：", type(save_error).__name__, save_error)
        return 1

    except Exception as e:
        print("\n02 Cloud Run retry 發生未預期錯誤：", type(e).__name__, e)
        print(traceback.format_exc())

        # 例外時也盡量保存已經補回的資料與剩餘 retry 清單。
        try:
            if storage_client is not None:
                rebuild_all_year_csv()
                upload_file_to_gcs(ALL_YEARS_RAW_CSV_FILE)
                save_retry_failed_csv(force_create_empty=True)
        except Exception as save_error:
            print("錯誤後保存又失敗：", type(save_error).__name__, save_error)

        return 1


if __name__ == "__main__":
    sys.exit(main())

"""
02_retry_self_generation_transaction_failed.py

T-REC「自用發電設備憑證成交紀錄」：
Cloud Run Playwright + data API failed retry 版

用途：
1. 正常由 04 呼叫時，只讀取 01 本次產生的 failed.csv。
2. 舊 failed_retry.csv 會保留，不能被本次 failed.csv 覆蓋；但主流程不會重新 retry 舊資料。
3. Retry-only Job 由 05 呼叫時，透過 FAILED_CSV_FILE 指定 failed_retry.csv，才只 retry 舊失敗資料。
4. 只 retry 自用發電設備的 data API；本資料來源沒有 detail API。
5. 成功資料立即補進本次 raw/dt=PIPELINE_DT/ 的年度 raw，並重建 / 上傳同日期 all_year。
6. Retry-only 流程會先複製最新快照建立新的 PIPELINE_DT，避免直接修改舊快照。
7. 本次 retry 後仍失敗的資料，會合併進 control/failed_retry.csv。
8. 02 不會改寫 01 的 control/failed.csv；failed.csv 永遠代表本次 01 的失敗清單。

環境變數：
    GCS_BUCKET=tibame-bronze
    GCS_PREFIX=self_generation_transaction
    PIPELINE_TIMEZONE=Asia/Taipei
    LOCAL_WORKDIR=/tmp

    # 不設定：只 retry 本次 failed.csv（主流程 04 使用）。
    # 設定後：只 retry 指定檔案（05 會指定 failed_retry.csv）。
    FAILED_CSV_FILE=trec_self_generation_transaction_raw_failed.csv
    FAILED_CSV_FILE=trec_self_generation_transaction_raw_failed_retry.csv

    PAGE_LENGTH=10
    API_BASE_YEAR=2026
    API_TIMEOUT_MS=30000
    DATA_API_RETRY_MAX=3
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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import storage
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# =========================================================
# 1. Cloud Run / GCS 基本設定
# =========================================================

START_URL = "https://www.trec.org.tw/certification_trade_situation"
DATA_API_URL = "https://www.trec.org.tw/certification_trade_situation/data"

# Cloud Run 的 /tmp 只適合暫存；正式資料要上傳 GCS。
LOCAL_WORKDIR = Path(os.getenv("LOCAL_WORKDIR", "/tmp")).resolve()
LOCAL_WORKDIR.mkdir(parents=True, exist_ok=True)

GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()
GCS_PREFIX = os.getenv(
    "GCS_PREFIX",
    "self_generation_transaction",
).strip("/")


# =========================================================
# 2. 執行參數
# =========================================================

RAW_PREFIX = "trec_self_generation_transaction_raw"

# 自用發電網站真正篩選資料年份的是 search[year]。
# payload 裡的 year 是頁面基準年度。
API_BASE_YEAR = os.getenv("API_BASE_YEAR", str(datetime.now().year)).strip()
if not re.fullmatch(r"20\d{2}", API_BASE_YEAR):
    raise ValueError("API_BASE_YEAR 必須是 YYYY，例如 2026")

def get_taipei_now() -> datetime:
    """取得專案使用的台灣時間；時區名稱無效時才退回系統時間。"""
    timezone_name = os.getenv("PIPELINE_TIMEZONE", "Asia/Taipei").strip() or "Asia/Taipei"
    try:
        return datetime.now(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError:
        print(f"警告：找不到時區 {timezone_name}，改用系統本地時間")
        return datetime.now()


def get_pipeline_dt() -> str:
    """取得 01→02→03 共用的資料快照日期。"""
    value = os.getenv("PIPELINE_DT", "").strip()
    if not value:
        return get_taipei_now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("PIPELINE_DT 必須是 YYYY-MM-DD，例如 2026-07-01") from exc
    return value


PIPELINE_DT = get_pipeline_dt()
PIPELINE_DATE_COMPACT = PIPELINE_DT.replace("-", "")
RAW_ROOT = "raw"
CONTROL_ROOT = "control"

PAGE_LENGTH = int(os.getenv("PAGE_LENGTH", "10"))
API_TIMEOUT_MS = int(os.getenv("API_TIMEOUT_MS", "30000"))
DATA_API_RETRY_MAX = int(os.getenv("DATA_API_RETRY_MAX", "3"))
API_RETRY_SLEEP_SECONDS = float(os.getenv("API_RETRY_SLEEP_SECONDS", "3"))
HEADLESS = os.getenv("HEADLESS", "true").lower() != "false"

PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH = os.getenv(
    "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
    "/usr/bin/chromium",
).strip()

# 空白：只處理本次 01 的 failed.csv（由 04 主流程使用）。
# 有設定：只處理指定檔案（由 05 指定 failed_retry.csv）。
FAILED_CSV_FILE_ENV = os.getenv("FAILED_CSV_FILE", "").strip()


# =========================================================
# 3. CSV 檔案與欄位
# =========================================================

ALL_YEARS_RAW_CSV_NAME = f"{RAW_PREFIX}_all_year_{PIPELINE_DATE_COMPACT}.csv"
FAILED_CSV_NAME = f"{RAW_PREFIX}_failed.csv"
RETRY_FAILED_CSV_NAME = f"{RAW_PREFIX}_failed_retry.csv"


def get_year_raw_csv_name(year: str) -> str:
    """找不到既有年度 raw 時，用本次 PIPELINE_DT 建立年度 raw 檔名。"""
    return f"{RAW_PREFIX}_{year}_{PIPELINE_DATE_COMPACT}.csv"


def local_path(filename: str) -> Path:
    """組出 /tmp 中的檔案完整路徑。"""
    return LOCAL_WORKDIR / filename


ALL_YEARS_RAW_CSV_FILE = local_path(ALL_YEARS_RAW_CSV_NAME)
FAILED_CSV_FILE_DEFAULT = local_path(FAILED_CSV_NAME)
RETRY_FAILED_CSV_FILE = local_path(RETRY_FAILED_CSV_NAME)

# 自用發電設備固定 7 欄。
# 全專案統一使用「移轉量(MWh)」。
FIELDNAMES: List[str] = [
    "出售單位",
    "發電設備",
    "購買者",
    "能源類型",
    "移轉量(MWh)",
    "憑證發放年份",
    "移轉日期",
]

# 舊版 CSV 使用的欄位名稱，僅用來讀取相容舊資料。
LEGACY_AMOUNT_FIELD = "移轉量"

FAILED_FIELDNAMES: List[str] = [
    "憑證發放年份",
    "頁數",
    "筆數",
    "出售單位",
    "發電設備",
    "購買者",
    "原因",
]

# retry_failed_data 永遠代表「目前仍未補成功」的資料。
retry_failed_data: List[Dict[str, str]] = []
storage_client: Optional[storage.Client] = None


# =========================================================
# 4. HTML / 文字清理工具
# =========================================================


class SimpleHTMLTextParser(HTMLParser):
    """將 seller_name 這類 HTML 字串轉成可用的純文字行。"""

    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: List[Tuple[str, Optional[str]]],
    ) -> None:
        if tag.lower() in {"div", "br", "p", "li", "label", "ol"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"div", "p", "li", "label", "ol"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)


def html_to_lines(value: Any) -> List[str]:
    """HTML 轉成去除空白後的文字行清單。"""
    if value is None:
        return []

    parser = SimpleHTMLTextParser()
    parser.feed(html.unescape(str(value)))

    return [line.strip() for line in "".join(parser.parts).splitlines() if line.strip()]


def clean_company_name(value: Any) -> str:
    """公司名稱清理：全形括號轉半形，移除括號周圍多餘空白。"""
    if value is None:
        return ""

    text = str(value).strip()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s*\(\s*", "(", text)
    text = re.sub(r"\s*\)\s*", ")", text)
    return text


def clean_text(value: Any) -> str:
    """一般文字欄位清理。"""
    return "" if value is None else str(value).strip()


def clean_number(value: Any) -> str:
    """數字字串清理：去掉空白與千分位逗號。"""
    return "" if value is None else str(value).strip().replace(",", "")


def get_seller_company_name(seller_html: Any) -> str:
    """seller_name HTML 的第一行是出售公司名稱。"""
    lines = html_to_lines(seller_html)
    return clean_company_name(lines[0]) if lines else ""


def preview_text(value: Optional[str], limit: int = 500) -> str:
    """失敗 log 只保留回應前段，避免 Cloud Run log 過長。"""
    if not value:
        return ""

    text = str(value).strip()
    return text if len(text) <= limit else text[:limit] + "...（後面省略）"


# =========================================================
# 5. CSV 資料轉換工具
# =========================================================


def normalize_raw_row(row: Dict[str, Any]) -> Dict[str, str]:
    """
    統一輸出成固定 7 欄。

    優先讀新版「移轉量(MWh)」；
    若讀到舊版 CSV，才退回讀「移轉量」。
    """
    amount = row.get("移轉量(MWh)", "")
    if clean_text(amount) == "":
        amount = row.get(LEGACY_AMOUNT_FIELD, "")

    return {
        "出售單位": clean_company_name(row.get("出售單位", "")),
        "發電設備": clean_text(row.get("發電設備", "")),
        "購買者": clean_company_name(row.get("購買者", "")),
        "能源類型": clean_text(row.get("能源類型", "")),
        "移轉量(MWh)": clean_number(amount),
        "憑證發放年份": clean_text(row.get("憑證發放年份", "")),
        "移轉日期": clean_text(row.get("移轉日期", "")),
    }


def normalize_failed_row(row: Dict[str, Any]) -> Dict[str, str]:
    """統一 failed / failed_retry 格式。"""
    return {
        "憑證發放年份": clean_text(row.get("憑證發放年份", "")),
        "頁數": clean_text(row.get("頁數", "")),
        "筆數": clean_text(row.get("筆數", "")),
        "出售單位": clean_company_name(row.get("出售單位", "")),
        "發電設備": clean_text(row.get("發電設備", "")),
        "購買者": clean_company_name(row.get("購買者", "")),
        "原因": clean_text(row.get("原因", "")),
    }


def build_raw_row_from_api_item(item: Any, requested_year: str) -> Dict[str, str]:
    """將 data API 單筆 JSON 資料轉成自用發電固定 7 欄。"""
    if not isinstance(item, dict):
        raise TypeError("data API 的單筆資料不是 object / dict")

    return normalize_raw_row(
        {
            "出售單位": get_seller_company_name(item.get("seller_name", "")),
            "發電設備": item.get("case_name", ""),
            "購買者": item.get("buyer_name", ""),
            "能源類型": item.get("energy", ""),
            "移轉量(MWh)": item.get("power", ""),
            "憑證發放年份": item.get("certification_year") or requested_year,
            "移轉日期": item.get("created_at", ""),
        }
    )


def get_item_basic_info(item: Any) -> Tuple[str, str, str]:
    """從 API item 取基本資料，方便寫入 failed_retry.csv。"""
    if not isinstance(item, dict):
        return "", "", ""

    return (
        get_seller_company_name(item.get("seller_name", "")),
        clean_text(item.get("case_name", "")),
        clean_company_name(item.get("buyer_name", "")),
    )


# =========================================================
# 6. GCS 工具：raw 快照 / control 控制檔
# =========================================================


def gcs_join(*parts: str) -> str:
    cleaned = [str(part).strip("/") for part in parts if str(part).strip("/")]
    return "/".join(cleaned)


def raw_snapshot_prefix(dt: str = PIPELINE_DT) -> str:
    return gcs_join(GCS_PREFIX, RAW_ROOT, f"dt={dt}")


def raw_snapshot_blob_name(filename: str, dt: str = PIPELINE_DT) -> str:
    return gcs_join(raw_snapshot_prefix(dt), filename)


def control_blob_name(filename: str) -> str:
    return gcs_join(GCS_PREFIX, CONTROL_ROOT, filename)


def create_storage_client() -> storage.Client:
    """建立 GCS client。"""
    if not GCS_BUCKET:
        raise ValueError("沒有設定 GCS_BUCKET，請在 Cloud Run Job 設定 bucket 名稱")
    return storage.Client()


def upload_file_to_gcs(path: Path, blob_name: Optional[str] = None) -> None:
    """上傳單一檔案；控制檔預設進 control/，raw 預設進本次 raw/dt=.../。"""
    if not path.exists():
        return
    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法上傳 GCS")

    if blob_name is None:
        if path.name in {FAILED_CSV_NAME, RETRY_FAILED_CSV_NAME}:
            blob_name = control_blob_name(path.name)
        else:
            blob_name = raw_snapshot_blob_name(path.name)

    bucket = storage_client.bucket(GCS_BUCKET)
    bucket.blob(blob_name).upload_from_filename(str(path))
    print(f"已上傳 GCS：{path}")
    print(f"GCS 位置：gs://{GCS_BUCKET}/{blob_name}")


def download_blob_if_missing(blob_name: str, destination: Path) -> bool:
    """/tmp 已有檔案則保留；否則下載指定 GCS object。"""
    if destination.exists():
        return True
    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法下載 GCS")

    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(blob_name)
    if not blob.exists(client=storage_client):
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(destination))
    print(f"已下載：gs://{GCS_BUCKET}/{blob_name} -> {destination}")
    return True


def is_year_raw_filename(filename: str) -> bool:
    return bool(
        re.fullmatch(rf"{re.escape(RAW_PREFIX)}_20\d{{2}}_\d{{8}}\.csv", filename)
    )


def parse_year_raw_filename(filename: str) -> Optional[Tuple[str, str]]:
    match = re.fullmatch(
        rf"{re.escape(RAW_PREFIX)}_(20\d{{2}})_(\d{{8}})\.csv",
        filename,
    )
    if not match:
        return None
    return match.group(1), match.group(2)


def find_latest_raw_snapshot_dt() -> Optional[str]:
    """找 raw/ 下日期最新且具有同日期 all_year 的可用快照。"""
    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法列出 GCS")

    root_prefix = gcs_join(GCS_PREFIX, RAW_ROOT)
    pattern = re.compile(
        rf"^{re.escape(root_prefix)}/dt=(\d{{4}}-\d{{2}}-\d{{2}})/"
        rf"{re.escape(RAW_PREFIX)}_all_year_(\d{{8}})\.csv$"
    )
    candidates: List[str] = []
    for blob in storage_client.list_blobs(GCS_BUCKET, prefix=root_prefix + "/"):
        match = pattern.fullmatch(blob.name)
        if not match:
            continue
        dt, compact_dt = match.groups()
        if compact_dt == dt.replace("-", ""):
            candidates.append(dt)
    return max(candidates) if candidates else None


def local_current_year_raw_files() -> Dict[str, Path]:
    """找 /tmp 裡本次 PIPELINE_DT 的每一年度 raw。"""
    result: Dict[str, Path] = {}
    pattern = str(local_path(f"{RAW_PREFIX}_20??_{PIPELINE_DATE_COMPACT}.csv"))
    for path_text in glob.glob(pattern):
        path = Path(path_text)
        parsed = parse_year_raw_filename(path.name)
        if parsed is not None:
            result[parsed[0]] = path
    return result


def ensure_working_raw_snapshot() -> Optional[str]:
    """
    確保 /tmp 有本次 PIPELINE_DT 的年度 raw。

    - 04 的 01→02：/tmp 已有本次 raw，直接使用。
    - 05 retry-only：複製最新快照每一年度 raw，改名成本次日期，先建立新快照。
    """
    current = local_current_year_raw_files()
    if current:
        print("02 偵測到 /tmp 已有本次 raw 快照，直接使用")
        return PIPELINE_DT

    source_dt = find_latest_raw_snapshot_dt()
    if source_dt is None:
        raise FileNotFoundError(
            "找不到可用 raw 快照（raw/dt=*/..._all_year_YYYYMMDD.csv）。"
            "請先成功執行主流程 04 的第一次完整抓取。"
        )
    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法下載 GCS")

    copied: List[str] = []
    source_prefix = raw_snapshot_prefix(source_dt) + "/"
    for blob in storage_client.list_blobs(GCS_BUCKET, prefix=source_prefix):
        parsed = parse_year_raw_filename(Path(blob.name).name)
        if parsed is None:
            continue
        year, _old_date = parsed
        destination = local_path(get_year_raw_csv_name(year))
        blob.download_to_filename(str(destination))
        copied.append(year)
        print(f"05/02 複製年度快照：{year}，{Path(blob.name).name} -> {destination.name}")

    if not copied:
        raise FileNotFoundError(f"raw/dt={source_dt} 沒有任何年度 raw CSV")

    # 05 先建立新快照，後續 retry 成功資料只會更新這個新日期。
    upload_all_current_raw_snapshot()
    print(f"02 已從 raw/dt={source_dt} 建立本次工作快照 dt={PIPELINE_DT}")
    return source_dt


def download_existing_files_from_gcs() -> None:
    """下載 control 檔，並準備本次 raw 工作快照。"""
    print("\n========== 02 準備 GCS 資料 ==========")
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)
    print("PIPELINE_DT：", PIPELINE_DT)

    download_blob_if_missing(control_blob_name(FAILED_CSV_NAME), FAILED_CSV_FILE_DEFAULT)
    download_blob_if_missing(control_blob_name(RETRY_FAILED_CSV_NAME), RETRY_FAILED_CSV_FILE)
    ensure_working_raw_snapshot()


def upload_all_current_raw_snapshot() -> None:
    """上傳本次 dt 下所有年度 raw，再重建與上傳同日期 all_year。"""
    for _year, path in sorted(local_current_year_raw_files().items()):
        upload_file_to_gcs(path, raw_snapshot_blob_name(path.name))
    rebuild_all_year_csv()
    upload_file_to_gcs(
        ALL_YEARS_RAW_CSV_FILE,
        raw_snapshot_blob_name(ALL_YEARS_RAW_CSV_FILE.name),
    )

# =========================================================
# 7. CSV 讀寫與 all_year 合併
# =========================================================


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    """讀取 CSV；檔案不存在或空檔時回傳空清單。"""
    if not path.exists() or path.stat().st_size == 0:
        return []

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def read_csv_header(path: Path) -> List[str]:
    """讀取 CSV 表頭；不存在或空檔時回傳空清單。"""
    if not path.exists() or path.stat().st_size == 0:
        return []

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return next(csv.reader(file), [])


def write_csv_atomic(
    path: Path,
    rows: List[Dict[str, Any]],
    fieldnames: List[str],
) -> None:
    """先寫 .tmp，再 os.replace，避免中斷時正式 CSV 損毀。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = path.with_suffix(path.suffix + ".tmp")

    with temp_file.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    os.replace(temp_file, path)


def ensure_year_raw_schema(year_raw_file: Path) -> None:
    """
    確保年度 raw 統一使用新版 7 欄。

    若 GCS 裡仍是舊欄位「移轉量」，會讀出資料、轉成「移轉量(MWh)」，
    再安全覆蓋寫回同一份年度 raw，避免 append 時出現欄位不一致。
    """
    if not year_raw_file.exists() or year_raw_file.stat().st_size == 0:
        return

    existing_header = read_csv_header(year_raw_file)
    if existing_header == FIELDNAMES:
        return

    has_new_amount = "移轉量(MWh)" in existing_header
    has_old_amount = LEGACY_AMOUNT_FIELD in existing_header

    if not has_new_amount and not has_old_amount:
        raise ValueError(
            f"年度 raw 表頭不含移轉量欄位，無法安全補資料："
            f"{year_raw_file.name}，表頭={existing_header}"
        )

    migrated_rows = [normalize_raw_row(row) for row in read_csv_rows(year_raw_file)]
    write_csv_atomic(year_raw_file, migrated_rows, FIELDNAMES)

    print("年度 raw 已統一為新版欄位「移轉量(MWh)」：", year_raw_file)


def find_latest_year_raw_files() -> Dict[str, Path]:
    """本次 PIPELINE_DT 的年度 raw；每年只會有一份。"""
    return local_current_year_raw_files()


def find_latest_year_raw_file(year: str) -> Path:
    """找本次快照指定年份 raw；找不到時回傳本次日期的新檔名。"""
    latest_by_year = find_latest_year_raw_files()
    if str(year) in latest_by_year:
        return latest_by_year[str(year)]

    return local_path(get_year_raw_csv_name(str(year)))


def rebuild_all_year_csv() -> None:
    """
    重建 all_year。

    all_year = 本次 PIPELINE_DT 每個年度 raw 的合併結果。
    輸出一定統一為新版欄位「移轉量(MWh)」。
    """
    latest_by_year = find_latest_year_raw_files()
    all_rows: List[Dict[str, str]] = []

    for year in sorted(latest_by_year.keys(), reverse=True):
        source_file = latest_by_year[year]
        print(f"合併年度 raw：{year} -> {source_file}")

        for row in read_csv_rows(source_file):
            all_rows.append(normalize_raw_row(row))

    write_csv_atomic(ALL_YEARS_RAW_CSV_FILE, all_rows, FIELDNAMES)

    print("\n========== all_year 已重建 ==========")
    print("all_year 檔案：", ALL_YEARS_RAW_CSV_FILE)
    print("all_year 總列數：", len(all_rows))


def upload_changed_raw_and_all_year(year_raw_file: Path) -> None:
    """retry 成功後，立即更新本次 raw/dt 快照與同日期 all_year。"""
    upload_file_to_gcs(year_raw_file, raw_snapshot_blob_name(year_raw_file.name))
    rebuild_all_year_csv()
    upload_file_to_gcs(
        ALL_YEARS_RAW_CSV_FILE,
        raw_snapshot_blob_name(ALL_YEARS_RAW_CSV_FILE.name),
    )


def append_rows_to_csv(csv_file: Path, rows: List[Dict[str, str]]) -> None:
    """
    將 retry 成功資料補進指定年份最新 raw。

    raw 階段不去重；03 才會統一去重。
    """
    if not rows:
        return

    # 若舊年度 raw 還是舊欄位，先升級表頭與資料。
    ensure_year_raw_schema(csv_file)

    file_exists = csv_file.exists()
    file_is_empty = (not file_exists) or csv_file.stat().st_size == 0
    csv_file.parent.mkdir(parents=True, exist_ok=True)

    encoding = "utf-8-sig" if file_is_empty else "utf-8"
    with csv_file.open("a", newline="", encoding=encoding) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDNAMES,
            extrasaction="ignore",
        )
        if file_is_empty:
            writer.writeheader()

        writer.writerows([normalize_raw_row(row) for row in rows])

    print("\n========== retry 成功資料已補進年度 raw ==========")
    print("年度 raw：", csv_file)
    print("補進列數：", len(rows))

    upload_changed_raw_and_all_year(csv_file)


# =========================================================
# 8. failed_retry 清單工具
# =========================================================


def make_failed_key(year: Any, page: Any, row_number: Any) -> Tuple[str, str, str]:
    """同一年、同頁、同筆的失敗資料視為同一筆。"""
    return clean_text(year), clean_text(page), clean_text(row_number)


def make_failed_key_from_row(row: Dict[str, str]) -> Tuple[str, str, str]:
    return make_failed_key(
        row.get("憑證發放年份", ""),
        row.get("頁數", ""),
        row.get("筆數", ""),
    )


def merge_failed_row_values(
    existing_row: Dict[str, str],
    incoming_row: Dict[str, str],
) -> Dict[str, str]:
    """
    合併相同 key 的 failed row。

    新資料有值時優先使用；新資料欄位空白時保留舊資料，避免本次
    failed.csv 欄位較少而把舊 failed_retry 的資訊洗掉。
    """
    merged = dict(existing_row)
    for field in FAILED_FIELDNAMES:
        incoming_value = clean_text(incoming_row.get(field, ""))
        if incoming_value:
            merged[field] = incoming_value
    return normalize_failed_row(merged)


def normalize_and_deduplicate_failed_rows(
    rows: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """正規化並依 年份 + 頁數 + 筆數 去重，保留較完整的欄位資料。"""
    by_key: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    ordered_keys: List[Tuple[str, str, str]] = []

    for row in rows:
        normalized = normalize_failed_row(row)
        key = make_failed_key_from_row(normalized)

        # 三個定位欄位缺一不可；否則 02 無法知道要 retry 哪一頁或哪一筆。
        if not all(key):
            continue

        if key not in by_key:
            by_key[key] = normalized
            ordered_keys.append(key)
        else:
            by_key[key] = merge_failed_row_values(by_key[key], normalized)

    return [by_key[key] for key in ordered_keys]


def merge_retry_failed_row_in_memory(failed_row: Dict[str, str]) -> None:
    """合併一筆資料到目前 failed_retry 工作清單，但暫時不寫檔。"""
    normalized = normalize_failed_row(failed_row)
    key = make_failed_key_from_row(normalized)

    if not all(key):
        return

    for index, old_row in enumerate(retry_failed_data):
        if make_failed_key_from_row(old_row) == key:
            retry_failed_data[index] = merge_failed_row_values(old_row, normalized)
            return

    retry_failed_data.append(normalized)


def save_retry_failed_csv(force_create_empty: bool = True) -> None:
    """覆蓋寫入目前仍未補成功的 failed_retry.csv，並立即上傳 GCS。"""
    if not retry_failed_data and not force_create_empty:
        return

    write_csv_atomic(RETRY_FAILED_CSV_FILE, retry_failed_data, FAILED_FIELDNAMES)

    print("failed_retry CSV 已存檔：", RETRY_FAILED_CSV_FILE)
    print("retry 仍失敗 / 等待日後處理筆數：", len(retry_failed_data))

    if storage_client is not None:
        upload_file_to_gcs(RETRY_FAILED_CSV_FILE)


def prepare_retry_failed_data(
    source_rows: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """
    建立本次 02 的 failed_retry 工作清單。

    規則：
    1. 先讀舊 failed_retry.csv，保留以前未成功的資料。
    2. 再加入本次來源（主流程是 failed.csv；05 則是 failed_retry.csv）。
    3. 相同 年份 + 頁數 + 筆數 只保留一筆。
    4. 立刻寫回 failed_retry.csv，避免 02 中斷時本次新失敗沒有留下來。

    重要：
    - 合併是為了「保留清單」，不是代表主流程要重抓舊資料。
    - main() 後面仍只用 source_rows 建立 groups，因此 04 只 retry 本次 failed.csv。
    - 05 的 source_rows 本身是 failed_retry.csv，才會 retry 舊資料。
    """
    retry_failed_data.clear()

    old_retry_rows = normalize_and_deduplicate_failed_rows(
        read_csv_rows(RETRY_FAILED_CSV_FILE)
    )
    normalized_source_rows = normalize_and_deduplicate_failed_rows(source_rows)

    # 先保留舊 backlog，再加入本次來源。
    for row in old_retry_rows:
        merge_retry_failed_row_in_memory(row)

    for row in normalized_source_rows:
        merge_retry_failed_row_in_memory(row)

    save_retry_failed_csv(force_create_empty=True)

    print("舊 failed_retry 保留筆數：", len(old_retry_rows))
    print("本次 retry 來源筆數：", len(normalized_source_rows))
    print("合併後待處理 / 待保留筆數：", len(retry_failed_data))

    return normalized_source_rows


def upsert_retry_failed_row(failed_row: Dict[str, str]) -> None:
    """新增或更新一筆 retry 後仍失敗的資料。"""
    normalized = normalize_failed_row(failed_row)
    key = make_failed_key_from_row(normalized)

    if not all(key):
        return

    for index, old_row in enumerate(retry_failed_data):
        if make_failed_key_from_row(old_row) == key:
            retry_failed_data[index] = merge_failed_row_values(old_row, normalized)
            break
    else:
        retry_failed_data.append(normalized)

    save_retry_failed_csv(force_create_empty=True)


def remove_retry_failed_row(year: Any, page: Any, row_number: Any) -> None:
    """資料已安全補進 raw 後，才從 failed_retry 清單移除。"""
    key = make_failed_key(year, page, row_number)
    old_count = len(retry_failed_data)

    retry_failed_data[:] = [
        row for row in retry_failed_data if make_failed_key_from_row(row) != key
    ]

    if len(retry_failed_data) != old_count:
        print("retry 成功 / 已處理，從 failed_retry 移除：", key)
        save_retry_failed_csv(force_create_empty=True)


def record_retry_failed(
    *,
    year: Any,
    page: Any,
    row_number: Any,
    seller_name: str = "",
    generation_device: str = "",
    buyer: str = "",
    reason: str,
) -> None:
    """記錄 retry 後仍失敗的資料，立即寫入 failed_retry.csv。"""
    failed_row = {
        "憑證發放年份": clean_text(year),
        "頁數": clean_text(page),
        "筆數": clean_text(row_number),
        "出售單位": clean_company_name(seller_name),
        "發電設備": clean_text(generation_device),
        "購買者": clean_company_name(buyer),
        "原因": clean_text(reason),
    }

    print("\n========== retry 仍失敗 ==========")
    print(failed_row)
    upsert_retry_failed_row(failed_row)


# =========================================================
# 9. retry 來源讀取與分組
# =========================================================


def find_failed_csv() -> Optional[Path]:
    """
    找 02 本次要 retry 的來源檔案。

    優先順序：
    1. FAILED_CSV_FILE 有設定：只讀指定檔案（05 會指定 failed_retry.csv）。
    2. 沒設定：只讀本次 01 的 failed.csv（04 主流程使用）。
    """
    if FAILED_CSV_FILE_ENV:
        configured_path = Path(FAILED_CSV_FILE_ENV)
        if not configured_path.is_absolute():
            configured_path = local_path(FAILED_CSV_FILE_ENV)

        if configured_path.exists():
            return configured_path

        print("找不到指定 FAILED_CSV_FILE：", configured_path)
        return None

    if FAILED_CSV_FILE_DEFAULT.exists():
        return FAILED_CSV_FILE_DEFAULT

    print("找不到本次 failed CSV：", FAILED_CSV_FILE_DEFAULT)
    return None


def group_failed_rows(
    failed_rows: List[Dict[str, str]],
) -> Dict[Tuple[str, int], List[Dict[str, Any]]]:
    """依 年份 + 頁數 分組，方便整頁 retry。"""
    groups: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}

    for row in failed_rows:
        year = clean_text(row.get("憑證發放年份", ""))
        page_text = clean_text(row.get("頁數", ""))
        row_text = clean_text(row.get("筆數", ""))

        if not year or not page_text or not row_text:
            continue

        try:
            page_number = int(page_text)
            row_number = int(row_text)
        except ValueError:
            continue

        groups.setdefault((year, page_number), []).append(
            {
                "year": year,
                "page_number": page_number,
                "row_number": row_number,
            }
        )

    return groups


def sort_group_key(
    item: Tuple[Tuple[str, int], List[Dict[str, Any]]],
) -> Tuple[int, int]:
    """年份倒序、頁數正序；不合法年份放最後。"""
    (year, page_number), _ = item

    try:
        return -int(year), page_number
    except ValueError:
        return 0, page_number


# =========================================================
# 10. DataTables payload / headers
# =========================================================


def build_data_payload(year: str, page_number: int) -> Dict[str, str]:
    """建立與 01 相同的 DataTables data API form payload。"""
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
        "columns[4][data]": "power",
        "columns[4][name]": "power",
        "columns[4][searchable]": "false",
        "columns[4][orderable]": "true",
        "columns[4][search][value]": "",
        "columns[4][search][regex]": "false",
        "columns[5][data]": "certification_year",
        "columns[5][name]": "certification_year",
        "columns[5][searchable]": "false",
        "columns[5][orderable]": "true",
        "columns[5][search][value]": "",
        "columns[5][search][regex]": "false",
        "columns[6][data]": "created_at",
        "columns[6][name]": "created_at",
        "columns[6][searchable]": "false",
        "columns[6][orderable]": "true",
        "columns[6][search][value]": "",
        "columns[6][search][regex]": "false",
        "order[0][column]": "6",
        "order[0][dir]": "desc",
        "order[0][name]": "created_at",
        "start": str(start),
        "length": str(PAGE_LENGTH),
        "search[value]": "",
        "search[regex]": "false",
        "search[year]": str(year),
        "search[energy]": "-1",
        "year": API_BASE_YEAR,
    }


def get_csrf_token(page: Any) -> str:
    """從首頁 meta tag 取得 CSRF Token。"""
    try:
        return (
            page.locator('meta[name="csrf-token"]').get_attribute(
                "content",
                timeout=3000,
            )
            or ""
        )
    except Exception:
        return ""


def build_headers(csrf_token: str) -> Dict[str, str]:
    """建立 data API request headers。"""
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.trec.org.tw",
        "Referer": START_URL,
    }

    if csrf_token:
        headers["X-CSRF-TOKEN"] = csrf_token

    return headers


def validate_response_year(
    data_json: Dict[str, Any],
    requested_year: str,
) -> Tuple[bool, str]:
    """
    確認 API 回傳 data 中的 certification_year 與要求年份一致。

    data 為空時沒有資料可驗證，由後續 retry 流程判斷。
    """
    items = data_json.get("data")

    if not isinstance(items, list):
        return False, "data API 的 data 欄位不是 list"

    returned_years = sorted(
        {
            clean_text(item.get("certification_year", ""))
            for item in items
            if isinstance(item, dict) and clean_text(item.get("certification_year", ""))
        }
    )

    if not returned_years:
        return True, "回傳 data 為空，沒有可驗證的 certification_year"

    if returned_years != [str(requested_year)]:
        return (
            False,
            "API 回傳年度與請求年度不一致："
            f"請求={requested_year}，回傳={returned_years}",
        )

    return True, f"請求年度={requested_year}，API 回傳年度={returned_years[0]}"


# =========================================================
# 11. data API retry 工具
# =========================================================


def fetch_data_api_once(
    context: Any,
    csrf_token: str,
    year: str,
    page_number: int,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """呼叫 data API 一次；成功回傳 JSON，失敗回傳原因。"""
    payload = build_data_payload(year, page_number)

    try:
        response = context.request.post(
            DATA_API_URL,
            form=payload,
            headers=build_headers(csrf_token),
            timeout=API_TIMEOUT_MS,
        )

        if not response.ok:
            return (
                None,
                "data API HTTP 狀態碼不是 2xx，"
                f"status={response.status}，response={preview_text(response.text())}",
            )

        try:
            data_json = response.json()
        except Exception as exc:
            return None, f"data API 回應不是合法 JSON：{type(exc).__name__}，{exc}"

        if not isinstance(data_json, dict):
            return None, "data API JSON 根節點不是 object / dict"

        valid_year, year_message = validate_response_year(data_json, year)
        print(f"retry 年份驗證：{year_message}")

        if not valid_year:
            return None, year_message

        return data_json, ""

    except Exception as exc:
        return None, f"data API 請求例外：{type(exc).__name__}，{exc}"


def fetch_data_api_with_retry(
    context: Any,
    csrf_token: str,
    year: str,
    page_number: int,
    max_attempts: int = DATA_API_RETRY_MAX,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """data API 最多重試 max_attempts 次。"""
    last_reason = ""

    for attempt in range(1, max_attempts + 1):
        print(
            f"data API retry：年份 {year} 第 {page_number} 頁，"
            f"第 {attempt}/{max_attempts} 次"
        )

        data_json, reason = fetch_data_api_once(
            context=context,
            csrf_token=csrf_token,
            year=year,
            page_number=page_number,
        )

        if data_json is not None:
            print(f"data API 成功：年份 {year} 第 {page_number} 頁")
            return data_json, ""

        last_reason = reason
        print("data API 本次失敗：", reason)

        if attempt < max_attempts:
            print(f"等待 {API_RETRY_SLEEP_SECONDS} 秒後再試一次...")
            time.sleep(API_RETRY_SLEEP_SECONDS)

    return None, f"data API 連續 {max_attempts} 次失敗。最後原因：{last_reason}"


def extract_items_or_raise(data_json: Dict[str, Any]) -> List[Any]:
    """確認 data API 的 data 欄位是 list。"""
    items = data_json.get("data")

    if not isinstance(items, list):
        raise TypeError("data API 的 data 欄位不是 list")

    return items


# =========================================================
# 12. retry 單筆 / 整頁流程
# =========================================================


def retry_single_failed_row(
    context: Any,
    csrf_token: str,
    year: str,
    page_number: int,
    row_number: int,
) -> Tuple[str, List[Dict[str, str]]]:
    """處理 failed.csv 中「筆數 > 0」的單筆資料失敗。"""
    print(
        "\n========== retry 單筆："
        f"年份 {year}，第 {page_number} 頁，第 {row_number} 筆 =========="
    )

    data_json, data_reason = fetch_data_api_with_retry(
        context=context,
        csrf_token=csrf_token,
        year=year,
        page_number=page_number,
    )

    if data_json is None:
        record_retry_failed(
            year=year,
            page=page_number,
            row_number=row_number,
            reason=f"retry data API 失敗：{data_reason}",
        )
        return "failed", []

    try:
        items = extract_items_or_raise(data_json)
    except Exception as exc:
        record_retry_failed(
            year=year,
            page=page_number,
            row_number=row_number,
            reason=("retry data API JSON 結構異常：" f"{type(exc).__name__}，{exc}"),
        )
        return "failed", []

    target_index = row_number - 1

    if target_index < 0 or target_index >= len(items):
        record_retry_failed(
            year=year,
            page=page_number,
            row_number=row_number,
            reason=(
                f"retry 第 {page_number} 頁只有 {len(items)} 筆，"
                f"找不到第 {row_number} 筆"
            ),
        )
        return "failed", []

    item = items[target_index]

    try:
        raw_row = build_raw_row_from_api_item(item, year)
        print(f"第 {row_number} 筆 retry 成功")
        return "success", [raw_row]

    except Exception as exc:
        seller_name, generation_device, buyer_name = get_item_basic_info(item)

        record_retry_failed(
            year=year,
            page=page_number,
            row_number=row_number,
            seller_name=seller_name,
            generation_device=generation_device,
            buyer=buyer_name,
            reason=("retry 單筆資料仍無法轉成 CSV：" f"{type(exc).__name__}，{exc}"),
        )
        return "failed", []


def retry_whole_failed_page(
    context: Any,
    csrf_token: str,
    year: str,
    page_number: int,
) -> Tuple[bool, int]:
    """
    處理 failed.csv 中「筆數 = 0」的整頁 data API 失敗。

    data API 成功後，重新處理本頁所有 item。
    若某一筆 item 格式仍異常，會改成 row_number > 0 的 failed_retry。

    安全順序：
    先把成功資料 append 到年度 raw 並同步 GCS，完成後才刪除對應的
    failed_retry 記錄，避免 Cloud Run 中斷時發生「retry 清單已刪、raw 卻沒寫入」。
    """
    print(
        "\n========== retry 整頁："
        f"年份 {year}，第 {page_number} 頁，筆數 = 0 =========="
    )

    data_json, data_reason = fetch_data_api_with_retry(
        context=context,
        csrf_token=csrf_token,
        year=year,
        page_number=page_number,
    )

    if data_json is None:
        record_retry_failed(
            year=year,
            page=page_number,
            row_number=0,
            reason=f"整頁 retry data API 失敗：{data_reason}",
        )
        return False, 0

    try:
        items = extract_items_or_raise(data_json)
    except Exception as exc:
        record_retry_failed(
            year=year,
            page=page_number,
            row_number=0,
            reason=(
                "整頁 retry data API JSON 結構異常：" f"{type(exc).__name__}，{exc}"
            ),
        )
        return False, 0

    if not items:
        record_retry_failed(
            year=year,
            page=page_number,
            row_number=0,
            reason="整頁 retry data API 成功，但本頁 data 為空，沒有可補抓資料",
        )
        return False, 0

    print(
        f"整頁 data API 成功：年份 {year} 第 {page_number} 頁，"
        f"本頁資料筆數：{len(items)}"
    )

    page_success_rows: List[Dict[str, str]] = []
    resolved_row_numbers: List[int] = []

    for row_number, item in enumerate(items, start=1):
        try:
            raw_row = build_raw_row_from_api_item(item, year)
            page_success_rows.append(raw_row)
            resolved_row_numbers.append(row_number)

        except Exception as exc:
            seller_name, generation_device, buyer_name = get_item_basic_info(item)

            record_retry_failed(
                year=year,
                page=page_number,
                row_number=row_number,
                seller_name=seller_name,
                generation_device=generation_device,
                buyer=buyer_name,
                reason=(
                    f"整頁 retry 的第 {row_number} 筆仍無法轉成 CSV："
                    f"{type(exc).__name__}，{exc}"
                ),
            )

    # 成功資料先正式寫入年度 raw、上傳 GCS、重建 all_year。
    # append 失敗會丟出例外，因此下面的 remove 不會執行。
    if page_success_rows:
        year_raw_file = find_latest_year_raw_file(year)
        append_rows_to_csv(year_raw_file, page_success_rows)

    # raw 寫入成功後，再把同頁已補成功的單筆失敗記錄移除。
    for row_number in resolved_row_numbers:
        remove_retry_failed_row(year, page_number, row_number)

    # data API 已成功取得，原本 page,row=0 的整頁失敗已被處理成成功資料
    # 或個別 row-level failed，因此此時才可移除 page,row=0。
    remove_retry_failed_row(year, page_number, 0)

    return True, len(page_success_rows)


# =========================================================
# 13. main
# =========================================================


def main() -> int:
    """
    02 主流程：只 retry 指定來源，並保留舊 failed_retry backlog。

    - 04 正常呼叫：FAILED_CSV_FILE 未設定，只 retry 本次 failed.csv。
    - 05 Retry-only 呼叫：FAILED_CSV_FILE=...failed_retry.csv，只 retry 歷史 retry。
    """
    global storage_client

    browser: Optional[Any] = None
    context: Optional[Any] = None
    total_success_rows = 0

    print("\n========== 02 自用發電設備成交紀錄 retry 啟動 ==========")
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR)
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)
    print(
        "FAILED_CSV_FILE_ENV：",
        FAILED_CSV_FILE_ENV or "(未指定：只讀本次 failed.csv)",
    )
    print("DATA_API_RETRY_MAX：", DATA_API_RETRY_MAX)
    print("API_RETRY_SLEEP_SECONDS：", API_RETRY_SLEEP_SECONDS)
    print("API_BASE_YEAR：", API_BASE_YEAR)
    print("API_TIMEOUT_MS：", API_TIMEOUT_MS)
    print("HEADLESS：", HEADLESS)

    try:
        # 1. 先下載年度 raw、failed、failed_retry。
        storage_client = create_storage_client()
        download_existing_files_from_gcs()

        # 2. 決定本次真正要 retry 的來源。
        #    - 04 主流程：來源是本次 failed.csv。
        #    - 05 Retry-only：來源是 failed_retry.csv。
        failed_csv = find_failed_csv()
        if failed_csv is None:
            print("找不到 retry 來源 failed CSV。仍會寫出本次工作快照，讓後續 03 可使用同一個 PIPELINE_DT。")
            upload_all_current_raw_snapshot()
            return 0

        source_rows = normalize_and_deduplicate_failed_rows(read_csv_rows(failed_csv))
        if not source_rows:
            print(
                "retry 來源 failed CSV 只有表頭或沒有可 retry 資料。仍會寫出本次工作快照。"
            )
            upload_all_current_raw_snapshot()
            return 0

        groups = group_failed_rows(source_rows)
        if not groups:
            print("retry 來源 failed CSV 裡沒有可 retry 的年份 / 頁數 / 筆數。仍會寫出本次工作快照。")
            upload_all_current_raw_snapshot()
            return 0

        is_retry_only_source = failed_csv.resolve() == RETRY_FAILED_CSV_FILE.resolve()
        if is_retry_only_source:
            print("本次模式：Retry-only，只處理歷史 failed_retry.csv")
        else:
            print("本次模式：主流程 retry，只處理本次 failed.csv")
            print("舊 failed_retry.csv 只會保留，不會在本次主流程重抓")

        # 3. 建立「保留舊 backlog + 加入本次來源」清單。
        #    後續 groups 仍只用 source_rows，因此主流程不會意外重抓舊 backlog。
        source_rows = prepare_retry_failed_data(source_rows)

        # 4. 開首頁取得 Cookie / CSRF Token，再使用 context.request retry data API。
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
            page = context.new_page()

            print("\n打開首頁，取得 Cookie / CSRF Token...")
            page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                print("networkidle 等待逾時，但頁面可能已可用，繼續執行")

            csrf_token = get_csrf_token(page)
            if csrf_token:
                print("已取得 CSRF Token")
            else:
                print("警告：沒有取得 CSRF Token，仍會嘗試 retry API")

            # 年份倒序、頁數正序。
            for (year, page_number), rows in sorted(
                groups.items(),
                key=sort_group_key,
            ):
                print("\n" + "=" * 80)
                print(
                    f"開始 retry 年份 {year} 第 {page_number} 頁，"
                    f"共 {len(rows)} 筆來源 failed"
                )
                print("=" * 80)

                page_level_failed = [row for row in rows if int(row["row_number"]) == 0]
                single_failed = [row for row in rows if int(row["row_number"]) > 0]

                # page,row=0 代表整頁 data API 曾失敗。
                # 成功後會處理該頁所有資料，所以同頁單筆不重複處理。
                if page_level_failed:
                    page_success, page_success_count = retry_whole_failed_page(
                        context=context,
                        csrf_token=csrf_token,
                        year=year,
                        page_number=page_number,
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

                # 沒有整頁失敗時，只補指定筆數。
                for row in sorted(
                    single_failed,
                    key=lambda value: int(value["row_number"]),
                ):
                    row_number = int(row["row_number"])

                    row_status, success_rows = retry_single_failed_row(
                        context=context,
                        csrf_token=csrf_token,
                        year=year,
                        page_number=page_number,
                        row_number=row_number,
                    )

                    if row_status == "success":
                        year_raw_file = find_latest_year_raw_file(year)
                        append_rows_to_csv(year_raw_file, success_rows)
                        total_success_rows += len(success_rows)
                        remove_retry_failed_row(year, page_number, row_number)

                    # "failed" 已由 record_retry_failed 即時存檔並上傳。

        # 5. 整體 retry 結束後，再完整重建 / 上傳一次 all_year 與 failed_retry。
        rebuild_all_year_csv()
        upload_file_to_gcs(
            ALL_YEARS_RAW_CSV_FILE,
            raw_snapshot_blob_name(ALL_YEARS_RAW_CSV_FILE.name),
        )
        save_retry_failed_csv(force_create_empty=True)

        print("\n========== 02 自用發電設備成交紀錄 retry 完成 ==========")
        print("retry 成功補回資料列數：", total_success_rows)
        print("retry 仍失敗 / 等待日後處理筆數：", len(retry_failed_data))
        print("all_year CSV：", ALL_YEARS_RAW_CSV_FILE)
        print("failed_retry CSV：", RETRY_FAILED_CSV_FILE)

        return 0

    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，嘗試保存 02 目前結果")

        try:
            if storage_client is not None:
                rebuild_all_year_csv()
                upload_file_to_gcs(
                    ALL_YEARS_RAW_CSV_FILE,
                    raw_snapshot_blob_name(ALL_YEARS_RAW_CSV_FILE.name),
                )
                save_retry_failed_csv(force_create_empty=True)
        except Exception as save_error:
            print("中斷後保存失敗：", type(save_error).__name__, save_error)

        return 1

    except Exception as exc:
        print("\n02 retry 發生未預期錯誤：", type(exc).__name__, exc)
        print(traceback.format_exc())

        try:
            if storage_client is not None:
                rebuild_all_year_csv()
                upload_file_to_gcs(
                    ALL_YEARS_RAW_CSV_FILE,
                    raw_snapshot_blob_name(ALL_YEARS_RAW_CSV_FILE.name),
                )
                save_retry_failed_csv(force_create_empty=True)
        except Exception as save_error:
            print("錯誤後保存又失敗：", type(save_error).__name__, save_error)

        return 1

    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass

        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())

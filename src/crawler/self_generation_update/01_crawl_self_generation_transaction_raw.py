"""
01_crawl_self_generation_transaction_raw.py

T-REC「自用發電設備憑證成交紀錄」：Cloud Run Playwright + data API raw 爬蟲

資料來源頁面：
https://www.trec.org.tw/certification_trade_situation

本程式工作：
1. 以 Playwright 開啟首頁，取得 Cookie 與 CSRF Token。
2. 使用 POST /certification_trade_situation/data 直接抓 DataTables JSON。
3. 不使用 detail API；data API 的每一筆資料就是一筆交易資料。
4. raw 階段不去重；年度 raw 與同日期 all_year 存入 raw/dt=PIPELINE_DT/。
5. 每 SAVE_EVERY_PAGES 頁與每年結束時，保存本次快照並上傳 GCS。
6. data API 或單筆資料格式真正異常時，立即寫入 control/failed.csv。
7. 沒有資料不是失敗，寫入 control/status.csv 歷史紀錄。
8. 指定部分年度更新時，會從最新快照沿用未更新年度，建立新的完整快照。
9. 01 不 retry；retry 交由 02_retry_self_generation_transaction_failed.py。

環境變數範例：
    GCS_BUCKET=tibame-bronze
    GCS_PREFIX=self_generation_transaction
    PIPELINE_TIMEZONE=Asia/Taipei
    LOCAL_WORKDIR=/tmp

    YEARS_TO_CRAWL=ALL
    YEARS_TO_CRAWL=2026
    YEARS_TO_CRAWL=2026,2025

    MAX_PAGES_PER_YEAR=0
    PAGE_LENGTH=10
    SAVE_EVERY_PAGES=10
    API_TIMEOUT_MS=30000
    DATA_API_SLEEP_SECONDS=1
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
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import storage
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# =========================================================
# 1. 網站、Cloud Run、GCS 基本設定
# =========================================================

START_URL = "https://www.trec.org.tw/certification_trade_situation"
DATA_API_URL = "https://www.trec.org.tw/certification_trade_situation/data"

# Cloud Run 的 /tmp 是暫存區。程式結束後不能把它當永久保存位置。
LOCAL_WORKDIR = Path(os.getenv("LOCAL_WORKDIR", "/tmp")).resolve()
LOCAL_WORKDIR.mkdir(parents=True, exist_ok=True)

# GCS 是正式保存 CSV 的位置。
GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()
GCS_PREFIX = os.getenv(
    "GCS_PREFIX",
    "self_generation_transaction",
).strip("/")


# =========================================================
# 2. 執行參數
# =========================================================

RAW_PREFIX = "trec_self_generation_transaction_raw"

# data API 真正的年度篩選欄位是 search[year]。
# payload 裡的 year 是頁面基準年度，不是表格年度篩選。
# 目前網站手動查 2025 時仍送 year=2026。
# 未來跨年度時，可用 Cloud Run 環境變數 API_BASE_YEAR 明確指定。
API_BASE_YEAR = os.getenv("API_BASE_YEAR", str(datetime.now().year)).strip()
if not re.fullmatch(r"20\d{2}", API_BASE_YEAR):
    raise ValueError("API_BASE_YEAR 必須是 YYYY，例如 2026")

# 環境變數根本沒設定時，才預設抓 2026。
# 若明確設成空字串，會視為設定錯誤，不會偷偷改抓 2026。
YEARS_ENV = os.getenv("YEARS_TO_CRAWL", "2026").strip()

# 0 = 不限制頁數，完整抓完該年度。
MAX_PAGES_PER_YEAR = int(os.getenv("MAX_PAGES_PER_YEAR", "0"))

# DataTables 每頁抓幾筆。網站目前預設是 10。
PAGE_LENGTH = int(os.getenv("PAGE_LENGTH", "10"))

# 每完成幾頁，保存年度 raw / all_year / failed 並上傳 GCS。
SAVE_EVERY_PAGES = int(os.getenv("SAVE_EVERY_PAGES", "10"))

# API 單次請求 timeout，單位是毫秒。
API_TIMEOUT_MS = int(os.getenv("API_TIMEOUT_MS", "30000"))

# 每處理完一頁後，等待幾秒再抓下一頁，避免請求過密。
DATA_API_SLEEP_SECONDS = float(os.getenv("DATA_API_SLEEP_SECONDS", "1"))

# Cloud Run 正式執行時使用無頭瀏覽器。
HEADLESS = os.getenv("HEADLESS", "true").lower() != "false"

# Dockerfile 若安裝系統 Chromium，預設會在這個位置。
# 若實際路徑不存在，程式會改用 Playwright 自己的 Chromium。
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH = os.getenv(
    "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
    "/usr/bin/chromium",
).strip()


# =========================================================
# 3. 本次執行資訊、PIPELINE_DT 與檔案名稱
# =========================================================


def get_taipei_now() -> datetime:
    """取得專案使用的台灣時間；時區名稱無效時才退回系統時間。"""
    timezone_name = os.getenv("PIPELINE_TIMEZONE", "Asia/Taipei").strip() or "Asia/Taipei"
    try:
        return datetime.now(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError:
        print(f"警告：找不到時區 {timezone_name}，改用系統本地時間")
        return datetime.now()


def get_pipeline_dt() -> str:
    """取得整條 01→02→03 共用的資料快照日期。"""
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
RUN_NOW = get_taipei_now()
RUN_BATCH_ID = RUN_NOW.strftime("%Y%m%d_%H%M%S_%f")
RUN_TIME = RUN_NOW.strftime("%Y-%m-%d %H:%M:%S")

# raw/ 儲存資料快照；control/ 儲存 failed、failed_retry、status 等控制檔。
RAW_ROOT = "raw"
CONTROL_ROOT = "control"

ALL_YEARS_RAW_CSV_NAME = f"{RAW_PREFIX}_all_year_{PIPELINE_DATE_COMPACT}.csv"
STATUS_CSV_NAME = f"{RAW_PREFIX}_status.csv"
FAILED_CSV_NAME = f"{RAW_PREFIX}_failed.csv"


def get_year_raw_csv_name(year: str) -> str:
    """年度 raw，例如 trec_self_generation_transaction_raw_2026_20260701.csv。"""
    return f"{RAW_PREFIX}_{year}_{PIPELINE_DATE_COMPACT}.csv"


def local_path(filename: str) -> Path:
    """組出 Cloud Run /tmp 底下的暫存檔完整路徑。"""
    return LOCAL_WORKDIR / filename


ALL_YEARS_RAW_CSV_FILE = local_path(ALL_YEARS_RAW_CSV_NAME)
STATUS_CSV_FILE = local_path(STATUS_CSV_NAME)
FAILED_CSV_FILE = local_path(FAILED_CSV_NAME)

# =========================================================
# 4. CSV 欄位
# =========================================================

# 這是使用者已確認的「自用發電設備憑證成交紀錄」固定 7 欄。
FIELDNAMES: List[str] = [
    "出售單位",
    "發電設備",
    "購買者",
    "能源類型",
    "移轉量(MWh)",
    "憑證發放年份",
    "移轉日期",
]

# status 是歷史紀錄，因此每次遇到「目前沒有資料」都 append。
STATUS_FIELDNAMES: List[str] = [
    "執行批次ID",
    "執行時間",
    "憑證發放年份",
    "頁數",
    "筆數",
    "狀態",
    "原因",
]

# failed 只代表「本次 01」的失敗清單，01 開始時會清空。
FAILED_FIELDNAMES: List[str] = [
    "憑證發放年份",
    "頁數",
    "筆數",
    "出售單位",
    "發電設備",
    "購買者",
    "原因",
]


# =========================================================
# 5. 本次執行暫存資料與統計
# =========================================================

# raw_data_by_year 只放本次 01 成功抓到的資料。
# 不把 GCS 舊年度 raw 全部讀進記憶體，避免資料量大時佔用過多 RAM。
raw_data_by_year: Dict[str, List[Dict[str, str]]] = {}

# failed_data 只放本次 01 真正失敗資料。
failed_data: List[Dict[str, str]] = []

# main() 建立成功後才會有值。
storage_client: Optional[storage.Client] = None


@dataclass
class YearStats:
    """統計單一年度的抓取結果。"""

    year: str
    pages_checked: int = 0
    api_rows: int = 0
    success_rows: int = 0
    failure_count: int = 0
    no_data_recorded: bool = False


@dataclass
class RunStats:
    """統計整個 01 執行結果。"""

    years_checked: int = 0
    total_api_rows: int = 0
    total_success_rows: int = 0
    total_failure_count: int = 0


# =========================================================
# 6. HTML / 文字清理工具
# =========================================================


class SimpleHTMLTextParser(HTMLParser):
    """把 seller_name 這類 HTML 字串轉成可使用的純文字行。"""

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
    """HTML 字串轉成去空白後的文字行清單。"""
    if value is None:
        return []

    parser = SimpleHTMLTextParser()
    parser.feed(html.unescape(str(value)))

    return [line.strip() for line in "".join(parser.parts).splitlines() if line.strip()]


def clean_company_name(value: Any) -> str:
    """公司名稱清理：全形括號轉半形、移除多餘空白。"""
    if value is None:
        return ""

    text = str(value).strip()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s*\(\s*", "(", text)
    text = re.sub(r"\s*\)\s*", ")", text)
    return text


def clean_text(value: Any) -> str:
    """一般文字欄位清理。"""
    if value is None:
        return ""
    return str(value).strip()


def clean_number(value: Any) -> str:
    """數字字串清理：移除前後空白與千分位逗號。"""
    if value is None:
        return ""
    return str(value).strip().replace(",", "")


def get_seller_company_name(seller_html: Any) -> str:
    """
    seller_name 回傳範例：
        <div><div>中華紙漿股份有限公司</div><div>中華紙漿股份有限公司花蓮廠</div></div>

    CSV 的「出售單位」只要第一行公司名稱。
    發電設備則使用 API 的 case_name，不從 seller_name 第二行取值。
    """
    lines = html_to_lines(seller_html)
    return clean_company_name(lines[0]) if lines else ""


def preview_text(value: Optional[str], limit: int = 800) -> str:
    """失敗 log 只保留回應前段，避免 Cloud Run log 太長。"""
    if not value:
        return ""

    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...（後面省略）"


# =========================================================
# 7. CSV 讀寫與資料轉換工具
# =========================================================


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    """讀取 CSV；檔案不存在、空檔時回傳空清單。"""
    if not path.exists() or path.stat().st_size == 0:
        return []

    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv_atomic(
    path: Path,
    rows: List[Dict[str, Any]],
    fieldnames: List[str],
) -> None:
    """先寫 .tmp，再用 os.replace 覆蓋正式檔，降低中斷時檔案損毀風險。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = path.with_suffix(path.suffix + ".tmp")

    with temp_file.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    os.replace(temp_file, path)


def normalize_raw_row(row: Dict[str, Any]) -> Dict[str, str]:
    """將 raw row 統一成固定 7 欄與一致格式。"""
    return {
        "出售單位": clean_company_name(row.get("出售單位", "")),
        "發電設備": clean_text(row.get("發電設備", "")),
        "購買者": clean_company_name(row.get("購買者", "")),
        "能源類型": clean_text(row.get("能源類型", "")),
        "移轉量(MWh)": clean_number(
            row.get("移轉量(MWh)", row.get("移轉量", ""))
        ),
        "憑證發放年份": clean_text(row.get("憑證發放年份", "")),
        "移轉日期": clean_text(row.get("移轉日期", "")),
    }


def build_raw_row_from_api_item(item: Any, requested_year: str) -> Dict[str, str]:
    """
    將 data API 的一筆 JSON 資料轉成 CSV 的固定 7 欄。

    API 對應：
    - seller_name         -> 出售單位（HTML 第一行）
    - case_name           -> 發電設備
    - buyer_name          -> 購買者
    - energy              -> 能源類型
    - power               -> 移轉量(MWh)
    - certification_year  -> 憑證發放年份
    - created_at          -> 移轉日期
    """
    if not isinstance(item, dict):
        raise TypeError("data API 的單筆資料不是 object / dict")

    return normalize_raw_row(
        {
            "出售單位": get_seller_company_name(item.get("seller_name", "")),
            "發電設備": item.get("case_name", ""),
            "購買者": item.get("buyer_name", ""),
            "能源類型": item.get("energy", ""),
            "移轉量(MWh)": item.get("power", ""),
            # 若 API 偶爾沒有 certification_year，至少保留本次請求的年度。
            "憑證發放年份": item.get("certification_year") or requested_year,
            "移轉日期": item.get("created_at", ""),
        }
    )


def get_item_basic_info(item: Any) -> Tuple[str, str, str]:
    """從 API item 取出失敗 CSV 可讀的基本資料。"""
    if not isinstance(item, dict):
        return "", "", ""

    return (
        get_seller_company_name(item.get("seller_name", "")),
        clean_text(item.get("case_name", "")),
        clean_company_name(item.get("buyer_name", "")),
    )


# =========================================================
# 8. GCS 工具：raw 快照 / control 控制檔
# =========================================================


def gcs_join(*parts: str) -> str:
    """安全組出 GCS object name，不產生重複斜線。"""
    cleaned = [str(part).strip("/") for part in parts if str(part).strip("/")]
    return "/".join(cleaned)


def raw_snapshot_prefix(dt: str = PIPELINE_DT) -> str:
    """回傳 raw/dt=YYYY-MM-DD 本次快照的 GCS prefix。"""
    return gcs_join(GCS_PREFIX, RAW_ROOT, f"dt={dt}")


def raw_snapshot_blob_name(filename: str, dt: str = PIPELINE_DT) -> str:
    return gcs_join(raw_snapshot_prefix(dt), filename)


def control_blob_name(filename: str) -> str:
    return gcs_join(GCS_PREFIX, CONTROL_ROOT, filename)


def create_storage_client() -> storage.Client:
    """建立 GCS client；Cloud Run service account 必須擁有 bucket 讀寫權限。"""
    if not GCS_BUCKET:
        raise ValueError("沒有設定 GCS_BUCKET，請在 Cloud Run Job 設定 bucket 名稱")
    return storage.Client()


def upload_file_to_gcs(path: Path, blob_name: Optional[str] = None) -> None:
    """
    上傳一份本機 CSV 到 GCS。

    未明確傳入 blob_name 時，控制檔會放 control/，年度 raw 與 all_year 會放本次 raw/dt=.../。
    保留此預設可讓 failed/status 發生時仍能立即上傳。
    """
    if not path.exists():
        return
    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法上傳 GCS")

    if blob_name is None:
        if path.name in {FAILED_CSV_NAME, STATUS_CSV_NAME}:
            blob_name = control_blob_name(path.name)
        else:
            blob_name = raw_snapshot_blob_name(path.name)

    bucket = storage_client.bucket(GCS_BUCKET)
    bucket.blob(blob_name).upload_from_filename(str(path))
    print(f"已上傳 GCS：{path}")
    print(f"GCS 位置：gs://{GCS_BUCKET}/{blob_name}")


def download_blob_to_path(blob_name: str, destination: Path) -> bool:
    """下載指定 object；找不到時回傳 False。"""
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
    """判斷 dt 快照架構的年度 raw 檔名。"""
    return bool(
        re.fullmatch(
            rf"{re.escape(RAW_PREFIX)}_20\d{{2}}_\d{{8}}\.csv",
            filename,
        )
    )


def parse_year_raw_filename(filename: str) -> Optional[Tuple[str, str]]:
    """解析年度 raw 檔名，回傳 (資料年度, 快照日期 YYYYMMDD)。"""
    match = re.fullmatch(
        rf"{re.escape(RAW_PREFIX)}_(20\d{{2}})_(\d{{8}})\.csv",
        filename,
    )
    if not match:
        return None
    return match.group(1), match.group(2)


def find_latest_raw_snapshot_dt() -> Optional[str]:
    """找 raw/ 下日期最新且具有同日期 all_year CSV 的可用快照。"""
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


def get_explicit_years_from_env() -> Optional[set[str]]:
    """ALL/AUTO 回傳 None；明確指定年度時回傳年度集合。"""
    if YEARS_ENV.upper() in {"ALL", "AUTO"}:
        return None
    return {year.strip() for year in YEARS_ENV.split(",") if year.strip()}


def download_existing_output_files_from_gcs() -> Optional[str]:
    """
    準備 01 的 /tmp 工作區。

    - status.csv 從 control/ 下載，保留歷史 append。
    - YEARS_TO_CRAWL=ALL：全部年度重新抓取，不複製舊年度 raw。
    - 指定部分年度：從最新 raw/dt=.../ 下載未更新年度，改成本次 PIPELINE_DT 檔名。

    回傳沿用的來源快照日期；沒有可用快照時回傳 None。
    """
    print("\n========== 01 準備 GCS 快照資料 ==========")
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)
    print("PIPELINE_DT：", PIPELINE_DT)

    download_blob_to_path(control_blob_name(STATUS_CSV_NAME), STATUS_CSV_FILE)

    target_years = get_explicit_years_from_env()
    if target_years is None:
        print("YEARS_TO_CRAWL=ALL/AUTO：不複製舊年度 raw，全部年份重新抓取")
        return None

    source_dt = find_latest_raw_snapshot_dt()
    if source_dt is None:
        print(
            "警告：找不到可用 raw 快照。此次只會建立指定年份的初始快照；"
            "第一次正式執行請使用 YEARS_TO_CRAWL=ALL。"
        )
        return None

    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法下載 GCS")

    source_prefix = raw_snapshot_prefix(source_dt) + "/"
    copied_years: List[str] = []
    for blob in storage_client.list_blobs(GCS_BUCKET, prefix=source_prefix):
        parsed = parse_year_raw_filename(Path(blob.name).name)
        if parsed is None:
            continue
        year, _old_date = parsed
        if year in target_years:
            continue

        destination = local_path(get_year_raw_csv_name(year))
        blob.download_to_filename(str(destination))
        copied_years.append(year)
        print(f"沿用舊年度：{year}，{blob.name} -> {destination.name}")

    print(f"已從 raw/dt={source_dt} 沿用年度：", ", ".join(sorted(copied_years)) or "(無)")
    return source_dt


def upload_output_files_to_gcs() -> None:
    """
    將 01 管理的檔案同步到 GCS。

    raw/dt=PIPELINE_DT/：本次全部年度 raw + all_year。
    control/：failed、status。
    """
    raw_candidates: List[Path] = [ALL_YEARS_RAW_CSV_FILE]
    raw_candidates.extend(
        Path(path_text)
        for path_text in glob.glob(
            str(local_path(f"{RAW_PREFIX}_20??_{PIPELINE_DATE_COMPACT}.csv"))
        )
        if is_year_raw_filename(Path(path_text).name)
    )

    uploaded: set[Path] = set()
    for path in sorted(raw_candidates, key=lambda item: item.name):
        if path in uploaded or not path.exists():
            continue
        uploaded.add(path)
        upload_file_to_gcs(path, raw_snapshot_blob_name(path.name))

    upload_file_to_gcs(FAILED_CSV_FILE, control_blob_name(FAILED_CSV_NAME))
    if STATUS_CSV_FILE.exists():
        upload_file_to_gcs(STATUS_CSV_FILE, control_blob_name(STATUS_CSV_NAME))

# =========================================================
# 9. 年度 raw / all_year 儲存工具
# =========================================================


def add_raw_row(
    row: Dict[str, str], year_stats: YearStats, run_stats: RunStats
) -> None:
    """加入本次 raw；raw 階段刻意不做去重。"""
    raw_data_by_year.setdefault(year_stats.year, []).append(normalize_raw_row(row))
    year_stats.success_rows += 1
    run_stats.total_success_rows += 1


def save_year_raw_csv(year: str) -> None:
    """
    將本次抓到的某年度資料寫成本次 PIPELINE_DT 的年度 raw。

    例如：
    trec_self_generation_transaction_raw_2026_20260701.csv

    每次完整重新抓某一年時，這一份 PIPELINE_DT 檔會是該年的本次版本。
    """
    year_rows = [normalize_raw_row(row) for row in raw_data_by_year.get(str(year), [])]
    year_file = local_path(get_year_raw_csv_name(str(year)))

    write_csv_atomic(year_file, year_rows, FIELDNAMES)

    print("年度 raw 已存檔：", year_file)
    print("年度 raw 資料列數：", len(year_rows))


def find_latest_year_raw_files() -> Dict[str, Path]:
    """找出 /tmp 中本次 PIPELINE_DT 的年度 raw；每年只會有一份。"""
    result: Dict[str, Path] = {}
    pattern = str(local_path(f"{RAW_PREFIX}_20??_{PIPELINE_DATE_COMPACT}.csv"))

    for path_text in glob.glob(pattern):
        path = Path(path_text)
        parsed = parse_year_raw_filename(path.name)
        if parsed is None:
            continue
        year, _date = parsed
        result[year] = path

    return result


def rebuild_all_year_csv() -> None:
    """把本次快照每個年度 raw 合併成同日期 all_year CSV。"""
    latest_by_year = find_latest_year_raw_files()
    all_rows: List[Dict[str, str]] = []

    for year in sorted(latest_by_year.keys(), reverse=True):
        source_file = latest_by_year[year]
        print(f"合併年度 raw：{year} -> {source_file}")

        for row in read_csv_rows(source_file):
            all_rows.append(normalize_raw_row(row))

    write_csv_atomic(ALL_YEARS_RAW_CSV_FILE, all_rows, FIELDNAMES)

    print("all_year 已重建：", ALL_YEARS_RAW_CSV_FILE)
    print("all_year 總列數：", len(all_rows))


# =========================================================
# 10. status 歷史 append 工具
# =========================================================


def ensure_status_csv_schema() -> None:
    """確保 status.csv 使用目前 7 欄表頭；舊版時保留資料並升級。"""
    if not STATUS_CSV_FILE.exists() or STATUS_CSV_FILE.stat().st_size == 0:
        write_csv_atomic(STATUS_CSV_FILE, [], STATUS_FIELDNAMES)
        return

    with STATUS_CSV_FILE.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        existing_fieldnames = reader.fieldnames or []
        existing_rows = list(reader)

    if existing_fieldnames == STATUS_FIELDNAMES:
        return

    migrated_rows: List[Dict[str, str]] = []
    for old_row in existing_rows:
        migrated_row = {field: "" for field in STATUS_FIELDNAMES}
        for field in STATUS_FIELDNAMES:
            if field in old_row:
                migrated_row[field] = str(old_row.get(field, "") or "")
        migrated_rows.append(migrated_row)

    write_csv_atomic(STATUS_CSV_FILE, migrated_rows, STATUS_FIELDNAMES)
    print("status CSV 已升級為目前欄位結構：", STATUS_CSV_FILE)


def append_status_row(row: Dict[str, str]) -> None:
    """將一筆 status 歷史追加到固定 status.csv。"""
    ensure_status_csv_schema()

    with STATUS_CSV_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=STATUS_FIELDNAMES,
            extrasaction="ignore",
        )
        writer.writerow(row)


def record_no_data(year: str, page: int, row_number: int, reason: str) -> None:
    """記錄正常的「目前沒有資料」狀態；這不是 failed。"""
    status_row = {
        "執行批次ID": RUN_BATCH_ID,
        "執行時間": RUN_TIME,
        "憑證發放年份": str(year),
        "頁數": str(page),
        "筆數": str(row_number),
        "狀態": "目前沒有資料",
        "原因": reason,
    }

    append_status_row(status_row)

    print("\n========== 目前沒有資料 ==========")
    print(status_row)

    # status 是歷史資料，立即上傳可減少 Job 中斷時遺失紀錄的機會。
    upload_file_to_gcs(STATUS_CSV_FILE)


# =========================================================
# 11. failed 即時保存工具
# =========================================================


def save_failed_csv(force_create_empty: bool = True) -> None:
    """覆蓋寫入本次 01 的 failed.csv。"""
    if not failed_data and not force_create_empty:
        return

    write_csv_atomic(FAILED_CSV_FILE, failed_data, FAILED_FIELDNAMES)
    print("failed CSV 已存檔：", FAILED_CSV_FILE)
    print("本次真正失敗筆數：", len(failed_data))


def initialize_failed_csv_for_new_run() -> None:
    """01 開始時，failed.csv 只重設為本次空失敗清單。"""
    failed_data.clear()
    save_failed_csv(force_create_empty=True)
    upload_file_to_gcs(FAILED_CSV_FILE)

    print("\nfailed.csv 已重設為本次 01 的空失敗清單")


def record_failed(
    *,
    year: str,
    page: int,
    row_number: int,
    seller_name: str = "",
    generation_device: str = "",
    buyer: str = "",
    reason: str,
    stage: str = "",
    api_url: str = "",
    payload: Optional[Dict[str, Any]] = None,
    http_status: Optional[int] = None,
    response_preview: Optional[str] = None,
    exception: Optional[BaseException] = None,
) -> None:
    """記錄真正失敗，立即存 failed.csv 並上傳 GCS。"""
    failed_row = {
        "憑證發放年份": str(year),
        "頁數": str(page),
        "筆數": str(row_number),
        "出售單位": clean_company_name(seller_name),
        "發電設備": clean_text(generation_device),
        "購買者": clean_company_name(buyer),
        "原因": reason,
    }
    failed_data.append(failed_row)

    print("\n!!!!!!!!!! 抓取失敗 !!!!!!!!!!")
    if stage:
        print("失敗階段：", stage)
    print("失敗原因：", reason)
    print("年份：", year)
    print("頁數：", page)
    print("筆數：", row_number)
    if api_url:
        print("API URL：", api_url)
    if http_status is not None:
        print("HTTP 狀態碼：", http_status)
    if payload:
        print("payload：", payload)
    if response_preview:
        print("回應預覽：")
        print(preview_text(response_preview))
    if exception is not None:
        print("例外：", type(exception).__name__, exception)
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

    save_failed_csv(force_create_empty=True)
    upload_file_to_gcs(FAILED_CSV_FILE)


# =========================================================
# 12. DataTables payload / headers
# =========================================================


def build_data_payload(year: str, page_number: int) -> Dict[str, str]:
    """
    建立網站實際使用的 DataTables form payload。

    已依 Chrome DevTools Network -> Payload 核對：
    - POST form-data（application/x-www-form-urlencoded）
    - search[year] 是真正的年份篩選參數
    - search[energy] = -1 代表「全部能源類型」
    - year 是頁面基準年度，不是表格篩選條件
    - start + length 是分頁
    - created_at 由新到舊排序
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
        # 真正控制表格資料的篩選欄位。
        "search[year]": str(year),
        "search[energy]": "-1",
        # 這是頁面基準年度，不是表格篩選年度。
        # DevTools 證實：查 2025 時，瀏覽器仍送 year=2026。
        "year": API_BASE_YEAR,
    }


def get_csrf_token(page: Any) -> str:
    """從首頁 meta tag 取得 CSRF token；拿不到時仍會嘗試呼叫 API。"""
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
    """
    建立 data API request headers。

    Cookie 不手動複製。Playwright 開首頁後，context.request 會自動共用 Cookie。
    """
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.trec.org.tw",
        "Referer": START_URL,
    }
    if csrf_token:
        headers["X-CSRF-TOKEN"] = csrf_token
    return headers


# =========================================================
# 13. 年份偵測工具
# =========================================================


def find_year_dropdown(page: Any) -> Any:
    """找到頁面上的「憑證發放年份」下拉選單。"""
    candidates = [
        "xpath=//*[normalize-space(text())='憑證發放年份']/following::div[contains(@class, 'dropdown')][1]",
        "xpath=//*[contains(normalize-space(text()), '憑證發放年份')]/following::div[contains(@class, 'dropdown')][1]",
        "div.ui.selection.dropdown",
        "div.ui.dropdown",
    ]

    for selector in candidates:
        locator = page.locator(selector)
        try:
            count = locator.count()
        except Exception:
            count = 0

        for index in range(count):
            candidate = locator.nth(index)
            try:
                if not candidate.is_visible(timeout=1000):
                    continue
                content = f"{candidate.inner_text(timeout=1000)} {candidate.evaluate('el => el.innerHTML')}"
                if re.search(r"20\d{2}", content):
                    return candidate
            except Exception:
                continue

    raise RuntimeError("找不到憑證發放年份下拉選單")


def get_all_years_from_page(page: Any) -> List[str]:
    """從網站頁面偵測全部可選年份，供 YEARS_TO_CRAWL=ALL 使用。"""
    years: List[str] = []

    # 先嘗試直接從 HTML 找 data-value，通常最快也最穩。
    try:
        content = page.content()
        years.extend(re.findall(r"data-value=[\"'](20\d{2})[\"']", content))
    except Exception:
        pass

    # 若直接 HTML 找不到，再展開下拉選單讀取項目。
    if not years:
        try:
            dropdown = find_year_dropdown(page)
            dropdown.scroll_into_view_if_needed(timeout=5000)
            dropdown.click(force=True, timeout=5000)
            page.wait_for_timeout(500)

            items = page.locator(
                ".visible.menu .item, .menu.transition.visible .item, .menu .item"
            )
            for index in range(items.count()):
                item = items.nth(index)
                try:
                    text = item.inner_text(timeout=1000).strip()
                    data_value = item.get_attribute("data-value", timeout=1000) or ""
                    years.extend(re.findall(r"\b(20\d{2})\b", f"{text} {data_value}"))
                except Exception:
                    continue

            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
        except Exception as e:
            print("警告：從年份下拉選單偵測年份失敗：", type(e).__name__, e)

    return sorted(set(years), reverse=True)


def get_years_to_crawl(page: Any) -> List[str]:
    """依 YEARS_TO_CRAWL 決定本次抓哪些年份。"""
    if not YEARS_ENV:
        return []

    if YEARS_ENV.upper() in {"ALL", "AUTO"}:
        years = get_all_years_from_page(page)
        if not years:
            raise RuntimeError("YEARS_TO_CRAWL=ALL，但無法從網站偵測任何年份")
        return years

    years = [year.strip() for year in YEARS_ENV.split(",") if year.strip()]
    invalid_years = [year for year in years if not re.fullmatch(r"20\d{2}", year)]
    if invalid_years:
        raise ValueError(f"YEARS_TO_CRAWL 有不合法年份：{invalid_years}")
    return years


def validate_response_year(
    data_json: Dict[str, Any],
    requested_year: str,
) -> Tuple[bool, str]:
    """
    防呆：確認 API 回傳資料的 certification_year 真的是本次要求年度。

    data 為空時沒有資料可驗證，交由後續「沒有資料」流程處理。
    """
    items = data_json.get("data")
    if not isinstance(items, list):
        return False, "data API 的 data 欄位不是 list"

    returned_years = sorted(
        {
            str(item.get("certification_year", "")).strip()
            for item in items
            if isinstance(item, dict)
            and str(item.get("certification_year", "")).strip()
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
# 14. data API 呼叫
# =========================================================


def fetch_data_api(
    context: Any,
    csrf_token: str,
    year: str,
    page_number: int,
    year_stats: YearStats,
    run_stats: RunStats,
) -> Optional[Dict[str, Any]]:
    """呼叫 data API 一次；01 不 retry，失敗交由 02 處理。"""
    payload = build_data_payload(year, page_number)

    try:
        response = context.request.post(
            DATA_API_URL,
            form=payload,
            headers=build_headers(csrf_token),
            timeout=API_TIMEOUT_MS,
        )

        if not response.ok:
            year_stats.failure_count += 1
            run_stats.total_failure_count += 1
            record_failed(
                year=year,
                page=page_number,
                row_number=0,
                reason=f"data API HTTP 狀態碼不是 2xx，status={response.status}",
                stage="data API",
                api_url=DATA_API_URL,
                payload=payload,
                http_status=response.status,
                response_preview=response.text(),
            )
            return None

        try:
            data_json = response.json()
        except Exception as e:
            year_stats.failure_count += 1
            run_stats.total_failure_count += 1
            record_failed(
                year=year,
                page=page_number,
                row_number=0,
                reason=f"data API 回應無法解析為 JSON：{type(e).__name__}，{e}",
                stage="data API JSON 解析",
                api_url=DATA_API_URL,
                payload=payload,
                http_status=response.status,
                response_preview=response.text(),
                exception=e,
            )
            return None

        if not isinstance(data_json, dict):
            year_stats.failure_count += 1
            run_stats.total_failure_count += 1
            record_failed(
                year=year,
                page=page_number,
                row_number=0,
                reason="data API JSON 根節點不是預期的 object 格式",
                stage="data API JSON 結構",
                api_url=DATA_API_URL,
                payload=payload,
                http_status=response.status,
                response_preview=str(data_json),
            )
            return None

        valid_year, year_message = validate_response_year(data_json, year)
        print(f"年份驗證：{year_message}")
        if not valid_year:
            year_stats.failure_count += 1
            run_stats.total_failure_count += 1
            record_failed(
                year=year,
                page=page_number,
                row_number=0,
                reason=year_message,
                stage="data API 年份驗證",
                api_url=DATA_API_URL,
                payload=payload,
                http_status=response.status,
                response_preview=response.text(),
            )
            return None

        return data_json

    except Exception as e:
        year_stats.failure_count += 1
        run_stats.total_failure_count += 1
        record_failed(
            year=year,
            page=page_number,
            row_number=0,
            reason=f"呼叫 data API 發生例外：{type(e).__name__}，{e}",
            stage="data API 請求",
            api_url=DATA_API_URL,
            payload=payload,
            exception=e,
        )
        return None


# =========================================================
# 15. 保存入口
# =========================================================


def save_everything(current_year: Optional[str], upload: bool = True) -> None:
    """
    01 統一保存流程：
    1. 寫出目前年度 raw。
    2. 用每年最新年度 raw 重建 all_year。
    3. 覆蓋寫入本次 failed.csv。
    4. 上傳輸出到 GCS。
    """
    if current_year:
        save_year_raw_csv(current_year)

    rebuild_all_year_csv()
    save_failed_csv(force_create_empty=True)

    if upload:
        upload_output_files_to_gcs()


# =========================================================
# 16. 單一年份抓取流程
# =========================================================


def crawl_one_year(
    context: Any,
    csrf_token: str,
    year: str,
    run_stats: RunStats,
) -> None:
    """抓取指定年度的所有 DataTables 頁面。"""
    year_stats = YearStats(year=year)

    print("\n" + "=" * 80)
    print(f"開始抓年份：{year}")
    print("=" * 80)

    page_number = 1
    known_total_pages: Optional[int] = None

    while True:
        if MAX_PAGES_PER_YEAR > 0 and page_number > MAX_PAGES_PER_YEAR:
            print(
                f"年份 {year} 已達 MAX_PAGES_PER_YEAR={MAX_PAGES_PER_YEAR}，停止本年份"
            )
            break

        print(f"\n年份 {year}，第 {page_number} 頁")

        data_json = fetch_data_api(
            context=context,
            csrf_token=csrf_token,
            year=year,
            page_number=page_number,
            year_stats=year_stats,
            run_stats=run_stats,
        )

        if data_json is None:
            # 第 1 頁失敗時不知道總頁數，不能猜後面有多少頁。
            if known_total_pages is None:
                print(
                    f"年份 {year} 第 {page_number} 頁 data API 失敗，"
                    "尚未知總頁數，停止本年份，交由 02 retry"
                )
                break

            # 已知總頁數時，可略過失敗頁並繼續抓後面頁；02 會補這一頁。
            print(
                f"年份 {year} 第 {page_number} 頁 data API 失敗，"
                "略過本頁、繼續後續頁面，交由 02 retry"
            )

            if page_number >= known_total_pages:
                break

            page_number += 1
            if DATA_API_SLEEP_SECONDS > 0:
                time.sleep(DATA_API_SLEEP_SECONDS)
            continue

        year_stats.pages_checked += 1

        try:
            records_total = int(data_json.get("recordsTotal") or 0)
            records_filtered = int(data_json.get("recordsFiltered") or 0)
            items = data_json.get("data") or []

            if not isinstance(items, list):
                raise TypeError("data API 的 data 欄位不是 list")
        except Exception as e:
            year_stats.failure_count += 1
            run_stats.total_failure_count += 1
            record_failed(
                year=year,
                page=page_number,
                row_number=0,
                reason=f"data API JSON 結構不是預期格式：{type(e).__name__}，{e}",
                stage="解析 data API JSON 結構",
                api_url=DATA_API_URL,
                response_preview=str(data_json),
                exception=e,
            )

            if known_total_pages is None or page_number >= known_total_pages:
                break

            page_number += 1
            if DATA_API_SLEEP_SECONDS > 0:
                time.sleep(DATA_API_SLEEP_SECONDS)
            continue

        # API 正常回傳後，才可安全計算總頁數。
        if records_filtered > 0:
            known_total_pages = (records_filtered + PAGE_LENGTH - 1) // PAGE_LENGTH

        # 第 1 頁就沒有資料 = 這一年目前沒有資料，這不是失敗。
        if records_total == 0 or records_filtered == 0:
            if page_number == 1:
                record_no_data(
                    year=year,
                    page=1,
                    row_number=0,
                    reason="data API 顯示該年份目前沒有資料",
                )
                year_stats.no_data_recorded = True
            else:
                print(f"年份 {year} 第 {page_number} 頁沒有更多資料")
            break

        # 有總筆數但這一頁卻空，通常代表已超出最後一頁或網站資料同步中。
        if not items:
            print(f"年份 {year} 第 {page_number} 頁 data 為空，停止本年份")
            break

        year_stats.api_rows += len(items)
        run_stats.total_api_rows += len(items)

        print("recordsTotal：", records_total)
        print("recordsFiltered：", records_filtered)
        print("本頁資料筆數：", len(items))
        print("計算總頁數：", known_total_pages)

        for row_number_in_page, item in enumerate(items, start=1):
            try:
                raw_row = build_raw_row_from_api_item(item, year)
                add_raw_row(raw_row, year_stats, run_stats)
            except Exception as e:
                seller_name, generation_device, buyer_name = get_item_basic_info(item)
                year_stats.failure_count += 1
                run_stats.total_failure_count += 1
                record_failed(
                    year=year,
                    page=page_number,
                    row_number=row_number_in_page,
                    seller_name=seller_name,
                    generation_device=generation_device,
                    buyer=buyer_name,
                    reason=f"單筆 data API 資料無法轉成 CSV：{type(e).__name__}，{e}",
                    stage="轉換單筆 data API 資料",
                    api_url=DATA_API_URL,
                    payload=build_data_payload(year, page_number),
                    response_preview=str(item),
                    exception=e,
                )

        # 每 N 頁保存一次，讓 Cloud Run 中斷時不至於遺失太多進度。
        if SAVE_EVERY_PAGES > 0 and page_number % SAVE_EVERY_PAGES == 0:
            print(f"\n年份 {year} 已完成第 {page_number} 頁，進行批次存檔與上傳")
            save_everything(current_year=year, upload=True)

        if known_total_pages is not None and page_number >= known_total_pages:
            print(
                f"年份 {year} 已抓到最後一頁："
                f"第 {page_number} 頁 / 共 {known_total_pages} 頁"
            )
            break

        page_number += 1
        if DATA_API_SLEEP_SECONDS > 0:
            time.sleep(DATA_API_SLEEP_SECONDS)

    # API 完全正常、卻沒有輸出任何 row 時，保留一筆 status 方便未來檢查。
    if (
        year_stats.success_rows == 0
        and year_stats.failure_count == 0
        and not year_stats.no_data_recorded
    ):
        record_no_data(
            year=year,
            page=1,
            row_number=0,
            reason="本年份沒有任何可輸出的交易資料",
        )
        year_stats.no_data_recorded = True

    print("\n" + "=" * 80)
    print(f"年份 {year} 抓取完成")
    print("成功取得 data API 頁數：", year_stats.pages_checked)
    print("data API 資料總筆數：", year_stats.api_rows)
    print("成功輸出資料列數：", year_stats.success_rows)
    print("真正失敗筆數：", year_stats.failure_count)
    print("=" * 80)

    # 年度結束時一定再保存一次。
    save_everything(current_year=year, upload=True)
    run_stats.years_checked += 1


# =========================================================
# 17. main
# =========================================================


def main() -> int:
    """01 入口：GCS 準備 -> 首頁 Cookie/CSRF -> data API 分頁抓取。"""
    global storage_client

    run_stats = RunStats()
    current_year: Optional[str] = None
    browser: Optional[Any] = None
    context: Optional[Any] = None

    print("\n========== 01 自用發電設備成交紀錄 raw 爬蟲啟動 ==========")
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR)
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)
    print("PIPELINE_DT：", PIPELINE_DT)
    print("RUN_BATCH_ID：", RUN_BATCH_ID)
    print("RUN_TIME：", RUN_TIME)
    print("YEARS_TO_CRAWL：", YEARS_ENV)
    print("MAX_PAGES_PER_YEAR：", MAX_PAGES_PER_YEAR)
    print("PAGE_LENGTH：", PAGE_LENGTH)
    print("SAVE_EVERY_PAGES：", SAVE_EVERY_PAGES)
    print("DATA_API_SLEEP_SECONDS：", DATA_API_SLEEP_SECONDS)
    print("API_BASE_YEAR：", API_BASE_YEAR)
    print("API_TIMEOUT_MS：", API_TIMEOUT_MS)
    print("HEADLESS：", HEADLESS)
    print(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH：",
        PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH or "(使用 Playwright 內建 Chromium)",
    )

    try:
        # 1. 部分年度更新時，從最新 raw/dt 快照複製未更新年度；status 從 control/ 下載。
        storage_client = create_storage_client()
        download_existing_output_files_from_gcs()

        # 2. failed.csv 只代表本次 01，一開始先重設為空檔並上傳。
        initialize_failed_csv_for_new_run()

        # 3. 開首頁取得 Cookie / CSRF token，再使用同一 context.request 呼叫 API。
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
                print("警告：沒有取得 CSRF Token，仍會嘗試 API")

            years = get_years_to_crawl(page)
            if not years:
                raise RuntimeError(
                    "沒有任何年份可抓。請檢查 YEARS_TO_CRAWL；空字串不是預設 2026。"
                )

            print("本次要抓年份：", years)

            for year in years:
                current_year = year
                crawl_one_year(
                    context=context,
                    csrf_token=csrf_token,
                    year=year,
                    run_stats=run_stats,
                )

        print("\n" + "#" * 80)
        print("01 全部完成")
        print("完成檢查年份數：", run_stats.years_checked)
        print("data API 總筆數：", run_stats.total_api_rows)
        print("成功輸出資料總列數：", run_stats.total_success_rows)
        print("總共真正失敗筆數：", run_stats.total_failure_count)
        print("raw 快照：", raw_snapshot_prefix())
        print("all_year CSV：", ALL_YEARS_RAW_CSV_FILE)
        print("status CSV：", STATUS_CSV_FILE)
        print("failed CSV：", FAILED_CSV_FILE)
        print("#" * 80)

        return 0

    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，中斷前嘗試保存與上傳目前資料")
        try:
            save_everything(current_year=current_year, upload=True)
        except Exception as save_error:
            print("中斷後保存失敗：", type(save_error).__name__, save_error)
        return 1

    except Exception as e:
        print("\n01 發生未預期錯誤：", type(e).__name__, e)
        print(traceback.format_exc())
        print("嘗試保存與上傳目前資料")

        try:
            save_everything(current_year=current_year, upload=True)
        except Exception as save_error:
            print("錯誤後保存又失敗：", type(save_error).__name__, save_error)

        return 1

    finally:
        print("\n關閉 Playwright 瀏覽器資源")
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

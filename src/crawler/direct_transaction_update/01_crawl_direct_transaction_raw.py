"""
01_crawl_direct_transaction_raw_cloudrun_playwright.py

T-REC 直轉供憑證成交紀錄：Cloud Run Playwright + API raw 爬蟲版

本版用途：
1. 執行於 Cloud Run Job。
2. 使用 Playwright 開啟首頁取得 Cookie / CSRF Token。
3. 使用 data API 抓外層列表、detail API 抓成交明細，不再用 Selenium 點表格與詳情彈窗。
4. raw 階段保留網站原始成交資料，不去重複。
5. 成功資料寫入年度 raw CSV，並重建 all_year CSV。
6. 每個年份最新年度 raw 會合併到 all_year；更新某一年時會保留其他年份資料。
7. Cloud Run 的 /tmp 是暫存空間：啟動時先從 GCS 下載舊年度 raw 與 status 歷史檔。
8. 每 SAVE_EVERY_PAGES 頁保存年度 raw / all_year / status / failed，並上傳 GCS。
9. 每一年結束一定再保存與上傳一次。
10. failed.csv 使用固定檔名；每次 01 開始時清空成只有表頭，代表本次 01 的失敗清單。
11. 發生真正失敗時，failed.csv 會立即寫入並上傳 GCS。
12. status.csv 使用固定檔名；遇到「目前沒有資料」時採 append，永久保留歷史紀錄。
13. detail 的「成交記錄 <ol></ol> 空白」不是失敗，只代表該筆沒有成交記錄。
14. 01 不做 retry；retry 交給 02。
15. 不做 checkpoint；每次 01 都從第 1 頁開始抓。

執行環境變數：
    GCS_BUCKET=tibame-bronze
    GCS_PREFIX=direct_transaction
    LOCAL_WORKDIR=/tmp

    YEARS_TO_CRAWL=2026
    YEARS_TO_CRAWL=2026,2025
    YEARS_TO_CRAWL=ALL

    MAX_PAGES_PER_YEAR=0
    SAVE_EVERY_PAGES=10
    PAGE_LENGTH=10

    YEAR_CHANGE_WAIT_SECONDS=2
    DATA_API_SLEEP_SECONDS=2
    DETAIL_API_SLEEP_SECONDS=1
    API_TIMEOUT_MS=30000

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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.cloud import storage
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# =========================================================
# 1. 網站與 Cloud Run 基本設定
# =========================================================

START_URL = "https://www.trec.org.tw/certification_trade_situation/direct_supply"
DATA_API_URL = (
    "https://www.trec.org.tw/certification_trade_situation/direct_supply/data"
)
DETAIL_API_URL = (
    "https://www.trec.org.tw/certification_trade_situation/direct_supply/detail"
)

# Cloud Run 容器的 /tmp 只適合暫存；正式資料最後一定要上傳 GCS。
LOCAL_WORKDIR = Path(os.getenv("LOCAL_WORKDIR", "/tmp")).resolve()
LOCAL_WORKDIR.mkdir(parents=True, exist_ok=True)

GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()
GCS_PREFIX = os.getenv(
    "GCS_PREFIX",
    "direct_transaction",
).strip("/")


# =========================================================
# 2. 執行參數
# =========================================================

RAW_PREFIX = "trec_direct_transaction_raw"

# T-REC data API 真正用 search[year] 篩選資料年度。
# 從瀏覽器 Network Payload 驗證，網站目前固定傳 year=2026。
API_BASE_YEAR = os.getenv("API_BASE_YEAR", "2026").strip()

# 只有「環境變數根本不存在」時才預設為 2026。
# 若把 Cloud Run 設成 YEARS_TO_CRAWL=""，會得到空字串並視為設定錯誤。
YEARS_ENV = os.getenv("YEARS_TO_CRAWL", "2026").strip()

# 0 = 不限制頁數，完整抓該年度。
MAX_PAGES_PER_YEAR = int(os.getenv("MAX_PAGES_PER_YEAR", "0"))

# T-REC DataTables 一頁固定抓幾筆。
PAGE_LENGTH = int(os.getenv("PAGE_LENGTH", "10"))

# 每完成幾頁保存並上傳一次。
SAVE_EVERY_PAGES = int(os.getenv("SAVE_EVERY_PAGES", "10"))

# API 單次請求 timeout，單位：毫秒。
API_TIMEOUT_MS = int(os.getenv("API_TIMEOUT_MS", "30000"))

# 切換年度後，等待 year-power 畫面更新時間，單位：秒。
YEAR_CHANGE_WAIT_SECONDS = float(os.getenv("YEAR_CHANGE_WAIT_SECONDS", "2"))

# 一整頁資料都處理完後，下一頁 data API 前的等待秒數。
DATA_API_SLEEP_SECONDS = float(os.getenv("DATA_API_SLEEP_SECONDS", "2"))

# 每一筆 detail API 處理完後，下一筆 detail API 前的等待秒數。
DETAIL_API_SLEEP_SECONDS = float(os.getenv("DETAIL_API_SLEEP_SECONDS", "1"))

# Cloud Run 正式執行預設無頭模式；HEADLESS=false 可在地端除錯時看瀏覽器。
HEADLESS = os.getenv("HEADLESS", "true").lower() != "false"

# 若 Dockerfile 安裝的是系統 Chromium（例如 /usr/bin/chromium），
# Playwright 會優先使用它；若路徑不存在，則改使用 Playwright 自己安裝的 Chromium。
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH = os.getenv(
    "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
    "/usr/bin/chromium",
).strip()


# =========================================================
# 3. 本次執行批次資訊、資料快照日期與檔案名稱
# =========================================================


def get_taipei_now() -> datetime:
    """取得專案使用的台灣時間；時區設定異常時退回系統本地時間。"""
    timezone_name = os.getenv("PIPELINE_TIMEZONE", "Asia/Taipei").strip() or "Asia/Taipei"
    try:
        return datetime.now(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError:
        print(f"警告：找不到時區 {timezone_name}，改用系統本地時間")
        return datetime.now()


def get_pipeline_dt() -> str:
    """
    取得同一次 01→02→03 共用的資料快照日期。

    - 04 / 05 會在一開始設定 PIPELINE_DT，避免跨午夜時三支程式落到不同 dt。
    - 單獨執行時，預設採用 Asia/Taipei 當日日期。
    """
    value = os.getenv("PIPELINE_DT", "").strip()
    if not value:
        return get_taipei_now().strftime("%Y-%m-%d")

    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(
            "PIPELINE_DT 必須是 YYYY-MM-DD，例如 2026-07-01"
        ) from exc
    return value


PIPELINE_DT = get_pipeline_dt()
PIPELINE_DATE_COMPACT = PIPELINE_DT.replace("-", "")
RUN_NOW = get_taipei_now()
RUN_BATCH_ID = RUN_NOW.strftime("%Y%m%d_%H%M%S_%f")
RUN_TIME = RUN_NOW.strftime("%Y-%m-%d %H:%M:%S")

# 01 只會寫入 raw 歷史快照與 control 控制檔。
RAW_ROOT = "raw"
CONTROL_ROOT = "control"

ALL_YEARS_RAW_CSV_NAME = f"{RAW_PREFIX}_all_year_{PIPELINE_DATE_COMPACT}.csv"
STATUS_CSV_NAME = f"{RAW_PREFIX}_status.csv"
FAILED_CSV_NAME = f"{RAW_PREFIX}_failed.csv"


def get_year_raw_csv_name(year: str) -> str:
    """年度 raw 檔名，例如 trec_direct_transaction_raw_2026_20260701.csv。"""
    return f"{RAW_PREFIX}_{year}_{PIPELINE_DATE_COMPACT}.csv"


def local_path(filename: str) -> Path:
    """組出 Cloud Run /tmp 底下的暫存檔路徑。"""
    return LOCAL_WORKDIR / filename


ALL_YEARS_RAW_CSV_FILE = local_path(ALL_YEARS_RAW_CSV_NAME)
STATUS_CSV_FILE = local_path(STATUS_CSV_NAME)
FAILED_CSV_FILE = local_path(FAILED_CSV_NAME)

# =========================================================
# 4. CSV 欄位
# =========================================================

FIELDNAMES: List[str] = [
    "出售單位",
    "發電設備",
    "購買者",
    "能源類型",
    "供電種類",
    "總移轉量(MWh)",
    "成交日期",
    "成交移轉量(MWh)",
]

# status 是歷史紀錄，因此加入執行批次與時間，並使用 append。
STATUS_FIELDNAMES: List[str] = [
    "執行批次ID",
    "執行時間",
    "憑證發放年份",
    "頁數",
    "筆數",
    "狀態",
    "原因",
]

# failed 只代表「本次 01」的失敗清單，因此不保留歷史、每次重新建立。
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
# 5. 全域暫存資料與統計
# =========================================================

# raw_data 只存「本次 01」成功抓到的資料，不載入舊年度 raw 進來。
raw_data: List[Dict[str, str]] = []

# failed_data 只存「本次 01」的真正失敗，Job 開始時會是空的。
failed_data: List[Dict[str, str]] = []

storage_client: Optional[storage.Client] = None


@dataclass
class YearStats:
    year: str
    pages_checked: int = 0
    outer_rows: int = 0
    detail_checked: int = 0
    empty_trade_record_count: int = 0
    success_rows: int = 0
    failure_count: int = 0


@dataclass
class RunStats:
    years_checked: int = 0
    total_outer_rows: int = 0
    total_detail_checked: int = 0
    total_empty_trade_record_count: int = 0
    total_success_rows: int = 0
    total_failure_count: int = 0


# =========================================================
# 6. HTML / 文字清理工具
# =========================================================


class SimpleHTMLTextParser(HTMLParser):
    """把 detail API 回傳的 HTML 轉成可解析純文字。"""

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


def html_to_text(value: Any) -> str:
    """HTML 字串轉成乾淨的純文字。"""
    if value is None:
        return ""

    parser = SimpleHTMLTextParser()
    parser.feed(html.unescape(str(value)))

    lines = [line.strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def html_to_lines(value: Any) -> List[str]:
    """HTML 字串轉成非空白文字行清單。"""
    return [line.strip() for line in html_to_text(value).splitlines() if line.strip()]


def clean_company_name(value: Any) -> str:
    """公司名稱清理：全形括號轉半形、去掉多餘空白。"""
    if value is None:
        return ""

    text = str(value).strip()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s*\(\s*", "(", text)
    text = re.sub(r"\s*\)\s*", ")", text)
    return text


def clean_number(value: Any) -> str:
    """數字字串清理：去掉空白與千分位逗號。"""
    if value is None:
        return ""
    return str(value).strip().replace(",", "")


def parse_number(value: Any) -> Optional[float]:
    """從畫面文字中取得第一個數值，例如 '0 MWh' -> 0.0。"""
    text = clean_number(value)
    if not text:
        return None

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None

    try:
        return float(match.group())
    except ValueError:
        return None


def preview_text(value: Optional[str], limit: int = 800) -> str:
    """失敗時只保留回應前段，避免 Cloud Run log 過長。"""
    if not value:
        return ""

    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...（後面省略）"


# =========================================================
# 7. CSV 讀寫工具
# =========================================================


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    """讀 CSV；不存在、空檔時回傳空清單。"""
    if not path.exists() or path.stat().st_size == 0:
        return []

    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv_atomic(
    path: Path,
    rows: List[Dict[str, Any]],
    fieldnames: List[str],
) -> None:
    """先寫 tmp，再 os.replace，避免中斷時正式 CSV 壞掉。"""
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
    """統一 raw 資料格式；__year 是程式內部欄位，不會寫入 CSV。"""
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


# =========================================================
# 8. GCS 工具：raw 快照 / control 控制檔
# =========================================================


def gcs_join(*parts: str) -> str:
    """安全組出 GCS object name，不產生重複斜線。"""
    cleaned = [str(part).strip("/") for part in parts if str(part).strip("/")]
    return "/".join(cleaned)


def raw_snapshot_prefix(dt: str = PIPELINE_DT) -> str:
    """回傳 raw/dt=YYYY-MM-DD 這次快照的 GCS prefix。"""
    return gcs_join(GCS_PREFIX, RAW_ROOT, f"dt={dt}")


def raw_snapshot_blob_name(filename: str, dt: str = PIPELINE_DT) -> str:
    """回傳指定 raw 快照內某檔案的完整 GCS object name。"""
    return gcs_join(raw_snapshot_prefix(dt), filename)


def control_blob_name(filename: str) -> str:
    """回傳 control 區控制檔的完整 GCS object name。"""
    return gcs_join(GCS_PREFIX, CONTROL_ROOT, filename)


def create_storage_client() -> storage.Client:
    """建立 GCS client；Cloud Run 需具備 bucket 讀寫權限。"""
    if not GCS_BUCKET:
        raise ValueError(
            "沒有設定 GCS_BUCKET，請在 Cloud Run Job 環境變數設定 bucket 名稱"
        )
    return storage.Client()


def upload_file_to_gcs(path: Path, blob_name: str) -> None:
    """把本機檔案上傳到指定 GCS object。"""
    if not path.exists():
        return
    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法上傳 GCS")

    bucket = storage_client.bucket(GCS_BUCKET)
    bucket.blob(blob_name).upload_from_filename(str(path))
    print(f"已上傳 GCS：{path}")
    print(f"GCS 位置：gs://{GCS_BUCKET}/{blob_name}")


def download_blob_to_path(blob_name: str, destination: Path) -> bool:
    """下載指定 object；不存在時回傳 False。"""
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
    """判斷新架構的年度 raw 檔名。"""
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
    """
    找 raw/ 下日期最新、且具有對應 all_year CSV 的快照。

    只以：
        raw/dt=YYYY-MM-DD/trec_direct_transaction_raw_all_year_YYYYMMDD.csv
    是否存在，判定該 dt 是可沿用的快照來源。
    """
    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法列出 GCS")

    root_prefix = gcs_join(GCS_PREFIX, RAW_ROOT)
    list_prefix = root_prefix + "/"
    pattern = re.compile(
        rf"^{re.escape(root_prefix)}/dt=(\d{{4}}-\d{{2}}-\d{{2}})/"
        rf"{re.escape(RAW_PREFIX)}_all_year_(\d{{8}})\.csv$"
    )
    candidates: List[str] = []

    for blob in storage_client.list_blobs(GCS_BUCKET, prefix=list_prefix):
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
    - YEARS_TO_CRAWL=ALL：不複製舊年度，所有年度都重新抓。
    - 指定部分年度：從 raw/ 下日期最新的快照下載「未更新年度」到 /tmp，
      並改成本次 PIPELINE_DT 的檔名；本次重新抓的年度會覆蓋自己的 local 檔。

    回傳使用的來源快照日期；沒有可用快照時回傳 None。
    """
    print("\n========== 01 準備 GCS 快照資料 ==========")
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)
    print("PIPELINE_DT：", PIPELINE_DT)

    download_blob_to_path(control_blob_name(STATUS_CSV_NAME), STATUS_CSV_FILE)

    target_years = get_explicit_years_from_env()
    if target_years is None:
        print("YEARS_TO_CRAWL=ALL/AUTO：本次不下載舊年度 raw，全部年份重新抓取")
        return None

    source_dt = find_latest_raw_snapshot_dt()
    if source_dt is None:
        print(
            "警告：找不到可用的 raw 快照。此次將只建立指定年份的初始快照；"
            "正式第一次執行建議使用 YEARS_TO_CRAWL=ALL。"
        )
        return None

    source_prefix = raw_snapshot_prefix(source_dt) + "/"
    copied_years: List[str] = []

    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法下載 GCS")

    for blob in storage_client.list_blobs(GCS_BUCKET, prefix=source_prefix):
        filename = Path(blob.name).name
        parsed = parse_year_raw_filename(filename)
        if parsed is None:
            continue

        year, _source_date = parsed
        if year in target_years:
            continue

        destination = local_path(get_year_raw_csv_name(year))
        blob.download_to_filename(str(destination))
        copied_years.append(year)
        print(f"沿用舊年度：{year}，{blob.name} -> {destination.name}")

    print(
        f"已從 raw/dt={source_dt} 沿用年度：",
        ", ".join(sorted(copied_years)) or "(無)",
    )
    return source_dt


def upload_output_files_to_gcs() -> None:
    """
    上傳 01 管理的檔案。

    raw/dt=PIPELINE_DT/：年度 raw + all_year（checkpoint 可覆蓋）
    control/：failed、status（控制檔）
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
    row: Dict[str, str],
    year_stats: YearStats,
    run_stats: RunStats,
) -> None:
    """加入成功 raw；01 不在這裡去重複。"""
    raw_data.append(normalize_raw_row(row))
    year_stats.success_rows += 1
    run_stats.total_success_rows += 1


def save_year_raw_csv(year: str) -> None:
    """寫出本次 PIPELINE_DT 下指定年度的 raw CSV。"""
    year_rows = [
        normalize_raw_row(row)
        for row in raw_data
        if str(row.get("__year", "")) == str(year)
    ]

    year_file = local_path(get_year_raw_csv_name(year))
    write_csv_atomic(year_file, year_rows, FIELDNAMES)
    print("年度 raw 已存檔：", year_file)
    print("年度 raw 資料列數：", len(year_rows))


def find_latest_year_raw_files() -> Dict[str, Path]:
    """
    找出 /tmp 內本次 PIPELINE_DT 的每一年度 raw。

    01 已把沿用年度重新命名為本次日期，因此不需要以 mtime 猜哪個檔案較新。
    """
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
    """合併本次快照中每個年度 raw，建立本次 all_year。"""
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
    """
    確保固定 status.csv 使用新版欄位。

    若 GCS 上是舊版 5 欄 status，會保留舊資料並補空白的批次 / 時間欄位，
    再改寫成新版 7 欄，避免新資料 append 後欄位錯位。
    """
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
    print("status CSV 已自動轉換為新版欄位結構：", STATUS_CSV_FILE)


def append_status_row(row: Dict[str, str]) -> None:
    """將一筆無資料紀錄追加到固定 status.csv，並保留舊歷史。"""
    ensure_status_csv_schema()

    with STATUS_CSV_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=STATUS_FIELDNAMES,
            extrasaction="ignore",
        )
        writer.writerow(row)


def record_no_data(year: str, page: int, row_number: int, reason: str) -> None:
    """
    記錄「目前沒有資料」。

    這不是 failed：
    - 立即 append 到固定 status.csv。
    - 立即上傳 GCS，避免 Job 中斷時少歷史紀錄。
    """
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

    upload_file_to_gcs(STATUS_CSV_FILE, control_blob_name(STATUS_CSV_NAME))


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
    """
    01 一開始就清空並上傳 failed.csv。

    這不會清空資料夾，也不會刪年度 raw / all_year / status。
    只會讓 failed.csv 從此刻起代表「本次 01 的失敗清單」。
    """
    failed_data.clear()
    save_failed_csv(force_create_empty=True)
    upload_file_to_gcs(FAILED_CSV_FILE, control_blob_name(FAILED_CSV_NAME))

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
    """
    記錄真正失敗，並立即覆蓋寫入 failed.csv + 上傳 GCS。

    failed_data 是本次執行的累積清單，因此每次新失敗都會把「本次全部失敗」
    重寫回同一份固定 failed.csv。
    """
    failed_row = {
        "憑證發放年份": str(year),
        "頁數": str(page),
        "筆數": str(row_number),
        "出售單位": clean_company_name(seller_name),
        "發電設備": str(generation_device).strip(),
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

    # Cloud Run 重要保護：失敗發生當下就保存與上傳。
    save_failed_csv(force_create_empty=True)
    upload_file_to_gcs(FAILED_CSV_FILE, control_blob_name(FAILED_CSV_NAME))


# =========================================================
# 12. detail HTML 解析
# =========================================================


def extract_detail_field(detail_html: str, label: str) -> str:
    """從 detail HTML 的 label + div 結構取出欄位值。"""
    pattern = rf"<label>\s*{re.escape(label)}\s*</label>\s*<div>(.*?)</div>"
    match = re.search(pattern, detail_html, flags=re.S)
    return html_to_text(match.group(1)).strip() if match else ""


def has_trade_record_section(detail_html: str) -> bool:
    """判斷 detail HTML 是否存在「成交記錄」區塊。"""
    return "成交記錄" in html_to_text(detail_html)


def is_trade_record_ol_empty(detail_html: str) -> bool:
    """
    判斷成交記錄的 <ol> 是否真的空白。

    True 代表正常回覆、但沒有成交紀錄；這不是失敗，也不寫 failed。
    """
    pattern = r"<label>\s*成交記錄\s*</label>.*?<ol[^>]*>(.*?)</ol>"
    match = re.search(pattern, detail_html, flags=re.S)
    if not match:
        return False
    return html_to_text(match.group(1)).strip() == ""


def extract_trade_records(detail_html: str) -> List[Tuple[str, str]]:
    """解析所有『於 YYYY-MM-DD 移轉 xxx MWh』成交記錄。"""
    text = html_to_text(detail_html)
    matches = re.findall(
        r"於\s*(\d{4}-\d{2}-\d{2})\s*移轉\s*([\d,]+(?:\.\d+)?)\s*MWh",
        text,
    )
    return [(date_text, clean_number(mwh_text)) for date_text, mwh_text in matches]


# =========================================================
# 13. API payload / headers
# =========================================================


def build_data_payload(year: str, page_number: int) -> Dict[str, str]:
    """建立 DataTables data API 的 form payload。"""
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

        # 真正控制要抓哪一個憑證發放年份。
        "search[year]": str(year),

        # -1 代表網頁上的能源類型「全部」。
        "search[energy]": "-1",

        # 網站目前固定送出的基準參數，不是實際篩選年度。
        "year": API_BASE_YEAR,
    }


def build_detail_payload(item: Dict[str, Any], year: str) -> Dict[str, str]:
    """建立 detail API payload。"""
    return {
        "case_id": str(item.get("case_id", "")).strip(),
        "year": str(year).strip(),
        "buyer": str(item.get("buyer", "")).strip(),
        "seller": str(item.get("seller", "")).strip(),
    }


def get_csrf_token(page: Any) -> str:
    """從首頁 meta tag 取得 CSRF token；拿不到仍會繼續嘗試 API。"""
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
    """建立 API headers；Cookie 由 Playwright context.request 自動共用。"""
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
# 14. Playwright 年份與 year-power 工具
# =========================================================


def find_year_dropdown(page: Any) -> Any:
    """找到『憑證發放年份』的下拉選單。"""
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
                text = candidate.inner_text(timeout=1000)
                inner_html = candidate.evaluate("el => el.innerHTML")
                if re.search(r"20\d{2}", f"{text} {inner_html}"):
                    return candidate
            except Exception:
                continue

    raise RuntimeError("找不到憑證發放年份下拉選單")


def get_all_years_from_page(page: Any) -> List[str]:
    """從年份下拉選單讀取網站真正提供的全部年份。"""
    years: List[str] = []

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
        print("警告：從下拉選單讀年份失敗，改從頁面 HTML 偵測：", e)

    if not years:
        try:
            content = page.content()
            years = re.findall(r"data-value=[\"'](20\d{2})[\"']", content)
            if not years:
                years = re.findall(r"\b(20\d{2})\b", content)
        except Exception:
            years = []

    return sorted(set(years), reverse=True)


def get_years_to_crawl(page: Any) -> List[str]:
    """依 YEARS_TO_CRAWL 環境變數決定本次抓哪些年份。"""
    if not YEARS_ENV:
        return []

    if YEARS_ENV.upper() in {"ALL", "AUTO"}:
        years = get_all_years_from_page(page)
        if not years:
            raise RuntimeError("YEARS_TO_CRAWL=ALL，但無法從網站偵測任何年份")
        return years

    return [year.strip() for year in YEARS_ENV.split(",") if year.strip()]


def click_year(page: Any, year: str) -> None:
    """切換網頁年度，只用於讀取 year-power。"""
    print(f"切換網頁年份到：{year}")

    dropdown = find_year_dropdown(page)
    dropdown.scroll_into_view_if_needed(timeout=5000)
    dropdown.click(force=True, timeout=5000)
    page.wait_for_timeout(500)

    selectors = [
        f".visible.menu .item[data-value='{year}']",
        f".menu.transition.visible .item[data-value='{year}']",
        f".menu .item[data-value='{year}']",
    ]

    target: Optional[Any] = None

    for selector in selectors:
        locator = page.locator(selector)
        try:
            if locator.count() > 0:
                target = locator.first
                break
        except Exception:
            continue

    if target is None:
        items = page.locator(
            ".visible.menu .item, .menu.transition.visible .item, .menu .item"
        )
        for index in range(items.count()):
            item = items.nth(index)
            try:
                text = item.inner_text(timeout=1000).strip()
                data_value = item.get_attribute("data-value", timeout=1000) or ""
                if text == str(year) or data_value == str(year):
                    target = item
                    break
            except Exception:
                continue

    if target is None:
        raise RuntimeError(f"下拉選單找不到年份：{year}")

    target.scroll_into_view_if_needed(timeout=5000)
    target.click(force=True, timeout=5000)
    time.sleep(YEAR_CHANGE_WAIT_SECONDS)

    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeoutError:
        # 年份切換後不一定真的會進入 networkidle；不要因此中止整個年份。
        pass


def read_year_power(page: Any, year: str) -> Optional[float]:
    """
    讀取年度總移轉量 year-power。

    回傳：
    - 0.0：網站明確表示該年度目前沒有資料。
    - 大於 0：該年度有資料，繼續 API 流程。
    - None：畫面讀取失敗，改由 data API 決定。
    """
    try:
        click_year(page, year)
        text = page.locator("span.data.year-power").first.inner_text(timeout=8000)
        value = parse_number(text)
        print(f"年份 {year} year-power：{text}")
        return value
    except Exception as e:
        print(
            f"警告：年份 {year} 讀取 year-power 失敗，"
            f"改走 data API：{type(e).__name__}，{e}"
        )
        return None


# =========================================================
# 15. API 呼叫
# =========================================================


def fetch_data_api(
    context: Any,
    csrf_token: str,
    year: str,
    page_number: int,
    year_stats: YearStats,
    run_stats: RunStats,
) -> Optional[Dict[str, Any]]:
    """呼叫外層 data API；01 不 retry，失敗交給 02。"""
    payload = build_data_payload(year, page_number)

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

        if not response.ok:
            year_stats.failure_count += 1
            run_stats.total_failure_count += 1
            record_failed(
                year=year,
                page=page_number,
                row_number=0,
                reason=("data API HTTP 狀態碼不是 2xx，" f"status={response.status}"),
                stage="外層 data API",
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
                stage="外層 data API JSON 解析",
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
                stage="外層 data API JSON 結構",
                api_url=DATA_API_URL,
                payload=payload,
                http_status=response.status,
                response_preview=str(data_json),
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
            stage="外層 data API 請求",
            api_url=DATA_API_URL,
            payload=payload,
            exception=e,
        )
        return None


def get_item_basic_info(item: Dict[str, Any]) -> Tuple[str, str, str]:
    """從 data API item 取基本資料，供 failed CSV 使用。"""
    seller_lines = html_to_lines(item.get("seller_name", ""))
    seller_name = seller_lines[0] if seller_lines else ""
    generation_device = str(item.get("case_name", "")).strip()
    buyer_name = str(item.get("buyer_name", "")).strip()
    return seller_name, generation_device, buyer_name


def fetch_detail_api(
    context: Any,
    csrf_token: str,
    item: Dict[str, Any],
    year: str,
    page_number: int,
    row_number_in_page: int,
    year_stats: YearStats,
    run_stats: RunStats,
) -> Optional[str]:
    """呼叫 detail API；01 不 retry，失敗交給 02。"""
    payload = build_detail_payload(item, year)
    seller_name, generation_device, buyer_name = get_item_basic_info(item)

    try:
        response = context.request.post(
            DETAIL_API_URL,
            form=payload,
            headers=build_headers(csrf_token, "text/html, */*; q=0.01"),
            timeout=API_TIMEOUT_MS,
        )

        if not response.ok:
            year_stats.failure_count += 1
            run_stats.total_failure_count += 1
            record_failed(
                year=year,
                page=page_number,
                row_number=row_number_in_page,
                seller_name=seller_name,
                generation_device=generation_device,
                buyer=buyer_name,
                reason=("detail API HTTP 狀態碼不是 2xx，" f"status={response.status}"),
                stage="內層 detail API",
                api_url=DETAIL_API_URL,
                payload=payload,
                http_status=response.status,
                response_preview=response.text(),
            )
            return None

        return response.text()

    except Exception as e:
        year_stats.failure_count += 1
        run_stats.total_failure_count += 1
        record_failed(
            year=year,
            page=page_number,
            row_number=row_number_in_page,
            seller_name=seller_name,
            generation_device=generation_device,
            buyer=buyer_name,
            reason=f"呼叫 detail API 發生例外：{type(e).__name__}，{e}",
            stage="內層 detail API 請求",
            api_url=DETAIL_API_URL,
            payload=payload,
            exception=e,
        )
        return None


# =========================================================
# 16. 外層 item + detail HTML 組成固定 8 欄
# =========================================================


def build_output_rows_from_item_and_detail(
    item: Dict[str, Any],
    detail_html: str,
    year: str,
    page_number: int,
    row_number_in_page: int,
    year_stats: YearStats,
    run_stats: RunStats,
) -> List[Dict[str, str]]:
    """
    合併 data API item 與 detail HTML。

    情況：
    - 沒有成交記錄區塊：真正 HTML 結構異常，寫 failed。
    - <ol></ol> 空白：正常無成交記錄，不寫 raw、不寫 failed。
    - 有內容但無法解析：真正資料格式異常，寫 failed。
    - 有多筆成交記錄：每筆成交日期各輸出一列 raw。
    """
    seller_name, generation_device, buyer_name = get_item_basic_info(item)

    if not has_trade_record_section(detail_html):
        year_stats.failure_count += 1
        run_stats.total_failure_count += 1
        record_failed(
            year=year,
            page=page_number,
            row_number=row_number_in_page,
            seller_name=seller_name,
            generation_device=generation_device,
            buyer=buyer_name,
            reason="detail HTML 找不到成交記錄區塊",
            stage="解析 detail HTML",
            api_url=DETAIL_API_URL,
            payload=build_detail_payload(item, year),
            response_preview=detail_html,
        )
        return []

    if is_trade_record_ol_empty(detail_html):
        year_stats.empty_trade_record_count += 1
        run_stats.total_empty_trade_record_count += 1
        return []

    trade_records = extract_trade_records(detail_html)
    if not trade_records:
        year_stats.failure_count += 1
        run_stats.total_failure_count += 1
        record_failed(
            year=year,
            page=page_number,
            row_number=row_number_in_page,
            seller_name=seller_name,
            generation_device=generation_device,
            buyer=buyer_name,
            reason=(
                "detail HTML 有成交記錄內容，但無法解析成"
                "『於 YYYY-MM-DD 移轉 xxx MWh』格式"
            ),
            stage="解析 detail HTML 成交記錄",
            api_url=DETAIL_API_URL,
            payload=build_detail_payload(item, year),
            response_preview=detail_html,
        )
        return []

    # detail 內的欄位優先；抓不到才用外層 data API 備援。
    seller_name = extract_detail_field(detail_html, "出售單位") or seller_name
    generation_device = (
        extract_detail_field(detail_html, "發電設備") or generation_device
    )
    buyer_name = extract_detail_field(detail_html, "購買者") or buyer_name

    energy_type = str(item.get("energy", "")).strip()
    supply_type = str(item.get("parallel_type", "")).strip()
    total_transfer_mwh = clean_number(item.get("power", ""))

    output_rows: List[Dict[str, str]] = []
    for trade_date, trade_mwh in trade_records:
        output_rows.append(
            {
                "__year": str(year),
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

    return output_rows


# =========================================================
# 17. 保存入口
# =========================================================


def save_everything(current_year: Optional[str], upload: bool = True) -> None:
    """
    Cloud Run 01 統一保存流程：
    1. 寫本次年度 raw。
    2. 用各年份最新年度 raw 重建 all_year。
    3. 覆蓋寫入本次 failed.csv。
    4. status 已在 record_no_data 當下 append；這裡只確保存在時可一併上傳。
    5. upload=True 時，把 01 管理的檔案上傳 GCS。
    """
    if current_year:
        save_year_raw_csv(current_year)

    rebuild_all_year_csv()
    save_failed_csv(force_create_empty=True)

    if upload:
        upload_output_files_to_gcs()


# =========================================================
# 18. 單一年份爬取流程
# =========================================================


def crawl_one_year(
    context: Any,
    page: Any,
    csrf_token: str,
    year: str,
    run_stats: RunStats,
) -> None:
    """抓取一個年份的所有頁與所有 detail。"""
    year_stats = YearStats(year=year)

    print("\n" + "=" * 80)
    print(f"開始抓年份：{year}")
    print("=" * 80)

    # 先透過畫面 year-power 判斷明確無資料；失敗時改由 API 決定。
    year_power = read_year_power(page, year)
    if year_power == 0:
        record_no_data(
            year=year,
            page=1,
            row_number=0,
            reason="年度總移轉量 year-power 為 0",
        )
        save_everything(current_year=year, upload=True)
        run_stats.years_checked += 1
        return

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
            # 若第 1 頁就失敗，尚不知道總頁數，不能安全推測後續頁面。
            if known_total_pages is None:
                print(
                    f"年份 {year} 第 {page_number} 頁 data API 失敗，"
                    "尚未知總頁數，停止本年份，交由 02 retry"
                )
                break

            # 已知頁數時，記錄本頁失敗後仍可繼續後面頁數；02 會補本頁。
            print(
                f"年份 {year} 第 {page_number} 頁 data API 失敗，"
                "略過此頁並繼續後面頁數，交由 02 retry"
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

        # data API 正常回應後，才能安全計算總頁數。
        if records_filtered > 0:
            known_total_pages = (records_filtered + PAGE_LENGTH - 1) // PAGE_LENGTH

        if records_total == 0 or records_filtered == 0 or not items:
            if page_number == 1 and year_stats.success_rows == 0:
                record_no_data(
                    year=year,
                    page=1,
                    row_number=0,
                    reason="data API 顯示該年份目前沒有資料",
                )
            else:
                print(f"年份 {year} 第 {page_number} 頁沒有更多資料")
            break

        year_stats.outer_rows += len(items)
        run_stats.total_outer_rows += len(items)

        print("recordsTotal：", records_total)
        print("recordsFiltered：", records_filtered)
        print("本頁外層列表筆數：", len(items))
        print("計算總頁數：", known_total_pages)

        for row_number_in_page, item in enumerate(items, start=1):
            year_stats.detail_checked += 1
            run_stats.total_detail_checked += 1

            detail_html = fetch_detail_api(
                context=context,
                csrf_token=csrf_token,
                item=item,
                year=year,
                page_number=page_number,
                row_number_in_page=row_number_in_page,
                year_stats=year_stats,
                run_stats=run_stats,
            )

            if detail_html is not None:
                output_rows = build_output_rows_from_item_and_detail(
                    item=item,
                    detail_html=detail_html,
                    year=year,
                    page_number=page_number,
                    row_number_in_page=row_number_in_page,
                    year_stats=year_stats,
                    run_stats=run_stats,
                )

                for output_row in output_rows:
                    add_raw_row(output_row, year_stats, run_stats)

            # 每筆 detail API 處理完後，等一下再打下一筆，避免請求太密集。
            if DETAIL_API_SLEEP_SECONDS > 0 and row_number_in_page < len(items):
                time.sleep(DETAIL_API_SLEEP_SECONDS)

        # 每 N 頁持久化到 GCS，避免 Cloud Run 中斷時損失過多進度。
        if SAVE_EVERY_PAGES > 0 and page_number % SAVE_EVERY_PAGES == 0:
            print(f"\n年份 {year} 已完成第 {page_number} 頁，進行批次存檔與上傳")
            save_everything(current_year=year, upload=True)

        # 已到 API 算出的最後一頁。
        if known_total_pages is not None and page_number >= known_total_pages:
            print(
                f"年份 {year} 已抓到最後一頁："
                f"第 {page_number} 頁 / 共 {known_total_pages} 頁"
            )
            break

        page_number += 1

        # 一整頁 detail 都處理完後，再等候下一頁 data API。
        if DATA_API_SLEEP_SECONDS > 0:
            time.sleep(DATA_API_SLEEP_SECONDS)

    # year-power 不是 0，API 也沒有失敗，但最後沒有任何成交資料。
    # 這種情況記到 status，作為歷史觀察紀錄。
    if year_stats.success_rows == 0 and year_stats.failure_count == 0:
        record_no_data(
            year=year,
            page=1,
            row_number=0,
            reason="本年份沒有任何可輸出的成交記錄",
        )

    print("\n" + "=" * 80)
    print(f"年份 {year} 抓取完成")
    print("成功取得 data API 頁數：", year_stats.pages_checked)
    print("外層列表筆數：", year_stats.outer_rows)
    print("detail 檢查筆數：", year_stats.detail_checked)
    print("空成交記錄筆數：", year_stats.empty_trade_record_count)
    print("成功輸出成交資料列數：", year_stats.success_rows)
    print("真正失敗筆數：", year_stats.failure_count)
    print("=" * 80)

    # 年度結束無論如何都再保存一次。
    save_everything(current_year=year, upload=True)
    run_stats.years_checked += 1


# =========================================================
# 19. main
# =========================================================


def main() -> int:
    global storage_client

    run_stats = RunStats()
    current_year: Optional[str] = None
    browser: Optional[Any] = None
    context: Optional[Any] = None

    print("\n========== 01 Cloud Run Playwright/API raw 爬蟲啟動 ==========")
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
    print("YEAR_CHANGE_WAIT_SECONDS：", YEAR_CHANGE_WAIT_SECONDS)
    print("DATA_API_SLEEP_SECONDS：", DATA_API_SLEEP_SECONDS)
    print("DETAIL_API_SLEEP_SECONDS：", DETAIL_API_SLEEP_SECONDS)
    print("API_TIMEOUT_MS：", API_TIMEOUT_MS)
    print("HEADLESS：", HEADLESS)
    print(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH：",
        PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH or "(使用 Playwright 內建 Chromium)",
    )

    try:
        # 1. 建立 GCS client。
        storage_client = create_storage_client()

        # 2. 部分年度更新時，從日期最新 raw 快照下載未更新年度；status 從 control/ 下載。
        download_existing_output_files_from_gcs()

        # 3. failed.csv 不保留歷史；本次 01 一開始就重設 control/failed.csv。
        initialize_failed_csv_for_new_run()

        # 4. 開首頁，取得 Cookie / CSRF，再使用 API 取得資料。
        with sync_playwright() as playwright:
            browser_launch_options: Dict[str, Any] = {"headless": HEADLESS}

            # 舊 Selenium Cloud Run Dockerfile 通常已安裝 /usr/bin/chromium。
            # 路徑存在就沿用；否則不指定 executable_path，讓 Playwright 用自己的瀏覽器。
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
                    "沒有任何年份可抓。請檢查 YEARS_TO_CRAWL；" "空字串不是預設 2026。"
                )

            print("本次要抓年份：", years)

            for year in years:
                current_year = year
                crawl_one_year(
                    context=context,
                    page=page,
                    csrf_token=csrf_token,
                    year=year,
                    run_stats=run_stats,
                )

        print("\n" + "#" * 80)
        print("01 全部完成")
        print("完成檢查年份數：", run_stats.years_checked)
        print("外層列表總筆數：", run_stats.total_outer_rows)
        print("detail 總檢查筆數：", run_stats.total_detail_checked)
        print("空成交記錄總筆數：", run_stats.total_empty_trade_record_count)
        print("成功輸出成交資料總列數：", run_stats.total_success_rows)
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
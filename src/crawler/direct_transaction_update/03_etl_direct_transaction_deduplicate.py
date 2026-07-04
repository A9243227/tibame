"""
03_etl_direct_transaction_deduplicate.py

T-REC 直轉供：讀取本次 raw 快照的 all_year，依固定 8 欄去重。

輸入：
    direct_transaction/raw/dt=PIPELINE_DT/
    trec_direct_transaction_raw_all_year_YYYYMMDD.csv

輸出：
    1. old_raw_data/playwright_trec/dt=PIPELINE_DT/
       trec_direct_transaction_raw.csv
       - 本次去重後的歷史版本。

    2. new_raw_data/playwright_trec/
       trec_direct_transaction_raw.csv
       - 最新去重後資料，BigQuery 固定讀取此檔。

    3. direct_transaction/audit/dt=PIPELINE_DT/
       trec_direct_transaction_dedup_report_YYYYMMDD.csv
       - 原始筆數、去重後筆數、重複群組與重複明細。

重要規則：
1. 固定只以 8 欄完全相同判斷重複，保留第一筆。
2. all_year 不存在、0 bytes 空檔、或只有表頭時：
   - 仍產生空的「本次歷史去重檔」與 0 筆 dedup report。
   - 03 正常結束（return 0）。
   - 不覆蓋 new_raw_data 的最新 BigQuery 正式檔。
3. CSV 欄位缺失、CSV 格式損壞、GCS 操作失敗、Python 例外等真正錯誤：
   - 不覆蓋 new_raw_data 的最新 BigQuery 正式檔。
   - 盡量寫入 0 筆 dedup report。
   - return 1。
"""

from __future__ import annotations

import csv
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
from google.cloud import storage

# =========================================================
# 1. Cloud Run / GCS / pipeline date
# =========================================================

LOCAL_WORKDIR = Path(os.getenv("LOCAL_WORKDIR", "/tmp")).resolve()
LOCAL_WORKDIR.mkdir(parents=True, exist_ok=True)

GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()
GCS_PREFIX = os.getenv("GCS_PREFIX", "direct_transaction").strip("/")

# 01 / 02 使用的專案根目錄仍是 direct_transaction；
# 03 的去重結果則依使用者確認，分別發布到 bucket 根目錄的 old_raw_data 與 new_raw_data。
HISTORICAL_DEDUP_PREFIX = os.getenv(
    "HISTORICAL_DEDUP_PREFIX",
    "old_raw_data/playwright_trec",
).strip("/")
LATEST_DEDUP_PREFIX = os.getenv(
    "LATEST_DEDUP_PREFIX",
    "new_raw_data/playwright_trec",
).strip("/")

RAW_PREFIX = "trec_direct_transaction_raw"
RAW_ROOT = "raw"
AUDIT_ROOT = "audit"

storage_client: Optional[storage.Client] = None


def get_taipei_now() -> datetime:
    """取得專案使用的台灣時間；時區設定異常時退回系統本地時間。"""
    timezone_name = (
        os.getenv("PIPELINE_TIMEZONE", "Asia/Taipei").strip() or "Asia/Taipei"
    )
    try:
        return datetime.now(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError:
        print(f"警告：找不到時區 {timezone_name}，改用系統本地時間")
        return datetime.now()


def get_pipeline_dt() -> str:
    """取得同一次 01 → 02 → 03 共用的快照日期。"""
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

INPUT_ALL_YEAR_NAME = f"{RAW_PREFIX}_all_year_{PIPELINE_DATE_COMPACT}.csv"
OUTPUT_NAME = f"{RAW_PREFIX}.csv"
DEDUP_REPORT_NAME = f"trec_direct_transaction_dedup_report_{PIPELINE_DATE_COMPACT}.csv"

INPUT_ALL_YEAR_FILE = LOCAL_WORKDIR / INPUT_ALL_YEAR_NAME
OUTPUT_FILE = LOCAL_WORKDIR / OUTPUT_NAME
DEDUP_REPORT_FILE = LOCAL_WORKDIR / DEDUP_REPORT_NAME


# =========================================================
# 2. CSV schema
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

# 保留舊版 dedup report 欄位，不額外新增欄位。
REPORT_FIELDNAMES: List[str] = [
    "執行批次ID",
    "執行時間",
    "原始資料筆數",
    "去重後資料筆數",
    "實際刪除重複列數",
    "重複群組數",
    "出現次數",
    "刪除重複筆數",
    *FIELDNAMES,
]


# =========================================================
# 3. GCS helpers
# =========================================================


def gcs_join(*parts: str) -> str:
    """安全組出 GCS object name，不產生重複斜線。"""
    cleaned = [str(part).strip("/") for part in parts if str(part).strip("/")]
    return "/".join(cleaned)


def raw_input_blob_name() -> str:
    return gcs_join(GCS_PREFIX, RAW_ROOT, f"dt={PIPELINE_DT}", INPUT_ALL_YEAR_NAME)


def historical_dedup_blob_name() -> str:
    """本次去重後歷史版本：old_raw_data/playwright_trec/dt=.../固定檔名。"""
    return gcs_join(HISTORICAL_DEDUP_PREFIX, f"dt={PIPELINE_DT}", OUTPUT_NAME)


def audit_blob_name() -> str:
    return gcs_join(GCS_PREFIX, AUDIT_ROOT, f"dt={PIPELINE_DT}", DEDUP_REPORT_NAME)


def latest_dedup_blob_name() -> str:
    """BigQuery 固定讀取的最新去重資料。"""
    return gcs_join(LATEST_DEDUP_PREFIX, OUTPUT_NAME)


def create_storage_client() -> storage.Client:
    """建立 GCS client；Cloud Run service account 必須具備 bucket 讀寫權限。"""
    if not GCS_BUCKET:
        raise ValueError("沒有設定 GCS_BUCKET，請在 Cloud Run Job 設定 bucket 名稱")
    return storage.Client()


def upload_file_to_gcs(path: Path, blob_name: str) -> None:
    """將本機檔案上傳到指定的 GCS object。"""
    if not path.exists():
        raise FileNotFoundError(f"準備上傳的檔案不存在：{path}")
    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法上傳 GCS")

    bucket = storage_client.bucket(GCS_BUCKET)
    bucket.blob(blob_name).upload_from_filename(str(path))
    print(f"已上傳 GCS：{path}")
    print(f"GCS 位置：gs://{GCS_BUCKET}/{blob_name}")


def download_file_from_gcs_if_missing(path: Path, blob_name: str) -> bool:
    """
    同一個 Job 的 /tmp 已有檔案時不覆蓋；單獨執行 03 時才由 GCS 下載。

    回傳：
    - True：本機原本已有檔案，或下載成功。
    - False：GCS 指定 object 不存在。
    """
    if path.exists():
        print(f"/tmp 已有檔案，直接使用：{path}")
        return True

    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法下載 GCS")

    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(blob_name)
    if not blob.exists(client=storage_client):
        print(f"GCS 找不到檔案：gs://{GCS_BUCKET}/{blob_name}")
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(path))
    print(f"已下載：gs://{GCS_BUCKET}/{blob_name} -> {path}")
    return True


def download_required_input_files() -> bool:
    """
    準備本次 03 的輸入與同日 audit report。

    all_year 不存在不是 Python 例外：主程式會建立空的本次歷史去重檔
    與 0 筆 report，並正常 return 0。
    """
    print("\n========== 03 準備輸入檔 ==========")
    print("PIPELINE_DT：", PIPELINE_DT)
    print("raw 輸入：", raw_input_blob_name())

    input_available = download_file_from_gcs_if_missing(
        INPUT_ALL_YEAR_FILE,
        raw_input_blob_name(),
    )

    # 同一天再次執行 03 時，延續該 dt 的 audit report，保留 append 行為。
    download_file_from_gcs_if_missing(DEDUP_REPORT_FILE, audit_blob_name())

    return input_available


# =========================================================
# 4. Local CSV helpers
# =========================================================


def write_empty_output() -> None:
    """產生只有固定 8 欄表頭的空去重 CSV。"""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = OUTPUT_FILE.with_suffix(OUTPUT_FILE.suffix + ".tmp")

    with temp_file.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()

    os.replace(temp_file, OUTPUT_FILE)
    print("已輸出空的本次去重 CSV：", OUTPUT_FILE)


def write_final_output(df_clean: pd.DataFrame) -> None:
    """安全寫入去重後、將發布到 old/new raw data 的 CSV。"""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = OUTPUT_FILE.with_suffix(OUTPUT_FILE.suffix + ".tmp")

    df_clean.to_csv(
        temp_file,
        index=False,
        encoding="utf-8-sig",
        columns=FIELDNAMES,
    )

    os.replace(temp_file, OUTPUT_FILE)
    print("本次去重 CSV 已輸出：", OUTPUT_FILE)


def check_columns(df: pd.DataFrame) -> None:
    """確認 all_year CSV 有固定 8 欄。"""
    missing = [column for column in FIELDNAMES if column not in df.columns]
    if missing:
        raise ValueError(f"all_year CSV 缺少固定欄位：{missing}")


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """保留舊版清理邏輯：固定 8 欄補空白、轉字串、去前後空白。"""
    result = df.copy()
    for column in FIELDNAMES:
        result[column] = result[column].fillna("").astype(str).str.strip()
    return result


# =========================================================
# 5. Dedup report helpers
# =========================================================


def empty_report_row() -> Dict[str, Any]:
    """建立所有 report 欄位先為空白的一列。"""
    return {column: "" for column in REPORT_FIELDNAMES}


def validate_existing_report_header() -> None:
    """確認同日既有 audit report 的表頭仍是舊版規格。"""
    if not DEDUP_REPORT_FILE.exists() or DEDUP_REPORT_FILE.stat().st_size == 0:
        return

    with DEDUP_REPORT_FILE.open("r", newline="", encoding="utf-8-sig") as f:
        existing_header = next(csv.reader(f), [])

    if existing_header != REPORT_FIELDNAMES:
        raise ValueError(
            "同一 PIPELINE_DT 的既有 dedup report 表頭和舊版規格不一致。"
            "請先備份或移除該 audit/dt=.../ 報表後再執行。"
        )


def append_report_rows(rows: List[Dict[str, Any]]) -> None:
    """沿用舊版：新檔建立表頭，既有檔案 append 本次統計與重複明細。"""
    if not rows:
        return

    DEDUP_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    validate_existing_report_header()

    has_content = DEDUP_REPORT_FILE.exists() and DEDUP_REPORT_FILE.stat().st_size > 0
    encoding = "utf-8" if has_content else "utf-8-sig"

    with DEDUP_REPORT_FILE.open("a", newline="", encoding=encoding) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=REPORT_FIELDNAMES,
            extrasaction="ignore",
        )
        if not has_content:
            writer.writeheader()
        writer.writerows(rows)

    print("dedup report 已追加：", DEDUP_REPORT_FILE)
    print("本次新增 report 列數：", len(rows))


def build_report_rows(
    *,
    batch_id: str,
    run_time: str,
    before_count: int,
    after_count: int,
    duplicate_count: int,
    duplicate_group_count: int,
    duplicate_groups: pd.DataFrame,
) -> List[Dict[str, Any]]:
    """保留舊版 report 寫法：第一列統計，後續列為重複群組明細。"""
    report_rows: List[Dict[str, Any]] = []

    summary_row = empty_report_row()
    summary_row.update(
        {
            "執行批次ID": batch_id,
            "執行時間": run_time,
            "原始資料筆數": before_count,
            "去重後資料筆數": after_count,
            "實際刪除重複列數": duplicate_count,
            "重複群組數": duplicate_group_count,
        }
    )
    report_rows.append(summary_row)

    if not duplicate_groups.empty:
        for _, group_row in duplicate_groups.iterrows():
            detail_row = empty_report_row()
            detail_row.update(
                {
                    "執行批次ID": batch_id,
                    "執行時間": run_time,
                    "出現次數": int(group_row["出現次數"]),
                    "刪除重複筆數": int(group_row["刪除重複筆數"]),
                }
            )
            for column in FIELDNAMES:
                detail_row[column] = group_row[column]
            report_rows.append(detail_row)

    return report_rows


def append_empty_or_failed_run_report(batch_id: str, run_time: str) -> None:
    """沿用舊版：無輸入、空輸入或失敗時，仍追加一列 0 筆統計。"""
    empty_groups = pd.DataFrame(columns=[*FIELDNAMES, "出現次數", "刪除重複筆數"])
    append_report_rows(
        build_report_rows(
            batch_id=batch_id,
            run_time=run_time,
            before_count=0,
            after_count=0,
            duplicate_count=0,
            duplicate_group_count=0,
            duplicate_groups=empty_groups,
        )
    )


# =========================================================
# 6. Publish helpers
# =========================================================


def publish_historical_dedup_and_audit() -> None:
    """上傳本次去重後歷史版本與 audit report。"""
    upload_file_to_gcs(OUTPUT_FILE, historical_dedup_blob_name())
    upload_file_to_gcs(DEDUP_REPORT_FILE, audit_blob_name())


def publish_latest_dedup() -> None:
    """覆蓋 BigQuery 固定讀取的最新去重資料；僅有有效 all_year 才呼叫。"""
    upload_file_to_gcs(OUTPUT_FILE, latest_dedup_blob_name())


def finish_empty_input_normally(reason: str, batch_id: str, run_time: str) -> int:
    """
    空資料情況的正常結束入口。

    保留舊版：建立空 output、寫 0 筆 report、return 0。
    重要保護：不覆蓋 new_raw_data 的最新 BigQuery 正式檔。
    """
    print(f"\n{reason}")
    write_empty_output()
    append_empty_or_failed_run_report(batch_id, run_time)
    publish_historical_dedup_and_audit()

    print("未更新 new_raw_data：本次 all_year 沒有可發布的交易資料")
    print("BigQuery 將繼續使用 new_raw_data 中前一次成功發布的正式 CSV")
    return 0


# =========================================================
# 7. Main
# =========================================================


def main() -> int:
    global storage_client

    # 保留舊版：同一次 ETL 的統計列、重複明細列共用一組 batch ID。
    now = get_taipei_now()
    batch_id = now.strftime("%Y%m%d_%H%M%S_%f")
    run_time = now.strftime("%Y-%m-%d %H:%M:%S")

    print("\n========== 03 Cloud Run ETL 去重開始 ==========")
    print("執行批次 ID：", batch_id)
    print("PIPELINE_DT：", PIPELINE_DT)
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR)
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)
    print("HISTORICAL_DEDUP_PREFIX：", HISTORICAL_DEDUP_PREFIX)
    print("LATEST_DEDUP_PREFIX：", LATEST_DEDUP_PREFIX)
    print("輸入 all_year：", INPUT_ALL_YEAR_FILE)
    print("去重後輸出：", OUTPUT_FILE)
    print("audit report：", DEDUP_REPORT_FILE)

    try:
        storage_client = create_storage_client()
        input_available = download_required_input_files()

        # -------------------------------------------------
        # A. 空資料規則：正常建立空的歷史去重檔 / report / return 0。
        #    但絕不覆蓋 new_raw_data 的最新 BigQuery 固定檔。
        # -------------------------------------------------
        if not input_available or not INPUT_ALL_YEAR_FILE.exists():
            return finish_empty_input_normally(
                "找不到 all_year CSV，輸出空的歷史去重檔與 0 筆 report",
                batch_id,
                run_time,
            )

        if INPUT_ALL_YEAR_FILE.stat().st_size == 0:
            return finish_empty_input_normally(
                "all_year CSV 是 0 bytes 空檔，輸出空的歷史去重檔與 0 筆 report",
                batch_id,
                run_time,
            )

        try:
            df = pd.read_csv(INPUT_ALL_YEAR_FILE, encoding="utf-8-sig")
        except pd.errors.EmptyDataError:
            # 全部空白行也視為舊版的空輸入，不是 pipeline error。
            return finish_empty_input_normally(
                "all_year CSV 沒有可讀取的內容，輸出空的歷史去重檔與 0 筆 report",
                batch_id,
                run_time,
            )

        # 有 CSV 表頭但沒有資料列：先驗證固定 8 欄，再正常輸出空檔。
        check_columns(df)
        df = df[FIELDNAMES]
        df = clean_dataframe(df)

        if df.empty:
            return finish_empty_input_normally(
                "all_year CSV 只有表頭、沒有資料列，輸出空的歷史去重檔與 0 筆 report",
                batch_id,
                run_time,
            )

        # -------------------------------------------------
        # B. 有資料時：保留舊版固定 8 欄去重、重複群組與 keep='first' 規則。
        # -------------------------------------------------
        before_count = len(df)

        duplicate_groups = (
            df.groupby(FIELDNAMES, dropna=False).size().reset_index(name="出現次數")
        )
        duplicate_groups = duplicate_groups[duplicate_groups["出現次數"] > 1].copy()
        duplicate_groups["刪除重複筆數"] = duplicate_groups["出現次數"] - 1

        if not duplicate_groups.empty:
            duplicate_groups = duplicate_groups.sort_values(
                by=["出現次數", *FIELDNAMES],
                ascending=[False] + [True] * len(FIELDNAMES),
                kind="stable",
            ).reset_index(drop=True)

        duplicate_group_count = len(duplicate_groups)

        df_clean = df.drop_duplicates(
            subset=FIELDNAMES,
            keep="first",
        ).reset_index(drop=True)

        after_count = len(df_clean)
        duplicate_count = before_count - after_count

        write_final_output(df_clean)
        append_report_rows(
            build_report_rows(
                batch_id=batch_id,
                run_time=run_time,
                before_count=before_count,
                after_count=after_count,
                duplicate_count=duplicate_count,
                duplicate_group_count=duplicate_group_count,
                duplicate_groups=duplicate_groups,
            )
        )

        # 先保留本次歷史去重版本與 audit，再發布最新 BigQuery 固定讀取檔。
        publish_historical_dedup_and_audit()
        publish_latest_dedup()

        print("\n========== 03 Cloud Run ETL 去重完成 ==========")
        print("原始 raw 資料筆數：", before_count)
        print("重複群組數：", duplicate_group_count)
        print("實際刪除重複資料筆數：", duplicate_count)
        print("去重後資料筆數：", after_count)
        print("歷史去重版本：", f"gs://{GCS_BUCKET}/{historical_dedup_blob_name()}")
        print("audit：", f"gs://{GCS_BUCKET}/{audit_blob_name()}")
        print("BigQuery 固定來源：", f"gs://{GCS_BUCKET}/{latest_dedup_blob_name()}")
        return 0

    except Exception as exc:
        # 真正錯誤才 return 1；BigQuery 固定檔絕不覆蓋。
        reason = f"{type(exc).__name__}：{exc}"
        print("\n03 Cloud Run ETL 發生錯誤：", reason)
        print(traceback.format_exc())

        # 沿用舊版：盡量留下 0 筆統計 report。失敗原因以 Cloud Run log 為準。
        try:
            append_empty_or_failed_run_report(batch_id, run_time)
            if storage_client is not None:
                upload_file_to_gcs(DEDUP_REPORT_FILE, audit_blob_name())
        except Exception as report_exc:
            print(
                "03 失敗後，dedup report 也無法寫入或上傳：",
                type(report_exc).__name__,
                report_exc,
            )

        print("未更新 new_raw_data：03 發生真正錯誤")
        return 1


if __name__ == "__main__":
    sys.exit(main())

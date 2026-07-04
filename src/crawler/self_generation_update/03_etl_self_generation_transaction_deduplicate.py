"""
03_etl_self_generation_transaction_deduplicate.py

T-REC 自用發電：讀取本次 raw 快照的 all_year，依固定 7 欄去重。

輸入：
    self_generation_transaction/raw/dt=PIPELINE_DT/
    trec_self_generation_transaction_raw_all_year_YYYYMMDD.csv

輸出：
    1. old_raw_data/playwright_trec_self/dt=PIPELINE_DT/
       trec_self_generation_transaction_raw.csv
       - 本次去重後的歷史版本。

    2. new_raw_data/playwright_trec_self/
       trec_self_generation_transaction_raw.csv
       - 最新去重後資料，BigQuery 固定讀取此檔。

    3. self_generation_transaction/audit/dt=PIPELINE_DT/
       trec_self_generation_transaction_dedup_report_YYYYMMDD.csv
       - 原始筆數、去重後筆數、重複群組與重複明細。

重要規則：
1. 固定只以 7 欄完全相同判斷重複，保留第一筆。
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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any, Dict, List, Optional

import pandas as pd
from google.cloud import storage

# =========================================================
# 1. Cloud Run / GCS / PIPELINE_DT
# =========================================================

LOCAL_WORKDIR = Path(os.getenv("LOCAL_WORKDIR", "/tmp")).resolve()
LOCAL_WORKDIR.mkdir(parents=True, exist_ok=True)

GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()
GCS_PREFIX = os.getenv(
    "GCS_PREFIX",
    "self_generation_transaction",
).strip("/")

# 01 / 02 使用的專案根目錄仍是 self_generation_transaction；
# 03 的去重結果依使用者確認，分別發布到 bucket 根目錄的 old_raw_data 與 new_raw_data。
HISTORICAL_DEDUP_PREFIX = os.getenv(
    "HISTORICAL_DEDUP_PREFIX",
    "old_raw_data/playwright_trec_self",
).strip("/")
LATEST_DEDUP_PREFIX = os.getenv(
    "LATEST_DEDUP_PREFIX",
    "new_raw_data/playwright_trec_self",
).strip("/")

RAW_PREFIX = "trec_self_generation_transaction_raw"
RAW_ROOT = "raw"
AUDIT_ROOT = "audit"

storage_client: Optional[storage.Client] = None


def get_taipei_now() -> datetime:
    """取得專案使用的台灣時間；時區名稱無效時退回系統時間。"""
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
RUN_NOW = get_taipei_now()
RUN_BATCH_ID = RUN_NOW.strftime("%Y%m%d_%H%M%S_%f")
RUN_TIME = RUN_NOW.strftime("%Y-%m-%d %H:%M:%S")


# =========================================================
# 2. 檔案與欄位設定
# =========================================================

INPUT_ALL_YEAR_NAME = f"{RAW_PREFIX}_all_year_{PIPELINE_DATE_COMPACT}.csv"
# 日期已由 GCS 的 dt=YYYY-MM-DD 資料夾區分；去重資料使用固定檔名。
OUTPUT_NAME = f"{RAW_PREFIX}.csv"
DEDUP_REPORT_NAME = f"trec_self_generation_transaction_dedup_report_{PIPELINE_DATE_COMPACT}.csv"

INPUT_ALL_YEAR_FILE = LOCAL_WORKDIR / INPUT_ALL_YEAR_NAME
OUTPUT_FILE = LOCAL_WORKDIR / OUTPUT_NAME
DEDUP_REPORT_FILE = LOCAL_WORKDIR / DEDUP_REPORT_NAME

# 使用者已確認的固定 7 欄。
FIELDNAMES: List[str] = [
    "出售單位",
    "發電設備",
    "購買者",
    "能源類型",
    "移轉量(MWh)",
    "憑證發放年份",
    "移轉日期",
]

# 舊版 CSV / 報表使用「移轉量」。保留相容轉換，避免舊資料的數值遺失。
LEGACY_FIELDNAMES: List[str] = [
    "出售單位",
    "發電設備",
    "購買者",
    "能源類型",
    "移轉量",
    "憑證發放年份",
    "移轉日期",
]

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

LEGACY_REPORT_FIELDNAMES: List[str] = [
    "執行批次ID",
    "執行時間",
    "原始資料筆數",
    "去重後資料筆數",
    "實際刪除重複列數",
    "重複群組數",
    "出現次數",
    "刪除重複筆數",
    *LEGACY_FIELDNAMES,
]


# =========================================================
# 3. GCS 工具
# =========================================================


def gcs_join(*parts: str) -> str:
    cleaned = [str(part).strip("/") for part in parts if str(part).strip("/")]
    return "/".join(cleaned)


def raw_input_blob_name() -> str:
    return gcs_join(GCS_PREFIX, RAW_ROOT, f"dt={PIPELINE_DT}", INPUT_ALL_YEAR_NAME)


def historical_dedup_blob_name() -> str:
    """本次去重後歷史版本：old_raw_data/playwright_trec_self/dt=.../固定檔名。"""
    return gcs_join(HISTORICAL_DEDUP_PREFIX, f"dt={PIPELINE_DT}", OUTPUT_NAME)


def audit_blob_name() -> str:
    return gcs_join(GCS_PREFIX, AUDIT_ROOT, f"dt={PIPELINE_DT}", DEDUP_REPORT_NAME)


def latest_dedup_blob_name() -> str:
    """BigQuery 固定讀取的最新去重資料。"""
    return gcs_join(LATEST_DEDUP_PREFIX, OUTPUT_NAME)


def create_storage_client() -> storage.Client:
    if not GCS_BUCKET:
        raise ValueError("沒有設定 GCS_BUCKET，請在 Cloud Run Job 設定 bucket 名稱")
    return storage.Client()


def upload_file_to_gcs(path: Path, blob_name: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"準備上傳的檔案不存在：{path}")
    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法上傳 GCS")

    bucket = storage_client.bucket(GCS_BUCKET)
    bucket.blob(blob_name).upload_from_filename(str(path))
    print(f"已上傳 GCS：{path}")
    print(f"GCS 位置：gs://{GCS_BUCKET}/{blob_name}")


def download_file_from_gcs_if_missing(path: Path, blob_name: str) -> bool:
    """同一 Job /tmp 已有輸入時不覆蓋；單獨跑 03 才從 GCS 下載。"""
    if path.exists():
        print(f"/tmp 已有檔案，直接使用：{path}")
        return True
    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法從 GCS 下載")

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
    """準備本次 raw/dt 輸入及同日 audit report。"""
    print("\n========== 03 準備輸入檔 ==========")
    print("PIPELINE_DT：", PIPELINE_DT)
    print("raw 輸入：", raw_input_blob_name())

    input_available = download_file_from_gcs_if_missing(
        INPUT_ALL_YEAR_FILE,
        raw_input_blob_name(),
    )
    # 同一天再次跑 03 時，延續同日 audit 的 append 行為。
    download_file_from_gcs_if_missing(DEDUP_REPORT_FILE, audit_blob_name())
    return input_available

# =========================================================
# 4. CSV 輸出與資料清理
# =========================================================


def write_empty_output() -> None:
    """沒有資料時仍建立只有表頭的本次去重 CSV，保留本次歷史結果。"""
    temp_file = OUTPUT_FILE.with_suffix(OUTPUT_FILE.suffix + ".tmp")

    with temp_file.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()

    os.replace(temp_file, OUTPUT_FILE)
    print("沒有可處理 raw 資料，已輸出空的本次去重 CSV：", OUTPUT_FILE)


def write_final_output(df_clean: pd.DataFrame) -> None:
    """安全輸出本次去重資料。"""
    temp_file = OUTPUT_FILE.with_suffix(OUTPUT_FILE.suffix + ".tmp")

    df_clean.to_csv(
        temp_file,
        index=False,
        encoding="utf-8-sig",
        columns=FIELDNAMES,
    )

    os.replace(temp_file, OUTPUT_FILE)
    print("本次去重 CSV 已輸出：", OUTPUT_FILE)


def migrate_legacy_amount_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    將舊欄位「移轉量」升級為新欄位「移轉量(MWh)」。

    正常完整流程中，01 已會把舊年度 raw 轉成新欄位。
    這裡再做一次保護，確保單獨執行 03 時也能讀取舊 all_year CSV。
    """
    df = df.copy()

    if "移轉量(MWh)" not in df.columns and "移轉量" in df.columns:
        df = df.rename(columns={"移轉量": "移轉量(MWh)"})
        print("偵測到舊欄位「移轉量」，已升級為「移轉量(MWh)」")
    elif "移轉量(MWh)" in df.columns and "移轉量" in df.columns:
        # 兩欄同時存在時，優先使用新欄位；新欄位空白才以舊欄位補值。
        new_amount = df["移轉量(MWh)"].fillna("").astype(str).str.strip()
        old_amount = df["移轉量"].fillna("").astype(str).str.strip()
        df["移轉量(MWh)"] = new_amount.where(new_amount != "", old_amount)
        df = df.drop(columns=["移轉量"])
        print("偵測到新舊移轉量欄位同時存在，已合併為「移轉量(MWh)」")

    return df


def check_columns(df: pd.DataFrame) -> None:
    """確認 all_year CSV 擁有固定 7 欄。"""
    missing = [column for column in FIELDNAMES if column not in df.columns]
    if missing:
        raise ValueError(f"CSV 缺少欄位：{missing}")


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """清理空值與前後空白，讓去重判斷一致。"""
    df = df.copy()

    for column in FIELDNAMES:
        df[column] = df[column].fillna("").astype(str).str.strip()

    # 數字欄位去掉千分位逗號。01 / 02 已做過，03 再做一次保護。
    df["移轉量(MWh)"] = df["移轉量(MWh)"].str.replace(",", "", regex=False)

    # 公司名稱全形括號轉半形；避免格式不同造成無法去重。
    for column in ["出售單位", "購買者"]:
        df[column] = (
            df[column]
            .str.replace("（", "(", regex=False)
            .str.replace("）", ")", regex=False)
            .str.replace(r"\s*\(\s*", "(", regex=True)
            .str.replace(r"\s*\)\s*", ")", regex=True)
        )

    return df


# =========================================================
# 5. 去重歷史報表工具
# =========================================================


def empty_report_row() -> Dict[str, Any]:
    return {column: "" for column in REPORT_FIELDNAMES}


def validate_existing_report_header() -> None:
    """
    確認既有 dedup report 的表頭。

    舊版自用發電設備報表的欄位叫「移轉量」；本版改為「移轉量(MWh)」。
    遇到舊版時會自動升級表頭與原本數值。若是不同專案的表頭，才明確阻擋。
    """
    if not DEDUP_REPORT_FILE.exists() or DEDUP_REPORT_FILE.stat().st_size == 0:
        return

    with DEDUP_REPORT_FILE.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        existing_header = reader.fieldnames or []
        existing_rows = list(reader)

    if existing_header == REPORT_FIELDNAMES:
        return

    if existing_header == LEGACY_REPORT_FIELDNAMES:
        migrated_rows: List[Dict[str, Any]] = []

        for old_row in existing_rows:
            new_row = {field: old_row.get(field, "") for field in REPORT_FIELDNAMES}
            new_row["移轉量(MWh)"] = old_row.get("移轉量", "")
            migrated_rows.append(new_row)

        temp_file = DEDUP_REPORT_FILE.with_suffix(DEDUP_REPORT_FILE.suffix + ".tmp")
        with temp_file.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=REPORT_FIELDNAMES,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(migrated_rows)

        os.replace(temp_file, DEDUP_REPORT_FILE)
        print("既有 dedup report 已從「移轉量」升級為「移轉量(MWh)」")
        return

    raise ValueError(
        "既有 dedup report 的表頭和目前自用發電設備版本不一致。"
        "請確認 GCS_PREFIX 是否使用了錯誤資料夾；或先備份、刪除舊報表後再執行。"
    )


def append_report_rows(rows: List[Dict[str, Any]]) -> None:
    """把本次統計與重複明細 append 到歷史報表。"""
    if not rows:
        return

    validate_existing_report_header()

    file_has_content = (
        DEDUP_REPORT_FILE.exists() and DEDUP_REPORT_FILE.stat().st_size > 0
    )
    encoding = "utf-8" if file_has_content else "utf-8-sig"

    with DEDUP_REPORT_FILE.open("a", newline="", encoding=encoding) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=REPORT_FIELDNAMES,
            extrasaction="ignore",
        )
        if not file_has_content:
            writer.writeheader()
        writer.writerows(rows)

    print("ETL 去重歷史報表已追加：", DEDUP_REPORT_FILE)
    print("本次新增報表列數：", len(rows))


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
    """建立一列統計 + 多列重複明細。"""
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
    """all_year 無資料或 03 出錯時，仍留下一列 0 筆統計。"""
    empty_groups = pd.DataFrame(columns=[*FIELDNAMES, "出現次數", "刪除重複筆數"])

    rows = build_report_rows(
        batch_id=batch_id,
        run_time=run_time,
        before_count=0,
        after_count=0,
        duplicate_count=0,
        duplicate_group_count=0,
        duplicate_groups=empty_groups,
    )
    append_report_rows(rows)


# =========================================================
# 6. 發布與 main
# =========================================================


def publish_historical_dedup_and_audit() -> None:
    """上傳本次歷史去重 CSV 與 audit report。"""
    upload_file_to_gcs(OUTPUT_FILE, historical_dedup_blob_name())
    upload_file_to_gcs(DEDUP_REPORT_FILE, audit_blob_name())


def publish_latest_dedup() -> None:
    """覆蓋 BigQuery 固定讀取的最新去重資料；僅限本次 all_year 至少一筆資料。"""
    upload_file_to_gcs(OUTPUT_FILE, latest_dedup_blob_name())


def finish_empty_input_normally(reason: str, batch_id: str, run_time: str) -> int:
    """
    all_year 不存在、0 bytes 或只有表頭時的正常結束。

    保留空的本次歷史去重檔和 0 筆 audit，但不覆蓋上一份 BigQuery 正式檔，
    避免網站暫時無資料時把下游 BigQuery / Tableau 清空。
    """
    print(f"\n{reason}")
    write_empty_output()
    append_empty_or_failed_run_report(batch_id, run_time)
    publish_historical_dedup_and_audit()
    print("未更新 new_raw_data：本次 all_year 沒有可發布的交易資料")
    return 0


def main() -> int:
    """03：讀本次 raw/dt all_year，固定 7 欄去重，發布 old_raw_data / new_raw_data / audit。"""
    global storage_client

    now = get_taipei_now()
    batch_id = now.strftime("%Y%m%d_%H%M%S_%f")
    run_time = now.strftime("%Y-%m-%d %H:%M:%S")

    print("\n========== 03 自用發電設備成交紀錄 ETL 去重開始 ==========")
    print("執行批次 ID：", batch_id)
    print("PIPELINE_DT：", PIPELINE_DT)
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR)
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)
    print("輸入 all_year：", INPUT_ALL_YEAR_FILE)
    print("本次去重輸出：", OUTPUT_FILE)
    print("audit report：", DEDUP_REPORT_FILE)

    try:
        storage_client = create_storage_client()
        input_available = download_required_input_files()

        if not input_available or not INPUT_ALL_YEAR_FILE.exists():
            return finish_empty_input_normally(
                "找不到 all_year CSV，輸出空的本次歷史去重檔與 0 筆 audit",
                batch_id,
                run_time,
            )

        if INPUT_ALL_YEAR_FILE.stat().st_size == 0:
            return finish_empty_input_normally(
                "all_year CSV 是 0 bytes 空檔，輸出空的本次歷史去重檔與 0 筆 audit",
                batch_id,
                run_time,
            )

        try:
            df = pd.read_csv(INPUT_ALL_YEAR_FILE, encoding="utf-8-sig")
        except pd.errors.EmptyDataError:
            return finish_empty_input_normally(
                "all_year CSV 沒有可讀內容，輸出空的本次歷史去重檔與 0 筆 audit",
                batch_id,
                run_time,
            )

        # 有表頭但沒有列時，仍先檢查 7 欄結構，再正常產生空歷史結果。
        df = migrate_legacy_amount_column(df)
        check_columns(df)
        df = clean_dataframe(df[FIELDNAMES])
        if df.empty:
            return finish_empty_input_normally(
                "all_year CSV 只有表頭、沒有資料列，輸出空的本次歷史去重檔與 0 筆 audit",
                batch_id,
                run_time,
            )

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
        df_clean = df.drop_duplicates(subset=FIELDNAMES, keep="first").reset_index(drop=True)
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

        # 先發布可追溯的當日結果，最後才覆蓋 BigQuery 固定正式來源。
        publish_historical_dedup_and_audit()
        publish_latest_dedup()

        print("\n========== 03 自用發電設備成交紀錄 ETL 去重完成 ==========")
        print("原始 raw 資料筆數：", before_count)
        print("重複群組數：", duplicate_group_count)
        print("實際刪除重複資料筆數：", duplicate_count)
        print("去重後資料筆數：", after_count)
        print("歷史去重資料：", f"gs://{GCS_BUCKET}/{historical_dedup_blob_name()}")
        print("audit：", f"gs://{GCS_BUCKET}/{audit_blob_name()}")
        print("最新 BigQuery 去重資料：", f"gs://{GCS_BUCKET}/{latest_dedup_blob_name()}")
        return 0

    except Exception as exc:
        print("\n03 ETL 發生錯誤：", type(exc).__name__, exc)
        print(traceback.format_exc())

        # 真正錯誤時不覆蓋 new_raw_data；盡量留下 0 筆 audit 供人追查。
        try:
            append_empty_or_failed_run_report(batch_id, run_time)
            if storage_client is not None:
                upload_file_to_gcs(DEDUP_REPORT_FILE, audit_blob_name())
        except Exception as report_error:
            print(
                "03 失敗後，dedup report 也無法寫入或上傳：",
                type(report_error).__name__,
                report_error,
            )

        print("未更新 new_raw_data：03 發生真正錯誤")
        return 1


if __name__ == "__main__":
    sys.exit(main())

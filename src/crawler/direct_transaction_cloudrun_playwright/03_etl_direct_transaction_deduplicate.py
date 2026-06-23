"""
03_etl_direct_transaction_deduplicate_cloudrun.py

T-REC 直轉供憑證成交紀錄：Cloud Run ETL 去重版

本版用途：
1. 執行於 Cloud Run Job；CSV 暫存於 /tmp，正式保存於 GCS。
2. 不使用 Selenium，也不使用 Playwright。
3. 讀取 01 / 02 產生的 trec_direct_transaction_raw_all_year.csv。
4. 只保留固定 8 欄，並以 8 欄完全相同判斷重複。
5. 輸出最終固定檔名：trec_direct_transaction_raw.csv。
6. 每次 ETL 都將「統計 + 重複明細」追加到
   trec_direct_transaction_dedup_report.csv，保留歷史比對資料。
7. Cloud Run 啟動時，若 /tmp 沒有輸入檔，會從 GCS 下載 all_year 與舊 dedup report。
8. Cloud Run 完成後，會把最終 raw 與更新後 dedup report 上傳回 GCS。

Cloud Run 常用環境變數：
    GCS_BUCKET=tibame-bronze
    GCS_PREFIX=raw_data/t_rec/direct_transaction
    LOCAL_WORKDIR=/tmp
"""

from __future__ import annotations

import csv
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from google.cloud import storage

# =========================================================
# 1. Cloud Run / GCS 路徑設定
# =========================================================

# Cloud Run 容器中的 /tmp 只是暫存區。
# Job 結束後不可當永久資料保存位置。
LOCAL_WORKDIR = Path(os.getenv("LOCAL_WORKDIR", "/tmp")).resolve()
LOCAL_WORKDIR.mkdir(parents=True, exist_ok=True)

# GCS 是正式保存位置。
GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()
GCS_PREFIX = os.getenv(
    "GCS_PREFIX",
    "raw_data/t_rec/direct_transaction",
).strip("/")

# main() 成功建立 GCS client 後才會有值。
storage_client: Optional[storage.Client] = None


# =========================================================
# 2. 檔案設定
# =========================================================

RAW_PREFIX = "trec_direct_transaction_raw"

# 01 / 02 合併每個年份最新 raw 後產生的輸入檔。
INPUT_ALL_YEAR_FILE = LOCAL_WORKDIR / f"{RAW_PREFIX}_all_year.csv"

# 最終去重後資料檔。
# 每次 03 都覆蓋，代表目前最新、最乾淨的結果。
OUTPUT_FILE = LOCAL_WORKDIR / f"{RAW_PREFIX}.csv"

# ETL 去重歷史報表。
# 固定檔名，內容採 append，保留每次執行歷史。
DEDUP_REPORT_FILE = LOCAL_WORKDIR / "trec_direct_transaction_dedup_report.csv"


# =========================================================
# 3. 欄位設定
# =========================================================

# 最終交易資料固定 8 欄。
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

# 去重歷史報表欄位。
#
# 同一次 03 執行會有相同的「執行批次ID」：
# 1. 一列 ETL 統計
# 2. 0 到多列重複明細
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
# 4. GCS 讀寫工具
# =========================================================


def build_gcs_blob_name(filename: str) -> str:
    """組出 bucket 中的 object 名稱。"""
    return f"{GCS_PREFIX}/{filename}" if GCS_PREFIX else filename


def create_storage_client() -> storage.Client:
    """建立 GCS client；Cloud Run service account 必須具備 bucket 讀寫權限。"""
    if not GCS_BUCKET:
        raise ValueError(
            "沒有設定 GCS_BUCKET，請在 Cloud Run Job 環境變數設定 bucket 名稱"
        )
    return storage.Client()


def upload_file_to_gcs(path: Path) -> None:
    """上傳 /tmp 中的一個檔案到 GCS。"""
    if not path.exists():
        return

    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法上傳 GCS")

    blob_name = build_gcs_blob_name(path.name)
    bucket = storage_client.bucket(GCS_BUCKET)
    bucket.blob(blob_name).upload_from_filename(str(path))

    print(f"已上傳 GCS：{path}")
    print(f"GCS 位置：gs://{GCS_BUCKET}/{blob_name}")


def download_file_from_gcs_if_missing(path: Path) -> bool:
    """
    只有 /tmp 裡沒有檔案時，才從 GCS 下載。

    好處：
    - 若 01 → 02 → 03 在同一次 Cloud Run Job 串接，
      03 不會覆蓋同一個 /tmp 裡最新的 all_year。
    - 若 03 單獨執行，/tmp 初始是空的，會自動從 GCS 下載輸入檔。
    """
    if path.exists():
        print(f"/tmp 已有檔案，直接使用：{path}")
        return True

    if storage_client is None:
        raise RuntimeError("storage_client 尚未建立，無法從 GCS 下載")

    blob_name = build_gcs_blob_name(path.name)
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(blob_name)

    if not blob.exists(client=storage_client):
        print(f"GCS 找不到檔案，略過下載：gs://{GCS_BUCKET}/{blob_name}")
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(path))

    print(f"已從 GCS 下載：gs://{GCS_BUCKET}/{blob_name}")
    print(f"下載到：{path}")
    return True


def download_required_input_files() -> None:
    """
    03 需要的雲端檔案：
    1. all_year.csv：ETL 的輸入。
    2. dedup_report.csv：保留歷史後再 append。

    final raw 不需要下載，因為本次 03 一定會重新產生並覆蓋。
    """
    print("\n========== 03 從 GCS 準備輸入檔 ==========")
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)

    download_file_from_gcs_if_missing(INPUT_ALL_YEAR_FILE)
    download_file_from_gcs_if_missing(DEDUP_REPORT_FILE)


# =========================================================
# 5. 最終 CSV 輸出工具
# =========================================================


def write_empty_output() -> None:
    """
    沒有 raw 資料時，仍建立只有表頭的最終 CSV。

    這樣後續 MySQL / BigQuery 不會因為找不到檔案而中斷。
    """
    temp_file = OUTPUT_FILE.with_suffix(OUTPUT_FILE.suffix + ".tmp")

    with temp_file.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()

    os.replace(temp_file, OUTPUT_FILE)

    print("沒有可處理 raw 資料，已輸出空的最終 CSV：", OUTPUT_FILE)


def write_final_output(df_clean: pd.DataFrame) -> None:
    """
    將去重後資料安全寫入最終 CSV。

    最終 CSV 每次覆蓋是刻意設計：
    它永遠代表目前最新、最乾淨的去重資料。
    """
    temp_file = OUTPUT_FILE.with_suffix(OUTPUT_FILE.suffix + ".tmp")

    df_clean.to_csv(
        temp_file,
        index=False,
        encoding="utf-8-sig",
        columns=FIELDNAMES,
    )

    os.replace(temp_file, OUTPUT_FILE)
    print("最終去重 CSV 已輸出：", OUTPUT_FILE)


# =========================================================
# 6. DataFrame 檢查與清理工具
# =========================================================


def check_columns(df: pd.DataFrame) -> None:
    """確認 all_year CSV 有固定 8 欄。"""
    missing = [col for col in FIELDNAMES if col not in df.columns]

    if missing:
        raise ValueError(f"CSV 缺少欄位：{missing}")


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    清理空值與前後空白。

    例如：
    ' 公司A ' 與 '公司A' 清理後都會變成 '公司A'，
    才能正確被判斷為相同資料。
    """
    df = df.copy()

    for col in FIELDNAMES:
        df[col] = df[col].fillna("").astype(str).str.strip()

    return df


# =========================================================
# 7. 去重歷史報表工具
# =========================================================


def empty_report_row() -> Dict[str, Any]:
    """建立所有欄位先為空白的一列報表資料。"""
    return {column: "" for column in REPORT_FIELDNAMES}


def validate_existing_report_header() -> None:
    """
    驗證既有歷史報表的表頭是否與目前程式一致。

    若你以前使用過舊版、欄位更多的 dedup report，
    直接 append 會造成欄位錯位，因此要先阻擋並提示你備份舊檔。
    """
    if not DEDUP_REPORT_FILE.exists() or DEDUP_REPORT_FILE.stat().st_size == 0:
        return

    with DEDUP_REPORT_FILE.open("r", newline="", encoding="utf-8-sig") as f:
        existing_header = next(csv.reader(f), [])

    if existing_header != REPORT_FIELDNAMES:
        raise ValueError(
            "既有 trec_direct_transaction_dedup_report.csv 的表頭和目前版本不一致。"
            "請先在 GCS 將舊報表改名備份或刪除，再重新執行 03。"
        )


def append_report_rows(rows: List[Dict[str, Any]]) -> None:
    """
    將本次 ETL 報表追加在歷史報表最後面。

    - 第一次執行：建立報表檔 + 寫表頭。
    - 後續執行：保留舊內容，追加本次資料。
    """
    if not rows:
        return

    validate_existing_report_header()

    file_has_content = (
        DEDUP_REPORT_FILE.exists() and DEDUP_REPORT_FILE.stat().st_size > 0
    )

    # 新檔案用 utf-8-sig，Excel 開啟中文不會亂碼。
    # 既有檔案用 utf-8 追加，避免中間額外插入 BOM。
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
    run_status: str,
    before_count: int,
    after_count: int,
    duplicate_count: int,
    duplicate_group_count: int,
    duplicate_groups: pd.DataFrame,
) -> List[Dict[str, Any]]:
    """
    將本次 ETL 結果整理成要寫入歷史報表的列。

    第一列一定是 ETL 統計。
    後面每一列是某一種重複資料的明細。

    注意：
    目前報表欄位沒有「執行狀態」或「原因」欄，
    run_status 只用來決定是否應寫入重複明細。
    """
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

    if run_status == "成功" and not duplicate_groups.empty:
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

            for col in FIELDNAMES:
                detail_row[col] = group_row[col]

            report_rows.append(detail_row)

    return report_rows


def append_empty_or_failed_run_report(
    *,
    batch_id: str,
    run_time: str,
    run_status: str,
) -> None:
    """
    輸入檔不存在、空檔、只有表頭，或 ETL 失敗時，
    仍追加一列全為 0 的 ETL 統計。

    因為目前使用者指定的報表欄位沒有「狀態」與「原因」，
    詳細原因會印在 Cloud Run 日誌中。
    """
    empty_groups = pd.DataFrame(columns=[*FIELDNAMES, "出現次數", "刪除重複筆數"])

    rows = build_report_rows(
        batch_id=batch_id,
        run_time=run_time,
        run_status=run_status,
        before_count=0,
        after_count=0,
        duplicate_count=0,
        duplicate_group_count=0,
        duplicate_groups=empty_groups,
    )

    append_report_rows(rows)


# =========================================================
# 8. 主程式
# =========================================================


def main() -> int:
    global storage_client

    # 同一次 ETL 的統計列與重複明細列，都使用同一個批次 ID。
    # 加入微秒，避免同一秒內連跑兩次造成 ID 重複。
    now = datetime.now()
    batch_id = now.strftime("%Y%m%d_%H%M%S_%f")
    run_time = now.strftime("%Y-%m-%d %H:%M:%S")

    print("\n========== 03 Cloud Run ETL 去重開始 ==========")
    print("執行批次 ID：", batch_id)
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR)
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)
    print("輸入 all_year：", INPUT_ALL_YEAR_FILE)
    print("輸出 final raw：", OUTPUT_FILE)
    print("去重歷史報表：", DEDUP_REPORT_FILE)

    try:
        # 1. 建立 GCS client，下載本次 ETL 所需輸入檔。
        storage_client = create_storage_client()
        download_required_input_files()

        # 2. 輸入 all_year 檔案存在性檢查。
        if not INPUT_ALL_YEAR_FILE.exists():
            print("找不到 all_year CSV，已輸出空的最終 CSV")
            write_empty_output()
            append_empty_or_failed_run_report(
                batch_id=batch_id,
                run_time=run_time,
                run_status="無資料",
            )
            upload_file_to_gcs(OUTPUT_FILE)
            upload_file_to_gcs(DEDUP_REPORT_FILE)
            return 0

        if INPUT_ALL_YEAR_FILE.stat().st_size == 0:
            print("all_year CSV 是空檔，已輸出空的最終 CSV")
            write_empty_output()
            append_empty_or_failed_run_report(
                batch_id=batch_id,
                run_time=run_time,
                run_status="無資料",
            )
            upload_file_to_gcs(OUTPUT_FILE)
            upload_file_to_gcs(DEDUP_REPORT_FILE)
            return 0

        # 3. 讀取 raw all_year CSV。
        df = pd.read_csv(INPUT_ALL_YEAR_FILE, encoding="utf-8-sig")

        # 只有表頭、沒有資料列。
        if len(df) == 0:
            print("all_year CSV 只有表頭，沒有資料列，已輸出空的最終 CSV")
            write_empty_output()
            append_empty_or_failed_run_report(
                batch_id=batch_id,
                run_time=run_time,
                run_status="無資料",
            )
            upload_file_to_gcs(OUTPUT_FILE)
            upload_file_to_gcs(DEDUP_REPORT_FILE)
            return 0

        # 4. 檢查欄位、只保留 8 欄、清理文字。
        check_columns(df)
        df = df[FIELDNAMES]
        df = clean_dataframe(df)

        before_count = len(df)

        # 5. 產生重複群組明細。
        duplicate_groups = (
            df.groupby(FIELDNAMES, dropna=False).size().reset_index(name="出現次數")
        )

        duplicate_groups = duplicate_groups[duplicate_groups["出現次數"] > 1].copy()

        # 某組出現 3 次，最終保留 1 次，所以實際刪除 2 次。
        duplicate_groups["刪除重複筆數"] = duplicate_groups["出現次數"] - 1

        # 報表中先顯示重複次數最多的資料，再依 8 欄排序。
        if not duplicate_groups.empty:
            duplicate_groups = duplicate_groups.sort_values(
                by=["出現次數", *FIELDNAMES],
                ascending=[False] + [True] * len(FIELDNAMES),
                kind="stable",
            ).reset_index(drop=True)

        duplicate_group_count = len(duplicate_groups)

        # 6. 去重並輸出最終資料。
        # keep="first"：每組完全相同資料只保留第一次出現者。
        df_clean = df.drop_duplicates(
            subset=FIELDNAMES,
            keep="first",
        ).reset_index(drop=True)

        after_count = len(df_clean)
        duplicate_count = before_count - after_count

        write_final_output(df_clean)

        # 7. 將本次統計與重複明細追加到歷史報表。
        report_rows = build_report_rows(
            batch_id=batch_id,
            run_time=run_time,
            run_status="成功",
            before_count=before_count,
            after_count=after_count,
            duplicate_count=duplicate_count,
            duplicate_group_count=duplicate_group_count,
            duplicate_groups=duplicate_groups,
        )
        append_report_rows(report_rows)

        # 8. 最終結果與歷史報表上傳 GCS。
        upload_file_to_gcs(OUTPUT_FILE)
        upload_file_to_gcs(DEDUP_REPORT_FILE)

        print("\n========== 03 Cloud Run ETL 去重完成 ==========")
        print("原始 raw 資料筆數：", before_count)
        print("重複群組數：", duplicate_group_count)
        print("實際刪除重複資料筆數：", duplicate_count)
        print("去重後資料筆數：", after_count)
        print("最終輸出檔案：", OUTPUT_FILE)
        print("歷史去重報表：", DEDUP_REPORT_FILE)
        print("本次報表批次 ID：", batch_id)

        return 0

    except Exception as e:
        print("\n03 Cloud Run ETL 發生錯誤：", type(e).__name__, e)
        print(traceback.format_exc())

        # 若 GCS 已經可使用，盡量留下本次失敗時間點的 0 筆統計。
        # 原因會保留在 Cloud Run 日誌；報表欄位依你目前規格不放狀態/原因。
        try:
            append_empty_or_failed_run_report(
                batch_id=batch_id,
                run_time=run_time,
                run_status="失敗",
            )

            if storage_client is not None:
                upload_file_to_gcs(DEDUP_REPORT_FILE)
        except Exception as report_error:
            print(
                "03 失敗後，去重歷史報表也無法寫入或上傳：",
                type(report_error).__name__,
                report_error,
            )

        return 1


if __name__ == "__main__":
    sys.exit(main())

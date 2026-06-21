"""
03_etl_direct_transaction_deduplicate.py

用途：
Cloud Run Job 版本的「直轉供成交 raw 去重 ETL」。

這支程式會做：
1. 從 LOCAL_WORKDIR 找 raw CSV
   Cloud Run 預設是 /tmp

2. 優先讀取最新日期版 raw：
   trec_direct_transaction_raw_all_*.csv

3. 如果找不到 raw_all，再支援固定檔名：
   trec_direct_transaction_raw.csv

4. 只保留固定 8 欄

5. 用 8 欄完全相同作為重複判斷

6. 輸出最新 ETL 結果：
   trec_direct_transaction_raw.csv

7. 上傳到 GCS

注意：
01 產生的是原始 raw，不去重複。
03 才做 ETL 去重，並輸出固定檔名 trec_direct_transaction_raw.csv。
"""

import os
import glob
import tempfile

import pandas as pd
from google.cloud import storage

# =========================
# 檔案設定
# =========================

RAW_PREFIX = "trec_direct_transaction_raw"

# Cloud Run 裡面使用 /tmp
# 本機測試時會使用電腦暫存資料夾
LOCAL_WORKDIR = os.getenv("LOCAL_WORKDIR", tempfile.gettempdir())
os.makedirs(LOCAL_WORKDIR, exist_ok=True)

# 固定 raw 檔名
# 這是 03 ETL 最後輸出的最新結果
RAW_FILE = f"{RAW_PREFIX}.csv"

# 日期版 raw_all 檔名格式
# 例如：
# trec_direct_transaction_raw_all_20260613.csv
RAW_ALL_PATTERN = f"{RAW_PREFIX}_all_*.csv"

# ETL 最終輸出檔名
# 注意：這是去重後的最新結果，不是 01 的原始 raw
OUTPUT_FILE = f"{RAW_PREFIX}.csv"


# =========================
# GCS 設定
# =========================

GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()
GCS_PREFIX = os.getenv(
    "GCS_PREFIX",
    "raw_data/t_rec/direct_transaction",
).strip("/")


# =========================
# 欄位設定
# =========================

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


# =========================
# 函式 1：組本地檔案路徑
# =========================


def local_path(filename):
    """
    組成本地檔案路徑。

    Cloud Run 裡會是：
    /tmp/檔名
    """

    return os.path.join(LOCAL_WORKDIR, filename)


# =========================
# 函式 2：GCS blob 路徑
# =========================


def build_gcs_blob_name(filename):
    """
    組出 GCS 上的檔案路徑。

    例如：
    raw_data/direct_transaction/test_da/trec_direct_transaction_raw.csv
    """

    if GCS_PREFIX:
        return f"{GCS_PREFIX}/{filename}"

    return filename


# =========================
# 函式 3：建立 GCS client
# =========================


def create_storage_client():
    """
    建立 GCS client。

    如果沒有設定 GCS_BUCKET，代表只跑本機，不上傳。
    """

    if not GCS_BUCKET:
        print("沒有設定 GCS_BUCKET，略過 GCS 功能")
        return None

    return storage.Client()


# =========================
# 函式 4：從 GCS 下載指定檔案
# =========================


def download_from_gcs_if_missing(storage_client, filename):
    """
    如果本地 /tmp 沒有檔案，就嘗試從 GCS 下載指定檔案。

    主要是 fallback 用。
    03 正常接在 01 後面跑時，/tmp 已經會有 raw_all 日期檔。
    """

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
        print(f"GCS 找不到檔案：gs://{GCS_BUCKET}/{blob_name}")
        return local_file

    print(f"下載：gs://{GCS_BUCKET}/{blob_name} -> {local_file}")
    blob.download_to_filename(local_file)

    return local_file


# =========================
# 函式 5：從 GCS 下載最新 raw_all 日期檔
# =========================


def download_latest_raw_all_from_gcs(storage_client):
    """
    如果 03 單獨執行，/tmp 裡可能沒有 raw_all 日期檔。

    這時候從 GCS_PREFIX 底下找最新的：
    trec_direct_transaction_raw_all_*.csv

    找到後下載到 /tmp。
    """

    if storage_client is None:
        print("沒有 GCS client，無法下載最新 raw_all")
        return None

    if not GCS_BUCKET:
        print("沒有 GCS_BUCKET，無法下載最新 raw_all")
        return None

    prefix = f"{GCS_PREFIX}/" if GCS_PREFIX else ""

    print("\n========== 嘗試從 GCS 找最新 raw_all ==========")
    print("Bucket：", GCS_BUCKET)
    print("Prefix：", GCS_PREFIX)

    candidates = []

    for blob in storage_client.list_blobs(GCS_BUCKET, prefix=prefix):
        filename = os.path.basename(blob.name)

        if filename.startswith(f"{RAW_PREFIX}_all_") and filename.endswith(".csv"):
            candidates.append(blob)

    if not candidates:
        print("GCS 找不到任何 raw_all 日期檔")
        return None

    latest_blob = max(candidates, key=lambda b: b.updated)
    latest_filename = os.path.basename(latest_blob.name)
    local_file = local_path(latest_filename)

    print(f"找到最新 raw_all：gs://{GCS_BUCKET}/{latest_blob.name}")
    print(f"下載到：{local_file}")

    latest_blob.download_to_filename(local_file)

    return local_file


# =========================
# 函式 6：上傳檔案到 GCS
# =========================


def upload_file_to_gcs(storage_client, local_file):
    """
    上傳單一檔案到 GCS。
    """

    if storage_client is None:
        print("沒有 GCS client，略過上傳")
        return

    if not os.path.exists(local_file):
        print("找不到本地檔案，無法上傳：", local_file)
        return

    filename = os.path.basename(local_file)
    blob_name = build_gcs_blob_name(filename)

    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(blob_name)

    blob.upload_from_filename(local_file)

    print("已上傳：", local_file)
    print(f"GCS 位置：gs://{GCS_BUCKET}/{blob_name}")


# =========================
# 函式 7：找到要 ETL 的 raw CSV
# =========================


def find_input_raw_file():
    """
    找要 ETL 的 raw CSV。

    優先順序：
    1. /tmp/trec_direct_transaction_raw_all_*.csv 最新一份
    2. /tmp/trec_direct_transaction_raw.csv

    注意：
    因為 01 現在會輸出日期版 raw_all，
    所以 03 要優先讀 raw_all 日期檔，
    不要先讀 trec_direct_transaction_raw.csv。
    """

    raw_all_pattern = local_path(RAW_ALL_PATTERN)
    files = glob.glob(raw_all_pattern)

    if files:
        latest_file = max(files, key=os.path.getmtime)
        print("找到最新 raw_all CSV：", latest_file)
        return latest_file

    fixed_raw_file = local_path(RAW_FILE)

    if os.path.exists(fixed_raw_file):
        if os.path.getsize(fixed_raw_file) > 0:
            print("找不到 raw_all，改用固定 raw CSV：", fixed_raw_file)
            return fixed_raw_file

    raise FileNotFoundError(
        "找不到 raw CSV，請確認是否有 "
        "trec_direct_transaction_raw_all_YYYYMMDD.csv "
        "或 trec_direct_transaction_raw.csv"
    )


# =========================
# 函式 8：檢查欄位
# =========================


def check_columns(df):
    """
    檢查 CSV 是否有需要的 8 個欄位。
    """

    missing_columns = []

    for col in FIELDNAMES:
        if col not in df.columns:
            missing_columns.append(col)

    if missing_columns:
        raise ValueError(f"CSV 缺少欄位：{missing_columns}")


# =========================
# 函式 9：清理欄位文字
# =========================


def clean_dataframe(df):
    """
    做簡單欄位清理。

    這裡不改資料意思，只做：
    1. 空值補成空字串
    2. 前後空白去掉
    """

    df = df.copy()

    for col in FIELDNAMES:
        df[col] = df[col].fillna("").astype(str).str.strip()

    return df


# =========================
# 主程式
# =========================


def main():
    print("\n========== 03 ETL 去重開始 ==========")
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR)
    print("GCS_BUCKET：", GCS_BUCKET)
    print("GCS_PREFIX：", GCS_PREFIX)

    storage_client = create_storage_client()

    # 03 正常接在 01 後面跑時，/tmp 裡應該已經有 raw_all 日期檔。
    # 如果 03 是單獨跑，這裡才嘗試從 GCS 下載最新 raw_all。
    local_raw_all_files = glob.glob(local_path(RAW_ALL_PATTERN))

    if not local_raw_all_files:
        download_latest_raw_all_from_gcs(storage_client)

    # 如果還是沒有 raw_all，再 fallback 嘗試下載固定 raw.csv
    local_raw_all_files = glob.glob(local_path(RAW_ALL_PATTERN))

    if not local_raw_all_files:
        download_from_gcs_if_missing(storage_client, RAW_FILE)

    input_file = find_input_raw_file()
    output_file = local_path(OUTPUT_FILE)

    print("\n讀取 raw 檔案：", input_file)

    df = pd.read_csv(input_file, encoding="utf-8-sig")

    check_columns(df)

    # 只保留固定 8 欄
    df = df[FIELDNAMES]

    # 清理空白與空值
    df = clean_dataframe(df)

    before_count = len(df)

    # 去掉 8 欄完全一樣的重複資料
    df_clean = df.drop_duplicates(subset=FIELDNAMES, keep="first")

    after_count = len(df_clean)
    duplicate_count = before_count - after_count

    # 用 tmp 檔避免寫到一半中斷，造成 CSV 壞掉
    temp_file = output_file + ".tmp"

    df_clean.to_csv(temp_file, index=False, encoding="utf-8-sig")
    os.replace(temp_file, output_file)

    print("\n========== 03 ETL 去重完成 ==========")
    print("原始 raw 資料筆數：", before_count)
    print("刪除重複資料筆數：", duplicate_count)
    print("去重後資料筆數：", after_count)
    print("輸出檔案：", output_file)

    upload_file_to_gcs(storage_client, output_file)

    print("\n03 ETL 去重流程完成")


if __name__ == "__main__":
    main()

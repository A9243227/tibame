"""
04_run_direct_transaction_pipeline.py

用途：
Cloud Run Job 版本的直轉供交易資料流程總控程式。

執行順序：
1. 01_crawl_direct_transaction_raw.py
   - 爬取 2026 raw 資料
   - 產生 raw / year raw / status / failed CSV
   - CSV 會存在 LOCAL_WORKDIR，Cloud Run 預設是 /tmp
   - 並上傳到 GCS

2. 如果 failed CSV 有真正失敗資料，才執行：
   02_retry_direct_transaction_failed.py
   - 讀取 failed CSV
   - 補抓失敗資料
   - 成功補回 raw CSV
   - 仍失敗則產生 retry failed CSV
   - 並上傳到 GCS

3. 03_etl_direct_transaction_deduplicate.py
   - 讀取 raw CSV
   - 去除重複資料
   - 輸出 trec_direct_transaction_raw.csv
   - 並上傳到 GCS

注意：
所有要在 Cloud Run 跑的 py 檔案，都要放在同一個資料夾：
direct_transaction_cloudrun/
"""

import csv
import glob
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

print("========== 04 檔案真的有被 Cloud Run 執行 ==========", flush=True)


# =========================
# 路徑設定
# =========================

# 取得目前這支 04.py 所在資料夾
# Cloud Run 裡會是 /app
BASE_DIR = Path(__file__).resolve().parent

# Cloud Run 建議用 /tmp
# 本機測試時，如果你沒有設定 LOCAL_WORKDIR，就會用系統暫存資料夾
LOCAL_WORKDIR = Path(os.getenv("LOCAL_WORKDIR", tempfile.gettempdir()))
os.makedirs(LOCAL_WORKDIR, exist_ok=True)


# =========================
# 檔案設定
# =========================

RAW_PREFIX = "trec_direct_transaction_raw"

# 目前 Cloud Run 版固定 failed 檔名
FIXED_FAILED_FILE = LOCAL_WORKDIR / f"{RAW_PREFIX}_failed.csv"

# 舊版日期 failed 檔名格式，保留支援
# 例如：
# trec_direct_transaction_raw_failed_20260612.csv
DATE_FAILED_PATTERN = str(LOCAL_WORKDIR / f"{RAW_PREFIX}_failed_*.csv")


# =========================
# 要依序執行的程式
# =========================

SCRIPT_01 = "01_crawl_direct_transaction_raw.py"
SCRIPT_02 = "02_retry_direct_transaction_failed.py"
SCRIPT_03 = "03_etl_direct_transaction_deduplicate.py"


# =========================
# 函式 1：執行單一 Python 程式
# =========================


def run_script(script_name):
    """
    執行指定 Python 檔案。

    使用 sys.executable：
    代表會用目前容器裡正在跑的 Python 執行。

    cwd=BASE_DIR：
    代表執行時工作目錄固定在 direct_transaction_cloudrun 這個資料夾。
    這樣就不會去看外面的 supply 或其他資料夾。
    """

    script_path = BASE_DIR / script_name

    if not script_path.exists():
        raise FileNotFoundError(f"找不到程式檔案：{script_path}")

    env = os.environ.copy()

    # 確保 01、02、03 都使用同一個暫存資料夾
    env["LOCAL_WORKDIR"] = str(LOCAL_WORKDIR)

    print("\n" + "=" * 70, flush=True)
    print(f"開始執行：{script_name}", flush=True)
    print("BASE_DIR：", BASE_DIR, flush=True)
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR, flush=True)
    print("=" * 70, flush=True)

    subprocess.run(
        [sys.executable, "-u", str(script_path)],
        cwd=str(BASE_DIR),
        check=True,
        env=env,
    )

    print("\n" + "=" * 70, flush=True)
    print(f"執行完成：{script_name}", flush=True)
    print("=" * 70, flush=True)


# =========================
# 函式 2：找 failed CSV
# =========================


def find_failed_csv():
    """
    找 failed CSV。

    優先順序：
    1. /tmp/trec_direct_transaction_raw_failed.csv
    2. /tmp/trec_direct_transaction_raw_failed_YYYYMMDD.csv 最新一份

    如果找不到，代表 01 沒有真正失敗資料，02 可以略過。
    """

    # 1. 固定檔名版本
    if FIXED_FAILED_FILE.exists():
        return FIXED_FAILED_FILE

    # 2. 舊版日期檔名支援
    files = []

    for file in glob.glob(DATE_FAILED_PATTERN):
        file_path = Path(file)
        file_name = file_path.name

        # 只吃：
        # trec_direct_transaction_raw_failed_20260612.csv
        #
        # 不吃：
        # trec_direct_transaction_raw_failed_retry.csv
        # trec_direct_transaction_raw_failed_retry_20260612.csv
        if re.match(rf"^{RAW_PREFIX}_failed_\d{{8}}\.csv$", file_name):
            files.append(file_path)

    if files:
        latest_file = max(files, key=lambda p: p.stat().st_mtime)
        return latest_file

    return None


# =========================
# 函式 3：判斷 failed CSV 是否有資料
# =========================


def failed_csv_has_data():
    """
    判斷 failed CSV 裡面是否真的有失敗資料。

    如果：
    1. 沒有 failed CSV
    2. failed CSV 是空檔
    3. failed CSV 只有表頭

    就代表沒有需要 retry 的資料，02 可以略過。
    """

    failed_file = find_failed_csv()

    if failed_file is None:
        print("\n沒有 failed CSV，略過 02 retry", flush=True)
        return False

    if not failed_file.exists():
        print("\nfailed CSV 不存在，略過 02 retry：", failed_file, flush=True)
        return False

    if failed_file.stat().st_size == 0:
        print("\nfailed CSV 是空檔，略過 02 retry：", failed_file, flush=True)
        return False

    with open(failed_file, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if len(rows) == 0:
        print("\nfailed CSV 只有表頭，沒有失敗資料，略過 02 retry", flush=True)
        print("failed CSV：", failed_file, flush=True)
        return False

    print("\n偵測到 failed CSV 有資料，準備執行 02 retry", flush=True)
    print("failed CSV：", failed_file, flush=True)
    print("failed 筆數：", len(rows), flush=True)

    return True


# =========================
# 主程式
# =========================


def main():
    print("\n========== T-REC 直轉供交易資料 Cloud Run 流程開始 ==========", flush=True)
    print("BASE_DIR：", BASE_DIR, flush=True)
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR, flush=True)
    print("GCS_BUCKET：", os.getenv("GCS_BUCKET", ""), flush=True)
    print("GCS_PREFIX：", os.getenv("GCS_PREFIX", ""), flush=True)
    print("YEARS_TO_CRAWL：", os.getenv("YEARS_TO_CRAWL", ""), flush=True)
    print("MAX_PAGES_PER_YEAR：", os.getenv("MAX_PAGES_PER_YEAR", ""), flush=True)

    try:
        # 1. 先跑 01 爬蟲
        run_script(SCRIPT_01)

        # 2. 如果 01 有產生 failed 且裡面有資料，才跑 02
        if failed_csv_has_data():
            run_script(SCRIPT_02)
        else:
            print("\n========== 略過 02 ==========", flush=True)
            print("原因：沒有真正失敗資料需要 retry", flush=True)

        # 3. 最後跑 03 ETL 去重
        run_script(SCRIPT_03)

    except subprocess.CalledProcessError as e:
        print("\n========== 流程中斷 ==========", flush=True)
        print("有程式執行失敗，所以後面的程式不會繼續跑。", flush=True)
        print("失敗 return code：", e.returncode, flush=True)

        raise

    except Exception as e:
        print("\n========== 流程發生錯誤 ==========", flush=True)
        print("錯誤類型：", type(e).__name__, flush=True)
        print("錯誤內容：", e, flush=True)

        raise

    print(
        "\n========== T-REC 直轉供交易資料 Cloud Run 流程全部完成 ==========",
        flush=True,
    )
    print("最後輸出檔案應為：trec_direct_transaction_raw.csv", flush=True)


if __name__ == "__main__":
    main()

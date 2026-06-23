"""
04_run_direct_transaction_pipeline.py

T-REC 直轉供憑證成交紀錄：
Cloud Run Job Playwright/API 流程總控版

流程：
1. 01_crawl_direct_transaction_raw.py
   - Playwright 開首頁取得 Cookie / CSRF Token
   - data API 抓外層列表
   - detail API 抓成交明細
   - 產生年度 raw / all_year / status / failed CSV
   - 上傳 GCS

2. 若 failed.csv 有真正失敗資料，才執行：
   02_retry_direct_transaction_failed.py
   - Playwright + API 補抓 failed
   - 成功資料補回年度 raw
   - 重建 all_year
   - retry 仍失敗資料寫入 failed_retry.csv
   - 上傳 GCS

3. 03_etl_direct_transaction_deduplicate.py
   - 讀取 all_year CSV
   - 以固定 8 欄完全相同進行去重
   - 輸出 trec_direct_transaction_raw.csv
   - 上傳 GCS

Cloud Run 重要設定：
- 所有暫存檔放 /tmp
- 正式 CSV 放 GCS
- 01、02、03 必須位於與本檔同一個資料夾
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# =========================================================
# 路徑設定
# =========================================================

# 目前 04 所在資料夾。
# Dockerfile 的 WORKDIR 是 /app，因此 Cloud Run 會是 /app。
BASE_DIR = Path(__file__).resolve().parent

# Cloud Run 預設使用 /tmp。
# 地端沒有設定時，使用系統暫存資料夾。
LOCAL_WORKDIR = Path(os.getenv("LOCAL_WORKDIR", tempfile.gettempdir())).resolve()

LOCAL_WORKDIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# CSV 檔案設定
# =========================================================

RAW_PREFIX = "trec_direct_transaction_raw"

FAILED_CSV_FILE = LOCAL_WORKDIR / f"{RAW_PREFIX}_failed.csv"
FINAL_RAW_CSV_FILE = LOCAL_WORKDIR / f"{RAW_PREFIX}.csv"
ALL_YEAR_RAW_CSV_FILE = LOCAL_WORKDIR / f"{RAW_PREFIX}_all_year.csv"
STATUS_CSV_FILE = LOCAL_WORKDIR / f"{RAW_PREFIX}_status.csv"
FAILED_RETRY_CSV_FILE = LOCAL_WORKDIR / f"{RAW_PREFIX}_failed_retry.csv"


# =========================================================
# 要依序執行的 Python 檔案
# =========================================================

SCRIPT_01 = "01_crawl_direct_transaction_raw.py"
SCRIPT_02 = "02_retry_direct_transaction_failed.py"
SCRIPT_03 = "03_etl_direct_transaction_deduplicate.py"


# =========================================================
# 工具函式
# =========================================================


def run_script(script_name: str) -> None:
    """
    使用目前容器的 Python 依序執行子程式。

    sys.executable：
        使用 Docker 容器目前正在執行的 Python。

    -u：
        不緩衝 print，Cloud Run Logs 可以即時看到輸出。

    cwd=BASE_DIR：
        確保 01、02、03 都從 /app 執行，
        可以找到同資料夾的程式檔。
    """
    script_path = BASE_DIR / script_name

    if not script_path.exists():
        raise FileNotFoundError(f"找不到要執行的程式檔案：{script_path}")

    # 把目前 Cloud Run 所有環境變數完整傳給子程式。
    # 包含：
    # GCS_BUCKET
    # GCS_PREFIX
    # YEARS_TO_CRAWL
    # MAX_PAGES_PER_YEAR
    # SAVE_EVERY_PAGES
    # HEADLESS
    env = os.environ.copy()

    # 強制確保 01、02、03 共用同一個 /tmp。
    env["LOCAL_WORKDIR"] = str(LOCAL_WORKDIR)

    print("\n" + "=" * 80, flush=True)
    print(f"開始執行：{script_name}", flush=True)
    print("BASE_DIR：", BASE_DIR, flush=True)
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR, flush=True)
    print("GCS_BUCKET：", env.get("GCS_BUCKET", ""), flush=True)
    print("GCS_PREFIX：", env.get("GCS_PREFIX", ""), flush=True)
    print("=" * 80, flush=True)

    subprocess.run(
        [sys.executable, "-u", str(script_path)],
        cwd=str(BASE_DIR),
        check=True,
        env=env,
    )

    print("\n" + "=" * 80, flush=True)
    print(f"執行完成：{script_name}", flush=True)
    print("=" * 80, flush=True)


def failed_csv_has_data() -> bool:
    """
    判斷 01 是否真的有 failed 資料。

    以下情況都不跑 02：
    1. failed.csv 不存在
    2. failed.csv 是空檔
    3. failed.csv 只有表頭
    """
    if not FAILED_CSV_FILE.exists():
        print("沒有 failed CSV，略過 02 retry", flush=True)
        return False

    if FAILED_CSV_FILE.stat().st_size == 0:
        print("failed CSV 是空檔，略過 02 retry", flush=True)
        print("failed CSV：", FAILED_CSV_FILE, flush=True)
        return False

    with FAILED_CSV_FILE.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("failed CSV 只有表頭，沒有失敗資料，略過 02 retry", flush=True)
        print("failed CSV：", FAILED_CSV_FILE, flush=True)
        return False

    print("偵測到 failed CSV 有資料，準備執行 02 retry", flush=True)
    print("failed CSV：", FAILED_CSV_FILE, flush=True)
    print("failed 筆數：", len(rows), flush=True)

    return True


def print_output_summary() -> None:
    """Cloud Run 流程結束時，印出預期輸出檔案位置。"""
    print("\n========== Cloud Run 流程輸出摘要 ==========", flush=True)
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR, flush=True)
    print("年度 raw / all_year / final raw 會同步上傳到 GCS", flush=True)
    print("all_year raw：", ALL_YEAR_RAW_CSV_FILE, flush=True)
    print("最終去重 raw：", FINAL_RAW_CSV_FILE, flush=True)
    print("status CSV：", STATUS_CSV_FILE, flush=True)
    print("failed CSV：", FAILED_CSV_FILE, flush=True)
    print("failed_retry CSV：", FAILED_RETRY_CSV_FILE, flush=True)


# =========================================================
# 主程式
# =========================================================


def main() -> int:
    print("\n" + "#" * 80, flush=True)
    print("04 Cloud Run Playwright/API 流程總控程式已啟動", flush=True)
    print("#" * 80, flush=True)

    print("BASE_DIR：", BASE_DIR, flush=True)
    print("LOCAL_WORKDIR：", LOCAL_WORKDIR, flush=True)
    print("GCS_BUCKET：", os.getenv("GCS_BUCKET", ""), flush=True)
    print("GCS_PREFIX：", os.getenv("GCS_PREFIX", ""), flush=True)
    print("YEARS_TO_CRAWL：", os.getenv("YEARS_TO_CRAWL", "2026"), flush=True)
    print(
        "MAX_PAGES_PER_YEAR：",
        os.getenv("MAX_PAGES_PER_YEAR", "0"),
        flush=True,
    )
    print("PAGE_LENGTH：", os.getenv("PAGE_LENGTH", "10"), flush=True)
    print(
        "SAVE_EVERY_PAGES：",
        os.getenv("SAVE_EVERY_PAGES", "10"),
        flush=True,
    )
    print("HEADLESS：", os.getenv("HEADLESS", "true"), flush=True)

    try:
        # 01：原始資料爬取。
        run_script(SCRIPT_01)

        # 02：只有真正失敗資料才 retry。
        if failed_csv_has_data():
            run_script(SCRIPT_02)
        else:
            print("\n========== 略過 02 retry ==========", flush=True)
            print("原因：01 沒有真正失敗資料", flush=True)

        # 03：固定執行 8 欄去重。
        run_script(SCRIPT_03)

    except subprocess.CalledProcessError as e:
        print("\n========== Cloud Run 流程中斷 ==========", flush=True)
        print("子程式執行失敗，後續流程不再執行。", flush=True)
        print("失敗 return code：", e.returncode, flush=True)
        print_output_summary()
        return e.returncode if e.returncode else 1

    except Exception as e:
        print("\n========== Cloud Run 流程發生錯誤 ==========", flush=True)
        print("錯誤類型：", type(e).__name__, flush=True)
        print("錯誤內容：", e, flush=True)
        print_output_summary()
        return 1

    print("\n" + "#" * 80, flush=True)
    print("Cloud Run 01 → 02 → 03 全部流程完成", flush=True)
    print("#" * 80, flush=True)

    print_output_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())

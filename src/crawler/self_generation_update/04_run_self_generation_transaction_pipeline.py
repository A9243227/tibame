"""
04_run_self_generation_transaction_pipeline.py

自用發電設備憑證成交紀錄主流程總控：
01 →（本次 failed 有資料才）02 → 03。

本檔只決定一次 PIPELINE_DT，並傳給所有子程式。
因此即使 Cloud Run Job 跨午夜，raw、old_raw_data 歷史去重版本與 audit 都會落在相同 dt=YYYY-MM-DD。
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE_DIR = Path(__file__).resolve().parent
LOCAL_WORKDIR = Path(os.getenv("LOCAL_WORKDIR", tempfile.gettempdir())).resolve()
LOCAL_WORKDIR.mkdir(parents=True, exist_ok=True)

RAW_PREFIX = "trec_self_generation_transaction_raw"
FAILED_CSV_FILE = LOCAL_WORKDIR / f"{RAW_PREFIX}_failed.csv"
FAILED_RETRY_CSV_FILE = LOCAL_WORKDIR / f"{RAW_PREFIX}_failed_retry.csv"

SCRIPT_01 = "01_crawl_self_generation_transaction_raw.py"
SCRIPT_02 = "02_retry_self_generation_transaction_failed.py"
SCRIPT_03 = "03_etl_self_generation_transaction_deduplicate.py"


def get_pipeline_dt() -> str:
    """優先沿用外部傳入的 PIPELINE_DT；否則採 Asia/Taipei 當日。"""
    value = os.getenv("PIPELINE_DT", "").strip()
    if value:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("PIPELINE_DT 必須是 YYYY-MM-DD，例如 2026-07-01") from exc
        return value

    timezone_name = os.getenv("PIPELINE_TIMEZONE", "Asia/Taipei").strip() or "Asia/Taipei"
    try:
        return datetime.now(ZoneInfo(timezone_name)).strftime("%Y-%m-%d")
    except ZoneInfoNotFoundError:
        print(f"警告：找不到時區 {timezone_name}，改用系統本地日期", flush=True)
        return datetime.now().strftime("%Y-%m-%d")


def run_script(script_name: str, env: dict[str, str]) -> None:
    """使用目前容器 Python 執行子程式，並傳遞同一份 PIPELINE_DT。"""
    script_path = BASE_DIR / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"找不到要執行的程式檔案：{script_path}")

    print("\n" + "=" * 80, flush=True)
    print(f"開始執行：{script_name}", flush=True)
    print("PIPELINE_DT：", env["PIPELINE_DT"], flush=True)
    print("LOCAL_WORKDIR：", env["LOCAL_WORKDIR"], flush=True)
    print("GCS_BUCKET：", env.get("GCS_BUCKET", ""), flush=True)
    print("GCS_PREFIX：", env.get("GCS_PREFIX", ""), flush=True)
    print("=" * 80, flush=True)

    subprocess.run(
        [sys.executable, "-u", str(script_path)],
        cwd=str(BASE_DIR),
        check=True,
        env=env,
    )


def failed_csv_has_data() -> bool:
    """failed.csv 不存在、空檔或只有表頭時，都不需要執行 02。"""
    if not FAILED_CSV_FILE.exists() or FAILED_CSV_FILE.stat().st_size == 0:
        print("failed.csv 不存在或是空檔，略過 02 retry", flush=True)
        return False

    with FAILED_CSV_FILE.open("r", newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))

    if not rows:
        print("failed.csv 只有表頭，略過 02 retry", flush=True)
        return False

    print("偵測到本次 failed.csv 有資料，準備執行 02", flush=True)
    print("failed 筆數：", len(rows), flush=True)
    return True


def print_output_summary(pipeline_dt: str) -> None:
    """列出最終 GCS 路徑：年度 raw、去重後歷史／最新資料、audit、control。"""
    bucket = os.getenv("GCS_BUCKET", "")
    prefix = os.getenv("GCS_PREFIX", "self_generation_transaction").strip("/")
    historical_prefix = os.getenv(
        "HISTORICAL_DEDUP_PREFIX",
        "old_raw_data/playwright_trec_self",
    ).strip("/")
    latest_prefix = os.getenv(
        "LATEST_DEDUP_PREFIX",
        "new_raw_data/playwright_trec_self",
    ).strip("/")

    project_base = f"gs://{bucket}/{prefix}".rstrip("/")
    historical_base = f"gs://{bucket}/{historical_prefix}".rstrip("/")
    latest_base = f"gs://{bucket}/{latest_prefix}".rstrip("/")
    compact_dt = pipeline_dt.replace("-", "")

    print("\n========== GCS 輸出摘要 ==========", flush=True)
    print(f"年度 raw／all_year：{project_base}/raw/dt={pipeline_dt}/", flush=True)
    print(
        "歷史去重資料："
        f"{historical_base}/dt={pipeline_dt}/{RAW_PREFIX}.csv",
        flush=True,
    )
    print(
        f"最新 BigQuery 去重資料：{latest_base}/{RAW_PREFIX}.csv",
        flush=True,
    )
    print(
        f"audit：{project_base}/audit/dt={pipeline_dt}/"
        f"trec_self_generation_transaction_dedup_report_{compact_dt}.csv",
        flush=True,
    )
    print(f"control failed：{project_base}/control/{RAW_PREFIX}_failed.csv", flush=True)
    print(f"control failed_retry：{project_base}/control/{RAW_PREFIX}_failed_retry.csv", flush=True)
    print(f"control status：{project_base}/control/{RAW_PREFIX}_status.csv", flush=True)


def main() -> int:
    pipeline_dt = get_pipeline_dt()

    base_env = os.environ.copy()
    base_env["LOCAL_WORKDIR"] = str(LOCAL_WORKDIR)
    base_env["PIPELINE_DT"] = pipeline_dt

    # 主流程 02 只能 retry 本次 01 產生的 failed.csv。
    # 避免 Cloud Run Job 環境變數殘留 FAILED_CSV_FILE=failed_retry.csv 而讀錯來源。
    base_env.pop("FAILED_CSV_FILE", None)

    print("\n" + "#" * 80, flush=True)
    print("04 自用發電主資料流程啟動：01 → 02（條件式）→ 03", flush=True)
    print("#" * 80, flush=True)
    print("PIPELINE_DT：", pipeline_dt, flush=True)
    print("YEARS_TO_CRAWL：", base_env.get("YEARS_TO_CRAWL", "2026"), flush=True)
    print("GCS_BUCKET：", base_env.get("GCS_BUCKET", ""), flush=True)
    print("GCS_PREFIX：", base_env.get("GCS_PREFIX", ""), flush=True)
    print("HISTORICAL_DEDUP_PREFIX：", base_env.get("HISTORICAL_DEDUP_PREFIX", "old_raw_data/playwright_trec_self"), flush=True)
    print("LATEST_DEDUP_PREFIX：", base_env.get("LATEST_DEDUP_PREFIX", "new_raw_data/playwright_trec_self"), flush=True)

    try:
        run_script(SCRIPT_01, base_env)

        if failed_csv_has_data():
            run_script(SCRIPT_02, base_env)
        else:
            print("\n略過 02：01 沒有真正失敗資料", flush=True)

        run_script(SCRIPT_03, base_env)

    except subprocess.CalledProcessError as exc:
        print("\n主流程中斷：子程式失敗，後續不再執行。", flush=True)
        print("return code：", exc.returncode, flush=True)
        print_output_summary(pipeline_dt)
        return exc.returncode or 1
    except Exception as exc:
        print("\n主流程發生錯誤：", type(exc).__name__, exc, flush=True)
        print_output_summary(pipeline_dt)
        return 1

    print("\n" + "#" * 80, flush=True)
    print("04 自用發電主資料流程完成", flush=True)
    print("#" * 80, flush=True)
    print_output_summary(pipeline_dt)
    return 0


if __name__ == "__main__":
    sys.exit(main())

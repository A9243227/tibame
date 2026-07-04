"""
05_run_direct_transaction_retry_pipeline.py

歷史 retry-only 總控：02（只讀 failed_retry）→ 03。03 會發布去重後歷史版本與最新 BigQuery 資料。

02 在 /tmp 沒有 raw 時，會從 raw/ 下日期最新、且有對應 all_year CSV 的快照複製年度檔，
建立新的 PIPELINE_DT 快照後再補抓，因此不會修改舊快照。
"""

from __future__ import annotations

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

RAW_PREFIX = "trec_direct_transaction_raw"
RETRY_FAILED_CSV_NAME = f"{RAW_PREFIX}_failed_retry.csv"

SCRIPT_02 = "02_retry_direct_transaction_failed.py"
SCRIPT_03 = "03_etl_direct_transaction_deduplicate.py"


def get_pipeline_dt() -> str:
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
    script_path = BASE_DIR / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"找不到要執行的程式檔案：{script_path}")

    print("\n" + "=" * 80, flush=True)
    print(f"開始執行：{script_name}", flush=True)
    print("PIPELINE_DT：", env["PIPELINE_DT"], flush=True)
    print("LOCAL_WORKDIR：", env["LOCAL_WORKDIR"], flush=True)
    print("GCS_BUCKET：", env.get("GCS_BUCKET", ""), flush=True)
    print("GCS_PREFIX：", env.get("GCS_PREFIX", ""), flush=True)
    print("FAILED_CSV_FILE：", env.get("FAILED_CSV_FILE", "(未設定)"), flush=True)
    print("=" * 80, flush=True)

    subprocess.run(
        [sys.executable, "-u", str(script_path)],
        cwd=str(BASE_DIR),
        check=True,
        env=env,
    )


def main() -> int:
    pipeline_dt = get_pipeline_dt()

    base_env = os.environ.copy()
    base_env["LOCAL_WORKDIR"] = str(LOCAL_WORKDIR)
    base_env["PIPELINE_DT"] = pipeline_dt
    base_env.pop("FAILED_CSV_FILE", None)

    retry_env = base_env.copy()
    retry_env["FAILED_CSV_FILE"] = RETRY_FAILED_CSV_NAME

    print("\n" + "#" * 80, flush=True)
    print("05 Retry-only 流程啟動：02（failed_retry）→ 03", flush=True)
    print("本流程不執行 01，不重新抓完整年度主資料。", flush=True)
    print("03 會更新 old_raw_data 歷史去重版本、new_raw_data 最新去重版本與 audit。", flush=True)
    print("#" * 80, flush=True)
    print("PIPELINE_DT：", pipeline_dt, flush=True)

    try:
        run_script(SCRIPT_02, retry_env)
        run_script(SCRIPT_03, base_env)
    except subprocess.CalledProcessError as exc:
        print("\nRetry-only 流程中斷，後續不再執行。", flush=True)
        print("return code：", exc.returncode, flush=True)
        return exc.returncode or 1
    except Exception as exc:
        print("\nRetry-only 流程發生錯誤：", type(exc).__name__, exc, flush=True)
        return 1

    print("\n" + "#" * 80, flush=True)
    print("05 Retry-only 流程完成：02 → 03", flush=True)
    print("#" * 80, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

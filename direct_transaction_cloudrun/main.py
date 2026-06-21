import os
import sys
import csv
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOCAL_WORKDIR = Path(os.getenv("LOCAL_WORKDIR", "/tmp"))


def run_python(script_name):
    script_path = BASE_DIR / script_name

    print("=" * 60)
    print(f"開始執行：{script_name}")
    print("=" * 60)

    subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(BASE_DIR),
        check=True,
        env=os.environ.copy(),
    )


def failed_csv_has_data():
    failed_file = LOCAL_WORKDIR / "trec_direct_transaction_raw_failed.csv"

    if not failed_file.exists():
        print("沒有 failed CSV，略過 02 retry")
        return False

    with open(failed_file, "r", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    if len(rows) <= 1:
        print("failed CSV 只有表頭，沒有失敗資料，略過 02 retry")
        return False

    return True


def main():
    os.environ.setdefault("LOCAL_WORKDIR", "/tmp")

    run_python("01_crawl_direct_transaction_raw.py")

    if failed_csv_has_data():
        run_python("02_retry_direct_transaction_failed.py")
    else:
        print("01 沒有 failed 資料，所以不跑 02")

    run_python("03_etl_direct_transaction_deduplicate.py")

    print("Cloud Run 全部流程完成")


if __name__ == "__main__":
    main()

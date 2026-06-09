"""
99_run_all_v5.py

用途：
一鍵執行 MySQL_GREEN_DATA 專案流程。

執行順序：
1. 建立資料庫與資料表
2. 匯入 trec_all_raw.csv
3. 匯入 trec_direct_supply_raw.csv
4. 匯入 trec_certificate_raw.csv
5. 建立資料資料表
6. 建立 View
7. 檢查資料庫
8. 產生 Sankey HTML

執行方式：
uv run python python/99_run_all_v5.py
"""

import subprocess
import sys
from pathlib import Path

from utils_v5 import SQL_DIR, execute_sql_file


BASE_DIR = Path(__file__).resolve().parents[1]
PYTHON_DIR = BASE_DIR / "python"


def run_python(script_name):
    """
    執行指定 Python 檔案。
    """
    script_path = PYTHON_DIR / script_name

    print("=" * 60)
    print(f"執行：{script_name}")
    print("=" * 60)

    subprocess.run([sys.executable, str(script_path)], check=True)


def main():
    """
    主流程：依序執行整個 ETL 與圖表產生流程。
    """
    print("=" * 60)
    print("開始建立 MySQL_GREEN_DATA 專案")
    print("=" * 60)

    execute_sql_file(SQL_DIR / "01_create_database_and_tables_v5.sql", use_database=False)

    run_python("01_import_trec_all_csv_v5.py")
    run_python("02_import_trec_direct_csv_v5.py")
    run_python("03_import_trec_certificate_csv_v5.py")
    run_python("04_build_normalized_tables_v5.py")
    run_python("05_create_views_v5.py")
    run_python("06_check_database_v5.py")
    run_python("08_check_raw_columns_v5.py")
    run_python("07_dashboard_sankey_top10_v5.py")

    print("=" * 60)
    print("V5 Final 全部流程執行完成")
    print("=" * 60)


if __name__ == "__main__":
    main()

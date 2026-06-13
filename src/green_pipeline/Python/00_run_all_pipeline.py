import runpy
from pathlib import Path
import pymysql

from utils import get_mysql_config, print_separator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MYSQL_DIR = PROJECT_ROOT / "MySQL"
PYTHON_DIR = PROJECT_ROOT / "Python"
DATABASE_NAME = get_mysql_config(include_database=True)["database"]

DROP_OBJECTS = [
    ("VIEW", "vw_transaction_detail"),
    ("VIEW", "vw_issued_certificate_detail"),
    ("TABLE", "fact_transaction"),
    ("TABLE", "fact_issued_certificate"),
    ("TABLE", "dim_facility"),
    ("TABLE", "dim_supply_type"),
    ("TABLE", "dim_energy_type"),
    ("TABLE", "dim_company"),
    ("TABLE", "trec_issued_certificate_clean"),
    ("TABLE", "trec_self_generation_transaction_clean"),
    ("TABLE", "trec_direct_transaction_clean"),
    ("TABLE", "trec_issued_certificate_raw"),
    ("TABLE", "trec_self_generation_transaction_raw"),
    ("TABLE", "trec_direct_transaction_raw"),
]

SQL_FILES = [
    "01_create_database_green_energy.sql",
    "02_trec_direct_transaction_raw.sql",
    "03_trec_self_generation_transaction_raw.sql",
    "04_trec_issued_certificate_raw.sql",
    "10_trec_direct_transaction_clean.sql",
    "11_trec_self_generation_transaction_clean.sql",
    "12_trec_issued_certificate_clean.sql",
    "20_dim_company.sql",
    "21_dim_energy_type.sql",
    "22_dim_supply_type.sql",
    "23_dim_facility.sql",
    "24_fact_transaction.sql",
    "25_vw_transaction_detail.sql",
    "26_fact_issued_certificate.sql",
    "27_vw_issued_certificate_detail.sql",
]

PYTHON_STEPS = [
    "01_import_trec_direct_transaction_raw.py",
    "02_import_trec_self_generation_transaction_raw.py",
    "03_import_trec_issued_certificate_raw.py",
    "check_raw_tables.py",
    "04_etl_trec_direct_transaction_clean.py",
    "05_etl_trec_self_generation_transaction_clean.py",
    "06_etl_trec_issued_certificate_clean.py",
    "07_load_dim_company.py",
    "08_load_dim_energy_type.py",
    "09_load_dim_supply_type.py",
    "10_load_dim_facility.py",
    "11_load_fact_transaction.py",
    "12_load_fact_issued_certificate.py",
    "13_check_normalized_model.py",
]

# 這支程式負責從 raw tables 到 clean tables、dim/fact tables、views 一次重建完整流程。
# 執行前必須輸入 YES，避免不小心 drop / rebuild 目前資料庫內容。
def get_server_connection():
    """
    建立不指定 database 的 MySQL 連線，用於建立資料庫與 drop 既有資料表。
    """
    return pymysql.connect(**get_mysql_config(include_database=False))

def read_sql_statements(sql_path):
    """
    讀取 SQL 檔案，移除註解後切成可逐段執行的 SQL statements。
    """
    sql = sql_path.read_text(encoding="utf-8")
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or stripped == "":
            continue
        lines.append(line)
    return [statement.strip() for statement in "\n".join(lines).split(";") if statement.strip()]

def confirm_rebuild():
    """
    顯示會被重建的資料庫物件，並要求使用者輸入 YES。
    """
    print_separator()
    print("完整流程會 drop / rebuild 下列資料庫物件：")
    for object_type, object_name in DROP_OBJECTS:
        print(f"{object_type}：{object_name}")
    print_separator()
    print("若確定目前可以重建資料庫內容，請輸入 YES 繼續。")
    user_input = input("請輸入 YES：").strip()
    if user_input != "YES":
        print("未輸入 YES，流程已取消")
        return False
    return True

def drop_existing_objects(cursor):
    """
    依照相依順序刪除既有 views 與 tables。
    """
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DATABASE_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cursor.execute(f"USE {DATABASE_NAME}")
    for object_type, object_name in DROP_OBJECTS:
        cursor.execute(f"DROP {object_type} IF EXISTS {object_name}")
        print(f"DROP {object_type} IF EXISTS {object_name}")

def execute_sql_files(cursor):
    """
    依序執行 MySQL/ 內的建表與建 view SQL。
    """
    for filename in SQL_FILES:
        sql_path = MYSQL_DIR / filename
        for statement in read_sql_statements(sql_path):
            cursor.execute(statement)
        print(f"已執行 SQL：{filename}")

def run_python_steps():
    """
    依序執行 Python/ 內的匯入、ETL、載入與檢查程式。
    """
    for filename in PYTHON_STEPS:
        print_separator()
        print(f"開始執行：{filename}")
        runpy.run_path(str(PYTHON_DIR / filename), run_name="__main__")

def run_all_pipeline():
    """
    執行完整重建流程。
    """
    if not confirm_rebuild():
        return
    conn = None
    cursor = None
    try:
        conn = get_server_connection()
        cursor = conn.cursor()
        print_separator()
        drop_existing_objects(cursor)
        execute_sql_files(cursor)
        conn.commit()
        cursor.close()
        conn.close()
        cursor = None
        conn = None
        run_python_steps()
        print_separator()
        print("完整資料流程執行完成")
        print_separator()
    except Exception as error:
        if conn is not None:
            conn.rollback()
        print_separator()
        print("完整資料流程執行失敗")
        print(f"錯誤訊息：{error}")
        print_separator()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

if __name__ == "__main__":
    run_all_pipeline()

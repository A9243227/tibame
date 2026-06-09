"""
utils_v5.py

專題：台灣綠電交易資料分析

共用工具：
1. 讀取 .env 資料庫連線設定
2. 建立 MySQL 連線
3. 清理空值、日期與數字欄位
4. 執行 SQL 檔案
5. 尋找 data/raw 或 data 資料夾中的 CSV
"""

import os
import re
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = BASE_DIR / "data" / "raw"
DATA_DIR = BASE_DIR / "data"
SQL_DIR = BASE_DIR / "sql"


def load_db_config():
    """
    讀取 .env 檔中的 MySQL 連線設定。
    """
    load_dotenv(BASE_DIR / ".env")

    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_NAME", "你的專案名稱"),
        "charset": "utf8mb4",
        "autocommit": False,
    }


def get_connection(database=True):
    """
    建立 MySQL 連線。
    database=False 時不指定資料庫，適合建立/刪除資料庫。
    """
    config = load_db_config()

    if not database:
        config.pop("database", None)

    return pymysql.connect(**config)


def clean_empty(value):
    """
    將空字串、NaN、NULL、None、-、— 統一轉成 None。
    """
    if pd.isna(value):
        return None

    value = str(value).strip()

    if value in ["", "nan", "NaN", "NULL", "null", "None", "-", "—"]:
        return None

    return value


def clean_decimal(value):
    """
    清理小數欄位。
    可處理 1,234.56、1,234.56 MWh、空值。
    """
    value = clean_empty(value)

    if value is None:
        return None

    value = re.sub(r"[^0-9.\-]", "", value)

    if value in ["", "-", "."]:
        return None

    try:
        return float(value)
    except ValueError:
        return None


def clean_int(value):
    """
    清理整數欄位。
    可處理 2024、2024.0、空值。
    """
    value = clean_empty(value)

    if value is None:
        return None

    value = re.sub(r"[^0-9.\-]", "", value)

    if value in ["", "-", "."]:
        return None

    try:
        return int(float(value))
    except ValueError:
        return None


def clean_date(value):
    """
    清理日期欄位。
    可解析時轉成 YYYY-MM-DD，否則回傳 None。
    """
    value = clean_empty(value)

    if value is None:
        return None

    dt = pd.to_datetime(value, errors="coerce")

    if pd.isna(dt):
        return None

    return dt.date()


def normalize_columns(df, column_mapping):
    """
    將 CSV 中文欄位名稱轉成英文欄位名稱。
    """
    df.columns = [str(col).strip() for col in df.columns]
    return df.rename(columns=column_mapping)


def read_csv_with_fallback(file_path):
    """
    讀取 CSV，優先使用 utf-8-sig，失敗時再嘗試其他常見編碼。
    """
    encodings = ["utf-8-sig", "utf-8", "cp950", "big5"]

    for encoding in encodings:
        try:
            return pd.read_csv(file_path, encoding=encoding)
        except UnicodeDecodeError:
            continue

    raise UnicodeDecodeError(f"無法讀取 CSV：{file_path}")


def find_csv_file(candidates):
    """
    在 data/raw 與 data 兩個資料夾尋找 CSV。
    這樣就算使用者把 CSV 放在 data/，程式也找得到。
    """
    search_dirs = [RAW_DATA_DIR, DATA_DIR]

    for folder in search_dirs:
        for filename in candidates:
            file_path = folder / filename
            if file_path.exists():
                return file_path

    return None


def execute_sql_file(sql_file_path, use_database=False):
    """
    執行 SQL 檔案。
    """
    sql_file_path = Path(sql_file_path)
    sql_text = sql_file_path.read_text(encoding="utf-8")

    conn = get_connection(database=use_database)
    cursor = conn.cursor()

    try:
        statements = [s.strip() for s in sql_text.split(";") if s.strip()]

        for statement in statements:
            cursor.execute(statement)

        conn.commit()
        print(f"SQL 執行完成：{sql_file_path.name}")

    except Exception as exc:
        conn.rollback()
        print(f"SQL 執行失敗：{sql_file_path.name}")
        raise exc

    finally:
        cursor.close()
        conn.close()

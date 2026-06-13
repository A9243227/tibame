import os
from datetime import datetime
from pathlib import Path
import pymysql

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MYSQL_CONFIG = {
    "MYSQL_HOST": "localhost",
    "MYSQL_PORT": "3306",
    "MYSQL_USER": "root",
    "MYSQL_DATABASE": "green_energy_exchange_db",
    "MYSQL_CHARSET": "utf8mb4",
}
TEXT_SYMBOL_MAP = str.maketrans({
    "（": "(", "）": ")", "，": ",", "。": ".", "：": ":", "；": ";",
    "！": "!", "？": "?", "、": ",", "／": "/", "－": "-", "～": "~",
    "「": "\"", "」": "\"", "『": "\"", "』": "\"", "　": " ",
})

# print_separator() 負責印出分隔線，讓終端機訊息比較容易閱讀。
def print_separator():
    """
    印出終端機訊息分隔線。
    """
    print("=" * 60)

# clean_empty() 負責將空字串轉成 None，方便寫入 MySQL NULL。
def clean_empty(value):
    """
    將空字串轉成 None。
    """
    if value is None:
        return None
    value = str(value).strip()
    if value == "":
        return None
    return value

# clean_text() 負責整理一般文字欄位，保留原文字內容但統一常見全形符號。
def clean_text(value):
    """
    將文字欄位的常見全形符號統一成半形符號。
    """
    value = clean_empty(value)
    if value is None:
        return None
    return value.translate(TEXT_SYMBOL_MAP).strip()

# clean_decimal() 負責將含千分位逗號或 MWh 單位的數字字串轉成小數字串。
def clean_decimal(value):
    """
    將數字字串整理成 DECIMAL 可接受的格式。
    """
    value = clean_empty(value)
    if value is None:
        return None
    value = value.translate(TEXT_SYMBOL_MAP)
    return value.replace(",", "").replace("MWh", "").replace("mWh", "").replace("mwh", "").strip()

# clean_date() 負責將日期字串轉成 YYYY-MM-DD。
def clean_date(value):
    """
    將日期字串轉成 YYYY-MM-DD。
    """
    value = clean_empty(value)
    if value is None:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()

# clean_year() 負責將 2026 或 2026.0 轉成 2026。
def clean_year(value):
    """
    將年份字串轉成整數年份。
    """
    value = clean_empty(value)
    if value is None:
        return None
    return int(float(value))

# clean_installed_capacity_kw() 負責移除 kW 並轉成純數字。
def clean_installed_capacity_kw(value):
    """
    將裝置容量字串轉成 kW 數值。
    """
    value = clean_empty(value)
    if value is None:
        return None
    value = value.translate(TEXT_SYMBOL_MAP)
    return value.replace(",", "").replace("kW", "").replace("KW", "").replace("kw", "").strip()

# split_generation_period() 負責將發電區間拆成開始日期與結束日期，支援 ~ 與 ～。
def split_generation_period(value):
    """
    將 2026-01-01~2026-03-31 拆成兩個日期。
    """
    value = clean_empty(value)
    if value is None:
        return None, None
    value = value.translate(TEXT_SYMBOL_MAP)
    start_date, end_date = value.split("~")
    return clean_date(start_date), clean_date(end_date)

# get_env_value() 負責先讀取環境變數，若沒有則從專案根目錄的 .env 讀取。
def get_env_value(key):
    """
    取得本機環境設定值。
    """
    value = os.getenv(key)
    if value is not None:
        return value
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line == "" or line.startswith("#"):
            continue
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return None

# get_mysql_config() 負責集中整理 MySQL 連線設定，方便所有程式共用同一份 .env 設定。
def get_mysql_config(include_database=True):
    """
    取得 MySQL 連線設定。
    """
    password = get_env_value("MYSQL_PASSWORD")
    if password is None:
        raise RuntimeError("請先設定 MYSQL_PASSWORD 環境變數或 .env，再執行資料庫連線程式")
    config = {
        "host": get_env_value("MYSQL_HOST") or DEFAULT_MYSQL_CONFIG["MYSQL_HOST"],
        "port": int(get_env_value("MYSQL_PORT") or DEFAULT_MYSQL_CONFIG["MYSQL_PORT"]),
        "user": get_env_value("MYSQL_USER") or DEFAULT_MYSQL_CONFIG["MYSQL_USER"],
        "password": password,
        "charset": get_env_value("MYSQL_CHARSET") or DEFAULT_MYSQL_CONFIG["MYSQL_CHARSET"],
    }
    if include_database:
        config["database"] = get_env_value("MYSQL_DATABASE") or DEFAULT_MYSQL_CONFIG["MYSQL_DATABASE"]
    return config

# get_connection() 負責建立 MySQL 連線。
# host、port、user、database、charset、password 會從環境變數或 .env 讀取。
# charset 使用 utf8mb4，才能完整支援中文公司名稱、地址等資料。
# 不要把真實密碼寫進程式碼或會提交到 Git 的檔案中。
def get_connection():
    """
    建立並回傳 MySQL 資料庫連線。

    連線設定會優先從環境變數讀取，若沒有設定，
    會再讀取專案根目錄中不提交到 Git 的 .env 檔。

    Returns:
        pymysql.connections.Connection: MySQL 資料庫連線物件
    """
    connection = pymysql.connect(**get_mysql_config(include_database=True))
    return connection

"""
08_check_raw_columns_v5.py

用途：
檢查 MySQL Raw Table 欄位是否與 CSV 欄位完整對應。

這支程式可以幫你確認：
1. trec_all_raw 是否保留 9 個主要 CSV 欄位
2. trec_direct_supply_raw 是否保留 7 個主要 CSV 欄位
3. trec_certificate_raw 是否保留 16 個主要 CSV 欄位
"""

from utils_v5 import get_connection


TABLES = [
    "trec_all_raw",
    "trec_direct_supply_raw",
    "trec_certificate_raw",
]


def main():
    """
    顯示三張 Raw Table 的欄位名稱與中文 COMMENT。
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        for table in TABLES:
            print("=" * 80)
            print(f"{table} 欄位檢查")
            print("=" * 80)

            cursor.execute(f"SHOW FULL COLUMNS FROM {table}")
            rows = cursor.fetchall()

            for row in rows:
                field = row[0]
                col_type = row[1]
                comment = row[8]
                print(f"{field:<30} {col_type:<20} {comment}")

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()

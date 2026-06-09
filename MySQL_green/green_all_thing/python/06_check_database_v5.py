"""
06_check_database_v5.py

用途：
檢查 MySQL_GREEN 主要資料表與 View 的筆數。
"""

from utils_v5 import get_connection


TABLES = [
    "trec_all_raw",
    "trec_direct_supply_raw",
    "trec_certificate_raw",
    "company_alias",
    "company",
    "facility",
    "energy_type",
    "supply_type",
    "transaction_fact",
    "certificate_fact",
    "vw_transaction_detail",
    "vw_sankey_data",
    "vw_certificate_detail",
]


def main():
    """
    主程式：逐一查詢主要資料表與 View 的資料筆數。
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        print("=" * 60)
        print("MySQL_GREEN 資料庫檢查")
        print("=" * 60)

        for table in TABLES:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"{table:<35} {count:>10} 筆")
            except Exception as exc:
                print(f"{table:<35} 檢查失敗：{exc}")

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()

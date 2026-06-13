from utils import clean_date, clean_decimal, clean_text, get_connection, print_separator

SOURCE_TABLE = "trec_direct_transaction_raw"
TARGET_TABLE = "trec_direct_transaction_clean"

# 這支程式負責將 trec_direct_transaction_raw 轉入 trec_direct_transaction_clean。
# 目前是 clean ETL 草稿，需等 clean table 建立後再執行。
def etl_trec_direct_transaction_clean():
    """
    將直轉供 raw table 清理後寫入 clean table。
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT
                raw_id,
                seller,
                facility_name,
                buyer,
                energy_type,
                supply_type,
                total_transfer_mwh,
                transaction_date,
                transaction_transfer_mwh,
                transaction_record_text
            FROM {SOURCE_TABLE}
            ORDER BY raw_id;
        """)
        rows = [
            (
                row[0],
                clean_text(row[1]),
                clean_text(row[2]),
                clean_text(row[3]),
                clean_text(row[4]),
                clean_text(row[5]),
                clean_decimal(row[6]),
                clean_date(row[7]),
                clean_decimal(row[8]),
                clean_text(row[9]),
            )
            for row in cursor.fetchall()
        ]
        insert_sql = f"""
            INSERT INTO {TARGET_TABLE} (
                raw_id,
                seller,
                facility_name,
                buyer,
                energy_type,
                supply_type,
                total_transfer_mwh,
                transaction_date,
                transaction_transfer_mwh,
                transaction_record_text
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print_separator()
        print(f"{TARGET_TABLE} ETL 完成")
        print(f"寫入筆數：{len(rows)}")
    except Exception as error:
        if conn is not None:
            conn.rollback()
        print_separator()
        print(f"{TARGET_TABLE} ETL 失敗")
        print(f"錯誤訊息：{error}")
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
            print("MySQL 連線已關閉")
            print_separator()

if __name__ == "__main__":
    etl_trec_direct_transaction_clean()

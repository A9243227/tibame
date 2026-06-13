from utils import get_connection, print_separator

TABLES = [
    "trec_direct_transaction_raw",
    "trec_self_generation_transaction_raw",
    "trec_issued_certificate_raw",
]

# 這支程式用來檢查三張 raw table 的匯入狀態。
# 目前會顯示每張表的資料筆數、最小 raw_id、最大 raw_id。
def check_raw_tables():
    """
    檢查三張 raw table 的資料筆數與 raw_id 範圍。
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        print_separator()
        for table in TABLES:
            cursor.execute(f"SELECT COUNT(*), MIN(raw_id), MAX(raw_id) FROM {table};")
            row_count, min_raw_id, max_raw_id = cursor.fetchone()
            print(f"資料表：{table}")
            print(f"資料筆數：{row_count}")
            print(f"raw_id 範圍：{min_raw_id} ~ {max_raw_id}")
            print_separator()
    except Exception as error:
        print_separator()
        print("raw table 檢查失敗")
        print(f"錯誤訊息：{error}")
        print_separator()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
            print("MySQL 連線已關閉")
            print_separator()

if __name__ == "__main__":
    check_raw_tables()

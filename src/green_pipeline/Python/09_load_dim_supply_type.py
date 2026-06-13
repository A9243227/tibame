from utils import clean_empty, get_connection, print_separator

TARGET_TABLE = "dim_supply_type"

# 這支程式負責從直轉供 clean table 收集供電種類，去重後寫入 dim_supply_type。
def load_dim_supply_type():
    """
    載入供電種類維度表。
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT supply_type FROM trec_direct_transaction_clean")
        supply_type_set = set()
        for row in cursor.fetchall():
            supply_type_name = clean_empty(row[0])
            if supply_type_name is not None:
                supply_type_set.add(supply_type_name)
        rows = [(supply_type_name,) for supply_type_name in sorted(supply_type_set)]
        insert_sql = f"""
            INSERT IGNORE INTO {TARGET_TABLE} (
                supply_type_name
            )
            VALUES (%s)
        """
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print_separator()
        print(f"{TARGET_TABLE} 載入完成")
        print(f"來源去重供電種類數：{len(rows)}")
        print(f"新增筆數：{cursor.rowcount}")
    except Exception as error:
        if conn is not None:
            conn.rollback()
        print_separator()
        print(f"{TARGET_TABLE} 載入失敗")
        print(f"錯誤訊息：{error}")
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
            print("MySQL 連線已關閉")
            print_separator()

if __name__ == "__main__":
    load_dim_supply_type()

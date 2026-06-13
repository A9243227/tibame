from utils import clean_empty, get_connection, print_separator

TARGET_TABLE = "dim_energy_type"

# 這支程式負責從 clean tables 收集能源類型，去重後寫入 dim_energy_type。
def load_dim_energy_type():
    """
    載入能源類型維度表。
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        source_queries = [
            "SELECT energy_type FROM trec_direct_transaction_clean",
            "SELECT energy_type FROM trec_self_generation_transaction_clean",
            "SELECT energy_type FROM trec_issued_certificate_clean",
        ]
        energy_type_set = set()
        for query in source_queries:
            cursor.execute(query)
            for row in cursor.fetchall():
                energy_type_name = clean_empty(row[0])
                if energy_type_name is not None:
                    energy_type_set.add(energy_type_name)
        rows = [(energy_type_name,) for energy_type_name in sorted(energy_type_set)]
        insert_sql = f"""
            INSERT IGNORE INTO {TARGET_TABLE} (
                energy_type_name
            )
            VALUES (%s)
        """
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print_separator()
        print(f"{TARGET_TABLE} 載入完成")
        print(f"來源去重能源類型數：{len(rows)}")
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
    load_dim_energy_type()

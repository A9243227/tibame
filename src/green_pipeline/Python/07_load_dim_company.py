from utils import clean_empty, get_connection, print_separator

TARGET_TABLE = "dim_company"

# 這支程式負責從 clean tables 收集公司與單位名稱，去重後寫入 dim_company。
# 角色欄位用來標記公司名稱曾出現在哪些來源欄位。
def load_dim_company():
    """
    載入公司維度表。
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        source_queries = [
            ("is_seller", "SELECT seller FROM trec_direct_transaction_clean"),
            ("is_buyer", "SELECT buyer FROM trec_direct_transaction_clean"),
            ("is_seller", "SELECT seller FROM trec_self_generation_transaction_clean"),
            ("is_buyer", "SELECT buyer FROM trec_self_generation_transaction_clean"),
            ("is_unit_name", "SELECT unit_name FROM trec_issued_certificate_clean"),
        ]
        company_map = {}
        for role, query in source_queries:
            cursor.execute(query)
            for row in cursor.fetchall():
                company_name = clean_empty(row[0])
                if company_name is not None:
                    company_map.setdefault(company_name, {
                        "is_seller": 0,
                        "is_buyer": 0,
                        "is_unit_name": 0,
                    })
                    company_map[company_name][role] = 1
        rows = [
            (
                company_name,
                roles["is_seller"],
                roles["is_buyer"],
                roles["is_unit_name"],
            )
            for company_name, roles in sorted(company_map.items())
        ]
        insert_sql = f"""
            INSERT IGNORE INTO {TARGET_TABLE} (
                company_name,
                is_seller,
                is_buyer,
                is_unit_name
            )
            VALUES (%s, %s, %s, %s)
        """
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print_separator()
        print(f"{TARGET_TABLE} 載入完成")
        print(f"來源去重公司數：{len(rows)}")
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
    load_dim_company()

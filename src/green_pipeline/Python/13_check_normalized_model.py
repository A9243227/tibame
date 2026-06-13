from utils import get_connection, print_separator

DIMENSION_TABLES = [
    ("dim_company", "公司維度表"),
    ("dim_energy_type", "能源類型維度表"),
    ("dim_supply_type", "供電種類維度表"),
    ("dim_facility", "發電設備維度表"),
]

FACT_AND_VIEW_PAIRS = [
    ("fact_transaction", "交易事實表", "vw_transaction_detail", "交易明細檢視表"),
    ("fact_issued_certificate", "已發放憑證事實表", "vw_issued_certificate_detail", "已發放憑證明細檢視表"),
]

TRANSACTION_SOURCE_LABELS = {
    "direct_transaction": "直轉供憑證成交",
    "self_generation_transaction": "自用發電設備憑證成交",
}

# 這支程式負責檢查 normalized model 的維度表、事實表與檢視表是否載入合理。
# 檢查內容只會讀取資料，不會修改任何資料表。
def fetch_count(cursor, table):
    """
    取得指定資料表或檢視表的資料筆數。
    """
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    return cursor.fetchone()[0]

def check_dimension_counts(cursor):
    """
    檢查各維度表筆數。
    """
    print("維度表筆數")
    for table_name, chinese_name in DIMENSION_TABLES:
        print(f"{table_name}：{chinese_name}：{fetch_count(cursor, table_name)} 筆")
    print_separator()

def check_fact_and_view_counts(cursor):
    """
    檢查事實表與對應 view 筆數是否一致。
    """
    print("事實表與檢視表筆數")
    for fact_table, fact_name, view_name, view_chinese_name in FACT_AND_VIEW_PAIRS:
        fact_count = fetch_count(cursor, fact_table)
        view_count = fetch_count(cursor, view_name)
        status = "OK" if fact_count == view_count else "不一致"
        print(f"{fact_table}：{fact_name}：{fact_count} 筆")
        print(f"{view_name}：{view_chinese_name}：{view_count} 筆")
        print(f"檢查結果：{status}")
    print_separator()

def check_fact_transaction_sources(cursor):
    """
    檢查交易事實表的來源分布。
    """
    print("fact_transaction：交易事實表 來源分布")
    cursor.execute("""
        SELECT transaction_source_type, COUNT(*)
        FROM fact_transaction
        GROUP BY transaction_source_type
        ORDER BY transaction_source_type
    """)
    for transaction_source_type, row_count in cursor.fetchall():
        chinese_name = TRANSACTION_SOURCE_LABELS.get(transaction_source_type, "未定義交易來源")
        print(f"{transaction_source_type}：{chinese_name}：{row_count} 筆")
    print_separator()

def check_issued_certificate_skipped_rows(cursor):
    """
    檢查已發放憑證 clean table 中因必要欄位缺漏而未進 fact 的 raw_id。
    """
    print("fact_issued_certificate：已發放憑證事實表 跳過資料檢查")
    cursor.execute("""
        SELECT raw_id
        FROM trec_issued_certificate_clean
        WHERE unit_name IS NULL OR facility_name IS NULL OR energy_type IS NULL
        ORDER BY raw_id
    """)
    skipped_raw_ids = [row[0] for row in cursor.fetchall()]
    print(f"必要欄位缺漏 raw_id：{skipped_raw_ids}")
    cursor.execute("SELECT COUNT(*) FROM trec_issued_certificate_clean")
    clean_count = cursor.fetchone()[0]
    fact_count = fetch_count(cursor, "fact_issued_certificate")
    expected_count = clean_count - len(skipped_raw_ids)
    status = "OK" if fact_count == expected_count else "不一致"
    print(f"clean table 筆數：{clean_count}")
    print(f"預期 fact 筆數：{expected_count}")
    print(f"實際 fact 筆數：{fact_count}")
    print(f"檢查結果：{status}")
    print_separator()

def check_normalized_model():
    """
    執行 normalized model 整體檢查。
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        print_separator()
        check_dimension_counts(cursor)
        check_fact_and_view_counts(cursor)
        check_fact_transaction_sources(cursor)
        check_issued_certificate_skipped_rows(cursor)
        print("normalized model 檢查完成")
        print_separator()
    except Exception as error:
        print_separator()
        print("normalized model 檢查失敗")
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
    check_normalized_model()

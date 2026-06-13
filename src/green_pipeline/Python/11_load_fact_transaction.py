from utils import clean_empty, get_connection, print_separator

TARGET_TABLE = "fact_transaction"

# 這支程式負責將前兩張交易 clean table 轉入 fact_transaction。
def build_facility_match_key(facility_name, energy_type_id):
    """
    建立交易資料用的發電設備判斷鍵。
    """
    return f"{facility_name}|{energy_type_id}|NO_ADDRESS"

def get_required(mapping, key, label):
    """
    取得維度主鍵，若找不到就停止載入。
    """
    value = mapping.get(key)
    if value is None:
        raise ValueError(f"找不到 {label}：{key}")
    return value

def load_fact_transaction():
    """
    載入交易事實表。
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT company_id, company_name FROM dim_company")
        company_map = {row[1]: row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT energy_type_id, energy_type_name FROM dim_energy_type")
        energy_type_map = {row[1]: row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT supply_type_id, supply_type_name FROM dim_supply_type")
        supply_type_map = {row[1]: row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT facility_id, facility_match_key FROM dim_facility")
        facility_map = {row[1]: row[0] for row in cursor.fetchall()}
        rows = []
        cursor.execute("""
            SELECT raw_id, seller, facility_name, buyer, energy_type, supply_type,
                   total_transfer_mwh, transaction_date, transaction_transfer_mwh,
                   transaction_record_text
            FROM trec_direct_transaction_clean
            ORDER BY raw_id
        """)
        for row in cursor.fetchall():
            energy_type_id = get_required(energy_type_map, clean_empty(row[4]), "能源類型")
            facility_key = build_facility_match_key(clean_empty(row[2]), energy_type_id)
            rows.append((
                "trec_direct_transaction_clean",
                row[0],
                "direct_transaction",
                get_required(company_map, clean_empty(row[1]), "出售單位"),
                get_required(company_map, clean_empty(row[3]), "購買者"),
                get_required(facility_map, facility_key, "發電設備"),
                energy_type_id,
                get_required(supply_type_map, clean_empty(row[5]), "供電種類"),
                None,
                row[7],
                row[8],
                row[6],
                row[9],
            ))
        cursor.execute("""
            SELECT raw_id, seller, facility_name, buyer, energy_type,
                   transfer_mwh, certificate_year, transfer_date
            FROM trec_self_generation_transaction_clean
            ORDER BY raw_id
        """)
        for row in cursor.fetchall():
            energy_type_id = get_required(energy_type_map, clean_empty(row[4]), "能源類型")
            facility_key = build_facility_match_key(clean_empty(row[2]), energy_type_id)
            rows.append((
                "trec_self_generation_transaction_clean",
                row[0],
                "self_generation_transaction",
                get_required(company_map, clean_empty(row[1]), "出售單位"),
                get_required(company_map, clean_empty(row[3]), "購買者"),
                get_required(facility_map, facility_key, "發電設備"),
                energy_type_id,
                None,
                row[6],
                row[7],
                row[5],
                None,
                None,
            ))
        insert_sql = f"""
            INSERT IGNORE INTO {TARGET_TABLE} (
                source_table,
                source_raw_id,
                transaction_source_type,
                seller_company_id,
                buyer_company_id,
                facility_id,
                energy_type_id,
                supply_type_id,
                certificate_year,
                transaction_date,
                transaction_mwh,
                total_transfer_mwh,
                transaction_record_text
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print_separator()
        print(f"{TARGET_TABLE} 載入完成")
        print(f"來源交易筆數：{len(rows)}")
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
    load_fact_transaction()

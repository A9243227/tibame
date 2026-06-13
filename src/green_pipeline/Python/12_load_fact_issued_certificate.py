from utils import clean_empty, get_connection, print_separator

TARGET_TABLE = "fact_issued_certificate"

# 這支程式負責將已發放憑證 clean table 轉入 fact_issued_certificate。
# 若來源資料缺少單位名稱、發電設備名稱或能源類型，會跳過並印出 raw_id 供追蹤。
def get_required(mapping, key, label):
    """
    取得維度主鍵，若找不到就停止載入。
    """
    value = mapping.get(key)
    if value is None:
        raise ValueError(f"找不到 {label}：{key}")
    return value

def load_fact_issued_certificate():
    """
    載入已發放憑證事實表。
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
        cursor.execute("SELECT facility_id, facility_name, energy_type_id, facility_address FROM dim_facility")
        facility_map = {(row[1], row[2], row[3]): row[0] for row in cursor.fetchall()}
        cursor.execute("""
            SELECT raw_id, unit_name, facility_name, energy_type, certificate_year,
                   transferred_mwh, remaining_mwh, facility_address, certificate_number,
                   trec_last_issue_date, generation_start_date, generation_end_date,
                   equipment_audit_report, power_generation_verification_report,
                   detail_transferred_mwh, detail_remaining_mwh
            FROM trec_issued_certificate_clean
            ORDER BY raw_id
        """)
        rows = []
        skipped_rows = []
        for row in cursor.fetchall():
            if clean_empty(row[1]) is None or clean_empty(row[2]) is None or clean_empty(row[3]) is None:
                skipped_rows.append(row[0])
                continue
            energy_type_id = get_required(energy_type_map, clean_empty(row[3]), "能源類型")
            facility_key = (clean_empty(row[2]), energy_type_id, clean_empty(row[7]))
            rows.append((
                row[0],
                get_required(company_map, clean_empty(row[1]), "單位名稱"),
                get_required(facility_map, facility_key, "發電設備"),
                energy_type_id,
                row[4],
                row[5],
                row[6],
                row[8],
                row[9],
                row[10],
                row[11],
                row[12],
                row[13],
                row[14],
                row[15],
            ))
        insert_sql = f"""
            INSERT IGNORE INTO {TARGET_TABLE} (
                source_raw_id,
                unit_company_id,
                facility_id,
                energy_type_id,
                certificate_year,
                transferred_mwh,
                remaining_mwh,
                certificate_number,
                trec_last_issue_date,
                generation_start_date,
                generation_end_date,
                equipment_audit_report,
                power_generation_verification_report,
                detail_transferred_mwh,
                detail_remaining_mwh
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print_separator()
        print(f"{TARGET_TABLE} 載入完成")
        print(f"來源已發放憑證筆數：{len(rows)}")
        print(f"新增筆數：{cursor.rowcount}")
        print(f"跳過必要欄位缺漏筆數：{len(skipped_rows)}")
        if skipped_rows:
            print(f"跳過 raw_id：{skipped_rows}")
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
    load_fact_issued_certificate()

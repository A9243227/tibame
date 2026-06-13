from utils import clean_date, clean_decimal, clean_installed_capacity_kw, clean_text, clean_year, split_generation_period, get_connection, print_separator

SOURCE_TABLE = "trec_issued_certificate_raw"
TARGET_TABLE = "trec_issued_certificate_clean"

# 這支程式負責將 trec_issued_certificate_raw 轉入 trec_issued_certificate_clean。
# 目前會清理年份、MWh 數字、裝置容量 kW，並將發電區間拆成起訖日期。
def etl_trec_issued_certificate_clean():
    """
    將已發放憑證 raw table 清理後寫入 clean table。
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT
                raw_id,
                unit_name,
                facility_name,
                energy_type,
                certificate_year,
                transferred_mwh,
                remaining_mwh,
                facility_address,
                installed_capacity,
                shared_company,
                certificate_number,
                trec_last_issue_date,
                generation_period,
                equipment_audit_report,
                power_generation_verification_report,
                detail_transferred_mwh,
                detail_remaining_mwh
            FROM {SOURCE_TABLE}
            ORDER BY raw_id;
        """)
        rows = []
        for row in cursor.fetchall():
            generation_start_date, generation_end_date = split_generation_period(row[12])
            rows.append((
                row[0],
                clean_text(row[1]),
                clean_text(row[2]),
                clean_text(row[3]),
                clean_year(row[4]),
                clean_decimal(row[5]),
                clean_decimal(row[6]),
                clean_text(row[7]),
                clean_installed_capacity_kw(row[8]),
                clean_text(row[9]),
                clean_text(row[10]),
                clean_date(row[11]),
                generation_start_date,
                generation_end_date,
                clean_text(row[13]),
                clean_text(row[14]),
                clean_decimal(row[15]),
                clean_decimal(row[16]),
            ))
        insert_sql = f"""
            INSERT INTO {TARGET_TABLE} (
                raw_id,
                unit_name,
                facility_name,
                energy_type,
                certificate_year,
                transferred_mwh,
                remaining_mwh,
                facility_address,
                installed_capacity_kw,
                shared_company,
                certificate_number,
                trec_last_issue_date,
                generation_start_date,
                generation_end_date,
                equipment_audit_report,
                power_generation_verification_report,
                detail_transferred_mwh,
                detail_remaining_mwh
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
    etl_trec_issued_certificate_clean()

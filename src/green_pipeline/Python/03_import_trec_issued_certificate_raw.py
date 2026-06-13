import csv
from pathlib import Path
from utils import get_connection, print_separator

CSV_PATH = Path(__file__).resolve().parent.parent / "data_raw" / "trec_issued_certificate_raw.csv"
TABLE_NAME = "trec_issued_certificate_raw"

# 這支程式負責匯入 trec_issued_certificate_raw.csv。
# raw_id 由 MySQL AUTO_INCREMENT 自動產生，Python 不需要寫入 raw_id。
# raw table 先保留 CSV 原始字串，數字與日期欄位會在後續 ETL 階段再轉型。
def import_trec_issued_certificate_raw():
    """
    將 data_raw/trec_issued_certificate_raw.csv 匯入 MySQL raw table。
    """
    conn = None
    cursor = None
    try:
        with open(CSV_PATH, mode="r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            rows = [
                (
                    row.get("單位名稱") or row["出售單位"],
                    row["發電設備"],
                    row["能源類型"],
                    row["憑證發放年份"],
                    row["已移轉量(MWh)"],
                    row["剩餘量(MWh)"],
                    row["發電設備地址"],
                    row["裝置總容量"],
                    row["發電設備共用單位"],
                    row["證書編號"],
                    row["T-REC最後憑證發放日期"],
                    row["發電區間"],
                    row["再生能源設備查核報告"],
                    row["再生能源發電量查證報告"],
                    row["詳情_已移轉量"],
                    row["詳情_剩餘量"],
                )
                for row in reader
            ]
        sql = f"""
            INSERT INTO {TABLE_NAME} (
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
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.executemany(sql, rows)
        conn.commit()
        print_separator()
        print(f"{TABLE_NAME} 匯入完成")
        print(f"匯入筆數：{len(rows)}")
    except Exception as error:
        if conn is not None:
            conn.rollback()
        print_separator()
        print(f"{TABLE_NAME} 匯入失敗")
        print(f"錯誤訊息：{error}")
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
            print("MySQL 連線已關閉")
            print_separator()

if __name__ == "__main__":
    import_trec_issued_certificate_raw()

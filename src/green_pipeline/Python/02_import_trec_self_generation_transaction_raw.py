import csv
from pathlib import Path
from utils import get_connection, print_separator

CSV_PATH = Path(__file__).resolve().parent.parent / "data_raw" / "trec_self_generation_transaction_raw.csv"
TABLE_NAME = "trec_self_generation_transaction_raw"

# 這支程式負責匯入 trec_self_generation_transaction_raw.csv。
# raw_id 由 MySQL AUTO_INCREMENT 自動產生，Python 不需要寫入 raw_id。
# raw table 先保留 CSV 原始字串，數字與日期欄位會在後續 ETL 階段再轉型。
def import_trec_self_generation_transaction_raw():
    """
    將 data_raw/trec_self_generation_transaction_raw.csv 匯入 MySQL raw table。
    """
    conn = None
    cursor = None
    try:
        with open(CSV_PATH, mode="r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            rows = [
                (
                    row["出售單位"],
                    row["發電設備"],
                    row["購買者"],
                    row["能源類型"],
                    row["移轉量(MWh)"],
                    row["憑證發放年份"],
                    row["移轉日期"],
                )
                for row in reader
            ]
        sql = f"""
            INSERT INTO {TABLE_NAME} (
                seller,
                facility_name,
                buyer,
                energy_type,
                transfer_mwh,
                certificate_year,
                transfer_date
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
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
    import_trec_self_generation_transaction_raw()

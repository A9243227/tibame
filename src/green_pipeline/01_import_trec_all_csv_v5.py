"""
01_import_trec_all_csv_v5.py

用途：
完整匯入 trec_all_raw.csv。

CSV 原始欄位：
出售單位、發電設備、購買者、能源類型、供電種類、
總移轉量(MWh)、成交日期、成交移轉量(MWh)、成交記錄原文

資料庫英文欄位：
seller、facility_name、buyer、energy_type、supply_type、
total_transfer_mwh、transaction_date、transaction_transfer_mwh、transaction_detail_raw
"""

from utils_v5 import (
    clean_date,
    clean_decimal,
    clean_empty,
    find_csv_file,
    get_connection,
    normalize_columns,
    read_csv_with_fallback,
)


COLUMN_MAPPING = {
    "出售單位": "seller",
    "發電設備": "facility_name",
    "購買者": "buyer",
    "能源類型": "energy_type",
    "供電種類": "supply_type",
    "總移轉量(MWh)": "total_transfer_mwh",
    "成交日期": "transaction_date",
    "成交移轉量(MWh)": "transaction_transfer_mwh",
    "成交記錄原文": "transaction_detail_raw",
}


def import_trec_all_raw():
    """
    讀取全部交易 CSV，完整保留 9 個原始欄位並寫入 MySQL。
    """
    file_path = find_csv_file(["trec_all_raw.csv", "trec_all.csv", "all_raw.csv"])

    if file_path is None:
        print("找不到 trec_all_raw.csv，略過全部交易資料匯入。")
        return

    df = read_csv_with_fallback(file_path)
    df = normalize_columns(df, COLUMN_MAPPING)

    insert_sql = """
        INSERT INTO trec_all_raw (
            seller,
            facility_name,
            buyer,
            energy_type,
            supply_type,
            total_transfer_mwh,
            transaction_date,
            transaction_transfer_mwh,
            transaction_detail_raw
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    rows = []

    for _, row in df.iterrows():
        rows.append((
            clean_empty(row.get("seller")),
            clean_empty(row.get("facility_name")),
            clean_empty(row.get("buyer")),
            clean_empty(row.get("energy_type")),
            clean_empty(row.get("supply_type")),
            clean_decimal(row.get("total_transfer_mwh")),
            clean_date(row.get("transaction_date")),
            clean_decimal(row.get("transaction_transfer_mwh")),
            clean_empty(row.get("transaction_detail_raw")),
        ))

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("TRUNCATE TABLE trec_all_raw")
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print(f"trec_all_raw 匯入完成：{len(rows)} 筆，欄位數：9 欄")

    except Exception as exc:
        conn.rollback()
        print("trec_all_raw 匯入失敗")
        raise exc

    finally:
        cursor.close()
        conn.close()


def main():
    """
    主程式：匯入全部直轉供憑證成交紀錄原始資料。
    """
    import_trec_all_raw()


if __name__ == "__main__":
    main()

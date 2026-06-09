"""
02_import_trec_direct_csv_v5.py

用途：
完整匯入 trec_direct_supply_raw.csv。

CSV 原始欄位：
出售單位、發電設備、購買者、能源類型、移轉量(MWh)、憑證發放年份、移轉日期

資料庫英文欄位：
seller、facility_name、buyer、energy_type、transfer_mwh、certificate_year、transfer_date
"""

from utils_v5 import (
    clean_date,
    clean_decimal,
    clean_empty,
    clean_int,
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
    "移轉量(MWh)": "transfer_mwh",
    "憑證發放年份": "certificate_year",
    "移轉日期": "transfer_date",
}


def import_trec_direct_supply_raw():
    """
    讀取直接供應 CSV，完整保留 7 個原始欄位並寫入 MySQL。
    """
    file_path = find_csv_file([
        "trec_direct_supply_raw.csv",
        "trec_direct_supply.csv",
        "direct_supply_raw.csv",
    ])

    if file_path is None:
        print("找不到 trec_direct_supply_raw.csv，略過直接供應資料匯入。")
        return

    df = read_csv_with_fallback(file_path)
    df = normalize_columns(df, COLUMN_MAPPING)

    insert_sql = """
        INSERT INTO trec_direct_supply_raw (
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

    rows = []

    for _, row in df.iterrows():
        rows.append((
            clean_empty(row.get("seller")),
            clean_empty(row.get("facility_name")),
            clean_empty(row.get("buyer")),
            clean_empty(row.get("energy_type")),
            clean_decimal(row.get("transfer_mwh")),
            clean_int(row.get("certificate_year")),
            clean_date(row.get("transfer_date")),
        ))

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("TRUNCATE TABLE trec_direct_supply_raw")
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print(f"trec_direct_supply_raw 匯入完成：{len(rows)} 筆，欄位數：7 欄")

    except Exception as exc:
        conn.rollback()
        print("trec_direct_supply_raw 匯入失敗")
        raise exc

    finally:
        cursor.close()
        conn.close()


def main():
    """
    主程式：自用發電設備憑證成交紀錄原始資料。
    """
    import_trec_direct_supply_raw()


if __name__ == "__main__":
    main()

"""
03_import_trec_certificate_csv_v5.py

用途：
完整匯入 trec_certificate_raw.csv。

CSV 原始欄位共 16 欄：
出售單位、發電設備、能源類型、憑證發放年份、已移轉量(MWh)、剩餘量(MWh)、
發電設備地址、裝置總容量、發電設備共用單位、證書編號、T-REC最後憑證發放日期、
發電區間、再生能源設備查核報告、再生能源發電量查證報告、詳情_已移轉量、詳情_剩餘量

資料庫欄位使用英文，中文說明寫在 SQL COMMENT。
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
    "能源類型": "energy_type",
    "憑證發放年份": "vintage_year",
    "已移轉量(MWh)": "transferred_mwh",
    "剩餘量(MWh)": "balance_mwh",
    "發電設備地址": "facility_location",
    "裝置總容量": "capacity",
    "發電設備共用單位": "co_owner",
    "證書編號": "certificate_no",
    "T-REC最後憑證發放日期": "trec_last_issue_date",
    "發電區間": "generation_period",
    "再生能源設備查核報告": "inspection_report",
    "再生能源發電量查證報告": "verification_report",
    "詳情_已移轉量": "detail_transferred_mwh",
    "詳情_剩餘量": "detail_available_mwh",

    # 兼容之前英文/混合欄位版本
    "Facility": "facility_name",
    "Location": "facility_location",
    "Certificate_no": "certificate_no",
    "TREC_Date": "trec_last_issue_date",
    "generation": "generation_period",
    "transferred": "transferred_mwh",
    "balance": "balance_mwh",
    "transferred_MWh": "detail_transferred_mwh",
    "Available_MWh": "detail_available_mwh",
}


def import_trec_certificate_raw():
    """
    讀取憑證 CSV，完整保留 16 個原始欄位並寫入 MySQL。
    """
    file_path = find_csv_file([
        "trec_certificate_raw.csv",
        "trec_certificate.csv",
        "certificate_raw.csv",
    ])

    if file_path is None:
        print("找不到 trec_certificate_raw.csv，略過憑證資料匯入。")
        return

    df = read_csv_with_fallback(file_path)
    df = normalize_columns(df, COLUMN_MAPPING)

    insert_sql = """
        INSERT INTO trec_certificate_raw (
            seller,
            facility_name,
            energy_type,
            vintage_year,
            transferred_mwh,
            balance_mwh,
            facility_location,
            capacity,
            co_owner,
            certificate_no,
            trec_last_issue_date,
            generation_period,
            inspection_report,
            verification_report,
            detail_transferred_mwh,
            detail_available_mwh
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    rows = []

    for _, row in df.iterrows():
        rows.append((
            clean_empty(row.get("seller")),
            clean_empty(row.get("facility_name")),
            clean_empty(row.get("energy_type")),
            clean_int(row.get("vintage_year")),
            clean_decimal(row.get("transferred_mwh")),
            clean_decimal(row.get("balance_mwh")),
            clean_empty(row.get("facility_location")),
            clean_empty(row.get("capacity")),
            clean_empty(row.get("co_owner")),
            clean_empty(row.get("certificate_no")),
            clean_date(row.get("trec_last_issue_date")),
            clean_empty(row.get("generation_period")),
            clean_empty(row.get("inspection_report")),
            clean_empty(row.get("verification_report")),
            clean_decimal(row.get("detail_transferred_mwh")),
            clean_decimal(row.get("detail_available_mwh")),
        ))

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("TRUNCATE TABLE trec_certificate_raw")
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print(f"trec_certificate_raw 匯入完成：{len(rows)} 筆，欄位數：16 欄")

    except Exception as exc:
        conn.rollback()
        print("trec_certificate_raw 匯入失敗")
        raise exc

    finally:
        cursor.close()
        conn.close()


def main():
    """
    主程式：匯入全部憑證資料。
    """
    import_trec_certificate_raw()


if __name__ == "__main__":
    main()

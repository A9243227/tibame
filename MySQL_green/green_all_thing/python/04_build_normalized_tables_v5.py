"""
04_build_normalized_tables_v5.py

用途：
將三張 Raw Table 轉成資料表與交易事實表。

Raw Table：
1. trec_all_raw：直轉供憑證成交紀錄原始資料，完整保留 9 欄 CSV
2. trec_direct_supply_raw：自用發電設備憑證成交紀錄原始資料，完整保留 7 欄 CSV
3. trec_certificate_raw：憑證原始資料，完整保留 16 欄 CSV

Fact Table：
1. transaction_fact：交易分析
2. certificate_fact：憑證分析
"""

from utils_v5 import get_connection


def insert_company_alias_seed(cursor):
    """
    建立公司別名初始資料。
    目前先把原始公司名稱視為標準公司名稱。
    """
    cursor.execute("""
        INSERT IGNORE INTO company_alias (alias_name, standard_company_name)
        SELECT company_name, company_name
        FROM (
            SELECT seller AS company_name FROM trec_all_raw
            UNION
            SELECT buyer AS company_name FROM trec_all_raw
            UNION
            SELECT seller AS company_name FROM trec_direct_supply_raw
            UNION
            SELECT buyer AS company_name FROM trec_direct_supply_raw
            UNION
            SELECT seller AS company_name FROM trec_certificate_raw
            UNION
            SELECT co_owner AS company_name FROM trec_certificate_raw
        ) src
        WHERE company_name IS NOT NULL
          AND TRIM(company_name) <> ''
    """)


def build_dimension_tables():
    """
    建立資料表：
    company_alias、company、facility、energy_type、supply_type
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        insert_company_alias_seed(cursor)

        # 公司資料
        cursor.execute("""
            INSERT IGNORE INTO company (company_name)
            SELECT DISTINCT standard_company_name
            FROM company_alias
            WHERE standard_company_name IS NOT NULL
              AND TRIM(standard_company_name) <> ''
        """)

        # 能源類型資料
        cursor.execute("""
            INSERT IGNORE INTO energy_type (energy_type_name)
            SELECT DISTINCT energy_type
            FROM (
                SELECT energy_type FROM trec_all_raw
                UNION
                SELECT energy_type FROM trec_direct_supply_raw
                UNION
                SELECT energy_type FROM trec_certificate_raw
            ) src
            WHERE energy_type IS NOT NULL
              AND TRIM(energy_type) <> ''
        """)

        # 供電種類資料，只從全部交易資料取得，因為直接供應 CSV 沒有供電種類欄位
        cursor.execute("""
            INSERT IGNORE INTO supply_type (supply_type_name)
            SELECT DISTINCT supply_type
            FROM trec_all_raw
            WHERE supply_type IS NOT NULL
              AND TRIM(supply_type) <> ''
        """)

        # 發電設備資料
        cursor.execute("""
            INSERT IGNORE INTO facility (facility_name)
            SELECT DISTINCT facility_name
            FROM (
                SELECT facility_name FROM trec_all_raw
                UNION
                SELECT facility_name FROM trec_direct_supply_raw
                UNION
                SELECT facility_name FROM trec_certificate_raw
            ) src
            WHERE facility_name IS NOT NULL
              AND TRIM(facility_name) <> ''
        """)

        # 使用憑證資料補充發電設備地址、裝置容量、設備所有者
        cursor.execute("""
            UPDATE facility f
            JOIN trec_certificate_raw r
              ON f.facility_name = r.facility_name
            LEFT JOIN company_alias ca
              ON r.seller = ca.alias_name
            LEFT JOIN company c
              ON ca.standard_company_name = c.company_name
            SET
                f.facility_location = COALESCE(f.facility_location, r.facility_location),
                f.capacity = COALESCE(f.capacity, r.capacity),
                f.owner_company_id = COALESCE(f.owner_company_id, c.company_id)
            WHERE r.facility_name IS NOT NULL
        """)

        conn.commit()
        print("資料表建立完成")

    except Exception as exc:
        conn.rollback()
        print("資料表建立失敗")
        raise exc

    finally:
        cursor.close()
        conn.close()


def build_transaction_fact():
    """
    建立 transaction_fact。

    來源：
    - trec_all_raw：使用 transaction_transfer_mwh，若空值則使用 total_transfer_mwh
    - trec_direct_supply_raw：使用 transfer_mwh
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        cursor.execute("TRUNCATE TABLE transaction_fact")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

        # 直轉供憑證成交紀錄原始資料
        cursor.execute("""
            INSERT INTO transaction_fact (
                seller_company_id,
                buyer_company_id,
                facility_id,
                energy_type_id,
                supply_type_id,
                transfer_mwh,
                transaction_date,
                source_table,
                raw_id
            )
            SELECT
                seller_company.company_id,
                buyer_company.company_id,
                f.facility_id,
                et.energy_type_id,
                st.supply_type_id,
                COALESCE(r.transaction_transfer_mwh, r.total_transfer_mwh),
                r.transaction_date,
                'trec_all_raw',
                r.raw_id
            FROM trec_all_raw r
            LEFT JOIN company_alias seller_alias
              ON r.seller = seller_alias.alias_name
            LEFT JOIN company seller_company
              ON seller_alias.standard_company_name = seller_company.company_name
            LEFT JOIN company_alias buyer_alias
              ON r.buyer = buyer_alias.alias_name
            LEFT JOIN company buyer_company
              ON buyer_alias.standard_company_name = buyer_company.company_name
            LEFT JOIN facility f
              ON r.facility_name = f.facility_name
            LEFT JOIN energy_type et
              ON r.energy_type = et.energy_type_name
            LEFT JOIN supply_type st
              ON r.supply_type = st.supply_type_name
        """)

        # 自用發電設備憑證成交紀錄原始資料
        cursor.execute("""
            INSERT INTO transaction_fact (
                seller_company_id,
                buyer_company_id,
                facility_id,
                energy_type_id,
                supply_type_id,
                transfer_mwh,
                transaction_date,
                source_table,
                raw_id
            )
            SELECT
                seller_company.company_id,
                buyer_company.company_id,
                f.facility_id,
                et.energy_type_id,
                NULL,
                r.transfer_mwh,
                r.transfer_date,
                'trec_direct_supply_raw',
                r.raw_id
            FROM trec_direct_supply_raw r
            LEFT JOIN company_alias seller_alias
              ON r.seller = seller_alias.alias_name
            LEFT JOIN company seller_company
              ON seller_alias.standard_company_name = seller_company.company_name
            LEFT JOIN company_alias buyer_alias
              ON r.buyer = buyer_alias.alias_name
            LEFT JOIN company buyer_company
              ON buyer_alias.standard_company_name = buyer_company.company_name
            LEFT JOIN facility f
              ON r.facility_name = f.facility_name
            LEFT JOIN energy_type et
              ON r.energy_type = et.energy_type_name
        """)

        conn.commit()
        print("transaction_fact 建立完成")

    except Exception as exc:
        conn.rollback()
        print("transaction_fact 建立失敗")
        raise exc

    finally:
        cursor.close()
        conn.close()


def build_certificate_fact():
    """
    建立 certificate_fact。

    來源：
    trec_certificate_raw
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        cursor.execute("TRUNCATE TABLE certificate_fact")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

        cursor.execute("""
            INSERT INTO certificate_fact (
                seller_company_id,
                co_owner_company_id,
                facility_id,
                energy_type_id,
                certificate_no,
                vintage_year,
                transferred_mwh,
                balance_mwh,
                trec_last_issue_date,
                generation_period,
                inspection_report,
                verification_report,
                raw_id
            )
            SELECT
                seller_company.company_id,
                co_owner_company.company_id,
                f.facility_id,
                et.energy_type_id,
                r.certificate_no,
                r.vintage_year,
                r.transferred_mwh,
                r.balance_mwh,
                r.trec_last_issue_date,
                r.generation_period,
                r.inspection_report,
                r.verification_report,
                r.raw_id
            FROM trec_certificate_raw r
            LEFT JOIN company_alias seller_alias
              ON r.seller = seller_alias.alias_name
            LEFT JOIN company seller_company
              ON seller_alias.standard_company_name = seller_company.company_name
            LEFT JOIN company_alias co_owner_alias
              ON r.co_owner = co_owner_alias.alias_name
            LEFT JOIN company co_owner_company
              ON co_owner_alias.standard_company_name = co_owner_company.company_name
            LEFT JOIN facility f
              ON r.facility_name = f.facility_name
            LEFT JOIN energy_type et
              ON r.energy_type = et.energy_type_name
        """)

        conn.commit()
        print("certificate_fact 建立完成")

    except Exception as exc:
        conn.rollback()
        print("certificate_fact 建立失敗")
        raise exc

    finally:
        cursor.close()
        conn.close()


def main():
    """
    主流程：
    1. 建立正規化資料表
    2. 建立直轉和自用交易事實表
    3. 建立憑證交易事實表
    """
    build_dimension_tables()
    build_transaction_fact()
    build_certificate_fact()

    print("=" * 60)
    print("MySQL_GREEN 正規化資料表建立完成")
    print("=" * 60)


if __name__ == "__main__":
    main()

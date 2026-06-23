from pathlib import Path
from google.cloud import bigquery

# 這支程式是 STAR0 的第 8 步。
# 目的：從 clean tables 與 dimension tables 建立兩張 fact tables。
# fact tables 儲存交易、憑證發放等可分析的事實資料，並用 id 關聯 dimension tables。

STAR0_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = STAR0_ROOT / ".env.gcp"

FACT_TABLES = [
    "fact_transaction",
    "fact_issued_certificate",
]

def print_separator():
    """
    印出分隔線，讓終端機輸出比較容易閱讀。
    """
    print("=" * 60)

def get_env_value(key):
    """
    從 BigQuery/STAR0/.env.gcp 讀取指定設定值。
    """
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line == "" or line.startswith("#"):
            continue
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return None

def get_config():
    """
    整理建立 fact tables 需要的設定。
    """
    project_id = get_env_value("GCP_PROJECT_ID")
    dataset_id = get_env_value("BQ_DATASET_ID")
    location = get_env_value("BQ_LOCATION")
    if not project_id:
        raise RuntimeError("請先在 BigQuery/STAR0/.env.gcp 設定 GCP_PROJECT_ID")
    if not dataset_id:
        raise RuntimeError("請先在 BigQuery/STAR0/.env.gcp 設定 BQ_DATASET_ID")
    if not location:
        raise RuntimeError("請先在 BigQuery/STAR0/.env.gcp 設定 BQ_LOCATION")
    return {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "location": location,
    }

def get_dataset_name(config):
    """
    回傳 BigQuery SQL 會使用的完整 dataset 名稱：project.dataset。
    """
    return f"{config['project_id']}.{config['dataset_id']}"

def build_fact_tables_sql(dataset_name):
    """
    建立兩張 fact tables 的 BigQuery SQL。

    BigQuery 不強制外鍵，所以這裡用 JOIN 把 dimension id 對回來。
    如果必要的維度資料找不到，該筆資料不會進入 fact table。
    """
    return f"""
    CREATE OR REPLACE TABLE `{dataset_name}.fact_transaction` AS
    WITH direct_transaction AS (
        SELECT
            'trec_direct_transaction_clean' AS source_table,
            direct.source_raw_id,
            direct.clean_id AS source_clean_id,
            'direct_transaction' AS transaction_source_type,
            seller.company_id AS seller_company_id,
            buyer.company_id AS buyer_company_id,
            facility.facility_id,
            energy.energy_type_id,
            supply.supply_type_id,
            CAST(NULL AS INT64) AS certificate_year,
            direct.transaction_date,
            direct.transaction_transfer_mwh AS transaction_mwh,
            direct.total_transfer_mwh
        FROM `{dataset_name}.trec_direct_transaction_clean` AS direct
        JOIN `{dataset_name}.dim_company` AS seller
            ON direct.seller = seller.company_name
        JOIN `{dataset_name}.dim_company` AS buyer
            ON direct.buyer = buyer.company_name
        JOIN `{dataset_name}.dim_energy_type` AS energy
            ON direct.energy_type = energy.energy_type_name
        JOIN `{dataset_name}.dim_supply_type` AS supply
            ON direct.supply_type = supply.supply_type_name
        JOIN `{dataset_name}.dim_facility` AS facility
            ON facility.facility_match_key = CONCAT(direct.facility_name, '|', CAST(energy.energy_type_id AS STRING), '|NO_ADDRESS')
        WHERE
            direct.seller IS NOT NULL
            AND direct.buyer IS NOT NULL
            AND direct.facility_name IS NOT NULL
            AND direct.energy_type IS NOT NULL
            AND direct.supply_type IS NOT NULL
            AND direct.transaction_date IS NOT NULL
            AND direct.transaction_transfer_mwh IS NOT NULL
    ),
    self_generation_transaction AS (
        SELECT
            'trec_self_generation_transaction_clean' AS source_table,
            self.source_raw_id,
            self.clean_id AS source_clean_id,
            'self_generation_transaction' AS transaction_source_type,
            seller.company_id AS seller_company_id,
            buyer.company_id AS buyer_company_id,
            facility.facility_id,
            energy.energy_type_id,
            CAST(NULL AS INT64) AS supply_type_id,
            self.certificate_year,
            self.transfer_date AS transaction_date,
            self.transfer_mwh AS transaction_mwh,
            CAST(NULL AS NUMERIC) AS total_transfer_mwh
        FROM `{dataset_name}.trec_self_generation_transaction_clean` AS self
        JOIN `{dataset_name}.dim_company` AS seller
            ON self.seller = seller.company_name
        JOIN `{dataset_name}.dim_company` AS buyer
            ON self.buyer = buyer.company_name
        JOIN `{dataset_name}.dim_energy_type` AS energy
            ON self.energy_type = energy.energy_type_name
        JOIN `{dataset_name}.dim_facility` AS facility
            ON facility.facility_match_key = CONCAT(self.facility_name, '|', CAST(energy.energy_type_id AS STRING), '|NO_ADDRESS')
        WHERE
            self.seller IS NOT NULL
            AND self.buyer IS NOT NULL
            AND self.facility_name IS NOT NULL
            AND self.energy_type IS NOT NULL
            AND self.transfer_date IS NOT NULL
            AND self.transfer_mwh IS NOT NULL
    ),
    transaction_union AS (
        SELECT * FROM direct_transaction
        UNION ALL
        SELECT * FROM self_generation_transaction
    )
    SELECT
        ROW_NUMBER() OVER (ORDER BY source_table, source_raw_id, source_clean_id) AS transaction_id,
        source_table,
        source_raw_id,
        source_clean_id,
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
        CURRENT_TIMESTAMP() AS created_at
    FROM transaction_union;

    CREATE OR REPLACE TABLE `{dataset_name}.fact_issued_certificate` AS
    WITH issued_with_dimension AS (
        SELECT
            issued.source_raw_id,
            issued.clean_id AS source_clean_id,
            company.company_id AS unit_company_id,
            facility.facility_id,
            energy.energy_type_id,
            issued.shared_company,
            issued.certificate_number,
            issued.trec_last_issue_date,
            issued.generation_start_date,
            issued.generation_end_date,
            issued.transferred_mwh,
            issued.remaining_mwh,
            issued.equipment_audit_report,
            issued.power_generation_verification_report
        FROM `{dataset_name}.trec_issued_certificate_clean` AS issued
        JOIN `{dataset_name}.dim_company` AS company
            ON issued.unit_name = company.company_name
        JOIN `{dataset_name}.dim_energy_type` AS energy
            ON issued.energy_type = energy.energy_type_name
        JOIN `{dataset_name}.dim_facility` AS facility
            ON facility.facility_match_key = CASE
                WHEN issued.facility_address IS NULL THEN CONCAT(issued.facility_name, '|', CAST(energy.energy_type_id AS STRING), '|NO_ADDRESS')
                ELSE CONCAT(issued.facility_name, '|', CAST(energy.energy_type_id AS STRING), '|', issued.facility_address)
            END
        WHERE
            issued.unit_name IS NOT NULL
            AND issued.facility_name IS NOT NULL
            AND issued.energy_type IS NOT NULL
    )
    SELECT
        ROW_NUMBER() OVER (ORDER BY source_raw_id, source_clean_id) AS issued_certificate_id,
        source_raw_id,
        source_clean_id,
        unit_company_id,
        facility_id,
        energy_type_id,
        shared_company,
        certificate_number,
        trec_last_issue_date,
        generation_start_date,
        generation_end_date,
        transferred_mwh,
        remaining_mwh,
        equipment_audit_report,
        power_generation_verification_report,
        CURRENT_TIMESTAMP() AS created_at
    FROM issued_with_dimension;
    """

def print_fact_table_counts(client, dataset_name):
    """
    印出兩張 fact tables 的筆數，確認 tables 已建立。
    """
    for table_name in FACT_TABLES:
        sql = f"SELECT COUNT(*) AS row_count FROM `{dataset_name}.{table_name}`"
        rows = list(client.query(sql).result())
        print(f"{table_name}：{rows[0]['row_count']} 筆")

def create_fact_tables():
    """
    主流程：建立兩張 fact tables。
    """
    config = get_config()
    dataset_name = get_dataset_name(config)
    client = bigquery.Client(
        project=config["project_id"],
        location=config["location"],
    )
    print_separator()
    print("開始建立 BigQuery fact tables")
    print(f"Dataset：{dataset_name}")
    sql = build_fact_tables_sql(dataset_name)
    client.query(sql).result()
    print_fact_table_counts(client, dataset_name)
    print_separator()
    print("兩張 fact tables 已建立完成")
    print_separator()

if __name__ == "__main__":
    create_fact_tables()

from pathlib import Path
from google.cloud import bigquery

# 這支程式是 STAR0 的第 4 步。
# 目的：從三張 raw tables 建立三張 clean tables。
# clean tables 會做基本欄位清理與型別轉換，但不建立 dimension / fact / view。

STAR0_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = STAR0_ROOT / ".env.gcp"

CLEAN_TABLES = [
    "trec_direct_transaction_clean",
    "trec_self_generation_transaction_clean",
    "trec_issued_certificate_clean",
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
    整理建立 clean tables 需要的設定。
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

def build_clean_tables_sql(dataset_name):
    """
    建立三張 clean tables 的 BigQuery SQL。

    這裡使用 TEMP FUNCTION 集中定義清理規則。
    TEMP FUNCTION 只在本次 SQL job 中有效，不會永久建立在 BigQuery 裡。
    """
    return f"""
    CREATE TEMP FUNCTION clean_empty(value STRING) AS (
        NULLIF(TRIM(value), '')
    );

    CREATE TEMP FUNCTION clean_text(value STRING) AS (
        NULLIF(TRIM(TRANSLATE(value, '（），。：；！？、／－～　', '(),.:;!?,/-~ ')), '')
    );

    CREATE TEMP FUNCTION clean_decimal(value STRING) AS (
        SAFE_CAST(
            TRIM(
                REPLACE(
                    REPLACE(
                        REPLACE(
                            REPLACE(TRANSLATE(value, '（），。：；！？、／－～　', '(),.:;!?,/-~ '), ',', ''),
                        'MWh', ''),
                    'mWh', ''),
                'mwh', '')
            ) AS NUMERIC
        )
    );

    CREATE TEMP FUNCTION clean_installed_capacity_kw(value STRING) AS (
        SAFE_CAST(
            TRIM(
                REPLACE(
                    REPLACE(
                        REPLACE(
                            REPLACE(TRANSLATE(value, '（），。：；！？、／－～　', '(),.:;!?,/-~ '), ',', ''),
                        'kW', ''),
                    'KW', ''),
                'kw', '')
            ) AS NUMERIC
        )
    );

    CREATE TEMP FUNCTION clean_date(value STRING) AS (
        SAFE.PARSE_DATE('%Y-%m-%d', clean_empty(value))
    );

    CREATE TEMP FUNCTION clean_year(value STRING) AS (
        SAFE_CAST(SAFE_CAST(clean_empty(value) AS FLOAT64) AS INT64)
    );

    CREATE OR REPLACE TABLE `{dataset_name}.trec_direct_transaction_clean` AS
    SELECT
        ROW_NUMBER() OVER (ORDER BY raw_id) AS clean_id,
        raw_id AS source_raw_id,
        clean_text(seller) AS seller,
        clean_text(facility_name) AS facility_name,
        clean_text(buyer) AS buyer,
        clean_text(energy_type) AS energy_type,
        clean_text(supply_type) AS supply_type,
        clean_decimal(total_transfer_mwh) AS total_transfer_mwh,
        clean_date(transaction_date) AS transaction_date,
        clean_decimal(transaction_transfer_mwh) AS transaction_transfer_mwh,
        CURRENT_TIMESTAMP() AS created_at
    FROM `{dataset_name}.trec_direct_transaction_raw`;

    CREATE OR REPLACE TABLE `{dataset_name}.trec_self_generation_transaction_clean` AS
    SELECT
        ROW_NUMBER() OVER (ORDER BY raw_id) AS clean_id,
        raw_id AS source_raw_id,
        clean_text(seller) AS seller,
        clean_text(facility_name) AS facility_name,
        clean_text(buyer) AS buyer,
        clean_text(energy_type) AS energy_type,
        clean_decimal(transfer_mwh) AS transfer_mwh,
        clean_year(certificate_year) AS certificate_year,
        clean_date(transfer_date) AS transfer_date,
        CURRENT_TIMESTAMP() AS created_at
    FROM `{dataset_name}.trec_self_generation_transaction_raw`;

    CREATE OR REPLACE TABLE `{dataset_name}.trec_issued_certificate_clean` AS
    WITH issued_base AS (
        SELECT
            raw_id AS source_raw_id,
            clean_text(unit_name) AS unit_name,
            clean_text(facility_name) AS facility_name,
            clean_text(energy_type) AS energy_type,
            clean_text(facility_address) AS facility_address,
            clean_installed_capacity_kw(installed_capacity) AS installed_capacity_kw,
            clean_text(shared_company) AS shared_company_text,
            clean_text(certificate_number) AS certificate_number,
            clean_date(trec_last_issue_date) AS trec_last_issue_date,
            clean_date(SPLIT(TRANSLATE(clean_empty(generation_period), '～', '~'), '~')[SAFE_OFFSET(0)]) AS generation_start_date,
            clean_date(SPLIT(TRANSLATE(clean_empty(generation_period), '～', '~'), '~')[SAFE_OFFSET(1)]) AS generation_end_date,
            clean_text(equipment_audit_report) AS equipment_audit_report,
            clean_text(power_generation_verification_report) AS power_generation_verification_report,
            clean_decimal(transferred_mwh) AS transferred_mwh,
            clean_decimal(remaining_mwh) AS remaining_mwh
        FROM `{dataset_name}.trec_issued_certificate_raw`
    ),
    issued_split AS (
        SELECT
            source_raw_id,
            unit_name,
            facility_name,
            energy_type,
            facility_address,
            installed_capacity_kw,
            clean_text(shared_company_item) AS shared_company,
            certificate_number,
            trec_last_issue_date,
            generation_start_date,
            generation_end_date,
            equipment_audit_report,
            power_generation_verification_report,
            transferred_mwh,
            remaining_mwh
        FROM issued_base
        CROSS JOIN UNNEST(
            CASE
                WHEN shared_company_text IS NULL THEN [CAST(NULL AS STRING)]
                ELSE SPLIT(shared_company_text, ',')
            END
        ) AS shared_company_item
    )
    SELECT
        ROW_NUMBER() OVER (ORDER BY source_raw_id, shared_company) AS clean_id,
        source_raw_id,
        unit_name,
        facility_name,
        energy_type,
        facility_address,
        installed_capacity_kw,
        shared_company,
        certificate_number,
        trec_last_issue_date,
        generation_start_date,
        generation_end_date,
        equipment_audit_report,
        power_generation_verification_report,
        transferred_mwh,
        remaining_mwh,
        CURRENT_TIMESTAMP() AS created_at
    FROM issued_split;
    """

def print_clean_table_counts(client, dataset_name):
    """
    印出三張 clean tables 的筆數，確認 clean tables 已建立。
    """
    for table_name in CLEAN_TABLES:
        sql = f"SELECT COUNT(*) AS row_count FROM `{dataset_name}.{table_name}`"
        rows = list(client.query(sql).result())
        print(f"{table_name}：{rows[0]['row_count']} 筆")

def create_clean_tables():
    """
    主流程：建立三張 clean tables。
    """
    config = get_config()
    dataset_name = get_dataset_name(config)
    client = bigquery.Client(
        project=config["project_id"],
        location=config["location"],
    )
    print_separator()
    print("開始建立 BigQuery clean tables")
    print(f"Dataset：{dataset_name}")
    sql = build_clean_tables_sql(dataset_name)
    client.query(sql).result()
    print_clean_table_counts(client, dataset_name)
    print_separator()
    print("三張 clean tables 已建立完成")
    print_separator()

if __name__ == "__main__":
    create_clean_tables()

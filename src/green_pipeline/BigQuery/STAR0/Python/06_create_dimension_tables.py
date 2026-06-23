from pathlib import Path
from google.cloud import bigquery

# 這支程式是 STAR0 的第 6 步。
# 目的：從三張 clean tables 建立四張 dimension tables。
# dimension tables 用來把重複出現的公司、能源類型、供電種類、發電設備整理成可重複關聯的主檔。

STAR0_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = STAR0_ROOT / ".env.gcp"

DIMENSION_TABLES = [
    "dim_company",
    "dim_energy_type",
    "dim_supply_type",
    "dim_facility",
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
    整理建立 dimension tables 需要的設定。
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

def build_dimension_tables_sql(dataset_name):
    """
    建立四張 dimension tables 的 BigQuery SQL。

    BigQuery 沒有像 MySQL AUTO_INCREMENT 一樣的自動流水號。
    這裡使用 ROW_NUMBER() 依名稱排序產生穩定的 id。
    """
    return f"""
    CREATE OR REPLACE TABLE `{dataset_name}.dim_company` AS
    WITH company_sources AS (
        SELECT seller AS company_name, TRUE AS is_seller, FALSE AS is_buyer, FALSE AS is_unit_name
        FROM `{dataset_name}.trec_direct_transaction_clean`
        WHERE seller IS NOT NULL
        UNION ALL
        SELECT buyer AS company_name, FALSE AS is_seller, TRUE AS is_buyer, FALSE AS is_unit_name
        FROM `{dataset_name}.trec_direct_transaction_clean`
        WHERE buyer IS NOT NULL
        UNION ALL
        SELECT seller AS company_name, TRUE AS is_seller, FALSE AS is_buyer, FALSE AS is_unit_name
        FROM `{dataset_name}.trec_self_generation_transaction_clean`
        WHERE seller IS NOT NULL
        UNION ALL
        SELECT buyer AS company_name, FALSE AS is_seller, TRUE AS is_buyer, FALSE AS is_unit_name
        FROM `{dataset_name}.trec_self_generation_transaction_clean`
        WHERE buyer IS NOT NULL
        UNION ALL
        SELECT unit_name AS company_name, FALSE AS is_seller, FALSE AS is_buyer, TRUE AS is_unit_name
        FROM `{dataset_name}.trec_issued_certificate_clean`
        WHERE unit_name IS NOT NULL
    ),
    company_grouped AS (
        SELECT
            company_name,
            LOGICAL_OR(is_seller) AS is_seller,
            LOGICAL_OR(is_buyer) AS is_buyer,
            LOGICAL_OR(is_unit_name) AS is_unit_name
        FROM company_sources
        GROUP BY company_name
    )
    SELECT
        ROW_NUMBER() OVER (ORDER BY company_name) AS company_id,
        company_name,
        is_seller,
        is_buyer,
        is_unit_name,
        CURRENT_TIMESTAMP() AS created_at
    FROM company_grouped;

    CREATE OR REPLACE TABLE `{dataset_name}.dim_energy_type` AS
    WITH energy_type_sources AS (
        SELECT energy_type AS energy_type_name
        FROM `{dataset_name}.trec_direct_transaction_clean`
        WHERE energy_type IS NOT NULL
        UNION DISTINCT
        SELECT energy_type AS energy_type_name
        FROM `{dataset_name}.trec_self_generation_transaction_clean`
        WHERE energy_type IS NOT NULL
        UNION DISTINCT
        SELECT energy_type AS energy_type_name
        FROM `{dataset_name}.trec_issued_certificate_clean`
        WHERE energy_type IS NOT NULL
    )
    SELECT
        ROW_NUMBER() OVER (ORDER BY energy_type_name) AS energy_type_id,
        energy_type_name,
        CURRENT_TIMESTAMP() AS created_at
    FROM energy_type_sources;

    CREATE OR REPLACE TABLE `{dataset_name}.dim_supply_type` AS
    WITH supply_type_sources AS (
        SELECT DISTINCT supply_type AS supply_type_name
        FROM `{dataset_name}.trec_direct_transaction_clean`
        WHERE supply_type IS NOT NULL
    )
    SELECT
        ROW_NUMBER() OVER (ORDER BY supply_type_name) AS supply_type_id,
        supply_type_name,
        CURRENT_TIMESTAMP() AS created_at
    FROM supply_type_sources;

    CREATE OR REPLACE TABLE `{dataset_name}.dim_facility` AS
    WITH facility_sources AS (
        SELECT
            facility_name,
            energy_type,
            CAST(NULL AS STRING) AS facility_address,
            CAST(NULL AS NUMERIC) AS installed_capacity_kw
        FROM `{dataset_name}.trec_direct_transaction_clean`
        WHERE facility_name IS NOT NULL AND energy_type IS NOT NULL
        UNION ALL
        SELECT
            facility_name,
            energy_type,
            CAST(NULL AS STRING) AS facility_address,
            CAST(NULL AS NUMERIC) AS installed_capacity_kw
        FROM `{dataset_name}.trec_self_generation_transaction_clean`
        WHERE facility_name IS NOT NULL AND energy_type IS NOT NULL
        UNION ALL
        SELECT
            facility_name,
            energy_type,
            facility_address,
            installed_capacity_kw
        FROM `{dataset_name}.trec_issued_certificate_clean`
        WHERE facility_name IS NOT NULL AND energy_type IS NOT NULL
    ),
    facility_with_energy_id AS (
        SELECT
            source.facility_name,
            energy.energy_type_id,
            source.facility_address,
            source.installed_capacity_kw,
            CASE
                WHEN source.facility_address IS NULL THEN CONCAT(source.facility_name, '|', CAST(energy.energy_type_id AS STRING), '|NO_ADDRESS')
                ELSE CONCAT(source.facility_name, '|', CAST(energy.energy_type_id AS STRING), '|', source.facility_address)
            END AS facility_match_key
        FROM facility_sources AS source
        JOIN `{dataset_name}.dim_energy_type` AS energy
            ON source.energy_type = energy.energy_type_name
    ),
    facility_grouped AS (
        SELECT
            facility_match_key,
            facility_name,
            energy_type_id,
            ARRAY_AGG(DISTINCT facility_address IGNORE NULLS ORDER BY facility_address LIMIT 1)[SAFE_OFFSET(0)] AS facility_address,
            ARRAY_AGG(DISTINCT installed_capacity_kw IGNORE NULLS ORDER BY installed_capacity_kw LIMIT 1)[SAFE_OFFSET(0)] AS installed_capacity_kw
        FROM facility_with_energy_id
        GROUP BY
            facility_match_key,
            facility_name,
            energy_type_id
    )
    SELECT
        ROW_NUMBER() OVER (ORDER BY facility_match_key) AS facility_id,
        facility_match_key,
        facility_name,
        facility_address,
        installed_capacity_kw,
        energy_type_id,
        CURRENT_TIMESTAMP() AS created_at
    FROM facility_grouped;
    """

def print_dimension_table_counts(client, dataset_name):
    """
    印出四張 dimension tables 的筆數，確認 tables 已建立。
    """
    for table_name in DIMENSION_TABLES:
        sql = f"SELECT COUNT(*) AS row_count FROM `{dataset_name}.{table_name}`"
        rows = list(client.query(sql).result())
        print(f"{table_name}：{rows[0]['row_count']} 筆")

def create_dimension_tables():
    """
    主流程：建立四張 dimension tables。
    """
    config = get_config()
    dataset_name = get_dataset_name(config)
    client = bigquery.Client(
        project=config["project_id"],
        location=config["location"],
    )
    print_separator()
    print("開始建立 BigQuery dimension tables")
    print(f"Dataset：{dataset_name}")
    sql = build_dimension_tables_sql(dataset_name)
    client.query(sql).result()
    print_dimension_table_counts(client, dataset_name)
    print_separator()
    print("四張 dimension tables 已建立完成")
    print_separator()

if __name__ == "__main__":
    create_dimension_tables()

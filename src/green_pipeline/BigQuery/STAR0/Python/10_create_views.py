from pathlib import Path
from google.cloud import bigquery

# 這支程式是 STAR0 的第 10 步。
# 目的：建立兩張閱讀用 views。
# views 會把 fact tables 裡的 dimension id 轉回中文可讀的公司、設備、能源與供電種類名稱。

STAR0_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = STAR0_ROOT / ".env.gcp"

VIEWS = [
    "vw_transaction_detail",
    "vw_issued_certificate_detail",
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
    整理建立 views 需要的設定。
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

def build_views_sql(dataset_name):
    """
    建立兩張 views 的 BigQuery SQL。

    vw_transaction_detail 不顯示地址與容量，因為兩張交易來源 clean table 沒有這兩個欄位。
    vw_issued_certificate_detail 會顯示地址、容量與 shared_company，因為已發放憑證來源本身有這些資訊。
    """
    return f"""
    CREATE OR REPLACE VIEW `{dataset_name}.vw_transaction_detail` AS
    SELECT
        fact.transaction_id AS transaction_id,
        fact.source_table AS source_table,
        fact.source_raw_id AS source_raw_id,
        fact.source_clean_id AS source_clean_id,
        fact.transaction_source_type AS transaction_source_type,
        CASE
            WHEN fact.transaction_source_type = 'direct_transaction' THEN '直轉供憑證成交'
            WHEN fact.transaction_source_type = 'self_generation_transaction' THEN '自用發電設備憑證成交'
            ELSE fact.transaction_source_type
        END AS transaction_source_name,
        seller.company_name AS seller_company_name,
        buyer.company_name AS buyer_company_name,
        facility.facility_name AS facility_name,
        energy.energy_type_name AS energy_type_name,
        supply.supply_type_name AS supply_type_name,
        fact.certificate_year AS certificate_year,
        fact.transaction_date AS transaction_date,
        fact.transaction_mwh AS transaction_mwh,
        fact.total_transfer_mwh AS total_transfer_mwh,
        fact.created_at AS created_at
    FROM `{dataset_name}.fact_transaction` AS fact
    JOIN `{dataset_name}.dim_company` AS seller
        ON fact.seller_company_id = seller.company_id
    JOIN `{dataset_name}.dim_company` AS buyer
        ON fact.buyer_company_id = buyer.company_id
    JOIN `{dataset_name}.dim_facility` AS facility
        ON fact.facility_id = facility.facility_id
    JOIN `{dataset_name}.dim_energy_type` AS energy
        ON fact.energy_type_id = energy.energy_type_id
    LEFT JOIN `{dataset_name}.dim_supply_type` AS supply
        ON fact.supply_type_id = supply.supply_type_id;

    CREATE OR REPLACE VIEW `{dataset_name}.vw_issued_certificate_detail` AS
    SELECT
        fact.issued_certificate_id AS issued_certificate_id,
        fact.source_raw_id AS source_raw_id,
        fact.source_clean_id AS source_clean_id,
        company.company_name AS unit_company_name,
        facility.facility_name AS facility_name,
        facility.facility_address AS facility_address,
        facility.installed_capacity_kw AS installed_capacity_kw,
        energy.energy_type_name AS energy_type_name,
        fact.shared_company AS shared_company,
        fact.certificate_number AS certificate_number,
        fact.trec_last_issue_date AS trec_last_issue_date,
        fact.generation_start_date AS generation_start_date,
        fact.generation_end_date AS generation_end_date,
        fact.transferred_mwh AS transferred_mwh,
        fact.remaining_mwh AS remaining_mwh,
        fact.equipment_audit_report AS equipment_audit_report,
        fact.power_generation_verification_report AS power_generation_verification_report,
        fact.created_at AS created_at
    FROM `{dataset_name}.fact_issued_certificate` AS fact
    JOIN `{dataset_name}.dim_company` AS company
        ON fact.unit_company_id = company.company_id
    JOIN `{dataset_name}.dim_facility` AS facility
        ON fact.facility_id = facility.facility_id
    JOIN `{dataset_name}.dim_energy_type` AS energy
        ON fact.energy_type_id = energy.energy_type_id;
    """

def print_view_counts(client, dataset_name):
    """
    印出兩張 views 的筆數，確認 views 可以查詢。
    """
    for view_name in VIEWS:
        sql = f"SELECT COUNT(*) AS row_count FROM `{dataset_name}.{view_name}`"
        rows = list(client.query(sql).result())
        print(f"{view_name}：{rows[0]['row_count']} 筆")

def create_views():
    """
    主流程：建立兩張 views。
    """
    config = get_config()
    dataset_name = get_dataset_name(config)
    client = bigquery.Client(
        project=config["project_id"],
        location=config["location"],
    )
    print_separator()
    print("開始建立 BigQuery views")
    print(f"Dataset：{dataset_name}")
    sql = build_views_sql(dataset_name)
    client.query(sql).result()
    print_view_counts(client, dataset_name)
    print_separator()
    print("兩張 views 已建立完成")
    print_separator()

if __name__ == "__main__":
    create_views()

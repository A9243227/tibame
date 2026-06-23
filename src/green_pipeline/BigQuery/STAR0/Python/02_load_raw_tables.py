from pathlib import Path
from google.cloud import bigquery

# 這支程式是 STAR0 的第 2 步。
# 目的：從 GCS CSV 建立三張 BigQuery raw tables。
# raw tables 只保存原始資料字串，型別轉換會留到後面的 clean tables。

STAR0_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = STAR0_ROOT / ".env.gcp"

SOURCE_TABLES = [
    {
        "label": "直轉供憑證成交",
        "table_name": "trec_direct_transaction_raw",
        "uri_env_key": "GCS_DIRECT_TRANSACTION_URI",
        "schema": [
            bigquery.SchemaField("seller", "STRING"),
            bigquery.SchemaField("facility_name", "STRING"),
            bigquery.SchemaField("buyer", "STRING"),
            bigquery.SchemaField("energy_type", "STRING"),
            bigquery.SchemaField("supply_type", "STRING"),
            bigquery.SchemaField("total_transfer_mwh", "STRING"),
            bigquery.SchemaField("transaction_date", "STRING"),
            bigquery.SchemaField("transaction_transfer_mwh", "STRING"),
        ],
        "order_columns": [
            "seller",
            "facility_name",
            "buyer",
            "energy_type",
            "supply_type",
            "transaction_date",
            "transaction_transfer_mwh",
        ],
    },
    {
        "label": "自用發電設備憑證成交",
        "table_name": "trec_self_generation_transaction_raw",
        "uri_env_key": "GCS_SELF_GENERATION_TRANSACTION_URI",
        "schema": [
            bigquery.SchemaField("seller", "STRING"),
            bigquery.SchemaField("facility_name", "STRING"),
            bigquery.SchemaField("buyer", "STRING"),
            bigquery.SchemaField("energy_type", "STRING"),
            bigquery.SchemaField("transfer_mwh", "STRING"),
            bigquery.SchemaField("certificate_year", "STRING"),
            bigquery.SchemaField("transfer_date", "STRING"),
        ],
        "order_columns": [
            "seller",
            "facility_name",
            "buyer",
            "energy_type",
            "certificate_year",
            "transfer_date",
        ],
    },
    {
        "label": "已發放憑證",
        "table_name": "trec_issued_certificate_raw",
        "uri_env_key": "GCS_ISSUED_CERTIFICATE_URI",
        "schema": [
            bigquery.SchemaField("unit_name", "STRING"),
            bigquery.SchemaField("facility_name", "STRING"),
            bigquery.SchemaField("energy_type", "STRING"),
            bigquery.SchemaField("facility_address", "STRING"),
            bigquery.SchemaField("installed_capacity", "STRING"),
            bigquery.SchemaField("shared_company", "STRING"),
            bigquery.SchemaField("certificate_number", "STRING"),
            bigquery.SchemaField("trec_last_issue_date", "STRING"),
            bigquery.SchemaField("generation_period", "STRING"),
            bigquery.SchemaField("equipment_audit_report", "STRING"),
            bigquery.SchemaField("power_generation_verification_report", "STRING"),
            bigquery.SchemaField("transferred_mwh", "STRING"),
            bigquery.SchemaField("remaining_mwh", "STRING"),
        ],
        "order_columns": [
            "unit_name",
            "facility_name",
            "energy_type",
            "certificate_number",
            "generation_period",
        ],
    },
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
    整理 BigQuery 與 GCS 載入流程需要的設定。
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

def get_required_env_value(key):
    """
    讀取必要設定；如果沒有設定就停止流程。
    """
    value = get_env_value(key)
    if not value:
        raise RuntimeError(f"請先在 BigQuery/STAR0/.env.gcp 設定 {key}")
    return value

def get_required_env_values(key):
    """
    讀取必要設定，並支援用逗號分隔多個 GCS URI。
    """
    value = get_required_env_value(key)
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise RuntimeError(f"請先在 BigQuery/STAR0/.env.gcp 設定 {key}")
    return values

def load_csv_to_staging_table(client, dataset_name, source_config):
    """
    將 GCS CSV 載入暫存 staging table。

    staging table 的用途：
    - 先接住 CSV 原始欄位
    - 下一步再補 raw_id 建成正式 raw table
    """
    table_name = source_config["table_name"]
    source_uris = get_required_env_values(source_config["uri_env_key"])
    staging_table_id = f"{dataset_name}._staging_{table_name}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        schema=source_config["schema"],
        skip_leading_rows=1,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        field_delimiter=",",
        encoding="UTF-8",
        allow_quoted_newlines=True,
        quote_character='"',
        max_bad_records=0,
    )
    print_separator()
    print(f"開始載入來源：{source_config['label']}")
    print("GCS URI：")
    for source_uri in source_uris:
        print(f"- {source_uri}")
    print(f"Staging table：{staging_table_id}")
    load_job = client.load_table_from_uri(
        source_uris,
        staging_table_id,
        job_config=job_config,
    )
    load_job.result()
    print(f"staging table 載入完成：{staging_table_id}")

def create_raw_table_from_staging(client, dataset_name, source_config):
    """
    從 staging table 建立正式 raw table，並產生 raw_id。

    BigQuery 沒有 MySQL AUTO_INCREMENT。
    這裡用 ROW_NUMBER() 產生 raw_id，讓每筆 raw data 有追蹤用的流水號。
    """
    table_name = source_config["table_name"]
    staging_table_id = f"{dataset_name}._staging_{table_name}"
    raw_table_id = f"{dataset_name}.{table_name}"
    columns = [field.name for field in source_config["schema"]]
    order_columns = ", ".join([f"`{column}`" for column in source_config["order_columns"]])
    select_columns = ",\n        ".join([f"`{column}`" for column in columns])
    create_sql = f"""
    CREATE OR REPLACE TABLE `{raw_table_id}` AS
    SELECT
        ROW_NUMBER() OVER (ORDER BY {order_columns}) AS raw_id,
        {select_columns},
        CURRENT_TIMESTAMP() AS created_at
    FROM `{staging_table_id}`;
    """
    client.query(create_sql).result()
    client.delete_table(staging_table_id, not_found_ok=True)
    table = client.get_table(raw_table_id)
    print(f"已建立 raw table：{raw_table_id}，筆數：{table.num_rows}")

def load_one_raw_table(client, dataset_name, source_config):
    """
    載入單一來源：
    1. GCS CSV -> staging table
    2. staging table -> raw table
    3. 刪除 staging table
    """
    load_csv_to_staging_table(client, dataset_name, source_config)
    create_raw_table_from_staging(client, dataset_name, source_config)

def load_raw_tables():
    """
    主流程：依序建立三張 raw tables。
    """
    config = get_config()
    dataset_name = get_dataset_name(config)
    client = bigquery.Client(
        project=config["project_id"],
        location=config["location"],
    )
    print_separator()
    print("開始建立 BigQuery raw tables")
    print(f"Dataset：{dataset_name}")
    for source_config in SOURCE_TABLES:
        load_one_raw_table(client, dataset_name, source_config)
    print_separator()
    print("三張 raw tables 已建立完成")
    print_separator()

if __name__ == "__main__":
    load_raw_tables()

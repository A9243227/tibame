from pathlib import Path
from google.cloud import bigquery

# 這支程式是 STAR0 的第 3 步。
# 目的：檢查 Step 02 建好的三張 raw tables。
# 這支程式只讀取資料，不會建立、修改或刪除任何 table。

STAR0_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = STAR0_ROOT / ".env.gcp"

RAW_TABLES = [
    {
        "table_name": "trec_direct_transaction_raw",
        "label": "直轉供憑證成交 raw table",
    },
    {
        "table_name": "trec_self_generation_transaction_raw",
        "label": "自用發電設備憑證成交 raw table",
    },
    {
        "table_name": "trec_issued_certificate_raw",
        "label": "已發放憑證 raw table",
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
    整理查詢 BigQuery raw tables 需要的設定。
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

def print_table_count(client, table_id):
    """
    查詢並印出 raw table 筆數。
    """
    sql = f"SELECT COUNT(*) AS row_count FROM `{table_id}`"
    rows = list(client.query(sql).result())
    print(f"筆數：{rows[0]['row_count']}")

def print_table_schema(client, table_id):
    """
    印出 raw table 欄位名稱與型別。
    """
    table = client.get_table(table_id)
    print("欄位：")
    for index, field in enumerate(table.schema, start=1):
        print(f"{index}. {field.name} ({field.field_type})")

def print_sample_rows(client, table_id):
    """
    印出 raw table 前 5 筆資料。

    SELECT * 只用於檢查少量資料。
    正式分析時應明確指定欄位，避免讀取不必要資料。
    """
    sql = f"""
    SELECT *
    FROM `{table_id}`
    ORDER BY raw_id
    LIMIT 5
    """
    rows = list(client.query(sql).result())
    print("前 5 筆資料：")
    for row in rows:
        print(dict(row))

def check_one_raw_table(client, dataset_name, table_config):
    """
    檢查單一 raw table。
    """
    table_id = f"{dataset_name}.{table_config['table_name']}"
    print_separator()
    print(table_config["label"])
    print(f"Table：{table_id}")
    print_table_count(client, table_id)
    print_table_schema(client, table_id)
    print_sample_rows(client, table_id)

def check_raw_tables():
    """
    主流程：依序檢查三張 raw tables。
    """
    config = get_config()
    dataset_name = get_dataset_name(config)
    client = bigquery.Client(
        project=config["project_id"],
        location=config["location"],
    )
    print_separator()
    print("開始檢查 BigQuery raw tables")
    print(f"Dataset：{dataset_name}")
    for table_config in RAW_TABLES:
        check_one_raw_table(client, dataset_name, table_config)
    print_separator()
    print("三張 raw tables 檢查完成")
    print_separator()

if __name__ == "__main__":
    check_raw_tables()

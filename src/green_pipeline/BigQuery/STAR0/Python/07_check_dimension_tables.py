from pathlib import Path
from google.cloud import bigquery

# 這支程式是 STAR0 的第 7 步。
# 目的：檢查第 6 步建立的四張 dimension tables。
# 這支程式只查詢資料，不會建立、修改或刪除任何 table。

STAR0_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = STAR0_ROOT / ".env.gcp"

DIMENSION_TABLES = [
    {
        "table_name": "dim_company",
        "label": "公司維度表",
        "unique_column": "company_name",
        "sample_order_column": "company_id",
    },
    {
        "table_name": "dim_energy_type",
        "label": "能源類型維度表",
        "unique_column": "energy_type_name",
        "sample_order_column": "energy_type_id",
    },
    {
        "table_name": "dim_supply_type",
        "label": "供電種類維度表",
        "unique_column": "supply_type_name",
        "sample_order_column": "supply_type_id",
    },
    {
        "table_name": "dim_facility",
        "label": "發電設備維度表",
        "unique_column": "facility_match_key",
        "sample_order_column": "facility_id",
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
    整理查詢 dimension tables 需要的設定。
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

def get_table_count(client, table_id):
    """
    查詢 table 筆數。
    """
    sql = f"SELECT COUNT(*) AS row_count FROM `{table_id}`"
    rows = list(client.query(sql).result())
    return rows[0]["row_count"]

def print_table_schema(client, table_id):
    """
    印出 table 欄位名稱與型別。
    """
    table = client.get_table(table_id)
    print("欄位：")
    for index, field in enumerate(table.schema, start=1):
        print(f"{index}. {field.name} ({field.field_type})")

def get_duplicate_count(client, table_id, unique_column):
    """
    檢查應該唯一的欄位是否有重複值。
    """
    sql = f"""
    SELECT COUNT(*) AS duplicate_count
    FROM (
        SELECT `{unique_column}`
        FROM `{table_id}`
        GROUP BY `{unique_column}`
        HAVING COUNT(*) > 1
    )
    """
    rows = list(client.query(sql).result())
    return rows[0]["duplicate_count"]

def print_sample_rows(client, table_id, order_column):
    """
    印出 table 前 5 筆資料。
    """
    sql = f"""
    SELECT *
    FROM `{table_id}`
    ORDER BY `{order_column}`
    LIMIT 5
    """
    rows = list(client.query(sql).result())
    print("前 5 筆資料：")
    for row in rows:
        print(dict(row))

def print_facility_energy_type_check(client, dataset_name):
    """
    檢查 dim_facility 的 energy_type_id 是否都能對應到 dim_energy_type。
    """
    sql = f"""
    SELECT COUNT(*) AS missing_count
    FROM `{dataset_name}.dim_facility` AS facility
    LEFT JOIN `{dataset_name}.dim_energy_type` AS energy
        ON facility.energy_type_id = energy.energy_type_id
    WHERE energy.energy_type_id IS NULL
    """
    rows = list(client.query(sql).result())
    missing_count = rows[0]["missing_count"]
    if missing_count == 0:
        print("dim_facility 能源類型對應檢查：通過")
    else:
        print(f"dim_facility 能源類型對應檢查：不通過，找不到能源類型的筆數 {missing_count}")

def print_company_role_counts(client, dataset_name):
    """
    印出 dim_company 中各角色的公司數量。
    """
    sql = f"""
    SELECT
        COUNTIF(is_seller) AS seller_count,
        COUNTIF(is_buyer) AS buyer_count,
        COUNTIF(is_unit_name) AS unit_name_count
    FROM `{dataset_name}.dim_company`
    """
    rows = list(client.query(sql).result())
    row = rows[0]
    print("公司角色統計：")
    print(f"is_seller / 出售單位：{row['seller_count']}")
    print(f"is_buyer / 購買者：{row['buyer_count']}")
    print(f"is_unit_name / 單位名稱：{row['unit_name_count']}")

def check_one_dimension_table(client, dataset_name, table_config):
    """
    檢查單一 dimension table。
    """
    table_id = f"{dataset_name}.{table_config['table_name']}"
    print_separator()
    print(table_config["label"])
    print(f"Table：{table_id}")
    row_count = get_table_count(client, table_id)
    duplicate_count = get_duplicate_count(client, table_id, table_config["unique_column"])
    print(f"筆數：{row_count}")
    if duplicate_count == 0:
        print(f"唯一值檢查：通過，{table_config['unique_column']} 沒有重複")
    else:
        print(f"唯一值檢查：不通過，{table_config['unique_column']} 重複數 {duplicate_count}")
    print_table_schema(client, table_id)
    print_sample_rows(client, table_id, table_config["sample_order_column"])

def check_dimension_tables():
    """
    主流程：依序檢查四張 dimension tables。
    """
    config = get_config()
    dataset_name = get_dataset_name(config)
    client = bigquery.Client(
        project=config["project_id"],
        location=config["location"],
    )
    print_separator()
    print("開始檢查 BigQuery dimension tables")
    print(f"Dataset：{dataset_name}")
    for table_config in DIMENSION_TABLES:
        check_one_dimension_table(client, dataset_name, table_config)
    print_separator()
    print_company_role_counts(client, dataset_name)
    print_facility_energy_type_check(client, dataset_name)
    print_separator()
    print("四張 dimension tables 檢查完成")
    print_separator()

if __name__ == "__main__":
    check_dimension_tables()

from pathlib import Path
from google.cloud import bigquery

# 這支程式是 STAR0 的第 11 步。
# 目的：檢查第 10 步建立的兩張 views。
# 這支程式只查詢資料，不會建立、修改或刪除任何 table 或 view。

STAR0_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = STAR0_ROOT / ".env.gcp"

VIEWS = [
    {
        "view_name": "vw_transaction_detail",
        "label": "交易明細檢視表",
        "fact_table_name": "fact_transaction",
        "id_column": "transaction_id",
    },
    {
        "view_name": "vw_issued_certificate_detail",
        "label": "已發放憑證明細檢視表",
        "fact_table_name": "fact_issued_certificate",
        "id_column": "issued_certificate_id",
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
    整理查詢 views 需要的設定。
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

def get_count(client, object_id):
    """
    查詢 table 或 view 筆數。
    """
    sql = f"SELECT COUNT(*) AS row_count FROM `{object_id}`"
    rows = list(client.query(sql).result())
    return rows[0]["row_count"]

def print_schema(client, object_id):
    """
    印出 view 欄位名稱與型別。
    """
    view = client.get_table(object_id)
    print("欄位：")
    for index, field in enumerate(view.schema, start=1):
        print(f"{index}. {field.name} ({field.field_type})")

def print_sample_rows(client, object_id, id_column):
    """
    印出 view 前 5 筆資料。
    """
    sql = f"""
    SELECT *
    FROM `{object_id}`
    ORDER BY `{id_column}`
    LIMIT 5
    """
    rows = list(client.query(sql).result())
    print("前 5 筆資料：")
    for row in rows:
        print(dict(row))

def print_count_check(client, dataset_name, view_config):
    """
    比對 view 與對應 fact table 的筆數。
    """
    fact_id = f"{dataset_name}.{view_config['fact_table_name']}"
    view_id = f"{dataset_name}.{view_config['view_name']}"
    fact_count = get_count(client, fact_id)
    view_count = get_count(client, view_id)
    print(f"fact table 筆數：{fact_count}")
    print(f"view 筆數：{view_count}")
    if fact_count == view_count:
        print("筆數檢查：通過，view 與 fact table 一致")
    else:
        print("筆數檢查：不通過，請檢查 view JOIN 是否造成資料遺失或重複")

def print_transaction_source_check(client, dataset_name):
    """
    檢查交易明細 view 的來源分布。
    """
    sql = f"""
    SELECT
        transaction_source_type,
        transaction_source_name,
        COUNT(*) AS row_count
    FROM `{dataset_name}.vw_transaction_detail`
    GROUP BY
        transaction_source_type,
        transaction_source_name
    ORDER BY transaction_source_type
    """
    rows = list(client.query(sql).result())
    print("交易明細來源分布：")
    for row in rows:
        print(f"{row['transaction_source_type']} / {row['transaction_source_name']}：{row['row_count']} 筆")

def check_one_view(client, dataset_name, view_config):
    """
    檢查單一 view。
    """
    view_id = f"{dataset_name}.{view_config['view_name']}"
    print_separator()
    print(view_config["label"])
    print(f"View：{view_id}")
    print_count_check(client, dataset_name, view_config)
    print_schema(client, view_id)
    print_sample_rows(client, view_id, view_config["id_column"])

def check_views():
    """
    主流程：依序檢查兩張 views。
    """
    config = get_config()
    dataset_name = get_dataset_name(config)
    client = bigquery.Client(
        project=config["project_id"],
        location=config["location"],
    )
    print_separator()
    print("開始檢查 BigQuery views")
    print(f"Dataset：{dataset_name}")
    for view_config in VIEWS:
        check_one_view(client, dataset_name, view_config)
    print_separator()
    print_transaction_source_check(client, dataset_name)
    print_separator()
    print("兩張 views 檢查完成")
    print_separator()

if __name__ == "__main__":
    check_views()

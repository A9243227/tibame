from pathlib import Path
from google.cloud import bigquery

# 這支程式是 STAR0 的第 5 步。
# 目的：檢查組員建立好的三張 clean tables。
# 這支程式只讀取資料，不會建立、修改或刪除任何 table。

STAR0_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = STAR0_ROOT / ".env.gcp"

CLEAN_TABLES = [
    {
        "raw_table_name": "trec_direct_transaction_raw",
        "clean_table_name": "trec_direct_transaction_clean",
        "label": "直轉供憑證成交 clean table",
        "count_rule": "same_count",
    },
    {
        "raw_table_name": "trec_self_generation_transaction_raw",
        "clean_table_name": "trec_self_generation_transaction_clean",
        "label": "自用發電設備憑證成交 clean table",
        "count_rule": "same_count",
    },
    {
        "raw_table_name": "trec_issued_certificate_raw",
        "clean_table_name": "trec_issued_certificate_clean",
        "label": "已發放憑證 clean table",
        "count_rule": "shared_company_split",
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
    整理查詢 BigQuery clean tables 需要的設定。
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

def get_table_field_names(client, table_id):
    """
    取得 table 欄位名稱清單。
    """
    table = client.get_table(table_id)
    return [field.name for field in table.schema]

def get_distinct_source_raw_id_count(client, table_id):
    """
    計算 clean table 中 source_raw_id 的不重複數量。
    """
    sql = f"SELECT COUNT(DISTINCT source_raw_id) AS source_count FROM `{table_id}`"
    rows = list(client.query(sql).result())
    return rows[0]["source_count"]

def print_count_check(client, dataset_name, table_config):
    """
    印出 raw table 與 clean table 筆數，並依照資料表規則檢查。
    """
    raw_table_id = f"{dataset_name}.{table_config['raw_table_name']}"
    clean_table_id = f"{dataset_name}.{table_config['clean_table_name']}"
    raw_count = get_table_count(client, raw_table_id)
    clean_count = get_table_count(client, clean_table_id)
    clean_fields = get_table_field_names(client, clean_table_id)
    print(f"raw table 筆數：{raw_count}")
    print(f"clean table 筆數：{clean_count}")
    if "source_raw_id" not in clean_fields:
        print("來源追蹤檢查：缺少 source_raw_id，請補上來源 raw table 對應欄位")
        return
    source_count = get_distinct_source_raw_id_count(client, clean_table_id)
    print(f"source_raw_id 不重複數：{source_count}")
    if table_config["count_rule"] == "same_count":
        if raw_count == clean_count and raw_count == source_count:
            print("筆數檢查：通過，raw / clean / source_raw_id 數量一致")
        else:
            print("筆數檢查：不通過，這張表應該 raw / clean / source_raw_id 數量一致")
    else:
        if clean_count >= raw_count and source_count <= raw_count:
            print("筆數檢查：通過，clean 可因 shared_company 拆分而多於 raw")
        else:
            print("筆數檢查：不通過，請確認 shared_company 拆分與 source_raw_id 對應")

def print_table_schema(client, table_id):
    """
    印出 clean table 欄位名稱與型別。
    """
    table = client.get_table(table_id)
    print("欄位：")
    for index, field in enumerate(table.schema, start=1):
        print(f"{index}. {field.name} ({field.field_type})")

def get_sample_order_column(client, table_id):
    """
    找出抽樣查詢要使用的排序欄位。

    如果 clean table 有 source_raw_id，就優先用 source_raw_id。
    如果沒有 source_raw_id，但有 raw_id，就用 raw_id。
    如果都沒有，就使用 table 的第一個欄位，例如 direct_clean_id。
    """
    table = client.get_table(table_id)
    field_names = [field.name for field in table.schema]
    if "source_raw_id" in field_names:
        return "source_raw_id"
    if "raw_id" in field_names:
        return "raw_id"
    return field_names[0]

def print_sample_rows(client, table_id):
    """
    印出 clean table 前 5 筆資料。

    SELECT * 只用於檢查少量資料。
    正式分析時應明確指定欄位，避免讀取不必要資料。
    """
    order_column = get_sample_order_column(client, table_id)
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

def check_one_clean_table(client, dataset_name, table_config):
    """
    檢查單一 clean table。
    """
    clean_table_id = f"{dataset_name}.{table_config['clean_table_name']}"
    print_separator()
    print(table_config["label"])
    print(f"Table：{clean_table_id}")
    print_count_check(client, dataset_name, table_config)
    print_table_schema(client, clean_table_id)
    print_sample_rows(client, clean_table_id)

def check_clean_tables():
    """
    主流程：依序檢查三張 clean tables。
    """
    config = get_config()
    dataset_name = get_dataset_name(config)
    client = bigquery.Client(
        project=config["project_id"],
        location=config["location"],
    )
    print_separator()
    print("開始檢查 BigQuery clean tables")
    print(f"Dataset：{dataset_name}")
    for table_config in CLEAN_TABLES:
        check_one_clean_table(client, dataset_name, table_config)
    print_separator()
    print("三張 clean tables 檢查完成")
    print_separator()

if __name__ == "__main__":
    check_clean_tables()

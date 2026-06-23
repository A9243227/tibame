from pathlib import Path
from google.cloud import bigquery

# 這支程式是 STAR0 的第 9 步。
# 目的：檢查第 8 步建立的兩張 fact tables。
# 這支程式只查詢資料，不會建立、修改或刪除任何 table。

STAR0_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = STAR0_ROOT / ".env.gcp"

FACT_TABLES = [
    {
        "table_name": "fact_transaction",
        "label": "交易事實表",
        "id_column": "transaction_id",
    },
    {
        "table_name": "fact_issued_certificate",
        "label": "已發放憑證事實表",
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
    整理查詢 fact tables 需要的設定。
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

def print_sample_rows(client, table_id, id_column):
    """
    印出 fact table 前 5 筆資料。
    """
    sql = f"""
    SELECT *
    FROM `{table_id}`
    ORDER BY `{id_column}`
    LIMIT 5
    """
    rows = list(client.query(sql).result())
    print("前 5 筆資料：")
    for row in rows:
        print(dict(row))

def print_transaction_source_check(client, dataset_name):
    """
    檢查 fact_transaction 中兩種交易來源的筆數。
    """
    sql = f"""
    SELECT
        transaction_source_type,
        COUNT(*) AS row_count
    FROM `{dataset_name}.fact_transaction`
    GROUP BY transaction_source_type
    ORDER BY transaction_source_type
    """
    rows = list(client.query(sql).result())
    print("fact_transaction 來源分布：")
    for row in rows:
        print(f"{row['transaction_source_type']}：{row['row_count']} 筆")

def print_fact_count_check(client, dataset_name):
    """
    比對 clean table 與 fact table 筆數。
    """
    sql = f"""
    SELECT
        (SELECT COUNT(*) FROM `{dataset_name}.trec_direct_transaction_clean`) AS direct_clean_count,
        (SELECT COUNT(*) FROM `{dataset_name}.trec_self_generation_transaction_clean`) AS self_clean_count,
        (SELECT COUNT(*) FROM `{dataset_name}.fact_transaction`) AS fact_transaction_count,
        (SELECT COUNT(*) FROM `{dataset_name}.trec_issued_certificate_clean`) AS issued_clean_count,
        (SELECT COUNT(*) FROM `{dataset_name}.fact_issued_certificate`) AS fact_issued_count
    """
    rows = list(client.query(sql).result())
    row = rows[0]
    expected_transaction_count = row["direct_clean_count"] + row["self_clean_count"]
    print("clean / fact 筆數比對：")
    print(f"交易 clean 合計：{expected_transaction_count}")
    print(f"fact_transaction：{row['fact_transaction_count']}")
    if expected_transaction_count == row["fact_transaction_count"]:
        print("交易 fact 筆數檢查：通過")
    else:
        print("交易 fact 筆數檢查：不通過，請檢查維度對應是否缺漏")
    print(f"已發放憑證 clean：{row['issued_clean_count']}")
    print(f"fact_issued_certificate：{row['fact_issued_count']}")
    if row["issued_clean_count"] == row["fact_issued_count"]:
        print("已發放憑證 fact 筆數檢查：通過")
    else:
        print("已發放憑證 fact 筆數檢查：不通過，可能有必要欄位缺漏或維度對應缺漏")

def print_missing_dimension_check(client, dataset_name):
    """
    檢查 fact tables 的主要 dimension id 是否為 NULL。
    """
    checks = [
        ("fact_transaction.seller_company_id", "fact_transaction", "seller_company_id"),
        ("fact_transaction.buyer_company_id", "fact_transaction", "buyer_company_id"),
        ("fact_transaction.facility_id", "fact_transaction", "facility_id"),
        ("fact_transaction.energy_type_id", "fact_transaction", "energy_type_id"),
        ("fact_issued_certificate.unit_company_id", "fact_issued_certificate", "unit_company_id"),
        ("fact_issued_certificate.facility_id", "fact_issued_certificate", "facility_id"),
        ("fact_issued_certificate.energy_type_id", "fact_issued_certificate", "energy_type_id"),
    ]
    print("dimension id 空值檢查：")
    for label, table_name, column_name in checks:
        sql = f"SELECT COUNT(*) AS missing_count FROM `{dataset_name}.{table_name}` WHERE `{column_name}` IS NULL"
        rows = list(client.query(sql).result())
        print(f"{label}：{rows[0]['missing_count']}")

def check_one_fact_table(client, dataset_name, table_config):
    """
    檢查單一 fact table。
    """
    table_id = f"{dataset_name}.{table_config['table_name']}"
    print_separator()
    print(table_config["label"])
    print(f"Table：{table_id}")
    print(f"筆數：{get_table_count(client, table_id)}")
    print_table_schema(client, table_id)
    print_sample_rows(client, table_id, table_config["id_column"])

def check_fact_tables():
    """
    主流程：依序檢查兩張 fact tables。
    """
    config = get_config()
    dataset_name = get_dataset_name(config)
    client = bigquery.Client(
        project=config["project_id"],
        location=config["location"],
    )
    print_separator()
    print("開始檢查 BigQuery fact tables")
    print(f"Dataset：{dataset_name}")
    for table_config in FACT_TABLES:
        check_one_fact_table(client, dataset_name, table_config)
    print_separator()
    print_transaction_source_check(client, dataset_name)
    print_fact_count_check(client, dataset_name)
    print_missing_dimension_check(client, dataset_name)
    print_separator()
    print("兩張 fact tables 檢查完成")
    print_separator()

if __name__ == "__main__":
    check_fact_tables()

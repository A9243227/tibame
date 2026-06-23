from pathlib import Path
from google.cloud import bigquery

# 這支程式是 STAR0 的第 0 步。
# 目的：只建立 BigQuery dataset，不做其他事情。
# 不會讀取 GCS，也不會建立 raw / clean / dim / fact / view tables。

# STAR0_ROOT 指向 BigQuery/STAR0 資料夾。
# 這樣設定檔可以放在 BigQuery/STAR0/.env.gcp，和前面完整 pipeline 分開。
STAR0_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = STAR0_ROOT / ".env.gcp"

# 如果 .env.gcp 沒有填 BQ_DATASET_ID 或 BQ_LOCATION，就使用這兩個預設值。
# GCP_PROJECT_ID 沒有預設值，因為每個人的 GCP 專案不同，必須明確填寫。
DEFAULT_DATASET_ID = "Rong_test"
DEFAULT_LOCATION = "asia-east1"

def print_separator():
    """
    印出分隔線，讓終端機輸出比較容易閱讀。
    """
    print("=" * 60)

def get_env_value(key):
    """
    從 BigQuery/STAR0/.env.gcp 讀取指定設定值。

    .env.gcp 格式範例：
    GCP_PROJECT_ID=my-project
    BQ_DATASET_ID=Rong_test
    BQ_LOCATION=asia-east1
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
    集中整理建立 dataset 需要的設定。

    必要設定：
    - GCP_PROJECT_ID：GCP 專案 ID

    可用預設值：
    - BQ_DATASET_ID：預設 Rong_test
    - BQ_LOCATION：預設 asia-east1
    """
    project_id = get_env_value("GCP_PROJECT_ID")
    if not project_id:
        raise RuntimeError("請先在 BigQuery/STAR0/.env.gcp 設定 GCP_PROJECT_ID")
    return {
        "project_id": project_id,
        "dataset_id": get_env_value("BQ_DATASET_ID") or DEFAULT_DATASET_ID,
        "location": get_env_value("BQ_LOCATION") or DEFAULT_LOCATION,
    }

def create_dataset():
    """
    建立 BigQuery dataset。

    exists_ok=True 表示：
    - 如果 dataset 還不存在，就建立它。
    - 如果 dataset 已經存在，不會報錯，會直接視為成功。
    """
    config = get_config()
    client = bigquery.Client(
        project=config["project_id"],
        location=config["location"],
    )
    dataset_id = f"{config['project_id']}.{config['dataset_id']}"
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = config["location"]
    client.create_dataset(dataset, exists_ok=True)
    print_separator()
    print("BigQuery dataset 已確認")
    print(f"Project ID：{config['project_id']}")
    print(f"Dataset ID：{config['dataset_id']}")
    print(f"Location：{config['location']}")
    print_separator()

if __name__ == "__main__":
    create_dataset()

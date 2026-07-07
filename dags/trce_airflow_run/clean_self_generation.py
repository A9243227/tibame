import datetime
from airflow import DAG
# 🌟 修正 1：將導入路徑改為 Airflow 3.x 標準的 airflow.sdk
from airflow.sdk import Asset
from airflow.operators.python import PythonOperator
from bq_cleaner import BigQueryETLPipeline

default_args = {
    'owner': 'data_engineer',
    'depends_on_past': False,
    'retries': 2,
    'retry_delay': datetime.timedelta(minutes=5),
}

PROJECT_ID = "tibametopics"
DATASET_ID = "trec_data"

def build_generation_transaction():
    pipeline = BigQueryETLPipeline(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID
        )
    pipeline.clean_self_generation_transaction()

asset_self_raw = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/trec_self_generation_transaction_raw")

# 🌟 修正 2：補上完整的三段式 BigQuery URI 格式
asset_self_gen = Asset(
    uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/trec_self_generation_transaction_clean"
)

with DAG(
    dag_id='stage1_1nf_self_generation_transaction',
    default_args=default_args,
    description='第一階段：1NF 資料清洗層',
    schedule=[asset_self_raw], 
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    tags=['trec', 'stage1', '1nf'],
) as dag_s1:
    
    PythonOperator(
        task_id='1NF_clean_self_generation',
        python_callable=build_generation_transaction,
        outlets=[asset_self_gen]
    )
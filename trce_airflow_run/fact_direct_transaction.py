import datetime
from airflow import DAG
# 🌟 修正 1：改用 Airflow 3.x 正確的導入路徑
from airflow.sdk import Asset
from airflow.operators.python import PythonOperator
from bq_cleaner import BigQueryETLPipeline

default_args = {
    'owner': 'data_engineer',
    'depends_on_past': False,         
    'retries': 2,                     
    'retry_delay': datetime.timedelta(minutes=5), 
}

# 1. 實例化管線物件
PROJECT_ID = "tibametopics"
DATASET_ID = "trec_data"

def build_fact_direct_transaction():
    pipeline = BigQueryETLPipeline(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID
        )
    pipeline.build_fact_direct_transaction()

# 🌟 修正 2：改為符合 Airflow 3.x 驗證器的三段式標準 URI 格式
asset_dim_company = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/dim_company")
asset_dim_energy = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/dim_energy_type")
asset_dim_facility = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/dim_facility")
asset_dim_supply = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/dim_supply_type")

asset_fact_direct = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/fact_direct_transaction")

with DAG(
    dag_id='stage3_2nf_fact_direct_transaction',       
    default_args=default_args,
    description='第三階段：2NF 星狀模型事實表建立',
    schedule=[asset_dim_company, asset_dim_energy, asset_dim_facility, asset_dim_supply],                  
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    tags=['trec', 'stage3', '2nf'],
) as dag_s3:

    task_build_fact_direct_transaction = PythonOperator(
        task_id='2NF_build_fact_direct_transaction',
        python_callable=build_fact_direct_transaction,
        outlets=[asset_fact_direct]
    )
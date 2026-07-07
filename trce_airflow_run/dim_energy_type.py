import datetime
from airflow import DAG
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

def build_dim_energy_type():
    pipeline = BigQueryETLPipeline(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID
        )
    pipeline.build_dim_energy_type()

# 💡 上游 1NF 訊號 (三段式標準格式)
asset_self_gen = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/trec_self_generation_transaction_clean")
asset_direct_tx = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/trec_direct_transaction_clean")
asset_issued_cert = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/trec_issued_certificate_clean")

# 💡 本身 2NF 訊號
asset_dim_energy = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/dim_energy_type")

with DAG(
    dag_id='stage2_2nf_dim_energy_type',
    default_args=default_args,
    description='第二階段：2NF 維度表建立',
    schedule=[asset_self_gen, asset_direct_tx, asset_issued_cert],                  
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    tags=['trec', 'stage2', '2nf'],
) as dag_s2:

    PythonOperator(
        task_id='2NF_build_dim_energy_type',
        python_callable=build_dim_energy_type,
        outlets=[asset_dim_energy]
    )
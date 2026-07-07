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

def build_fact_issued_certificate():
    pipeline = BigQueryETLPipeline(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID
        )
    pipeline.build_fact_issued_certificate()

# 💡 監聽的 4 個 2NF 維度表完成訊號 (三段式標準格式)
asset_dim_company = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/dim_company")
asset_dim_energy = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/dim_energy_type")
asset_dim_facility = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/dim_facility")
asset_dim_supply = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/dim_supply_type")

asset_fact_issued = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/fact_issued_certificate")


with DAG(
    dag_id='stage3_2nf_fact_issued_certificate',       
    default_args=default_args,
    description='第三階段：2NF 星狀模型事實表建立',
    schedule=[asset_dim_company, asset_dim_energy, asset_dim_facility, asset_dim_supply],                  
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    tags=['trec', 'stage3', '2nf'],
) as dag_s3:

    task_build_fact_issued_certificate = PythonOperator(
        task_id='2NF_build_fact_issued_certificate',
        python_callable=build_fact_issued_certificate,
        outlets=[asset_fact_issued]
    )
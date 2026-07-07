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

def clean_issued_certificate():
    pipeline = BigQueryETLPipeline(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID
        )
    pipeline.clean_issued_certificate()

asset_fact_issued = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/trec_issued_certificate_raw")

# 🌟 修正 2：補上完整的三段式 BigQuery URI 格式
asset_issued_cert = Asset(
    uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/trec_issued_certificate_clean"
)

with DAG(
    dag_id='stage1_1nf_issued_certificate',
    default_args=default_args,
    description='第一階段：1NF 資料清洗層',
    schedule=[asset_fact_issued], 
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    tags=['trec', 'stage1', '1nf'],
) as dag_s3:
    
    PythonOperator(
        task_id='1NF_clean_issued_certificate',
        python_callable=clean_issued_certificate,
        outlets=[asset_issued_cert]
    )
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

def clean_direct_transaction():
    pipeline = BigQueryETLPipeline(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID
        )
    pipeline.clean_direct_transaction()

asset_self_gen = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/trec_direct_transaction_raw")

asset_direct_tx = Asset(
    uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/trec_direct_transaction_clean"
)

with DAG(
    dag_id='stage1_1nf_direct_transaction',
    default_args=default_args,
    description='第一階段：1NF 資料清洗層',
    schedule=[asset_self_gen],
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    tags=['trec', 'stage1', '1nf'],
) as dag_s2:

    PythonOperator(
        task_id='1NF_clean_direct_transaction',
        python_callable=clean_direct_transaction,
        outlets=[asset_direct_tx]
    )
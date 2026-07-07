from datetime import datetime, timedelta
from airflow import DAG
from airflow.sdk import Asset
from airflow.operators.python import PythonOperator
# 💡 從你的任務腳本中引用對應的 def
from nick_gcs_to_bigquery_tasks import import_direct_transaction_to_bq

PROJECT_ID = "tibametopics"
DATASET_ID = "trec_data"
BQ_DATASET = "gcstobq_airflowtest"

direct_raw_asset = Asset(f"bq://{PROJECT_ID}.{BQ_DATASET}.direct_raw")

asset_self_gen = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/trec_direct_transaction_raw")

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2026, 1, 1),  # 可依需求調整起始日期
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    dag_id='gcs_to_bq_direct_transaction',
    default_args=default_args,
    description='任務一：從 GCS 讀取直購綠電交易資料並寫入 BigQuery (帶說明)',
    schedule=[direct_raw_asset],
    catchup=False,
    tags=['gcs', 'bigquery', 'raw'],
) as dag:

    PythonOperator(
        task_id='import_direct_transaction',
        python_callable=import_direct_transaction_to_bq,
        outlets=[asset_self_gen]
    )
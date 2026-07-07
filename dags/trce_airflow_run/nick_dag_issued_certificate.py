from datetime import datetime, timedelta
from airflow import DAG
from airflow.sdk import Asset
from airflow.operators.python import PythonOperator
# 💡 從你的任務腳本中引用對應的 def
from nick_gcs_to_bigquery_tasks import import_issued_certificate_to_bq
from common_config import GCS_BUCKET

PROJECT_ID = "tibametopics"
DATASET_ID = "trec_data"
BQ_DATASET = "gcstobq_airflowtest"

rec_gcs_asset = Asset(f"gcs://{GCS_BUCKET}/rec_raw_data/")

asset_fact_issued = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/trec_issued_certificate_raw")


default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2026, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    dag_id='gcs_to_bq_issued_certificate',
    default_args=default_args,
    description='任務二：合併 GCS 萬用字元憑證 CSV 檔案並寫入 BigQuery (帶說明)',
    schedule=[rec_gcs_asset],
    catchup=False,
    tags=['gcs', 'bigquery', 'raw', 'wildcard'],
) as dag:

    PythonOperator(
        task_id='import_issued_certificate',
        python_callable=import_issued_certificate_to_bq,
        op_kwargs={
        'project_id': "tibametopics",        # 例如 'my-gcp-project'
        'dataset_id': "trec_data",   # 例如 'bronze_dataset'
        'table_id': 'trec_issued_certificate_raw' # 你想建立的資料表名稱
        },
        dag=dag,
        outlets=[asset_fact_issued]
    )
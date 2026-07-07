import datetime
from airflow import DAG
from airflow.sdk import Asset
from airflow.decorators import task
from bq_cleaner import BigQueryETLPipeline

default_args = {
    'owner': 'data_engineer',
    'depends_on_past': False,
    'retries': 2,
    'retry_delay': datetime.timedelta(minutes=3),
}

PROJECT_ID = "tibametopics"
DATASET_ID = "trec_data"

# 定義上游資料觸發資產（這裡維持使用變數，方便未來改動）
asset_fact_direct = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/fact_direct_transaction")
asset_fact_issued = Asset(uri=f"bigquery://{PROJECT_ID}/{DATASET_ID}/fact_issued_certificate")

with DAG(
    dag_id='stage4_dashboard_views_builder',
    default_args=default_args,
    description='第四階段：建置前端網站與 Looker 共用之 BigQuery View 視圖層',
    schedule=[asset_fact_direct, asset_fact_issued],                  
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    tags=['trec', 'stage4', 'dashboard', 'view'],
) as dag:

    # =========================================================================
    #  定義 9 個獨立的 @task 區塊（括號完全掏空，利用 Class 內部的預設值）
    # =========================================================================
    @task(task_id='build_vw_transaction_detail')
    def build_detail():
        BigQueryETLPipeline().create_vw_transaction_detail()

    @task(task_id='build_vw_dashboard_yearly')
    def build_yearly():
        BigQueryETLPipeline().create_vw_dashboard_yearly()

    @task(task_id='build_vw_dashboard_monthly')
    def build_monthly():
        BigQueryETLPipeline().create_vw_dashboard_monthly()

    @task(task_id='build_vw_dashboard_daily')
    def build_daily():
        BigQueryETLPipeline().create_vw_dashboard_daily()

    @task(task_id='build_vw_dashboard_energy_type')
    def build_energy_type():
        BigQueryETLPipeline().create_vw_dashboard_energy_type()

    @task(task_id='build_vw_dashboard_source')
    def build_source():
        BigQueryETLPipeline().create_vw_dashboard_source()

    @task(task_id='build_vw_dashboard_supply_type')
    def build_supply_type():
        BigQueryETLPipeline().create_vw_dashboard_supply_type()

    @task(task_id='build_vw_dashboard_seller')
    def build_seller():
        BigQueryETLPipeline().create_vw_dashboard_seller()

    @task(task_id='build_vw_dashboard_buyer')
    def build_buyer():
        BigQueryETLPipeline().create_vw_dashboard_buyer()

    # =========================================================================
    #  直接點火啟動：完全平等、平行執行
    # =========================================================================
    build_detail()
    build_yearly()
    build_monthly()
    build_daily()
    build_energy_type()
    build_source()
    build_supply_type()
    build_seller()
    build_buyer()
import datetime
from airflow import DAG
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.providers.google.cloud.operators.cloud_run import CloudRunExecuteJobOperator
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import GCSToBigQueryOperator

# 假設與設定：
# 1. Cloud Run Job 的名稱與專案相關設定，這邊使用變數或 placeholder，後續可至 Airflow Variables 或直接修改。
# 2. GCSToBigQueryOperator 需要設定 bucket, source_objects, destination_project_dataset_table。
# 3. 三條爬蟲路線平行執行，完成後各自寫入 GCS。
# 4. 為了避免 BigQuery 轉換作業 (00-10) 發生重複執行或併發衝突，這邊設定一個匯集點 (join_before_bq)，
#    等待所有資料皆寫入 BQ Raw Table 後，再統一執行 00-10 的後續轉換。

PROJECT_ID = "tibametopics"
REGION = "asia-east1"
GCS_BUCKET = "tibame-bronze"
BQ_DATASET = "gcstobq_airflowtest"

default_args = {
    'owner': 'data_engineer',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': datetime.timedelta(minutes=5),
}

with DAG(
    dag_id='gcp_medallion_pipeline_dag_v1',
    default_args=default_args,
    description='Pipeline for crawling data, saving to GCS, loading to BQ and transforming data',
    schedule='@daily',
    start_date=datetime.datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'crawler', 'bigquery'],
) as dag:

    start_task = EmptyOperator(task_id='start')

    # ==========================================
    # Branch 1: Direct Transaction Pipeline
    # ==========================================
    crawl_direct_01 = CloudRunExecuteJobOperator(
        task_id='01_crawl_direct_transaction_raw',
        project_id=PROJECT_ID,
        region=REGION,
        job_name='crawl-direct-transaction-raw',
    )
    
    crawl_direct_02 = CloudRunExecuteJobOperator(
        task_id='02_retry_direct_transaction_failed',
        project_id=PROJECT_ID,
        region=REGION,
        job_name='retry-direct-transaction-failed',
    )
    
    crawl_direct_03 = CloudRunExecuteJobOperator(
        task_id='03_etl_direct_transaction_deduplicate',
        project_id=PROJECT_ID,
        region=REGION,
        job_name='etl-direct-transaction-dedup',
    )
    
    crawl_direct_04 = CloudRunExecuteJobOperator(
        task_id='04_run_direct_transaction_pipeline',
        project_id=PROJECT_ID,
        region=REGION,
        job_name='run-direct-transaction-pipeline',
    )
    
    gcs_to_bq_direct = GCSToBigQueryOperator(
        task_id='gcs_to_bq_direct',
        bucket=GCS_BUCKET,
        source_objects=['direct_transaction_raw/*.csv'], # 需替換為實際路徑
        destination_project_dataset_table=f'{PROJECT_ID}.{BQ_DATASET}.direct_raw',
        write_disposition='WRITE_TRUNCATE',
        source_format='CSV',
        autodetect=True,
    )

    # Branch 1 Flow
    start_task >> crawl_direct_01 >> crawl_direct_02 >> crawl_direct_03 >> crawl_direct_04 >> gcs_to_bq_direct


    # ==========================================
    # Branch 2: Self Use Pipeline
    # ==========================================
    crawl_self_use = CloudRunExecuteJobOperator(
        task_id='2_self_use',
        project_id=PROJECT_ID,
        region=REGION,
        job_name='self-use-crawler',
    )
    
    gcs_to_bq_self = GCSToBigQueryOperator(
        task_id='gcs_to_bq_self_use',
        bucket=GCS_BUCKET,
        source_objects=['self_use_raw/*.csv'], # 需替換為實際路徑
        destination_project_dataset_table=f'{PROJECT_ID}.{BQ_DATASET}.self_raw',
        write_disposition='WRITE_TRUNCATE',
        source_format='CSV',
        autodetect=True,
    )

    # Branch 2 Flow
    start_task >> crawl_self_use >> gcs_to_bq_self


    # ==========================================
    # Branch 3: REC Cloudrun Pipeline
    # ==========================================
    crawl_rec = CloudRunExecuteJobOperator(
        task_id='REC_cloudrun_playwright_ver',
        project_id=PROJECT_ID,
        region=REGION,
        job_name='rec-cloudrun-playwright',
    )
    
    gcs_to_bq_rec = GCSToBigQueryOperator(
        task_id='gcs_to_bq_rec',
        bucket=GCS_BUCKET,
        source_objects=['rec_raw/*.csv'], # 需替換為實際路徑
        destination_project_dataset_table=f'{PROJECT_ID}.{BQ_DATASET}.rec_raw',
        write_disposition='WRITE_TRUNCATE',
        source_format='CSV',
        autodetect=True,
    )

    # Branch 3 Flow
    start_task >> crawl_rec >> gcs_to_bq_rec


    # ==========================================
    # Join Point: 匯集點
    # 等待三支爬蟲皆完成 GCS to BQ 後，統一進行 BQ 轉換作業
    # ==========================================
    join_before_bq = EmptyOperator(task_id='join_before_bq')

    [gcs_to_bq_direct, gcs_to_bq_self, gcs_to_bq_rec] >> join_before_bq

    # ==========================================
    # BigQuery Transformation Pipeline
    # (使用 CloudRunExecuteJobOperator 執行 Python 轉換腳本)
    # ==========================================
    bq_00_create_dataset = CloudRunExecuteJobOperator(
        task_id='00_create_dataset',
        project_id=PROJECT_ID,
        region=REGION,
        job_name='bq-create-dataset',
    )

    bq_02_load_raw = CloudRunExecuteJobOperator(
        task_id='02_load_raw_tables',
        project_id=PROJECT_ID,
        region=REGION,
        job_name='bq-load-raw-tables',
    )

    bq_04_create_clean = CloudRunExecuteJobOperator(
        task_id='04_create_clean_tables',
        project_id=PROJECT_ID,
        region=REGION,
        job_name='bq-create-clean-tables',
    )

    bq_06_create_dim = CloudRunExecuteJobOperator(
        task_id='06_create_dimension_table',
        project_id=PROJECT_ID,
        region=REGION,
        job_name='bq-create-dimension-table',
    )

    bq_08_create_fact = CloudRunExecuteJobOperator(
        task_id='08_create_fact_table',
        project_id=PROJECT_ID,
        region=REGION,
        job_name='bq-create-fact-table',
    )

    bq_10_create_view = CloudRunExecuteJobOperator(
        task_id='10_create_views',
        project_id=PROJECT_ID,
        region=REGION,
        job_name='bq-create-views',
    )

    # BQ Transformation Flow
    (
        join_before_bq
        >> bq_00_create_dataset
        >> bq_02_load_raw
        >> bq_04_create_clean
        >> bq_06_create_dim
        >> bq_08_create_fact
        >> bq_10_create_view
    )

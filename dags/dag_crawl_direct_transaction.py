import datetime

from airflow.sdk import dag, Asset
from airflow.providers.google.cloud.operators.cloud_run import CloudRunExecuteJobOperator
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import GCSToBigQueryOperator

from common_config import PROJECT_ID, REGION, GCS_BUCKET, BQ_DATASET, DEFAULT_ARGS, CRAWLER_JOB_NAME

direct_raw_asset = Asset(f"bq://{PROJECT_ID}.{BQ_DATASET}.direct_raw")


@dag(
    description='爬取 Direct Transaction 資料，清洗後寫入 BQ direct_raw table',
    schedule='@daily',
    start_date=datetime.datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'crawler', 'direct_transaction'],
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
)
def crawl_direct_transaction():
    crawl_01 = CloudRunExecuteJobOperator(
        task_id='01_crawl_direct_transaction_raw',
        project_id=PROJECT_ID,
        region=REGION,
        job_name=CRAWLER_JOB_NAME,
        overrides={
            "container_overrides": [
                {"args": ["python", "src/crawler/direct_transaction_cloudrun_playwright/01_crawl_direct_transaction_raw.py"]}
            ]
        },
    )

    crawl_02 = CloudRunExecuteJobOperator(
        task_id='02_retry_direct_transaction_failed',
        project_id=PROJECT_ID,
        region=REGION,
        job_name=CRAWLER_JOB_NAME,
        overrides={
            "container_overrides": [
                {"args": ["python", "src/crawler/direct_transaction_cloudrun_playwright/02_retry_direct_transaction_failed.py"]}
            ]
        },
    )

    crawl_03 = CloudRunExecuteJobOperator(
        task_id='03_etl_direct_transaction_deduplicate',
        project_id=PROJECT_ID,
        region=REGION,
        job_name=CRAWLER_JOB_NAME,
        overrides={
            "container_overrides": [
                {"args": ["python", "src/crawler/direct_transaction_cloudrun_playwright/03_etl_direct_transaction_deduplicate.py"]}
            ]
        },
    )

    crawl_04 = CloudRunExecuteJobOperator(
        task_id='04_run_direct_transaction_pipeline',
        project_id=PROJECT_ID,
        region=REGION,
        job_name=CRAWLER_JOB_NAME,
        overrides={
            "container_overrides": [
                {"args": ["python", "src/crawler/direct_transaction_cloudrun_playwright/04_run_direct_transaction_pipeline.py"]}
            ]
        },
    )

    gcs_to_bq_direct = GCSToBigQueryOperator(
        task_id='gcs_to_bq_direct',
        bucket=GCS_BUCKET,
        source_objects=['direct_transaction_raw/*.csv'],
        destination_project_dataset_table=f'{PROJECT_ID}.{BQ_DATASET}.direct_raw',
        write_disposition='WRITE_TRUNCATE',
        source_format='CSV',
        autodetect=True,
        outlets=[direct_raw_asset],
    )

    crawl_01 >> crawl_02 >> crawl_03 >> crawl_04 >> gcs_to_bq_direct


crawl_direct_transaction()

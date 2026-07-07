import datetime

from airflow.sdk import dag, Asset
from airflow.providers.google.cloud.operators.cloud_run import CloudRunExecuteJobOperator
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import GCSToBigQueryOperator

from common_config import PROJECT_ID, REGION, GCS_BUCKET, BQ_DATASET, DEFAULT_ARGS, CRAWLER_JOB_NAME

rec_raw_asset = Asset(f"bq://{PROJECT_ID}.{BQ_DATASET}.rec_raw")


@dag(
    description='使用 Playwright 爬取 REC 資料，寫入 BQ rec_raw table',
    schedule='@daily',
    start_date=datetime.datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'crawler', 'rec'],
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
)
def crawl_rec():
    crawl_rec_task = CloudRunExecuteJobOperator(
        task_id='01_rec_cloudrun_playwright',
        project_id=PROJECT_ID,
        region=REGION,
        job_name=CRAWLER_JOB_NAME,
        overrides={
            "container_overrides": [
                {"args": ["python", "src/crawler/REC_cloudrun_playwright_ver.py"]}
            ]
        },
    )

    gcs_to_bq_rec = GCSToBigQueryOperator(
        task_id='gcs_to_bq_rec',
        bucket=GCS_BUCKET,
        source_objects=['rec_raw/*.csv'],
        destination_project_dataset_table=f'{PROJECT_ID}.{BQ_DATASET}.rec_raw',
        write_disposition='WRITE_TRUNCATE',
        source_format='CSV',
        autodetect=True,
        outlets=[rec_raw_asset],
    )

    crawl_rec_task >> gcs_to_bq_rec


crawl_rec()

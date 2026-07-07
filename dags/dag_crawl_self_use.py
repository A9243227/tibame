import datetime

from airflow.sdk import dag, Asset
from airflow.providers.google.cloud.operators.cloud_run import CloudRunExecuteJobOperator
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import GCSToBigQueryOperator

from common_config import PROJECT_ID, REGION, GCS_BUCKET, BQ_DATASET, DEFAULT_ARGS

self_raw_asset = Asset(f"bq://{PROJECT_ID}.{BQ_DATASET}.self_raw")


@dag(
    description='爬取 Self Use 資料，寫入 BQ self_raw table',
    schedule='@daily',
    start_date=datetime.datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'crawler', 'self_use'],
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
)
def crawl_self_use():
    crawl_self_use_task = CloudRunExecuteJobOperator(
        task_id='01_self_use_crawler',
        project_id=PROJECT_ID,
        region=REGION,
        job_name='self-use-crawler',
    )

    gcs_to_bq_self = GCSToBigQueryOperator(
        task_id='gcs_to_bq_self_use',
        bucket=GCS_BUCKET,
        source_objects=['self_use_raw/*.csv'],
        destination_project_dataset_table=f'{PROJECT_ID}.{BQ_DATASET}.self_raw',
        write_disposition='WRITE_TRUNCATE',
        source_format='CSV',
        autodetect=True,
        outlets=[self_raw_asset],
    )

    crawl_self_use_task >> gcs_to_bq_self


crawl_self_use()

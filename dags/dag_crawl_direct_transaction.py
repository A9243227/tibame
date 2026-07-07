import datetime

from airflow.sdk import dag
from airflow.providers.google.cloud.operators.cloud_run import CloudRunExecuteJobOperator

from common_config import PROJECT_ID, REGION, DEFAULT_ARGS, CRAWLER_JOB_NAME


@dag(
    description='爬取 Direct Transaction 資料，清洗後上傳 GCS',
    schedule='@daily',
    dag_id='dag_crawl_direct_transaction',
    start_date=datetime.datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'crawler', 'direct_transaction'],
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
)
def crawl_direct_transaction():
    # 04 內部負責依序呼叫 01 → (有 failed 才) 02 → 03
    CloudRunExecuteJobOperator(
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


crawl_direct_transaction()

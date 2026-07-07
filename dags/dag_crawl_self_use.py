import datetime

from airflow.sdk import dag
from airflow.providers.google.cloud.operators.cloud_run import CloudRunExecuteJobOperator

from common_config import PROJECT_ID, REGION, DEFAULT_ARGS, CRAWLER_JOB_NAME


@dag(
    description='爬取 Self Use 資料，上傳 GCS',
    schedule='@daily',
    dag_id='dag_crawl_self_use',
    start_date=datetime.datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'crawler', 'self_use'],
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
)
def crawl_self_use():
    CloudRunExecuteJobOperator(
        task_id='04_run_self_generation_pipeline',
        project_id=PROJECT_ID,
        region=REGION,
        job_name=CRAWLER_JOB_NAME,
        overrides={
            "container_overrides": [
                {"args": ["python", "src/crawler/self_generation_update/04_run_self_generation_transaction_pipeline.py"]}
            ]
        },
    )


crawl_self_use()

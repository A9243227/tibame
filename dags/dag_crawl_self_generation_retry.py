import datetime

from airflow.sdk import dag
from airflow.providers.google.cloud.operators.cloud_run import CloudRunExecuteJobOperator

from common_config import PROJECT_ID, REGION, DEFAULT_ARGS, CRAWLER_JOB_NAME


@dag(
    description='Self Generation retry-only：02（failed_retry）→ 03，手動觸發補跑失敗資料',
    schedule=None,
    dag_id='dag_crawl_self_generation_retry',
    start_date=datetime.datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'crawler', 'self_use', 'retry'],
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
)
def crawl_self_generation_retry():
    CloudRunExecuteJobOperator(
        task_id='05_run_self_generation_retry_pipeline',
        project_id=PROJECT_ID,
        region=REGION,
        job_name=CRAWLER_JOB_NAME,
        overrides={
            "container_overrides": [
                {"args": ["python", "src/crawler/self_generation_update/05_run_self_generation_transaction_retry_pipeline.py"]}
            ]
        },
    )


crawl_self_generation_retry()

import datetime

from airflow.sdk import dag, Asset
from airflow.providers.google.cloud.operators.cloud_run import CloudRunExecuteJobOperator

from common_config import PROJECT_ID, REGION, BQ_DATASET, DEFAULT_ARGS, BQ_JOB_NAME

direct_raw_asset = Asset(f"bq://{PROJECT_ID}.{BQ_DATASET}.direct_raw")
self_raw_asset = Asset(f"bq://{PROJECT_ID}.{BQ_DATASET}.self_raw")
rec_raw_asset = Asset(f"bq://{PROJECT_ID}.{BQ_DATASET}.rec_raw")


@dag(
    description='三個 raw table 皆更新後，執行 BQ 轉換作業 (00-10)',
    schedule=[direct_raw_asset, self_raw_asset, rec_raw_asset],
    start_date=datetime.datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'bigquery', 'transform'],
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
)
def bq_transform_pipeline():
    bq_00_create_dataset = CloudRunExecuteJobOperator(
        task_id='00_create_dataset',
        project_id=PROJECT_ID,
        region=REGION,
        job_name=BQ_JOB_NAME,
        overrides={
            "container_overrides": [
                {"args": ["python", "src/green_pipeline/BigQuery/STAR0/Python/00_create_dataset.py"]}
            ]
        },
    )

    bq_02_load_raw = CloudRunExecuteJobOperator(
        task_id='02_load_raw_tables',
        project_id=PROJECT_ID,
        region=REGION,
        job_name=BQ_JOB_NAME,
        overrides={
            "container_overrides": [
                {"args": ["python", "src/green_pipeline/BigQuery/STAR0/Python/02_load_raw_tables.py"]}
            ]
        },
    )

    bq_04_create_clean = CloudRunExecuteJobOperator(
        task_id='04_create_clean_tables',
        project_id=PROJECT_ID,
        region=REGION,
        job_name=BQ_JOB_NAME,
        overrides={
            "container_overrides": [
                {"args": ["python", "src/green_pipeline/BigQuery/STAR0/Python/04_create_clean_tables.py"]}
            ]
        },
    )

    bq_06_create_dim = CloudRunExecuteJobOperator(
        task_id='06_create_dimension_table',
        project_id=PROJECT_ID,
        region=REGION,
        job_name=BQ_JOB_NAME,
        overrides={
            "container_overrides": [
                {"args": ["python", "src/green_pipeline/BigQuery/STAR0/Python/06_create_dimension_tables.py"]}
            ]
        },
    )

    bq_08_create_fact = CloudRunExecuteJobOperator(
        task_id='08_create_fact_table',
        project_id=PROJECT_ID,
        region=REGION,
        job_name=BQ_JOB_NAME,
        overrides={
            "container_overrides": [
                {"args": ["python", "src/green_pipeline/BigQuery/STAR0/Python/08_create_fact_tables.py"]}
            ]
        },
    )

    bq_10_create_view = CloudRunExecuteJobOperator(
        task_id='10_create_views',
        project_id=PROJECT_ID,
        region=REGION,
        job_name=BQ_JOB_NAME,
        overrides={
            "container_overrides": [
                {"args": ["python", "src/green_pipeline/BigQuery/STAR0/Python/10_create_views.py"]}
            ]
        },
    )

    (
        bq_00_create_dataset
        >> bq_02_load_raw
        >> bq_04_create_clean
        >> bq_06_create_dim
        >> bq_08_create_fact
        >> bq_10_create_view
    )


bq_transform_pipeline()

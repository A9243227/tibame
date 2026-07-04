import datetime
from airflow import DAG
from airflow.providers.google.cloud.operators.cloud_run import CloudRunExecuteJobOperator
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import GCSToBigQueryOperator

PROJECT_ID = "tibametopics"
REGION = "asia-east1"
GCS_BUCKET = "tibame-bronze"
BQ_DATASET = "gcstobq_airflowtest"

CRAWLER_JOB_NAME = "crawler-image"
BQ_JOB_NAME = "bq-image"

default_args = {
    'owner': 'data_engineer',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': datetime.timedelta(minutes=5),
}

# ==========================================
# 輔助函數：建立 Cloud Run 獨立 DAG
# ==========================================
def create_cloud_run_dag(dag_id, job_name, script_path, schedule=None):
    dag = DAG(
        dag_id=dag_id,
        default_args=default_args,
        schedule=schedule, # 設為 None 讓您可以手動觸發，或自行填寫 '@daily', '0 8 * * *' 等
        start_date=datetime.datetime(2023, 1, 1),
        catchup=False,
        tags=['gcp', 'cloud_run', 'independent'],
    )
    
    with dag:
        CloudRunExecuteJobOperator(
            task_id='run_job',
            project_id=PROJECT_ID,
            region=REGION,
            job_name=job_name,
            # 使用 overrides 來覆寫 Dockerfile 裡面的 CMD，告訴 Job 要執行哪支 Python
            overrides={
                "container_overrides": [
                    {
                        "args": ["python", script_path]
                    }
                ]
            }
        )
    return dag

# ==========================================
# 輔助函數：建立 GCS to BQ 獨立 DAG
# ==========================================
def create_gcs_to_bq_dag(dag_id, source_objects, destination_table, schedule=None):
    dag = DAG(
        dag_id=dag_id,
        default_args=default_args,
        schedule=schedule,
        start_date=datetime.datetime(2023, 1, 1),
        catchup=False,
        tags=['gcp', 'gcs', 'bigquery', 'independent'],
    )
    
    with dag:
        GCSToBigQueryOperator(
            task_id='gcs_to_bq',
            bucket=GCS_BUCKET,
            source_objects=[source_objects],
            destination_project_dataset_table=f'{PROJECT_ID}.{BQ_DATASET}.{destination_table}',
            write_disposition='WRITE_TRUNCATE',
            source_format='CSV',
            autodetect=True,
        )
    return dag

# ==========================================
# 1. Direct Transaction Pipeline (爬蟲 4 支 + GCS2BQ)
# ==========================================
dag_01_crawl_direct = create_cloud_run_dag(
    dag_id="dag_01_crawl_direct_transaction",
    job_name=CRAWLER_JOB_NAME,
    script_path="src/crawler/direct_transaction_cloudrun_playwright/01_crawl_direct_transaction_raw.py"
)

dag_02_retry_direct = create_cloud_run_dag(
    dag_id="dag_02_retry_direct_transaction",
    job_name=CRAWLER_JOB_NAME,
    script_path="src/crawler/direct_transaction_cloudrun_playwright/02_retry_direct_transaction_failed.py"
)

dag_03_etl_direct = create_cloud_run_dag(
    dag_id="dag_03_etl_direct_transaction",
    job_name=CRAWLER_JOB_NAME,
    script_path="src/crawler/direct_transaction_cloudrun_playwright/03_etl_direct_transaction_deduplicate.py"
)

dag_04_run_direct = create_cloud_run_dag(
    dag_id="dag_04_run_direct_transaction",
    job_name=CRAWLER_JOB_NAME,
    script_path="src/crawler/direct_transaction_cloudrun_playwright/04_run_direct_transaction_pipeline.py"
)

dag_gcs_to_bq_direct = create_gcs_to_bq_dag(
    dag_id="dag_gcs_to_bq_direct",
    source_objects="direct_transaction_raw/*.csv",
    destination_table="direct_raw"
)


# ==========================================
# 2. Self Use Pipeline (爬蟲 1 支 + GCS2BQ)
# ==========================================
dag_2_self_use = create_cloud_run_dag(
    dag_id="dag_2_self_use",
    job_name=CRAWLER_JOB_NAME,
    script_path="src/crawler/2_self_use.py"
)

dag_gcs_to_bq_self = create_gcs_to_bq_dag(
    dag_id="dag_gcs_to_bq_self",
    source_objects="self_use_raw/*.csv",
    destination_table="self_raw"
)


# ==========================================
# 3. REC Cloudrun Pipeline (爬蟲 1 支 + GCS2BQ)
# ==========================================
dag_rec_cloudrun = create_cloud_run_dag(
    dag_id="dag_rec_cloudrun",
    job_name=CRAWLER_JOB_NAME,
    script_path="src/crawler/REC_cloudrun_playwright_ver.py"
)

dag_gcs_to_bq_rec = create_gcs_to_bq_dag(
    dag_id="dag_gcs_to_bq_rec",
    source_objects="rec_raw/*.csv",
    destination_table="rec_raw"
)


# ==========================================
# 4. BigQuery Transformation Pipeline (BQ 6 支)
# ==========================================
dag_bq_00_create_dataset = create_cloud_run_dag(
    dag_id="dag_bq_00_create_dataset",
    job_name=BQ_JOB_NAME,
    script_path="src/green_pipeline/BigQuery/STAR0/Python/00_create_dataset.py"
)

dag_bq_02_load_raw = create_cloud_run_dag(
    dag_id="dag_bq_02_load_raw",
    job_name=BQ_JOB_NAME,
    script_path="src/green_pipeline/BigQuery/STAR0/Python/02_load_raw_tables.py"
)

dag_bq_04_create_clean = create_cloud_run_dag(
    dag_id="dag_bq_04_create_clean",
    job_name=BQ_JOB_NAME,
    script_path="src/green_pipeline/BigQuery/STAR0/Python/04_create_clean_tables.py"
)

dag_bq_06_create_dim = create_cloud_run_dag(
    dag_id="dag_bq_06_create_dim",
    job_name=BQ_JOB_NAME,
    script_path="src/green_pipeline/BigQuery/STAR0/Python/06_create_dimension_tables.py"
)

dag_bq_08_create_fact = create_cloud_run_dag(
    dag_id="dag_bq_08_create_fact",
    job_name=BQ_JOB_NAME,
    script_path="src/green_pipeline/BigQuery/STAR0/Python/08_create_fact_tables.py"
)

dag_bq_10_create_views = create_cloud_run_dag(
    dag_id="dag_bq_10_create_views",
    job_name=BQ_JOB_NAME,
    script_path="src/green_pipeline/BigQuery/STAR0/Python/10_create_views.py"
)

# 注意：當您把這個檔案放入 Airflow 後，
# 上面建立的 15 個 `dag_` 開頭的變數，會自動被 Airflow 識別成 15 個獨立的 DAG。
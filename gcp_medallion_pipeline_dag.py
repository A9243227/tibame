import os
from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.google.cloud.operators.cloud_run import CloudRunExecuteJobOperator
from airflow.operators.bash import BashOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator

# ==========================================
# 定義基本參數
# ==========================================
PROJECT_ID = "your-gcp-project-id"
REGION = "asia-east1"
CLOUD_RUN_JOB_NAME = "your-cloud-run-job-name"
CRAWLER_TASK_INDICES = [0, 1]

DAGS_FOLDER = os.environ.get("DAGS_FOLDER", "/opt/airflow/dags")
PYTHON_SCRIPTS_DIR = f"{DAGS_FOLDER}/src/green_pipeline/BigQuery/STAR0/Python"

default_args = {
    'owner': 'data_engineer',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# ==========================================
# DAG 1: 平行觸發 Cloud Run 爬蟲
# ==========================================
with DAG(
    'gcp_medallion_01_crawler_dag',
    default_args=default_args,
    description='平行觸發 Cloud Run 爬蟲 (Bronze Layer 萃取)',
    schedule_interval='@daily',
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'crawler'],
) as dag_crawler:

    crawler_tasks = []
    for task_index in CRAWLER_TASK_INDICES:
        run_crawler_job = CloudRunExecuteJobOperator(
            task_id=f"run_cloud_run_crawler_{task_index}",
            project_id=PROJECT_ID,
            region=REGION,
            job_name=CLOUD_RUN_JOB_NAME,
            overrides={
                "container_overrides": [
                    {
                        "env": [
                            {"name": "CLOUD_RUN_TASK_INDEX", "value": str(task_index)}
                        ]
                    }
                ]
            },
        )
        crawler_tasks.append(run_crawler_job)

    # 觸發下一個 DAG
    trigger_raw = TriggerDagRunOperator(
        task_id='trigger_load_raw_dag',
        trigger_dag_id='gcp_medallion_02_load_raw_dag',
        wait_for_completion=False,
    )

    for crawler_task in crawler_tasks:
        crawler_task >> trigger_raw

# ==========================================
# DAG 2: 載入 Raw Tables
# ==========================================
with DAG(
    'gcp_medallion_02_load_raw_dag',
    default_args=default_args,
    description='執行 02_load_raw_tables.py',
    schedule_interval=None, # 由上一個 DAG 觸發
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'raw'],
) as dag_raw:

    load_raw_tables = BashOperator(
        task_id='load_raw_tables',
        bash_command=f"python {PYTHON_SCRIPTS_DIR}/02_load_raw_tables.py",
    )

    trigger_clean = TriggerDagRunOperator(
        task_id='trigger_create_clean_dag',
        trigger_dag_id='gcp_medallion_03_create_clean_dag',
        wait_for_completion=False,
    )

    load_raw_tables >> trigger_clean

# ==========================================
# DAG 3: 清洗資料並建立 Clean Tables
# ==========================================
with DAG(
    'gcp_medallion_03_create_clean_dag',
    default_args=default_args,
    description='執行 04_create_clean_tables.py',
    schedule_interval=None,
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'clean'],
) as dag_clean:

    create_clean_tables = BashOperator(
        task_id='create_clean_tables',
        bash_command=f"python {PYTHON_SCRIPTS_DIR}/04_create_clean_tables.py",
    )

    trigger_dim = TriggerDagRunOperator(
        task_id='trigger_create_dim_dag',
        trigger_dag_id='gcp_medallion_04_create_dim_dag',
        wait_for_completion=False,
    )

    create_clean_tables >> trigger_dim

# ==========================================
# DAG 4: 建立 Dimension Tables
# ==========================================
with DAG(
    'gcp_medallion_04_create_dim_dag',
    default_args=default_args,
    description='執行 06_create_dimension_tables.py',
    schedule_interval=None,
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'dimension'],
) as dag_dim:

    create_dimension_tables = BashOperator(
        task_id='create_dimension_tables',
        bash_command=f"python {PYTHON_SCRIPTS_DIR}/06_create_dimension_tables.py",
    )

    trigger_fact = TriggerDagRunOperator(
        task_id='trigger_create_fact_dag',
        trigger_dag_id='gcp_medallion_05_create_fact_dag',
        wait_for_completion=False,
    )

    create_dimension_tables >> trigger_fact

# ==========================================
# DAG 5: 建立 Fact Tables
# ==========================================
with DAG(
    'gcp_medallion_05_create_fact_dag',
    default_args=default_args,
    description='執行 08_create_fact_tables.py',
    schedule_interval=None,
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'fact'],
) as dag_fact:

    create_fact_tables = BashOperator(
        task_id='create_fact_tables',
        bash_command=f"python {PYTHON_SCRIPTS_DIR}/08_create_fact_tables.py",
    )

    trigger_views = TriggerDagRunOperator(
        task_id='trigger_create_views_dag',
        trigger_dag_id='gcp_medallion_06_create_views_dag',
        wait_for_completion=False,
    )

    create_fact_tables >> trigger_views

# ==========================================
# DAG 6: 建立 Views
# ==========================================
with DAG(
    'gcp_medallion_06_create_views_dag',
    default_args=default_args,
    description='執行 10_create_views.py',
    schedule_interval=None,
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'view'],
) as dag_view:

    create_views = BashOperator(
        task_id='create_views',
        bash_command=f"python {PYTHON_SCRIPTS_DIR}/10_create_views.py",
    )

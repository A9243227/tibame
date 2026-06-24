import os
from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.google.cloud.operators.cloud_run import CloudRunExecuteJobOperator
from airflow.operators.bash import BashOperator

# ==========================================
# 定義基本參數 (請替換為你的實際專案資訊)
# ==========================================
PROJECT_ID = "your-gcp-project-id"
REGION = "asia-east1"

# 1. Cloud Run 參數
CLOUD_RUN_JOB_NAME = "your-cloud-run-job-name"
# 假設我們目前有 2 支爬蟲腳本想要平行執行 (Index 0 和 1)
CRAWLER_TASK_INDICES = [0, 1]

# 2. BigQuery ETL 參數
# 假設 src 資料夾與此 DAG 檔一起部署在 Airflow 的 DAGs 資料夾底下
DAGS_FOLDER = os.environ.get("DAGS_FOLDER", "/opt/airflow/dags")
PYTHON_SCRIPTS_DIR = f"{DAGS_FOLDER}/src/green_pipeline/BigQuery/STAR0/Python"

# ==========================================
# DAG 預設參數設定
# ==========================================
default_args = {
    'owner': 'data_engineer',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# ==========================================
# 定義 DAG 工作流
# ==========================================
with DAG(
    'gcp_medallion_pipeline_dag',
    default_args=default_args,
    description='Cloud Run 爬蟲 -> BigQuery Medallion ETL (Raw -> Clean -> Dim/Fact -> Views)',
    schedule_interval='@daily',
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=['gcp', 'crawler', 'medallion', 'bigquery'],
) as dag:

    # ==========================================
    # 階段 1: 平行觸發 Cloud Run 爬蟲 (Bronze Layer 萃取)
    # ==========================================
    crawler_tasks = []
    for task_index in CRAWLER_TASK_INDICES:
        run_crawler_job = CloudRunExecuteJobOperator(
            task_id=f"run_cloud_run_crawler_{task_index}",
            project_id=PROJECT_ID,
            region=REGION,
            job_name=CLOUD_RUN_JOB_NAME,
            # 傳遞環境變數給 Cloud Run Job，指定要跑哪一支爬蟲
            overrides={
                "container_overrides": [
                    {
                        "env": [
                            {"name": "CLOUD_RUN_TASK_INDEX", "value": str(task_index)}
                        ]
                    }
                ]
            },
            # deferrable=True, # 若 Airflow 版本支援，開啟此選項可節省等待時的 Worker 資源
        )
        crawler_tasks.append(run_crawler_job)

    # ==========================================
    # 階段 2: BigQuery ETL 流程 (Silver & Gold Layer 轉換)
    # ==========================================
    
    # 執行 02_load_raw_tables.py (將 GCS 載入 BigQuery 建立 Raw tables)
    load_raw_tables = BashOperator(
        task_id='load_raw_tables',
        bash_command=f"python {PYTHON_SCRIPTS_DIR}/02_load_raw_tables.py",
    )

    # 執行 04_create_clean_tables.py (清洗資料並轉換型別)
    create_clean_tables = BashOperator(
        task_id='create_clean_tables',
        bash_command=f"python {PYTHON_SCRIPTS_DIR}/04_create_clean_tables.py",
    )

    # 執行 06_create_dimension_tables.py (建立維度表)
    create_dimension_tables = BashOperator(
        task_id='create_dimension_tables',
        bash_command=f"python {PYTHON_SCRIPTS_DIR}/06_create_dimension_tables.py",
    )

    # 執行 08_create_fact_tables.py (建立事實表)
    create_fact_tables = BashOperator(
        task_id='create_fact_tables',
        bash_command=f"python {PYTHON_SCRIPTS_DIR}/08_create_fact_tables.py",
    )

    # 執行 10_create_views.py (建立資料超市/報表 Views)
    create_views = BashOperator(
        task_id='create_views',
        bash_command=f"python {PYTHON_SCRIPTS_DIR}/10_create_views.py",
    )

    # ==========================================
    # 設定任務依賴順序 (Workflow Pipeline)
    # ==========================================
    
    # 所有爬蟲必須執行完畢，才能開始載入 raw tables
    for crawler_task in crawler_tasks:
        crawler_task >> load_raw_tables

    # 依序執行 BigQuery 的資料轉換流程
    (
        load_raw_tables
        >> create_clean_tables
        >> create_dimension_tables
        >> create_fact_tables
        >> create_views
    )

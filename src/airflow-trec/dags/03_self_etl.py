from datetime import datetime

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator


# =========================================================
# DAG 03：自用發電 ETL 去重與發布
# =========================================================
# 工作內容：
# 1. 接收 DAG 02 傳入的 pipeline_dt。
# 2. 觸發 Cloud Run Job：trec-update-sg-03。
# 3. 完成去重、產生 processed、audit、BigQuery 固定來源。
#
# Cloud Run Job 03 內部應執行：
# 03_etl_self_generation_transaction_deduplicate.py
# =========================================================

DAG_ID = "trec_update_sg_03_etl"

ETL_JOB_NAME = "trec-update-sg-03"


# =========================================================
# DAG 03 不自己猜日期。
# ---------------------------------------------------------
# 正常流程：
# DAG 02 自動傳入 pipeline_dt。
#
# 手動補跑 DAG 03：
# 必須在 Airflow UI 的 Trigger with config 輸入：
#
# {
#   "pipeline_dt": "2026-07-03"
# }
# =========================================================
PIPELINE_DT_TEMPLATE = (
    "{{ "
    "dag_run.conf.get('pipeline_dt', '') "
    "if dag_run and dag_run.conf "
    "else '' "
    "}}"
)


def build_cloud_run_command(job_name: str) -> str:
    """建立 Airflow 呼叫 Cloud Run Job 的 Bash 指令。"""
    return f"""
set -euo pipefail

if [ -z "${{PIPELINE_DT:-}}" ]; then
  echo "錯誤：DAG 03 必須收到 pipeline_dt。"
  echo '手動執行時，請在 Config 輸入：{{"pipeline_dt": "2026-07-03"}}'
  exit 1
fi

if ! [[ "$PIPELINE_DT" =~ ^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$ ]]; then
  echo "錯誤：pipeline_dt 格式錯誤，必須是 YYYY-MM-DD。"
  echo "目前收到：$PIPELINE_DT"
  exit 1
fi

if ! python -c "from datetime import datetime; import sys; datetime.strptime(sys.argv[1], '%Y-%m-%d')" "$PIPELINE_DT"; then
  echo "錯誤：pipeline_dt 不是有效日期。"
  echo "目前收到：$PIPELINE_DT"
  exit 1
fi

echo "DAG 03 開始執行：自用發電 ETL"
echo "Cloud Run Job：{job_name}"
echo "PIPELINE_DT：$PIPELINE_DT"

python /opt/airflow/scripts/trigger_cloud_run_job.py \\
  --job-name {job_name} \\
  --pipeline-dt "$PIPELINE_DT"
"""


with DAG(
    dag_id=DAG_ID,
    description="自用發電更新 DAG 03：ETL 去重與最終資料發布",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=[
        "green_energy",
        "self_generation",
        "cloud_run",
        "03_etl",
    ],
) as dag:

    run_cloud_run_job_03 = BashOperator(
        task_id="run_cloud_run_job_03_self_etl",
        bash_command=build_cloud_run_command(ETL_JOB_NAME),
        env={
            "PIPELINE_DT": PIPELINE_DT_TEMPLATE,
        },
        append_env=True,
        skip_on_exit_code=None,
    )
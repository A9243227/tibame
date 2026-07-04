from datetime import datetime

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.trigger_dagrun import (
    TriggerDagRunOperator,
)


# =========================================================
# DAG 02：自用發電失敗補抓
# =========================================================
# 工作內容：
# 1. 接收 DAG 01 傳入的 pipeline_dt。
# 2. 觸發 Cloud Run Job：trec-update-sg-02
# 3. Cloud Run Job 02 成功後，自動觸發 DAG 03。
#
# Cloud Run Job 02 內部應執行：
# 02_retry_self_generation_transaction_failed.py
# =========================================================

DAG_ID = "trec_update_sg_02_self_retry_failed"

RETRY_JOB_NAME = "trec-update-sg-02"

NEXT_DAG_ID = "trec_update_sg_03_etl"


# =========================================================
# DAG 02 不自己猜日期。
# ---------------------------------------------------------
# 正常流程：
# DAG 01 自動傳入 pipeline_dt。
#
# 手動補跑 DAG 02：
# 請在 Airflow UI 的 Trigger with config 輸入：
#
# {
#   "pipeline_dt": "2026-07-03"
# }
#
# 沒有帶日期時，DAG 02 會故意失敗，
# 避免讀錯 GCS 的其他 dt 快照資料。
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
  echo "錯誤：DAG 02 必須收到 pipeline_dt。"
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

echo "DAG 02 開始執行：自用發電 failed retry"
echo "Cloud Run Job：{job_name}"
echo "PIPELINE_DT：$PIPELINE_DT"

python /opt/airflow/scripts/trigger_cloud_run_job.py \\
  --job-name {job_name} \\
  --pipeline-dt "$PIPELINE_DT"
"""


with DAG(
    dag_id=DAG_ID,
    description="自用發電更新 DAG 02：失敗補抓成功後自動觸發 DAG 03",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=[
        "green_energy",
        "self_generation",
        "cloud_run",
        "02_retry",
    ],
) as dag:

    # 即使 failed.csv 沒有資料，
    # Cloud Run Job 02 仍會正常結束，接著進入 DAG 03。
    run_cloud_run_job_02 = BashOperator(
        task_id="run_cloud_run_job_02_self_retry",
        bash_command=build_cloud_run_command(RETRY_JOB_NAME),
        env={
            "PIPELINE_DT": PIPELINE_DT_TEMPLATE,
        },
        append_env=True,
        skip_on_exit_code=None,
    )

    trigger_dag_03 = TriggerDagRunOperator(
        task_id="trigger_dag_03_self_etl",
        trigger_dag_id=NEXT_DAG_ID,
        conf={
            "pipeline_dt": PIPELINE_DT_TEMPLATE,
        },
        wait_for_completion=False,
    )

    run_cloud_run_job_02 >> trigger_dag_03
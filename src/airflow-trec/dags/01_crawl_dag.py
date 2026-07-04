from datetime import datetime

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.trigger_dagrun import (
    TriggerDagRunOperator,
)


# =========================================================
# DAG 01：主抓取
# =========================================================
# 工作內容：
# 1. 觸發 Cloud Run Job：trec-update-dt-01
# 2. Cloud Run Job 01 成功後，自動觸發 DAG 02
#
# Cloud Run Job 01 內部應執行：
# 01_crawl_direct_transaction_raw.py
# =========================================================


DAG_ID = "trec_update_dt_01_crawl"

CRAWL_JOB_NAME = "trec-update-dt-01"

NEXT_DAG_ID = "trec_update_dt_02_retry_failed_again"


# =========================================================
# pipeline_dt 規則
# ---------------------------------------------------------
# 優先順序：
#
# 1. 使用者手動 Trigger DAG 01 時傳入：
#    {
#      "pipeline_dt": "2026-07-02"
#    }
#
# 2. 若沒有傳入，使用這次 DAG Run 的台北日期。
# =========================================================
PIPELINE_DT_TEMPLATE = (
    "{{ "
    "dag_run.conf.get('pipeline_dt') "
    "if dag_run and dag_run.conf and dag_run.conf.get('pipeline_dt') "
    "else logical_date.in_timezone('Asia/Taipei').strftime('%Y-%m-%d') "
    "}}"
)


def build_cloud_run_command(job_name: str) -> str:
    """
    建立 Airflow 呼叫 Cloud Run Job 的 Bash 指令。

    注意：
    trigger_cloud_run_job.py 必須等待 Cloud Run Job 完整結束。

    Cloud Run Job 成功：
        trigger_cloud_run_job.py exit code = 0
        Airflow Task = success

    Cloud Run Job 失敗：
        trigger_cloud_run_job.py exit code != 0
        Airflow Task = failed
    """
    return f"""
set -euo pipefail

if [ -z "${{PIPELINE_DT:-}}" ]; then
  echo "錯誤：DAG 01 沒有取得 pipeline_dt。"
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

echo "DAG 01 開始執行"
echo "Cloud Run Job：{job_name}"
echo "PIPELINE_DT：$PIPELINE_DT"

python /opt/airflow/scripts/trigger_cloud_run_job.py \\
  --job-name {job_name} \\
  --pipeline-dt "$PIPELINE_DT"
"""


with DAG(
    dag_id=DAG_ID,
    description="直轉供更新 DAG 01：主抓取成功後自動觸發 DAG 02",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=[
        "green_energy",
        "direct_transaction",
        "cloud_run",
        "01_crawl",
    ],
) as dag:

    # -----------------------------------------------------
    # Task 01：
    # 執行 Cloud Run Job 01 主抓取
    # -----------------------------------------------------
    run_cloud_run_job_01 = BashOperator(
        task_id="run_cloud_run_job_01_crawl",
        bash_command=build_cloud_run_command(CRAWL_JOB_NAME),
        env={
            "PIPELINE_DT": PIPELINE_DT_TEMPLATE,
        },
        append_env=True,
        skip_on_exit_code=None,
    )

    # -----------------------------------------------------
    # Task 02：
    # 只有 DAG 01 的 Cloud Run Job 成功後，
    # 才會自動觸發 DAG 02。
    #
    # 同時把完全相同的 pipeline_dt 傳給 DAG 02。
    # -----------------------------------------------------
    trigger_dag_02 = TriggerDagRunOperator(
        task_id="trigger_dag_02_retry_failed_again",
        trigger_dag_id=NEXT_DAG_ID,
        conf={
            "pipeline_dt": PIPELINE_DT_TEMPLATE,
        },
        wait_for_completion=False,
    )

    run_cloud_run_job_01 >> trigger_dag_02
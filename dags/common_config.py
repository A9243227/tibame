"""
共用設定值，供各 DAG 檔案 import 使用。
集中管理，避免每支 DAG 各自複製一份，改一個地方全部生效。
"""
import datetime

PROJECT_ID = "tibametopics"
REGION = "asia-east1"
GCS_BUCKET = "tibame-bronze"
BQ_DATASET = "gcstobq_airflowtest"

DEFAULT_ARGS = {
    'owner': 'data_engineer',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': datetime.timedelta(minutes=5),
}

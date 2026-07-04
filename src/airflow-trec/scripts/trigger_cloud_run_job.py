from __future__ import annotations

import argparse
import time

from google.cloud import run_v2


PROJECT_ID = "project-c865579e-705e-4adb-aca"
REGION = "asia-east1"

# 每 30 秒查一次 Cloud Run 執行狀態。
POLL_INTERVAL_SECONDS = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="啟動 Cloud Run Job，並等待 Execution 執行完成。"
    )

    parser.add_argument(
        "--job-name",
        required=True,
        help="Cloud Run Job 名稱，例如 trec-update-dt-01",
    )

    parser.add_argument(
        "--pipeline-dt",
        required=True,
        help="本次 01、02、03 共用日期，格式 YYYY-MM-DD",
    )

    return parser.parse_args()


def is_timestamp_set(timestamp) -> bool:
    """
    判斷 Cloud Run 回傳的時間欄位是否已設定。

    舊版可能回傳 protobuf Timestamp，
    新版 google-cloud-run 可能回傳 DatetimeWithNanoseconds。
    """
    if timestamp is None:
        return False

    # 相容 protobuf Timestamp 型別。
    if hasattr(timestamp, "seconds") and hasattr(timestamp, "nanos"):
        return bool(timestamp.seconds or timestamp.nanos)

    # DatetimeWithNanoseconds / datetime 只要不是 None，
    # 就代表 Cloud Run 已回傳時間。
    return True

def main() -> None:
    args = parse_args()

    jobs_client = run_v2.JobsClient()
    executions_client = run_v2.ExecutionsClient()

    job_path = jobs_client.job_path(
        PROJECT_ID,
        REGION,
        args.job_name,
    )

    print("=" * 70)
    print("準備啟動 Cloud Run Job")
    print(f"Project：{PROJECT_ID}")
    print(f"Region：{REGION}")
    print(f"Job：{args.job_name}")
    print(f"PIPELINE_DT：{args.pipeline_dt}")
    print("=" * 70)

    # 執行本次 Job 時，覆寫 PIPELINE_DT。
    # 因此 01、02、03 一定使用同一個快照日期。
    request = run_v2.RunJobRequest(
        name=job_path,
        overrides=run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(
                    env=[
                        run_v2.EnvVar(
                            name="PIPELINE_DT",
                            value=args.pipeline_dt,
                        )
                    ]
                )
            ]
        ),
    )

    operation = jobs_client.run_job(request=request)

    print("Cloud Run 已收到啟動要求，等待建立 Execution...")
    execution = operation.result()

    print(f"Execution：{execution.name}")

    while True:
        execution = executions_client.get_execution(
            name=execution.name
        )

        print(
            "目前狀態："
            f"running={execution.running_count}, "
            f"succeeded={execution.succeeded_count}, "
            f"failed={execution.failed_count}, "
            f"cancelled={execution.cancelled_count}"
        )

        if not is_timestamp_set(execution.completion_time):
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        if execution.failed_count > 0:
            raise RuntimeError(
                f"Cloud Run Job 執行失敗：{args.job_name}"
            )

        if execution.cancelled_count > 0:
            raise RuntimeError(
                f"Cloud Run Job 被取消：{args.job_name}"
            )

        if execution.succeeded_count == execution.task_count:
            print("Cloud Run Job 執行成功")
            return

        raise RuntimeError(
            "Cloud Run Job 已結束，但結果不是成功狀態。"
        )


if __name__ == "__main__":
    main()
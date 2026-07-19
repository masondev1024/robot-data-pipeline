import os

import sagemaker
from sagemaker.xgboost import XGBoost

from src.common.athena import start_query, wait_for_query
from src.common.aws import get_client

S3_BUCKET = os.environ.get("S3_BUCKET_NAME", "robot-telemetry-data")
ATHENA_DATABASE = os.environ.get("ATHENA_DATABASE", "robot_telemetry_db")
ATHENA_OUTPUT = os.environ.get("ATHENA_OUTPUT_LOCATION", f"s3://{S3_BUCKET}/project-athena-results/")
MODEL_PREFIX = "ml-models/robot-failure-predictor"

# Task 8.2: 라벨을 룰 기반(anomaly_record_count) 자기참조에서 generator ground truth
# (dominant_failure_type) 6-class 로 전환. NONE→0, TWF→1, HDF→2, PWF→3, OSF→4, RNF→5.
# Athena 결과는 "label,sample_weight,feat1..feat5" 컬럼 순서로 SageMaker 학습에 전달.
LABEL_MAP = {"NONE": 0, "TWF": 1, "HDF": 2, "PWF": 3, "OSF": 4, "RNF": 5}
NUM_CLASSES = len(LABEL_MAP)
FEATURE_COLUMNS = [
    "avg_motor_temp",
    "max_motor_temp",
    "battery_drain",
    "active_hours",
    "max_temp_load_ratio",
]

# Class-imbalance: NONE 이 ~99% 점유 예상 → minority class 가중치 50.0 (faulty 1건 ≈ NONE 50건).
# XGBoost multi:softprob 는 scale_pos_weight 미지원이므로 sample_weight 칼럼으로 가중치 주입.
_MINORITY_WEIGHT = 50.0
QUERY = f"""
SELECT
    CASE dominant_failure_type
        WHEN 'NONE' THEN 0
        WHEN 'TWF'  THEN 1
        WHEN 'HDF'  THEN 2
        WHEN 'PWF'  THEN 3
        WHEN 'OSF'  THEN 4
        WHEN 'RNF'  THEN 5
        ELSE 0
    END                                                         AS label,
    CASE WHEN dominant_failure_type = 'NONE' THEN 1.0
         ELSE {_MINORITY_WEIGHT} END                            AS sample_weight,
    avg_motor_temp,
    max_motor_temp,
    battery_drain,
    active_hours,
    max_temp_load_ratio
FROM gold_robot_daily_stats
WHERE dt >= current_date - interval '30' day
  AND avg_motor_temp IS NOT NULL
  AND dominant_failure_type IS NOT NULL
"""


def fetch_training_data():
    execution_id = start_query(QUERY, database=ATHENA_DATABASE, output_location=ATHENA_OUTPUT)
    wait_for_query(execution_id)

    raw_uri = f"{ATHENA_OUTPUT}{execution_id}.csv"
    s3 = get_client("s3")
    bucket, key = raw_uri.replace("s3://", "").split("/", 1)
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    headerless = "\n".join(body.splitlines()[1:])

    train_key = f"{MODEL_PREFIX}/train/{execution_id}.csv"
    s3.put_object(Bucket=S3_BUCKET, Key=train_key, Body=headerless.encode("utf-8"))
    return f"s3://{S3_BUCKET}/{train_key}"


def run_training_job(data_s3_uri: str, role_arn: str):
    session = sagemaker.Session()
    estimator = XGBoost(
        entry_point="train_entry.py",
        source_dir="src/ml/",
        role=role_arn,
        instance_count=1,
        instance_type="ml.m5.large",
        framework_version="1.7-1",
        hyperparameters={
            "objective": "multi:softprob",
            "num_class": NUM_CLASSES,
            "eval_metric": "mlogloss",
            "num_round": 100,
            "max_depth": 5,
            "eta": 0.1,
        },
        output_path=f"s3://{S3_BUCKET}/{MODEL_PREFIX}/",
    )
    estimator.fit({"train": data_s3_uri})
    return estimator


def _cleanup_existing_endpoint(endpoint_name: str = "robot-failure-predictor"):
    """멱등성: SDK 2.257+ 에서 update_endpoint kwarg 제거됨에 따라 명시적 cleanup."""
    sm = get_client("sagemaker")
    for delete_fn, name_kwarg in [
        (sm.delete_endpoint, "EndpointName"),
        (sm.delete_endpoint_config, "EndpointConfigName"),
    ]:
        try:
            delete_fn(**{name_kwarg: endpoint_name})
        except sm.exceptions.ClientError:
            pass  # 없으면 무시


def main():
    data_uri = fetch_training_data()
    estimator = run_training_job(data_uri, os.environ["SAGEMAKER_ROLE_ARN"])
    _cleanup_existing_endpoint()
    estimator.deploy(
        initial_instance_count=1,
        instance_type="ml.t2.medium",
        endpoint_name="robot-failure-predictor",
    )


if __name__ == "__main__":
    main()

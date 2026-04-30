import os

import sagemaker
from sagemaker.xgboost import XGBoost

from src.common.athena import start_query, wait_for_query
from src.common.aws import get_client

S3_BUCKET = os.environ.get("S3_BUCKET_NAME", "de-ai-06-smartfactory-bucket")
ATHENA_DATABASE = os.environ.get("ATHENA_DATABASE", "robot_telemetry_db")
ATHENA_OUTPUT = os.environ.get("ATHENA_OUTPUT_LOCATION", f"s3://{S3_BUCKET}/project-athena-results/")
MODEL_PREFIX = "ml-models/robot-failure-predictor"

QUERY = """
SELECT
    CASE WHEN max_motor_temp > 90.0 THEN 1 ELSE 0 END AS label,
    avg_motor_temp,
    max_motor_temp,
    battery_drain,
    active_hours
FROM gold_robot_daily_stats
WHERE dt >= current_date - interval '30' day
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
            "objective": "binary:logistic",
            "num_round": 100,
            "max_depth": 5,
            "eta": 0.1,
        },
        output_path=f"s3://{S3_BUCKET}/{MODEL_PREFIX}/",
    )
    estimator.fit({"train": data_s3_uri})
    return estimator


def main():
    data_uri = fetch_training_data()
    estimator = run_training_job(data_uri, os.environ["SAGEMAKER_ROLE_ARN"])
    estimator.deploy(
        initial_instance_count=1,
        instance_type="ml.t2.medium",
        endpoint_name="robot-failure-predictor",
        update_endpoint=True,
    )


if __name__ == "__main__":
    main()

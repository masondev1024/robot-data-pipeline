import os
import time

import boto3
import pandas as pd
import sagemaker
from sagemaker.xgboost import XGBoost

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
WHERE dt >= date_format(current_date - interval '30' day, '%Y-%m-%d')
"""


def fetch_training_data():
    athena = boto3.client("athena", region_name="eu-west-1")
    response = athena.start_query_execution(
        QueryString=QUERY,
        QueryExecutionContext={"Database": ATHENA_DATABASE},
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
    )
    execution_id = response["QueryExecutionId"]

    for _ in range(150):
        status = athena.get_query_execution(QueryExecutionId=execution_id)
        state = status["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "unknown")
            raise RuntimeError(f"Athena query {state}: {reason}")
        time.sleep(2)
    else:
        raise TimeoutError("Athena query timed out after 300s")

    raw_uri = f"{ATHENA_OUTPUT}{execution_id}.csv"
    s3 = boto3.client("s3", region_name="eu-west-1")
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


if __name__ == "__main__":
    data_uri = fetch_training_data()
    estimator = run_training_job(data_uri, os.environ["SAGEMAKER_ROLE_ARN"])
    estimator.deploy(
        initial_instance_count=1,
        instance_type="ml.t2.medium",
        endpoint_name="robot-failure-predictor",
    )

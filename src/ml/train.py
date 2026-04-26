import boto3
import pandas as pd
import sagemaker
from sagemaker.xgboost import XGBoost

ATHENA_DATABASE = "robot_telemetry_db"
ATHENA_OUTPUT = "s3://de-ai-06-827913617635-ap-northeast-2-an/project-athena-results/"
S3_BUCKET = "de-ai-06-827913617635-ap-northeast-2-an"
MODEL_PREFIX = "ml-models/robot-failure-predictor"

QUERY = """
SELECT
    robot_id,
    avg_motor_temp,
    max_motor_temp,
    battery_drain,
    active_hours,
    CASE WHEN max_motor_temp > 90.0 THEN 1 ELSE 0 END AS label
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
    # ... (폴링 로직)
    return f"{ATHENA_OUTPUT}{execution_id}.csv"


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
    import os
    data_uri = fetch_training_data()
    estimator = run_training_job(data_uri, os.environ["SAGEMAKER_ROLE_ARN"])
    estimator.deploy(
        initial_instance_count=1,
        instance_type="ml.t2.medium",
        endpoint_name="robot-failure-predictor",
    )

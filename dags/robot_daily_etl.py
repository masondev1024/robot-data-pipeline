from datetime import datetime, timedelta

import boto3
from airflow import DAG
from airflow.operators.python import PythonOperator, ShortCircuitOperator

S3_BUCKET = "de-ai-06-827913617635-ap-northeast-2-an"
ATHENA_DATABASE = "robot_telemetry_db"
ATHENA_WORKGROUP = "robot-telemetry-workgroup"
ATHENA_OUTPUT = f"s3://{S3_BUCKET}/project-athena-results/"

default_args = {
    "owner": "robot-telemetry",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="robot_daily_etl",
    default_args=default_args,
    description="Bronze→Silver→Gold ETL + Bedrock 리포트 + 주간 ML 재학습",
    schedule_interval="0 15 * * *",  # 매일 00:00 KST (UTC 15:00)
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["robot-telemetry", "etl"],
)


def _run_athena_query(query: str) -> str:
    """Athena 쿼리 실행 후 QueryExecutionId 반환."""
    client = boto3.client("athena", region_name="eu-west-1")
    response = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": ATHENA_DATABASE},
        WorkGroup=ATHENA_WORKGROUP,
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
    )
    execution_id = response["QueryExecutionId"]

    import time
    for _ in range(60):
        result = client.get_query_execution(QueryExecutionId=execution_id)
        state = result["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return execution_id
        if state in ("FAILED", "CANCELLED"):
            reason = result["QueryExecution"]["Status"].get("StateChangeReason", "unknown")
            raise RuntimeError(f"Athena query {state}: {reason}")
        time.sleep(2)

    raise TimeoutError("Athena query timed out after 120 seconds")


def _bronze_to_silver(**ctx):
    """이상치 제거·중복 제거·타입 Casting 후 Silver 테이블에 INSERT OVERWRITE."""
    execution_date = ctx["execution_date"]
    dt = execution_date.strftime("%Y-%m-%d")

    query = f"""
INSERT INTO silver_robot_telemetry
SELECT
    robot_id,
    CAST(pos_x AS DOUBLE)          AS pos_x,
    CAST(pos_y AS DOUBLE)          AS pos_y,
    CAST(battery_level AS INTEGER) AS battery_level,
    CAST(current_load AS INTEGER)  AS current_load,
    CAST(motor_temp AS DOUBLE)     AS motor_temp,
    timestamp,
    '{dt}'                         AS dt
FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY robot_id, timestamp ORDER BY timestamp) AS rn
    FROM bronze_robot_telemetry
    WHERE dt = '{dt}'
      AND robot_id IS NOT NULL
      AND battery_level BETWEEN 0 AND 100
      AND motor_temp BETWEEN 0 AND 500
      AND timestamp IS NOT NULL
) deduped
WHERE rn = 1
"""
    _run_athena_query(query)


def _silver_to_gold(**ctx):
    """일별/로봇별 집계 후 Gold 테이블에 INSERT OVERWRITE."""
    execution_date = ctx["execution_date"]
    dt = execution_date.strftime("%Y-%m-%d")

    query = f"""
INSERT INTO gold_robot_daily_stats
SELECT
    robot_id,
    AVG(motor_temp)                                              AS avg_motor_temp,
    MAX(motor_temp)                                              AS max_motor_temp,
    MAX(battery_level)                                           AS battery_start,
    MIN(battery_level)                                           AS battery_end,
    MAX(battery_level) - MIN(battery_level)                      AS battery_drain,
    CAST(COUNT(*) AS DOUBLE) / 86400.0                           AS operation_ratio,
    MAX(battery_level) - MIN(battery_level)                      AS battery_drain_rate,
    '{dt}'                                                       AS dt
FROM silver_robot_telemetry
WHERE dt = '{dt}'
GROUP BY robot_id
"""
    _run_athena_query(query)


def _bedrock_report(**ctx):
    """Gold 데이터 기반 Bedrock 정비 리포트 생성 후 S3에 저장."""
    import json
    execution_date = ctx["execution_date"]
    dt = execution_date.strftime("%Y-%m-%d")

    athena = boto3.client("athena", region_name="eu-west-1")
    query = f"""
SELECT robot_id, avg_motor_temp, max_motor_temp, battery_drain_rate, operation_ratio
FROM gold_robot_daily_stats
WHERE dt = '{dt}'
ORDER BY avg_motor_temp DESC
LIMIT 20
"""
    execution_id = _run_athena_query(query)
    paginator = athena.get_paginator("get_query_results")
    rows = []
    columns = None
    for page in paginator.paginate(QueryExecutionId=execution_id):
        result_rows = page["ResultSet"]["Rows"]
        if columns is None:
            columns = [col["VarCharValue"] for col in result_rows[0]["Data"]]
            result_rows = result_rows[1:]
        for row in result_rows:
            values = [cell.get("VarCharValue", "") for cell in row["Data"]]
            rows.append(dict(zip(columns, values)))

    data_summary = "\n".join(
        f"{r['robot_id']}: 평균온도={r['avg_motor_temp']}°C, 배터리소모율={r['battery_drain_rate']}"
        for r in rows
    )
    prompt = (
        f"다음은 오늘 공장 로봇들의 상태 지표야.\n{data_summary}\n\n"
        "이를 분석해서 가장 점검이 시급한 로봇 3대와 그 이유를 정비반장에게 보내는 형식으로 300자 이내로 요약해."
    )

    bedrock = boto3.client("bedrock-runtime", region_name="eu-west-1")
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": prompt}],
    })
    response = bedrock.invoke_model(
        modelId="anthropic.claude-3-haiku-20240307-v1:0",
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    report_text = json.loads(response["body"].read())["content"][0]["text"]

    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=f"reports/{dt}.txt",
        Body=report_text.encode("utf-8"),
    )


def _is_monday(**ctx):
    return ctx["execution_date"].weekday() == 0  # 월요일만 실행


def _retrain_model(**ctx):
    import subprocess
    subprocess.run(["python", "src/ml/train.py"], check=True)


bronze_to_silver = PythonOperator(
    task_id="bronze_to_silver",
    python_callable=_bronze_to_silver,
    dag=dag,
)

silver_to_gold = PythonOperator(
    task_id="silver_to_gold",
    python_callable=_silver_to_gold,
    dag=dag,
)

bedrock_report = PythonOperator(
    task_id="bedrock_report",
    python_callable=_bedrock_report,
    dag=dag,
)

check_monday = ShortCircuitOperator(
    task_id="check_monday",
    python_callable=_is_monday,
    dag=dag,
)

retrain_model = PythonOperator(
    task_id="retrain_ml_model",
    python_callable=_retrain_model,
    dag=dag,
)

bronze_to_silver >> silver_to_gold >> bedrock_report >> check_monday >> retrain_model

import json
import os
from datetime import datetime, timedelta

import boto3
from airflow import DAG
from airflow.operators.python import PythonOperator

from src.common.athena import fetch_rows, start_query, wait_for_query
from src.common.bedrock import invoke_claude

S3_BUCKET = os.environ.get("S3_BUCKET_NAME", "robot-telemetry-data")
ATHENA_DATABASE = os.environ.get("ATHENA_DATABASE", "robot_telemetry_db")
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "robot-telemetry-workgroup")
ATHENA_OUTPUT = os.environ.get("ATHENA_OUTPUT_LOCATION", f"s3://{S3_BUCKET}/project-athena-results/")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-west-1")

DQ_FAILURE_RATIO_THRESHOLD = 0.01
BEDROCK_REPORT_TOP_N = 20

default_args = {
    "owner": "robot-telemetry",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="robot_daily_etl",
    default_args=default_args,
    description="Bronze→Silver→Gold ETL + Bedrock 리포트 (재학습은 weekly_ml_retrain DAG 로 분리)",
    schedule="0 15 * * *",  # 매일 00:00 KST (UTC 15:00). schedule_interval 은 Airflow 3 에서 제거 예정.
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["robot-telemetry", "etl"],
)


def _run_athena_query(query: str) -> str:
    """Athena 쿼리 실행 후 QueryExecutionId 반환."""
    client = boto3.client("athena", region_name=AWS_REGION)
    response = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": ATHENA_DATABASE},
        WorkGroup=ATHENA_WORKGROUP,
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
    )
    execution_id = response["QueryExecutionId"]
    wait_for_query(execution_id)
    return execution_id


def evaluate_quality(
    total: int,
    null_id: int,
    bad_temp: int,
    bad_battery: int,
    bad_failure_type: int = 0,
) -> list[str]:
    """Bronze 품질 게이트 평가. 빈 리스트 = 통과.

    Task 8.6: bad_failure_type — failure_type ∉ {NONE,TWF,HDF,PWF,OSF,RNF} 건수
    (NULL은 silver 변환 시 'NONE' 으로 fill 되므로 제외).
    """
    if total == 0:
        return ["레코드 0건"]

    failures = []
    if null_id / total >= DQ_FAILURE_RATIO_THRESHOLD:
        failures.append(f"robot_id null 비율 {null_id/total:.2%}")
    if bad_temp / total >= DQ_FAILURE_RATIO_THRESHOLD:
        failures.append(f"motor_temp 이상치 비율 {bad_temp/total:.2%}")
    if bad_battery / total >= DQ_FAILURE_RATIO_THRESHOLD:
        failures.append(f"battery_level 이상치 비율 {bad_battery/total:.2%}")
    if bad_failure_type / total >= DQ_FAILURE_RATIO_THRESHOLD:
        failures.append(f"failure_type enum 이탈 비율 {bad_failure_type/total:.2%}")
    return failures


def _publish_dq_failure(detail: str):
    """SNS robot-anomaly-alerts 토픽으로 DQ 실패 알림 발송."""
    sns = boto3.client("sns", region_name=AWS_REGION)
    topic_arn = os.environ.get(
        "DQ_SNS_TOPIC_ARN",
        f"arn:aws:sns:{AWS_REGION}:{os.environ.get('AWS_ACCOUNT_ID', '')}:robot-anomaly-alerts",
    )
    sns.publish(
        TopicArn=topic_arn,
        Subject="[Robot ETL] 데이터 품질 검사 실패",
        Message=f"Bronze 단계 품질 게이트 실패: {detail}",
    )


def _quality_check(**ctx):
    """Bronze 데이터 품질 게이트. 임계 위반 시 SNS 알림 + AirflowException."""
    from airflow.exceptions import AirflowException

    execution_date = ctx["execution_date"]
    year, month, day = execution_date.year, execution_date.month, execution_date.day

    query = f"""
SELECT
    COUNT(*)                                                            AS total_count,
    SUM(CASE WHEN robot_id IS NULL THEN 1 ELSE 0 END)                   AS null_robot_id,
    SUM(CASE WHEN motor_temp NOT BETWEEN 0 AND 500 THEN 1 ELSE 0 END)   AS bad_temp,
    SUM(CASE WHEN battery_level NOT BETWEEN 0 AND 100 THEN 1 ELSE 0 END) AS bad_battery,
    SUM(CASE WHEN failure_type IS NOT NULL
                  AND failure_type NOT IN ('NONE','TWF','HDF','PWF','OSF','RNF')
             THEN 1 ELSE 0 END)                                          AS bad_failure_type
FROM bronze_robot_telemetry
WHERE year = '{year:04d}' AND month = '{month:02d}' AND day = '{day:02d}'
"""
    execution_id = _run_athena_query(query)

    athena = boto3.client("athena", region_name=AWS_REGION)
    rows = athena.get_query_results(QueryExecutionId=execution_id)["ResultSet"]["Rows"]
    values = [cell.get("VarCharValue", "0") for cell in rows[1]["Data"]]
    total, null_id, bad_temp, bad_battery, bad_failure_type = (int(v) for v in values)

    failures = evaluate_quality(total, null_id, bad_temp, bad_battery, bad_failure_type)
    if failures:
        msg = "; ".join(failures)
        _publish_dq_failure(msg)
        raise AirflowException(f"Data quality check failed: {msg}")


def _delete_s3_partition(prefix: str) -> int:
    """[멱등성] S3 prefix 하위 모든 객체 삭제. Athena INSERT INTO 전 호출하여
    재실행 시 동일 파티션 중복 누적을 방지한다 (INSERT OVERWRITE 대체)."""
    s3 = boto3.client("s3", region_name=AWS_REGION)
    paginator = s3.get_paginator("list_objects_v2")
    deleted = 0
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        contents = page.get("Contents", [])
        if not contents:
            continue
        objects = [{"Key": obj["Key"]} for obj in contents]
        s3.delete_objects(Bucket=S3_BUCKET, Delete={"Objects": objects, "Quiet": True})
        deleted += len(objects)
    if deleted:
        print(f"[idempotency] Deleted {deleted} objects under s3://{S3_BUCKET}/{prefix}")
    return deleted


def _bronze_to_silver(**ctx):
    """이상치 제거·중복 제거·타입 Casting 후 Silver 테이블에 INSERT (멱등)."""
    execution_date = ctx["execution_date"]
    dt = execution_date.strftime("%Y-%m-%d")
    year, month, day = execution_date.year, execution_date.month, execution_date.day

    _delete_s3_partition(f"silver/dt={dt}/")

    # Task 8.1/8.6: failure_type NULL → 'NONE' fill (backward compat: v1 schema 송출 데이터)
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
    COALESCE(failure_type, 'NONE') AS failure_type,
    DATE '{dt}'                    AS dt
FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY robot_id, timestamp ORDER BY timestamp) AS rn
    FROM bronze_robot_telemetry
    WHERE year = '{year:04d}' AND month = '{month:02d}' AND day = '{day:02d}'
      AND robot_id IS NOT NULL
      AND battery_level BETWEEN 0 AND 100
      AND motor_temp BETWEEN 0 AND 500
      AND timestamp IS NOT NULL
) deduped
WHERE rn = 1
"""
    _run_athena_query(query)


def _silver_to_gold(**ctx):
    """일별/로봇별 집계 후 Gold 테이블에 INSERT (멱등)."""
    execution_date = ctx["execution_date"]
    dt = execution_date.strftime("%Y-%m-%d")

    _delete_s3_partition(f"gold/dt={dt}/")

    # Task 8.1: dominant_failure_type — 일일 최빈 failure_type (NONE 제외 후 mode).
    # 모든 record 가 NONE 이면 'NONE'. Athena Trino: array_agg + filter 패턴 사용
    # (Trino 는 MODE() 함수 미지원).
    query = f"""
INSERT INTO gold_robot_daily_stats
SELECT
    s.robot_id,
    AVG(s.motor_temp)                                                                     AS avg_motor_temp,
    MAX(s.motor_temp)                                                                     AS max_motor_temp,
    MAX(s.battery_level)                                                                  AS battery_start,
    MIN(s.battery_level)                                                                  AS battery_end,
    MAX(s.battery_level) - MIN(s.battery_level)                                           AS battery_drain,
    CAST(COUNT(DISTINCT date_trunc('hour', from_iso8601_timestamp(s.timestamp))) AS INTEGER) AS active_hours,
    CAST(COUNT(CASE WHEN s.motor_temp >= 92.0
                      AND s.motor_temp / GREATEST(CAST(s.current_load AS DOUBLE), 1.0) > 2.5
                    THEN 1 END) AS INTEGER)                                                AS anomaly_record_count,
    MAX(s.motor_temp / GREATEST(CAST(s.current_load AS DOUBLE), 1.0))                      AS max_temp_load_ratio,
    COALESCE(
        (SELECT failure_type
         FROM silver_robot_telemetry s2
         WHERE s2.dt = DATE '{dt}' AND s2.robot_id = s.robot_id
           AND s2.failure_type <> 'NONE'
         GROUP BY failure_type
         ORDER BY COUNT(*) DESC
         LIMIT 1),
        'NONE'
    )                                                                                      AS dominant_failure_type,
    DATE '{dt}'                                                                            AS dt
FROM silver_robot_telemetry s
WHERE s.dt = DATE '{dt}'
GROUP BY s.robot_id
"""
    _run_athena_query(query)


def _refresh_api_cache(**ctx):
    """robot-telemetry-api 의 Gold 캐시 즉시 재조회 트리거.
    Why: API pod 의 _gold_cache 는 startup + 매일 KST 01:00 cron 에만 갱신되어,
    pod 가 daily_etl 종료 전에 띄워졌을 경우 '(데이터 없음)' 으로 굳어 다음 cron 까지 stale.
    2026-05-07 사고 — 09:32 KST pod 시작 / 09:49 KST gold 적재 / 챗봇은 빈 응답.
    cluster-internal DNS 로 POST. /api/refresh 는 BasicAuth 면제 + rate limit 5/min."""
    import urllib.request
    import urllib.error

    api_url = os.environ.get(
        "ROBOT_API_REFRESH_URL",
        "http://robot-telemetry-api.robot-telemetry.svc.cluster.local/api/refresh",
    )
    req = urllib.request.Request(api_url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            print(f"[cache_refresh] {payload}")
            if payload.get("rows_after", 0) == 0:
                # gold partition 이 비어있는 비정상 — 경고만, fail 시키진 않음 (DAG 자체는 성공).
                print("[cache_refresh] WARN — rows_after=0, 적재 직후인데 캐시 비어있음")
    except urllib.error.URLError as e:
        # API 가 다운돼 있어도 ETL 자체는 끝났으므로 fail 시키지 않는다 — 다음 pod 재시작이나
        # KST 01:00 cron 이 자연 복구. 단 로그로 표시.
        print(f"[cache_refresh] WARN — refresh 호출 실패: {e}. 다음 cron 까지 stale 가능.")


def _bedrock_report(**ctx):
    """Gold 데이터 기반 Bedrock 정비 리포트 생성 후 S3에 저장."""
    execution_date = ctx["execution_date"]
    dt = execution_date.strftime("%Y-%m-%d")

    query = f"""
SELECT robot_id, avg_motor_temp, max_motor_temp, battery_drain, active_hours
FROM gold_robot_daily_stats
WHERE dt = DATE '{dt}'
ORDER BY avg_motor_temp DESC
LIMIT {BEDROCK_REPORT_TOP_N}
"""
    execution_id = _run_athena_query(query)
    rows = fetch_rows(execution_id)

    data_summary = "\n".join(
        f"{r['robot_id']}: 평균온도={r['avg_motor_temp']}°C, 최고온도={r['max_motor_temp']}°C, "
        f"배터리소모={r['battery_drain']}, 가동시간={r['active_hours']}h"
        for r in rows
    )
    system_prompt = (
        "당신은 한국 스마트 팩토리 정비반장에게 보내는 일별 리포트를 작성하는 분석가입니다. "
        "주어진 로봇 텔레메트리 지표를 바탕으로, 점검이 가장 시급한 로봇 3대와 그 이유를 markdown 으로 요약합니다. "
        "로봇 ID 는 [ROBOT-XXXXX] 형식으로 표기하고, 수치 인용 시 컬럼명(avg_motor_temp, max_motor_temp, battery_drain, active_hours)을 명시합니다. "
        "본문 300자 이내, 추측 금지, 데이터에 명시되지 않은 정보는 인용하지 않습니다."
    )
    prompt = (
        f"<gold_data>\n{data_summary}\n</gold_data>\n\n"
        "위 데이터에서 점검이 가장 시급한 로봇 3대와 그 이유를 정비반장 보고 형식으로 요약하세요."
    )

    model_id = os.environ.get(
        "BEDROCK_MODEL_ID",
        "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
    )
    # cache_system=False — 본 함수는 daily 1회 호출이라 5분 TTL 캐시 적중 불가.
    # ADR-012 의 caching 패턴은 chat API(고빈도) 에 적용.
    report_text = invoke_claude(
        prompt,
        system=system_prompt,
        max_tokens=512,
        model_id=model_id,
        cache_system=False,
    )

    s3 = boto3.client("s3", region_name=AWS_REGION)
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=f"reports/{dt}.txt",
        Body=report_text.encode("utf-8"),
    )


quality_check = PythonOperator(
    task_id="quality_check",
    python_callable=_quality_check,
    dag=dag,
)

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

cache_refresh = PythonOperator(
    task_id="cache_refresh",
    python_callable=_refresh_api_cache,
    dag=dag,
    # silver_to_gold 직후가 의미적으로 맞지만 bedrock_report 가 같은 gold 데이터를 쓰므로
    # 둘 다 끝난 뒤 마지막에 한 번만 호출. bedrock_report 실패 시 cache_refresh 도 skip 되는데
    # 이 경우 ETL 자체는 silver_to_gold 까지 성공했으므로 retry 또는 다음 cron 으로 자연 복구.
)

quality_check >> bronze_to_silver >> silver_to_gold >> bedrock_report >> cache_refresh

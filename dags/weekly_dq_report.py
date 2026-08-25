"""주간 데이터 품질 리포트 DAG — 7일 추세 + Bedrock 요약 + Slack 발행.

robot_daily_etl 의 quality_check 는 단일 게이트(pass/fail)일 뿐 추세를 못 잡는다.
이 DAG 는 한 주 마감 직후(일 23:00 KST = 14:00 UTC) bronze/silver/gold 의
- 일별 row count
- null 비율
- failure_type 분포
를 집계하여 Claude 3.5 Sonnet으로 markdown 요약 → S3 저장 → Slack 발행 → 회귀 시 SNS 알림.

XCom 회피: 각 query 결과는 S3 staging path 에 JSON 으로 떨어지고 다음 task 가 path 만 받음.
멱등성: staging prefix 는 매 실행마다 사전 삭제 후 write.
파티션 프루닝: 모든 Athena WHERE 절에 dt/year/month/day 명시 (CLAUDE.md § 1.E).
"""
import json
import os
from datetime import datetime, timedelta

import boto3
import urllib.request
from airflow import DAG
from airflow.exceptions import AirflowException, AirflowSkipException
from airflow.operators.python import PythonOperator

from src.common.athena import fetch_rows, start_query, wait_for_query
from src.common.bedrock import invoke_claude

S3_BUCKET = os.environ.get("S3_BUCKET_NAME", "robot-telemetry-data")
ATHENA_DATABASE = os.environ.get("ATHENA_DATABASE", "robot_telemetry_db")
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "robot-telemetry-workgroup")
ATHENA_OUTPUT = os.environ.get("ATHENA_OUTPUT_LOCATION", f"s3://{S3_BUCKET}/project-athena-results/")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-2")

REPORT_PREFIX = "reports/weekly-dq"
STAGING_PREFIX = "reports/weekly-dq/_staging"  # task 간 path 전달 (멱등 사전 삭제)

# 회귀 임계값
NULL_RATIO_REGRESSION = 1.5  # 전 주 대비 null 비율 +50% 초과 시 alert
ROW_COUNT_REGRESSION = 0.8  # 전 주 대비 row count 80% 미만(=20% 감소) 시 alert


default_args = {
    "owner": "robot-telemetry",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="weekly_dq_report",
    default_args=default_args,
    description="주간 DQ 추세 + Bedrock 요약 + Slack 발행 (Wed 23:00 KST)",
    # 매주 수요일 23:00 KST = 14:00 UTC. weekly_ml_retrain 과 2시간 간격(execution_delta) 유지.
    schedule="0 14 * * 3",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["robot-telemetry", "dq", "weekly"],
)


# ──────────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────────
def _delete_s3_prefix(prefix: str) -> int:
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


def _staging_key(execution_date: datetime, name: str) -> str:
    """주차별 staging key — week-of-year 단위로 격리."""
    week_tag = execution_date.strftime("%Yw%U")  # 예: 2026w18
    return f"{STAGING_PREFIX}/{week_tag}/{name}.json"


def _put_json(key: str, payload) -> str:
    s3 = boto3.client("s3", region_name=AWS_REGION)
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{S3_BUCKET}/{key}"


def _get_json(key: str):
    s3 = boto3.client("s3", region_name=AWS_REGION)
    body = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read().decode("utf-8")
    return json.loads(body)


def _run_athena(query: str) -> list[dict]:
    execution_id = start_query(
        query,
        database=ATHENA_DATABASE,
        workgroup=ATHENA_WORKGROUP,
        output_location=ATHENA_OUTPUT,
    )
    wait_for_query(execution_id)
    return fetch_rows(execution_id)


def _week_window(execution_date: datetime) -> tuple[str, str, str, str]:
    """이번 주 / 직전 주 7일 윈도우 (모두 inclusive 시작/종료)."""
    end_dt = execution_date.date()
    this_start = end_dt - timedelta(days=6)
    prev_end = this_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    return (this_start.isoformat(), end_dt.isoformat(),
            prev_start.isoformat(), prev_end.isoformat())


# ──────────────────────────────────────────────────────────────────────────────
# 1. query_layer_rowcounts — bronze/silver/gold 7일치 일별 row count
# ──────────────────────────────────────────────────────────────────────────────
def _query_layer_rowcounts(**ctx):
    execution_date = ctx["execution_date"]
    this_start, this_end, prev_start, prev_end = _week_window(execution_date)

    # bronze: varchar partition (year/month/day) — 가드레일 § 1.E.
    # 14일 윈도우(이번 주 + 전 주) 한 번에 fetch — 비교용.
    bronze_q = f"""
SELECT 'bronze' AS layer,
       year, month, day,
       COUNT(*) AS row_count
FROM bronze_robot_telemetry
WHERE date_parse(year || '-' || month || '-' || day, '%Y-%m-%d')
      BETWEEN date '{prev_start}' AND date '{this_end}'
GROUP BY year, month, day
"""
    silver_q = f"""
SELECT 'silver' AS layer,
       CAST(year(dt) AS VARCHAR)  AS year,
       LPAD(CAST(month(dt) AS VARCHAR), 2, '0') AS month,
       LPAD(CAST(day(dt) AS VARCHAR), 2, '0')   AS day,
       COUNT(*) AS row_count
FROM silver_robot_telemetry
WHERE dt BETWEEN date '{prev_start}' AND date '{this_end}'
GROUP BY dt
"""
    gold_q = f"""
SELECT 'gold' AS layer,
       CAST(year(dt) AS VARCHAR)  AS year,
       LPAD(CAST(month(dt) AS VARCHAR), 2, '0') AS month,
       LPAD(CAST(day(dt) AS VARCHAR), 2, '0')   AS day,
       COUNT(*) AS row_count
FROM gold_robot_daily_stats
WHERE dt BETWEEN date '{prev_start}' AND date '{this_end}'
GROUP BY dt
"""

    rows = []
    for q in (bronze_q, silver_q, gold_q):
        rows.extend(_run_athena(q))

    payload = {
        "this_week": {"start": this_start, "end": this_end},
        "prev_week": {"start": prev_start, "end": prev_end},
        "rows": rows,
    }

    key = _staging_key(execution_date, "rowcounts")
    _delete_s3_prefix(key)  # 단일 객체지만 same-key overwrite 도 멱등
    uri = _put_json(key, payload)
    return {"s3_key": key, "s3_uri": uri}


query_layer_rowcounts = PythonOperator(
    task_id="query_layer_rowcounts",
    python_callable=_query_layer_rowcounts,
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# 2. query_null_trends — motor_temp / battery_level / failure_type null 비율 추세
# ──────────────────────────────────────────────────────────────────────────────
def _query_null_trends(**ctx):
    execution_date = ctx["execution_date"]
    this_start, this_end, prev_start, prev_end = _week_window(execution_date)

    # bronze 기준 — null 은 silver 변환 단계에서 fill 되므로 source 단계 검사.
    q = f"""
SELECT
    year, month, day,
    COUNT(*)                                                             AS total,
    SUM(CASE WHEN motor_temp IS NULL THEN 1 ELSE 0 END)                  AS null_motor_temp,
    SUM(CASE WHEN battery_level IS NULL THEN 1 ELSE 0 END)               AS null_battery,
    SUM(CASE WHEN failure_type IS NULL THEN 1 ELSE 0 END)                AS null_failure_type
FROM bronze_robot_telemetry
WHERE date_parse(year || '-' || month || '-' || day, '%Y-%m-%d')
      BETWEEN date '{prev_start}' AND date '{this_end}'
GROUP BY year, month, day
ORDER BY year, month, day
"""
    rows = _run_athena(q)
    payload = {
        "this_week": {"start": this_start, "end": this_end},
        "prev_week": {"start": prev_start, "end": prev_end},
        "rows": rows,
    }

    key = _staging_key(execution_date, "null_trends")
    uri = _put_json(key, payload)
    return {"s3_key": key, "s3_uri": uri}


query_null_trends = PythonOperator(
    task_id="query_null_trends",
    python_callable=_query_null_trends,
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# 3. query_failure_distribution — failure_type 분포 + 전 주 대비 % 변화
# ──────────────────────────────────────────────────────────────────────────────
def _query_failure_distribution(**ctx):
    execution_date = ctx["execution_date"]
    this_start, this_end, prev_start, prev_end = _week_window(execution_date)

    # silver 기준 (NONE 으로 fill 된 후) — daily ETL 의 silver 가 일관된 분포 source.
    q = f"""
SELECT
    CASE WHEN dt BETWEEN date '{this_start}' AND date '{this_end}' THEN 'this_week'
         ELSE 'prev_week' END                                              AS window,
    failure_type,
    COUNT(*)                                                               AS cnt
FROM silver_robot_telemetry
WHERE dt BETWEEN date '{prev_start}' AND date '{this_end}'
GROUP BY 1, failure_type
"""
    rows = _run_athena(q)
    payload = {
        "this_week": {"start": this_start, "end": this_end},
        "prev_week": {"start": prev_start, "end": prev_end},
        "rows": rows,
    }
    key = _staging_key(execution_date, "failure_distribution")
    uri = _put_json(key, payload)
    return {"s3_key": key, "s3_uri": uri}


query_failure_distribution = PythonOperator(
    task_id="query_failure_distribution",
    python_callable=_query_failure_distribution,
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# 4. generate_report_bedrock — Claude 3.5 Sonnet markdown 요약
# ──────────────────────────────────────────────────────────────────────────────
def _generate_report_bedrock(**ctx):
    ti = ctx["ti"]
    rc_meta = ti.xcom_pull(task_ids="query_layer_rowcounts")
    nt_meta = ti.xcom_pull(task_ids="query_null_trends")
    fd_meta = ti.xcom_pull(task_ids="query_failure_distribution")

    rowcounts = _get_json(rc_meta["s3_key"])
    null_trends = _get_json(nt_meta["s3_key"])
    failure_dist = _get_json(fd_meta["s3_key"])

    # 데이터 요약은 압축해서 prompt 에 — full row dump 회피.
    def _fmt(payload, title):
        return f"## {title}\n" + json.dumps(payload, ensure_ascii=False, default=str)[:3000]

    data_block = "\n\n".join([
        _fmt(rowcounts, "Layer Rowcounts (7d this vs prev)"),
        _fmt(null_trends, "Null Ratio Trends"),
        _fmt(failure_dist, "Failure Type Distribution"),
    ])

    system_prompt = (
        "당신은 한국 스마트 팩토리 데이터 엔지니어링 팀에 보내는 주간 데이터 품질 리포트를 작성합니다. "
        "주어진 JSON 지표만 인용하여 markdown 으로 요약합니다. "
        "섹션: (1) 한 줄 요약 (2) Layer 별 row count 추세 (3) null 비율 회귀 여부 (4) failure_type 분포 변화. "
        "추측 금지, 데이터에 명시되지 않은 정보는 인용하지 않습니다. 본문 600자 이내."
    )
    prompt = (
        f"<weekly_dq_data>\n{data_block}\n</weekly_dq_data>\n\n"
        "위 데이터로 주간 데이터 품질 리포트를 작성하세요."
    )

    model_id = os.environ.get(
        "BEDROCK_MODEL_ID",
        "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
    )
    report_md = invoke_claude(
        prompt,
        system=system_prompt,
        max_tokens=1024,
        model_id=model_id,
        cache_system=False,
    )

    execution_date = ctx["execution_date"]
    key = _staging_key(execution_date, "report")
    # markdown 자체는 별도 key 로 저장 (publish_to_s3 가 최종 path 로 옮김)
    s3 = boto3.client("s3", region_name=AWS_REGION)
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key.replace(".json", ".md"),
        Body=report_md.encode("utf-8"),
        ContentType="text/markdown",
    )
    return {"s3_key": key.replace(".json", ".md"), "preview": report_md[:200]}


generate_report_bedrock = PythonOperator(
    task_id="generate_report_bedrock",
    python_callable=_generate_report_bedrock,
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# 5. publish_to_s3 — 최종 리포트 path: reports/weekly-dq/year=/month=/week=/report.md
# ──────────────────────────────────────────────────────────────────────────────
def _publish_to_s3(**ctx):
    execution_date = ctx["execution_date"]
    rep_meta = ctx["ti"].xcom_pull(task_ids="generate_report_bedrock")
    src_key = rep_meta["s3_key"]

    year = execution_date.strftime("%Y")
    month = execution_date.strftime("%m")
    week = execution_date.strftime("%U")
    final_prefix = f"{REPORT_PREFIX}/year={year}/month={month}/week={week}/"
    final_key = f"{final_prefix}report.md"

    # 멱등성: 동일 주차 final prefix 사전 삭제 후 copy
    _delete_s3_prefix(final_prefix)

    s3 = boto3.client("s3", region_name=AWS_REGION)
    s3.copy_object(
        Bucket=S3_BUCKET,
        CopySource={"Bucket": S3_BUCKET, "Key": src_key},
        Key=final_key,
        ContentType="text/markdown",
        MetadataDirective="REPLACE",
    )
    final_uri = f"s3://{S3_BUCKET}/{final_key}"
    print(f"[publish_to_s3] {final_uri}")
    return {"s3_uri": final_uri, "s3_key": final_key}


publish_to_s3 = PythonOperator(
    task_id="publish_to_s3",
    python_callable=_publish_to_s3,
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# 6. publish_to_slack — Slack webhook 발행 (URL 은 env 에서, 하드코딩 금지)
# ──────────────────────────────────────────────────────────────────────────────
def _publish_to_slack(**ctx):
    """Slack webhook URL 은 SLACK_WEBHOOK_URL env 에서만 읽음 (가드레일 § 1.B)."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        # 환경상 webhook 없음 — skip (CI / 비용 셧다운 시 흔함)
        raise AirflowSkipException("SLACK_WEBHOOK_URL env 미설정 — 발행 스킵")

    rep_meta = ctx["ti"].xcom_pull(task_ids="generate_report_bedrock")
    pub_meta = ctx["ti"].xcom_pull(task_ids="publish_to_s3")

    payload = {
        "text": (
            "*[Robot Telemetry] 주간 데이터 품질 리포트*\n"
            f"S3: `{pub_meta['s3_uri']}`\n"
            f"```\n{rep_meta['preview']}\n```"
        )
    }
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status >= 300:
            raise AirflowException(f"Slack webhook returned {resp.status}")
    print("[publish_to_slack] OK")


publish_to_slack = PythonOperator(
    task_id="publish_to_slack",
    python_callable=_publish_to_slack,
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# 7. alert_on_regression — 전 주 대비 회귀 시만 SNS 발행
# ──────────────────────────────────────────────────────────────────────────────
def _detect_regression(rowcounts: dict, null_trends: dict) -> list[str]:
    """회귀 사유 리스트 반환. 빈 리스트면 정상."""
    issues: list[str] = []
    this_w = (rowcounts["this_week"]["start"], rowcounts["this_week"]["end"])
    prev_w = (rowcounts["prev_week"]["start"], rowcounts["prev_week"]["end"])

    def _sum_rows(rows, layer, window):
        total = 0
        for r in rows:
            if r.get("layer") != layer:
                continue
            ymd = f"{r['year']}-{r['month']}-{r['day']}"
            if window[0] <= ymd <= window[1]:
                total += int(r.get("row_count", 0) or 0)
        return total

    for layer in ("bronze", "silver", "gold"):
        this_sum = _sum_rows(rowcounts["rows"], layer, this_w)
        prev_sum = _sum_rows(rowcounts["rows"], layer, prev_w)
        if prev_sum > 0 and this_sum / prev_sum < ROW_COUNT_REGRESSION:
            issues.append(
                f"{layer} row count 회귀: this={this_sum}, prev={prev_sum} "
                f"(ratio={this_sum/prev_sum:.2f} < {ROW_COUNT_REGRESSION})"
            )

    # null 비율 회귀
    def _avg_null_ratio(rows, window, col):
        total_records = 0
        total_nulls = 0
        for r in rows:
            ymd = f"{r['year']}-{r['month']}-{r['day']}"
            if window[0] <= ymd <= window[1]:
                total_records += int(r.get("total", 0) or 0)
                total_nulls += int(r.get(col, 0) or 0)
        return (total_nulls / total_records) if total_records else 0.0

    for col in ("null_motor_temp", "null_battery", "null_failure_type"):
        this_r = _avg_null_ratio(null_trends["rows"], this_w, col)
        prev_r = _avg_null_ratio(null_trends["rows"], prev_w, col)
        if prev_r > 0 and this_r / prev_r > NULL_RATIO_REGRESSION:
            issues.append(
                f"{col} null 비율 회귀: this={this_r:.4f}, prev={prev_r:.4f} "
                f"(ratio={this_r/prev_r:.2f} > {NULL_RATIO_REGRESSION})"
            )
    return issues


def _alert_on_regression(**ctx):
    ti = ctx["ti"]
    rc_meta = ti.xcom_pull(task_ids="query_layer_rowcounts")
    nt_meta = ti.xcom_pull(task_ids="query_null_trends")
    rowcounts = _get_json(rc_meta["s3_key"])
    null_trends = _get_json(nt_meta["s3_key"])

    issues = _detect_regression(rowcounts, null_trends)
    if not issues:
        print("[alert_on_regression] no regression detected — skip SNS")
        raise AirflowSkipException("no regression")

    sns = boto3.client("sns", region_name=AWS_REGION)
    topic_arn = os.environ.get(
        "DQ_SNS_TOPIC_ARN",
        f"arn:aws:sns:{AWS_REGION}:{os.environ.get('AWS_ACCOUNT_ID', '')}:robot-anomaly-alerts",
    )
    sns.publish(
        TopicArn=topic_arn,
        Subject="[Robot DQ] 주간 회귀 감지",
        Message="weekly_dq_report 회귀 사유:\n- " + "\n- ".join(issues),
    )
    print(f"[alert_on_regression] published {len(issues)} issues")


alert_on_regression = PythonOperator(
    task_id="alert_on_regression",
    python_callable=_alert_on_regression,
    # publish_to_slack 와 무관하게 항상 실행 — 회귀 감지는 발행 성공/실패와 별개.
    trigger_rule="all_done",
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# Topology
# ──────────────────────────────────────────────────────────────────────────────
[query_layer_rowcounts, query_null_trends, query_failure_distribution] >> generate_report_bedrock
generate_report_bedrock >> publish_to_s3 >> publish_to_slack >> alert_on_regression

"""주간 ML 재학습 DAG — robot-failure-predictor SageMaker endpoint 재배포.

Phase 5 분리: 기존 robot_daily_etl 의 ShortCircuitOperator 패턴(`check_monday`)을
ExternalTaskSensor 기반 별도 DAG 로 떼어내 의존성·재시도·sensor 학습용 토폴로지 강화.

스케줄: 매주 목요일 KST 02:00 (UTC 수요일 17:00).
       robot_daily_etl 이 KST 00:00(UTC 15:00) 시작 → ~2시간 여유 후 그날 Gold 파티션이
       확실히 적재된 상태에서 학습 시작.

토폴로지:
    wait_for_daily_etl (ExternalTaskSensor: silver_to_gold 완료 대기)
        >> fetch_training_data (Athena → S3 학습 prefix)
        >> validate_rowcount (BranchPythonOperator)
            ├─ row >= MIN_ROWS  → train_xgboost (retries=1)
            └─ row <  MIN_ROWS  → skip_train_alert (SNS)
        >> deploy_endpoint (멱등 cleanup + deploy, retries=1)
        >> verify_prediction (sample inference, 실패 시 SNS 수동 롤백 안내)

XCom 회피: task 간 큰 데이터는 S3 path 만 매개변수로 전달.
멱등성: S3 prefix delete 후 INSERT, endpoint 는 cleanup 후 deploy.
"""
import json
import os
from datetime import datetime, timedelta

import boto3
from airflow import DAG
from airflow.exceptions import AirflowException, AirflowSkipException
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.sensors.external_task import ExternalTaskSensor

from src.common.athena import fetch_rows, start_query, wait_for_query

S3_BUCKET = os.environ.get("S3_BUCKET_NAME", "de-ai-06-smartfactory-bucket")
ATHENA_DATABASE = os.environ.get("ATHENA_DATABASE", "robot_telemetry_db")
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "robot-telemetry-workgroup")
ATHENA_OUTPUT = os.environ.get("ATHENA_OUTPUT_LOCATION", f"s3://{S3_BUCKET}/project-athena-results/")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-west-1")

MODEL_PREFIX = "ml-models/robot-failure-predictor"
ENDPOINT_NAME = "robot-failure-predictor"
TRAIN_STAGING_PREFIX = f"{MODEL_PREFIX}/train-staging"  # weekly DAG 전용 staging (멱등)
MIN_TRAINING_ROWS = 100  # 이 미만이면 학습 스킵 (overfitting 위험)

# SageMaker SDK 의 source_dir 은 worker pod CWD 기준 상대경로로 해석됨.
# DAG 는 /opt/airflow/dags/repo/dags/ 에 있고 worker CWD 는 /opt/airflow → 절대 경로 필요.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ML_SOURCE_DIR = os.path.join(_REPO_ROOT, "src", "ml")


default_args = {
    "owner": "robot-telemetry",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="weekly_ml_retrain",
    default_args=default_args,
    description="주간 SageMaker XGBoost 재학습 + endpoint 재배포 (Thu 02:00 KST)",
    # 매주 수요일 17:00 UTC = 목요일 02:00 KST. daily ETL(15:00 UTC) 후 2시간 여유.
    schedule="0 17 * * 3",
    # start_date 가 과거이면 catchup=False 여도 scheduler 가 missing slot 1개를
    # 반복 trigger → 데이터 없던 시기(2026-04 이전) 의 weekly run 이 영구 fail
    # 루프. 2026-05-04 이후로 옮겨 첫 정상 schedule = 5/6(수) 이 되도록 차단.
    start_date=datetime(2026, 5, 4),
    catchup=False,
    tags=["robot-telemetry", "ml", "weekly"],
)


# ──────────────────────────────────────────────────────────────────────────────
# 1. ExternalTaskSensor — daily ETL 의 silver_to_gold 완료 대기
# ──────────────────────────────────────────────────────────────────────────────
# weekly_ml_retrain 의 logical date = 수요일 17:00 UTC
# robot_daily_etl       의 logical date = 같은 수요일 15:00 UTC (cron 0 15 * * *)
# → 같은 calendar day (UTC), 시간만 2시간 차이 → execution_delta = +2h.
# (Airflow logical date 비교: target_dttm = self_dttm - execution_delta)
WAIT_EXECUTION_DELTA = timedelta(hours=2)


wait_for_daily_etl = ExternalTaskSensor(
    task_id="wait_for_daily_etl",
    external_dag_id="robot_daily_etl",
    external_task_id="silver_to_gold",
    execution_delta=WAIT_EXECUTION_DELTA,
    mode="reschedule",  # poke 보다 worker slot 절약
    poke_interval=300,  # 5분
    timeout=60 * 60 * 2,  # 2시간 안에 안 끝나면 실패
    allowed_states=["success"],
    failed_states=["failed", "skipped"],
    # target dag_run 자체가 없으면 (scheduler down 등으로 누락) 즉시 fail.
    # 미설정 시 영원히 poke → 2h timeout 까지 worker slot 점유 + 진단 지연.
    # 2026-05-04 회귀 — robot_daily_etl 4/22 run 누락으로 sensor 가 2h timeout.
    check_existence=True,
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# 2. fetch_training_data — Athena 30일 Gold → S3 학습 CSV (멱등)
# ──────────────────────────────────────────────────────────────────────────────
# Class-imbalance 가중치는 train.py 의 LABEL_MAP/_MINORITY_WEIGHT 와 동일하게 유지.
# 파티션 프루닝: WHERE dt >= current_date - interval '30' day.
_MINORITY_WEIGHT = 50.0
_TRAINING_QUERY = f"""
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


def _delete_s3_prefix(prefix: str) -> int:
    """[멱등성] S3 prefix 하위 객체 일괄 삭제."""
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


def _fetch_training_data(**ctx):
    """Athena 결과 CSV 를 학습 staging prefix 로 복사. 결과 메타(S3 URI, row count)만 XCom."""
    execution_date = ctx["execution_date"]
    week_tag = execution_date.strftime("%Y%m%d")  # logical date 기준 주차 식별자

    # 멱등성: 같은 주차 staging prefix 재실행 시 사전 삭제
    staging_prefix = f"{TRAIN_STAGING_PREFIX}/week={week_tag}/"
    _delete_s3_prefix(staging_prefix)

    execution_id = start_query(
        _TRAINING_QUERY,
        database=ATHENA_DATABASE,
        workgroup=ATHENA_WORKGROUP,
        output_location=ATHENA_OUTPUT,
    )
    wait_for_query(execution_id)

    s3 = boto3.client("s3", region_name=AWS_REGION)
    raw_key = f"project-athena-results/{execution_id}.csv"
    body = s3.get_object(Bucket=S3_BUCKET, Key=raw_key)["Body"].read().decode("utf-8")
    lines = body.splitlines()
    header = lines[0] if lines else ""
    data_lines = lines[1:]

    headerless = "\n".join(data_lines)
    train_key = f"{staging_prefix}train.csv"
    s3.put_object(Bucket=S3_BUCKET, Key=train_key, Body=headerless.encode("utf-8"))

    train_uri = f"s3://{S3_BUCKET}/{train_key}"
    row_count = len(data_lines)
    print(f"[fetch_training_data] uri={train_uri} rows={row_count} header={header}")

    # 작은 메타만 XCom — S3 path + row count.
    return {"train_uri": train_uri, "row_count": row_count}


fetch_training_data = PythonOperator(
    task_id="fetch_training_data",
    python_callable=_fetch_training_data,
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# 3. validate_rowcount — Branch (학습 진행 vs 스킵 알림)
# ──────────────────────────────────────────────────────────────────────────────
def _validate_rowcount(**ctx):
    meta = ctx["ti"].xcom_pull(task_ids="fetch_training_data")
    if not meta:
        raise AirflowException("fetch_training_data meta missing")
    rows = int(meta.get("row_count", 0))
    print(f"[validate] row_count={rows} threshold={MIN_TRAINING_ROWS}")
    if rows >= MIN_TRAINING_ROWS:
        return "train_xgboost"
    return "skip_train_alert"


validate_rowcount = BranchPythonOperator(
    task_id="validate_rowcount",
    python_callable=_validate_rowcount,
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# 4a. skip_train_alert — 학습 데이터 부족 SNS 알림
# ──────────────────────────────────────────────────────────────────────────────
def _skip_train_alert(**ctx):
    meta = ctx["ti"].xcom_pull(task_ids="fetch_training_data") or {}
    rows = meta.get("row_count", 0)
    sns = boto3.client("sns", region_name=AWS_REGION)
    topic_arn = os.environ.get(
        "DQ_SNS_TOPIC_ARN",
        f"arn:aws:sns:{AWS_REGION}:{os.environ.get('AWS_ACCOUNT_ID', '')}:robot-anomaly-alerts",
    )
    sns.publish(
        TopicArn=topic_arn,
        Subject="[Robot ML] 주간 재학습 스킵 — 데이터 부족",
        Message=(
            f"weekly_ml_retrain: training rows={rows} < threshold={MIN_TRAINING_ROWS}. "
            "기존 endpoint 유지 (재배포 없음). 30일 Gold 파티션 적재 상태 확인 필요."
        ),
    )
    raise AirflowSkipException(f"training rows {rows} below threshold")


skip_train_alert = PythonOperator(
    task_id="skip_train_alert",
    python_callable=_skip_train_alert,
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# 4b. train_xgboost — SageMaker XGBoost 학습 (재시도 1회)
# ──────────────────────────────────────────────────────────────────────────────
def _train_xgboost(**ctx):
    """Staging CSV 를 입력으로 XGBoost 학습 → model.tar.gz S3 URI 반환."""
    # NOTE: sagemaker SDK(313MB) 는 worker pod 만 설치 (helm/airflow-values.yaml workers.env).
    # top-level import 하면 scheduler/webserver 도 DAG parse 시 import 시도 → ModuleNotFoundError.
    import sagemaker
    from sagemaker.xgboost import XGBoost

    from src.ml.train import FEATURE_COLUMNS, NUM_CLASSES  # noqa: F401 (학습 일관성 확인용)

    meta = ctx["ti"].xcom_pull(task_ids="fetch_training_data")
    train_uri = meta["train_uri"]
    role_arn = os.environ["SAGEMAKER_ROLE_ARN"]

    session = sagemaker.Session()
    estimator = XGBoost(
        entry_point="train_entry.py",
        source_dir=_ML_SOURCE_DIR,
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
        sagemaker_session=session,
    )
    estimator.fit({"train": train_uri})

    model_uri = estimator.model_data
    print(f"[train_xgboost] model_data={model_uri}")
    return {"model_data_uri": model_uri}


train_xgboost = PythonOperator(
    task_id="train_xgboost",
    python_callable=_train_xgboost,
    retries=1,
    retry_delay=timedelta(minutes=10),
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# 5. deploy_endpoint — 기존 endpoint cleanup 후 재배포 (멱등)
# ──────────────────────────────────────────────────────────────────────────────
def _deploy_endpoint(**ctx):
    from sagemaker.xgboost import XGBoostModel

    from src.ml.train import _cleanup_existing_endpoint

    meta = ctx["ti"].xcom_pull(task_ids="train_xgboost")
    if not meta:
        raise AirflowException("train_xgboost output missing — upstream may have skipped")
    model_data = meta["model_data_uri"]
    role_arn = os.environ["SAGEMAKER_ROLE_ARN"]

    # default_bucket override — SDK 의 sagemaker-{region}-{account} 자동 버킷 회피.
    # 권한은 datalake 버킷에만 있으므로 모든 SageMaker 부산물(source.tar.gz 등)을 여기로.
    import sagemaker as _sm
    session = _sm.Session(default_bucket=S3_BUCKET)
    model = XGBoostModel(
        model_data=model_data,
        role=role_arn,
        entry_point="train_entry.py",
        source_dir=_ML_SOURCE_DIR,
        framework_version="1.7-1",
        sagemaker_session=session,
    )
    _cleanup_existing_endpoint(ENDPOINT_NAME)  # 멱등성: 기존 endpoint+config 제거 후 deploy
    model.deploy(
        initial_instance_count=1,
        instance_type="ml.t2.medium",
        endpoint_name=ENDPOINT_NAME,
    )
    print(f"[deploy_endpoint] endpoint={ENDPOINT_NAME} model_data={model_data}")


deploy_endpoint = PythonOperator(
    task_id="deploy_endpoint",
    python_callable=_deploy_endpoint,
    retries=1,
    retry_delay=timedelta(minutes=5),
    # train_xgboost 가 skip 되면 자동 skip — branch 로 already 차단되므로 default trigger_rule.
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# 6. verify_prediction — 배포 직후 sample inference, 실패 시 SNS 수동 롤백 안내
# ──────────────────────────────────────────────────────────────────────────────
def _verify_prediction(**ctx):
    """샘플 1건 invoke. 실패 시 SNS 알림 + 예외.
    TODO(v2): 자동 롤백 (직전 EndpointConfig 보존 + delete_endpoint 시 재생성).
    """
    sm_runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)

    # FEATURE_COLUMNS 순서(avg_motor_temp, max_motor_temp, battery_drain, active_hours,
    # max_temp_load_ratio) 와 일치하는 정상 범위 sample 1건.
    sample_csv = "70.0,80.0,30.0,8,1.5"

    try:
        resp = sm_runtime.invoke_endpoint(
            EndpointName=ENDPOINT_NAME,
            ContentType="text/csv",
            Body=sample_csv.encode("utf-8"),
        )
        body = resp["Body"].read().decode("utf-8")
        print(f"[verify_prediction] sample_response={body[:200]}")

        # 응답 형식: JSON array 또는 CSV — 양쪽 지원 (가드레일 § 1.F).
        try:
            parsed = json.loads(body)
            if not isinstance(parsed, list) or not parsed:
                raise ValueError(f"unexpected JSON shape: {body[:80]}")
        except json.JSONDecodeError:
            # CSV fallback
            if not body.strip():
                raise ValueError("empty CSV response")
        return {"verified": True, "response_preview": body[:200]}

    except Exception as exc:  # noqa: BLE001 — alert 후 raise
        sns = boto3.client("sns", region_name=AWS_REGION)
        topic_arn = os.environ.get(
            "DQ_SNS_TOPIC_ARN",
            f"arn:aws:sns:{AWS_REGION}:{os.environ.get('AWS_ACCOUNT_ID', '')}:robot-anomaly-alerts",
        )
        sns.publish(
            TopicArn=topic_arn,
            Subject="[Robot ML] 재배포 직후 검증 실패 — 수동 롤백 필요",
            Message=(
                f"weekly_ml_retrain.verify_prediction failed: {exc}\n"
                f"endpoint={ENDPOINT_NAME}\n"
                "권장 조치: src/ml/redeploy.py 로 직전 model.tar.gz 재배포 또는 endpoint 삭제."
            ),
        )
        raise AirflowException(f"endpoint verification failed: {exc}")


verify_prediction = PythonOperator(
    task_id="verify_prediction",
    python_callable=_verify_prediction,
    retries=0,  # 검증 실패는 즉시 알림 — 재시도가 오히려 false negative 소비
    dag=dag,
)


# ──────────────────────────────────────────────────────────────────────────────
# Topology
# ──────────────────────────────────────────────────────────────────────────────
wait_for_daily_etl >> fetch_training_data >> validate_rowcount
validate_rowcount >> [train_xgboost, skip_train_alert]
train_xgboost >> deploy_endpoint >> verify_prediction

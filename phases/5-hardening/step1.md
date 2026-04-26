# Step 1: predictive-maintenance

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/terraform/modules/data_pipeline/iam.tf` (기존 IRSA 패턴)
- `/src/api/main.py` (FastAPI 기존 엔드포인트 구조)
- `/dags/robot_daily_etl.py` (DAG Task 추가 위치 파악)
- `/.harness_shadow/sql/gold_ddl.sql` (Gold 테이블 컬럼 확인)

## 작업

SageMaker XGBoost 고장 예측 모델 학습 파이프라인과 FastAPI 예측 엔드포인트를 구성하라.

### `terraform/modules/data_pipeline/sagemaker.tf`

```hcl
resource "aws_iam_role" "sagemaker" {
  name = "robot-telemetry-sagemaker-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sagemaker.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "sagemaker_full" {
  role       = aws_iam_role.sagemaker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

resource "aws_iam_role_policy" "sagemaker_s3" {
  name = "sagemaker-s3-access"
  role = aws_iam_role.sagemaker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
      Resource = [
        "arn:aws:s3:::de-ai-06-827913617635-ap-northeast-2-an",
        "arn:aws:s3:::de-ai-06-827913617635-ap-northeast-2-an/ml-models/*"
      ]
    }]
  })
}
```

### `src/ml/train.py`

```python
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
    avg_motor_temp,
    max_motor_temp,
    battery_drain_rate,
    operation_ratio,
    machine_failure
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
    # 쿼리 완료 대기 후 결과 S3 경로 반환
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
```

### `dags/robot_daily_etl.py` — 주간 재학습 Task 추가

기존 DAG 마지막 Task 이후에 아래를 추가:

```python
from airflow.operators.python import ShortCircuitOperator, PythonOperator

def _is_monday(**ctx):
    return ctx["execution_date"].weekday() == 0  # 월요일만 실행

def _retrain_model(**ctx):
    import subprocess
    subprocess.run(["python", "src/ml/train.py"], check=True)

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

# bedrock_report >> check_monday >> retrain_model
```

### `src/api/main.py` — `/api/predict` 엔드포인트 추가

기존 FastAPI 앱에 아래를 추가:

```python
import boto3
from pydantic import BaseModel

sagemaker_runtime = boto3.client("sagemaker-runtime", region_name="eu-west-1")
ENDPOINT_NAME = "robot-failure-predictor"

class PredictRequest(BaseModel):
    robot_id: str
    avg_motor_temp: float
    max_motor_temp: float
    battery_drain_rate: float
    operation_ratio: float

@app.post("/api/predict")
@limiter.limit("20/minute")
async def predict_failure(request: Request, body: PredictRequest):
    features = f"{body.avg_motor_temp},{body.max_motor_temp},{body.battery_drain_rate},{body.operation_ratio}"
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=ENDPOINT_NAME,
        ContentType="text/csv",
        Body=features,
    )
    failure_prob = float(response["Body"].read().decode())
    return {
        "robot_id": body.robot_id,
        "failure_probability": round(failure_prob, 4),
        "risk_level": "high" if failure_prob > 0.7 else "medium" if failure_prob > 0.4 else "low",
    }
```

### `k8s/api/deployment.yaml` — IRSA 권한 추가

기존 API IRSA Role에 `sagemaker:InvokeEndpoint` 권한 추가 (`terraform/modules/data_pipeline/iam.tf`).

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/
python3 -m py_compile src/ml/train.py && echo "OK: train.py syntax"
grep -q "robot-failure-predictor" src/api/main.py && echo "OK: predict endpoint"
grep -q "retrain_ml_model" dags/robot_daily_etl.py && echo "OK: retrain task"
grep -q "sagemaker:InvokeEndpoint" terraform/modules/data_pipeline/iam.tf && echo "OK: SageMaker IAM"
ls tests/ml/test_predict_endpoint.py && echo "OK: test file"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - SageMaker IAM Role이 S3 `ml-models/` prefix 읽기/쓰기 권한을 가지는가?
   - Airflow DAG에 `check_monday → retrain_ml_model` Task 체인이 있는가?
   - `/api/predict`가 `failure_probability`와 `risk_level`을 반환하는가?
   - API IRSA에 `sagemaker:InvokeEndpoint` 권한이 있는가?
   - Rate Limit이 분당 20회로 설정되어 있는가?
3. `phases/5-hardening/index.json` step 1 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "sagemaker.tf + train.py + /api/predict 엔드포인트 + 주간 재학습 DAG Task 작성"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- SageMaker Endpoint를 `ml.m5.xlarge` 이상 인스턴스로 배포하지 마라. 이유: 비용 절감, `ml.t2.medium`으로 충분
- Airflow DAG에서 재학습을 매일 실행하지 마라. 이유: 월요일(weekday==0)에만 실행하여 SageMaker 학습 비용 제한
- Gold 테이블 전체 스캔 쿼리를 작성하지 마라. 이유: 최근 30일 파티션만 읽어 Athena 스캔 비용 최적화

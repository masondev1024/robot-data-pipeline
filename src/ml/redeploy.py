"""SageMaker `robot-failure-predictor` 엔드포인트를 학습 스킵하고 재배포한다.

train.py 의 model.tar.gz 가 S3 에 보존돼 있으면(`MODEL_PREFIX/<job-name>/output/model.tar.gz`)
학습 단계 없이 inference container 만 띄워 ~3-5분 내 endpoint 부활 가능.
발표·데모용으로 일시 활성화한 뒤 `aws sagemaker delete-endpoint` 로 즉시 청구 정지하는 흐름.

boto3 만 사용 (sagemaker SDK 313MB 회피) — 비용 셧다운 후 로컬 어디서든 즉시 실행 가능.

실행:
    SAGEMAKER_ROLE_ARN=arn:aws:iam::827913617635:role/robot-telemetry-sagemaker-role \
    python3 -m src.ml.redeploy

환경변수:
    SAGEMAKER_ROLE_ARN          (필수) SageMaker execution role
    SAGEMAKER_MODEL_DATA_URI    (옵션) model.tar.gz S3 URI override
"""
import io
import os
import tarfile
import time
from pathlib import Path

import boto3

REGION = os.environ.get("AWS_REGION", "eu-west-1")
S3_BUCKET = os.environ.get("S3_BUCKET_NAME", "de-ai-06-smartfactory-bucket")
ENDPOINT_NAME = "robot-failure-predictor"

# SageMaker XGBoost framework container (region-specific registry).
# eu-west-1 framework registry = 141502667606 (sagemaker.image_uris.retrieve 검증).
# 버킷이 eu-west-1 이라 cross-region 시 CreateModel 이 ModelDataUrl access 거부.
XGBOOST_IMAGE = f"141502667606.dkr.ecr.{REGION}.amazonaws.com/sagemaker-xgboost:1.7-1"

# 5/7 학습본 (가장 최근 model.tar.gz). 신규 학습 시 weekly_ml_retrain 이 자동 갱신.
DEFAULT_MODEL_DATA_URI = (
    f"s3://{S3_BUCKET}/ml-models/robot-failure-predictor/"
    "sagemaker-xgboost-2026-05-07-00-53-13-398/output/model.tar.gz"
)
SOURCE_S3_KEY = "ml-models/robot-failure-predictor/source/source.tar.gz"
SOURCE_DIR = Path(__file__).resolve().parent  # src/ml/ 절대경로 (가드레일 F)


def _package_and_upload_source() -> str:
    """train_entry.py 만 담은 source.tar.gz 를 메모리에서 만들어 S3 업로드."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(SOURCE_DIR / "train_entry.py", arcname="train_entry.py")
    buf.seek(0)

    s3 = boto3.client("s3", region_name=REGION)
    s3.put_object(Bucket=S3_BUCKET, Key=SOURCE_S3_KEY, Body=buf.getvalue())
    uri = f"s3://{S3_BUCKET}/{SOURCE_S3_KEY}"
    print(f"[redeploy] source uploaded: {uri}")
    return uri


def _cleanup(sm, name: str):
    """기존 endpoint + config + model 삭제 (멱등). delete_endpoint 는 비동기 — Deleting 동안 다음 step 진행 불가."""
    try:
        state = sm.describe_endpoint(EndpointName=name)["EndpointStatus"]
        print(f"[redeploy] 기존 endpoint state={state} → delete")
        sm.delete_endpoint(EndpointName=name)
        for _ in range(30):
            try:
                sm.describe_endpoint(EndpointName=name)
                time.sleep(5)
            except sm.exceptions.ClientError:
                break
    except sm.exceptions.ClientError:
        pass
    for delete_fn, kwarg in [
        (sm.delete_endpoint_config, "EndpointConfigName"),
        (sm.delete_model, "ModelName"),
    ]:
        try:
            delete_fn(**{kwarg: name})
        except sm.exceptions.ClientError:
            pass


def main():
    role_arn = os.environ["SAGEMAKER_ROLE_ARN"]
    model_data = os.environ.get("SAGEMAKER_MODEL_DATA_URI", DEFAULT_MODEL_DATA_URI)
    source_uri = _package_and_upload_source()

    sm = boto3.client("sagemaker", region_name=REGION)
    _cleanup(sm, ENDPOINT_NAME)

    sm.create_model(
        ModelName=ENDPOINT_NAME,
        ExecutionRoleArn=role_arn,
        PrimaryContainer={
            "Image": XGBOOST_IMAGE,
            "ModelDataUrl": model_data,
            "Environment": {
                "SAGEMAKER_PROGRAM": "train_entry.py",
                "SAGEMAKER_SUBMIT_DIRECTORY": source_uri,
                "SAGEMAKER_REGION": REGION,
                "SAGEMAKER_CONTAINER_LOG_LEVEL": "20",
            },
        },
    )
    print(f"[redeploy] Model 생성: {ENDPOINT_NAME} (model_data={model_data})")

    sm.create_endpoint_config(
        EndpointConfigName=ENDPOINT_NAME,
        ProductionVariants=[{
            "VariantName": "AllTraffic",
            "ModelName": ENDPOINT_NAME,
            "InitialInstanceCount": 1,
            "InstanceType": "ml.t2.medium",
        }],
    )
    sm.create_endpoint(EndpointName=ENDPOINT_NAME, EndpointConfigName=ENDPOINT_NAME)
    print(f"[redeploy] Endpoint 생성 요청 — InService 까지 ~5분")

    for _ in range(80):  # 80 × 10s = 13min 안전 마진
        state = sm.describe_endpoint(EndpointName=ENDPOINT_NAME)["EndpointStatus"]
        print(f"[redeploy] state={state}")
        if state == "InService":
            print(f"[redeploy] DONE — endpoint={ENDPOINT_NAME}")
            return
        if state == "Failed":
            reason = sm.describe_endpoint(EndpointName=ENDPOINT_NAME).get("FailureReason", "?")
            raise RuntimeError(f"Endpoint 생성 실패: {reason}")
        time.sleep(10)
    raise TimeoutError(f"Endpoint InService 대기 timeout (13min)")


if __name__ == "__main__":
    main()

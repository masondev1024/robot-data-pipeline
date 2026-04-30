"""SageMaker `robot-failure-predictor` 엔드포인트를 학습 스킵하고 재배포한다.

train.py 의 model.tar.gz 가 S3 에 보존돼 있으면(`MODEL_PREFIX/<job-name>/output/model.tar.gz`)
학습 단계 없이 inference container 만 띄워 ~3-5분 내 endpoint 부활 가능.
발표·데모용으로 일시 활성화한 뒤 `aws sagemaker delete-endpoint` 로 즉시 청구 정지하는 흐름.

실행:
    SAGEMAKER_ROLE_ARN=arn:aws:iam::827913617635:role/robot-telemetry-sagemaker-role \
    python3 -m src.ml.redeploy

환경변수:
    SAGEMAKER_ROLE_ARN          (필수) SageMaker execution role
    SAGEMAKER_MODEL_DATA_URI    (옵션) model.tar.gz S3 URI override
"""
import os

from sagemaker.xgboost import XGBoostModel

from src.ml.train import _cleanup_existing_endpoint

DEFAULT_MODEL_DATA_URI = (
    "s3://de-ai-06-smartfactory-bucket/ml-models/robot-failure-predictor/"
    "sagemaker-xgboost-2026-04-30-06-50-28-185/output/model.tar.gz"
)
ENDPOINT_NAME = "robot-failure-predictor"


def main():
    role_arn = os.environ["SAGEMAKER_ROLE_ARN"]
    model_data = os.environ.get("SAGEMAKER_MODEL_DATA_URI", DEFAULT_MODEL_DATA_URI)

    model = XGBoostModel(
        model_data=model_data,
        role=role_arn,
        entry_point="train_entry.py",
        source_dir="src/ml/",
        framework_version="1.7-1",
    )
    _cleanup_existing_endpoint(ENDPOINT_NAME)
    model.deploy(
        initial_instance_count=1,
        instance_type="ml.t2.medium",
        endpoint_name=ENDPOINT_NAME,
    )


if __name__ == "__main__":
    main()

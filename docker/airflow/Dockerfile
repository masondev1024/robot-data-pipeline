# Custom Airflow image — pip 의존성 baked-in
#
# Why: 기존 helm/airflow-values.yaml 의 `_PIP_ADDITIONAL_REQUIREMENTS` 글로벌(boto3) +
# workers.env(boto3+sagemaker) 가 매 콜드스타트마다 pip resolve + 다운로드 →
# Airflow 2.10.5 providers preload + gunicorn fork 합산 ~94s 소요 → chart default
# startupProbe(60s) 초과 → 5분 grace 강요 + down/up 사이클 길어짐.
# image 에 baked-in 하면 콜드스타트 ~30s 로 단축, probe grace 도 다시 줄일 수 있음.
#
# 핀 사유:
#   boto3==1.35.0 : apache-airflow-providers-amazon + sagemaker SDK 호환 (기존과 동일)
#   sagemaker>=2.200,<3 : weekly_ml_retrain DAG 의 task callable 에서 SageMaker
#     SDK(.fit / endpoint deploy) 사용 (313MB SDK)
#
# 빌드:
#   aws ecr get-login-password --region eu-west-1 \
#     | docker login --username AWS --password-stdin 827913617635.dkr.ecr.eu-west-1.amazonaws.com
#   docker buildx build --platform linux/amd64 \
#     -t 827913617635.dkr.ecr.eu-west-1.amazonaws.com/robot-telemetry-airflow:<tag> \
#     --push docker/airflow/
#
# 태그 전략: <airflow-version>-r<revision> (예: 2.10.5-r1, 2.10.5-r2 …)
FROM apache/airflow:2.10.5

RUN pip install --no-cache-dir \
    "boto3==1.35.0" \
    "sagemaker>=2.200,<3"

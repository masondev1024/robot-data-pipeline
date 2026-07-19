# Architecture and design decisions

## 목표

1,000대 로봇이 보내는 텔레메트리를 실시간 수집하면서 분석용 이력을 Parquet으로 보존하고, 배치 집계·예측·운영자 권고가 같은 데이터 계약을 사용하도록 설계했습니다.

## 데이터 경로

1. Generator가 `robot_id`를 partition key로 Kinesis Data Streams에 이벤트를 보냅니다.
2. Firehose가 JSON을 Parquet/Snappy로 변환해 S3 Bronze에 시간 단위로 동적 파티셔닝합니다.
3. Glue/Athena가 Partition Projection으로 파티션 등록 작업 없이 데이터를 조회합니다.
4. Airflow DAG가 Silver 정제와 Gold 집계를 멱등 실행합니다. Task 간 payload 전달 대신 S3 경로를 계약으로 사용합니다.
5. SageMaker predictor와 PRISM supervisor가 Gold/Silver 데이터를 읽어 예측과 권고를 생성합니다.
6. FastAPI와 Grafana가 serving/observability surface를 제공합니다.

## 실시간 경로

Managed Flink는 event-time watermark를 적용해 이상 이벤트를 alert KDS로 분리합니다. Lambda가 alert stream을 소비해 Slack으로 직접 전송합니다. Flink 애플리케이션은 AWS Studio Notebook을 운영 원본으로 사용하므로 저장소의 코드가 실제 배포 원본인 것처럼 표현하지 않습니다.

## 플랫폼 경계

- Terraform: VPC, EKS, IAM/IRSA, Kinesis, Firehose, S3, Glue, Lambda, SageMaker, observability 자원
- Kubernetes/Helm: generator, API, Grafana, ADOT, autoscaling, disruption budgets, Airflow
- GitHub Actions: OIDC 기반 AWS 인증, Terraform 검증, image/workload 배포, post-deploy 검증
- Secrets Manager/SSM: secret과 late-bound endpoint의 분리

## 핵심 트레이드오프

### EKS와 serverless 혼합

상시 확장되는 generator/API/observability는 EKS에, 이벤트 기반 알림은 Lambda에 배치했습니다. 모든 컴포넌트를 Kubernetes에 넣는 것보다 운영 책임과 비용 경계를 명확히 하기 위한 선택입니다.

### Athena serving cache

사용자 요청마다 Athena를 직접 조회하지 않고 최신 유효 파티션을 읽어 API cache를 갱신합니다. 쿼리 비용과 지연을 낮추되, 데이터 신선도는 batch 주기에 종속됩니다.

### demo와 production의 계약 공유

`DataSource`와 `Predictor` Protocol을 경계로 DuckDB/local XGBoost와 Athena/SageMaker 구현을 교체합니다. demo 결과가 production E2E를 증명하지는 않지만, orchestration 로직의 회귀를 AWS 없이 검증할 수 있습니다.

## 확장 시 우선순위

- dev/stage/prod 다중 계정과 별도 Terraform state
- SLO/error-budget 기반 alerting 및 synthetic probe
- policy-as-code와 image/SBOM 공급망 검증
- disaster recovery 목표(RTO/RPO)와 복구 훈련 자동화

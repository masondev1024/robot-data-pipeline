# Architecture and design decisions

## 목표

1,000대 로봇이 보내는 텔레메트리를 실시간 수집하면서 분석용 이력을 Parquet으로 보존하고, 배치 집계·예측·운영자 권고가 같은 데이터 계약을 사용하도록 설계했습니다.

## 데이터 경로

1. Generator가 `robot_id`를 partition key로 Kinesis Data Streams에 이벤트를 보냅니다.
2. Firehose가 JSON을 Parquet/Snappy로 변환해 S3 Bronze에 시간 prefix로 적재하고,
   Glue/Athena Partition Projection으로 조회 범위를 계산합니다. robot_id 같은
   고카디널리티 동적 파티셔닝은 작은 파일·활성 파티션 버퍼 비용을 만들 수 있어
   의도적으로 끄고, Parquet predicate pushdown을 사용합니다.
3. Glue/Athena가 Partition Projection으로 파티션 등록 작업 없이 데이터를 조회합니다.
4. Airflow DAG가 Silver 정제와 Gold 집계를 멱등 실행합니다. Task 간 payload 전달 대신 S3 경로를 계약으로 사용합니다.
5. SageMaker predictor와 PRISM supervisor가 Gold/Silver 데이터를 읽어 예측과 권고를 생성합니다.
6. FastAPI와 Grafana가 serving/observability surface를 제공합니다.

## 실시간 경로

Managed Flink는 event-time watermark를 적용해 이상 이벤트를 alert KDS로 분리합니다. 현재 탐지 계약은 Z-Score `σ>3` OR `motor_temp>=92°C` 및 `motor_temp/current_load>2.5`이며, 5분 이동 통계와 1분 tumbling 집계를 사용합니다. Lambda가 alert stream을 소비해 Slack으로 직접 전송합니다. Flink 애플리케이션은 AWS Studio Notebook을 운영 원본으로 사용하므로 저장소의 코드가 실제 배포 원본인 것처럼 표현하지 않습니다. 계약과 live 검증 방법은 [FLINK-ANOMALY-CONTRACT.md](FLINK-ANOMALY-CONTRACT.md)에 기록합니다.

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
- SLO/error-budget 기반 alerting 및 synthetic probe (KDS iterator age와 Firehose freshness guardrail은 구현; batch freshness 측정은 후속)
- policy-as-code와 image/SBOM 공급망 검증
- disaster recovery 목표(RTO/RPO)와 복구 훈련 자동화

## 비용 프로필과 검증 경계

전체 플랫폼과 단기 데이터 경로 검증은 같은 Terraform root에서 무조건 함께 실행하지 않는다.

| 프로필 | 목적 | 포함 | 제외 |
|---|---|---|---|
| `terraform/validation` | Kinesis → Firehose → S3 Parquet 및 SLO 확인 | Kinesis 2 shards, Firehose, S3, Glue, CloudWatch | EKS, EC2, NAT, ALB, RDS, ECR, SageMaker, Slack/Lambda |
| 전체 플랫폼 | Kubernetes workload, API, HPA, RDS, Canary, ML 통합 검증 | 기존 Terraform 전체 구성 | 비용 승인 없는 자동 실행 |

단기 프로필은 기존 전체 plan 104개에서 14개 리소스로 축소했다. EKS와 NAT를 제거해 생성·삭제 대기시간을 줄이고, Firehose buffer를 128MB/300초에서 Parquet 변환이 허용하는 최소값인 64MB/60초로 조정해 데이터 신선도 피드백을 빠르게 한다. 이 선택은 비용과 피드백 속도를 최적화하지만 Kubernetes와 API 용량을 검증하지 않으므로, 프로필 간 결과를 혼용하지 않는다.

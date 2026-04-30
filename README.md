# Robot Data Pipeline

스마트 팩토리 로봇 10,000대의 실시간 텔레메트리를 수집·이상 탐지·AI 분석까지 처리하는 **엔터프라이즈급 데이터 플랫폼** — AWS 위에 Lambda Architecture(Speed + Batch) + Medallion(Bronze/Silver/Gold)로 구축.

> Kaggle AI4I 2020 Predictive Maintenance 데이터를 Seed로 한 가상 로봇 시뮬레이션부터, Slack 실시간 알림 · Grafana 운영 대시보드 · Bedrock(Claude Sonnet 4.5) 대화형 AI 분석까지 End-to-End. 발표 데드라인: 2026-05-01.

---

## 1분 요약

```
[Generator (10K robots, 10 KRPS)]
        │  Kinesis Data Streams
        ├─────────────────────────┬────────────────────┐
        ▼ (Speed Layer)           ▼ (Batch Layer)      ▼ (Storage)
   Apache Flink                Airflow KubernetesExec   Kinesis Firehose
   (motor_temp > 90°C          매일 00:00 KST          → S3 Bronze (Parquet
   Tumbling Window 1m)         Bronze→Silver→Gold        + Dynamic Partition
        │                       + Bedrock LLM Report      year/month/day/hour)
        ▼
   alert KDS → Lambda         (Glue Catalog → Athena)
        │     (urllib POST)         │
        ▼                           ▼
   Slack Webhook              Grafana Dashboards (Athena/CloudWatch)
                                    │
                              FastAPI /api/chat
                                    │ (Bedrock invoke_model
                                    │  Sonnet 4.5, max_tokens=512)
                                    ▼
                              Portal UI (대시보드 + AI 챗봇 통합)
```

---

## 기술 스택

| 레이어 | 기술 | 비고 |
|---|---|---|
| Ingestion | Kinesis Data Streams · Firehose | 동적 파티셔닝 (`year=!{timestamp:yyyy}/month=.../day=.../hour=...`) |
| Speed Layer | Amazon Managed Service for Apache Flink (Studio Notebook) | 1분 Tumbling Window, Watermark로 Late Data 처리 |
| Batch Layer | Airflow (KubernetesExecutor) · Athena (Partition Projection) | 멱등성 보장, XCom 지양·S3 경로 매개변수 전달 |
| Storage | S3 Medallion (Bronze/Silver/Gold) · Glue Catalog | Bronze: Parquet + 시간 파티션 |
| ML | SageMaker Random Cut Forest (예측정비) · Bedrock Claude Sonnet 4.5 (LLM 리포트/챗) | EU inference profile, IRSA `bedrock:InvokeModel` |
| Serving | FastAPI · Grafana 11.x · Lambda + SNS + Slack | Portal에 Grafana iframe + 챗봇 통합 |
| Compute | EKS (Karpenter v1, NodePool spot 우선) | HPA 표준 채택, Generator/API 양 디플로이 |
| IaC | Terraform (modular `modules/data_pipeline/`) · GitHub Actions OIDC | EKS Access Entry로 워크플로우 권한 IaC 영구화 |
| Observability | X-Ray · OTEL · CloudWatch | ALB dimension은 LoadBalancer 실제 ARN 사용 |

---

## 핵심 의사결정 3가지

1. **Lambda Architecture + Medallion** — 실시간 알림(Speed)과 일별 리포트(Batch)의 SLA가 다르기 때문에 단일 처리 경로 대신 두 레이어로 분리. Bronze는 Firehose의 raw Parquet, Silver/Gold는 Airflow 야간 집계로 비용/지연 최적화.
2. **EU inference profile (Bedrock Sonnet 4.5)** — `eu-west-1` 단일 리전 배포 원칙을 유지하면서 Claude 3.5 Sonnet 미배포 이슈를 EU profile (`eu.anthropic.claude-sonnet-4-5-20250929-v1:0`)로 해소. IRSA에 `bedrock:InvokeModel` Resource `*` 부여, IAM 변경 없음.
3. **Slack 알림은 Lambda urllib POST 직접 호출** — SNS HTTPS 구독은 Slack Webhook의 `SubscribeURL` GET 정책과 충돌(PendingConfirmation 영구 고착)하므로, AWS 권장 패턴인 Lambda direct POST로 우회. timeout 10s(SSM 조회 + cold start 여유).

---

## 디렉토리 구조

```
.
├── src/                    # 애플리케이션 코드
│   ├── generator/          #   asyncio 로봇 시뮬레이터 → KDS (Python)
│   ├── api/                #   FastAPI 챗봇/Portal (Jinja2)
│   ├── lambda/             #   Slack 알림 Lambda (urllib)
│   ├── ml/                 #   SageMaker train/deploy 엔트리
│   └── common/             #   AWS client/Bedrock 헬퍼
├── dags/                   # Airflow DAG (Bronze→Silver→Gold + LLM 리포트)
├── flink/                  # Flink Studio Notebook (Zeppelin) 자료
├── sql/                    # Athena DDL (Partition Projection)
├── grafana/dashboards/     # Robot Fleet · Anomaly · Pipeline Health
├── k8s/                    # EKS manifests (api/generator/monitoring/karpenter)
├── helm/                   # Airflow Helm values
├── terraform/              # IaC — root + modules/data_pipeline/
├── docs/                   # PRD · ARCHITECTURE · ADR · UI_GUIDE · research
├── phases/                 # 7단계 phase 산출물 (0-setup ~ 6-autoscaling)
├── scripts/                # 운영 자동화 스크립트
├── data/                   # AI4I 2020 Seed CSV
└── .github/workflows/      # k8s-deploy · post-deploy · terraform
```

---

## 데모 시나리오 (발표용)

1. **Generator 로컬 기동** → 10,000대 로봇이 KDS에 초당 ~10K 레코드 push
2. **`SIGUSR1` 시그널** → 60초 동안 모든 로봇 motor_temp 강제 spike → Flink 즉시 감지 → Slack 알림 폭주
3. **Portal UI** → 좌측 Grafana 대시보드(이상 탐지 타임라인 실시간 갱신) + 우측 AI 챗봇 ("이상치 로봇 보여줘" → Claude Sonnet 4.5가 markdown 리포트로 응답)
4. **Karpenter 오토스케일링** → 30개 stress pod 투입 → 4개 spot 노드 자동 프로비저닝 → 부하 제거 후 consolidation으로 0대까지 회수

---

## 실행 (요약)

### 로컬 — Generator만
```bash
pip install -r requirements.txt
export KINESIS_STREAM_NAME=robot-telemetry-ingest
export ROBOT_COUNT=10000 TICK_INTERVAL_SECONDS=1.0
python -m src.generator.app
```

### 클라우드 — 전체 배포
```bash
cd terraform && terraform init && terraform apply   # AWS 인프라
kubectl apply -f k8s/ --recursive                    # EKS 워크로드
# 이후 main 브랜치 push 시 GitHub Actions가 자동으로 ECR 빌드 + rollout restart
```

자세한 운영 가이드: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), 의사결정 기록: [docs/ADR.md](docs/ADR.md), UI 사용법: [docs/UI_GUIDE.md](docs/UI_GUIDE.md).

---

## 프로젝트 메타

- **데드라인**: 2026-05-01
- **AWS 리전**: `eu-west-1` (단일 리전 배포)
- **테스트**: 122/122 passed (포트폴리오 빌드에는 미포함)
- **CI/CD**: GitHub Actions OIDC (AWS_ROLE_ARN secret + EKS Access Entry로 권한 부여)

# Robot Data Pipeline

스마트 팩토리 로봇 텔레메트리를 실시간으로 수집·이상 탐지·AI 분석까지 처리하는 **엔터프라이즈급 데이터 플랫폼** — AWS 위에 Lambda Architecture(Speed + Batch) + Medallion(Bronze/Silver/Gold) 로 구축.

> Kaggle AI4I 2020 Predictive Maintenance 데이터를 Seed 로 한 가상 로봇 시뮬레이션부터, Slack 실시간 알림 · Grafana 운영 대시보드 · Bedrock(Claude Sonnet 4.5) 대화형 AI 분석 · SageMaker XGBoost 예측 정비까지 End-to-End. 발표 데드라인: **2026-05-08**.

---

## 1분 요약

```
┌─ Speed Layer ────────────────────────────────────────────────┐
│  Generator (asyncio, 100 robots × 2s tick = 50 rec/s)        │
│   └─ KDS robot-telemetry-stream (1 shard, 24h)               │
│       ├─→ Managed Flink (Studio Notebook, Z-Score σ>3        │
│       │     OR motor_temp/load > 1.8, OVER 5min window)      │
│       │     └─→ alert KDS → Lambda urllib POST → Slack       │
│       └─→ Firehose (300s/128MB buffer, JSON→Parquet+Snappy)  │
│             └─→ S3 bronze/year=…/month=…/day=…/hour=…/       │
└──────────────────────────────────────────────────────────────┘

┌─ Batch Layer (Airflow on EKS) ───────────────────────────────┐
│  robot_daily_etl   (매일 KST 00:00) Bronze→Silver→Gold       │
│                    + Bedrock Haiku 정비 리포트 → S3           │
│  weekly_dq_report  (주간) DQ 리포트 → Slack                   │
│  weekly_ml_retrain (주간) SageMaker XGBoost 재학습 + 배포     │
└──────────────────────────────────────────────────────────────┘

┌─ Serving Layer ──────────────────────────────────────────────┐
│  Athena (Partition Projection) ← Glue Catalog                │
│  Grafana (Helm, monitoring ns) — Fleet/Anomaly/Health        │
│  Portal (FastAPI + Jinja2)                                   │
│   ├─ 다크 모드 통일 + 실시간 stick bar (60s polling)         │
│   ├─ 자동채우기/예측 (Gold 캐시 + SageMaker endpoint)         │
│   └─ AI 챗봇 — Bedrock Converse API + Tool Use               │
│        (predict_robot_failure / query_telemetry tools)       │
└──────────────────────────────────────────────────────────────┘
```

> **현재 운영값**은 학습/비용 최적화 기준 (100 robots, 1 shard). 발표 시 `scripts/load_demo.sh` 로 1000대 부하 시뮬 가능 — KDS shard count 만 늘리면 동일 코드로 그대로 확장.

---

## 기술 스택

| 레이어 | 기술 | 비고 |
|---|---|---|
| Ingestion | Kinesis Data Streams · Firehose | Dynamic Partitioning (`year/month/day/hour`), JSON→Parquet+Snappy, Glue Schema Registry 검증 |
| Speed Layer | Amazon Managed Service for Apache Flink (Studio Notebook) | Z-Score σ>3 + 다변량 (motor_temp/load > 1.8) OR, 5-min OVER window, Watermark 5s |
| Batch Layer | Airflow 2.10.5 (KubernetesExecutor, custom ECR image) · Athena (Partition Projection) | 멱등성·XCom 회피·S3 경로 매개변수, 콜드스타트 ~30s (이전 ~94s) |
| Storage | S3 Medallion (Bronze/Silver/Gold) · Glue Catalog | Bronze 90d Glacier IR, Silver 365d Glacier IR, Gold 영구 |
| ML | SageMaker XGBoost (Phase 8 multi-class PdM) · Bedrock Claude Sonnet 4.5 (LLM 챗) · Claude Haiku (배치 리포트) | EU inference profile, IRSA `bedrock:InvokeModel`, weekly retrain |
| Serving | FastAPI · Grafana 11.x · Lambda + Slack Webhook | Portal 에 Grafana iframe + AI 챗봇 통합, Lambda direct POST (no SNS hop) |
| Compute | EKS · Karpenter v1 (NodePool spot 우선) | HPA 표준, Generator/API/Airflow worker 자동 스케일 |
| IaC | Terraform (modular `modules/data_pipeline/`) · GitHub Actions OIDC | EKS Access Entry 로 워크플로우 권한 IaC 영구화 |
| Observability | X-Ray · OpenTelemetry · CloudWatch | DLQ Lifecycle, Firehose `DeliveryToS3.Success` 알람 (소수 임계값) |

---

## 핵심 의사결정 3가지

1. **Lambda Architecture + Medallion** — 실시간 알림(Speed) 과 일별 리포트(Batch) 의 SLA 가 다르기 때문에 단일 처리 경로 대신 두 레이어로 분리. Bronze 는 Firehose 의 raw Parquet, Silver/Gold 는 Airflow 야간 집계로 비용/지연 최적화. ([ADR-001](docs/ADR.md))

2. **EU inference profile (Bedrock Sonnet 4.5)** — `eu-west-1` 단일 리전 배포 원칙 유지하면서 Claude 3.5 Sonnet 미배포 이슈를 EU profile (`eu.anthropic.claude-sonnet-4-5-20250929-v1:0`) 로 해소. IRSA 에 `bedrock:InvokeModel` Resource `*` 부여, IAM 변경 없음. ([ADR-004](docs/ADR.md))

3. **Slack 알림은 Lambda urllib POST 직접 호출** — SNS HTTPS 구독은 Slack Webhook 의 `SubscribeURL` GET 정책과 충돌(PendingConfirmation 영구 고착)하므로, Lambda direct POST 로 우회. SNS Topic 자체는 향후 fan-out (이메일·PagerDuty) 대비 idle 보존. ([ADR-007a](docs/ADR.md))

---

## AI Engineering 의사결정

LLM 을 단순 호출 1회로 끝내지 않고, **probabilistic system 을 deterministic 보이게** 운영하기 위한 4가지 축으로 설계.

### 1. 모델 선택 — Cost / Quality Trade-off

| 호출 패턴 | 모델 | 근거 |
|---|---|---|
| 야간 배치 리포트 ([dags/robot_daily_etl.py](dags/robot_daily_etl.py)) | **Claude Haiku 4.5** | 정량 요약 위주 → Haiku 충분, 비용 최소화 |
| 실시간 챗 ([src/api/main.py](src/api/main.py)) | **Claude Sonnet 4.5** + Prompt Caching | 분석 깊이 우선, system prompt 캐시로 비용 보전 |
| 시계열 예측 (정형) | SageMaker XGBoost (multi-class) | weekly retrain ([dags/weekly_ml_retrain.py](dags/weekly_ml_retrain.py)) |

### 2. Prompt Caching ([ADR-012](docs/ADR.md))

`src/common/bedrock.py` 의 `system` 블록을 `cache_control: ephemeral` 로 마킹 → 시스템 프롬프트(역할/citation 규칙/edge case 처리, ~1.5K tokens)가 5분간 캐시 → `cache_read_input_tokens` 메트릭으로 적중률 추적.

### 3. Tool Use — Conversational Agent ([ADR-013](docs/ADR.md))

`invoke_model` → **Bedrock Converse API** 로 마이그레이션, LLM 이 직접 도구를 선택해 호출:
- `predict_robot_failure(robot_id)` — SageMaker XGBoost endpoint 호출
- `query_telemetry(robot_id, hours)` — Athena Gold 테이블 조회

LLM 이 SQL 결과를 보고 "추가 ML 예측 필요" 판단 시 자체적으로 tool 호출 → 자연어 종합. 단순 chatbot 이 아니라 agent 패턴.

### 4. Eval-Driven Development ([ADR-011](docs/ADR.md))

`evals/` 에 30개 골든 QA + LLM-as-judge (Opus 가 relevance/accuracy/grounding 1-5점 채점) → GitHub Actions `eval.yml` workflow_dispatch 로 회귀 검증. **LLM 출력은 비결정적이라는 사실을 코드가 아닌 데이터로 검증.**

### Failure Mode 의식

| 모드 | 대응 |
|---|---|
| Hallucination | Tool 결과 인용 강제 (`<source>` 태그 + SQL 행 번호) |
| Prompt Injection | 사용자 입력을 `<user_input>` 태그 격리, system 에 boundary 명시 |
| Cost runaway | `max_tokens=512` 캡 + CloudWatch billing alarm |
| Output 비결정성 | LLM-as-judge 정량 점수 회귀 (PR 마다) |

---

## 디렉토리 구조

```
.
├── src/                    # 애플리케이션 코드
│   ├── generator/          #   asyncio 로봇 시뮬레이터 → KDS (Python)
│   ├── api/                #   FastAPI 챗봇/Portal (Jinja2, 다크 모드)
│   ├── lambda/             #   Slack 알림 Lambda (urllib direct POST)
│   ├── ml/                 #   SageMaker XGBoost train/deploy
│   └── common/             #   AWS client / Bedrock helper (invoke_claude)
├── dags/                   # Airflow DAG 3종
│   ├── robot_daily_etl.py       #   Bronze→Silver→Gold + Bedrock 리포트
│   ├── weekly_dq_report.py      #   주간 DQ 리포트 → Slack
│   └── weekly_ml_retrain.py     #   주간 XGBoost 재학습 + endpoint deploy
├── sql/                    # Athena DDL (Partition Projection)
├── grafana/dashboards/     # Robot Fleet · Anomaly · Pipeline Health
├── k8s/                    # EKS manifests (api/generator/monitoring/karpenter)
├── helm/                   # Airflow Helm values (custom ECR image)
├── docker/airflow/         # Airflow custom image Dockerfile (PIP baked-in)
├── terraform/              # IaC — root + modules/data_pipeline/
├── docs/                   # PRD · ARCHITECTURE · ADR · UI_GUIDE · research
├── evals/                  # LLM 회귀 검증 (golden QA + LLM-as-judge)
├── tests/                  # pytest (generator/api/dags/lambda/common)
├── scripts/                # 운영 자동화 (load_demo.sh, dlq_alarm_e2e.sh 등)
├── data/                   # AI4I 2020 Seed CSV
└── .github/workflows/      # k8s-deploy · post-deploy · terraform · eval
```

---

## 데모 시나리오 (발표용)

1. **Generator 동작 확인** — Portal 헤더의 "실시간 갱신 hh:mm:ss" 가 60초 polling 으로 갱신, Grafana Fleet KPI 가 실시간 텔레메트리 반영
2. **`SIGUSR1` 시그널** ([src/generator/app.py:58](src/generator/app.py)) — 60초간 모든 로봇 motor_temp 강제 spike → Flink 즉시 감지 → Slack 알림 + Portal 다크모드 알람 카드 갱신
3. **AI 챗봇** — "고장 위험 Top 3 로봇" 같은 자연어 질문 → Bedrock Converse 가 `query_telemetry` + `predict_robot_failure` tool 자체 호출 → markdown 리포트 응답
4. **Karpenter 오토스케일링** — `scripts/load_demo.sh` 로 부하 spike → 4-5개 spot 노드 자동 프로비저닝 → 부하 제거 후 consolidation 으로 회수

---

## 실행

### 로컬 — Generator 만
```bash
pip install -r requirements.txt
export KINESIS_STREAM_NAME=robot-telemetry-stream
export ROBOT_COUNT=100 TICK_INTERVAL_SECONDS=2.0
python -m src.generator.app
```

### 클라우드 — 전체 배포
```bash
cd terraform && terraform init && terraform apply   # 로컬 state 운영
kubectl apply -f k8s/ --recursive                    # EKS 워크로드
# 이후 main 브랜치 push 시 GitHub Actions (k8s-deploy) 가
# 자동으로 ECR 빌드 + rollout restart
```

> `terraform` workflow 의 `apply` job 은 backend(S3) 미설정으로 GitHub Actions runner state 가 매 push 마다 빈 상태 → 의도적으로 `workflow_dispatch` 만으로 격하. 인프라 변경은 로컬에서 직접 `terraform apply`.

자세한 운영 가이드: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), 의사결정 기록: [docs/ADR.md](docs/ADR.md), UI 사용법: [docs/UI_GUIDE.md](docs/UI_GUIDE.md), Phase 0~8 완료 기록: [docs/plan/archive/phases-0-8.md](docs/plan/archive/phases-0-8.md).

---

## 프로젝트 메타

- **데드라인**: 2026-05-08
- **AWS 리전**: `eu-west-1` (단일 리전 배포)
- **현재 운영 규모**: 100 robots × 2s tick, KDS 1 shard (학습/비용 최적화)
- **Phase 진행**: Phase 0~8 모두 completed (Phase 8 = Multi-class PdM)
- **CI/CD**: GitHub Actions OIDC (`AWS_ROLE_ARN` secret + EKS Access Entry)
  - `k8s-deploy` — `k8s/`, `src/` 변경 시 자동 ECR 빌드 + rollout
  - `post-deploy` — ALB DNS 확정 후 SSM 자동 저장
  - `terraform` — PR plan + manual `workflow_dispatch` apply
  - `eval` — manual LLM 회귀 검증 (PR 마다 트리거 가능)

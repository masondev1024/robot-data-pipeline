# Robot Data Pipeline + PRISM AI 인과추론

**스마트 공장 1000대 로봇 텔레메트리 실시간 데이터 파이프라인** 위에 **PRISM AI 인과추론·운영자 의사결정 콘솔** 을 접목한 통합 저장소.

- **Production 파이프라인:** KDS → Firehose → S3 Parquet (Bronze/Silver/Gold) → Athena → SageMaker → Grafana → FastAPI portal
- **AI 인과추론 레이어 (PRISM):** DoWhy 6-Node DAG + 4-Agent Supervisor + Bedrock LLM 자연어 권고
- **Demo:** 노트북 1대 + docker-compose 로 오프라인 시연 가능 (`prism/`)

---

## 두 가지 부팅 모드

### A. PRISM Demo (오프라인 · 노트북 1대)

PRISM AI 인과추론 + 운영자 콘솔을 **AWS 인프라 없이** 결정론적으로 시연.

```bash
cd prism/
cp .env.example .env       # Bedrock offline 모드면 그대로
docker compose up --build
```

- <http://localhost:8501> — Demo (cache replay, deterministic)
- <http://localhost:8502> — Live (Bedrock 라이브)
- <http://localhost:8503> — Operator-first 콘솔

데이터 백엔드: DuckDB in-process. AI 추론: `assets/cache_replay.jsonl` 사전 녹화 응답.

운영 가이드 → [`prism/operator-guide.md`](prism/operator-guide.md)
배포 단위 상세 → [`prism/README.md`](prism/README.md)

### B. Production (EKS · 1000대 스케일)

```bash
# Step 0: Secrets Manager 사전 작업 (사람이 직접)
#   /robot-telemetry/slack-webhook-url
#   /robot-telemetry/grafana-admin-password

# Step 1: 인프라
cd terraform/ && terraform apply

# Step 2: K8s 워크로드
kubectl apply -f k8s/

# Step 3: ALB DNS polling + SSM 저장 (GitHub Actions post-deploy)

# Step 4: Airflow Helm
helm upgrade airflow apache-airflow/airflow -f helm/airflow-values.yaml --version 1.16.0 --wait
```

배포 4단계 + 사고 가드레일 → [`CLAUDE.md`](CLAUDE.md)
비용 셧다운/복구 → [`비용절감플랜/`](비용절감플랜/)

---

## 저장소 구조

```
robot-data-pipeline/
├── apps/                    PRISM Streamlit 콘솔 (demo · operator)
├── prism/                   PRISM 배포 단위 (docker-compose + 운영 자료)
├── src/
│   ├── orchestration/       PRISM AI 레이어 (supervisor, causal_dag, agents, llm_cache)
│   ├── generator/           KDS producer (legacy) + cnc_stream (PRISM demo)
│   ├── ml/                  SageMaker train/redeploy (legacy) + local_predictor (PRISM demo)
│   ├── api/                 FastAPI portal (legacy)
│   ├── lambda/              Slack alert handler (legacy)
│   └── common/              athena · aws · bedrock helper
├── terraform/               IaC (EKS, KDS, Firehose, Glue, Lambda, ALB, SageMaker)
├── k8s/                     StatefulSet · HPA · Karpenter · ALB Ingress · Grafana
├── helm/                    airflow-values.yaml (chart 1.16.0 pinned)
├── dags/                    Airflow 3 DAG (daily ETL · weekly DQ · weekly ML retrain)
├── sql/                     Athena DDL (Bronze/Silver/Gold + dim view)
├── grafana/                 5 monitoring dashboards
├── docker/airflow/          Airflow 커스텀 이미지
├── scripts/                 운영 스크립트 (PRISM demo · 인프라 진단)
├── 비용절감플랜/             EKS up.sh / down.sh
├── tests/                   PRISM smoke (root) + legacy unit (api/etl/generator/lambda/ml)
├── assets/                  XGBoost model · cache_replay · causal DAG
├── data/                    DuckDB demo data
├── docs/                    설계 문서 + INTERFACE 계약 (gitignored)
└── legacy/                  학습 · 발표 자료 아카이브 (이주 완료)
```

---

## AI 인과추론 레이어 = production · demo 공통

PRISM 의 `src/orchestration/` 코드는 두 모드에서 동일하게 동작한다. 데이터 소스만 `DataSource` Protocol 로 추상화:

| 모드 | `DataSource` 구현체 | 데이터 |
|---|---|---|
| Demo (PRISM_MODE=demo/live) | `DuckDBDataSource` | DuckDB · cache_replay |
| Production (PRISM_MODE=production) | `AthenaDataSource` | Athena Gold table |

자세한 연결 계약 → [`docs/INTERFACE.md`](docs/INTERFACE.md) (gitignored, 로컬 참조)

---

## 핵심 기술 결정 (ADR)

| ADR | 결정 |
|---|---|
| Streaming | Kinesis Data Streams + Managed Flink (Studio Notebook = single source of truth) |
| Lakehouse | Firehose → S3 Parquet + Partition Projection (`year/month/day/hour`) |
| Batch | Airflow 3 (chart 1.16.0 pinned, `helm/airflow-values.yaml`) |
| Causal | DoWhy 6-Node DAG (`src/orchestration/causal_dag.py`) |
| AI | Bedrock Claude Haiku 3 + 4 도메인 에이전트 supervisor |
| ML | SageMaker XGBoost (production) / 6-class XGBoost pickle (demo) |
| Alerting | Lambda → Slack (단일 채널, SNS 우회 금지) |
| Cost | EKS 비용 셧다운 자동화 (Karpenter · HPA · ALB · EIP 누수 0) |

근거 사고 로그 → [`CLAUDE.md`](CLAUDE.md) §1

---

## 라이선스 · 데이터

- 시연 데이터: AI4I 2020 Predictive Maintenance Dataset (CC BY 4.0)
- 외부 합성 데이터 추가 금지 (재현성 · 라이선스 무결성)

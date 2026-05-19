# legacy/ — Production Scale-Up Reference

이 디렉토리는 **PRISM MVP에 직접 쓰이지 않는** 인프라·코드 자산을 모아둔 곳이다.
PRISM 본선 시연(2026-05-22)은 가벼운 로컬 스택(`prism/`)만 사용한다.

## 왜 지우지 않고 두는가

PRISM MVP는 단일 호스트에서 동작하지만, 실제 1000대 robot 규모 production 으로
가져갈 때는 streaming + batch lakehouse 패턴이 필요하다. 이 디렉토리는
**"이미 한 번 구축해 본 production scale-up 패턴"** 의 reference 구현체로 보존된다.

발표 슬라이드 1장 ("PRISM → Production 확장 경로") 의 근거 자료.

## 구성

| 경로 | 역할 | PRISM MVP 대체재 |
|---|---|---|
| `dags/` | Airflow ETL/ML 재학습 (3개 DAG) | `prism/causal/` 가 Streamlit 안에서 직접 호출 |
| `terraform/` | EKS, KDS, Firehose, Glue, Lambda, ALB | docker-compose 1줄 (`prism/docker-compose.yml`) |
| `helm/` | airflow-values.yaml (chart 1.16.0) | — |
| `k8s/` | StatefulSet/HPA/Karpenter/ALB Ingress | docker container 1개 |
| `grafana/` | 실시간 fleet 모니터링 dashboard 5장 | Streamlit 콘솔이 batch 결과 표시 |
| `sql/` | Bronze/Silver/Gold Athena DDL (Iceberg) | DuckDB + Parquet 로컬 |
| `docker/airflow/` | Airflow 커스텀 이미지 | — |
| `src/api/` | FastAPI portal (chat / work-orders) | Streamlit 이 직접 UI |
| `src/lambda/` | Slack alert handler | Streamlit 내 알림 영역 |
| `src/ml/` (train/redeploy/synthesize) | SageMaker XGBoost 학습·배포 | `src/ml/local_predictor.py` (PRISM, 로컬 추론) |
| `src/common/athena.py` | Athena query helper | DuckDB SQL |
| `tests/api,lambda,ml,etl/` | 위 컴포넌트 단위 테스트 | `tests/` 루트(=PRISM) 만 CI 회귀 |
| `docs/plan/` | active.md 작업 큐 + ops-checklist | PRISM MVP 단계는 별도 추적 불요 |
| `비용절감플랜/` | EKS up/down 셧다운 스크립트 | docker compose down |
| `scripts/diagnose_grafana.sh` 외 | EKS·Grafana·Karpenter·ADOT 운영 스크립트 | — |
| `발표자료.md` | 데이터 파이프라인 발표 원고 (PRISM 이전) | `PRISM_TALKING_POINTS.md` (root) |

## 사용 금지 (현재 스코프 한정)

- 본선(5/22) 시연·전시 부스에서 이 디렉토리의 어떤 것도 부팅하지 않는다.
  - EKS 셧다운 상태 유지. ALB·EIP 누수 0.
- `legacy/` 코드 변경 = production 확장 시 다시 살릴 때만.
- CI 는 `legacy/tests/` 를 default 회귀에서 제외한다 (`tests/` 루트만 = PRISM).

## 복구 (Production scale-up 시작할 때)

1. `git mv legacy/terraform terraform` (또는 symlink) 후 plan 검토.
2. `legacy/CLAUDE.md` (옛 robot-data-pipeline 운영 가드레일) 을 root `CLAUDE.md` 에 다시 병합.
3. AWS Secrets Manager 에 `slack-webhook-url`, `grafana-admin-password` 수동 저장.
4. `legacy/비용절감플랜/up.sh` 실행.

자세한 옛 운영 가드레일은 `legacy/CLAUDE.md` 참조.

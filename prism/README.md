# prism/ — Deployable MVP Stack

PRISM 운영 콘솔의 **현장 배포 단위**. AWS·EKS·Airflow 없이 노트북 1대 또는 단일 호스트에서
docker compose 한 줄로 가동된다.

## 한 줄 부팅 (시연·현장 공통)

```bash
cd prism/
cp .env.example .env       # Bedrock 키 등 입력 (offline 시연이면 그대로 두기)
docker compose up --build
```

부팅 후:
- Streamlit 운영 콘솔: <http://localhost:8501>
- CNC generator: docker network 안에서 tick 발신 → Streamlit 이 DuckDB 로 직접 적재

## 왜 가벼운 스택인가

본선 시연·현장 PoC 의 본질 기여는 **인과 카드 + 운영자 결정 루프 + 시뮬레이션 fast-forward**
지, 1000대 robot 을 KDS/Firehose/Flink 로 실시간 처리하는 게 아니다. 1000대 production
확장 패턴은 `legacy/` 가 reference 로 보존한다.

| 기존 robot-data-pipeline | PRISM MVP |
|---|---|
| Kinesis Data Streams (2 shard) | docker network 안 generator → Streamlit 직접 |
| Firehose → S3 Parquet (Iceberg) | DuckDB 단일 파일 (`data/prism_demo.duckdb`) |
| Athena workgroup + partition projection | DuckDB SQL in-process |
| SageMaker Endpoint (XGBoost) | `src/ml/local_predictor.py` 로컬 XGBoost |
| Airflow 3 DAG | 시연 timeline 은 Streamlit 안 마커 5개 |
| Grafana fleet 모니터링 | Streamlit 운영 콘솔이 batch 결과 시각화 |
| 월 운영비 \~\$1,200 (EKS+Karpenter+ALB+KDS+Firehose+SageMaker) | 노트북 1대 + Bedrock on-demand \~\$10-20 |

## 구성

```
prism/
├── README.md              ← 이 파일
├── docker-compose.yml     ← Streamlit + generator 컨테이너 정의
├── Dockerfile.app         ← Streamlit 이미지 (apps/prism_demo.py 실행)
├── Dockerfile.generator   ← CNC stream generator 이미지
├── requirements.txt       ← prism 컨테이너 공통 Python deps
├── .env.example           ← Bedrock·시연 옵션 템플릿
└── operator-guide.md      ← 현장 운영자용 사용 가이드 (마커별 시나리오)
```

런타임이 참조하는 외부 디렉토리(루트 기준):
- `apps/prism_demo.py` — Streamlit entry point
- `src/orchestration/` — 인과 DAG, 카드, supervisor, llm_cache
- `src/generator/cnc_stream.py` — CNC stream tick
- `src/ml/local_predictor.py` — 로컬 6-class XGBoost
- `src/common/bedrock.py` — Bedrock invoke (offline 시 cache_replay 사용)
- `assets/` — `xgb_6class.pkl`, `cache_replay.jsonl`, `causal_refute_v2.json`
- `data/prism_demo.duckdb` — DuckDB 적재 위치 (read-write mount)

## 환경 변수 (.env)

| 키 | 기본값 | 용도 |
|---|---|---|
| `PRISM_MODE` | `demo` | `demo` = 결정론적 시연 (`PYTHONHASHSEED=2026` 강제) |
| `BEDROCK_REGION` | `us-west-2` | Bedrock Claude 호출 region |
| `BEDROCK_OFFLINE` | `false` | `true` 면 cache_replay 만 사용 (네트워크 없이도 시연) |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | — | Bedrock 호출 시. offline 모드면 불필요 |
| `STREAMLIT_PORT` | `8501` | 호스트 포트 |

## 시연 안정성 — offline 모드

본선·전시 부스에서 네트워크가 불안정해도 결정론적 결과 보장:

```bash
BEDROCK_OFFLINE=true docker compose up
```

`assets/cache_replay.jsonl` 의 사전 녹화된 Bedrock 응답을 그대로 재생한다.
`llm_cache.py` 가 hash 키로 lookup → cache miss 면 `CacheReplayError` 즉시 raise (조용한 실패 금지).

## 현장 배포 (고객사 PoC)

1. 노트북 / 미니 서버에 Docker 설치.
2. 이 저장소 clone 또는 `prism/` 디렉토리 + `apps/`, `src/`, `assets/`, `data/` rsync.
3. `.env` 에 고객사 Bedrock 키 또는 `BEDROCK_OFFLINE=true` 설정.
4. `docker compose up -d` 후 노트북 IP:8501 사내망 공유.
5. 운영자는 `operator-guide.md` 따라 마커별 의사결정 실행.

## 1000대 robot production 확장 경로

이 MVP 가 그대로 production 으로 가지 **않는다**. scale-up 시 `legacy/` 자산을 활용:

- generator → `legacy/k8s/generator/statefulset.yaml` (HPA + Karpenter)
- 적재 → `legacy/terraform/modules/data_pipeline/kinesis.tf` (KDS 2 shard)
- batch → `legacy/dags/robot_daily_etl.py` (Bronze→Silver→Gold)
- ML → `legacy/src/ml/train.py` (SageMaker XGBoost)
- 알림 → `legacy/src/lambda/alert_handler.py` (Slack webhook)

발표 슬라이드 1장: "PRISM MVP (현재) → 1000대 production (확장)" 양방향 화살표.

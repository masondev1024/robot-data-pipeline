# PRISM — 스마트 공장 운영 시스템 MVP

**P**robabilistic **R**oot-cause **I**nference & **S**imulation **M**onitor.
CNC 텔레메트리에서 이상을 감지하고, **인과 추론 카드**로 운영자에게 권고하고,
"보류" 결정 시 **시뮬레이션 fast-forward** 로 결과를 미리 보여주는 운영 콘솔.

> 해커톤 본선 2026-05-22. 노트북 1대 + Docker 만으로 동작하는 lightweight MVP.

---

## 한 줄 부팅 (시연·현장 공통)

```bash
cd prism/
cp .env.example .env       # offline 시연이면 그대로 두기
docker compose up --build
```

브라우저: <http://localhost:8501>

자세한 운영 가이드 → [`prism/operator-guide.md`](prism/operator-guide.md)
배포 구성 상세  → [`prism/README.md`](prism/README.md)

---

## 4분 시연 timeline

| 시각 | 마커 | 운영자 동작 | 화면 |
|---|---|---|---|
| 0:00 | 1. 정상 운영 | sensor 11 stream watch | 정상 라이브 차트 |
| 0:15 | 2. 이상 감지 | XGBoost 6-class 라벨 확인 | `tool_wear_imminent` 표시 |
| 0:30 | 3. 인과 v1 카드 | "절삭유 +5%" 권고 검토 | DoWhy CE=0.78, refute pass |
| 0:45 | 3. **"보류"** | 보류 버튼 클릭 | timeline 이벤트 기록 |
| 1:00 | 4. 시뮬 가속 | 3시간 fast-forward | 결함 진행 예측 |
| 1:15 | 5. 불량 발생 | defect=1 진입 | 보류 결정의 결과 |
| 1:30 | 6. 인과 v2 | CE 0.78 → 0.71 재추정 | v1↔v2 비교 카드 |

라이브 wiring 4개 + 사전 녹화 2개 → 동작 가능 + 시연 결정론성 양립.

---

## 핵심 기술 스택

| 컴포넌트 | 선택 | 이유 |
|---|---|---|
| UI | Streamlit | 단일 호스트 콘솔, 실시간 차트 + 의사결정 위젯 |
| 저장 | DuckDB (in-process) | KDS/S3/Athena 불요. 노트북 1대로 충분 |
| 인과 추론 | DoWhy | 6-Node DAG (tool_age → spindle_rpm → … → defect), backdoor + IV refute |
| 분류 | XGBoost 로컬 | 6-class fault label (`src/ml/local_predictor.py`) |
| LLM | Bedrock Claude (offline 가능) | cache_replay 로 네트워크 끊겨도 시연 결정론적 |
| 패키징 | Docker Compose | `docker compose up` 한 줄 |

월 운영비 추정: 노트북 + Bedrock on-demand **≈ \$10-20**.

---

## 디렉토리 구조

```
.
├── prism/               ← 배포 단위 (현장·시연용)
│   ├── docker-compose.yml
│   ├── Dockerfile.app
│   ├── README.md
│   ├── operator-guide.md
│   ├── requirements.txt
│   └── .env.example
│
├── apps/
│   └── prism_demo.py    ← Streamlit entry (마커 6개)
│
├── src/
│   ├── orchestration/   ← causal_dag, causal_card, supervisor, llm_cache, storage
│   ├── generator/       ← cnc_stream (CNCStreamGenerator)
│   ├── ml/              ← local_predictor (6-class XGBoost)
│   └── common/          ← aws.py, bedrock.py
│
├── assets/              ← xgb_6class.pkl, cache_replay.jsonl, causal_refute_v2.json
├── data/                ← prism_demo.duckdb, seed_data_sample.csv
├── docs/                ← PRD, ARCHITECTURE, ADR, hackathon-prism/, UI_GUIDE
├── evals/               ← golden_qa, prism_qa, judge_prompt
├── metrics/             ← bedrock_tokens, cache_hit_rate, e2e_runtime
├── tests/               ← PRISM 회귀 (190 tests)
│
├── presentation/        ← PPTX, 스크린샷
├── 학습자료/, 프로젝트 정보/
│
├── PRISM_briefing.md, PRISM_DEMO_DAY.md, PRISM_TALKING_POINTS.md
├── PRISM_마스터가이드.pdf, 스마트 공장 운영 시스템 mvp 개발 기획서.pdf
│
└── legacy/              ← Production scale-up reference (현재 미가동)
    ├── README.md            ← 자산 매핑
    ├── CLAUDE.md            ← 옛 운영 가드레일
    ├── dags/                ← Airflow 3 DAG
    ├── terraform/, helm/, k8s/, grafana/, sql/, docker/
    ├── src/{api,lambda,ml,common,generator}/
    ├── tests/{api,lambda,ml,etl,generator}/
    ├── scripts/             ← EKS/Grafana/ADOT 운영 스크립트
    ├── docs/plan/           ← 옛 작업 큐
    └── 비용절감플랜/
```

---

## 1000대 robot production 확장 경로

PRISM MVP 가 그대로 production 으로 가지 **않는다**. 1000대 규모로 가져갈 때는
이미 한 번 구축해 본 `legacy/` 의 자산을 다시 살린다 (발표 슬라이드 1장 = "확장 경로").

| 단계 | MVP (현재) | 1000대 production |
|---|---|---|
| Ingest | Streamlit 안 generator tick | KDS 2 shard (`legacy/terraform/modules/data_pipeline/kinesis.tf`) |
| Lakehouse | DuckDB 단일 파일 | Firehose → S3 Iceberg (`legacy/sql/*_ddl.sql`) |
| Batch | — (불요) | Airflow 3 DAG (`legacy/dags/`) |
| ML | 로컬 XGBoost | SageMaker XGBoost (`legacy/src/ml/train.py`) |
| 알림 | Streamlit 내 영역 | Lambda → Slack (`legacy/src/lambda/alert_handler.py`) |
| 모니터링 | Streamlit 콘솔 | Grafana fleet/anomaly (`legacy/grafana/dashboards/`) |
| 운영 | docker compose | EKS + Karpenter (`legacy/k8s/`, `legacy/helm/`) |

scale-up 진입 시 → `legacy/README.md` + `legacy/CLAUDE.md` 가드레일 재활성.

---

## 개발 / 테스트

```bash
# 로컬 개발 (Docker 없이 직접 streamlit)
pip install -r prism/requirements.txt
PYTHONHASHSEED=2026 streamlit run apps/prism_demo.py

# 회귀 테스트
PYTHONHASHSEED=2026 python3 -m pytest -q
# tests/ 루트만 실행 (legacy/tests/ 는 pytest.ini 가 norecursedirs 로 제외).
```

| 명령 | 용도 |
|---|---|
| `python3 -m pytest -q` | PRISM 회귀 (190 tests, ~100s) |
| `python3 scripts/verify_demo_determinism.py` | 시연 결정론성 검증 (Bedrock 토큰 / cache hit / e2e 런타임) |
| `python3 scripts/build_cache_replay.py` | cache_replay.jsonl 재녹화 |
| `python3 scripts/precompute_causal_refute.py` | causal_refute_v2.json 재생성 |

---

## 라이선스 / 데이터셋

- 시드 데이터: **AI4I 2020 Predictive Maintenance Dataset** (CC BY 4.0,
  [Kaggle](https://www.kaggle.com/datasets/stephanmatzka/predictive-maintenance-dataset-ai4i-2020))
- 코드: 본 저장소 (해커톤 제출용)

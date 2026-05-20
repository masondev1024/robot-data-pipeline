# PRISM 운영자 사용 가이드

이 문서는 현장(고객사 PoC, 본선 부스, 전시) 운영자가 PRISM 콘솔 앞에서
어떤 순서로 어떤 결정을 내리는지 정의한다. 시연 timeline 은 `apps/prism_demo.py` 의
`MARKERS` 리스트 (11개, 0:00 ~ 3:45) 와 1:1 매칭.

## 부팅 확인 (시연 시작 30초 전)

```bash
cd prism/
docker compose ps         # app 상태 healthy 확인
docker compose logs app | tail -20
```

브라우저 접속: <http://localhost:8501>
콘솔 상단 "PRISM — Predictive Real-time Intelligence for Smart Manufacturing"
헤더 + KPI 카드 4장(OEE/RCA/Defect/비용) + 그 아래 **🏭 10대 CNC fleet 라이브 모니터링**
fact line ("현재 incident CNC-01 · 정상 가동 9대") 가 보이면 정상.

## 시연 timeline (apps/prism_demo.py MARKERS 와 일치)

| idx | 시각 | 라벨 | 설명 |
|---|---|---|---|
| 0 | 0:00 | 정상 | 센서 데이터 정상 흐름, 모든 라인 가동 중 |
| 1 | 0:15 | 예지경보 risk62% | **라이브 XGBoost 6-class predict_proba** (TWF 1순위, tool_age 18h 누적 — 표준 200h 대비 빠른 마모) |
| 2 | 0:30 | 인과 v1 | DoWhy 6-Node DAG 인과 추론 v1 — **공구 교체 추천 (tool_age reset)**. XGBoost 감지 변수와 통일 |
| 3 | 0:45 | 운영자결정 | **운영자 "보류"** (공구 교체 4h 정지 부담, v1 추천 미적용) |
| 4 | 1:00 | 시뮬가속 | **라이브 DoWhy do(tool_age) ATE** — 3h fast-forward |
| 5 | 1:15 | 불량 #47 | 결함 #47 실제 발생, motor_temp 105°C (TWF secondary symptom — 공구 마모로 인한 motor 부하 ↑) |
| 6 | 1:30 | 인과 v2 | Causal Effect 재추정 CE 0.78 → 0.71 |
| 7 | 2:15 | 4 Agent | **라이브 4 Domain Agent** (품질·안전·설비·생산, Bedrock cache_replay) |
| 8 | 3:00 | Supervisor | **라이브 Supervisor Net Value** 산정 — 최적 액션 권고 |
| 9 | 3:30 | 재학습 0.62→0.91 | 강화학습 모델 재학습 완료 (+47%) |
| 10 | 3:45 | OEE +35% | OEE 달성 + Closed-Loop 요약 + 비용 임팩트 |

운영자 조작: 우측 컬럼 **◀ Prev / Next ▶** 버튼으로 마커 이동. "처음으로" 버튼으로 0 으로 리셋.

## 라이브 wiring vs 사전 녹화 분포

| 마커 | 컴포넌트 | 라이브 여부 | 소요시간 | 호출 경로 |
|---|---|---|---|---|
| 1 | XGBoost 6-class | ✅ live | ~1ms | `src/ml/local_predictor.py::predict_proba_timed` |
| 2 | DAG v1 color narrative | static | — | `_node_colors_for_marker(2)` |
| 3 | 운영자 결정 UI | static | — | `render_human_decision` |
| 4 | DoWhy do(tool_age) ATE | ✅ live | ~0.6s | `src/orchestration/causal_dag.py::estimate_intervention_effect` (XGBoost 감지 변수와 통일) |
| 5 | incident alert | static | — | `render_incident_alert` (DuckDB seed 100 rows) |
| 6 | DAG v2 narrative | static | — | `causal_refute_v2.json` (사전 계산) |
| 7 | 4 Domain Agent | ✅ live (Bedrock) | ~3s | `src/orchestration/supervisor.py::negotiate_with_candidates` → `agents/base.py::invoke_claude` |
| 8 | Supervisor Net Value | ✅ live | ~5s | 위 + `compute_net_value_KRW` (α/β/γ slider 라이브 반영) |
| 9 | 재학습 evidence | static | — | `render_retrain_evidence` (사전 metric) |
| 10 | OEE / Closed-Loop | static | — | `render_oee_evidence` + `render_cost_impact` |

**라이브 4개 (1, 4, 7, 8) + 정적 7개**. 라이브 4개는 시연 중 실제 추론 호출 → 화면에 latency
ms 단위로 표기되어 청중이 "live" 임을 확인 가능. 정적 7개는 사전 계산된 narrative 로 결정론
보장.

## Bedrock offline 모드

본선·전시 부스 네트워크 불안정 대비 결정론 보장:

```bash
# prism/.env
BEDROCK_OFFLINE=true
```

`assets/cache_replay.jsonl` 의 사전 녹화 응답을 `src/orchestration/llm_cache.py` 가 hash
키로 lookup. cache miss → `CacheReplayError` raise → `fallback_video()` 가
`presentation/prism_demo_master.mp4` 재생 (영상 fallback 자동 전환).

## 마커 3 의 "보류" narrative — 발표 핵심 포인트

기획서 page 7 (User Case) 정합:
- v1 추천 = **공구 교체** (tool_age reset — XGBoost·DoWhy 감지·추천 변수 통일)
- 운영자 결정 = **"보류"** (4h 라인 정지 부담)
- 시뮬 = **3h 압축** 으로 보류 시 결함 진행 path 미리 보기 (라이브 `do(tool_age)`)
- 결과 = **불량 #47 발생** → 인과 v2 재추정 (mediator `coolant_temp` 추가 학습, CE 0.78 → 0.71)

"AI 가 옳다는 걸 시연에서 운영자 결정으로 증명한다" — 4 Agent Closed-Loop 의 핵심.

## 장애 대응

| 증상 | 원인 | 조치 |
|---|---|---|
| 마커 1 risk% 가 0 으로 표시 | xgb_6class.pkl 누락 | `python3 src/generator/generate_xgb_pkl.py` 로 재생성 |
| 마커 4 fast-forward 무반응 (5초+) | DoWhy 학습 진행 중 | 정상. `@st.cache_resource` 라 시연 시작 1회만 ~3초 |
| 마커 7-8 "Cache miss" 에러 | offline 모드인데 cache_replay 키 mismatch | `BEDROCK_OFFLINE=false` + Bedrock 키 채우거나 cache_replay 재녹화 (`scripts/build_cache_replay.py`) |
| fallback_video "Recording pending D-1" | `presentation/prism_demo_master.mp4` 없음 | 시연 D-1 까지 영상 녹화 필요 (offline fallback 안전망) |
| 8501 포트 충돌 | 다른 streamlit 인스턴스 | `.env` 의 `STREAMLIT_PORT=8502` 변경 후 재기동 |
| DuckDB 락 → sensor stream 멈춤 | 동시 write | `docker compose restart app` (`data/prism_demo.duckdb` 보존) |

## 시연 후 정리

```bash
docker compose down       # 컨테이너 정리 (DuckDB 파일은 호스트 ../data/ 에 보존)
git status               # 결정론적 시연이면 diff 0 (PYTHONHASHSEED=2026)
```

## 현장 PoC 인수인계 체크리스트

- [ ] 노트북 / 미니 서버에 Docker Desktop 24+ 설치 확인
- [ ] `.env` 의 `BEDROCK_OFFLINE` 정책 결정 (인터넷 가능 → false, 없으면 true)
- [ ] `assets/xgb_6class.pkl`, `assets/cache_replay.jsonl`, `assets/causal_refute_v2.json` 동봉
- [ ] `data/prism_demo.duckdb` 초기 상태 확인 (생산 라인별 seed 다를 수 있음)
- [ ] `presentation/prism_demo_master.mp4` (D-1 녹화본) 동봉 — offline fallback 안전망
- [ ] 사내망 접근 URL 공지 (`http://<host-ip>:8501`)
- [ ] 운영자에게 11 마커 timeline + Prev/Next 조작 숙지시킴

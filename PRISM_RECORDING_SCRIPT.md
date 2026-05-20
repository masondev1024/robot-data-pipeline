# PRISM 발표 녹화 스크립트 (Screen Recording Cue Sheet)

> **목적**: 본선 발표 영상 자료 + offline fallback (`presentation/prism_demo_master.mp4`) 동시
> 생성. 7분 시연 timeline 을 **second-precise UI 조작 cue** 로 풀어놓은 문서.
>
> **참조 관계**:
> - 멘트(narration) = [`PRISM_TALKING_POINTS.md`](PRISM_TALKING_POINTS.md) 마커별 블록 그대로.
> - 라이브 운영 매뉴얼 = [`PRISM_DEMO_DAY.md`](PRISM_DEMO_DAY.md).
> - **이 문서 = 클릭/머무름/cursor 위치/take 컷 포인트** 에만 집중.
>
> **기준 timing**: cumulative 0:00 ~ 7:03 (423s 본론 + 10~15s 클로징 fade).

---

## 0. 녹화 전 준비 (T-10분)

### 0.1 환경 변수 + 부팅

```bash
cd /Users/mason/Desktop/Projects/robot-data-pipeline
PYTHONHASHSEED=2026 PRISM_MODE=demo \
    PRISM_CACHE_PATH=assets/cache_replay.jsonl \
    streamlit run apps/prism_demo.py
```

- [ ] 브라우저 자동 오픈 → `http://localhost:8501`
- [ ] view mode = **"전체 시연 (Timeline View)"** 확인 (사이드바 라디오)
- [ ] 마커 인덱스 = 0 (처음으로 버튼 → reset)

### 0.2 브라우저 / 화면 세팅

| 항목 | 값 | 이유 |
|---|---|---|
| 해상도 | **1920×1080** (FHD) | 본선 프로젝터 표준 + 영상 처리 무난 |
| 브라우저 zoom | **100%** | DAG 노드 크기 일관 |
| Streamlit theme | dark | `.streamlit/config.toml` 기 설정 |
| 사이드바 | **펼친 상태** | M0 deep dive 핵심 — collapse 금지 |
| 우측 컬럼 | 자동 (Streamlit 기본 2:1) | Prev/Next 버튼 보이게 |
| 메뉴바 / 알림 | 모두 hide | F11 또는 Cmd+Ctrl+F 전체화면 |

### 0.3 녹화 도구 (OBS Studio)

- [ ] **Display Capture** (전체화면 1920×1080) 또는 **Browser Source** 직접
- [ ] FPS 30, bitrate ≥ 4500 kbps (CBR), 인코더 H.264
- [ ] 마우스 cursor **표시 ON** (포인터 따라 narration 시선 유도)
- [ ] 마이크 게인 -12 dB ~ -6 dB (clipping 회피)
- [ ] **timer overlay** (right-bottom corner) — 0:00 부터 카운트업

### 0.4 cursor 시작 위치

화면 좌측 상단 (`PRISM` 헤더 옆) — 첫 narration 시작과 함께 자연스럽게 fleet line 으로 이동.

### 0.5 take 전략

- **2 take 최소 권장**: 첫 take 는 전체 호흡 잡기용, 두 번째 take 가 final.
- 마커별 cut point 표시 (아래 시간표) — 실수 시 해당 마커만 재녹화 후 컷편집.
- α/β/γ slider 는 **2회 같은 위치 reset 어려움** → take 1 컷에서 한 번에 가는 게 안전.

---

## 1. Timeline 마스터 표 (재확인용)

| Marker | Start | End | Dur | 강조 | 주요 UI 액션 |
|---|---|---|---|---|---|
| M0 | 0:00 | 2:00 | 120s | 사이드바 deep dive | expander 2번 열기 (자세히 / 학술 ref) |
| M1 | 2:00 | 2:22 | 22s | XGBoost 라이브 | TWF bar 가리키기 |
| M2 | 2:22 | 2:50 | 28s | 인과 v1 | DAG tool_age 노드 hover |
| M3 | 2:50 | 3:12 | 22s | 보류 결정 | "보류" 메트릭 카드 가리키기 |
| M4 | 3:12 | 3:50 | 38s | ⭐ DoWhy ATE | latency caption + ATE Δ 메트릭 |
| M5 | 3:50 | 4:12 | 22s | 결함 발생 | motor_temp 105°C 강조 |
| M6 | 4:12 | 4:40 | 28s | 인과 v2 | DAG color 변화 |
| M7 | 4:40 | 5:18 | 38s | ⭐ 4 Agent | Bedrock latency caption |
| M8 | 5:18 | 6:03 | 45s | 🔑 β slider | **slider 1.0 → 2.0 → 5.0** |
| M9 | 6:03 | 6:25 | 22s | 재학습 | 라이브 0.81→0.97 evidence |
| M10 | 6:25 | 7:03 | 38s | OEE+closing | KPI 4장 zoom + 비용 카드 |

---

## 2. Marker-by-marker 녹화 cue

각 cue 는 **(cum_t)** = 녹화 시작 후 누적 초.
**🎤** = narration 시작 (TALKING_POINTS 의 해당 블록 그대로 읽기).
**👆** = cursor 이동/클릭. **👀** = 시청자 시선 유도 (cursor hover, hand-gesture 없음).

---

### Marker 0 — 도입 (0:00 ~ 2:00, 120s)

> **TALKING_POINTS Marker 0 블록 그대로**. 단, 아래 cue 와 1:1 sync.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 0:00 | 🎤 시작 "정상 가동 상태입니다…" | 헤더 + fleet caption 전체 view |
| 0:00~0:10 | 👀 cursor 를 `🏭 10대 CNC fleet …` caption 위로 좌→우 슬로우 sweep | fleet fact line |
| 0:10~0:18 | 🎤 "페이지 구성은 셋 — 왼쪽 사이드바…" / 👆 cursor 사이드바 → 가운데 DAG → 위쪽 KPI 순으로 큰 원 그리기 | 3분할 구조 시각화 |
| 0:18~0:22 | 🎤 "먼저 사이드바 첫째 카드 — 인과 모델 검증. σ_max 0.40 robust." / 👀 cursor 사이드바 첫 카드 헤더 hover | Causal Robustness 카드 |
| **0:22** | **👆 클릭: `🔍 자세히 (native output)` expander** | expander 펼침 |
| 0:22~0:40 | 🎤 "[자세히 클릭] 펼치면 4 Refuter 검증이 보입니다. 위약 처치, 무작위 공통 원인, 80% 부분 데이터, σ_max 스캔." / 👀 cursor 4개 `Refute:` 헤더 위 차례로 stop 0.5s 씩 (총 ~3s) | 4 refute 블록 |
| 0:40~0:42 | 🎤 "4개 독립 반증 시도 전부 통과 — ATE 방향 안 바뀝니다." / 👀 cursor 첫 블록 `p value: 2.0` 위 잠시 | 검증 결과 |
| **0:42** | **👆 클릭: `📖 학술 reference (Wright 1991)` expander** | 학술 박스 펼침 |
| 0:42~0:54 | 🎤 "[학술 reference 클릭] 학술 근거는 Wright 1991 partial R². …" / 👀 cursor Wright 텍스트 위 sweep | 학술 reference |
| 0:54~1:02 | 🎤 "그 밑 α/β/γ 가중치 slider…" / 👀 cursor α/β/γ slider 3개 위로 (절대 만지지 말 것 — M8 에서 핵심 시연) | slider 3개 |
| 1:02~1:30 | 🎤 "둘째 카드 — DuckDB lineage. Bronze → Silver → Gold…" / 👀 cursor 둘째 카드 Bronze/Silver/Gold 라벨 차례로 | Medallion 카드 |
| 1:30~1:50 | 🎤 "셋째 카드 — Bedrock 상태…" + "이제 가운데 6-Node 인과 DAG." / 👆 cursor 가운데 DAG 노드 7개 위 좌→우 sweep | DAG 노드 layer |
| 1:50~1:58 | 🎤 "위쪽 KPI 4개 — OEE, RCA, Defect, 비용. 지금 모두 정상." / 👆 cursor 4 KPI 카드 위 좌→우 | KPI 4장 |
| 1:58~2:00 | 🎤 "이제 흐름 시작하겠습니다." / 👀 cursor 우측 **`Next ▶`** 버튼 hover | 버튼 ready |
| **2:00** | **👆 클릭: `Next ▶`** | M1 진입 |

> **컷 포인트**: 2:00 전후 (Next 클릭 정확히 누른 직후) 가 take 분할 1차 옵션.

---

### Marker 1 — 예지경보 (2:00 ~ 2:22, 22s)

화면 변화: 헤더 아래 `⚠️ 예지경보 — ROBOT-00018…` warning + **XGBoost 6-class 확률 bar chart** + latency caption (`🤖 라이브 XGBoost predict_proba: 0.81ms`).

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 2:00~2:03 | 화면 안정화 wait (DAG 색 변화 인식 시간) | 전체 |
| 2:03~2:08 | 🎤 "ML 모델이 위험 신호를 감지했습니다. 결함 위험 62% — TWF 1순위." / 👀 cursor `결함 Risk 62%` 메트릭 카드 hover | 좌측 메트릭 |
| 2:08~2:15 | 🎤 "tool_age 18h 누적, 표준 200h 대비 빠른 마모 추세." / 👆 cursor TWF (주황색) bar 위 hover, 1초 머무름 | XGBoost bar chart 1순위 |
| 2:15~2:20 | 🎤 "단순 임계값이 아닙니다. XGBoost 6-class softmax 확률." / 👀 cursor `🤖 라이브 XGBoost predict_proba: ~ms` caption | latency caption |
| **2:22** | **👆 클릭: `Next ▶`** | M2 진입 |

---

### Marker 2 — 인과 v1 (2:22 ~ 2:50, 28s)

화면 변화: DAG `tool_age` 노드 **주황색**, recommendation 표 (3 후보 중 v1 ✅ 공구 교체).

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 2:22~2:28 | 🎤 "여기가 인과 분석 시작. DAG 에서 tool_age 가 주황색 —" / 👆 cursor DAG `tool_age` 노드 hover, 2초 머무름 | DAG 주황색 노드 |
| 2:28~2:34 | 🎤 "DoWhy 인과 모델이 핵심 원인 변수로 식별. v1 추천 = '공구 교체'." / 👀 cursor 표의 ✅ 행 (`tool_age` 공구 교체) | recommendation 표 행 |
| 2:34~2:48 | 🎤 "중요한 점: XGBoost 가 감지한 변수와 DoWhy 가 추천한 intervention 변수가 동일." / 👀 cursor 메인 영역 `XGBoost 감지 변수와 통일` caption 위 sweep | 인과 일관성 |
| **2:50** | **👆 클릭: `Next ▶`** | M3 진입 |

---

### Marker 3 — 운영자 결정 (2:50 ~ 3:12, 22s)

화면 변화: DAG title 에 `⏸ 운영자 결정: 보류 (v1 추천 미적용)` amber, 우측 "보류" 카드.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 2:50~2:58 | 🎤 "여기서 자율 AI 가 아닙니다. 운영자가 검토:" / 👆 cursor 메인 우측 "⏸️ 운영자 결정" 카드 hover | 운영자 결정 카드 |
| 2:58~3:06 | 🎤 "공구 교체는 4h 라인 정지 부담. 적용 전에 먼저 시뮬해보자." / 👀 cursor `결정 사유: 라인 가동 우선` 메트릭 | 사유 메트릭 |
| 3:06~3:10 | 🎤 "보류 결정 — Human-in-the-loop." / 👀 cursor `⚠️ 다음 (마커 4): 보류 시 3시간 fast-forward 시뮬` | next-cue caption |
| **3:12** | **👆 클릭: `Next ▶`** | M4 진입 |

---

### Marker 4 — ⭐ 시뮬 가속 (3:12 ~ 3:50, 38s)

화면 변화: `🎬 시뮬레이션 가속 — 보류 시 3시간 fast-forward` warning + 라이브 DoWhy ATE 결과 박스 + trajectory chart.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 3:12~3:15 | 화면 안정화 wait (DoWhy ATE 라이브 계산 ~0.6s 자동 진행) | 전체 |
| 3:15~3:25 | 🎤 "라이브 counterfactual — do(tool_age = −1σ) 시뮬레이션. 공구 교체 시나리오." / 👆 cursor `🔬 라이브 DoWhy ATE 호출 (5k row…)` success 박스 위 hover | DoWhy success 박스 |
| 3:25~3:35 | 🎤 "DoWhy ATE 라이브 계산. defect_prob 62% → 18%." / 👆 cursor `defect_prob 예측 62% → 95%` 메트릭 + `🔬 라이브 ATE Δ` 메트릭 | 메트릭 2장 |
| 3:35~3:46 | 🎤 "4시간 분량 시뮬을 1초에. 적용 전 검증 완료." / 👀 cursor trajectory chart (motor_temp 100°C 임계 선) 위 sweep | trajectory chart |
| **3:50** | **👆 클릭: `Next ▶`** | M5 진입 |

> ⚠️ M4 는 라이브 DoWhy 호출 — 콜드 스타트 시 1~3초 spinner 가능. 첫 take 에서 cache 활성 후 두 번째 take 가 안전.

---

### Marker 5 — 결함 발생 (3:50 ~ 4:12, 22s)

화면 변화: incident alert (red), motor_temp 105°C 메트릭, DuckDB seed 100 rows 기반 fault timeline.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 3:50~3:58 | 🎤 "실제 결함 발생. motor_temp 105도 — SOP 임계 100도 초과." / 👆 cursor `motor_temp 105°C` 표시 위 hover | incident alert 박스 |
| 3:58~4:08 | 🎤 "사전 예지가 실제 발현됐습니다. INCIDENT #47." / 👀 cursor incident 카드 전체 sweep | 카드 전체 |
| **4:12** | **👆 클릭: `Next ▶`** | M6 진입 |

---

### Marker 6 — 인과 v2 (4:12 ~ 4:40, 28s)

화면 변화: DAG v2 — `coolant_temp` mediator 추가 학습 표시, CE 0.78 → 0.71 비교 카드.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 4:12~4:22 | 🎤 "새로운 인과 path 발견 — coolant_temp 가 thermal_drift 에 영향." / 👆 cursor DAG `coolant_temp` 새 path edge 위 hover | DAG 신규 edge |
| 4:22~4:35 | 🎤 "DAG v2 로 자동 업데이트. 이게 4단계 학습 자산화의 시작." / 👀 cursor `CE 0.78 → 0.71` 비교 카드 sweep | CE 비교 카드 |
| **4:40** | **👆 클릭: `Next ▶`** | M7 진입 |

---

### Marker 7 — ⭐ 4 Agent (4:40 ~ 5:18, 38s)

화면 변화: 4 Domain Agent 카드 4개 (품질·안전·설비·생산), Bedrock cache_replay latency caption.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 4:40~4:43 | 화면 안정화 wait (Bedrock cache_replay lookup ~ms) | 4 Agent grid 형성 |
| 4:43~4:50 | 🎤 "이제 4 Agent 협상 시작." / 👀 cursor 4 카드 위 큰 원 (좌상→우상→우하→좌하) | 4 카드 전체 |
| 4:50~4:55 | 🎤 "품질 Agent: 위험 — HDF." / 👆 cursor 품질 카드 hover, defect_prob 메트릭 | 품질 카드 |
| 4:55~5:00 | 🎤 "안전 Agent: SOP 위반 — 감속 필요." / 👆 cursor 안전 카드 hover | 안전 카드 |
| 5:00~5:05 | 🎤 "설비 Agent: 정비 시급 — RUL 18시간." / 👆 cursor 설비 카드 hover | 설비 카드 |
| 5:05~5:10 | 🎤 "생산 Agent: 그래도 진행 가능 — UPH 235." / 👆 cursor 생산 카드 hover | 생산 카드 |
| 5:10~5:16 | 🎤 "3 vs 1 의견 충돌입니다." / 👀 cursor 4 카드 중앙 + Bedrock latency caption | latency caption |
| **5:18** | **👆 클릭: `Next ▶`** | M8 진입 |

---

### Marker 8 — 🔑 Supervisor + β slider (5:18 ~ 6:03, 45s)

> **여기서 사이드바 β slider 가 핵심 인터랙션**. 베타 1.0 (기본) → 2.0 → (옵션) 5.0 순차 이동.
> 각 slider 이동 후 Supervisor decision 카드가 라이브로 재계산됨 (Streamlit `st.rerun` 자동).

화면 변화: Supervisor decision 카드 (`continue` 또는 `throttle_50pct`) + Net Value KRW + 4 Agent 협상 근거.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 5:18~5:22 | 화면 안정화 wait | Supervisor 카드 형성 |
| 5:22~5:30 | 🎤 "Sonnet Supervisor 가 Net Value 로 협상." / 👆 cursor Supervisor decision 카드 `action_id: continue` + `net_value_KRW: +X억` hover | decision 카드 |
| 5:30~5:35 | 🎤 "기본 베타 1.0 에서는 continue, +1억원." / 👀 cursor 사이드바 **β slider** 위 hover (아직 클릭 X) | β slider |
| **5:35** | **👆 클릭/드래그: β slider 1.0 → 2.0** (정확히 2.0 stop) | slider 이동 |
| 5:35~5:42 | 🎤 "하지만 평가자께서 보수성을 높이고 싶으면 — [beta slider 2.0 으로 이동]" / 👀 cursor decision 카드 — `action_id` 가 `throttle_50pct` 로 자동 변경 확인 | decision 재계산 |
| 5:42~5:48 | 🎤 "바로 throttle_50pct 로 권고가 바뀝니다." / 👀 cursor `net_value_KRW` 메트릭 변화 hover | Net Value 변화 |
| 5:48~6:00 | 🎤 "이게 명시적 협상 — 모호한 AI 의사결정이 아닙니다." / 👀 cursor 4 Agent 카드 + Supervisor 카드 묶어서 큰 원 | 협상 전체 |
| **6:03** | **👆 클릭: `Next ▶`** | M9 진입 |

> ⚠️ β slider 이동 후 **β=2.0 으로 두고 다음 마커로**. M9/M10 narrative 영향 없음 (slider 는 M8 한정).
> 더 임팩트 원하면 **β=5.0 까지 한 번 더 sweep** (선택) — 단 시간 5초 추가 → M9 시작 6:08 로 밀림.

---

### Marker 9 — 재학습 (6:03 ~ 6:25, 22s)

화면 변화: 라이브 incident test 정확도 0.81 → 0.97 + per-class F1 chart (HDF +6%p) + feature importance 변화 (motor_temp_max 0.18 → 0.31).

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 6:03~6:13 | 🎤 "인시던트 패턴 자동 학습 — incident test 정확도 0.81 → 0.97, 20% 향상. 라이브 XGBoost fit() 1.76s." / 👆 cursor 정확도 metric hover | live accuracy |
| 6:13~6:23 | 🎤 "HDF F1 +6%p — incident extreme outlier 패턴이 모델 결정 트리에 흡수됐습니다." / 👀 cursor feature importance (motor_temp_max 0.18→0.31 강조) | feature importance |
| **6:25** | **👆 클릭: `Next ▶`** | M10 진입 |

---

### Marker 10 — ⭐ OEE + 클로징 (6:25 ~ 7:03, 38s)

화면 변화: render_oee_evidence (Nakajima 표준) + render_closed_loop_summary + render_cost_impact.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 6:25~6:35 | 🎤 "최종 OEE +35%. Nakajima 표준 — 가용, 성능, 품질 모두 개선." / 👆 cursor OEE evidence 카드 hover, 3 sub-metric 차례로 | OEE evidence |
| 6:35~6:50 | 🎤 "비용 임팩트: 연 24만원 PRISM vs MES 천만원 — 98% 감소." / 👆 cursor cost_impact 카드 hover, `-98%` 강조 | 비용 카드 |
| 6:50~7:00 | 🎤 "1인 메이커스페이스가 엔터프라이즈급 RCA + 인과 추론을 활용합니다." / 👀 cursor closed_loop_summary 카드 전체 sweep | closed-loop 카드 |
| 7:00~7:03 | 🎤 "시연 끝났습니다. 질문 받겠습니다." / 👀 cursor 화면 상단 PRISM 헤더로 복귀 | 헤더 |
| **7:03** | 녹화 정지 또는 fade-out 추가 take | end |

> **클로징 fade**: 영상 편집에서 7:03 ~ 7:15 까지 검은 fade + PRISM 로고 still 권장.

---

## 3. 자주 실수하는 cut point + 재녹화 권장

| 실수 패턴 | 영향 | 대응 |
|---|---|---|
| M0 사이드바 expander 클릭 누락 | refute 4개 안 보임 → "자세히" 메시지 약화 | M0 take 재녹화 (120s) |
| M4 DoWhy 라이브 spinner | 화면 5초 정지 | 같은 마커 2회 navigation (M3↔M4) 후 cache hit 후 재시작 |
| M8 β slider 1.0 그대로 | decision 변화 시연 실패 = 핵심 임팩트 0 | M8 take **반드시** 재녹화 |
| 우측 컬럼 cursor 가 Next 버튼 위에 안 머무름 → 클릭 누락 | timeline 안 넘어감 | 화면 끝나서야 발견 → 처음부터 재녹화 |
| α/β/γ slider M0 에서 실수 클릭 | M8 base 상태 깨짐 | 즉시 처음으로 reset 후 처음부터 |

---

## 4. take 후 영상 편집 체크리스트

- [ ] 7:03 시점 정확 (오차 ±5초 허용)
- [ ] β slider M8 인터랙션 명확히 보임 (decision 카드 변화 frame 포함)
- [ ] M0 두 개 expander 모두 펼침 확인 (refute 4 헤더 + Wright 1991 텍스트)
- [ ] cursor 가 화면 밖으로 나간 시점 없음
- [ ] narration 과 화면 sync (±0.5s 이내)
- [ ] 클로징 fade-out 12~15s
- [ ] resolution 1920×1080, 30fps, MP4 (H.264) export
- [ ] 파일명 `prism_demo_master.mp4`, 위치 `presentation/`

---

## 5. fallback 영상 production 빌드

본 영상을 그대로 `presentation/prism_demo_master.mp4` 로 배포:

```bash
# 영상 ready 확인 (offline fallback gate)
ls -lh presentation/prism_demo_master.mp4
# Streamlit cache miss / Bedrock timeout 시 자동 swap (apps/prism_demo.py::fallback_video)
```

`apps/prism_demo.py:1502` 의 `fallback_video()` 가 위 경로 mp4 를 자동 재생.
파일이 없으면 `Recording pending D-1 (presentation/prism_demo_master.mp4)` 경고 출력 — 본 영상이
**offline 시연 안전망**.

---

**행운을 빈다 🎬 — D-Day 2026-05-22, 본선 통과.**

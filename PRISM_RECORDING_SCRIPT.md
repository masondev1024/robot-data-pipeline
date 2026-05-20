# PRISM 발표 녹화 스크립트 (Screen Recording Cue Sheet)

> **목적**: 본선 발표 영상 자료 + offline fallback (`presentation/prism_demo_master.mp4`) 동시
> 생성. 9분 시연 timeline 을 **second-precise UI 조작 cue** 로 풀어놓은 문서.
>
> **참조 관계**:
> - 멘트(narration) = [`PRISM_TALKING_POINTS.md`](PRISM_TALKING_POINTS.md) 마커별 블록 그대로.
> - 라이브 운영 매뉴얼 = [`PRISM_DEMO_DAY.md`](PRISM_DEMO_DAY.md).
> - **이 문서 = 클릭/머무름/cursor 위치/take 컷 포인트** 에만 집중.
>
> **기준 timing**: cumulative 0:00 ~ 8:36 (516s 본론 + 10~15s 클로징 fade).
> M5 결함 발생 직후 **운영자 대시보드 (Operator View) 전환** 43s, M10 클로징에
> **Enterprise Scale-out Vision (V3) 전환** 50s 추가 — 평가자에게 실 운영 UX +
> production scale-out 비전까지 한 영상에서 보여주는 구조.

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
- **view mode 전환 2회 (M5 → Operator, M10 → V3, 둘 다 복귀)** — 사이드바 라디오 클릭 정확도 필수.

---

## 1. Timeline 마스터 표 (재확인용)

| Marker | Start | End | Dur | 강조 | 주요 UI 액션 |
|---|---|---|---|---|---|
| M0 | 0:00 | 2:00 | 120s | 사이드바 deep dive | expander 2번 열기 (자세히 / 학술 ref) |
| M1 | 2:00 | 2:22 | 22s | XGBoost 라이브 | TWF bar 가리키기 |
| M2 | 2:22 | 2:50 | 28s | 인과 v1 | DAG tool_age 노드 hover |
| M3 | 2:50 | 3:12 | 22s | 보류 결정 | "보류" 메트릭 카드 가리키기 |
| M4 | 3:12 | 3:50 | 38s | ⭐ DoWhy ATE | latency caption + ATE Δ 메트릭 |
| **M5** | **3:50** | **4:55** | **65s** | 🚨 **결함 + 운영자 대시보드** | motor_temp 105°C + **view mode toggle → Operator View** |
| M6 | 4:55 | 5:23 | 28s | 인과 v2 | DAG color 변화 |
| M7 | 5:23 | 6:01 | 38s | ⭐ 4 Agent | Bedrock latency caption |
| M8 | 6:01 | 6:46 | 45s | 🔑 β slider | **slider 1.0 → 2.0 → 5.0** |
| M9 | 6:46 | 7:08 | 22s | 재학습 | 라이브 0.81→0.97 evidence |
| **M10** | **7:08** | **8:36** | **88s** | ⭐ OEE + 🚀 **V3 Enterprise Vision** | KPI/비용 + **view mode toggle → V3** 5 layer sweep + closing |

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

### Marker 5 — 🚨 결함 발생 + Operator View 전환 (3:50 ~ 4:55, 65s)

> **2 phase 구조**: ① Timeline view 에서 incident 알람 (3:50~4:12, 22s) →
> ② **사이드바 view mode → "🚨 운영자 대시보드 (Operator View)"** 전환 후
> 실 운영자 UX 시연 (4:12~4:52, 40s) → ③ Timeline View 복귀 (4:52~4:55, 3s).

화면 변화 (Phase 1): incident alert (red), motor_temp 105°C 메트릭, DuckDB seed 100 rows 기반 fault timeline.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 3:50~3:58 | 🎤 "실제 결함 발생. motor_temp 105도 — SOP 임계 100도 초과." / 👆 cursor `motor_temp 105°C` 표시 위 hover | incident alert 박스 |
| 3:58~4:08 | 🎤 "사전 예지가 실제 발현됐습니다. INCIDENT #47." / 👀 cursor incident 카드 전체 sweep | 카드 전체 |
| 4:08~4:12 | 🎤 "근데 실 운영자는 이 timeline view 안 봐요. 매일 보는 화면이 따로 있습니다 — 잠시 전환해 보겠습니다." / 👀 cursor 사이드바 view mode 라디오 위 hover | view mode 라디오 |
| **4:12** | **👆 클릭: 사이드바 `🚨 운영자 대시보드 (Operator View)`** | view 전환 (~0.5s rerun) |

화면 변화 (Phase 2 — Operator View): 헤더 변경 → "🎛️ 운영자 대시보드 (Production UX)" + **3-col Fleet KPI bar** (Fleet 규모 10대 / 정상 9대 / Incident 1대) + 🚨 **ALARM 카드** (red, CNC-01 incident #47) + 3 의사결정 버튼 (적용/보류/정지) + 최근 5 incident table + 최근 30s sensor mini chart.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 4:12~4:15 | 화면 안정화 wait (view 전환 rerun) | Operator View 전체 형성 |
| 4:15~4:22 | 🎤 "이게 실제 운영자가 매일 보는 화면입니다. 평소엔 background — 결함 발생하면 이 alarm 화면이 자동 팝업." / 👀 cursor 🚨 ALARM 카드 hover | ALARM 카드 |
| 4:22~4:28 | 🎤 "Fleet 컨텍스트가 위쪽 3 KPI — 10대 전체, 정상 9대, incident 1대 (CNC-01)." / 👆 cursor 3-col KPI bar 좌→우 (`Fleet 규모` → `정상` → `Incident`) | Fleet KPI bar |
| 4:28~4:38 | 🎤 "운영자는 30초 안에 의사결정 — AI 추천 적용, 보류, 즉시 정지 세 버튼." / 👆 cursor `✅ AI 추천 적용` / `⏸ 보류` / `🛑 즉시 정지` 버튼 차례로 hover (절대 클릭 X — toast 발화 시 화면 어지러움) | 3 의사결정 버튼 |
| 4:38~4:45 | 🎤 "그 밑은 최근 incident 5건과 30초 sensor 추세 — 결정 input 다시 확인용." / 👀 cursor 최근 5 incident 테이블 → sensor mini chart 까지 좌→우 sweep | history + chart |
| 4:45~4:52 | 🎤 "평소엔 이 화면 안 보고, 결함 때만 이 화면. Slack 알람 + 30초 결정 — 1인 운영자 production UX." / 👀 cursor 화면 우측 사이드바 view mode 라디오 위 복귀 | view mode 라디오 ready |
| **4:52** | **👆 클릭: 사이드바 `전체 시연 (Timeline View)` 복귀** | Timeline View 복원 (~0.5s rerun) |
| 4:52~4:55 | 화면 안정화 + 🎤 "다시 timeline 으로 돌아가겠습니다." / 👀 cursor 우측 `Next ▶` 버튼 hover | Timeline 복귀 |
| **4:55** | **👆 클릭: `Next ▶`** | M6 진입 |

> ⚠️ **컷 포인트**: 4:12 view 전환 직전, 4:52 복귀 직후 — 둘 다 take 분할 후보.
> view 전환 클릭 정확도가 핵심 — 라디오 박스 다른 옵션 잘못 클릭 시 V3 view 가 떠버려 narrative 깨짐.

---

### Marker 6 — 인과 v2 (4:55 ~ 5:23, 28s)

화면 변화: DAG v2 — `coolant_temp` mediator 추가 학습 표시, CE 0.78 → 0.71 비교 카드.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 4:55~5:05 | 🎤 "새로운 인과 path 발견 — coolant_temp 가 thermal_drift 에 영향." / 👆 cursor DAG `coolant_temp` 새 path edge 위 hover | DAG 신규 edge |
| 5:05~5:18 | 🎤 "DAG v2 로 자동 업데이트. 이게 4단계 학습 자산화의 시작." / 👀 cursor `CE 0.78 → 0.71` 비교 카드 sweep | CE 비교 카드 |
| **5:23** | **👆 클릭: `Next ▶`** | M7 진입 |

---

### Marker 7 — ⭐ 4 Agent (5:23 ~ 6:01, 38s)

화면 변화: 4 Domain Agent 카드 4개 (품질·안전·설비·생산), Bedrock cache_replay latency caption.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 5:23~5:26 | 화면 안정화 wait (Bedrock cache_replay lookup ~ms) | 4 Agent grid 형성 |
| 5:26~5:33 | 🎤 "이제 4 Agent 협상 시작." / 👀 cursor 4 카드 위 큰 원 (좌상→우상→우하→좌하) | 4 카드 전체 |
| 5:33~5:38 | 🎤 "품질 Agent: 위험 — HDF." / 👆 cursor 품질 카드 hover, defect_prob 메트릭 | 품질 카드 |
| 5:38~5:43 | 🎤 "안전 Agent: SOP 위반 — 감속 필요." / 👆 cursor 안전 카드 hover | 안전 카드 |
| 5:43~5:48 | 🎤 "설비 Agent: 정비 시급 — RUL 18시간." / 👆 cursor 설비 카드 hover | 설비 카드 |
| 5:48~5:53 | 🎤 "생산 Agent: 그래도 진행 가능 — UPH 235." / 👆 cursor 생산 카드 hover | 생산 카드 |
| 5:53~5:59 | 🎤 "3 vs 1 의견 충돌입니다." / 👀 cursor 4 카드 중앙 + Bedrock latency caption | latency caption |
| **6:01** | **👆 클릭: `Next ▶`** | M8 진입 |

---

### Marker 8 — 🔑 Supervisor + β slider (6:01 ~ 6:46, 45s)

> **여기서 사이드바 β slider 가 핵심 인터랙션**. 베타 1.0 (기본) → 2.0 → (옵션) 5.0 순차 이동.
> 각 slider 이동 후 Supervisor decision 카드가 라이브로 재계산됨 (Streamlit `st.rerun` 자동).

화면 변화: Supervisor decision 카드 (`continue` 또는 `throttle_50pct`) + Net Value KRW + 4 Agent 협상 근거.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 6:01~6:05 | 화면 안정화 wait | Supervisor 카드 형성 |
| 6:05~6:13 | 🎤 "Sonnet Supervisor 가 Net Value 로 협상." / 👆 cursor Supervisor decision 카드 `action_id: continue` + `net_value_KRW: +X억` hover | decision 카드 |
| 6:13~6:18 | 🎤 "기본 베타 1.0 에서는 continue, +1억원." / 👀 cursor 사이드바 **β slider** 위 hover (아직 클릭 X) | β slider |
| **6:18** | **👆 클릭/드래그: β slider 1.0 → 2.0** (정확히 2.0 stop) | slider 이동 |
| 6:18~6:25 | 🎤 "하지만 평가자께서 보수성을 높이고 싶으면 — [beta slider 2.0 으로 이동]" / 👀 cursor decision 카드 — `action_id` 가 `throttle_50pct` 로 자동 변경 확인 | decision 재계산 |
| 6:25~6:31 | 🎤 "바로 throttle_50pct 로 권고가 바뀝니다." / 👀 cursor `net_value_KRW` 메트릭 변화 hover | Net Value 변화 |
| 6:31~6:43 | 🎤 "이게 명시적 협상 — 모호한 AI 의사결정이 아닙니다." / 👀 cursor 4 Agent 카드 + Supervisor 카드 묶어서 큰 원 | 협상 전체 |
| **6:46** | **👆 클릭: `Next ▶`** | M9 진입 |

> ⚠️ β slider 이동 후 **β=2.0 으로 두고 다음 마커로**. M9/M10 narrative 영향 없음 (slider 는 M8 한정).
> 더 임팩트 원하면 **β=5.0 까지 한 번 더 sweep** (선택) — 단 시간 5초 추가 → M9 시작 6:51 로 밀림.

---

### Marker 9 — 재학습 (6:46 ~ 7:08, 22s)

화면 변화: 라이브 incident test 정확도 **0.8067 → 0.9667 (+19.8%)** + per-class F1 chart (HDF 0.695 → 0.752 +5.7%p) + feature importance 변화 (motor_temp_max 0.18 → 0.31).

> ⚠️ **앱 시작 시 cache_resource 가 cold 면 첫 M9 진입에 spinner ~2s**.
> 녹화 전 한 번 M9 까지 navigation 해서 cache warm 시키고 → 처음으로 reset → take.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 6:46~6:51 | 화면 안정화 wait (cache warm 가정, instant render) | F1 chart + metric 형성 |
| 6:51~7:01 | 🎤 "인시던트 패턴 자동 학습 — incident test 정확도 0.81 → 0.97, 20% 향상. 라이브 XGBoost fit() 1.76s." / 👆 cursor `재학습 후 정확도 0.9667` metric + delta `+0.16 (+19.8%)` hover | live accuracy metric |
| 7:01~7:06 | 🎤 "HDF F1 +6%p — incident extreme outlier 패턴이 모델 결정 트리에 흡수됐습니다." / 👀 cursor F1 chart HDF bar (재학습 전 0.69 / 후 0.75) hover, 그 다음 feature importance motor_temp_max 0.18→0.31 카드 | F1 chart + feature importance |
| **7:08** | **👆 클릭: `Next ▶`** | M10 진입 |

> 💡 **선택**: 7:06~7:08 사이에 **"🔄 재학습 실행 (라이브)" 버튼 클릭** → 스피너 2s →
> 같은 결과 재현 (결정성 증거). M10 진입이 7:10 로 살짝 밀리지만 학술 평가자에게 강한 신호.

---

### Marker 10 — ⭐ OEE + 🚀 V3 Enterprise Vision + 클로징 (7:08 ~ 8:36, 88s)

> **3 phase 구조**: ① Timeline view 에서 OEE/비용 evidence (7:08~7:43, 35s) →
> ② **사이드바 view mode → "🚀 Enterprise Scale-out Vision (V3)"** 전환 후
> 5 layer scale-out 비전 시연 (7:43~8:33, 50s) → ③ V3 view 그대로 클로징 (8:33~8:36, 3s).

화면 변화 (Phase 1): render_oee_evidence (Nakajima 표준 — OEE 34.1% → 66.5%, delta `+32.4%p (절대)`) + render_closed_loop_summary (재학습 정확도 0.97 카드) + render_cost_impact.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 7:08~7:18 | 🎤 "최종 OEE 0.34 → 0.67, +32%p Nakajima 절대 표준. 가용·성능·품질 모두 개선." / 👆 cursor OEE evidence 카드 hover, 3 sub-bar (가용 0.75→0.85 / 성능 0.70→0.85 / 품질 0.65→0.92) 차례로 | OEE evidence (Nakajima 1989) |
| 7:18~7:33 | 🎤 "비용 임팩트: 연 24만원 PRISM vs MES 천만원 — 98% 감소." / 👆 cursor cost_impact 카드 `-97.6%` delta + `연간 절감 ₩9,760,000+` 메트릭 hover | 비용 카드 |
| 7:33~7:41 | 🎤 "1인 메이커스페이스가 엔터프라이즈급 RCA + 인과 추론을 활용합니다." / 👀 cursor closed_loop_summary 4카드 (센서통합/인과RCA/Multi-Agent/학습자산화) 좌→우 sweep | closed-loop 4카드 |
| 7:41~7:43 | 🎤 "그리고 이 구조가 어떻게 1000대 production 으로 확장되는지 — 마지막으로 한 화면 보여드리겠습니다." / 👀 cursor 사이드바 view mode 라디오 hover | view mode 라디오 |
| **7:43** | **👆 클릭: 사이드바 `🚀 Enterprise Scale-out Vision (V3)`** | view 전환 (~0.5s rerun) |

화면 변화 (Phase 2 — V3 View): 헤더 → "🚀 PRISM MVP → V3 Enterprise Scale-out Vision" + intro info 박스 (CNC fleet 10대 시연 → 1000대 robot 확장) + 5 layer 카드 (Streaming / ETL / Portal / ML Inference / LLM Operator) — 각 카드 좌측 production 스크린샷 + 우측 MVP vs V3 비교.

| cum_t | 액션 | 화면 포커스 |
|---|---|---|
| 7:43~7:48 | 화면 안정화 wait (V3 view rerun) / 🎤 "PRISM MVP 는 노트북 1대 + 10대 fleet, production 진입 시 같은 인과 DAG 구조 그대로." / 👀 cursor intro info 박스 sweep | V3 intro |
| 7:48~7:55 | 🎤 "1번 Streaming Layer — MVP 의 in-process DuckDB 가 production 에서 Kinesis Data Streams 로." / 👆 cursor Layer 1 카드 (KDS 스크린샷 → MVP/V3 텍스트) sweep | Layer 1 |
| 7:55~8:02 | 🎤 "2번 ETL — 단일 Streamlit narrative 가 Airflow 5단계 medallion 자동화로." / 👆 cursor Layer 2 카드 sweep | Layer 2 |
| 8:02~8:09 | 🎤 "3번 Enterprise Portal — 단일 대시보드가 1000대 fleet KPI + 116 이상치 + TOP 10 점검 대상 portal 로." / 👆 cursor Layer 3 카드 sweep | Layer 3 |
| 8:09~8:16 | 🎤 "4번 ML Inference — 라이브 local_predictor 가 production 자동채우기 + HIGH/MEDIUM threshold 가이드로." / 👆 cursor Layer 4 카드 sweep | Layer 4 |
| 8:16~8:23 | 🎤 "5번 LLM Operator — Supervisor cache replay 가 Claude Bedrock 자연어 drill-down 으로." / 👆 cursor Layer 5 카드 sweep | Layer 5 |
| 8:23~8:33 | 🎤 "핵심은 동일 6-Node 인과 DAG — 식품·물류·반도체 transfer 까지 가능합니다. 도메인이 바뀌어도 구조는 그대로." / 👀 cursor 하단 success 박스 (transfer narrative) sweep | scale-out 종합 |
| 8:33~8:36 | 🎤 "시연 끝났습니다. 질문 받겠습니다." / 👀 cursor 화면 상단 V3 헤더 ("PRISM MVP → V3 …") 위 복귀 | V3 헤더 |
| **8:36** | 녹화 정지 또는 fade-out 추가 take (V3 view 그대로 freeze 권장) | end |

> **클로징 fade**: 영상 편집에서 8:36 ~ 8:50 까지 검은 fade + PRISM 로고 still 권장.
> V3 view 마지막 화면이 클로징 still 로도 좋은 framing — production scale-out 메시지가 마지막 인상.

---

## 3. 자주 실수하는 cut point + 재녹화 권장

| 실수 패턴 | 영향 | 대응 |
|---|---|---|
| M0 사이드바 expander 클릭 누락 | refute 4개 안 보임 → "자세히" 메시지 약화 | M0 take 재녹화 (120s) |
| M4 DoWhy 라이브 spinner | 화면 5초 정지 | 같은 마커 2회 navigation (M3↔M4) 후 cache hit 후 재시작 |
| **M5 view mode 라디오 다른 옵션 클릭 (V3)** | Operator View 가 아닌 V3 가 떠 narrative 깨짐 | 즉시 Timeline 복귀 → M5 take 재녹화 (65s) |
| M5 Operator View 의 의사결정 버튼 실수 클릭 | toast 알림 발화 + 화면 어지러움 | hover 만, 클릭 X. 실수 시 즉시 take 종료 |
| M8 β slider 1.0 그대로 | decision 변화 시연 실패 = 핵심 임팩트 0 | M8 take **반드시** 재녹화 |
| **M10 view mode → V3 전환 누락** | scale-out 비전 시연 0 → 영상 OEE 카드에서 종료 | 7:43 cue 강조 표시 (사전 mental rehearsal 필수) |
| 우측 컬럼 cursor 가 Next 버튼 위에 안 머무름 → 클릭 누락 | timeline 안 넘어감 | 화면 끝나서야 발견 → 처음부터 재녹화 |
| α/β/γ slider M0 에서 실수 클릭 | M8 base 상태 깨짐 | 즉시 처음으로 reset 후 처음부터 |

---

## 4. take 후 영상 편집 체크리스트

- [ ] 8:36 시점 정확 (오차 ±5초 허용)
- [ ] β slider M8 인터랙션 명확히 보임 (decision 카드 변화 frame 포함)
- [ ] M0 두 개 expander 모두 펼침 확인 (refute 4 헤더 + Wright 1991 텍스트)
- [ ] **M5 view mode 전환 2회 (Operator → Timeline) 정확히 frame 잡혔는지**
- [ ] **M10 view mode 전환 1회 (V3) 정확 + V3 5 layer 모두 hover 됐는지**
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

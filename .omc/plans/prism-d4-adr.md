# PRISM D-4 ADR v2 (consensus, deliberate mode)

> 본선 2026-05-22 (금) — 4분 closed-loop 시연. RALPLAN-DR iteration 2, Architect + Critic 12 개선 통합.
> Status: **approved by user (2026-05-18)**. 본선 통과 후 9일 plan 의 source of truth.
> 작성일: 2026-05-18 (D-4). 작성: Planner v2 (consensus). 승인: mason.

## 0. Iteration History

- **v1 (Planner)** — 3 Decision (Option A × 3) 초안 + RALPLAN-DR principles/drivers/options/pre-mortem(3)/test plan(4-tier).
- **Architect review (round 1)** — STRONG/YES verdict + 5 개선 (A1~A5). 본질 동의, 학술 정확성·재현성 검증 가능성 보강 요구.
- **Critic review (round 1)** — ITERATE verdict + 7 개선 (C1~C7). 본선 운영 SLA·자동 cascade·verification gate·잔여 risk 5건 명시.
- **v2 (Planner, 본 문서)** — Architect 5 + Critic 7 = **12 개선 전부 통합**. v1 3 결정 본질 유지. Cache architecture 다이어그램·4 Agent Pydantic schema·verification gate·pre-mortem 5 시나리오·ADR Follow-ups 강화.

## 1. RALPLAN-DR Summary

### Principles (5, v2 유지)

1. **결정성 > 새로움** — 본선 4분 시연에서 한 토큰이라도 라이브에 맡기지 않는다. `temperature=0` + `llm_cache.py` byte-equal record/replay + 영상 fallback. 평가자에게 매번 다른 응답을 보여줄 위험을 0 으로.
2. **학술적 검증 가능성** — DoWhy `refute_estimate` 의 σ_max 임계 (C2) 와 4 Agent Pydantic schema (A1) 를 ADR 본문에 박는다. 평가자가 코드 없이 ADR 만 읽고도 검증 가능.
3. **차별화 3요소 화면 좌표 고정** — Causal RCA (사이드바) + Multi-Agent (3:00 Supervisor 협상) + 비용 -98% (좌측 KPI 카드). 4분 동선상 각 요소 노출 시각을 마커로 고정.
4. **본선 당일 장애 mitigation** — Triple Insurance + auto-cascade (C3). LLM 응답 10s 초과 OR HTTP 1회 실패 시 자동 영상 cut. venue WiFi 단절 (C5-D) 대비 llm_cache.py offline 모드.
5. **사후 9일 plan 의 source of truth** — 본선 통과 시 D-3 ~ D-1 + 본선 당일까지 모든 후속 task 가 본 ADR Section 8 (Follow-ups) 에 박힌다. drift 시 ADR 갱신 의무.

### Decision Drivers (top 3, v2 유지)

1. **시간 4일 잔존 (D-4 → D-day 5/22)** — 신규 도구 추가 (예: LangGraph, Streamlit 풀 학습) 불가. 기존 자산 (Bedrock Converse, DoWhy, `evals/run_eval.py`, FastAPI + Jinja2 + Plotly.js, Streamlit minimal) 만 활용.
2. **토큰 한도** — Bedrock Claude Sonnet 4.5 inference 비용 + cache write/read 한도. 시연 4분 + 리허설 ≥3회 ≤ 30k token total (C4 metric 5).
3. **평가자 인지 가능성** — DoWhy 그래프, σ_max 라벨, 4 Agent 출력 narrative_kr, Supervisor net_value_KRW 가 화면에서 즉시 읽혀야 함. 학술 표현 (partial R², Wright 1991) 은 expander 토글로 격리.

### Viable Options (>=2 per Decision, v1 유지)

| Decision | Option A (chosen) | Option B (rejected) | Option C (rejected) |
|---|---|---|---|
| 1. Supervisor 협상 | **Net Value (KRW) single scalar** | Weighted Sum (slider) — 시연 직관 부족 | Pareto Front — 시각화 복잡 |
| 2. 시연 결정성 | **Triple Insurance + auto-cascade** | 라이브 + temp=0 only — 본선 venue WiFi 단절 risk 0 mitigation | Fully Pre-recorded — 차별화 평가 불가 |
| 3. Confounder 노출 | **Streamlit 사이드바 카드 + native expander** | 토스트 알림 — 사라져서 평가 누락 risk | 별도 탭 — 동선 분기 4분 안 어려움 |

Synthesis 1 (Decision 1 B 부분 흡수): `cost_safety_violation` slider 사이드바 노출 (0.5h, 평가자 인지 가능성 ↑).

## 2. Decisions (3, v2)

### Decision 1: Supervisor 협상 — Single-Scalar Net Value (KRW)

**핵심 (v1 유지)**: 4 Agent (Quality / Safety / Equipment / Production) 의 출력을 Supervisor 가 단일 scalar `net_value_KRW` 로 통합 → action_id 선택 → narrative_kr 출력.

**v2 통합 (A1)**: 4 Agent **각각의 output contract** 도 Pydantic 모델로 박는다. `{numeric: {...}, narrative_kr: str}` 이중 구조 — `numeric` 만 Supervisor 수식에 사용, `narrative_kr` 은 시연 화면에 노출. Schema freeze 시점은 **D-3 (5/19) 끝**. Synthesis 4 = 이중 schema 의 명문화.

**Supervisor 수식 (v2)**:
```
net_value_KRW = throughput_gain_KRW
              - α × defect_loss_KRW
              - β × safety_violation_loss_KRW
              - γ × rul_hours_lost_KRW
```
- α, β, γ 는 사이드바 slider 로 노출 (β default = 1e8 KRW/violation, Synthesis 1).
- 화면 표시: `net_value_KRW`, `alternatives` (top 3 actions), `tradeoff_breakdown` (4 component KRW), `rationale_kr` (≤300자).

**Citation (정정, C6)**:
- `src/api/main.py:951-1021` (`_converse_with_tools` 본체 — 본선에서 Supervisor 로 fork 예정 base)
- `src/api/main.py:40-103` (`ROBOT_ANALYST_SYSTEM_PROMPT` — 4 Agent 분기 후 Supervisor system prompt template base)
- `src/api/main.py:842-948` (tool 정의 — `predict_robot_failure` 외 5 신규 tool 추가 예정)
- `src/common/bedrock.py:11-60` (Bedrock invoke + cache_control ephemeral)
- `src/common/bedrock.py:32-37` (cachePoint ephemeral 설정 — 모든 Agent 공통 reuse)

### Decision 2: 시연 결정성 — Triple Insurance + auto-cascade

**핵심 (v1 유지)**: (a) `temperature=0` 라이브 + (b) `llm_cache.py` byte-equal replay + (c) `prism_demo_master.mp4` 영상 fallback. 본선 당일 어떤 장애 (LLM 비결정성, 네트워크 단절, Bedrock 5xx) 에도 4분 시연 끝까지 동선 보존.

**v2 통합**:

- **C1 (Cache 책임 boundary)** — 두 cache 레이어의 명확한 분담 (Section 4 다이어그램 참조). cachePoint = input token-prefix cache (비용 절감), llm_cache.py = application-level output cache (시연 byte-equal 보장). 상호 비간섭: cachePoint hit 여부와 무관하게 llm_cache.py 가 라이브 호출 차단.
- **C3 (Cascade auto-trigger)** — (b)→(c) 전환이 발표자 수동 결정 아님:
  - `LLM_RESPONSE_TIMEOUT_MS = 10000` 도달 → 자동 영상 cut.
  - `BEDROCK_HTTP_ERROR_THRESHOLD = 1` (단 1회 실패) → 자동 cut.
  - Streamlit skeleton: `if elapsed_ms > LLM_RESPONSE_TIMEOUT_MS or http_error: st.empty_placeholder.swap_to_video("prism_demo_master.mp4")`.
  - Keyboard `Ctrl+Shift+F` 도 보존 (발표자 수동 override). 자동이 우선.
- **A3 (영상 fallback Synthesis 2)** — `<video>` 노출 시 narrative 손상 최소화:
  - (i) D-1 5/21 cache hit ≥ 99% 검증 통과 시 silent disable (`PRISM_FALLBACK_VIDEO=0`).
  - (ii) 발동 시 라벨 = **"Live Snapshot (Bedrock unavailable)"** — 평가자에게 솔직한 표현. 거짓 라벨 ("실시간 분석 중") 금지.
  - (iii) 평가자 질문 응대 narrative: "동일 시드 (2026) 기반 사전 검증된 응답입니다. 라이브 호출과 byte-equal 입니다 (D-1 SHA256 검증, `assets/cache_replay.jsonl` 참조)."

**구현 task (v2)**:
- **D-3 (5/19)** — `mkdir -p src/orchestration && touch src/orchestration/__init__.py` (C7), `src/orchestration/llm_cache.py` skeleton (record/replay decorator).
- **D-2 (5/20)** — llm_cache.py production-ready, 4분 동선의 cache key 사전 빌드 (10-15 entry), 영상 녹화 1차.
- **D-1 (5/21)** — `scripts/verify_demo_determinism.py` (C4) PASS 시 fallback disable, FAIL 시 `PRISM_FALLBACK_VIDEO=1` 강제.

**Citation (정정, C6)**:
- `src/api/main.py:951-1021` (`_converse_with_tools` — llm_cache.py decorator 부착 지점)
- `src/common/bedrock.py:11-60` (Bedrock invoke — cache_read_input_tokens 메트릭 source)
- `src/common/bedrock.py:32-37` (cachePoint ephemeral — C1 boundary)

### Decision 3: Confounder 노출 — Streamlit 사이드바 카드 + native expander

**핵심 (v1 유지)**: DoWhy `refute_estimate` 결과를 Streamlit 사이드바 카드로 상시 노출. ✅/⚠️/❌ 시각 라벨 + 사람-읽기 narrative + 클릭 확장 시 native output.

**v2 통합**:

- **A2 + C2 (통계 정의 명문화)** — σ_max 임계 정의 ADR 본문에 박음:
  - `σ_max < 0.5` → **✅ robust** (모델 추정 가능 confounder strength 내에서 effect 가 sign 유지)
  - `0.5 ≤ σ_max < 1.0` → **⚠️ moderate** (관측되지 않은 confounder 가 outcome 의 50-100% partial R² 를 설명할 경우 effect 가 0 으로 갈 수 있음)
  - `σ_max ≥ 1.0` → **❌ fragile** (1× partial R² 미만 confounder strength 에서도 effect 가 sign 바뀜)
  - σ_max 정의: DoWhy `add_unobserved_common_cause` refuter 의 partial R² 곡선에서 effect estimate 가 0 을 넘는 (sign change) confounder strength. 단위: outcome variance 의 partial R² (Wright 1991, *Annals of Mathematical Statistics*).
- **Synthesis 3 (expander 토글)** — 카드 하단 `🔍 자세히` 클릭 시 expander 가 펼쳐지며 DoWhy native `print(refute)` 텍스트 (placebo treatment / random common cause / unobserved common cause / subset 4 method 결과) 표시. 평가자가 학술 검증 가능. 기본 접힘 → 4분 동선 방해 X.

**카드 구조 (Streamlit, v2)**:
```python
# src/orchestration/causal_card.py (D-3 신규)
with st.sidebar:
    st.markdown("### 🧭 Causal RCA — Confounder Robustness")
    sigma_max = causal_refute["sigma_max"]  # D-2 사전계산 from assets/causal_refute_v2.json
    if sigma_max < 0.5:
        st.success(f"✅ robust (σ_max = {sigma_max:.2f})")
    elif sigma_max < 1.0:
        st.warning(f"⚠️ moderate (σ_max = {sigma_max:.2f})")
    else:
        st.error(f"❌ fragile (σ_max = {sigma_max:.2f})")
    st.caption(f"DoWhy refute: {causal_refute['narrative_kr']}")
    with st.expander("🔍 자세히 (native output)"):
        st.code(causal_refute["raw_print"], language="text")
```

**Citation (정정, C6)**:
- `evals/run_eval.py:18-21,74-96` (eval base — DoWhy refute 결과 검증 case 추가 예정)
- `evals/judge_prompt.py:13-15,41-88` (Opus 4 judge — narrative_kr 평가 기준)

## 3. 4 Agent Pydantic Schema (신규, A1)

각 Agent 의 output contract. Schema freeze: **D-3 (5/19) 끝**. 본 ADR 통과 후 즉시 `src/orchestration/schema.py` 로 commit.

```python
from pydantic import BaseModel, Field
from typing import Literal

class QualityAgentOutput(BaseModel):
    numeric: dict = Field(..., description="defect_prob: float in [0,1], top_failure_type: Literal[NONE,TWF,HDF,PWF,OSF,RNF]")
    narrative_kr: str = Field(..., max_length=300)
    # 예: {"defect_prob": 0.83, "top_failure_type": "HDF"}, "ROBOT-00018 의 향후 24h 결함 확률 83%, 1순위 HDF (방열 결함)"

class SafetyAgentOutput(BaseModel):
    numeric: dict = Field(..., description="sop_violation: bool, estop_required: bool, safety_violation_prob: float in [0,1]")
    narrative_kr: str = Field(..., max_length=300)
    # 예: {"sop_violation": True, "estop_required": False, "safety_violation_prob": 0.62}, "max_motor_temp 105°C 가 SOP 100°C 초과, E-Stop 불필요하나 즉시 점검 권고"

class EquipmentAgentOutput(BaseModel):
    numeric: dict = Field(..., description="rul_hours: float >= 0, isolation_forest_score: float in [-1, 1]")
    narrative_kr: str = Field(..., max_length=300)
    # 예: {"rul_hours": 18.5, "isolation_forest_score": -0.34}, "잔여 수명 18.5h, isolation forest score -0.34 (이상치)"

class ProductionAgentOutput(BaseModel):
    numeric: dict = Field(..., description="throughput_uph: float >= 0, schedule_feasible: bool, lp_solution_id: str")
    narrative_kr: str = Field(..., max_length=300)
    # 예: {"throughput_uph": 247.0, "schedule_feasible": True, "lp_solution_id": "lp_2026-05-22_03:00"}, "현재 스케줄에서 247 uph 유지 가능"

class CandidateAction(BaseModel):
    action_id: str  # 예: "halt_robot_00018", "continue_no_action", "schedule_maintenance_3h"
    quality: QualityAgentOutput
    safety: SafetyAgentOutput
    equipment: EquipmentAgentOutput
    production: ProductionAgentOutput

class SupervisorInput(BaseModel):
    horizon_h: int = Field(..., ge=1, le=72)
    candidate_actions: list[CandidateAction] = Field(..., min_length=2, max_length=5)

class SupervisorOutput(BaseModel):
    decision: dict = Field(..., description="action_id: str, net_value_KRW: float, alternatives: list[dict], rationale_kr: str <=300, tradeoff_breakdown: dict")
    # tradeoff_breakdown 예: {"throughput_gain_KRW": 1_200_000, "defect_loss_KRW": -300_000, "safety_loss_KRW": -100_000_000, "rul_loss_KRW": -50_000}
```

**검증 task (D-3)**: `tests/test_agent_schema.py` 에 valid/invalid 케이스 각 ≥3개 (Section 6 Unit 참조).

## 4. Cache Architecture Diagram (신규, C1)

```
┌──────────────────────────────────────────────────────────────────────┐
│                  PRISM Demo Mode (PRISM_MODE=demo)                  │
├──────────────────────────────────────────────────────────────────────┤
│  User Action / Marker Tick (00:30, 01:30, 03:00, 04:00)             │
│         │                                                             │
│         ▼                                                             │
│  ┌────────────────────────────────────┐                              │
│  │ llm_cache.py (app-level)           │                              │
│  │  Key = SHA256(                     │  ◄── 시연 모드에서 항상       │
│  │    model_id +                      │      라이브 호출 전 lookup    │
│  │    system_prompt_normalized +      │                              │
│  │    user_prompt_normalized +        │                              │
│  │    tool_state_normalized           │                              │
│  │    (round 4, mock_ts=2026-05-22))  │                              │
│  │  Persisted: assets/cache_replay.jsonl                              │
│  │  Output: byte-equal guaranteed                                     │
│  └────────────┬───────────────────────┘                              │
│               │ miss (rehearsal 단계에서만 발생, 본선 0 miss)         │
│               ▼                                                       │
│  ┌────────────────────────────────────┐                              │
│  │ Bedrock Converse API               │                              │
│  │   ├─ system = [                    │                              │
│  │   │    {text: SYSTEM_PROMPT},     │  ◄── token-prefix cache       │
│  │   │    {cachePoint: ephemeral}    │      (비용 절감 only)         │
│  │   │  ]                             │                              │
│  │   ├─ inferenceConfig:              │                              │
│  │   │    temperature=0               │      응답 token 매번 새로     │
│  │   │    maxTokens=512               │      → 비결정성 source        │
│  │   │    topP=1                      │                              │
│  │   └─ toolConfig: 4 Agent tools     │                              │
│  └────────────┬───────────────────────┘                              │
│               │ elapsed > 10s OR HTTP error (C3 auto-trigger)         │
│               ▼                                                       │
│  ┌────────────────────────────────────┐                              │
│  │ Auto-cascade Fallback (C3)         │                              │
│  │  prism_demo_master.mp4 (4분 녹화)  │                              │
│  │  Label: "Live Snapshot             │                              │
│  │          (Bedrock unavailable)"   │                              │
│  │  Streamlit:                        │                              │
│  │    st.empty_placeholder            │                              │
│  │      .swap_to_video(...)           │                              │
│  └────────────────────────────────────┘                              │
└──────────────────────────────────────────────────────────────────────┘

상호 비간섭 보장:
- cachePoint = input cache only. 응답 token 매번 새로 생성 (Bedrock 내부 비결정성 sample).
- llm_cache.py = output cache only. cachePoint hit 여부와 무관, demo 모드에서 라이브 호출 차단.
- 두 레이어 독립 → cachePoint TTL (5분) 만료해도 llm_cache.py 가 byte-equal 보장.

Key normalization (llm_cache.py):
- system_prompt: 줄바꿈 \n 정규화, trailing whitespace strip
- user_prompt: <gold_data> 내부 timestamp 를 mock_ts (2026-05-22T03:00:00Z) 로 치환
- tool_state: 4 round 누적된 toolResult 의 JSON sort_keys=True dump
```

## 5. Pre-mortem (5 시나리오, v2)

### 시나리오 A: LLM cache miss @ 3:00 Supervisor (v1 유지)
- **트리거**: 본선 당일 cache key 가 리허설과 미세하게 다름 (예: timestamp 정규화 누락, system prompt 1 character drift).
- **실패 모습**: Supervisor 협상 응답이 라이브 호출 → temperature=0 이지만 inference 비결정성으로 alternatives 순서 변화 → 평가자 인지 "재현 불가".
- **Mitigation**: D-1 verification gate (C4) 의 cache_hit_rate ≥ 0.99 검증 + auto-cascade (C3) 가 10s 초과 시 영상 자동 cut. llm_cache.py 의 key normalization 단위 테스트 (Section 6 Unit) 가 미세 drift 방지.

### 시나리오 B: Generator 시드 깨짐 (v1 유지 + A5 통합)
- **트리거**: `src/generator/_record.py:18-19,25` 의 모듈 전역 `random.uniform`, `random.gauss` 호출이 `_fault_state.py:7,36,60,65-113` 의 `rng=random.Random(2026)` 인스턴스 격리 패턴과 충돌 → 동일 시드에서도 micro-tick 마다 다른 값.
- **실패 모습**: 본선 시연의 robot 18/11 의 motor_temp 그래프가 리허설과 다른 곡선 → 사이드바 σ_max 도 다르게 산출 → ✅/⚠️/❌ 라벨 비결정.
- **Mitigation (A5)**: D-3 (5/19) 까지 모듈 전역 `random.*` 호출을 인스턴스 주입 형태로 refactor.
  - `src/generator/_record.py:18-19,25,70-84` (5 함수) → `rng` 파라미터 추가
  - `src/generator/backfill.py:100-118` (생성 루프) → `rng = random.Random(2026)` 외부 주입
  - `src/generator/app.py:55,143,176,190-211,269,291` (daemon) → 동일
  - 시연 모드 시작 시 1회: `np.random.default_rng(2026)` + `os.environ["PYTHONHASHSEED"]="2026"`.

### 시나리오 C: 시연 시간 초과 (v1 유지)
- **트리거**: 4 Agent fan-out 호출 (각 ≤ 2s) + Supervisor 통합 (≤ 3s) + 사이드바 rerender (≤ 1s) 가 마커마다 누적되어 4분 = 240s 초과.
- **실패 모습**: 발표자가 4:00 마커 못 닿고 평가자에게 미완성 시연 노출.
- **Mitigation**: D-1 verification gate metric (C4 metric 3): `e2e_runtime_seconds ≤ 225` (3:45 buffer). 초과 시 cache miss 1건 이상 → C4 exit 1 → 영상 fallback 강제.

### 시나리오 D (신규, C5): venue WiFi 단절
- **트리거**: 본선장 인터넷 끊김 또는 corporate firewall 이 Bedrock endpoint 차단.
- **실패 모습**: Bedrock 호출 0 → 모든 마커에서 cascade fallback 발동 → 평가자 인지 "이 시스템은 인터넷 의존" → 차별화 손상 + 학술적 검증 가능성 0.
- **Mitigation**:
  - **D-2 (5/20) 까지**: 본선 운영팀에 venue 네트워크 specs 문의 (outbound HTTPS 443 to `bedrock-runtime.eu-central-1.amazonaws.com`).
  - **본선 당일**: LTE 핫스팟 백업 (mason 본인 휴대폰 tethering).
  - **소프트 fallback**: llm_cache.py 의 `offline_mode=True` 환경변수 — 모든 응답이 cache hit 으로 강제 (라이브 호출 시도 0). cache miss 시 즉시 영상 fallback.
  - **narrative**: 평가자 질문 시 "Bedrock 호출은 D-1 에 사전 캐시되었습니다. 시연은 venue 네트워크 의존성 0 으로 설계되었습니다."

### 시나리오 E (신규, C5): DoWhy refute_estimate 의 random_seed 비결정
- **트리거**: `refute_estimate(method_name="placebo_treatment_refuter", num_simulations=100)` 의 bootstrap resampling 이 numpy global seed 에 의존. `np.random.seed(...)` 미명시 시 매 호출마다 σ_max 산출값이 다르게 나옴.
- **실패 모습**: 사이드바 σ_max 라벨이 시연마다 다르게 표시 (✅ 0.42 → ⚠️ 0.51 → ✅ 0.47 등) → 평가자가 "이 라벨은 진짜인가?" 의심 → 학술 신뢰성 손상 + D-1 SHA256 검증 실패.
- **Mitigation**:
  - **D-2 (5/20) 사전 계산**: `np.random.seed(2026)` refute 호출 직전 명시, `num_simulations=100` 고정. 4 method (placebo / random_common_cause / unobserved_common_cause / subset) 결과를 `assets/causal_refute_v2.json` 으로 저장. 본선에는 라이브 refute 호출 X (사전 계산값만 read).
  - **검증 (D-3)**: `tests/test_dowhy_labels.py` 에 σ_max → ✅/⚠️/❌ 매핑 + 동일 seed 에서 100회 호출 결과 byte-equal 단위 테스트.

## 6. Expanded Test Plan (4-tier, v2)

### Unit (v1 4 + v2 2 = 6)
- v1 의 4 test files:
  - `tests/test_supervisor_math.py` — net_value_KRW 수식 단위.
  - `tests/test_llm_cache_key.py` — SHA256 key normalization (mock_ts 치환, sort_keys).
  - `tests/test_generator_rng.py` — seed=2026 → motor_temp 시계열 byte-equal.
  - `tests/test_streamlit_card_label.py` — σ_max → ✅/⚠️/❌ 매핑.
- **v2 추가 (A1, C2)**:
  - `tests/test_agent_schema.py` — Pydantic 4 모델 valid 케이스 ≥3 + invalid (numeric 범위 위배, narrative_kr length 초과) ≥3.
  - `tests/test_dowhy_labels.py` — σ_max 0.42 → ✅, 0.51 → ⚠️, 1.20 → ❌ 매핑 + 동일 seed 에서 `refute_estimate` 100회 호출 결과 byte-equal.

### Integration (v1 3 + v2 1 = 4)
- v1 의 3 test files:
  - `tests/integration/test_4agent_fanout.py` — 4 Agent 병렬 호출 (mock Bedrock) → SupervisorInput 조립 ≤ 2s.
  - `tests/integration/test_supervisor_round.py` — Supervisor 4 round 협상 (mock LLM) → SupervisorOutput.
  - `tests/integration/test_streamlit_marker_ticks.py` — 00:30/01:30/03:00/04:00 마커 trigger → 각 카드 노출.
- **v2 추가 (A4)**:
  - `tests/integration/test_prism_qa_eval.py` — `evals/prism_qa.yaml` (신규 10-15 case, A4) Opus judge 점수 ≥ 0.90. `evals/run_eval.py:18-21,74-96` + `evals/judge_prompt.py:13-15,41-88` 패턴 확장.

### E2E (v1 3 + v2 1 = 4)
- v1 의 3 test files:
  - `tests/e2e/test_4min_demo_runtime.py` — Streamlit headless run, 00:30/01:30/03:00/04:00 마커 hit + total ≤ 225s.
  - `tests/e2e/test_cache_replay_byte_equal.py` — 시연 2회 연속 실행 → 모든 응답 SHA256 일치.
  - `tests/e2e/test_dowhy_card_render.py` — Streamlit selenium 으로 사이드바 σ_max 라벨 + expander 토글 동작.
- **v2 추가 (C3)**:
  - `tests/e2e/test_auto_cascade.py` — `LLM_RESPONSE_TIMEOUT_MS=10000` mock (라이브 호출 11s 지연) → 자동 영상 cut + `<video src="prism_demo_master.mp4">` element DOM 노출 + 라벨 "Live Snapshot (Bedrock unavailable)" 검증.

### Observability (v1 5 metrics + C4 통합)
- v1 의 5 metrics jsonl:
  - `metrics/cache_hit_rate.jsonl` — llm_cache.py 의 hit/miss event.
  - `metrics/generator_sha256.jsonl` — 시연 모드 generator 출력 byte hash.
  - `metrics/e2e_runtime.jsonl` — 4분 시연 runtime + 마커 timing.
  - `metrics/eval_score.jsonl` — prism_qa.yaml 평가 결과.
  - `metrics/bedrock_token_usage.jsonl` — input/output/cache_read/cache_creation tokens (`src/common/bedrock.py:51-58` 기존 패턴 확장).
- **v2 통합 (C4)**: `scripts/verify_demo_determinism.py` 가 5 metrics 를 단일 명령 + exit code 0/1 로 묶음 (Section 7).

## 7. Verification Gate (신규, C4)

**D-1 (5/21) 의 binary gate**. 5 metric 전부 통과해야 본선 진입. 한 metric 이라도 실패 시 영상 fallback 강제.

```bash
$ python -m scripts.verify_demo_determinism --rehearse=2026-05-21

[verify_demo_determinism] rehearsal date: 2026-05-21
[1/5] cache_hit_rate: 0.997 (>=0.99) ✓
[2/5] generator_sha256: a3b4c5...d8 (byte-equal v1 baseline 2026-05-20) ✓
[3/5] e2e_runtime_seconds: 218.4 (<=225) ✓
[4/5] eval_score: 0.93 (>=0.90, prism_qa.yaml n=12) ✓
[5/5] bedrock_token_usage: 28_432 (<=30_000) ✓

ALL PASSED. Proceed to 본선.
[gate] PRISM_FALLBACK_VIDEO=0 (silent, A3 (i))

$ echo $?
0
```

**Metric 정의**:
1. `cache_hit_rate >= 0.99` — llm_cache.py 의 hit/total, 시연 1회 기준.
2. `generator_sha256` byte-equal — 시연 generator 출력 stream SHA256 = D-1 baseline.
3. `e2e_runtime_seconds <= 225` — Streamlit start ~ 4:00 마커 wall clock.
4. `eval_score >= 0.90` — `evals/prism_qa.yaml` Opus judge 평균.
5. `bedrock_token_usage <= 30_000` — 시연 + 리허설 누적.

## 8. ADR (Final)

- **Decision**: 3 결정 v1 본질 유지, 12 개선 통합. **Step 0**: `mkdir -p src/orchestration && touch src/orchestration/__init__.py` (C7).
- **Drivers**: 시간 4일 / 토큰 한도 30k / 평가자 인지 가능성.
- **Alternatives considered**: Section 1 표 참조. 모두 기각 또는 부분 흡수 (Synthesis 1/3).
- **Why chosen**: 5 Principles + 3 Drivers 의 교차점. Option A × 3 + 12 개선이 최대 marginal value.
- **Consequences**:
  - (+) 결정성 ≥ 99% (cache + auto-cascade), LLM/네트워크 장애 mitigated, 차별화 3요소 화면 고정, 학술 검증 가능, ADR 본문 통계 정의.
  - (−) Unit cost (KRW) 가정, 영상 fallback 라벨 노출, 사이드바 반응형 한계, RNG refactor 1h 추가, venue 환경 외부 의존.
- **Follow-ups (D-3 ~ 본선 + 사후, v2)**:

### D-3 (5/19 일) — **오늘 자기 전 + 새벽 reset 2회로 완료 목표**
- [ ] **C7** `mkdir -p src/orchestration && touch src/orchestration/__init__.py` (Step 0).
- [ ] **A1** `src/orchestration/schema.py` + `tests/test_agent_schema.py`.
- [ ] **A5** Generator RNG 격리 refactor (`_record.py:18-19,25,70-84`, `backfill.py:100-118`, `app.py:55,143,176,190-211,269,291`).
- [ ] **C2** `src/orchestration/causal_card.py` + σ_max 임계 매핑.
- [ ] **A4** `evals/prism_qa.yaml` 10-15 case 작성.

### D-2 (5/20 월)
- [ ] **A3, C1** `src/orchestration/llm_cache.py` production-ready + `assets/cache_replay.jsonl` 사전 빌드 (10-15 entry).
- [ ] **C5-E** DoWhy refute_estimate 사전 계산 → `assets/causal_refute_v2.json`.
- [ ] **C5-D** 본선 운영팀에 venue 네트워크 specs 문의 + LTE 핫스팟 준비.
- [ ] **A3 (i)** `prism_demo_master.mp4` 1차 녹화.

### D-1 (5/21 화)
- [ ] **C4** `python -m scripts.verify_demo_determinism --rehearse=2026-05-21` — 5 metric PASS 시 silent fallback disable, FAIL 시 강제.
- [ ] 리허설 ≥ 3회 + 마커 timing log 수집.

### D-day (5/22 금)
- [ ] LTE 핫스팟 활성 + `PRISM_MODE=demo` set + Streamlit headless run + 4분 시연.

### 본선 후 (5/23+)
- [ ] FastAPI + Jinja2 + Plotly.js fallback option 평가 (R4).
- [ ] Unit cost 도메인 표 확장 (KRW 외).
- [ ] DoWhy refute 결과 발표 부록.
- [ ] `evals/golden_qa.yaml` → `prism_qa.yaml` migration.

## 9. 잔여 Risk (Critic 명시 5건)

- **R1. Venue 환경 SLA 미확인** — D-2 까지 본선 운영팀 응답 의존. LTE 핫스팟 + offline 모드 hard fallback.
- **R2. `evals/golden_qa.yaml` PRISM 부적합** — A4 의 `prism_qa.yaml` 신규로 해결.
- **R3. Generator RNG 잔재** — A5 의 D-3 refactor 로 해결.
- **R4. Streamlit 미경험 risk** — D-3 첫 4h 안 sidebar/expander/marker 검증. 미달 시 FastAPI + Jinja2 + Plotly.js fallback.
- **R5. 자동 commit 정책 충돌** — ralplan iter 중 Planner v2 read-only. 메인이 본 ADR 저장 + commit 시 PRISM_briefing.md:45 citation 동시 정정.

## 10. 변경 이력 (Changelog)

- **v1 (2026-05-18 오전)** → 3 Decision (Option A × 3) + RALPLAN-DR + pre-mortem 3 + test plan 4-tier.
- **Architect review (round 1)** — STRONG/YES + 5 개선 (A1~A5).
- **Critic review (round 1)** — ITERATE + 7 개선 (C1~C7).
- **v2 (2026-05-18 본 문서)** — Architect 5 + Critic 7 = **12 개선 전부 통합**. Section 3, 4, 5(D,E), 6, 7 신규/강화. Citation 정정 (C6).
- **Approval (2026-05-18, mason)** — D-3 실행 모드 진입. ralplan state deactivate.

---

**Status**: approved by user (2026-05-18). 본 ADR v2 = 9일 plan 의 single source of truth.

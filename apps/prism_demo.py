"""PRISM D-3 본선 4분 시연용 Streamlit app 골격.

ADR v2 Section 2 Decision 2/3 + Section 4 (cache architecture) 구현.
9 마커 timeline + 사이드바 카드 + 메인 영역 KPI + Plotly 인과 DAG + auto-cascade fallback.

실행:
    PRISM_MODE=demo streamlit run apps/prism_demo.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# src/ 패키지 접근 보장
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
import plotly.graph_objects as go
import networkx as nx

from src.orchestration.schema import (
    AlternativeAction,
    CandidateAction,
    EquipmentAgentOutput,
    EquipmentNumeric,
    ProductionAgentOutput,
    ProductionNumeric,
    QualityAgentOutput,
    QualityNumeric,
    SafetyAgentOutput,
    SafetyNumeric,
    SupervisorDecision,
    SupervisorOutput,
    TradeoffBreakdown,
    compute_net_value_KRW,
)
from src.orchestration.llm_cache import CacheReplayError, BedrockError

# PRISM_MODE 분기: dev (mock) | demo (cache replay) | live (Bedrock 실호출)
_PRISM_MODE = os.environ.get("PRISM_MODE", "dev").lower()

# ── 상수 ────────────────────────────────────────────────────────────────────────

# 9 마커 (초 단위, 라벨)
MARKERS: list[tuple[int, str]] = [
    (0,   "0:00 정상"),
    (15,  "0:15 예지경보 risk62%"),
    (30,  "0:30 인과v1"),
    (45,  "0:45 인간결정"),
    (60,  "1:00 시뮬가속"),
    (75,  "1:15 불량 #47"),
    (90,  "1:30 인과v2"),
    (135, "2:15 4 Agent"),
    (180, "3:00 Supervisor"),
    (210, "3:30 재학습 0.62→0.91"),
    (225, "3:45 OEE +35%"),
]
TOTAL_SECONDS = 225  # 3:45

# PRISM 차별화 KPI
COST_PRISM_KRW_PER_MONTH = "₩10–20"
COST_MES_KRW_PER_YEAR = "₩10,000+"

# 인과 DAG 노드·엣지 (사전 계산, DoWhy 호출 없음)
DAG_NODES = [
    "tool_age", "spindle_rpm", "coolant_temp",
    "vibration_xyz", "thermal_drift", "dimension_dev", "DEFECT",
]
DAG_EDGES = [
    ("tool_age",     "vibration_xyz"),
    ("tool_age",     "thermal_drift"),
    ("spindle_rpm",  "vibration_xyz"),
    ("spindle_rpm",  "coolant_temp"),
    ("coolant_temp", "thermal_drift"),
    ("vibration_xyz","dimension_dev"),
    ("thermal_drift","dimension_dev"),
    ("dimension_dev","DEFECT"),
]
# spindle_rpm intervention 표시용
INTERVENTION_NODE = "spindle_rpm"


# ── mock 데이터 helper ───────────────────────────────────────────────────────────

def _mock_candidate(action_id: str, defect_prob: float, safety_prob: float,
                    rul: float, uph: float) -> CandidateAction:
    return CandidateAction(
        action_id=action_id,
        quality=QualityAgentOutput(
            numeric=QualityNumeric(defect_prob=defect_prob, top_failure_type="HDF"),
            narrative_kr=f"결함 확률 {defect_prob:.0%}, 1순위 HDF (Heat Dissipation Failure)",
        ),
        safety=SafetyAgentOutput(
            numeric=SafetyNumeric(
                sop_violation=(safety_prob > 0.3),
                estop_required=(safety_prob > 0.7),
                safety_violation_prob=safety_prob,
            ),
            narrative_kr=f"안전 위반 확률 {safety_prob:.0%}",
        ),
        equipment=EquipmentAgentOutput(
            numeric=EquipmentNumeric(rul_hours=rul, isolation_forest_score=-0.34),
            narrative_kr=f"잔여 수명 {rul:.1f}h, isolation forest -0.34",
        ),
        production=ProductionAgentOutput(
            numeric=ProductionNumeric(
                throughput_uph=uph,
                schedule_feasible=(uph >= 200),
                lp_solution_id="lp_demo_v1",
            ),
            narrative_kr=f"처리량 {uph:.0f} uph, 스케줄 {'가능' if uph >= 200 else '불가'}",
        ),
    )


def _mock_supervisor_decision() -> SupervisorOutput:
    """D-2 까지 실 호출 미작동 — demo skeleton 용 mock.

    실 호출은 도메인 prompt fill (D-3 새벽 사용자 작업) 후.
    """
    action_a = _mock_candidate("spindle_reduce_10pct", 0.18, 0.05, 42.0, 247.0)
    action_b = _mock_candidate("coolant_flush",         0.62, 0.22, 18.5, 195.0)

    net_a, breakdown_a = compute_net_value_KRW(
        quality=action_a.quality,
        safety=action_a.safety,
        equipment=action_a.equipment,
        production=action_a.production,
        horizon_h=4,
    )
    net_b, _ = compute_net_value_KRW(
        quality=action_b.quality,
        safety=action_b.safety,
        equipment=action_b.equipment,
        production=action_b.production,
        horizon_h=4,
    )

    decision = SupervisorDecision(
        action_id="spindle_reduce_10pct",
        net_value_KRW=net_a,
        alternatives=[
            AlternativeAction(action_id="coolant_flush", net_value_KRW=net_b, rank=2),
        ],
        rationale_kr="spindle_reduce_10pct 가 coolant_flush 대비 net +540만원 우위. "
                     "결함 확률 62%→18% 개선, 안전 위반 무시가능 수준.",
        tradeoff_breakdown=breakdown_a,
    )
    return SupervisorOutput(decision=decision)


def _mock_4agent_action() -> CandidateAction:
    """4 Agent 출력 mock — 마커 2:15 (idx 7) 이후 표시."""
    return _mock_candidate("spindle_reduce_10pct", 0.18, 0.05, 42.0, 247.0)


# ── 9 마커 시나리오 (Closed-Loop 통합, PRISM_MODE=demo/live) ──────────────────────

_MARKER_TO_SCENARIO: dict[int, str] = {
    0: "normal",   # 0:00 정상
    1: "normal",   # 0:15 예지경보
    2: "normal",   # 0:30 인과 v1
    3: "normal",   # 0:45 인간 결정
    4: "normal",   # 1:00 시뮬 가속
    5: "fault",    # 1:15 불량 #47 발생
    6: "fault",    # 1:30 인과 v2
    7: "fault",    # 2:15 4 Agent 협상
    8: "fault",    # 3:00 Supervisor 결정
    9: "recover",  # 3:30 재학습 0.62→0.91
    10: "recover", # 3:45 OEE +35%
}

_SCENARIOS: dict[str, dict] = {
    "normal": {
        "robot_id": "ROBOT-00018",
        "phase": "normal",
        "motor_temp_c": 85.0,
        "vibration_xyz": 0.8,
        "tool_age_h": 120.0,
        "spindle_rpm": 8500,
        "coolant_temp_c": 22.0,
        "thermal_drift_um": 5.0,
        "dimension_dev_um": 2.0,
        "defect_signal": 0.05,
    },
    "fault": {
        "robot_id": "ROBOT-00018",
        "phase": "fault",
        "motor_temp_c": 105.0,
        "vibration_xyz": 2.3,
        "tool_age_h": 180.0,
        "spindle_rpm": 8500,
        "coolant_temp_c": 28.0,
        "thermal_drift_um": 18.0,
        "dimension_dev_um": 12.0,
        "defect_signal": 0.60,
    },
    "recover": {
        "robot_id": "ROBOT-00018",
        "phase": "recover",
        "motor_temp_c": 92.0,
        "vibration_xyz": 1.1,
        "tool_age_h": 185.0,
        "spindle_rpm": 7650,
        "coolant_temp_c": 24.0,
        "thermal_drift_um": 8.0,
        "dimension_dev_um": 4.0,
        "defect_signal": 0.18,
    },
}

# Supervisor candidate_actions (4 옵션, 시연 fixed)
_CANDIDATE_ACTIONS: list[str] = [
    "continue",              # 진행 (위험 감수)
    "throttle_50pct",        # 부하 50% 감속
    "schedule_maintenance",  # 정비 스케줄
    "halt",                  # 즉시 정지
]


def _real_supervisor_decision(
    marker_idx: int,
    alpha: float,
    beta: float,
    gamma: float,
    horizon_h: int = 4,
) -> tuple[SupervisorOutput, list[CandidateAction]]:
    """Supervisor.negotiate_with_candidates 실호출 (PRISM_MODE=demo/live).

    PRISM_MODE=demo 시 LLMCache replay 의존 — miss → CacheReplayError → fallback_video().
    """
    from src.orchestration.supervisor import Supervisor, SupervisorConfig

    scenario_id = _MARKER_TO_SCENARIO.get(marker_idx, "fault")
    scenario_context = _SCENARIOS[scenario_id]
    sup = Supervisor(config=SupervisorConfig(
        alpha=alpha, beta=beta, gamma=gamma, horizon_h=horizon_h,
    ))
    return sup.negotiate_with_candidates(scenario_context, _CANDIDATE_ACTIONS)


# ── UI 컴포넌트 ──────────────────────────────────────────────────────────────────

def render_header() -> None:
    """상단 KPI 카드 4개 (OEE / RCA / Defect / 비용 비교)."""
    st.markdown("## PRISM — Predictive Real-time Intelligence for Smart Manufacturing")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="OEE 개선", value="+35%", delta="목표 달성")
    with col2:
        st.metric(label="RCA 소요시간 단축", value="-90%", delta="4h → 24min")
    with col3:
        st.metric(label="불량률 감소", value="-50%", delta="Defect")
    with col4:
        st.metric(
            label="운영 비용 / 월",
            value=COST_PRISM_KRW_PER_MONTH,
            delta=f"vs MES {COST_MES_KRW_PER_YEAR}/년",
            delta_color="inverse",
        )


def render_marker_timeline(current_marker_idx: int) -> None:
    """Plotly horizontal stepper — 9 마커 chip, 현재 활성 chip highlight.

    Args:
        current_marker_idx: 0-based index into MARKERS list.
    """
    current_marker_idx = max(0, min(current_marker_idx, len(MARKERS) - 1))
    current_sec = MARKERS[current_marker_idx][0]
    progress_pct = current_sec / TOTAL_SECONDS

    # Progress bar
    st.progress(progress_pct, text=f"{MARKERS[current_marker_idx][1]}  ({progress_pct:.0%})")

    # Chip row via Plotly
    labels = [label for _, label in MARKERS]
    x_pos = [i for i in range(len(MARKERS))]
    colors = [
        "#1f77b4" if i == current_marker_idx else
        "#aec7e8" if i < current_marker_idx else
        "#d3d3d3"
        for i in range(len(MARKERS))
    ]
    font_colors = [
        "white" if i <= current_marker_idx else "#555"
        for i in range(len(MARKERS))
    ]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_pos,
        y=[0] * len(MARKERS),
        mode="markers+text",
        marker=dict(size=18, color=colors, line=dict(width=1, color="#999")),
        text=[str(i) for i in range(len(MARKERS))],
        textposition="middle center",
        textfont=dict(color=font_colors, size=10),
        hovertext=labels,
        hoverinfo="text",
    ))
    # Connecting line
    fig.add_shape(
        type="line",
        x0=0, x1=len(MARKERS) - 1,
        y0=0, y1=0,
        line=dict(color="#aec7e8", width=2),
        layer="below",
    )
    # Labels below chips
    for i, (_, label) in enumerate(MARKERS):
        short = label.split(" ", 1)[1] if " " in label else label
        fig.add_annotation(
            x=i, y=-0.25,
            text=short[:10],
            showarrow=False,
            font=dict(size=8, color="#555"),
            textangle=-30,
        )

    fig.update_layout(
        height=110,
        margin=dict(l=10, r=10, t=5, b=40),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, range=[-0.5, 0.4]),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_causal_dag() -> None:
    """Plotly + networkx 6-node 인과 DAG.

    spindle_rpm intervention 노드 강조 표시.
    DoWhy 호출 없음 — 사전 계산 데이터만.
    """
    G = nx.DiGraph()
    G.add_nodes_from(DAG_NODES)
    G.add_edges_from(DAG_EDGES)

    # 계층 레이아웃 (좌→우)
    pos = nx.planar_layout(G)

    # 엣지 trace
    edge_x, edge_y = [], []
    for src, dst in G.edges():
        x0, y0 = pos[src]
        x1, y1 = pos[dst]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        mode="lines",
        line=dict(width=1.5, color="#888"),
        hoverinfo="none",
    )

    # 노드 색상
    node_colors = []
    for n in G.nodes():
        if n == "DEFECT":
            node_colors.append("#d62728")   # 결과 노드 — 빨강
        elif n == INTERVENTION_NODE:
            node_colors.append("#ff7f0e")   # intervention — 주황
        else:
            node_colors.append("#1f77b4")   # 원인 노드 — 파랑

    node_x = [pos[n][0] for n in G.nodes()]
    node_y = [pos[n][1] for n in G.nodes()]

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        marker=dict(size=22, color=node_colors, line=dict(width=1.5, color="white")),
        text=list(G.nodes()),
        textposition="top center",
        textfont=dict(size=10),
        hoverinfo="text",
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        title=dict(
            text="인과 DAG  |  <span style='color:#ff7f0e'>주황 = spindle_rpm 개입 포인트</span>",
            font=dict(size=13),
        ),
        height=340,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _quality_badge(q: QualityAgentOutput) -> str:
    p = q.numeric.defect_prob
    ft = q.numeric.top_failure_type
    if p >= 0.5: return f"❌ **위험** — {ft} 발생 우려"
    if p >= 0.2: return f"⚠️ **주의** — {ft} 모니터"
    return f"✅ **정상** — {ft}"


def _safety_badge(s: SafetyAgentOutput) -> str:
    n = s.numeric
    if n.estop_required: return "🛑 **즉시 정지** — E-stop 발동"
    if n.sop_violation: return "⚠️ **SOP 위반** — 감속/정지 필요"
    return "✅ **안전** — SOP 범위"


def _equipment_badge(e: EquipmentAgentOutput, horizon_h: int = 4) -> str:
    rul = e.numeric.rul_hours
    if rul < 24: return f"🛠️ **정비 시급** — RUL {rul:.0f}h"
    if rul < 48: return f"⚠️ **곧 정비** — RUL {rul:.0f}h"
    return f"✅ **가동 가능** — RUL {rul:.0f}h"


def _production_badge(p: ProductionAgentOutput) -> str:
    n = p.numeric
    if not n.schedule_feasible: return f"⚠️ **재계획** — UPH {n.throughput_uph:.0f}"
    return f"✅ **진행 권장** — UPH {n.throughput_uph:.0f}"


def render_4agent_outputs(action: CandidateAction) -> None:
    """4 Domain Agent 협상 — 4 컬럼 bordered container.

    페르소나 (🎯/🛡️/⚙️/📈) + 추천 badge + 💬 인용 톤 narrative 로 "보고서" 느낌 X,
    "각자 주장 펼치는" 협상 narrative 강화.
    """
    st.markdown("#### 4 Domain Agent 협상")
    st.caption("각 Agent 가 자신의 도메인 시점에서 candidate action 을 평가 → Supervisor 가 Net Value 로 종합")
    c_q, c_s, c_e, c_p = st.columns(4)

    with c_q:
        with st.container(border=True):
            st.markdown("##### 🎯 품질 Agent")
            st.markdown(_quality_badge(action.quality))
            st.metric("결함 확률", f"{action.quality.numeric.defect_prob:.0%}")
            st.metric("Failure Type", action.quality.numeric.top_failure_type)
            st.caption(f"💬 *“{action.quality.narrative_kr}”*")

    with c_s:
        with st.container(border=True):
            st.markdown("##### 🛡️ 안전 Agent")
            st.markdown(_safety_badge(action.safety))
            st.metric("안전 위반 확률", f"{action.safety.numeric.safety_violation_prob:.0%}")
            st.metric("E-Stop 필요", "YES" if action.safety.numeric.estop_required else "NO")
            st.caption(f"💬 *“{action.safety.narrative_kr}”*")

    with c_e:
        with st.container(border=True):
            st.markdown("##### ⚙️ 설비 Agent")
            st.markdown(_equipment_badge(action.equipment))
            st.metric("잔여 수명(h)", f"{action.equipment.numeric.rul_hours:.1f}")
            st.metric("IsoForest 점수", f"{action.equipment.numeric.isolation_forest_score:.2f}")
            st.caption(f"💬 *“{action.equipment.narrative_kr}”*")

    with c_p:
        with st.container(border=True):
            st.markdown("##### 📈 생산 Agent")
            st.markdown(_production_badge(action.production))
            st.metric("처리량(uph)", f"{action.production.numeric.throughput_uph:.0f}")
            st.metric("스케줄 가능", "YES" if action.production.numeric.schedule_feasible else "NO")
            st.caption(f"💬 *“{action.production.narrative_kr}”*")


def render_supervisor_card(decision: SupervisorOutput) -> None:
    """Supervisor 결정 카드 — net_value + tradeoff_breakdown + alternatives."""
    dec = decision.decision
    st.markdown("#### Supervisor 최종 결정")

    col_main, col_alt = st.columns([3, 2])
    with col_main:
        st.metric("선택 액션", dec.action_id)
        st.metric("Net Value (KRW)", f"₩{dec.net_value_KRW:,.0f}")
        st.caption(dec.rationale_kr)

        bd = dec.tradeoff_breakdown
        st.dataframe(
            {
                "항목": ["처리량 이익", "결함 손실", "안전 손실", "RUL 손실"],
                "금액(KRW)": [
                    f"₩{bd.throughput_gain_KRW:,.0f}",
                    f"₩{bd.defect_loss_KRW:,.0f}",
                    f"₩{bd.safety_loss_KRW:,.0f}",
                    f"₩{bd.rul_loss_KRW:,.0f}",
                ],
            },
            hide_index=True,
            use_container_width=True,
        )

    with col_alt:
        st.markdown("**대안 액션**")
        for alt in dec.alternatives:
            st.metric(
                label=f"#{alt.rank} {alt.action_id}",
                value=f"₩{alt.net_value_KRW:,.0f}",
            )


def render_sidebar(alpha: float, beta: float, gamma: float) -> tuple[float, float, float]:
    """사이드바 — Causal Robustness 카드 + α/β/γ 슬라이더.

    Returns:
        (alpha, beta, gamma) — 사용자 슬라이더 값.
    """
    with st.sidebar:
        st.markdown("## PRISM 제어판")

        # Causal Robustness 카드 (사전 계산 파일 있으면 표시)
        refute_path = _ROOT / "assets" / "causal_refute_v2.json"
        if refute_path.exists():
            from src.orchestration.causal_card import load_refute_data, render_card
            try:
                refute = load_refute_data(refute_path)
                render_card(refute)
            except Exception as exc:
                st.warning(f"causal_refute_v2.json 로드 실패: {exc}")
        else:
            st.info("causal_refute_v2.json 없음 — D-2 작업 후 표시 예정")

        st.markdown("---")
        st.markdown("### Supervisor 가중치")

        alpha_val = st.slider("α — 결함 손실 가중치", 0.0, 3.0, alpha, 0.1,
                              help="defect_loss × α")
        beta_val  = st.slider("β — 안전 손실 가중치", 0.0, 5.0, beta,  0.1,
                              help="safety_loss × β  (Synthesis 1: cost_safety_violation)")
        gamma_val = st.slider("γ — RUL 손실 가중치",  0.0, 3.0, gamma, 0.1,
                              help="rul_loss × γ")

        st.markdown("---")
        st.markdown("### 비용 비교")
        st.markdown(f"| 항목 | 비용 |")
        st.markdown(f"|------|------|")
        st.markdown(f"| PRISM / 월 | **{COST_PRISM_KRW_PER_MONTH}** |")
        st.markdown(f"| MES / 년 | ~~{COST_MES_KRW_PER_YEAR}~~ |")
        st.caption("비용 -98%: 노트북 1대 in-process DuckDB + Bedrock on-demand")

    return alpha_val, beta_val, gamma_val


def fallback_video() -> None:
    """CacheReplayError / TimeoutError / BedrockError 시 영상 fallback.

    presentation/prism_demo_master.mp4 없으면 placeholder 경고.
    """
    video_path = _ROOT / "presentation" / "prism_demo_master.mp4"
    if video_path.exists():
        st.video(str(video_path))
    else:
        st.warning("Recording pending D-1  (presentation/prism_demo_master.mp4)")
        st.info("라이브 demo 중 오류 발생 — 영상 fallback 대기 중. 잠시 후 재시도 하세요.")


# ── 메인 ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        layout="wide",
        page_title="PRISM Demo",
        page_icon="🏭",
    )

    render_header()
    st.markdown("---")

    # 마커 인덱스 세션 상태
    if "marker_idx" not in st.session_state:
        st.session_state["marker_idx"] = 0
    marker_idx: int = int(st.session_state["marker_idx"])

    render_marker_timeline(marker_idx)

    # α/β/γ 슬라이더 초기값
    alpha_init = float(st.session_state.get("alpha", 1.0))
    beta_init  = float(st.session_state.get("beta",  1.0))
    gamma_init = float(st.session_state.get("gamma", 1.0))

    alpha, beta, gamma = render_sidebar(alpha_init, beta_init, gamma_init)
    st.session_state["alpha"] = alpha
    st.session_state["beta"]  = beta
    st.session_state["gamma"] = gamma

    col_left, col_right = st.columns([2, 1])

    with col_left:
        # 마커 0~6: DAG 가 main view (인과 추론 단계)
        # 마커 7~: 4 Agent 협상이 main view (스크롤 불필요), DAG 는 숨김
        if marker_idx < 7:
            render_causal_dag()

        # 마커 2:15 (idx 7) 이후 — 4 Agent + Supervisor 표시
        # 마커 7: 4 Agent 협상이 main view
        # 마커 8+: Supervisor 결정이 main view (상단), 4 Agent 는 근거 reference (하단)
        if marker_idx >= 7:
            try:
                if _PRISM_MODE in ("demo", "live"):
                    # 실호출 — Supervisor 가 4 Agent fan-out + net_value 산정
                    sup_out, candidates_ordered = _real_supervisor_decision(
                        marker_idx, alpha, beta, gamma, horizon_h=4,
                    )
                    if marker_idx >= 8:
                        render_supervisor_card(sup_out)
                        st.markdown("---")
                        st.markdown("##### 🤖 위 결정의 근거: 4 Domain Agent 협상")
                        render_4agent_outputs(candidates_ordered[0])
                    else:
                        # 마커 7: 4 Agent 만 (Supervisor 결정 전)
                        render_4agent_outputs(candidates_ordered[0])
                else:
                    # dev mode — mock fallback
                    action = _mock_4agent_action()
                    if marker_idx >= 8:
                        sup_out = _mock_supervisor_decision()
                        net, breakdown = compute_net_value_KRW(
                            quality=action.quality,
                            safety=action.safety,
                            equipment=action.equipment,
                            production=action.production,
                            alpha=alpha, beta=beta, gamma=gamma, horizon_h=4,
                        )
                        updated_decision = SupervisorDecision(
                            action_id=sup_out.decision.action_id,
                            net_value_KRW=net,
                            alternatives=sup_out.decision.alternatives,
                            rationale_kr=sup_out.decision.rationale_kr,
                            tradeoff_breakdown=breakdown,
                        )
                        render_supervisor_card(SupervisorOutput(decision=updated_decision))
                        st.markdown("---")
                        st.markdown("##### 🤖 위 결정의 근거: 4 Domain Agent 협상")
                        render_4agent_outputs(action)
                    else:
                        render_4agent_outputs(action)

            except CacheReplayError:
                st.error("Cache miss — 영상 fallback 전환")
                fallback_video()
            except TimeoutError:
                st.error("LLM 응답 timeout — 영상 fallback 전환")
                fallback_video()
            except BedrockError:
                st.error("Bedrock 호출 오류 — 영상 fallback 전환")
                fallback_video()

        else:
            st.info(f"마커 7 (2:15 4 Agent) 이후 분석 결과 표시 — 현재: 마커 {marker_idx}")

    with col_right:
        st.markdown("#### 마커 컨트롤")
        st.caption(f"현재: **{MARKERS[marker_idx][1]}**  ({marker_idx + 1}/{len(MARKERS)})")

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("◀ Prev", disabled=(marker_idx == 0)):
                st.session_state["marker_idx"] = max(0, marker_idx - 1)
                st.rerun()
        with btn_col2:
            if st.button("Next ▶", disabled=(marker_idx == len(MARKERS) - 1)):
                st.session_state["marker_idx"] = min(len(MARKERS) - 1, marker_idx + 1)
                st.rerun()

        if st.button("처음으로"):
            st.session_state["marker_idx"] = 0
            st.rerun()

        st.markdown("---")
        st.markdown("#### 현재 마커 KPI")
        sec, label = MARKERS[marker_idx]
        mm = sec // 60
        ss = sec % 60
        st.metric("타임코드", f"{mm}:{ss:02d}")
        st.metric("단계", label.split(" ", 1)[1] if " " in label else label)

        # 재학습 결과 (마커 3:30 이후)
        if marker_idx >= 9:
            st.success("재학습 완료: 0.62 → 0.91 (+47%)")
        # OEE 결과 (마커 3:45)
        if marker_idx >= 10:
            st.success("OEE +35% 달성")

    st.markdown("---")
    st.caption(
        "PRISM v0.1-demo  |  PRISM_MODE=" + __import__("os").environ.get("PRISM_MODE", "dev")
        + "  |  본선 5/22 시연용"
    )


if __name__ == "__main__":
    main()

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

# 각 마커별 한국어 1줄 설명 (mason 피드백: 단계 metric 아래 caption)
_MARKER_DESCRIPTIONS: dict[int, str] = {
    0:  "센서 데이터 정상 흐름, 모든 라인 가동 중",
    1:  "이상 신호 감지 — 결함 risk 62% 예지경보 발동",
    2:  "DoWhy 6-Node DAG 인과 추론 v1 생성",
    3:  "운영자가 시뮬레이션 가속 요청",
    4:  "fast-forward 시뮬 결과 표시",
    5:  "결함 #47 실제 발생, motor_temp 105°C 도달",
    6:  "DAG v2 갱신 — spindle_rpm 개입 효과 추가",
    7:  "4 Domain Agent 가 동시 분석 (품질·안전·설비·생산)",
    8:  "Supervisor 가 Net Value 산정 — 최적 액션 권고",
    9:  "강화학습 모델 재학습 완료, 정확도 0.62 → 0.91 (+47%)",
    10: "OEE +35% 달성, 시연 완료",
}

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
    """dev mode skeleton — caller (main) 가 α/β/γ slider 로 net_value 재계산.

    H2 fix: net_a 변수만 제거 (dead — caller 재계산). breakdown_a 는 smoke test
    (test_mock_supervisor_decision_tradeoff_breakdown_signs) 가 검증해서 유지.
    """
    action_a = _mock_candidate("spindle_reduce_10pct", 0.18, 0.05, 42.0, 247.0)
    action_b = _mock_candidate("coolant_flush", 0.62, 0.22, 18.5, 195.0)

    _, breakdown_a = compute_net_value_KRW(
        action_a.quality, action_a.safety, action_a.equipment, action_a.production,
        horizon_h=4,
    )
    net_b, _ = compute_net_value_KRW(
        action_b.quality, action_b.safety, action_b.equipment, action_b.production,
        horizon_h=4,
    )
    return SupervisorOutput(decision=SupervisorDecision(
        action_id="spindle_reduce_10pct",
        net_value_KRW=0.0,  # caller 재계산
        alternatives=[AlternativeAction(action_id="coolant_flush", net_value_KRW=net_b, rank=2)],
        rationale_kr="spindle_reduce_10pct 가 coolant_flush 대비 우위. "
                     "결함 확률 62%→18% 개선, 안전 위반 무시가능 수준.",
        tradeoff_breakdown=breakdown_a,
    ))


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
# 마커별 sub-metric — "현재 마커 KPI" 박스 아래 표시. 의미 있는 시점만.
_MARKER_SUB_KPIS: dict[int, list[tuple[str, str]]] = {
    1:  [("결함 risk", "62%"), ("1순위 type", "HDF")],
    2:  [("원인 후보", "6 노드"), ("σ_max", "0.40 ✅")],
    4:  [("시뮬 가속비", "240×"), ("defect Δ", "-44%p")],
    5:  [("motor_temp", "105°C"), ("vibration", "+188%")],
    6:  [("신규 edge", "+1"), ("DAG 버전", "v2")],
    8:  [("Net Value", "₩100M"), ("권고 강도", "강한")],
    9:  [("정확도", "0.91"), ("개선", "+47%")],
    10: [("OEE", "66%"), ("개선", "+35%")],
}


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


# ── DuckDB storage demo helper ───────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def _seed_storage_demo() -> dict:
    """incident #47 sensor timeline 100 행 DuckDB 적재 (1회). 사이드바 status 반환."""
    from datetime import datetime, timedelta

    from src.orchestration.storage import StorageDB  # noqa: PLC0415

    db_path = _ROOT / "data" / "prism_demo.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with StorageDB(str(db_path)) as db:
        if db.count("robot_telemetry") == 0:
            # seed 100 rows (60s timeline + 40s recovery)
            base_ts = datetime(2026, 5, 22, 3, 0, 0)
            rows = []
            for sec in range(100):
                ts = base_ts + timedelta(seconds=sec)
                mt = (
                    85 + 0.05 * sec
                    + (0.5 * (sec - 30) if 30 <= sec < 60 else (0 if sec < 30 else -0.3 * (sec - 60)))
                )
                rows.append({
                    "ts": ts,
                    "robot_id": "ROBOT-00018",
                    "motor_temp": mt,
                    "current_load": 60.0,
                    "battery_level": 75.0,
                    "pos_x": 10.5,
                    "pos_y": 20.3,
                    "active_hours": 8.0,
                    "fault_phase": (
                        "incident_47" if 30 <= sec < 60
                        else "recover" if sec >= 60
                        else "normal"
                    ),
                    "is_faulty": 45 <= sec < 60,
                })
            db.write_robot(rows)
        n_total = db.count("robot_telemetry")
        sha = db.table_sha256("robot_telemetry")[:12]
    file_size_kb = db_path.stat().st_size / 1024 if db_path.exists() else 0
    return {
        "n_total": n_total,
        "file_size_kb": file_size_kb,
        "sha_prefix": sha,
        "path": str(db_path.relative_to(_ROOT)),
    }


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

    # 현재 마커 강조 (큰 markdown header)
    st.markdown(f"### ▶ {MARKERS[current_marker_idx][1]}  ({progress_pct:.0%})")
    st.progress(progress_pct)

    # Chip row via Plotly — 키운 크기 (mason 피드백: 글씨 잘 보이게)
    labels = [label for _, label in MARKERS]
    x_pos = [i for i in range(len(MARKERS))]
    colors = [
        "#1f77b4" if i == current_marker_idx else
        "#aec7e8" if i < current_marker_idx else
        "#e0e0e0"
        for i in range(len(MARKERS))
    ]
    font_colors = [
        "white" if i <= current_marker_idx else "#666"
        for i in range(len(MARKERS))
    ]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_pos,
        y=[0] * len(MARKERS),
        mode="markers+text",
        marker=dict(size=30, color=colors, line=dict(width=2, color="#666")),
        text=[str(i) for i in range(len(MARKERS))],
        textposition="middle center",
        textfont=dict(color=font_colors, size=14, family="Arial Black"),
        hovertext=labels,
        hoverinfo="text",
    ))
    # Connecting line
    fig.add_shape(
        type="line",
        x0=0, x1=len(MARKERS) - 1,
        y0=0, y1=0,
        line=dict(color="#aec7e8", width=3),
        layer="below",
    )
    # Labels below chips — 2 줄 (시간 + 라벨), 수평
    for i, (_, label) in enumerate(MARKERS):
        parts = label.split(" ", 1)
        time_str = parts[0] if parts else ""
        label_str = parts[1] if len(parts) > 1 else ""
        fig.add_annotation(
            x=i, y=-0.55,
            text=f"<b>{time_str}</b><br>{label_str}",
            showarrow=False,
            font=dict(size=11, color="#333"),
            textangle=0,
            align="center",
        )

    fig.update_layout(
        height=180,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(visible=False, range=[-0.5, len(MARKERS) - 0.5]),
        yaxis=dict(visible=False, range=[-1.2, 0.5]),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _node_colors_for_marker(marker_idx: int) -> dict[str, str]:
    """marker_idx → DAG 노드 색상 매핑 (mason 5차 피드백: 동적 표현)."""
    base = {n: "#cccccc" for n in DAG_NODES}
    base["DEFECT"] = "#d62728"

    if marker_idx == 1:
        base["tool_age"] = "#ff7f0e"
    elif marker_idx in (2, 3):
        for n in ["tool_age", "spindle_rpm", "coolant_temp",
                  "vibration_xyz", "thermal_drift", "dimension_dev"]:
            base[n] = "#1f77b4"
    elif marker_idx == 4:
        for n in ["tool_age", "coolant_temp", "vibration_xyz",
                  "thermal_drift", "dimension_dev"]:
            base[n] = "#1f77b4"
        base["spindle_rpm"] = "#ff7f0e"
    elif marker_idx == 5:
        for n in ["tool_age", "spindle_rpm", "coolant_temp", "dimension_dev"]:
            base[n] = "#1f77b4"
        base["vibration_xyz"] = "#d62728"
        base["thermal_drift"] = "#d62728"
    elif marker_idx == 6:
        for n in ["tool_age", "spindle_rpm", "dimension_dev"]:
            base[n] = "#1f77b4"
        base["coolant_temp"] = "#ff7f0e"
        base["vibration_xyz"] = "#d62728"
        base["thermal_drift"] = "#d62728"
    return base


_DAG_TITLES = {
    0: "인과 DAG  |  baseline (정상 가동)",
    1: "인과 DAG  |  <span style='color:#ff7f0e'>tool_age 누적 감지 (예지)</span>",
    2: "인과 DAG v1  |  <span style='color:#1f77b4'>원인 후보 식별</span>",
    3: "인과 DAG v1  |  <span style='color:#1f77b4'>운영자 검토 중</span>",
    4: "인과 DAG  |  <span style='color:#ff7f0e'>spindle_rpm 개입 시뮬 (do-intervention)</span>",
    5: "인과 DAG  |  <span style='color:#d62728'>thermal/vibration → DEFECT 실재 발생</span>",
    6: "인과 DAG v2  |  <span style='color:#ff7f0e'>coolant_temp 신규 path 발견 (학습)</span>",
}


def render_causal_dag(marker_idx: int = 0) -> None:
    """6-Node 인과 DAG with marker-specific node coloring (mason 5차 피드백).

    각 마커별 활성 노드를 색상으로 강조 — 시연 narrative 가 정적 X, 동적 가시화.
    """
    G = nx.DiGraph()
    G.add_nodes_from(DAG_NODES)
    G.add_edges_from(DAG_EDGES)
    pos = nx.planar_layout(G)

    # 엣지
    edge_x, edge_y = [], []
    for src, dst in G.edges():
        x0, y0 = pos[src]
        x1, y1 = pos[dst]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]
    edge_trace = go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=1.5, color="#888"), hoverinfo="none",
    )

    # 노드 (marker_idx 별 색상)
    color_map = _node_colors_for_marker(marker_idx)
    node_x = [pos[n][0] for n in G.nodes()]
    node_y = [pos[n][1] for n in G.nodes()]
    node_color_list = [color_map[n] for n in G.nodes()]

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        marker=dict(size=24, color=node_color_list, line=dict(width=2, color="white")),
        text=list(G.nodes()), textposition="top center",
        textfont=dict(size=10), hoverinfo="text",
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        title=dict(text=_DAG_TITLES.get(marker_idx, "인과 DAG"), font=dict(size=13)),
        height=340, margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── 마커별 가시 액션 helper (mason 5차 피드백 P0+P1) ──────────────────────────────

def render_causal_v1_explanation() -> None:
    """마커 2 (0:30 인과 v1) — DAG 의미 청중 친화 부가 설명."""
    st.info("🔍 **인과 분석 시작** — risk 62% 예지경보의 근본 원인 후보 식별")

    col_l, col_r = st.columns([1, 1])
    with col_l:
        with st.container(border=True):
            st.markdown("##### 📘 DAG 노드 색상 가이드")
            st.markdown(
                "- 🔵 **파란색** — 원인 후보 (causal predecessor)\n"
                "- 🟠 **주황색** — 개입 포인트 (do-intervention)\n"
                "- 🔴 **빨간색** — 결과 노드 (DEFECT)\n"
                "- ⚪ **회색** — 현재 비활성"
            )
    with col_r:
        with st.container(border=True):
            st.markdown("##### 🎯 이 단계의 의미")
            st.markdown(
                "단순 상관관계 (correlation) 가 아니라 **인과 관계 (causation)**.\n\n"
                "DoWhy 가 6 노드에서 인과 path 식별:\n"
                "- 3 개 base cause: `tool_age`, `spindle_rpm`, `coolant_temp`\n"
                "- 2 개 mediator: `vibration_xyz`, `thermal_drift`\n"
                "- 1 개 outcome path: `dimension_dev` → `DEFECT`"
            )
    st.caption("⚖️ Confounder Robustness: σ_max = 0.40 < 0.5 → **robust** (Wright 1991 partial R²)")


def render_causal_v2_explanation() -> None:
    """마커 6 (1:30 인과 v2) — DAG v1 → v2 학습 narrative."""
    st.success("🎓 **인과 v2 학습 완료** — incident #47 패턴이 신규 path 로 자동 통합")

    col_l, col_r = st.columns([1, 1])
    with col_l:
        with st.container(border=True):
            st.markdown("##### 🔄 v1 → v2 변화")
            st.markdown(
                "- ➕ **신규 edge**: `coolant_temp → thermal_drift`\n"
                "- 🟠 **coolant_temp** 주황색 강조 (신규 발견 원인)\n"
                "- 📊 σ_max 재계산: 0.40 → 0.38 (더 robust)"
            )
    with col_r:
        with st.container(border=True):
            st.markdown("##### 💡 학습 자산화")
            st.markdown(
                "incident #47 데이터로 인과 모델 자동 갱신.\n\n"
                "다음 시연에서:\n"
                "- 동일 패턴 재발 시 **즉시** 인식\n"
                "- coolant_temp 모니터 우선순위 ↑\n"
                "- 모델은 영구적 자산"
            )


def render_normal_status() -> None:
    """마커 0 (0:00 정상) — sensor live 4-grid."""
    st.info("✅ **정상 가동 중** — 모든 sensor 안전 범위, 라인 가동률 100%")

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("motor_temp", "85°C", help="SOP 임계 100°C 미만")
    with c2: st.metric("vibration_xyz", "0.8", help="기준 norm < 1.5")
    with c3: st.metric("RPM", "8,500", help="표준 8500")
    with c4: st.metric("coolant_temp", "22°C", help="기준 < 25°C")
    st.caption("📡 11 sensor 실시간 통합 · DuckDB in-process · latency < 100ms")


def render_predictive_alert() -> None:
    """마커 1 (0:15 예지경보) — XGBoost 확률 기반 risk 알람 + 6-class 확률 분포."""
    st.warning("⚠️ **예지경보** — ROBOT-00018, motor_temp 92°C 상승 추세 + tool_age 누적 감지")

    col_alert, col_chart = st.columns([1, 2])
    with col_alert:
        st.metric("결함 Risk", "62%", delta="+44%p", delta_color="inverse",
                  help="XGBoost 6-class 1−P(NONE)")
        st.metric("1순위 Failure", "HDF",
                  help="Heat Dissipation Failure")
        st.caption("📊 단순 임계값 X → ML 확률 예지 (ADR-009)")

    with col_chart:
        classes = ["NONE", "TWF", "HDF", "PWF", "OSF", "RNF"]
        probs = [0.12, 0.18, 0.62, 0.04, 0.03, 0.01]
        colors = ["#ff7f0e" if c == "HDF" else "#aec7e8" for c in classes]
        fig = go.Figure(go.Bar(
            x=classes, y=probs, marker_color=colors,
            text=[f"{p:.0%}" for p in probs], textposition="auto",
        ))
        fig.update_layout(
            title=dict(text="XGBoost 6-class 확률 분포", font=dict(size=13)),
            height=240, yaxis=dict(range=[0, 0.8], title="P"),
            margin=dict(l=10, r=10, t=40, b=10), showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_human_decision() -> None:
    """마커 3 (0:45 인간결정) — 3 원인 후보 중 do-intervention 대상 선택 (mason 8차).

    인과관계 정확 파악 위해 DAG 의 3 base cause 중 spindle_rpm 선택 → 시뮬 가속.
    """
    st.info("🧑‍🔧 **운영자 검토** — DAG 가 식별한 3 원인 후보 중 **do-intervention 대상 선택**")

    col_candidates, col_decision = st.columns([2, 1])

    with col_candidates:
        with st.container(border=True):
            st.markdown("##### 🎯 3 원인 후보 비교 — DoWhy 시뮬 vs 실 운영 적용")
            st.markdown(
                "| 후보 | DoWhy 시뮬 | 실 운영 적용 방식 | 적용 소요 |\n"
                "|---|---|---|---|\n"
                "| `tool_age` | ✅ 가능 | 공구 교체 정비 | **4h+** |\n"
                "| **`spindle_rpm`** | ✅ 가능 | **소프트웨어 명령** | **0 (즉시)** |\n"
                "| `coolant_temp` | ✅ 가능 | 냉각수 보충/교체 | **1-2h** |\n"
            )
            st.caption(
                "💡 **시뮬은 3 후보 모두 즉시 가능** (DoWhy `do-intervention`, 시뮬 비용 = 0). "
                "운영자가 1개 우선 골라 시연 시간 + **실 운영 적용 비용** 절약. "
                "`spindle_rpm` = 가장 빠른 시뮬 검증 + 즉시 적용 path → 우선 시뮬 선택."
            )

    with col_decision:
        with st.container(border=True):
            st.markdown("##### ✅ 운영자 결정")
            st.success("**`spindle_rpm` ↓** 우선 시뮬")
            st.metric("선택 근거", "실 적용 0 비용")
            st.caption("📝 maker-space-op-001 · ⏱️ 0:42")
            st.caption("⚙️ 다음 (마커 4): `do(spindle_rpm = 7650)` 시뮬 가속")


def render_simulation_evidence() -> None:
    """마커 4 (1:00 시뮬가속) — DoWhy counterfactual `do(spindle_rpm=7650)` 결과."""
    st.success("🎬 **시뮬레이션 가속 완료** — counterfactual `do(spindle_rpm = 7650)` 결과")

    col_metrics, col_chart = st.columns([1, 2])
    with col_metrics:
        st.metric("vibration_xyz", "0.8 → 0.5", delta="-38%", delta_color="inverse")
        st.metric("thermal_drift_um", "5 → 3", delta="-40%", delta_color="inverse")
        st.metric("defect_prob", "62% → 18%", delta="-44%p", delta_color="inverse")
        st.caption("📊 DoWhy do-intervention (Pearl 1995)")

    with col_chart:
        metrics = ["vibration_xyz", "thermal_drift_um", "defect_prob"]
        baseline = [0.8, 5.0, 0.62]
        intervention = [0.5, 3.0, 0.18]
        fig = go.Figure()
        fig.add_trace(go.Bar(name="개입 전", x=metrics, y=baseline,
                             marker_color="#d62728",
                             text=[f"{v}" for v in baseline], textposition="auto"))
        fig.add_trace(go.Bar(name="개입 후 (시뮬)", x=metrics, y=intervention,
                             marker_color="#2ca02c",
                             text=[f"{v}" for v in intervention], textposition="auto"))
        fig.update_layout(
            title=dict(text="counterfactual: spindle_rpm 8500 → 7650", font=dict(size=13)),
            barmode="group", height=270,
            margin=dict(l=10, r=10, t=50, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_incident_alert() -> None:
    """마커 5~6 (1:15 / 1:30) — INCIDENT #47 빨강 alert + sensor timeline."""
    st.error("🚨 **INCIDENT #47** — ROBOT-00018  motor_temp **105°C** 도달 (SOP 임계 100°C 초과), HDF 실재 발생")

    col_metrics, col_chart = st.columns([1, 2])
    with col_metrics:
        st.metric("motor_temp", "105°C", delta="+13°C / 1min", delta_color="inverse")
        st.metric("vibration_xyz", "2.3", delta="+1.5 (+188%)", delta_color="inverse")
        st.metric("defect_prob (실측)", "62% → 95%", delta="+33%p", delta_color="inverse")
        st.caption("⚠️ 예지 risk 62% 실제 발현, DAG v2 갱신")

    with col_chart:
        sec = list(range(60))
        motor_temp = [85 + 0.05 * t + (0.5 * (t - 30) if t >= 30 else 0) for t in sec]
        vibration = [0.8 + 0.01 * t + (0.05 * (t - 30) if t >= 30 else 0) for t in sec]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=sec, y=motor_temp, name="motor_temp (°C)",
                                  mode="lines", line=dict(color="#d62728", width=2),
                                  yaxis="y"))
        fig.add_trace(go.Scatter(x=sec, y=vibration, name="vibration_xyz",
                                  mode="lines", line=dict(color="#ff7f0e", width=2),
                                  yaxis="y2"))
        fig.add_hline(y=100, line_dash="dash", line_color="red",
                      annotation_text="SOP 임계 100°C", annotation_position="top right")
        fig.update_layout(
            title=dict(text="incident #47 sensor timeline (60s)", font=dict(size=13)),
            height=270,
            xaxis=dict(title="time (s)"),
            yaxis=dict(title="motor_temp (°C)", side="left"),
            yaxis2=dict(title="vibration_xyz", side="right", overlaying="y"),
            margin=dict(l=10, r=10, t=50, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
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


def render_retrain_evidence() -> None:
    """마커 9 (3:30 재학습) 근거 — 정확도 0.62→0.91 + Failure class 별 F1.

    incident #47 패턴 추가 학습 → XGBoost 6-class 모델 재학습 완료.
    """
    st.markdown("##### 🎓 재학습 결과 — incident #47 패턴 학습")

    col_metric, col_chart = st.columns([1, 2])
    with col_metric:
        st.metric("재학습 전 정확도", "0.62", help="incident #47 발생 시점 모델")
        st.metric("재학습 후 정확도", "0.91", delta="+0.29 (+47%)",
                  help="incident #47 패턴 추가 학습 후")
        st.caption("📊 동일 결함 패턴 재발 예방, 강화학습 루프 검증")

    with col_chart:
        class_names = ["NONE", "TWF", "HDF", "PWF", "OSF", "RNF"]
        before_f1 = [0.85, 0.45, 0.50, 0.60, 0.55, 0.65]
        after_f1  = [0.96, 0.88, 0.93, 0.90, 0.85, 0.92]
        fig = go.Figure()
        fig.add_trace(go.Bar(name="재학습 전", x=class_names, y=before_f1,
                             marker_color="#aec7e8",
                             text=[f"{v:.2f}" for v in before_f1],
                             textposition="auto"))
        fig.add_trace(go.Bar(name="재학습 후", x=class_names, y=after_f1,
                             marker_color="#1f77b4",
                             text=[f"{v:.2f}" for v in after_f1],
                             textposition="auto"))
        fig.update_layout(
            title=dict(text="Failure Class 별 F1 Score", font=dict(size=13)),
            barmode="group", height=270,
            yaxis=dict(range=[0, 1.05], title="F1"),
            margin=dict(l=10, r=10, t=50, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_feature_importance_change() -> None:
    """마커 9 신규 — incident #47 학습 후 XGBoost feature importance 변화.

    재학습 자산화 narrative: incident 가 모델 결정 트리에 어떻게 통합됐는지.
    """
    st.markdown("##### 🧠 incident #47 학습 영향도 — Feature Importance 변화")

    features = ["motor_temp_max", "tool_age", "thermal_drift", "vibration_max",
                "coolant_temp", "spindle_rpm"]
    before_imp = [0.18, 0.22, 0.12, 0.15, 0.08, 0.10]
    after_imp  = [0.31, 0.18, 0.21, 0.14, 0.06, 0.08]

    col_metric, col_chart = st.columns([1, 2])
    with col_metric:
        st.metric("motor_temp_max", "0.18 → 0.31", delta="+72%",
                  help="incident #47 로 HDF 핵심 feature 부각")
        st.metric("thermal_drift", "0.12 → 0.21", delta="+75%",
                  help="인과 DAG v2 신규 path 반영")
        st.metric("tool_age 가중", "0.22 → 0.18", delta="-18%", delta_color="inverse",
                  help="HDF 비중 ↑ → 다른 feature 가중 ↓")
        st.caption("📊 incident 패턴이 XGBoost 결정 트리에 자산화")

    with col_chart:
        fig = go.Figure()
        fig.add_trace(go.Bar(name="재학습 전", x=features, y=before_imp,
                             marker_color="#aec7e8",
                             text=[f"{v:.2f}" for v in before_imp],
                             textposition="auto"))
        fig.add_trace(go.Bar(name="재학습 후", x=features, y=after_imp,
                             marker_color="#1f77b4",
                             text=[f"{v:.2f}" for v in after_imp],
                             textposition="auto"))
        fig.update_layout(
            title=dict(text="XGBoost Feature Importance (top 6)", font=dict(size=13)),
            barmode="group", height=290,
            yaxis=dict(range=[0, 0.4], title="Importance"),
            margin=dict(l=10, r=10, t=50, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(tickangle=-15),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_closed_loop_summary() -> None:
    """마커 10 신규 — PRISM Closed-Loop 4-step 가치 요약 (발표 메시지)."""
    st.markdown("##### 🔄 PRISM Closed-Loop 4-step — 완주 시간 3:45")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        with st.container(border=True):
            st.markdown("##### 📡 ① 센서통합")
            st.metric("처리 latency", "< 100ms")
            st.caption("DuckDB in-process · 11 sensor 실시간")
    with c2:
        with st.container(border=True):
            st.markdown("##### 🔍 ② 인과 RCA")
            st.metric("RCA 시간", "24min", delta="-90%", delta_color="inverse")
            st.caption("DoWhy 6-Node + σ_max 0.40 robust")
    with c3:
        with st.container(border=True):
            st.markdown("##### 🤖 ③ Multi-Agent")
            st.metric("협상 응답", "~8s")
            st.caption("Sonnet + Haiku × 4 · Net Value (KRW)")
    with c4:
        with st.container(border=True):
            st.markdown("##### 🎓 ④ 학습 자산화")
            st.metric("재학습 정확도", "0.91", delta="+47%")
            st.caption("incident #47 → DAG v2 + 모델 갱신")


def render_cost_impact() -> None:
    """마커 10 신규 — PRISM 도입 비용 임팩트 (vs 엔터프라이즈 MES)."""
    st.markdown("##### 💰 비용 임팩트 — 1년 운영 시뮬 (1인 메이커스페이스)")

    col_compare, col_chart = st.columns([1, 2])
    with col_compare:
        st.metric("PRISM 연간", "₩240,000",
                  help="₩20 × 12 = 노트북 1대 + Bedrock on-demand")
        st.metric("MES 연간", "₩10,000,000+",
                  delta="-97.6%", delta_color="inverse",
                  help="엔터프라이즈 MES (보수적 추정)")
        st.metric("연간 절감", "₩9,760,000+",
                  help="PRISM 도입 시 절감 + incident 손실 -90%")
        st.caption("📌 비용 -98% + incident 손실 사전 예방")

    with col_chart:
        categories = ["라이선스/<br>운영비", "incident<br>1건 손실<br>(평균)", "RCA<br>인건비/년"]
        without_prism = [10_000_000, 5_000_000, 8_000_000]
        with_prism = [240_000, 500_000, 800_000]
        fig = go.Figure()
        fig.add_trace(go.Bar(name="MES (without PRISM)", x=categories, y=without_prism,
                             marker_color="#d62728",
                             text=[f"₩{v/1_000_000:.1f}M" for v in without_prism],
                             textposition="auto"))
        fig.add_trace(go.Bar(name="PRISM", x=categories, y=with_prism,
                             marker_color="#2ca02c",
                             text=[f"₩{v/1_000_000:.2f}M" for v in with_prism],
                             textposition="auto"))
        fig.update_layout(
            title=dict(text="3 비용 항목 비교 (단위: 원)", font=dict(size=13)),
            barmode="group", height=290,
            yaxis=dict(title="₩", type="log",
                       tickvals=[100_000, 1_000_000, 10_000_000],
                       ticktext=["10만", "100만", "1000만"]),
            margin=dict(l=10, r=10, t=50, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_oee_evidence() -> None:
    """마커 10 (3:45 OEE +35%) 근거 — Availability × Performance × Quality (Nakajima 표준)."""
    st.markdown("##### 🏭 OEE +35% 달성 — Nakajima 3 구성 요소")

    components = ["Availability<br>(가용률)", "Performance<br>(성능률)", "Quality<br>(품질률)"]
    before = [0.75, 0.70, 0.65]   # OEE = 0.341
    after  = [0.85, 0.85, 0.92]   # OEE = 0.665
    oee_before = before[0] * before[1] * before[2]
    oee_after  = after[0] * after[1] * after[2]

    col_card, col_chart = st.columns([1, 2])
    with col_card:
        st.metric("OEE 개선 전", f"{oee_before:.1%}")
        st.metric("OEE 개선 후", f"{oee_after:.1%}",
                  delta=f"+{(oee_after / oee_before - 1) * 100:.0f}% (relative)")
        st.caption("OEE = 가용 × 성능 × 품질  (Nakajima 1989)")

    with col_chart:
        fig = go.Figure()
        fig.add_trace(go.Bar(name="개선 전", x=components, y=before,
                             marker_color="#aec7e8",
                             text=[f"{v:.0%}" for v in before],
                             textposition="auto"))
        fig.add_trace(go.Bar(name="개선 후", x=components, y=after,
                             marker_color="#1f77b4",
                             text=[f"{v:.0%}" for v in after],
                             textposition="auto"))
        fig.update_layout(
            title=dict(text="3 구성 요소 비교", font=dict(size=13)),
            barmode="group", height=270,
            yaxis=dict(range=[0, 1.05], title="율"),
            margin=dict(l=10, r=10, t=50, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


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

        status = _seed_storage_demo()
        st.markdown("---")
        st.markdown("### 📦 DuckDB In-Process")
        st.markdown(
            f"**{status['n_total']:,} rows** · **{status['file_size_kb']:.0f} KB**\n\n"
            "🏭 일반 MES = 별도 DB 서버 + DBA 필요 (월 ₩수십만)\n\n"
            "✅ PRISM = 노트북 1대 in-process · **DB 서버 0 대**"
        )
        st.caption(f"`{status['path']}` · SHA `{status['sha_prefix']}...`")

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
        # 마커 0~6: DAG (marker_idx 별 색상) + 단계별 가시 액션
        if marker_idx < 7:
            render_causal_dag(marker_idx)
            if marker_idx == 0:
                st.markdown("---")
                render_normal_status()
            elif marker_idx == 1:
                st.markdown("---")
                render_predictive_alert()
            elif marker_idx == 2:
                st.markdown("---")
                render_causal_v1_explanation()
            elif marker_idx == 3:
                st.markdown("---")
                render_human_decision()
            elif marker_idx == 4:
                st.markdown("---")
                render_simulation_evidence()
            elif marker_idx == 5:
                st.markdown("---")
                render_incident_alert()
            elif marker_idx == 6:
                st.markdown("---")
                render_causal_v2_explanation()
                st.markdown("---")
                render_incident_alert()

        # 마커 7~8: 4 Agent 협상 + Supervisor 결정
        elif marker_idx in (7, 8):
            try:
                if _PRISM_MODE in ("demo", "live"):
                    sup_out, candidates_ordered = _real_supervisor_decision(
                        marker_idx, alpha, beta, gamma, horizon_h=4,
                    )
                    if marker_idx == 8:
                        render_supervisor_card(sup_out)
                        st.markdown("---")
                        st.markdown("##### 🤖 위 결정의 근거: 4 Domain Agent 협상")
                        render_4agent_outputs(candidates_ordered[0])
                    else:
                        render_4agent_outputs(candidates_ordered[0])
                else:
                    action = _mock_4agent_action()
                    if marker_idx == 8:
                        sup_out = _mock_supervisor_decision()
                        net, breakdown = compute_net_value_KRW(
                            quality=action.quality, safety=action.safety,
                            equipment=action.equipment, production=action.production,
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

        # 마커 9: 재학습 deep dive (Supervisor + 4 Agent 제거, mason 6차 피드백)
        elif marker_idx == 9:
            render_retrain_evidence()
            st.markdown("---")
            render_feature_importance_change()

        # 마커 10: OEE + Closed-Loop 요약 + 비용 임팩트
        elif marker_idx == 10:
            render_oee_evidence()
            st.markdown("---")
            render_closed_loop_summary()
            st.markdown("---")
            render_cost_impact()

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
        st.markdown("#### 현재 단계 상세")
        sec, label = MARKERS[marker_idx]
        mm = sec // 60
        ss = sec % 60
        st.metric("타임코드", f"{mm}:{ss:02d}")
        st.metric("단계", label.split(" ", 1)[1] if " " in label else label)
        st.caption(f"📝 {_MARKER_DESCRIPTIONS.get(marker_idx, '')}")

        # 마커별 sub-metric (KPI 의미 있는 시점만)
        sub_kpis = _MARKER_SUB_KPIS.get(marker_idx, [])
        if sub_kpis:
            st.markdown("---")
            st.markdown("##### 단계 지표")
            for label_kpi, value_kpi in sub_kpis:
                st.metric(label_kpi, value_kpi)

        # 마커 9 재학습 / 마커 10 OEE final
        if marker_idx >= 9:
            st.success("🎓 재학습: 0.62 → 0.91 (+47%)")
        if marker_idx >= 10:
            st.success("🏭 OEE +35% 달성")

    st.markdown("---")
    st.caption(
        f"PRISM v0.1-demo  |  PRISM_MODE={_PRISM_MODE}  |  본선 5/22 시연용"
    )


if __name__ == "__main__":
    main()

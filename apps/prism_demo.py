"""PRISM 본선 7분 시연용 Streamlit app 골격.

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
    (45,  "0:45 운영자결정"),
    (60,  "1:00 시뮬가속"),
    (75,  "1:15 불량 #47"),
    (90,  "1:30 인과v2"),
    (135, "2:15 4 Agent"),
    (180, "3:00 Supervisor"),
    (210, "3:30 재학습 0.81→0.97"),
    (225, "3:45 OEE +32%p"),
]
TOTAL_SECONDS = 225  # 3:45

# CNC fleet (시연 narrative 는 incident 1대 중심, 9대 는 정상 가동 배경 fact).
# 기획서 "스마트 공장" 의미 충족 + V3 enterprise scale-out 의 정량 anchor.
FLEET_SIZE = 10
FLEET_MACHINE_IDS: list[str] = [f"CNC-{i:02d}" for i in range(1, FLEET_SIZE + 1)]
INCIDENT_MACHINE_ID = "CNC-01"  # narrative 의 단일 incident 머신
HEALTHY_MACHINE_IDS: list[str] = [m for m in FLEET_MACHINE_IDS if m != INCIDENT_MACHINE_ID]

# 각 마커별 한국어 1줄 설명 (mason 피드백: 단계 metric 아래 caption)
_MARKER_DESCRIPTIONS: dict[int, str] = {
    0:  "센서 데이터 정상 흐름, 모든 라인 가동 중",
    1:  "tool_age 18h 누적 (표준 200h 곡선 대비 빠른 마모 추세) → 라이브 XGBoost 예지경보 (TWF 1순위)",
    2:  "DoWhy 6-Node DAG 인과 추론 v1 생성 — 공구 교체 추천 (tool_age reset, XGBoost 감지 변수와 통일)",
    3:  "운영자 결정: '보류' (라인 가동 우선, v1 추천 미적용)",
    4:  "보류 시 3시간 fast-forward 시뮬 → 결함 진행 trajectory",
    5:  "결함 #47 실제 발생 — 보류 결정의 결과, motor_temp 105°C",
    6:  "인과 v2 학습 — Causal Effect 정확화 (CE 0.78 → 0.71)",
    7:  "4 Domain Agent 가 동시 분석 (품질·안전·설비·생산)",
    8:  "Supervisor 가 Net Value 산정 — 최적 액션 권고",
    9:  "라이브 XGBoost 재학습 — incident #47 패턴 추가, accuracy 라이브 측정",
    10: "OEE +32%p 달성, 시연 완료",
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
    3: "normal",   # 0:45 운영자 결정
    4: "normal",   # 1:00 시뮬 가속
    5: "fault",    # 1:15 불량 #47 발생
    6: "fault",    # 1:30 인과 v2
    7: "fault",    # 2:15 4 Agent 협상
    8: "fault",    # 3:00 Supervisor 결정
    9: "recover",  # 3:30 재학습 (라이브 측정값은 _get_retrain_artifact)
    10: "recover", # 3:45 OEE +32%p (0.34→0.67 Nakajima 절대)
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
    1:  [("결함 risk", "라이브"), ("1순위 type", "TWF")],
    2:  [("v1 추천", "coolant +5%"), ("σ_max", "0.40 ✅")],
    3:  [("결정", "보류"), ("사유", "라인 우선")],
    4:  [("시뮬 압축", "3h → 1s"), ("defect 예측", "62%→95%")],
    5:  [("motor_temp", "105°C"), ("vibration", "+188%")],
    6:  [("CE 정확도", "0.78→0.71"), ("σ_max", "0.40→0.38")],
    8:  [("Net Value", "₩100M"), ("권고 강도", "강한")],
    9:  [("정확도", "라이브"), ("개선", "라이브 Δ")],
    10: [("OEE", "66.5%"), ("개선", "+32.4%p")],
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


# ── 학습 자산화 라이브 재학습 캐시 (마커 9: 본선 라이브 retrain) ───────────────────

@st.cache_resource(show_spinner="🎓 라이브 재학습 중... (5.3k row, ~2초)")
def _get_retrain_artifact() -> dict:
    """incident #47 패턴 추가 → 라이브 XGBoost 재학습 결과 캐시.

    base (5k row) + incident (300 row 극단 outlier) → 합본 학습 → incident test set 정확도 비교.
    시연 시작 시 1회 학습 (~2초), rerun 시 재계산 X.
    """
    from src.ml.local_predictor import (  # noqa: PLC0415
        synthesize_training_data, synthesize_incident_pattern, retrain_with_incident,
    )
    base_df = synthesize_training_data(n=5_000, seed=2026)
    incident_df = synthesize_incident_pattern(n=300, seed=2026)
    new_model, before_acc, after_acc, elapsed_s, before_f1, after_f1 = retrain_with_incident(
        base_df, incident_df, seed=2026,
    )
    return {
        "new_model": new_model,
        "before_acc": before_acc,
        "after_acc": after_acc,
        "elapsed_s": elapsed_s,
        "before_f1": before_f1,
        "after_f1": after_f1,
        "base_rows": len(base_df),
        "incident_rows": len(incident_df),
    }


# ── XGBoost 6-class 라이브 추론 캐시 (Phase 3: 마커 1 예지경보) ───────────────────

@st.cache_resource(show_spinner="🤖 XGBoost 6-class 모델 로드 중...")
def _get_xgb_predictor():
    """LocalXGBoost6Class .pkl 로드 — 시연 시작 1회. predict_proba 라이브 호출용."""
    from src.ml.local_predictor import LocalXGBoost6Class  # noqa: PLC0415
    return LocalXGBoost6Class.load()


# 마커 1 fault-pre-trend feature (standardised, tool_age 누적 → TWF 1순위 trigger)
# narrative: "tool_age 18h 누적 → 표준 200h 대비 빠른 마모 추세 → TWF 예지"
_MARKER1_XGB_FEATURES: dict[str, float] = {
    "tool_age":      3.0,    # 누적 임계 (base cause)
    "spindle_rpm":   0.0,
    "coolant_temp":  0.0,
    "vibration_xyz": 0.6,    # tool wear 동반 진동 약상승
    "thermal_drift": 0.0,
    "dimension_dev": 0.4,    # 치수 편차 시작
}


# ── DoWhy 라이브 ATE 계산 캐시 (Phase 1: 본선 라이브 do-intervention) ─────────────

@st.cache_resource(show_spinner="🔬 DoWhy 6-Node DAG 학습 중... (5k row, ~3초)")
def _get_causal_artifact() -> dict:
    """5k row 합성 데이터 + DoWhy CausalModel — 시연 시작 1회 학습.

    @st.cache_resource process-lifetime 캐시. rerun 시 재계산 X.
    마커 4 (보류 fast-forward) 에서 라이브 do(tool_age) ATE 호출 — XGBoost·DoWhy 변수 통일.
    model_coolant 는 마커 6 v2 학습 (mediator 추가) narrative 용.
    """
    import warnings  # noqa: PLC0415
    from src.orchestration.causal_dag import (  # noqa: PLC0415
        build_dag, synthetic_sensor_data, fit_causal_model_for,
    )
    dag = build_dag()
    df = synthetic_sensor_data(n=5_000, seed=2026)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model_tool_age = fit_causal_model_for(df, dag, treatment="tool_age", outcome="DEFECT")
        model_coolant = fit_causal_model_for(df, dag, treatment="coolant_temp", outcome="DEFECT")
    return {
        "dag": dag, "df": df,
        "model_tool_age": model_tool_age,
        "model_coolant": model_coolant,
    }


# ── CNC stream generator (1 instance, session 유지) ─────────────────────────────

@st.cache_resource(show_spinner=False)
def _get_cnc_generator():
    """CNCStreamGenerator 인스턴스 1개를 세션 전체에 공유. seed=2026 고정."""
    from src.generator.cnc_stream import CNCStreamGenerator  # noqa: PLC0415

    return CNCStreamGenerator(machine_id=INCIDENT_MACHINE_ID, seed=2026)


# ── DuckDB storage demo helper ───────────────────────────────────────────────────

def _incident_cnc_row(sec: int, base_ts, tool_age_h0: float = 17.8) -> dict:
    """INCIDENT_MACHINE_ID 의 100s sensor 타임라인 row 1개.

    0-59s 정상 (tool_age 빠른 마모 추세), 60-89s fault (incident #47),
    90-99s recover. 기존 timeline 과 비트레벨 동일.
    """
    from datetime import timedelta  # noqa: PLC0415
    ts = base_ts + timedelta(seconds=sec)
    tool_age = tool_age_h0 + 0.005 * sec  # 정상 추세 + 누적
    spindle_rpm = 8500.0 + (sec % 3 - 1) * 30
    if sec < 60:
        coolant = 22.0 + (sec % 5) * 0.1
        vibration = 0.8 + (sec % 3) * 0.05
        thermal = 5.0 + (sec % 4) * 0.2
        dim_dev = 2.0 + (sec % 3) * 0.1
        defect = False
    elif sec < 90:
        coolant = 22.0 + (sec - 60) * 0.2
        vibration = 0.8 + (sec - 60) * 0.05
        thermal = 5.0 + (sec - 60) * 0.5
        dim_dev = 2.0 + (sec - 60) * 0.4
        defect = (sec >= 75)
    else:
        coolant = 28.0 - (sec - 90) * 0.4
        vibration = 2.3 - (sec - 90) * 0.12
        thermal = 20.0 - (sec - 90) * 1.2
        dim_dev = 14.0 - (sec - 90) * 1.0
        defect = False
    return {
        "ts": ts,
        "machine_id": INCIDENT_MACHINE_ID,
        "tool_age": tool_age,
        "spindle_rpm": spindle_rpm,
        "coolant_temp": coolant,
        "vibration_xyz": vibration,
        "thermal_drift": thermal,
        "dimension_dev": dim_dev,
        "defect": defect,
    }


def _healthy_cnc_row(sec: int, machine_id: str, machine_index: int, base_ts) -> dict:
    """배경 fact 용 정상 가동 머신 sensor row 1개.

    machine_index (1-base) 로 baseline 미세 변동 — 동일 fleet 인데 모두 똑같으면
    부자연스러움. tool_age baseline 만 머신별 다르고 fault phase 없음.
    """
    from datetime import timedelta  # noqa: PLC0415
    ts = base_ts + timedelta(seconds=sec)
    # 머신별 tool_age baseline (8h ~ 16h, INCIDENT_MACHINE_ID 가 가장 마모됨)
    tool_age_h0 = 8.0 + (machine_index % 5) * 1.5
    tool_age = tool_age_h0 + 0.005 * sec
    spindle_rpm = 8500.0 + (machine_index * 5) + (sec % 3 - 1) * 20
    coolant = 22.0 + (machine_index % 4) * 0.15 + (sec % 5) * 0.05
    vibration = 0.7 + (machine_index % 3) * 0.05 + (sec % 3) * 0.03
    thermal = 4.5 + (machine_index % 4) * 0.3 + (sec % 4) * 0.1
    dim_dev = 1.8 + (machine_index % 3) * 0.1 + (sec % 3) * 0.05
    return {
        "ts": ts,
        "machine_id": machine_id,
        "tool_age": tool_age,
        "spindle_rpm": spindle_rpm,
        "coolant_temp": coolant,
        "vibration_xyz": vibration,
        "thermal_drift": thermal,
        "dimension_dev": dim_dev,
        "defect": False,
    }


@st.cache_resource(show_spinner=False)
def _seed_storage_demo() -> dict:
    """FLEET_SIZE 대 CNC fleet sensor timeline 적재 (1회).

    INCIDENT_MACHINE_ID (CNC-01) = 기존 100s incident timeline (정상 60s + fault 30s + recover 10s).
    HEALTHY_MACHINE_IDS (CNC-02 ~ CNC-10) = 100s 정상 timeline (per-machine baseline 변동).
    robot_telemetry (ROBOT-00018) 은 기존 그대로 유지.

    re-seed gate: 기존 단일 머신 DuckDB 가 디스크에 남아 있으면 fleet 부족 → 자동 보충.
    """
    from datetime import datetime  # noqa: PLC0415

    from src.orchestration.storage import StorageDB  # noqa: PLC0415

    db_path = _ROOT / "data" / "prism_demo.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    base_ts = datetime(2026, 5, 22, 3, 0, 0)
    with StorageDB(str(db_path)) as db:
        if db.count("robot_telemetry") == 0:
            # robot_telemetry: 100 rows (60s timeline + 40s recovery)
            from datetime import timedelta  # noqa: PLC0415
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
        # cnc_telemetry: fleet (incident 1대 + healthy 9대). 기존 single-machine seed 도 보충.
        if db.count("cnc_telemetry") < FLEET_SIZE * 100:
            cnc_rows: list = []
            # INCIDENT_MACHINE_ID — 기존 timeline 유지
            if db.query(
                f"SELECT COUNT(*) AS n FROM cnc_telemetry WHERE machine_id = '{INCIDENT_MACHINE_ID}'"
            )[0]["n"] == 0:
                cnc_rows.extend(_incident_cnc_row(sec, base_ts) for sec in range(100))
            # HEALTHY_MACHINE_IDS — 누락된 머신만 보충
            for idx, mid in enumerate(HEALTHY_MACHINE_IDS, start=2):
                if db.query(
                    f"SELECT COUNT(*) AS n FROM cnc_telemetry WHERE machine_id = '{mid}'"
                )[0]["n"] == 0:
                    cnc_rows.extend(_healthy_cnc_row(sec, mid, idx, base_ts) for sec in range(100))
            if cnc_rows:
                db.write_cnc(cnc_rows)
        n_total = db.count("robot_telemetry")
        cnc_total = db.count("cnc_telemetry")
        sha = db.table_sha256("robot_telemetry")[:12]
    file_size_kb = db_path.stat().st_size / 1024 if db_path.exists() else 0
    return {
        "n_total": n_total,
        "cnc_total": cnc_total,
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
        st.metric(label="OEE 개선", value="+32%p", delta="목표 달성")
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

    # Fleet 배경 fact — narrative 는 incident 1대 중심, 9대 정상 가동은 배경.
    st.caption(
        f"🏭 **{FLEET_SIZE}대 CNC fleet** 라이브 모니터링 (DuckDB cnc_telemetry) · "
        f"현재 incident **{INCIDENT_MACHINE_ID}** · 정상 가동 **{len(HEALTHY_MACHINE_IDS)}대** "
        f"({HEALTHY_MACHINE_IDS[0]} ~ {HEALTHY_MACHINE_IDS[-1]})"
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


# DAG 노드 색상 의미 (legend 와 1:1)
# 4색 신호등 시스템 (청중 인지 우선):
#   ⚪ 회색 = 정상 / 비활성 / 보류 미적용
#   🟡 amber = 예지 risk (아직 미발현)
#   🟠 주황 = 핵심 인과 변수 (감지·추천·학습)
#   🔴 빨강 = 결함 활성 (시뮬·실재 공통, 시뮬 vs 실은 caption 으로 구분)
_COLOR_GREY         = "#9ca3af"
_COLOR_RISK_AMBER   = "#fbbf24"
_COLOR_FOCUS_ORANGE = "#ff7f0e"
_COLOR_DEFECT_RED   = "#d62728"


def _node_colors_for_marker(marker_idx: int) -> dict[str, str]:
    """marker_idx → DAG 노드 색상 (4색 신호등 시스템, tool_age 인과 통일).

    Color semantic (legend 와 1:1):
        ⚪ 회색  = 정상 / 비활성 / 보류
        🟡 amber = 예지 risk (아직 미발현)
        🟠 주황 = 핵심 인과 변수 (감지·추천·학습)
        🔴 빨강 = 결함 활성 (시뮬·실재 공통, caption 으로 구분)

    마커별 narrative (XGBoost·DoWhy 변수 통일 = tool_age):
        0 baseline    : 전부 회색
        1 예지경보    : tool_age 주황 (XGBoost 감지) + DEFECT amber (TWF 예지 risk)
        2 v1 추천     : tool_age 주황 (DoWhy 추천: 공구 교체) + DEFECT amber
        3 보류        : tool_age 회색 (⏸ 추천 적용 안 함) + DEFECT amber
        4 fast-forward: tool_age 회색 (보류 유지) + dimension_dev/DEFECT 빨강 (시뮬 결함)
        5 실 결함     : tool_age 주황 (root cause 확정) + 결함 path 빨강
        6 v2 학습     : tool_age + coolant_temp 주황 (v2 mediator 추가 학습) + DEFECT 빨강
    """
    base = {n: _COLOR_GREY for n in DAG_NODES}

    if marker_idx == 0:
        pass  # 전부 회색
    elif marker_idx == 1:
        base["tool_age"] = _COLOR_FOCUS_ORANGE
        base["DEFECT"] = _COLOR_RISK_AMBER
    elif marker_idx == 2:
        base["tool_age"] = _COLOR_FOCUS_ORANGE
        base["DEFECT"] = _COLOR_RISK_AMBER
    elif marker_idx == 3:
        base["DEFECT"] = _COLOR_RISK_AMBER
    elif marker_idx == 4:
        base["vibration_xyz"] = _COLOR_DEFECT_RED
        base["dimension_dev"] = _COLOR_DEFECT_RED
        base["DEFECT"] = _COLOR_DEFECT_RED
    elif marker_idx == 5:
        base["tool_age"] = _COLOR_FOCUS_ORANGE
        base["vibration_xyz"] = _COLOR_DEFECT_RED
        base["thermal_drift"] = _COLOR_DEFECT_RED
        base["dimension_dev"] = _COLOR_DEFECT_RED
        base["DEFECT"] = _COLOR_DEFECT_RED
    elif marker_idx == 6:
        base["tool_age"] = _COLOR_FOCUS_ORANGE
        base["coolant_temp"] = _COLOR_FOCUS_ORANGE
        base["DEFECT"] = _COLOR_DEFECT_RED
    return base


_DAG_TITLES = {
    0: "인과 DAG  |  <span style='color:#6b7280'>baseline (정상 가동, 결함 미발현)</span>",
    1: "인과 DAG  |  <span style='color:#ff7f0e'>tool_age 18h 누적 감지 (XGBoost TWF 1순위)</span> · <span style='color:#fbbf24'>DEFECT amber (예지 risk)</span>",
    2: "인과 DAG v1  |  <span style='color:#ff7f0e'>v1 추천: 공구 교체 (tool_age reset)</span>",
    3: "인과 DAG v1  |  <span style='color:#9ca3af'>⏸ 운영자 결정: 보류 (공구 교체 미적용)</span>",
    4: "인과 DAG  |  <span style='color:#d62728'>보류 fast-forward (3h 압축) — 결함 진행 시뮬</span>",
    5: "인과 DAG  |  <span style='color:#d62728'>실 결함 — 보류 결정의 결과 (TWF 예지 적중)</span>",
    6: "인과 DAG v2  |  <span style='color:#ff7f0e'>incident 학습 — coolant_temp mediator 추가, CE 0.78 → 0.71</span>",
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

    # base cause (tool_age, spindle_rpm, coolant_temp) + outcome (dimension_dev, DEFECT)
    # → "bottom center" (edge 가 노드 위로 모이는 위치라 label 가림 해소).
    # mediator (vibration_xyz, thermal_drift) → "top center" (노드 위 edge 적음).
    _BOTTOM_LABEL = {"tool_age", "spindle_rpm", "coolant_temp", "dimension_dev", "DEFECT"}
    text_positions = [
        "bottom center" if n in _BOTTOM_LABEL else "top center"
        for n in G.nodes()
    ]

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        marker=dict(size=26, color=node_color_list, line=dict(width=2, color="white")),
        text=[f"<b>{n}</b>" for n in G.nodes()],  # 굵게 (가시성)
        textposition=text_positions,
        textfont=dict(size=13, family="Arial Black, sans-serif"),
        hoverinfo="text",
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        title=dict(text=_DAG_TITLES.get(marker_idx, "인과 DAG"), font=dict(size=13)),
        height=340, margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


_DAG_COLOR_CAPTIONS: dict[int, str] = {
    0: "🎨 DAG 색: 전부 회색 (정상 — risk 미감지)",
    1: "🎨 DAG 색: `tool_age` 주황 (XGBoost가 18h 누적 → TWF 1순위 감지) · `DEFECT` amber (예지 risk, 아직 미발현)",
    2: "🎨 DAG 색: `tool_age` 주황 (DoWhy v1 추천 변수 — 공구 교체로 reset) · `DEFECT` amber 유지",
    3: "🎨 DAG 색: `tool_age` 주황 → **회색** (⏸ 보류, 공구 교체 미적용) · `DEFECT` amber 유지",
    4: "🎨 DAG 색: 결함 path (`vibration/dimension_dev/DEFECT`) **빨강** (시뮬 — 보류 시 trajectory 압축 예측)",
    5: "🎨 DAG 색: 모든 fault path **빨강** (실 결함 manifest) · `tool_age` 주황 (TWF root cause 확정)",
    6: "🎨 DAG 색: `tool_age + coolant_temp` 주황 (v2 학습 — tool_age root cause + coolant_temp mediator 추가, CE 0.78→0.71)",
}


def _render_dag_color_caption(marker_idx: int) -> None:
    """DAG 아래 색 narrative — 단계별 시각 차별화를 청중이 인지하도록."""
    cap = _DAG_COLOR_CAPTIONS.get(marker_idx)
    if cap:
        st.caption(cap)


# ── 마커별 가시 액션 helper (mason 5차 피드백 P0+P1) ──────────────────────────────

def render_causal_v1_explanation() -> None:
    """마커 2 (0:30 인과 v1) — DAG 의미 청중 친화 부가 설명."""
    st.info("🔍 **인과 분석 시작** — risk 62% 예지경보의 근본 원인 후보 식별")

    col_l, col_r = st.columns([1, 1])
    with col_l:
        with st.container(border=True):
            st.markdown("##### 📘 DAG 색상 (4색 신호등)")
            st.markdown(
                "- ⚪ **회색** — 정상 / 보류 / 비활성\n"
                "- 🟡 **amber** — 예지 risk (아직 미발현)\n"
                "- 🟠 **주황** — 핵심 인과 변수 (감지·추천·학습)\n"
                "- 🔴 **빨강** — 결함 활성 (시뮬·실재는 caption으로 구분)"
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
    """마커 6 (1:30 v2) — incident #47 학습으로 Causal Effect 추정 정확화 (기획서 page 7 정합).

    CE 0.78 → 0.71 — v1 의 시뮬 추정 vs 실 결함 mismatch 해소.
    """
    st.success("🎓 **인과 v2 학습 완료** — Causal Effect 추정 정확화 (CE **0.78 → 0.71**)")

    col_l, col_r = st.columns([1, 1])
    with col_l:
        with st.container(border=True):
            st.markdown("##### 📊 v1 vs v2 — Causal Effect (CE)")
            st.markdown(
                "**v1 (incident 전)**:\n"
                "- `coolant_temp → DEFECT` CE = **0.78** (추정)\n"
                "- 시뮬 가속 결과 vs 실 결함 = **mismatch** (보류 시 결함 진행 실측)\n\n"
                "**v2 (incident #47 학습 후)**:\n"
                "- `coolant_temp → DEFECT` CE = **0.71** (실 데이터 반영)\n"
                "- 시뮬 ↔ 실 데이터 정합성 ↑\n"
                "- σ_max 재계산: 0.40 → 0.38 (더 robust)"
            )
    with col_r:
        with st.container(border=True):
            st.markdown("##### 💡 PRISM 핵심 가치 — 학습 자산화")
            st.markdown(
                "❌ **MES**: 사고 발생 → 알람만 → 인간 매번 처음부터 진단\n\n"
                "✅ **PRISM**: 사고 발생 → **인과 모델 자동 갱신** → 다음 사이클부터:\n"
                "- 동일 패턴 **즉시** 인식 (1-2h → 수초)\n"
                "- CE 추정 정확도 ↑ (시뮬 ↔ 실 mismatch 해소)\n"
                "- 모델은 **노트북에 영구 누적** 자산"
            )


def render_normal_status() -> None:
    """마커 0 (0:00 정상) — DuckDB cnc_telemetry 정상 phase row 라이브 read.

    advisor 권고 통합: 시연 화면이 DuckDB 와 유기적으로 연결되어 있음을 평가자에게 입증.
    fallback: DuckDB query 실패 시 하드코딩 표시.
    """
    from src.orchestration.storage import StorageDB  # noqa: PLC0415

    st.info("✅ **정상 가동 중** — DuckDB `cnc_telemetry` 정상 phase row 라이브 read")

    db_path = _ROOT / "data" / "prism_demo.duckdb"
    row = None
    if db_path.exists():
        try:
            with StorageDB(str(db_path)) as db:
                # 정상 phase (defect=False, 60s 이전 row 중 마지막)
                result = db.query(
                    "SELECT * FROM cnc_telemetry WHERE defect = FALSE "
                    "ORDER BY ts DESC LIMIT 1"
                )
                if result:
                    row = result[0]
        except Exception:
            row = None

    c1, c2, c3, c4 = st.columns(4)
    if row:
        with c1: st.metric("coolant_temp", f"{row['coolant_temp']:.1f}°C", help="DuckDB live · 기준 < 25°C")
        with c2: st.metric("vibration_xyz", f"{row['vibration_xyz']:.2f}", help="DuckDB live · 기준 norm < 1.5")
        with c3: st.metric("spindle_rpm", f"{int(row['spindle_rpm']):,}", help="DuckDB live · 표준 8500")
        with c4: st.metric("tool_age", f"{row['tool_age']:.1f}h", help="DuckDB live · 표준 200h 곡선 대비 빠른 마모 추세")
        st.caption(f"📡 DuckDB cnc_telemetry 라이브 read · machine_id={row['machine_id']} · ts={row['ts']}")
    else:
        # fallback (DuckDB 없을 때)
        with c1: st.metric("coolant_temp", "22°C", help="기준 < 25°C")
        with c2: st.metric("vibration_xyz", "0.8", help="기준 norm < 1.5")
        with c3: st.metric("spindle_rpm", "8,500", help="표준 8500")
        with c4: st.metric("tool_age", "17.8h", help="표준 200h 곡선 대비 빠른 마모 추세")
        st.caption("📡 11 sensor — DuckDB 미가동 (fallback 표시)")


_FAILURE_LABEL_HELP: dict[str, str] = {
    "NONE": "정상",
    "TWF":  "Tool Wear Failure (공구 마모)",
    "HDF":  "Heat Dissipation Failure (방열 실패)",
    "PWF":  "Power Failure (전력)",
    "OSF":  "Overstrain Failure (과부하)",
    "RNF":  "Random Failure (랜덤)",
}


def _render_dag_color_legend_compact() -> None:
    """마커 1 등 색 가이드 처음 등장 시점에 표시. 4색 신호등."""
    with st.expander("📘 DAG 색상 가이드 (4색 신호등)", expanded=False):
        st.markdown(
            "- ⚪ **회색** — 정상 / 보류 / 비활성\n"
            "- 🟡 **amber** — 예지 risk (아직 미발현)\n"
            "- 🟠 **주황** — 핵심 인과 변수 (감지·추천·학습)\n"
            "- 🔴 **빨강** — 결함 활성 (시뮬·실재는 caption으로 구분)"
        )


def render_predictive_alert() -> None:
    """마커 1 (0:15 예지경보) — 라이브 XGBoost 6-class predict_proba 호출 (Phase 3).

    fault-pre-trend feature (_MARKER1_XGB_FEATURES) 입력 → 사전 학습 .pkl 라이브 추론.
    cache replay 아닌 실 호출 (~1ms). seed=2026 → 결정성 보장.
    """
    st.warning(
        "⚠️ **예지경보** — ROBOT-00018, **tool_age 18h 누적** (최근 공구 교체 후, "
        "표준 200h 곡선 대비 **빠른 마모 추세**) + vibration 약상승 + 치수 편차 시작 → "
        "TWF (Tool Wear Failure) 1순위"
    )
    _render_dag_color_legend_compact()

    from src.ml.local_predictor import LABEL_NAMES  # noqa: PLC0415
    model = _get_xgb_predictor()
    probs_dict, latency_ms = model.predict_proba_timed(_MARKER1_XGB_FEATURES)
    probs = [probs_dict[c] for c in LABEL_NAMES]
    top_class = max(probs_dict, key=probs_dict.get)
    risk = 1.0 - probs_dict["NONE"]

    col_alert, col_chart = st.columns([1, 2])
    with col_alert:
        st.metric(
            "결함 Risk", f"{risk:.1%}",
            delta=f"{(risk - 0.18) * 100:+.0f}%p",
            delta_color="inverse",
            help="XGBoost 6-class 1−P(NONE) (라이브 호출)",
        )
        st.metric(
            "1순위 Failure", top_class,
            help=_FAILURE_LABEL_HELP.get(top_class, ""),
        )
        st.caption(f"🤖 라이브 XGBoost predict_proba: **{latency_ms:.2f}ms** (PRISM Phase 3)")

    with col_chart:
        colors = ["#ff7f0e" if c == top_class else "#aec7e8" for c in LABEL_NAMES]
        fig = go.Figure(go.Bar(
            x=LABEL_NAMES, y=probs, marker_color=colors,
            text=[f"{p:.1%}" for p in probs], textposition="auto",
        ))
        fig.update_layout(
            title=dict(text="XGBoost 6-class 확률 분포 (라이브 추론)", font=dict(size=13)),
            height=240, yaxis=dict(range=[0, max(probs) + 0.1], title="P"),
            margin=dict(l=10, r=10, t=40, b=10), showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_human_decision() -> None:
    """마커 3 (0:45 운영자결정) — v1 추천 (공구 교체) 보류 결정 (기획서 page 7 정합).

    인간 인지 한계 narrative — 4h 정지 부담으로 적용 보류, 결과는 마커 4 fast-forward 시뮬.
    XGBoost·DoWhy 추천 변수 통일 (tool_age).
    """
    st.info("🧑‍🔧 **운영자 검토** — v1 인과 추천 (공구 교체) 적용 여부")
    st.caption(
        "💡 위 DAG 의 `tool_age` 주황은 v1 추천 변수. XGBoost 가 감지한 변수와 "
        "DoWhy 가 추천한 intervention 변수가 **동일** — 인과 일관성 확보. "
        "보류 결정은 **DAG 적용 X** — 다음 마커 4 에서 보류 시 결함 진행 fast-forward."
    )

    col_candidates, col_decision = st.columns([2, 1])

    with col_candidates:
        with st.container(border=True):
            st.markdown("##### 🎯 인과 v1 분석 결과 — 3 원인 후보")
            st.markdown(
                "| 후보 | v1 추천 | 실 운영 적용 방식 | 적용 비용 |\n"
                "|---|---|---|---|\n"
                "| **`tool_age`** | ✅ **v1 추천: reset** | **공구 교체 (XGBoost 감지 변수와 통일)** | **4h** |\n"
                "| `coolant_temp` | 미추천 (mediator) | 절삭유 보충 | 1-2h |\n"
                "| `spindle_rpm` | 미추천 (직접 path 검증 부족) | 소프트웨어 명령 | 0 |\n"
            )
            st.caption(
                "💡 **v1 인과 모델 추천**: `tool_age` reset (공구 교체) → 누적 마모 path 차단. "
                "단, 라인 정지 4h 비용 발생 — 운영자 결정 필요."
            )

    with col_decision:
        with st.container(border=True):
            st.markdown("##### ⏸️ 운영자 결정")
            st.warning("**보류** (공구 교체 미적용)")
            st.metric("결정 사유", "라인 가동 우선")
            st.caption("📌 공구 교체 적용 시 4h 라인 정지 부담")
            st.caption("📝 maker-space-op-001 · ⏱️ 0:42")
            st.caption("⚠️ 다음 (마커 4): **'보류 시 3시간 fast-forward'** 시뮬")


def render_simulation_evidence() -> None:
    """마커 4 (1:00 시뮬가속) — 운영자 보류 시 3시간 fast-forward (기획서 page 7 정합).

    Phase 1 (본선 라이브): DoWhy do(tool_age) ATE 라이브 호출 — 보류 vs 공구 교체 차이를
    실 인과추론으로 보여준다. XGBoost (마커 1) ·DoWhy 변수 통일 = tool_age.
    trajectory plot 은 결정성 위해 결정론적 공식 유지.
    """
    st.warning("🎬 **시뮬레이션 가속 — 보류 시 3시간 fast-forward**")

    # ── 라이브 DoWhy do(tool_age) ATE — 보류 vs 공구 교체 ───────────────────────
    import warnings  # noqa: PLC0415
    from src.orchestration.causal_dag import estimate_intervention_effect  # noqa: PLC0415
    art = _get_causal_artifact()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # 보류: tool_age 변화 X (baseline 유지). treatment=control=0 → ATE=0.
        ate_hold = estimate_intervention_effect(
            art["model_tool_age"], treatment_value=0.0, control_value=0.0,
        )
        # 적용 (공구 교체 = tool_age −1σ standardised reset): treatment=−1, control=0.
        ate_apply = estimate_intervention_effect(
            art["model_tool_age"], treatment_value=-1.0, control_value=0.0,
        )
    ate_delta = ate_apply - ate_hold

    st.markdown(
        "운영자가 v1 추천 **'공구 교체 보류'** 시 어떻게 되는지 시간 가속 시뮬 — "
        "`do(intervention = None)` counterfactual, **3시간 → 1초 압축**."
    )
    st.success(
        "🔬 **라이브 DoWhy ATE 호출 (5k row, backdoor.linear_regression)**  \n"
        f"- 보류 시 ATE = `{ate_hold:+.4f}` (baseline, treatment=control)  \n"
        f"- 적용 시 ATE = `{ate_apply:+.4f}` (공구 교체 = `do(tool_age = −1σ)`, reset)  \n"
        f"- **인과 효과 차이 Δ = `{ate_delta:+.4f}`** → 적용 시 DEFECT 확률 ↓"
    )

    col_metrics, col_chart = st.columns([1, 2])
    with col_metrics:
        st.metric("시뮬 가속비", "3h → 1s", help="240× 압축 (DoWhy do(None) trajectory)")
        st.metric("defect_prob 예측", "62% → 95%", delta="+33%p", delta_color="inverse")
        st.metric("결함 발생 예상", "~45분 후", help="motor_temp 100°C SOP 임계 도달 (TWF secondary symptom)")
        st.metric(
            "🔬 라이브 ATE Δ", f"{ate_delta:+.4f}",
            delta_color="inverse",
            help="DoWhy do(tool_age=−1σ) − do(=0) — 5k row 합성 데이터 실시간 계산",
        )
        st.caption("📊 보류 trajectory + 라이브 DoWhy ATE")

    with col_chart:
        minutes = list(range(0, 181, 5))  # 0 ~ 180 분, 5분 간격
        motor_temp = [85 + 0.1 * m + (0.15 * (m - 30) if m >= 30 else 0) for m in minutes]
        defect_prob = [min(0.62 + 0.005 * m, 0.95) for m in minutes]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=minutes, y=motor_temp, name="motor_temp (°C)",
            mode="lines", line=dict(color="#d62728", width=2.5), yaxis="y",
        ))
        fig.add_trace(go.Scatter(
            x=minutes, y=defect_prob, name="defect_prob 예측",
            mode="lines", line=dict(color="#ff7f0e", width=2.5), yaxis="y2",
        ))
        fig.add_hline(
            y=100, line_dash="dash", line_color="red",
            annotation_text="SOP 임계 100°C", annotation_position="top right",
        )
        fig.add_vline(
            x=45, line_dash="dot", line_color="#666",
            annotation_text="45분 시점 → 결함 진입",
            annotation_position="top left",
        )
        fig.update_layout(
            title=dict(text="3시간 압축 trajectory (do(intervention = None))", font=dict(size=13)),
            height=270,
            xaxis=dict(title="elapsed (min)"),
            yaxis=dict(title="motor_temp (°C)", side="left", range=[80, 115]),
            yaxis2=dict(title="defect_prob", side="right", overlaying="y", range=[0.5, 1.0]),
            margin=dict(l=10, r=10, t=50, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_incident_alert() -> None:
    """마커 5~6 — INCIDENT #47 빨강 alert + sensor timeline.

    narrative B+A: 예지 적중 + v1 모델 단일 path 한계 노출 → 학습 자산화 motivation.
    """
    st.error("🚨 **INCIDENT #47** — ROBOT-00018  motor_temp **105°C** 도달 (SOP 임계 100°C 초과), HDF 실재 발생")

    col_metrics, col_chart = st.columns([1, 2])
    with col_metrics:
        st.metric("motor_temp", "105°C", delta="+13°C / 1min", delta_color="inverse")
        st.metric("vibration_xyz", "2.3", delta="+1.5 (+188%)", delta_color="inverse")
        st.metric("defect_prob (실측)", "62% → 95%", delta="+33%p", delta_color="inverse")
        st.caption(
            "⚠️ 예지 risk 62% 적중 — 단, **v1 은 spindle_rpm 단일 path 만 봤음**. "
            "실제는 `coolant_temp → thermal_drift` 도 작용 (v1 누락). "
            "→ 학습 자산화 motivation (다음 마커 v2)."
        )

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
    """마커 9 (3:30 재학습) — 라이브 XGBoost 재학습 + accuracy 측정.

    Task 2 (본선 라이브): base (5k row) + incident (300 row 극단 outlier) 합본 학습 →
    incident test set 정확도 비교. cache_replay 아닌 실 fit() 호출.
    """
    col_title, col_btn = st.columns([2, 1])
    with col_title:
        st.markdown("##### 🎓 라이브 재학습 결과 — incident #47 패턴 학습")
    with col_btn:
        if st.button(
            "🔄 재학습 실행 (라이브)",
            help="cache 우회 → 매번 새 XGBoost fit() 호출 (~1.7s). 평가자 직접 클릭 가능.",
            use_container_width=True,
        ):
            _get_retrain_artifact.clear()
            st.rerun()

    art = _get_retrain_artifact()
    before_acc = art["before_acc"]
    after_acc = art["after_acc"]
    delta = after_acc - before_acc
    delta_pct = (delta / before_acc) * 100 if before_acc > 0 else 0

    col_metric, col_chart = st.columns([1, 2])
    with col_metric:
        st.metric(
            "재학습 전 정확도", f"{before_acc:.4f}",
            help=f"base {art['base_rows']} row 만 학습한 모델 — incident pattern 모름",
        )
        st.metric(
            "재학습 후 정확도", f"{after_acc:.4f}",
            delta=f"+{delta:.4f} ({delta_pct:+.1f}%)",
            help=f"base + incident {art['incident_rows']} row 합본 학습",
        )
        st.caption(
            f"🔬 라이브 XGBoost fit() 2회 비교 — {art['elapsed_s']:.2f}s "
            f"(incident extreme outlier {art['incident_rows']} row 자산화)"
        )

    with col_chart:
        class_names = ["NONE", "TWF", "HDF", "PWF", "OSF", "RNF"]
        before_f1 = art["before_f1"]
        after_f1  = art["after_f1"]
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

    art = _get_retrain_artifact()
    before_acc = art["before_acc"]
    after_acc = art["after_acc"]
    delta_pct = ((after_acc - before_acc) / before_acc * 100) if before_acc > 0 else 0

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
            st.metric("재학습 정확도", f"{after_acc:.2f}", delta=f"{delta_pct:+.0f}%")
            st.caption(f"incident #47 라이브 fit() · {before_acc:.2f}→{after_acc:.2f}")


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
    """마커 10 (3:45 OEE +32%p) 근거 — Availability × Performance × Quality (Nakajima 표준)."""
    st.markdown("##### 🏭 OEE +32%p 달성 — Nakajima 3 구성 요소")

    components = ["Availability<br>(가용률)", "Performance<br>(성능률)", "Quality<br>(품질률)"]
    before = [0.75, 0.70, 0.65]   # OEE = 0.341
    after  = [0.85, 0.85, 0.92]   # OEE = 0.665
    oee_before = before[0] * before[1] * before[2]
    oee_after  = after[0] * after[1] * after[2]

    col_card, col_chart = st.columns([1, 2])
    with col_card:
        st.metric("OEE 개선 전", f"{oee_before:.1%}")
        st.metric("OEE 개선 후", f"{oee_after:.1%}",
                  delta=f"+{(oee_after - oee_before) * 100:.1f}%p (절대)")
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


def _render_sidebar_medallion() -> None:
    """사이드바 Medallion Lineage 섹션.

    Bronze / Silver / Gold 3 layer 카드 — row count + 최신 ts.
    각 카드는 expander 로 LIMIT 10 sample row 표 표시.
    """
    from src.orchestration.medallion import create_medallion_views, get_medallion_stats  # noqa: PLC0415
    from src.orchestration.storage import StorageDB  # noqa: PLC0415

    db_path = _ROOT / "data" / "prism_demo.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _LAYER_META = [
        ("bronze", "bronze_cnc_raw",         "🥉 Bronze — Raw",       "#cd7f32"),
        ("silver", "silver_cnc_validated",    "🥈 Silver — Validated", "#aaa9ad"),
        ("gold",   "gold_cnc_window_stats",   "🥇 Gold — Aggregated",  "#ffd700"),
    ]

    try:
        with StorageDB(str(db_path)) as db:
            create_medallion_views(db)
            stats = get_medallion_stats(db)

            for layer_key, view_name, label, color in _LAYER_META:
                layer_stats = stats[layer_key]
                rc = layer_stats["row_count"]
                lt = layer_stats["latest_ts"] or "—"
                with st.expander(f"{label}  |  **{rc:,} rows**", expanded=False):
                    st.caption(f"latest ts: `{lt}`")
                    if rc > 0:
                        sample = db.query(
                            f"SELECT * FROM {view_name} LIMIT 10"  # noqa: S608
                        )
                        import pandas as pd  # noqa: PLC0415
                        st.dataframe(
                            pd.DataFrame(sample),
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.info("데이터 없음 — CNC stream 을 시작하세요.")
    except Exception as exc:
        st.warning(f"Medallion view 로드 실패: {exc}")


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

        # ── Medallion Lineage ────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 📊 Medallion Lineage")
        _render_sidebar_medallion()

        st.markdown("---")
        st.markdown("### 비용 비교")
        st.markdown(f"| 항목 | 비용 |")
        st.markdown(f"|------|------|")
        st.markdown(f"| PRISM / 월 | **{COST_PRISM_KRW_PER_MONTH}** |")
        st.markdown(f"| MES / 년 | ~~{COST_MES_KRW_PER_YEAR}~~ |")
        st.caption("비용 -98%: 노트북 1대 in-process DuckDB + Bedrock on-demand")

        # ── 🔴 LIVE CNC stream ──────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 🔴 LIVE CNC stream")

        if "cnc_stream_running" not in st.session_state:
            st.session_state["cnc_stream_running"] = False
        if "cnc_t" not in st.session_state:
            st.session_state["cnc_t"] = 0.0

        stream_running: bool = st.session_state["cnc_stream_running"]
        btn_label = "⏹ Stop stream" if stream_running else "▶ Start stream"
        if st.button(btn_label, key="cnc_stream_toggle"):
            st.session_state["cnc_stream_running"] = not stream_running
            st.rerun()

        if st.session_state["cnc_stream_running"]:
            import time
            from src.generator.cnc_stream import CNCStreamGenerator  # noqa: PLC0415
            from src.orchestration.storage import StorageDB  # noqa: PLC0415

            gen = _get_cnc_generator()

            # 현재 t 에서 1s 진행
            t = float(st.session_state["cnc_t"])
            sample = gen.next_sample(t)
            st.session_state["cnc_t"] = t + 1.0

            # DuckDB 적재
            db_path = _ROOT / "data" / "prism_demo.duckdb"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with StorageDB(str(db_path)) as db:
                db.write_cnc([sample])
                cnc_total = db.count("cnc_telemetry")

            st.caption(f"t={t:.0f}s · 총 {cnc_total}행 적재 · machine_id={sample['machine_id']}")

            # last 10s 센서 표
            history_samples = [gen.next_sample(float(max(0.0, t - 9 + i))) for i in range(10)]
            import pandas as pd  # noqa: PLC0415
            df_hist = pd.DataFrame(history_samples)[
                ["ts", "spindle_rpm", "coolant_temp", "vibration_xyz", "thermal_drift", "dimension_dev"]
            ]
            st.dataframe(df_hist.tail(10), use_container_width=True, hide_index=True)

            # 라인 차트 (coolant_temp, vibration_xyz, thermal_drift)
            st.line_chart(
                df_hist[["coolant_temp", "vibration_xyz", "thermal_drift"]].reset_index(drop=True),
                height=160,
            )

            # 1초 후 자동 갱신
            time.sleep(1.0)
            st.rerun()
        else:
            st.caption("▶ Start stream 버튼으로 라이브 스트림을 시작합니다.")

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

def render_operator_view() -> None:
    """운영자 대시보드 (mason 의 advisor 권고 — 플랫폼 기획 보강).

    "평소엔 백그라운드, 문제 발생 시 알람 + 승인/거절 버튼" narrative.
    실 운영자가 매일 보는 production UX (시연 timeline view 와 분리).
    """
    from src.orchestration.storage import StorageDB  # noqa: PLC0415

    st.markdown("## 🎛️ 운영자 대시보드 (Production UX)")
    st.caption(
        "📡 평소에는 백그라운드로 모니터링 · 문제 발생 시 Slack 알람 + 이 화면 팝업. "
        "1인 메이커스페이스 운영자가 매일 사용하는 UI."
    )

    # 라이브 sensor + alarm 상태 (DuckDB cnc_telemetry 라이브 read).
    # narrative 안정성을 위해 incident machine 만 조회 — fleet 의 다른 머신은 배경 fact.
    db_path = _ROOT / "data" / "prism_demo.duckdb"
    last_row = None
    incident_rows: list = []
    fleet_summary: list = []
    if db_path.exists():
        try:
            with StorageDB(str(db_path)) as db:
                result = db.query(
                    "SELECT * FROM cnc_telemetry "
                    f"WHERE machine_id = '{INCIDENT_MACHINE_ID}' "
                    "ORDER BY ts DESC LIMIT 1"
                )
                if result:
                    last_row = result[0]
                # 최근 5 incident (defect=True) — 전 fleet 대상
                incident_rows = db.query(
                    "SELECT ts, machine_id, coolant_temp, vibration_xyz, dimension_dev "
                    "FROM cnc_telemetry WHERE defect = TRUE ORDER BY ts DESC LIMIT 5"
                )
                # fleet status — 머신별 최신 defect 상태 + 마지막 sensor metric
                fleet_summary = db.query(
                    "SELECT machine_id, "
                    "       MAX(CAST(defect AS INTEGER)) AS ever_defect, "
                    "       COUNT(*) AS n_rows "
                    "FROM cnc_telemetry GROUP BY machine_id ORDER BY machine_id"
                )
        except Exception:
            pass

    # Fleet KPI bar — 배경 fact (incident 카운트 / 정상 카운트)
    n_incident_now = sum(1 for r in fleet_summary if r.get("ever_defect", 0))
    n_healthy_now = len(fleet_summary) - n_incident_now if fleet_summary else 0
    if fleet_summary:
        k1, k2, k3 = st.columns(3)
        with k1:
            st.metric("Fleet 규모", f"{len(fleet_summary)}대", help="DuckDB cnc_telemetry distinct machine_id")
        with k2:
            st.metric("정상 가동", f"{n_healthy_now}대", delta="OK" if n_healthy_now else None)
        with k3:
            st.metric("Incident", f"{n_incident_now}대",
                      delta=("⚠️ 액션 필요" if n_incident_now else "0"),
                      delta_color="inverse" if n_incident_now else "normal")

    # 🚨 ALARM 카드 (큰 글씨)
    is_alarm = last_row is not None and last_row.get("defect", False)
    if is_alarm:
        st.error(
            f"## 🚨 ALARM — INCIDENT #47 진행 중\n\n"
            f"**{last_row['machine_id']}** (fleet 중 1대)  ·  coolant_temp **{last_row['coolant_temp']:.1f}°C** "
            f"·  vibration **{last_row['vibration_xyz']:.2f}**  ·  dimension_dev **{last_row['dimension_dev']:.1f}μm**\n\n"
            f"⚡ TWF (Tool Wear Failure) 예지 + HDF (Heat Dissipation Failure) 진행 — **즉시 의사결정 필요**\n\n"
            f"🏭 다른 {n_healthy_now}대 ({', '.join(HEALTHY_MACHINE_IDS[:3])} 등) 는 정상 가동 중"
        )
    elif last_row:
        st.success(
            f"## ✅ 정상 가동 — DuckDB cnc_telemetry 라이브\n\n"
            f"**{last_row['machine_id']}**  ·  tool_age **{last_row['tool_age']:.1f}h**  ·  "
            f"coolant **{last_row['coolant_temp']:.1f}°C**  ·  vibration **{last_row['vibration_xyz']:.2f}**\n\n"
            f"🏭 fleet {len(fleet_summary) or FLEET_SIZE}대 전체 정상"
        )
    else:
        st.warning("⚠️ DuckDB 미가동 — 사이드바의 CNC stream Start 또는 demo 모드 실행 필요")

    # 3 의사결정 버튼 (실 운영자 액션)
    st.markdown("### 🎯 운영자 의사결정")
    col_apply, col_hold, col_halt = st.columns(3)
    with col_apply:
        if st.button("✅ AI 추천 적용", use_container_width=True, type="primary"):
            st.toast("✅ 공구 교체 명령 발송 (tool_age reset) — Slack 통보", icon="✅")
    with col_hold:
        if st.button("⏸ 보류 (모니터링 계속)", use_container_width=True):
            st.toast("⏸ 보류 결정 — 운영자 모니터링 모드 유지", icon="⏸")
    with col_halt:
        if st.button("🛑 즉시 정지", use_container_width=True):
            st.toast("🛑 라인 정지 — 정비 요청 발송", icon="🛑")

    st.markdown("---")

    # 최근 5 incident history table
    col_history, col_chart = st.columns([1, 1])
    with col_history:
        st.markdown("##### 📋 최근 5 incident (DuckDB)")
        if incident_rows:
            import pandas as pd  # noqa: PLC0415
            df_inc = pd.DataFrame(incident_rows)
            st.dataframe(df_inc, use_container_width=True, hide_index=True)
        else:
            st.caption("최근 incident 없음 (정상 가동 중)")

    # last 30s sensor mini chart (DuckDB read)
    with col_chart:
        st.markdown("##### 📈 최근 30s sensor (DuckDB live)")
        try:
            with StorageDB(str(db_path)) as db:
                recent = db.query(
                    "SELECT ts, coolant_temp, vibration_xyz FROM cnc_telemetry "
                    "ORDER BY ts DESC LIMIT 30"
                )
            if recent:
                recent.reverse()  # 시간순 정렬
                ts_list = [r["ts"] for r in recent]
                coolant_list = [r["coolant_temp"] for r in recent]
                vibration_list = [r["vibration_xyz"] for r in recent]
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=ts_list, y=coolant_list, name="coolant",
                                          line=dict(color="#ff7f0e")))
                fig.add_trace(go.Scatter(x=ts_list, y=vibration_list, name="vibration",
                                          line=dict(color="#d62728"), yaxis="y2"))
                fig.update_layout(
                    height=240,
                    yaxis=dict(title="coolant °C", side="left"),
                    yaxis2=dict(title="vibration", side="right", overlaying="y"),
                    margin=dict(l=10, r=10, t=20, b=10),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        except Exception:
            st.caption("sensor history 없음")

    st.markdown("---")
    st.info(
        "💡 **실 운영 narrative**: 평소엔 이 화면 안 봄 — Slack 알람만 받음 (incident 발생 시). "
        "알람 클릭 → 이 화면 팝업 → 30초 안에 의사결정 (적용/보류/정지). "
        "**production scale-out 단계**: legacy/grafana/dashboards/* 의 5 dashboard (robot_fleet, "
        "robot_detail, pipeline_health, observability, anomaly_timeline) 로 enterprise stack 확장."
    )


# ── V3 Enterprise Scale-out Vision ──────────────────────────────────────────────

_V3_LAYERS: list[dict] = [
    {
        "title": "1️⃣  Streaming Layer — Kinesis Data Streams",
        "image": "presentation/screenshots/measure-kds-dashboard.png",
        "mvp": f"In-process DuckDB · 노트북 1대 · CNC fleet {FLEET_SIZE}대 (CNC-01 incident + {len(HEALTHY_MACHINE_IDS)}대 정상)",
        "v3":  "KDS + Firehose, 1000대 robot 실시간 telemetry — GetRecords/PutRecords 처리량 + latency 모니터링",
    },
    {
        "title": "2️⃣  ETL Pipeline — Airflow Medallion",
        "image": "presentation/screenshots/airflow-daily-etl.png",
        "mvp": f"단일 Streamlit narrative · {FLEET_SIZE}대 fleet sensor 적재",
        "v3":  "Airflow DAG 5 단계 (quality_check → bronze → silver → gold → bedrock_report → cache_refresh) 일별 자동화",
    },
    {
        "title": "3️⃣  Enterprise Portal — 1000대 Fleet Telemetry",
        "image": "presentation/screenshots/portal-overview.png",
        "mvp": f"Streamlit 단일 대시보드 · {FLEET_SIZE}대 fleet 배경 fact",
        "v3":  "FastAPI + Jinja2 Portal — 1K robot KPI · 116 이상치 · 7일 TWF/HDF/PWF/OSF/RNF 분포 · TOP 10 점검 대상",
    },
    {
        "title": "4️⃣  ML Inference — 6-Class Failure Predict",
        "image": "presentation/screenshots/predict-high.png",
        "mvp": "src/ml/local_predictor.py 라이브 호출 (마커 1)",
        "v3":  "Production predict UI — 자동 채우기 · HIGH/MEDIUM threshold · TWF 98% HIGH 시 공구 마모 교체 가이드",
    },
    {
        "title": "5️⃣  LLM Operator — Bedrock NL Drill-down",
        "image": "presentation/screenshots/bedrock-chat.png",
        "mvp": "Supervisor cache_replay (마커 7~8)",
        "v3":  "Claude Bedrock 자연어 분석 — '긴급 점검 대상 TOP 3' 동적 리포트 + 개별 robot drill-down 차트",
    },
]


def render_enterprise_vision() -> None:
    """V3 view — PRISM MVP 4 차별화 축이 1000대 enterprise stack 으로 확장된 예시.

    legacy/ 의 실 구현 자산을 발췌해 평가자에게 scale-out 비전 시각 증거 제공.
    본선 7분 timeline 외 toggle view — 평가자 자율 탐색용.
    """
    st.markdown("## 🚀 PRISM MVP → V3 Enterprise Scale-out Vision")
    st.info(
        f"💡 **확장 narrative**: PRISM MVP (노트북 1대 + Streamlit + DuckDB + Bedrock cache · "
        f"CNC fleet {FLEET_SIZE}대 시연) 가 production 진입 시 동일 인과 DAG 구조를 유지하면서 "
        "1000대 robot fleet 으로 확장한 예시. "
        "아래 5 layer 는 mason 의 사전 구축 자산 (`legacy/`) 발췌 — **동일 도메인 (제조) 의 layer 별 진화 경로**."
    )
    st.markdown("---")

    for layer in _V3_LAYERS:
        img_path = _ROOT / layer["image"]
        with st.container(border=True):
            st.markdown(f"### {layer['title']}")
            col_img, col_text = st.columns([3, 2])
            with col_img:
                if img_path.exists():
                    st.image(str(img_path), use_container_width=True)
                else:
                    st.warning(f"이미지 누락: {layer['image']}")
            with col_text:
                st.markdown(f"**MVP (현재)**  \n{layer['mvp']}")
                st.markdown("")
                st.markdown(f"**V3 (확장)**  \n{layer['v3']}")
        st.markdown("")

    st.markdown("---")
    st.success(
        "🎯 **scale-out 핵심**: 동일 6-Node 인과 DAG 구조 (`tool_age → vibration/thermal → "
        "dimension_dev → DEFECT`) 를 식품·물류·반도체 등 타 도메인으로 **transfer 가능** — "
        "변수만 도메인 맞춤 (온도 → 신선도, 진동 → 진동, 가동시간 → 가동시간), 인과 모델 구조는 재사용."
    )


def main() -> None:
    st.set_page_config(
        layout="wide",
        page_title="PRISM Demo",
        page_icon="🏭",
    )

    render_header()
    st.markdown("---")

    # View 모드 toggle (mason 의 advisor 권고 — Operator View 분리)
    view_mode = st.radio(
        "🎛️ View 모드",
        options=["전체 시연 (Timeline View)", "🚨 운영자 대시보드 (Operator View)", "🚀 Enterprise Scale-out Vision (V3)"],
        index=0, horizontal=True,
        help="Timeline = 평가자용 시연 view · Operator = 실 운영자 production UX · Enterprise = 대규모 파이프라인 확장 비전",
    )

    if view_mode == "🚨 운영자 대시보드 (Operator View)":
        render_operator_view()
        return
    elif view_mode == "🚀 Enterprise Scale-out Vision (V3)":
        render_enterprise_vision()
        return

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
            _render_dag_color_caption(marker_idx)
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
            _art = _get_retrain_artifact()
            _b, _a = _art["before_acc"], _art["after_acc"]
            _d = ((_a - _b) / _b * 100) if _b > 0 else 0
            st.success(f"🎓 재학습: {_b:.2f} → {_a:.2f} ({_d:+.0f}%)")
        if marker_idx >= 10:
            st.success("🏭 OEE +32%p 달성 (0.34→0.67)")

    st.markdown("---")
    st.caption(
        f"PRISM v0.1-demo  |  PRISM_MODE={_PRISM_MODE}  |  본선 5/22 시연용"
    )


if __name__ == "__main__":
    main()

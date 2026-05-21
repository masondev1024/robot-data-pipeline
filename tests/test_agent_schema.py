"""PRISM 4 Agent + Supervisor Pydantic schema 검증 (ADR v2 Section 6 Unit, A1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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
    SupervisorInput,
    SupervisorOutput,
    TradeoffBreakdown,
    compute_net_value_KRW,
)


def _quality(defect_prob: float = 0.83, ftype: str = "HDF") -> QualityAgentOutput:
    return QualityAgentOutput(
        numeric=QualityNumeric(defect_prob=defect_prob, top_failure_type=ftype),
        narrative_kr="ROBOT-00018 향후 24h 결함 확률 83%, 1순위 HDF",
    )


def _safety(prob: float = 0.62, sop: bool = True, estop: bool = False) -> SafetyAgentOutput:
    return SafetyAgentOutput(
        numeric=SafetyNumeric(sop_violation=sop, estop_required=estop, safety_violation_prob=prob),
        narrative_kr="max_motor_temp 105°C 가 SOP 100°C 초과, 즉시 점검 권고",
    )


def _equipment(rul: float = 18.5, iso: float = -0.34) -> EquipmentAgentOutput:
    return EquipmentAgentOutput(
        numeric=EquipmentNumeric(rul_hours=rul, isolation_forest_score=iso),
        narrative_kr="잔여 수명 18.5h, isolation forest -0.34",
    )


def _production(uph: float = 247.0, feasible: bool = True) -> ProductionAgentOutput:
    return ProductionAgentOutput(
        numeric=ProductionNumeric(throughput_uph=uph, schedule_feasible=feasible, lp_solution_id="lp_test"),
        narrative_kr="현재 스케줄 247 uph 유지 가능",
    )


def _action(action_id: str = "halt_robot_00018") -> CandidateAction:
    return CandidateAction(
        action_id=action_id,
        quality=_quality(),
        safety=_safety(),
        equipment=_equipment(),
        production=_production(),
    )


# ── valid ≥3 ────────────────────────────────────────────────────

def test_valid_quality_agent_minimal():
    out = _quality(defect_prob=0.0, ftype="NONE")
    assert out.numeric.defect_prob == 0.0
    assert out.numeric.top_failure_type == "NONE"


def test_valid_supervisor_input_two_actions():
    inp = SupervisorInput(
        horizon_h=4,
        candidate_actions=[_action("a1"), _action("a2")],
    )
    assert inp.horizon_h == 4
    assert len(inp.candidate_actions) == 2


def test_valid_supervisor_output_with_alternatives():
    decision = SupervisorDecision(
        action_id="a2",
        net_value_KRW=4_320_000.0,
        alternatives=[
            AlternativeAction(action_id="a1", net_value_KRW=-1_152_000.0, rank=2),
        ],
        rationale_kr="A2 가 net +540만원 우위",
        tradeoff_breakdown=TradeoffBreakdown(
            throughput_gain_KRW=8_640_000.0,
            defect_loss_KRW=-300_000.0,
            safety_loss_KRW=-100_000_000.0,
            rul_loss_KRW=-50_000.0,
        ),
    )
    out = SupervisorOutput(decision=decision)
    assert out.decision.action_id == "a2"
    assert out.decision.alternatives[0].rank == 2


# ── invalid ≥3 ──────────────────────────────────────────────────

def test_invalid_defect_prob_above_1():
    with pytest.raises(ValidationError):
        QualityNumeric(defect_prob=1.5, top_failure_type="HDF")


def test_invalid_narrative_kr_length_over_600():
    # mason 32차 (2026-05-21): schema max_length 300 → 600 확대 (라이브 Bedrock 응답 정합).
    # 테스트 threshold 도 600 기준으로 동기화.
    with pytest.raises(ValidationError):
        QualityAgentOutput(
            numeric=QualityNumeric(defect_prob=0.5, top_failure_type="HDF"),
            narrative_kr="가" * 601,
        )


def test_invalid_horizon_h_zero():
    with pytest.raises(ValidationError):
        SupervisorInput(horizon_h=0, candidate_actions=[_action("a1"), _action("a2")])


def test_invalid_candidate_actions_single():
    with pytest.raises(ValidationError):
        SupervisorInput(horizon_h=4, candidate_actions=[_action("a1")])


def test_invalid_failure_type_enum():
    with pytest.raises(ValidationError):
        QualityNumeric(defect_prob=0.5, top_failure_type="INVALID_TYPE")


# ── compute_net_value_KRW ───────────────────────────────────────

def test_net_value_safety_violation_dominates():
    """β safety_violation=1억 KRW → 중간 throughput 까지 net 음수 압도.

    UPH 247 full capacity (178M throughput) 에서는 β default=1 만으로 safety=100M 압도 안 됨.
    이건 도메인 의도 (β slider 가산 시연으로 halt 유도, ADR Decision 1 Synthesis 1).
    UPH 100 = 72M throughput < 100M safety → 압도 검증.
    """
    net, breakdown = compute_net_value_KRW(
        quality=_quality(defect_prob=0.0),
        safety=_safety(prob=1.0),
        equipment=_equipment(rul=100.0),
        production=_production(uph=100.0),
        horizon_h=4,
    )
    assert breakdown.safety_loss_KRW == -100_000_000.0
    assert net < 0


def test_net_value_normal_case():
    """안전 위반 없으면 throughput_gain 이 dominant."""
    net, breakdown = compute_net_value_KRW(
        quality=_quality(defect_prob=0.05),
        safety=_safety(prob=0.0),
        equipment=_equipment(rul=100.0),
        production=_production(uph=247.0),
        horizon_h=4,
    )
    assert breakdown.safety_loss_KRW == 0
    assert net > 0


def test_net_value_deterministic_same_input():
    """동일 입력 → byte-equal 출력 (deterministic, 시연 결정성 prerequisite)."""
    args = dict(
        quality=_quality(defect_prob=0.62),
        safety=_safety(prob=0.0),
        equipment=_equipment(rul=18.5),
        production=_production(uph=247.0),
        horizon_h=4,
    )
    net1, b1 = compute_net_value_KRW(**args)
    net2, b2 = compute_net_value_KRW(**args)
    assert net1 == net2
    assert b1.model_dump() == b2.model_dump()

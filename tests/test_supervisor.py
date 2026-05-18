"""Supervisor 협상 검증 (ADR v2 Decision 1)."""

from __future__ import annotations

import pytest

from src.orchestration.agents.base import AgentOutput
from src.orchestration.schema import (
    EquipmentAgentOutput,
    EquipmentNumeric,
    ProductionAgentOutput,
    ProductionNumeric,
    QualityAgentOutput,
    QualityNumeric,
    SafetyAgentOutput,
    SafetyNumeric,
)
from src.orchestration.supervisor import Supervisor, SupervisorConfig


# ── mock agents ────────────────────────────────────────────────


class _MockAgent:
    """invoke() 시 미리 정의된 Pydantic output 을 반환."""

    def __init__(self, outputs_by_action: dict[str, object]) -> None:
        self._outputs = outputs_by_action

    def invoke(self, user_prompt: str, context: dict | None = None) -> AgentOutput:
        action_id = self._extract_action(user_prompt)
        parsed = self._outputs[action_id]
        return AgentOutput(raw={}, parsed=parsed)

    @staticmethod
    def _extract_action(prompt: str) -> str:
        start = prompt.find("<candidate_action>") + len("<candidate_action>")
        end = prompt.find("</candidate_action>")
        return prompt[start:end].strip()


def _build_quality(action: str, defect_prob: float = 0.1) -> QualityAgentOutput:
    return QualityAgentOutput(
        numeric=QualityNumeric(defect_prob=defect_prob, top_failure_type="NONE"),
        narrative_kr=f"action {action} 결함 확률 {defect_prob}",
    )


def _build_safety(action: str, estop: bool = False, prob: float = 0.0) -> SafetyAgentOutput:
    return SafetyAgentOutput(
        numeric=SafetyNumeric(sop_violation=estop, estop_required=estop, safety_violation_prob=prob),
        narrative_kr=f"action {action} estop={estop}",
    )


def _build_equipment(action: str, rul: float = 100.0) -> EquipmentAgentOutput:
    return EquipmentAgentOutput(
        numeric=EquipmentNumeric(rul_hours=rul, isolation_forest_score=-0.1),
        narrative_kr=f"action {action} rul={rul}",
    )


def _build_production(action: str, uph: float = 247.0) -> ProductionAgentOutput:
    return ProductionAgentOutput(
        numeric=ProductionNumeric(throughput_uph=uph, schedule_feasible=True, lp_solution_id="lp_t"),
        narrative_kr=f"action {action} uph={uph}",
    )


# ── tests ──────────────────────────────────────────────────────


def test_negotiate_two_actions_picks_higher_throughput():
    """동일 defect/safety/rul → throughput 큰 action 채택."""
    actions = ["continue", "halt"]
    sup = Supervisor(
        quality_agent=_MockAgent({a: _build_quality(a) for a in actions}),
        safety_agent=_MockAgent({a: _build_safety(a) for a in actions}),
        equipment_agent=_MockAgent({a: _build_equipment(a) for a in actions}),
        production_agent=_MockAgent({
            "continue": _build_production("continue", uph=247.0),
            "halt": _build_production("halt", uph=0.0),
        }),
        config=SupervisorConfig(),
    )
    out = sup.negotiate({"robot_id": "ROBOT-00018"}, actions)
    assert out.decision.action_id == "continue"
    assert out.decision.net_value_KRW > 0
    assert out.decision.alternatives[0].action_id == "halt"
    assert out.decision.alternatives[0].rank == 2


def test_negotiate_safety_hard_block():
    """estop_required=True 인 action 은 net_value=-inf → 후순위."""
    actions = ["risky", "safe"]
    sup = Supervisor(
        quality_agent=_MockAgent({a: _build_quality(a) for a in actions}),
        safety_agent=_MockAgent({
            "risky": _build_safety("risky", estop=True, prob=1.0),
            "safe": _build_safety("safe", estop=False, prob=0.0),
        }),
        equipment_agent=_MockAgent({a: _build_equipment(a) for a in actions}),
        production_agent=_MockAgent({a: _build_production(a) for a in actions}),
    )
    out = sup.negotiate({"robot_id": "R-1"}, actions)
    assert out.decision.action_id == "safe"
    assert out.decision.alternatives[0].action_id == "risky"


def test_negotiate_rationale_contains_net_value():
    sup = Supervisor(
        quality_agent=_MockAgent({a: _build_quality(a) for a in ["a", "b"]}),
        safety_agent=_MockAgent({a: _build_safety(a) for a in ["a", "b"]}),
        equipment_agent=_MockAgent({a: _build_equipment(a) for a in ["a", "b"]}),
        production_agent=_MockAgent({
            "a": _build_production("a", uph=300.0),
            "b": _build_production("b", uph=200.0),
        }),
    )
    out = sup.negotiate({}, ["a", "b"])
    assert "net_value" in out.decision.rationale_kr or "₩" in out.decision.rationale_kr


def test_negotiate_min_two_actions_required():
    sup = Supervisor(
        quality_agent=_MockAgent({}),
        safety_agent=_MockAgent({}),
        equipment_agent=_MockAgent({}),
        production_agent=_MockAgent({}),
    )
    with pytest.raises(ValueError):
        sup.negotiate({}, ["onlyone"])


def test_negotiate_tradeoff_breakdown_present():
    sup = Supervisor(
        quality_agent=_MockAgent({a: _build_quality(a, defect_prob=0.5) for a in ["a", "b"]}),
        safety_agent=_MockAgent({a: _build_safety(a, prob=0.05) for a in ["a", "b"]}),
        equipment_agent=_MockAgent({a: _build_equipment(a, rul=2.0) for a in ["a", "b"]}),
        production_agent=_MockAgent({a: _build_production(a) for a in ["a", "b"]}),
    )
    out = sup.negotiate({}, ["a", "b"])
    bd = out.decision.tradeoff_breakdown
    # safety_loss 가 정확히 0 이 아니어야 (prob=0.05)
    assert bd.safety_loss_KRW < 0
    # rul_loss 가 음수 (rul=2 < horizon=4)
    assert bd.rul_loss_KRW < 0
    # throughput_gain 양수
    assert bd.throughput_gain_KRW > 0


def test_negotiate_config_alpha_beta_gamma():
    """β 큰 가중치 → safety_loss 더 크게 → safety 0인 action 우월."""
    actions = ["risky_low_safety", "safe"]
    sup = Supervisor(
        quality_agent=_MockAgent({a: _build_quality(a) for a in actions}),
        safety_agent=_MockAgent({
            "risky_low_safety": _build_safety("risky_low_safety", prob=0.1, estop=False),
            "safe": _build_safety("safe", prob=0.0, estop=False),
        }),
        equipment_agent=_MockAgent({a: _build_equipment(a) for a in actions}),
        production_agent=_MockAgent({
            "risky_low_safety": _build_production("risky_low_safety", uph=300.0),
            "safe": _build_production("safe", uph=200.0),
        }),
        config=SupervisorConfig(beta=10.0),  # β=10 → safety_loss 10배
    )
    out = sup.negotiate({}, actions)
    # β=10 이면 safety_violation 의 10배 cost → risky 가 더 손해.
    assert out.decision.action_id == "safe"

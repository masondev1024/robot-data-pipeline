"""PRISM 4 Agent + Supervisor Pydantic schema (ADR v2 Section 3, A1).

Schema freeze: D-3 (2026-05-19) 끝.
numeric/narrative_kr 이중 구조 — numeric 만 Supervisor 수식에 사용, narrative_kr 은 화면 노출.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FailureType = Literal["NONE", "TWF", "HDF", "PWF", "OSF", "RNF"]


class QualityNumeric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    defect_prob: float = Field(..., ge=0.0, le=1.0)
    top_failure_type: FailureType


class QualityAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numeric: QualityNumeric
    narrative_kr: str = Field(..., max_length=300)


class SafetyNumeric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sop_violation: bool
    estop_required: bool
    safety_violation_prob: float = Field(..., ge=0.0, le=1.0)


class SafetyAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numeric: SafetyNumeric
    narrative_kr: str = Field(..., max_length=300)


class EquipmentNumeric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rul_hours: float = Field(..., ge=0.0)
    isolation_forest_score: float = Field(..., ge=-1.0, le=1.0)


class EquipmentAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numeric: EquipmentNumeric
    narrative_kr: str = Field(..., max_length=300)


class ProductionNumeric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    throughput_uph: float = Field(..., ge=0.0)
    schedule_feasible: bool
    lp_solution_id: str


class ProductionAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numeric: ProductionNumeric
    narrative_kr: str = Field(..., max_length=300)


class CandidateAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str
    quality: QualityAgentOutput
    safety: SafetyAgentOutput
    equipment: EquipmentAgentOutput
    production: ProductionAgentOutput


class SupervisorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    horizon_h: int = Field(..., ge=1, le=72)
    candidate_actions: list[CandidateAction] = Field(..., min_length=2, max_length=5)


class TradeoffBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")
    throughput_gain_KRW: float
    defect_loss_KRW: float
    safety_loss_KRW: float
    rul_loss_KRW: float


class AlternativeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str
    net_value_KRW: float
    rank: int = Field(..., ge=1, le=5)


class SupervisorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str
    net_value_KRW: float
    alternatives: list[AlternativeAction] = Field(..., max_length=4)
    rationale_kr: str = Field(..., max_length=300)
    tradeoff_breakdown: TradeoffBreakdown


class SupervisorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: SupervisorDecision


def compute_net_value_KRW(
    quality: QualityAgentOutput,
    safety: SafetyAgentOutput,
    equipment: EquipmentAgentOutput,
    production: ProductionAgentOutput,
    *,
    alpha: float = 1.0,
    beta: float = 1.0,
    gamma: float = 1.0,
    horizon_h: int = 4,
    unit_revenue_KRW: float = 18_000.0,
    unit_defect_cost_KRW: float = 50_000.0,
    safety_violation_KRW: float = 100_000_000.0,
    rul_hour_cost_KRW: float = 25_000.0,
) -> tuple[float, TradeoffBreakdown]:
    """Supervisor net_value (ADR v2 Decision 1).

    net_value_KRW = throughput_gain - α·defect_loss - β·safety_loss - γ·rul_loss

    β default 는 사이드바 slider 의 cost_safety_violation 노출 대상 (Synthesis 1).
    """
    throughput_gain = production.numeric.throughput_uph * horizon_h * unit_revenue_KRW
    defect_loss = quality.numeric.defect_prob * unit_defect_cost_KRW * production.numeric.throughput_uph * horizon_h
    safety_loss = safety.numeric.safety_violation_prob * safety_violation_KRW
    rul_loss = max(0.0, horizon_h - equipment.numeric.rul_hours) * rul_hour_cost_KRW

    breakdown = TradeoffBreakdown(
        throughput_gain_KRW=throughput_gain,
        defect_loss_KRW=-alpha * defect_loss,
        safety_loss_KRW=-beta * safety_loss,
        rul_loss_KRW=-gamma * rul_loss,
    )
    net = (
        breakdown.throughput_gain_KRW
        + breakdown.defect_loss_KRW
        + breakdown.safety_loss_KRW
        + breakdown.rul_loss_KRW
    )
    return net, breakdown

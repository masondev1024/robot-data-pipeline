"""PRISM Supervisor — 4 Domain Agent fan-out + net_value 협상 (ADR v2 Decision 1).

흐름:
    candidate_actions (e.g., ["continue", "halt", "schedule_maintenance"]) 각각에 대해
        ├─ Quality Agent  → QualityAgentOutput
        ├─ Safety Agent   → SafetyAgentOutput
        ├─ Equipment Agent → EquipmentAgentOutput
        └─ Production Agent → ProductionAgentOutput
        → compute_net_value_KRW(α, β, γ) → (net_value_KRW, breakdown)
    argmax(net_value_KRW) → SupervisorOutput.decision

α/β/γ 는 Streamlit 사이드바 slider 노출 (Synthesis 1 — Decision 1 의 Option B 부분 흡수).

system_prompt 는 자리표시자. D-3 새벽 사용자 + /ccg 합의 후 fill.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from src.orchestration.agents.base import BaseAgent
from src.orchestration.agents.equipment import EquipmentAgent
from src.orchestration.agents.production import ProductionAgent
from src.orchestration.agents.quality import QualityAgent
from src.orchestration.agents.safety import SafetyAgent
from src.orchestration.schema import (
    AlternativeAction,
    CandidateAction,
    SupervisorDecision,
    SupervisorOutput,
    TradeoffBreakdown,
    compute_net_value_KRW,
)


SUPERVISOR_SYSTEM_PROMPT = """\
너는 PRISM 의 **Supervisor Agent** 다 (Bedrock Sonnet).

4 Domain Agent (Quality / Safety / Equipment / Production) 의 출력을 받아
net_value_KRW 가 최대인 action 을 선택한다. 안전 위반 (estop_required=True)
은 net_value 와 무관하게 hard-block 한다.

[TODO: D-3 새벽 사용자 + /ccg 합의 후 fill — 협상 narrative 톤, KRW
단위 설명, 차이 ⩾10만원 시 강한 권고, alternatives 표시 룰]

JSON output (`SupervisorOutput` Pydantic 검증 통과 필수):
{
  "decision": {
    "action_id": "<chosen>",
    "net_value_KRW": <float>,
    "alternatives": [{"action_id": ..., "net_value_KRW": ..., "rank": 2}],
    "rationale_kr": "<300자 한국어 markdown>",
    "tradeoff_breakdown": {
        "throughput_gain_KRW": <float>,
        "defect_loss_KRW": <float>,
        "safety_loss_KRW": <float>,
        "rul_loss_KRW": <float>
    }
  }
}
"""


@dataclass
class SupervisorConfig:
    """협상 가중치 (Streamlit 사이드바 slider 로 노출, Synthesis 1)."""

    alpha: float = 1.0   # defect_loss 가중치
    beta: float = 1.0    # safety_loss 가중치 (default 1e8 KRW × β)
    gamma: float = 1.0   # rul_loss 가중치
    horizon_h: int = 4


class Supervisor:
    """4 Agent fan-out + net_value argmax + SupervisorOutput 조립.

    Dependency injection 으로 4 Agent 객체 주입 — 테스트 시 mock 가능.
    """

    def __init__(
        self,
        quality_agent: BaseAgent | None = None,
        safety_agent: BaseAgent | None = None,
        equipment_agent: BaseAgent | None = None,
        production_agent: BaseAgent | None = None,
        config: SupervisorConfig | None = None,
    ) -> None:
        self.quality = quality_agent or QualityAgent()
        self.safety = safety_agent or SafetyAgent()
        self.equipment = equipment_agent or EquipmentAgent()
        self.production = production_agent or ProductionAgent()
        self.config = config or SupervisorConfig()
        self.model_id = os.environ.get(
            "PRISM_SUPERVISOR_MODEL",
            "anthropic.claude-sonnet-4-6-20250513-v1:0",
        )

    def _fan_out(self, action_id: str, scenario_context: dict) -> CandidateAction:
        """단일 action 에 대해 4 Agent invoke → CandidateAction 조립."""
        user_prompt = self._build_user_prompt(action_id, scenario_context)

        q = self.quality.invoke(user_prompt, context=scenario_context)
        s = self.safety.invoke(user_prompt, context=scenario_context)
        e = self.equipment.invoke(user_prompt, context=scenario_context)
        p = self.production.invoke(user_prompt, context=scenario_context)

        return CandidateAction(
            action_id=action_id,
            quality=q.parsed,
            safety=s.parsed,
            equipment=e.parsed,
            production=p.parsed,
        )

    @staticmethod
    def _build_user_prompt(action_id: str, scenario_context: dict) -> str:
        """4 Agent 가 동일하게 받는 user_prompt. 도메인 prompt fill 후 enrich 예정."""
        return (
            f"<scenario>\n{scenario_context}\n</scenario>\n"
            f"<candidate_action>{action_id}</candidate_action>\n"
            "위 시나리오에서 candidate_action 을 채택했을 때의 도메인 numeric + narrative_kr 을 JSON 으로 반환하라."
        )

    def negotiate(
        self,
        scenario_context: dict,
        candidate_actions: list[str],
    ) -> SupervisorOutput:
        """4 Agent fan-out + net_value 산정 + argmax → SupervisorOutput.

        - safety.numeric.estop_required=True 인 action 은 hard-block (net_value = -inf).
        - 가장 net_value 큰 action 이 decision. 나머지 = alternatives (rank 2~).
        """
        if len(candidate_actions) < 2:
            raise ValueError("candidate_actions 는 ≥2 필요 (Pydantic SupervisorInput 제약)")

        scored: list[tuple[CandidateAction, float, TradeoffBreakdown, bool]] = []
        for action_id in candidate_actions:
            candidate = self._fan_out(action_id, scenario_context)
            hard_block = candidate.safety.numeric.estop_required
            if hard_block:
                # hard-block: net_value 최소화. tradeoff 는 그래도 산정 (rationale 용)
                _, breakdown = compute_net_value_KRW(
                    candidate.quality, candidate.safety, candidate.equipment, candidate.production,
                    alpha=self.config.alpha, beta=self.config.beta, gamma=self.config.gamma,
                    horizon_h=self.config.horizon_h,
                )
                net = float("-inf")
            else:
                net, breakdown = compute_net_value_KRW(
                    candidate.quality, candidate.safety, candidate.equipment, candidate.production,
                    alpha=self.config.alpha, beta=self.config.beta, gamma=self.config.gamma,
                    horizon_h=self.config.horizon_h,
                )
            scored.append((candidate, net, breakdown, hard_block))

        # argmax. hard-block 만 있으면 첫 번째를 임시 선택 + rationale 명시.
        scored.sort(key=lambda x: x[1], reverse=True)
        best, best_net, best_break, best_block = scored[0]

        alternatives: list[AlternativeAction] = []
        for rank, (cand, net, _, _) in enumerate(scored[1:5], start=2):
            alternatives.append(AlternativeAction(
                action_id=cand.action_id,
                net_value_KRW=net if net != float("-inf") else -1e15,
                rank=rank,
            ))

        rationale = self._build_rationale(best, best_net, best_break, best_block, scored)

        decision = SupervisorDecision(
            action_id=best.action_id,
            net_value_KRW=best_net if best_net != float("-inf") else -1e15,
            alternatives=alternatives,
            rationale_kr=rationale,
            tradeoff_breakdown=best_break,
        )
        return SupervisorOutput(decision=decision)

    @staticmethod
    def _build_rationale(
        best: CandidateAction,
        best_net: float,
        breakdown: TradeoffBreakdown,
        hard_block: bool,
        scored: list[tuple[CandidateAction, float, TradeoffBreakdown, bool]],
    ) -> str:
        """간결한 한국어 rationale (≤300자). 도메인 prompt fill 후 LLM 으로 대체 가능."""
        if hard_block:
            return (
                f"⚠️ 모든 후보가 안전 위반 (estop_required). 임시 선택: {best.action_id}. "
                f"운영자 즉시 개입 필요."
            )
        runner_up_net = scored[1][1] if len(scored) > 1 else 0.0
        delta = best_net - runner_up_net
        return (
            f"{best.action_id} 채택 — net_value ₩{best_net:,.0f} "
            f"(2순위 대비 +₩{delta:,.0f}). throughput_gain ₩{breakdown.throughput_gain_KRW:,.0f}, "
            f"defect ₩{breakdown.defect_loss_KRW:,.0f}, safety ₩{breakdown.safety_loss_KRW:,.0f}."
        )[:300]

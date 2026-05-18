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
**Single-Scalar Net Value (KRW)** 가 최대인 action 을 선택한다.

## 협상 수식 (ADR v2 Decision 1)
```
net_value_KRW = throughput_gain_KRW
              − α × defect_loss_KRW     (Quality 출력 기반)
              − β × safety_loss_KRW     (Safety 출력 기반, β default=1.0 × 1억 KRW)
              − γ × rul_loss_KRW        (Equipment 출력 기반)
```
- α/β/γ: Streamlit 사이드바 slider (default 1.0). β 가 가장 민감 (1억 KRW × prob).
- horizon_h: 기본 4h (사이드바 노출 안 함, ADR Section 5 Pre-mortem C)

## Hard-block 룰 (안전 우선)
- **safety.numeric.estop_required = True** → 해당 action 의 net_value = −∞ (선택 불가)
- 모든 candidate 가 estop_required=True 면 첫 번째 임시 선택 + rationale_kr 에 "⚠️ 운영자 즉시 개입 필요" 명시

## 추천 강도 (rationale_kr 표현 룰)
- |net_value(1위) − net_value(2위)| ≥ **100,000 KRW (10만원)** → "**강한 권고**: {action} 채택 — net_value ₩X (2순위 대비 +₩Δ)"
- < 10만원 → "유보적 권고, 대안 검토 권장"

## Alternatives 표시
- 1위 = decision.action_id
- 2~5위 = alternatives (rank 2~5), 각 net_value_KRW 명시
- hard-block 된 action 도 alternatives 에 포함 (net_value = -1e15 로 표현)

## 비용 상수 (project_memory_add_directive 4일 동결)
- unit_revenue = **180,000 KRW** / UPH·h
- unit_defect_cost = **50,000 KRW** / 결함
- safety_violation = **100,000,000 KRW (1억)** ← 무조건 halt 유도 설계
- rul_hour_cost = **25,000 KRW** / 부족 h

## 출력 (반드시 JSON 만, schema.SupervisorOutput Pydantic 검증 통과)
{
  "decision": {
    "action_id": "<chosen action_id>",
    "net_value_KRW": <float>,
    "alternatives": [
      {"action_id": "<...>", "net_value_KRW": <float>, "rank": 2}
    ],
    "rationale_kr": "<≤300자 한국어 markdown. 형식: '{action} 채택 — net_value ₩X (2순위 대비 +₩Δ). throughput_gain ₩A, defect ₩-B, safety ₩-C, rul ₩-D.'>",
    "tradeoff_breakdown": {
      "throughput_gain_KRW": <float (양수)>,
      "defect_loss_KRW": <float (음수)>,
      "safety_loss_KRW": <float (음수)>,
      "rul_loss_KRW": <float (음수)>
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

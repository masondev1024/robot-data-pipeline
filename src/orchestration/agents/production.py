"""PRISM Production Agent — PuLP 스케줄링 기반 throughput + schedule feasibility 추정."""

from __future__ import annotations

import os

from pydantic import BaseModel

from src.orchestration.schema import ProductionAgentOutput
from src.orchestration.agents.base import BaseAgent

SYSTEM_PROMPT = """\
너는 PRISM 의 **생산 Agent (Production)** 다 (Bedrock Haiku).
PuLP LP 솔버 결과와 센서 컨텍스트를 바탕으로 시간당 생산량 (UPH),
스케줄 실행 가능 여부, LP solution ID 를 출력한다.

## 입력
센서 reading JSON + candidate_action (예: "continue", "halt",
"schedule_maintenance", "throttle_50pct") + (선택) horizon_h (기본 4h).

## 도메인 룰
UPH (Units Per Hour):
- 표준 라인 정상 UPH ≈ **247** (계획 capacity)
- 부하 감속 (throttle) 시 UPH × throttle_ratio
- halt / estop action → UPH = 0
- schedule_maintenance → 해당 horizon 동안 UPH = 0, 이후 회복

LP feasibility (PuLP 결과, 하드 룰):
- **UPH ≥ 200**: schedule_feasible = True (경제성 보장)
- **UPH < 200**: schedule_feasible = False (재계획 필요)

lp_solution_id 형식: `lp_<scenario_slug>_<short_hash>` (예: `lp_continue_a1b2`,
`lp_throttle50_c3d4`, `lp_halt_e5f6`)

## 출력 (반드시 JSON 만, schema.ProductionAgentOutput Pydantic 검증 통과)
{
  "numeric": {
    "throughput_uph": <float ≥ 0.0>,
    "schedule_feasible": <bool — UPH ≥ 200 ? true : false>,
    "lp_solution_id": "<str>"
  },
  "narrative_kr": "<≤300자 한국어 markdown. [ROBOT-XXXXX] citation 의무. UPH 산정 근거 + LP 결정>"
}

## 비용 컨텍스트 (Supervisor 협상 입력)
throughput_gain_KRW = throughput_uph × horizon_h × **180,000 KRW**
"""


class ProductionAgent(BaseAgent):
    """Production domain agent — throughput_uph + schedule_feasible + lp_solution_id."""

    @property
    def name(self) -> str:
        return "production"

    @property
    def model_id(self) -> str:
        return os.environ.get(
            "PRISM_HAIKU_MODEL",
            "anthropic.claude-haiku-4-5-20251001-v1:0",
        )

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    @property
    def tools(self) -> list[dict]:
        # [TODO: D-3 새벽 사용자 fill — PuLP scheduling tool 정의]
        return []

    @property
    def output_model(self) -> type[BaseModel]:
        return ProductionAgentOutput

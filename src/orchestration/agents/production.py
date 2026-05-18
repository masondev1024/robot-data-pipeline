"""PRISM Production Agent — PuLP 스케줄링 기반 throughput + schedule feasibility 추정."""

from __future__ import annotations

import os

from pydantic import BaseModel

from src.orchestration.schema import ProductionAgentOutput
from src.orchestration.agents.base import BaseAgent

SYSTEM_PROMPT = """
너는 PRISM 의 **생산 Agent** 다. PuLP LP 솔버 결과와 센서 컨텍스트를 바탕으로
시간당 생산량(UPH), 스케줄 실행 가능 여부, LP solution ID 를 출력한다.

[TODO: D-3 새벽 사용자 fill — PuLP 스케줄링 도메인 지식 + throughput 계산 기준 +
한국어 markdown 출력 + [ROBOT-XXXXX] citation 룰]

반드시 JSON output 만 반환:
{"numeric": {"throughput_uph": float, "schedule_feasible": bool, "lp_solution_id": str}, "narrative_kr": str}
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

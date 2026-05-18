"""PRISM Safety Agent — SOP 위반 여부 + E-stop 필요 여부 + 안전 위반 확률 추정."""

from __future__ import annotations

import os

from pydantic import BaseModel

from src.orchestration.schema import SafetyAgentOutput
from src.orchestration.agents.base import BaseAgent

SYSTEM_PROMPT = """
너는 PRISM 의 **안전 Agent** 다. 로봇/CNC 공정 센서 데이터로 SOP 위반,
E-stop 필요 여부, 안전 위반 확률을 판단한다.

[TODO: D-3 새벽 사용자 fill — SOP 규정 도메인 지식 + E-stop 트리거 조건 +
한국어 markdown 출력 + [ROBOT-XXXXX] citation 룰]

반드시 JSON output 만 반환:
{"numeric": {"sop_violation": bool, "estop_required": bool, "safety_violation_prob": float}, "narrative_kr": str}
"""


class SafetyAgent(BaseAgent):
    """Safety domain agent — SOP violation + estop_required + safety_violation_prob."""

    @property
    def name(self) -> str:
        return "safety"

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
        # [TODO: D-3 새벽 사용자 fill — safety tool 정의]
        return []

    @property
    def output_model(self) -> type[BaseModel]:
        return SafetyAgentOutput

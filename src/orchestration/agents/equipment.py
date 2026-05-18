"""PRISM Equipment Agent — RUL(잔여 수명) + Isolation Forest anomaly score 추정."""

from __future__ import annotations

import os

from pydantic import BaseModel

from src.orchestration.schema import EquipmentAgentOutput
from src.orchestration.agents.base import BaseAgent

SYSTEM_PROMPT = """
너는 PRISM 의 **설비 Agent** 다. 로봇/CNC 장비의 잔여 수명(RUL, 시간 단위)과
Isolation Forest anomaly score 를 추정한다.

[TODO: D-3 새벽 사용자 fill — RUL 추정 도메인 지식 + Isolation Forest score
해석 기준 + 한국어 markdown 출력 + [ROBOT-XXXXX] citation 룰]

반드시 JSON output 만 반환:
{"numeric": {"rul_hours": float, "isolation_forest_score": float}, "narrative_kr": str}
"""


class EquipmentAgent(BaseAgent):
    """Equipment domain agent — rul_hours + isolation_forest_score."""

    @property
    def name(self) -> str:
        return "equipment"

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
        # [TODO: D-3 새벽 사용자 fill — RUL / isolation forest tool 정의]
        return []

    @property
    def output_model(self) -> type[BaseModel]:
        return EquipmentAgentOutput

"""PRISM Quality Agent — CNC 공정 결함 확률 + AI4I 6-class failure type 추정."""

from __future__ import annotations

import os

from pydantic import BaseModel

from src.orchestration.schema import QualityAgentOutput
from src.orchestration.agents.base import BaseAgent

SYSTEM_PROMPT = """
너는 PRISM 의 **품질 Agent** 다. CNC 제조 공정의 결함 확률과 1순위 failure
type 을 추정한다.

[TODO: D-3 새벽 사용자 fill — AI4I 6-class (TWF/HDF/PWF/OSF/RNF/NONE) 도메인
지식 + 한국어 markdown 출력 + [ROBOT-XXXXX] citation 룰]

반드시 JSON output 만 반환:
{"numeric": {"defect_prob": float, "top_failure_type": str}, "narrative_kr": str}
"""


class QualityAgent(BaseAgent):
    """Quality domain agent — defect_prob + top_failure_type."""

    @property
    def name(self) -> str:
        return "quality"

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
        # [TODO: D-3 새벽 사용자 fill — predict_robot_failure 등 tool 정의]
        return []

    @property
    def output_model(self) -> type[BaseModel]:
        return QualityAgentOutput

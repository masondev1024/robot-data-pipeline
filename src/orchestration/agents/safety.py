"""PRISM Safety Agent — SOP 위반 여부 + E-stop 필요 여부 + 안전 위반 확률 추정."""

from __future__ import annotations

import os

from pydantic import BaseModel

from src.orchestration.schema import SafetyAgentOutput
from src.orchestration.agents.base import BaseAgent

SYSTEM_PROMPT = """\
너는 PRISM 의 **안전 Agent (Safety)** 다 (Bedrock Haiku).
로봇/CNC 공정 센서 데이터로 SOP 위반, E-stop 필요 여부, 안전 위반 확률을 판단한다.

## 입력
센서 reading JSON (motor_temp, vibration_xyz, coolant_temp, current,
spindle_rpm …) + candidate_action.

## 도메인 룰 (SOP / E-stop)
SOP 임계:
- **motor_temp > 100°C**: SOP 임계 진입 (경고)
- **motor_temp > 105°C**: SOP 명백 위반 → sop_violation=True
- **safety_violation_prob > 0.30**: 위반 확률 임계 → sop_violation=True

E-stop 발동 (estop_required=True):
- SOP 명백 위반 + 사고로 이어질 위험. 즉각 정지 필수.
- 예: motor_temp > 110°C OR vibration_xyz norm > 5σ OR safety_violation_prob > 0.50

## 출력 (반드시 JSON 만, schema.SafetyAgentOutput Pydantic 검증 통과)
{
  "numeric": {
    "sop_violation": <bool>,
    "estop_required": <bool>,
    "safety_violation_prob": <float ∈ [0.0, 1.0]>
  },
  "narrative_kr": "<≤300자 한국어 markdown. [ROBOT-XXXXX] citation 의무. 위반 센서·임계 명시>"
}

## 비용 컨텍스트 (Supervisor 협상 입력)
safety_loss_KRW = safety_violation_prob × **100,000,000 KRW (1억)** ← 압도적 패널티 = 무조건 halt 유도
estop_required=True → Supervisor hard-block (net_value = -∞)
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
            "apac.anthropic.claude-3-haiku-20240307-v1:0",
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

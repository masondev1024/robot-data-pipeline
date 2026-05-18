"""PRISM Equipment Agent — RUL(잔여 수명) + Isolation Forest anomaly score 추정."""

from __future__ import annotations

import os

from pydantic import BaseModel

from src.orchestration.schema import EquipmentAgentOutput
from src.orchestration.agents.base import BaseAgent

SYSTEM_PROMPT = """\
너는 PRISM 의 **설비 Agent (Equipment)** 다 (Bedrock Haiku).
로봇/CNC 장비의 잔여 수명 (RUL, h) 과 Isolation Forest anomaly score 를 추정한다.

## 입력
센서 reading JSON (tool_age, motor_temp_trend, vibration_xyz, thermal_drift …)
+ candidate_action + (선택) top_failure_type 힌트 (Quality Agent 동조 시).

## 도메인 룰 (RUL 추정)
top_failure_type 별 RUL 감가율:
- **HDF**: 1~2일 (24~48h) 내 고장 위험
- **TWF**: ~5일 (~120h)
- **PWF**: 즉시 정지 권고 (RUL → 0)
- **OSF**: 점진적 감소 (부하 재배분 시 회복 가능)
- **RNF**: 통계적 불확실, 보수적 추정 (50~100h)
- **NONE**: RUL 충분 (≥ horizon_h × 10)

RUL < horizon_h 시 시간당 **25,000 KRW** 손실 (Supervisor 협상 입력).

## Isolation Forest score 해석 (∈ [-1.0, 1.0])
- **[-1.0, -0.20]**: 명확한 anomaly (절대값 클수록 강한 비정상)
- **[-0.20, -0.10]**: 경계 영역 (검토 필요)
- **[-0.10, 0.10]**: 정상 범주
- **[0.10, 1.0]**: 매우 안정 정상

## 출력 (반드시 JSON 만, schema.EquipmentAgentOutput Pydantic 검증 통과)
{
  "numeric": {
    "rul_hours": <float ≥ 0.0>,
    "isolation_forest_score": <float ∈ [-1.0, 1.0]>
  },
  "narrative_kr": "<≤300자 한국어 markdown. [ROBOT-XXXXX] citation 의무. RUL 근거 + score 해석>"
}

## 비용 컨텍스트
rul_loss_KRW = max(0, horizon_h - rul_hours) × 25,000 KRW
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

"""PRISM Quality Agent — CNC 공정 결함 확률 + AI4I 6-class failure type 추정."""

from __future__ import annotations

import os

from pydantic import BaseModel

from src.orchestration.schema import QualityAgentOutput
from src.orchestration.agents.base import BaseAgent

SYSTEM_PROMPT = """\
너는 PRISM 의 **품질 Agent (Quality)** 다 (Bedrock Haiku).
CNC 제조 공정의 결함 확률 (defect_prob) 과 1순위 failure type 을 추정한다.

## 입력
센서 reading JSON (motor_temp, vibration_xyz, tool_age, spindle_rpm,
coolant_temp, thermal_drift, dimension_dev …) + candidate_action.

## 도메인 룰 (AI4I 2020 Predictive Maintenance, 6-class)
top_failure_type ∈ {"NONE", "TWF", "HDF", "PWF", "OSF", "RNF"}:
- **TWF** (Tool Wear Failure): 공구 마모. tool_age 누적 + dimension_dev 증가.
- **HDF** (Heat Dissipation Failure): 열 방출/냉각 실패. **max_motor_temp > 110°C** 시 위험 급증.
- **PWF** (Power Failure): 전력/전원 고장. spindle_rpm 불안정 + 전류 스파이크.
- **OSF** (Overstrain Failure): 과부하 누적. 부하 재배분 권장, 점진적 RUL 감소.
- **RNF** (Random Failures): 무작위성 고장. 통계적 outlier.
- **NONE**: 정상. defect_prob 낮음 + 모든 임계 안전 범위.

defect_prob 는 XGBoost (6-class softmax) 의 1−P(NONE) 으로 근사.

## 출력 (반드시 JSON 만, schema.QualityAgentOutput Pydantic 검증 통과)
{
  "numeric": {
    "defect_prob": <float ∈ [0.0, 1.0]>,
    "top_failure_type": "<NONE|TWF|HDF|PWF|OSF|RNF>"
  },
  "narrative_kr": "<≤300자 한국어 markdown. [ROBOT-XXXXX] citation 의무. 근거 센서 1-2개 + 1순위 failure type 명시>"
}

## 비용 컨텍스트 (Supervisor 협상 입력)
defect_loss_KRW = defect_prob × **50,000 KRW** × throughput_uph × horizon_h
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
            "apac.anthropic.claude-3-haiku-20240307-v1:0",
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

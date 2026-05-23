"""Predictor Protocol — production 5F robot failure 추론 라우팅.

Demo (PRISM_MODE=demo|live|dev)
    → DemoRobotPredictorUnavailable
    → 이유: PRISM demo 는 CNC 6F 시연용(`src/ml/local_predictor.py` LocalXGBoost6Class)
      이고 robot 5F 모델이 별도로 없음. demo 모드에서 robot failure 예측이 호출되면
      명시적 "not available in demo" 응답으로 graceful degradation.

Production (PRISM_MODE=production)
    → SageMakerPredictor
    → SageMaker endpoint `robot-failure-predictor` (5F robot telemetry)

Supervisor 자체는 ML 추론을 직접 호출하지 않음 — 4 agent 합의 + net_value 산정만 담당.
이 모듈은 FastAPI portal `/recommendation` (Task 3) 같은 caller 가 use case 별로 주입.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Predictor(Protocol):
    """Robot failure 추론 인터페이스 (5F robot telemetry)."""

    def predict_robot_failure(self, features: dict[str, Any]) -> dict[str, Any]:
        """5F features → failure 확률 분포 + recommended action.

        features keys (필수): avg_motor_temp, max_motor_temp, battery_drain,
            active_hours, max_temp_load_ratio. 'robot_id' optional (echo).

        Returns: 성공 시 distribution dict, 미가동 시 error dict.
            상세 셰이프는 sagemaker_predictor.SageMakerPredictor.predict_robot_failure
            docstring 참조.
        """
        ...


class DemoRobotPredictorUnavailable:
    """Demo 모드에서 robot 5F predictor 호출 시 graceful degradation.

    demo 는 CNC 6F (`src/ml/local_predictor.py`) 만 보유. robot 5F 는 production
    SageMaker endpoint 만 존재. error dict 형식은 SageMakerPredictor 의 미가동
    응답과 동일 (caller 가 동일 분기 코드 사용 가능).
    """

    def predict_robot_failure(self, features: dict[str, Any]) -> dict[str, Any]:
        return {
            "error": "predictor not deployed",
            "fallback_message": (
                "Robot 5F predictor 는 PRISM_MODE=production (SageMaker endpoint) "
                "에서만 사용 가능. 현재는 demo 모드이며 CNC 6F local_predictor "
                "(src/ml/local_predictor.py) 만 활성."
            ),
            "endpoint": None,
        }


def get_predictor(mode: str | None = None) -> Predictor:
    """PRISM_MODE → Predictor 라우팅 팩토리.

    Args:
        mode: 'demo' | 'live' | 'dev' | 'production'. None 이면 환경변수.

    Returns:
        production → SageMakerPredictor
        그 외      → DemoRobotPredictorUnavailable (graceful "not available")
    """
    mode = (mode or os.environ.get("PRISM_MODE", "demo")).lower()
    if mode == "production":
        from src.orchestration.sagemaker_predictor import SageMakerPredictor
        return SageMakerPredictor()
    return DemoRobotPredictorUnavailable()

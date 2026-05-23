"""SageMaker XGBoost endpoint 호출 wrapper (production 전용).

5-feature robot telemetry (avg_motor_temp, max_motor_temp, battery_drain,
active_hours, max_temp_load_ratio) → 6-class softprob 응답.

기존 `src/api/main.py:375-432` 의 `/api/predict` 로직을 재사용 가능한 형태로 추출.
이로써 FastAPI portal `/recommendation` (Task 3) + 다른 caller 가 동일 인터페이스 공유.

가드레일 (CLAUDE.md §1.F):
- EndpointNotFound → `{"error": "predictor not deployed"}` 명시 반환 (silent 실패 금지)
- 응답 파싱 JSON 배열 + CSV 양쪽 지원
"""

from __future__ import annotations

import json
import os
from typing import Any


FAILURE_TYPE_LABELS = ["NONE", "TWF", "HDF", "PWF", "OSF", "RNF"]

RECOMMENDED_ACTIONS = {
    "NONE": "정상 — 일상 점검 외 별도 조치 불필요",
    "TWF": "공구 마모(TWF) — 공구 마모도 측정 + 교체 주기 점검",
    "HDF": "방열 결함(HDF) — 방열핀/팬 청소·점검, 냉각 유로 확인",
    "PWF": "전력 결함(PWF) — 전력 공급부·인버터 점검, 전압/전류 모니터링",
    "OSF": "과부하(OSF) — 부하 한도 재설정, 토크 프로파일 검토",
    "RNF": "랜덤 결함(RNF) — 통신/배선/센서 연결 상태 종합 점검",
}

# 5F payload 순서 (train.py FEATURE_COLUMNS 와 정합 — 절대 순서 변경 금지)
ROBOT_FEATURE_ORDER = (
    "avg_motor_temp",
    "max_motor_temp",
    "battery_drain",
    "active_hours",
    "max_temp_load_ratio",
)


def parse_softprob_response(raw: str) -> list[float]:
    """SageMaker XGBoost multi:softprob 응답을 확률 리스트로 파싱.

    응답 형식 (CLAUDE.md §1.F 가드레일: JSON + CSV 양쪽 지원):
      - text/csv: "0.72,0.05,0.08,0.06,0.05,0.04"
      - JSON:     "[[0.72, 0.05, ...]]" 또는 "[0.72, 0.05, ...]"
    """
    raw = raw.strip()
    if raw.startswith("["):
        data = json.loads(raw)
        probs = data[0] if isinstance(data, list) and data and isinstance(data[0], list) else data
    else:
        first_line = raw.split("\n")[0]
        probs = [float(v) for v in first_line.split(",")]
    return [float(p) for p in probs]


def _risk_level(fault_probability: float) -> str:
    if fault_probability > 0.7:
        return "high"
    if fault_probability > 0.4:
        return "medium"
    return "low"


def _build_csv_payload(features: dict[str, Any]) -> str:
    """5F 순서대로 CSV 한 줄. 누락 키는 KeyError (호출 전 검증 필수)."""
    return ",".join(str(features[k]) for k in ROBOT_FEATURE_ORDER)


def _missing_keys(features: dict[str, Any]) -> list[str]:
    return [k for k in ROBOT_FEATURE_ORDER if k not in features]


class SageMakerPredictor:
    """Production 5F robot telemetry → SageMaker endpoint 호출.

    Demo 모드(`PRISM_MODE=demo`) 에서는 라우팅되지 않음 (DemoPredictorUnavailable
    이 대신 반환됨, predictor.get_predictor() 참조).
    """

    def __init__(self, endpoint_name: str | None = None) -> None:
        self.endpoint_name = endpoint_name or os.environ.get(
            "SAGEMAKER_ENDPOINT_NAME", "robot-failure-predictor"
        )

    def predict_robot_failure(self, features: dict[str, Any]) -> dict[str, Any]:
        """5F features → failure 확률 분포 + recommended action.

        Args:
            features: dict with keys avg_motor_temp, max_motor_temp,
                battery_drain, active_hours, max_temp_load_ratio.
                선택적 'robot_id' 는 응답에 echo.

        Returns:
            성공:
                {
                    "robot_id": str | None,
                    "failure_distribution": {label: prob},
                    "predicted_failure_type": str,
                    "fault_probability": float,
                    "risk_level": "high|medium|low",
                    "recommended_action": str,
                }
            endpoint 미가동:
                {"error": "predictor not deployed", "fallback_message": str,
                 "endpoint": str}
            응답 차원 불일치:
                {"error": "softprob_dim_mismatch", "got": int, "expected": int}
        """
        missing = _missing_keys(features)
        if missing:
            raise KeyError(f"missing features: {missing} (need {list(ROBOT_FEATURE_ORDER)})")

        body = _build_csv_payload(features)
        try:
            from src.common.aws import get_client
            client = get_client("sagemaker-runtime")
            response = client.invoke_endpoint(
                EndpointName=self.endpoint_name,
                ContentType="text/csv",
                Body=body,
            )
            raw = response["Body"].read().decode()
            probs = parse_softprob_response(raw)
        except Exception as exc:  # boto3 ClientError 포함
            return {
                "error": "predictor not deployed",
                "fallback_message": (
                    f"SageMaker endpoint '{self.endpoint_name}' 호출 실패: {exc}. "
                    f"비용 셧다운 또는 endpoint 미배포 상태일 수 있음."
                ),
                "endpoint": self.endpoint_name,
            }

        if len(probs) != len(FAILURE_TYPE_LABELS):
            return {
                "error": "softprob_dim_mismatch",
                "got": len(probs),
                "expected": len(FAILURE_TYPE_LABELS),
            }

        distribution = {label: round(p, 4) for label, p in zip(FAILURE_TYPE_LABELS, probs)}
        argmax_idx = max(range(len(probs)), key=lambda i: probs[i])
        predicted = FAILURE_TYPE_LABELS[argmax_idx]
        fault_prob = round(1.0 - distribution["NONE"], 4)

        return {
            "robot_id": features.get("robot_id"),
            "failure_distribution": distribution,
            "predicted_failure_type": predicted,
            "fault_probability": fault_prob,
            "risk_level": _risk_level(fault_prob),
            "recommended_action": RECOMMENDED_ACTIONS[predicted],
        }

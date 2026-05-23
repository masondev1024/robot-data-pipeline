"""SageMakerPredictor + Predictor factory 단위 테스트.

AWS 부팅 0회 — `src.common.aws.boto3.client` mock 으로 invoke_endpoint 응답 위조.
"""
from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from src.orchestration.predictor import (
    DemoRobotPredictorUnavailable,
    Predictor,
    get_predictor,
)
from src.orchestration.sagemaker_predictor import (
    FAILURE_TYPE_LABELS,
    RECOMMENDED_ACTIONS,
    ROBOT_FEATURE_ORDER,
    SageMakerPredictor,
    parse_softprob_response,
)


_VALID_FEATURES = {
    "robot_id": "ROBOT-00001",
    "avg_motor_temp": 75.2,
    "max_motor_temp": 92.5,
    "battery_drain": 70,
    "active_hours": 8,
    "max_temp_load_ratio": 1.23,
}


def _runtime_mock(body_bytes: bytes) -> MagicMock:
    """sagemaker-runtime invoke_endpoint mock."""
    client = MagicMock()
    body = MagicMock()
    body.read.return_value = body_bytes
    client.invoke_endpoint.return_value = {"Body": body}
    return client


# ── softprob 파싱 (CSV + JSON 양쪽) ----------------------------------------


def test_parse_softprob_csv():
    probs = parse_softprob_response("0.72,0.05,0.08,0.06,0.05,0.04")
    assert len(probs) == 6
    assert probs[0] == pytest.approx(0.72)


def test_parse_softprob_json_nested():
    probs = parse_softprob_response("[[0.5, 0.2, 0.1, 0.1, 0.05, 0.05]]")
    assert len(probs) == 6
    assert probs[0] == 0.5


def test_parse_softprob_json_flat():
    probs = parse_softprob_response("[0.3, 0.3, 0.2, 0.1, 0.05, 0.05]")
    assert probs[0] == 0.3
    assert probs[2] == 0.2


# ── SageMakerPredictor 정상 호출 -------------------------------------------


@patch("src.common.aws.boto3.client")
def test_predict_returns_distribution_and_top_label(mock_client):
    mock_client.return_value = _runtime_mock(b"0.1,0.6,0.1,0.1,0.05,0.05")
    pred = SageMakerPredictor()

    result = pred.predict_robot_failure(_VALID_FEATURES)

    assert result["robot_id"] == "ROBOT-00001"
    assert result["predicted_failure_type"] == "TWF"  # argmax index 1
    assert result["failure_distribution"]["TWF"] == 0.6
    assert result["fault_probability"] == pytest.approx(0.9, abs=1e-6)  # 1 - NONE
    assert result["risk_level"] == "high"
    assert result["recommended_action"] == RECOMMENDED_ACTIONS["TWF"]


@patch("src.common.aws.boto3.client")
def test_predict_passes_csv_payload_in_correct_order(mock_client):
    mock_client.return_value = _runtime_mock(b"1,0,0,0,0,0")
    pred = SageMakerPredictor()
    pred.predict_robot_failure(_VALID_FEATURES)

    call = mock_client.return_value.invoke_endpoint.call_args
    body = call.kwargs["Body"]
    parts = body.split(",")
    # 5F 순서: avg_motor_temp, max_motor_temp, battery_drain, active_hours, max_temp_load_ratio
    assert parts == ["75.2", "92.5", "70", "8", "1.23"]
    assert call.kwargs["ContentType"] == "text/csv"
    assert call.kwargs["EndpointName"] == "robot-failure-predictor"


@patch("src.common.aws.boto3.client")
def test_predict_uses_custom_endpoint_name(mock_client):
    mock_client.return_value = _runtime_mock(b"1,0,0,0,0,0")
    pred = SageMakerPredictor(endpoint_name="my-custom-endpoint")
    pred.predict_robot_failure(_VALID_FEATURES)
    call = mock_client.return_value.invoke_endpoint.call_args
    assert call.kwargs["EndpointName"] == "my-custom-endpoint"


@patch("src.common.aws.boto3.client")
def test_predict_env_endpoint_override(mock_client, monkeypatch):
    monkeypatch.setenv("SAGEMAKER_ENDPOINT_NAME", "env-endpoint")
    mock_client.return_value = _runtime_mock(b"1,0,0,0,0,0")
    pred = SageMakerPredictor()
    pred.predict_robot_failure(_VALID_FEATURES)
    call = mock_client.return_value.invoke_endpoint.call_args
    assert call.kwargs["EndpointName"] == "env-endpoint"


@patch("src.common.aws.boto3.client")
def test_predict_risk_level_medium(mock_client):
    mock_client.return_value = _runtime_mock(b"0.5,0.2,0.1,0.1,0.05,0.05")
    pred = SageMakerPredictor()
    result = pred.predict_robot_failure(_VALID_FEATURES)
    assert result["risk_level"] == "medium"


@patch("src.common.aws.boto3.client")
def test_predict_risk_level_low(mock_client):
    mock_client.return_value = _runtime_mock(b"0.9,0.02,0.02,0.02,0.02,0.02")
    pred = SageMakerPredictor()
    result = pred.predict_robot_failure(_VALID_FEATURES)
    assert result["risk_level"] == "low"


# ── 오류·예외 처리 ----------------------------------------------------------


@patch("src.common.aws.boto3.client")
def test_predict_endpoint_not_found_returns_error_dict(mock_client):
    client = MagicMock()
    client.invoke_endpoint.side_effect = Exception("endpoint not found")
    mock_client.return_value = client

    pred = SageMakerPredictor()
    result = pred.predict_robot_failure(_VALID_FEATURES)

    assert result["error"] == "predictor not deployed"
    assert "robot-failure-predictor" in result["fallback_message"]
    assert result["endpoint"] == "robot-failure-predictor"


@patch("src.common.aws.boto3.client")
def test_predict_dim_mismatch_returns_error_dict(mock_client):
    # 6-class 가 아닌 3개만 반환된 비정상 응답
    mock_client.return_value = _runtime_mock(b"0.5,0.3,0.2")
    pred = SageMakerPredictor()
    result = pred.predict_robot_failure(_VALID_FEATURES)
    assert result["error"] == "softprob_dim_mismatch"
    assert result["got"] == 3
    assert result["expected"] == 6


def test_predict_missing_features_raises_keyerror():
    pred = SageMakerPredictor()
    with pytest.raises(KeyError, match="missing features"):
        pred.predict_robot_failure({"robot_id": "R1", "avg_motor_temp": 70})


# ── 5F feature 순서 상수 ---------------------------------------------------


def test_robot_feature_order_constant():
    # train.py FEATURE_COLUMNS 와 정합 — 절대 순서 변경 금지
    assert ROBOT_FEATURE_ORDER == (
        "avg_motor_temp",
        "max_motor_temp",
        "battery_drain",
        "active_hours",
        "max_temp_load_ratio",
    )


def test_failure_type_labels_constant():
    assert FAILURE_TYPE_LABELS == ["NONE", "TWF", "HDF", "PWF", "OSF", "RNF"]


# ── get_predictor 라우팅 ---------------------------------------------------


def test_get_predictor_production_returns_sagemaker(monkeypatch):
    monkeypatch.setenv("PRISM_MODE", "production")
    pred = get_predictor()
    assert isinstance(pred, SageMakerPredictor)


def test_get_predictor_demo_returns_unavailable(monkeypatch):
    monkeypatch.setenv("PRISM_MODE", "demo")
    pred = get_predictor()
    assert isinstance(pred, DemoRobotPredictorUnavailable)


def test_get_predictor_explicit_mode_override():
    assert isinstance(get_predictor("production"), SageMakerPredictor)
    assert isinstance(get_predictor("demo"), DemoRobotPredictorUnavailable)
    assert isinstance(get_predictor("dev"), DemoRobotPredictorUnavailable)
    assert isinstance(get_predictor("live"), DemoRobotPredictorUnavailable)


def test_demo_predictor_returns_graceful_error():
    pred = DemoRobotPredictorUnavailable()
    result = pred.predict_robot_failure(_VALID_FEATURES)
    assert result["error"] == "predictor not deployed"
    assert "production" in result["fallback_message"]
    assert result["endpoint"] is None


def test_both_implementations_satisfy_protocol():
    assert isinstance(SageMakerPredictor(), Predictor)
    assert isinstance(DemoRobotPredictorUnavailable(), Predictor)

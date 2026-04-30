"""/api/predict multi-class (Task 8.3) 응답 검증."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _csv_response(probs: list[float]) -> MagicMock:
    """SageMaker text/csv 응답 mock — multi:softprob 6-class 확률."""
    mock_resp = MagicMock()
    mock_resp["Body"].read.return_value = ",".join(f"{p:.4f}" for p in probs).encode()
    return mock_resp


def _json_response(probs: list[float]) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp["Body"].read.return_value = str([probs]).encode()
    return mock_resp


_BASE_PAYLOAD = {
    "robot_id": "ROBOT-00001",
    "avg_motor_temp": 92.5,
    "max_motor_temp": 97.0,
    "battery_drain": 30,
    "active_hours": 8,
    "max_temp_load_ratio": 3.1,
}


@patch("src.api.main.sagemaker_runtime")
def test_predict_multiclass_high_risk_hdf(mock_sm):
    """HDF 우세 + NONE<0.3 → high risk + recommended_action=HDF."""
    from src.api.main import app

    # NONE=0.10, TWF=0.05, HDF=0.70, PWF=0.05, OSF=0.05, RNF=0.05
    mock_sm.invoke_endpoint.return_value = _csv_response([0.10, 0.05, 0.70, 0.05, 0.05, 0.05])
    client = TestClient(app)

    resp = client.post("/api/predict", json=_BASE_PAYLOAD)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["robot_id"] == "ROBOT-00001"
    assert data["predicted_failure_type"] == "HDF"
    assert data["risk_level"] == "high"
    assert data["fault_probability"] == 0.9
    assert "방열" in data["recommended_action"]
    assert set(data["failure_distribution"].keys()) == {"NONE", "TWF", "HDF", "PWF", "OSF", "RNF"}


@patch("src.api.main.sagemaker_runtime")
def test_predict_multiclass_medium_risk_osf(mock_sm):
    """NONE=0.35, OSF=0.45 (argmax), 나머지 0.05 each → fault_prob=0.65 → medium."""
    mock_sm.invoke_endpoint.return_value = _csv_response([0.35, 0.05, 0.05, 0.05, 0.45, 0.05])
    from src.api.main import app
    client = TestClient(app)
    resp = client.post("/api/predict", json={**_BASE_PAYLOAD, "robot_id": "ROBOT-00002"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["predicted_failure_type"] == "OSF"
    assert data["risk_level"] == "medium"
    assert "과부하" in data["recommended_action"] or "OSF" in data["recommended_action"]


@patch("src.api.main.sagemaker_runtime")
def test_predict_multiclass_low_risk_none(mock_sm):
    # NONE=0.85 우세 → low risk, predicted=NONE
    mock_sm.invoke_endpoint.return_value = _csv_response([0.85, 0.03, 0.03, 0.03, 0.03, 0.03])
    from src.api.main import app
    client = TestClient(app)
    resp = client.post("/api/predict", json={**_BASE_PAYLOAD, "robot_id": "ROBOT-00003"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["predicted_failure_type"] == "NONE"
    assert data["risk_level"] == "low"
    assert data["fault_probability"] == 0.15


@patch("src.api.main.sagemaker_runtime")
def test_predict_handles_json_response(mock_sm):
    """JSON 응답(`[[...]]`)도 정상 파싱."""
    mock_sm.invoke_endpoint.return_value = _json_response([0.10, 0.05, 0.05, 0.70, 0.05, 0.05])
    from src.api.main import app
    client = TestClient(app)
    resp = client.post("/api/predict", json=_BASE_PAYLOAD)
    assert resp.status_code == 200
    assert resp.json()["predicted_failure_type"] == "PWF"


@patch("src.api.main.sagemaker_runtime")
def test_predict_dimension_mismatch_returns_502(mock_sm):
    """6 미만 차원 응답 시 502 (binary 모델 잔재 가드)."""
    mock_sm.invoke_endpoint.return_value = _csv_response([0.32])
    from src.api.main import app
    client = TestClient(app)
    resp = client.post("/api/predict", json=_BASE_PAYLOAD)
    assert resp.status_code == 502
    assert "차원 불일치" in resp.json()["detail"]


@patch("src.api.main.sagemaker_runtime")
def test_predict_returns_robot_id_unchanged(mock_sm):
    mock_sm.invoke_endpoint.return_value = _csv_response([0.10, 0.05, 0.05, 0.05, 0.70, 0.05])
    from src.api.main import app
    client = TestClient(app)
    resp = client.post("/api/predict", json={**_BASE_PAYLOAD, "robot_id": "ROBOT-00042"})
    assert resp.status_code == 200
    assert resp.json()["robot_id"] == "ROBOT-00042"


@patch("src.api.main.sagemaker_runtime")
def test_predict_recommended_action_for_each_type(mock_sm):
    """6개 type 별 argmax 응답이 각각 올바른 recommended_action 매핑."""
    from src.api.main import app
    client = TestClient(app)

    cases = [
        ([0.85, 0.03, 0.03, 0.03, 0.03, 0.03], "NONE", "정상"),
        ([0.10, 0.70, 0.05, 0.05, 0.05, 0.05], "TWF", "공구"),
        ([0.10, 0.05, 0.70, 0.05, 0.05, 0.05], "HDF", "방열"),
        ([0.10, 0.05, 0.05, 0.70, 0.05, 0.05], "PWF", "전력"),
        ([0.10, 0.05, 0.05, 0.05, 0.70, 0.05], "OSF", "과부하"),
        ([0.10, 0.05, 0.05, 0.05, 0.05, 0.70], "RNF", "랜덤"),
    ]
    for probs, expected_type, expected_keyword in cases:
        mock_sm.invoke_endpoint.return_value = _csv_response(probs)
        resp = client.post("/api/predict", json=_BASE_PAYLOAD)
        assert resp.status_code == 200
        data = resp.json()
        assert data["predicted_failure_type"] == expected_type
        assert expected_keyword in data["recommended_action"], (
            f"{expected_type}: '{expected_keyword}' not in {data['recommended_action']}"
        )

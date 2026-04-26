from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _make_sagemaker_response(prob: float):
    mock_resp = MagicMock()
    mock_resp["Body"].read.return_value = str(prob).encode()
    return mock_resp


@patch("src.api.main.sagemaker_runtime")
def test_predict_high_risk(mock_sm):
    from src.api.main import app

    mock_sm.invoke_endpoint.return_value = _make_sagemaker_response(0.85)
    client = TestClient(app)

    resp = client.post(
        "/api/predict",
        json={
            "robot_id": "ROBOT-00001",
            "avg_motor_temp": 92.5,
            "max_motor_temp": 97.0,
            "battery_drain": 30,
            "active_hours": 8,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["robot_id"] == "ROBOT-00001"
    assert "failure_probability" in data
    assert data["failure_probability"] == 0.85
    assert data["risk_level"] == "high"


@patch("src.api.main.sagemaker_runtime")
def test_predict_medium_risk(mock_sm):
    from src.api.main import app

    mock_sm.invoke_endpoint.return_value = _make_sagemaker_response(0.55)
    client = TestClient(app)

    resp = client.post(
        "/api/predict",
        json={
            "robot_id": "ROBOT-00002",
            "avg_motor_temp": 75.0,
            "max_motor_temp": 80.0,
            "battery_drain": 20,
            "active_hours": 6,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["risk_level"] == "medium"


@patch("src.api.main.sagemaker_runtime")
def test_predict_low_risk(mock_sm):
    from src.api.main import app

    mock_sm.invoke_endpoint.return_value = _make_sagemaker_response(0.2)
    client = TestClient(app)

    resp = client.post(
        "/api/predict",
        json={
            "robot_id": "ROBOT-00003",
            "avg_motor_temp": 65.0,
            "max_motor_temp": 70.0,
            "battery_drain": 10,
            "active_hours": 4,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["risk_level"] == "low"
    assert data["failure_probability"] == 0.2


@patch("src.api.main.sagemaker_runtime")
def test_predict_returns_robot_id(mock_sm):
    from src.api.main import app

    mock_sm.invoke_endpoint.return_value = _make_sagemaker_response(0.3)
    client = TestClient(app)

    resp = client.post(
        "/api/predict",
        json={
            "robot_id": "ROBOT-00042",
            "avg_motor_temp": 68.0,
            "max_motor_temp": 72.0,
            "battery_drain": 15,
            "active_hours": 5,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["robot_id"] == "ROBOT-00042"

"""/api/recommendation 단위 테스트.

AWS 부팅 0회 — DataSource·Predictor·Supervisor 모두 mock 으로 주입.
모든 요청은 deterministic test credential 로 BasicAuth 경계를 통과한다.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_AUTH_HEADERS
from src.api.main import app
from src.orchestration.schema import (
    AlternativeAction,
    SupervisorDecision,
    SupervisorOutput,
    TradeoffBreakdown,
)


client = TestClient(app, headers=TEST_AUTH_HEADERS)


_GOLD_ROW = {
    "robot_id": "ROBOT-00001",
    "avg_motor_temp": 75.2,
    "max_motor_temp": 92.5,
    "battery_start": 100,
    "battery_end": 30,
    "battery_drain": 70,
    "active_hours": 8,
    "anomaly_record_count": 3,
    "max_temp_load_ratio": 1.23,
    "dominant_failure_type": "TWF",
}


def _build_supervisor_output(action: str = "halt", net_value: float = 1_500_000.0) -> SupervisorOutput:
    return SupervisorOutput(
        decision=SupervisorDecision(
            action_id=action,
            net_value_KRW=net_value,
            alternatives=[
                AlternativeAction(action_id="continue", net_value_KRW=800_000.0, rank=2),
                AlternativeAction(action_id="schedule_maintenance", net_value_KRW=600_000.0, rank=3),
            ],
            rationale_kr=f"{action} 채택 — net_value ₩{net_value:,.0f} (2순위 대비 +₩700,000).",
            tradeoff_breakdown=TradeoffBreakdown(
                throughput_gain_KRW=2_000_000.0,
                defect_loss_KRW=-200_000.0,
                safety_loss_KRW=-100_000.0,
                rul_loss_KRW=-200_000.0,
            ),
        )
    )


def _mock_data_source(rows: list[dict] | None = None) -> MagicMock:
    ds = MagicMock()
    ds.query_robot_daily_stats.return_value = pd.DataFrame(rows if rows is not None else [_GOLD_ROW])
    return ds


def _mock_predictor() -> MagicMock:
    pred = MagicMock()
    pred.predict_robot_failure.return_value = {
        "robot_id": "ROBOT-00001",
        "failure_distribution": {"NONE": 0.1, "TWF": 0.6, "HDF": 0.1, "PWF": 0.1, "OSF": 0.05, "RNF": 0.05},
        "predicted_failure_type": "TWF",
        "fault_probability": 0.9,
        "risk_level": "high",
        "recommended_action": "공구 마모(TWF) — 공구 마모도 측정 + 교체 주기 점검",
    }
    return pred


def _mock_supervisor_class(output: SupervisorOutput | None = None) -> MagicMock:
    sup_class = MagicMock()
    instance = MagicMock()
    instance.negotiate.return_value = output or _build_supervisor_output()
    sup_class.return_value = instance
    return sup_class


# ── 정상 경로 ----------------------------------------------------------------


def test_recommendation_happy_path_demo_mode():
    with patch("src.orchestration.datasource.get_data_source", return_value=_mock_data_source()), \
         patch("src.orchestration.predictor.get_predictor", return_value=_mock_predictor()), \
         patch("src.orchestration.supervisor.Supervisor", _mock_supervisor_class()):
        r = client.post("/api/recommendation", json={"dt": "2026-05-23"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"]["action_id"] == "halt"
    assert body["decision"]["net_value_KRW"] == 1_500_000.0
    assert len(body["decision"]["alternatives"]) == 2
    assert "throughput_gain_KRW" in body["decision"]["tradeoff_breakdown"]


def test_recommendation_filters_by_robot_id():
    rows = [
        {**_GOLD_ROW, "robot_id": "ROBOT-00001"},
        {**_GOLD_ROW, "robot_id": "ROBOT-00099", "avg_motor_temp": 60.0},
    ]
    ds = _mock_data_source(rows)
    sup_class = _mock_supervisor_class()
    with patch("src.orchestration.datasource.get_data_source", return_value=ds), \
         patch("src.orchestration.predictor.get_predictor", return_value=_mock_predictor()), \
         patch("src.orchestration.supervisor.Supervisor", sup_class):
        r = client.post(
            "/api/recommendation",
            json={"dt": "2026-05-23", "robot_id": "ROBOT-00099"},
        )

    assert r.status_code == 200, r.text
    # supervisor 가 받은 scenario_context 의 robot_data 가 99번이어야 함
    call_args = sup_class.return_value.negotiate.call_args
    scenario_context = call_args.args[0]
    assert scenario_context["robot_data"]["robot_id"] == "ROBOT-00099"
    assert scenario_context["robot_data"]["avg_motor_temp"] == 60.0


def test_recommendation_custom_candidate_actions_and_weights():
    sup_class = _mock_supervisor_class()
    with patch("src.orchestration.datasource.get_data_source", return_value=_mock_data_source()), \
         patch("src.orchestration.predictor.get_predictor", return_value=_mock_predictor()), \
         patch("src.orchestration.supervisor.Supervisor", sup_class):
        r = client.post(
            "/api/recommendation",
            json={
                "dt": "2026-05-23",
                "candidate_actions": ["throttle", "shutdown"],
                "alpha": 0.5, "beta": 2.0, "gamma": 1.5, "horizon_h": 8,
            },
        )

    assert r.status_code == 200, r.text
    # Supervisor 가 받은 candidate_actions 확인
    call_args = sup_class.return_value.negotiate.call_args
    assert call_args.args[1] == ["throttle", "shutdown"]
    # SupervisorConfig α/β/γ/horizon 가 전달됐는지
    sup_init_kwargs = sup_class.call_args.kwargs
    config = sup_init_kwargs["config"]
    assert config.alpha == 0.5
    assert config.beta == 2.0
    assert config.gamma == 1.5
    assert config.horizon_h == 8


def test_recommendation_includes_ml_prediction_in_context():
    sup_class = _mock_supervisor_class()
    pred = _mock_predictor()
    with patch("src.orchestration.datasource.get_data_source", return_value=_mock_data_source()), \
         patch("src.orchestration.predictor.get_predictor", return_value=pred), \
         patch("src.orchestration.supervisor.Supervisor", sup_class):
        r = client.post("/api/recommendation", json={"dt": "2026-05-23"})

    assert r.status_code == 200
    scenario_context = sup_class.return_value.negotiate.call_args.args[0]
    assert "ml_prediction" in scenario_context
    assert scenario_context["ml_prediction"]["predicted_failure_type"] == "TWF"
    # Predictor 가 5F + robot_id 로 호출됐는지
    pred_call = pred.predict_robot_failure.call_args.args[0]
    assert "avg_motor_temp" in pred_call
    assert "max_temp_load_ratio" in pred_call


# ── 입력 검증 (400) ---------------------------------------------------------


def test_recommendation_invalid_dt_format_returns_400():
    r = client.post("/api/recommendation", json={"dt": "2026/05/23"})
    assert r.status_code == 400
    assert "dt 형식" in r.json()["detail"]


def test_recommendation_too_few_candidates_returns_400():
    r = client.post(
        "/api/recommendation",
        json={"dt": "2026-05-23", "candidate_actions": ["only_one"]},
    )
    assert r.status_code == 400
    assert "최소 2개" in r.json()["detail"]


def test_recommendation_missing_dt_returns_422():
    # Pydantic 자동 검증 (필수 필드 누락)
    r = client.post("/api/recommendation", json={})
    assert r.status_code == 422


# ── 404 경로 ---------------------------------------------------------------


def test_recommendation_empty_partition_returns_404():
    ds = _mock_data_source(rows=[])
    with patch("src.orchestration.datasource.get_data_source", return_value=ds), \
         patch("src.orchestration.predictor.get_predictor", return_value=_mock_predictor()), \
         patch("src.orchestration.supervisor.Supervisor", _mock_supervisor_class()):
        r = client.post("/api/recommendation", json={"dt": "2026-05-23"})

    assert r.status_code == 404
    assert "데이터가 없습니다" in r.json()["detail"]


def test_recommendation_robot_not_found_returns_404():
    ds = _mock_data_source()  # only ROBOT-00001
    with patch("src.orchestration.datasource.get_data_source", return_value=ds), \
         patch("src.orchestration.predictor.get_predictor", return_value=_mock_predictor()), \
         patch("src.orchestration.supervisor.Supervisor", _mock_supervisor_class()):
        r = client.post(
            "/api/recommendation",
            json={"dt": "2026-05-23", "robot_id": "ROBOT-99999"},
        )

    assert r.status_code == 404
    assert "ROBOT-99999" in r.json()["detail"]


# ── 502 경로 (DataSource·Supervisor 실패) ----------------------------------


def test_recommendation_datasource_failure_returns_502():
    ds = MagicMock()
    ds.query_robot_daily_stats.side_effect = Exception("Athena timeout")
    with patch("src.orchestration.datasource.get_data_source", return_value=ds):
        r = client.post("/api/recommendation", json={"dt": "2026-05-23"})

    assert r.status_code == 502
    assert "DataSource 조회 실패" in r.json()["detail"]


def test_recommendation_supervisor_failure_returns_502():
    sup_class = MagicMock()
    instance = MagicMock()
    instance.negotiate.side_effect = Exception("Bedrock throttled")
    sup_class.return_value = instance

    with patch("src.orchestration.datasource.get_data_source", return_value=_mock_data_source()), \
         patch("src.orchestration.predictor.get_predictor", return_value=_mock_predictor()), \
         patch("src.orchestration.supervisor.Supervisor", sup_class):
        r = client.post("/api/recommendation", json={"dt": "2026-05-23"})

    assert r.status_code == 502
    assert "Supervisor 협의 실패" in r.json()["detail"]

"""Offline contract tests for the Airflow daily Bedrock report task."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest


pytest.importorskip("airflow")

import robot_daily_etl as etl


@pytest.fixture
def gold_rows():
    return [
        {
            "robot_id": "ROBOT-00001",
            "avg_motor_temp": "92.5",
            "max_motor_temp": "98.0",
            "battery_drain": "30",
            "active_hours": "8",
        },
        {
            "robot_id": "ROBOT-00002",
            "avg_motor_temp": "88.3",
            "max_motor_temp": "95.0",
            "battery_drain": "25",
            "active_hours": "7",
        },
    ]


@pytest.fixture
def report_mocks(monkeypatch, gold_rows):
    run_query = MagicMock(return_value="query-123")
    fetch_rows = MagicMock(return_value=gold_rows)
    invoke_claude = MagicMock(return_value="# 일별 정비 리포트")
    s3 = MagicMock()

    monkeypatch.setattr(etl, "_run_athena_query", run_query)
    monkeypatch.setattr(etl, "fetch_rows", fetch_rows)
    monkeypatch.setattr(etl, "invoke_claude", invoke_claude)
    monkeypatch.setattr(etl.boto3, "client", MagicMock(return_value=s3))
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    return run_query, fetch_rows, invoke_claude, s3


def test_bedrock_report_passes_gold_data_to_helper_and_writes_s3(report_mocks):
    run_query, fetch_rows, invoke_claude, s3 = report_mocks

    etl._bedrock_report(execution_date=datetime(2026, 4, 25))

    query = run_query.call_args.args[0]
    assert "WHERE dt = DATE '2026-04-25'" in query
    assert "LIMIT" in query
    fetch_rows.assert_called_once_with("query-123")

    prompt = invoke_claude.call_args.args[0]
    kwargs = invoke_claude.call_args.kwargs
    assert "ROBOT-00001" in prompt
    assert "avg_motor_temp" not in prompt
    assert "평균온도=92.5°C" in prompt
    assert "스마트 팩토리 정비반장" in kwargs["system"]
    assert kwargs == {
        "system": kwargs["system"],
        "max_tokens": 512,
        "model_id": "test-model",
        "cache_system": False,
    }

    s3.put_object.assert_called_once_with(
        Bucket=etl.S3_BUCKET,
        Key="reports/2026-04-25.txt",
        Body="# 일별 정비 리포트".encode("utf-8"),
    )


def test_bedrock_failure_fails_task_without_writing_report(report_mocks):
    _, _, invoke_claude, s3 = report_mocks
    invoke_claude.side_effect = RuntimeError("Bedrock unavailable")

    with pytest.raises(RuntimeError, match="Bedrock unavailable"):
        etl._bedrock_report(execution_date=datetime(2026, 4, 25))

    s3.put_object.assert_not_called()


def test_bedrock_report_task_is_between_gold_and_cache_refresh():
    task = etl.dag.get_task("bedrock_report")

    assert task.upstream_task_ids == {"silver_to_gold"}
    assert task.downstream_task_ids == {"cache_refresh"}


def test_daily_dag_contains_expected_tasks():
    assert {
        "quality_check",
        "bronze_to_silver",
        "silver_to_gold",
        "bedrock_report",
        "cache_refresh",
    } <= set(etl.dag.task_ids)

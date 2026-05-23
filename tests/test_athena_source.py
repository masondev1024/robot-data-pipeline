"""AthenaDataSource 단위 테스트.

AWS 부팅 0회 — `src.common.aws.boto3.client` 모킹 패턴 (`tests/api/test_status.py:46`
참조). Athena 응답 셰이프는 boto3 athena API 실제 응답 형식.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.orchestration.athena_source import (
    AthenaDataSource,
    _GOLD_COL_TYPES,
    _SILVER_COL_TYPES,
    DEFAULT_DATABASE,
    DEFAULT_WORKGROUP,
)


def _athena_mock(rows: list[list[str]]) -> MagicMock:
    """Athena boto3 client mock.

    rows[0] 는 header, rows[1:] 는 데이터. 모든 값은 VarCharValue 문자열.
    """
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "qid-test"}
    client.get_query_execution.return_value = {
        "QueryExecution": {"Status": {"State": "SUCCEEDED"}}
    }
    page = {
        "ResultSet": {
            "Rows": [
                {"Data": [{"VarCharValue": v} for v in row]}
                for row in rows
            ]
        }
    }
    paginator = MagicMock()
    paginator.paginate.return_value = iter([page])
    client.get_paginator.return_value = paginator
    return client


# ── factory & env -----------------------------------------------------------


def test_default_workgroup_and_database():
    ds = AthenaDataSource()
    assert ds.workgroup == DEFAULT_WORKGROUP
    assert ds.database == DEFAULT_DATABASE


def test_env_override(monkeypatch):
    monkeypatch.setenv("ATHENA_WORKGROUP", "custom-wg")
    monkeypatch.setenv("ATHENA_DATABASE", "custom_db")
    monkeypatch.setenv("ATHENA_OUTPUT_LOCATION", "s3://bucket/custom/")
    ds = AthenaDataSource()
    assert ds.workgroup == "custom-wg"
    assert ds.database == "custom_db"
    assert ds.output_location == "s3://bucket/custom/"


# ── query_robot_daily_stats -------------------------------------------------


@patch("src.common.aws.boto3.client")
def test_query_robot_daily_stats_returns_gold_schema(mock_client):
    header = list(_GOLD_COL_TYPES.keys())
    data = [
        ["ROBOT-00001", "75.2", "92.5", "100", "30", "70", "8", "3", "1.23", "TWF"],
        ["ROBOT-00002", "68.1", "85.0", "98", "55", "43", "7", "0", "1.24", "NONE"],
    ]
    mock_client.return_value = _athena_mock([header, *data])

    ds = AthenaDataSource()
    df = ds.query_robot_daily_stats("2026-05-23", limit=10)

    assert list(df.columns) == header
    assert len(df) == 2
    assert df.iloc[0]["robot_id"] == "ROBOT-00001"
    assert df.iloc[0]["avg_motor_temp"] == 75.2
    assert df.iloc[0]["battery_drain"] == 70
    assert df.iloc[1]["dominant_failure_type"] == "NONE"


@patch("src.common.aws.boto3.client")
def test_query_robot_daily_stats_partition_pruning_in_sql(mock_client):
    mock_client.return_value = _athena_mock([list(_GOLD_COL_TYPES.keys())])
    ds = AthenaDataSource()
    ds.query_robot_daily_stats("2026-05-23")
    sql = mock_client.return_value.start_query_execution.call_args.kwargs["QueryString"]
    assert "WHERE dt = DATE '2026-05-23'" in sql
    assert "gold_robot_daily_stats" in sql


@patch("src.common.aws.boto3.client")
def test_query_robot_daily_stats_empty_strings_become_none(mock_client):
    header = list(_GOLD_COL_TYPES.keys())
    data = [["ROBOT-00003", "", "92.5", "", "30", "70", "8", "0", "", "NONE"]]
    mock_client.return_value = _athena_mock([header, *data])

    ds = AthenaDataSource()
    df = ds.query_robot_daily_stats("2026-05-23")
    assert df.iloc[0]["avg_motor_temp"] is None
    assert df.iloc[0]["battery_start"] is None
    assert df.iloc[0]["max_temp_load_ratio"] is None
    assert df.iloc[0]["robot_id"] == "ROBOT-00003"


# ── query_robot_realtime ----------------------------------------------------


@patch("src.common.aws.boto3.client")
def test_query_robot_realtime_returns_silver_schema(mock_client):
    header = list(_SILVER_COL_TYPES.keys())
    data = [
        ["ROBOT-00001", "1.5", "2.3", "85", "42", "78.5", "2026-05-23T10:00:00Z", "NONE"],
    ]
    mock_client.return_value = _athena_mock([header, *data])

    ds = AthenaDataSource()
    df = ds.query_robot_realtime(limit=50)

    assert list(df.columns) == header
    assert df.iloc[0]["motor_temp"] == 78.5
    assert df.iloc[0]["battery_level"] == 85


@patch("src.common.aws.boto3.client")
def test_query_robot_realtime_uses_max_dt_fallback(mock_client):
    mock_client.return_value = _athena_mock([list(_SILVER_COL_TYPES.keys())])
    ds = AthenaDataSource()
    ds.query_robot_realtime(limit=10)
    sql = mock_client.return_value.start_query_execution.call_args.kwargs["QueryString"]
    assert "MAX(dt)" in sql
    assert "INTERVAL '7' DAY" in sql
    assert "silver_robot_telemetry" in sql


# ── CNC = NotImplementedError (영구) -----------------------------------------


def test_query_cnc_telemetry_not_implemented():
    ds = AthenaDataSource()
    with pytest.raises(NotImplementedError, match="CNC 는 PRISM demo 전용"):
        ds.query_cnc_telemetry()


def test_insert_cnc_row_not_implemented():
    ds = AthenaDataSource()
    with pytest.raises(NotImplementedError, match="production 적재는 KDS producer"):
        ds.insert_cnc_row({"machine_id": "CNC-01"})


# ── workgroup/database 가 boto3 호출에 전달되는지 ---------------------------


@patch("src.common.aws.boto3.client")
def test_workgroup_passed_to_athena_call(mock_client):
    mock_client.return_value = _athena_mock([list(_GOLD_COL_TYPES.keys())])
    ds = AthenaDataSource(workgroup="my-wg", database="my-db")
    ds.query_robot_daily_stats("2026-05-23")
    kwargs = mock_client.return_value.start_query_execution.call_args.kwargs
    assert kwargs["WorkGroup"] == "my-wg"
    assert kwargs["QueryExecutionContext"]["Database"] == "my-db"

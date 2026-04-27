"""ETL SQL 필터/멱등성 단위 테스트.

실 Athena 실행 없이 _run_athena_query를 mock으로 가로채서 생성된 SQL 문자열에
요구된 필터/컬럼이 포함되어 있는지 검증한다. 또한 멱등성 (s3 partition 삭제 →
INSERT) 호출 순서도 검증.
"""
from datetime import datetime
from unittest.mock import patch, MagicMock, call

import pytest

pytest.importorskip("airflow")

from robot_daily_etl import _bronze_to_silver, _silver_to_gold


def _ctx(year: int = 2026, month: int = 4, day: int = 27):
    return {"execution_date": datetime(year, month, day)}


# ── Bronze → Silver SQL 검증 ──────────────────────────────────────

@patch("robot_daily_etl._delete_s3_partition")
@patch("robot_daily_etl._run_athena_query")
def test_bronze_to_silver_filters_outliers(mock_run, mock_delete):
    """500도 이상 motor_temp는 WHERE 절에서 제외되어야 한다."""
    _bronze_to_silver(**_ctx())
    sql = mock_run.call_args[0][0]
    assert "motor_temp BETWEEN 0 AND 500" in sql


@patch("robot_daily_etl._delete_s3_partition")
@patch("robot_daily_etl._run_athena_query")
def test_bronze_to_silver_filters_null_robot_id(mock_run, mock_delete):
    """robot_id NULL은 제거되어야 한다."""
    _bronze_to_silver(**_ctx())
    sql = mock_run.call_args[0][0]
    assert "robot_id IS NOT NULL" in sql


@patch("robot_daily_etl._delete_s3_partition")
@patch("robot_daily_etl._run_athena_query")
def test_bronze_to_silver_battery_range(mock_run, mock_delete):
    """battery_level은 0~100 범위로 필터링되어야 한다."""
    _bronze_to_silver(**_ctx())
    sql = mock_run.call_args[0][0]
    assert "battery_level BETWEEN 0 AND 100" in sql


@patch("robot_daily_etl._delete_s3_partition")
@patch("robot_daily_etl._run_athena_query")
def test_bronze_to_silver_dedup_by_row_number(mock_run, mock_delete):
    """robot_id + timestamp 기준 중복 제거 (ROW_NUMBER) 포함."""
    _bronze_to_silver(**_ctx())
    sql = mock_run.call_args[0][0]
    assert "ROW_NUMBER() OVER" in sql
    assert "PARTITION BY robot_id, timestamp" in sql
    assert "WHERE rn = 1" in sql


@patch("robot_daily_etl._delete_s3_partition")
@patch("robot_daily_etl._run_athena_query")
def test_bronze_to_silver_uses_partition_keys(mock_run, mock_delete):
    """bronze WHERE 절은 year/month/day 파티션 키를 사용해야 한다 (dt 컬럼 X)."""
    _bronze_to_silver(**_ctx(2026, 4, 27))
    sql = mock_run.call_args[0][0]
    assert "year = 2026" in sql
    assert "month = 4" in sql
    assert "day = 27" in sql


# ── Silver → Gold SQL 검증 ────────────────────────────────────────

@patch("robot_daily_etl._delete_s3_partition")
@patch("robot_daily_etl._run_athena_query")
def test_silver_to_gold_active_hours_int_cast(mock_run, mock_delete):
    """active_hours는 INTEGER로 cast 되어야 한다 (gold DDL 정합성)."""
    _silver_to_gold(**_ctx())
    sql = mock_run.call_args[0][0]
    assert "AS active_hours" in sql
    assert "AS INTEGER" in sql


@patch("robot_daily_etl._delete_s3_partition")
@patch("robot_daily_etl._run_athena_query")
def test_silver_to_gold_no_stale_columns(mock_run, mock_delete):
    """gold INSERT에 더 이상 존재하지 않는 컬럼이 없어야 한다."""
    _silver_to_gold(**_ctx())
    sql = mock_run.call_args[0][0]
    assert "operation_ratio" not in sql
    assert "battery_drain_rate" not in sql


# ── 멱등성 (S3 파티션 사전 삭제) 검증 ────────────────────────────

@patch("robot_daily_etl._delete_s3_partition")
@patch("robot_daily_etl._run_athena_query")
def test_idempotent_silver_partition_deleted(mock_run, mock_delete):
    """_bronze_to_silver는 INSERT 전 silver/dt={dt}/ 파티션을 삭제해야 한다."""
    _bronze_to_silver(**_ctx(2026, 4, 27))
    mock_delete.assert_called_once_with("silver/dt=2026-04-27/")


@patch("robot_daily_etl._delete_s3_partition")
@patch("robot_daily_etl._run_athena_query")
def test_idempotent_gold_partition_deleted(mock_run, mock_delete):
    """_silver_to_gold는 INSERT 전 gold/dt={dt}/ 파티션을 삭제해야 한다."""
    _silver_to_gold(**_ctx(2026, 4, 27))
    mock_delete.assert_called_once_with("gold/dt=2026-04-27/")


@patch("robot_daily_etl._delete_s3_partition")
@patch("robot_daily_etl._run_athena_query")
def test_delete_called_before_insert(mock_run, mock_delete):
    """파티션 삭제가 INSERT 보다 먼저 호출되어야 한다."""
    parent = MagicMock()
    parent.attach_mock(mock_delete, "delete")
    parent.attach_mock(mock_run, "insert")

    _bronze_to_silver(**_ctx())

    # parent.mock_calls의 순서를 검증
    method_names = [c[0] for c in parent.mock_calls]
    assert method_names.index("delete") < method_names.index("insert")


# ── _delete_s3_partition 자체 검증 (S3 boto3 mock) ───────────────

@patch("robot_daily_etl.boto3.client")
def test_delete_s3_partition_calls_delete_objects(mock_boto):
    """_delete_s3_partition은 list_objects + delete_objects를 호출해야 한다."""
    from robot_daily_etl import _delete_s3_partition

    mock_s3 = MagicMock()
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [
        {"Contents": [{"Key": "silver/dt=2026-04-27/file1.parquet"}]},
    ]
    mock_s3.get_paginator.return_value = mock_paginator
    mock_boto.return_value = mock_s3

    deleted = _delete_s3_partition("silver/dt=2026-04-27/")

    assert deleted == 1
    mock_s3.delete_objects.assert_called_once()


@patch("robot_daily_etl.boto3.client")
def test_delete_s3_partition_handles_empty(mock_boto):
    """빈 파티션은 0건 반환, delete_objects 호출 안 함."""
    from robot_daily_etl import _delete_s3_partition

    mock_s3 = MagicMock()
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [{}]  # Contents 키 없음
    mock_s3.get_paginator.return_value = mock_paginator
    mock_boto.return_value = mock_s3

    deleted = _delete_s3_partition("silver/dt=2099-12-31/")

    assert deleted == 0
    mock_s3.delete_objects.assert_not_called()

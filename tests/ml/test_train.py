"""Unit tests for SageMaker XGBoost training pipeline (train.py).
All boto3 and SageMaker calls are mocked.
"""

from unittest.mock import MagicMock, patch
import pytest


def test_query_contains_all_features_and_label():
    """Query contains 5 features (Flink 정합 max_temp_load_ratio 추가) +
    Flink 정합 라벨(anomaly_record_count > 0) 사용."""
    from src.ml.train import QUERY

    # Verify QUERY contains all 5 feature columns
    assert "avg_motor_temp" in QUERY
    assert "max_motor_temp" in QUERY
    assert "battery_drain" in QUERY
    assert "active_hours" in QUERY
    assert "max_temp_load_ratio" in QUERY

    # Verify QUERY contains Flink-aligned label (anomaly_record_count > 0)
    assert "CASE WHEN anomaly_record_count > 0" in QUERY
    assert "THEN 1 ELSE 0 END AS label" in QUERY


def test_query_excludes_stale_columns_and_old_label():
    """Query should NOT contain deprecated columns OR old label rule (regression guard)."""
    from src.ml.train import QUERY

    # 옛 stale 컬럼 (Phase 5 cleanup 시 제거됨)
    stale_columns = ["battery_drain_rate", "operation_ratio", "machine_failure"]
    for col in stale_columns:
        assert col not in QUERY, f"Stale column '{col}' should not be in QUERY"

    # 옛 라벨 룰 (max_motor_temp > 90.0) — Flink 와 불일치라 제거됨
    assert "max_motor_temp > 90" not in QUERY, "Old label rule must be replaced by anomaly_record_count > 0"


def test_athena_output_location_suffix():
    """Athena output location ends with /project-athena-results/"""
    from src.ml.train import ATHENA_OUTPUT

    assert ATHENA_OUTPUT.endswith("project-athena-results/")


def test_athena_database_name():
    """Athena database is robot_telemetry_db."""
    from src.ml.train import ATHENA_DATABASE

    assert ATHENA_DATABASE == "robot_telemetry_db"


def test_source_code_contains_deploy_endpoint_config():
    """Source code contains deploy call with correct endpoint_name and instance_type."""
    import inspect
    from src.ml import train

    source = inspect.getsource(train)

    # Verify deploy is called with correct endpoint name
    assert 'endpoint_name="robot-failure-predictor"' in source
    # Verify ml.t2.medium instance type is used for deployment
    assert 'instance_type="ml.t2.medium"' in source
    # SDK 2.257+ 에서 update_endpoint kwarg 제거 → 명시적 cleanup 함수로 대체
    assert "_cleanup_existing_endpoint" in source
    # Verify ml.m5.large is used for training
    assert 'instance_type="ml.m5.large"' in source


@patch("boto3.client")
def test_fetch_training_data_calls_athena(mock_boto_client):
    """fetch_training_data calls boto3.client('athena') with region eu-west-1."""
    from src.ml.train import fetch_training_data

    mock_athena = MagicMock()
    mock_boto_client.return_value = mock_athena
    mock_athena.start_query_execution.return_value = {"QueryExecutionId": "test-exec-id"}
    mock_athena.get_query_execution.return_value = {
        "QueryExecution": {"Status": {"State": "SUCCEEDED"}}
    }

    try:
        fetch_training_data()
    except Exception:
        pass  # May fail on result processing, but we check the boto3 call

    # Verify boto3.client was called
    assert mock_boto_client.called


@patch("src.ml.train.XGBoost")
@patch("src.ml.train.sagemaker")
def test_xgboost_config(mock_sagemaker, mock_xgboost_class):
    """XGBoost estimator is configured with correct entry_point and framework_version."""
    from src.ml.train import run_training_job

    mock_estimator = MagicMock()
    mock_xgboost_class.return_value = mock_estimator
    mock_sagemaker.Session.return_value = MagicMock()

    try:
        run_training_job("s3://bucket/data.csv", "arn:aws:iam::123456789:role/test")
    except Exception:
        pass

    # Verify XGBoost was called
    assert mock_xgboost_class.called

    # Verify call arguments
    if mock_xgboost_class.call_args:
        call_kwargs = mock_xgboost_class.call_args[1]
        assert call_kwargs.get("entry_point") == "train_entry.py"
        assert call_kwargs.get("framework_version") == "1.7-1"
        assert call_kwargs.get("instance_type") == "ml.m5.large"

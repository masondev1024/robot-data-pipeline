"""Unit tests for SageMaker XGBoost training pipeline (train.py).

Task 8.2: Multi-class (6 classes) — 라벨이 dominant_failure_type 기반,
sample_weight 칼럼이 추가됨.
"""

from unittest.mock import MagicMock, patch

import pytest


def test_query_contains_all_features_and_label_column():
    """Query contains 5 features + label CASE on dominant_failure_type + sample_weight."""
    from src.ml.train import QUERY

    for col in [
        "avg_motor_temp",
        "max_motor_temp",
        "battery_drain",
        "active_hours",
        "max_temp_load_ratio",
    ]:
        assert col in QUERY

    # 라벨은 dominant_failure_type 기반 6-class CASE
    assert "CASE dominant_failure_type" in QUERY
    assert "AS label" in QUERY
    assert "sample_weight" in QUERY


def test_query_contains_six_class_label_mapping():
    """6-class enum: NONE/TWF/HDF/PWF/OSF/RNF."""
    from src.ml.train import QUERY, LABEL_MAP, NUM_CLASSES

    assert LABEL_MAP == {"NONE": 0, "TWF": 1, "HDF": 2, "PWF": 3, "OSF": 4, "RNF": 5}
    assert NUM_CLASSES == 6
    for label_name in ["NONE", "TWF", "HDF", "PWF", "OSF", "RNF"]:
        assert f"'{label_name}'" in QUERY


def test_query_excludes_old_self_referential_label():
    """옛 자기참조 라벨(anomaly_record_count > 0) 제거 확인."""
    from src.ml.train import QUERY

    assert "anomaly_record_count > 0" not in QUERY, (
        "self-referential label rule must be replaced by dominant_failure_type"
    )
    assert "max_motor_temp > 90" not in QUERY


def test_query_excludes_stale_columns():
    """옛 stale 컬럼 (Phase 5 cleanup 시 제거됨) — 회귀 가드."""
    from src.ml.train import QUERY

    for col in ["battery_drain_rate", "operation_ratio", "machine_failure"]:
        assert col not in QUERY, f"Stale column '{col}' should not be in QUERY"


def test_query_filters_null_dominant_failure_type():
    """dominant_failure_type IS NOT NULL 필터로 라벨 누락 row 제외."""
    from src.ml.train import QUERY

    assert "dominant_failure_type IS NOT NULL" in QUERY


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
    assert 'endpoint_name="robot-failure-predictor"' in source
    assert 'instance_type="ml.t2.medium"' in source
    assert "_cleanup_existing_endpoint" in source
    assert 'instance_type="ml.m5.large"' in source


@patch("boto3.client")
def test_fetch_training_data_calls_athena(mock_boto_client):
    """fetch_training_data calls boto3.client('athena')."""
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
        pass

    assert mock_boto_client.called


@patch("src.ml.train.XGBoost")
@patch("src.ml.train.sagemaker")
def test_xgboost_multi_class_hyperparameters(mock_sagemaker, mock_xgboost_class):
    """Estimator 호출 시 multi:softprob, num_class=6, eval_metric=mlogloss 가 전달된다."""
    from src.ml.train import run_training_job

    mock_estimator = MagicMock()
    mock_xgboost_class.return_value = mock_estimator
    mock_sagemaker.Session.return_value = MagicMock()

    try:
        run_training_job("s3://bucket/data.csv", "arn:aws:iam::123456789:role/test")
    except Exception:
        pass

    assert mock_xgboost_class.called

    call_kwargs = mock_xgboost_class.call_args[1]
    assert call_kwargs.get("entry_point") == "train_entry.py"
    assert call_kwargs.get("framework_version") == "1.7-1"
    assert call_kwargs.get("instance_type") == "ml.m5.large"

    hp = call_kwargs.get("hyperparameters", {})
    assert hp.get("objective") == "multi:softprob"
    assert hp.get("num_class") == 6
    assert hp.get("eval_metric") == "mlogloss"

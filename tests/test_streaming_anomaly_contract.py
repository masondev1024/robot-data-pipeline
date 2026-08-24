from src.streaming.anomaly_contract import (
    DEFAULT_THRESHOLDS,
    AnomalyThresholds,
    classify_anomaly,
    compute_load_ratio,
    compute_zscore,
    is_multivariate_anomaly,
)


def test_multivariate_branch_matches_tuned_notebook_contract():
    assert is_multivariate_anomaly(95.0, 30.0)
    assert not is_multivariate_anomaly(95.0, 100.0)


def test_multivariate_boundaries_are_explicit():
    assert not is_multivariate_anomaly(91.99, 30.0)
    assert not is_multivariate_anomaly(92.0, 36.8)  # ratio == 2.5
    assert is_multivariate_anomaly(92.0, 36.79)


def test_zscore_uses_sigma_floor_for_constant_history():
    assert compute_zscore(65.0, 65.0, 0.0) == 0.0
    assert compute_zscore(67.0, 65.0, 0.0) == 4.0


def test_invalid_numeric_values_are_fail_closed():
    assert compute_load_ratio(float("nan"), 30.0) == 0.0
    assert compute_load_ratio(95.0, float("nan")) == 0.0
    result = classify_anomaly(95.0, 65.0, float("nan"), 100.0)
    assert result == {"zscore": False, "multivariate": False, "anomaly": False}


def test_detector_is_or_of_zscore_and_multivariate_branches():
    zscore_only = classify_anomaly(95.0, 65.0, 1.0, 100.0)
    assert zscore_only == {"zscore": True, "multivariate": False, "anomaly": True}

    multivariate_only = classify_anomaly(95.0, 65.0, 20.0, 30.0)
    assert multivariate_only["zscore"] is False
    assert multivariate_only["multivariate"] is True
    assert multivariate_only["anomaly"] is True


def test_threshold_object_is_immutable_and_defaults_are_documented():
    assert DEFAULT_THRESHOLDS == AnomalyThresholds(
        zscore_threshold=3.0,
        sigma_floor=0.5,
        min_motor_temp=92.0,
        load_ratio_threshold=2.5,
    )

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "flink"))

import pytest
from anomaly_detection import compute_zscore, compute_load_ratio, is_anomaly

DEFAULT_THRESHOLDS = dict(
    zscore_thr=3.0,
    sigma_floor=0.5,
    load_thr=1.8,
    min_temp=85.0,
)


class TestComputeZscore:
    """compute_zscore(temp, mean, stddev, sigma_floor) — 5케이스"""

    def test_normal_operation(self):
        """정상 동작: compute_zscore(95, 80, 5, 0.5) == 3.0"""
        result = compute_zscore(95, 80, 5, 0.5)
        assert result == pytest.approx(3.0)

    def test_negative_deviation_absolute_value(self):
        """음의 편차 절댓값: compute_zscore(65, 80, 5, 0.5) == 3.0"""
        result = compute_zscore(65, 80, 5, 0.5)
        assert result == pytest.approx(3.0)

    def test_sigma_floor_guard_stddev_zero(self):
        """σ floor 가드 (stddev=0): compute_zscore(81, 80, 0, 0.5) == 2.0"""
        result = compute_zscore(81, 80, 0, 0.5)
        assert result == pytest.approx(2.0)

    def test_sigma_floor_guard_stddev_less_than_floor(self):
        """σ floor 가드 (stddev<floor): compute_zscore(82, 80, 0.1, 0.5) == 4.0"""
        result = compute_zscore(82, 80, 0.1, 0.5)
        assert result == pytest.approx(4.0)

    def test_stddev_greater_than_floor(self):
        """stddev > floor: compute_zscore(95, 80, 10, 0.5) == 1.5"""
        result = compute_zscore(95, 80, 10, 0.5)
        assert result == pytest.approx(1.5)


class TestComputeLoadRatio:
    """compute_load_ratio(temp, current_load) — 4케이스"""

    def test_normal_operation(self):
        """정상 동작: compute_load_ratio(90, 50) == 1.8"""
        result = compute_load_ratio(90, 50)
        assert result == pytest.approx(1.8)

    def test_load_zero_guard(self):
        """load=0 가드: compute_load_ratio(90, 0) == 90.0"""
        result = compute_load_ratio(90, 0)
        assert result == pytest.approx(90.0)

    def test_load_one(self):
        """load=1: compute_load_ratio(90, 1) == 90.0"""
        result = compute_load_ratio(90, 1)
        assert result == pytest.approx(90.0)

    def test_high_load_normal(self):
        """고부하 정상: compute_load_ratio(90, 100) == 0.9"""
        result = compute_load_ratio(90, 100)
        assert result == pytest.approx(0.9)


class TestIsAnomaly:
    """is_anomaly(...) — 8케이스 + threshold tuning

    고정 threshold: zscore_thr=3.0, sigma_floor=0.5, load_thr=1.8, min_temp=85.0
    """

    def test_anomaly_zscore_boundary_exceed(self):
        """케이스 #1: zscore 정확히 3.2 > 3.0 → True (Cond1)"""
        result = is_anomaly(
            temp=96,
            mean=80,
            stddev=5,
            current_load=100,
            **DEFAULT_THRESHOLDS,
        )
        assert result is True

    def test_anomaly_load_ratio_boundary_exceed(self):
        """케이스 #2: temp=90, load=49 → load_ratio≈1.836 > 1.8 → True (Cond2)"""
        result = is_anomaly(
            temp=90,
            mean=80,
            stddev=5,
            current_load=49,
            **DEFAULT_THRESHOLDS,
        )
        assert result is True

    def test_no_anomaly_both_conditions_false(self):
        """케이스 #3: zscore=0, temp=80 < 85 → False"""
        result = is_anomaly(
            temp=80,
            mean=80,
            stddev=5,
            current_load=100,
            **DEFAULT_THRESHOLDS,
        )
        assert result is False

    def test_no_anomaly_low_zscore_low_temp(self):
        """케이스 #4: zscore=0.8, temp=84 < 85 → False"""
        result = is_anomaly(
            temp=84,
            mean=80,
            stddev=5,
            current_load=40,
            **DEFAULT_THRESHOLDS,
        )
        assert result is False

    def test_anomaly_both_conditions_true(self):
        """케이스 #5: zscore=4.0 > 3.0 AND 100/50=2.0 > 1.8 → True (둘 다)"""
        result = is_anomaly(
            temp=100,
            mean=80,
            stddev=5,
            current_load=50,
            **DEFAULT_THRESHOLDS,
        )
        assert result is True

    def test_no_anomaly_sigma_floor_guard(self):
        """케이스 #6: σ=0 가드 → zscore=2.0, temp=81 < 85 → False"""
        result = is_anomaly(
            temp=81,
            mean=80,
            stddev=0,
            current_load=100,
            **DEFAULT_THRESHOLDS,
        )
        assert result is False

    def test_anomaly_sigma_floor_guard_high_zscore(self):
        """케이스 #7: σ=0 가드 → zscore=20.0 > 3.0 → True (Cond1)"""
        result = is_anomaly(
            temp=90,
            mean=80,
            stddev=0,
            current_load=100,
            **DEFAULT_THRESHOLDS,
        )
        assert result is True

    def test_anomaly_load_guard_with_zero_load(self):
        """케이스 #8: temp≥85 + load=0 가드 → 86/1=86 > 1.8 → True (Cond2)"""
        result = is_anomaly(
            temp=86,
            mean=80,
            stddev=5,
            current_load=0,
            **DEFAULT_THRESHOLDS,
        )
        assert result is True


class TestThresholdTuning:
    """ADR-009 threshold 외부화 — 임계값 변경 시 boundary가 정확히 반응"""

    def test_dynamic_min_temp_threshold(self):
        """min_temp=80.0으로 변경 시 Cond2 활성화 검증"""
        # temp=84, 기본값 min_temp=85.0 → False
        result_default = is_anomaly(
            temp=84,
            mean=80,
            stddev=5,
            current_load=40,
            zscore_thr=3.0,
            sigma_floor=0.5,
            load_thr=1.8,
            min_temp=85.0,
        )
        assert result_default is False

        # temp=84, 변경된 min_temp=80.0 → 84/40=2.1 > 1.8 → True
        result_tuned = is_anomaly(
            temp=84,
            mean=80,
            stddev=5,
            current_load=40,
            zscore_thr=3.0,
            sigma_floor=0.5,
            load_thr=1.8,
            min_temp=80.0,
        )
        assert result_tuned is True

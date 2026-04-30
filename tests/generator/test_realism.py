"""실무 현실성 보강 helper(load↔temp 상관, hour-of-day 사이클, battery factor) 단위 테스트."""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/generator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from _record import (
    battery_drain_factor,
    hour_load_multiplier,
    load_temp_delta,
)


class TestLoadTempDelta:
    def test_zero_load_zero_delta(self):
        assert load_temp_delta(0, coeff=5.0) == pytest.approx(0.0)

    def test_full_load_full_coeff(self):
        assert load_temp_delta(100, coeff=5.0) == pytest.approx(5.0)

    def test_half_load_half_coeff(self):
        assert load_temp_delta(50, coeff=5.0) == pytest.approx(2.5)

    def test_negative_load_clamped_to_zero(self):
        """음수 load는 음의 delta가 되지 않도록 clamp."""
        assert load_temp_delta(-10, coeff=5.0) == pytest.approx(0.0)


class TestHourLoadMultiplier:
    def test_peak_hour_returns_max(self):
        """UTC 14시(peak) → 가장 큰 multiplier."""
        peak = hour_load_multiplier(14, variance=0.4)
        idle = hour_load_multiplier(2, variance=0.4)
        assert peak > idle

    def test_idle_hour_uses_lower_bound(self):
        """UTC 02시(반대) → 0.6 ~ baseline 사이."""
        idle = hour_load_multiplier(2, variance=0.4)
        assert 0.55 < idle < 0.7

    def test_zero_variance_returns_constant(self):
        """variance=0 이면 항상 1.0 (사이클 없음)."""
        for h in range(24):
            assert hour_load_multiplier(h, variance=0.0) == pytest.approx(1.0)

    def test_multiplier_in_reasonable_bounds(self):
        """모든 시간대에 대해 [0.6, 1.0] 범위 (default variance=0.4)."""
        for h in range(24):
            m = hour_load_multiplier(h, variance=0.4)
            assert 0.55 <= m <= 1.05, f"hour={h} multiplier={m}"


class TestBatteryDrainFactor:
    def test_no_load_no_temp_returns_one(self):
        """load=0, temp<=70 → drain factor = 1.0 (영향 없음)."""
        f = battery_drain_factor(current_load=0, motor_temp=65, load_coeff=0.5, temp_coeff=0.3)
        assert f == pytest.approx(1.0)

    def test_full_load_increases_drain(self):
        """load=100 → load_factor 1.5 (default coeff 0.5)."""
        f = battery_drain_factor(current_load=100, motor_temp=65, load_coeff=0.5, temp_coeff=0.3)
        assert f == pytest.approx(1.5)

    def test_high_temp_increases_drain(self):
        """motor_temp=100 (70+30) → temp_factor 1.3 (default coeff 0.3)."""
        f = battery_drain_factor(current_load=0, motor_temp=100, load_coeff=0.5, temp_coeff=0.3)
        assert f == pytest.approx(1.3)

    def test_combined_factors_multiply(self):
        """load=100, temp=100 → 1.5 * 1.3 = 1.95."""
        f = battery_drain_factor(current_load=100, motor_temp=100, load_coeff=0.5, temp_coeff=0.3)
        assert f == pytest.approx(1.95)

    def test_temp_below_threshold_no_temp_effect(self):
        """temp < 70 → temp_factor = 1.0."""
        f = battery_drain_factor(current_load=0, motor_temp=60, load_coeff=0.5, temp_coeff=0.3)
        assert f == pytest.approx(1.0)

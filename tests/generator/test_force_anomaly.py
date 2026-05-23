"""SIGUSR1 force-anomaly 윈도우 + _should_spike 헬퍼 테스트."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/generator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from app import _should_spike, _trigger_force_anomaly
import app as generator_app


@pytest.fixture(autouse=True)
def reset_force_window():
    """각 테스트 시작 시 모듈 전역 상태를 리셋."""
    generator_app._force_anomaly_until_ts = 0.0
    yield
    generator_app._force_anomaly_until_ts = 0.0


class TestShouldSpike:
    def test_force_window_active_always_spikes(self):
        """force window 내부면 is_faulty=False여도 spike."""
        profile = {"is_faulty": False}
        now = 1000.0
        force_until = 1010.0
        assert _should_spike(profile, now, force_until) is True

    def test_force_window_active_for_faulty_robot(self):
        """force window 내부면 is_faulty=True도 당연히 spike."""
        profile = {"is_faulty": True}
        now = 1000.0
        force_until = 1010.0
        assert _should_spike(profile, now, force_until) is True

    def test_force_window_expired_non_faulty_no_spike(self):
        """force window 만료 + is_faulty=False → spike 없음."""
        profile = {"is_faulty": False}
        now = 1000.0
        force_until = 999.0  # 이미 지남
        assert _should_spike(profile, now, force_until) is False

    def test_force_window_zero_means_disabled(self):
        """force_until_ts=0이면 비활성 상태(평소 룰만 적용)."""
        profile = {"is_faulty": False}
        assert _should_spike(profile, time.time(), 0.0) is False

    def test_faulty_robot_outside_window_uses_random(self, monkeypatch):
        """force window 밖에서 is_faulty=True면 random.random() < 0.05 룰 적용."""
        profile = {"is_faulty": True}
        now = 1000.0
        force_until = 0.0

        # random.random()을 0.04로 고정 → spike (< 0.05)
        monkeypatch.setattr("app.random.random", lambda: 0.04)
        assert _should_spike(profile, now, force_until) is True

        # random.random()을 0.06으로 고정 → no spike (>= 0.05)
        monkeypatch.setattr("app.random.random", lambda: 0.06)
        assert _should_spike(profile, now, force_until) is False


class TestTriggerForceAnomaly:
    def test_sets_until_ts_to_now_plus_default_60s(self, monkeypatch):
        """SIGUSR1 핸들러는 기본 60초 윈도우를 연다."""
        monkeypatch.delenv("FORCE_ANOMALY_DURATION_SEC", raising=False)
        monkeypatch.setattr("app.time.time", lambda: 5000.0)

        _trigger_force_anomaly()

        assert generator_app._force_anomaly_until_ts == 5060.0

    def test_respects_env_var_duration(self, monkeypatch):
        """FORCE_ANOMALY_DURATION_SEC env var로 윈도우 길이 조정."""
        monkeypatch.setenv("FORCE_ANOMALY_DURATION_SEC", "120")
        monkeypatch.setattr("app.time.time", lambda: 5000.0)

        _trigger_force_anomaly()

        assert generator_app._force_anomaly_until_ts == 5120.0

    def test_repeated_trigger_extends_or_resets_window(self, monkeypatch):
        """연속 SIGUSR1은 윈도우를 새로 갱신(가장 최근 시각 기준)."""
        monkeypatch.setenv("FORCE_ANOMALY_DURATION_SEC", "60")

        monkeypatch.setattr("app.time.time", lambda: 1000.0)
        _trigger_force_anomaly()
        first_until = generator_app._force_anomaly_until_ts

        monkeypatch.setattr("app.time.time", lambda: 1030.0)
        _trigger_force_anomaly()
        second_until = generator_app._force_anomaly_until_ts

        # 두 번째 trigger가 새 윈도우 열어야 함 (1030+60 = 1090 > 1060)
        assert second_until > first_until
        assert second_until == 1090.0

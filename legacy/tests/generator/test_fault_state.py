"""Fault state machine 단위 테스트.

NORMAL → RAMPING → OVERHEATED → COOLING → NORMAL 라이프사이클과
STUCK sub-state 의 결정성·경계 동작을 검증한다. RNG는 random.Random 인스턴스로 주입해
재현 가능하게 만든다.
"""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/generator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from _fault_state import Phase, advance_phase, init_state


DEFAULT_PARAMS = {
    "fault_entry_prob": 0.0002,
    "fault_ramp_ticks": 20,
    "fault_peak_ticks": 40,
    "fault_cooldown_ticks": 30,
    "fault_peak_temp_delta": 25.0,
    "stuck_entry_prob": 0.00005,
    "stuck_min_ticks": 60,
    "stuck_max_ticks": 120,
}


class TestInit:
    def test_init_state_is_normal(self):
        state = init_state()
        assert state["phase"] == Phase.NORMAL
        assert state["ticks_remaining"] == 0
        assert state["peak_delta"] == 0.0


class TestNormalPhase:
    def test_non_faulty_robot_stays_normal(self):
        """is_faulty=False 로봇은 시간이 흘러도 NORMAL 유지."""
        profile = {"is_faulty": False}
        rng = random.Random(42)
        state = init_state()
        for _ in range(10000):
            state, delta, is_stuck = advance_phase(
                state, profile, DEFAULT_PARAMS, force_anomaly=False, rng=rng
            )
        assert state["phase"] == Phase.NORMAL
        assert delta == 0.0
        assert is_stuck is False

    def test_faulty_robot_with_zero_entry_prob_stays_normal(self):
        """entry_prob=0 이면 faulty 로봇도 NORMAL 유지."""
        profile = {"is_faulty": True}
        params = {**DEFAULT_PARAMS, "fault_entry_prob": 0.0, "stuck_entry_prob": 0.0}
        rng = random.Random(42)
        state = init_state()
        for _ in range(10000):
            state, delta, is_stuck = advance_phase(
                state, profile, params, force_anomaly=False, rng=rng
            )
        assert state["phase"] == Phase.NORMAL


class TestRamping:
    def test_faulty_robot_with_certain_entry_enters_ramping(self):
        profile = {"is_faulty": True}
        params = {**DEFAULT_PARAMS, "fault_entry_prob": 1.0, "stuck_entry_prob": 0.0}
        rng = random.Random(42)
        state = init_state()
        state, delta, _ = advance_phase(state, profile, params, False, rng)
        assert state["phase"] == Phase.RAMPING
        assert state["ticks_remaining"] > 0
        assert state["peak_delta"] > 0

    def test_ramping_delta_grows_over_ticks(self):
        """RAMPING 단계에서 temp_delta가 점진적으로 증가."""
        profile = {"is_faulty": True}
        params = {
            **DEFAULT_PARAMS,
            "fault_entry_prob": 1.0,
            "fault_ramp_ticks": 5,
            "stuck_entry_prob": 0.0,
        }
        rng = random.Random(42)
        state = init_state()
        deltas = []
        # 첫 tick에서 RAMPING 진입
        state, delta, _ = advance_phase(state, profile, params, False, rng)
        deltas.append(delta)
        # 추가 RAMPING ticks
        while state["phase"] == Phase.RAMPING:
            state, delta, _ = advance_phase(state, profile, params, False, rng)
            deltas.append(delta)
        # 마지막 delta는 peak에 가깝게
        assert deltas[0] < deltas[-2], f"deltas not monotonic: {deltas}"
        assert deltas[-1] >= params["fault_peak_temp_delta"] * 0.8

    def test_ramping_transitions_to_overheated(self):
        profile = {"is_faulty": True}
        params = {
            **DEFAULT_PARAMS,
            "fault_entry_prob": 1.0,
            "fault_ramp_ticks": 3,
            "stuck_entry_prob": 0.0,
        }
        rng = random.Random(42)
        state = init_state()
        # 강제로 RAMPING 진입 → 3 tick 더 → OVERHEATED
        for _ in range(5):
            state, _, _ = advance_phase(state, profile, params, False, rng)
        assert state["phase"] == Phase.OVERHEATED


class TestOverheated:
    def test_overheated_holds_peak_delta(self):
        profile = {"is_faulty": True}
        params = {
            **DEFAULT_PARAMS,
            "fault_entry_prob": 1.0,
            "fault_ramp_ticks": 1,
            "fault_peak_ticks": 5,
            "stuck_entry_prob": 0.0,
        }
        rng = random.Random(42)
        state = init_state()
        # RAMPING 1 tick → OVERHEATED 진입
        state, _, _ = advance_phase(state, profile, params, False, rng)  # RAMPING
        state, _, _ = advance_phase(state, profile, params, False, rng)  # RAMPING last → next OVERHEATED
        peak_delta = state["peak_delta"]
        # OVERHEATED 단계 delta는 peak에 가까움
        for _ in range(3):
            state, delta, _ = advance_phase(state, profile, params, False, rng)
            assert state["phase"] == Phase.OVERHEATED
            assert abs(delta - peak_delta) < 5.0  # ±noise


class TestCooling:
    def test_overheated_to_cooling_to_normal(self):
        profile = {"is_faulty": True}
        params = {
            **DEFAULT_PARAMS,
            "fault_entry_prob": 1.0,
            "fault_ramp_ticks": 1,
            "fault_peak_ticks": 2,
            "fault_cooldown_ticks": 3,
            "stuck_entry_prob": 0.0,
        }
        rng = random.Random(42)
        state = init_state()
        phases_seen = []
        for _ in range(20):
            state, _, _ = advance_phase(state, profile, params, False, rng)
            phases_seen.append(state["phase"])
            if state["phase"] == Phase.NORMAL and len(phases_seen) > 5:
                break
        assert Phase.RAMPING in phases_seen
        assert Phase.OVERHEATED in phases_seen
        assert Phase.COOLING in phases_seen
        assert phases_seen[-1] == Phase.NORMAL

    def test_cooling_delta_decreases(self):
        profile = {"is_faulty": True}
        params = {
            **DEFAULT_PARAMS,
            "fault_entry_prob": 1.0,
            "fault_ramp_ticks": 1,
            "fault_peak_ticks": 1,
            "fault_cooldown_ticks": 4,
            "stuck_entry_prob": 0.0,
        }
        rng = random.Random(42)
        state = init_state()
        # 진행: NORMAL→RAMPING→OVERHEATED→COOLING. COOLING 도달까지 advance.
        guard = 0
        while state["phase"] != Phase.COOLING and guard < 20:
            state, _, _ = advance_phase(state, profile, params, False, rng)
            guard += 1
        assert state["phase"] == Phase.COOLING
        cooling_deltas = []
        while state["phase"] == Phase.COOLING:
            state, delta, _ = advance_phase(state, profile, params, False, rng)
            cooling_deltas.append(delta)
        assert len(cooling_deltas) >= 2
        assert cooling_deltas[0] > cooling_deltas[-1], f"cooling not decreasing: {cooling_deltas}"


class TestForceAnomaly:
    def test_force_anomaly_drives_normal_to_overheated(self):
        """SIGUSR1 force window → 즉시 OVERHEATED."""
        profile = {"is_faulty": False}
        rng = random.Random(42)
        state = init_state()
        state, delta, _ = advance_phase(state, profile, DEFAULT_PARAMS, force_anomaly=True, rng=rng)
        assert state["phase"] == Phase.OVERHEATED
        assert delta >= DEFAULT_PARAMS["fault_peak_temp_delta"] * 0.8

    def test_force_anomaly_keeps_overheated_extended(self):
        """force window 동안에는 ticks_remaining 만료돼도 OVERHEATED 유지."""
        profile = {"is_faulty": False}
        rng = random.Random(42)
        state = init_state()
        for _ in range(100):
            state, delta, _ = advance_phase(state, profile, DEFAULT_PARAMS, force_anomaly=True, rng=rng)
            assert state["phase"] == Phase.OVERHEATED
            assert delta > 0


class TestStuckSensor:
    def test_stuck_entry_returns_is_stuck_true(self):
        profile = {"is_faulty": True}
        params = {
            **DEFAULT_PARAMS,
            "fault_entry_prob": 0.0,
            "stuck_entry_prob": 1.0,
            "stuck_min_ticks": 5,
            "stuck_max_ticks": 10,
        }
        rng = random.Random(42)
        state = init_state()
        state, _, is_stuck = advance_phase(state, profile, params, False, rng)
        assert state["phase"] == Phase.STUCK
        assert is_stuck is True

    def test_stuck_returns_to_normal(self):
        profile = {"is_faulty": True}
        params = {
            **DEFAULT_PARAMS,
            "fault_entry_prob": 0.0,
            "stuck_entry_prob": 1.0,
            "stuck_min_ticks": 3,
            "stuck_max_ticks": 3,
        }
        rng = random.Random(42)
        state = init_state()
        # Tick 1: enter STUCK with ticks_remaining=3
        state, _, is_stuck = advance_phase(state, profile, params, False, rng)
        assert state["phase"] == Phase.STUCK
        # 3 more ticks → NORMAL
        for _ in range(3):
            state, _, _ = advance_phase(state, profile, params, False, rng)
        assert state["phase"] == Phase.NORMAL

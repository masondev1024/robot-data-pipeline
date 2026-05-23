"""Failure type ground truth channel 단위 테스트 (Task 8.1).

Generator가 AI4I CSV의 5종 failure 칼럼(TWF/HDF/PWF/OSF/RNF)을 보존하여
profile에 failure_type 필드로 매핑하고, simulate_robot에서 fault episode
(OVERHEATED/STUCK) 발화 시에만 송출하는지 검증.

우선순위: HDF > PWF > OSF > TWF > RNF (모터 직결 우선).
"""
import asyncio
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/generator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from app import load_profiles, simulate_robot
from _record import resolve_failure_type


SEED_CSV = os.path.join(os.path.dirname(__file__), "../../data/seed_data_sample.csv")


class TestResolveFailureType:
    def test_all_zero_returns_none(self):
        assert resolve_failure_type({"TWF": 0, "HDF": 0, "PWF": 0, "OSF": 0, "RNF": 0}) == "NONE"

    def test_hdf_wins_over_others(self):
        """HDF=1 + PWF=1 → HDF (모터 직결 최우선)."""
        assert resolve_failure_type({"TWF": 1, "HDF": 1, "PWF": 1, "OSF": 1, "RNF": 1}) == "HDF"

    def test_pwf_wins_over_osf_twf_rnf(self):
        assert resolve_failure_type({"TWF": 1, "HDF": 0, "PWF": 1, "OSF": 1, "RNF": 1}) == "PWF"

    def test_osf_wins_over_twf_rnf(self):
        assert resolve_failure_type({"TWF": 1, "HDF": 0, "PWF": 0, "OSF": 1, "RNF": 1}) == "OSF"

    def test_twf_wins_over_rnf(self):
        assert resolve_failure_type({"TWF": 1, "HDF": 0, "PWF": 0, "OSF": 0, "RNF": 1}) == "TWF"

    def test_rnf_alone(self):
        assert resolve_failure_type({"TWF": 0, "HDF": 0, "PWF": 0, "OSF": 0, "RNF": 1}) == "RNF"


class TestProfileFailureType:
    def test_profile_has_failure_type_field(self):
        """모든 profile에 failure_type 필드가 포함된다."""
        profiles = load_profiles(SEED_CSV, (0, 50))
        for p in profiles:
            assert "failure_type" in p, f"Missing failure_type: {p['robot_id']}"

    def test_failure_type_in_valid_enum(self):
        """failure_type ∈ {NONE, TWF, HDF, PWF, OSF, RNF}."""
        valid = {"NONE", "TWF", "HDF", "PWF", "OSF", "RNF"}
        profiles = load_profiles(SEED_CSV, (0, 200))
        for p in profiles:
            assert p["failure_type"] in valid, f"Invalid failure_type: {p['failure_type']}"

    def test_non_faulty_robots_have_none(self):
        """is_faulty=False 로봇은 failure_type=NONE."""
        profiles = load_profiles(SEED_CSV, (0, 200))
        for p in profiles:
            if not p["is_faulty"]:
                assert p["failure_type"] == "NONE", (
                    f"{p['robot_id']} not faulty but failure_type={p['failure_type']}"
                )

    def test_faulty_robots_have_non_none(self):
        """is_faulty=True 로봇은 NONE이 아닌 type을 가진다 (한 명 이상 존재 보장)."""
        profiles = load_profiles(SEED_CSV, (0, 200))
        faulty = [p for p in profiles if p["is_faulty"]]
        assert len(faulty) > 0, "no faulty robot found"
        for p in faulty:
            assert p["failure_type"] != "NONE", (
                f"{p['robot_id']} is faulty but failure_type=NONE"
            )


class TestSimulateRobotEmitsFailureType:
    """simulate_robot가 fault episode 발화 시에만 profile.failure_type 송출."""

    def _make_profile(self, failure_type: str, is_faulty: bool = True):
        return {
            "robot_id": "ROBOT-00001",
            "pos_x": 37.4,
            "pos_y": 126.8,
            "motor_temp_base": 70.0,
            "load_base": 50,
            "drain_factor": 1.0,
            "is_faulty": is_faulty,
            "failure_type": failure_type,
            "battery": 80,
        }

    def _drain_records(self, profile, ticks=5, force_anomaly=False):
        """simulate_robot 1개를 ticks회 돌리고 큐에서 record dict들을 회수.

        force_anomaly=True 면 SIGUSR1 핸들러를 직접 호출해 force window 활성.
        """
        async def _runner():
            queue = asyncio.Queue()
            shutdown = asyncio.Event()
            if force_anomaly:
                # 모듈 전역 _force_anomaly_until_ts 갱신
                import app as _app
                import time as _time
                _app._force_anomaly_until_ts = _time.time() + 3600
            else:
                import app as _app
                _app._force_anomaly_until_ts = 0.0

            task = asyncio.create_task(
                simulate_robot(profile, queue, tick_interval=0.001, shutdown=shutdown)
            )
            await asyncio.sleep(0.05)
            shutdown.set()
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except asyncio.TimeoutError:
                task.cancel()
            records = []
            while not queue.empty():
                records.append(queue.get_nowait())
            return records

        return asyncio.run(_runner())

    def test_record_always_has_failure_type_field(self):
        """모든 송출 record에 failure_type 필드 존재."""
        profile = self._make_profile("HDF", is_faulty=False)
        records = self._drain_records(profile, ticks=5)
        assert len(records) > 0
        for r in records:
            assert "failure_type" in r

    def test_normal_phase_emits_none(self):
        """is_faulty=False → NORMAL 유지 → failure_type='NONE'."""
        profile = self._make_profile("HDF", is_faulty=False)
        records = self._drain_records(profile, ticks=10)
        for r in records:
            assert r["failure_type"] == "NONE", (
                f"non-faulty robot emitted failure_type={r['failure_type']}"
            )

    def test_force_anomaly_emits_profile_failure_type(self):
        """force window → OVERHEATED → record.failure_type == profile.failure_type."""
        profile = self._make_profile("HDF", is_faulty=False)
        records = self._drain_records(profile, ticks=5, force_anomaly=True)
        assert len(records) > 0
        # force window 활성이므로 모든 record가 OVERHEATED → HDF 송출
        non_none = [r for r in records if r["failure_type"] != "NONE"]
        assert len(non_none) > 0, "force window 인데 failure_type 없음"
        for r in non_none:
            assert r["failure_type"] == "HDF"

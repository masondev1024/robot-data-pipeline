"""RNG 격리 테스트 — generator 모듈 전역 random.* 오염 없이 재현 가능한지 검증.

본선 시연 모드의 byte-equal SHA256 검증 (verify_demo_determinism.py metric #2) prerequisite.
"""
import hashlib
import json
import os
import random
import sys
from datetime import datetime, timezone

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/generator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from backfill import generate_record


# ── 공통 픽스처 ──────────────────────────────────────────────────

PROFILE = {
    "robot_id":        "ROBOT-00001",
    "pos_x":           37.5,
    "pos_y":           126.9,
    "motor_temp_base": 75.0,
    "load_base":       50,
    "drain_factor":    1.5,
    "is_faulty":       False,
    "battery":         80,
}

FAULTY_PROFILE = {**PROFILE, "robot_id": "ROBOT-00002", "is_faulty": True}

FIXED_TS = datetime(2026, 5, 22, 14, 0, tzinfo=timezone.utc)


def _record_sha256(record: dict) -> str:
    """record dict → JSON bytes (key 정렬) → SHA256 hex."""
    payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _generate_n_records(seed: int, n: int) -> list[str]:
    """시드 고정 RNG 로 n개 record 생성 → SHA256 list."""
    rng = random.Random(seed)
    return [
        _record_sha256(generate_record(PROFILE, FIXED_TS, rng))
        for _ in range(n)
    ]


# ── Test 1: 동일 시드 3회 호출 → byte-equal (SHA256 일치) ───────

class TestDeterministicReproducibility:
    def test_same_seed_three_runs_byte_equal(self):
        """시드 2026으로 생성한 3회 연속 record 리스트가 byte-equal."""
        run_a = _generate_n_records(2026, 10)
        run_b = _generate_n_records(2026, 10)
        run_c = _generate_n_records(2026, 10)
        assert run_a == run_b == run_c, (
            "동일 시드 3회 실행 결과가 다름 — 모듈 전역 random.* 오염 의심"
        )

    def test_same_seed_produces_same_sha256(self):
        """단일 record 의 SHA256이 시드 고정 시 항상 동일."""
        rng_a = random.Random(2026)
        rng_b = random.Random(2026)
        rec_a = generate_record(PROFILE, FIXED_TS, rng_a)
        rec_b = generate_record(PROFILE, FIXED_TS, rng_b)
        assert _record_sha256(rec_a) == _record_sha256(rec_b)


# ── Test 2: 시드 다르면 출력 다름 (sanity check) ─────────────────

class TestDifferentSeedsDifferentOutput:
    def test_different_seeds_produce_different_records(self):
        """시드 2026 vs 9999 → 출력이 달라야 한다."""
        rng_a = random.Random(2026)
        rng_b = random.Random(9999)
        rec_a = generate_record(PROFILE, FIXED_TS, rng_a)
        rec_b = generate_record(PROFILE, FIXED_TS, rng_b)
        # pos_x, pos_y, battery_level, load, motor_temp 중 하나 이상 달라야 함
        assert rec_a != rec_b, "다른 시드인데 동일한 record 생성 — 시드 주입 미작동"

    def test_none_rng_fallback_varies(self):
        """rng=None 시 매번 새 Random() 생성 → 결과가 달라야 한다 (100회 중)."""
        results = {
            _record_sha256(generate_record(PROFILE, FIXED_TS, rng=None))
            for _ in range(20)
        }
        # 20회 중 최소 2개 이상 달라야 (모두 같으면 격리 실패)
        assert len(results) > 1, "rng=None fallback 이 항상 동일한 결과 반환"


# ── Test 3: 모듈 전역 random 오염 격리 ──────────────────────────

class TestModuleLevelRNGIsolation:
    def test_global_random_calls_do_not_affect_injected_rng(self):
        """외부 코드가 global random.random() 5회 호출 후에도 injected rng 결과 불변."""
        rng_baseline = random.Random(2026)
        rec_baseline = generate_record(PROFILE, FIXED_TS, rng_baseline)

        # 외부 코드가 모듈 전역 random 을 오염
        for _ in range(5):
            random.random()
            random.gauss(0, 1)
            random.uniform(0, 100)

        rng_after = random.Random(2026)
        rec_after = generate_record(PROFILE, FIXED_TS, rng_after)

        assert _record_sha256(rec_baseline) == _record_sha256(rec_after), (
            "모듈 전역 random 호출이 injected RNG 결과에 영향을 줌 — 격리 실패"
        )

    def test_rng_state_advances_independently(self):
        """두 개의 독립 RNG 인스턴스가 서로의 state 에 영향을 주지 않는다."""
        rng_a = random.Random(42)
        rng_b = random.Random(42)

        # rng_a 를 10번 소진
        for _ in range(10):
            rng_a.gauss(0, 1)

        # rng_b 는 독립 → 동일 시드에서 같은 첫 번째 값을 생성해야 함
        val_b_first = rng_b.gauss(0, 1)

        rng_b_replay = random.Random(42)
        val_replay = rng_b_replay.gauss(0, 1)

        assert val_b_first == val_replay, (
            "두 RNG 인스턴스 간 state 누수 — 격리 실패"
        )


# ── Test 4: 시연 모드 setup 후 deterministic ─────────────────────

class TestDemoModeSetup:
    def test_demo_seed_with_numpy_and_pythonhashseed(self, monkeypatch):
        """np.random.default_rng(2026) + PYTHONHASHSEED=2026 환경에서 generator deterministic."""
        monkeypatch.setenv("PYTHONHASHSEED", "2026")

        # numpy RNG 초기화 (시연 모드 setup 흉내)
        np_rng = np.random.default_rng(2026)

        # generator 는 자체 random.Random(2026) 사용
        rng_a = random.Random(2026)
        rng_b = random.Random(2026)

        rec_a = generate_record(PROFILE, FIXED_TS, rng_a)
        rec_b = generate_record(PROFILE, FIXED_TS, rng_b)

        # numpy 난수 소진 (외부 코드 시뮬레이션)
        _ = np_rng.standard_normal(100)

        # numpy 오염 후에도 generator 결과 불변
        rng_c = random.Random(2026)
        rec_c = generate_record(PROFILE, FIXED_TS, rng_c)

        sha_a = _record_sha256(rec_a)
        sha_b = _record_sha256(rec_b)
        sha_c = _record_sha256(rec_c)

        assert sha_a == sha_b == sha_c, (
            f"시연 모드 setup 후 determinism 실패: {sha_a} vs {sha_b} vs {sha_c}"
        )

    def test_faulty_robot_demo_deterministic(self):
        """faulty 로봇도 시드 고정 시 spike 여부가 재현 가능."""
        rng_a = random.Random(2026)
        rng_b = random.Random(2026)

        temps_a = [
            generate_record(FAULTY_PROFILE, FIXED_TS, rng_a)["motor_temp"]
            for _ in range(50)
        ]
        temps_b = [
            generate_record(FAULTY_PROFILE, FIXED_TS, rng_b)["motor_temp"]
            for _ in range(50)
        ]

        assert temps_a == temps_b, "faulty 로봇 시드 고정 재현성 실패"

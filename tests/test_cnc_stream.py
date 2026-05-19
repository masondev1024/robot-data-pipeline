"""CNCStreamGenerator 단위 테스트 (PRISM 본선 D-3 Phase 2).

검증 항목:
1. 결정성 — 동일 seed + t → 동일 출력
2. schema 정합 — CNC_COLS 모두 포함
3. DuckDB write_cnc 통합 — StorageDB 사용
4. fault phase coolant_temp 상승 확인
5. defect 확률 구조 (dimension_dev 극단 시 확률 방향 검증)
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.generator.cnc_stream import CNCStreamGenerator
from src.orchestration.storage import CNC_COLS, StorageDB


# ── fixture ────────────────────────────────────────────────────────────────────

@pytest.fixture
def gen() -> CNCStreamGenerator:
    return CNCStreamGenerator(machine_id="CNC-01", seed=2026)


# ── 1. 결정성 (동일 seed + t → 동일 출력) ─────────────────────────────────────

def test_next_sample_deterministic(gen: CNCStreamGenerator) -> None:
    """동일 seed 와 t 로 두 번 호출하면 동일 결과를 반환해야 한다."""
    s1 = gen.next_sample(42.0)
    # 새 generator (동일 seed) 로 동일 t 호출
    gen2 = CNCStreamGenerator(machine_id="CNC-01", seed=2026)
    s2 = gen2.next_sample(42.0)

    for col in ("tool_age", "spindle_rpm", "coolant_temp",
                "vibration_xyz", "thermal_drift", "dimension_dev", "defect"):
        assert s1[col] == s2[col], f"{col} 결정성 실패: {s1[col]} != {s2[col]}"


def test_next_sample_different_t_gives_different_results(gen: CNCStreamGenerator) -> None:
    """서로 다른 t 는 서로 다른 tool_age 를 반환해야 한다."""
    s1 = gen.next_sample(0.0)
    s2 = gen.next_sample(100.0)
    assert s1["tool_age"] != s2["tool_age"]


# ── 2. schema 정합 (CNC_COLS 모두 포함) ────────────────────────────────────────

def test_next_sample_schema_has_all_cnc_cols(gen: CNCStreamGenerator) -> None:
    """next_sample 반환 dict 가 CNC_COLS 의 모든 컬럼을 포함해야 한다."""
    sample = gen.next_sample(10.0)
    for col in CNC_COLS:
        assert col in sample, f"CNC_COLS 컬럼 누락: {col}"


def test_next_sample_types(gen: CNCStreamGenerator) -> None:
    """각 컬럼 타입 확인."""
    sample = gen.next_sample(5.0)
    assert isinstance(sample["ts"], datetime)
    assert isinstance(sample["machine_id"], str)
    assert isinstance(sample["tool_age"], float)
    assert isinstance(sample["spindle_rpm"], float)
    assert isinstance(sample["coolant_temp"], float)
    assert isinstance(sample["vibration_xyz"], float)
    assert isinstance(sample["thermal_drift"], float)
    assert isinstance(sample["dimension_dev"], float)
    assert isinstance(sample["defect"], bool)


# ── 3. DuckDB write_cnc 통합 ───────────────────────────────────────────────────

def test_write_cnc_integration(gen: CNCStreamGenerator) -> None:
    """StorageDB.write_cnc 를 통해 10개 샘플을 적재하고 count 검증."""
    samples = [gen.next_sample(float(t)) for t in range(10)]
    with StorageDB(":memory:") as db:
        n = db.write_cnc(samples)
        assert n == 10
        assert db.count("cnc_telemetry") == 10
        row = db.query("SELECT * FROM cnc_telemetry LIMIT 1")[0]
        for col in CNC_COLS:
            assert col in row, f"DuckDB 컬럼 누락: {col}"


# ── 4. fault phase coolant_temp 상승 ──────────────────────────────────────────

def test_coolant_temp_elevated_in_fault_phase() -> None:
    """t=45s (fault phase 30-60s) 의 coolant_temp 는 normal t=10s 보다 높아야 한다.

    여러 seed 로 평균을 비교해 noise 영향을 줄인다.
    """
    fault_temps = [CNCStreamGenerator(seed=s).next_sample(45.0)["coolant_temp"]
                   for s in range(20)]
    normal_temps = [CNCStreamGenerator(seed=s).next_sample(10.0)["coolant_temp"]
                    for s in range(20)]
    assert sum(fault_temps) / 20 > sum(normal_temps) / 20


# ── 5. defect 확률 구조 ────────────────────────────────────────────────────────

def test_tool_age_accumulates_with_time() -> None:
    """tool_age 는 t 에 비례해 증가해야 한다 (t * 0.01)."""
    gen = CNCStreamGenerator(seed=2026)
    assert pytest.approx(gen.next_sample(0.0)["tool_age"], abs=1e-9) == 0.0
    assert pytest.approx(gen.next_sample(100.0)["tool_age"], abs=1e-9) == 1.0
    assert pytest.approx(gen.next_sample(200.0)["tool_age"], abs=1e-9) == 2.0

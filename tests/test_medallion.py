"""DuckDB Mini-Medallion 검증 — PRISM Phase 4."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.orchestration.medallion import create_medallion_views, get_medallion_stats
from src.orchestration.storage import StorageDB


# ── helpers ───────────────────────────────────────────────────────────────────


def _cnc_row(ts: datetime, machine_id: str = "CNC-01", **overrides) -> dict:
    base = {
        "ts": ts,
        "machine_id": machine_id,
        "tool_age": 120.0,
        "spindle_rpm": 8500.0,
        "coolant_temp": 24.0,
        "vibration_xyz": 0.42,
        "thermal_drift": 0.08,
        "dimension_dev": 0.012,
        "defect": False,
    }
    base.update(overrides)
    return base


def _db_with_rows(rows: list[dict]) -> StorageDB:
    db = StorageDB(":memory:")
    db.open()
    db.write_cnc(rows)
    create_medallion_views(db)
    return db


# ── 1. 멱등성 ─────────────────────────────────────────────────────────────────


def test_create_medallion_views_idempotent():
    """create_medallion_views 를 두 번 호출해도 에러 없이 동일 view 유지."""
    ts = datetime(2026, 5, 22, 3, 0, 0)
    with StorageDB(":memory:") as db:
        db.write_cnc([_cnc_row(ts)])
        create_medallion_views(db)
        create_medallion_views(db)  # 두 번째 호출 — CREATE OR REPLACE 여야 함
        rows = db.query("SELECT * FROM bronze_cnc_raw")
        assert len(rows) == 1


# ── 2. 3 VIEW 모두 존재 ────────────────────────────────────────────────────────


def test_all_three_views_exist():
    """bronze / silver / gold 3 view 가 DuckDB 카탈로그에 등록된다."""
    ts = datetime(2026, 5, 22, 3, 0, 0)
    with StorageDB(":memory:") as db:
        db.write_cnc([_cnc_row(ts)])
        create_medallion_views(db)
        view_names = {
            r["table_name"]
            for r in db.query(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_type = 'VIEW'"
            )
        }
        assert "bronze_cnc_raw" in view_names
        assert "silver_cnc_validated" in view_names
        assert "gold_cnc_window_stats" in view_names


# ── 3. silver NULL fill ────────────────────────────────────────────────────────


def test_silver_fills_null_coolant_temp():
    """silver_cnc_validated 는 coolant_temp NULL row 를 median 으로 fill 한다."""
    base_ts = datetime(2026, 5, 22, 3, 0, 0)
    from datetime import timedelta

    rows = [
        _cnc_row(base_ts + timedelta(seconds=i), coolant_temp=20.0 + i)
        for i in range(4)
    ]
    # 한 row 에 NULL 주입
    rows.append(_cnc_row(base_ts + timedelta(seconds=10), coolant_temp=None))

    with StorageDB(":memory:") as db:
        db.write_cnc(rows)
        create_medallion_views(db)
        silver_rows = db.query("SELECT coolant_temp FROM silver_cnc_validated")
        # NULL 이 없어야 한다
        assert all(r["coolant_temp"] is not None for r in silver_rows), (
            "silver 에 NULL coolant_temp row 남아있음"
        )


def test_silver_fills_null_tool_age():
    """silver_cnc_validated 는 tool_age NULL row 를 median 으로 fill 한다."""
    from datetime import timedelta

    base_ts = datetime(2026, 5, 22, 4, 0, 0)
    rows = [_cnc_row(base_ts + timedelta(seconds=i), tool_age=100.0 + i) for i in range(4)]
    rows.append(_cnc_row(base_ts + timedelta(seconds=10), tool_age=None))

    with StorageDB(":memory:") as db:
        db.write_cnc(rows)
        create_medallion_views(db)
        silver_rows = db.query("SELECT tool_age FROM silver_cnc_validated")
        assert all(r["tool_age"] is not None for r in silver_rows)


# ── 4. gold 5분 window 집계 ───────────────────────────────────────────────────


def test_gold_aggregates_into_5min_windows():
    """gold_cnc_window_stats 는 5분 tumbling window 로 집계한다.

    2개의 서로 다른 5분 버킷에 row 를 넣고 Gold 가 2 행을 반환하는지 검증.
    """
    from datetime import timedelta

    # window 1: 03:00~03:04
    # window 2: 03:05~03:09  → 다른 bucket
    from datetime import timedelta as _td

    base1 = datetime(2026, 5, 22, 3, 0, 0)
    win1_rows = [
        _cnc_row(base1 + _td(seconds=i * 30), spindle_rpm=8000.0)
        for i in range(8)  # 8 rows in 03:00~03:03:30
    ]
    base2 = datetime(2026, 5, 22, 3, 5, 0)
    win2_rows = [
        _cnc_row(base2 + _td(seconds=i * 30), spindle_rpm=8500.0)
        for i in range(4)  # 4 rows in 03:05~03:06:30
    ]

    with StorageDB(":memory:") as db:
        db.write_cnc(win1_rows + win2_rows)
        create_medallion_views(db)
        gold_rows = db.query(
            "SELECT window_start, row_count FROM gold_cnc_window_stats ORDER BY window_start"
        )
        assert len(gold_rows) == 2, f"예상 2 window, 실제 {len(gold_rows)}"
        assert gold_rows[0]["row_count"] == 8
        assert gold_rows[1]["row_count"] == 4


# ── 5. Bronze ≥ Silver ≥ Gold row count (압축 방향) ───────────────────────────


def test_bronze_silver_gold_row_count_compression():
    """집계 레이어로 올라갈수록 row count 가 줄거나 같아야 한다.

    Bronze = 원본 행 수
    Silver = 동일 행 수 (view 에서 1:1 변환)
    Gold   = 5분 window 집계 → 반드시 ≤ Bronze
    """
    from datetime import timedelta

    # 21 rows (7 per bucket), 서로 다른 3개 5분 bucket
    rows = []
    for bucket in range(3):
        base_bucket = datetime(2026, 5, 22, 3, bucket * 5, 0)
        for sec in range(7):
            rows.append(
                _cnc_row(
                    base_bucket + timedelta(seconds=sec * 30),
                    spindle_rpm=8000.0 + bucket * 100,
                )
            )

    with StorageDB(":memory:") as db:
        db.write_cnc(rows)
        create_medallion_views(db)
        stats = get_medallion_stats(db)

    b = stats["bronze"]["row_count"]
    s = stats["silver"]["row_count"]
    g = stats["gold"]["row_count"]

    assert b >= s, f"Bronze({b}) < Silver({s})"
    assert s >= g, f"Silver({s}) < Gold({g})"
    assert g <= b, f"Gold({g}) > Bronze({b})"
    assert g == 3, f"3 window 예상, 실제 {g}"


# ── 6. get_medallion_stats 반환 구조 ─────────────────────────────────────────


def test_get_medallion_stats_keys():
    """get_medallion_stats 가 bronze / silver / gold 키와 row_count / latest_ts 를 반환."""
    ts = datetime(2026, 5, 22, 3, 0, 0)
    with StorageDB(":memory:") as db:
        db.write_cnc([_cnc_row(ts)])
        create_medallion_views(db)
        stats = get_medallion_stats(db)

    for layer in ("bronze", "silver", "gold"):
        assert layer in stats, f"stats 에 '{layer}' 키 없음"
        assert "row_count" in stats[layer]
        assert "latest_ts" in stats[layer]

    assert stats["bronze"]["row_count"] == 1
    assert stats["silver"]["row_count"] == 1
    assert stats["bronze"]["latest_ts"] is not None

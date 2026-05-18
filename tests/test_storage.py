"""DuckDB storage 검증 (사용자 로드맵 5/18 야간)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.orchestration.storage import (
    CNC_COLS,
    ROBOT_COLS,
    StorageDB,
    default_path,
)


def _robot_row(ts: datetime, robot_id: str = "ROBOT-00001", motor_temp: float = 85.0) -> dict:
    return {
        "ts": ts,
        "robot_id": robot_id,
        "motor_temp": motor_temp,
        "current_load": 60.0,
        "battery_level": 75.0,
        "pos_x": 10.5,
        "pos_y": 20.3,
        "active_hours": 8.0,
        "fault_phase": "normal",
        "is_faulty": False,
    }


def _cnc_row(ts: datetime, machine_id: str = "CNC-01") -> dict:
    return {
        "ts": ts,
        "machine_id": machine_id,
        "tool_age": 120.5,
        "spindle_rpm": 8500.0,
        "coolant_temp": 24.3,
        "vibration_xyz": 0.42,
        "thermal_drift": 0.08,
        "dimension_dev": 0.012,
        "defect": False,
    }


# ── schema / lifecycle ─────────────────────────────────────────


def test_bootstrap_schema_in_memory():
    with StorageDB(":memory:") as db:
        tables = db.query(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        )
        names = {t["table_name"] for t in tables}
        assert "robot_telemetry" in names
        assert "cnc_telemetry" in names


def test_file_backed_creates_parent_dir(tmp_path: Path):
    nested = tmp_path / "nested" / "db.duckdb"
    with StorageDB(nested) as db:
        assert nested.exists() or nested.parent.exists()
        assert db.count("robot_telemetry") == 0


def test_context_manager_closes():
    db = StorageDB(":memory:")
    with db:
        db.write_robot([_robot_row(datetime(2026, 5, 18, 10, 0))])
    with pytest.raises(RuntimeError):
        db.query("SELECT 1")


# ── write_robot ────────────────────────────────────────────────


def test_write_robot_inserts_rows():
    with StorageDB(":memory:") as db:
        n = db.write_robot([
            _robot_row(datetime(2026, 5, 18, 10, 0), "ROBOT-00018"),
            _robot_row(datetime(2026, 5, 18, 10, 1), "ROBOT-00011"),
        ])
        assert n == 2
        assert db.count("robot_telemetry") == 2


def test_write_robot_columns_present():
    with StorageDB(":memory:") as db:
        db.write_robot([_robot_row(datetime(2026, 5, 18), motor_temp=99.9)])
        row = db.query("SELECT robot_id, motor_temp, fault_phase FROM robot_telemetry")[0]
        assert row["robot_id"] == "ROBOT-00001"
        assert row["motor_temp"] == 99.9
        assert row["fault_phase"] == "normal"


def test_write_robot_empty_noop():
    with StorageDB(":memory:") as db:
        assert db.write_robot([]) == 0
        assert db.count("robot_telemetry") == 0


# ── write_cnc ──────────────────────────────────────────────────


def test_write_cnc_inserts_dowhy_nodes():
    with StorageDB(":memory:") as db:
        n = db.write_cnc([
            _cnc_row(datetime(2026, 5, 22, 3, 0), "CNC-01"),
            _cnc_row(datetime(2026, 5, 22, 3, 1), "CNC-01"),
        ])
        assert n == 2
        # 6-Node DAG 컬럼 전부 존재 (tool_age ~ defect).
        row = db.query("SELECT * FROM cnc_telemetry LIMIT 1")[0]
        for col in ("tool_age", "spindle_rpm", "coolant_temp", "vibration_xyz",
                    "thermal_drift", "dimension_dev", "defect"):
            assert col in row


# ── determinism (verification gate prerequisite) ───────────────


def test_table_sha256_deterministic():
    """동일 입력 → 동일 SHA256. C4 verify_demo_determinism metric #2 prerequisite."""
    rows = [_robot_row(datetime(2026, 5, 22, 3, i), f"R-{i:03}") for i in range(5)]

    h1, h2 = None, None
    for target in (h1, h2):  # noqa: B007  (loop is just for readability)
        pass
    with StorageDB(":memory:") as db:
        db.write_robot(rows)
        h1 = db.table_sha256("robot_telemetry")
    with StorageDB(":memory:") as db:
        db.write_robot(rows)
        h2 = db.table_sha256("robot_telemetry")
    assert h1 == h2


def test_table_sha256_differs_on_content_change():
    with StorageDB(":memory:") as db:
        db.write_robot([_robot_row(datetime(2026, 5, 22, 3, 0), motor_temp=80.0)])
        h1 = db.table_sha256("robot_telemetry")
    with StorageDB(":memory:") as db:
        db.write_robot([_robot_row(datetime(2026, 5, 22, 3, 0), motor_temp=90.0)])
        h2 = db.table_sha256("robot_telemetry")
    assert h1 != h2


# ── default_path env ───────────────────────────────────────────


def test_default_path_demo_mode(monkeypatch):
    monkeypatch.setenv("PRISM_MODE", "demo")
    assert default_path() == "data/prism_demo.duckdb"


def test_default_path_dev_mode(monkeypatch):
    monkeypatch.setenv("PRISM_MODE", "dev")
    assert default_path() == ":memory:"
    monkeypatch.delenv("PRISM_MODE", raising=False)
    assert default_path() == ":memory:"


# ── 컬럼 const sanity ─────────────────────────────────────────


def test_robot_cols_const_matches_schema_keys():
    sample = _robot_row(datetime(2026, 5, 18))
    assert set(ROBOT_COLS) == set(sample.keys())


def test_cnc_cols_const_matches_schema_keys():
    sample = _cnc_row(datetime(2026, 5, 22))
    assert set(CNC_COLS) == set(sample.keys())


# ── SQL injection 방어 (D-3 보안 M2 fix) ──────────────────────────


def test_write_rows_rejects_invalid_table(tmp_path):
    db_path = tmp_path / "test.duckdb"
    with StorageDB(str(db_path)) as db:
        with pytest.raises(ValueError, match="unknown table"):
            db._write_rows("malicious; DROP TABLE robot_telemetry;", ROBOT_COLS, [{}])


def test_count_rejects_invalid_table(tmp_path):
    db_path = tmp_path / "test.duckdb"
    with StorageDB(str(db_path)) as db:
        with pytest.raises(ValueError, match="unknown table"):
            db.count("system_tables")


def test_table_sha256_rejects_invalid_table(tmp_path):
    db_path = tmp_path / "test.duckdb"
    with StorageDB(str(db_path)) as db:
        with pytest.raises(ValueError, match="unknown table"):
            db.table_sha256("DROP_TABLE_HACK")


def test_table_sha256_rejects_invalid_order_by(tmp_path):
    db_path = tmp_path / "test.duckdb"
    with StorageDB(str(db_path)) as db:
        with pytest.raises(ValueError, match="unknown order_by"):
            db.table_sha256("robot_telemetry", order_by="1; SELECT * FROM secrets")

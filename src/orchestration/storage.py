"""DuckDB in-process storage (사용자 로드맵 5/18 야간 + 기획서 Lightweight Stack).

기획서 차별화: "노트북 1대 in-process, 운영 비용 월 $10-20". 따라서 KDS/Firehose/Athena
대신 DuckDB single-file 또는 :memory:.

Schemas:
- robot_telemetry — AI4I 시드 호환 (`src/generator/_record.py` 출력 1:1).
- cnc_telemetry   — 6-Node DoWhy DAG 노드 (tool_age, spindle_rpm, coolant_temp,
                     vibration_xyz, thermal_drift, dimension_dev, defect).

PRISM_MODE=demo 일 때 path = `data/prism_demo.duckdb` (재현성 + 시연 빠른 startup).
dev 모드는 `:memory:` 가 default.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Iterable

import duckdb

ROBOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS robot_telemetry (
    ts TIMESTAMP,
    robot_id VARCHAR NOT NULL,
    motor_temp DOUBLE,
    current_load DOUBLE,
    battery_level DOUBLE,
    pos_x DOUBLE,
    pos_y DOUBLE,
    active_hours DOUBLE,
    fault_phase VARCHAR,
    is_faulty BOOLEAN
);
"""

CNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS cnc_telemetry (
    ts TIMESTAMP,
    machine_id VARCHAR NOT NULL,
    tool_age DOUBLE,
    spindle_rpm DOUBLE,
    coolant_temp DOUBLE,
    vibration_xyz DOUBLE,
    thermal_drift DOUBLE,
    dimension_dev DOUBLE,
    defect BOOLEAN
);
"""

ROBOT_COLS = (
    "ts", "robot_id", "motor_temp", "current_load", "battery_level",
    "pos_x", "pos_y", "active_hours", "fault_phase", "is_faulty",
)
CNC_COLS = (
    "ts", "machine_id", "tool_age", "spindle_rpm", "coolant_temp",
    "vibration_xyz", "thermal_drift", "dimension_dev", "defect",
)


def default_path() -> str:
    """PRISM_MODE=demo → data/prism_demo.duckdb, else :memory:."""
    if os.environ.get("PRISM_MODE", "dev").lower() == "demo":
        return "data/prism_demo.duckdb"
    return ":memory:"


class StorageDB:
    """DuckDB connection wrapper. open() / close() / context manager 지원."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = str(path) if path is not None else default_path()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None

    def open(self) -> "StorageDB":
        self._conn = duckdb.connect(self.path)
        self._conn.execute(ROBOT_SCHEMA)
        self._conn.execute(CNC_SCHEMA)
        return self

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "StorageDB":
        return self.open()

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            raise RuntimeError("StorageDB not opened. Call open() or use context manager.")
        return self._conn

    # ── write ──────────────────────────────────────────────────

    def _write_rows(self, table: str, cols: tuple[str, ...], rows: Iterable[dict]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        placeholders = ",".join("?" for _ in cols)
        sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
        values = [tuple(r.get(c) for c in cols) for r in rows]
        self.conn.executemany(sql, values)
        return len(values)

    def write_robot(self, records: Iterable[dict]) -> int:
        """robot_telemetry 적재. records 각 dict 는 ROBOT_COLS 키를 포함."""
        return self._write_rows("robot_telemetry", ROBOT_COLS, records)

    def write_cnc(self, records: Iterable[dict]) -> int:
        """cnc_telemetry 적재. records 각 dict 는 CNC_COLS 키를 포함."""
        return self._write_rows("cnc_telemetry", CNC_COLS, records)

    # ── read ───────────────────────────────────────────────────

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = self.conn.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def count(self, table: str) -> int:
        return self.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]

    def table_sha256(self, table: str, order_by: str = "ts") -> str:
        """결정성 검증용. ORDER BY ts → row 순서 고정 → SHA256."""
        rows = self.query(f"SELECT * FROM {table} ORDER BY {order_by}")
        blob = "\n".join(repr(sorted(r.items())) for r in rows).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

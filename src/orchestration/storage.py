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

# SQL injection 방어 (D-3 보안 M2): caller 가 외부 입력으로 table/order_by 라우팅 시
# f-string 보간 (line 109, 130, 134) 으로 인한 회귀 위험 차단.
_ALLOWED_TABLES = frozenset({"robot_telemetry", "cnc_telemetry"})
_ALLOWED_ORDER_COLS = frozenset({"ts", "robot_id", "machine_id"})


def _assert_table(table: str) -> None:
    if table not in _ALLOWED_TABLES:
        raise ValueError(
            f"unknown table: {table!r} (allowed: {sorted(_ALLOWED_TABLES)})"
        )


def _assert_order_by(order_by: str) -> None:
    if order_by not in _ALLOWED_ORDER_COLS:
        raise ValueError(
            f"unknown order_by: {order_by!r} (allowed: {sorted(_ALLOWED_ORDER_COLS)})"
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
        _assert_table(table)
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
        _assert_table(table)
        return self.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]

    def table_sha256(self, table: str, order_by: str = "ts") -> str:
        """결정성 검증용. ORDER BY ts → row 순서 고정 → SHA256.

        table/order_by 는 whitelist 검증 (M2 SQL injection 방어).
        """
        _assert_table(table)
        _assert_order_by(order_by)
        rows = self.query(f"SELECT * FROM {table} ORDER BY {order_by}")
        blob = "\n".join(repr(sorted(r.items())) for r in rows).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    # ── DataSource Protocol 구현 (production 어댑터 인터페이스) ──────────
    #
    # PRISM AI 레이어가 demo↔production 양쪽에서 동일하게 동작하려면 production
    # Athena Gold 스키마와 같은 컬럼 셰이프로 반환해야 한다. DuckDB demo 데이터는
    # per-tick 이라 Gold 의 일별 집계 컬럼을 즉석에서 계산.

    def query_robot_daily_stats(self, dt: str, limit: int = 1000):
        """Athena `gold_robot_daily_stats` 와 동일 컬럼 셰이프 반환 (DuckDB 즉석 집계).

        DataFrame 컬럼: robot_id, avg_motor_temp, max_motor_temp,
            battery_start, battery_end, battery_drain, active_hours,
            anomaly_record_count, max_temp_load_ratio, dominant_failure_type.
        """
        sql = """
            WITH base AS (
                SELECT robot_id, ts, motor_temp, current_load,
                       battery_level, active_hours, fault_phase
                FROM robot_telemetry
                WHERE CAST(ts AS DATE) = CAST(? AS DATE)
            )
            SELECT
                robot_id,
                AVG(motor_temp) AS avg_motor_temp,
                MAX(motor_temp) AS max_motor_temp,
                CAST(FIRST(battery_level ORDER BY ts ASC) AS INTEGER) AS battery_start,
                CAST(LAST(battery_level ORDER BY ts ASC) AS INTEGER) AS battery_end,
                CAST(FIRST(battery_level ORDER BY ts ASC)
                     - LAST(battery_level ORDER BY ts ASC) AS INTEGER) AS battery_drain,
                CAST(MAX(active_hours) AS INTEGER) AS active_hours,
                CAST(SUM(CASE WHEN motor_temp > 90 THEN 1 ELSE 0 END) AS INTEGER)
                    AS anomaly_record_count,
                MAX(CASE WHEN current_load > 0 THEN motor_temp / current_load END)
                    AS max_temp_load_ratio,
                MODE(fault_phase) AS dominant_failure_type
            FROM base
            GROUP BY robot_id
            LIMIT ?
        """
        import pandas as pd
        rows = self.query(sql, (dt, limit))
        return pd.DataFrame(rows)

    def query_robot_realtime(self, limit: int = 100):
        """legacy `silver_robot_telemetry` 와 동일 컬럼 셰이프 반환.

        DataFrame 컬럼: robot_id, pos_x, pos_y, battery_level, current_load,
            motor_temp, timestamp, failure_type.
        """
        sql = """
            SELECT robot_id, pos_x, pos_y,
                   CAST(battery_level AS INTEGER) AS battery_level,
                   CAST(current_load AS INTEGER) AS current_load,
                   motor_temp,
                   CAST(ts AS VARCHAR) AS timestamp,
                   fault_phase AS failure_type
            FROM robot_telemetry
            ORDER BY ts DESC
            LIMIT ?
        """
        import pandas as pd
        rows = self.query(sql, (limit,))
        return pd.DataFrame(rows)

    def query_cnc_telemetry(self, limit: int = 100):
        """CNC 텔레메트리 — PRISM demo 전용 (production 에는 스키마 없음).

        DataFrame 컬럼: ts, machine_id, tool_age, spindle_rpm, coolant_temp,
            vibration_xyz, thermal_drift, dimension_dev, defect.
        """
        import pandas as pd
        rows = self.query(
            "SELECT * FROM cnc_telemetry ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        return pd.DataFrame(rows)

    def insert_cnc_row(self, row: dict) -> None:
        """CNC tick 1행 적재 (demo generator 전용)."""
        self.write_cnc([row])


# ── DataSource Protocol alias (PRISM_MODE=demo|live|dev 라우팅 목표) ─────
# 12개 기존 호출처 (`apps/prism_demo.py`, `apps/prism_operator_demo.py`,
# `medallion.py`, tests) 가 `from src.orchestration.storage import StorageDB`
# 그대로 사용할 수 있도록 alias 유지. 신규 코드는 `DuckDBDataSource` 권장.
DuckDBDataSource = StorageDB

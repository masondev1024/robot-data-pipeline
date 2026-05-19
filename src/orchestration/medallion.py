"""DuckDB Mini-Medallion Architecture (PRISM 본선 Phase 4).

Bronze → Silver → Gold 3-layer view — 실제 데이터 복사 없음 (VIEW 전용).

Bronze : cnc_telemetry 그대로
Silver : NULL fill (median) + type cast
Gold   : 5분 window 집계 (avg / max / min / stddev_pop)
"""

from __future__ import annotations

from src.orchestration.storage import StorageDB

# ── VIEW DDL ──────────────────────────────────────────────────────────────────

_BRONZE_DDL = """
CREATE OR REPLACE VIEW bronze_cnc_raw AS
SELECT
    ts,
    machine_id,
    tool_age,
    spindle_rpm,
    coolant_temp,
    vibration_xyz,
    thermal_drift,
    dimension_dev,
    defect
FROM cnc_telemetry;
"""

# Silver: NULL 컬럼은 같은 machine_id 전체 median 으로 fill.
# DuckDB MEDIAN() over (PARTITION BY machine_id) 을 COALESCE 로 감싼다.
_SILVER_DDL = """
CREATE OR REPLACE VIEW silver_cnc_validated AS
SELECT
    CAST(ts AS TIMESTAMP)                                                     AS ts,
    CAST(machine_id AS VARCHAR)                                               AS machine_id,
    COALESCE(
        tool_age,
        MEDIAN(tool_age) OVER (PARTITION BY machine_id)
    )                                                                         AS tool_age,
    COALESCE(
        spindle_rpm,
        MEDIAN(spindle_rpm) OVER (PARTITION BY machine_id)
    )                                                                         AS spindle_rpm,
    COALESCE(
        coolant_temp,
        MEDIAN(coolant_temp) OVER (PARTITION BY machine_id)
    )                                                                         AS coolant_temp,
    COALESCE(
        vibration_xyz,
        MEDIAN(vibration_xyz) OVER (PARTITION BY machine_id)
    )                                                                         AS vibration_xyz,
    COALESCE(
        thermal_drift,
        MEDIAN(thermal_drift) OVER (PARTITION BY machine_id)
    )                                                                         AS thermal_drift,
    COALESCE(
        dimension_dev,
        MEDIAN(dimension_dev) OVER (PARTITION BY machine_id)
    )                                                                         AS dimension_dev,
    COALESCE(defect, FALSE)                                                   AS defect
FROM cnc_telemetry;
"""

# Gold: 5분(300초) tumbling window 집계.
# DuckDB time_bucket(INTERVAL '5 minutes', ts) 로 window 경계를 통일.
_GOLD_DDL = """
CREATE OR REPLACE VIEW gold_cnc_window_stats AS
SELECT
    time_bucket(INTERVAL '5 minutes', ts)  AS window_start,
    machine_id,
    COUNT(*)                               AS row_count,
    AVG(tool_age)                          AS avg_tool_age,
    MAX(tool_age)                          AS max_tool_age,
    MIN(tool_age)                          AS min_tool_age,
    STDDEV_POP(tool_age)                   AS std_tool_age,
    AVG(spindle_rpm)                       AS avg_spindle_rpm,
    MAX(spindle_rpm)                       AS max_spindle_rpm,
    MIN(spindle_rpm)                       AS min_spindle_rpm,
    STDDEV_POP(spindle_rpm)                AS std_spindle_rpm,
    AVG(coolant_temp)                      AS avg_coolant_temp,
    MAX(coolant_temp)                      AS max_coolant_temp,
    MIN(coolant_temp)                      AS min_coolant_temp,
    STDDEV_POP(coolant_temp)               AS std_coolant_temp,
    AVG(vibration_xyz)                     AS avg_vibration_xyz,
    MAX(vibration_xyz)                     AS max_vibration_xyz,
    MIN(vibration_xyz)                     AS min_vibration_xyz,
    STDDEV_POP(vibration_xyz)              AS std_vibration_xyz,
    SUM(CAST(defect AS INTEGER))           AS defect_count,
    MAX(ts)                                AS latest_ts
FROM silver_cnc_validated
GROUP BY
    time_bucket(INTERVAL '5 minutes', ts),
    machine_id;
"""

_VIEWS = ("bronze_cnc_raw", "silver_cnc_validated", "gold_cnc_window_stats")


# ── public API ────────────────────────────────────────────────────────────────

def create_medallion_views(db: StorageDB) -> None:
    """Bronze / Silver / Gold VIEW 를 멱등으로 생성 (CREATE OR REPLACE).

    실제 데이터 복사 없음 — VIEW 정의만 DuckDB 카탈로그에 등록.
    """
    db.conn.execute(_BRONZE_DDL)
    db.conn.execute(_SILVER_DDL)
    db.conn.execute(_GOLD_DDL)


def get_medallion_stats(db: StorageDB) -> dict:
    """각 medallion layer 의 row count 와 최신 ts 를 반환.

    Returns:
        {
            "bronze": {"row_count": int, "latest_ts": str | None},
            "silver": {"row_count": int, "latest_ts": str | None},
            "gold":   {"row_count": int, "latest_ts": str | None},
        }
    """
    def _layer_stats(view: str) -> dict:
        rows = db.query(f"SELECT COUNT(*) AS n, MAX(ts) AS latest FROM {view}")  # noqa: S608
        row = rows[0] if rows else {"n": 0, "latest": None}
        return {
            "row_count": int(row["n"]),
            "latest_ts": str(row["latest"]) if row["latest"] is not None else None,
        }

    # Gold view 에는 ts 컬럼이 없고 latest_ts がある
    def _gold_stats() -> dict:
        rows = db.query(
            "SELECT COUNT(*) AS n, MAX(latest_ts) AS latest FROM gold_cnc_window_stats"
        )
        row = rows[0] if rows else {"n": 0, "latest": None}
        return {
            "row_count": int(row["n"]),
            "latest_ts": str(row["latest"]) if row["latest"] is not None else None,
        }

    return {
        "bronze": _layer_stats("bronze_cnc_raw"),
        "silver": _layer_stats("silver_cnc_validated"),
        "gold": _gold_stats(),
    }

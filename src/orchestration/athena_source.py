"""Athena DataSource — production source of truth.

PRISM_MODE=production 일 때 `datasource.get_data_source()` 가 반환하는 구현체.
`src/common/athena.py` 의 `run_query()` 헬퍼를 통과해 Gold/Silver 테이블 read.

가드레일 (CLAUDE.md §1.E):
- 파티션 프루닝 필수 — `dt = DATE '...'` WHERE 절 + partition projection 활용
- `dt = D-1` hard-code 금지 — caller 가 dt 명시 (FastAPI portal 책임)
- WHERE 절 타입 정합 — dt 는 DATE, 다른 partition 은 varchar

CNC 메서드는 영구 NotImplementedError (CNC 는 demo-only, legacy 파이프라인에 스키마 없음).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    import pandas as pd


DEFAULT_WORKGROUP = "robot-telemetry-workgroup"
DEFAULT_DATABASE = "robot_telemetry_db"
DEFAULT_OUTPUT_LOCATION = "s3://robot-telemetry-data/project-athena-results/"


# Gold/Silver column → Python type 변환표. Athena get_query_results 는 모든 값을
# VarCharValue 문자열로 반환하므로 supervisor·agents 가 numeric 연산할 수 있도록
# 명시적 캐스팅.
_GOLD_COL_TYPES: dict[str, Callable[[str], Any]] = {
    "robot_id": str,
    "avg_motor_temp": float,
    "max_motor_temp": float,
    "battery_start": int,
    "battery_end": int,
    "battery_drain": int,
    "active_hours": int,
    "anomaly_record_count": int,
    "max_temp_load_ratio": float,
    "dominant_failure_type": str,
}

_SILVER_COL_TYPES: dict[str, Callable[[str], Any]] = {
    "robot_id": str,
    "pos_x": float,
    "pos_y": float,
    "battery_level": int,
    "current_load": int,
    "motor_temp": float,
    "timestamp": str,
    "failure_type": str,
}


def _cast_rows(rows: list[dict], col_types: dict[str, Callable[[str], Any]]) -> list[dict]:
    """Athena 문자열 row 를 type-cast (빈 문자열은 None)."""
    out: list[dict] = []
    for row in rows:
        casted: dict[str, Any] = {}
        for col, cast in col_types.items():
            raw = row.get(col, "")
            casted[col] = None if raw == "" else cast(raw)
        out.append(casted)
    return out


class AthenaDataSource:
    """Athena Gold/Silver 어댑터.

    Production supervisor 가 robot 5F (avg_motor_temp, max_motor_temp,
    battery_drain, active_hours, max_temp_load_ratio) 기반으로 동작하도록
    `gold_robot_daily_stats` 컬럼 그대로 반환.
    """

    def __init__(
        self,
        workgroup: str | None = None,
        database: str | None = None,
        output_location: str | None = None,
    ) -> None:
        self.workgroup = workgroup or os.environ.get("ATHENA_WORKGROUP", DEFAULT_WORKGROUP)
        self.database = database or os.environ.get("ATHENA_DATABASE", DEFAULT_DATABASE)
        self.output_location = output_location or os.environ.get(
            "ATHENA_OUTPUT_LOCATION", DEFAULT_OUTPUT_LOCATION
        )

    def _run(self, sql: str) -> list[dict]:
        from src.common.athena import run_query
        return run_query(
            sql,
            database=self.database,
            workgroup=self.workgroup,
            output_location=self.output_location,
        )

    def query_robot_daily_stats(self, dt: str, limit: int = 1000) -> "pd.DataFrame":
        """gold_robot_daily_stats partition `dt` read.

        Args:
            dt: 'YYYY-MM-DD' (partition projection key)
            limit: 최대 row 수

        Returns:
            DataFrame columns (sql/gold_ddl.sql 매칭):
                robot_id, avg_motor_temp, max_motor_temp,
                battery_start, battery_end, battery_drain,
                active_hours, anomaly_record_count,
                max_temp_load_ratio, dominant_failure_type
        """
        sql = f"""
            SELECT robot_id, avg_motor_temp, max_motor_temp,
                   battery_start, battery_end, battery_drain,
                   active_hours, anomaly_record_count,
                   max_temp_load_ratio, dominant_failure_type
            FROM gold_robot_daily_stats
            WHERE dt = DATE '{dt}'
            LIMIT {int(limit)}
        """
        rows = self._run(sql)
        import pandas as pd
        return pd.DataFrame(_cast_rows(rows, _GOLD_COL_TYPES))

    def query_robot_realtime(self, limit: int = 100) -> "pd.DataFrame":
        """silver_robot_telemetry 최신 N rows read.

        Silver partition 은 `dt DATE`. 최근 7일 윈도우 안에서 `MAX(dt)` 서브쿼리로
        fallback (CLAUDE.md §1.E — 비용 셧다운 다음날 D-1 부재 회피).

        Returns:
            DataFrame columns (sql/silver_ddl.sql 매칭):
                robot_id, pos_x, pos_y, battery_level, current_load,
                motor_temp, timestamp, failure_type
        """
        sql = f"""
            SELECT robot_id, pos_x, pos_y, battery_level, current_load,
                   motor_temp, "timestamp", failure_type
            FROM silver_robot_telemetry
            WHERE dt = (
                SELECT MAX(dt) FROM silver_robot_telemetry
                WHERE dt >= current_date - INTERVAL '7' DAY
            )
            ORDER BY "timestamp" DESC
            LIMIT {int(limit)}
        """
        rows = self._run(sql)
        import pandas as pd
        return pd.DataFrame(_cast_rows(rows, _SILVER_COL_TYPES))

    def query_cnc_telemetry(self, limit: int = 100) -> "pd.DataFrame":
        raise NotImplementedError(
            "AthenaDataSource.query_cnc_telemetry — CNC 는 PRISM demo 전용 기능. "
            "legacy KDS/Firehose/Athena 파이프라인에 CNC 스키마 없음. "
            "production 에서 CNC 가 필요하면 별도 스프린트 (KDS shard + Firehose + Athena DDL 신규)."
        )

    def insert_cnc_row(self, row: dict) -> None:
        raise NotImplementedError(
            "AthenaDataSource.insert_cnc_row — production 적재는 KDS producer 가 담당. "
            "CNC 는 demo 전용이므로 production 에서 호출되지 않아야 함."
        )

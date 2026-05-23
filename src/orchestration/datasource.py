"""DataSource Protocol — PRISM AI 레이어가 데이터 백엔드에 의존하지 않게 추상화.

Demo (PRISM_MODE=demo|live|dev)
    → DuckDBDataSource (= storage.StorageDB alias)
    → 데이터 백엔드: DuckDB in-process (`data/prism_demo.duckdb`)

Production (PRISM_MODE=production)
    → AthenaDataSource (스텁, 실 구현은 별도 스프린트)
    → 데이터 백엔드: Athena Gold table (`gold_robot_daily_stats`)

PRISM 인과추론 supervisor·agents 는 DataSource Protocol 만 알면 demo↔production
양쪽에서 동일하게 동작. CNC 텔레메트리는 PRISM demo 전용 기능 — legacy 파이프라인에
스키마가 없으므로 production 에서는 NotImplementedError.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import pandas as pd


@runtime_checkable
class DataSource(Protocol):
    """PRISM AI 레이어 ↔ 데이터 백엔드 사이 계약.

    구현체:
        - DuckDBDataSource: demo (storage.py)
        - AthenaDataSource: production (athena_source.py, 스텁)

    제약:
        - 메서드 시그니처 변경은 두 구현체 동시 갱신 필수.
        - production 모드에서 CNC 메서드 호출은 NotImplementedError 정상.
    """

    def query_robot_daily_stats(
        self, dt: str, limit: int = 1000
    ) -> "pd.DataFrame":
        """일별 로봇 집계 — production canonical schema (gold_robot_daily_stats).

        Args:
            dt: 'YYYY-MM-DD' 파티션 키 (Athena partition projection).
            limit: 최대 row 수.

        Returns 컬럼:
            robot_id, avg_motor_temp, max_motor_temp, battery_start,
            battery_end, battery_drain, active_hours,
            anomaly_record_count, max_temp_load_ratio, dominant_failure_type.
        """
        ...

    def query_robot_realtime(self, limit: int = 100) -> "pd.DataFrame":
        """실시간 로봇 텔레메트리 — Athena silver 또는 KDS 직접 consume.

        Returns 컬럼:
            robot_id, pos_x, pos_y, battery_level, current_load,
            motor_temp, timestamp, failure_type.
        """
        ...

    def query_cnc_telemetry(self, limit: int = 100) -> "pd.DataFrame":
        """CNC 텔레메트리 — PRISM demo 전용 기능.

        Production 구현체는 NotImplementedError (legacy 파이프라인에 CNC 스키마 없음).
        """
        ...

    def insert_cnc_row(self, row: dict) -> None:
        """CNC tick 적재 — demo generator (`cnc_stream.py`) 전용.

        Production 에서는 KDS producer 가 별도로 담당하므로 NotImplementedError.
        """
        ...


def get_data_source(mode: str | None = None) -> DataSource:
    """PRISM_MODE → DataSource 라우팅 팩토리.

    Args:
        mode: 'demo' | 'live' | 'dev' | 'production'. None 이면 환경변수.

    Returns:
        production → AthenaDataSource (스텁)
        그 외      → DuckDBDataSource (= StorageDB)
    """
    mode = (mode or os.environ.get("PRISM_MODE", "demo")).lower()
    if mode == "production":
        from src.orchestration.athena_source import AthenaDataSource
        return AthenaDataSource()
    from src.orchestration.storage import DuckDBDataSource
    return DuckDBDataSource()

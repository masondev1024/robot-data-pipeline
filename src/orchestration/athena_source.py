"""Athena DataSource — production source of truth (스텁).

PRISM_MODE=production 일 때 `datasource.get_data_source()` 가 반환하는 구현체.
실 구현은 별도 스프린트:

    boto3 athena client → StartQueryExecution → GetQueryResults
    또는 awswrangler / pyathena 사용

현재 단계 = "연결 준비". 메서드별 명시적 NotImplementedError 로 production 오인 호출 차단.

참조:
    - 스키마: sql/gold_ddl.sql, sql/silver_ddl.sql
    - 인터페이스 계약: docs/INTERFACE.md
    - 설계: docs/superpowers/specs/2026-05-23-prism-production-integration-design.md
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


class AthenaDataSource:
    """Athena Gold/Silver 어댑터 스텁.

    실 구현 가이드 (별도 스프린트):
        - boto3 athena client + StartQueryExecution polling
        - S3 query result location 설정 (terraform athena_workgroup output)
        - partition projection 활용 (`dt = '{dt}'` WHERE 절)
        - SageMaker endpoint URL은 환경변수 또는 SSM 에서 read
    """

    def __init__(self, workgroup: str | None = None, database: str | None = None) -> None:
        self.workgroup = workgroup
        self.database = database or "robot_telemetry_db"

    def query_robot_daily_stats(self, dt: str, limit: int = 1000) -> "pd.DataFrame":
        raise NotImplementedError(
            "AthenaDataSource.query_robot_daily_stats — production schema 연결 미구현. "
            "별도 스프린트에서 sql/gold_ddl.sql 의 gold_robot_daily_stats 를 boto3 athena 로 read. "
            "현재는 DuckDBDataSource (PRISM_MODE=demo) 만 사용 가능."
        )

    def query_robot_realtime(self, limit: int = 100) -> "pd.DataFrame":
        raise NotImplementedError(
            "AthenaDataSource.query_robot_realtime — production schema 연결 미구현. "
            "별도 스프린트에서 silver_robot_telemetry 또는 KDS shard iterator 로 read. "
            "현재는 DuckDBDataSource (PRISM_MODE=demo) 만 사용 가능."
        )

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

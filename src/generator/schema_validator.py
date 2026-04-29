"""Glue Schema Registry 기반 record 필드 검증.

upstream(예: 시뮬레이터 코드 변경, CSV 컬럼 추가)에서 필드명이 바뀌거나 빠지면
파이프라인 전체가 silently broken 되는 사고를 막는다. 모듈 로드 시 Glue
Schema Registry에서 스키마를 1회 fetch하여 required 필드 set을 캐시.

운영상 비용: schema fetch 1회 + record당 set 차집합 1회. negligible.
"""
import json
import os
from typing import Optional

from src.common.aws import get_client


_required_fields: Optional[frozenset[str]] = None
_validation_failures: int = 0


def _fetch_required_fields() -> frozenset[str]:
    """Glue Schema Registry에서 robot-telemetry-schema의 required 필드 set 반환."""
    registry = os.environ.get("GLUE_SCHEMA_REGISTRY_NAME", "robot-telemetry-registry")
    schema = os.environ.get("GLUE_SCHEMA_NAME", "robot-telemetry-schema")

    response = get_client("glue").get_schema_version(
        SchemaId={"RegistryName": registry, "SchemaName": schema},
        SchemaVersionNumber={"LatestVersion": True},
    )
    schema_def = json.loads(response["SchemaDefinition"])
    return frozenset(schema_def.get("required", []))


def get_required_fields() -> frozenset[str]:
    """Cached required field set. 첫 호출 시 Glue에서 fetch."""
    global _required_fields
    if _required_fields is None:
        try:
            _required_fields = _fetch_required_fields()
            print(f"[schema_validator] Loaded {len(_required_fields)} required fields from Glue Schema Registry")
        except Exception as e:
            # Fail-open: Glue 접근 실패 시 record-level fallback set 사용 (파이프라인 정지 방지)
            print(f"[schema_validator] Glue fetch failed, using fallback: {str(e)}")
            _required_fields = frozenset({"robot_id", "timestamp"})
    return _required_fields


def validate_record(record: dict) -> bool:
    """필수 필드가 모두 있고 None이 아닌지 확인. False → drop."""
    global _validation_failures
    required = get_required_fields()
    missing = [k for k in required if record.get(k) is None]
    if missing:
        _validation_failures += 1
        if _validation_failures % 100 == 1:
            print(f"[schema_validator] missing fields: {missing} (total failures: {_validation_failures})")
        return False
    return True


def get_failure_count() -> int:
    return _validation_failures

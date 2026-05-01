"""Schema Registry SDK 기반 record 검증 단위 테스트 (Task 1.1 line 200).

Glue Schema Registry 에서 required 필드를 fetch 하여 캐시하고, validate_record 가
필수 필드 누락/failure_type enum 위반 시 drop 하는 로직 검증.

Mock 대상: src.common.aws.get_client → glue boto3 client. 실 Glue 호출 0건.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.generator import schema_validator


@pytest.fixture(autouse=True)
def _reset_module_state():
    """모듈 전역 캐시(_required_fields, _validation_failures) 테스트 격리."""
    schema_validator._required_fields = None
    schema_validator._validation_failures = 0
    yield
    schema_validator._required_fields = None
    schema_validator._validation_failures = 0


def _glue_mock(required_fields: list[str]) -> MagicMock:
    client = MagicMock()
    client.get_schema_version.return_value = {
        "SchemaDefinition": '{"required": ' + str(required_fields).replace("'", '"') + "}",
    }
    return client


class TestFetchRequiredFields:
    def test_returns_frozenset_from_glue_response(self):
        client = _glue_mock(["robot_id", "timestamp", "motor_temp"])
        with patch("src.generator.schema_validator.get_client", return_value=client):
            result = schema_validator._fetch_required_fields()
        assert result == frozenset({"robot_id", "timestamp", "motor_temp"})
        client.get_schema_version.assert_called_once()

    def test_calls_glue_with_registry_and_schema_names(self, monkeypatch):
        monkeypatch.setenv("GLUE_SCHEMA_REGISTRY_NAME", "custom-registry")
        monkeypatch.setenv("GLUE_SCHEMA_NAME", "custom-schema")
        client = _glue_mock(["robot_id"])
        with patch("src.generator.schema_validator.get_client", return_value=client):
            schema_validator._fetch_required_fields()
        call_kwargs = client.get_schema_version.call_args.kwargs
        assert call_kwargs["SchemaId"]["RegistryName"] == "custom-registry"
        assert call_kwargs["SchemaId"]["SchemaName"] == "custom-schema"
        assert call_kwargs["SchemaVersionNumber"] == {"LatestVersion": True}


class TestGetRequiredFieldsCaching:
    def test_first_call_fetches_from_glue(self):
        client = _glue_mock(["robot_id", "timestamp"])
        with patch("src.generator.schema_validator.get_client", return_value=client):
            result = schema_validator.get_required_fields()
        assert result == frozenset({"robot_id", "timestamp"})
        assert client.get_schema_version.call_count == 1

    def test_second_call_uses_cache(self):
        client = _glue_mock(["robot_id"])
        with patch("src.generator.schema_validator.get_client", return_value=client):
            schema_validator.get_required_fields()
            schema_validator.get_required_fields()
        assert client.get_schema_version.call_count == 1

    def test_glue_failure_fallback_to_minimal_set(self):
        client = MagicMock()
        client.get_schema_version.side_effect = RuntimeError("Glue API down")
        with patch("src.generator.schema_validator.get_client", return_value=client):
            result = schema_validator.get_required_fields()
        # Fail-open: 파이프라인 정지 방지를 위한 fallback set
        assert result == frozenset({"robot_id", "timestamp"})


class TestValidateRecord:
    def setup_method(self):
        # 캐시 직접 주입 — get_client mock 없이 검증 로직만 테스트
        schema_validator._required_fields = frozenset({"robot_id", "timestamp", "motor_temp"})

    def test_all_required_fields_present_returns_true(self):
        record = {"robot_id": "ROBOT-00001", "timestamp": "2026-05-01T00:00:00Z", "motor_temp": 75.0}
        assert schema_validator.validate_record(record) is True

    def test_missing_required_field_returns_false(self):
        record = {"robot_id": "ROBOT-00001", "timestamp": "2026-05-01T00:00:00Z"}
        assert schema_validator.validate_record(record) is False
        assert schema_validator.get_failure_count() == 1

    def test_none_value_treated_as_missing(self):
        record = {"robot_id": "ROBOT-00001", "timestamp": None, "motor_temp": 75.0}
        assert schema_validator.validate_record(record) is False

    def test_failure_type_none_value_passes(self):
        record = {
            "robot_id": "ROBOT-00001",
            "timestamp": "2026-05-01T00:00:00Z",
            "motor_temp": 75.0,
            "failure_type": None,
        }
        assert schema_validator.validate_record(record) is True

    @pytest.mark.parametrize("ft", ["NONE", "TWF", "HDF", "PWF", "OSF", "RNF"])
    def test_failure_type_valid_enum_passes(self, ft):
        record = {
            "robot_id": "ROBOT-00001",
            "timestamp": "2026-05-01T00:00:00Z",
            "motor_temp": 75.0,
            "failure_type": ft,
        }
        assert schema_validator.validate_record(record) is True

    @pytest.mark.parametrize("bad", ["INVALID", "twf", "OVERHEATED", ""])
    def test_failure_type_invalid_enum_returns_false(self, bad):
        record = {
            "robot_id": "ROBOT-00001",
            "timestamp": "2026-05-01T00:00:00Z",
            "motor_temp": 75.0,
            "failure_type": bad,
        }
        assert schema_validator.validate_record(record) is False

    def test_failure_count_accumulates(self):
        bad_record = {"robot_id": "ROBOT-00001"}  # missing timestamp + motor_temp
        for _ in range(3):
            schema_validator.validate_record(bad_record)
        assert schema_validator.get_failure_count() == 3

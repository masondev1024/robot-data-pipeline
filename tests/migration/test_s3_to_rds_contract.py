from __future__ import annotations

from src.migration.s3_to_rds_contract import (
    canonical_event_id,
    reconcile_counts,
    validate_batch,
)


def _record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "robot_id": "ROBOT-00001",
        "pos_x": 12.5,
        "pos_y": 33.2,
        "battery_level": 88.0,
        "current_load": 52.4,
        "motor_temp": 74.2,
        "timestamp": "2026-09-03T00:00:00Z",
        "failure_type": "NONE",
    }
    record.update(overrides)
    return record


def test_same_business_event_has_same_id_after_retries() -> None:
    first = canonical_event_id(_record())
    second = canonical_event_id(_record())

    assert first == second
    assert len(first) == 64


def test_batch_reports_rejects_and_exact_duplicates() -> None:
    accepted, rejected, report = validate_batch(
        [_record(), _record(), _record(battery_level=101)],
        "batch-20260903",
    )

    assert len(accepted) == 1
    assert len(rejected) == 1
    assert report.source_rows == 3
    assert report.accepted_rows == 1
    assert report.rejected_rows == 1
    assert report.duplicate_rows == 1
    assert report.status == "REJECTED"


def test_missing_required_field_is_rejected_without_partial_acceptance() -> None:
    record = _record()
    del record["motor_temp"]

    accepted, rejected, report = validate_batch([record], "batch-1")

    assert accepted == []
    assert rejected[0]["reason_code"] == "MISSING_REQUIRED"
    assert report.violations[0].field == "motor_temp"


def test_reconciliation_requires_source_and_stage_counts_to_match() -> None:
    _, _, report = validate_batch([_record(), _record(robot_id="ROBOT-00002")], "batch-1")

    reconciliation = reconcile_counts(report, staged_rows=2)

    assert reconciliation.is_reconciled is True
    assert reconciliation.as_dict()["is_reconciled"] is True

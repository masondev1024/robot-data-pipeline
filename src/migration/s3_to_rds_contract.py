"""Contract and deterministic validation for the robot Bronze-to-RDS lab.

The production Bronze schema is defined in ``terraform/modules/data_pipeline/glue.tf``.
This module deliberately has no Spark, AWS, or database dependency so the contract can
be tested locally and reused by a Glue job as an extra Python file.

The delivery guarantee is at-least-once.  ``event_id`` is deterministic, so a retry can
be safely staged again and deduplicated during the transactional promotion step.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


REQUIRED_FIELDS = (
    "robot_id",
    "pos_x",
    "pos_y",
    "battery_level",
    "current_load",
    "motor_temp",
    "timestamp",
    "failure_type",
)
FAILURE_TYPES = frozenset({"NONE", "HDF", "PWF", "OSF", "TWF", "RNF"})
NUMERIC_RANGES = {
    "pos_x": (-1_000_000.0, 1_000_000.0),
    "pos_y": (-1_000_000.0, 1_000_000.0),
    "battery_level": (0.0, 100.0),
    "current_load": (0.0, 100.0),
    "motor_temp": (-40.0, 200.0),
}


@dataclass(frozen=True)
class ContractViolation:
    """One row-level reason for rejecting a source record."""

    row_number: int
    code: str
    field: str
    message: str


@dataclass(frozen=True)
class BatchQualityReport:
    """Counts used for the audit record and reconciliation gate."""

    batch_id: str
    source_rows: int
    accepted_rows: int
    rejected_rows: int
    duplicate_rows: int
    violations: tuple[ContractViolation, ...]

    @property
    def status(self) -> str:
        return "REJECTED" if self.rejected_rows else "READY"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["violations"] = [asdict(item) for item in self.violations]
        payload["status"] = self.status
        return payload


@dataclass(frozen=True)
class Reconciliation:
    """A small, explicit count invariant for one migration attempt."""

    source_rows: int
    accepted_rows: int
    rejected_rows: int
    duplicate_rows: int
    staged_rows: int

    @property
    def is_reconciled(self) -> bool:
        return (
            self.source_rows == self.accepted_rows + self.rejected_rows + self.duplicate_rows
            and self.staged_rows == self.accepted_rows
        )

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "is_reconciled": self.is_reconciled}


def _parse_timestamp(value: Any) -> datetime:
    if value is None or str(value).strip() == "":
        raise ValueError("timestamp is required")

    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _finite_float(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    lower, upper = NUMERIC_RANGES[field]
    if not lower <= number <= upper:
        raise ValueError(f"{field} must be between {lower} and {upper}")
    return number


def _normalized_values(record: Mapping[str, Any]) -> dict[str, Any]:
    robot_id = str(record.get("robot_id", "")).strip()
    if not robot_id:
        raise ValueError("robot_id is required")
    if len(robot_id) > 128:
        raise ValueError("robot_id must be at most 128 characters")

    event_time = _parse_timestamp(record.get("timestamp"))
    normalized = {
        "robot_id": robot_id,
        "pos_x": _finite_float(record.get("pos_x"), "pos_x"),
        "pos_y": _finite_float(record.get("pos_y"), "pos_y"),
        "battery_level": _finite_float(record.get("battery_level"), "battery_level"),
        "current_load": _finite_float(record.get("current_load"), "current_load"),
        "motor_temp": _finite_float(record.get("motor_temp"), "motor_temp"),
        "timestamp": event_time.isoformat(),
        "failure_type": str(record.get("failure_type", "")).strip().upper(),
    }
    if normalized["failure_type"] not in FAILURE_TYPES:
        raise ValueError(f"failure_type must be one of {sorted(FAILURE_TYPES)}")
    return normalized


def canonical_event_id(record: Mapping[str, Any]) -> str:
    """Return the same ID for the same business event across retries."""

    normalized = _normalized_values(record)
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _missing_fields(record: Mapping[str, Any]) -> list[str]:
    return [field for field in REQUIRED_FIELDS if field not in record or record[field] is None]


def validate_batch(
    records: Sequence[Mapping[str, Any]],
    batch_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], BatchQualityReport]:
    """Validate and normalize a finite batch.

    Exact duplicates inside one source file are counted separately and only the first
    copy is accepted.  Invalid rows are returned with a safe, structured reason so a
    Glue job can write them to a reject prefix without leaking credentials.
    """

    if not batch_id.strip():
        raise ValueError("batch_id must not be empty")

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    violations: list[ContractViolation] = []
    seen_ids: set[str] = set()
    duplicate_rows = 0

    for row_number, raw in enumerate(records, start=1):
        missing = _missing_fields(raw)
        if missing:
            message = f"missing required fields: {', '.join(missing)}"
            violation = ContractViolation(row_number, "MISSING_REQUIRED", ",".join(missing), message)
            violations.append(violation)
            rejected.append({"row_number": row_number, "reason_code": violation.code, "reason": message, **dict(raw)})
            continue

        try:
            normalized = _normalized_values(raw)
            event_id = canonical_event_id(normalized)
        except ValueError as exc:
            message = str(exc)
            field = message.split(" ", 1)[0] if message else "record"
            violation = ContractViolation(row_number, "INVALID_VALUE", field, message)
            violations.append(violation)
            rejected.append({"row_number": row_number, "reason_code": violation.code, "reason": message, **dict(raw)})
            continue

        if event_id in seen_ids:
            duplicate_rows += 1
            continue

        seen_ids.add(event_id)
        accepted.append(
            {
                **normalized,
                "event_id": event_id,
                "batch_id": batch_id,
                "source_row_number": row_number,
            }
        )

    report = BatchQualityReport(
        batch_id=batch_id,
        source_rows=len(records),
        accepted_rows=len(accepted),
        rejected_rows=len(rejected),
        duplicate_rows=duplicate_rows,
        violations=tuple(violations),
    )
    return accepted, rejected, report


def reconcile_counts(
    report: BatchQualityReport,
    staged_rows: int,
) -> Reconciliation:
    """Build the count gate after the staging write has completed."""

    return Reconciliation(
        source_rows=report.source_rows,
        accepted_rows=report.accepted_rows,
        rejected_rows=report.rejected_rows,
        duplicate_rows=report.duplicate_rows,
        staged_rows=staged_rows,
    )

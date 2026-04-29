"""Athena query helpers — start, poll, paginate results.

Consolidates the polling state machine + result pagination duplicated across
api/main.py, dags/robot_daily_etl.py, and ml/train.py.
"""
import time
from typing import Optional

from src.common.aws import get_client


class AthenaState:
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TERMINAL_FAILURES = (FAILED, CANCELLED)


_POLL_INTERVAL_SEC = 2
_POLL_MAX_ATTEMPTS = 60  # 60 * 2s = 120s


def start_query(
    query: str,
    *,
    database: str,
    workgroup: Optional[str] = None,
    output_location: Optional[str] = None,
) -> str:
    client = get_client("athena")
    kwargs = {
        "QueryString": query,
        "QueryExecutionContext": {"Database": database},
    }
    if workgroup:
        kwargs["WorkGroup"] = workgroup
    if output_location:
        kwargs["ResultConfiguration"] = {"OutputLocation": output_location}
    return client.start_query_execution(**kwargs)["QueryExecutionId"]


def wait_for_query(execution_id: str) -> None:
    client = get_client("athena")
    for _ in range(_POLL_MAX_ATTEMPTS):
        result = client.get_query_execution(QueryExecutionId=execution_id)
        state = result["QueryExecution"]["Status"]["State"]
        if state == AthenaState.SUCCEEDED:
            return
        if state in AthenaState.TERMINAL_FAILURES:
            reason = result["QueryExecution"]["Status"].get("StateChangeReason", "unknown")
            raise RuntimeError(f"Athena query {state}: {reason}")
        time.sleep(_POLL_INTERVAL_SEC)
    raise TimeoutError(
        f"Athena query timed out after {_POLL_MAX_ATTEMPTS * _POLL_INTERVAL_SEC} seconds"
    )


def fetch_rows(execution_id: str) -> list[dict]:
    client = get_client("athena")
    paginator = client.get_paginator("get_query_results")
    rows: list[dict] = []
    columns: Optional[list[str]] = None
    for page in paginator.paginate(QueryExecutionId=execution_id):
        result_rows = page["ResultSet"]["Rows"]
        if columns is None:
            columns = [col["VarCharValue"] for col in result_rows[0]["Data"]]
            result_rows = result_rows[1:]
        for row in result_rows:
            values = [cell.get("VarCharValue", "") for cell in row["Data"]]
            rows.append(dict(zip(columns, values)))
    return rows


def run_query(
    query: str,
    *,
    database: str,
    workgroup: Optional[str] = None,
    output_location: Optional[str] = None,
) -> list[dict]:
    """One-shot: start + wait + fetch."""
    execution_id = start_query(
        query, database=database, workgroup=workgroup, output_location=output_location
    )
    wait_for_query(execution_id)
    return fetch_rows(execution_id)

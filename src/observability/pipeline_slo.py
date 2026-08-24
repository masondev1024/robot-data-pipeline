"""CloudWatch query and evaluation helpers for streaming SLOs.

This module deliberately has no AWS client dependency.  Query construction and
threshold evaluation can therefore be tested deterministically before a live
AWS environment exists, while the CLI is responsible only for the read-only
``GetMetricData`` call.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_ITERATOR_AGE_THRESHOLD_MILLISECONDS = 120_000
DEFAULT_FIREHOSE_FRESHNESS_THRESHOLD_SECONDS = 600
DEFAULT_SUCCESSFUL_PUTS_MINIMUM = 1
DEFAULT_WRITE_THROTTLE_MAXIMUM = 0


def _metric_query(
    *,
    query_id: str,
    namespace: str,
    metric_name: str,
    dimensions: list[dict[str, str]],
    period: int,
    statistic: str,
) -> dict[str, Any]:
    """Build one CloudWatch metric query with an explicit unit contract."""

    return {
        "Id": query_id,
        "MetricStat": {
            "Metric": {
                "Namespace": namespace,
                "MetricName": metric_name,
                "Dimensions": dimensions,
            },
            "Period": period,
            "Stat": statistic,
        },
        "ReturnData": True,
    }


def build_cloudwatch_queries(
    stream_name: str,
    firehose_name: str,
) -> list[dict[str, Any]]:
    """Return the AWS metrics used by the streaming SLO verifier.

    ``DeliveryToS3.Success`` is intentionally queried as ``Minimum``.  AWS
    defines it as a count of successful S3 put commands, not a 0-1 ratio.  The
    freshness budget is measured independently in seconds by
    ``DeliveryToS3.DataFreshness``.
    """

    return [
        _metric_query(
            query_id="iterator_age_ms",
            namespace="AWS/Kinesis",
            metric_name="GetRecords.IteratorAgeMilliseconds",
            dimensions=[{"Name": "StreamName", "Value": stream_name}],
            period=60,
            statistic="Maximum",
        ),
        _metric_query(
            query_id="write_throttle",
            namespace="AWS/Kinesis",
            metric_name="WriteProvisionedThroughputExceeded",
            dimensions=[{"Name": "StreamName", "Value": stream_name}],
            period=60,
            statistic="Sum",
        ),
        _metric_query(
            query_id="firehose_freshness_seconds",
            namespace="AWS/Firehose",
            metric_name="DeliveryToS3.DataFreshness",
            dimensions=[{"Name": "DeliveryStreamName", "Value": firehose_name}],
            period=300,
            statistic="Maximum",
        ),
        _metric_query(
            query_id="firehose_successful_puts",
            namespace="AWS/Firehose",
            metric_name="DeliveryToS3.Success",
            dimensions=[{"Name": "DeliveryStreamName", "Value": firehose_name}],
            period=300,
            statistic="Minimum",
        ),
    ]


def latest_metric_value(result: Mapping[str, Any]) -> float | None:
    """Return the value for the newest timestamp in one GetMetricData result.

    CloudWatch can return datapoints in descending order, and a missing value
    is meaningful for an operational verifier.  Selecting by timestamp avoids
    silently evaluating an older datapoint or treating an empty result as zero.
    """

    values = result.get("Values", [])
    timestamps = result.get("Timestamps", [])
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return None
    if not isinstance(timestamps, Sequence) or isinstance(timestamps, (str, bytes)):
        return None
    if not values or not timestamps or len(values) != len(timestamps):
        return None

    newest_index = max(range(len(timestamps)), key=lambda index: timestamps[index])
    value = values[newest_index]
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status(value: float | None, *, comparator: str, threshold: float) -> str:
    if value is None:
        return "NO_DATA"
    if comparator == "less_equal":
        return "PASS" if value <= threshold else "FAIL"
    if comparator == "greater_equal":
        return "PASS" if value >= threshold else "FAIL"
    if comparator == "greater_than":
        return "PASS" if value <= threshold else "FAIL"
    raise ValueError(f"Unsupported comparator: {comparator}")


def evaluate_snapshot(
    values: Mapping[str, float | None],
    *,
    iterator_age_threshold_ms: float = DEFAULT_ITERATOR_AGE_THRESHOLD_MILLISECONDS,
    firehose_freshness_threshold_seconds: float = DEFAULT_FIREHOSE_FRESHNESS_THRESHOLD_SECONDS,
    successful_puts_minimum: float = DEFAULT_SUCCESSFUL_PUTS_MINIMUM,
    write_throttle_maximum: float = DEFAULT_WRITE_THROTTLE_MAXIMUM,
) -> dict[str, Any]:
    """Evaluate one metric snapshot using fail-closed SLO semantics."""

    metrics = {
        "iterator_age_ms": {
            "value": values.get("iterator_age_ms"),
            "threshold": iterator_age_threshold_ms,
            "unit": "milliseconds",
            "status": _status(
                values.get("iterator_age_ms"),
                comparator="less_equal",
                threshold=iterator_age_threshold_ms,
            ),
        },
        "write_throttle": {
            "value": values.get("write_throttle"),
            "threshold": write_throttle_maximum,
            "unit": "events",
            "status": _status(
                values.get("write_throttle"),
                comparator="greater_than",
                threshold=write_throttle_maximum,
            ),
        },
        "firehose_freshness_seconds": {
            "value": values.get("firehose_freshness_seconds"),
            "threshold": firehose_freshness_threshold_seconds,
            "unit": "seconds",
            "status": _status(
                values.get("firehose_freshness_seconds"),
                comparator="less_equal",
                threshold=firehose_freshness_threshold_seconds,
            ),
        },
        "firehose_successful_puts": {
            "value": values.get("firehose_successful_puts"),
            "threshold": successful_puts_minimum,
            "unit": "successful_s3_put_commands",
            "status": _status(
                values.get("firehose_successful_puts"),
                comparator="greater_equal",
                threshold=successful_puts_minimum,
            ),
        },
    }

    statuses = {metric["status"] for metric in metrics.values()}
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "NO_DATA" in statuses:
        overall = "NO_DATA"
    else:
        overall = "PASS"

    return {"overall": overall, "metrics": metrics}

#!/usr/bin/env python3
"""Read-only CloudWatch verifier for the robot telemetry streaming SLO."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Make the repository root importable when this file is invoked as
# ``python scripts/verify_pipeline_slo.py`` rather than as a module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.observability.pipeline_slo import (
    DEFAULT_FIREHOSE_FRESHNESS_THRESHOLD_SECONDS,
    DEFAULT_ITERATOR_AGE_THRESHOLD_MILLISECONDS,
    build_cloudwatch_queries,
    evaluate_snapshot,
    latest_metric_value,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stream-name", required=True)
    parser.add_argument("--firehose-name", required=True)
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "eu-west-1",
    )
    parser.add_argument("--lookback-minutes", type=int, default=15)
    parser.add_argument(
        "--iterator-age-threshold-ms",
        type=float,
        default=DEFAULT_ITERATOR_AGE_THRESHOLD_MILLISECONDS,
    )
    parser.add_argument(
        "--firehose-freshness-threshold-seconds",
        type=float,
        default=DEFAULT_FIREHOSE_FRESHNESS_THRESHOLD_SECONDS,
    )
    parser.add_argument(
        "--allow-no-data",
        action="store_true",
        help="Return success for an otherwise healthy but inactive pipeline.",
    )
    return parser


def _metric_values(results: list[dict[str, Any]]) -> dict[str, float | None]:
    by_id = {result.get("Id"): result for result in results}
    return {
        metric_id: latest_metric_value(by_id.get(metric_id, {}))
        for metric_id in (
            "iterator_age_ms",
            "write_throttle",
            "firehose_freshness_seconds",
            "firehose_successful_puts",
        )
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.lookback_minutes <= 0:
        print("--lookback-minutes must be greater than zero", file=sys.stderr)
        return 2

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=args.lookback_minutes)
    try:
        client = boto3.client("cloudwatch", region_name=args.region)
        response = client.get_metric_data(
            MetricDataQueries=build_cloudwatch_queries(args.stream_name, args.firehose_name),
            StartTime=start_time,
            EndTime=end_time,
            ScanBy="TimestampDescending",
            MaxDatapoints=100,
        )
    except (BotoCoreError, ClientError) as exc:
        print(json.dumps({"overall": "ERROR", "error": str(exc)}), file=sys.stderr)
        return 3

    values = _metric_values(response.get("MetricDataResults", []))
    evaluation = evaluate_snapshot(
        values,
        iterator_age_threshold_ms=args.iterator_age_threshold_ms,
        firehose_freshness_threshold_seconds=args.firehose_freshness_threshold_seconds,
    )
    output = {
        "observed_at": end_time.isoformat(),
        "region": args.region,
        "lookback_minutes": args.lookback_minutes,
        "stream_name": args.stream_name,
        "firehose_name": args.firehose_name,
        **evaluation,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))

    if evaluation["overall"] == "PASS":
        return 0
    if evaluation["overall"] == "NO_DATA" and args.allow_no_data:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

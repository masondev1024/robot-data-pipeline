from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import yaml

from src.observability.pipeline_slo import (
    build_cloudwatch_queries,
    evaluate_snapshot,
    latest_metric_value,
)


def test_cloudwatch_queries_keep_metric_units_and_dimensions_explicit():
    queries = build_cloudwatch_queries("telemetry-stream", "telemetry-firehose")

    assert [query["Id"] for query in queries] == [
        "iterator_age_ms",
        "write_throttle",
        "firehose_freshness_seconds",
        "firehose_successful_puts",
    ]
    assert queries[0]["MetricStat"]["Metric"] == {
        "Namespace": "AWS/Kinesis",
        "MetricName": "GetRecords.IteratorAgeMilliseconds",
        "Dimensions": [{"Name": "StreamName", "Value": "telemetry-stream"}],
    }
    assert queries[2]["MetricStat"]["Metric"] == {
        "Namespace": "AWS/Firehose",
        "MetricName": "DeliveryToS3.DataFreshness",
        "Dimensions": [{"Name": "DeliveryStreamName", "Value": "telemetry-firehose"}],
    }
    assert queries[3]["MetricStat"]["Stat"] == "Minimum"


def test_deployed_pipeline_slo_dashboard_matches_canonical_source():
    canonical = json.loads(Path("grafana/dashboards/pipeline_slo.json").read_text())
    config_map = yaml.safe_load(Path("k8s/monitoring/grafana-dashboards.yaml").read_text())

    deployed = json.loads(config_map["data"]["pipeline_slo.json"])

    assert deployed == canonical


def test_latest_metric_value_selects_newest_timestamp_not_last_list_item():
    now = datetime.now(timezone.utc)
    result = {
        "Values": [10, 20],
        "Timestamps": [now - timedelta(minutes=1), now],
    }

    assert latest_metric_value(result) == 20


def test_latest_metric_value_returns_no_data_for_mismatched_or_empty_results():
    assert latest_metric_value({}) is None
    assert latest_metric_value({"Values": [1], "Timestamps": []}) is None
    assert latest_metric_value({"Values": [1, 2], "Timestamps": [datetime.now(timezone.utc)]}) is None


def test_evaluate_snapshot_passes_when_all_streaming_budgets_hold():
    evaluation = evaluate_snapshot(
        {
            "iterator_age_ms": 30_000,
            "write_throttle": 0,
            "firehose_freshness_seconds": 120,
            "firehose_successful_puts": 4,
        }
    )

    assert evaluation["overall"] == "PASS"
    assert all(metric["status"] == "PASS" for metric in evaluation["metrics"].values())


def test_evaluate_snapshot_fails_on_lag_or_delivery_freshness_breach():
    evaluation = evaluate_snapshot(
        {
            "iterator_age_ms": 120_001,
            "write_throttle": 0,
            "firehose_freshness_seconds": 601,
            "firehose_successful_puts": 1,
        }
    )

    assert evaluation["overall"] == "FAIL"
    assert evaluation["metrics"]["iterator_age_ms"]["status"] == "FAIL"
    assert evaluation["metrics"]["firehose_freshness_seconds"]["status"] == "FAIL"


def test_evaluate_snapshot_fails_closed_when_any_metric_has_no_data():
    evaluation = evaluate_snapshot(
        {
            "iterator_age_ms": 10,
            "write_throttle": 0,
            "firehose_freshness_seconds": None,
            "firehose_successful_puts": 2,
        }
    )

    assert evaluation["overall"] == "NO_DATA"
    assert evaluation["metrics"]["firehose_freshness_seconds"]["status"] == "NO_DATA"

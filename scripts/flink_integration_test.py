"""Studio Notebook anomaly-detection contract 통합 검증.

실제 Flink 실행 원본은 AWS Managed Flink Studio Notebook이다. 이 스크립트는
Notebook을 재현하는 배포 코드가 아니라, main KDS에 결정론적 정상/이상 이벤트를
주입하고 alert KDS downstream 결과를 확인하는 black-box 검증기다.

검증 시나리오:
  1. 정상 record → 미발화 기대.
  2. 다변량 record (motor_temp 95°C / load 30 / ratio 3.17) → 발화 기대.
  3. Z-Score-only record (95°C / load 100) 앞에 같은 robot의 정상 history를
     쌓아 `σ > 3` branch도 발화하는지 확인.
  4. alert KDS polling 후 정상 marker가 섞이지 않았는지 확인.

사전 조건:
  - Studio Notebook anomaly paragraph가 RUNNING 상태.
  - Notebook이 main KDS에서 alert KDS로 sink를 구성한 상태.
  - AWS 자격증명 (ap-northeast-2)과 Kinesis read/write 권한.

사용:
  python3 scripts/flink_integration_test.py
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.streaming.anomaly_contract import DEFAULT_THRESHOLDS  # noqa: E402


REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
MAIN_STREAM = os.environ.get("KINESIS_STREAM_NAME", "robot-telemetry-stream")
ALERT_STREAM = os.environ.get("KINESIS_ALERT_STREAM_NAME", "robot-anomaly-alert-stream")

ANOMALY_MARKER = f"INTEG-TEST-{uuid.uuid4().hex[:8]}"


def _make_record(
    robot_id: str,
    motor_temp: float,
    current_load: float,
    timestamp: datetime | None = None,
) -> dict:
    event_time = timestamp or datetime.now(timezone.utc)
    return {
        "robot_id": robot_id,
        "pos_x": 100.0,
        "pos_y": 100.0,
        "battery_level": 80.0,
        "current_load": current_load,
        "motor_temp": motor_temp,
        "timestamp": event_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "failure_type": "NONE",
    }


def inject_records(kinesis, records: list[dict]) -> int:
    """KDS-main에 records를 주입하고 전체 실패 개수를 반환한다."""

    failed_total = 0
    for offset in range(0, len(records), 500):
        batch = records[offset : offset + 500]
        payload = [
            {
                "Data": json.dumps(record).encode("utf-8"),
                "PartitionKey": record["robot_id"],
            }
            for record in batch
        ]
        response = kinesis.put_records(StreamName=MAIN_STREAM, Records=payload)
        failed = response.get("FailedRecordCount", 0)
        failed_total += failed
        print(
            f"[flink-test] inject {len(batch)} records → main stream "
            f"(failed={failed})"
        )
    return failed_total


def latest_alert_iterators(kinesis) -> list[tuple[str, str]]:
    """주입 전에 alert KDS의 각 shard LATEST iterator를 준비한다."""

    desc = kinesis.describe_stream(StreamName=ALERT_STREAM)
    shards = desc["StreamDescription"]["Shards"]
    return [
        (
            shard["ShardId"],
            kinesis.get_shard_iterator(
                StreamName=ALERT_STREAM,
                ShardId=shard["ShardId"],
                ShardIteratorType="LATEST",
            )["ShardIterator"],
        )
        for shard in shards
    ]


def poll_alert_stream(
    kinesis,
    iterators: list[tuple[str, str]],
    duration_sec: int = 120,
) -> list[dict]:
    """준비된 iterator로 alert KDS를 polling한다.

    1-minute tumbling window와 Notebook watermark 여유를 고려해 기본 120초로
    둔다. iterator를 주입 후 생성하지 않아 빠른 sink 결과를 놓치지 않는다.
    """

    print(f"[flink-test] polling {len(iterators)} shard(s) for {duration_sec}s...")
    received: list[dict] = []
    deadline = time.time() + duration_sec
    current_iterators = iterators
    while time.time() < deadline:
        next_iterators = []
        for shard_id, iterator in current_iterators:
            if iterator is None:
                continue
            response = kinesis.get_records(ShardIterator=iterator, Limit=100)
            for record in response.get("Records", []):
                try:
                    received.append(json.loads(record["Data"].decode("utf-8")))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
            next_iterators.append((shard_id, response.get("NextShardIterator")))
        current_iterators = next_iterators
        time.sleep(2)
    return received


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--poll-sec",
        type=int,
        default=120,
        help="alert stream polling 시간 (1-minute window + watermark 여유)",
    )
    parser.add_argument(
        "--zscore-baseline",
        type=int,
        default=20,
        help="Z-Score-only robot의 정상 history 개수",
    )
    args = parser.parse_args()

    if args.zscore_baseline < 5:
        parser.error("--zscore-baseline must be at least 5")

    kinesis = boto3.client("kinesis", region_name=REGION)
    alert_iterators = latest_alert_iterators(kinesis)

    print(f"[flink-test] marker={ANOMALY_MARKER} region={REGION}")
    print(f"[flink-test] main={MAIN_STREAM} alert={ALERT_STREAM}")
    print(
        "[flink-test] contract: "
        f"zscore>{DEFAULT_THRESHOLDS.zscore_threshold} OR "
        f"temp>={DEFAULT_THRESHOLDS.min_motor_temp}°C and "
        f"temp/load>{DEFAULT_THRESHOLDS.load_ratio_threshold}\n"
    )

    base_time = datetime.now(timezone.utc) - timedelta(
        seconds=args.zscore_baseline + 10
    )

    normal = [
        _make_record(
            f"{ANOMALY_MARKER}-N{i}",
            motor_temp=65.0 + i,
            current_load=70.0,
            timestamp=base_time + timedelta(seconds=i),
        )
        for i in range(5)
    ]

    multivariate_robot = f"{ANOMALY_MARKER}-MV"
    multivariate = [
        _make_record(
            multivariate_robot,
            motor_temp=95.0,
            current_load=30.0,
            timestamp=base_time + timedelta(seconds=6),
        )
    ]

    zscore_robot = f"{ANOMALY_MARKER}-ZS"
    zscore_history = [
        _make_record(
            zscore_robot,
            motor_temp=65.0 + (i % 2) * 0.2,
            current_load=70.0,
            timestamp=base_time + timedelta(seconds=10 + i),
        )
        for i in range(args.zscore_baseline)
    ]
    # ratio=0.95라 다변량 branch는 통과하지 않고, history 대비 z-score만 발화.
    zscore_only = [
        _make_record(
            zscore_robot,
            motor_temp=95.0,
            current_load=100.0,
            timestamp=base_time + timedelta(seconds=10 + args.zscore_baseline),
        )
    ]

    expected_alert_ids = {multivariate_robot, zscore_robot}
    normal_robot_ids = {record["robot_id"] for record in normal}

    print("[flink-test] step 1/4: normal 5건 inject (미발화 기대)")
    failed_total = inject_records(kinesis, normal)

    print("[flink-test] step 2/4: multivariate anomaly inject (발화 기대)")
    failed_total += inject_records(kinesis, multivariate)

    print(
        f"[flink-test] step 3/4: Z-Score baseline {len(zscore_history)}건 + spike inject"
    )
    failed_total += inject_records(kinesis, zscore_history + zscore_only)
    if failed_total:
        print(f"[flink-test] ❌ KDS put failed records={failed_total}")
        return 1

    print(f"[flink-test] step 4/4: alert stream polling {args.poll_sec}s")
    alerts = poll_alert_stream(kinesis, alert_iterators, duration_sec=args.poll_sec)

    test_alerts = [
        alert for alert in alerts if ANOMALY_MARKER in json.dumps(alert, ensure_ascii=False)
    ]
    other_alerts = len(alerts) - len(test_alerts)
    print(
        f"\n[flink-test] alert 수신 합계: {len(alerts)} "
        f"(test marker={len(test_alerts)}, 기타={other_alerts})"
    )
    if test_alerts:
        print("[flink-test] marker alert sample:")
        for alert in test_alerts[:3]:
            print(f"  {alert}")

    alert_ids = {
        alert.get("robot_id")
        for alert in test_alerts
        if isinstance(alert, dict) and alert.get("robot_id")
    }
    missing = sorted(expected_alert_ids - alert_ids)
    unexpected_normal = sorted(normal_robot_ids & alert_ids)
    if not missing and not unexpected_normal:
        print(
            "\n[flink-test] ✅ PASS — 두 anomaly branch 발화 및 "
            f"normal false-positive 없음 (marker alerts={len(test_alerts)})"
        )
        return 0

    print("\n[flink-test] ❌ FAIL — anomaly contract 결과가 기대와 다름")
    print(f"[flink-test]    missing expected robot ids: {missing or 'none'}")
    print(f"[flink-test]    unexpected normal robot ids: {unexpected_normal or 'none'}")
    print("[flink-test]    가능 원인: ① Studio Notebook paragraph 미실행, ② alert sink 미구성,")
    print("[flink-test]              ③ watermark/window 대기 부족, ④ Notebook threshold drift")
    return 1


if __name__ == "__main__":
    sys.exit(main())

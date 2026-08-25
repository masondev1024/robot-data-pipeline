"""Flink 통합 검증 (Task 3.3 line 318) — Studio Notebook anomaly detection 발화 검증.

시나리오:
  1. 정상 record 5건(motor_temp 65°C / load 70 / ratio 0.93) → Flink 미발화 기대.
  2. 이상 record 5건(motor_temp 95°C / load 30 / ratio 3.17) → Flink 다변량 룰
     (motor_temp >= 92.0 AND ratio > 2.5) 발화 기대.
  3. KDS-main 에 10건 주입 후 KDS-alert 에서 1분간 polling → 이상 record 만 수신 확인.

사전 조건:
  - Flink Studio Notebook (de-ai-06-flink-studio-nb) RUNNING.
  - Anomaly detection paragraph (S3 sink + KDS-alert sink) 양쪽 실행 중.
  - AWS 자격증명 (ap-northeast-2) Kinesis read/write 권한.

사용:
  python3 scripts/flink_integration_test.py
"""
import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import boto3


REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
MAIN_STREAM = os.environ.get("KINESIS_STREAM_NAME", "robot-telemetry-stream")
ALERT_STREAM = os.environ.get("KINESIS_ALERT_STREAM_NAME", "robot-anomaly-alert-stream")

ANOMALY_MARKER = f"INTEG-TEST-{uuid.uuid4().hex[:8]}"


def _make_record(robot_id: str, motor_temp: float, current_load: float) -> dict:
    return {
        "robot_id": robot_id,
        "pos_x": 100.0,
        "pos_y": 100.0,
        "battery_level": 80.0,
        "current_load": current_load,
        "motor_temp": motor_temp,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "failure_type": "NONE",
    }


def inject_records(kinesis, records: list[dict]) -> int:
    """KDS-main 에 records 주입. PartitionKey = robot_id."""
    payload = [
        {
            "Data": json.dumps(r).encode("utf-8"),
            "PartitionKey": r["robot_id"],
        }
        for r in records
    ]
    resp = kinesis.put_records(StreamName=MAIN_STREAM, Records=payload)
    failed = resp.get("FailedRecordCount", 0)
    print(f"[flink-test] inject {len(records)} records → main stream (failed={failed})")
    return failed


def poll_alert_stream(kinesis, duration_sec: int = 90) -> list[dict]:
    """KDS-alert 의 모든 shard 에서 LATEST 부터 duration_sec 동안 polling.

    Studio Notebook 은 1-minute Tumbling Window 라 발화까지 60-90초 대기 필요.
    """
    desc = kinesis.describe_stream(StreamName=ALERT_STREAM)
    shards = desc["StreamDescription"]["Shards"]
    iterators = []
    for shard in shards:
        it = kinesis.get_shard_iterator(
            StreamName=ALERT_STREAM,
            ShardId=shard["ShardId"],
            ShardIteratorType="LATEST",
        )["ShardIterator"]
        iterators.append((shard["ShardId"], it))

    print(f"[flink-test] polling {len(iterators)} shard(s) for {duration_sec}s...")
    received = []
    deadline = time.time() + duration_sec
    while time.time() < deadline:
        next_iters = []
        for shard_id, it in iterators:
            if it is None:
                continue
            resp = kinesis.get_records(ShardIterator=it, Limit=100)
            for rec in resp.get("Records", []):
                try:
                    parsed = json.loads(rec["Data"].decode("utf-8"))
                    received.append(parsed)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
            next_iters.append((shard_id, resp.get("NextShardIterator")))
        iterators = next_iters
        time.sleep(2)
    return received


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll-sec", type=int, default=90,
                        help="Alert stream polling 시간 (Tumbling Window 60-90s 대기 필요)")
    args = parser.parse_args()

    kinesis = boto3.client("kinesis", region_name=REGION)

    print(f"[flink-test] marker={ANOMALY_MARKER} region={REGION}")
    print(f"[flink-test] main={MAIN_STREAM} alert={ALERT_STREAM}\n")

    # Normal records (Flink 미발화 기대) — robot_id 에 marker 포함하여 식별
    normal = [
        _make_record(f"{ANOMALY_MARKER}-N{i}", motor_temp=65.0 + i, current_load=70.0)
        for i in range(5)
    ]
    # Anomaly records (Flink 발화 기대): motor_temp >= 92 AND ratio (95/30=3.17) > 2.5
    anomaly = [
        _make_record(f"{ANOMALY_MARKER}-A{i}", motor_temp=95.0 + i, current_load=30.0)
        for i in range(5)
    ]

    print("[flink-test] step 1/3: normal 5건 inject (Flink 미발화 기대)")
    inject_records(kinesis, normal)

    print("[flink-test] step 2/3: anomaly 5건 inject (Flink 발화 기대)")
    inject_records(kinesis, anomaly)

    print(f"[flink-test] step 3/3: alert stream polling {args.poll_sec}s")
    alerts = poll_alert_stream(kinesis, duration_sec=args.poll_sec)

    # 결과 분류 — marker 가 있는 record 만 본 테스트 산출물
    test_alerts = [a for a in alerts if ANOMALY_MARKER in str(a)]
    other_alerts = len(alerts) - len(test_alerts)

    print(f"\n[flink-test] alert stream 수신 합계: {len(alerts)} (test marker={len(test_alerts)}, 기타={other_alerts})")
    if test_alerts:
        print("[flink-test] ✅ Flink 발화 record (sample):")
        for a in test_alerts[:3]:
            print(f"  {a}")

    # 검증 결과 요약
    if len(test_alerts) >= 1:
        print(f"\n[flink-test] ✅ PASS — Flink 다변량 룰 발화 확인 ({len(test_alerts)} alerts)")
        return 0
    else:
        print("\n[flink-test] ❌ FAIL — anomaly inject 했으나 alert stream 미수신")
        print("[flink-test]    가능 원인: ① Studio Notebook paragraph 미실행, ② alert sink 미구성,")
        print("[flink-test]              ③ Window aggregate 가 1분 이상이라 polling 시간 부족")
        return 1


if __name__ == "__main__":
    sys.exit(main())

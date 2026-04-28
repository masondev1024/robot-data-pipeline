"""Generator backfill mode — 과거 N일치 historical record를 KDS로 일괄 push 후 종료.

기존 src/generator/app.py 의 daemon 모드와 분리된 one-shot 진입점.
profiles 로딩 + record 생성 로직은 동일한 algorithm 을 재사용하되, timestamp 만
[now - days, now] 범위에서 interval_min 간격으로 분산한다.

KDF가 정상 경로(KDS → Firehose Parquet 변환 → S3 bronze/year=/month=/day=/hour=)로
적재하므로 Glue Catalog schema와 자동 일치 — Athena 쿼리 즉시 가능.

Usage:
    BACKFILL_DAYS=7 \\
    BACKFILL_INTERVAL_MIN=5 \\
    ROBOT_COUNT=10000 \\
    KINESIS_STREAM_NAME=robot-telemetry-stream \\
    SEED_CSV_PATH=data/seed_data_sample.csv \\
    AWS_DEFAULT_REGION=eu-west-1 \\
    python -m src.generator.backfill

기본값:
    7 days × 24 hours × 12 records/hour (5-min interval)
    = 2,016 records per robot × 10,000 robots
    = 20.16M records total
    KDS 10 shards × 1MB/sec = 10MB/sec → ~7 분 소요 추정
"""

import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator

import boto3


def _load_dotenv(path: str = ".env") -> None:
    """.env 파일을 stdlib로 로드 (python-dotenv 의존성 없이). 이미 export된 변수는 덮어쓰지 않음."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


# 프로젝트 루트의 .env 자동 로드 (cwd 기준 + 모듈 위치 기준 둘 다 시도)
_load_dotenv(".env")
_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))

# 같은 패키지의 load_profiles 재사용 (CSV → robot 프로필 변환 로직 동일)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.generator.app import load_profiles  # noqa: E402


# ── 1. Timestamp 분산 생성 ───────────────────────────────────────

def generate_timestamps(days: int, interval_min: int) -> list[datetime]:
    """[now - days, now) 범위에서 interval_min 간격으로 datetime list 생성."""
    if days <= 0:
        return []
    if interval_min <= 0:
        raise ValueError("interval_min must be positive")

    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=days)
    interval = timedelta(minutes=interval_min)

    timestamps = []
    t = start
    while t < end:
        timestamps.append(t)
        t += interval
    return timestamps


# ── 2. Record 생성 (단일 시점) ────────────────────────────────────

def generate_record(profile: dict, t: datetime) -> dict:
    """Backfill용 단일 record. simulate_robot 알고리즘 단순화 — drift/battery 누적 없음.

    daemon 모드의 stateful drift/battery 누적은 backfill 의 의도(과거 분포 재현)와
    무관하므로 제거. 각 timestamp 의 motor_temp 는 base + 노이즈 + faulty spike 만 반영.
    """
    motor_base = profile["motor_temp_base"]
    spike = 0.0
    if profile["is_faulty"] and random.random() < 0.05:
        spike = random.uniform(91, 99) - motor_base

    motor_temp = round(
        min(110.0, max(55.0, motor_base + random.gauss(0, 2) + spike)),
        2,
    )
    load = int(min(100, max(0, profile["load_base"] + random.gauss(0, 5))))

    return {
        "robot_id":      profile["robot_id"],
        "pos_x":         round(profile["pos_x"] + random.uniform(-0.0001, 0.0001), 6),
        "pos_y":         round(profile["pos_y"] + random.uniform(-0.0001, 0.0001), 6),
        "battery_level": random.randint(20, 100),
        "current_load":  load,
        "motor_temp":    motor_temp,
        "timestamp":     t.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ── 3. Record 스트림 (제너레이터 — 메모리 통제) ───────────────────

def backfill_records(profiles: list[dict],
                      timestamps: list[datetime]) -> Iterator[dict]:
    """profile × timestamp 조합으로 record 를 lazy 하게 yield.

    list 로 한꺼번에 만들면 20M × dict 가 메모리 폭증 위험. yield 로 streaming.
    """
    for t in timestamps:
        for profile in profiles:
            yield generate_record(profile, t)


def chunked(iterable: Iterable[dict], size: int) -> Iterator[list[dict]]:
    """iterable 을 size 단위 list 로 묶어 yield."""
    chunk: list[dict] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


# ── 4. KDS Push ───────────────────────────────────────────────────

KINESIS_BATCH_LIMIT = 500       # PutRecords 한도
KINESIS_BATCH_SLEEP = 0.05      # batch 사이 sleep — KDS throughput throttle 회피

def push_to_kinesis(records: Iterable[dict],
                    stream_name: str,
                    kinesis_client,
                    progress_every: int = 50) -> int:
    """records 를 KINESIS_BATCH_LIMIT 단위로 PutRecords. 총 push 건수 반환.

    50 batch 마다 진행 상황 stderr 출력. KDS throttle 시 boto3 가 자동 retry.
    """
    total = 0
    batch_idx = 0
    for batch in chunked(records, KINESIS_BATCH_LIMIT):
        kinesis_records = [
            {"Data": json.dumps(r).encode(), "PartitionKey": r["robot_id"]}
            for r in batch
        ]
        kinesis_client.put_records(StreamName=stream_name, Records=kinesis_records)
        total += len(batch)
        batch_idx += 1
        if batch_idx % progress_every == 0:
            print(f"  ... {total:,} records pushed (batch #{batch_idx})", file=sys.stderr)
        time.sleep(KINESIS_BATCH_SLEEP)
    return total


# ── 5. 진입점 ─────────────────────────────────────────────────────

def main() -> None:
    days         = int(os.environ.get("BACKFILL_DAYS", "7"))
    interval_min = int(os.environ.get("BACKFILL_INTERVAL_MIN", "5"))
    robot_count  = int(os.environ.get("ROBOT_COUNT", "10000"))
    stream_name  = os.environ["KINESIS_STREAM_NAME"]
    csv_path     = os.environ.get("SEED_CSV_PATH", "data/seed_data_sample.csv")
    region       = os.environ.get("AWS_DEFAULT_REGION", "eu-west-1")

    if days <= 0:
        print(f"BACKFILL_DAYS={days} (≤0) — backfill mode disabled, exiting.")
        return

    print(f"Loading profiles from {csv_path} for {robot_count:,} robots...")
    profiles = load_profiles(csv_path, robot_count)

    timestamps = generate_timestamps(days, interval_min)
    total_expected = len(profiles) * len(timestamps)
    print(
        f"Backfill plan: {len(profiles):,} robots × {len(timestamps):,} timestamps "
        f"({days}d × {interval_min}min) = {total_expected:,} records"
    )
    print(f"Target stream: {stream_name} ({region})")

    kinesis = boto3.client("kinesis", region_name=region)
    t0 = time.monotonic()
    pushed = push_to_kinesis(
        backfill_records(profiles, timestamps),
        stream_name,
        kinesis,
    )
    elapsed = time.monotonic() - t0
    rate = pushed / elapsed if elapsed > 0 else 0
    print(
        f"Backfill complete: {pushed:,} records pushed in {elapsed:,.1f}s "
        f"({rate:,.0f} rec/sec)"
    )


if __name__ == "__main__":
    main()

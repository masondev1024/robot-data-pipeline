import asyncio
import csv
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path

import boto3

from src.generator.schema_validator import validate_record


# ── 1. Seed CSV 로딩 ──────────────────────────────────────────

def load_profiles(csv_path: str, robot_count: int) -> list[dict]:
    """
    AI4I 2020 CSV를 읽어 robot_count개 로봇 프로필을 반환한다.
    CSV 행 수 < robot_count이면 행을 순환(cycle)한다.

    컬럼 매핑:
      Process temperature [K] → motor_temp_base  (K-273.15, clamp 60~100°C)
      Rotational speed [rpm]  → load_base         (1168~2886 → 0~100 정규화)
      Tool wear [min]         → drain_factor       (0~250 → 0.1~3.0)
      Machine failure         → is_faulty          (True면 스파이크 확률 70%)
    """
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    profiles = []
    for i in range(robot_count):
        r = rows[i % len(rows)]
        proc_k  = float(r["Process temperature [K]"])
        rpm     = float(r["Rotational speed [rpm]"])
        wear    = float(r["Tool wear [min]"])
        failure = int(r["Machine failure"])

        motor_base  = min(100.0, max(60.0, proc_k - 273.15 + 30))
        load_base   = int(min(100, max(0, (rpm - 1168) / (2886 - 1168) * 100)))
        drain       = min(3.0, max(0.1, wear / 100))

        # 공장 그리드 좌표 (균등 배치)
        grid_x = 37.4 + (i % 100) * 0.003
        grid_y = 126.8 + (i // 100) * 0.004

        profiles.append({
            "robot_id":        f"ROBOT-{i+1:05d}",
            "pos_x":           round(grid_x, 6),
            "pos_y":           round(grid_y, 6),
            "motor_temp_base": motor_base,
            "load_base":       load_base,
            "drain_factor":    drain,
            "is_faulty":       bool(failure),
            "battery":         random.randint(50, 100),
        })
    return profiles


# ── 2. 로봇 시뮬레이터 (1 coroutine = 1 로봇) ──────────────────

async def simulate_robot(profile: dict, queue: asyncio.Queue) -> None:
    """초당 1건 센서 레코드를 생성하여 queue에 넣는다. 무한 루프."""
    battery = profile["battery"]
    drift   = 0.0  # 점진적 온도 드리프트

    while True:
        # motor_temp: 베이스 ± 가우시안 노이즈 + 드리프트
        noise = random.gauss(0, 2)
        spike = 0.0
        if profile["is_faulty"] and random.random() < 0.05:
            spike = random.uniform(91, 99) - profile["motor_temp_base"]
        drift = drift * 0.99 + random.gauss(0, 0.1)  # 천천히 변화
        motor_temp = round(
            min(110.0, max(55.0,
                profile["motor_temp_base"] + noise + drift + spike)), 2)

        # battery: drain_factor 기반 감소, 0 도달 시 재충전
        battery -= profile["drain_factor"] * random.uniform(0.01, 0.05)
        if battery <= 0:
            battery = round(random.uniform(80, 100), 1)

        # current_load: RPM 베이스 ± 노이즈
        load = int(min(100, max(0,
            profile["load_base"] + random.gauss(0, 5))))

        record = {
            "robot_id":      profile["robot_id"],
            "pos_x":         profile["pos_x"] + random.uniform(-0.0001, 0.0001),
            "pos_y":         profile["pos_y"] + random.uniform(-0.0001, 0.0001),
            "battery_level": int(max(0, min(100, battery))),
            "current_load":  load,
            "motor_temp":    motor_temp,
            "timestamp":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        await queue.put(record)
        await asyncio.sleep(1.0)


# ── 3. 배치 전송 (put_records 500건) ───────────────────────────

async def batch_sender(queue: asyncio.Queue,
                        stream_name: str,
                        kinesis_client) -> None:
    """
    queue에서 최대 500건씩 꺼내 put_records 호출.
    50ms 간격 = 초당 최대 20회 배치 → 10,000 rec/sec 처리 가능.
    """
    loop = asyncio.get_event_loop()
    while True:
        batch = []
        while len(batch) < 500:
            try:
                record = queue.get_nowait()
                if not validate_record(record):
                    continue  # schema 불일치 → drop (carrier로 들어가지 않음)
                batch.append({
                    "Data":         json.dumps(record).encode(),
                    "PartitionKey": record["robot_id"],
                })
            except asyncio.QueueEmpty:
                break

        if batch:
            await loop.run_in_executor(
                None,
                lambda b=batch: kinesis_client.put_records(
                    StreamName=stream_name, Records=b),
            )

        await asyncio.sleep(0.05)


# ── 4. 진입점 ───────────────────────────────────────────────────

async def main() -> None:
    robot_count = int(os.environ.get("ROBOT_COUNT", "10000"))
    stream_name = os.environ["KINESIS_STREAM_NAME"]
    csv_path    = os.environ.get("SEED_CSV_PATH", "data/seed_data_sample.csv")

    print(f"Loading profiles from {csv_path} for {robot_count} robots...")
    profiles = load_profiles(csv_path, robot_count)

    kinesis = boto3.client("kinesis", region_name=os.environ.get("AWS_DEFAULT_REGION", "eu-west-1"))
    queue   = asyncio.Queue(maxsize=robot_count * 2)

    tasks = [asyncio.create_task(simulate_robot(p, queue)) for p in profiles]
    tasks += [asyncio.create_task(batch_sender(queue, stream_name, kinesis))]

    print(f"Started {len(profiles)} robot simulators. Streaming to {stream_name}...")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import csv
import json
import os
import random
import signal
import time
from datetime import datetime, timezone

import boto3

from src.generator.schema_validator import get_failure_count, validate_record


# 시연 통제용: SIGUSR1 수신 시 N초 동안 모든 로봇 모터 온도 강제 spike.
# 0이면 비활성. handler가 time.time()+duration 으로 갱신.
_force_anomaly_until_ts: float = 0.0


def _should_spike(profile: dict, now_ts: float, force_until_ts: float) -> bool:
    """이번 tick에서 motor_temp spike 여부 결정.

    - force window 내(now < force_until_ts): 모든 로봇 무조건 spike
    - 그 외: 기존 룰(is_faulty 로봇만 5% 확률)
    """
    if now_ts < force_until_ts:
        return True
    return profile["is_faulty"] and random.random() < 0.05


def _trigger_force_anomaly() -> None:
    """SIGUSR1 핸들러 — FORCE_ANOMALY_DURATION_SEC 초 동안 모든 로봇 spike."""
    global _force_anomaly_until_ts
    duration = int(os.environ.get("FORCE_ANOMALY_DURATION_SEC", "60"))
    _force_anomaly_until_ts = time.time() + duration
    print(json.dumps({
        "event": "force_anomaly_triggered",
        "duration_sec": duration,
        "until_ts": _force_anomaly_until_ts,
    }))


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

async def simulate_robot(profile: dict,
                          queue: asyncio.Queue,
                          tick_interval: float,
                          shutdown: asyncio.Event) -> None:
    """tick_interval초마다 센서 레코드 1건 생성하여 queue에 넣는다.
    shutdown 이벤트가 set되면 즉시 종료."""
    battery = profile["battery"]
    drift   = 0.0  # 점진적 온도 드리프트

    while not shutdown.is_set():
        # motor_temp: 베이스 ± 가우시안 노이즈 + 드리프트
        noise = random.gauss(0, 2)
        spike = 0.0
        if _should_spike(profile, time.time(), _force_anomaly_until_ts):
            spike = random.uniform(91, 99) - profile["motor_temp_base"]
        drift = drift * 0.99 + random.gauss(0, 0.1)
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
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=tick_interval)
            return  # shutdown 신호 도착 → 종료
        except asyncio.TimeoutError:
            continue  # 다음 tick


# ── 3. 배치 전송 (put_records 500건 + 재시도) ──────────────────

# 누적 카운터 (graceful shutdown 시 stdout에 보고)
sent_count: int = 0
failed_count: int = 0


async def _send_with_retry(records: list[dict],
                            stream_name: str,
                            kinesis_client,
                            max_attempts: int = 3) -> int:
    """put_records 호출 + FailedRecordCount 검사 + 지수 백오프 재시도.

    실패 인덱스만 추려서 재시도. 최종 실패 건은 stdout에 JSON으로 로깅하고
    실패 건수를 반환한다 (호출자가 카운터에 누적).
    """
    loop = asyncio.get_event_loop()
    attempt = 0
    pending = records

    while pending and attempt < max_attempts:
        try:
            response = await loop.run_in_executor(
                None,
                lambda b=pending: kinesis_client.put_records(
                    StreamName=stream_name, Records=b),
            )
        except Exception as e:
            # 전체 호출 실패 (네트워크/throttling 등) → 백오프 후 전체 재시도
            backoff = (2 ** attempt) * 0.1 + random.uniform(0, 0.05)
            print(json.dumps({
                "event": "put_records_call_failed",
                "attempt": attempt + 1,
                "error": str(e),
                "retry_in_s": round(backoff, 3),
                "batch_size": len(pending),
            }))
            await asyncio.sleep(backoff)
            attempt += 1
            continue

        failed_count_in_response = response.get("FailedRecordCount", 0)
        if failed_count_in_response == 0:
            return 0

        # 실패한 인덱스만 추출 (응답의 Records 배열은 요청과 동일 순서)
        next_pending = []
        for i, result in enumerate(response.get("Records", [])):
            if "ErrorCode" in result:
                next_pending.append(pending[i])

        backoff = (2 ** attempt) * 0.1 + random.uniform(0, 0.05)
        print(json.dumps({
            "event": "put_records_partial_failure",
            "attempt": attempt + 1,
            "failed": len(next_pending),
            "total": len(pending),
            "retry_in_s": round(backoff, 3),
        }))
        await asyncio.sleep(backoff)
        pending = next_pending
        attempt += 1

    # max_attempts 후에도 남은 건은 최종 실패
    if pending:
        print(json.dumps({
            "event": "put_records_giving_up",
            "dropped": len(pending),
            "sample_partition_keys": [r["PartitionKey"] for r in pending[:3]],
        }))
    return len(pending)


async def batch_sender(queue: asyncio.Queue,
                        stream_name: str,
                        kinesis_client,
                        shutdown: asyncio.Event) -> None:
    """queue에서 최대 500건씩 꺼내 put_records.
    shutdown 신호 후에도 큐가 빌 때까지 계속 flush."""
    global sent_count, failed_count

    while True:
        batch = []
        while len(batch) < 500:
            try:
                record = queue.get_nowait()
                if not validate_record(record):
                    continue
                batch.append({
                    "Data":         json.dumps(record).encode(),
                    "PartitionKey": record["robot_id"],
                })
            except asyncio.QueueEmpty:
                break

        if batch:
            failed = await _send_with_retry(batch, stream_name, kinesis_client)
            sent_count += len(batch) - failed
            failed_count += failed
        else:
            # 큐가 비었음. shutdown 중이면 종료, 아니면 잠시 대기.
            if shutdown.is_set():
                return
            await asyncio.sleep(0.05)


# ── 4. 진입점 ───────────────────────────────────────────────────

async def main() -> None:
    robot_count   = int(os.environ.get("ROBOT_COUNT", "10000"))
    tick_interval = float(os.environ.get("TICK_INTERVAL_SECONDS", "1.0"))
    stream_name   = os.environ["KINESIS_STREAM_NAME"]
    csv_path      = os.environ.get("SEED_CSV_PATH", "data/seed_data_sample.csv")

    print(f"Loading profiles from {csv_path} for {robot_count} robots (tick={tick_interval}s)...")
    profiles = load_profiles(csv_path, robot_count)

    kinesis = boto3.client("kinesis", region_name=os.environ.get("AWS_DEFAULT_REGION", "eu-west-1"))
    queue   = asyncio.Queue(maxsize=robot_count * 2)
    shutdown = asyncio.Event()

    # SIGINT/SIGTERM 핸들러: shutdown 이벤트 set
    loop = asyncio.get_running_loop()
    def _request_shutdown():
        if not shutdown.is_set():
            print("\n[shutdown] signal received, draining queue...")
            shutdown.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            # Windows에서 add_signal_handler 미지원 → KeyboardInterrupt로 처리됨
            pass

    # SIGUSR1: 시연자가 알람 폭주를 무대 위에서 토글
    try:
        loop.add_signal_handler(signal.SIGUSR1, _trigger_force_anomaly)
    except (NotImplementedError, AttributeError):
        pass  # Windows: SIGUSR1 미존재

    sim_tasks = [asyncio.create_task(simulate_robot(p, queue, tick_interval, shutdown))
                 for p in profiles]
    sender_task = asyncio.create_task(batch_sender(queue, stream_name, kinesis, shutdown))

    print(f"Started {len(profiles)} robot simulators. Streaming to {stream_name}...")

    try:
        await asyncio.gather(*sim_tasks, return_exceptions=True)
    except KeyboardInterrupt:
        # Windows fallback
        _request_shutdown()

    # simulator 모두 종료 → batch_sender가 큐 마지막까지 flush 후 자체 종료
    await sender_task

    drop = get_failure_count()
    print(json.dumps({
        "event": "shutdown_complete",
        "sent": sent_count,
        "failed": failed_count,
        "schema_dropped": drop,
    }))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[shutdown] forced exit")

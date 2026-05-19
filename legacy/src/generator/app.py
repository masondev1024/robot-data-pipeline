import asyncio
import csv
import json
import math
import os
import random
import signal
import time
from datetime import datetime, timezone

from src.common.aws import get_client
from src.generator._fault_state import Phase, advance_phase, init_state
from src.generator._record import (
    battery_drain_factor,
    hour_load_multiplier,
    iso_z_now,
    jittered_pos,
    load_temp_delta,
    resolve_failure_type,
    to_kinesis_record,
)
from src.generator.schema_validator import get_failure_count, validate_record


# 시연 통제용: SIGUSR1 수신 시 N초 동안 모든 로봇 모터 온도 강제 spike.
# 0이면 비활성. handler가 time.time()+duration 으로 갱신.
_force_anomaly_until_ts: float = 0.0

# 네트워크 재시도 backoff jitter 전용 RNG — robot 시뮬레이션 RNG 와 격리.
_retry_rng: random.Random = random.Random()


def _load_realism_params() -> dict:
    """Env var 기반 fault-state 파라미터 + realism 계수 dict 반환."""
    return {
        "fault_entry_prob": float(os.environ.get("FAULT_ENTRY_PROB", "0.0002")),
        "fault_ramp_ticks": int(os.environ.get("FAULT_RAMP_TICKS", "20")),
        "fault_peak_ticks": int(os.environ.get("FAULT_PEAK_TICKS", "40")),
        "fault_cooldown_ticks": int(os.environ.get("FAULT_COOLDOWN_TICKS", "30")),
        "fault_peak_temp_delta": float(os.environ.get("FAULT_PEAK_TEMP_DELTA", "25.0")),
        "stuck_entry_prob": float(os.environ.get("STUCK_ENTRY_PROB", "0.00005")),
        "stuck_min_ticks": int(os.environ.get("STUCK_MIN_TICKS", "60")),
        "stuck_max_ticks": int(os.environ.get("STUCK_MAX_TICKS", "120")),
        "load_temp_coeff": float(os.environ.get("LOAD_TEMP_COEFF", "5.0")),
        "hour_load_variance": float(os.environ.get("HOUR_LOAD_VARIANCE", "0.4")),
        "battery_load_coeff": float(os.environ.get("BATTERY_LOAD_COEFF", "0.5")),
        "battery_temp_coeff": float(os.environ.get("BATTERY_TEMP_COEFF", "0.3")),
    }


def _should_spike(profile: dict, now_ts: float, force_until_ts: float) -> bool:
    """[DEPRECATED — Phase 7 fault-state machine으로 대체됨]
    하위 호환성을 위해 시그니처 보존. 실제 simulate_robot 흐름은 advance_phase 사용.
    test_force_anomaly.py 기존 케이스 보존을 위해 단발 룰 그대로 유지.
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


def _resolve_robot_id_range() -> tuple[int, int]:
    """StatefulSet ordinal + replicas 기반 robot ID range 결정.

    POD_NAME 끝의 숫자 = ordinal. TOTAL_ROBOTS / POD_TOTAL_REPLICAS = pod 당 robot 수.
    e.g. POD_NAME='generator-3', TOTAL_ROBOTS=1000, POD_TOTAL_REPLICAS=10
         → robots_per_pod = 100 → start=300, end=400

    1000대를 10 pod 으로 분할 시 마지막 pod 이 잔여 분 담당 (ceil 분배).
    배포 시 POD_TOTAL_REPLICAS 와 StatefulSet spec.replicas 가 일치해야 함.
    """
    pod_name = os.environ["POD_NAME"]
    pod_index = int(pod_name.rsplit("-", 1)[-1])
    total_robots = int(os.environ["TOTAL_ROBOTS"])
    total_replicas = int(os.environ["POD_TOTAL_REPLICAS"])
    robots_per_pod = math.ceil(total_robots / total_replicas)
    start = pod_index * robots_per_pod
    end = min(start + robots_per_pod, total_robots)
    return start, end


def load_profiles(csv_path: str, id_range: tuple[int, int]) -> list[dict]:
    """
    AI4I 2020 CSV를 읽어 id_range 슬라이스 만큼 로봇 프로필을 반환한다.
    CSV 행 수 < global index 이면 행을 순환(cycle)한다.

    Args:
        csv_path: AI4I 2020 시드 CSV 경로
        id_range: (start_global_index, end_global_index) — 전역 robot 번호 슬라이스.
                  e.g. (0, 100) → robot_id ROBOT-00001~ROBOT-00100
                       (300, 400) → robot_id ROBOT-00301~ROBOT-00400 (StatefulSet pod-3)

    컬럼 매핑:
      Process temperature [K] → motor_temp_base  (K-273.15, clamp 60~100°C)
      Rotational speed [rpm]  → load_base         (1168~2886 → 0~100 정규화)
      Tool wear [min]         → drain_factor       (0~250 → 0.1~3.0)
      Machine failure         → is_faulty          (True면 스파이크 확률 70%)
      TWF/HDF/PWF/OSF/RNF     → failure_type       (Task 8.1, ground truth 라벨)
    """
    start, end = id_range
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    profiles = []
    for i in range(start, end):
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

        # is_faulty=True 인데 5종 칼럼이 모두 0인 row가 존재 (CSV 정합) → "RNF"로 기본 분류.
        is_faulty = bool(failure)
        f_type = resolve_failure_type(r) if is_faulty else "NONE"
        if is_faulty and f_type == "NONE":
            f_type = "RNF"

        profiles.append({
            "robot_id":        f"ROBOT-{i+1:05d}",
            "pos_x":           round(grid_x, 6),
            "pos_y":           round(grid_y, 6),
            "motor_temp_base": motor_base,
            "load_base":       load_base,
            "drain_factor":    drain,
            "is_faulty":       is_faulty,
            "failure_type":    f_type,
            "battery":         random.Random().randint(50, 100),
        })
    return profiles


async def simulate_robot(profile: dict,
                          queue: asyncio.Queue,
                          tick_interval: float,
                          shutdown: asyncio.Event,
                          params: dict | None = None,
                          rng: random.Random | None = None) -> None:
    """tick_interval초마다 센서 레코드 1건 생성하여 queue에 넣는다.

    Phase 7: 단발 spike → fault-state machine(NORMAL/RAMPING/OVERHEATED/COOLING/STUCK)
    + load↔temp 상관 + hour-of-day 부하 사이클 + 현실적 battery drain.
    shutdown 이벤트가 set되면 즉시 종료.
    """
    battery = profile["battery"]
    drift   = 0.0  # 점진적 온도 드리프트
    fault_state = init_state()
    last_motor_temp: float | None = None
    charging = False
    if params is None:
        params = _load_realism_params()
    if rng is None:
        rng = random.Random()

    while not shutdown.is_set():
        # 1) 현재 시간대 기반 부하 multiplier
        hour_utc = datetime.now(timezone.utc).hour
        shift_factor = hour_load_multiplier(hour_utc, params["hour_load_variance"])
        current_load = round(
            min(100.0, max(0.0,
                profile["load_base"] * shift_factor + rng.gauss(0, 5))),
            2,
        )

        # 2) Fault state machine 진행
        force_active = time.time() < _force_anomaly_until_ts
        fault_state, episode_delta, is_stuck = advance_phase(
            fault_state, profile, params, force_active, rng,
        )

        # 3) motor_temp 계산: base + load 상관 + noise + drift + episode delta
        if is_stuck and last_motor_temp is not None:
            motor_temp = last_motor_temp
        else:
            noise = rng.gauss(0, 2)
            drift = drift * 0.99 + rng.gauss(0, 0.1)
            load_corr = load_temp_delta(current_load, params["load_temp_coeff"])
            motor_temp = round(
                min(110.0, max(55.0,
                    profile["motor_temp_base"] + load_corr + noise + drift + episode_delta)),
                2,
            )
            last_motor_temp = motor_temp

        # 4) Battery: load·temp factor 기반 drain + 점진적 충전
        if charging:
            battery += rng.uniform(0.5, 1.0)
            if battery >= 100.0:
                battery = 100.0
                charging = False
        else:
            factor = battery_drain_factor(
                current_load, motor_temp,
                params["battery_load_coeff"], params["battery_temp_coeff"],
            )
            battery -= profile["drain_factor"] * factor * rng.uniform(0.01, 0.05)
            if battery <= 5.0:
                charging = True  # 5% 도달 시 charging 진입 (즉시 100% 점프 금지)

        # Task 8.1: fault episode (OVERHEATED/STUCK) 발화 시에만 ground truth
        # failure_type 송출. NORMAL/RAMPING/COOLING 은 NONE — 라벨이 episode 의
        # peak 구간에 정렬되도록 한다 (ML 학습 신호 정합).
        active_phase = fault_state["phase"]
        if active_phase in (Phase.OVERHEATED, Phase.STUCK):
            emit_failure_type = profile.get("failure_type", "NONE")
        else:
            emit_failure_type = "NONE"

        record = {
            "robot_id":      profile["robot_id"],
            "pos_x":         jittered_pos(profile["pos_x"], rng),
            "pos_y":         jittered_pos(profile["pos_y"], rng),
            "battery_level": round(float(max(0.0, min(100.0, battery))), 2),
            "current_load":  current_load,
            "motor_temp":    motor_temp,
            "timestamp":     iso_z_now(),
            "failure_type":  emit_failure_type,
        }
        await queue.put(record)
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=tick_interval)
            return  # shutdown 신호 도착 → 종료
        except asyncio.TimeoutError:
            continue  # 다음 tick


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
            backoff = (2 ** attempt) * 0.1 + _retry_rng.uniform(0, 0.05)
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
                batch.append(to_kinesis_record(record))
            except asyncio.QueueEmpty:
                break

        if batch:
            failed = await _send_with_retry(batch, stream_name, kinesis_client)
            sent_count += len(batch) - failed
            failed_count += failed
        else:
            if shutdown.is_set():
                return
            await asyncio.sleep(0.05)


async def main() -> None:
    # 1000대 production 분할: StatefulSet ordinal 기반 robot ID range.
    # POD_NAME 미설정 시 (로컬 dev) 옛 ROBOT_COUNT env 호환 모드로 fallback.
    if "POD_NAME" in os.environ:
        id_range = _resolve_robot_id_range()
    else:
        legacy_count = int(os.environ.get("ROBOT_COUNT", "100"))
        id_range = (0, legacy_count)

    robot_count   = id_range[1] - id_range[0]
    tick_interval = float(os.environ.get("TICK_INTERVAL_SECONDS", "1.0"))
    stream_name   = os.environ["KINESIS_STREAM_NAME"]
    csv_path      = os.environ.get("SEED_CSV_PATH", "data/seed_data_sample.csv")

    print(f"Loading profiles from {csv_path} for robots {id_range[0]}~{id_range[1]} (tick={tick_interval}s)...")
    profiles = load_profiles(csv_path, id_range)

    kinesis = get_client("kinesis")
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

    realism_params = _load_realism_params()
    sim_tasks = [
        asyncio.create_task(simulate_robot(p, queue, tick_interval, shutdown, realism_params))
        for p in profiles
    ]
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

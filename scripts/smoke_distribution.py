"""Phase 7 분포 검증 smoke test (Task 7.8).

generator 의 fault state machine + load↔temp 상관 + hour cycle 로직을 KDS 송신
없이 N robots × M ticks 시뮬 → motor_temp 분포 히스토그램 + Flink 룰 발화율 출력.

운영 배포 전 fault entry 확률·peak temp delta 등 env tuning 결과를 빠르게 검증.

사용:
    python3 scripts/smoke_distribution.py --robots 1000 --ticks 600

기본값(1000 × 600 = 60만 records) 실행 시간 < 10초. faulty 로봇만 episode 발화.
KDS / Glue / S3 의존성 0 (순수 함수만 호출).
"""
import argparse
import os
import random
import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.generator.app import _load_realism_params, load_profiles
from src.generator._fault_state import Phase, advance_phase, init_state
from src.generator._record import (
    battery_drain_factor,
    hour_load_multiplier,
    load_temp_delta,
)
from src.streaming.anomaly_contract import DEFAULT_THRESHOLDS, is_multivariate_anomaly


# Flink Notebook parity (운영 원본은 AWS Studio Notebook)
FLINK_MIN_TEMP = DEFAULT_THRESHOLDS.min_motor_temp
FLINK_LOAD_RATIO = DEFAULT_THRESHOLDS.load_ratio_threshold


def simulate_one_robot(profile: dict, ticks: int, params: dict, rng: random.Random) -> list[float]:
    """단일 로봇의 motor_temp 시퀀스 반환 (KDS 미전송, async 미사용)."""
    fault_state = init_state()
    last_motor_temp: float | None = None
    drift = 0.0
    battery = profile["battery"]
    charging = False
    motor_temps: list[float] = []
    loads: list[float] = []

    # hour 고정 — 실시간 진행 무관하게 분포 자체를 본다 (UTC 14시 peak 가정)
    hour_utc = datetime.now(timezone.utc).hour

    for _ in range(ticks):
        shift = hour_load_multiplier(hour_utc, params["hour_load_variance"])
        current_load = round(
            min(100.0, max(0.0, profile["load_base"] * shift + rng.gauss(0, 5))), 2
        )

        fault_state, episode_delta, is_stuck = advance_phase(
            fault_state, profile, params, force_anomaly=False, rng=rng,
        )

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

        # battery (분포에 영향 미미하나 charging 진입으로 인한 fault 흐름 영향은 보존)
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
                charging = True

        motor_temps.append(motor_temp)
        loads.append(current_load)

    return motor_temps, loads


def histogram(values: list[float], bins: list[tuple[float, float]]) -> list[tuple[str, int, float]]:
    """[(label, count, pct), ...] 반환."""
    n = len(values)
    out = []
    for lo, hi in bins:
        c = sum(1 for v in values if lo <= v < hi)
        out.append((f"{lo:>5.0f}–{hi:<5.0f}", c, 100.0 * c / n if n else 0.0))
    return out


def flink_anomaly_rate(temps: list[float], loads: list[float]) -> tuple[int, float]:
    """Flink 다변량 branch 발화 건수·비율을 계산한다."""
    hits = sum(is_multivariate_anomaly(t, l) for t, l in zip(temps, loads))
    return hits, 100.0 * hits / max(len(temps), 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--robots", type=int, default=1000)
    parser.add_argument("--ticks", type=int, default=600,
                        help="robot 당 tick 수 (default 600 = 10분 분량)")
    parser.add_argument("--seed-csv", default="data/seed_data_sample.csv")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    random.seed(args.seed)  # gauss 등 module-level 시드 고정

    params = _load_realism_params()
    # load_profiles는 StatefulSet shard와 동일한 전역 id 범위를 받는다.
    profiles = load_profiles(args.seed_csv, (0, args.robots))
    faulty_count = sum(1 for p in profiles if p.get("is_faulty"))

    print(f"[smoke] robots={args.robots} ticks={args.ticks} faulty_profiles={faulty_count}")
    print(f"[smoke] params: fault_entry_prob={params['fault_entry_prob']} "
          f"peak_temp_delta={params['fault_peak_temp_delta']} "
          f"load_temp_coeff={params['load_temp_coeff']}")

    all_temps: list[float] = []
    all_loads: list[float] = []
    for p in profiles:
        # 각 로봇 별도 RNG → 재현성 + 로봇 간 독립
        robot_rng = random.Random(args.seed + hash(p["robot_id"]) % 10**9)
        temps, loads = simulate_one_robot(p, args.ticks, params, robot_rng)
        all_temps.extend(temps)
        all_loads.extend(loads)

    bins = [(55, 65), (65, 75), (75, 85), (85, 90), (90, 95), (95, 100), (100, 110)]
    hist = histogram(all_temps, bins)

    print(f"\n[smoke] motor_temp histogram (n={len(all_temps):,}):")
    for label, count, pct in hist:
        bar = "█" * int(pct / 2)
        print(f"  {label} °C  {count:>10,}  {pct:>6.2f}%  {bar}")

    hits, rate = flink_anomaly_rate(all_temps, all_loads)
    print(f"\n[smoke] Flink 룰 발화 (motor_temp>={FLINK_MIN_TEMP} AND temp/load>{FLINK_LOAD_RATIO}):")
    print(f"  hits={hits:,} / total={len(all_temps):,} → rate={rate:.4f}%")

    target_lo, target_hi = 0.01, 0.05
    if target_lo <= rate <= target_hi:
        verdict = "✅ TARGET"
    elif rate < target_lo:
        verdict = "⚠️  UNDER (faulty 발화 부족 — FAULT_ENTRY_PROB 상향 검토)"
    else:
        verdict = "⚠️  OVER  (anomaly 폭주 — FAULT_PEAK_TEMP_DELTA 하향 또는 FAULT_PEAK_TICKS 단축)"
    print(f"  목표 범위 {target_lo}~{target_hi}% → {verdict}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

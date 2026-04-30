"""Generator helpers shared between daemon (app.py) and backfill (backfill.py).

Stateful per-robot drift in app.py vs stateless backfill is intentional, so
the per-tick record builder is NOT shared. Only truly identical pieces live here.
"""
import json
import math
import random
from datetime import datetime, timezone

ISO_Z_FMT = "%Y-%m-%dT%H:%M:%SZ"


def iso_z_now() -> str:
    return datetime.now(timezone.utc).strftime(ISO_Z_FMT)


def jittered_pos(pos: float) -> float:
    return round(pos + random.uniform(-0.0001, 0.0001), 6)


def jittered_load(load_base: int) -> float:
    # Glue Bronze catalog가 DOUBLE이므로 float로 송신해야 KDF Parquet 변환이
    # 결정적으로 DOUBLE을 선택한다. INT 송신 시 INT32/DOUBLE 비결정 → HIVE_BAD_DATA.
    return round(min(100.0, max(0.0, load_base + random.gauss(0, 5))), 2)


def to_kinesis_record(record: dict) -> dict:
    return {"Data": json.dumps(record).encode(), "PartitionKey": record["robot_id"]}


def load_temp_delta(current_load: float, coeff: float) -> float:
    """부하-온도 양의 상관관계: load 100% → +coeff °C. load≤0은 0으로 clamp."""
    if current_load <= 0:
        return 0.0
    return min(current_load, 100.0) / 100.0 * coeff


def hour_load_multiplier(hour_utc: int, variance: float) -> float:
    """Hour-of-day load 사이클: UTC 14시 peak, 02시 idle. variance=0이면 1.0 상수.

    공식: 1 - variance/2 + variance/2 * cos((hour - 14) * π/12)
    → variance=0.4: peak=1.0, trough=0.6
    """
    if variance == 0:
        return 1.0
    baseline = 1.0 - variance / 2.0
    swing = variance / 2.0 * math.cos((hour_utc - 14) * math.pi / 12)
    return baseline + swing


def battery_drain_factor(
    current_load: float,
    motor_temp: float,
    load_coeff: float,
    temp_coeff: float,
) -> float:
    """Load·temp 영향 multiplier. 기준선 1.0 위에서 가산.

    load_factor = 1 + (load/100) * load_coeff   — 부하 100%일 때 (1+coeff)배
    temp_factor = 1 + max(0, temp-70)/30 * temp_coeff — 70°C 이하면 영향 없음, 100°C 일 때 (1+coeff)배
    """
    load_clamp = max(0.0, min(100.0, current_load))
    load_factor = 1.0 + (load_clamp / 100.0) * load_coeff
    temp_factor = 1.0 + max(0.0, motor_temp - 70.0) / 30.0 * temp_coeff
    return load_factor * temp_factor

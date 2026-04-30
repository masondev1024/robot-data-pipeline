"""Generator helpers shared between daemon (app.py) and backfill (backfill.py).

Stateful per-robot drift in app.py vs stateless backfill is intentional, so
the per-tick record builder is NOT shared. Only truly identical pieces live here.
"""
import json
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

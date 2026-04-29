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


def jittered_load(load_base: int) -> int:
    return int(min(100, max(0, load_base + random.gauss(0, 5))))


def to_kinesis_record(record: dict) -> dict:
    return {"Data": json.dumps(record).encode(), "PartitionKey": record["robot_id"]}

"""Create a deterministic Parquet fixture for the S3-to-RDS Glue lab."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


FIELDS = [
    "robot_id",
    "pos_x",
    "pos_y",
    "battery_level",
    "current_load",
    "motor_temp",
    "timestamp",
    "failure_type",
]


def create_fixture(output: Path, source_csv: Path | None = None) -> Path:
    input_path = source_csv or Path(__file__).parents[1] / "jobs/glue/sample/robot_telemetry_sample.csv"
    with input_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    table = pa.Table.from_pylist(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, output, compression="snappy")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-csv", type=Path)
    args = parser.parse_args()
    path = create_fixture(args.output, args.source_csv)
    print(f"created {path}")


if __name__ == "__main__":
    main()

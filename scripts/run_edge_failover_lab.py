#!/usr/bin/env python3
"""Run the no-AWS multi-region/multi-CDN failover portfolio experiment."""

from __future__ import annotations

import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.edge_reliability.failover import run_region_outage_scenario  # noqa: E402


def main() -> int:
    result = run_region_outage_scenario()
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.failures_after_failover == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

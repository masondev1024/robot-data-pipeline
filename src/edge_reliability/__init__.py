"""Cost-free reliability experiments for edge and media delivery paths."""

from .failover import (
    EdgeEndpoint,
    EdgeRouter,
    ScenarioResult,
    build_demo_topology,
    run_region_outage_scenario,
    validate_topology,
)

__all__ = [
    "EdgeEndpoint",
    "EdgeRouter",
    "ScenarioResult",
    "build_demo_topology",
    "run_region_outage_scenario",
    "validate_topology",
]

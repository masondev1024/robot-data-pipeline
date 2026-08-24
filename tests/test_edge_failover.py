from __future__ import annotations

import pytest

from src.edge_reliability.failover import (
    EdgeEndpoint,
    EdgeRouter,
    build_demo_topology,
    run_region_outage_scenario,
    validate_topology,
)


def test_topology_requires_region_and_cdn_redundancy() -> None:
    with pytest.raises(ValueError, match="2 regions"):
        validate_topology(
            [
                EdgeEndpoint("only", "ap-northeast-2", "cdn-a", 100, 20),
            ]
        )


def test_router_prefers_healthy_capacity_in_preferred_region() -> None:
    router = EdgeRouter(build_demo_topology())

    decision = router.route(300, preferred_region="ap-northeast-2")

    assert decision.status == "ROUTED"
    assert decision.endpoint == "kr-primary"
    assert decision.cdn == "cdn-a"
    assert decision.utilization == 0.3


def test_router_rejects_a_batch_that_exceeds_all_healthy_capacity() -> None:
    router = EdgeRouter(
        [
            EdgeEndpoint("a", "ap-northeast-2", "cdn-a", 100, 20),
            EdgeEndpoint("b", "eu-west-1", "cdn-b", 100, 100),
        ]
    )

    decision = router.route(101)

    assert decision.status == "REJECTED"
    assert decision.reason == "capacity_exhausted"


def test_region_outage_fails_over_to_a_second_cdn_without_residual_errors() -> None:
    result = run_region_outage_scenario()

    assert result.failover_at_second == 6
    assert result.failover_rto_seconds == 2
    assert result.failures_after_failover == 0
    assert result.selected_cdns == ("cdn-a", "cdn-b")
    assert result.availability_percent == pytest.approx(83.33, abs=0.01)


def test_probe_refreshes_health_cache_after_injected_outage() -> None:
    router = EdgeRouter(build_demo_topology())
    router.set_actual_health("kr-primary", False)

    assert router.route(300, preferred_region="ap-northeast-2").endpoint == "kr-primary"
    assert router.probe() == ("kr-primary",)
    assert router.route(300, preferred_region="ap-northeast-2").endpoint == "eu-secondary"

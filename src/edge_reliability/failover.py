"""Deterministic multi-region and multi-CDN failover laboratory.

This module is intentionally dependency-free. It models health probes, routing,
capacity admission, and an injected region outage so the failure policy can be
tested without creating cloud resources or claiming production media traffic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class EdgeEndpoint:
    """An origin/edge path exposed through a region and CDN provider."""

    name: str
    region: str
    cdn: str
    capacity_rps: int
    latency_ms: float
    actual_healthy: bool = True


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """A single routing decision, suitable for structured logging."""

    status: str
    endpoint: str | None
    region: str | None
    cdn: str | None
    reason: str
    estimated_latency_ms: float | None
    utilization: float | None


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """Aggregated evidence from one deterministic failure experiment."""

    scenario: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    failover_at_second: int | None
    failover_rto_seconds: int | None
    p95_latency_ms: float | None
    selected_endpoints: tuple[str, ...]
    selected_cdns: tuple[str, ...]
    failures_after_failover: int

    @property
    def availability_percent(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return round(self.successful_requests / self.total_requests * 100, 2)

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "availability_percent": self.availability_percent,
            "failover_at_second": self.failover_at_second,
            "failover_rto_seconds": self.failover_rto_seconds,
            "p95_latency_ms": self.p95_latency_ms,
            "selected_endpoints": list(self.selected_endpoints),
            "selected_cdns": list(self.selected_cdns),
            "failures_after_failover": self.failures_after_failover,
        }


def validate_topology(
    endpoints: Iterable[EdgeEndpoint],
    *,
    minimum_regions: int = 2,
    minimum_cdns: int = 2,
) -> tuple[EdgeEndpoint, ...]:
    """Validate the minimum topology before a routing policy is deployed."""

    normalized = tuple(endpoints)
    if not normalized:
        raise ValueError("at least one edge endpoint is required")

    names = [endpoint.name for endpoint in normalized]
    if len(names) != len(set(names)):
        raise ValueError("edge endpoint names must be unique")
    if any(endpoint.capacity_rps <= 0 for endpoint in normalized):
        raise ValueError("edge endpoint capacity_rps must be positive")
    if any(endpoint.latency_ms < 0 for endpoint in normalized):
        raise ValueError("edge endpoint latency_ms cannot be negative")

    regions = {endpoint.region for endpoint in normalized}
    cdns = {endpoint.cdn for endpoint in normalized}
    if len(regions) < minimum_regions:
        raise ValueError(
            f"topology needs at least {minimum_regions} regions; found {len(regions)}"
        )
    if len(cdns) < minimum_cdns:
        raise ValueError(
            f"topology needs at least {minimum_cdns} CDN providers; found {len(cdns)}"
        )
    return normalized


class EdgeRouter:
    """Health-cache based router with explicit probe and admission boundaries."""

    def __init__(self, endpoints: Iterable[EdgeEndpoint]) -> None:
        validated = validate_topology(endpoints)
        self._endpoints = {endpoint.name: endpoint for endpoint in validated}
        self._observed_health = {
            endpoint.name: endpoint.actual_healthy for endpoint in validated
        }

    @property
    def endpoints(self) -> tuple[EdgeEndpoint, ...]:
        return tuple(self._endpoints.values())

    def set_actual_health(self, endpoint_name: str, healthy: bool) -> None:
        """Inject an outage; the router learns it only at the next probe."""

        endpoint = self._endpoints.get(endpoint_name)
        if endpoint is None:
            raise KeyError(f"unknown edge endpoint: {endpoint_name}")
        self._endpoints[endpoint_name] = EdgeEndpoint(
            name=endpoint.name,
            region=endpoint.region,
            cdn=endpoint.cdn,
            capacity_rps=endpoint.capacity_rps,
            latency_ms=endpoint.latency_ms,
            actual_healthy=healthy,
        )

    def is_actually_healthy(self, endpoint_name: str) -> bool:
        return self._endpoints[endpoint_name].actual_healthy

    def probe(self) -> tuple[str, ...]:
        """Refresh observed health and return endpoints whose state changed."""

        changed: list[str] = []
        for endpoint in self._endpoints.values():
            observed = self._observed_health[endpoint.name]
            if observed != endpoint.actual_healthy:
                changed.append(endpoint.name)
                self._observed_health[endpoint.name] = endpoint.actual_healthy
        return tuple(changed)

    def route(
        self,
        request_rps: int,
        *,
        preferred_region: str | None = None,
        current_rps: Mapping[str, int] | None = None,
    ) -> RouteDecision:
        """Choose the healthiest endpoint that can admit the request batch."""

        if request_rps <= 0:
            raise ValueError("request_rps must be positive")
        current = current_rps or {}
        candidates = []
        healthy_seen = False
        for endpoint in self._endpoints.values():
            if not self._observed_health[endpoint.name]:
                continue
            healthy_seen = True
            projected_rps = current.get(endpoint.name, 0) + request_rps
            if projected_rps > endpoint.capacity_rps:
                continue
            utilization = projected_rps / endpoint.capacity_rps
            preference_rank = 0 if endpoint.region == preferred_region else 1
            candidates.append((preference_rank, endpoint.latency_ms, utilization, endpoint))

        if not candidates:
            reason = "capacity_exhausted" if healthy_seen else "no_healthy_endpoint"
            return RouteDecision(
                status="REJECTED",
                endpoint=None,
                region=None,
                cdn=None,
                reason=reason,
                estimated_latency_ms=None,
                utilization=None,
            )

        _, _, utilization, endpoint = min(
            candidates, key=lambda item: (item[0], item[1], item[2], item[3].name)
        )
        return RouteDecision(
            status="ROUTED",
            endpoint=endpoint.name,
            region=endpoint.region,
            cdn=endpoint.cdn,
            reason="preferred_healthy_capacity" if preferred_region else "healthy_capacity",
            estimated_latency_ms=endpoint.latency_ms,
            utilization=round(utilization, 4),
        )


def build_demo_topology() -> tuple[EdgeEndpoint, ...]:
    """Return two CDN providers across three regions for the portfolio lab."""

    return (
        EdgeEndpoint(
            name="kr-primary",
            region="ap-northeast-2",
            cdn="cdn-a",
            capacity_rps=1_000,
            latency_ms=35,
        ),
        EdgeEndpoint(
            name="eu-secondary",
            region="eu-west-1",
            cdn="cdn-b",
            capacity_rps=1_000,
            latency_ms=180,
        ),
        EdgeEndpoint(
            name="us-secondary",
            region="us-east-1",
            cdn="cdn-b",
            capacity_rps=2_000,
            latency_ms=220,
        ),
    )


def _p95(samples: list[float]) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
    return ordered[index]


def run_region_outage_scenario(
    endpoints: Iterable[EdgeEndpoint] | None = None,
    *,
    duration_seconds: int = 12,
    failure_at_second: int = 4,
    probe_interval_seconds: int = 3,
    request_rps: int = 300,
    preferred_region: str = "ap-northeast-2",
) -> ScenarioResult:
    """Run an outage experiment and measure failover RTO and residual errors."""

    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if not 0 <= failure_at_second < duration_seconds:
        raise ValueError("failure_at_second must be within the scenario duration")
    if probe_interval_seconds <= 0:
        raise ValueError("probe_interval_seconds must be positive")

    router = EdgeRouter(endpoints or build_demo_topology())
    failed = 0
    successful = 0
    total = duration_seconds * request_rps
    latencies: list[float] = []
    selected: list[str] = []
    selected_cdns: list[str] = []
    failover_at: int | None = None
    failures_after_failover = 0

    for second in range(duration_seconds):
        if second == failure_at_second:
            router.set_actual_health("kr-primary", False)
        if second % probe_interval_seconds == 0:
            router.probe()

        decision = router.route(request_rps, preferred_region=preferred_region)
        if decision.status != "ROUTED":
            failed += request_rps
            if failover_at is not None:
                failures_after_failover += request_rps
            continue

        selected.append(decision.endpoint or "")
        selected_cdns.append(decision.cdn or "")
        if decision.endpoint and not router.is_actually_healthy(decision.endpoint):
            failed += request_rps
            if failover_at is not None:
                failures_after_failover += request_rps
            continue

        successful += request_rps
        if decision.estimated_latency_ms is not None:
            latencies.append(decision.estimated_latency_ms)
        if second >= failure_at_second and decision.endpoint != "kr-primary":
            failover_at = failover_at if failover_at is not None else second

    rto = None if failover_at is None else failover_at - failure_at_second
    return ScenarioResult(
        scenario="primary_region_outage",
        total_requests=total,
        successful_requests=successful,
        failed_requests=failed,
        failover_at_second=failover_at,
        failover_rto_seconds=rto,
        p95_latency_ms=_p95(latencies),
        selected_endpoints=tuple(dict.fromkeys(selected)),
        selected_cdns=tuple(dict.fromkeys(selected_cdns)),
        failures_after_failover=failures_after_failover,
    )

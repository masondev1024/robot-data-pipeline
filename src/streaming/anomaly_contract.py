"""Notebook-parity anomaly contract.

The production detector remains an AWS Managed Flink Studio Notebook. This
module deliberately contains only the deterministic contract used by smoke
tests and integration-test assertions; it is not a Flink deployment artifact.
Keeping the thresholds here prevents local checks and the live validator from
silently drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class AnomalyThresholds:
    """Thresholds that must match the active Studio Notebook paragraph."""

    zscore_threshold: float = 3.0
    sigma_floor: float = 0.5
    min_motor_temp: float = 92.0
    load_ratio_threshold: float = 2.5

    def __post_init__(self) -> None:
        if self.zscore_threshold <= 0:
            raise ValueError("zscore_threshold must be positive")
        if self.sigma_floor <= 0:
            raise ValueError("sigma_floor must be positive")
        if self.load_ratio_threshold <= 0:
            raise ValueError("load_ratio_threshold must be positive")


DEFAULT_THRESHOLDS = AnomalyThresholds()


def compute_zscore(
    temperature: float,
    mean_temperature: float,
    standard_deviation: float,
    sigma_floor: float = DEFAULT_THRESHOLDS.sigma_floor,
) -> float:
    """Return the absolute moving z-score with a zero-variance guard."""

    values = (temperature, mean_temperature, standard_deviation, sigma_floor)
    if not all(isfinite(value) for value in values):
        return 0.0
    denominator = max(abs(standard_deviation), sigma_floor)
    return abs(temperature - mean_temperature) / denominator


def compute_load_ratio(temperature: float, current_load: float) -> float:
    """Return temperature/load while avoiding division by zero."""

    if not isfinite(temperature) or not isfinite(current_load):
        return 0.0
    return temperature / max(current_load, 1.0)


def is_multivariate_anomaly(
    temperature: float,
    current_load: float,
    thresholds: AnomalyThresholds = DEFAULT_THRESHOLDS,
) -> bool:
    """Evaluate the tuned temperature/load condition.

    The comparison is intentionally strict for the ratio, matching the
    notebook SQL predicate ``ratio > threshold``.
    """

    return (
        temperature >= thresholds.min_motor_temp
        and compute_load_ratio(temperature, current_load)
        > thresholds.load_ratio_threshold
    )


def classify_anomaly(
    temperature: float,
    mean_temperature: float,
    standard_deviation: float,
    current_load: float,
    thresholds: AnomalyThresholds = DEFAULT_THRESHOLDS,
) -> dict[str, bool]:
    """Return both detector branches for observability and contract tests."""

    zscore = (
        compute_zscore(
            temperature,
            mean_temperature,
            standard_deviation,
            thresholds.sigma_floor,
        )
        > thresholds.zscore_threshold
    )
    multivariate = is_multivariate_anomaly(temperature, current_load, thresholds)
    return {
        "zscore": zscore,
        "multivariate": multivariate,
        "anomaly": zscore or multivariate,
    }

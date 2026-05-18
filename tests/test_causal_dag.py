"""6-Node DoWhy DAG 단위 테스트 (ADR v2 Decision 3 + Section 5-E).

num_simulations=20 으로 시간 절약 (determinism 검증은 3회 동일 값 확인).
"""

from __future__ import annotations

import hashlib
import json
import warnings

import numpy as np
import pandas as pd
import pytest

from src.orchestration.causal_dag import (
    _dag_to_dot,
    build_dag,
    compute_sigma_max,
    fit_causal_model,
    narrative_kr_for_sigma_max,
    serialize_refute_data,
    synthetic_sensor_data,
)
from src.orchestration.causal_card import load_refute_data, label_for_sigma_max


# ── test_dag_structure ────────────────────────────────────────────────────────

def test_dag_structure():
    """6 노드 + 6 엣지 검증."""
    dag = build_dag()

    expected_nodes = {
        "tool_age", "spindle_rpm", "coolant_temp",
        "vibration_xyz", "thermal_drift", "dimension_dev", "DEFECT",
    }
    expected_edges = {
        ("tool_age", "vibration_xyz"),
        ("spindle_rpm", "vibration_xyz"),
        ("coolant_temp", "thermal_drift"),
        ("vibration_xyz", "dimension_dev"),
        ("thermal_drift", "dimension_dev"),
        ("dimension_dev", "DEFECT"),
    }

    assert set(dag.nodes()) == expected_nodes, f"nodes mismatch: {set(dag.nodes())}"
    assert set(dag.edges()) == expected_edges, f"edges mismatch: {set(dag.edges())}"
    assert len(dag.nodes()) == 7
    assert len(dag.edges()) == 6


# ── test_synthetic_data_deterministic ────────────────────────────────────────

def _df_sha256(df: pd.DataFrame) -> str:
    return hashlib.sha256(
        pd.util.hash_pandas_object(df, index=True).values.tobytes()
    ).hexdigest()


def test_synthetic_data_deterministic():
    """seed=2026 → 3회 호출 동일 SHA256."""
    hashes = [_df_sha256(synthetic_sensor_data(n=1_000, seed=2026)) for _ in range(3)]
    assert len(set(hashes)) == 1, f"non-deterministic: {hashes}"


def test_synthetic_data_columns():
    """컬럼 7개 + DEFECT 이진."""
    df = synthetic_sensor_data(n=500, seed=2026)
    expected_cols = {
        "tool_age", "spindle_rpm", "coolant_temp",
        "vibration_xyz", "thermal_drift", "dimension_dev", "DEFECT",
    }
    assert set(df.columns) == expected_cols
    assert df["DEFECT"].isin([0, 1]).all()
    assert len(df) == 500


# ── test_estimate_ate_positive ────────────────────────────────────────────────

def test_estimate_ate_positive():
    """spindle_rpm ↑ → DEFECT ↑ (양의 ATE).

    causal structure 에서 spindle_rpm → vibration_xyz → dimension_dev → DEFECT
    이므로 ATE > 0 이어야 한다.
    """
    dag = build_dag()
    df = synthetic_sensor_data(n=3_000, seed=2026)
    model = fit_causal_model(df, dag)

    identified = model.identify_effect()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        estimate = model.estimate_effect(identified, method_name="backdoor.linear_regression")

    assert float(estimate.value) > 0, (
        f"Expected positive ATE (spindle_rpm → DEFECT), got {estimate.value}"
    )


# ── test_sigma_max_deterministic ─────────────────────────────────────────────

@pytest.mark.slow
def test_sigma_max_deterministic():
    """seed=2026 → 3회 호출 동일 sigma_max."""
    dag = build_dag()
    df = synthetic_sensor_data(n=3_000, seed=2026)
    model = fit_causal_model(df, dag)

    results = []
    for _ in range(3):
        sigma_max, _ = compute_sigma_max(model, num_simulations=20, seed=2026)
        results.append(sigma_max)

    assert len(set(results)) == 1, f"non-deterministic sigma_max: {results}"


# ── test_serialize_roundtrip ──────────────────────────────────────────────────

def test_serialize_roundtrip(tmp_path):
    """serialize → load_refute_data → 동일 sigma_max."""
    dag = build_dag()
    df = synthetic_sensor_data(n=1_000, seed=2026)
    model = fit_causal_model(df, dag)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sigma_max, summary = compute_sigma_max(model, num_simulations=20, seed=2026)

    out_path = str(tmp_path / "causal_refute_v2.json")
    raw_print = "test raw print output"
    serialize_refute_data(sigma_max=sigma_max, summary=summary, raw_print=raw_print, path=out_path)

    loaded = load_refute_data(out_path)
    assert loaded.sigma_max == sigma_max
    assert loaded.raw_print == raw_print
    assert loaded.method_summary["unobserved_common_cause"]["sigma_max"] == sigma_max


# ── test_narrative ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "sigma_max,expected_label",
    [
        (0.1, "robust"),
        (0.42, "robust"),
        (0.5, "moderate"),
        (0.75, "moderate"),
        (1.0, "fragile"),
    ],
)
def test_narrative_contains_label(sigma_max: float, expected_label: str):
    narrative = narrative_kr_for_sigma_max(sigma_max)
    assert expected_label in narrative
    assert str(round(sigma_max, 2)) in narrative

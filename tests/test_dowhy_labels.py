"""σ_max → ✅/⚠️/❌ 매핑 검증 (ADR v2 Decision 3 + Section 6 Unit, C2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.orchestration.causal_card import (
    CausalRefuteData,
    icon_for_label,
    label_for_sigma_max,
    load_refute_data,
)


# ── label_for_sigma_max ─────────────────────────────────────────

@pytest.mark.parametrize(
    "sigma_max,expected",
    [
        (0.0, "robust"),
        (0.42, "robust"),
        (0.499, "robust"),
        (0.5, "moderate"),
        (0.75, "moderate"),
        (0.999, "moderate"),
        (1.0, "fragile"),
        (1.20, "fragile"),
        (100.0, "fragile"),
    ],
)
def test_label_threshold(sigma_max: float, expected: str):
    assert label_for_sigma_max(sigma_max) == expected


def test_icon_mapping():
    assert icon_for_label("robust") == "✅"
    assert icon_for_label("moderate") == "⚠️"
    assert icon_for_label("fragile") == "❌"


# ── CausalRefuteData schema ─────────────────────────────────────

def test_valid_refute_data():
    data = CausalRefuteData(
        sigma_max=0.42,
        narrative_kr="모든 4 refuter 통과, effect sign 유지",
        raw_print="Refute: Add a Random Common Cause\nEstimated effect:0.62\nNew effect:0.61\np value:0.91\n",
        method_summary={
            "placebo": {"p_value": 0.91},
            "random_common_cause": {"new_effect": 0.61},
            "unobserved_common_cause": {"sigma_max": 0.42},
            "data_subset": {"new_effect": 0.63},
        },
    )
    assert data.sigma_max == 0.42
    assert label_for_sigma_max(data.sigma_max) == "robust"


def test_invalid_refute_negative_sigma():
    with pytest.raises(ValidationError):
        CausalRefuteData(
            sigma_max=-0.1,
            narrative_kr="test",
            raw_print="x",
            method_summary={},
        )


def test_invalid_refute_narrative_too_long():
    with pytest.raises(ValidationError):
        CausalRefuteData(
            sigma_max=0.5,
            narrative_kr="가" * 301,
            raw_print="x",
            method_summary={},
        )


# ── load_refute_data ────────────────────────────────────────────

def test_load_refute_data_roundtrip(tmp_path: Path):
    sample = {
        "sigma_max": 0.83,
        "narrative_kr": "moderate confounder strength, 추정치 주의",
        "raw_print": "Refute (4 methods)...",
        "method_summary": {"placebo": {"p_value": 0.74}},
    }
    p = tmp_path / "causal_refute_v2.json"
    p.write_text(json.dumps(sample), encoding="utf-8")

    data = load_refute_data(p)
    assert data.sigma_max == 0.83
    assert label_for_sigma_max(data.sigma_max) == "moderate"


def test_load_refute_data_missing_file():
    with pytest.raises(FileNotFoundError):
        load_refute_data("nonexistent_path_xyz.json")

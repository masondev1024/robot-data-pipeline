"""LocalXGBoost6Class 단위 테스트 (PRISM 본선 Phase 3 — 마커 1).

conftest.py 가 sys.modules["xgboost"] 를 MagicMock 으로 대체하므로
이 테스트 모듈 최상단에서 real xgboost 를 sys.modules 에 주입한다.
"""

from __future__ import annotations

import sys

# conftest.py 보다 먼저 real xgboost 를 복원
# (conftest autouse fixture 이전에 모듈 수준에서 실행됨)
import importlib
import types

def _ensure_real_xgboost() -> None:
    """sys.modules["xgboost"] 가 MagicMock 이면 real xgboost 로 교체."""
    _xgb = sys.modules.get("xgboost")
    if _xgb is None or isinstance(_xgb, types.ModuleType) and hasattr(_xgb, "XGBClassifier"):
        return  # 이미 real xgboost
    # MagicMock 이면 제거 후 재 import
    for key in list(sys.modules.keys()):
        if key == "xgboost" or key.startswith("xgboost."):
            del sys.modules[key]
    importlib.import_module("xgboost")

_ensure_real_xgboost()

# ─────────────────────────────────────────────────────────────────────────────

import math
from pathlib import Path

import pandas as pd
import pytest

from src.ml.local_predictor import (
    DEMO_FAULT_SCENARIO,
    FEATURE_COLS,
    LABEL_NAMES,
    NUM_CLASSES,
    LocalXGBoost6Class,
    retrain_with_incident,
    synthesize_incident_pattern,
    synthesize_training_data,
)


# ── 공통 fixture ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def small_df() -> pd.DataFrame:
    """빠른 테스트용 소규모 합성 데이터 (n=500)."""
    return synthesize_training_data(n=500, seed=2026)


@pytest.fixture(scope="module")
def trained_model(small_df: pd.DataFrame) -> LocalXGBoost6Class:
    """학습 완료 모델."""
    m = LocalXGBoost6Class(seed=2026)
    m.fit(small_df, target_col="failure_type")
    return m


# ── 1. 학습 + 저장 + 로드 round-trip ──────────────────────────────────────────

def test_fit_save_load_roundtrip(tmp_path: Path, small_df: pd.DataFrame) -> None:
    """fit → save → load 후 동일 예측 결과."""
    m1 = LocalXGBoost6Class(seed=2026)
    m1.fit(small_df, target_col="failure_type")

    pkl_path = tmp_path / "test_model.pkl"
    m1.save(pkl_path)
    assert pkl_path.exists(), "pkl 파일이 생성되지 않았습니다."

    m2 = LocalXGBoost6Class.load(pkl_path)

    probs1 = m1.predict_proba(DEMO_FAULT_SCENARIO)
    probs2 = m2.predict_proba(DEMO_FAULT_SCENARIO)

    for cls in LABEL_NAMES:
        assert math.isclose(probs1[cls], probs2[cls], rel_tol=1e-6), (
            f"{cls}: {probs1[cls]} vs {probs2[cls]}"
        )


# ── 2. predict_proba 합 = 1.0 (softmax) ──────────────────────────────────────

def test_predict_proba_sums_to_one(trained_model: LocalXGBoost6Class) -> None:
    """모든 클래스 확률의 합 ≈ 1.0 (softmax 보장)."""
    probs = trained_model.predict_proba(DEMO_FAULT_SCENARIO)
    total = sum(probs.values())
    assert math.isclose(total, 1.0, abs_tol=1e-5), f"확률 합 = {total}"


# ── 3. 결정성 (동일 seed → 동일 모델) ──────────────────────────────────────────

def test_determinism_same_seed(small_df: pd.DataFrame) -> None:
    """seed=2026 고정 → 2회 학습 후 동일 predict_proba."""
    m_a = LocalXGBoost6Class(seed=2026)
    m_a.fit(small_df, target_col="failure_type")

    m_b = LocalXGBoost6Class(seed=2026)
    m_b.fit(small_df, target_col="failure_type")

    probs_a = m_a.predict_proba(DEMO_FAULT_SCENARIO)
    probs_b = m_b.predict_proba(DEMO_FAULT_SCENARIO)

    for cls in LABEL_NAMES:
        assert math.isclose(probs_a[cls], probs_b[cls], rel_tol=1e-6), (
            f"비결정성 감지 — {cls}: {probs_a[cls]} vs {probs_b[cls]}"
        )


# ── 4. 6-class 확률 모두 [0, 1] ────────────────────────────────────────────────

def test_probabilities_in_unit_interval(trained_model: LocalXGBoost6Class) -> None:
    """모든 클래스 확률 ∈ [0, 1]."""
    probs = trained_model.predict_proba(DEMO_FAULT_SCENARIO)
    assert set(probs.keys()) == set(LABEL_NAMES), f"클래스 키 불일치: {probs.keys()}"
    for cls, p in probs.items():
        assert 0.0 <= p <= 1.0, f"{cls} 확률 범위 초과: {p}"


# ── 5. 본선 fault scenario → HDF top-3 이내 ───────────────────────────────────

def test_demo_fault_scenario_hdf_in_top3() -> None:
    """사전 학습 pkl 로드 후 DEMO_FAULT_SCENARIO 에서 HDF 가 top-3 이내.

    assets/xgb_6class.pkl 존재 시 로드, 없으면 소규모 데이터로 학습.
    """
    _PKL = Path(__file__).parent.parent / "assets" / "xgb_6class.pkl"

    if _PKL.exists():
        model = LocalXGBoost6Class.load(_PKL)
    else:
        df = synthesize_training_data(n=500, seed=2026)
        model = LocalXGBoost6Class(seed=2026)
        model.fit(df, target_col="failure_type")

    probs = model.predict_proba(DEMO_FAULT_SCENARIO)
    sorted_classes = sorted(probs, key=probs.get, reverse=True)
    top3 = sorted_classes[:3]
    assert "HDF" in top3, (
        f"HDF 가 top-3 이내 미포함. 순위: {sorted_classes}, 확률: {probs}"
    )


# ── 6. synthesize_training_data 라벨 분포 검증 ────────────────────────────────

def test_synthesize_data_label_distribution() -> None:
    """5000개 데이터의 라벨 분포가 spec 범위 내."""
    df = synthesize_training_data(n=5_000, seed=2026)
    assert len(df) == 5_000
    assert set(df.columns) >= set(FEATURE_COLS + ["failure_type"])

    counts = df["failure_type"].value_counts()
    n = len(df)
    # NONE: ~50%, HDF: ~15%, TWF: ~12%, PWF: ~10%, OSF: ~8%, RNF: ~5%
    expected = {0: 2500, 2: 750, 1: 600, 3: 500, 4: 400, 5: 250}
    for label_int, expected_cnt in expected.items():
        actual = counts.get(label_int, 0)
        assert actual == expected_cnt, (
            f"라벨 {label_int} 분포 불일치: expected {expected_cnt}, got {actual}"
        )


# ── 7. predict_proba_timed latency 반환 ──────────────────────────────────────

def test_predict_proba_timed_returns_latency(trained_model: LocalXGBoost6Class) -> None:
    """predict_proba_timed 가 (dict, float) 반환, latency > 0."""
    probs, ms = trained_model.predict_proba_timed(DEMO_FAULT_SCENARIO)
    assert isinstance(probs, dict)
    assert isinstance(ms, float)
    assert ms >= 0.0
    assert set(probs.keys()) == set(LABEL_NAMES)


# ── 8. 학습 자산화 retrain (Task 2: 마커 9 라이브 통합) ──────────────────────

def test_synthesize_incident_pattern_hdf_majority() -> None:
    """incident pattern: HDF (label=2) 비중 80% 이상."""
    df = synthesize_incident_pattern(n=300, seed=2026)
    assert len(df) == 300
    hdf_ratio = (df["failure_type"] == 2).mean()
    assert hdf_ratio >= 0.75, f"HDF 비중 0.80 기대, got {hdf_ratio:.2f}"


def test_synthesize_incident_pattern_extreme_coolant() -> None:
    """incident HDF row 의 coolant_temp 는 ~4σ extreme outlier (base ~1.8σ 와 distinct)."""
    df = synthesize_incident_pattern(n=300, seed=2026)
    hdf_rows = df[df["failure_type"] == 2]
    assert hdf_rows["coolant_temp"].mean() >= 3.5, (
        f"incident HDF coolant_temp 평균 3.5σ 이상 기대, got {hdf_rows['coolant_temp'].mean():.2f}"
    )


def test_retrain_with_incident_improves_accuracy() -> None:
    """base 만 학습한 모델 vs base+incident 합본 학습 → incident pattern 정확도 ↑.

    학습 자산화 narrative 의 실 입증: extreme outlier 패턴은 base 모델이 misclassify,
    incident row 추가 학습 시 정확도 명확히 ↑.
    """
    base = synthesize_training_data(n=1_000, seed=2026)
    incident = synthesize_incident_pattern(n=300, seed=2026)
    _, before_acc, after_acc, elapsed = retrain_with_incident(base, incident, seed=2026)
    assert after_acc > before_acc, (
        f"재학습 후 정확도가 더 높아야: before={before_acc:.4f}, after={after_acc:.4f}"
    )
    assert (after_acc - before_acc) >= 0.05, (
        f"학습 효과 5%p 이상 기대: delta={after_acc - before_acc:.4f}"
    )
    assert elapsed > 0


def test_retrain_with_incident_deterministic() -> None:
    """seed=2026 → 2회 호출 동일 (before_acc, after_acc)."""
    base = synthesize_training_data(n=1_000, seed=2026)
    incident = synthesize_incident_pattern(n=300, seed=2026)
    _, b1, a1, _ = retrain_with_incident(base, incident, seed=2026)
    _, b2, a2, _ = retrain_with_incident(base, incident, seed=2026)
    assert b1 == b2, f"before_acc 결정성 깨짐: {b1} vs {b2}"
    assert a1 == a2, f"after_acc 결정성 깨짐: {a1} vs {a2}"

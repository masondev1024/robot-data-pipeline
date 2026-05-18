"""6-Node DoWhy DAG + Confounder Robustness 사전 계산 (ADR v2 Decision 3, Section 5-E).

DoWhy 0.8 / networkx 3.4+ 호환 shim 포함:
  - nx.algorithms.d_separated  → nx.algorithms.d_separation.is_d_separator
  - RegressionEstimator._estimate_effect  → params.iloc[0] 수정

본선 당일 라이브 DoWhy 호출 X — assets/causal_refute_v2.json 사전 계산값만 read.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ── DoWhy / networkx 호환 shim (project-level, site-packages 미수정) ──────────
def _apply_dowhy_shims() -> None:
    """DoWhy 0.8 + networkx 3.4+ 호환 monkey-patch.

    1. nx.algorithms.d_separated 누락 → is_d_separator 로 alias.
    2. RegressionEstimator._estimate_effect 의 params[0] integer-index →
       params.iloc[0] 로 교체 (pandas 2.x 에서 named-index KeyError 방지).
    """
    import networkx as nx
    if not hasattr(nx.algorithms, "d_separated"):
        nx.algorithms.d_separated = nx.algorithms.d_separation.is_d_separator

    import dowhy.causal_estimators.regression_estimator as _re
    from dowhy.causal_estimator import CausalEstimate

    def _patched_estimate_effect(self, data_df=None, need_conditional_estimates=None):  # noqa: ANN001
        if data_df is None:
            data_df = self._data
        if need_conditional_estimates is None:
            need_conditional_estimates = self.need_conditional_estimates
        if not self.model:
            _, self.model = self._build_model()
            coefficients = self.model.params.iloc[1:]
            self.logger.debug(
                "Coefficients of the fitted model: " + ",".join(map(str, coefficients))
            )
            self.logger.debug(self.model.summary())
        effect_estimate = (
            self._do(self._treatment_value, data_df)
            - self._do(self._control_value, data_df)
        )
        conditional_effect_estimates = None
        if need_conditional_estimates:
            conditional_effect_estimates = self._estimate_conditional_effects(
                self._estimate_effect_fn,
                effect_modifier_names=self._effect_modifier_names,
            )
        return CausalEstimate(
            estimate=effect_estimate,
            control_value=self._control_value,
            treatment_value=self._treatment_value,
            conditional_estimates=conditional_effect_estimates,
            target_estimand=self._target_estimand,
            realized_estimand_expr=self.symbolic_estimator,
            intercept=self.model.params.iloc[0],
        )

    _re.RegressionEstimator._estimate_effect = _patched_estimate_effect


_apply_dowhy_shims()

import dowhy  # noqa: E402  (must come after shim)
import networkx as nx  # noqa: E402


# ── DAG 정의 ─────────────────────────────────────────────────────────────────

_NODES = [
    "tool_age",
    "spindle_rpm",
    "coolant_temp",
    "vibration_xyz",
    "thermal_drift",
    "dimension_dev",
    "DEFECT",
]

_EDGES = [
    ("tool_age", "vibration_xyz"),
    ("spindle_rpm", "vibration_xyz"),
    ("coolant_temp", "thermal_drift"),
    ("vibration_xyz", "dimension_dev"),
    ("thermal_drift", "dimension_dev"),
    ("dimension_dev", "DEFECT"),
]


def build_dag() -> nx.DiGraph:
    """6-노드 + 6-엣지 인과 DAG 반환."""
    g = nx.DiGraph()
    g.add_nodes_from(_NODES)
    g.add_edges_from(_EDGES)
    return g


# ── DOT 직렬화 ────────────────────────────────────────────────────────────────

def _dag_to_dot(dag: nx.DiGraph) -> str:
    """DoWhy CausalModel graph= 파라미터용 DOT 문자열 생성."""
    edges = " ".join(f"{u} -> {v};" for u, v in dag.edges())
    return f"digraph {{ {edges} }}"


# ── 합성 데이터 ───────────────────────────────────────────────────────────────

def synthetic_sensor_data(n: int = 5_000, seed: int = 2026) -> pd.DataFrame:
    """DAG 결정 구조 + Gaussian noise 로 합성 시계열 데이터 생성.

    causal structure (standardised coefficients):
        tool_age      ~ N(0,1)
        spindle_rpm   ~ N(0,1)
        coolant_temp  ~ N(0,1)
        vibration_xyz = 0.4*tool_age + 0.6*spindle_rpm + noise(0.3)
        thermal_drift = 0.7*coolant_temp              + noise(0.3)
        dimension_dev = 0.5*vibration_xyz + 0.5*thermal_drift + noise(0.2)
        DEFECT        = Bernoulli(sigmoid(2.0*dimension_dev))
    """
    rng = np.random.default_rng(seed)

    tool_age = rng.normal(0, 1, n)
    spindle_rpm = rng.normal(0, 1, n)
    coolant_temp = rng.normal(0, 1, n)

    vibration_xyz = 0.4 * tool_age + 0.6 * spindle_rpm + rng.normal(0, 0.3, n)
    thermal_drift = 0.7 * coolant_temp + rng.normal(0, 0.3, n)
    dimension_dev = 0.5 * vibration_xyz + 0.5 * thermal_drift + rng.normal(0, 0.2, n)

    defect_prob = 1.0 / (1.0 + np.exp(-2.0 * dimension_dev))
    DEFECT = (rng.uniform(0, 1, n) < defect_prob).astype(int)

    return pd.DataFrame(
        {
            "tool_age": tool_age,
            "spindle_rpm": spindle_rpm,
            "coolant_temp": coolant_temp,
            "vibration_xyz": vibration_xyz,
            "thermal_drift": thermal_drift,
            "dimension_dev": dimension_dev,
            "DEFECT": DEFECT,
        }
    )


# ── DoWhy 모델 ────────────────────────────────────────────────────────────────

def fit_causal_model(df: pd.DataFrame, dag: nx.DiGraph) -> dowhy.CausalModel:
    """DoWhy CausalModel: treatment=spindle_rpm, outcome=DEFECT."""
    return dowhy.CausalModel(
        data=df,
        treatment="spindle_rpm",
        outcome="DEFECT",
        graph=_dag_to_dot(dag),
        proceed_when_unidentifiable=True,
    )


def estimate_ate(model: dowhy.CausalModel) -> float:
    """backdoor.linear_regression ATE 추정."""
    identified = model.identify_effect()
    estimate = model.estimate_effect(identified, method_name="backdoor.linear_regression")
    return float(estimate.value)


# ── Refute + σ_max ────────────────────────────────────────────────────────────

def _scan_sigma_max(
    model: dowhy.CausalModel,
    identified: Any,
    estimate: Any,
    strengths: list[float],
) -> float:
    """Confounder strength 스캔 → effect sign change 발생 지점 반환 (σ_max).

    effect sign change: new_effect * original_effect < 0.
    sign change 없으면 최대 스캔 strength 반환 (≥ 1.0 이면 fragile 판정 회피 목적으로 max+0.1).
    """
    original_effect = float(estimate.value)
    for s in strengths:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = model.refute_estimate(
                identified,
                estimate,
                method_name="add_unobserved_common_cause",
                confounders_effect_on_treatment="linear",
                confounders_effect_on_outcome="linear",
                effect_strength_on_treatment=s,
                effect_strength_on_outcome=s,
            )
        if float(r.new_effect) * original_effect <= 0:
            return s
    return strengths[-1]


def compute_sigma_max(
    model: dowhy.CausalModel,
    num_simulations: int = 100,
    seed: int = 2026,
) -> tuple[float, dict]:
    """4 refute method 호출 + σ_max 산출.

    Returns:
        sigma_max: effect sign change confounder strength (partial R² proxy).
        summary: {placebo, random_common_cause, unobserved_common_cause, data_subset}.
    """
    np.random.seed(seed)

    identified = model.identify_effect()
    estimate = model.estimate_effect(identified, method_name="backdoor.linear_regression")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        r_placebo = model.refute_estimate(
            identified,
            estimate,
            method_name="placebo_treatment_refuter",
            num_simulations=num_simulations,
            random_seed=seed,
        )
        r_random_cc = model.refute_estimate(
            identified,
            estimate,
            method_name="random_common_cause",
            num_simulations=num_simulations,
            random_seed=seed,
        )
        r_data_subset = model.refute_estimate(
            identified,
            estimate,
            method_name="data_subset_refuter",
            subset_fraction=0.8,
            num_simulations=num_simulations,
            random_seed=seed,
        )

    # partial R² 스캔: 0.05 단위 0.05 ~ 2.0
    scan_strengths = [round(x * 0.05, 4) for x in range(1, 41)]
    sigma_max = _scan_sigma_max(model, identified, estimate, scan_strengths)

    # unobserved summary: σ_max 지점의 new_effect
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r_unobs = model.refute_estimate(
            identified,
            estimate,
            method_name="add_unobserved_common_cause",
            confounders_effect_on_treatment="linear",
            confounders_effect_on_outcome="linear",
            effect_strength_on_treatment=sigma_max,
            effect_strength_on_outcome=sigma_max,
        )

    # placebo p_value 추출 (DoWhy 0.8 refutation_result dict 또는 float)
    placebo_rr = r_placebo.refutation_result
    if isinstance(placebo_rr, dict):
        placebo_p = placebo_rr.get("p_value", float("nan"))
        if hasattr(placebo_p, "item"):
            placebo_p = placebo_p.item()
    else:
        placebo_p = float(placebo_rr) if placebo_rr is not None else float("nan")

    summary = {
        "placebo": {"p_value": placebo_p},
        "random_common_cause": {"new_effect": float(r_random_cc.new_effect)},
        "unobserved_common_cause": {"sigma_max": float(sigma_max)},
        "data_subset": {"new_effect": float(r_data_subset.new_effect)},
    }

    return sigma_max, summary


def _collect_raw_print(model: dowhy.CausalModel, num_simulations: int = 100, seed: int = 2026) -> str:
    """4 refute method 의 str() 결과 concat (causal_card raw_print 필드용)."""
    import io
    np.random.seed(seed)

    identified = model.identify_effect()
    estimate = model.estimate_effect(identified, method_name="backdoor.linear_regression")

    lines = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for method, kwargs in [
            ("placebo_treatment_refuter", {"num_simulations": num_simulations, "random_seed": seed}),
            ("random_common_cause", {"num_simulations": num_simulations, "random_seed": seed}),
            ("data_subset_refuter", {"subset_fraction": 0.8, "num_simulations": num_simulations, "random_seed": seed}),
        ]:
            r = model.refute_estimate(identified, estimate, method_name=method, **kwargs)
            lines.append(str(r))

    return "\n\n".join(lines)


# ── 직렬화 ────────────────────────────────────────────────────────────────────

def serialize_refute_data(
    sigma_max: float,
    summary: dict,
    raw_print: str,
    path: str = "assets/causal_refute_v2.json",
) -> None:
    """CausalRefuteData schema 검증 후 JSON 저장."""
    from src.orchestration.causal_card import CausalRefuteData, label_for_sigma_max

    narrative = narrative_kr_for_sigma_max(sigma_max)

    data = CausalRefuteData(
        sigma_max=sigma_max,
        narrative_kr=narrative,
        raw_print=raw_print,
        method_summary=summary,
    )

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(data.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Narrative ─────────────────────────────────────────────────────────────────

def narrative_kr_for_sigma_max(sigma_max: float) -> str:
    """σ_max 에 따라 한국어 narrative 생성."""
    from src.orchestration.causal_card import label_for_sigma_max

    label = label_for_sigma_max(sigma_max)
    if label == "robust":
        return (
            f"4 refuter 통과, effect sign 유지. "
            f"σ_max={sigma_max:.2f} (robust) — "
            "관측되지 않은 교란변수가 결과 분산의 "
            f"{sigma_max:.0%} 이하를 설명해야 effect 방향이 역전됩니다."
        )
    if label == "moderate":
        return (
            f"4 refuter 통과, σ_max={sigma_max:.2f} (moderate) — "
            "50-100% partial R² 교란변수 가정 시 effect 가 0 으로 수렴할 수 있습니다. "
            "주요 공변량 통제 권고."
        )
    return (
        f"σ_max={sigma_max:.2f} (fragile) — "
        "1× partial R² 미만 교란변수 strength 에서도 effect sign 이 역전됩니다. "
        "추가 변수 수집 또는 도구변수 추정 권고."
    )

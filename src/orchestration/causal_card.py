"""DoWhy Confounder Robustness 사이드바 카드 (ADR v2 Decision 3, C2).

σ_max 임계 정의 (Wright 1991, partial R²):
- σ_max < 0.5  → ✅ robust  (effect sign 유지)
- 0.5 ≤ σ_max < 1.0 → ⚠️ moderate (50-100% partial R² confounder 가 effect 를 0 으로 끌어내릴 수 있음)
- σ_max ≥ 1.0 → ❌ fragile  (1× partial R² 미만 confounder 도 sign 바꿈)

사전 계산값 (D-2 5/20 작업): assets/causal_refute_v2.json.
runtime DoWhy 호출 없음 (시연 결정성 prerequisite, Section 5-E mitigation).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

CausalLabel = Literal["robust", "moderate", "fragile"]


class CausalRefuteData(BaseModel):
    """assets/causal_refute_v2.json 의 schema (D-2 작업으로 생성)."""

    model_config = ConfigDict(extra="forbid")
    sigma_max: float = Field(..., ge=0.0)
    narrative_kr: str = Field(..., max_length=300)
    raw_print: str = Field(..., description="DoWhy `print(refute)` native text (4 method 결과 concat)")
    method_summary: dict = Field(
        ...,
        description="{placebo: {p_value: float}, random_common_cause: {new_effect: float}, "
        "unobserved_common_cause: {sigma_max: float}, data_subset: {new_effect: float}}",
    )


def label_for_sigma_max(sigma_max: float) -> CausalLabel:
    """ADR v2 Decision 3 의 임계 매핑."""
    if sigma_max < 0.5:
        return "robust"
    if sigma_max < 1.0:
        return "moderate"
    return "fragile"


def icon_for_label(label: CausalLabel) -> str:
    return {"robust": "✅", "moderate": "⚠️", "fragile": "❌"}[label]


def load_refute_data(path: str | Path = "assets/causal_refute_v2.json") -> CausalRefuteData:
    """사전 계산 파일 load. 본선 당일 라이브 DoWhy 호출 X."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return CausalRefuteData.model_validate(raw)


def render_card(refute: CausalRefuteData) -> None:
    """Streamlit sidebar card. import 는 함수 내부 (테스트가 streamlit 없이 가능)."""
    import streamlit as st

    label = label_for_sigma_max(refute.sigma_max)
    icon = icon_for_label(label)
    line = f"{icon} {label} (σ_max = {refute.sigma_max:.2f})"

    with st.sidebar:
        st.markdown("### 🧭 Causal RCA — Confounder Robustness")
        if label == "robust":
            st.success(line)
        elif label == "moderate":
            st.warning(line)
        else:
            st.error(line)
        st.caption(f"DoWhy refute: {refute.narrative_kr}")
        with st.expander("🔍 자세히 (native output)"):
            st.code(refute.raw_print, language="text")

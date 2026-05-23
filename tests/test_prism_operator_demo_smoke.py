"""PRISM Operator-first app smoke tests."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path


_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _import_operator_demo_no_st() -> types.ModuleType:
    try:
        import streamlit  # noqa: F401
    except ModuleNotFoundError:
        import unittest.mock as mock

        sys.modules.setdefault("streamlit", mock.MagicMock())

    for pkg in ("plotly", "plotly.graph_objects", "networkx"):
        if pkg not in sys.modules:
            try:
                importlib.import_module(pkg)
            except ModuleNotFoundError:
                import unittest.mock as mock

                sys.modules[pkg] = mock.MagicMock()

    spec = importlib.util.spec_from_file_location(
        "apps.prism_operator_demo",
        str(_ROOT / "apps" / "prism_operator_demo.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_operator_view_is_first_option():
    demo = _import_operator_demo_no_st()
    assert [demo.OPERATOR_VIEW_MODE, demo.TIMELINE_VIEW_MODE, demo.V3_VIEW_MODE][0] == demo.OPERATOR_VIEW_MODE


def test_operator_app_reuses_demo_markers():
    demo = _import_operator_demo_no_st()
    assert len(demo.MARKERS) == 11
    assert demo.MARKERS[0][0] == 0
    assert demo.MARKERS[-1][0] == 225


def test_operator_incident_recommendation():
    demo = _import_operator_demo_no_st()
    title, action, why = demo._operator_recommendation(5)
    assert title == "AI 추천 적용"
    assert "spindle_reduce_10pct" in action
    assert "Net Value" in why


def test_operator_normal_recommendation():
    demo = _import_operator_demo_no_st()
    title, action, why = demo._operator_recommendation(0)
    assert title == "모니터링 유지"
    assert "정상" in action
    assert "백그라운드" in why

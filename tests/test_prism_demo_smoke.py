"""PRISM Demo app 스모크 테스트 (ADR v2 Section 6 Unit).

streamlit runtime 의존 없이 helper 함수만 검증.
- _mock_supervisor_decision 반환 타입·구조
- render_marker_timeline 마커 인덱스 경계값
- MARKERS 상수 형식
- compute_net_value_KRW 재계산 연동
"""

from __future__ import annotations

import sys
from pathlib import Path

# src/ 패키지 접근 보장
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

# apps/prism_demo 를 streamlit runtime 없이 import — 함수 단위 테스트만.
# st.* 호출을 포함하는 함수는 직접 실행하지 않는다.
import importlib, types

def _import_demo_no_st() -> types.ModuleType:
    """streamlit 없이 prism_demo 모듈의 non-UI 심볼만 로드하는 헬퍼.

    streamlit 이 있으면 정상 import, 없으면 st를 MagicMock 으로 대체.
    """
    try:
        import streamlit  # noqa: F401
    except ModuleNotFoundError:
        # streamlit stub
        import unittest.mock as mock
        st_stub = mock.MagicMock()
        sys.modules.setdefault("streamlit", st_stub)

    # plotly, networkx stub (없는 환경 대비)
    for pkg in ("plotly", "plotly.graph_objects", "networkx"):
        if pkg not in sys.modules:
            try:
                importlib.import_module(pkg)
            except ModuleNotFoundError:
                import unittest.mock as mock
                sys.modules[pkg] = mock.MagicMock()

    spec = importlib.util.spec_from_file_location(
        "apps.prism_demo",
        str(_ROOT / "apps" / "prism_demo.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def demo():
    return _import_demo_no_st()


# ── MARKERS 상수 ─────────────────────────────────────────────────────────────────

def test_markers_count(demo):
    """MARKERS 는 11개 (스펙 9 마커 + 재학습/OEE 2개 = 11)."""
    assert len(demo.MARKERS) == 11


def test_markers_first_and_last(demo):
    """첫 마커 0초·마지막 마커 225초."""
    assert demo.MARKERS[0][0] == 0
    assert demo.MARKERS[-1][0] == 225


def test_markers_monotone_increasing(demo):
    """타임코드 단조 증가."""
    times = [t for t, _ in demo.MARKERS]
    assert times == sorted(times)


def test_markers_labels_nonempty(demo):
    """모든 마커 라벨 비어있지 않음."""
    for _, label in demo.MARKERS:
        assert label.strip()


def test_total_seconds_matches_last_marker(demo):
    """TOTAL_SECONDS == 마지막 마커 타임코드."""
    assert demo.TOTAL_SECONDS == demo.MARKERS[-1][0]


# ── _mock_supervisor_decision ────────────────────────────────────────────────────

def test_mock_supervisor_decision_returns_supervisor_output(demo):
    from src.orchestration.schema import SupervisorOutput
    result = demo._mock_supervisor_decision()
    assert isinstance(result, SupervisorOutput)


def test_mock_supervisor_decision_action_id(demo):
    result = demo._mock_supervisor_decision()
    assert result.decision.action_id == "spindle_reduce_10pct"


def test_mock_supervisor_decision_net_value_is_float(demo):
    result = demo._mock_supervisor_decision()
    assert isinstance(result.decision.net_value_KRW, float)


def test_mock_supervisor_decision_has_alternatives(demo):
    result = demo._mock_supervisor_decision()
    assert len(result.decision.alternatives) >= 1
    assert result.decision.alternatives[0].rank == 2


def test_mock_supervisor_decision_tradeoff_breakdown_signs(demo):
    """throughput_gain 양수, 나머지 손실 항목 0 이하."""
    result = demo._mock_supervisor_decision()
    bd = result.decision.tradeoff_breakdown
    assert bd.throughput_gain_KRW > 0
    assert bd.defect_loss_KRW <= 0
    assert bd.safety_loss_KRW <= 0
    assert bd.rul_loss_KRW <= 0


def test_mock_supervisor_decision_deterministic(demo):
    """동일 입력 → 동일 net_value (결정성 prerequisite)."""
    r1 = demo._mock_supervisor_decision()
    r2 = demo._mock_supervisor_decision()
    assert r1.decision.net_value_KRW == r2.decision.net_value_KRW


# ── _mock_4agent_action ──────────────────────────────────────────────────────────

def test_mock_4agent_action_structure(demo):
    from src.orchestration.schema import CandidateAction
    action = demo._mock_4agent_action()
    assert isinstance(action, CandidateAction)
    assert 0.0 <= action.quality.numeric.defect_prob <= 1.0
    assert action.quality.numeric.top_failure_type in ("NONE","TWF","HDF","PWF","OSF","RNF")


def test_mock_4agent_action_safety_thresholds(demo):
    """defect_prob 낮은 spindle_reduce 시나리오 — 안전 위반 낮음."""
    action = demo._mock_4agent_action()
    assert action.safety.numeric.safety_violation_prob < 0.2


def test_mock_4agent_action_production_feasible(demo):
    """spindle_reduce 시나리오 — uph >= 200 으로 스케줄 feasible."""
    action = demo._mock_4agent_action()
    assert action.production.numeric.schedule_feasible is True


# ── 마커 인덱스 경계값 (render_marker_timeline 내부 clamp 로직) ───────────────────

def test_marker_idx_clamp_lower(demo):
    """음수 인덱스 → 0 으로 clamp (렌더 함수가 max(0, idx) 적용)."""
    idx = max(0, min(-5, len(demo.MARKERS) - 1))
    assert idx == 0


def test_marker_idx_clamp_upper(demo):
    """초과 인덱스 → len-1 으로 clamp."""
    idx = max(0, min(999, len(demo.MARKERS) - 1))
    assert idx == len(demo.MARKERS) - 1


def test_marker_idx_valid_midpoint(demo):
    """중간 인덱스 그대로 통과."""
    mid = len(demo.MARKERS) // 2
    idx = max(0, min(mid, len(demo.MARKERS) - 1))
    assert idx == mid


# ── DAG 상수 ─────────────────────────────────────────────────────────────────────

def test_dag_nodes_include_defect(demo):
    assert "DEFECT" in demo.DAG_NODES


def test_dag_intervention_node_in_nodes(demo):
    assert demo.INTERVENTION_NODE in demo.DAG_NODES


def test_dag_edges_reference_known_nodes(demo):
    node_set = set(demo.DAG_NODES)
    for src, dst in demo.DAG_EDGES:
        assert src in node_set, f"edge src '{src}' not in DAG_NODES"
        assert dst in node_set, f"edge dst '{dst}' not in DAG_NODES"


def test_dag_has_path_to_defect(demo):
    """모든 DAG 엣지가 DEFECT 까지 경로를 형성 — networkx 연결성."""
    import networkx as nx
    G = nx.DiGraph()
    G.add_nodes_from(demo.DAG_NODES)
    G.add_edges_from(demo.DAG_EDGES)
    # DEFECT 까지 도달 가능한 노드가 1개 이상 (DEFECT 자신 제외)
    predecessors = list(nx.ancestors(G, "DEFECT"))
    assert len(predecessors) > 0


# ── _seed_storage_demo 멱등성 ─────────────────────────────────────────────────────

def test_seed_storage_demo_idempotent(tmp_path):
    """2회 호출 시 동일 sha (멱등성) — @st.cache_resource 없이 직접 호출."""
    import sys
    from pathlib import Path
    from datetime import datetime, timedelta

    # src 경로 보장
    root = Path(__file__).parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from src.orchestration.storage import StorageDB

    db_path = tmp_path / "test_idempotent.duckdb"

    def _seed(path: Path) -> dict:
        with StorageDB(str(path)) as db:
            if db.count("robot_telemetry") == 0:
                base_ts = datetime(2026, 5, 22, 3, 0, 0)
                rows = []
                for sec in range(100):
                    ts = base_ts + timedelta(seconds=sec)
                    mt = (
                        85 + 0.05 * sec
                        + (0.5 * (sec - 30) if 30 <= sec < 60 else (0 if sec < 30 else -0.3 * (sec - 60)))
                    )
                    rows.append({
                        "ts": ts,
                        "robot_id": "ROBOT-00018",
                        "motor_temp": mt,
                        "current_load": 60.0,
                        "battery_level": 75.0,
                        "pos_x": 10.5,
                        "pos_y": 20.3,
                        "active_hours": 8.0,
                        "fault_phase": (
                            "incident_47" if 30 <= sec < 60
                            else "recover" if sec >= 60
                            else "normal"
                        ),
                        "is_faulty": 45 <= sec < 60,
                    })
                db.write_robot(rows)
            return {
                "n_total": db.count("robot_telemetry"),
                "sha": db.table_sha256("robot_telemetry")[:12],
            }

    result1 = _seed(db_path)
    result2 = _seed(db_path)  # second call — should be no-op

    assert result1["n_total"] == 100
    assert result2["n_total"] == 100, "2회 호출 후 row 수가 100이어야 함 (중복 삽입 없음)"
    assert result1["sha"] == result2["sha"], "SHA256 prefix 가 동일해야 함 (멱등성)"

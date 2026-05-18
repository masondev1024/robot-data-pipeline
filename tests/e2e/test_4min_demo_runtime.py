"""PRISM 4분 시연 e2e 결정성 검증 (ADR v2 §7 Verification Gate, D-1 prep).

검증:
1. assets/cache_replay.jsonl 51 entries
2. Supervisor.negotiate_with_candidates 3 시나리오 cache hit (Bedrock 호출 0회)
3. 3 시나리오 × 3회 호출 → byte-equal 결정성
4. compute_net_value_KRW 동일 입력 byte-equal
5. e2e runtime < 1초 (cache replay)

실행:
    cd /Users/mason/Desktop/Projects/robot-data-pipeline
    PYTHONHASHSEED=2026 PRISM_MODE=demo python3 -m pytest tests/e2e/test_4min_demo_runtime.py -v
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── fixture ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _demo_env(monkeypatch):
    """PRISM_MODE=demo + cache path 강제."""
    monkeypatch.setenv("PYTHONHASHSEED", "2026")
    monkeypatch.setenv("PRISM_MODE", "demo")
    monkeypatch.setenv(
        "PRISM_CACHE_PATH",
        str(ROOT / "assets" / "cache_replay.jsonl"),
    )


@pytest.fixture
def supervisor():
    from src.orchestration.supervisor import Supervisor, SupervisorConfig
    return Supervisor(config=SupervisorConfig(alpha=1.0, beta=1.0, gamma=1.0, horizon_h=4))


# ── cache 인프라 ────────────────────────────────────────────────


def test_cache_replay_jsonl_has_51_entries():
    cache_path = ROOT / "assets" / "cache_replay.jsonl"
    assert cache_path.exists(), f"missing: {cache_path}"
    lines = [
        line for line in cache_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 51, f"cache entries {len(lines)} != 51"


def test_supervisor_negotiate_cache_hit_no_bedrock(supervisor):
    """fault scenario — cache hit, Bedrock 호출 0회 (miss → BedrockError raise)."""
    from apps.prism_demo import _SCENARIOS, _CANDIDATE_ACTIONS
    sup_out, candidates = supervisor.negotiate_with_candidates(
        _SCENARIOS["fault"], _CANDIDATE_ACTIONS
    )
    assert sup_out.decision.action_id in _CANDIDATE_ACTIONS
    assert len(candidates) == 4


# ── byte-equal 결정성 ────────────────────────────────────────────


def _decision_blob(sup_out) -> str:
    """SupervisorOutput → 정렬된 JSON string (deterministic 비교용)."""
    d = sup_out.decision
    return json.dumps({
        "action_id": d.action_id,
        "net_value_KRW": round(d.net_value_KRW, 2),
        "alternatives": [
            {"action_id": a.action_id,
             "net_value_KRW": round(a.net_value_KRW, 2),
             "rank": a.rank}
            for a in d.alternatives
        ],
        "tradeoff_breakdown": {
            "throughput_gain_KRW": round(d.tradeoff_breakdown.throughput_gain_KRW, 2),
            "defect_loss_KRW":     round(d.tradeoff_breakdown.defect_loss_KRW, 2),
            "safety_loss_KRW":     round(d.tradeoff_breakdown.safety_loss_KRW, 2),
            "rul_loss_KRW":        round(d.tradeoff_breakdown.rul_loss_KRW, 2),
        },
    }, sort_keys=True)


@pytest.mark.parametrize("scenario_id", ["normal", "fault", "recover"])
def test_supervisor_decision_byte_equal_three_runs(scenario_id):
    """3 시나리오 각각 3회 호출 → byte-equal (시연 결정성 prerequisite)."""
    from apps.prism_demo import _SCENARIOS, _CANDIDATE_ACTIONS
    from src.orchestration.supervisor import Supervisor, SupervisorConfig

    config = SupervisorConfig(alpha=1.0, beta=1.0, gamma=1.0, horizon_h=4)
    blobs = []
    for _ in range(3):
        sup = Supervisor(config=config)
        sup_out, _ = sup.negotiate_with_candidates(
            _SCENARIOS[scenario_id], _CANDIDATE_ACTIONS
        )
        blobs.append(_decision_blob(sup_out))

    assert blobs[0] == blobs[1] == blobs[2], (
        f"determinism 깨짐 ({scenario_id}): {blobs}"
    )


def test_compute_net_value_byte_equal_repeat():
    """compute_net_value_KRW 동일 입력 5회 byte-equal."""
    from src.orchestration.schema import (
        compute_net_value_KRW,
        QualityAgentOutput, QualityNumeric,
        SafetyAgentOutput, SafetyNumeric,
        EquipmentAgentOutput, EquipmentNumeric,
        ProductionAgentOutput, ProductionNumeric,
    )
    q = QualityAgentOutput(
        numeric=QualityNumeric(defect_prob=0.62, top_failure_type="HDF"),
        narrative_kr="t",
    )
    s = SafetyAgentOutput(
        numeric=SafetyNumeric(sop_violation=True, estop_required=False, safety_violation_prob=0.40),
        narrative_kr="t",
    )
    e = EquipmentAgentOutput(
        numeric=EquipmentNumeric(rul_hours=18.0, isolation_forest_score=-0.34),
        narrative_kr="t",
    )
    p = ProductionAgentOutput(
        numeric=ProductionNumeric(throughput_uph=235.0, schedule_feasible=True, lp_solution_id="lp_x"),
        narrative_kr="t",
    )
    nets = [compute_net_value_KRW(q, s, e, p, horizon_h=4) for _ in range(5)]
    first_net = nets[0][0]
    first_bd = nets[0][1].model_dump()
    for n, bd in nets[1:]:
        assert n == first_net
        assert bd.model_dump() == first_bd


# ── runtime budget (ADR §7 verification gate) ─────────────────────


def test_e2e_runtime_3_scenarios_under_1s(supervisor):
    """3 scenario × Supervisor.negotiate (16 cache hit) 합산 < 1초.

    ADR §7 verification gate 의 e2e_runtime ≤ 225s pre-check —
    1초 초과 = cache miss (live Bedrock 호출).
    """
    from apps.prism_demo import _SCENARIOS, _CANDIDATE_ACTIONS

    t0 = time.monotonic()
    for scenario_id in ["normal", "fault", "recover"]:
        sup_out, candidates = supervisor.negotiate_with_candidates(
            _SCENARIOS[scenario_id], _CANDIDATE_ACTIONS
        )
        assert sup_out.decision.action_id in _CANDIDATE_ACTIONS
        assert len(candidates) == 4
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, (
        f"3 시나리오 e2e > 1초: {elapsed:.2f}s — cache miss (live Bedrock 호출) 의심"
    )


# ── beta slider 시연 정합 (mason 발표 narrative) ──────────────────


def test_fault_beta_slider_recommendation_shift():
    """fault 시나리오: β=1 → continue, β=2+ → throttle_50pct (slider 시연 narrative)."""
    from apps.prism_demo import _SCENARIOS, _CANDIDATE_ACTIONS
    from src.orchestration.supervisor import Supervisor, SupervisorConfig

    def _decision_for_beta(beta: float) -> str:
        sup = Supervisor(config=SupervisorConfig(alpha=1.0, beta=beta, gamma=1.0, horizon_h=4))
        out, _ = sup.negotiate_with_candidates(_SCENARIOS["fault"], _CANDIDATE_ACTIONS)
        return out.decision.action_id

    # β=1 default 면 continue (위험 감수)
    assert _decision_for_beta(1.0) == "continue", "β=1 default 시 continue 권고 (시연 narrative)"
    # β=2 이상이면 throttle (보수성 가산)
    assert _decision_for_beta(2.0) == "throttle_50pct", "β=2 시 throttle 권고 (slider 시연)"
    assert _decision_for_beta(5.0) == "throttle_50pct", "β=5 극보수 시 throttle 유지"

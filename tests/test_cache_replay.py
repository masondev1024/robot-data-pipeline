"""cache_replay.jsonl 검증 (ADR v2 Decision 2, Triple Insurance (b)).

각 entry:
  1. response JSON 이 Pydantic schema (QualityAgentOutput / SafetyAgentOutput /
     EquipmentAgentOutput / ProductionAgentOutput / SupervisorOutput) 를 통과.
  2. LLMCache.get(key) 가 hit 되는지 확인 (재현성 보장).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.orchestration.llm_cache import LLMCache, cache_key
from src.orchestration.schema import (
    EquipmentAgentOutput,
    ProductionAgentOutput,
    QualityAgentOutput,
    SafetyAgentOutput,
    SupervisorOutput,
)

# ── fixtures ────────────────────────────────────────────────────────────────

CACHE_PATH = Path(__file__).parent.parent / "assets" / "cache_replay.jsonl"

# agent slug → Pydantic model (supervisor handled separately)
_AGENT_SCHEMA = {
    "quality": QualityAgentOutput,
    "safety": SafetyAgentOutput,
    "equipment": EquipmentAgentOutput,
    "production": ProductionAgentOutput,
}

HAIKU_MODEL = "anthropic.claude-haiku-4-5-20251001-v1:0"
SONNET_MODEL = "anthropic.claude-sonnet-4-6-20250513-v1:0"


def _load_entries() -> list[dict]:
    assert CACHE_PATH.exists(), f"cache_replay.jsonl 없음: {CACHE_PATH}"
    entries = []
    for line in CACHE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


# ── helpers ─────────────────────────────────────────────────────────────────

import hashlib
import re

MOCK_TIMESTAMP = "2026-05-22T03:00:00Z"
_TS_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:[+\-Z][\d:]*)?)?"
)


def _recompute_key(model_id: str, system_prompt: str, user_prompt: str, tool_state) -> str:
    """Replicate cache_key logic locally (no import side-effects)."""
    def _norm_sys(p):
        return "\n".join(line.rstrip() for line in p.splitlines())

    def _norm_user(p):
        return _TS_PATTERN.sub(MOCK_TIMESTAMP, p)

    def _norm_tool(s):
        return json.dumps(s or {}, sort_keys=True, ensure_ascii=False)

    parts = [
        model_id.strip(),
        _norm_sys(system_prompt),
        _norm_user(user_prompt),
        _norm_tool(tool_state),
    ]
    blob = "\n---\n".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ── tests ────────────────────────────────────────────────────────────────────


def test_cache_file_exists():
    assert CACHE_PATH.exists(), "assets/cache_replay.jsonl 가 없습니다."


def test_entry_count():
    """정확히 51 개 (3 시점 × 4 candidates × 4 agents + 3 supervisor)."""
    entries = _load_entries()
    assert len(entries) == 51, f"entry 수 불일치: {len(entries)} != 51"


def test_all_keys_unique():
    entries = _load_entries()
    keys = [e["key"] for e in entries]
    assert len(keys) == len(set(keys)), "중복 key 존재"


def test_all_entries_have_key_and_response():
    for i, entry in enumerate(_load_entries()):
        assert "key" in entry, f"entry {i}: 'key' 필드 없음"
        assert "response" in entry, f"entry {i}: 'response' 필드 없음"


def test_all_keys_are_sha256_hex():
    """key 가 64자 hex string 인지 확인."""
    for i, entry in enumerate(_load_entries()):
        assert len(entry["key"]) == 64, f"entry {i}: key 길이 != 64"
        int(entry["key"], 16)  # raises ValueError if not hex


def test_all_response_values_are_valid_json():
    for i, entry in enumerate(_load_entries()):
        resp = entry["response"]
        assert isinstance(resp, str), f"entry {i}: response 가 str 아님"
        try:
            json.loads(resp)
        except json.JSONDecodeError as exc:
            pytest.fail(f"entry {i}: response JSON 파싱 실패 — {exc}")


def test_pydantic_validation_domain_agents():
    """48 domain-agent entries: 각 response 가 해당 schema 를 통과."""
    entries = _load_entries()
    # domain-agent entries = first 48 (3 scenarios × 4 candidates × 4 agents, in order)
    # agent order per (scenario, action) block: quality, safety, equipment, production
    agent_order = ["quality", "safety", "equipment", "production"]
    domain_entries = entries[:48]
    assert len(domain_entries) == 48

    for idx, entry in enumerate(domain_entries):
        agent_slot = idx % 4
        agent_name = agent_order[agent_slot]
        schema_cls = _AGENT_SCHEMA[agent_name]
        raw_dict = json.loads(entry["response"])
        try:
            schema_cls.model_validate(raw_dict)
        except Exception as exc:
            scenario_idx = idx // 16
            action_idx = (idx % 16) // 4
            scenario = ["normal", "fault", "recovery"][scenario_idx]
            action = ["continue", "halt", "throttle_50pct", "schedule_maintenance"][action_idx]
            pytest.fail(
                f"Pydantic 검증 실패 [{agent_name}|{scenario}|{action}] entry {idx}: {exc}"
            )


def test_pydantic_validation_supervisor():
    """마지막 3 entries: SupervisorOutput 검증."""
    entries = _load_entries()
    supervisor_entries = entries[48:]
    assert len(supervisor_entries) == 3, f"supervisor entry 수 != 3: {len(supervisor_entries)}"

    for idx, entry in enumerate(supervisor_entries):
        raw_dict = json.loads(entry["response"])
        try:
            SupervisorOutput.model_validate(raw_dict)
        except Exception as exc:
            scenario = ["normal", "fault", "recovery"][idx]
            pytest.fail(f"SupervisorOutput 검증 실패 [{scenario}]: {exc}")


def test_narrative_kr_max_300_chars():
    """모든 narrative_kr / rationale_kr ≤ 300 자."""
    entries = _load_entries()
    agent_order = ["quality", "safety", "equipment", "production"]

    for idx, entry in enumerate(entries):
        raw_dict = json.loads(entry["response"])

        if idx < 48:
            narr = raw_dict.get("narrative_kr", "")
            assert len(narr) <= 300, (
                f"entry {idx}: narrative_kr {len(narr)} > 300 chars"
            )
        else:
            # supervisor
            rationale = raw_dict.get("decision", {}).get("rationale_kr", "")
            assert len(rationale) <= 300, (
                f"supervisor entry {idx}: rationale_kr {len(rationale)} > 300 chars"
            )


def test_domain_numerics_in_range():
    """numeric 필드 범위 체크 (schema constraint 보조 검증)."""
    entries = _load_entries()
    agent_order = ["quality", "safety", "equipment", "production"]

    for idx, entry in enumerate(entries[:48]):
        agent_name = agent_order[idx % 4]
        raw = json.loads(entry["response"])["numeric"]

        if agent_name == "quality":
            assert 0.0 <= raw["defect_prob"] <= 1.0, f"entry {idx}: defect_prob out of range"
            assert raw["top_failure_type"] in {"NONE", "TWF", "HDF", "PWF", "OSF", "RNF"}
        elif agent_name == "safety":
            assert 0.0 <= raw["safety_violation_prob"] <= 1.0
            assert isinstance(raw["sop_violation"], bool)
            assert isinstance(raw["estop_required"], bool)
        elif agent_name == "equipment":
            assert raw["rul_hours"] >= 0.0
            assert -1.0 <= raw["isolation_forest_score"] <= 1.0
        elif agent_name == "production":
            assert raw["throughput_uph"] >= 0.0
            assert isinstance(raw["schedule_feasible"], bool)
            uph = raw["throughput_uph"]
            sf = raw["schedule_feasible"]
            assert (uph >= 200) == sf, (
                f"entry {idx}: schedule_feasible={sf} inconsistent with uph={uph}"
            )


def test_llmcache_get_hits_all_entries():
    """LLMCache(cache_replay.jsonl).get(key) 가 51 개 모두 hit."""
    cache = LLMCache(CACHE_PATH)
    entries = _load_entries()

    misses = []
    for i, entry in enumerate(entries):
        result = cache.get(entry["key"])
        if result is None:
            misses.append(i)

    assert not misses, f"cache miss 발생한 entry indices: {misses}"
    assert cache.hits == 51


def test_llmcache_hit_rate_100pct():
    """모든 entry 조회 후 hit_rate = 1.0."""
    cache = LLMCache(CACHE_PATH)
    entries = _load_entries()
    for entry in entries:
        cache.get(entry["key"])
    assert cache.hit_rate() == pytest.approx(1.0)


def test_supervisor_decision_action_ids_valid():
    """supervisor entries 의 decision.action_id 가 알려진 action 중 하나."""
    valid_actions = {"continue", "halt", "throttle_50pct", "schedule_maintenance"}
    entries = _load_entries()
    for idx, entry in enumerate(entries[48:]):
        raw = json.loads(entry["response"])
        action_id = raw["decision"]["action_id"]
        assert action_id in valid_actions, (
            f"supervisor entry {idx}: unknown action_id={action_id!r}"
        )


def test_supervisor_alternatives_rank_sequential():
    """alternatives rank 가 2 부터 연속 증가 (gaps 없음)."""
    entries = _load_entries()
    for idx, entry in enumerate(entries[48:]):
        raw = json.loads(entry["response"])
        alts = raw["decision"]["alternatives"]
        ranks = [a["rank"] for a in alts]
        expected = list(range(2, 2 + len(ranks)))
        assert ranks == expected, (
            f"supervisor entry {idx}: alternative ranks {ranks} != {expected}"
        )


def test_fault_scenario_supervisor_recommends_halt():
    """fault 시나리오 supervisor 가 halt 권고 (시연 핵심 결정)."""
    entries = _load_entries()
    # supervisor entries: index 48=normal, 49=fault, 50=recovery
    fault_sup = json.loads(entries[49]["response"])
    assert fault_sup["decision"]["action_id"] == "halt", (
        "fault 시나리오 supervisor 가 halt 을 선택해야 합니다 (3:00 마커)."
    )


def test_recovery_scenario_supervisor_recommends_continue():
    """recovery 시나리오 supervisor 가 continue 권고 (OEE +35% 회복)."""
    entries = _load_entries()
    recovery_sup = json.loads(entries[50]["response"])
    assert recovery_sup["decision"]["action_id"] == "continue", (
        "recovery 시나리오 supervisor 가 continue 를 선택해야 합니다 (3:45 마커)."
    )

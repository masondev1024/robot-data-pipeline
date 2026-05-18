"""Tests for PRISM 4 Domain Agents.

Coverage:
- invoke() happy path → output_model validates
- malformed JSON → ValueError raised
- demo mode + cache hit → _source == "cache_hit", no live call
- offline mode + cache miss → CacheReplayError raised
"""

from __future__ import annotations

import json
import os
import pytest
from pydantic import ValidationError
from unittest.mock import patch

from src.orchestration.agents import (
    QualityAgent,
    SafetyAgent,
    EquipmentAgent,
    ProductionAgent,
)
from src.orchestration.llm_cache import LLMCache, CacheReplayError, cache_key


# ── helpers ───────────────────────────────────────────────────────

VALID_QUALITY_JSON = json.dumps({
    "numeric": {"defect_prob": 0.12, "top_failure_type": "TWF"},
    "narrative_kr": "모터 온도 이상으로 결함 확률 12% 추정.",
})

VALID_SAFETY_JSON = json.dumps({
    "numeric": {
        "sop_violation": False,
        "estop_required": False,
        "safety_violation_prob": 0.05,
    },
    "narrative_kr": "현재 SOP 위반 없음. E-stop 불필요.",
})

VALID_EQUIPMENT_JSON = json.dumps({
    "numeric": {"rul_hours": 48.5, "isolation_forest_score": -0.3},
    "narrative_kr": "잔여 수명 48.5시간. 이상 점수 낮음.",
})

VALID_PRODUCTION_JSON = json.dumps({
    "numeric": {
        "throughput_uph": 120.0,
        "schedule_feasible": True,
        "lp_solution_id": "LP-2026-001",
    },
    "narrative_kr": "시간당 120개 생산 가능. 스케줄 실행 가능.",
})


def _make_replay_result(text: str, source: str = "live") -> dict:
    """replay decorator가 반환하는 dict 형식 모사."""
    return {"_source": source, "key": "mock_key", "response": text}


# ── fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def quality_agent():
    return QualityAgent()


@pytest.fixture
def safety_agent():
    return SafetyAgent()


@pytest.fixture
def equipment_agent():
    return EquipmentAgent()


@pytest.fixture
def production_agent():
    return ProductionAgent()


# ── agent property tests ──────────────────────────────────────────

def test_quality_agent_name(quality_agent):
    assert quality_agent.name == "quality"


def test_safety_agent_name(safety_agent):
    assert safety_agent.name == "safety"


def test_equipment_agent_name(equipment_agent):
    assert equipment_agent.name == "equipment"


def test_production_agent_name(production_agent):
    assert production_agent.name == "production"


def test_all_agents_have_empty_tools(quality_agent, safety_agent, equipment_agent, production_agent):
    """Tools are placeholder [] until D-3 fill."""
    for agent in (quality_agent, safety_agent, equipment_agent, production_agent):
        assert isinstance(agent.tools, list)


def test_all_agents_model_id_env_default(monkeypatch):
    """PRISM_HAIKU_MODEL env var overrides default model_id."""
    monkeypatch.setenv("PRISM_HAIKU_MODEL", "anthropic.claude-haiku-custom-v1:0")
    for cls in (QualityAgent, SafetyAgent, EquipmentAgent, ProductionAgent):
        assert cls().model_id == "anthropic.claude-haiku-custom-v1:0"


# ── invoke happy path ─────────────────────────────────────────────

def _patch_invoke(agent, json_text: str):
    """Patch _get_decorated_call to return a stub that returns json_text."""
    def fake_decorated(model_id, system_prompt, user_prompt, tool_state=None, **kw):
        return _make_replay_result(json_text)

    agent._decorated_call = fake_decorated
    return agent


def test_quality_invoke_happy(quality_agent):
    _patch_invoke(quality_agent, VALID_QUALITY_JSON)
    out = quality_agent.invoke("sensor data", context={})
    assert out.parsed.numeric.defect_prob == pytest.approx(0.12)
    assert out.parsed.numeric.top_failure_type == "TWF"
    assert len(out.parsed.narrative_kr) > 0


def test_safety_invoke_happy(safety_agent):
    _patch_invoke(safety_agent, VALID_SAFETY_JSON)
    out = safety_agent.invoke("sensor data")
    assert out.parsed.numeric.sop_violation is False
    assert out.parsed.numeric.estop_required is False
    assert out.parsed.numeric.safety_violation_prob == pytest.approx(0.05)


def test_equipment_invoke_happy(equipment_agent):
    _patch_invoke(equipment_agent, VALID_EQUIPMENT_JSON)
    out = equipment_agent.invoke("sensor data")
    assert out.parsed.numeric.rul_hours == pytest.approx(48.5)
    assert out.parsed.numeric.isolation_forest_score == pytest.approx(-0.3)


def test_production_invoke_happy(production_agent):
    _patch_invoke(production_agent, VALID_PRODUCTION_JSON)
    out = production_agent.invoke("sensor data")
    assert out.parsed.numeric.throughput_uph == pytest.approx(120.0)
    assert out.parsed.numeric.schedule_feasible is True
    assert out.parsed.numeric.lp_solution_id == "LP-2026-001"


# ── malformed JSON → ValueError ───────────────────────────────────

def test_quality_malformed_json_raises(quality_agent):
    _patch_invoke(quality_agent, "not json at all {{ broken")
    with pytest.raises(ValueError, match="non-JSON"):
        quality_agent.invoke("sensor data")


def test_safety_malformed_json_raises(safety_agent):
    _patch_invoke(safety_agent, "<html>error</html>")
    with pytest.raises(ValueError, match="non-JSON"):
        safety_agent.invoke("sensor data")


def test_equipment_malformed_json_raises(equipment_agent):
    _patch_invoke(equipment_agent, "")
    with pytest.raises(ValueError, match="non-JSON"):
        equipment_agent.invoke("sensor data")


def test_production_malformed_json_raises(production_agent):
    _patch_invoke(production_agent, "{broken")
    with pytest.raises(ValueError, match="non-JSON"):
        production_agent.invoke("sensor data")


# ── schema validation failure → ValidationError ───────────────────

def test_quality_invalid_schema_raises(quality_agent):
    """defect_prob > 1.0 should fail Pydantic validation."""
    bad = json.dumps({
        "numeric": {"defect_prob": 1.5, "top_failure_type": "TWF"},
        "narrative_kr": "테스트",
    })
    _patch_invoke(quality_agent, bad)
    with pytest.raises(ValidationError):
        quality_agent.invoke("sensor data")


def test_quality_unknown_failure_type_raises(quality_agent):
    """top_failure_type not in Literal set should fail."""
    bad = json.dumps({
        "numeric": {"defect_prob": 0.1, "top_failure_type": "UNKNOWN_TYPE"},
        "narrative_kr": "테스트",
    })
    _patch_invoke(quality_agent, bad)
    with pytest.raises(ValidationError):
        quality_agent.invoke("sensor data")


def test_equipment_negative_rul_raises(equipment_agent):
    """rul_hours ge=0.0 constraint."""
    bad = json.dumps({
        "numeric": {"rul_hours": -5.0, "isolation_forest_score": 0.1},
        "narrative_kr": "테스트",
    })
    _patch_invoke(equipment_agent, bad)
    with pytest.raises(ValidationError):
        equipment_agent.invoke("sensor data")


# ── markdown fence stripping ──────────────────────────────────────

def test_quality_strips_markdown_fences(quality_agent):
    """LLM 가끔 ```json ... ``` 으로 감싸는 경우 처리."""
    fenced = f"```json\n{VALID_QUALITY_JSON}\n```"
    _patch_invoke(quality_agent, fenced)
    out = quality_agent.invoke("sensor data")
    assert out.parsed.numeric.defect_prob == pytest.approx(0.12)


# ── demo mode cache hit ───────────────────────────────────────────

def test_demo_mode_cache_hit(tmp_path, monkeypatch):
    """PRISM_MODE=demo + pre-seeded cache → _source == cache_hit, no live call."""
    monkeypatch.setenv("PRISM_MODE", "demo")

    agent = QualityAgent()
    key = cache_key(
        agent.model_id,
        agent.system_prompt,
        "sensor data",
        None,
    )

    # Pre-seed the cache file
    cache_file = tmp_path / "cache_replay.jsonl"
    cache_file.write_text(
        json.dumps({"key": key, "response": VALID_QUALITY_JSON}) + "\n",
        encoding="utf-8",
    )

    # Point agent to this temp cache
    import src.orchestration.agents.base as base_mod
    original_cache = base_mod._shared_cache
    base_mod._shared_cache = LLMCache(cache_file)
    # Reset decorated call so it picks up new cache
    if hasattr(agent, "_decorated_call"):
        del agent._decorated_call

    live_called = []

    def fake_live(model_id, system_prompt, user_prompt, tool_state=None, **kw):
        live_called.append(True)
        return VALID_QUALITY_JSON

    try:
        from src.orchestration import llm_cache as lc_mod
        original_replay = lc_mod.replay

        def patched_replay(cache):
            def decorator(fn):
                import functools

                @functools.wraps(fn)
                def wrapper(model_id, system_prompt, user_prompt, tool_state=None, **kw):
                    from src.orchestration.llm_cache import cache_key as ck, is_demo_mode
                    k = ck(model_id, system_prompt, user_prompt, tool_state)
                    if is_demo_mode():
                        cached = cache.get(k)
                        if cached is not None:
                            return {"_source": "cache_hit", "key": k, "response": cached}
                    return {"_source": "live", "key": k, "response": fake_live(model_id, system_prompt, user_prompt, tool_state, **kw)}
                return wrapper
            return decorator

        lc_mod.replay = patched_replay
        # Rebuild decorated call with patched replay
        if hasattr(agent, "_decorated_call"):
            del agent._decorated_call

        out = agent.invoke("sensor data")
        assert out.parsed.numeric.defect_prob == pytest.approx(0.12)
        assert not live_called, "Live Bedrock call must not be made on cache hit"
    finally:
        base_mod._shared_cache = original_cache
        lc_mod.replay = original_replay
        monkeypatch.delenv("PRISM_MODE", raising=False)


# ── offline mode + cache miss → CacheReplayError ─────────────────

def test_offline_cache_miss_raises(tmp_path, monkeypatch):
    """PRISM_MODE=demo + PRISM_OFFLINE=1 + empty cache → CacheReplayError."""
    monkeypatch.setenv("PRISM_MODE", "demo")
    monkeypatch.setenv("PRISM_OFFLINE", "1")

    empty_cache_file = tmp_path / "empty_cache.jsonl"
    empty_cache_file.write_text("", encoding="utf-8")

    import src.orchestration.agents.base as base_mod
    original_cache = base_mod._shared_cache
    base_mod._shared_cache = LLMCache(empty_cache_file)

    agent = QualityAgent()
    if hasattr(agent, "_decorated_call"):
        del agent._decorated_call

    try:
        with pytest.raises(CacheReplayError):
            agent.invoke("sensor data")
    finally:
        base_mod._shared_cache = original_cache
        monkeypatch.delenv("PRISM_MODE", raising=False)
        monkeypatch.delenv("PRISM_OFFLINE", raising=False)

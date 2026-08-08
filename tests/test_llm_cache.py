"""llm_cache.py 검증 (ADR v2 §6 Unit, A3 + C1 + C3)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.orchestration.llm_cache import (
    BedrockError,
    CacheReplayError,
    LLM_RESPONSE_TIMEOUT_MS,
    LLMCache,
    MOCK_TIMESTAMP,
    cache_key,
    is_demo_mode,
    is_offline_mode,
    normalize_system_prompt,
    normalize_tool_state,
    normalize_user_prompt,
    replay,
)


# ── normalization ───────────────────────────────────────────────


def test_normalize_system_strips_trailing_whitespace():
    raw = "line1   \nline2\t\nline3"
    assert normalize_system_prompt(raw) == "line1\nline2\nline3"


def test_normalize_user_replaces_timestamps():
    raw = "오늘 2026-05-18T15:30:00Z 의 robot 상태"
    norm = normalize_user_prompt(raw)
    assert MOCK_TIMESTAMP in norm
    assert "2026-05-18T15:30:00Z" not in norm


def test_normalize_user_replaces_date_only():
    raw = "data_date=2026-04-30 기준"
    norm = normalize_user_prompt(raw)
    assert MOCK_TIMESTAMP in norm


def test_normalize_tool_state_sort_keys():
    a = {"b": 1, "a": 2}
    b = {"a": 2, "b": 1}
    assert normalize_tool_state(a) == normalize_tool_state(b)


def test_normalize_tool_state_none_handles_empty():
    assert normalize_tool_state(None) == "{}"


# ── cache_key ───────────────────────────────────────────────────


def test_cache_key_stable_across_timestamp_drift():
    """동일 내용 + 다른 timestamp → 동일 key (시연 결정성)."""
    k1 = cache_key("opus-4-7", "sys", "오늘 2026-05-18T10:00:00Z 상태", {"a": 1})
    k2 = cache_key("opus-4-7", "sys", "오늘 2026-05-22T03:00:00Z 상태", {"a": 1})
    assert k1 == k2


def test_cache_key_differs_on_model_change():
    k1 = cache_key("opus-4-7", "sys", "q", None)
    k2 = cache_key("haiku-4-5", "sys", "q", None)
    assert k1 != k2


def test_cache_key_differs_on_content_change():
    k1 = cache_key("opus-4-7", "sys", "q1", None)
    k2 = cache_key("opus-4-7", "sys", "q2", None)
    assert k1 != k2


# ── LLMCache persistence ────────────────────────────────────────


def test_cache_get_miss_returns_none(tmp_path: Path):
    c = LLMCache(tmp_path / "c.jsonl")
    assert c.get("absent") is None
    assert c.misses == 1


def test_cache_put_then_get(tmp_path: Path):
    c = LLMCache(tmp_path / "c.jsonl")
    c.put("k1", {"text": "hello"})
    assert c.get("k1") == {"text": "hello"}
    assert c.hits == 1


def test_cache_persists_to_jsonl(tmp_path: Path):
    p = tmp_path / "c.jsonl"
    c1 = LLMCache(p)
    c1.put("k1", {"x": 1})
    c1.put("k2", {"y": 2})

    c2 = LLMCache(p)
    assert c2.get("k1") == {"x": 1}
    assert c2.get("k2") == {"y": 2}


def test_cache_hit_rate(tmp_path: Path):
    c = LLMCache(tmp_path / "c.jsonl")
    c.put("k1", "v1")
    c.get("k1")  # hit
    c.get("k1")  # hit
    c.get("k2")  # miss
    assert c.hit_rate() == pytest.approx(2 / 3)


# ── replay decorator ────────────────────────────────────────────


def test_replay_dev_mode_calls_live(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PRISM_MODE", raising=False)
    cache = LLMCache(tmp_path / "c.jsonl")
    call_count = {"n": 0}

    @replay(cache)
    def fn(model_id, system_prompt, user_prompt, tool_state=None, **kw):
        call_count["n"] += 1
        return {"text": "live_response"}

    r = fn("opus-4-7", "sys", "q", None)
    assert r["_source"] == "live"
    assert call_count["n"] == 1
    # dev 모드: cache 에 저장 안 함
    assert cache.get(r["key"]) is None


def test_replay_demo_mode_caches(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PRISM_MODE", "demo")
    cache = LLMCache(tmp_path / "c.jsonl")
    call_count = {"n": 0}

    @replay(cache)
    def fn(model_id, system_prompt, user_prompt, tool_state=None, **kw):
        call_count["n"] += 1
        return {"text": "live"}

    r1 = fn("opus-4-7", "sys", "q", None)
    assert r1["_source"] == "live"
    r2 = fn("opus-4-7", "sys", "q", None)
    assert r2["_source"] == "cache_hit"
    assert call_count["n"] == 1  # 두 번째는 cache hit, 라이브 호출 안 함


def test_replay_offline_cache_miss_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PRISM_MODE", "demo")
    monkeypatch.setenv("PRISM_OFFLINE", "1")
    cache = LLMCache(tmp_path / "c.jsonl")

    @replay(cache)
    def fn(model_id, system_prompt, user_prompt, tool_state=None, **kw):
        return {"text": "should_not_reach"}

    with pytest.raises(CacheReplayError):
        fn("opus-4-7", "sys", "q", None)


def test_replay_timeout_raises(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PRISM_MODE", raising=False)
    cache = LLMCache(tmp_path / "c.jsonl")

    @replay(cache)
    def fn(model_id, system_prompt, user_prompt, tool_state=None, **kw):
        import time
        time.sleep((LLM_RESPONSE_TIMEOUT_MS + 50) / 1000.0)
        return {"text": "too_slow"}

    with pytest.raises(TimeoutError):
        fn("opus-4-7", "sys", "q", None)


def test_replay_bedrock_error_wraps_exception(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PRISM_MODE", raising=False)
    cache = LLMCache(tmp_path / "c.jsonl")

    @replay(cache)
    def fn(model_id, system_prompt, user_prompt, tool_state=None, **kw):
        raise ValueError("simulated bedrock 5xx")

    with pytest.raises(BedrockError):
        fn("opus-4-7", "sys", "q", None)


# ── env helpers ────────────────────────────────────────────────


def test_is_demo_mode(monkeypatch):
    monkeypatch.setenv("PRISM_MODE", "demo")
    assert is_demo_mode()
    monkeypatch.setenv("PRISM_MODE", "dev")
    assert not is_demo_mode()
    monkeypatch.delenv("PRISM_MODE", raising=False)
    assert not is_demo_mode()


def test_is_offline_mode(monkeypatch):
    monkeypatch.setenv("PRISM_OFFLINE", "1")
    assert is_offline_mode()
    monkeypatch.setenv("PRISM_OFFLINE", "0")
    assert not is_offline_mode()
    monkeypatch.delenv("PRISM_OFFLINE", raising=False)
    assert not is_offline_mode()


def test_is_offline_mode_accepts_documented_legacy_flag(monkeypatch):
    monkeypatch.delenv("PRISM_OFFLINE", raising=False)
    monkeypatch.setenv("BEDROCK_OFFLINE", "true")
    assert is_offline_mode()


def test_is_offline_mode_prefers_explicit_public_flag(monkeypatch):
    monkeypatch.setenv("BEDROCK_OFFLINE", "true")
    monkeypatch.setenv("PRISM_OFFLINE", "0")
    assert not is_offline_mode()

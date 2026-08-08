"""Application-level LLM record/replay cache (ADR v2 Decision 2, A3 + C1 + C3).

본 모듈의 책임 boundary (C1):
- 본 모듈 = application-level **output** cache (byte-equal replay 보장).
- Bedrock cachePoint (`src/common/bedrock.py:32-37`) = token-prefix **input** cache (비용 절감).
- 두 레이어 독립. PRISM_MODE=demo 시 본 모듈이 라이브 호출 차단.

Auto-cascade trigger (C3):
- LLM_RESPONSE_TIMEOUT_MS = 10000 → TimeoutError.
- BEDROCK_HTTP_ERROR_THRESHOLD = 1 → BedrockError.
- 두 예외는 호출자 (Streamlit 시연 컴포넌트) 가 영상 fallback 으로 전환하는 signal.

Key normalization (ADR Section 4):
- system_prompt: trailing whitespace strip per line.
- user_prompt: <gold_data> 내부 timestamp 를 MOCK_TIMESTAMP 로 치환.
- tool_state: JSON sort_keys=True dump.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

# ── constants (ADR v2 §2 Decision 2 + §5-D offline 모드) ────────

LLM_RESPONSE_TIMEOUT_MS = 10_000
BEDROCK_HTTP_ERROR_THRESHOLD = 1
MOCK_TIMESTAMP = "2026-05-22T03:00:00Z"
_TS_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:[+\-Z][\d:]*)?)?"
)

DEFAULT_CACHE_PATH = "assets/cache_replay.jsonl"


# ── exceptions ──────────────────────────────────────────────────


class CacheReplayError(RuntimeError):
    """offline mode + cache miss → 호출자가 영상 fallback 으로 전환."""


class BedrockError(RuntimeError):
    """라이브 Bedrock 호출 실패 (HTTP error / SDK exception)."""


# ── key normalization ──────────────────────────────────────────


def normalize_system_prompt(prompt: str) -> str:
    """줄별 trailing whitespace strip."""
    return "\n".join(line.rstrip() for line in prompt.splitlines())


def normalize_user_prompt(prompt: str) -> str:
    """<gold_data> 내부 timestamp 를 MOCK_TIMESTAMP 로 치환."""
    return _TS_PATTERN.sub(MOCK_TIMESTAMP, prompt)


def normalize_tool_state(state: dict | None) -> str:
    """sort_keys=True 로 JSON dump."""
    return json.dumps(state or {}, sort_keys=True, ensure_ascii=False)


def cache_key(
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    tool_state: dict | None = None,
) -> str:
    """SHA256 hex digest. ADR §4 Key normalization."""
    parts = [
        model_id.strip(),
        normalize_system_prompt(system_prompt),
        normalize_user_prompt(user_prompt),
        normalize_tool_state(tool_state),
    ]
    blob = "\n---\n".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ── persistence ─────────────────────────────────────────────────


class LLMCache:
    """jsonl-backed deterministic cache."""

    def __init__(self, path: str | Path = DEFAULT_CACHE_PATH) -> None:
        self.path = Path(path)
        self._store: dict[str, Any] = {}
        self.hits = 0
        self.misses = 0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            self._store[entry["key"]] = entry["response"]

    def get(self, key: str) -> Any | None:
        if key in self._store:
            self.hits += 1
            return self._store[key]
        self.misses += 1
        return None

    def put(self, key: str, response: Any) -> None:
        self._store[key] = response
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": key, "response": response}, ensure_ascii=False) + "\n")

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def stats(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": self.hit_rate(),
            "entries": len(self._store),
            "path": str(self.path),
        }


# ── decorator ───────────────────────────────────────────────────


def is_demo_mode() -> bool:
    return os.environ.get("PRISM_MODE", "dev").lower() == "demo"


def is_offline_mode() -> bool:
    """Return the deterministic replay policy with legacy env compatibility."""
    explicit = os.environ.get("PRISM_OFFLINE")
    if explicit is not None:
        return explicit == "1"
    return os.environ.get("BEDROCK_OFFLINE", "false").lower() == "true"


def replay(cache: LLMCache) -> Callable:
    """Bedrock Converse-style 함수에 부착하는 record/replay decorator.

    Decorated function 시그니처:
        fn(model_id: str, system_prompt: str, user_prompt: str,
           tool_state: dict | None = None, **kwargs) -> Any
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(
            model_id: str,
            system_prompt: str,
            user_prompt: str,
            tool_state: dict | None = None,
            **kwargs: Any,
        ) -> dict:
            key = cache_key(model_id, system_prompt, user_prompt, tool_state)
            demo = is_demo_mode()

            if demo:
                cached = cache.get(key)
                if cached is not None:
                    return {"_source": "cache_hit", "key": key, "response": cached}
                if is_offline_mode():
                    raise CacheReplayError(
                        f"offline mode + cache miss: key={key[:16]}... — 영상 fallback 으로 전환 필요"
                    )

            t0 = time.monotonic()
            try:
                response = fn(model_id, system_prompt, user_prompt, tool_state, **kwargs)
            except Exception as exc:
                raise BedrockError(f"live call failed: {exc}") from exc

            elapsed_ms = (time.monotonic() - t0) * 1000.0
            if elapsed_ms > LLM_RESPONSE_TIMEOUT_MS:
                raise TimeoutError(
                    f"elapsed={elapsed_ms:.0f}ms > LLM_RESPONSE_TIMEOUT_MS={LLM_RESPONSE_TIMEOUT_MS}ms"
                )

            if demo:
                cache.put(key, response)

            return {
                "_source": "live",
                "key": key,
                "response": response,
                "elapsed_ms": elapsed_ms,
            }

        return wrapper

    return decorator

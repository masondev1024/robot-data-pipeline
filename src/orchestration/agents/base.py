"""PRISM BaseAgent — abstract class for all 4 domain agents.

Decorated invoke() uses llm_cache.py replay decorator for demo determinism (ADR v2 Decision 2).
Each subclass must implement: system_prompt, tools, output_model.
"""

from __future__ import annotations

import json
import os
import re
import sys
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError

from src.orchestration.llm_cache import LLMCache, replay, DEFAULT_CACHE_PATH

# Shared cache instance (module-level singleton — all agents share one JSONL file)
_shared_cache = LLMCache(os.environ.get("PRISM_CACHE_PATH", DEFAULT_CACHE_PATH))


class AgentOutput(BaseModel):
    """Thin wrapper returned by invoke() — raw dict + typed model."""
    raw: dict
    parsed: BaseModel
    _source: str = "live"


class BaseAgent(ABC):
    """Abstract base for PRISM domain agents.

    Subclasses declare:
        name          — short slug ("quality", "safety", ...)
        model_id      — Bedrock model ID (Haiku for domain agents)
        system_prompt — domain-specific instruction string
        tools         — Bedrock toolConfig tool list (may be [])
        output_model  — Pydantic model to validate LLM JSON output
    """

    # ── abstract properties ───────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def model_id(self) -> str:
        ...

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        ...

    @property
    @abstractmethod
    def tools(self) -> list[dict]:
        ...

    @property
    @abstractmethod
    def output_model(self) -> type[BaseModel]:
        ...

    # ── core LLM call (replay-decorated) ─────────────────────────

    @staticmethod
    def _llm_call(
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        tool_state: dict | None = None,
        **kwargs: Any,
    ) -> str:
        """Raw Bedrock invoke — wrapped by replay decorator at invoke() time.

        Uses invoke_claude from src.common.bedrock (adds cachePoint ephemeral).
        """
        from src.common.bedrock import invoke_claude

        return invoke_claude(
            user_prompt,
            system=system_prompt,
            model_id=model_id,
            cache_system=True,
            max_tokens=kwargs.get("max_tokens", 1024),
        )

    # Build the replay-decorated version lazily (once per instance)
    def _get_decorated_call(self):
        if not hasattr(self, "_decorated_call"):
            self._decorated_call = replay(_shared_cache)(self.__class__._llm_call)
        return self._decorated_call

    # ── public invoke ─────────────────────────────────────────────

    def invoke(self, user_prompt: str, context: dict | None = None) -> AgentOutput:
        """Call Bedrock (or replay from cache) and validate output.

        Args:
            user_prompt: task description / sensor reading JSON string.
            context:     optional tool_state dict passed to cache key.

        Returns:
            AgentOutput with .parsed typed Pydantic model.

        Raises:
            ValidationError: if LLM JSON does not satisfy output_model.
            BedrockError:    if live call fails.
            CacheReplayError: if offline + cache miss.
        """
        decorated = self._get_decorated_call()

        result = decorated(
            self.model_id,
            self.system_prompt,
            user_prompt,
            context or None,
        )

        raw_text: str = result["response"]

        stripped = raw_text.strip()
        stripped = re.sub(r"^```(?:json)?\s*\n?", "", stripped)
        stripped = re.sub(r"\n?```\s*$", "", stripped)
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if match:
            stripped = match.group(0)

        try:
            raw_dict = json.loads(stripped)
        except json.JSONDecodeError as exc:
            print(
                f"\n[{self.name}] FAILED JSON parse. FULL raw_text follows:\n"
                f"{'─' * 60}\n{raw_text}\n{'─' * 60}\n",
                file=sys.stderr, flush=True,
            )
            raise ValueError(
                f"[{self.name}] LLM returned non-JSON (len={len(raw_text)}): "
                f"{raw_text[:500]!r}"
            ) from exc

        # Pydantic validation — raises ValidationError on schema mismatch
        parsed = self.output_model.model_validate(raw_dict)

        return AgentOutput(raw=raw_dict, parsed=parsed, _source=result.get("_source", "live"))

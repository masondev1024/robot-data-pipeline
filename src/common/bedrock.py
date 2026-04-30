"""Bedrock Claude invocation helper — Prompt Caching + usage 로깅 (ADR-012)."""
import json
import os
from typing import Optional, Union

from src.common.aws import get_client

DEFAULT_MODEL_ID = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"


def invoke_claude(
    prompt: str,
    *,
    system: Optional[Union[str, list]] = None,
    max_tokens: int = 512,
    model_id: Optional[str] = None,
    cache_system: bool = True,
) -> str:
    """Bedrock Claude invoke + system prompt caching.

    system 이 string 으로 들어오면 자동으로 ephemeral cache block 으로 wrap.
    응답 usage(input/output/cache_read/cache_creation) 는 JSON 라인으로 stdout 출력 →
    CloudWatch Logs 가 자동 수집 → metric filter 로 cache hit rate 추적.
    """
    body: dict = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    if system:
        if cache_system and isinstance(system, str):
            body["system"] = [{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }]
        else:
            body["system"] = system

    resolved_model = model_id or os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
    response = get_client("bedrock-runtime").invoke_model(
        modelId=resolved_model,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )

    parsed = json.loads(response["body"].read())
    usage = parsed.get("usage", {})
    print(json.dumps({
        "event": "bedrock_invoke",
        "model": resolved_model,
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
    }))

    return parsed["content"][0]["text"]

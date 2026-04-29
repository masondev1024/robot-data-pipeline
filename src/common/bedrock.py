"""Bedrock Claude invocation helper."""
import json
import os
from typing import Optional

from src.common.aws import get_client

DEFAULT_MODEL_ID = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"


def invoke_claude(
    prompt: str,
    *,
    system: Optional[str] = None,
    max_tokens: int = 512,
    model_id: Optional[str] = None,
) -> str:
    body: dict = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    response = get_client("bedrock-runtime").invoke_model(
        modelId=model_id or os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    return json.loads(response["body"].read())["content"][0]["text"]

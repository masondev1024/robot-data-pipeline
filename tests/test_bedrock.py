"""Offline unit tests for the shared Bedrock invoke_model helper."""

import json
from unittest.mock import MagicMock

from src.common import bedrock


def _response(text: str = "정비 리포트") -> dict:
    body = MagicMock()
    body.read.return_value = json.dumps(
        {
            "content": [{"text": text}],
            "usage": {
                "input_tokens": 20,
                "output_tokens": 5,
                "cache_read_input_tokens": 10,
            },
        }
    ).encode("utf-8")
    return {"body": body}


def test_invoke_claude_builds_cached_anthropic_request(monkeypatch, capsys):
    client = MagicMock()
    client.invoke_model.return_value = _response()
    monkeypatch.setattr(bedrock, "get_client", MagicMock(return_value=client))

    result = bedrock.invoke_claude(
        "로봇 상태를 요약해줘",
        system="정비 분석가",
        model_id="test-model",
    )

    assert result == "정비 리포트"
    kwargs = client.invoke_model.call_args.kwargs
    assert kwargs["modelId"] == "test-model"
    assert kwargs["contentType"] == "application/json"
    assert kwargs["accept"] == "application/json"
    body = json.loads(kwargs["body"])
    assert body["anthropic_version"] == "bedrock-2023-05-31"
    assert body["max_tokens"] == 512
    assert body["messages"] == [
        {"role": "user", "content": "로봇 상태를 요약해줘"}
    ]
    assert body["system"] == [
        {
            "type": "text",
            "text": "정비 분석가",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    usage_log = json.loads(capsys.readouterr().out)
    assert usage_log["event"] == "bedrock_invoke"
    assert usage_log["cache_read_input_tokens"] == 10


def test_invoke_claude_can_disable_system_prompt_cache(monkeypatch):
    client = MagicMock()
    client.invoke_model.return_value = _response()
    monkeypatch.setattr(bedrock, "get_client", MagicMock(return_value=client))

    bedrock.invoke_claude(
        "daily report",
        system="system prompt",
        cache_system=False,
    )

    body = json.loads(client.invoke_model.call_args.kwargs["body"])
    assert body["system"] == "system prompt"

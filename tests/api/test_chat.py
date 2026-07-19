"""Contract tests for POST /api/chat and the Bedrock Converse tool loop."""

from copy import deepcopy

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_AUTH_HEADERS
import src.api.main as api


MODEL_ID = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"


def _client() -> TestClient:
    return TestClient(api.app, headers=TEST_AUTH_HEADERS)


def _final_response(text: str) -> dict:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": text}],
            },
        },
        "usage": {"inputTokens": 10, "outputTokens": 4},
        "stopReason": "end_turn",
    }


@pytest.fixture(autouse=True)
def reset_chat_state(monkeypatch):
    api.limiter._storage.storage.clear()
    monkeypatch.setenv("BEDROCK_MODEL_ID", MODEL_ID)
    monkeypatch.setattr(
        api,
        "_gold_cache",
        "robot_id,avg_motor_temp,max_motor_temp,battery_drain,active_hours\n"
        "ROBOT-00001,92.5,98.0,30,8",
    )
    monkeypatch.setattr(api, "_cache_updated_at", "2026-04-27T10:00:00+00:00")
    monkeypatch.setattr(api, "_data_date", "2026-04-26")


@pytest.fixture
def bedrock(monkeypatch):
    client = MagicMock()
    client.converse.return_value = _final_response(
        "점검 시급: [ROBOT-00123], [ROBOT-00456]"
    )
    monkeypatch.setattr(api, "_bedrock_runtime", client)
    return client


def test_chat_returns_answer_metadata_and_robot_links(bedrock):
    response = _client().post(
        "/api/chat", json={"question": "최고 온도 로봇은?"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "점검 시급: [ROBOT-00123], [ROBOT-00456]",
        "cached_at": "2026-04-27T10:00:00+00:00",
        "data_date": "2026-04-26",
        "links": [
            {"label": "ROBOT-00123 차트", "url": "/?robot_id=ROBOT-00123"},
            {"label": "ROBOT-00456 차트", "url": "/?robot_id=ROBOT-00456"},
        ],
    }


def test_chat_sends_converse_contract_with_cache_point_and_tools(bedrock):
    response = _client().post(
        "/api/chat", json={"question": "문제가 있는 로봇은?"}
    )

    assert response.status_code == 200
    kwargs = bedrock.converse.call_args.kwargs
    assert kwargs["modelId"] == MODEL_ID
    assert kwargs["inferenceConfig"] == {"maxTokens": 512}
    assert kwargs["system"][0] == {"text": api.ROBOT_ANALYST_SYSTEM_PROMPT}
    assert kwargs["system"][1] == {"cachePoint": {"type": "default"}}
    assert kwargs["toolConfig"] == api.CHAT_TOOL_CONFIG
    assert kwargs["messages"][0]["role"] == "user"
    prompt = kwargs["messages"][0]["content"][0]["text"]
    assert "<gold_data>" in prompt
    assert "문제가 있는 로봇은?" in prompt


def test_converse_executes_tool_and_returns_second_turn(monkeypatch):
    client = MagicMock()
    responses = iter([
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "tool-1",
                                "name": "predict_robot_failure",
                                "input": {"robot_id": "ROBOT-00001"},
                            },
                        },
                    ],
                },
            },
            "stopReason": "tool_use",
        },
        _final_response("ROBOT-00001은 예방 정비가 필요합니다."),
    ])
    messages_at_call = []

    def converse(**kwargs):
        messages_at_call.append(deepcopy(kwargs["messages"]))
        return next(responses)

    client.converse.side_effect = converse
    tool = MagicMock(return_value={"top_failure_type": "HDF"})
    monkeypatch.setattr(api, "_bedrock_runtime", client)
    monkeypatch.setattr(
        api,
        "_TOOL_IMPLEMENTATIONS",
        {"predict_robot_failure": tool},
    )

    result = api._converse_with_tools("ROBOT-00001을 예측해줘")

    assert result == "ROBOT-00001은 예방 정비가 필요합니다."
    tool.assert_called_once_with(robot_id="ROBOT-00001")
    second_messages = messages_at_call[1]
    assert second_messages[-1] == {
        "role": "user",
        "content": [
            {
                "toolResult": {
                    "toolUseId": "tool-1",
                    "content": [{"json": {"top_failure_type": "HDF"}}],
                },
            },
        ],
    }


def test_chat_returns_503_when_gold_cache_is_empty(monkeypatch):
    monkeypatch.setattr(api, "_gold_cache", "")

    response = _client().post("/api/chat", json={"question": "test"})

    assert response.status_code == 503
    assert response.json()["detail"] == "캐시가 아직 준비되지 않았습니다."


def test_chat_translates_bedrock_failure_to_502(bedrock):
    bedrock.converse.side_effect = RuntimeError("service unavailable")

    response = _client().post("/api/chat", json={"question": "test"})

    assert response.status_code == 502
    assert response.json()["detail"] == "Bedrock 호출 실패: service unavailable"


def test_chat_rate_limit_is_ten_requests_per_minute(bedrock):
    client = _client()
    for index in range(10):
        assert client.post("/api/chat", json={"question": f"q{index}"}).status_code == 200

    assert client.post("/api/chat", json={"question": "q10"}).status_code == 429

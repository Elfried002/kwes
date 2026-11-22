"""Client DeepSeek : contrat LLMClient, conversion des messages, erreurs typées.

Aucun appel réseau réel : le transport httpx est simulé (`MockTransport`).
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.agent.deepseek_text import DeepSeekTextClient
from app.agent.llm import LLMError, LLMTimeout
from app.core.config import Settings


def _settings(**overrides) -> Settings:
    values = dict(
        app_env="dev",
        deepseek_api_key="sk-test-not-a-real-key",
        deepseek_model="deepseek-chat",
        deepseek_base_url="https://api.deepseek.example",
        deepseek_timeout_seconds=5.0,
        deepseek_temperature=0.1,
    )
    values.update(overrides)
    return Settings(**values)


def _client(handler, **overrides) -> tuple[DeepSeekTextClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(_record)
    return DeepSeekTextClient(_settings(**overrides), transport=transport), seen


@pytest.mark.asyncio
async def test_chat_returns_text_usage_and_model() -> None:
    payload = {
        "id": "chat-1",
        "model": "deepseek-chat",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "Réponse citée [1]."}}
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 42, "total_tokens": 162},
    }
    client, seen = _client(lambda request: httpx.Response(200, json=payload))

    result = await client.chat(
        [{"role": "system", "content": "Tu cites."}, {"role": "user", "content": "Question ?"}],
        purpose="research",
        max_tokens=900,
    )

    assert result.content == "Réponse citée [1]."
    assert result.model == "deepseek-chat"
    assert result.tool_calls == []
    assert result.usage["input_tokens"] == 120
    assert result.usage["output_tokens"] == 42
    assert result.mock is False

    request = seen[0]
    assert str(request.url) == "https://api.deepseek.example/chat/completions"
    assert request.headers["authorization"].startswith("Bearer ")
    body = json.loads(request.content)
    assert body["model"] == "deepseek-chat"
    assert body["temperature"] == 0.1
    assert body["max_tokens"] == 900
    assert body["stream"] is False
    assert body["messages"][0] == {"role": "system", "content": "Tu cites."}


@pytest.mark.asyncio
async def test_tool_calls_and_tool_messages_are_converted_to_openai_shape() -> None:
    payload = {
        "model": "deepseek-chat",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_9",
                            "type": "function",
                            "function": {"name": "remember", "arguments": "{\"key\": \"ville\", \"value\": \"Abidjan\"}"},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    client, seen = _client(lambda request: httpx.Response(200, json=payload))

    result = await client.chat(
        [
            {"role": "user", "content": "Retiens ma ville"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_1", "name": "remember", "arguments": {"key": "ville"}}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "{\"status\": \"executed\"}"},
        ],
        tools=[
            {
                "type": "function",
                "function": {"name": "remember", "description": "mémorise", "parameters": {"type": "object"}},
            }
        ],
    )

    assert [call["name"] for call in result.tool_calls] == ["remember"]
    assert result.tool_calls[0]["arguments"] == {"key": "ville", "value": "Abidjan"}
    assert result.tool_calls[0]["id"] == "call_9"

    body = json.loads(seen[0].content)
    # L'historique assistant est rejoué au format OpenAI strict (arguments en texte).
    assistant = [m for m in body["messages"] if m["role"] == "assistant"][0]
    assert assistant["tool_calls"][0]["function"]["name"] == "remember"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"key": "ville"}
    tool_message = [m for m in body["messages"] if m["role"] == "tool"][0]
    assert tool_message["tool_call_id"] == "call_1"
    assert body["tools"][0]["function"]["name"] == "remember"
    assert body["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_json_mode_sets_response_format() -> None:
    payload = {
        "model": "deepseek-chat",
        "choices": [{"message": {"content": "{\"ok\": true}"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    client, seen = _client(lambda request: httpx.Response(200, json=payload))

    result = await client.chat(
        [{"role": "user", "content": "Réponds en json."}], json_mode=True, max_tokens=50
    )

    assert result.json() == {"ok": True}
    assert json.loads(seen[0].content)["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "PROVIDER_AUTH", False),
        (403, "PROVIDER_AUTH", False),
        (402, "PROVIDER_BALANCE", False),
        (429, "RATE_LIMITED", True),
        (503, "PROVIDER_UNAVAILABLE", True),
    ],
)
async def test_http_errors_are_typed(status: int, code: str, retryable: bool) -> None:
    client, _ = _client(
        lambda request: httpx.Response(status, json={"error": {"message": "refusé"}})
    )
    with pytest.raises(LLMError) as caught:
        await client.chat([{"role": "user", "content": "Bonjour"}])
    assert caught.value.code == code
    assert caught.value.retryable is retryable
    # Le message reste lisible, sans jamais recopier la clé.
    assert "sk-test" not in str(caught.value)


@pytest.mark.asyncio
async def test_timeout_becomes_llm_timeout() -> None:
    def _raise(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("trop lent", request=request)

    client, _ = _client(_raise)
    with pytest.raises(LLMTimeout):
        await client.chat([{"role": "user", "content": "Bonjour"}], timeout=0.5)


@pytest.mark.asyncio
async def test_missing_key_fails_without_network_call() -> None:
    client, seen = _client(lambda request: httpx.Response(200, json={}), deepseek_api_key="")
    with pytest.raises(LLMError) as caught:
        await client.chat([{"role": "user", "content": "Bonjour"}])
    assert caught.value.code == "PROVIDER_NOT_CONFIGURED"
    assert seen == []


@pytest.mark.asyncio
async def test_reasoning_only_response_is_reported_as_truncated() -> None:
    """`deepseek-flash` raisonne : budget épuisé = contenu vide, pas une panne."""
    payload = {
        "model": "deepseek-flash",
        "choices": [
            {
                "message": {"role": "assistant", "content": "", "reasoning_content": "je réfléchis…"},
                "finish_reason": "length",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 120, "total_tokens": 130},
    }
    client, _ = _client(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(LLMError) as caught:
        await client.chat([{"role": "user", "content": "Bonjour"}], max_tokens=120)
    assert caught.value.code == "OUTPUT_TRUNCATED"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_empty_response_is_reported_not_returned() -> None:
    payload = {"model": "deepseek-chat", "choices": [{"message": {"content": ""}}], "usage": {}}
    client, _ = _client(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(LLMError) as caught:
        await client.chat([{"role": "user", "content": "Bonjour"}])
    assert caught.value.code == "INVALID_OUTPUT"

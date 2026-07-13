import json

import httpx
import pytest

from backend.app.config import get_settings
from backend.app.services import llm as llm_module
from backend.app.services.llm import LLMClient, LLMProviderError


def configure_real_client(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "unit-test-placeholder")
    monkeypatch.setenv("LLM_BASE_URL", "https://provider.invalid/v1")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "1200")
    get_settings.cache_clear()


def install_transport(monkeypatch, handler):
    real_client = httpx.Client

    def client_factory(*, timeout, follow_redirects):
        return real_client(
            transport=httpx.MockTransport(handler),
            timeout=timeout,
            follow_redirects=follow_redirects,
        )

    monkeypatch.setattr(llm_module.httpx, "Client", client_factory)


def test_llm_chat_sends_tools_and_parses_tool_calls(monkeypatch):
    configure_real_client(monkeypatch)
    captured = {}

    def handler(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "search_text", "arguments": '{"query":"RAG"}'},
                                }
                            ],
                        }
                    }
                ]
            },
        )

    install_transport(monkeypatch, handler)
    tools = [{"type": "function", "function": {"name": "search_text", "parameters": {"type": "object"}}}]
    message = LLMClient().chat([{"role": "user", "content": "search"}], tools=tools)

    assert captured["payload"]["tools"] == tools
    assert captured["payload"]["tool_choice"] == "auto"
    assert captured["payload"]["max_tokens"] == 1_200
    assert message["tool_calls"][0]["function"]["name"] == "search_text"
    get_settings.cache_clear()


def test_llm_provider_error_is_sanitized(monkeypatch):
    configure_real_client(monkeypatch)
    monkeypatch.setattr(llm_module.time, "sleep", lambda _: None)
    install_transport(monkeypatch, lambda request: httpx.Response(429, text="secret provider response"))

    with pytest.raises(LLMProviderError) as exc_info:
        LLMClient().chat([{"role": "user", "content": "search"}])

    assert str(exc_info.value) == "provider_http_429"
    assert "secret" not in str(exc_info.value)
    get_settings.cache_clear()


def test_llm_retries_transient_connection_error(monkeypatch):
    configure_real_client(monkeypatch)
    monkeypatch.setattr(llm_module.time, "sleep", lambda _: None)
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("temporary", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "OK"}}]})

    install_transport(monkeypatch, handler)
    message = LLMClient().chat([{"role": "user", "content": "test"}])

    assert attempts == 2
    assert message["content"] == "OK"
    get_settings.cache_clear()


def test_gpt5_chat_uses_compatible_payload_without_spoofed_sdk_headers(monkeypatch):
    configure_real_client(monkeypatch)
    monkeypatch.setenv("LLM_CHAT_MODEL", "gpt-5.5-medium")
    get_settings.cache_clear()
    captured = {}

    def handler(request):
        captured["payload"] = json.loads(request.content)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "OK"}}]})

    install_transport(monkeypatch, handler)
    message = LLMClient().chat([{"role": "user", "content": "test"}])

    assert message["content"] == "OK"
    assert captured["payload"]["max_completion_tokens"] == 1_200
    assert "max_tokens" not in captured["payload"]
    assert "temperature" not in captured["payload"]
    assert captured["headers"]["accept"] == "application/json"
    assert captured["headers"]["authorization"] == "Bearer unit-test-placeholder"
    get_settings.cache_clear()

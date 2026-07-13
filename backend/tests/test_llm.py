import json
from urllib.error import HTTPError

import pytest

from backend.app.config import get_settings
from backend.app.services import llm as llm_module
from backend.app.services.llm import LLMClient, LLMProviderError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def configure_real_client(monkeypatch):
    monkeypatch.setenv("ENABLE_MOCK_LLM", "false")
    monkeypatch.setenv("LLM_API_KEY", "unit-test-placeholder")
    monkeypatch.setenv("LLM_BASE_URL", "https://provider.invalid/v1")
    get_settings.cache_clear()


def test_llm_chat_sends_tools_and_parses_tool_calls(monkeypatch):
    configure_real_client(monkeypatch)
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
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
            }
        )

    monkeypatch.setattr(llm_module, "_open_request", fake_urlopen)
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

    def failed_urlopen(request, timeout):
        raise HTTPError(request.full_url, 429, "secret provider response", {}, None)

    monkeypatch.setattr(llm_module, "_open_request", failed_urlopen)
    with pytest.raises(LLMProviderError) as exc_info:
        LLMClient().chat([{"role": "user", "content": "search"}])

    assert str(exc_info.value) == "provider_http_429"
    assert "secret" not in str(exc_info.value)
    get_settings.cache_clear()


def test_llm_retries_transient_connection_error(monkeypatch):
    configure_real_client(monkeypatch)
    monkeypatch.setattr(llm_module.time, "sleep", lambda _: None)
    attempts = 0

    def flaky_urlopen(request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            from urllib.error import URLError

            raise URLError("temporary")
        return FakeResponse({"choices": [{"message": {"role": "assistant", "content": "OK"}}]})

    monkeypatch.setattr(llm_module, "_open_request", flaky_urlopen)
    message = LLMClient().chat([{"role": "user", "content": "test"}])

    assert attempts == 2
    assert message["content"] == "OK"
    get_settings.cache_clear()


def test_gpt5_chat_uses_compatible_payload_and_sdk_headers(monkeypatch):
    configure_real_client(monkeypatch)
    monkeypatch.setenv("LLM_CHAT_MODEL", "gpt-5.5-medium")
    get_settings.cache_clear()
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["headers"] = dict(request.header_items())
        return FakeResponse({"choices": [{"message": {"role": "assistant", "content": "OK"}}]})

    monkeypatch.setattr(llm_module, "_open_request", fake_urlopen)
    message = LLMClient().chat([{"role": "user", "content": "test"}])

    assert message["content"] == "OK"
    assert captured["payload"]["max_completion_tokens"] == 1_200
    assert "max_tokens" not in captured["payload"]
    assert "temperature" not in captured["payload"]
    assert captured["headers"]["User-agent"].startswith("OpenAI/Python")
    assert captured["headers"]["Accept"] == "application/json"
    get_settings.cache_clear()


def test_llm_redirect_handler_never_forwards_request_headers():
    handler = llm_module._NoRedirectHandler()
    original = llm_module.Request(
        "https://provider.invalid/v1/chat/completions",
        headers={"Authorization": "Bearer unit-test-placeholder"},
    )

    redirected = handler.redirect_request(
        original,
        None,
        302,
        "Found",
        {"Location": "https://redirect-target.invalid/collect"},
        "https://redirect-target.invalid/collect",
    )

    assert redirected is None

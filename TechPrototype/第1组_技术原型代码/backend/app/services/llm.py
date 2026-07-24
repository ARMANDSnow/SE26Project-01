from __future__ import annotations

import json
import time
from typing import Any, Iterator

import httpx

from ..config import get_settings


class LLMConfigurationError(RuntimeError):
    pass


class LLMServiceError(RuntimeError):
    pass


class LLMProviderError(LLMServiceError):
    """Sanitized provider failure that never includes response bodies or credentials."""


def _is_gpt5_family(model: str) -> bool:
    normalized = model.strip().lower().removeprefix("openai/")
    return normalized.startswith("gpt-5")


def _extract_text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    chunks: list[str] = []
    for part in value:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            chunks.append(text)
            continue
        if isinstance(text, dict) and isinstance(text.get("value"), str):
            chunks.append(text["value"])
    return "".join(chunks)


def _extract_choice_text(data: Any, *, streaming: bool) -> str:
    try:
        choice = data["choices"][0]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(choice, dict):
        return ""
    container = choice.get("delta") if streaming else choice.get("message")
    if not isinstance(container, dict):
        return ""
    return _extract_text_content(container.get("content"))


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _require_configured(self) -> None:
        if not self.settings.llm_available:
            raise LLMConfigurationError("LLM_API_KEY is not configured")

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.settings.llm_api_key}",
        }

    def _payload(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        json_mode: bool = False,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.llm_chat_model,
            "messages": messages,
            "stream": stream,
        }
        if _is_gpt5_family(self.settings.llm_chat_model):
            payload["max_completion_tokens"] = self.settings.llm_max_output_tokens
        else:
            payload["temperature"] = 0.2
            payload["max_tokens"] = self.settings.llm_max_output_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        *,
        timeout_seconds: float = 120,
        json_mode: bool = False,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        self._require_configured()
        payload = self._payload(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            json_mode=json_mode,
        )
        url = f"{self.settings.llm_base_url}/chat/completions"
        attempts = max(1, max_attempts)
        for attempt in range(attempts):
            try:
                with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
                    response = client.post(url, headers=self._headers(), json=payload)
                if response.status_code in {408, 409, 429} or response.status_code >= 500:
                    if attempt < attempts - 1:
                        time.sleep(2**attempt)
                        continue
                response.raise_for_status()
                data = response.json()
                message = data["choices"][0]["message"]
                if not isinstance(message, dict):
                    raise TypeError("invalid message")
                return message
            except httpx.HTTPStatusError as exc:
                raise LLMProviderError(f"provider_http_{exc.response.status_code}") from exc
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < attempts - 1:
                    time.sleep(2**attempt)
                    continue
                raise LLMProviderError("provider_unreachable") from exc
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise LLMProviderError("provider_invalid_response") from exc
        raise LLMProviderError("provider_unreachable")

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
        *,
        timeout_seconds: float = 120,
        max_attempts: int = 3,
    ) -> str:
        message = self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("provider_empty_content")
        return content

    def stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        self._require_configured()
        if not self.settings.llm_streaming:
            message = self.chat(messages, timeout_seconds=90, max_attempts=1)
            content = _extract_text_content(message.get("content"))
            if not content.strip():
                raise LLMProviderError("provider_empty_content")
            yield content
            return
        payload = self._payload(messages, stream=True)
        url = f"{self.settings.llm_base_url}/chat/completions"
        yielded_text = False
        non_sse_lines: list[str] = []
        try:
            with httpx.Client(timeout=90, follow_redirects=False) as client:
                with client.stream("POST", url, headers=self._headers(), json=payload) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            if line.strip():
                                non_sse_lines.append(line)
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        delta = _extract_choice_text(data, streaming=True)
                        if delta:
                            yielded_text = True
                            yield delta
                    if not yielded_text and non_sse_lines:
                        try:
                            data = json.loads("\n".join(non_sse_lines))
                        except json.JSONDecodeError:
                            data = None
                        content = _extract_choice_text(data, streaming=False)
                        if content:
                            yielded_text = True
                            yield content
                    if not yielded_text:
                        raise LLMProviderError("provider_empty_content")
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(f"provider_http_{exc.response.status_code}") from exc
        except (httpx.TimeoutException, httpx.NetworkError, OSError) as exc:
            raise LLMProviderError("provider_unreachable") from exc

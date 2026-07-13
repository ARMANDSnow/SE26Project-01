from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..config import get_settings
from .text_utils import deterministic_embedding


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def embed(self, text: str) -> list[float]:
        if self.settings.should_use_mock_llm:
            return deterministic_embedding(text)
        payload = {
            "model": self.settings.llm_embed_model,
            "input": text,
        }
        request = Request(
            f"{self.settings.llm_base_url}/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
        )
        with _open_request(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["data"][0]["embedding"]

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if self.settings.should_use_mock_llm:
            return ""
        message = self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
        return str(message.get("content") or "")

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        if self.settings.should_use_mock_llm:
            return {"role": "assistant", "content": ""}
        payload = {
            "model": self.settings.llm_chat_model,
            "messages": messages,
        }
        if _is_gpt5_family(self.settings.llm_chat_model):
            payload["max_completion_tokens"] = 1_200
        else:
            payload["temperature"] = 0.2
            payload["max_tokens"] = 1_200
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        request = Request(
            f"{self.settings.llm_base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
        )
        data: dict[str, Any] | None = None
        for attempt in range(3):
            try:
                with _open_request(request, timeout=120) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                is_transient = exc.code in {408, 409, 429} or exc.code >= 500
                if is_transient and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise LLMProviderError(f"provider_http_{exc.code}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise LLMProviderError("provider_unreachable") from exc
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise LLMProviderError("provider_invalid_response") from exc
        try:
            message = data["choices"][0]["message"] if data is not None else None
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LLMProviderError("provider_invalid_response") from exc
        if not isinstance(message, dict):
            raise LLMProviderError("provider_invalid_message")
        return message

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "User-Agent": "OpenAI/Python 2.38.0",
            "X-Stainless-Lang": "python",
            "X-Stainless-Package-Version": "2.38.0",
            "X-Stainless-Runtime": "CPython",
        }


class LLMProviderError(RuntimeError):
    """Sanitized provider failure that never includes response bodies or credentials."""


def _is_gpt5_family(model: str) -> bool:
    normalized = model.strip().lower().removeprefix("openai/")
    return normalized.startswith("gpt-5")


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = build_opener(_NoRedirectHandler())


def _open_request(request: Request, timeout: int):
    """Open an API request without forwarding Authorization across redirects."""
    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)

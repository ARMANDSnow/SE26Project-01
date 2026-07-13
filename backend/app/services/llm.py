from __future__ import annotations

import json
import httpx
from urllib.request import Request, urlopen
from urllib.error import URLError

from ..config import get_settings


class LLMConfigurationError(RuntimeError):
    pass


class LLMServiceError(RuntimeError):
    pass


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        if not self.settings.llm_available:
            raise LLMConfigurationError("LLM_API_KEY 或 apikey.txt 未配置")
        payload = {
            "model": self.settings.llm_chat_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": self.settings.llm_max_output_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        request = Request(
            f"{self.settings.llm_base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.llm_api_key}",
            },
        )
        try:
            with urlopen(request, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError, URLError, OSError) as exc:
            raise LLMServiceError(f"LLM 请求失败：{exc}") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMServiceError("LLM 返回了空内容")
        return content

    def stream(self, messages: list[dict[str, str]]):
        if not self.settings.llm_available:
            raise LLMConfigurationError("LLM_API_KEY 或 apikey.txt 未配置")
        payload = {
            "model": self.settings.llm_chat_model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": self.settings.llm_max_output_tokens,
            "stream": True,
        }
        try:
            with httpx.Client(timeout=90) as client:
                with client.stream(
                    "POST",
                    f"{self.settings.llm_base_url}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.settings.llm_api_key}",
                    },
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            data = json.loads(raw)
                            delta = data["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                            continue
                        if isinstance(delta, str) and delta:
                            yield delta
        except (httpx.HTTPError, OSError) as exc:
            raise LLMServiceError(f"LLM 流式请求失败：{exc}") from exc

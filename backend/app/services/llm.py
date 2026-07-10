from __future__ import annotations

import json
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

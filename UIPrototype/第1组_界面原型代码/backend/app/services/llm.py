from __future__ import annotations

import json
from urllib.request import Request, urlopen

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
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.llm_api_key}",
            },
        )
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["data"][0]["embedding"]

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if self.settings.should_use_mock_llm:
            return ""
        payload = {
            "model": self.settings.llm_chat_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        request = Request(
            f"{self.settings.llm_base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.llm_api_key}",
            },
        )
        with urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

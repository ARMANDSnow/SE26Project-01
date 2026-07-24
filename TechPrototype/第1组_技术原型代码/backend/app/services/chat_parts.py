from __future__ import annotations

import json
from typing import Any


ChatPart = dict[str, Any]


def text_parts(content: str) -> list[ChatPart]:
    return [{"type": "text", "text": content}]


def research_run_parts(label: str, run_id: str) -> list[ChatPart]:
    return [
        {"type": "text", "text": label},
        {"type": "data", "name": "research-run", "data": {"run_id": run_id}},
    ]


def encode_parts(parts: list[ChatPart]) -> str:
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def decode_parts(raw: str | None, fallback_text: str) -> list[ChatPart]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        return text_parts(fallback_text)
    if not isinstance(value, list):
        return text_parts(fallback_text)

    decoded: list[ChatPart] = []
    for part in value:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            decoded.append({"type": "text", "text": part["text"]})
            continue
        data = part.get("data")
        if (
            part.get("type") == "data"
            and part.get("name") == "research-run"
            and isinstance(data, dict)
            and isinstance(data.get("run_id"), str)
        ):
            decoded.append(
                {
                    "type": "data",
                    "name": "research-run",
                    "data": {"run_id": data["run_id"]},
                }
            )
    return decoded or text_parts(fallback_text)

from __future__ import annotations

import re
from typing import Any

from .text_utils import tokenize


DEFAULT_CHUNK_CHARS = 1_200
DEFAULT_CHUNK_OVERLAP = 160


def normalize_fulltext(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r", "\n").splitlines()]
    return "\n".join(line for line in lines if line).strip()


def chunk_markdown(
    markdown: str,
    *,
    max_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    """Create traceable chunks from the current persisted PaperDocument only."""
    text = normalize_fulltext(markdown)
    if not text:
        return []
    heading_positions = [
        (match.start(), match.group(1).strip())
        for match in re.finditer(r"(?m)^#{1,6}\s+(.+)$", text)
    ]
    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            minimum = start + max(200, (end - start) // 2)
            candidates = [text.rfind(mark, minimum, end) for mark in ("\n", "。", ".", " ")]
            boundary = max(candidates)
            if boundary > minimum:
                end = boundary + 1
        raw = text[start:end]
        leading = len(raw) - len(raw.lstrip())
        content = raw.strip()
        if content:
            char_start = start + leading
            char_end = char_start + len(content)
            heading = "Document"
            for position, title in heading_positions:
                if position > char_start:
                    break
                heading = title
            chunks.append(
                {
                    "chunk_index": len(chunks),
                    "heading": heading,
                    "content": content,
                    "char_start": char_start,
                    "char_end": char_end,
                    "token_count": len(tokenize(content)),
                }
            )
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks

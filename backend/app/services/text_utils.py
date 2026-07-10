from __future__ import annotations

import hashlib
import re


TOKEN_RE = re.compile(r"[A-Za-z0-9_+\-.]+|[\u4e00-\u9fff]")


def normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def title_hash(title: str) -> str:
    return hashlib.sha256(normalize_text(title).encode("utf-8")).hexdigest()


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(normalize_text(text))


def keyword_score(query: str, text: str) -> float:
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return 0.0
    text_norm = normalize_text(text)
    matches = sum(1 for token in query_tokens if token in text_norm)
    return matches / max(len(query_tokens), 1)

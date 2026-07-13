from __future__ import annotations

from collections import Counter
import hashlib
import math
import re
from typing import Iterable


TOKEN_RE = re.compile(r"[A-Za-z0-9_+\-.]+|[\u4e00-\u9fff]")


def normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def title_hash(title: str) -> str:
    return hashlib.sha256(normalize_text(title).encode("utf-8")).hexdigest()


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(normalize_text(text))


def deterministic_embedding(text: str, dimensions: int = 96) -> list[float]:
    vector = [0.0] * dimensions
    tokens = tokenize(text)
    if not tokens:
        tokens = ["empty"]
    counts = Counter(tokens)
    for token, count in counts.items():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [round(item / norm, 6) for item in vector]


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    left_values = list(left)
    right_values = list(right)
    size = min(len(left_values), len(right_values))
    if size == 0:
        return 0.0
    dot = sum(left_values[index] * right_values[index] for index in range(size))
    left_norm = math.sqrt(sum(value * value for value in left_values[:size]))
    right_norm = math.sqrt(sum(value * value for value in right_values[:size]))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def keyword_score(query: str, text: str) -> float:
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return 0.0
    text_norm = normalize_text(text)
    matches = sum(1 for token in query_tokens if token in text_norm)
    return matches / max(len(query_tokens), 1)

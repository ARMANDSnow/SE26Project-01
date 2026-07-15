from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..repositories.uploads import accessible_paper_condition
from .search import extract_snippet, search_chunks


MAX_SEARCH_LIMIT = 12
MAX_OPEN_CHARS = 4_000
MAX_TOTAL_OPEN_CHARS = 16_000


class ToolInputError(ValueError):
    pass


class PaperToolbox:
    """Read-only, scoped tools for exploring the local paper repository."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        allowed_paper_ids: list[int] | None = None,
        user_id: int = 1,
    ) -> None:
        self.conn = conn
        self.user_id = user_id
        self.allowed_paper_ids = set(allowed_paper_ids) if allowed_paper_ids else None
        self.search_registry: dict[str, dict[str, Any]] = {}
        self.opened_registry: dict[str, dict[str, Any]] = {}
        self.evidence_ids: dict[str, str] = {}
        self.total_open_chars = 0

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "search_metadata":
            return self.search_metadata(**arguments)
        if name == "search_text":
            return self.search_text(**arguments)
        if name == "open_evidence":
            return self.open_evidence(**arguments)
        raise ToolInputError("unknown_tool")

    def search_metadata(
        self,
        query: str = "",
        category: str = "",
        paper_ids: list[int] | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        scope = self._resolve_scope(paper_ids)
        bounded_limit = _bounded_int(limit, 1, 20, "limit")
        clauses: list[str] = []
        params: list[Any] = []
        if scope is not None:
            if not scope:
                return {"items": [], "count": 0}
            clauses.append("id IN ({})".format(",".join("?" for _ in scope)))
            params.extend(sorted(scope))
        cleaned_query = str(query).strip()
        cleaned_category = str(category).strip()
        if len(cleaned_query) > 500 or len(cleaned_category) > 80:
            raise ToolInputError("search_term_too_long")
        if cleaned_category:
            clauses.append("primary_category = ?")
            params.append(cleaned_category)
        access_condition, access_params = accessible_paper_condition("p", self.user_id)
        clauses.append(access_condition)
        params.extend(access_params)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT id, source, source_id, source_url, venue, title, authors_json,
                   abstract, primary_category, published_at, processing_status
            FROM papers p
            {where}
            ORDER BY published_at DESC, id DESC
            """,
            tuple(params),
        ).fetchall()
        needle = cleaned_query.lower()
        items = []
        for row in rows:
            authors = json.loads(row["authors_json"])
            haystack = " ".join([row["title"], row["abstract"], " ".join(authors), row["primary_category"]]).lower()
            if needle and needle not in haystack:
                continue
            items.append(
                {
                    "paper_id": int(row["id"]),
                    "source": row["source"],
                    "source_id": row["source_id"],
                    "source_url": row["source_url"],
                    "venue": row["venue"],
                    "title": row["title"],
                    "authors": authors,
                    "abstract_snippet": str(row["abstract"])[:500],
                    "category": row["primary_category"],
                    "published_at": row["published_at"],
                    "processing_status": row["processing_status"],
                }
            )
            if len(items) >= bounded_limit:
                break
        return {"items": items, "count": len(items)}

    def search_text(
        self,
        query: str,
        paper_ids: list[int] | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        cleaned_query = str(query).strip()
        if not cleaned_query:
            raise ToolInputError("query_required")
        if len(cleaned_query) > 500:
            raise ToolInputError("query_too_long")
        scope = self._resolve_scope(paper_ids)
        if scope is not None and not scope:
            return {"items": [], "count": 0}
        bounded_limit = _bounded_int(limit, 1, MAX_SEARCH_LIMIT, "limit")
        results = search_chunks(
            self.conn,
            cleaned_query,
            limit=bounded_limit,
            paper_ids=sorted(scope) if scope is not None else None,
            user_id=self.user_id,
        )
        items = []
        for result in results:
            ref_id = _ref_id(result)
            self.search_registry[ref_id] = result
            items.append(
                {
                    "ref_id": ref_id,
                    "paper_id": int(result["paper_id"]),
                    "paper_title": result["paper_title"],
                    "section_title": result["section_title"],
                    "source": "chunk",
                    "score": result["score"],
                    "snippet": extract_snippet(result["content"], 420),
                }
            )
        return {"items": items, "count": len(items)}

    def open_evidence(self, ref_id: str, max_chars: int = 2_400) -> dict[str, Any]:
        ref = str(ref_id).strip()
        if ref not in self.search_registry:
            raise ToolInputError("ref_not_in_search_results")
        if ref in self.evidence_ids:
            evidence_id = self.evidence_ids[ref]
            return _opened_tool_result(self.opened_registry[evidence_id], ref, evidence_id)
        bounded_chars = _bounded_int(max_chars, 200, MAX_OPEN_CHARS, "max_chars")
        remaining_chars = MAX_TOTAL_OPEN_CHARS - self.total_open_chars
        if remaining_chars < 200:
            raise ToolInputError("evidence_budget_exceeded")
        bounded_chars = min(bounded_chars, remaining_chars)
        item = dict(self.search_registry[ref])
        if self.allowed_paper_ids is not None and int(item["paper_id"]) not in self.allowed_paper_ids:
            raise ToolInputError("paper_out_of_scope")
        item["content"] = str(item["content"])[:bounded_chars]
        if ref not in self.evidence_ids:
            self.evidence_ids[ref] = f"E{len(self.evidence_ids) + 1}"
        evidence_id = self.evidence_ids[ref]
        item["evidence_id"] = evidence_id
        item["ref_id"] = ref
        self.opened_registry[evidence_id] = item
        self.total_open_chars += len(item["content"])
        return _opened_tool_result(item, ref, evidence_id)

    def citations(self, evidence_ids: list[str] | None = None) -> list[dict[str, Any]]:
        requested = list(self.opened_registry) if evidence_ids is None else evidence_ids
        citations = []
        for evidence_id in requested:
            item = self.opened_registry.get(evidence_id)
            if item is None:
                continue
            citation = {key: value for key, value in item.items() if key not in {"evidence_id", "ref_id"}}
            citation["evidence_id"] = evidence_id
            citations.append(citation)
        return citations

    def _resolve_scope(self, requested: list[int] | None) -> set[int] | None:
        if requested is None:
            return set(self.allowed_paper_ids) if self.allowed_paper_ids is not None else None
        if not isinstance(requested, list) or len(requested) > 20:
            raise ToolInputError("invalid_paper_ids")
        if any(type(item) is not int or item <= 0 for item in requested):
            raise ToolInputError("invalid_paper_ids")
        scope = set(requested)
        if self.allowed_paper_ids is not None and not scope.issubset(self.allowed_paper_ids):
            raise ToolInputError("paper_out_of_scope")
        return scope


PAPER_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_metadata",
            "description": "按标题、摘要、作者或分类寻找候选论文，只返回紧凑元数据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "maxLength": 500},
                    "category": {"type": "string", "maxLength": 80},
                    "paper_ids": {"type": "array", "items": {"type": "integer", "minimum": 1}, "maxItems": 20},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "在当前已解析论文正文 chunk 中搜索文本，返回可继续打开的 ref_id。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 500},
                    "paper_ids": {"type": "array", "items": {"type": "integer", "minimum": 1}, "maxItems": 20},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_LIMIT},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_evidence",
            "description": "打开 search_text 返回的一条证据。只有打开过的证据才允许被最终答案引用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref_id": {"type": "string", "minLength": 1},
                    "max_chars": {"type": "integer", "minimum": 200, "maximum": MAX_OPEN_CHARS},
                },
                "required": ["ref_id"],
                "additionalProperties": False,
            },
        },
    },
]


def _ref_id(result: dict[str, Any]) -> str:
    return f"chunk:{int(result['id'])}"


def _opened_tool_result(item: dict[str, Any], ref_id: str, evidence_id: str) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "ref_id": ref_id,
        "paper_id": item["paper_id"],
        "paper_title": item["paper_title"],
        "section_title": item["section_title"],
        "source": "chunk",
        "paper_source": item.get("paper_source"),
        "source_id": item.get("source_id"),
        "source_url": item.get("source_url"),
        "pdf_view_url": item.get("pdf_view_url"),
        "source_hash": item.get("source_hash"),
        "chunk_index": item.get("chunk_index"),
        "char_start": item.get("char_start"),
        "char_end": item.get("char_end"),
        "content": item["content"],
    }


def _bounded_int(value: Any, minimum: int, maximum: int, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ToolInputError(f"invalid_{name}") from exc
    if parsed < minimum or parsed > maximum:
        raise ToolInputError(f"invalid_{name}")
    return parsed

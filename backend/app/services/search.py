from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..db.schema import paper_chunks_fts_ready
from .llm import LLMClient
from .text_utils import cosine_similarity, deterministic_embedding, keyword_score, normalize_text, tokenize


CJK_SEQUENCE_RE = re.compile(r"[\u3400-\u9fff]{2,}")


def extract_snippet(content: str, limit: int = 150) -> str:
    lines = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line.lstrip("- ").strip())
    return " ".join(lines)[:limit]


def _fts_match_query(query: str) -> str:
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        cleaned = term.strip()
        if len(cleaned) < 3 or cleaned in seen:
            return
        seen.add(cleaned)
        terms.append(cleaned)

    for phrase in CJK_SEQUENCE_RE.findall(normalize_text(query)):
        add(phrase)
    for token in tokenize(query):
        add(token)
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms[:16])


def _fts_candidate_ids(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    paper_ids: list[int] | None,
) -> list[int] | None:
    if not paper_chunks_fts_ready(conn):
        return None
    match_query = _fts_match_query(query)
    if not match_query:
        return None
    clauses = ["paper_chunks_fts MATCH ?"]
    params: list[Any] = [match_query]
    if paper_ids:
        clauses.append("pc.paper_id IN ({})".format(",".join("?" for _ in paper_ids)))
        params.extend(paper_ids)
    params.append(max(limit * 16, 80))
    try:
        rows = conn.execute(
            f"""
            SELECT pc.id
            FROM paper_chunks_fts
            JOIN paper_chunks pc ON pc.id = paper_chunks_fts.rowid
            JOIN paper_documents d ON d.id = pc.document_id
            WHERE {' AND '.join(clauses)}
              AND d.status = 'completed' AND d.source_hash = pc.source_hash
            ORDER BY bm25(paper_chunks_fts), pc.created_at DESC, pc.chunk_index
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    except sqlite3.Error:
        return None
    return [int(row["id"]) for row in rows]


def _fetch_chunk_rows(
    conn: sqlite3.Connection,
    *,
    paper_ids: list[int] | None = None,
    chunk_ids: list[int] | None = None,
) -> list[sqlite3.Row]:
    clauses = ["d.status = 'completed'", "d.source_hash = pc.source_hash"]
    params: list[Any] = []
    if paper_ids:
        clauses.append("pc.paper_id IN ({})".format(",".join("?" for _ in paper_ids)))
        params.extend(paper_ids)
    if chunk_ids is not None:
        if not chunk_ids:
            return []
        clauses.append("pc.id IN ({})".format(",".join("?" for _ in chunk_ids)))
        params.extend(chunk_ids)
    return conn.execute(
        f"""
        SELECT pc.id, pc.paper_id, pc.source_hash, pc.chunk_index, pc.heading,
               pc.content, pc.char_start, pc.char_end, pc.token_count, pc.embedding_json,
               p.title AS paper_title, p.source, p.source_id, p.source_url,
               p.primary_category
        FROM paper_chunks pc
        JOIN paper_documents d ON d.id = pc.document_id
        JOIN papers p ON p.id = pc.paper_id
        WHERE {' AND '.join(clauses)}
        ORDER BY pc.created_at DESC, pc.chunk_index
        """,
        tuple(params),
    ).fetchall()


def search_chunks(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 8,
    paper_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    cleaned = query.strip()
    candidate_ids = _fts_candidate_ids(conn, cleaned, limit, paper_ids) if cleaned else None
    if candidate_ids == []:
        return []
    rows = _fetch_chunk_rows(conn, paper_ids=paper_ids, chunk_ids=candidate_ids)
    query_embedding = deterministic_embedding(cleaned)
    results: list[dict[str, Any]] = []
    for row in rows:
        score = 0.7 * keyword_score(cleaned, row["content"] + " " + row["paper_title"])
        score += 0.3 * cosine_similarity(query_embedding, json.loads(row["embedding_json"]))
        if cleaned and score <= 0:
            continue
        results.append(
            {
                "id": int(row["id"]),
                "chunk_id": int(row["id"]),
                "paper_id": int(row["paper_id"]),
                "paper_title": row["paper_title"],
                "source": "chunk",
                "paper_source": row["source"],
                "source_id": row["source_id"],
                "source_url": row["source_url"],
                "pdf_view_url": f"/api/papers/{int(row['paper_id'])}/pdf",
                "primary_category": row["primary_category"],
                "section": "chunk",
                "section_title": row["heading"],
                "heading": row["heading"],
                "content": row["content"],
                "score": round(float(score), 4),
                "source_hash": row["source_hash"],
                "chunk_index": int(row["chunk_index"]),
                "char_start": int(row["char_start"]),
                "char_end": int(row["char_end"]),
                "token_count": int(row["token_count"]),
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def _search_wiki_sections(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    paper_ids: list[int] | None,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ws.id, ws.paper_id, ws.section, ws.title AS section_title, ws.content,
               p.title AS paper_title, p.source, p.source_id, p.source_url, p.primary_category
        FROM wiki_sections ws JOIN papers p ON p.id = ws.paper_id
        ORDER BY ws.updated_at DESC
        """
    ).fetchall()
    allowed = set(paper_ids or [])
    results = []
    for row in rows:
        if allowed and int(row["paper_id"]) not in allowed:
            continue
        score = keyword_score(query, row["content"] + " " + row["paper_title"])
        if query.strip() and score <= 0:
            continue
        results.append(
            {
                "id": int(row["id"]),
                "paper_id": int(row["paper_id"]),
                "paper_title": row["paper_title"],
                "source": "wiki",
                "paper_source": row["source"],
                "source_id": row["source_id"],
                "source_url": row["source_url"],
                "primary_category": row["primary_category"],
                "section": row["section"],
                "section_title": row["section_title"],
                "content": row["content"],
                "score": round(float(score), 4),
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def search_wiki(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 8,
    paper_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    combined = [
        *search_chunks(conn, query, limit=limit, paper_ids=paper_ids),
        *_search_wiki_sections(conn, query, limit=limit, paper_ids=paper_ids),
    ]
    combined.sort(key=lambda item: item["score"] + (0.04 if item["source"] == "chunk" else 0), reverse=True)
    return combined[:limit]


def answer_question(conn: sqlite3.Connection, question: str, paper_ids: list[int] | None = None) -> dict[str, Any]:
    evidence = [item for item in search_chunks(conn, question, limit=5, paper_ids=paper_ids) if item["score"] >= 0.08]
    if not evidence:
        return {
            "answer": "当前没有已解析且可核验的论文正文证据。请先解析相关论文。",
            "citations": [],
            "confidence": 0.1,
            "agent_trace": ["ClassicQA", "ChunkRetriever", "EvidenceValidator"],
        }
    evidence_text = "\n\n".join(
        f"[{index + 1}] 论文：{item['paper_title']}\n章节：{item['section_title']}\n片段：{extract_snippet(item['content'], 500)}"
        for index, item in enumerate(evidence)
    )
    answer = LLMClient().complete(
        "你是科研论文问答助手。只能依据给定的已解析论文正文回答，不得编造来源。",
        f"问题：{question}\n\n证据：\n{evidence_text}\n\n请用中文简洁回答并标明证据编号。",
    ).strip()
    return {
        "answer": answer,
        "citations": evidence,
        "confidence": round(min(0.92, 0.55 + sum(item["score"] for item in evidence[:3]) / 3), 2),
        "agent_trace": ["ClassicQA", "ChunkRetriever", "LLMAnswerSynthesizer", "EvidenceValidator"],
    }


def build_graph(conn: sqlite3.Connection, topic: str = "", limit: int = 42) -> dict[str, Any]:
    concept_rows = conn.execute(
        """
        SELECT c.id, c.name, c.description, COUNT(pc.paper_id) AS paper_count
        FROM concepts c JOIN paper_concepts pc ON pc.concept_id = c.id
        GROUP BY c.id ORDER BY paper_count DESC, c.name LIMIT ?
        """,
        (limit,),
    ).fetchall()
    topic_norm = topic.strip().lower()
    nodes = [
        {
            "id": f"c-{row['id']}",
            "label": row["name"],
            "type": "concept",
            "description": row["description"],
            "weight": row["paper_count"],
        }
        for row in concept_rows
        if not topic_norm or topic_norm in row["name"].lower() or topic_norm in row["description"].lower()
    ]
    visible_concepts = {int(node["id"].split("-")[1]) for node in nodes}
    if not visible_concepts:
        return {"nodes": [], "links": []}
    placeholders = ",".join("?" for _ in visible_concepts)
    paper_rows = conn.execute(
        f"""
        SELECT DISTINCT p.id, p.title, p.primary_category
        FROM papers p JOIN paper_concepts pc ON pc.paper_id = p.id
        WHERE pc.concept_id IN ({placeholders})
        ORDER BY p.published_at DESC LIMIT 16
        """,
        tuple(visible_concepts),
    ).fetchall()
    nodes.extend(
        {
            "id": f"p-{row['id']}",
            "label": row["title"],
            "type": "paper",
            "category": row["primary_category"],
            "weight": 1,
        }
        for row in paper_rows
    )
    visible_papers = {int(node["id"].split("-")[1]) for node in nodes if node["type"] == "paper"}
    links = []
    for row in conn.execute("SELECT source_concept_id, target_concept_id, relation, weight FROM concept_edges"):
        if row["source_concept_id"] in visible_concepts and row["target_concept_id"] in visible_concepts:
            links.append(
                {
                    "source": f"c-{row['source_concept_id']}",
                    "target": f"c-{row['target_concept_id']}",
                    "relation": row["relation"],
                    "weight": row["weight"],
                }
            )
    for row in conn.execute(
        f"SELECT paper_id, concept_id, relation, weight FROM paper_concepts WHERE concept_id IN ({placeholders})",
        tuple(visible_concepts),
    ):
        if row["paper_id"] in visible_papers:
            links.append(
                {
                    "source": f"p-{row['paper_id']}",
                    "target": f"c-{row['concept_id']}",
                    "relation": row["relation"],
                    "weight": row["weight"],
                }
            )
    return {"nodes": nodes, "links": links}

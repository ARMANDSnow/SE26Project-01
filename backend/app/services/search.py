from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..database import paper_chunks_fts_ready
from .llm import LLMClient, LLMProviderError
from .text_utils import cosine_similarity, deterministic_embedding, keyword_score, normalize_text, tokenize


CJK_SEQUENCE_RE = re.compile(r"[\u4e00-\u9fff]+")


def extract_snippet(content: str, limit: int = 150) -> str:
    lines = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line.lstrip("- ").strip())
    return " ".join(lines)[:limit]


def search_wiki(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 8,
    paper_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    chunk_results = _search_chunks(conn, query, limit=limit, paper_ids=paper_ids)
    wiki_results = _search_wiki_sections(conn, query, limit=limit, paper_ids=paper_ids)
    combined: list[dict[str, Any]] = []
    seen: set[tuple[int, str, int]] = set()
    for item in [*chunk_results, *wiki_results]:
        key = (int(item["paper_id"]), str(item.get("source", "wiki")), int(item["id"]))
        if key in seen:
            continue
        seen.add(key)
        combined.append(item)
    combined.sort(
        key=lambda item: item["score"] + (0.04 if item.get("source") == "chunk" else 0.0),
        reverse=True,
    )
    return combined[:limit]


def _search_chunks(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 8,
    paper_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    candidate_ids: list[int] | None = None
    if query.strip():
        candidate_ids = _fts_chunk_candidate_ids(conn, query, limit=limit, paper_ids=paper_ids)
    if candidate_ids == []:
        return []
    rows = _fetch_chunk_rows(conn, paper_ids=paper_ids, chunk_ids=candidate_ids)
    results = _rank_chunk_rows(rows, query)
    if candidate_ids and query.strip() and not results:
        results = _rank_chunk_rows(_fetch_chunk_rows(conn, paper_ids=paper_ids), query)
    return results[:limit]


def _fetch_chunk_rows(
    conn: sqlite3.Connection,
    paper_ids: list[int] | None = None,
    chunk_ids: list[int] | None = None,
) -> list[sqlite3.Row]:
    allowed = set(paper_ids or [])
    params: list[Any] = []
    clauses: list[str] = []
    if allowed:
        clauses.append("pc.paper_id IN ({})".format(",".join("?" for _ in allowed)))
        params.extend(sorted(allowed))
    if chunk_ids is not None:
        if not chunk_ids:
            return []
        clauses.append("pc.id IN ({})".format(",".join("?" for _ in chunk_ids)))
        params.extend(chunk_ids)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.execute(
        f"""
        SELECT pc.id, pc.paper_id, pc.source_type, pc.source_url, pc.chunk_index, pc.heading,
               pc.content, pc.char_start, pc.char_end, pc.token_count, pc.embedding_json,
               p.title AS paper_title, p.arxiv_id, p.arxiv_url, p.pdf_url, p.primary_category
        FROM paper_chunks pc
        JOIN papers p ON p.id = pc.paper_id
        {where}
        ORDER BY pc.created_at DESC, pc.chunk_index
        """,
        tuple(params),
    ).fetchall()


def _rank_chunk_rows(rows: list[sqlite3.Row], query: str) -> list[dict[str, Any]]:
    query_embedding = deterministic_embedding(query)
    results: list[dict[str, Any]] = []
    for row in rows:
        embedding = json.loads(row["embedding_json"])
        score = 0.7 * keyword_score(query, row["content"] + " " + row["paper_title"]) + 0.3 * cosine_similarity(
            query_embedding, embedding
        )
        if query.strip() and score <= 0:
            continue
        section_title = row["heading"] or f"{row['source_type']} chunk {row['chunk_index'] + 1}"
        results.append(
            {
                "id": row["id"],
                "chunk_id": row["id"],
                "paper_id": row["paper_id"],
                "paper_title": row["paper_title"],
                "arxiv_id": row["arxiv_id"],
                "arxiv_url": row["arxiv_url"],
                "pdf_url": row["pdf_url"],
                "primary_category": row["primary_category"],
                "section": "chunk",
                "section_title": section_title,
                "content": row["content"],
                "score": round(float(score), 4),
                "source": "chunk",
                "source_type": row["source_type"],
                "source_url": row["source_url"],
                "chunk_index": row["chunk_index"],
                "heading": row["heading"],
                "char_start": row["char_start"],
                "char_end": row["char_end"],
                "token_count": row["token_count"],
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    return results


def _fts_chunk_candidate_ids(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 8,
    paper_ids: list[int] | None = None,
) -> list[int] | None:
    if not paper_chunks_fts_ready(conn):
        return None
    match_query = _fts_match_query(query)
    if not match_query:
        return None
    allowed = set(paper_ids or [])
    clauses = ["paper_chunks_fts MATCH ?"]
    params: list[Any] = [match_query]
    if allowed:
        clauses.append("pc.paper_id IN ({})".format(",".join("?" for _ in allowed)))
        params.extend(sorted(allowed))
    candidate_limit = max(limit * 16, 80)
    params.append(candidate_limit)
    try:
        rows = conn.execute(
            f"""
            SELECT pc.id
            FROM paper_chunks_fts
            JOIN paper_chunks pc ON pc.id = paper_chunks_fts.rowid
            WHERE {' AND '.join(clauses)}
            ORDER BY bm25(paper_chunks_fts), pc.created_at DESC, pc.chunk_index
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    except sqlite3.Error:
        return None
    return [int(row["id"]) for row in rows]


def _fts_match_query(query: str) -> str:
    terms: list[str] = []
    seen: set[str] = set()

    def add_term(term: str) -> None:
        cleaned = term.strip()
        if len(cleaned) < 3 or cleaned in seen:
            return
        seen.add(cleaned)
        terms.append(cleaned)

    for phrase in CJK_SEQUENCE_RE.findall(normalize_text(query)):
        add_term(phrase)
    for token in tokenize(query):
        if len(token) == 1 and CJK_SEQUENCE_RE.fullmatch(token):
            continue
        add_term(token)
    return " OR ".join(_fts_quote(term) for term in terms[:16])


def _fts_quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _search_wiki_sections(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 8,
    paper_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ws.id, ws.paper_id, ws.section, ws.title AS section_title, ws.content, ws.embedding_json,
               p.title AS paper_title, p.arxiv_id, p.arxiv_url, p.pdf_url, p.primary_category
        FROM wiki_sections ws
        JOIN papers p ON p.id = ws.paper_id
        ORDER BY ws.updated_at DESC
        """
    ).fetchall()
    query_embedding = deterministic_embedding(query)
    allowed = set(paper_ids or [])
    results: list[dict[str, Any]] = []
    for row in rows:
        if allowed and int(row["paper_id"]) not in allowed:
            continue
        embedding = json.loads(row["embedding_json"])
        score = 0.65 * keyword_score(query, row["content"] + " " + row["paper_title"]) + 0.35 * cosine_similarity(
            query_embedding, embedding
        )
        if query.strip() and score <= 0:
            continue
        results.append(
            {
                "id": row["id"],
                "paper_id": row["paper_id"],
                "paper_title": row["paper_title"],
                "arxiv_id": row["arxiv_id"],
                "arxiv_url": row["arxiv_url"],
                "pdf_url": row["pdf_url"],
                "primary_category": row["primary_category"],
                "section": row["section"],
                "section_title": row["section_title"],
                "content": row["content"],
                "score": round(float(score), 4),
                "source": "wiki",
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def answer_question(conn: sqlite3.Connection, question: str, paper_ids: list[int] | None = None) -> dict[str, Any]:
    results = search_wiki(conn, question, limit=5, paper_ids=paper_ids)
    useful = [item for item in results if item["score"] >= 0.08]
    if not useful:
        return {
            "answer": "当前知识库中没有足够证据回答这个问题。建议先抓取或处理更多相关论文。",
            "citations": [],
            "confidence": 0.18,
            "agent_trace": ["QAAgent", "HybridRetriever", "EvidenceValidator"],
        }
    answer = synthesize_answer(question, useful[:5])
    agent_trace = ["QAAgent", "HybridRetriever", "EvidenceValidator"]
    if answer is None:
        bullets = []
        for item in useful[:3]:
            snippet = extract_snippet(item["content"])
            bullets.append(f"《{item['paper_title']}》的 {item['section_title']} 指出：{snippet}")
        answer = "基于当前论文 Wiki，可以得到以下结论：\n\n" + "\n".join(f"{index + 1}. {bullet}" for index, bullet in enumerate(bullets))
        answer += "\n\n这些结论来自已处理论文片段，适合继续进入论文详情页核对原文链接。"
    else:
        agent_trace.insert(2, "LLMAnswerSynthesizer")
    return {
        "answer": answer,
        "citations": useful,
        "confidence": round(min(0.92, 0.55 + sum(item["score"] for item in useful[:3]) / 3), 2),
        "agent_trace": agent_trace,
    }


def synthesize_answer(question: str, evidence: list[dict[str, Any]]) -> str | None:
    client = LLMClient()
    if client.settings.should_use_mock_llm:
        return None
    evidence_text = "\n\n".join(
        f"[{index + 1}] 论文：{item['paper_title']}\n章节：{item['section_title']}\n片段：{extract_snippet(item['content'], 320)}"
        for index, item in enumerate(evidence)
    )
    try:
        answer = client.complete(
            "你是科研论文问答助手。只能基于给定证据回答，必须在回答中说明依据来自哪些论文或章节。",
            f"问题：{question}\n\n证据：\n{evidence_text}\n\n请用中文给出简洁答案，并保留论文出处。",
        ).strip()
    except LLMProviderError:
        raise
    except Exception:
        return None
    return answer or None


def build_graph(conn: sqlite3.Connection, topic: str = "", limit: int = 42) -> dict[str, Any]:
    concept_rows = conn.execute(
        """
        SELECT c.id, c.name, c.description, COUNT(pc.paper_id) AS paper_count
        FROM concepts c
        JOIN paper_concepts pc ON pc.concept_id = c.id
        GROUP BY c.id
        ORDER BY paper_count DESC, c.name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    concept_ids = [row["id"] for row in concept_rows]
    topic_norm = topic.strip().lower()
    nodes: list[dict[str, Any]] = []
    for row in concept_rows:
        if topic_norm and topic_norm not in row["name"].lower() and topic_norm not in row["description"].lower():
            continue
        nodes.append(
            {
                "id": f"c-{row['id']}",
                "label": row["name"],
                "type": "concept",
                "description": row["description"],
                "weight": row["paper_count"],
            }
        )
    visible_concepts = {int(node["id"].split("-")[1]) for node in nodes}
    if not visible_concepts:
        if topic_norm:
            return {"nodes": [], "links": []}
        visible_concepts = set(concept_ids[: min(12, len(concept_ids))])
        nodes = [
            {
                "id": f"c-{row['id']}",
                "label": row["name"],
                "type": "concept",
                "description": row["description"],
                "weight": row["paper_count"],
            }
            for row in concept_rows
            if row["id"] in visible_concepts
        ]
    paper_rows = conn.execute(
        """
        SELECT DISTINCT p.id, p.title, p.primary_category
        FROM papers p
        JOIN paper_concepts pc ON pc.paper_id = p.id
        WHERE pc.concept_id IN ({})
        ORDER BY p.published_at DESC
        LIMIT 16
        """.format(",".join("?" for _ in visible_concepts)),
        tuple(visible_concepts),
    ).fetchall() if visible_concepts else []
    for row in paper_rows:
        nodes.append({"id": f"p-{row['id']}", "label": row["title"], "type": "paper", "category": row["primary_category"], "weight": 1})
    edge_rows = conn.execute(
        """
        SELECT source_concept_id, target_concept_id, relation, weight
        FROM concept_edges
        """
    ).fetchall()
    links: list[dict[str, Any]] = []
    for row in edge_rows:
        if row["source_concept_id"] in visible_concepts and row["target_concept_id"] in visible_concepts:
            links.append(
                {
                    "source": f"c-{row['source_concept_id']}",
                    "target": f"c-{row['target_concept_id']}",
                    "relation": row["relation"],
                    "weight": row["weight"],
                }
            )
    paper_concept_rows = conn.execute(
        """
        SELECT paper_id, concept_id, relation, weight
        FROM paper_concepts
        WHERE concept_id IN ({})
        LIMIT 60
        """.format(",".join("?" for _ in visible_concepts)),
        tuple(visible_concepts),
    ).fetchall() if visible_concepts else []
    visible_papers = {int(node["id"].split("-")[1]) for node in nodes if node["type"] == "paper"}
    for row in paper_concept_rows:
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

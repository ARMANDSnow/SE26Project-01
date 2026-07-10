from __future__ import annotations

import sqlite3
from typing import Any

from .llm import LLMClient
from .text_utils import keyword_score


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
    rows = conn.execute(
        """
        SELECT ws.id, ws.paper_id, ws.section, ws.title AS section_title, ws.content,
               p.title AS paper_title, p.arxiv_id, p.arxiv_url, p.pdf_url, p.primary_category
        FROM wiki_sections ws
        JOIN papers p ON p.id = ws.paper_id
        ORDER BY ws.updated_at DESC
        """
    ).fetchall()
    allowed = set(paper_ids or [])
    results: list[dict[str, Any]] = []
    for row in rows:
        if allowed and int(row["paper_id"]) not in allowed:
            continue
        score = keyword_score(query, row["content"] + " " + row["paper_title"])
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
    agent_trace = ["QAAgent", "KeywordRetriever", "LLMAnswerSynthesizer", "EvidenceValidator"]
    return {
        "answer": answer,
        "citations": useful,
        "confidence": round(min(0.92, 0.55 + sum(item["score"] for item in useful[:3]) / 3), 2),
        "agent_trace": agent_trace,
    }


def synthesize_answer(question: str, evidence: list[dict[str, Any]]) -> str:
    client = LLMClient()
    evidence_text = "\n\n".join(
        f"[{index + 1}] 论文：{item['paper_title']}\n章节：{item['section_title']}\n片段：{extract_snippet(item['content'], 320)}"
        for index, item in enumerate(evidence)
    )
    return client.complete(
        "你是科研论文问答助手。只能基于给定证据回答，必须在回答中说明依据来自哪些论文或章节。",
        f"问题：{question}\n\n证据：\n{evidence_text}\n\n请用中文给出简洁答案，并保留论文出处。",
    ).strip()


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

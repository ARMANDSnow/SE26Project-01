from __future__ import annotations

import sqlite3

from backend.app.database import attach_concepts, replace_wiki_sections, upsert_paper


def add_test_paper(
    conn: sqlite3.Connection,
    *,
    arxiv_id: str = "test.00001",
    title: str = "RAG Evidence Grounding",
    category: str = "cs.CL",
    processed: bool = True,
) -> int:
    paper_id = upsert_paper(
        conn,
        {
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": ["Ada Lovelace", "Grace Hopper"],
            "abstract": f"{title} evaluates grounded answers using retrieved paper evidence.",
            "categories": [category],
            "primary_category": category,
            "published_at": "2025-01-01",
            "updated_at": "2025-01-02",
            "pdf_url": "https://example.test/paper.pdf",
            "arxiv_url": "https://example.test/paper",
            "doi": None,
            "processing_status": "processed" if processed else "pending",
        },
    )
    if processed:
        replace_wiki_sections(
            conn,
            paper_id,
            {
                "summary": f"# Summary\n\n{title} grounds each answer in retrieved paper evidence.",
                "concepts": "# Concepts\n\n- Evidence Grounding keeps answers traceable to source text.",
                "methods": "# Methods\n\nThe method retrieves evidence before generating an answer.",
                "experiments": "# Experiments\n\nThe evaluation measures citation accuracy and retrieval recall.",
            },
        )
        attach_concepts(
            conn,
            paper_id,
            [
                {"name": "RAG", "description": "Retrieval-augmented generation", "relation": "topic", "weight": 1.0},
                {"name": "Evidence Grounding", "description": "Answers cite paper evidence", "relation": "method", "weight": 0.9},
            ],
        )
    return paper_id


def populate_test_library(conn: sqlite3.Connection) -> list[int]:
    return [
        add_test_paper(conn),
        add_test_paper(conn, arxiv_id="test.00002", title="Graph Methods for Paper Discovery", category="cs.AI"),
        add_test_paper(conn, arxiv_id="test.00003", title="Pending Paper", processed=False),
    ]

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.database import add_note, connect, get_paper_detail, init_db, init_schema, list_papers, set_favorite, upsert_paper
from backend.app.main import app
from backend.app.services.agents import SummaryAgent, process_paper
from backend.app.services.search import answer_question, build_graph, search_wiki
from backend.tests.fixtures import add_test_paper, populate_test_library


def memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    populate_test_library(conn)
    return conn


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.sqlite3"))
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY_FILE", str(tmp_path / "missing-api-key.txt"))
    get_settings.cache_clear()
    with TestClient(app) as client:
        with connect() as conn:
            populate_test_library(conn)
        yield client
    get_settings.cache_clear()


def test_init_db_does_not_create_demo_papers(tmp_path):
    path = tmp_path / "empty.sqlite3"
    init_db(path)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0


def test_config_reads_key_from_explicit_file(tmp_path, monkeypatch):
    key_path = tmp_path / "api-key.txt"
    key_path.write_text("test-key\n", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY_FILE", str(key_path))
    get_settings.cache_clear()
    assert get_settings().llm_available is True
    assert get_settings().llm_chat_model == "deepseek-v4-flash"
    get_settings.cache_clear()


def test_list_papers_filters_by_category_and_keyword():
    conn = memory_db()
    papers = list_papers(conn, q="RAG", category="cs.CL", limit=20)
    assert len(papers) == 1
    assert papers[0]["title"] == "RAG Evidence Grounding"


def test_process_paper_generates_required_wiki_sections(monkeypatch):
    conn = memory_db()
    pending = conn.execute("SELECT id FROM papers WHERE processing_status = 'pending'").fetchone()["id"]

    def summarize(_, __):
        return (
            {
                "summary": "# Summary\n\nA sufficiently long generated summary based on the real paper abstract.",
                "concepts": "# Concepts\n\nA sufficiently long generated concepts section for this paper.",
                "methods": "# Methods\n\nA sufficiently long generated methods section for this paper.",
                "experiments": "# Experiments\n\nA sufficiently long generated experiments section for this paper.",
            },
            [{"name": "Test concept", "description": "A test-only LLM response", "relation": "topic", "weight": 0.8}],
        )

    monkeypatch.setattr(SummaryAgent, "summarize", summarize)
    result = process_paper(conn, pending)
    assert result["status"] == "processed"
    detail = get_paper_detail(conn, pending)
    assert {section["section"] for section in detail["wiki"]} >= {"summary", "concepts", "methods", "experiments"}


def test_search_uses_real_keywords_only():
    conn = memory_db()
    assert search_wiki(conn, "Evidence Grounding", limit=5)
    assert search_wiki(conn, "definitely-no-such-topic", limit=5) == []


def test_qa_uses_explicit_test_double(monkeypatch):
    conn = memory_db()
    monkeypatch.setattr("backend.app.services.search.synthesize_answer", lambda question, evidence: "Grounded answer from test evidence.")
    result = answer_question(conn, "How is evidence grounded?")
    assert result["citations"]
    assert result["answer"] == "Grounded answer from test evidence."


def test_favorite_note_history_flow():
    conn = memory_db()
    paper_id = conn.execute("SELECT id FROM papers LIMIT 1").fetchone()["id"]
    detail = set_favorite(conn, paper_id, True)
    assert detail["is_favorite"] is True
    note = add_note(conn, paper_id, "Compare the method section.", "test note")
    assert note["paper_id"] == paper_id


def test_set_favorite_missing_paper_raises_value_error():
    conn = memory_db()
    with pytest.raises(ValueError):
        set_favorite(conn, 999_999, True)


def test_graph_has_nodes_and_links():
    conn = memory_db()
    graph = build_graph(conn, topic="RAG")
    assert graph["nodes"]
    assert graph["links"]


def test_graph_unknown_topic_returns_empty_result():
    conn = memory_db()
    assert build_graph(conn, topic="definitely-no-such-topic-xyz") == {"nodes": [], "links": []}


def test_upsert_paper_deduplicates_same_title_different_arxiv_id():
    conn = memory_db()
    first_id = add_test_paper(conn, arxiv_id="dedupe.00001", title="A Stable Duplicate Title")
    second_id = upsert_paper(
        conn,
        {
            "arxiv_id": "dedupe.00002",
            "title": "A Stable Duplicate Title",
            "authors": ["Ada"],
            "abstract": "A duplicate title should map to one paper record.",
            "categories": ["cs.AI"],
            "primary_category": "cs.AI",
            "published_at": "2026-07-09",
        },
    )
    assert second_id == first_id


def test_api_health_reports_llm_unavailable(api_client):
    health = api_client.get("/api/health").json()
    assert health["llm_available"] is False
    assert health["papers"] == 3


def test_api_process_requires_configured_llm(api_client):
    paper_id = api_client.get("/api/papers?limit=1").json()["items"][0]["id"]
    response = api_client.post(f"/api/papers/{paper_id}/process")
    assert response.status_code == 503


def test_api_qa_requires_configured_llm(api_client):
    response = api_client.post("/api/qa", json={"question": "How is evidence grounded?"})
    assert response.status_code == 503


def test_api_ingest_reports_duplicate_count(api_client, monkeypatch):
    fetched = [
        {
            "arxiv_id": "2699.10001",
            "title": "Imported duplicate title",
            "authors": ["Ada"],
            "abstract": "First fetched duplicate.",
            "categories": ["cs.AI"],
            "primary_category": "cs.AI",
            "published_at": "2026-07-09",
        },
        {
            "arxiv_id": "2699.10002",
            "title": "Imported duplicate title",
            "authors": ["Grace"],
            "abstract": "Second fetched duplicate.",
            "categories": ["cs.AI"],
            "primary_category": "cs.AI",
            "published_at": "2026-07-09",
        },
    ]
    monkeypatch.setattr("backend.app.main.fetch_arxiv_papers", lambda categories, keywords, max_results: fetched)
    response = api_client.post("/api/ingest/arxiv", json={"categories": ["cs.AI"], "keywords": [], "max_results": 2})
    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["duplicate_count"] == 1

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.database import (
    add_note,
    connect,
    get_paper_detail,
    init_schema,
    list_paper_chunks,
    list_papers,
    paper_chunks_fts_ready,
    rebuild_paper_chunks_fts,
    replace_paper_chunks,
    set_favorite,
    supports_fts5,
    upsert_paper,
)
from backend.app.main import app
from backend.app.seed_data import seed_database
from backend.app.services import fulltext, search as search_module
from backend.app.services.agents import process_paper
from backend.app.services.fulltext import FullTextDocument, chunk_document
from backend.app.services.search import answer_question, build_graph, search_wiki


def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    seed_database(conn)
    return conn


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.sqlite3"))
    monkeypatch.setenv("ENABLE_MOCK_LLM", "true")
    get_settings.cache_clear()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def test_seed_has_at_least_100_papers():
    conn = memory_db()
    count = conn.execute("SELECT COUNT(*) AS count FROM papers").fetchone()["count"]
    assert count >= 100


def test_seed_backfills_processed_paper_chunks():
    conn = memory_db()
    processed = conn.execute("SELECT COUNT(*) AS count FROM papers WHERE processing_status = 'processed'").fetchone()["count"]
    chunks = conn.execute("SELECT COUNT(DISTINCT paper_id) AS count FROM paper_chunks").fetchone()["count"]
    assert chunks == processed


def test_schema_creates_paper_chunks_table():
    conn = memory_db()
    row = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'paper_chunks'").fetchone()
    assert row is not None


def test_schema_creates_paper_chunks_fts_table_when_supported():
    conn = memory_db()
    if not supports_fts5(conn):
        pytest.skip("SQLite FTS5 is not available")
    assert paper_chunks_fts_ready(conn)


def test_schema_without_fts5_still_supports_search(monkeypatch):
    from backend.app import database as database_module

    monkeypatch.setattr(database_module, "supports_fts5", lambda conn: False)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    database_module.init_schema(conn)
    seed_database(conn)

    assert not paper_chunks_fts_ready(conn)
    assert search_wiki(conn, "RAG Evidence Grounding", limit=5)


def test_seed_backfills_processed_paper_chunks_fts():
    conn = memory_db()
    if not paper_chunks_fts_ready(conn):
        pytest.skip("SQLite FTS5 is not available")
    chunks = conn.execute("SELECT COUNT(*) AS count FROM paper_chunks").fetchone()["count"]
    fts_rows = conn.execute("SELECT COUNT(*) AS count FROM paper_chunks_fts").fetchone()["count"]
    assert fts_rows == chunks


def test_rebuild_paper_chunks_fts_indexes_existing_chunks():
    conn = memory_db()
    if not paper_chunks_fts_ready(conn):
        pytest.skip("SQLite FTS5 is not available")
    conn.execute("DELETE FROM paper_chunks_fts")
    assert conn.execute("SELECT COUNT(*) AS count FROM paper_chunks_fts").fetchone()["count"] == 0

    assert rebuild_paper_chunks_fts(conn) is True
    chunks = conn.execute("SELECT COUNT(*) AS count FROM paper_chunks").fetchone()["count"]
    fts_rows = conn.execute("SELECT COUNT(*) AS count FROM paper_chunks_fts").fetchone()["count"]
    assert fts_rows == chunks


def test_chunk_document_preserves_order_offsets_and_overlap():
    text = " ".join(f"token-{index}" for index in range(90))
    document = FullTextDocument(source_type="metadata", source_url="https://arxiv.org/abs/1", text=text)
    chunks = chunk_document(document, max_chars=120, overlap=24)

    assert len(chunks) > 1
    assert [chunk["chunk_index"] for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk["char_start"] < chunk["char_end"] for chunk in chunks)
    assert chunks[1]["char_start"] < chunks[0]["char_end"]
    assert chunks[0]["content"] == text[chunks[0]["char_start"] : chunks[0]["char_end"]]


def test_fulltext_fetch_failure_falls_back_to_metadata(monkeypatch):
    monkeypatch.setenv("ENABLE_FULLTEXT_FETCH", "true")
    get_settings.cache_clear()

    def failed_urlopen(*args, **kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(fulltext, "urlopen", failed_urlopen)
    conn = memory_db()
    paper_id = conn.execute("SELECT id FROM papers LIMIT 1").fetchone()["id"]
    paper = get_paper_detail(conn, paper_id)
    chunks = fulltext.chunks_for_paper(paper)

    assert chunks
    assert chunks[0]["source_type"] == "metadata"
    assert paper["title"] in chunks[0]["content"]
    get_settings.cache_clear()


def test_list_papers_filters_by_category_and_keyword():
    conn = memory_db()
    papers = list_papers(conn, q="RAG", category="cs.CL", limit=20)
    assert papers
    assert all("cs.CL" in paper["categories"] for paper in papers)


def test_process_paper_generates_required_wiki_sections():
    conn = memory_db()
    pending = conn.execute("SELECT id FROM papers WHERE processing_status = 'pending' LIMIT 1").fetchone()["id"]
    result = process_paper(conn, pending)
    assert result["status"] == "processed"
    detail = get_paper_detail(conn, pending)
    assert {section["section"] for section in detail["wiki"]} >= {"summary", "concepts", "methods", "experiments"}
    assert detail["chunk_count"] >= 1
    chunks, count = list_paper_chunks(conn, pending)
    assert count >= 1
    assert chunks[0]["source_type"] == "metadata"
    assert detail["title"] in chunks[0]["content"]


def test_replace_paper_chunks_removes_stale_rows():
    conn = memory_db()
    paper_id = conn.execute("SELECT id FROM papers LIMIT 1").fetchone()["id"]
    replace_paper_chunks(
        conn,
        paper_id,
        [
            {"chunk_index": 0, "source_type": "metadata", "content": "first chunk", "token_count": 2},
            {"chunk_index": 1, "source_type": "metadata", "content": "stale chunk", "token_count": 2},
        ],
    )
    replace_paper_chunks(
        conn,
        paper_id,
        [{"chunk_index": 0, "source_type": "metadata", "content": "replacement chunk", "token_count": 2}],
    )
    chunks, count = list_paper_chunks(conn, paper_id)
    assert count == 1
    assert chunks[0]["content"] == "replacement chunk"


def test_replace_paper_chunks_syncs_fts_rows():
    conn = memory_db()
    if not paper_chunks_fts_ready(conn):
        pytest.skip("SQLite FTS5 is not available")
    paper_id = conn.execute("SELECT id FROM papers LIMIT 1").fetchone()["id"]
    replace_paper_chunks(
        conn,
        paper_id,
        [{"chunk_index": 0, "source_type": "metadata", "content": "iter03stale chunk", "token_count": 2}],
    )
    replace_paper_chunks(
        conn,
        paper_id,
        [{"chunk_index": 0, "source_type": "metadata", "content": "iter03replacement chunk", "token_count": 2}],
    )

    stale = conn.execute(
        "SELECT COUNT(*) AS count FROM paper_chunks_fts WHERE paper_chunks_fts MATCH ?",
        ('"iter03stale"',),
    ).fetchone()["count"]
    replacement = conn.execute(
        "SELECT rowid, chunk_id FROM paper_chunks_fts WHERE paper_chunks_fts MATCH ?",
        ('"iter03replacement"',),
    ).fetchall()

    assert stale == 0
    assert replacement
    assert replacement[0]["rowid"] == replacement[0]["chunk_id"]


def test_replace_paper_chunks_falls_back_when_fts_sync_fails(monkeypatch):
    from backend.app import database as database_module

    conn = memory_db()
    if not paper_chunks_fts_ready(conn):
        pytest.skip("SQLite FTS5 is not available")
    paper_id = conn.execute("SELECT id FROM papers LIMIT 1").fetchone()["id"]

    def failed_fts_insert(conn, row):
        raise sqlite3.OperationalError("simulated fts failure")

    monkeypatch.setattr(database_module, "insert_paper_chunk_fts_row", failed_fts_insert)
    replace_paper_chunks(
        conn,
        paper_id,
        [{"chunk_index": 0, "source_type": "metadata", "content": "iter03fallback chunk", "token_count": 2}],
    )

    chunks, count = list_paper_chunks(conn, paper_id)
    assert count == 1
    assert chunks[0]["content"] == "iter03fallback chunk"
    assert not paper_chunks_fts_ready(conn)
    assert search_wiki(conn, "iter03fallback", limit=3)[0]["source"] == "chunk"


def test_delete_paper_cascades_chunk_fts_rows():
    conn = memory_db()
    if not paper_chunks_fts_ready(conn):
        pytest.skip("SQLite FTS5 is not available")
    paper_id = conn.execute("SELECT paper_id FROM paper_chunks LIMIT 1").fetchone()["paper_id"]
    assert conn.execute("SELECT COUNT(*) AS count FROM paper_chunks_fts WHERE paper_id = ?", (paper_id,)).fetchone()["count"] >= 1

    conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
    conn.commit()

    assert conn.execute("SELECT COUNT(*) AS count FROM paper_chunks_fts WHERE paper_id = ?", (paper_id,)).fetchone()["count"] == 0


def test_search_and_qa_return_citations():
    conn = memory_db()
    conn.execute("DELETE FROM paper_chunks")
    conn.commit()
    results = search_wiki(conn, "RAG Evidence Grounding", limit=5)
    assert results
    assert all(result["source"] == "wiki" for result in results)
    answer = answer_question(conn, "RAG 如何保证答案有出处？")
    assert answer["citations"]
    assert "出处" in answer["answer"] or "论文 Wiki" in answer["answer"]


def test_search_and_qa_prefer_chunk_citations_after_processing():
    conn = memory_db()
    paper_id = conn.execute("SELECT id FROM papers WHERE processing_status = 'pending' LIMIT 1").fetchone()["id"]
    detail = get_paper_detail(conn, paper_id)
    process_paper(conn, paper_id)

    results = search_wiki(conn, detail["title"], limit=5)
    assert results[0]["source"] == "chunk"
    assert results[0]["chunk_id"]
    assert results[0]["section_title"].startswith("Metadata")

    answer = answer_question(conn, detail["title"], paper_ids=[paper_id])
    assert answer["citations"]
    assert answer["citations"][0]["source"] == "chunk"


def test_search_and_qa_keep_paper_scope_with_fts_candidates():
    conn = memory_db()
    target_id = conn.execute("SELECT id FROM papers ORDER BY id LIMIT 1").fetchone()["id"]
    other_ids = [
        row["id"]
        for row in conn.execute("SELECT id FROM papers WHERE id != ? ORDER BY id LIMIT 30", (target_id,)).fetchall()
    ]
    for paper_id in other_ids:
        replace_paper_chunks(
            conn,
            paper_id,
            [{"chunk_index": 0, "source_type": "metadata", "content": f"iter03scoped popular other {paper_id}", "token_count": 4}],
            commit=False,
        )
    replace_paper_chunks(
        conn,
        target_id,
        [{"chunk_index": 0, "source_type": "metadata", "content": "iter03scoped target evidence", "token_count": 4}],
        commit=False,
    )
    conn.commit()
    if paper_chunks_fts_ready(conn):
        candidate_ids = search_module._fts_chunk_candidate_ids(
            conn,
            "iter03scoped target evidence",
            limit=1,
            paper_ids=[target_id],
        )
        assert candidate_ids
        candidate_paper_ids = {
            row["paper_id"]
            for row in conn.execute(
                "SELECT paper_id FROM paper_chunks WHERE id IN ({})".format(",".join("?" for _ in candidate_ids)),
                tuple(candidate_ids),
            ).fetchall()
        }
        assert candidate_paper_ids == {target_id}

    results = search_wiki(conn, "iter03scoped target evidence", limit=5, paper_ids=[target_id])
    assert results
    assert all(result["paper_id"] == target_id for result in results)
    assert results[0]["source"] == "chunk"

    answer = answer_question(conn, "iter03scoped target evidence", paper_ids=[target_id])
    assert answer["citations"]
    assert answer["citations"][0]["paper_id"] == target_id
    assert answer["citations"][0]["source"] == "chunk"


def test_search_handles_special_fts_queries():
    conn = memory_db()
    paper_id = conn.execute("SELECT id FROM papers LIMIT 1").fetchone()["id"]
    replace_paper_chunks(
        conn,
        paper_id,
        [
            {
                "chunk_index": 0,
                "source_type": "metadata",
                "content": "iter03special C++ gpt-4o-mini 图神经网络 知识图谱",
                "token_count": 6,
            }
        ],
    )

    cxx_results = search_wiki(conn, 'C++ gpt-4o-mini "RAG"', limit=5)
    assert cxx_results[0]["source"] == "chunk"
    assert cxx_results[0]["paper_id"] == paper_id

    chinese_results = search_wiki(conn, "图神经网络(知识图谱)", limit=5)
    assert chinese_results[0]["source"] == "chunk"
    assert chinese_results[0]["paper_id"] == paper_id

    assert isinstance(search_wiki(conn, "", limit=5), list)
    if paper_chunks_fts_ready(conn):
        no_match_results = search_wiki(conn, "definitely-no-such-topic-xyz", limit=5)
        assert all(result["source"] != "chunk" for result in no_match_results)


def test_upsert_paper_updates_title_hash_for_title_deduplication():
    conn = memory_db()
    paper = {
        "arxiv_id": "2699.20001",
        "title": "iter03 Original Title",
        "authors": ["Ada A."],
        "abstract": "Initial title.",
        "categories": ["cs.AI"],
        "primary_category": "cs.AI",
        "published_at": "2026-07-09",
        "updated_at": "2026-07-09",
        "pdf_url": "https://arxiv.org/pdf/2699.20001",
        "arxiv_url": "https://arxiv.org/abs/2699.20001",
    }
    first_id = upsert_paper(conn, paper)
    updated_id = upsert_paper(conn, {**paper, "title": "iter03 Updated Title", "abstract": "Updated title."})
    duplicate_title_id = upsert_paper(conn, {**paper, "arxiv_id": "2699.20002", "title": "iter03 Updated Title"})

    assert updated_id == first_id
    assert duplicate_title_id == first_id


def test_favorite_note_history_flow():
    conn = memory_db()
    paper_id = conn.execute("SELECT id FROM papers LIMIT 1").fetchone()["id"]
    detail = set_favorite(conn, paper_id, True)
    assert detail["is_favorite"] is True
    note = add_note(conn, paper_id, "这篇适合和知识图谱论文对比。", "关注方法章节")
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
    graph = build_graph(conn, topic="definitely-no-such-topic-xyz")
    assert graph == {"nodes": [], "links": []}


def test_upsert_paper_deduplicates_same_title_different_arxiv_id():
    conn = memory_db()
    paper = {
        "arxiv_id": "2699.00001",
        "title": "A Stable Duplicate Title For iter01",
        "authors": ["Ada A."],
        "abstract": "A duplicate title should map to one paper record.",
        "categories": ["cs.AI"],
        "primary_category": "cs.AI",
        "published_at": "2026-07-09",
        "updated_at": "2026-07-09",
        "pdf_url": "https://arxiv.org/pdf/2699.00001",
        "arxiv_url": "https://arxiv.org/abs/2699.00001",
    }
    first_id = upsert_paper(conn, paper)
    second_id = upsert_paper(conn, {**paper, "arxiv_id": "2699.00002"})
    assert second_id == first_id


def test_api_favorite_missing_paper_returns_404(api_client):
    response = api_client.post("/api/library/favorites", json={"paper_id": 999_999, "favorite": True})
    assert response.status_code == 404


def test_api_process_validation_failure_returns_422(api_client, monkeypatch):
    paper_id = api_client.get("/api/papers?limit=1").json()["items"][0]["id"]

    def failed_process(conn, paper_id):
        return {"status": "failed", "errors": ["缺少 Wiki 分区：summary"], "agents": ["ValidatorAgent"]}

    monkeypatch.setattr("backend.app.main.process_paper", failed_process)
    response = api_client.post(f"/api/papers/{paper_id}/process")
    assert response.status_code == 422
    assert response.json()["status"] == "failed"
    assert response.json()["errors"]


def test_api_ingest_reports_duplicate_count(api_client, monkeypatch):
    duplicate_title = "iter01 Duplicate arXiv Title"
    fetched = [
        {
            "arxiv_id": "2699.10001",
            "title": duplicate_title,
            "authors": ["Ada A."],
            "abstract": "First fetched duplicate.",
            "categories": ["cs.AI"],
            "primary_category": "cs.AI",
            "published_at": "2026-07-09",
            "updated_at": "2026-07-09",
            "pdf_url": "https://arxiv.org/pdf/2699.10001",
            "arxiv_url": "https://arxiv.org/abs/2699.10001",
        },
        {
            "arxiv_id": "2699.10002",
            "title": duplicate_title,
            "authors": ["Ada B."],
            "abstract": "Second fetched duplicate.",
            "categories": ["cs.AI"],
            "primary_category": "cs.AI",
            "published_at": "2026-07-09",
            "updated_at": "2026-07-09",
            "pdf_url": "https://arxiv.org/pdf/2699.10002",
            "arxiv_url": "https://arxiv.org/abs/2699.10002",
        },
    ]
    monkeypatch.setattr("backend.app.main.fetch_arxiv_papers", lambda categories, keywords, max_results: fetched)

    response = api_client.post("/api/ingest/arxiv", json={"categories": ["cs.AI"], "keywords": [], "max_results": 2})
    assert response.status_code == 200
    data = response.json()
    assert data["fetched_count"] == 2
    assert data["duplicate_count"] == 1
    assert data["count"] == 1
    assert len(data["paper_ids"]) == 1


def test_api_paper_chunks_pagination_and_missing_paper(api_client):
    paper_id = api_client.get("/api/papers?limit=1").json()["items"][0]["id"]
    with connect() as conn:
        replace_paper_chunks(
            conn,
            paper_id,
            [
                {"chunk_index": 0, "source_type": "metadata", "content": "first api chunk", "token_count": 3},
                {"chunk_index": 1, "source_type": "metadata", "content": "second api chunk", "token_count": 3},
            ],
        )

    response = api_client.get(f"/api/papers/{paper_id}/chunks?limit=1&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 1
    assert len(data["items"]) == 1
    assert data["items"][0]["chunk_index"] == 0
    assert data["items"][0]["source_type"] == "metadata"

    second_page = api_client.get(f"/api/papers/{paper_id}/chunks?limit=1&offset=1")
    assert second_page.status_code == 200
    second_data = second_page.json()
    assert second_data["count"] == 2
    assert second_data["items"][0]["chunk_index"] == 1
    assert second_data["items"][0]["content"] == "second api chunk"

    missing = api_client.get("/api/papers/999999/chunks")
    assert missing.status_code == 404


def test_api_search_and_qa_keep_chunk_citation_shape(api_client):
    response = api_client.get("/api/wiki/search?q=RAG&limit=8")
    assert response.status_code == 200
    chunk = next(item for item in response.json()["items"] if item.get("source") == "chunk")
    for field in ["id", "chunk_id", "source", "source_type", "chunk_index", "char_start", "char_end", "token_count"]:
        assert field in chunk

    qa_response = api_client.post("/api/qa", json={"question": "RAG", "paper_ids": []})
    assert qa_response.status_code == 200
    citation = next(item for item in qa_response.json()["citations"] if item.get("source") == "chunk")
    for field in ["id", "chunk_id", "source", "source_type", "chunk_index", "char_start", "char_end", "token_count"]:
        assert field in citation


def test_api_unknown_graph_topic_returns_empty(api_client):
    response = api_client.get("/api/graph?topic=definitely-no-such-topic-xyz&limit=42")
    assert response.status_code == 200
    assert response.json() == {"nodes": [], "links": []}


def test_api_subscriptions_list_and_create(api_client):
    initial = api_client.get("/api/subscriptions")
    assert initial.status_code == 200
    response = api_client.post("/api/subscriptions", json={"topic": "可信 RAG"})
    assert response.status_code == 200
    assert response.json()["topic"] == "可信 RAG"
    topics = [item["topic"] for item in api_client.get("/api/subscriptions").json()["items"]]
    assert "可信 RAG" in topics


def test_seed_qa_citation_accuracy_baseline():
    conn = memory_db()
    cases = [
        ("RAG Evidence Grounding", "RAG"),
        ("Multi-Agent Evidence Grounding", "Multi-Agent"),
        ("Long Context Evidence Grounding", "Long Context"),
        ("Graph Neural Network Evidence Grounding", "Graph Neural Network"),
        ("Domain Adaptation Evidence Grounding", "Domain Adaptation"),
        ("Safe RL Evidence Grounding", "Safe RL"),
        ("Code LLM Evidence Grounding", "Code LLM"),
        ("Multimodal Learning Evidence Grounding", "Multimodal Learning"),
        ("Federated Learning Evidence Grounding", "Federated Learning"),
        ("Causal Discovery Evidence Grounding", "Causal Discovery"),
    ]
    hits = 0
    grounded_answers = 0
    for question, expected in cases:
        result = answer_question(conn, question)
        combined_citations = " ".join(item["content"] + " " + item["paper_title"] for item in result["citations"]).lower()
        if expected.lower() in combined_citations:
            hits += 1
        if result["citations"] and ("出处" in result["answer"] or "论文" in result["answer"]):
            grounded_answers += 1

    assert hits / len(cases) >= 0.9
    assert grounded_answers / len(cases) >= 0.9

from __future__ import annotations

import sqlite3
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from backend.app.config import get_settings
from backend.app.database import add_note, connect, get_paper_detail, init_db, init_schema, list_papers, set_favorite, upsert_paper
from backend.app.main import app
from backend.app.services.agents import SummaryAgent, process_paper
from backend.app.services.sources.common import MetadataPage
from backend.app.services.sources.sigops import SigopsAcceptedPapersParser, SigopsTocParser
from backend.app.services.sources.usenix import _detail_to_paper
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
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
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
    data = response.json()
    assert data["fetched_count"] == 2
    assert data["duplicate_count"] == 1
    assert data["count"] == 1
    assert len(data["paper_ids"]) == 1


def test_sigops_toc_parser_reads_title_authors_and_abstract():
    parser = SigopsTocParser()
    parser.feed(
        '<h3><a href="https://dl.acm.org/doi/10.1145/example">A Systems Paper</a></h3>'
        '<ul><li>Ada Lovelace</li><li>Grace Hopper</li></ul>'
        '<p>A concise abstract from the official proceedings page.</p>'
    )
    parser.close()
    assert parser.papers == [
        {
            "title": "A Systems Paper",
            "url": "https://dl.acm.org/doi/10.1145/example",
            "authors": ["Ada Lovelace", "Grace Hopper"],
            "abstract": "A concise abstract from the official proceedings page.",
        }
    ]


def test_sigops_accepted_papers_parser_reads_recent_sosp_list():
    parser = SigopsAcceptedPapersParser()
    parser.feed(
        '<ul class="paperlist">'
        '<li><b>A Recent SOSP Paper</b><br><em>Ada Lovelace, Grace Hopper</em></li>'
        '<li><b>Another SOSP Paper</b><br><em>Linus Torvalds</em></li>'
        '</ul>'
    )
    parser.close()
    assert parser.papers == [
        {
            "title": "A Recent SOSP Paper",
            "url": "",
            "authors": ["Ada Lovelace", "Grace Hopper"],
            "abstract": "",
        },
        {
            "title": "Another SOSP Paper",
            "url": "",
            "authors": ["Linus Torvalds"],
            "abstract": "",
        },
    ]


def test_usenix_detail_normalizes_citation_metadata():
    page = MetadataPage()
    page.feed(
        '<meta name="citation_title" content="A USENIX Paper">'
        '<meta name="citation_author" content="Ada Lovelace">'
        '<meta name="citation_abstract" content="An extracted abstract.">'
        '<meta name="citation_pdf_url" content="https://example.test/paper.pdf">'
    )
    paper = _detail_to_paper(page, "https://www.usenix.org/conference/osdi24/presentation/example", "OSDI", 2024)
    assert paper is not None
    assert paper["source"] == "usenix"
    assert paper["title"] == "A USENIX Paper"
    assert paper["pdf_url"] == "https://example.test/paper.pdf"


def test_usenix_detail_removes_bibtex_title_braces():
    page = MetadataPage()
    page.feed('<pre>@inproceedings {1, title = {A {Hardware-Accelerated} System}, author = {Ada and Grace}}</pre>')
    paper = _detail_to_paper(page, "https://www.usenix.org/conference/osdi24/presentation/example", "OSDI", 2024)
    assert paper is not None
    assert paper["title"] == "A Hardware-Accelerated System"


def test_api_ingests_usenix_source(api_client, monkeypatch):
    monkeypatch.setattr(
        "backend.app.main.fetch_usenix_papers",
        lambda venue, year, max_results: [
            {
                "arxiv_id": "usenix:osdi:2024:demo",
                "source": "usenix",
                "source_url": "https://example.test/osdi-demo",
                "venue": "OSDI 2024",
                "title": "USENIX import demo",
                "authors": ["Ada"],
                "abstract": "Imported from a mocked USENIX page.",
                "categories": ["systems"],
                "primary_category": "systems",
                "published_at": "2024-01-01",
            }
        ],
    )
    response = api_client.post("/api/ingest/usenix", json={"venue": "osdi", "year": 2024, "max_results": 1})
    assert response.status_code == 200
    assert response.json()["count"] == 1
    paper = api_client.get("/api/papers?q=USENIX%20import%20demo").json()["items"][0]
    assert paper["source"] == "usenix"
    assert paper["venue"] == "OSDI 2024"


def test_api_upload_records_local_pdf(api_client, monkeypatch):
    monkeypatch.setattr(
        "backend.app.main.save_and_extract_pdf",
        lambda file, upload_dir: SimpleNamespace(path="demo.pdf", title="Extracted PDF title", text="Extracted PDF text."),
    )
    response = api_client.post(
        "/api/papers/upload",
        files={"file": ("demo.pdf", b"%PDF-1.4 mock", "application/pdf")},
        data={"authors": "Ada, Grace", "year": "2025"},
    )
    assert response.status_code == 200
    paper = response.json()
    assert paper["source"] == "upload"
    assert paper["file_url"] == f"/api/papers/{paper['id']}/file"
    assert paper["authors"] == ["Ada", "Grace"]


def test_api_upload_and_download_real_pdf(api_client):
    payload = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "Real PDF upload"})
    writer.write(payload)
    response = api_client.post(
        "/api/papers/upload",
        files={"file": ("real.pdf", payload.getvalue(), "application/pdf")},
        data={"year": "2025"},
    )
    assert response.status_code == 200
    paper = response.json()
    assert paper["title"] == "Real PDF upload"
    download = api_client.get(paper["file_url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF-")


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


def test_library_folder_recommendation_requires_user_approval(api_client, monkeypatch):
    paper_id = api_client.get("/api/papers?limit=1").json()["items"][0]["id"]
    saved = api_client.post("/api/library/favorites", json={"paper_id": paper_id, "favorite": True})
    assert saved.status_code == 200

    folders = api_client.get("/api/library/folders").json()["items"]
    root = next(folder for folder in folders if folder["is_root"])
    inbox = next(folder for folder in folders if folder["name"] == "待整理")
    created = api_client.post(
        "/api/library/folders",
        json={"name": "可信 RAG", "parent_id": root["id"], "description": "检索增强与证据引用"},
    ).json()
    item = api_client.get(f"/api/library/items?folder_id={inbox['id']}").json()["items"][0]

    monkeypatch.setattr(
        "backend.app.services.library.LLMClient.complete",
        lambda self, system_prompt, user_prompt, json_mode=False: (
            f'{{"folder_id": {created["id"]}, "reason": "论文研究证据增强检索。"}}'
        ),
    )
    recommendation = api_client.post(f"/api/library/items/{item['library_item_id']}/recommend-folder")
    assert recommendation.status_code == 200
    assert recommendation.json()["folder_id"] == created["id"]

    unchanged = api_client.get(f"/api/library/items?folder_id={inbox['id']}").json()["items"]
    assert [entry["library_item_id"] for entry in unchanged] == [item["library_item_id"]]

    moved = api_client.post(
        f"/api/library/items/{item['library_item_id']}/move",
        json={"folder_id": created["id"]},
    )
    assert moved.status_code == 200
    assert moved.json()["folder_id"] == created["id"]
    assert api_client.get(f"/api/library/items?folder_id={inbox['id']}").json()["items"] == []


def test_library_favorites_are_isolated_by_user_header(api_client):
    paper_id = api_client.get("/api/papers?limit=1").json()["items"][0]["id"]
    response = api_client.post(
        "/api/library/favorites",
        headers={"X-User-ID": "2"},
        json={"paper_id": paper_id, "favorite": True},
    )
    assert response.status_code == 200
    assert response.json()["is_favorite"] is True
    assert api_client.get("/api/library/items").json()["items"] == []
    user_two_items = api_client.get("/api/library/items", headers={"X-User-ID": "2"}).json()["items"]
    assert [item["id"] for item in user_two_items] == [paper_id]


def test_library_schema_does_not_store_last_recommendation():
    conn = memory_db()
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(library_items)").fetchall()}
    assert "last_recommended_folder_id" not in columns

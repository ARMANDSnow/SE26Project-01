import sqlite3
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from backend.app.config import get_settings
from backend.app.database import add_note, get_paper_detail, init_schema, list_papers, set_favorite, upsert_paper
from backend.app.main import app
from backend.app.seed_data import seed_database
from backend.app.services.agents import process_paper
from backend.app.services.sources.common import MetadataPage
from backend.app.services.sources.sigops import SigopsTocParser
from backend.app.services.sources.usenix import _detail_to_paper
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
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("ENABLE_MOCK_LLM", "true")
    get_settings.cache_clear()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def test_seed_has_at_least_100_papers():
    conn = memory_db()
    count = conn.execute("SELECT COUNT(*) AS count FROM papers").fetchone()["count"]
    assert count >= 100


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


def test_search_and_qa_return_citations():
    conn = memory_db()
    results = search_wiki(conn, "RAG Evidence Grounding", limit=5)
    assert results
    answer = answer_question(conn, "RAG 如何保证答案有出处？")
    assert answer["citations"]
    assert "出处" in answer["answer"] or "论文 Wiki" in answer["answer"]


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

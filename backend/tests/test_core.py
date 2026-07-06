import sqlite3

from backend.app.database import add_note, get_paper_detail, init_schema, list_papers, set_favorite
from backend.app.seed_data import seed_database
from backend.app.services.agents import process_paper
from backend.app.services.search import answer_question, build_graph, search_wiki


def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    seed_database(conn)
    return conn


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


def test_graph_has_nodes_and_links():
    conn = memory_db()
    graph = build_graph(conn, topic="RAG")
    assert graph["nodes"]
    assert graph["links"]

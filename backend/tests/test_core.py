from __future__ import annotations

import json
import sqlite3
from io import BytesIO
from types import SimpleNamespace
from urllib.request import Request

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from backend.app.auth.session import MemorySessionStore
from backend.app.config import get_settings
from backend.app.database import (
    SCHEMA_VERSION,
    IncompatibleSchemaError,
    add_note,
    attach_concepts,
    connect,
    get_paper_detail,
    init_db,
    init_schema,
    list_paper_chunks,
    list_papers,
    replace_wiki_sections,
    set_favorite,
    set_paper_asset_id,
    upsert_paper,
)
from backend.app.db.migrations import (
    Migration,
    MigrationError,
    V3_MIGRATION,
    V4_MIGRATION,
    V5_MIGRATION,
    V6_MIGRATION,
    apply_migrations,
)
from backend.app.main import app
from backend.app.models import AssetId, AssetInfo, PaperCandidate, PaperSource
from backend.app.repositories.uploads import paper_is_accessible
from backend.app.repositories.research import (
    ResearchConflictError,
    claim_next_step,
    create_harness_run,
    fail_step,
    finish_step,
    get_run_snapshot,
    heartbeat_step,
    request_action,
    recover_expired_leases,
    reconcile_requested_actions,
    resolve_decision,
    retry_run,
)
from backend.app.services.agents import SummaryAgent, process_paper
from backend.app.services.asset_store import LocalAssetStore
from backend.app.services.sources.common import MetadataPage
from backend.app.services.sources.sigops import (
    SigopsAcceptedPapersParser,
    SigopsTocParser,
    _match_candidate,
    _schedule_candidates,
    fetch_sigops_papers,
)
from backend.app.services.http_safety import UnsafeUrlError, _TrustedRedirectHandler
from backend.app.services.paper_tools import PaperToolbox
from backend.app.services.research_tools import _arxiv_discovery_terms
from backend.app.services.research import ResearchExecutor
from backend.app.services.sources.arxiv import build_query
from backend.app.services.sources.usenix import _detail_to_paper
from backend.app.services.search import answer_question, build_graph, search_wiki
from backend.app.services.conversations import (
    build_model_messages,
    create_thread,
    get_message_repository,
    list_threads,
    prepare_run,
    stream_run,
)
from backend.app.services.chat_routing import (
    ChatRoutingUnavailable,
    LLMChatRouteClassifier,
    get_chat_route_classifier,
)
from backend.tests.fixtures import add_test_paper, populate_test_library


def memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    conn.execute(
        """
        INSERT INTO users(id, name, username, password_hash, is_active)
        VALUES (1, 'Test User', 'test_user', '!unit-test-only', 1)
        """
    )
    populate_test_library(conn)
    return conn


def test_topic_arxiv_discovery_uses_broad_terms_in_one_query() -> None:
    terms = _arxiv_discovery_terms(
        [
            "arXiv 2024 retrieval augmented generation citation grounding correctness",
            "arXiv RAG evidence attribution verification",
        ]
    )

    assert terms == [
        "retrieval augmented generation",
        "citation",
        "grounding",
        "correctness",
    ]
    assert build_query(["cs.CL", "cs.IR"], terms, match_any=True) == (
        '(cat:cs.CL OR cat:cs.IR) AND '
        '(all:"retrieval augmented generation" OR all:"citation" OR all:"grounding" '
        'OR all:"correctness")'
    )
    assert build_query(["cs.CL"], terms, match_any=True, require_first=True) == (
        '(cat:cs.CL) AND all:"retrieval augmented generation" AND '
        '(all:"citation" OR all:"grounding" OR all:"correctness")'
    )


def test_migration_runner_applies_contiguous_versions() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA user_version = 1")

    applied = apply_migrations(
        conn,
        [Migration(version=2, name="create probe", apply=lambda db: db.execute("CREATE TABLE probe(id INTEGER)"))],
        target_version=2,
    )

    assert applied == [2]
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'probe'").fetchone() is not None


def test_migration_runner_rejects_incomplete_chain() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA user_version = 1")

    with pytest.raises(MigrationError, match="incomplete"):
        apply_migrations(conn, [], target_version=2)


def test_memory_session_store_expires_and_deletes_sessions(monkeypatch):
    now = 1_000.0
    monkeypatch.setattr("backend.app.auth.session.time.time", lambda: now)
    store = MemorySessionStore(ttl_seconds=10)
    session_id = store.create(7)
    assert store.get(session_id).user_id == 7

    now = 1_011.0
    assert store.get(session_id) is None
    store.delete(session_id)


def test_v2_private_data_migrates_to_disabled_legacy_user() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("CREATE TABLE papers(id INTEGER PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE notes(id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL REFERENCES papers(id), note TEXT NOT NULL, comment TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE reading_history(id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL REFERENCES papers(id), action TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE subscriptions(id INTEGER PRIMARY KEY, topic TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("INSERT INTO users(id, name) VALUES (1, 'Legacy')")
    conn.execute("INSERT INTO papers(id) VALUES (10)")
    conn.execute("INSERT INTO notes(id, paper_id, note) VALUES (20, 10, 'legacy note')")
    conn.execute("INSERT INTO reading_history(id, paper_id, action) VALUES (30, 10, 'read')")
    conn.execute("INSERT INTO subscriptions(id, topic) VALUES (40, 'RAG')")
    conn.execute("PRAGMA user_version = 2")

    assert apply_migrations(conn, [V3_MIGRATION], target_version=3) == [3]
    legacy = conn.execute(
        "SELECT username, password_hash, is_active FROM users WHERE id = 1"
    ).fetchone()
    assert dict(legacy) == {
        "username": "legacy_1",
        "password_hash": "!legacy-account-has-no-password",
        "is_active": 0,
    }
    assert conn.execute("SELECT user_id FROM notes WHERE id = 20").fetchone()[0] == 1
    assert conn.execute("SELECT user_id FROM reading_history WHERE id = 30").fetchone()[0] == 1
    assert conn.execute("SELECT user_id FROM subscriptions WHERE id = 40").fetchone()[0] == 1


def test_v3_uploads_migrate_as_legacy_public_documents() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE papers(id INTEGER PRIMARY KEY, source TEXT NOT NULL)")
    conn.execute("INSERT INTO papers(id, source) VALUES (7, 'upload'), (8, 'arxiv')")
    conn.execute("PRAGMA user_version = 3")

    assert apply_migrations(conn, [V4_MIGRATION], target_version=4) == [4]
    migrated = conn.execute(
        """
        SELECT owner_user_id, visibility, provenance, moderation_status
        FROM paper_uploads WHERE paper_id = 7
        """
    ).fetchone()
    assert dict(migrated) == {
        "owner_user_id": None,
        "visibility": "public",
        "provenance": "legacy_upload",
        "moderation_status": "approved",
    }
    assert conn.execute("SELECT 1 FROM paper_uploads WHERE paper_id = 8").fetchone() is None


def test_v4_research_schema_migrates_to_v5() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE chat_threads(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id))"
    )
    conn.execute("PRAGMA user_version = 4")

    assert apply_migrations(conn, [V5_MIGRATION], target_version=5) == [5]
    run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(research_runs)")}
    step_columns = {row["name"] for row in conn.execute("PRAGMA table_info(research_steps)")}
    assert {"user_id", "requested_action", "state_version"} <= run_columns
    assert {"lease_owner", "lease_generation", "lease_expires_at"} <= step_columns
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_v5_migration_has_expected_research_tables_and_rolls_back_on_failure() -> None:
    migrated = sqlite3.connect(":memory:")
    migrated.row_factory = sqlite3.Row
    migrated.execute("PRAGMA foreign_keys = ON")
    migrated.execute("CREATE TABLE users(id INTEGER PRIMARY KEY)")
    migrated.execute(
        "CREATE TABLE chat_threads(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id))"
    )
    migrated.execute("PRAGMA user_version = 4")
    apply_migrations(migrated, [V5_MIGRATION], target_version=5)

    assert {row[1] for row in migrated.execute("PRAGMA table_info(research_runs)")} >= {
        "id", "user_id", "thread_id", "mode", "status", "requested_action", "state_version", "budget_json", "usage_json",
    }
    assert {row[1] for row in migrated.execute("PRAGMA table_info(research_steps)")} >= {
        "id", "run_id", "step_key", "depends_on_json", "idempotency_key", "lease_owner", "lease_generation", "lease_expires_at",
    }
    assert {row[1] for row in migrated.execute("PRAGMA table_info(research_events)")} >= {"id", "run_id", "step_id", "event_type", "payload_json"}
    assert {row[1] for row in migrated.execute("PRAGMA table_info(research_decisions)")} >= {"id", "run_id", "step_id", "options_json", "answer_json"}
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []

    rollback = sqlite3.connect(":memory:")
    rollback.execute("CREATE TABLE users(id INTEGER PRIMARY KEY)")
    rollback.execute("CREATE TABLE chat_threads(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL)")
    rollback.execute("PRAGMA user_version = 4")

    def fail_v6(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE must_rollback(id INTEGER)")
        raise RuntimeError("injected migration failure")

    with pytest.raises(RuntimeError, match="injected"):
        apply_migrations(
            rollback,
            [V5_MIGRATION, Migration(version=6, name="fail", apply=fail_v6)],
            target_version=6,
        )
    assert rollback.execute("PRAGMA user_version").fetchone()[0] == 4
    assert rollback.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'research_runs'"
    ).fetchone() is None
    assert rollback.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'must_rollback'"
    ).fetchone() is None


def test_v5_chat_messages_migrate_to_v6_content_parts_and_roll_back() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE chat_messages(
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL DEFAULT ''
        )
        """
    )
    values = [("plain", "hello"), ("unicode", "论文\n引号：\"RAG\""), ("empty", "")]
    conn.executemany("INSERT INTO chat_messages(id, content) VALUES (?, ?)", values)
    conn.execute("PRAGMA user_version = 5")

    assert apply_migrations(conn, [V6_MIGRATION], target_version=6) == [6]
    migrated = {
        row["id"]: json.loads(row["content_parts_json"])
        for row in conn.execute("SELECT id, content_parts_json FROM chat_messages")
    }
    assert migrated == {
        message_id: [{"type": "text", "text": content}]
        for message_id, content in values
    }

    fresh = sqlite3.connect(":memory:")
    fresh.row_factory = sqlite3.Row
    init_schema(fresh)
    full_legacy = sqlite3.connect(":memory:")
    full_legacy.row_factory = sqlite3.Row
    full_legacy.execute("CREATE TABLE chat_threads(id TEXT PRIMARY KEY)")
    full_legacy.execute(
        """
        CREATE TABLE chat_messages (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
            parent_id TEXT REFERENCES chat_messages(id),
            source_message_id TEXT REFERENCES chat_messages(id),
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
            content TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'complete',
            token_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        )
        """
    )
    full_legacy.execute("PRAGMA user_version = 5")
    apply_migrations(full_legacy, [V6_MIGRATION], target_version=6)
    assert [tuple(row) for row in full_legacy.execute("PRAGMA table_info(chat_messages)")] == [
        tuple(row) for row in fresh.execute("PRAGMA table_info(chat_messages)")
    ]

    rollback = sqlite3.connect(":memory:")
    rollback.row_factory = sqlite3.Row
    rollback.execute("CREATE TABLE chat_messages(id TEXT PRIMARY KEY, content TEXT NOT NULL)")
    rollback.execute("INSERT INTO chat_messages VALUES ('one', 'before')")
    rollback.execute("PRAGMA user_version = 5")

    def fail_v7(db: sqlite3.Connection) -> None:
        db.execute("CREATE TABLE must_rollback_v7(id INTEGER)")
        raise RuntimeError("injected v7 failure")

    with pytest.raises(RuntimeError, match="injected v7"):
        apply_migrations(
            rollback,
            [V6_MIGRATION, Migration(version=7, name="fail", apply=fail_v7)],
            target_version=7,
        )
    assert rollback.execute("PRAGMA user_version").fetchone()[0] == 5
    assert "content_parts_json" not in {
        row["name"] for row in rollback.execute("PRAGMA table_info(chat_messages)")
    }


def test_init_schema_rejects_forged_v6_without_content_parts() -> None:
    conn = memory_db()
    conn.execute("ALTER TABLE chat_messages DROP COLUMN content_parts_json")

    with pytest.raises(IncompatibleSchemaError, match="chat message schema"):
        init_schema(conn)


def test_upload_without_visibility_metadata_is_hidden_by_default() -> None:
    with memory_db() as conn:
        paper_id = upsert_paper(
            conn,
            PaperCandidate(
                source=PaperSource.UPLOAD,
                source_id="orphan-upload",
                title="Orphan upload",
                authors=(),
                abstract="Must not become public without access metadata.",
                categories=("manual",),
                primary_category="manual",
                published_at="2025-01-01",
            ),
        )

        assert paper_is_accessible(conn, paper_id, user_id=1) is False


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.sqlite3"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()
    with TestClient(app) as client:
        registered = client.post(
            "/api/auth/register",
            json={"username": "test_user", "password": "test-password"},
        )
        assert registered.status_code == 201
        with connect() as conn:
            populate_test_library(conn)
        yield client
    get_settings.cache_clear()


def test_init_db_does_not_create_demo_papers(tmp_path):
    path = tmp_path / "empty.sqlite3"
    init_db(path)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0


def test_business_api_requires_session_but_health_is_public(api_client):
    logged_out = api_client.post("/api/auth/logout")
    assert logged_out.status_code == 200
    assert api_client.get("/api/health").status_code == 200
    assert api_client.get("/api/papers").status_code == 401
    assert api_client.get("/api/stats").status_code == 401


def test_registration_hashes_password_and_login_rotates_session(api_client):
    api_client.post("/api/auth/logout")
    registered = api_client.post(
        "/api/auth/register",
        json={"username": "secure_user", "password": "correct-horse-battery"},
    )
    assert registered.status_code == 201
    first_session = api_client.cookies.get("paperwiki_session")
    assert first_session
    with connect() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = 'secure_user'"
        ).fetchone()
    assert row["password_hash"].startswith("$argon2id$")
    assert "correct-horse-battery" not in row["password_hash"]

    logged_in = api_client.post(
        "/api/auth/login",
        json={"username": "secure_user", "password": "correct-horse-battery"},
    )
    assert logged_in.status_code == 200
    second_session = api_client.cookies.get("paperwiki_session")
    assert second_session and second_session != first_session
    assert api_client.get("/api/auth/me").json()["username"] == "secure_user"
    failed_login = api_client.post(
        "/api/auth/login",
        json={"username": "secure_user", "password": "wrong-password"},
    )
    assert failed_login.status_code == 401
    assert api_client.get("/api/auth/me").json()["username"] == "secure_user"
    old_session_response = api_client.get(
        "/api/auth/me",
        headers={"Cookie": f"paperwiki_session={first_session}"},
    )
    assert old_session_response.status_code == 401


def test_login_rejects_wrong_password_without_leaking_account_state(api_client):
    api_client.post("/api/auth/logout")
    missing = api_client.post(
        "/api/auth/login",
        json={"username": "missing_user", "password": "wrong-password"},
    )
    wrong = api_client.post(
        "/api/auth/login",
        json={"username": "test_user", "password": "wrong-password"},
    )
    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json()


def test_papers_schema_uses_asset_id_without_legacy_columns():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(papers)").fetchall()}
    assert {"source", "source_id", "source_url", "pdf_url", "venue", "asset_id"} <= columns
    assert {
        "arxiv_id",
        "arxiv_url",
        "file_path",
        "doi",
        "reading_status",
        "is_favorite",
        "title_hash",
    }.isdisjoint(columns)
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'assets'").fetchone() is None
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    thread_columns = {row["name"]: row["notnull"] for row in conn.execute("PRAGMA table_info(chat_threads)")}
    assert thread_columns["paper_id"] == 0
    user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    assert {"username", "password_hash", "is_active", "updated_at"} <= user_columns
    for table in ("notes", "reading_history", "subscriptions"):
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert "user_id" in columns
    upload_columns = {row["name"] for row in conn.execute("PRAGMA table_info(paper_uploads)")}
    assert {
        "paper_id",
        "owner_user_id",
        "visibility",
        "provenance",
        "moderation_status",
        "original_filename",
    } <= upload_columns


def test_init_schema_rejects_legacy_database_with_reset_command():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE papers (id INTEGER PRIMARY KEY, arxiv_id TEXT NOT NULL)")

    with pytest.raises(IncompatibleSchemaError, match="reset_database.py"):
        init_schema(conn)


def test_local_asset_store_deduplicates_pdf_content(tmp_path):
    store = LocalAssetStore(tmp_path / "assets")
    payload = b"%PDF-1.4 identical content"
    first = store.put_pdf(BytesIO(payload))
    second = store.put_pdf(BytesIO(payload))

    assert first.id == second.id
    assert first.id == AssetId("sha256:ffb7192b0e6b6a4d3fbbe5dc8eecfa5828f0562d61511c94e7eb0cea0d8c4e23")
    assert store.path_for(first.id).read_bytes() == payload
    assert len(list((tmp_path / "assets" / "blobs").rglob("*.pdf"))) == 1


def test_config_reads_key_only_from_environment(tmp_path, monkeypatch):
    key_path = tmp_path / "api-key.txt"
    key_path.write_text("test-key\n", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY_FILE", str(key_path))
    get_settings.cache_clear()
    assert get_settings().llm_available is False
    monkeypatch.setenv("LLM_API_KEY", "environment-key")
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

    def parse_document(conn, paper_id, user_id=1):
        conn.execute(
            """
            INSERT INTO paper_documents(
                paper_id, parser_name, parser_version, source_hash,
                content_markdown, token_count, status, parsed_at
            ) VALUES (?, 'test-parser', '1', ?, ?, 20, 'completed', CURRENT_TIMESTAMP)
            """,
            (paper_id, "b" * 64, "# Test paper\n\nA complete parsed document used by the unit test."),
        )
        conn.commit()
        return {"status": "completed"}

    monkeypatch.setattr("backend.app.services.agents.parse_paper_document", parse_document)
    result = process_paper(conn, pending)
    assert result["status"] == "processed"
    detail = get_paper_detail(conn, pending)
    assert {section["section"] for section in detail["wiki"]} >= {"summary", "concepts", "methods", "experiments"}


def test_search_uses_real_keywords_only():
    conn = memory_db()
    assert search_wiki(conn, "Evidence Grounding", limit=5)
    assert search_wiki(conn, "definitely-no-such-topic", limit=5) == []


def test_chunks_and_derived_knowledge_are_invalidated_when_pdf_asset_changes():
    conn = memory_db()
    paper_id = conn.execute("SELECT id FROM papers WHERE processing_status = 'processed' LIMIT 1").fetchone()["id"]
    assert list_paper_chunks(conn, paper_id)[1] > 0
    assert conn.execute("SELECT COUNT(*) FROM wiki_sections WHERE paper_id = ?", (paper_id,)).fetchone()[0] > 0

    set_paper_asset_id(conn, paper_id, AssetId(f"sha256:{'c' * 64}"))

    assert list_paper_chunks(conn, paper_id) == ([], 0)
    assert conn.execute("SELECT processing_status FROM papers WHERE id = ?", (paper_id,)).fetchone()[0] == "pending"
    assert conn.execute("SELECT 1 FROM paper_documents WHERE paper_id = ?", (paper_id,)).fetchone() is None
    assert conn.execute("SELECT 1 FROM wiki_sections WHERE paper_id = ?", (paper_id,)).fetchone() is None
    assert conn.execute("SELECT 1 FROM paper_concepts WHERE paper_id = ?", (paper_id,)).fetchone() is None


def test_classic_qa_does_not_fall_back_to_unparsed_metadata():
    conn = memory_db()
    paper_id = conn.execute("SELECT id FROM papers WHERE processing_status = 'pending'").fetchone()["id"]
    result = answer_question(conn, "Pending Paper", [paper_id])
    assert result["citations"] == []
    assert "已解析" in result["answer"]


def test_metadata_search_recalls_named_paper_from_a_long_research_query():
    conn = memory_db()
    add_test_paper(conn, source_id="smartrag.0001", title="SmartRAG: Structured Retrieval on Mobile Devices")

    result = PaperToolbox(conn).search_metadata(
        query="SmartRAG structured retrieval augmented generation mobile arXiv"
    )

    assert result["items"]
    assert result["items"][0]["title"].startswith("SmartRAG")


def test_qa_uses_explicit_test_double(monkeypatch):
    conn = memory_db()
    monkeypatch.setattr(
        "backend.app.services.search.LLMClient.complete",
        lambda self, system_prompt, user_prompt: "Grounded answer from test evidence.",
    )
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


def test_upsert_paper_keeps_same_title_source_records_independent():
    conn = memory_db()
    first_id = add_test_paper(conn, source_id="dedupe.00001", title="A Stable Duplicate Title")
    second_id = upsert_paper(
        conn,
        PaperCandidate(
            source=PaperSource.ARXIV,
            source_id="dedupe.00002",
            title="A Stable Duplicate Title",
            authors=("Ada",),
            abstract="A duplicate title should map to one paper record.",
            categories=("cs.AI",),
            primary_category="cs.AI",
            published_at="2026-07-09",
        ),
    )
    third_id = upsert_paper(
        conn,
        PaperCandidate(
            source=PaperSource.USENIX,
            source_id="osdi26:stable-title",
            source_url="https://www.usenix.org/conference/osdi26/presentation/stable",
            venue="OSDI 2026",
            title="A Stable Duplicate Title",
            authors=("Grace",),
            abstract="A distinct conference source record.",
            categories=("systems",),
            primary_category="OSDI",
            published_at="2026-07-10",
        ),
    )

    assert len({first_id, int(second_id), int(third_id)}) == 3
    rows = conn.execute(
        "SELECT source, source_id, authors_json, venue FROM papers WHERE title = ? ORDER BY id",
        ("A Stable Duplicate Title",),
    ).fetchall()
    assert [(row["source"], row["source_id"]) for row in rows] == [
        ("arxiv", "dedupe.00001"),
        ("arxiv", "dedupe.00002"),
        ("usenix", "osdi26:stable-title"),
    ]
    assert rows[0]["authors_json"] != rows[2]["authors_json"]
    assert rows[0]["venue"] is None
    assert rows[2]["venue"] == "OSDI 2026"


def test_metadata_refresh_preserves_processed_state_and_document():
    conn = memory_db()
    paper = conn.execute(
        "SELECT id, source_id FROM papers WHERE processing_status = 'processed' ORDER BY id LIMIT 1"
    ).fetchone()
    paper_id = int(paper["id"])

    refreshed_id = upsert_paper(
        conn,
        PaperCandidate(
            source=PaperSource.ARXIV,
            source_id=str(paper["source_id"]),
            title="Refreshed title",
            authors=("Updated Author",),
            abstract="Updated metadata without a new asset.",
            categories=("cs.CL",),
            primary_category="cs.CL",
            published_at="2025-01-01",
        ),
    )

    assert int(refreshed_id) == paper_id
    state = conn.execute("SELECT processing_status FROM papers WHERE id = ?", (paper_id,)).fetchone()
    assert state["processing_status"] == "processed"
    assert conn.execute("SELECT 1 FROM paper_documents WHERE paper_id = ?", (paper_id,)).fetchone() is not None
    assert conn.execute("SELECT COUNT(*) FROM paper_chunks WHERE paper_id = ?", (paper_id,)).fetchone()[0] > 0


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


def test_api_chunks_returns_current_parsed_document_chunks(api_client):
    paper_id = api_client.get("/api/papers?q=RAG%20Evidence%20Grounding").json()["items"][0]["id"]
    response = api_client.get(f"/api/papers/{paper_id}/chunks?limit=2")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["total"] >= 2
    assert all(item["paper_id"] == paper_id for item in payload["items"])


def test_api_ingest_does_not_deduplicate_matching_titles(api_client, monkeypatch):
    fetched = [
        PaperCandidate(
            source=PaperSource.ARXIV,
            source_id="2699.10001",
            title="Imported duplicate title",
            authors=("Ada",),
            abstract="First fetched duplicate.",
            categories=("cs.AI",),
            primary_category="cs.AI",
            published_at="2026-07-09",
        ),
        PaperCandidate(
            source=PaperSource.ARXIV,
            source_id="2699.10002",
            title="Imported duplicate title",
            authors=("Grace",),
            abstract="Second fetched duplicate.",
            categories=("cs.AI",),
            primary_category="cs.AI",
            published_at="2026-07-09",
        ),
    ]
    monkeypatch.setattr(
        "backend.app.api.routers.ingest.fetch_arxiv_papers",
        lambda categories, keywords, max_results: fetched,
    )
    response = api_client.post("/api/ingest/arxiv", json={"categories": ["cs.AI"], "keywords": [], "max_results": 2})
    assert response.status_code == 200
    data = response.json()
    assert data["fetched_count"] == 2
    assert data["duplicate_count"] == 0
    assert data["count"] == 2
    assert len(data["paper_ids"]) == 2


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


def test_sigops_schedule_maps_direct_and_acm_pdf_links():
    candidates = _schedule_candidates(
        '<a href="assets/papers/example.pdf"><strong>A Direct SOSP Paper</strong></a>'
        '<a href="https://dl.acm.org/doi/10.1145/3694715.3695951">An ACM SOSP Paper</a>',
        "https://sigops.org/s/conferences/sosp/2024/schedule.html",
    )

    direct = _match_candidate("A Direct SOSP Paper", candidates)
    acm = _match_candidate("An ACM SOSP Paper", candidates)
    assert direct is not None
    assert direct["pdf_url"] == "https://sigops.org/s/conferences/sosp/2024/assets/papers/example.pdf"
    assert acm is not None
    assert acm["doi"] == "10.1145/3694715.3695951"
    assert acm["pdf_url"] == "https://dl.acm.org/doi/pdf/10.1145/3694715.3695951?download=true"


def test_sigops_rejects_untrusted_proceedings_url_before_open(monkeypatch):
    opened: list[str] = []

    def fake_open(*args, **kwargs):
        opened.append(str(args[0]))
        raise AssertionError("untrusted URL must not be opened")

    monkeypatch.setattr("backend.app.services.sources.sigops.open_trusted_url", fake_open)
    with pytest.raises(UnsafeUrlError):
        fetch_sigops_papers(
            "sosp",
            2026,
            proceedings_url="http://127.0.0.1:8000/internal",
        )
    assert opened == []


@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1/internal",
        "https://127.0.0.1/internal",
        "https://www.usenix.org:8443/paper.pdf",
        "https://www.usenix.org@127.0.0.1/paper.pdf",
    ],
)
def test_trusted_redirect_handler_rejects_target_before_following(target):
    handler = _TrustedRedirectHandler({"www.usenix.org"})
    request = Request("https://www.usenix.org/start.pdf")
    with pytest.raises(UnsafeUrlError):
        handler.redirect_request(request, None, 302, "Found", {}, target)


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
    assert paper.source == PaperSource.USENIX
    assert paper.title == "A USENIX Paper"
    assert paper.pdf_url == "https://example.test/paper.pdf"


def test_usenix_detail_removes_bibtex_title_braces():
    page = MetadataPage()
    page.feed('<pre>@inproceedings {1, title = {A {Hardware-Accelerated} System}, author = {Ada and Grace}}</pre>')
    paper = _detail_to_paper(page, "https://www.usenix.org/conference/osdi24/presentation/example", "OSDI", 2024)
    assert paper is not None
    assert paper.title == "A Hardware-Accelerated System"


def test_api_ingests_usenix_source(api_client, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.routers.ingest.fetch_usenix_papers",
        lambda venue, year, max_results: [
            PaperCandidate(
                source=PaperSource.USENIX,
                source_id="osdi:2024:demo",
                source_url="https://example.test/osdi-demo",
                venue="OSDI 2024",
                title="USENIX import demo",
                authors=("Ada",),
                abstract="Imported from a mocked USENIX page.",
                categories=("systems",),
                primary_category="systems",
                published_at="2024-01-01",
            )
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
        "backend.app.api.routers.papers.save_and_extract_pdf",
        lambda file, store: SimpleNamespace(
            asset=AssetInfo(id=AssetId(f"sha256:{'a' * 64}"), size_bytes=16),
            title="Extracted PDF title",
            text="Extracted PDF text.",
        ),
    )
    response = api_client.post(
        "/api/papers/upload",
        files={"file": ("demo.pdf", b"%PDF-1.4 mock", "application/pdf")},
        data={"authors": "Ada, Grace", "year": "2025"},
    )
    assert response.status_code == 200
    paper = response.json()
    assert paper["source"] == "upload"
    assert paper["pdf"] == {
        "available": True,
        "cached": True,
        "view_url": f"/api/papers/{paper['id']}/pdf",
        "download_url": f"/api/papers/{paper['id']}/pdf/download",
    }
    assert {"file_url", "pdf_url", "asset_id"}.isdisjoint(paper)
    assert paper["authors"] == ["Ada", "Grace"]
    assert paper["upload"] == {
        "visibility": "private",
        "provenance": "user_upload",
        "moderation_status": "unreviewed",
        "owned_by_current_user": True,
        "original_filename": "demo.pdf",
    }


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
    view = api_client.get(paper["pdf"]["view_url"])
    assert view.status_code == 200
    assert view.headers["content-type"] == "application/pdf"
    assert view.headers["content-disposition"].startswith("inline")
    assert view.headers["accept-ranges"] == "bytes"
    assert view.content.startswith(b"%PDF-")

    partial = api_client.get(paper["pdf"]["view_url"], headers={"Range": "bytes=0-4"})
    assert partial.status_code == 206
    assert partial.content == b"%PDF-"

    not_modified = api_client.get(paper["pdf"]["view_url"], headers={"If-None-Match": view.headers["etag"]})
    assert not_modified.status_code == 304
    assert not_modified.content == b""

    download = api_client.get(paper["pdf"]["download_url"])
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment")
    assert download.content == view.content
    assert api_client.get(f"/api/papers/{paper['id']}/file").status_code == 404


def test_private_and_public_upload_visibility_covers_direct_and_indirect_reads(
    api_client,
    monkeypatch,
):
    monkeypatch.setattr(
        "backend.app.api.routers.papers.save_and_extract_pdf",
        lambda file, store: SimpleNamespace(
            asset=AssetInfo(id=AssetId(f"sha256:{'c' * 64}"), size_bytes=16),
            title="Private visibility sentinel",
            text="Private visibility sentinel content.",
        ),
    )
    first_user = api_client.get("/api/auth/me").json()
    first_session = api_client.cookies.get("paperwiki_session")
    public_health_count = api_client.get("/api/health").json()["papers"]
    uploaded = api_client.post(
        "/api/papers/upload",
        files={"file": ("private-sentinel.pdf", b"%PDF-1.4 mock", "application/pdf")},
        data={"year": "2025", "visibility": "private"},
    )
    assert uploaded.status_code == 200
    paper_id = uploaded.json()["id"]
    assert api_client.get("/api/health").json()["papers"] == public_health_count
    with connect() as conn:
        replace_wiki_sections(
            conn,
            paper_id,
            {"summary": "Private visibility sentinel wiki evidence."},
        )
        attach_concepts(
            conn,
            paper_id,
            [
                {
                    "name": "PrivateVisibilityConcept",
                    "description": "Private visibility sentinel concept.",
                    "relation": "topic",
                    "weight": 1.0,
                }
            ],
        )

    registered = api_client.post(
        "/api/auth/register",
        json={"username": "visibility_reader", "password": "reader-password"},
    )
    assert registered.status_code == 201
    second_user = registered.json()
    second_session = api_client.cookies.get("paperwiki_session")
    first_headers = {"Cookie": f"paperwiki_session={first_session}"}
    second_headers = {"Cookie": f"paperwiki_session={second_session}"}

    assert paper_id not in [
        item["id"]
        for item in api_client.get("/api/papers", headers=second_headers).json()["items"]
    ]
    for path in (
        f"/api/papers/{paper_id}",
        f"/api/papers/{paper_id}/chunks",
        f"/api/papers/{paper_id}/pdf",
    ):
        assert api_client.get(path, headers=second_headers).status_code == 404
    for path in (
        f"/api/papers/{paper_id}/process",
        f"/api/papers/{paper_id}/document/parse",
        f"/api/papers/{paper_id}/summaries",
    ):
        assert api_client.post(path, headers=second_headers).status_code == 404
    assert api_client.post(
        "/api/library/favorites",
        headers=second_headers,
        json={"paper_id": paper_id, "favorite": True},
    ).status_code == 404
    assert api_client.post(
        "/api/notes",
        headers=second_headers,
        json={"paper_id": paper_id, "note": "should not be accepted"},
    ).status_code == 404
    assert api_client.post(
        f"/api/papers/{paper_id}/chat/threads",
        headers=second_headers,
        json={},
    ).status_code == 404
    assert api_client.post(
        "/api/qa",
        headers=second_headers,
        json={"question": "sentinel", "paper_ids": [paper_id], "mode": "classic"},
    ).status_code == 404
    assert api_client.get(
        "/api/wiki/search?q=Private%20visibility%20sentinel",
        headers=second_headers,
    ).json()["items"] == []
    assert api_client.get(
        "/api/graph?topic=PrivateVisibilityConcept",
        headers=second_headers,
    ).json() == {"nodes": [], "links": []}
    with connect() as conn:
        assert PaperToolbox(conn, user_id=second_user["id"]).search_metadata(
            query="Private visibility sentinel"
        )["items"] == []

    published = api_client.patch(
        f"/api/papers/{paper_id}/visibility",
        headers=first_headers,
        json={"visibility": "public"},
    )
    assert published.status_code == 200
    assert published.json()["upload"]["owned_by_current_user"] is True
    assert api_client.get("/api/health").json()["papers"] == public_health_count + 1
    public_detail = api_client.get(f"/api/papers/{paper_id}", headers=second_headers)
    assert public_detail.status_code == 200
    assert public_detail.json()["upload"] == {
        "visibility": "public",
        "provenance": "user_upload",
        "moderation_status": "unreviewed",
        "owned_by_current_user": False,
        "original_filename": None,
    }
    assert api_client.patch(
        f"/api/papers/{paper_id}/visibility",
        headers=second_headers,
        json={"visibility": "private"},
    ).status_code == 404
    favorite = api_client.post(
        "/api/library/favorites",
        headers=second_headers,
        json={"paper_id": paper_id, "favorite": True},
    )
    assert favorite.status_code == 200
    thread = api_client.post(
        f"/api/papers/{paper_id}/chat/threads",
        headers=second_headers,
        json={},
    ).json()
    assert api_client.get(
        "/api/wiki/search?q=Private%20visibility%20sentinel",
        headers=second_headers,
    ).json()["items"]

    privatized = api_client.patch(
        f"/api/papers/{paper_id}/visibility",
        headers=first_headers,
        json={"visibility": "private"},
    )
    assert privatized.status_code == 200
    assert api_client.get("/api/health").json()["papers"] == public_health_count
    assert api_client.get("/api/library/items", headers=second_headers).json()["items"] == []
    assert all(
        folder["item_count"] == 0
        for folder in api_client.get("/api/library/folders", headers=second_headers).json()["items"]
    )
    assert api_client.get(f"/api/chat/threads/{thread['id']}", headers=second_headers).status_code == 404
    assert api_client.get(
        f"/api/papers/{paper_id}/chat/threads",
        headers=second_headers,
    ).json()["items"] == []
    assert api_client.get(
        "/api/wiki/search?q=Private%20visibility%20sentinel",
        headers=second_headers,
    ).json()["items"] == []
    assert paper_id not in [
        item["paper_id"]
        for item in api_client.get("/api/history", headers=second_headers).json()["items"]
    ]
    first_stats = api_client.get("/api/stats", headers=first_headers).json()
    second_stats = api_client.get("/api/stats", headers=second_headers).json()
    assert first_stats["papers"] == second_stats["papers"] + 1
    assert first_user["id"] != second_user["id"]


def test_api_remote_pdf_downloads_once_and_serves_cache(api_client, monkeypatch):
    with connect() as conn:
        paper_id = conn.execute("SELECT id FROM papers ORDER BY id LIMIT 1").fetchone()["id"]
        conn.execute(
            "UPDATE papers SET pdf_url = ?, asset_id = NULL WHERE id = ?",
            ("https://www.usenix.org/system/files/paper.pdf", paper_id),
        )
        conn.commit()

    class FakeResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def geturl(self):
            return "https://www.usenix.org/system/files/paper.pdf"

        def read(self, _size=-1):
            if getattr(self, "read_once", False):
                return b""
            self.read_once = True
            return b"%PDF-1.4 cached\n%%EOF\n"

    calls = []

    def fake_urlopen(*_args, **_kwargs):
        calls.append(True)
        return FakeResponse()

    monkeypatch.setattr("backend.app.services.remote_pdf.open_trusted_url", fake_urlopen)
    first = api_client.get(f"/api/papers/{paper_id}/pdf")
    second = api_client.get(f"/api/papers/{paper_id}/pdf")
    not_modified = api_client.get(
        f"/api/papers/{paper_id}/pdf",
        headers={"If-None-Match": first.headers["etag"]},
    )

    assert first.status_code == 200
    assert first.headers["content-type"] == "application/pdf"
    assert first.headers["content-disposition"].startswith("inline")
    assert first.headers["cache-control"] == "private, max-age=3600, must-revalidate"
    assert first.content.startswith(b"%PDF-")
    assert second.status_code == 200
    assert second.content == first.content
    assert not_modified.status_code == 304
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        (b"%PDF-1.4 truncated", {}),
        (b"%PDF-1.4 complete\n%%EOF\n", {"Content-Length": "999"}),
    ],
)
def test_api_remote_pdf_rejects_incomplete_downloads(api_client, monkeypatch, body, headers):
    with connect() as conn:
        paper_id = conn.execute("SELECT id FROM papers ORDER BY id LIMIT 1").fetchone()["id"]
        conn.execute(
            "UPDATE papers SET pdf_url = ?, asset_id = NULL WHERE id = ?",
            ("https://www.usenix.org/system/files/incomplete.pdf", paper_id),
        )
        conn.commit()

    class FakeResponse:
        def __init__(self):
            self.headers = headers
            self.read_once = False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def geturl(self):
            return "https://www.usenix.org/system/files/incomplete.pdf"

        def read(self, _size=-1):
            if self.read_once:
                return b""
            self.read_once = True
            return body

    monkeypatch.setattr(
        "backend.app.services.remote_pdf.open_trusted_url",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    response = api_client.get(f"/api/papers/{paper_id}/pdf")

    assert response.status_code == 502
    assert response.json() == {"detail": "remote PDF download failed"}
    with connect() as conn:
        assert conn.execute("SELECT asset_id FROM papers WHERE id = ?", (paper_id,)).fetchone()["asset_id"] is None


def test_research_sensitive_reads_disable_http_caching(api_client) -> None:
    created = api_client.post(
        "/api/research/runs",
        json={"title": "No-store", "goal": "Verify private research response caching"},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]

    for suffix in ("artifacts", "citations", "reports"):
        response = api_client.get(f"/api/research/runs/{run_id}/{suffix}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"


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
    assert root["item_count"] == 1
    assert inbox["item_count"] == 1
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
    folders_after_move = api_client.get("/api/library/folders").json()["items"]
    assert next(folder for folder in folders_after_move if folder["is_root"])["item_count"] == 1


def test_library_favorites_are_isolated_by_session_and_ignore_user_header(api_client):
    paper_id = api_client.get("/api/papers?limit=1").json()["items"][0]["id"]
    first_session = api_client.cookies.get("paperwiki_session")
    registered = api_client.post(
        "/api/auth/register",
        json={"username": "second_user", "password": "second-password"},
    )
    assert registered.status_code == 201
    second_session = api_client.cookies.get("paperwiki_session")
    response = api_client.post(
        "/api/library/favorites",
        headers={"X-User-ID": "1", "Cookie": f"paperwiki_session={second_session}"},
        json={"paper_id": paper_id, "favorite": True},
    )
    assert response.status_code == 200
    assert response.json()["is_favorite"] is True
    first_items = api_client.get(
        "/api/library/items",
        headers={"Cookie": f"paperwiki_session={first_session}"},
    ).json()["items"]
    assert first_items == []
    user_two_items = api_client.get(
        "/api/library/items",
        headers={"Cookie": f"paperwiki_session={second_session}"},
    ).json()["items"]
    assert [item["id"] for item in user_two_items] == [paper_id]


def test_notes_history_subscriptions_and_chat_are_isolated_by_session(api_client):
    paper_id = api_client.get("/api/papers?limit=1").json()["items"][0]["id"]
    first_session = api_client.cookies.get("paperwiki_session")
    registered = api_client.post(
        "/api/auth/register",
        json={"username": "private_owner", "password": "private-password"},
    )
    assert registered.status_code == 201
    second_session = api_client.cookies.get("paperwiki_session")
    second_headers = {"Cookie": f"paperwiki_session={second_session}"}
    first_headers = {"Cookie": f"paperwiki_session={first_session}"}

    note = api_client.post(
        "/api/notes",
        headers=second_headers,
        json={"paper_id": paper_id, "note": "only second user", "comment": "private"},
    )
    assert note.status_code == 200
    subscription = api_client.post(
        "/api/subscriptions",
        headers=second_headers,
        json={"topic": "private topic"},
    )
    assert subscription.status_code == 200
    thread = api_client.post("/api/chat/threads", headers=second_headers, json={}).json()

    second_detail = api_client.get(f"/api/papers/{paper_id}", headers=second_headers).json()
    assert [item["note"] for item in second_detail["notes"]] == ["only second user"]
    assert [item["topic"] for item in api_client.get("/api/subscriptions", headers=second_headers).json()["items"]] == [
        "private topic"
    ]
    assert api_client.get(f"/api/chat/threads/{thread['id']}", headers=second_headers).status_code == 200

    first_detail = api_client.get(f"/api/papers/{paper_id}", headers=first_headers).json()
    assert first_detail["notes"] == []
    first_history = api_client.get("/api/history", headers=first_headers).json()["items"]
    assert all(item["action"] != "新增笔记" for item in first_history)
    assert api_client.get("/api/subscriptions", headers=first_headers).json()["items"] == []
    assert api_client.get(f"/api/chat/threads/{thread['id']}", headers=first_headers).status_code == 404
    assert api_client.get("/api/stats", headers=first_headers).json()["notes"] == 0
    assert api_client.get("/api/stats", headers=second_headers).json()["notes"] == 1


def test_library_schema_does_not_store_last_recommendation():
    conn = memory_db()
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(library_items)").fetchall()}
    assert "last_recommended_folder_id" not in columns


def test_chat_message_tree_keeps_regenerated_answers_as_siblings():
    conn = memory_db()
    paper_id = conn.execute("SELECT id FROM papers LIMIT 1").fetchone()["id"]
    thread = create_thread(conn, paper_id)
    conn.execute(
        """
        UPDATE paper_documents
        SET content_markdown = '# Full paper\n\nComplete source text.', token_count = 12, status = 'completed'
        WHERE paper_id = ?
        """,
        (paper_id,),
    )
    first = prepare_run(
        conn,
        thread_id=thread["id"],
        user_message={"id": "u1", "parent_id": None, "content": "What is the contribution?"},
        parent_message_id=None,
        assistant_message_id="a1",
        source_message_id=None,
        message_token_limit=12000,
    )
    second = prepare_run(
        conn,
        thread_id=thread["id"],
        user_message=None,
        parent_message_id="u1",
        assistant_message_id="a2",
        source_message_id="a1",
        message_token_limit=12000,
        operation="regenerate",
    )
    assert first["input_message_id"] == second["input_message_id"] == "u1"
    repository = get_message_repository(conn, thread["id"])
    parents = {row["id"]: row["parent_id"] for row in repository["messages"]}
    assert parents["a1"] == parents["a2"] == "u1"
    assert repository["headId"] == "a2"


def test_chat_message_id_collision_does_not_create_run_or_overwrite_answer():
    conn = memory_db()
    paper_id = conn.execute("SELECT id FROM papers LIMIT 1").fetchone()["id"]
    thread = create_thread(conn, paper_id)
    prepare_run(
        conn,
        thread_id=thread["id"],
        user_message={"id": "collision-u1", "parent_id": None, "content": "First question"},
        parent_message_id=None,
        assistant_message_id="collision-a1",
        source_message_id=None,
        message_token_limit=12000,
    )
    conn.execute(
        "UPDATE chat_messages SET content = 'historical answer', status = 'complete' WHERE id = 'collision-a1'"
    )
    conn.commit()

    with pytest.raises(ValueError, match="message id already exists"):
        prepare_run(
            conn,
            thread_id=thread["id"],
            user_message=None,
            parent_message_id="collision-u1",
            assistant_message_id="collision-a1",
            source_message_id=None,
            message_token_limit=12000,
            operation="regenerate",
        )

    answer = conn.execute(
        "SELECT content, status FROM chat_messages WHERE id = 'collision-a1'"
    ).fetchone()
    assert dict(answer) == {"content": "historical answer", "status": "complete"}
    assert conn.execute("SELECT COUNT(*) FROM chat_runs").fetchone()[0] == 1


def test_general_chat_uses_only_conversation_lineage():
    conn = memory_db()
    thread = create_thread(conn, None)
    assert thread["paper_id"] is None
    first = prepare_run(
        conn,
        thread_id=thread["id"],
        user_message={"id": "general-u1", "parent_id": None, "content": "Remember ALPHA_SENTINEL"},
        parent_message_id=None,
        assistant_message_id="general-a1",
        source_message_id=None,
        message_token_limit=12000,
    )
    conn.execute(
        "UPDATE chat_messages SET content = 'Acknowledged ALPHA_SENTINEL', status = 'complete' WHERE id = ?",
        (first["assistant_message_id"],),
    )
    second = prepare_run(
        conn,
        thread_id=thread["id"],
        user_message={"id": "general-u2", "parent_id": "general-a1", "content": "What did I ask you to remember?"},
        parent_message_id=None,
        assistant_message_id="general-a2",
        source_message_id=None,
        message_token_limit=12000,
    )
    messages = build_model_messages(conn, second)
    assert [message["role"] for message in messages] == ["system", "user", "assistant", "user"]
    assert "ALPHA_SENTINEL" in messages[1]["content"]
    assert "论文完整解析正文" not in "\n".join(message["content"] for message in messages)
    assert list_threads(conn, None)[0]["id"] == thread["id"]


def test_chat_operation_contract_rejects_mismatched_payloads():
    conn = memory_db()
    thread = create_thread(conn, None)
    with pytest.raises(ValueError, match="regenerate must reuse"):
        prepare_run(
            conn,
            thread_id=thread["id"],
            user_message={"id": "u1", "parent_id": None, "content": "Hello"},
            parent_message_id=None,
            assistant_message_id="a1",
            source_message_id=None,
            message_token_limit=12000,
            operation="regenerate",
        )
    assert conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0


def test_api_creates_and_lists_general_chat_threads(api_client):
    created = api_client.post("/api/chat/threads", json={})
    assert created.status_code == 200
    assert created.json()["paper_id"] is None
    listed = api_client.get("/api/chat/threads")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [created.json()["id"]]


def test_research_step_completion_is_fenced_and_pause_wins() -> None:
    conn = memory_db()
    created = create_harness_run(
        conn,
        user_id=1,
        title="Harness fencing",
        goal="Verify safe pause",
    )
    step = claim_next_step(conn, worker_id="worker-a", lease_seconds=60)
    assert step is not None
    assert heartbeat_step(
        conn,
        step_id=step["id"],
        worker_id="worker-b",
        lease_generation=step["lease_generation"],
        lease_seconds=60,
    ) is False
    request_action(conn, created["id"], 1, "pause")
    assert finish_step(
        conn,
        step_id=step["id"],
        worker_id="worker-a",
        lease_generation=step["lease_generation"],
        output={"must_not_commit": True},
    ) is True
    snapshot = get_run_snapshot(conn, created["id"], 1)
    assert snapshot["status"] == "paused"
    assert snapshot["steps"][0]["status"] == "paused"
    assert snapshot["steps"][0]["output"] == {}


def test_research_expired_lease_reclaim_rejects_old_worker() -> None:
    conn = memory_db()
    run = create_harness_run(conn, user_id=1, title="Lease recovery", goal="Fence old owner")
    first = claim_next_step(conn, worker_id="worker-a", lease_seconds=60)
    assert first is not None
    conn.execute(
        "UPDATE research_steps SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?",
        (first["id"],),
    )
    conn.commit()
    assert heartbeat_step(
        conn,
        step_id=first["id"],
        worker_id="worker-a",
        lease_generation=first["lease_generation"],
        lease_seconds=60,
    ) is False
    assert finish_step(
        conn,
        step_id=first["id"],
        worker_id="worker-a",
        lease_generation=first["lease_generation"],
        output={"expired": True},
    ) is False
    assert recover_expired_leases(conn) == 1
    second = claim_next_step(conn, worker_id="worker-b", lease_seconds=60)
    assert second is not None
    assert second["id"] == first["id"]
    assert second["lease_generation"] == first["lease_generation"] + 1
    assert finish_step(
        conn,
        step_id=first["id"],
        worker_id="worker-a",
        lease_generation=first["lease_generation"],
        output={"stale": True},
    ) is False
    assert finish_step(
        conn,
        step_id=second["id"],
        worker_id="worker-b",
        lease_generation=second["lease_generation"],
        output={"scaffold_only": True},
    ) is True
    assert get_run_snapshot(conn, run["id"], 1)["steps"][0]["output"] == {
        "scaffold_only": True
    }


def test_research_executor_restart_recovers_expired_lease_and_fences_old_worker(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "restart-recovery.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    get_settings.cache_clear()
    init_db(database)
    with connect(database) as conn:
        conn.execute(
            """
            INSERT INTO users(id, name, username, password_hash, is_active)
            VALUES (1, 'Restart User', 'restart_user', '!unit-test-only', 1)
            """
        )
        conn.commit()
        run = create_harness_run(
            conn,
            user_id=1,
            title="Restart recovery",
            goal="Recover the expired step without external calls",
        )
        stale = claim_next_step(conn, worker_id="worker-before-restart", lease_seconds=60)
        assert stale is not None
        conn.execute(
            "UPDATE research_steps SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?",
            (stale["id"],),
        )
        conn.commit()

    executor = ResearchExecutor(lease_seconds=1, heartbeat_seconds=1, poll_seconds=0.01)
    executor.start()
    try:
        completed = None
        for _ in range(200):
            with connect(database) as conn:
                snapshot = get_run_snapshot(conn, run["id"], 1)
            if snapshot["status"] == "completed":
                completed = snapshot
                break
            import time

            time.sleep(0.01)
        assert completed is not None
        assert [step["status"] for step in completed["steps"]] == [
            "completed",
            "completed",
            "completed",
        ]
        with connect(database) as conn:
            assert finish_step(
                conn,
                step_id=stale["id"],
                worker_id="worker-before-restart",
                lease_generation=stale["lease_generation"],
                output={"stale": True},
            ) is False
            events = conn.execute(
                "SELECT id FROM research_events WHERE run_id = ? ORDER BY id",
                (run["id"],),
            ).fetchall()
        event_ids = [int(row["id"]) for row in events]
        assert event_ids == sorted(set(event_ids))
    finally:
        executor.stop()
        get_settings.cache_clear()


def test_research_manual_retry_grants_new_attempt_without_leaking_error() -> None:
    conn = memory_db()
    run = create_harness_run(conn, user_id=1, title="Retry", goal="Retry a failed step")
    step = claim_next_step(conn, worker_id="worker-a", lease_seconds=60)
    assert step is not None
    assert fail_step(
        conn,
        step_id=step["id"],
        worker_id="worker-a",
        lease_generation=step["lease_generation"],
        error_code="provider_failed",
        error_message="Authorization: Bearer super-secret /Users/private/file",
    ) is True
    failed = get_run_snapshot(conn, run["id"], 1)
    assert "super-secret" not in str(failed)
    retried = retry_run(conn, run["id"], 1)
    assert retried["status"] == "queued"
    claimed = claim_next_step(conn, worker_id="worker-b", lease_seconds=60)
    assert claimed is not None
    assert claimed["attempt_count"] == 2
    assert claimed["max_attempts"] == 2
    assert claimed["idempotency_key"].startswith(f"{step['idempotency_key']}:manual:")


def test_research_decision_resolution_requeues_waiting_step() -> None:
    conn = memory_db()
    run = create_harness_run(conn, user_id=1, title="Decision", goal="Resume a waiting step")
    step_id = run["steps"][0]["id"]
    conn.execute("UPDATE research_runs SET status = 'waiting_input' WHERE id = ?", (run["id"],))
    conn.execute("UPDATE research_steps SET status = 'waiting_input' WHERE id = ?", (step_id,))
    conn.execute(
        """
        INSERT INTO research_decisions(
            id, run_id, step_id, question, options_json, recommended_option
        ) VALUES ('decision-1', ?, ?, 'Continue?', '[{"id":"continue","label":"Continue"}]', 'continue')
        """,
        (run["id"], step_id),
    )
    conn.commit()

    with pytest.raises(ResearchConflictError, match="queued or running"):
        request_action(conn, run["id"], 1, "pause")
    resolved = resolve_decision(conn, "decision-1", 1, "continue")
    assert resolved["status"] == "queued"
    assert resolved["steps"][0]["status"] == "queued"
    claimed = claim_next_step(conn, worker_id="worker-a", lease_seconds=60)
    assert claimed is not None
    assert claimed["id"] == step_id


def test_research_cancel_cancels_waiting_decision_and_blocks_answer() -> None:
    conn = memory_db()
    run = create_harness_run(conn, user_id=1, title="Cancel decision", goal="Cancel safely")
    step_id = run["steps"][0]["id"]
    conn.execute("UPDATE research_runs SET status = 'waiting_input' WHERE id = ?", (run["id"],))
    conn.execute("UPDATE research_steps SET status = 'waiting_input' WHERE id = ?", (step_id,))
    conn.execute(
        """
        INSERT INTO research_decisions(id, run_id, step_id, question, options_json)
        VALUES ('decision-cancel', ?, ?, 'Continue?', '[{"id":"yes","label":"Yes"}]')
        """,
        (run["id"], step_id),
    )
    conn.commit()
    request_action(conn, run["id"], 1, "cancel")
    assert reconcile_requested_actions(conn) == 1
    cancelled = get_run_snapshot(conn, run["id"], 1)
    assert cancelled["status"] == "cancelled"
    assert cancelled["steps"][0]["status"] == "cancelled"
    assert cancelled["decisions"][0]["status"] == "cancelled"
    with pytest.raises(ResearchConflictError, match="already resolved"):
        resolve_decision(conn, "decision-cancel", 1, "yes")


def test_research_api_runs_deterministic_harness_and_isolates_owner(api_client):
    first_session = api_client.cookies.get("paperwiki_session")
    created = api_client.post(
        "/api/research/runs",
        json={"title": "RAG research harness", "goal": "Prepare a deterministic scaffold"},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]

    completed = None
    for _ in range(50):
        snapshot = api_client.get(f"/api/research/runs/{run_id}")
        assert snapshot.status_code == 200
        if snapshot.json()["status"] == "completed":
            completed = snapshot.json()
            break
        import time

        time.sleep(0.02)
    assert completed is not None
    assert [step["status"] for step in completed["steps"]] == [
        "completed",
        "completed",
        "completed",
    ]
    assert completed["steps"][-1]["output"]["scaffold_only"] is True
    assert completed["steps"][-1]["output"]["research_claims"] == []
    assert api_client.get("/api/research/runs").json()["items"][0]["id"] == run_id

    registered = api_client.post(
        "/api/auth/register",
        json={"username": "research_other", "password": "other-password"},
    )
    assert registered.status_code == 201
    second_session = api_client.cookies.get("paperwiki_session")
    assert first_session and second_session
    first_headers = {"Cookie": f"paperwiki_session={first_session}"}
    second_headers = {"Cookie": f"paperwiki_session={second_session}"}
    for method, path in (
        ("get", f"/api/research/runs/{run_id}"),
        ("get", f"/api/research/runs/{run_id}/events?after=0"),
        ("get", f"/api/research/runs/{run_id}/artifacts"),
        ("get", f"/api/research/runs/{run_id}/artifacts/not-owned"),
        ("get", f"/api/research/runs/{run_id}/papers"),
        ("get", f"/api/research/runs/{run_id}/papers/1/brief"),
        ("get", f"/api/research/runs/{run_id}/citations"),
        ("get", f"/api/research/runs/{run_id}/citations/not-owned"),
        ("get", f"/api/research/runs/{run_id}/citations/not-owned/evidence"),
        ("get", f"/api/research/runs/{run_id}/reports"),
        ("get", f"/api/research/runs/{run_id}/reports/1"),
        ("get", f"/api/research/runs/{run_id}/comparison-matrix"),
        ("post", f"/api/research/runs/{run_id}/report-regeneration"),
        ("post", f"/api/research/runs/{run_id}/pause"),
        ("post", f"/api/research/runs/{run_id}/cancel"),
        ("post", f"/api/research/runs/{run_id}/retry"),
    ):
        response = getattr(api_client, method)(path, headers=second_headers)
        assert response.status_code == 404

    events = api_client.get(
        f"/api/research/runs/{run_id}/events",
        headers={**first_headers, "Last-Event-ID": "0"},
    )
    assert events.status_code == 200
    event_ids = [
        int(line.removeprefix("id: "))
        for line in events.text.splitlines()
        if line.startswith("id: ")
    ]
    assert event_ids == sorted(set(event_ids))
    assert "event: run.completed" in events.text
    resumed = api_client.get(
        f"/api/research/runs/{run_id}/events",
        headers={**first_headers, "Last-Event-ID": str(event_ids[1])},
    )
    resumed_ids = [
        int(line.removeprefix("id: "))
        for line in resumed.text.splitlines()
        if line.startswith("id: ")
    ]
    assert resumed_ids == [event_id for event_id in event_ids if event_id > event_ids[1]]


def test_research_sse_rejects_invalid_last_event_id(api_client):
    created = api_client.post(
        "/api/research/runs",
        json={"title": "Invalid cursor", "goal": "Check cursor validation"},
    ).json()
    response = api_client.get(
        f"/api/research/runs/{created['id']}/events",
        headers={"Last-Event-ID": "not-an-integer"},
    )
    assert response.status_code == 400
    too_large = api_client.get(
        f"/api/research/runs/{created['id']}/events",
        headers={"Last-Event-ID": "9223372036854775808"},
    )
    assert too_large.status_code == 400


def test_api_streams_and_persists_general_chat(api_client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    get_settings.cache_clear()
    captured: list[list[dict[str, str]]] = []

    def fake_stream(_self, messages):
        captured.append(messages)
        yield "你好"
        yield "，世界"

    monkeypatch.setattr("backend.app.services.conversations.LLMClient.stream", fake_stream)
    thread = api_client.post("/api/chat/threads", json={}).json()
    response = api_client.post(
        "/api/chat/runs",
        json={
            "thread_id": thread["id"],
            "operation": "append",
            "user_message": {"id": "general-api-u1", "content": "请打招呼"},
            "assistant_message_id": "general-api-a1",
        },
    )
    assert response.status_code == 200
    assert "message.completed" in response.text
    assert captured[0][-1] == {"role": "user", "content": "请打招呼"}
    assert "METHOD_SENTINEL" not in "\n".join(message["content"] for message in captured[0])

    repository = api_client.get(f"/api/chat/threads/{thread['id']}/messages").json()
    assert repository["headId"] == "general-api-a1"
    assert [(item["role"], item["content"]) for item in repository["messages"]] == [
        ("user", "请打招呼"),
        ("assistant", "你好，世界"),
    ]
    assert repository["messages"][1]["content_parts"] == [
        {"type": "text", "text": "你好，世界"}
    ]
    get_settings.cache_clear()


def test_chat_route_explicit_research_is_atomic_idempotent_and_persists_parts(api_client):
    thread = api_client.post("/api/chat/threads", json={}).json()
    payload = {
        "thread_id": thread["id"],
        "mode": "deep_research",
        "user_message": {"id": "route-u1", "content": "调研 RAG 检索优化论文"},
        "assistant_message_id": "route-a1",
    }
    first = api_client.post("/api/chat/route", json=payload)
    assert first.status_code == 200
    assert first.json()["route"] == "research_run"
    run_id = first.json()["run"]["id"]
    assert first.json()["reason"] == "explicit"

    replay = api_client.post("/api/chat/route", json=payload)
    assert replay.status_code == 200
    assert replay.json()["run"]["id"] == run_id
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_runs WHERE thread_id = ?", (thread["id"],)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM chat_messages WHERE thread_id = ?", (thread["id"],)).fetchone()[0] == 2
    repository = api_client.get(f"/api/chat/threads/{thread['id']}/messages").json()
    assert repository["headId"] == "route-a1"
    assert repository["messages"][0]["content_parts"] == [
        {"type": "text", "text": "调研 RAG 检索优化论文"}
    ]
    card_parts = repository["messages"][1]["content_parts"]
    assert card_parts[-1] == {
        "type": "data",
        "name": "research-run",
        "data": {"run_id": run_id},
    }
    assert "content_parts_json" not in repository["messages"][1]

    conflict = api_client.post(
        "/api/chat/route",
        json={**payload, "user_message": {"id": "route-u1", "content": "different"}},
    )
    assert conflict.status_code == 409


def test_topic_research_without_llm_configuration_fails_explicitly(api_client):
    thread = api_client.post("/api/chat/threads", json={}).json()
    routed = api_client.post(
        "/api/chat/route",
        json={
            "thread_id": thread["id"],
            "mode": "deep_research",
            "user_message": {"id": "missing-llm-u", "content": "调研 RAG 证据链论文"},
            "assistant_message_id": "missing-llm-a",
        },
    )
    assert routed.status_code == 200
    run_id = routed.json()["run"]["id"]
    failed = None
    for _ in range(80):
        snapshot = api_client.get(f"/api/research/runs/{run_id}")
        assert snapshot.status_code == 200
        if snapshot.json()["status"] == "failed":
            failed = snapshot.json()
            break
        import time

        time.sleep(0.02)
    assert failed is not None, json.dumps(snapshot.json(), ensure_ascii=False)
    assert failed["mode"] == "topic"
    assert len(failed["steps"]) == 17
    assert failed["error_code"] == "llm_configuration_unavailable"
    assert failed["error_message"] == "主题调研需要真实模型配置；当前 LLM_API_KEY 未配置。"
    serialized = json.dumps(failed, ensure_ascii=False)
    assert "Authorization" not in serialized
    assert "Bearer" not in serialized
    assert "/Users/" not in serialized


def test_chat_route_replay_skips_unstable_auto_classifier(api_client):
    class UnstableClassifier:
        calls = 0

        def classify(self, _content: str) -> str:
            self.calls += 1
            if self.calls == 1:
                return "research_run"
            raise ChatRoutingUnavailable("routing_unavailable")

    classifier = UnstableClassifier()
    app.dependency_overrides[get_chat_route_classifier] = lambda: classifier
    try:
        thread = api_client.post("/api/chat/threads", json={}).json()
        payload = {
            "thread_id": thread["id"],
            "mode": "auto",
            "user_message": {"id": "auto-replay-u", "content": "RAG 最近有什么值得关注的方向"},
            "assistant_message_id": "auto-replay-a",
        }
        first = api_client.post("/api/chat/route", json=payload)
        replay = api_client.post("/api/chat/route", json=payload)
        assert first.status_code == replay.status_code == 200
        assert replay.json()["run"]["id"] == first.json()["run"]["id"]
        assert replay.json()["reason"] == "model"
        assert classifier.calls == 1
    finally:
        app.dependency_overrides.pop(get_chat_route_classifier, None)


def test_chat_route_rolls_back_every_write_when_run_insert_fails(api_client, monkeypatch):
    thread = api_client.post("/api/chat/threads", json={}).json()

    def injected_failure(*_args, **_kwargs):
        raise RuntimeError("injected after user message")

    monkeypatch.setattr("backend.app.services.chat_routing.insert_topic_research_run", injected_failure)
    with pytest.raises(RuntimeError, match="injected"):
        api_client.post(
            "/api/chat/route",
            json={
                "thread_id": thread["id"],
                "mode": "deep_research",
                "user_message": {"id": "rollback-u", "content": "调研事务回滚"},
                "assistant_message_id": "rollback-a",
            },
        )
    with connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE thread_id = ?", (thread["id"],)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM research_runs WHERE thread_id = ?", (thread["id"],)
        ).fetchone()[0] == 0


def test_chat_stream_redacts_provider_exception_from_sse_and_database(api_client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "configured-test-key")
    get_settings.cache_clear()

    def failing_stream(_self, _messages):
        raise RuntimeError("Authorization: Bearer secret-value /Users/private provider-body")
        yield "unreachable"

    monkeypatch.setattr("backend.app.services.conversations.LLMClient.stream", failing_stream)
    thread = api_client.post("/api/chat/threads", json={}).json()
    response = api_client.post(
        "/api/chat/runs",
        json={
            "thread_id": thread["id"],
            "operation": "append",
            "user_message": {"id": "redact-u", "content": "safe prompt"},
            "assistant_message_id": "redact-a",
        },
    )
    assert response.status_code == 200
    assert "secret-value" not in response.text
    assert "/Users/private" not in response.text
    assert "回答生成失败" in response.text
    with connect() as conn:
        row = conn.execute(
            """
            SELECT m.content, r.error FROM chat_messages m
            JOIN chat_runs r ON r.output_message_id = m.id
            WHERE m.id = 'redact-a'
            """
        ).fetchone()
        assert "secret-value" not in str(dict(row))
        assert row["error"] == "chat_generation_failed"
    get_settings.cache_clear()


def test_chat_route_modes_and_unavailable_classifier_do_not_write(api_client):
    thread = api_client.post("/api/chat/threads", json={}).json()
    normal = api_client.post(
        "/api/chat/route",
        json={
            "thread_id": thread["id"],
            "mode": "normal",
            "user_message": {"id": "normal-u", "content": "任何内容"},
            "assistant_message_id": "normal-a",
        },
    )
    assert normal.json() == {"route": "normal_chat", "reason": "explicit"}
    deterministic = api_client.post(
        "/api/chat/route",
        json={
            "thread_id": thread["id"],
            "mode": "auto",
            "user_message": {"id": "research-u", "content": "请帮我做一份论文综述"},
            "assistant_message_id": "research-a",
        },
    )
    assert deterministic.status_code == 200
    assert deterministic.json()["reason"] == "deterministic"

    ambiguous_thread = api_client.post("/api/chat/threads", json={}).json()
    unavailable = api_client.post(
        "/api/chat/route",
        json={
            "thread_id": ambiguous_thread["id"],
            "mode": "auto",
            "user_message": {"id": "ambiguous-u", "content": "RAG 最近怎么样"},
            "assistant_message_id": "ambiguous-a",
        },
    )
    assert unavailable.status_code == 503
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM chat_messages WHERE thread_id = ?", (ambiguous_thread["id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM research_runs WHERE thread_id = ?", (ambiguous_thread["id"],)).fetchone()[0] == 0


def test_chat_route_hides_another_users_thread(api_client):
    owner_session = api_client.cookies.get("paperwiki_session")
    thread = api_client.post("/api/chat/threads", json={}).json()
    registered = api_client.post(
        "/api/auth/register",
        json={"username": "route_other", "password": "other-password"},
    )
    assert registered.status_code == 201
    other_session = api_client.cookies.get("paperwiki_session")
    assert owner_session and other_session
    for mode in ("normal", "deep_research", "auto"):
        response = api_client.post(
            "/api/chat/route",
            headers={"Cookie": f"paperwiki_session={other_session}"},
            json={
                "thread_id": thread["id"],
                "mode": mode,
                "user_message": {"id": f"other-{mode}-u", "content": "调研私有线程"},
                "assistant_message_id": f"other-{mode}-a",
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Research object not found"
    with connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE thread_id = ?", (thread["id"],)
        ).fetchone()[0] == 0


def test_chat_route_model_classifier_uses_dependency_override(api_client):
    class FakeClassifier:
        def classify(self, content: str) -> str:
            assert content == "一个需要判断的请求"
            return "normal_chat"

    app.dependency_overrides[get_chat_route_classifier] = lambda: FakeClassifier()
    try:
        thread = api_client.post("/api/chat/threads", json={}).json()
        response = api_client.post(
            "/api/chat/route",
            json={
                "thread_id": thread["id"],
                "mode": "auto",
                "user_message": {"id": "model-u", "content": "一个需要判断的请求"},
                "assistant_message_id": "model-a",
            },
        )
        assert response.json() == {"route": "normal_chat", "reason": "model"}
    finally:
        app.dependency_overrides.pop(get_chat_route_classifier, None)


@pytest.mark.parametrize("invalid_output", ["not-json", "{}", '{"route":"other"}'])
def test_chat_route_classifier_rejects_invalid_structured_output(monkeypatch, invalid_output):
    monkeypatch.setattr(
        "backend.app.services.chat_routing.LLMClient.complete",
        lambda *_args, **_kwargs: invalid_output,
    )
    with pytest.raises(ChatRoutingUnavailable, match="routing_unavailable"):
        LLMChatRouteClassifier().classify("ambiguous request")


def test_standalone_research_run_rejects_chat_association(api_client):
    thread = api_client.post("/api/chat/threads", json={}).json()
    response = api_client.post(
        "/api/research/runs",
        json={"title": "invalid", "goal": "must use chat route", "thread_id": thread["id"]},
    )
    assert response.status_code == 422


def test_chat_context_always_contains_full_paper():
    conn = memory_db()
    paper_id = conn.execute("SELECT id FROM papers LIMIT 1").fetchone()["id"]
    thread = create_thread(conn, paper_id)
    full_text = "# Full paper\n\nMETHOD_SENTINEL and all original content."
    conn.execute(
        """
        UPDATE paper_documents SET content_markdown = ?, token_count = 20, status = 'completed'
        WHERE paper_id = ?
        """,
        (full_text, paper_id),
    )
    run = prepare_run(
        conn,
        thread_id=thread["id"],
        user_message={"id": "question", "parent_id": None, "content": "Explain the method."},
        parent_message_id=None,
        assistant_message_id="answer",
        source_message_id=None,
        message_token_limit=0,
    )
    messages = build_model_messages(conn, run)
    assert "METHOD_SENTINEL" in messages[1]["content"]
    assert messages[-1]["content"] == "Explain the method."


def test_api_chat_requires_configured_llm(api_client):
    paper_id = api_client.get("/api/papers?limit=1").json()["items"][0]["id"]
    thread = api_client.post(f"/api/papers/{paper_id}/chat/threads", json={}).json()
    response = api_client.post(
        "/api/chat/runs",
        json={
            "thread_id": thread["id"],
            "user_message": {"id": "u-api", "content": "Question"},
            "assistant_message_id": "a-api",
        },
    )
    assert response.status_code == 503

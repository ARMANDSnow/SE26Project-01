from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.db.migrations import (
    Migration,
    V3_MIGRATION,
    V4_MIGRATION,
    V5_MIGRATION,
    V6_MIGRATION,
    V7_MIGRATION,
    V8_MIGRATION,
    apply_migrations,
)
from backend.app.db.migrations.v7 import migrate_v6_to_v7
from backend.app.db.migrations.v7 import RESEARCH_DATA_SCHEMA_SQL
from backend.app.db.migrations.v8 import migrate_v7_to_v8
from backend.app.db.schema import IncompatibleSchemaError, init_schema
from backend.app.config import get_settings
from backend.app.database import connect, init_db
from backend.app.models import AssetId, AssetInfo, PaperCandidate, PaperSource
from backend.app.repositories.papers import upsert_paper
from backend.app.repositories.research import (
    ResearchConflictError,
    ResearchNotFoundError,
    claim_next_step,
    get_run_snapshot,
    insert_topic_research_run,
    finish_step,
    list_events,
    resolve_decision,
)
from backend.app.repositories.research_data import (
    assert_safe_research_payload,
    create_artifact,
    get_paper_brief,
    list_artifacts,
    list_run_papers,
    reserve_budget,
    upsert_run_paper,
)
from backend.app.repositories.research_citations import list_citations, register_opened_evidence, request_report_regeneration
from backend.app.services.conversations import create_thread
from backend.app.services.llm import LLMProviderError
from backend.app.services.research_agents import CoordinatorAgent, LLMStructuredResearchModel
from backend.app.services.research_contracts import ResearchBrief, ResearchStepError, canonical_arxiv_id
from backend.app.services.research_contracts import (
    ComparisonMatrix, PaperBrief, ResearchReport, ScreeningResult, SearchQueries,
    SynthesisClaims, SynthesisPlan,
)
from backend.app.services.topic_research import TopicResearchPipeline
from backend.app.services.research_tools import build_research_tool_registry
from backend.tests.fixtures import add_test_paper, populate_test_library


def research_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    conn.execute(
        "INSERT INTO users(id, name, username, password_hash, is_active) VALUES (1, 'One', 'one', '!', 1)"
    )
    conn.execute(
        "INSERT INTO users(id, name, username, password_hash, is_active) VALUES (2, 'Two', 'two', '!', 1)"
    )
    populate_test_library(conn)
    return conn


def create_claimed_topic(conn: sqlite3.Connection) -> tuple[dict[str, object], dict[str, object]]:
    thread = create_thread(conn, None, 1, "Topic")
    conn.execute("BEGIN IMMEDIATE")
    run_id = insert_topic_research_run(
        conn,
        user_id=1,
        title="RAG topic",
        goal="Study RAG retrieval",
        thread_id=str(thread["id"]),
    )
    conn.commit()
    step = claim_next_step(conn, worker_id="worker-a", lease_seconds=60)
    assert step is not None
    return get_run_snapshot(conn, run_id, 1), step


def brief(topic: str = "RAG") -> dict[str, object]:
    return ResearchBrief(
        topic=topic,
        research_questions=["How is retrieval evaluated?"],
        scope="Retrieval optimization papers",
        inclusion_criteria=["Contains empirical evaluation"],
        exclusion_criteria=["Not a paper"],
        date_range={"start_year": 2023, "end_year": 2026},
        preferred_sources=["local", "arxiv"],
        output_language="zh-CN",
        constraints=[],
    ).model_dump(mode="json")


def test_structured_model_includes_schema_and_respects_json_mode_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[bool, str]] = []
    monkeypatch.setenv("LLM_JSON_RESPONSE_FORMAT", "false")
    get_settings.cache_clear()

    def complete(
        _self: object,
        system_prompt: str,
        _user_prompt: str,
        json_mode: bool = False,
        *,
        timeout_seconds: float = 120,
        max_attempts: int = 3,
    ) -> str:
        del timeout_seconds, max_attempts
        calls.append((json_mode, system_prompt))
        return json.dumps(brief("Recoverable research"), ensure_ascii=False)

    monkeypatch.setattr(
        "backend.app.services.research_agents.LLMClient.complete",
        complete,
    )

    result = CoordinatorAgent(LLMStructuredResearchModel()).build_brief("Recoverable research")

    assert result.topic == "Recoverable research"
    assert [json_mode for json_mode, _ in calls] == [False]
    assert all('"preferred_sources"' in prompt for _, prompt in calls)
    assert all("Return exactly one JSON object" in prompt for _, prompt in calls)
    get_settings.cache_clear()


def test_structured_model_provider_error_does_not_make_a_hidden_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []
    monkeypatch.setenv("LLM_JSON_RESPONSE_FORMAT", "true")
    get_settings.cache_clear()

    def complete(
        _self: object,
        _system_prompt: str,
        _user_prompt: str,
        json_mode: bool = False,
        *,
        timeout_seconds: float = 120,
        max_attempts: int = 3,
    ) -> str:
        del timeout_seconds, max_attempts
        calls.append(json_mode)
        raise LLMProviderError("provider_http_400")

    monkeypatch.setattr(
        "backend.app.services.research_agents.LLMClient.complete",
        complete,
    )

    with pytest.raises(ResearchStepError) as exc_info:
        CoordinatorAgent(LLMStructuredResearchModel()).build_brief("Recoverable research")

    assert exc_info.value.code == "structured_model_output_invalid"
    assert calls == [True]
    get_settings.cache_clear()


def table_signature(conn: sqlite3.Connection, table: str) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    return (
        [tuple(row) for row in conn.execute(f"PRAGMA table_info({table})")],
        [tuple(row) for row in conn.execute(f"PRAGMA foreign_key_list({table})")],
    )


def test_v7_fresh_v6_and_v2_migrations_match_and_failure_rolls_back() -> None:
    fresh = sqlite3.connect(":memory:")
    fresh.row_factory = sqlite3.Row
    init_schema(fresh)

    from_v6 = sqlite3.connect(":memory:")
    from_v6.row_factory = sqlite3.Row
    init_schema(from_v6)
    from_v6.execute("DROP TABLE research_artifacts")
    from_v6.execute("DROP TABLE research_run_papers")
    from_v6.execute("PRAGMA user_version = 6")
    assert apply_migrations(from_v6, [V7_MIGRATION], target_version=7) == [7]

    from_v2 = sqlite3.connect(":memory:")
    from_v2.row_factory = sqlite3.Row
    from_v2.execute("PRAGMA foreign_keys = ON")
    from_v2.executescript(
        """
        CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE papers(id INTEGER PRIMARY KEY, source TEXT NOT NULL);
        CREATE TABLE notes(id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL, note TEXT NOT NULL, comment TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE reading_history(id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE subscriptions(id INTEGER PRIMARY KEY, topic TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE chat_threads(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id));
        CREATE TABLE chat_messages(id TEXT PRIMARY KEY, content TEXT NOT NULL DEFAULT '');
        PRAGMA user_version = 2;
        """
    )
    assert apply_migrations(
        from_v2,
        [V3_MIGRATION, V4_MIGRATION, V5_MIGRATION, V6_MIGRATION, V7_MIGRATION],
        target_version=7,
    ) == [3, 4, 5, 6, 7]

    for table in ("research_artifacts", "research_run_papers"):
        assert table_signature(from_v2, table) == table_signature(from_v6, table)

    rollback = sqlite3.connect(":memory:")
    rollback.execute("CREATE TABLE research_runs(id TEXT PRIMARY KEY)")
    rollback.execute("CREATE TABLE research_steps(id TEXT PRIMARY KEY)")
    rollback.execute("CREATE TABLE papers(id INTEGER PRIMARY KEY)")
    rollback.execute("PRAGMA user_version = 6")

    def fail_v7(db: sqlite3.Connection) -> None:
        migrate_v6_to_v7(db)
        raise RuntimeError("injected v7 failure")

    with pytest.raises(RuntimeError, match="injected v7"):
        apply_migrations(rollback, [Migration(7, "fail-v7", fail_v7)], target_version=7)
    assert rollback.execute("PRAGMA user_version").fetchone()[0] == 6
    assert rollback.execute("SELECT 1 FROM sqlite_master WHERE name = 'research_artifacts'").fetchone() is None
    assert rollback.execute("SELECT 1 FROM sqlite_master WHERE name = 'research_run_papers'").fetchone() is None


def test_forged_v7_missing_required_index_fails_closed() -> None:
    conn = research_db()
    conn.execute("DROP INDEX idx_research_run_papers_stage")
    with pytest.raises(IncompatibleSchemaError, match="topic research schema"):
        init_schema(conn)

    forged = research_db()
    sql = forged.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'research_artifacts'"
    ).fetchone()[0]
    forged.execute("PRAGMA foreign_keys = OFF")
    forged.execute("ALTER TABLE research_artifacts RENAME TO research_artifacts_valid")
    forged.execute(str(sql).replace("CHECK(version >= 1)", "CHECK(version >= 0)"))
    forged.execute("DROP TABLE research_artifacts_valid")
    forged.execute(
        "CREATE INDEX idx_research_artifacts_run_type ON research_artifacts(run_id, artifact_type, version DESC)"
    )
    forged.execute(
        "CREATE INDEX idx_research_artifacts_paper ON research_artifacts(paper_id, artifact_type, version DESC)"
    )
    forged.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(IncompatibleSchemaError, match="topic research schema"):
        init_schema(forged)


def test_v8_fresh_v7_and_v2_migrations_match_and_failure_rolls_back() -> None:
    fresh = sqlite3.connect(":memory:")
    fresh.row_factory = sqlite3.Row
    fresh.execute("PRAGMA foreign_keys = ON")
    init_schema(fresh)

    from_v7 = sqlite3.connect(":memory:")
    from_v7.row_factory = sqlite3.Row
    from_v7.execute("PRAGMA foreign_keys = ON")
    init_schema(from_v7)
    from_v7.execute("PRAGMA foreign_keys = OFF")
    from_v7.execute("DROP TABLE research_citations")
    from_v7.execute("DROP TABLE research_evidence")
    from_v7.execute("DROP TABLE research_model_calls")
    from_v7.execute("DROP INDEX idx_research_artifacts_run_type")
    from_v7.execute("DROP INDEX idx_research_artifacts_paper")
    from_v7.execute("ALTER TABLE research_artifacts RENAME TO research_artifacts_v8")
    from_v7.execute(RESEARCH_DATA_SCHEMA_SQL.split(";")[0])
    from_v7.execute("""
        INSERT INTO research_artifacts(
            id, run_id, paper_id, artifact_type, schema_version, source_step_id,
            version, status, content_json, source_hash, idempotency_key,
            content_hash, created_at, updated_at
        )
        SELECT id, run_id, paper_id, artifact_type, schema_version, source_step_id,
               version, status, content_json, source_hash, idempotency_key,
               content_hash, created_at, updated_at
        FROM research_artifacts_v8
    """)
    from_v7.execute("DROP TABLE research_artifacts_v8")
    from_v7.execute("CREATE INDEX idx_research_artifacts_run_type ON research_artifacts(run_id, artifact_type, version DESC)")
    from_v7.execute("CREATE INDEX idx_research_artifacts_paper ON research_artifacts(paper_id, artifact_type, version DESC)")
    from_v7.execute("PRAGMA foreign_keys = ON")
    from_v7.execute("PRAGMA user_version = 7")
    assert apply_migrations(from_v7, [V8_MIGRATION], target_version=8) == [8]

    from_v2 = sqlite3.connect(":memory:")
    from_v2.row_factory = sqlite3.Row
    from_v2.execute("PRAGMA foreign_keys = ON")
    from_v2.executescript("""
        CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE papers(id INTEGER PRIMARY KEY, source TEXT NOT NULL);
        CREATE TABLE notes(id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL, note TEXT NOT NULL, comment TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE reading_history(id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE subscriptions(id INTEGER PRIMARY KEY, topic TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE chat_threads(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id));
        CREATE TABLE chat_messages(id TEXT PRIMARY KEY, content TEXT NOT NULL DEFAULT '');
        PRAGMA user_version = 2;
    """)
    assert apply_migrations(from_v2, [V3_MIGRATION, V4_MIGRATION, V5_MIGRATION, V6_MIGRATION, V7_MIGRATION, V8_MIGRATION], target_version=8) == [3, 4, 5, 6, 7, 8]
    for table in ("research_artifacts", "research_model_calls", "research_evidence", "research_citations"):
        assert table_signature(from_v2, table) == table_signature(from_v7, table)

    rollback = sqlite3.connect(":memory:")
    rollback.row_factory = sqlite3.Row
    rollback.execute("PRAGMA foreign_keys = ON")
    from_v2.backup(rollback)
    rollback.execute("DROP TABLE research_citations")
    rollback.execute("DROP TABLE research_evidence")
    rollback.execute("DROP TABLE research_model_calls")
    rollback.execute("PRAGMA user_version = 7")

    def fail_v8(db: sqlite3.Connection) -> None:
        migrate_v7_to_v8(db)
        raise RuntimeError("injected v8 failure")

    with pytest.raises(RuntimeError, match="injected v8"):
        apply_migrations(rollback, [Migration(8, "fail-v8", fail_v8)], target_version=8)
    assert rollback.execute("PRAGMA user_version").fetchone()[0] == 7
    assert rollback.execute("SELECT 1 FROM sqlite_master WHERE name = 'research_citations'").fetchone() is None


def test_forged_v8_model_call_constraint_fails_closed() -> None:
    conn = research_db()
    sql = str(conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'research_model_calls'").fetchone()[0])
    conn.execute("DROP TABLE research_model_calls")
    conn.execute(sql.replace("CHECK(length(input_hash) = 64)", "CHECK(length(input_hash) >= 1)"))
    with pytest.raises(IncompatibleSchemaError, match="citation schema"):
        init_schema(conn)


def test_synthesis_contracts_reject_duplicate_claims_and_cross_paper_matrix_citations() -> None:
    duplicate = {"claim_id": "same", "claim": "Supported fact", "claim_type": "finding", "confidence": 0.9, "supporting_citations": ["C1"], "contradicting_citations": [], "covered_paper_ids": [1], "caveats": [], "schema_version": 1}
    with pytest.raises(ValueError, match="identities must be unique"):
        SynthesisClaims.model_validate({"claims": [duplicate, duplicate], "schema_version": 1})

    matrix = ComparisonMatrix.model_validate({
        "dimensions": ["method"],
        "papers": [{"paper_id": 1, "title": "A"}, {"paper_id": 2, "title": "B"}],
        "cells": [{"cell_id": "cell-a", "dimension": "method", "paper_id": 1, "value": "Claim about A", "citation_keys": ["C2"], "evidence_ids": ["EV-" + "b" * 24]}],
        "agreements": [], "disagreements": [], "missing_evidence": [], "schema_version": 1,
    })
    briefs = [SimpleNamespace(paper_id=1, title="A"), SimpleNamespace(paper_id=2, title="B")]
    candidates = [
        {"citation_key": "C1", "paper_id": 1, "evidence_id": "EV-" + "a" * 24},
        {"citation_key": "C2", "paper_id": 2, "evidence_id": "EV-" + "b" * 24},
    ]
    with pytest.raises(ResearchStepError) as exc_info:
        TopicResearchPipeline._validate_matrix(matrix, candidates, briefs)  # type: ignore[arg-type]
    assert exc_info.value.code == "comparison_evidence_invalid"


def test_report_validation_requires_exact_statement_citation_pair() -> None:
    claims = SynthesisClaims.model_validate({
        "claims": [{
            "claim_id": "claim-a", "claim": "Evidence is mixed.", "claim_type": "finding",
            "confidence": 0.8, "supporting_citations": ["C1"], "contradicting_citations": ["C2"],
            "covered_paper_ids": [1, 2], "caveats": [], "schema_version": 1,
        }],
        "schema_version": 1,
    })
    matrix = ComparisonMatrix.model_validate({
        "dimensions": ["method"], "papers": [{"paper_id": 1, "title": "A"}],
        "cells": [{
            "cell_id": "cell-a", "dimension": "method", "paper_id": 1,
            "value": "A separate matrix fact.", "citation_keys": ["C3"],
            "evidence_ids": ["EV-" + "a" * 24],
        }],
        "agreements": [], "disagreements": [], "missing_evidence": [], "schema_version": 1,
    })
    incomplete = {"statement_id": "s1", "text": "Evidence is mixed.", "citation_keys": ["C1"]}
    report = ResearchReport.model_validate({
        "title": "Report", "topic": "Topic", "executive_summary": [incomplete],
        "research_questions": ["Question?"], "findings": [dict(incomplete, statement_id="s2")],
        "agreements": [], "disagreements": [], "limitations": [], "research_gaps": [],
        "conclusion": [dict(incomplete, statement_id="s3")], "citation_keys": ["C1"],
        "generated_from_artifact_versions": {"synthesis_plan": 1}, "schema_version": 1,
    })

    with pytest.raises(ResearchStepError) as exc_info:
        TopicResearchPipeline._validate_report_statement_pairs(report, claims, matrix)
    assert exc_info.value.code == "report_statement_unverified"


def test_artifacts_version_without_overwrite_and_owner_isolation() -> None:
    conn = research_db()
    run, step = create_claimed_topic(conn)
    args = {
        "run_id": str(run["id"]),
        "source_step_id": str(step["id"]),
        "worker_id": "worker-a",
        "lease_generation": int(step["lease_generation"]),
        "artifact_type": "research_brief",
    }
    first = create_artifact(conn, **args, content=brief(), idempotency_key="brief:one")
    replay = create_artifact(conn, **args, content=brief(), idempotency_key="brief:one")
    second = create_artifact(conn, **args, content=brief("Graph RAG"), idempotency_key="brief:two")
    assert first["id"] == replay["id"]
    assert first["version"] == 1 and second["version"] == 2
    assert [item["version"] for item in list_artifacts(conn, str(run["id"]), 1)] == [2, 1]
    with pytest.raises(ResearchNotFoundError):
        list_artifacts(conn, str(run["id"]), 2)


def test_run_paper_dedup_stage_reasons_and_paper_brief_source_hash_invalidation() -> None:
    conn = research_db()
    run, step = create_claimed_topic(conn)
    paper_id = add_test_paper(conn, source_id="abcde.0001", title="Topic Paper")
    base = {
        "run_id": str(run["id"]),
        "source_step_id": str(step["id"]),
        "worker_id": "worker-a",
        "lease_generation": int(step["lease_generation"]),
        "paper_id": paper_id,
    }
    upsert_run_paper(conn, **base, stage="candidate")
    upsert_run_paper(conn, **base, stage="candidate")
    upsert_run_paper(conn, **base, stage="selected", rank=1, score=0.95, inclusion_reason="Directly relevant")
    document = conn.execute("SELECT source_hash FROM paper_documents WHERE paper_id = ?", (paper_id,)).fetchone()
    source_hash = str(document["source_hash"])
    conn.execute("UPDATE papers SET asset_id = ? WHERE id = ?", (f"sha256:{source_hash}", paper_id))
    conn.commit()
    upsert_run_paper(conn, **base, stage="fulltext_ready", source_hash=source_hash)
    upsert_run_paper(conn, **base, stage="read", source_hash=source_hash)
    assert len(list_run_papers(conn, str(run["id"]), 1)) == 1

    paper = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    chunk = conn.execute("SELECT * FROM paper_chunks WHERE paper_id = ? ORDER BY id LIMIT 1", (paper_id,)).fetchone()
    content = {
        "paper_id": paper_id,
        "source": paper["source"],
        "source_id": paper["source_id"],
        "title": paper["title"],
        "authors": __import__("json").loads(paper["authors_json"]),
        "year": int(paper["published_at"][:4]),
        "research_question": "How is evidence retrieved?",
        "method": "Chunk retrieval",
        "dataset": "Local benchmark",
        "experiments": "Retrieval recall",
        "key_findings": ["Evidence improves traceability"],
        "limitations": ["Small benchmark"],
        "relevance": "Directly addresses the brief",
        "evidence_ids": [{
            "chunk_id": int(chunk["id"]), "paper_id": paper_id,
            "source_hash": source_hash, "chunk_index": int(chunk["chunk_index"]),
            "char_start": int(chunk["char_start"]), "char_end": int(chunk["char_end"]),
            "heading": chunk["heading"],
        }],
        "source_hash": source_hash,
        "schema_version": 1,
    }
    opened = register_opened_evidence(
        conn, run_id=str(run["id"]), step_id=str(step["id"]), worker_id="worker-a",
        lease_generation=int(step["lease_generation"]), user_id=1, chunk_id=int(chunk["id"]),
    )
    content["evidence_ids"][0]["evidence_id"] = opened["id"]
    create_artifact(
        conn,
        **{key: base[key] for key in ("run_id", "source_step_id", "worker_id", "lease_generation")},
        artifact_type="paper_brief",
        content=content,
        idempotency_key="paper-brief:one",
        paper_id=paper_id,
        source_hash=source_hash,
    )
    unopened = dict(content)
    unopened["evidence_ids"] = [dict(content["evidence_ids"][0], evidence_id="EV-" + "f" * 24)]
    with pytest.raises(ResearchConflictError, match="not opened"):
        create_artifact(
            conn,
            **{key: base[key] for key in ("run_id", "source_step_id", "worker_id", "lease_generation")},
            artifact_type="paper_brief", content=unopened, idempotency_key="paper-brief:unopened",
            paper_id=paper_id, source_hash=source_hash,
        )
    conn.execute("UPDATE paper_chunks SET content = content || ' tampered' WHERE id = ?", (int(chunk["id"]),))
    conn.commit()
    with pytest.raises(ResearchConflictError, match="not opened"):
        create_artifact(
            conn,
            **{key: base[key] for key in ("run_id", "source_step_id", "worker_id", "lease_generation")},
            artifact_type="paper_brief", content=content, idempotency_key="paper-brief:tampered-quote",
            paper_id=paper_id, source_hash=source_hash,
        )
    conn.execute("UPDATE paper_chunks SET content = ? WHERE id = ?", (str(chunk["content"]), int(chunk["id"])))
    conn.commit()
    with pytest.raises(ResearchConflictError, match="requires a paper relation"):
        create_artifact(
            conn,
            **{key: base[key] for key in ("run_id", "source_step_id", "worker_id", "lease_generation")},
            artifact_type="paper_brief",
            content=content,
            idempotency_key="paper-brief:missing-relation",
        )
    forged_evidence = dict(content)
    forged_evidence["evidence_ids"] = [dict(content["evidence_ids"][0], paper_id=paper_id + 1)]
    with pytest.raises(ResearchConflictError, match="evidence identity"):
        create_artifact(
            conn,
            **{key: base[key] for key in ("run_id", "source_step_id", "worker_id", "lease_generation")},
            artifact_type="paper_brief",
            content=forged_evidence,
            idempotency_key="paper-brief:forged-evidence",
            paper_id=paper_id,
            source_hash=source_hash,
        )
    assert get_paper_brief(conn, str(run["id"]), paper_id, 1)["is_current"] is True
    conn.execute("UPDATE papers SET asset_id = ? WHERE id = ?", (f"sha256:{'f' * 64}", paper_id))
    conn.commit()
    assert get_paper_brief(conn, str(run["id"]), paper_id, 1)["is_current"] is False
    conn.execute("UPDATE papers SET asset_id = ? WHERE id = ?", (f"sha256:{source_hash}", paper_id))
    conn.commit()
    assert get_paper_brief(conn, str(run["id"]), paper_id, 1)["is_current"] is True
    conn.execute(
        "UPDATE paper_documents SET source_hash = ? WHERE paper_id = ?",
        ("f" * 64, paper_id),
    )
    conn.commit()
    assert get_paper_brief(conn, str(run["id"]), paper_id, 1)["is_current"] is False


def test_withdrawn_public_upload_is_removed_from_aggregate_artifact_step_and_events() -> None:
    conn = research_db()
    run, step = create_claimed_topic(conn)
    paper_id = int(
        upsert_paper(
            conn,
            PaperCandidate(
                source=PaperSource.UPLOAD,
                source_id="owner-two-upload",
                title="Private after withdrawal",
                authors=("Owner Two",),
                abstract="Sensitive uploaded abstract",
                categories=("manual",),
                primary_category="manual",
                published_at="2025-01-01",
            ),
        )
    )
    conn.execute(
        """
        INSERT INTO paper_uploads(
            paper_id, owner_user_id, visibility, provenance, moderation_status, original_filename
        ) VALUES (?, 2, 'public', 'user_upload', 'unreviewed', 'private.pdf')
        """,
        (paper_id,),
    )
    conn.commit()
    upsert_run_paper(
        conn,
        run_id=str(run["id"]),
        source_step_id=str(step["id"]),
        worker_id="worker-a",
        lease_generation=int(step["lease_generation"]),
        paper_id=paper_id,
        stage="candidate",
    )
    create_artifact(
        conn,
        run_id=str(run["id"]),
        source_step_id=str(step["id"]),
        worker_id="worker-a",
        lease_generation=int(step["lease_generation"]),
        artifact_type="candidate_papers",
        idempotency_key="candidate:upload",
        content={
            "items": [{
                "paper_id": paper_id,
                "source": "upload",
                "source_id": "owner-two-upload",
                "title": "Private after withdrawal",
                "authors": ["Owner Two"],
                "abstract": "Sensitive uploaded abstract",
                "categories": ["manual"],
                "primary_category": "manual",
                "published_at": "2025-01-01",
            }],
            "schema_version": 1,
        },
    )
    conn.execute(
        "UPDATE research_steps SET output_json = ? WHERE id = ?",
        (__import__("json").dumps({"evidence_refs": {str(paper_id): [{"chunk_id": 1}]}}), step["id"]),
    )
    conn.commit()
    assert list_artifacts(conn, str(run["id"]), 1, artifact_type="candidate_papers")[0]["content"]["items"]
    conn.execute("UPDATE paper_uploads SET visibility = 'private' WHERE paper_id = ?", (paper_id,))
    conn.commit()
    artifact = list_artifacts(conn, str(run["id"]), 1, artifact_type="candidate_papers")[0]
    assert artifact["content"]["items"] == []
    assert list_run_papers(conn, str(run["id"]), 1) == []
    snapshot = get_run_snapshot(conn, str(run["id"]), 1)
    assert snapshot["steps"][0]["output"]["evidence_refs"] == {}
    events = list_events(conn, str(run["id"]), 1, after_id=0)
    paper_events = [item for item in events if item["event_type"] == "paper.updated"]
    assert paper_events and paper_events[-1]["payload"] == {"paper_withdrawn": True}


def test_budget_boundary_creates_real_decision_and_continue_updates_cap() -> None:
    conn = research_db()
    run, step = create_claimed_topic(conn)
    conn.execute(
        "UPDATE research_runs SET budget_json = json_set(budget_json, '$.max_tool_calls', 0) WHERE id = ?",
        (run["id"],),
    )
    conn.commit()
    assert reserve_budget(
        conn,
        run_id=str(run["id"]),
        step_id=str(step["id"]),
        worker_id="worker-a",
        lease_generation=int(step["lease_generation"]),
        kind="tool_calls",
    ) is False
    waiting = get_run_snapshot(conn, str(run["id"]), 1)
    assert waiting["status"] == "waiting_input"
    decision = waiting["decisions"][0]
    resumed = resolve_decision(conn, decision["id"], 1, "continue")
    assert resumed["status"] == "queued"
    reclaimed = claim_next_step(conn, worker_id="worker-b", lease_seconds=60)
    assert reclaimed is not None
    assert reserve_budget(
        conn,
        run_id=str(run["id"]),
        step_id=str(reclaimed["id"]),
        worker_id="worker-b",
        lease_generation=int(reclaimed["lease_generation"]),
        kind="tool_calls",
    ) is True


def test_tool_registry_contracts_and_research_state_redaction() -> None:
    registry = build_research_tool_registry()
    assert {definition.name for definition in registry.definitions()} == {
        "local_paper_search", "arxiv_search", "deduplicated_import", "fetch_document",
        "parse_document", "chunk_search", "open_evidence",
    }
    for definition in registry.definitions():
        assert definition.input_model.model_json_schema()["type"] == "object"
        assert definition.output_model.model_json_schema()["type"] == "object"
        assert definition.owner_scope in {"run_owner", "paper_access"}
        assert definition.timeout_seconds > 0
        assert definition.retry_policy.max_attempts >= 1
        assert definition.redaction_strategy
        assert definition.error_codes
    for secret in (
        "Authorization: Bearer abcdef123456",
        "sk-1234567890abcdef",
        "/Users/example/private.pdf",
        "C:\\Users\\example\\private.pdf",
    ):
        with pytest.raises(ValueError, match="unsafe research"):
            assert_safe_research_payload({"summary": secret})


def test_arxiv_identity_is_canonical_across_versions_and_old_style_ids() -> None:
    assert canonical_arxiv_id("https://arxiv.org/abs/2401.12345v3") == "2401.12345"
    assert canonical_arxiv_id("https://arxiv.org/abs/math/0301234v2") == "math/0301234"


class DeterministicStructuredModel:
    """Strict test substitute injected through the production agent contract."""

    def generate(self, model: type[Any], *, system_prompt: str, input_data: dict[str, Any]) -> Any:
        del system_prompt
        if model is ResearchBrief:
            payload: dict[str, Any] = brief("RAG evidence grounding")
        elif model is SearchQueries:
            payload = {"queries": ["RAG evidence grounding"], "categories": ["cs.CL"], "schema_version": 1}
        elif model is ScreeningResult:
            payload = {
                "items": [
                    {
                        "paper_id": int(item["paper_id"]),
                        "selected": index == 0,
                        "score": 0.95 if index == 0 else 0.2,
                        "rank": 1 if index == 0 else None,
                        "inclusion_reason": "Direct empirical evidence" if index == 0 else None,
                        "exclusion_reason": None if index == 0 else "Outside the focused evidence scope",
                    }
                    for index, item in enumerate(input_data["candidates"])
                ],
                "schema_version": 1,
            }
        elif model is PaperBrief:
            paper = input_data["paper"]
            opened = input_data["opened_evidence"]
            payload = {
                "paper_id": int(paper["paper_id"]),
                "source": paper["source"],
                "source_id": paper["source_id"],
                "title": paper["title"],
                "authors": paper["authors"],
                "year": int(str(paper["published_at"])[:4]),
                "research_question": "How does retrieval improve grounded answers?",
                "method": "Retrieve evidence chunks before answer generation.",
                "dataset": "A citation-grounding benchmark.",
                "experiments": "Citation accuracy and retrieval recall.",
                "key_findings": ["Retrieved evidence improves traceability."],
                "limitations": ["The benchmark is small."],
                "relevance": "Directly answers the configured research brief.",
                "evidence_ids": [item["evidence"] for item in opened],
                "source_hash": input_data["source_hash"],
                "schema_version": 1,
            }
        elif model is SynthesisPlan:
            payload = {
                "topic": "RAG evidence grounding",
                "research_questions": ["How does retrieval improve grounding?"],
                "comparison_dimensions": ["method"],
                "synthesis_strategy": "Compare evidence-grounding methods using opened chunks.",
                "expected_outputs": ["comparison matrix", "cited report"],
                "constraints": ["Use verified citations only"],
                "schema_version": 1,
            }
        elif model is ComparisonMatrix:
            paper = input_data["paper_briefs"][0]
            citation = input_data["citation_candidates"][0]
            payload = {
                "dimensions": ["method"],
                "papers": [{"paper_id": paper["paper_id"], "title": paper["title"]}],
                "cells": [{"cell_id": "cell-1", "dimension": "method", "paper_id": paper["paper_id"], "value": paper["method"], "citation_keys": [citation["citation_key"]], "evidence_ids": [citation["evidence_id"]]}],
                "agreements": [], "disagreements": [], "missing_evidence": [], "schema_version": 1,
            }
        elif model is SynthesisClaims:
            citation = input_data["citation_candidates"][0]
            paper_id = input_data["comparison_matrix"]["papers"][0]["paper_id"]
            payload = {"claims": [{"claim_id": "claim-1", "claim": "Opened evidence supports retrieval-grounded generation.", "claim_type": "finding", "confidence": 0.9, "supporting_citations": [citation["citation_key"]], "contradicting_citations": [], "covered_paper_ids": [paper_id], "caveats": [], "schema_version": 1}], "schema_version": 1}
        elif model is ResearchReport:
            key = input_data["valid_citation_keys"][0]
            statement = {"statement_id": "report-1", "text": "Opened evidence supports retrieval-grounded generation.", "citation_keys": [key]}
            payload = {
                "title": "RAG Evidence Grounding", "topic": "RAG evidence grounding",
                "executive_summary": [statement], "research_questions": ["How does retrieval improve grounding?"],
                "findings": [dict(statement, statement_id="finding-1")], "agreements": [], "disagreements": [],
                "limitations": ["The dataset contains one paper."], "research_gaps": ["Broader evaluation is needed."],
                "conclusion": [dict(statement, statement_id="conclusion-1")], "citation_keys": [key],
                "generated_from_artifact_versions": input_data["generated_from_artifact_versions"], "schema_version": 1,
            }
        else:  # pragma: no cover - fails loudly if an agent contract expands
            raise AssertionError(f"unexpected structured model: {model}")
        return model.model_validate(payload)


def test_topic_pipeline_completes_and_reuses_paper_document_with_injected_dependencies(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "topic.sqlite3"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()
    init_db()
    source_hash = "abcde0001" + "0" * 55
    with connect() as conn:
        conn.execute(
            "INSERT INTO users(id, name, username, password_hash, is_active) VALUES (1, 'One', 'one', '!', 1)"
        )
        paper_id = add_test_paper(conn, source_id="abcde.0001", title="RAG Evidence Grounding")
        conn.execute(
            "UPDATE papers SET asset_id = ? WHERE id = ?",
            (f"sha256:{source_hash}", paper_id),
        )
        conn.commit()

    monkeypatch.setattr("backend.app.services.research_tools.fetch_arxiv_papers", lambda *_args: [])
    monkeypatch.setattr(
        "backend.app.services.research_tools.PaperPdfService.ensure",
        lambda _self, _paper_id, **_kwargs: AssetInfo(id=AssetId(f"sha256:{source_hash}"), size_bytes=1_024),
    )
    pipeline = TopicResearchPipeline(model=DeterministicStructuredModel())

    def execute_run(title: str) -> str:
        with connect() as conn:
            thread = create_thread(conn, None, 1, title)
            conn.execute("BEGIN IMMEDIATE")
            run_id = insert_topic_research_run(
                conn,
                user_id=1,
                title=title,
                goal="Study RAG evidence grounding",
                thread_id=str(thread["id"]),
            )
            conn.commit()
        for _ in range(17):
            with connect() as conn:
                step = claim_next_step(conn, worker_id="pipeline-test", lease_seconds=60)
            assert step is not None
            output = pipeline.handle(step)
            with connect() as conn:
                assert finish_step(
                    conn,
                    step_id=str(step["id"]),
                    worker_id="pipeline-test",
                    lease_generation=int(step["lease_generation"]),
                    output=output,
                )
        return run_id

    first_id = execute_run("First topic run")
    second_id = execute_run("Second topic run")
    with connect() as conn:
        regenerated = request_report_regeneration(conn, first_id, 1)
        assert regenerated["status"] == "queued"
    for _ in range(7):
        with connect() as conn:
            step = claim_next_step(conn, worker_id="regeneration-test", lease_seconds=60)
        assert step is not None and step["run_id"] == first_id
        output = pipeline.handle(step)
        with connect() as conn:
            assert finish_step(conn, step_id=str(step["id"]), worker_id="regeneration-test", lease_generation=int(step["lease_generation"]), output=output)
    with connect() as conn:
        first = get_run_snapshot(conn, first_id, 1)
        second = get_run_snapshot(conn, second_id, 1)
        assert first["status"] == second["status"] == "completed"
        assert len(first["steps"]) == len(second["steps"]) == 17
        assert first["usage"]["model_calls"] == 12
        assert second["usage"]["model_calls"] == 8
        assert first["usage"]["tool_calls"] > 0
        first_papers = list_run_papers(conn, first_id, 1)
        second_papers = list_run_papers(conn, second_id, 1)
        assert [item["paper_id"] for item in first_papers] == [paper_id]
        assert [item["paper_id"] for item in second_papers] == [paper_id]
        assert first_papers[0]["stage"] == second_papers[0]["stage"] == "extracted"
        assert get_paper_brief(conn, first_id, paper_id, 1)["is_current"] is True
        assert get_paper_brief(conn, second_id, paper_id, 1)["is_current"] is True
        assert conn.execute("SELECT COUNT(*) FROM papers WHERE source_id = 'abcde.0001'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM paper_documents WHERE paper_id = ?", (paper_id,)).fetchone()[0] == 1
        citations = list_citations(conn, first_id, 1)
        assert citations and {item["status"] for item in citations} == {"valid", "stale"}
        assert {item["status"] for item in citations if item["artifact_version"] == 2} == {"valid"}
        with pytest.raises(ResearchNotFoundError):
            list_citations(conn, first_id, 2)
        reports = list_artifacts(conn, first_id, 1, artifact_type="research_report")
        assert reports[0]["is_current"] is True
        assert [item["version"] for item in reports] == [2, 1]
        assert reports[1]["status"] == "stale"
        assert {item["artifact_version"] for item in citations} == {1, 2}
        conn.execute("UPDATE papers SET asset_id = ? WHERE id = ?", ("sha256:" + "f" * 64, paper_id))
        conn.commit()
        assert {item["status"] for item in list_citations(conn, first_id, 1)} == {"stale"}
        assert list_artifacts(conn, first_id, 1, artifact_type="research_report")[0]["is_current"] is False
    get_settings.cache_clear()

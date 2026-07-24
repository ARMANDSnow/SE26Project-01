from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from backend.app.db.migrations import (
    V3_MIGRATION,
    V4_MIGRATION,
    V5_MIGRATION,
    V6_MIGRATION,
    V7_MIGRATION,
    V8_MIGRATION,
    apply_migrations,
)
from backend.app.db.migrations.runner import Migration
from backend.app.db.migrations.v9 import MIGRATION as V9_MIGRATION, migrate_v8_to_v9
from backend.app.db.schema import IncompatibleSchemaError, init_schema
from backend.app.repositories.projects import (
    _dependency_status,
    add_project_item,
    create_project,
    create_project_analysis_run,
    delete_project,
    get_project_analysis_inputs,
    get_project,
    list_project_items,
    project_backlinks,
    remove_project_item,
    reorder_project_items,
    set_project_status,
    update_project,
    validate_project_inputs,
)
from backend.app.repositories.research import ResearchConflictError, ResearchNotFoundError


def _legacy_v2() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE papers(id INTEGER PRIMARY KEY, source TEXT NOT NULL);
        CREATE TABLE notes(id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL,
            note TEXT NOT NULL, comment TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE reading_history(id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL,
            action TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE subscriptions(id INTEGER PRIMARY KEY, topic TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE chat_threads(id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id));
        CREATE TABLE chat_messages(id TEXT PRIMARY KEY, content TEXT NOT NULL DEFAULT '');
        PRAGMA user_version = 2;
        """
    )
    return conn


def _to_v8(conn: sqlite3.Connection) -> None:
    apply_migrations(
        conn,
        [
            V3_MIGRATION,
            V4_MIGRATION,
            V5_MIGRATION,
            V6_MIGRATION,
            V7_MIGRATION,
            V8_MIGRATION,
        ],
        target_version=8,
    )


def _signature(conn: sqlite3.Connection, table: str) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]], list[tuple[object, ...]]]:
    return (
        [tuple(row) for row in conn.execute(f"PRAGMA table_info({table})")],
        [tuple(row) for row in conn.execute(f"PRAGMA foreign_key_list({table})")],
        [tuple(row) for row in conn.execute(f"PRAGMA index_list({table})")],
    )


def test_v9_fresh_v8_and_v2_match_and_migration_rolls_back() -> None:
    fresh = sqlite3.connect(":memory:")
    fresh.row_factory = sqlite3.Row
    fresh.execute("PRAGMA foreign_keys = ON")
    init_schema(fresh)

    from_v8 = _legacy_v2()
    _to_v8(from_v8)
    assert apply_migrations(from_v8, [V9_MIGRATION], target_version=9) == [9]

    from_v2 = _legacy_v2()
    assert apply_migrations(
        from_v2,
        [
            V3_MIGRATION,
            V4_MIGRATION,
            V5_MIGRATION,
            V6_MIGRATION,
            V7_MIGRATION,
            V8_MIGRATION,
            V9_MIGRATION,
        ],
        target_version=9,
    ) == [3, 4, 5, 6, 7, 8, 9]

    for table in (
        "research_projects",
        "research_project_items",
        "research_runs",
        "research_artifacts",
        "research_artifact_dependencies",
        "research_project_citation_refs",
        "research_citations",
        "research_steps",
        "research_events",
        "research_decisions",
        "research_model_calls",
        "research_evidence",
        "research_run_papers",
    ):
        assert _signature(from_v8, table) == _signature(fresh, table)
        assert _signature(from_v2, table) == _signature(fresh, table)
    assert fresh.execute("PRAGMA foreign_key_check").fetchall() == []
    assert from_v8.execute("PRAGMA foreign_key_check").fetchall() == []
    assert from_v2.execute("PRAGMA foreign_key_check").fetchall() == []

    rollback = _legacy_v2()
    _to_v8(rollback)

    def fail_v9(db: sqlite3.Connection) -> None:
        migrate_v8_to_v9(db)
        raise RuntimeError("injected v9 failure")

    with pytest.raises(RuntimeError, match="injected v9"):
        apply_migrations(rollback, [Migration(9, "fail-v9", fail_v9)], target_version=9)
    assert rollback.execute("PRAGMA user_version").fetchone()[0] == 8
    assert rollback.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'research_projects'"
    ).fetchone() is None
    assert rollback.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'research_runs'"
    ).fetchone() is not None
    assert rollback.execute("PRAGMA foreign_key_check").fetchall() == []


def test_forged_v9_missing_project_unique_index_fails_closed() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    conn.execute("DROP INDEX idx_project_items_unique_report")
    with pytest.raises(IncompatibleSchemaError, match="project schema"):
        init_schema(conn)


def _repository_db() -> tuple[sqlite3.Connection, int, str, str]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    conn.executemany(
        """
        INSERT INTO users(id, name, username, password_hash, is_active)
        VALUES (?, ?, ?, '!', 1)
        """,
        [(1, "Owner", "owner"), (2, "Other", "other")],
    )
    conn.execute(
        """
        INSERT INTO papers(
            id, source, source_id, title, authors_json, abstract, categories_json,
            primary_category, published_at, processing_status
        ) VALUES (1, 'arxiv', '2501.00001', 'Traceable RAG', '["A"]',
                  'Evidence-aware retrieval', '["cs.AI"]', 'cs.AI', '2025-01-01', 'pending')
        """
    )
    conn.execute(
        "INSERT INTO chat_threads(id, user_id, title) VALUES ('thread-1', 1, 'Research')"
    )
    run_id = "run-source"
    step_id = "step-source"
    conn.execute(
        """
        INSERT INTO research_runs(id, user_id, thread_id, title, goal, mode, status)
        VALUES (?, 1, 'thread-1', 'Source run', 'Study RAG', 'topic', 'completed')
        """,
        (run_id,),
    )
    conn.execute(
        """
        INSERT INTO research_steps(
            id, run_id, step_key, step_type, title, agent_name, status, position,
            idempotency_key
        ) VALUES (?, ?, 'report_generation', 'topic.report_generation', 'Report',
                  'Report Agent', 'completed', 0, 'source-report')
        """,
        (step_id, run_id),
    )
    report = {
        "title": "Traceable report",
        "topic": "RAG",
        "executive_summary": [
            {"statement_id": "s1", "text": "Evidence is required.", "citation_keys": ["C1"]}
        ],
        "research_questions": ["How?"],
        "findings": [
            {"statement_id": "s2", "text": "Evidence is required.", "citation_keys": ["C1"]}
        ],
        "agreements": [],
        "disagreements": [],
        "limitations": [],
        "research_gaps": [],
        "conclusion": [
            {"statement_id": "s3", "text": "Evidence is required.", "citation_keys": ["C1"]}
        ],
        "citation_keys": ["C1"],
        "generated_from_artifact_versions": {"synthesis_plan": 1},
        "schema_version": 1,
    }
    encoded = json.dumps(report, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    content_hash = hashlib.sha256(encoded.encode()).hexdigest()
    artifact_id = "report-v1"
    conn.execute(
        """
        INSERT INTO research_artifacts(
            id, run_id, artifact_type, schema_version, source_step_id, version,
            status, content_json, idempotency_key, content_hash
        ) VALUES (?, ?, 'research_report', 1, ?, 1, 'completed', ?, 'report-v1', ?)
        """,
        (artifact_id, run_id, step_id, encoded, content_hash),
    )
    conn.commit()
    return conn, 1, run_id, artifact_id


def test_run_derived_paper_metadata_dependency_uses_canonical_hash() -> None:
    conn, paper_id, run_id, _ = _repository_db()
    conn.execute(
        """
        INSERT INTO research_run_papers(
            run_id, paper_id, stage, source, source_id
        ) VALUES (?, ?, 'candidate', 'arxiv', '2501.00001')
        """,
        (run_id, paper_id),
    )
    conn.commit()
    project = create_project(conn, 1, "Run dependency", "Canonical paper hash")
    project_id = str(project["id"])
    add_project_item(conn, project_id, 1, "run", run_id=run_id)

    inputs = get_project_analysis_inputs(conn, project_id, 1)
    dependency = next(
        dict(item)
        for item in inputs["dependencies"]
        if item["dependency_type"] == "paper_metadata"
    )
    for nullable_key in (
        "project_item_id",
        "upstream_artifact_id",
        "upstream_artifact_version",
        "citation_id",
        "evidence_id",
        "paper_id",
        "source_hash_snapshot",
    ):
        dependency.setdefault(nullable_key, None)
    assert _dependency_status(
        conn,
        dependency,  # type: ignore[arg-type]
        project_id=project_id,
        user_id=1,
        visited_artifact_ids=set(),
    ) == "current"


def test_project_owner_archive_items_fixed_report_and_backlinks() -> None:
    conn, paper_id, run_id, report_id = _repository_db()
    project = create_project(conn, 1, "RAG Landscape", "Traceable sources")
    project_id = str(project["id"])
    with pytest.raises(ResearchConflictError, match="archived before deletion"):
        delete_project(conn, project_id, 1)
    run_item = add_project_item(conn, project_id, 1, "run", run_id=run_id)
    paper_item = add_project_item(conn, project_id, 1, "paper", paper_id=paper_id)
    report_item = add_project_item(
        conn,
        project_id,
        1,
        "research_report",
        artifact_id=report_id,
        artifact_version=1,
    )
    assert [item["item_type"] for item in list_project_items(conn, project_id, 1)] == [
        "run",
        "paper",
        "research_report",
    ]
    with pytest.raises(ResearchConflictError):
        add_project_item(conn, project_id, 1, "paper", paper_id=paper_id)
    with pytest.raises(ResearchNotFoundError):
        get_project(conn, project_id, 2)
    assert project_backlinks(conn, 1, "run", run_id=run_id)[0]["id"] == project_id
    assert project_backlinks(conn, 1, "paper", paper_id=paper_id)[0]["id"] == project_id
    assert project_backlinks(
        conn,
        1,
        "research_report",
        artifact_id=report_id,
        artifact_version=1,
    )[0]["id"] == project_id

    reordered = reorder_project_items(
        conn,
        project_id,
        1,
        [report_item["id"], paper_item["id"], run_item["id"]],
    )
    assert [item["id"] for item in reordered] == [
        report_item["id"],
        paper_item["id"],
        run_item["id"],
    ]
    archived = set_project_status(conn, project_id, 1, "archived")
    assert archived["status"] == "archived"
    with pytest.raises(ResearchConflictError, match="read-only"):
        remove_project_item(conn, project_id, 1, paper_item["id"])
    set_project_status(conn, project_id, 1, "active")

    validation = validate_project_inputs(conn, project_id, 1)
    assert validation["coverage"] == {
        "total": 3,
        "valid": 2,
        "stale": 1,
        "inaccessible": 0,
        "runs": 1,
        "papers": 1,
        "reports": 0,
        "unique_papers": 1,
        "valid_citations": 0,
        "ready": False,
    }
    analysis = create_project_analysis_run(conn, project_id, 1)
    assert analysis["mode"] == "project"
    assert analysis["project_id"] == project_id
    assert len(analysis["steps"]) == 7
    persisted = conn.execute(
        "SELECT project_revision, input_fingerprint FROM research_runs WHERE id = ?",
        (analysis["id"],),
    ).fetchone()
    assert persisted is not None
    assert int(persisted["project_revision"]) == validation["project_revision"]
    assert str(persisted["input_fingerprint"]) == validation["input_fingerprint"]
    update_project(
        conn,
        project_id,
        1,
        title="RAG Landscape updated",
        description="Traceable sources",
    )
    fenced_by_revision = conn.execute(
        "SELECT status, requested_action FROM research_runs WHERE id = ?",
        (analysis["id"],),
    ).fetchone()
    assert fenced_by_revision is not None
    assert (str(fenced_by_revision["status"]), str(fenced_by_revision["requested_action"])) == (
        "cancelling",
        "cancel",
    )

    report_v1 = conn.execute(
        "SELECT * FROM research_artifacts WHERE id = ?", (report_id,)
    ).fetchone()
    assert report_v1 is not None
    conn.execute(
        """
        INSERT INTO research_artifacts(
            id, run_id, artifact_type, schema_version, source_step_id, version,
            status, content_json, idempotency_key, content_hash
        ) VALUES ('report-v2', ?, 'research_report', 1, ?, 2, 'completed', ?,
                  'report-v2', ?)
        """,
        (
            run_id,
            str(report_v1["source_step_id"]),
            str(report_v1["content_json"]),
            str(report_v1["content_hash"]),
        ),
    )
    conn.commit()
    stale_items = list_project_items(conn, project_id, 1)
    assert next(item for item in stale_items if item["id"] == report_item["id"])["status"] == "stale"
    assert next(item for item in stale_items if item["id"] == run_item["id"])["status"] == "stale"

    source_counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("papers",)
    }
    source_artifact_count = conn.execute(
        "SELECT COUNT(*) FROM research_artifacts WHERE project_id IS NULL"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO research_artifacts(
            id, run_id, project_id, artifact_type, schema_version, source_step_id,
            version, status, content_json, input_snapshot_json,
            dependency_snapshot_json, snapshot_hash, idempotency_key, content_hash
        ) VALUES ('project-artifact', ?, ?, 'research_landscape_plan', 1,
                  (SELECT id FROM research_steps WHERE run_id = ? ORDER BY position LIMIT 1),
                  1, 'completed', '{}', '{}', '[]', ?, 'project-artifact', ?)
        """,
        (
            analysis["id"],
            project_id,
            analysis["id"],
            hashlib.sha256(b"snapshot").hexdigest(),
            hashlib.sha256(b"{}").hexdigest(),
        ),
    )
    conn.execute(
        """
        INSERT INTO research_artifact_dependencies(
            id, artifact_id, dependency_type, dependency_key,
            upstream_artifact_id, upstream_artifact_version, dependency_hash
        ) VALUES ('project-dependency', 'project-artifact', 'artifact',
                  'artifact:report-v1:1', 'report-v1', 1, ?)
        """,
        (str(report_v1["content_hash"]),),
    )
    conn.commit()
    set_project_status(conn, project_id, 1, "archived")
    fenced = conn.execute(
        "SELECT status, requested_action FROM research_runs WHERE id = ?",
        (analysis["id"],),
    ).fetchone()
    assert fenced is not None
    assert (str(fenced["status"]), str(fenced["requested_action"])) == (
        "cancelling",
        "cancel",
    )
    delete_project(conn, project_id, 1)
    assert conn.execute("SELECT 1 FROM research_projects WHERE id = ?", (project_id,)).fetchone() is None
    assert {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("papers",)
    } == source_counts
    assert conn.execute(
        "SELECT COUNT(*) FROM research_artifacts WHERE project_id IS NULL"
    ).fetchone()[0] == source_artifact_count


def test_project_item_dynamic_stale_and_inaccessible_tombstone() -> None:
    conn, _, _, _ = _repository_db()
    conn.execute(
        """
        INSERT INTO papers(
            id, source, source_id, title, authors_json, abstract, categories_json,
            primary_category, published_at, processing_status
        ) VALUES (2, 'upload', 'private.pdf', 'Private title', '["Secret"]',
                  'Secret abstract', '["cs.AI"]', 'cs.AI', '2025-01-01', 'pending')
        """
    )
    conn.execute(
        """
        INSERT INTO paper_uploads(
            paper_id, owner_user_id, visibility, provenance, moderation_status
        ) VALUES (2, 2, 'public', 'user_upload', 'unreviewed')
        """
    )
    conn.commit()
    project_id = create_project(conn, 1, "ACL project")["id"]
    public_item = add_project_item(conn, project_id, 1, "paper", paper_id=2)
    conn.execute("UPDATE paper_uploads SET visibility = 'private' WHERE paper_id = 2")
    conn.commit()
    projected = list_project_items(conn, project_id, 1)[0]
    assert projected == {
        "id": public_item["id"],
        "item_type": "paper",
        "status": "inaccessible",
    }
    validation = validate_project_inputs(conn, project_id, 1)
    assert validation["coverage"]["inaccessible"] == 1
    assert validation["items"] == [projected]

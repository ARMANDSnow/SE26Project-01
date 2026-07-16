from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .connection import connect
from .migrations import (
    V3_MIGRATION,
    V4_MIGRATION,
    V5_MIGRATION,
    V6_MIGRATION,
    V7_MIGRATION,
    V8_MIGRATION,
    apply_migrations,
)
from .migrations.v5 import RESEARCH_SCHEMA_SQL
from .migrations.v7 import RESEARCH_DATA_SCHEMA_SQL
from .migrations.v8 import migrate_v7_to_v8
from .migrations.v9 import MIGRATION as V9_MIGRATION, migrate_v8_to_v9


PAPER_CHUNKS_FTS_TABLE = "paper_chunks_fts"
SCHEMA_VERSION = 9


class IncompatibleSchemaError(RuntimeError):
    pass


def _schema_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }


def _schema_reset_command(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    path = str(row[2]) if row is not None and row[2] else "<database-path>"
    return f'python scripts/reset_database.py --database "{path}" --apply'


def _table_sql(conn: sqlite3.Connection, table: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return " ".join(str(row[0] or "").lower().split()) if row is not None else ""


def _index_signature(conn: sqlite3.Connection, table: str) -> dict[str, tuple[int, tuple[str, ...]]]:
    result: dict[str, tuple[int, tuple[str, ...]]] = {}
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        name = str(row[1])
        columns = tuple(
            str(item[2]) for item in conn.execute(f'PRAGMA index_info("{name}")').fetchall()
        )
        result[name] = (int(row[2]), columns)
    return result


def _assert_research_data_schema(conn: sqlite3.Connection) -> None:
    artifact_rows = conn.execute("PRAGMA table_info(research_artifacts)").fetchall()
    paper_rows = conn.execute("PRAGMA table_info(research_run_papers)").fetchall()
    artifact_specs = {
        str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5])) for row in artifact_rows
    }
    paper_specs = {
        str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5])) for row in paper_rows
    }
    expected_artifact = {
        "id": ("TEXT", 0, 1),
        "run_id": ("TEXT", 1, 0),
        "project_id": ("TEXT", 0, 0),
        "paper_id": ("INTEGER", 0, 0),
        "artifact_type": ("TEXT", 1, 0),
        "schema_version": ("INTEGER", 1, 0),
        "source_step_id": ("TEXT", 1, 0),
        "version": ("INTEGER", 1, 0),
        "status": ("TEXT", 1, 0),
        "content_json": ("TEXT", 1, 0),
        "source_hash": ("TEXT", 0, 0),
        "input_snapshot_json": ("TEXT", 1, 0),
        "dependency_snapshot_json": ("TEXT", 1, 0),
        "snapshot_hash": ("TEXT", 0, 0),
        "idempotency_key": ("TEXT", 1, 0),
        "content_hash": ("TEXT", 1, 0),
        "created_at": ("TEXT", 1, 0),
        "updated_at": ("TEXT", 1, 0),
    }
    expected_paper = {
        "run_id": ("TEXT", 1, 1),
        "paper_id": ("INTEGER", 1, 2),
        "source_step_id": ("TEXT", 0, 0),
        "stage": ("TEXT", 1, 0),
        "rank": ("INTEGER", 0, 0),
        "score": ("REAL", 0, 0),
        "inclusion_reason": ("TEXT", 0, 0),
        "exclusion_reason": ("TEXT", 0, 0),
        "source": ("TEXT", 1, 0),
        "source_id": ("TEXT", 1, 0),
        "source_hash": ("TEXT", 0, 0),
        "created_at": ("TEXT", 1, 0),
        "updated_at": ("TEXT", 1, 0),
    }
    artifact_fks = {
        (str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper())
        for row in conn.execute("PRAGMA foreign_key_list(research_artifacts)").fetchall()
    }
    paper_fks = {
        (str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper())
        for row in conn.execute("PRAGMA foreign_key_list(research_run_papers)").fetchall()
    }
    artifact_indexes = _index_signature(conn, "research_artifacts")
    paper_indexes = _index_signature(conn, "research_run_papers")
    artifact_sql = _table_sql(conn, "research_artifacts")
    paper_sql = _table_sql(conn, "research_run_papers")
    if (
        artifact_specs != expected_artifact
        or paper_specs != expected_paper
        or not {
            ("run_id", "research_runs", "id", "CASCADE"),
            ("project_id", "research_projects", "id", "RESTRICT"),
            ("paper_id", "papers", "id", "CASCADE"),
            ("source_step_id", "research_steps", "id", "CASCADE"),
        }.issubset(artifact_fks)
        or not {
            ("run_id", "research_runs", "id", "CASCADE"),
            ("paper_id", "papers", "id", "CASCADE"),
            ("source_step_id", "research_steps", "id", "SET NULL"),
        }.issubset(paper_fks)
        or artifact_indexes.get("idx_research_artifacts_run_type") != (
            0,
            ("run_id", "artifact_type", "version"),
        )
        or artifact_indexes.get("idx_research_artifacts_paper") != (
            0,
            ("paper_id", "artifact_type", "version"),
        )
        or artifact_indexes.get("idx_research_artifacts_project_type") != (
            0,
            ("project_id", "artifact_type", "version"),
        )
        or artifact_indexes.get("idx_research_artifacts_project_version") != (
            1,
            ("project_id", "artifact_type", "version"),
        )
        or paper_indexes.get("idx_research_run_papers_stage") != (
            0,
            ("run_id", "stage", "rank", "paper_id"),
        )
        or paper_indexes.get("idx_research_run_papers_source") != (
            0,
            ("source", "source_id", "source_hash"),
        )
        or "unique(run_id, artifact_type, version)" not in artifact_sql
        or "unique(run_id, idempotency_key)" not in artifact_sql
        or "check(json_valid(content_json))" not in artifact_sql
        or "'research_landscape_plan', 'topic_clusters', 'research_timeline', 'research_graph', 'project_analysis_validation'" not in artifact_sql
        or "check(schema_version >= 1)" not in artifact_sql
        or "check(version >= 1)" not in artifact_sql
        or "check(status in ('draft', 'completed', 'failed', 'stale'))" not in artifact_sql
        or "check(artifact_type != 'paper_brief' or ( paper_id is not null and length(trim(coalesce(source_hash, ''))) = 64 ))" not in artifact_sql
        or "check(json_valid(input_snapshot_json))" not in artifact_sql
        or "check(json_valid(dependency_snapshot_json))" not in artifact_sql
        or "snapshot_hash is not null" not in artifact_sql
        or "primary key(run_id, paper_id)" not in paper_sql
        or "unique(run_id, source, source_id)" not in paper_sql
        or "'candidate', 'selected', 'excluded', 'fulltext_ready', 'read', 'extracted'"
        not in paper_sql
        or "check(rank is null or rank > 0)" not in paper_sql
        or "check(score is null or (score >= 0 and score <= 1))" not in paper_sql
        or "check(stage != 'excluded' or length(trim(coalesce(exclusion_reason, ''))) > 0)" not in paper_sql
        or "check(stage not in ('selected', 'fulltext_ready', 'read', 'extracted') or length(trim(coalesce(inclusion_reason, ''))) > 0)" not in paper_sql
        or "check(stage not in ('fulltext_ready', 'read', 'extracted') or (length(trim(coalesce(source_hash, ''))) = 64 and source_hash not glob '*[^0-9a-f]*'))" not in paper_sql
    ):
        raise IncompatibleSchemaError(
            f"Database topic research schema does not match version {SCHEMA_VERSION}; "
            f"rebuild it with: {_schema_reset_command(conn)}"
        )


def _assert_citation_schema(conn: sqlite3.Connection) -> None:
    model_calls = {str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5])) for row in conn.execute("PRAGMA table_info(research_model_calls)").fetchall()}
    evidence = {str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5])) for row in conn.execute("PRAGMA table_info(research_evidence)").fetchall()}
    citations = {str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5])) for row in conn.execute("PRAGMA table_info(research_citations)").fetchall()}
    expected_evidence = {
        "id": ("TEXT", 0, 1), "run_id": ("TEXT", 1, 0), "opened_by_step_id": ("TEXT", 1, 0),
        "paper_id": ("INTEGER", 1, 0), "chunk_id": ("INTEGER", 1, 0), "source": ("TEXT", 1, 0),
        "source_id": ("TEXT", 1, 0), "source_hash": ("TEXT", 1, 0), "heading": ("TEXT", 1, 0),
        "char_start": ("INTEGER", 1, 0), "char_end": ("INTEGER", 1, 0), "quote_hash": ("TEXT", 1, 0),
        "status": ("TEXT", 1, 0), "created_at": ("TEXT", 1, 0), "updated_at": ("TEXT", 1, 0),
    }
    expected_model_calls = {
        "id": ("TEXT", 0, 1), "run_id": ("TEXT", 1, 0), "step_id": ("TEXT", 1, 0),
        "idempotency_key": ("TEXT", 1, 0), "model_name": ("TEXT", 1, 0), "input_hash": ("TEXT", 1, 0),
        "status": ("TEXT", 1, 0), "result_json": ("TEXT", 0, 0), "created_at": ("TEXT", 1, 0),
        "updated_at": ("TEXT", 1, 0),
    }
    expected_citations = {
        "id": ("TEXT", 0, 1), "run_id": ("TEXT", 1, 0), "artifact_id": ("TEXT", 1, 0),
        "artifact_version": ("INTEGER", 1, 0), "citation_key": ("TEXT", 1, 0), "claim_id": ("TEXT", 1, 0),
        "paper_id": ("INTEGER", 1, 0), "chunk_id": ("INTEGER", 1, 0), "evidence_id": ("TEXT", 1, 0),
        "source": ("TEXT", 1, 0), "source_id": ("TEXT", 1, 0), "source_hash": ("TEXT", 1, 0),
        "heading": ("TEXT", 1, 0), "char_start": ("INTEGER", 1, 0), "char_end": ("INTEGER", 1, 0),
        "quote_hash": ("TEXT", 1, 0), "status": ("TEXT", 1, 0), "created_at": ("TEXT", 1, 0),
        "updated_at": ("TEXT", 1, 0),
    }
    evidence_indexes = _index_signature(conn, "research_evidence")
    citation_indexes = _index_signature(conn, "research_citations")
    evidence_sql = _table_sql(conn, "research_evidence")
    citation_sql = _table_sql(conn, "research_citations")
    evidence_fks = {(str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper()) for row in conn.execute("PRAGMA foreign_key_list(research_evidence)")}
    citation_fks = {(str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper()) for row in conn.execute("PRAGMA foreign_key_list(research_citations)")}
    model_call_fks = {(str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper()) for row in conn.execute("PRAGMA foreign_key_list(research_model_calls)")}
    model_call_sql = _table_sql(conn, "research_model_calls")
    if (
        model_calls != expected_model_calls
        or evidence != expected_evidence or citations != expected_citations
        or not {("run_id", "research_runs", "id", "CASCADE"), ("step_id", "research_steps", "id", "CASCADE")}.issubset(model_call_fks)
        or not {("run_id", "research_runs", "id", "CASCADE"), ("opened_by_step_id", "research_steps", "id", "CASCADE"), ("paper_id", "papers", "id", "RESTRICT")}.issubset(evidence_fks)
        or not {("run_id", "research_runs", "id", "CASCADE"), ("artifact_id", "research_artifacts", "id", "CASCADE"), ("paper_id", "papers", "id", "RESTRICT"), ("evidence_id", "research_evidence", "id", "RESTRICT")}.issubset(citation_fks)
        or evidence_indexes.get("idx_research_evidence_run_paper") != (0, ("run_id", "paper_id", "source_hash", "chunk_id"))
        or citation_indexes.get("idx_research_citations_run_status") != (0, ("run_id", "status", "citation_key"))
        or citation_indexes.get("idx_research_citations_evidence") != (0, ("evidence_id", "artifact_id", "artifact_version"))
        or "unique(run_id, chunk_id, source_hash, char_start, char_end)" not in evidence_sql
        or "unique(artifact_id, artifact_version, citation_key)" not in citation_sql
        or "length(source_hash) = 64 and source_hash not glob '*[^0-9a-f]*'" not in evidence_sql
        or "length(quote_hash) = 64 and quote_hash not glob '*[^0-9a-f]*'" not in evidence_sql
        or "check(char_start >= 0)" not in evidence_sql or "check(char_end >= char_start)" not in evidence_sql
        or "length(source_hash) = 64 and source_hash not glob '*[^0-9a-f]*'" not in citation_sql
        or "length(quote_hash) = 64 and quote_hash not glob '*[^0-9a-f]*'" not in citation_sql
        or "check(char_start >= 0)" not in citation_sql or "check(char_end >= char_start)" not in citation_sql
        or "check(artifact_version >= 1)" not in citation_sql or "check(length(trim(citation_key)) > 0)" not in citation_sql
        or "status in ('valid', 'stale', 'inaccessible', 'invalid')" not in evidence_sql
        or "status in ('valid', 'stale', 'inaccessible', 'invalid')" not in citation_sql
        or "unique(run_id, idempotency_key)" not in model_call_sql
        or "check(length(input_hash) = 64)" not in model_call_sql
        or "check(result_json is null or json_valid(result_json))" not in model_call_sql
        or "status in ('started', 'completed', 'failed', 'ambiguous')" not in model_call_sql
    ):
        raise IncompatibleSchemaError(
            f"Database citation schema does not match version {SCHEMA_VERSION}; rebuild it with: {_schema_reset_command(conn)}"
        )


def _column_signature(conn: sqlite3.Connection, table: str) -> dict[str, tuple[str, int, int]]:
    return {
        str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _foreign_key_signature(conn: sqlite3.Connection, table: str) -> set[tuple[str, str, str, str]]:
    return {
        (str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper())
        for row in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    }


def _assert_project_schema(conn: sqlite3.Connection) -> None:
    projects = _column_signature(conn, "research_projects")
    items = _column_signature(conn, "research_project_items")
    dependencies = _column_signature(conn, "research_artifact_dependencies")
    citation_refs = _column_signature(conn, "research_project_citation_refs")
    runs = _column_signature(conn, "research_runs")
    expected_projects = {
        "id": ("TEXT", 0, 1),
        "owner_user_id": ("INTEGER", 1, 0),
        "title": ("TEXT", 1, 0),
        "description": ("TEXT", 1, 0),
        "status": ("TEXT", 1, 0),
        "items_revision": ("INTEGER", 1, 0),
        "created_at": ("TEXT", 1, 0),
        "updated_at": ("TEXT", 1, 0),
    }
    expected_items = {
        "id": ("TEXT", 0, 1),
        "project_id": ("TEXT", 1, 0),
        "item_type": ("TEXT", 1, 0),
        "run_id": ("TEXT", 0, 0),
        "paper_id": ("INTEGER", 0, 0),
        "artifact_id": ("TEXT", 0, 0),
        "artifact_version": ("INTEGER", 0, 0),
        "source_hash_snapshot": ("TEXT", 1, 0),
        "position": ("INTEGER", 1, 0),
        "added_at": ("TEXT", 1, 0),
        "updated_at": ("TEXT", 1, 0),
    }
    expected_dependencies = {
        "id": ("TEXT", 0, 1),
        "artifact_id": ("TEXT", 1, 0),
        "dependency_type": ("TEXT", 1, 0),
        "dependency_key": ("TEXT", 1, 0),
        "project_item_id": ("TEXT", 0, 0),
        "upstream_artifact_id": ("TEXT", 0, 0),
        "upstream_artifact_version": ("INTEGER", 0, 0),
        "citation_id": ("TEXT", 0, 0),
        "evidence_id": ("TEXT", 0, 0),
        "paper_id": ("INTEGER", 0, 0),
        "source_hash_snapshot": ("TEXT", 0, 0),
        "dependency_hash": ("TEXT", 1, 0),
        "created_at": ("TEXT", 1, 0),
    }
    expected_refs = {
        "id": ("TEXT", 0, 1),
        "project_id": ("TEXT", 1, 0),
        "analysis_run_id": ("TEXT", 1, 0),
        "citation_key": ("TEXT", 1, 0),
        "reference_type": ("TEXT", 1, 0),
        "citation_id": ("TEXT", 0, 0),
        "evidence_id": ("TEXT", 0, 0),
        "paper_id": ("INTEGER", 1, 0),
        "source_hash_snapshot": ("TEXT", 1, 0),
        "created_at": ("TEXT", 1, 0),
        "updated_at": ("TEXT", 1, 0),
    }
    project_fks = _foreign_key_signature(conn, "research_projects")
    item_fks = _foreign_key_signature(conn, "research_project_items")
    dependency_fks = _foreign_key_signature(conn, "research_artifact_dependencies")
    ref_fks = _foreign_key_signature(conn, "research_project_citation_refs")
    run_fks = _foreign_key_signature(conn, "research_runs")
    project_indexes = _index_signature(conn, "research_projects")
    item_indexes = _index_signature(conn, "research_project_items")
    run_indexes = _index_signature(conn, "research_runs")
    project_sql = _table_sql(conn, "research_projects")
    item_sql = _table_sql(conn, "research_project_items")
    dependency_sql = _table_sql(conn, "research_artifact_dependencies")
    ref_sql = _table_sql(conn, "research_project_citation_refs")
    run_sql = _table_sql(conn, "research_runs")
    if (
        projects != expected_projects
        or items != expected_items
        or dependencies != expected_dependencies
        or citation_refs != expected_refs
        or runs.get("project_id") != ("TEXT", 0, 0)
        or runs.get("project_revision") != ("INTEGER", 0, 0)
        or runs.get("input_fingerprint") != ("TEXT", 0, 0)
        or ("owner_user_id", "users", "id", "CASCADE") not in project_fks
        or not {
            ("project_id", "research_projects", "id", "CASCADE"),
            ("run_id", "research_runs", "id", "RESTRICT"),
            ("paper_id", "papers", "id", "RESTRICT"),
            ("artifact_id", "research_artifacts", "id", "RESTRICT"),
        }.issubset(item_fks)
        or not {
            ("artifact_id", "research_artifacts", "id", "CASCADE"),
            ("upstream_artifact_id", "research_artifacts", "id", "RESTRICT"),
            ("citation_id", "research_citations", "id", "RESTRICT"),
            ("evidence_id", "research_evidence", "id", "RESTRICT"),
            ("paper_id", "papers", "id", "RESTRICT"),
        }.issubset(dependency_fks)
        or not {
            ("project_id", "research_projects", "id", "CASCADE"),
            ("analysis_run_id", "research_runs", "id", "CASCADE"),
            ("citation_id", "research_citations", "id", "RESTRICT"),
            ("evidence_id", "research_evidence", "id", "RESTRICT"),
            ("paper_id", "papers", "id", "RESTRICT"),
        }.issubset(ref_fks)
        or ("project_id", "research_projects", "id", "RESTRICT") not in run_fks
        or project_indexes.get("idx_research_projects_owner_status")
        != (0, ("owner_user_id", "status", "updated_at"))
        or item_indexes.get("idx_project_items_unique_run") != (1, ("project_id", "run_id"))
        or item_indexes.get("idx_project_items_unique_paper") != (1, ("project_id", "paper_id"))
        or item_indexes.get("idx_project_items_unique_report")
        != (1, ("project_id", "artifact_id", "artifact_version"))
        or run_indexes.get("idx_research_runs_one_active_project") != (1, ("project_id",))
        or "length(trim(title)) between 1 and 200" not in project_sql
        or "status in ('active', 'archived')" not in project_sql
        or "item_type in ('run', 'paper', 'research_report')" not in item_sql
        or "item_type = 'research_report'" not in item_sql
        or "dependency_type = 'citation'" not in dependency_sql
        or "unique(artifact_id, dependency_type, dependency_key)" not in dependency_sql
        or "reference_type in ('citation', 'evidence')" not in ref_sql
        or "unique(analysis_run_id, citation_key)" not in ref_sql
        or "mode in ('harness', 'topic', 'paper', 'project')" not in run_sql
        or "mode = 'project' and project_id is not null" not in run_sql
        or "project_revision is not null and input_fingerprint is not null" not in run_sql
    ):
        raise IncompatibleSchemaError(
            f"Database project schema does not match version {SCHEMA_VERSION}; "
            f"rebuild it with: {_schema_reset_command(conn)}"
        )


def _assert_schema_compatible(conn: sqlite3.Connection) -> None:
    tables = _schema_tables(conn)
    if not tables:
        return
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version != SCHEMA_VERSION:
        raise IncompatibleSchemaError(
            f"Database schema version {version} is incompatible with required version "
            f"{SCHEMA_VERSION}. No data migration is provided; rebuild the database with: "
            f"{_schema_reset_command(conn)}"
        )

    paper_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(papers)").fetchall()}
    thread_columns = {
        str(row[1]): int(row[3]) for row in conn.execute("PRAGMA table_info(chat_threads)").fetchall()
    }
    user_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    note_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(notes)").fetchall()}
    history_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(reading_history)").fetchall()
    }
    subscription_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(subscriptions)").fetchall()
    }
    upload_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(paper_uploads)").fetchall()
    }
    chat_message_column_rows = conn.execute("PRAGMA table_info(chat_messages)").fetchall()
    chat_message_columns = {str(row[1]) for row in chat_message_column_rows}
    chat_message_specs = {str(row[1]): (str(row[2]).upper(), int(row[3]), row[4]) for row in chat_message_column_rows}
    research_run_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(research_runs)").fetchall()
    }
    research_step_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(research_steps)").fetchall()
    }
    research_event_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(research_events)").fetchall()
    }
    research_decision_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(research_decisions)").fetchall()
    }
    index_names = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name IS NOT NULL"
        ).fetchall()
    }
    required_paper_columns = {"source", "source_id", "asset_id", "processing_status"}
    if not required_paper_columns.issubset(paper_columns) or "title_hash" in paper_columns:
        raise IncompatibleSchemaError(
            f"Database schema does not match version {SCHEMA_VERSION}; rebuild it with: "
            f"{_schema_reset_command(conn)}"
        )
    if thread_columns.get("paper_id") != 0:
        raise IncompatibleSchemaError(
            f"Database chat schema does not match version {SCHEMA_VERSION}; rebuild it with: "
            f"{_schema_reset_command(conn)}"
        )
    if not {"username", "password_hash", "is_active", "updated_at"}.issubset(user_columns):
        raise IncompatibleSchemaError(
            f"Database user schema does not match version {SCHEMA_VERSION}; rebuild it with: "
            f"{_schema_reset_command(conn)}"
        )
    if any(
        "user_id" not in columns
        for columns in (note_columns, history_columns, subscription_columns)
    ):
        raise IncompatibleSchemaError(
            f"Database private-data schema does not match version {SCHEMA_VERSION}; rebuild it with: "
            f"{_schema_reset_command(conn)}"
        )
    if not {
        "paper_id",
        "owner_user_id",
        "visibility",
        "provenance",
        "moderation_status",
        "original_filename",
    }.issubset(upload_columns):
        raise IncompatibleSchemaError(
            f"Database upload schema does not match version {SCHEMA_VERSION}; rebuild it with: "
            f"{_schema_reset_command(conn)}"
        )
    if "content_parts_json" not in chat_message_columns or chat_message_specs.get(
        "content_parts_json"
    ) != ("TEXT", 1, "'[]'"):
        raise IncompatibleSchemaError(
            f"Database chat message schema does not match version {SCHEMA_VERSION}; rebuild it with: "
            f"{_schema_reset_command(conn)}"
        )
    if not {
        "user_id",
        "thread_id",
        "status",
        "requested_action",
        "state_version",
    }.issubset(research_run_columns) or not {
        "run_id",
        "status",
        "idempotency_key",
        "lease_owner",
        "lease_generation",
        "lease_expires_at",
    }.issubset(research_step_columns):
        raise IncompatibleSchemaError(
            f"Database research schema does not match version {SCHEMA_VERSION}; rebuild it with: "
            f"{_schema_reset_command(conn)}"
        )
    if not {"run_id", "step_id", "event_type", "summary", "payload_json"}.issubset(
        research_event_columns
    ) or not {
        "run_id",
        "step_id",
        "question",
        "options_json",
        "status",
        "answer_json",
    }.issubset(research_decision_columns) or not {
        "idx_research_runs_user_status",
        "idx_research_steps_runnable",
        "idx_research_events_run",
        "idx_research_decisions_one_pending",
    }.issubset(index_names):
        raise IncompatibleSchemaError(
            f"Database research event schema does not match version {SCHEMA_VERSION}; rebuild it with: "
            f"{_schema_reset_command(conn)}"
        )
    _assert_research_data_schema(conn)
    _assert_citation_schema(conn)
    _assert_project_schema(conn)


def supports_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp._fts5_probe USING fts5(value)")
        conn.execute("DROP TABLE IF EXISTS temp._fts5_probe")
    except sqlite3.Error:
        return False
    return True


def init_paper_chunks_fts(conn: sqlite3.Connection) -> bool:
    if not supports_fts5(conn):
        return False
    try:
        existing = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (PAPER_CHUNKS_FTS_TABLE,),
        ).fetchone()
        existing_sql = str(existing["sql"] or "").lower() if existing else ""
        if existing and ("source_hash" not in existing_sql or "trigram" not in existing_sql):
            conn.execute("DROP TRIGGER IF EXISTS trg_paper_chunks_delete_fts")
            conn.execute("DROP TABLE IF EXISTS paper_chunks_fts")
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS paper_chunks_fts USING fts5(
                chunk_id UNINDEXED,
                paper_id UNINDEXED,
                source_hash UNINDEXED,
                chunk_index UNINDEXED,
                heading,
                content,
                paper_title,
                tokenize='trigram'
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_paper_chunks_delete_fts
            AFTER DELETE ON paper_chunks
            BEGIN
                DELETE FROM paper_chunks_fts WHERE rowid = OLD.id;
            END
            """
        )
    except sqlite3.Error:
        return False
    return True


def paper_chunks_fts_ready(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT rowid FROM paper_chunks_fts LIMIT 0")
    except sqlite3.Error:
        return False
    return True


def _insert_paper_chunk_fts_row(conn: sqlite3.Connection, row: sqlite3.Row | dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO paper_chunks_fts(
            rowid, chunk_id, paper_id, source_hash, chunk_index, heading, content, paper_title
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["id"],
            row["id"],
            row["paper_id"],
            row["source_hash"],
            row["chunk_index"],
            row["heading"],
            row["content"],
            row["paper_title"],
        ),
    )


def rebuild_paper_chunks_fts(conn: sqlite3.Connection, paper_id: int | None = None) -> bool:
    if not paper_chunks_fts_ready(conn):
        return False
    savepoint = "paper_chunks_fts_rebuild"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        if paper_id is None:
            conn.execute("DELETE FROM paper_chunks_fts")
            rows = conn.execute(
                """
                SELECT pc.*, p.title AS paper_title
                FROM paper_chunks pc JOIN papers p ON p.id = pc.paper_id
                ORDER BY pc.id
                """
            ).fetchall()
        else:
            conn.execute("DELETE FROM paper_chunks_fts WHERE paper_id = ?", (paper_id,))
            rows = conn.execute(
                """
                SELECT pc.*, p.title AS paper_title
                FROM paper_chunks pc JOIN papers p ON p.id = pc.paper_id
                WHERE pc.paper_id = ? ORDER BY pc.id
                """,
                (paper_id,),
            ).fetchall()
        for row in rows:
            _insert_paper_chunk_fts_row(conn, row)
    except sqlite3.Error:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        return False
    conn.execute(f"RELEASE {savepoint}")
    return True


def init_schema(conn: sqlite3.Connection) -> None:
    tables = _schema_tables(conn)
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if tables and version in {2, 3, 4, 5, 6, 7, 8}:
        apply_migrations(
            conn,
            [
                V3_MIGRATION,
                V4_MIGRATION,
                V5_MIGRATION,
                V6_MIGRATION,
                V7_MIGRATION,
                V8_MIGRATION,
                V9_MIGRATION,
            ],
            target_version=SCHEMA_VERSION,
        )
    _assert_schema_compatible(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_url TEXT,
            venue TEXT,
            pdf_url TEXT,
            asset_id TEXT,
            title TEXT NOT NULL,
            authors_json TEXT NOT NULL,
            abstract TEXT NOT NULL,
            categories_json TEXT NOT NULL,
            primary_category TEXT NOT NULL,
            published_at TEXT NOT NULL,
            updated_at TEXT,
            processing_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, source_id)
        );

        CREATE TABLE IF NOT EXISTS wiki_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            section TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(paper_id, section)
        );

        CREATE TABLE IF NOT EXISTS concepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT NOT NULL,
            embedding_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_concepts (
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
            relation TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            PRIMARY KEY (paper_id, concept_id)
        );

        CREATE TABLE IF NOT EXISTS concept_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
            target_concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
            relation TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            UNIQUE(source_concept_id, target_concept_id, relation)
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            note TEXT NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reading_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            topic TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, topic)
        );

        CREATE TABLE IF NOT EXISTS paper_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL UNIQUE REFERENCES papers(id) ON DELETE CASCADE,
            parser_name TEXT NOT NULL DEFAULT 'docling',
            parser_version TEXT,
            source_hash TEXT,
            content_markdown TEXT NOT NULL DEFAULT '',
            structure_json TEXT NOT NULL DEFAULT '{}',
            token_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT,
            parsed_at TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS paper_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            document_id INTEGER NOT NULL REFERENCES paper_documents(id) ON DELETE CASCADE,
            source_hash TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            heading TEXT NOT NULL,
            content TEXT NOT NULL,
            char_start INTEGER NOT NULL,
            char_end INTEGER NOT NULL,
            token_count INTEGER NOT NULL,
            embedding_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(paper_id, source_hash, chunk_index)
        );

        CREATE TABLE IF NOT EXISTS summary_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL DEFAULT 'paper-summary-v1',
            source_hash TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chat_threads (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
            title TEXT NOT NULL DEFAULT '新对话',
            active_leaf_id TEXT,
            message_token_limit INTEGER NOT NULL DEFAULT 12000,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
            parent_id TEXT REFERENCES chat_messages(id),
            source_message_id TEXT REFERENCES chat_messages(id),
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
            content TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'complete',
            token_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            content_parts_json TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS chat_runs (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
            input_message_id TEXT NOT NULL REFERENCES chat_messages(id),
            output_message_id TEXT NOT NULL UNIQUE REFERENCES chat_messages(id),
            status TEXT NOT NULL DEFAULT 'running',
            model TEXT,
            usage_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS library_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            parent_id INTEGER REFERENCES library_folders(id) ON DELETE RESTRICT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            is_system INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, parent_id, name)
        );

        CREATE TABLE IF NOT EXISTS library_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            folder_id INTEGER NOT NULL REFERENCES library_folders(id) ON DELETE RESTRICT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, paper_id)
        );

        CREATE TABLE IF NOT EXISTS paper_uploads (
            paper_id INTEGER PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
            owner_user_id INTEGER REFERENCES users(id) ON DELETE RESTRICT,
            visibility TEXT NOT NULL CHECK(visibility IN ('private', 'public')),
            provenance TEXT NOT NULL CHECK(provenance IN ('user_upload', 'legacy_upload')),
            moderation_status TEXT NOT NULL
                CHECK(moderation_status IN ('unreviewed', 'approved', 'rejected')),
            original_filename TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK(provenance = 'legacy_upload' OR owner_user_id IS NOT NULL)
        );

        CREATE INDEX IF NOT EXISTS idx_papers_category ON papers(primary_category);
        CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published_at);
        CREATE INDEX IF NOT EXISTS idx_papers_source ON papers(source);
        CREATE INDEX IF NOT EXISTS idx_papers_asset ON papers(asset_id);
        CREATE INDEX IF NOT EXISTS idx_wiki_sections_section ON wiki_sections(section);
        CREATE INDEX IF NOT EXISTS idx_notes_user_paper ON notes(user_id, paper_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_reading_history_user ON reading_history(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_summary_versions_paper ON summary_versions(paper_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_paper_chunks_paper ON paper_chunks(paper_id, source_hash, chunk_index);
        CREATE INDEX IF NOT EXISTS idx_chat_threads_paper ON chat_threads(user_id, paper_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_thread ON chat_messages(thread_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_parent ON chat_messages(parent_id);
        CREATE INDEX IF NOT EXISTS idx_library_folders_user ON library_folders(user_id, parent_id);
        CREATE INDEX IF NOT EXISTS idx_library_items_folder ON library_items(user_id, folder_id);
        CREATE INDEX IF NOT EXISTS idx_paper_uploads_owner ON paper_uploads(owner_user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_paper_uploads_visibility ON paper_uploads(visibility, moderation_status);
        """
    )
    conn.executescript(RESEARCH_SCHEMA_SQL.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ").replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ").replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS "))
    conn.executescript(RESEARCH_DATA_SCHEMA_SQL.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ").replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ").replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS "))
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'research_citations'").fetchone():
        migrate_v7_to_v8(conn)
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'research_projects'"
    ).fetchone():
        migrate_v8_to_v9(conn)
    init_paper_chunks_fts(conn)
    rebuild_paper_chunks_fts(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    _assert_schema_compatible(conn)
    conn.commit()


def init_db(path: Path | str | None = None) -> None:
    with connect(path) as conn:
        init_schema(conn)

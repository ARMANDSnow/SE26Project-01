from __future__ import annotations

import sqlite3

from .runner import Migration


RESEARCH_DATA_SCHEMA_SQL = """
CREATE TABLE research_artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL CHECK(artifact_type IN (
        'research_brief', 'search_queries', 'candidate_papers',
        'screening_result', 'paper_brief', 'extraction_result'
    )),
    schema_version INTEGER NOT NULL CHECK(schema_version >= 1),
    source_step_id TEXT NOT NULL REFERENCES research_steps(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK(version >= 1),
    status TEXT NOT NULL CHECK(status IN ('draft', 'completed', 'failed', 'stale')),
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    source_hash TEXT,
    idempotency_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, artifact_type, version),
    UNIQUE(run_id, idempotency_key),
    CHECK(artifact_type != 'paper_brief' OR (
        paper_id IS NOT NULL AND length(trim(COALESCE(source_hash, ''))) = 64
    ))
);

CREATE TABLE research_run_papers (
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    source_step_id TEXT REFERENCES research_steps(id) ON DELETE SET NULL,
    stage TEXT NOT NULL CHECK(stage IN (
        'candidate', 'selected', 'excluded', 'fulltext_ready', 'read', 'extracted'
    )),
    rank INTEGER CHECK(rank IS NULL OR rank > 0),
    score REAL CHECK(score IS NULL OR (score >= 0 AND score <= 1)),
    inclusion_reason TEXT,
    exclusion_reason TEXT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(run_id, paper_id),
    UNIQUE(run_id, source, source_id),
    CHECK(stage != 'excluded' OR length(trim(COALESCE(exclusion_reason, ''))) > 0),
    CHECK(stage NOT IN ('selected', 'fulltext_ready', 'read', 'extracted')
        OR length(trim(COALESCE(inclusion_reason, ''))) > 0),
    CHECK(stage NOT IN ('fulltext_ready', 'read', 'extracted')
        OR (length(trim(COALESCE(source_hash, ''))) = 64
            AND source_hash NOT GLOB '*[^0-9a-f]*'))
);

CREATE INDEX idx_research_artifacts_run_type
    ON research_artifacts(run_id, artifact_type, version DESC);
CREATE INDEX idx_research_artifacts_paper
    ON research_artifacts(paper_id, artifact_type, version DESC);
CREATE INDEX idx_research_run_papers_stage
    ON research_run_papers(run_id, stage, rank, paper_id);
CREATE INDEX idx_research_run_papers_source
    ON research_run_papers(source, source_id, source_hash);
"""


def migrate_v6_to_v7(conn: sqlite3.Connection) -> None:
    # sqlite3.executescript commits implicitly. Keep the migration runner's
    # savepoint authoritative by executing each DDL statement separately.
    for statement in RESEARCH_DATA_SCHEMA_SQL.split(";"):
        if statement.strip():
            conn.execute(statement)


MIGRATION = Migration(version=7, name="topic-research-data", apply=migrate_v6_to_v7)

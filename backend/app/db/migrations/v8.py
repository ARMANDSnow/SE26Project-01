from __future__ import annotations

import sqlite3

from .runner import Migration


ARTIFACT_TYPES = (
    "'research_brief', 'search_queries', 'candidate_papers', 'screening_result', "
    "'paper_brief', 'extraction_result', 'synthesis_plan', 'comparison_matrix', "
    "'synthesis_claims', 'citation_registry', 'research_report', "
    "'citation_validation_result'"
)

RESEARCH_ARTIFACTS_V8_SQL = f"""
CREATE TABLE research_artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL CHECK(artifact_type IN ({ARTIFACT_TYPES})),
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
)
"""

RESEARCH_CITATION_SCHEMA_SQL = """
CREATE TABLE research_model_calls (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    step_id TEXT NOT NULL REFERENCES research_steps(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    model_name TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK(length(input_hash) = 64),
    status TEXT NOT NULL CHECK(status IN ('started', 'completed', 'failed', 'ambiguous')),
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, idempotency_key)
);

CREATE TABLE research_evidence (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    opened_by_step_id TEXT NOT NULL REFERENCES research_steps(id) ON DELETE CASCADE,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE RESTRICT,
    chunk_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_hash TEXT NOT NULL CHECK(
        length(source_hash) = 64 AND source_hash NOT GLOB '*[^0-9a-f]*'
    ),
    heading TEXT NOT NULL,
    char_start INTEGER NOT NULL CHECK(char_start >= 0),
    char_end INTEGER NOT NULL CHECK(char_end >= char_start),
    quote_hash TEXT NOT NULL CHECK(
        length(quote_hash) = 64 AND quote_hash NOT GLOB '*[^0-9a-f]*'
    ),
    status TEXT NOT NULL CHECK(status IN ('valid', 'stale', 'inaccessible', 'invalid')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, chunk_id, source_hash, char_start, char_end)
);

CREATE TABLE research_citations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL REFERENCES research_artifacts(id) ON DELETE CASCADE,
    artifact_version INTEGER NOT NULL CHECK(artifact_version >= 1),
    citation_key TEXT NOT NULL CHECK(length(trim(citation_key)) > 0),
    claim_id TEXT NOT NULL CHECK(length(trim(claim_id)) > 0),
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE RESTRICT,
    chunk_id INTEGER NOT NULL,
    evidence_id TEXT NOT NULL REFERENCES research_evidence(id) ON DELETE RESTRICT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_hash TEXT NOT NULL CHECK(
        length(source_hash) = 64 AND source_hash NOT GLOB '*[^0-9a-f]*'
    ),
    heading TEXT NOT NULL,
    char_start INTEGER NOT NULL CHECK(char_start >= 0),
    char_end INTEGER NOT NULL CHECK(char_end >= char_start),
    quote_hash TEXT NOT NULL CHECK(
        length(quote_hash) = 64 AND quote_hash NOT GLOB '*[^0-9a-f]*'
    ),
    status TEXT NOT NULL CHECK(status IN ('valid', 'stale', 'inaccessible', 'invalid')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(artifact_id, artifact_version, citation_key)
);

CREATE INDEX idx_research_evidence_run_paper
    ON research_evidence(run_id, paper_id, source_hash, chunk_id);
CREATE INDEX idx_research_citations_run_status
    ON research_citations(run_id, status, citation_key);
CREATE INDEX idx_research_citations_evidence
    ON research_citations(evidence_id, artifact_id, artifact_version);
"""


def migrate_v7_to_v8(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX idx_research_artifacts_run_type")
    conn.execute("DROP INDEX idx_research_artifacts_paper")
    conn.execute("ALTER TABLE research_artifacts RENAME TO research_artifacts_v7")
    conn.execute(RESEARCH_ARTIFACTS_V8_SQL)
    conn.execute(
        """
        INSERT INTO research_artifacts(
            id, run_id, paper_id, artifact_type, schema_version, source_step_id,
            version, status, content_json, source_hash, idempotency_key,
            content_hash, created_at, updated_at
        )
        SELECT id, run_id, paper_id, artifact_type, schema_version, source_step_id,
               version, status, content_json, source_hash, idempotency_key,
               content_hash, created_at, updated_at
        FROM research_artifacts_v7
        """
    )
    conn.execute("DROP TABLE research_artifacts_v7")
    conn.execute(
        "CREATE INDEX idx_research_artifacts_run_type ON research_artifacts(run_id, artifact_type, version DESC)"
    )
    conn.execute(
        "CREATE INDEX idx_research_artifacts_paper ON research_artifacts(paper_id, artifact_type, version DESC)"
    )
    for statement in RESEARCH_CITATION_SCHEMA_SQL.split(";"):
        if statement.strip():
            conn.execute(statement)


MIGRATION = Migration(version=8, name="cited-research-synthesis", apply=migrate_v7_to_v8)

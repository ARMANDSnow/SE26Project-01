from __future__ import annotations

import sqlite3

from .runner import Migration


PROJECT_ARTIFACT_TYPES = (
    "'research_landscape_plan', 'topic_clusters', 'research_timeline', "
    "'research_graph', 'project_analysis_validation'"
)

ALL_ARTIFACT_TYPES = (
    "'research_brief', 'search_queries', 'candidate_papers', 'screening_result', "
    "'paper_brief', 'extraction_result', 'synthesis_plan', 'comparison_matrix', "
    "'synthesis_claims', 'citation_registry', 'research_report', "
    "'citation_validation_result', "
    + PROJECT_ARTIFACT_TYPES
)


RESEARCH_PROJECT_SCHEMA_SQL = f"""
CREATE TABLE research_projects (
    id TEXT PRIMARY KEY,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 200),
    description TEXT NOT NULL DEFAULT '' CHECK(length(description) <= 4000),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived')),
    items_revision INTEGER NOT NULL DEFAULT 1 CHECK(items_revision >= 1),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE research_runs_v9 (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES research_projects(id) ON DELETE RESTRICT,
    project_revision INTEGER CHECK(project_revision IS NULL OR project_revision >= 1),
    input_fingerprint TEXT CHECK(input_fingerprint IS NULL OR (
        length(input_fingerprint) = 64 AND input_fingerprint NOT GLOB '*[^0-9a-f]*'
    )),
    thread_id TEXT REFERENCES chat_threads(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    goal TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'harness' CHECK(mode IN ('harness', 'topic', 'paper', 'project')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN (
        'queued', 'running', 'waiting_input', 'paused', 'completed', 'failed',
        'cancelling', 'cancelled'
    )),
    requested_action TEXT CHECK(requested_action IN ('pause', 'cancel')),
    state_version INTEGER NOT NULL DEFAULT 1,
    plan_version INTEGER NOT NULL DEFAULT 1,
    budget_json TEXT NOT NULL DEFAULT '{{}}',
    usage_json TEXT NOT NULL DEFAULT '{{}}',
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    CHECK((mode = 'project' AND project_id IS NOT NULL
            AND project_revision IS NOT NULL AND input_fingerprint IS NOT NULL)
       OR (mode != 'project' AND project_id IS NULL
            AND project_revision IS NULL AND input_fingerprint IS NULL))
);

CREATE TABLE research_steps_v9 (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs_v9(id) ON DELETE CASCADE,
    step_key TEXT NOT NULL,
    step_type TEXT NOT NULL,
    title TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN (
        'queued', 'running', 'waiting_input', 'paused', 'completed', 'failed',
        'skipped', 'cancelled'
    )),
    position INTEGER NOT NULL,
    plan_version INTEGER NOT NULL DEFAULT 1,
    depends_on_json TEXT NOT NULL DEFAULT '[]',
    input_json TEXT NOT NULL DEFAULT '{{}}',
    output_json TEXT NOT NULL DEFAULT '{{}}',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 1,
    idempotency_key TEXT NOT NULL,
    lease_owner TEXT,
    lease_generation INTEGER NOT NULL DEFAULT 0,
    lease_expires_at TEXT,
    heartbeat_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, step_key, plan_version),
    UNIQUE(run_id, idempotency_key)
);

CREATE TABLE research_events_v9 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES research_runs_v9(id) ON DELETE CASCADE,
    step_id TEXT REFERENCES research_steps_v9(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{{}}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE research_decisions_v9 (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs_v9(id) ON DELETE CASCADE,
    step_id TEXT REFERENCES research_steps_v9(id) ON DELETE SET NULL,
    question TEXT NOT NULL,
    options_json TEXT NOT NULL,
    recommended_option TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'resolved', 'cancelled')),
    answer_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);

CREATE TABLE research_artifacts_v9 (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs_v9(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES research_projects(id) ON DELETE RESTRICT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL CHECK(artifact_type IN ({ALL_ARTIFACT_TYPES})),
    schema_version INTEGER NOT NULL CHECK(schema_version >= 1),
    source_step_id TEXT NOT NULL REFERENCES research_steps_v9(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK(version >= 1),
    status TEXT NOT NULL CHECK(status IN ('draft', 'completed', 'failed', 'stale')),
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    source_hash TEXT,
    input_snapshot_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(input_snapshot_json)),
    dependency_snapshot_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(dependency_snapshot_json)),
    snapshot_hash TEXT CHECK(snapshot_hash IS NULL OR (
        length(snapshot_hash) = 64 AND snapshot_hash NOT GLOB '*[^0-9a-f]*'
    )),
    idempotency_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, artifact_type, version),
    UNIQUE(run_id, idempotency_key),
    CHECK(artifact_type != 'paper_brief' OR (
        paper_id IS NOT NULL AND length(trim(COALESCE(source_hash, ''))) = 64
    )),
    CHECK(artifact_type NOT IN ({PROJECT_ARTIFACT_TYPES}) OR (
        project_id IS NOT NULL AND snapshot_hash IS NOT NULL
    ))
);

CREATE TABLE research_run_papers_v9 (
    run_id TEXT NOT NULL REFERENCES research_runs_v9(id) ON DELETE CASCADE,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    source_step_id TEXT REFERENCES research_steps_v9(id) ON DELETE SET NULL,
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

CREATE TABLE research_model_calls_v9 (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs_v9(id) ON DELETE CASCADE,
    step_id TEXT NOT NULL REFERENCES research_steps_v9(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    model_name TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK(length(input_hash) = 64),
    status TEXT NOT NULL CHECK(status IN ('started', 'completed', 'failed', 'ambiguous')),
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, idempotency_key)
);

CREATE TABLE research_evidence_v9 (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs_v9(id) ON DELETE CASCADE,
    opened_by_step_id TEXT NOT NULL REFERENCES research_steps_v9(id) ON DELETE CASCADE,
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

CREATE TABLE research_citations_v9 (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs_v9(id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL REFERENCES research_artifacts_v9(id) ON DELETE CASCADE,
    artifact_version INTEGER NOT NULL CHECK(artifact_version >= 1),
    citation_key TEXT NOT NULL CHECK(length(trim(citation_key)) > 0),
    claim_id TEXT NOT NULL CHECK(length(trim(claim_id)) > 0),
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE RESTRICT,
    chunk_id INTEGER NOT NULL,
    evidence_id TEXT NOT NULL REFERENCES research_evidence_v9(id) ON DELETE RESTRICT,
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

CREATE TABLE research_project_items (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL CHECK(item_type IN ('run', 'paper', 'research_report')),
    run_id TEXT REFERENCES research_runs_v9(id) ON DELETE RESTRICT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE RESTRICT,
    artifact_id TEXT REFERENCES research_artifacts_v9(id) ON DELETE RESTRICT,
    artifact_version INTEGER CHECK(artifact_version IS NULL OR artifact_version >= 1),
    source_hash_snapshot TEXT NOT NULL CHECK(
        length(source_hash_snapshot) = 64 AND source_hash_snapshot NOT GLOB '*[^0-9a-f]*'
    ),
    position INTEGER NOT NULL CHECK(position >= 0),
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(
        (item_type = 'run' AND run_id IS NOT NULL AND paper_id IS NULL
            AND artifact_id IS NULL AND artifact_version IS NULL)
        OR (item_type = 'paper' AND run_id IS NULL AND paper_id IS NOT NULL
            AND artifact_id IS NULL AND artifact_version IS NULL)
        OR (item_type = 'research_report' AND run_id IS NULL AND paper_id IS NULL
            AND artifact_id IS NOT NULL AND artifact_version IS NOT NULL)
    )
);

CREATE TABLE research_artifact_dependencies (
    id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES research_artifacts_v9(id) ON DELETE CASCADE,
    dependency_type TEXT NOT NULL CHECK(dependency_type IN (
        'project_item', 'artifact', 'citation', 'evidence', 'paper_metadata'
    )),
    dependency_key TEXT NOT NULL CHECK(length(trim(dependency_key)) > 0),
    project_item_id TEXT,
    upstream_artifact_id TEXT REFERENCES research_artifacts_v9(id) ON DELETE RESTRICT,
    upstream_artifact_version INTEGER CHECK(
        upstream_artifact_version IS NULL OR upstream_artifact_version >= 1
    ),
    citation_id TEXT REFERENCES research_citations_v9(id) ON DELETE RESTRICT,
    evidence_id TEXT REFERENCES research_evidence_v9(id) ON DELETE RESTRICT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE RESTRICT,
    source_hash_snapshot TEXT CHECK(source_hash_snapshot IS NULL OR (
        length(source_hash_snapshot) = 64
        AND source_hash_snapshot NOT GLOB '*[^0-9a-f]*'
    )),
    dependency_hash TEXT NOT NULL CHECK(
        length(dependency_hash) = 64 AND dependency_hash NOT GLOB '*[^0-9a-f]*'
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(artifact_id, dependency_type, dependency_key),
    CHECK(
        (dependency_type = 'project_item' AND project_item_id IS NOT NULL
            AND upstream_artifact_id IS NULL AND upstream_artifact_version IS NULL
            AND citation_id IS NULL AND evidence_id IS NULL AND paper_id IS NULL)
        OR (dependency_type = 'artifact' AND project_item_id IS NULL
            AND upstream_artifact_id IS NOT NULL AND upstream_artifact_version IS NOT NULL
            AND citation_id IS NULL AND evidence_id IS NULL AND paper_id IS NULL)
        OR (dependency_type = 'citation' AND project_item_id IS NULL
            AND upstream_artifact_id IS NULL AND upstream_artifact_version IS NULL
            AND citation_id IS NOT NULL AND evidence_id IS NULL AND paper_id IS NULL)
        OR (dependency_type = 'evidence' AND project_item_id IS NULL
            AND upstream_artifact_id IS NULL AND upstream_artifact_version IS NULL
            AND citation_id IS NULL AND evidence_id IS NOT NULL AND paper_id IS NULL)
        OR (dependency_type = 'paper_metadata' AND project_item_id IS NULL
            AND upstream_artifact_id IS NULL AND upstream_artifact_version IS NULL
            AND citation_id IS NULL AND evidence_id IS NULL AND paper_id IS NOT NULL)
    )
);

CREATE TABLE research_project_citation_refs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    analysis_run_id TEXT NOT NULL REFERENCES research_runs_v9(id) ON DELETE CASCADE,
    citation_key TEXT NOT NULL CHECK(length(trim(citation_key)) BETWEEN 1 AND 120),
    reference_type TEXT NOT NULL CHECK(reference_type IN ('citation', 'evidence')),
    citation_id TEXT REFERENCES research_citations_v9(id) ON DELETE RESTRICT,
    evidence_id TEXT REFERENCES research_evidence_v9(id) ON DELETE RESTRICT,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE RESTRICT,
    source_hash_snapshot TEXT NOT NULL CHECK(
        length(source_hash_snapshot) = 64 AND source_hash_snapshot NOT GLOB '*[^0-9a-f]*'
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(analysis_run_id, citation_key),
    CHECK((reference_type = 'citation' AND citation_id IS NOT NULL AND evidence_id IS NULL)
       OR (reference_type = 'evidence' AND citation_id IS NULL AND evidence_id IS NOT NULL))
);
"""


INDEX_SQL = """
CREATE INDEX idx_research_projects_owner_status
    ON research_projects(owner_user_id, status, updated_at DESC);
CREATE INDEX idx_research_runs_user_status
    ON research_runs(user_id, status, updated_at DESC);
CREATE INDEX idx_research_runs_project
    ON research_runs(project_id, created_at DESC);
CREATE UNIQUE INDEX idx_research_runs_one_active_project
    ON research_runs(project_id) WHERE mode = 'project'
        AND status IN ('queued', 'running', 'waiting_input', 'paused', 'cancelling');
CREATE INDEX idx_research_steps_runnable
    ON research_steps(status, lease_expires_at, run_id, position);
CREATE INDEX idx_research_steps_run ON research_steps(run_id, position);
CREATE INDEX idx_research_events_run ON research_events(run_id, id);
CREATE INDEX idx_research_decisions_run
    ON research_decisions(run_id, status, created_at);
CREATE UNIQUE INDEX idx_research_decisions_one_pending
    ON research_decisions(run_id) WHERE status = 'pending';
CREATE INDEX idx_research_artifacts_run_type
    ON research_artifacts(run_id, artifact_type, version DESC);
CREATE INDEX idx_research_artifacts_paper
    ON research_artifacts(paper_id, artifact_type, version DESC);
CREATE INDEX idx_research_artifacts_project_type
    ON research_artifacts(project_id, artifact_type, version DESC);
CREATE UNIQUE INDEX idx_research_artifacts_project_version
    ON research_artifacts(project_id, artifact_type, version)
    WHERE project_id IS NOT NULL;
CREATE INDEX idx_research_run_papers_stage
    ON research_run_papers(run_id, stage, rank, paper_id);
CREATE INDEX idx_research_run_papers_source
    ON research_run_papers(source, source_id, source_hash);
CREATE INDEX idx_research_evidence_run_paper
    ON research_evidence(run_id, paper_id, source_hash, chunk_id);
CREATE INDEX idx_research_citations_run_status
    ON research_citations(run_id, status, citation_key);
CREATE INDEX idx_research_citations_evidence
    ON research_citations(evidence_id, artifact_id, artifact_version);
CREATE UNIQUE INDEX idx_project_items_unique_run
    ON research_project_items(project_id, run_id) WHERE item_type = 'run';
CREATE UNIQUE INDEX idx_project_items_unique_paper
    ON research_project_items(project_id, paper_id) WHERE item_type = 'paper';
CREATE UNIQUE INDEX idx_project_items_unique_report
    ON research_project_items(project_id, artifact_id, artifact_version)
    WHERE item_type = 'research_report';
CREATE INDEX idx_project_items_project_position
    ON research_project_items(project_id, position, added_at);
CREATE INDEX idx_project_items_run ON research_project_items(run_id, project_id);
CREATE INDEX idx_project_items_paper ON research_project_items(paper_id, project_id);
CREATE INDEX idx_project_items_artifact
    ON research_project_items(artifact_id, artifact_version, project_id);
CREATE INDEX idx_artifact_dependencies_artifact
    ON research_artifact_dependencies(artifact_id, dependency_type);
CREATE INDEX idx_artifact_dependencies_upstream
    ON research_artifact_dependencies(upstream_artifact_id, upstream_artifact_version);
CREATE INDEX idx_artifact_dependencies_citation
    ON research_artifact_dependencies(citation_id, evidence_id);
CREATE INDEX idx_project_citation_refs_project
    ON research_project_citation_refs(project_id, analysis_run_id, citation_key);
CREATE UNIQUE INDEX idx_project_citation_refs_source_citation
    ON research_project_citation_refs(analysis_run_id, citation_id)
    WHERE reference_type = 'citation';
CREATE UNIQUE INDEX idx_project_citation_refs_source_evidence
    ON research_project_citation_refs(analysis_run_id, evidence_id)
    WHERE reference_type = 'evidence';
"""


_OLD_INDEXES = (
    "idx_research_runs_user_status",
    "idx_research_steps_runnable",
    "idx_research_steps_run",
    "idx_research_events_run",
    "idx_research_decisions_run",
    "idx_research_decisions_one_pending",
    "idx_research_artifacts_run_type",
    "idx_research_artifacts_paper",
    "idx_research_run_papers_stage",
    "idx_research_run_papers_source",
    "idx_research_evidence_run_paper",
    "idx_research_citations_run_status",
    "idx_research_citations_evidence",
)


def _execute_statements(conn: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            conn.execute(statement)


def migrate_v8_to_v9(conn: sqlite3.Connection) -> None:
    for name in _OLD_INDEXES:
        conn.execute(f'DROP INDEX "{name}"')

    # Rename the complete research FK graph. Parent renames then remain confined
    # to these v8 copies while the v9 graph is built under the canonical names.
    for table in (
        "research_citations",
        "research_model_calls",
        "research_evidence",
        "research_run_papers",
        "research_artifacts",
        "research_decisions",
        "research_events",
        "research_steps",
        "research_runs",
    ):
        conn.execute(f'ALTER TABLE "{table}" RENAME TO "{table}_v8"')

    _execute_statements(conn, RESEARCH_PROJECT_SCHEMA_SQL)

    conn.execute(
        """
        INSERT INTO research_runs_v9(
            id, user_id, project_id, project_revision, input_fingerprint,
            thread_id, title, goal, mode, status,
            requested_action, state_version, plan_version, budget_json, usage_json,
            error_code, error_message, created_at, started_at, updated_at, completed_at
        )
        SELECT id, user_id, NULL, NULL, NULL, thread_id, title, goal, mode, status,
               requested_action, state_version, plan_version, budget_json, usage_json,
               error_code, error_message, created_at, started_at, updated_at, completed_at
        FROM research_runs_v8
        """
    )
    conn.execute("INSERT INTO research_steps_v9 SELECT * FROM research_steps_v8")
    conn.execute("INSERT INTO research_events_v9 SELECT * FROM research_events_v8")
    conn.execute("INSERT INTO research_decisions_v9 SELECT * FROM research_decisions_v8")
    conn.execute(
        """
        INSERT INTO research_artifacts_v9(
            id, run_id, project_id, paper_id, artifact_type, schema_version,
            source_step_id, version, status, content_json, source_hash,
            input_snapshot_json, dependency_snapshot_json, snapshot_hash,
            idempotency_key, content_hash, created_at, updated_at
        )
        SELECT id, run_id, NULL, paper_id, artifact_type, schema_version,
               source_step_id, version, status, content_json, source_hash,
               '[]', '[]', NULL, idempotency_key, content_hash, created_at, updated_at
        FROM research_artifacts_v8
        """
    )
    conn.execute("INSERT INTO research_run_papers_v9 SELECT * FROM research_run_papers_v8")
    conn.execute("INSERT INTO research_model_calls_v9 SELECT * FROM research_model_calls_v8")
    conn.execute("INSERT INTO research_evidence_v9 SELECT * FROM research_evidence_v8")
    conn.execute("INSERT INTO research_citations_v9 SELECT * FROM research_citations_v8")

    for table in (
        "research_citations_v8",
        "research_model_calls_v8",
        "research_evidence_v8",
        "research_run_papers_v8",
        "research_artifacts_v8",
        "research_decisions_v8",
        "research_events_v8",
        "research_steps_v8",
        "research_runs_v8",
    ):
        conn.execute(f'DROP TABLE "{table}"')

    # Rename parents before children so SQLite rewrites the new graph's FK
    # targets, then install all explicit indexes under their stable names.
    for temporary, canonical in (
        ("research_runs_v9", "research_runs"),
        ("research_steps_v9", "research_steps"),
        ("research_events_v9", "research_events"),
        ("research_decisions_v9", "research_decisions"),
        ("research_artifacts_v9", "research_artifacts"),
        ("research_run_papers_v9", "research_run_papers"),
        ("research_model_calls_v9", "research_model_calls"),
        ("research_evidence_v9", "research_evidence"),
        ("research_citations_v9", "research_citations"),
    ):
        conn.execute(f'ALTER TABLE "{temporary}" RENAME TO "{canonical}"')
    _execute_statements(conn, INDEX_SQL)

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError("v9 migration produced invalid foreign keys")


MIGRATION = Migration(version=9, name="research-landscape-projects", apply=migrate_v8_to_v9)

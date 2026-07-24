from __future__ import annotations

import sqlite3

from .runner import Migration


RESEARCH_SCHEMA_SQL = """
CREATE TABLE research_runs (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id TEXT REFERENCES chat_threads(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    goal TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'harness' CHECK(mode IN ('harness', 'topic', 'paper')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN (
        'queued', 'running', 'waiting_input', 'paused', 'completed', 'failed',
        'cancelling', 'cancelled'
    )),
    requested_action TEXT CHECK(requested_action IN ('pause', 'cancel')),
    state_version INTEGER NOT NULL DEFAULT 1,
    plan_version INTEGER NOT NULL DEFAULT 1,
    budget_json TEXT NOT NULL DEFAULT '{}',
    usage_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE TABLE research_steps (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
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
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT NOT NULL DEFAULT '{}',
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

CREATE TABLE research_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    step_id TEXT REFERENCES research_steps(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE research_decisions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    step_id TEXT REFERENCES research_steps(id) ON DELETE SET NULL,
    question TEXT NOT NULL,
    options_json TEXT NOT NULL,
    recommended_option TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'resolved', 'cancelled')),
    answer_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);

CREATE INDEX idx_research_runs_user_status
    ON research_runs(user_id, status, updated_at DESC);
CREATE INDEX idx_research_steps_runnable
    ON research_steps(status, lease_expires_at, run_id, position);
CREATE INDEX idx_research_steps_run
    ON research_steps(run_id, position);
CREATE INDEX idx_research_events_run
    ON research_events(run_id, id);
CREATE INDEX idx_research_decisions_run
    ON research_decisions(run_id, status, created_at);
CREATE UNIQUE INDEX idx_research_decisions_one_pending
    ON research_decisions(run_id) WHERE status = 'pending';
"""


def migrate_v4_to_v5(conn: sqlite3.Connection) -> None:
    # ``executescript`` commits implicitly in sqlite3 and would defeat the
    # migration runner's rollback savepoint. Keep every DDL statement inside it.
    for statement in RESEARCH_SCHEMA_SQL.split(";"):
        if statement.strip():
            conn.execute(statement)


MIGRATION = Migration(version=5, name="research-run-harness", apply=migrate_v4_to_v5)

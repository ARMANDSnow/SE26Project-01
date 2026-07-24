from __future__ import annotations

import sqlite3

from .runner import Migration


PAPER_PROCESSING_SCHEMA_SQL = """
CREATE TABLE paper_processing_jobs (
    id TEXT PRIMARY KEY,
    paper_id INTEGER NOT NULL UNIQUE REFERENCES papers(id) ON DELETE CASCADE,
    requested_by_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint) = 64),
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN (
        'queued', 'running', 'retry_wait', 'completed', 'failed'
    )),
    phase TEXT NOT NULL DEFAULT 'queued' CHECK(phase IN (
        'queued', 'download', 'parse', 'index', 'completed'
    )),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts BETWEEN 1 AND 10),
    next_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_owner TEXT,
    lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation >= 0),
    lease_expires_at TEXT,
    heartbeat_at TEXT,
    last_progress_at TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    CHECK((status = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
       OR (status != 'running' AND lease_owner IS NULL AND lease_expires_at IS NULL)),
    CHECK(status != 'completed' OR phase = 'completed')
);

CREATE INDEX idx_paper_processing_jobs_runnable
    ON paper_processing_jobs(status, next_attempt_at, lease_expires_at, created_at);
CREATE INDEX idx_paper_processing_jobs_requester
    ON paper_processing_jobs(requested_by_user_id, status, updated_at DESC);
"""


def _execute_statements(conn: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            conn.execute(statement)


def migrate_v9_to_v10(conn: sqlite3.Connection) -> None:
    _execute_statements(conn, PAPER_PROCESSING_SCHEMA_SQL)
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError("v10 migration produced invalid foreign keys")


MIGRATION = Migration(
    version=10,
    name="async-paper-processing",
    apply=migrate_v9_to_v10,
)

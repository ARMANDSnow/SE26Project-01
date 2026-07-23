from __future__ import annotations

import sqlite3

from .runner import Migration
from .v10 import PAPER_PROCESSING_SCHEMA_SQL, _execute_statements


def migrate_v10_to_v11(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    if "paper_processing_jobs" not in tables:
        _execute_statements(conn, PAPER_PROCESSING_SCHEMA_SQL)
    if "workspaces" not in tables:
        conn.executescript(
            """
            CREATE TABLE workspaces (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 160),
                description TEXT NOT NULL DEFAULT '',
                project_id TEXT REFERENCES research_projects(id) ON DELETE CASCADE,
                folder_id INTEGER REFERENCES library_folders(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK((project_id IS NOT NULL) != (folder_id IS NOT NULL)),
                UNIQUE(owner_user_id, title)
            );
            CREATE INDEX idx_workspaces_owner_updated
                ON workspaces(owner_user_id, updated_at DESC);
            """
        )
    thread_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(chat_threads)").fetchall()
    }
    if "workspace_id" not in thread_columns:
        conn.execute(
            "ALTER TABLE chat_threads ADD COLUMN workspace_id TEXT "
            "REFERENCES workspaces(id) ON DELETE SET NULL"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_threads_workspace "
        "ON chat_threads(user_id, workspace_id, updated_at DESC)"
    )
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError("v11 migration produced invalid foreign keys")


MIGRATION = Migration(version=11, name="chat-workspaces", apply=migrate_v10_to_v11)
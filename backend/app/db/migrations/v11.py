from __future__ import annotations

import sqlite3

from .runner import Migration


def migrate_v10_to_v11(conn: sqlite3.Connection) -> None:
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
        ALTER TABLE chat_threads ADD COLUMN workspace_id TEXT
            REFERENCES workspaces(id) ON DELETE SET NULL;
        CREATE INDEX idx_chat_threads_workspace
            ON chat_threads(user_id, workspace_id, updated_at DESC);
        """
    )


MIGRATION = Migration(version=11, name="chat-workspaces", apply=migrate_v10_to_v11)
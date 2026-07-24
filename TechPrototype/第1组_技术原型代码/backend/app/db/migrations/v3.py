from __future__ import annotations

import sqlite3

from .runner import Migration


LEGACY_PASSWORD_HASH = "!legacy-account-has-no-password"


def migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Add authentication fields and assign v2 private data to its legacy owner."""

    conn.execute("INSERT OR IGNORE INTO users(id, name) VALUES (1, 'Legacy User 1')")
    conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
    conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE users ADD COLUMN updated_at TEXT")
    conn.execute("UPDATE users SET username = 'legacy_' || id WHERE username IS NULL")
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE password_hash IS NULL",
        (LEGACY_PASSWORD_HASH,),
    )
    conn.execute("UPDATE users SET updated_at = created_at WHERE updated_at IS NULL")
    conn.execute(
        "CREATE UNIQUE INDEX uq_users_username_nocase ON users(username COLLATE NOCASE)"
    )

    conn.execute("ALTER TABLE notes RENAME TO notes_v2")
    conn.execute(
        """
        CREATE TABLE notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            note TEXT NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO notes(id, user_id, paper_id, note, comment, created_at, updated_at)
        SELECT id, 1, paper_id, note, comment, created_at, updated_at FROM notes_v2
        """
    )
    conn.execute("DROP TABLE notes_v2")

    conn.execute("ALTER TABLE reading_history RENAME TO reading_history_v2")
    conn.execute(
        """
        CREATE TABLE reading_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO reading_history(id, user_id, paper_id, action, created_at)
        SELECT id, 1, paper_id, action, created_at FROM reading_history_v2
        """
    )
    conn.execute("DROP TABLE reading_history_v2")

    conn.execute("ALTER TABLE subscriptions RENAME TO subscriptions_v2")
    conn.execute(
        """
        CREATE TABLE subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            topic TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, topic)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO subscriptions(id, user_id, topic, created_at)
        SELECT id, 1, topic, created_at FROM subscriptions_v2
        """
    )
    conn.execute("DROP TABLE subscriptions_v2")

    conn.execute("CREATE INDEX idx_notes_user_paper ON notes(user_id, paper_id, created_at DESC)")
    conn.execute(
        "CREATE INDEX idx_reading_history_user ON reading_history(user_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX idx_subscriptions_user ON subscriptions(user_id, created_at DESC)"
    )


MIGRATION = Migration(version=3, name="session-user-isolation", apply=migrate_v2_to_v3)

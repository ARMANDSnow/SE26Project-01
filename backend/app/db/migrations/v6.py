from __future__ import annotations

import json
import sqlite3

from .runner import Migration


def migrate_v5_to_v6(conn: sqlite3.Connection) -> None:
    conn.execute(
        "ALTER TABLE chat_messages ADD COLUMN content_parts_json TEXT NOT NULL DEFAULT '[]'"
    )
    rows = conn.execute("SELECT id, content FROM chat_messages").fetchall()
    for row in rows:
        message_id = row["id"] if isinstance(row, sqlite3.Row) else row[0]
        content = row["content"] if isinstance(row, sqlite3.Row) else row[1]
        encoded = json.dumps(
            [{"type": "text", "text": str(content)}],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        conn.execute(
            "UPDATE chat_messages SET content_parts_json = ? WHERE id = ?",
            (encoded, message_id),
        )


MIGRATION = Migration(version=6, name="chat-content-parts", apply=migrate_v5_to_v6)

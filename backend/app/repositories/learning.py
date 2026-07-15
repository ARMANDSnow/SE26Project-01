from __future__ import annotations

import sqlite3
from typing import Any


def add_reading_history(
    conn: sqlite3.Connection,
    paper_id: int,
    action: str,
    user_id: int = 1,
    *,
    commit: bool = True,
) -> None:
    conn.execute(
        "INSERT INTO reading_history (user_id, paper_id, action) VALUES (?, ?, ?)",
        (user_id, paper_id, action),
    )
    if commit:
        conn.commit()


def add_note(
    conn: sqlite3.Connection,
    paper_id: int,
    note: str,
    comment: str = "",
    user_id: int = 1,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    cursor = conn.execute(
        "INSERT INTO notes (user_id, paper_id, note, comment) VALUES (?, ?, ?, ?)",
        (user_id, paper_id, note, comment),
    )
    conn.execute(
        "INSERT INTO reading_history (user_id, paper_id, action) VALUES (?, ?, ?)",
        (user_id, paper_id, "新增笔记"),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        "SELECT id, paper_id, note, comment, created_at, updated_at FROM notes WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return dict(row)


def get_history(
    conn: sqlite3.Connection,
    limit: int = 30,
    user_id: int = 1,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT h.id, h.action, h.created_at, p.id AS paper_id, p.title, p.primary_category
        FROM reading_history h
        JOIN papers p ON p.id = h.paper_id
        WHERE h.user_id = ?
        ORDER BY h.created_at DESC, h.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def upsert_subscription(
    conn: sqlite3.Connection,
    topic: str,
    user_id: int = 1,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    conn.execute(
        "INSERT OR IGNORE INTO subscriptions (user_id, topic) VALUES (?, ?)",
        (user_id, topic.strip()),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        "SELECT id, topic, created_at FROM subscriptions WHERE user_id = ? AND topic = ?",
        (user_id, topic.strip()),
    ).fetchone()
    return dict(row)


def get_subscriptions(conn: sqlite3.Connection, user_id: int = 1) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, topic, created_at FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]

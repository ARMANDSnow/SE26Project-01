from __future__ import annotations

import sqlite3
from typing import Any, cast


def get_user_by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return cast(
        sqlite3.Row | None,
        conn.execute(
            """
            SELECT id, username, password_hash, is_active, created_at, updated_at
            FROM users WHERE username = ? COLLATE NOCASE
            """,
            (username,),
        ).fetchone(),
    )


def get_active_user_by_id(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return cast(
        sqlite3.Row | None,
        conn.execute(
            """
            SELECT id, username, password_hash, is_active, created_at, updated_at
            FROM users WHERE id = ? AND is_active = 1
            """,
            (user_id,),
        ).fetchone(),
    )


def create_user(
    conn: sqlite3.Connection,
    username: str,
    password_hash: str,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    try:
        cursor = conn.execute(
            """
            INSERT INTO users(name, username, password_hash, is_active, updated_at)
            VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
            """,
            (username, username, password_hash),
        )
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError("username already exists") from exc
    if commit:
        conn.commit()
    if cursor.lastrowid is None:
        raise RuntimeError("user insert did not return an id")
    row = get_active_user_by_id(conn, int(cursor.lastrowid))
    if row is None:
        raise RuntimeError("user could not be loaded after insert")
    return dict(row)


def update_password_hash(
    conn: sqlite3.Connection,
    user_id: int,
    password_hash: str,
    *,
    commit: bool = True,
) -> None:
    conn.execute(
        """
        UPDATE users
        SET password_hash = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (password_hash, user_id),
    )
    if commit:
        conn.commit()

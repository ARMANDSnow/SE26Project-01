from __future__ import annotations

import sqlite3
from typing import Any

from .uploads import accessible_paper_condition


def paper_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS count FROM papers").fetchone()["count"])


def application_stats(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    access_condition, access_params = accessible_paper_condition("p", user_id)
    accessible_count = conn.execute(
        f"SELECT COUNT(*) AS count FROM papers p WHERE {access_condition}",
        access_params,
    ).fetchone()["count"]
    processed_count = conn.execute(
        f"""
        SELECT COUNT(*) AS count FROM papers p
        WHERE p.processing_status = 'processed' AND {access_condition}
        """,
        access_params,
    ).fetchone()["count"]
    favorite_count = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM library_items i JOIN papers p ON p.id = i.paper_id
        WHERE i.user_id = ? AND {access_condition}
        """,
        (user_id, *access_params),
    ).fetchone()["count"]
    concept_count = conn.execute(
        f"""
        SELECT COUNT(DISTINCT pc.concept_id) AS count
        FROM paper_concepts pc JOIN papers p ON p.id = pc.paper_id
        WHERE {access_condition}
        """,
        access_params,
    ).fetchone()["count"]
    notes_count = conn.execute(
        "SELECT COUNT(*) AS count FROM notes WHERE user_id = ?", (user_id,)
    ).fetchone()["count"]
    categories = conn.execute(
        f"""
        SELECT p.primary_category AS category, COUNT(*) AS count
        FROM papers p WHERE {access_condition}
        GROUP BY p.primary_category ORDER BY count DESC
        """,
        access_params,
    ).fetchall()
    return {
        "papers": int(accessible_count),
        "processed": int(processed_count),
        "favorites": int(favorite_count),
        "concepts": int(concept_count),
        "notes": int(notes_count),
        "categories": [dict(row) for row in categories],
    }

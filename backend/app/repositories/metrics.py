from __future__ import annotations

import sqlite3
from typing import Any


def paper_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS count FROM papers").fetchone()["count"])


def application_stats(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    processed_count = conn.execute(
        "SELECT COUNT(*) AS count FROM papers WHERE processing_status = 'processed'"
    ).fetchone()["count"]
    favorite_count = conn.execute(
        "SELECT COUNT(*) AS count FROM library_items WHERE user_id = ?", (user_id,)
    ).fetchone()["count"]
    concept_count = conn.execute("SELECT COUNT(*) AS count FROM concepts").fetchone()["count"]
    notes_count = conn.execute(
        "SELECT COUNT(*) AS count FROM notes WHERE user_id = ?", (user_id,)
    ).fetchone()["count"]
    categories = conn.execute(
        "SELECT primary_category AS category, COUNT(*) AS count "
        "FROM papers GROUP BY primary_category ORDER BY count DESC"
    ).fetchall()
    return {
        "papers": paper_count(conn),
        "processed": int(processed_count),
        "favorites": int(favorite_count),
        "concepts": int(concept_count),
        "notes": int(notes_count),
        "categories": [dict(row) for row in categories],
    }

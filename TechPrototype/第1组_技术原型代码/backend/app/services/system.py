from __future__ import annotations

import sqlite3
from typing import Any

from ..config import get_settings
from ..repositories.metrics import application_stats, public_paper_count


def health_status(conn: sqlite3.Connection) -> dict[str, Any]:
    settings = get_settings()
    return {
        "ok": True,
        "papers": public_paper_count(conn),
        "llm_available": settings.llm_available,
        "llm_model": settings.llm_chat_model if settings.llm_available else None,
    }


def stats(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    return application_stats(conn, user_id)

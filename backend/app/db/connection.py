from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import get_settings


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path is not None else get_settings().database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if str(db_path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn

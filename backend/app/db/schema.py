from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .connection import connect
from .migrations import V3_MIGRATION, apply_migrations


PAPER_CHUNKS_FTS_TABLE = "paper_chunks_fts"
SCHEMA_VERSION = 3


class IncompatibleSchemaError(RuntimeError):
    pass


def _schema_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }


def _schema_reset_command(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    path = str(row[2]) if row is not None and row[2] else "<database-path>"
    return f'python scripts/reset_database.py --database "{path}" --apply'


def _assert_schema_compatible(conn: sqlite3.Connection) -> None:
    tables = _schema_tables(conn)
    if not tables:
        return
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version != SCHEMA_VERSION:
        raise IncompatibleSchemaError(
            f"Database schema version {version} is incompatible with required version "
            f"{SCHEMA_VERSION}. No data migration is provided; rebuild the database with: "
            f"{_schema_reset_command(conn)}"
        )

    paper_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(papers)").fetchall()}
    thread_columns = {
        str(row[1]): int(row[3]) for row in conn.execute("PRAGMA table_info(chat_threads)").fetchall()
    }
    user_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    note_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(notes)").fetchall()}
    history_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(reading_history)").fetchall()
    }
    subscription_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(subscriptions)").fetchall()
    }
    required_paper_columns = {"source", "source_id", "asset_id", "processing_status"}
    if not required_paper_columns.issubset(paper_columns) or "title_hash" in paper_columns:
        raise IncompatibleSchemaError(
            f"Database schema does not match version {SCHEMA_VERSION}; rebuild it with: "
            f"{_schema_reset_command(conn)}"
        )
    if thread_columns.get("paper_id") != 0:
        raise IncompatibleSchemaError(
            f"Database chat schema does not match version {SCHEMA_VERSION}; rebuild it with: "
            f"{_schema_reset_command(conn)}"
        )
    if not {"username", "password_hash", "is_active", "updated_at"}.issubset(user_columns):
        raise IncompatibleSchemaError(
            f"Database user schema does not match version {SCHEMA_VERSION}; rebuild it with: "
            f"{_schema_reset_command(conn)}"
        )
    if any(
        "user_id" not in columns
        for columns in (note_columns, history_columns, subscription_columns)
    ):
        raise IncompatibleSchemaError(
            f"Database private-data schema does not match version {SCHEMA_VERSION}; rebuild it with: "
            f"{_schema_reset_command(conn)}"
        )


def supports_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp._fts5_probe USING fts5(value)")
        conn.execute("DROP TABLE IF EXISTS temp._fts5_probe")
    except sqlite3.Error:
        return False
    return True


def init_paper_chunks_fts(conn: sqlite3.Connection) -> bool:
    if not supports_fts5(conn):
        return False
    try:
        existing = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (PAPER_CHUNKS_FTS_TABLE,),
        ).fetchone()
        existing_sql = str(existing["sql"] or "").lower() if existing else ""
        if existing and ("source_hash" not in existing_sql or "trigram" not in existing_sql):
            conn.execute("DROP TRIGGER IF EXISTS trg_paper_chunks_delete_fts")
            conn.execute("DROP TABLE IF EXISTS paper_chunks_fts")
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS paper_chunks_fts USING fts5(
                chunk_id UNINDEXED,
                paper_id UNINDEXED,
                source_hash UNINDEXED,
                chunk_index UNINDEXED,
                heading,
                content,
                paper_title,
                tokenize='trigram'
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_paper_chunks_delete_fts
            AFTER DELETE ON paper_chunks
            BEGIN
                DELETE FROM paper_chunks_fts WHERE rowid = OLD.id;
            END
            """
        )
    except sqlite3.Error:
        return False
    return True


def paper_chunks_fts_ready(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT rowid FROM paper_chunks_fts LIMIT 0")
    except sqlite3.Error:
        return False
    return True


def _insert_paper_chunk_fts_row(conn: sqlite3.Connection, row: sqlite3.Row | dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO paper_chunks_fts(
            rowid, chunk_id, paper_id, source_hash, chunk_index, heading, content, paper_title
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["id"],
            row["id"],
            row["paper_id"],
            row["source_hash"],
            row["chunk_index"],
            row["heading"],
            row["content"],
            row["paper_title"],
        ),
    )


def rebuild_paper_chunks_fts(conn: sqlite3.Connection, paper_id: int | None = None) -> bool:
    if not paper_chunks_fts_ready(conn):
        return False
    savepoint = "paper_chunks_fts_rebuild"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        if paper_id is None:
            conn.execute("DELETE FROM paper_chunks_fts")
            rows = conn.execute(
                """
                SELECT pc.*, p.title AS paper_title
                FROM paper_chunks pc JOIN papers p ON p.id = pc.paper_id
                ORDER BY pc.id
                """
            ).fetchall()
        else:
            conn.execute("DELETE FROM paper_chunks_fts WHERE paper_id = ?", (paper_id,))
            rows = conn.execute(
                """
                SELECT pc.*, p.title AS paper_title
                FROM paper_chunks pc JOIN papers p ON p.id = pc.paper_id
                WHERE pc.paper_id = ? ORDER BY pc.id
                """,
                (paper_id,),
            ).fetchall()
        for row in rows:
            _insert_paper_chunk_fts_row(conn, row)
    except sqlite3.Error:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        return False
    conn.execute(f"RELEASE {savepoint}")
    return True


def init_schema(conn: sqlite3.Connection) -> None:
    tables = _schema_tables(conn)
    if tables and int(conn.execute("PRAGMA user_version").fetchone()[0]) == 2:
        apply_migrations(conn, [V3_MIGRATION], target_version=SCHEMA_VERSION)
    _assert_schema_compatible(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_url TEXT,
            venue TEXT,
            pdf_url TEXT,
            asset_id TEXT,
            title TEXT NOT NULL,
            authors_json TEXT NOT NULL,
            abstract TEXT NOT NULL,
            categories_json TEXT NOT NULL,
            primary_category TEXT NOT NULL,
            published_at TEXT NOT NULL,
            updated_at TEXT,
            processing_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, source_id)
        );

        CREATE TABLE IF NOT EXISTS wiki_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            section TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(paper_id, section)
        );

        CREATE TABLE IF NOT EXISTS concepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT NOT NULL,
            embedding_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_concepts (
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
            relation TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            PRIMARY KEY (paper_id, concept_id)
        );

        CREATE TABLE IF NOT EXISTS concept_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
            target_concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
            relation TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            UNIQUE(source_concept_id, target_concept_id, relation)
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            note TEXT NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reading_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            topic TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, topic)
        );

        CREATE TABLE IF NOT EXISTS paper_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL UNIQUE REFERENCES papers(id) ON DELETE CASCADE,
            parser_name TEXT NOT NULL DEFAULT 'docling',
            parser_version TEXT,
            source_hash TEXT,
            content_markdown TEXT NOT NULL DEFAULT '',
            structure_json TEXT NOT NULL DEFAULT '{}',
            token_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT,
            parsed_at TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS paper_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            document_id INTEGER NOT NULL REFERENCES paper_documents(id) ON DELETE CASCADE,
            source_hash TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            heading TEXT NOT NULL,
            content TEXT NOT NULL,
            char_start INTEGER NOT NULL,
            char_end INTEGER NOT NULL,
            token_count INTEGER NOT NULL,
            embedding_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(paper_id, source_hash, chunk_index)
        );

        CREATE TABLE IF NOT EXISTS summary_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL DEFAULT 'paper-summary-v1',
            source_hash TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chat_threads (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
            title TEXT NOT NULL DEFAULT '新对话',
            active_leaf_id TEXT,
            message_token_limit INTEGER NOT NULL DEFAULT 12000,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
            parent_id TEXT REFERENCES chat_messages(id),
            source_message_id TEXT REFERENCES chat_messages(id),
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
            content TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'complete',
            token_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS chat_runs (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
            input_message_id TEXT NOT NULL REFERENCES chat_messages(id),
            output_message_id TEXT NOT NULL UNIQUE REFERENCES chat_messages(id),
            status TEXT NOT NULL DEFAULT 'running',
            model TEXT,
            usage_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS library_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            parent_id INTEGER REFERENCES library_folders(id) ON DELETE RESTRICT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            is_system INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, parent_id, name)
        );

        CREATE TABLE IF NOT EXISTS library_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            folder_id INTEGER NOT NULL REFERENCES library_folders(id) ON DELETE RESTRICT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, paper_id)
        );

        CREATE INDEX IF NOT EXISTS idx_papers_category ON papers(primary_category);
        CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published_at);
        CREATE INDEX IF NOT EXISTS idx_papers_source ON papers(source);
        CREATE INDEX IF NOT EXISTS idx_papers_asset ON papers(asset_id);
        CREATE INDEX IF NOT EXISTS idx_wiki_sections_section ON wiki_sections(section);
        CREATE INDEX IF NOT EXISTS idx_notes_user_paper ON notes(user_id, paper_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_reading_history_user ON reading_history(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_summary_versions_paper ON summary_versions(paper_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_paper_chunks_paper ON paper_chunks(paper_id, source_hash, chunk_index);
        CREATE INDEX IF NOT EXISTS idx_chat_threads_paper ON chat_threads(user_id, paper_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_thread ON chat_messages(thread_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_parent ON chat_messages(parent_id);
        CREATE INDEX IF NOT EXISTS idx_library_folders_user ON library_folders(user_id, parent_id);
        CREATE INDEX IF NOT EXISTS idx_library_items_folder ON library_items(user_id, folder_id);
        """
    )
    init_paper_chunks_fts(conn)
    rebuild_paper_chunks_fts(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def init_db(path: Path | str | None = None) -> None:
    with connect(path) as conn:
        init_schema(conn)

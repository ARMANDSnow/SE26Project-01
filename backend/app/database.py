from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from typing import Any

from .config import get_settings
from .models import AssetId, PaperCandidate, PaperId, PaperRecord, PaperSource
from .services.text_utils import deterministic_embedding, title_hash


PAPER_CHUNKS_FTS_TABLE = "paper_chunks_fts"


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
            title_hash TEXT NOT NULL,
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
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            note TEXT NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reading_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
            user_id INTEGER NOT NULL DEFAULT 1,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
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
            input_message_id TEXT REFERENCES chat_messages(id),
            output_message_id TEXT REFERENCES chat_messages(id),
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
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
        CREATE INDEX IF NOT EXISTS idx_papers_title_hash ON papers(title_hash);
        CREATE INDEX IF NOT EXISTS idx_papers_asset ON papers(asset_id);
        CREATE INDEX IF NOT EXISTS idx_wiki_sections_section ON wiki_sections(section);
        CREATE INDEX IF NOT EXISTS idx_notes_paper ON notes(paper_id);
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
    ensure_user_library(conn, 1)
    conn.commit()


def init_db(path: Path | str | None = None) -> None:
    with connect(path) as conn:
        init_schema(conn)


def row_to_paper_record(row: sqlite3.Row) -> PaperRecord:
    return PaperRecord(
        id=PaperId(int(row["id"])),
        source=PaperSource(str(row["source"])),
        source_id=str(row["source_id"]),
        source_url=str(row["source_url"]) if row["source_url"] is not None else None,
        venue=str(row["venue"]) if row["venue"] is not None else None,
        pdf_url=str(row["pdf_url"]) if row["pdf_url"] is not None else None,
        asset_id=AssetId(str(row["asset_id"])) if row["asset_id"] is not None else None,
        title=str(row["title"]),
        authors=tuple(json.loads(str(row["authors_json"]))),
        abstract=str(row["abstract"]),
        categories=tuple(json.loads(str(row["categories_json"]))),
        primary_category=str(row["primary_category"]),
        published_at=str(row["published_at"]),
        updated_at=str(row["updated_at"]) if row["updated_at"] is not None else None,
        title_hash=str(row["title_hash"]),
        processing_status=str(row["processing_status"]),
        created_at=str(row["created_at"]),
    )


def row_to_paper(row: sqlite3.Row, is_favorite: bool | None = None) -> dict[str, Any]:
    paper = row_to_paper_record(row)
    pdf_available = paper.asset_id is not None or paper.pdf_url is not None
    pdf_base_url = f"/api/papers/{int(paper.id)}/pdf"
    return {
        "id": int(paper.id),
        "source": paper.source.value,
        "source_id": paper.source_id,
        "source_url": paper.source_url,
        "venue": paper.venue,
        "title": paper.title,
        "authors": list(paper.authors),
        "abstract": paper.abstract,
        "categories": list(paper.categories),
        "primary_category": paper.primary_category,
        "published_at": paper.published_at,
        "updated_at": paper.updated_at,
        "pdf": {
            "available": pdf_available,
            "cached": paper.asset_id is not None,
            "view_url": pdf_base_url if pdf_available else None,
            "download_url": f"{pdf_base_url}/download" if pdf_available else None,
        },
        "processing_status": paper.processing_status,
        "is_favorite": bool(is_favorite),
        "created_at": paper.created_at,
    }


def find_existing_paper_id(conn: sqlite3.Connection, paper: PaperCandidate) -> PaperId | None:
    hash_value = title_hash(paper.title)
    row = conn.execute(
        """
        SELECT id FROM papers
        WHERE (source = ? AND source_id = ?)
           OR title_hash = ?
        ORDER BY CASE WHEN source = ? AND source_id = ? THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (paper.source.value, paper.source_id, hash_value, paper.source.value, paper.source_id),
    ).fetchone()
    return PaperId(int(row["id"])) if row is not None else None


def upsert_paper(conn: sqlite3.Connection, paper: PaperCandidate, commit: bool = True) -> PaperId:
    hash_value = title_hash(paper.title)
    existing_id = find_existing_paper_id(conn, paper)
    if existing_id is not None:
        identity_row = conn.execute(
            "SELECT source, source_id, asset_id FROM papers WHERE id = ?",
            (int(existing_id),),
        ).fetchone()
        same_source = (
            identity_row is not None
            and identity_row["source"] == paper.source.value
            and identity_row["source_id"] == paper.source_id
        )
        conn.execute(
            """
            UPDATE papers SET
                title = ?,
                authors_json = ?,
                abstract = ?,
                categories_json = ?,
                primary_category = ?,
                published_at = ?,
                updated_at = ?,
                pdf_url = CASE WHEN ? THEN ? ELSE pdf_url END,
                source_url = COALESCE(?, source_url),
                venue = COALESCE(?, venue),
                asset_id = asset_id,
                title_hash = ?,
                processing_status = ?
            WHERE id = ?
            """,
            (
                paper.title,
                json.dumps(paper.authors, ensure_ascii=False),
                paper.abstract,
                json.dumps(paper.categories, ensure_ascii=False),
                paper.primary_category,
                paper.published_at,
                paper.updated_at,
                1 if same_source else 0,
                paper.pdf_url,
                paper.source_url,
                paper.venue,
                hash_value,
                paper.processing_status,
                int(existing_id),
            ),
        )
        if paper.asset_id and identity_row is not None and identity_row["asset_id"] != str(paper.asset_id):
            set_paper_asset_id(conn, existing_id, paper.asset_id, commit=False)
        if commit:
            conn.commit()
        return existing_id

    conn.execute(
        """
        INSERT INTO papers (
            source, source_id, source_url, venue, pdf_url, asset_id,
            title, authors_json, abstract, categories_json, primary_category,
            published_at, updated_at, title_hash, processing_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper.source.value,
            paper.source_id,
            paper.source_url,
            paper.venue,
            paper.pdf_url,
            str(paper.asset_id) if paper.asset_id else None,
            paper.title,
            json.dumps(paper.authors, ensure_ascii=False),
            paper.abstract,
            json.dumps(paper.categories, ensure_ascii=False),
            paper.primary_category,
            paper.published_at,
            paper.updated_at,
            hash_value,
            paper.processing_status,
        ),
    )
    row = conn.execute(
        "SELECT id FROM papers WHERE source = ? AND source_id = ?",
        (paper.source.value, paper.source_id),
    ).fetchone()
    if commit:
        conn.commit()
    return PaperId(int(row["id"]))


def get_paper_record(conn: sqlite3.Connection, paper_id: PaperId | int) -> PaperRecord | None:
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (int(paper_id),)).fetchone()
    return row_to_paper_record(row) if row is not None else None


def set_paper_asset_id(
    conn: sqlite3.Connection,
    paper_id: PaperId | int,
    asset_id: AssetId | None,
    *,
    commit: bool = True,
) -> None:
    row = conn.execute("SELECT asset_id FROM papers WHERE id = ?", (int(paper_id),)).fetchone()
    if row is None:
        raise ValueError("paper not found")
    next_asset_id = str(asset_id) if asset_id else None
    if row["asset_id"] != next_asset_id:
        conn.execute("DELETE FROM paper_documents WHERE paper_id = ?", (int(paper_id),))
        conn.execute("UPDATE summary_versions SET is_active = 0 WHERE paper_id = ?", (int(paper_id),))
        conn.execute("DELETE FROM wiki_sections WHERE paper_id = ?", (int(paper_id),))
        conn.execute("DELETE FROM paper_concepts WHERE paper_id = ?", (int(paper_id),))
        rebuild_concept_edges(conn)
    cursor = conn.execute(
        "UPDATE papers SET asset_id = ? WHERE id = ?",
        (next_asset_id, int(paper_id)),
    )
    if cursor.rowcount == 0:
        raise ValueError("paper not found")
    if commit:
        conn.commit()


def paper_exists(conn: sqlite3.Connection, paper_id: int) -> bool:
    return conn.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone() is not None


def replace_paper_chunks(
    conn: sqlite3.Connection,
    paper_id: int,
    source_hash: str,
    chunks: list[dict[str, Any]],
    *,
    commit: bool = True,
) -> None:
    document = conn.execute(
        "SELECT id, status, source_hash FROM paper_documents WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if document is None or document["status"] != "completed" or document["source_hash"] != source_hash:
        raise ValueError("paper document is not current")
    savepoint = "replace_paper_chunks"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        conn.execute("DELETE FROM paper_chunks WHERE paper_id = ?", (paper_id,))
        for chunk in chunks:
            content = str(chunk["content"]).strip()
            if not content:
                continue
            conn.execute(
                """
                INSERT INTO paper_chunks(
                    paper_id, document_id, source_hash, chunk_index, heading, content,
                    char_start, char_end, token_count, embedding_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    int(document["id"]),
                    source_hash,
                    int(chunk["chunk_index"]),
                    str(chunk.get("heading") or f"Document #{int(chunk['chunk_index']) + 1}"),
                    content,
                    int(chunk["char_start"]),
                    int(chunk["char_end"]),
                    int(chunk["token_count"]),
                    json.dumps(deterministic_embedding(content), ensure_ascii=False),
                ),
            )
    except sqlite3.Error:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise
    conn.execute(f"RELEASE {savepoint}")
    rebuild_paper_chunks_fts(conn, paper_id)
    if commit:
        conn.commit()


def list_paper_chunks(
    conn: sqlite3.Connection,
    paper_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    current = conn.execute(
        "SELECT source_hash FROM paper_documents WHERE paper_id = ? AND status = 'completed'",
        (paper_id,),
    ).fetchone()
    if current is None or not current["source_hash"]:
        return [], 0
    params = (paper_id, current["source_hash"])
    total = conn.execute(
        "SELECT COUNT(*) AS count FROM paper_chunks WHERE paper_id = ? AND source_hash = ?",
        params,
    ).fetchone()["count"]
    rows = conn.execute(
        """
        SELECT id, paper_id, source_hash, chunk_index, heading, content,
               char_start, char_end, token_count, created_at
        FROM paper_chunks
        WHERE paper_id = ? AND source_hash = ?
        ORDER BY chunk_index LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    return [dict(row) for row in rows], int(total)


def replace_wiki_sections(
    conn: sqlite3.Connection,
    paper_id: int,
    sections: dict[str, str],
    commit: bool = True,
) -> None:
    labels = {
        "summary": "summary.md",
        "concepts": "concepts.md",
        "methods": "methods.md",
        "experiments": "experiments.md",
    }
    for section, content in sections.items():
        conn.execute(
            """
            INSERT INTO wiki_sections (paper_id, section, title, content, embedding_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(paper_id, section) DO UPDATE SET
                title = excluded.title,
                content = excluded.content,
                embedding_json = excluded.embedding_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                paper_id,
                section,
                labels.get(section, f"{section}.md"),
                content,
                "[]",
            ),
        )
    if commit:
        conn.commit()


def attach_concepts(
    conn: sqlite3.Connection,
    paper_id: int,
    concepts: list[dict[str, Any]],
    commit: bool = True,
) -> None:
    cleaned_concepts = [concept for concept in concepts if concept.get("name", "").strip()]
    conn.execute("DELETE FROM paper_concepts WHERE paper_id = ?", (paper_id,))
    for concept in cleaned_concepts:
        name = concept["name"].strip()
        description = concept.get("description", f"{name} 相关概念")
        conn.execute(
            """
            INSERT INTO concepts (name, description, embedding_json)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET description = excluded.description
            """,
            (name, description, "[]"),
        )
        concept_row = conn.execute("SELECT id FROM concepts WHERE name = ?", (name,)).fetchone()
        conn.execute(
            """
            INSERT INTO paper_concepts (paper_id, concept_id, relation, weight)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(paper_id, concept_id) DO UPDATE SET
                relation = excluded.relation,
                weight = excluded.weight
            """,
            (
                paper_id,
                int(concept_row["id"]),
                concept.get("relation", "涉及"),
                float(concept.get("weight", 1.0)),
            ),
        )
    conn.execute(
        "DELETE FROM concepts WHERE NOT EXISTS (SELECT 1 FROM paper_concepts pc WHERE pc.concept_id = concepts.id)"
    )
    rebuild_concept_edges(conn)
    if commit:
        conn.commit()


def rebuild_concept_edges(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM concept_edges")
    rows = conn.execute(
        "SELECT paper_id, concept_id FROM paper_concepts ORDER BY paper_id, concept_id"
    ).fetchall()
    by_paper: dict[int, list[int]] = {}
    for row in rows:
        by_paper.setdefault(int(row["paper_id"]), []).append(int(row["concept_id"]))
    for concept_ids in by_paper.values():
        for index, source_id in enumerate(concept_ids):
            for target_id in concept_ids[index + 1 :]:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO concept_edges(
                        source_concept_id, target_concept_id, relation, weight
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (source_id, target_id, "共同出现在论文中", 0.75),
                )


def list_papers(
    conn: sqlite3.Connection,
    q: str = "",
    category: str = "",
    concept: str = "",
    author: str = "",
    favorite: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    user_id: int = 1,
) -> list[dict[str, Any]]:
    ensure_user_library(conn, user_id)
    saved_ids = {
        int(row["paper_id"])
        for row in conn.execute("SELECT paper_id FROM library_items WHERE user_id = ?", (user_id,)).fetchall()
    }
    rows = conn.execute("SELECT * FROM papers ORDER BY published_at DESC").fetchall()
    query = q.strip().lower()
    author_query = author.strip().lower()
    concept_query = concept.strip().lower()
    results: list[dict[str, Any]] = []
    for row in rows:
        paper = row_to_paper(row, int(row["id"]) in saved_ids)
        haystack = " ".join(
            [paper["title"], paper["abstract"], " ".join(paper["authors"]), " ".join(paper["categories"])]
        ).lower()
        if query and query not in haystack:
            continue
        if category and category not in paper["categories"] and category != paper["primary_category"]:
            continue
        if author_query and author_query not in " ".join(paper["authors"]).lower():
            continue
        if favorite is not None and paper["is_favorite"] != favorite:
            continue
        if concept_query:
            concept_rows = conn.execute(
                """
                SELECT c.name FROM concepts c
                JOIN paper_concepts pc ON pc.concept_id = c.id
                WHERE pc.paper_id = ?
                """,
                (paper["id"],),
            ).fetchall()
            if not any(concept_query in item["name"].lower() for item in concept_rows):
                continue
        results.append(paper)
    return results[offset : offset + limit]


def get_paper_detail(conn: sqlite3.Connection, paper_id: int, user_id: int = 1) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if row is None:
        return None
    saved = conn.execute(
        "SELECT 1 FROM library_items WHERE user_id = ? AND paper_id = ?",
        (user_id, paper_id),
    ).fetchone() is not None
    paper = row_to_paper(row, saved)
    sections = conn.execute(
        "SELECT section, title, content, updated_at FROM wiki_sections WHERE paper_id = ? ORDER BY id",
        (paper_id,),
    ).fetchall()
    concepts = conn.execute(
        """
        SELECT c.id, c.name, c.description, pc.relation, pc.weight
        FROM concepts c
        JOIN paper_concepts pc ON pc.concept_id = c.id
        WHERE pc.paper_id = ?
        ORDER BY pc.weight DESC, c.name
        """,
        (paper_id,),
    ).fetchall()
    notes = conn.execute(
        "SELECT id, note, comment, created_at, updated_at FROM notes WHERE paper_id = ? ORDER BY created_at DESC",
        (paper_id,),
    ).fetchall()
    document = conn.execute(
        """
        SELECT parser_name, parser_version, source_hash, content_markdown, token_count,
               status, error, parsed_at, updated_at
        FROM paper_documents WHERE paper_id = ?
        """,
        (paper_id,),
    ).fetchone()
    summaries = conn.execute(
        """
        SELECT id, content, model, prompt_version, source_hash, is_active, created_at
        FROM summary_versions WHERE paper_id = ? ORDER BY created_at DESC, id DESC
        """,
        (paper_id,),
    ).fetchall()
    paper["wiki"] = [dict(item) for item in sections]
    paper["concepts"] = [dict(item) for item in concepts]
    paper["notes"] = [dict(item) for item in notes]
    paper["document"] = dict(document) if document else None
    paper["summaries"] = [dict(item) for item in summaries]
    return paper


def set_favorite(conn: sqlite3.Connection, paper_id: int, favorite: bool, user_id: int = 1) -> dict[str, Any]:
    if conn.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone() is None:
        conn.rollback()
        raise ValueError("paper not found")
    folders = ensure_user_library(conn, user_id)
    if favorite:
        conn.execute(
            "INSERT OR IGNORE INTO library_items (user_id, paper_id, folder_id) VALUES (?, ?, ?)",
            (user_id, paper_id, folders["inbox_id"]),
        )
    else:
        conn.execute("DELETE FROM library_items WHERE user_id = ? AND paper_id = ?", (user_id, paper_id))
    conn.execute(
        "INSERT INTO reading_history (paper_id, action) VALUES (?, ?)",
        (paper_id, "收藏" if favorite else "取消收藏"),
    )
    conn.commit()
    detail = get_paper_detail(conn, paper_id, user_id=user_id)
    if detail is None:
        raise ValueError("paper not found")
    return detail


def ensure_user_library(conn: sqlite3.Connection, user_id: int) -> dict[str, int]:
    conn.execute("INSERT OR IGNORE INTO users (id, name) VALUES (?, ?)", (user_id, f"用户 {user_id}"))
    root = conn.execute(
        "SELECT id FROM library_folders WHERE user_id = ? AND parent_id IS NULL AND is_system = 1",
        (user_id,),
    ).fetchone()
    if root is None:
        cursor = conn.execute(
            "INSERT INTO library_folders (user_id, parent_id, name, description, is_system) VALUES (?, NULL, ?, ?, 1)",
            (user_id, "我的资料库", "个人论文资料库根目录"),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("failed to create root library folder")
        root_id = int(cursor.lastrowid)
    else:
        root_id = int(root["id"])
    inbox = conn.execute(
        "SELECT id FROM library_folders WHERE user_id = ? AND parent_id = ? AND is_system = 1",
        (user_id, root_id),
    ).fetchone()
    if inbox is None:
        cursor = conn.execute(
            "INSERT INTO library_folders (user_id, parent_id, name, description, is_system) VALUES (?, ?, ?, ?, 1)",
            (user_id, root_id, "待整理", "新收藏的论文默认放在这里"),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("failed to create inbox library folder")
        inbox_id = int(cursor.lastrowid)
    else:
        inbox_id = int(inbox["id"])
    return {"root_id": root_id, "inbox_id": inbox_id}


def list_library_folders(conn: sqlite3.Connection, user_id: int = 1) -> list[dict[str, Any]]:
    defaults = ensure_user_library(conn, user_id)
    rows = conn.execute(
        """
        SELECT f.*, COUNT(i.id) AS item_count
        FROM library_folders f
        LEFT JOIN library_items i ON i.folder_id = f.id AND i.user_id = f.user_id
        WHERE f.user_id = ?
        GROUP BY f.id
        ORDER BY f.is_system DESC, lower(f.name), f.id
        """,
        (user_id,),
    ).fetchall()
    by_id = {int(row["id"]): row for row in rows}

    def path_for(folder_id: int) -> str:
        names: list[str] = []
        current = by_id.get(folder_id)
        seen: set[int] = set()
        while current is not None and int(current["id"]) not in seen:
            seen.add(int(current["id"]))
            names.append(str(current["name"]))
            current = by_id.get(int(current["parent_id"])) if current["parent_id"] is not None else None
        return " / ".join(reversed(names))

    payload = [
        {
            "id": int(row["id"]),
            "parent_id": int(row["parent_id"]) if row["parent_id"] is not None else None,
            "name": row["name"],
            "description": row["description"],
            "is_system": bool(row["is_system"]),
            "item_count": int(row["item_count"]),
            "path": path_for(int(row["id"])),
            "is_root": int(row["id"]) == defaults["root_id"],
        }
        for row in rows
    ]
    children: dict[int | None, list[dict[str, Any]]] = {}
    for folder in payload:
        children.setdefault(folder["parent_id"], []).append(folder)
    for entries in children.values():
        entries.sort(key=lambda folder: (not folder["is_system"], folder["name"].casefold(), folder["id"]))
    ordered: list[dict[str, Any]] = []

    def visit(parent_id: int | None) -> None:
        for folder in children.get(parent_id, []):
            ordered.append(folder)
            visit(folder["id"])

    visit(None)
    return ordered


def create_library_folder(
    conn: sqlite3.Connection,
    name: str,
    parent_id: int | None = None,
    description: str = "",
    user_id: int = 1,
) -> dict[str, Any]:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("folder name is required")
    defaults = ensure_user_library(conn, user_id)
    target_parent = parent_id or defaults["root_id"]
    parent = conn.execute(
        "SELECT id FROM library_folders WHERE id = ? AND user_id = ?",
        (target_parent, user_id),
    ).fetchone()
    if parent is None:
        raise ValueError("folder not found")
    try:
        cursor = conn.execute(
            "INSERT INTO library_folders (user_id, parent_id, name, description) VALUES (?, ?, ?, ?)",
            (user_id, target_parent, clean_name, description.strip()),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError("folder already exists") from exc
    return next(folder for folder in list_library_folders(conn, user_id) if folder["id"] == cursor.lastrowid)


def delete_library_folder(conn: sqlite3.Connection, folder_id: int, user_id: int = 1) -> None:
    folder = conn.execute(
        "SELECT is_system FROM library_folders WHERE id = ? AND user_id = ?",
        (folder_id, user_id),
    ).fetchone()
    if folder is None:
        raise ValueError("folder not found")
    if folder["is_system"]:
        raise ValueError("system folder cannot be deleted")
    has_content = conn.execute(
        "SELECT 1 FROM library_items WHERE folder_id = ? UNION SELECT 1 FROM library_folders WHERE parent_id = ? LIMIT 1",
        (folder_id, folder_id),
    ).fetchone()
    if has_content is not None:
        raise ValueError("folder is not empty")
    conn.execute("DELETE FROM library_folders WHERE id = ? AND user_id = ?", (folder_id, user_id))
    conn.commit()


def list_library_items(conn: sqlite3.Connection, folder_id: int | None = None, user_id: int = 1) -> list[dict[str, Any]]:
    ensure_user_library(conn, user_id)
    params: list[Any] = [user_id]
    where = "i.user_id = ?"
    if folder_id is not None:
        where += " AND i.folder_id = ?"
        params.append(folder_id)
    rows = conn.execute(
        f"""
        SELECT i.id AS library_item_id, i.folder_id, i.created_at AS saved_at, p.*
        FROM library_items i JOIN papers p ON p.id = i.paper_id
        WHERE {where}
        ORDER BY i.updated_at DESC, i.id DESC
        """,
        params,
    ).fetchall()
    items = []
    for row in rows:
        paper = row_to_paper(row, True)
        paper.update({"library_item_id": int(row["library_item_id"]), "folder_id": int(row["folder_id"]), "saved_at": row["saved_at"]})
        items.append(paper)
    return items


def move_library_item(conn: sqlite3.Connection, item_id: int, folder_id: int, user_id: int = 1) -> dict[str, Any]:
    folder = conn.execute(
        "SELECT id FROM library_folders WHERE id = ? AND user_id = ?",
        (folder_id, user_id),
    ).fetchone()
    if folder is None:
        raise ValueError("folder not found")
    cursor = conn.execute(
        "UPDATE library_items SET folder_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
        (folder_id, item_id, user_id),
    )
    if cursor.rowcount == 0:
        conn.rollback()
        raise ValueError("library item not found")
    conn.commit()
    return next(item for item in list_library_items(conn, user_id=user_id) if item["library_item_id"] == item_id)


def add_note(conn: sqlite3.Connection, paper_id: int, note: str, comment: str = "") -> dict[str, Any]:
    cursor = conn.execute(
        "INSERT INTO notes (paper_id, note, comment) VALUES (?, ?, ?)",
        (paper_id, note, comment),
    )
    conn.execute("INSERT INTO reading_history (paper_id, action) VALUES (?, ?)", (paper_id, "新增笔记"))
    conn.commit()
    row = conn.execute(
        "SELECT id, paper_id, note, comment, created_at, updated_at FROM notes WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return dict(row)


def get_history(conn: sqlite3.Connection, limit: int = 30) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT h.id, h.action, h.created_at, p.id AS paper_id, p.title, p.primary_category
        FROM reading_history h
        JOIN papers p ON p.id = h.paper_id
        ORDER BY h.created_at DESC, h.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def upsert_subscription(conn: sqlite3.Connection, topic: str) -> dict[str, Any]:
    conn.execute("INSERT OR IGNORE INTO subscriptions (topic) VALUES (?)", (topic.strip(),))
    conn.commit()
    row = conn.execute("SELECT id, topic, created_at FROM subscriptions WHERE topic = ?", (topic.strip(),)).fetchone()
    return dict(row)


def get_subscriptions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT id, topic, created_at FROM subscriptions ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]

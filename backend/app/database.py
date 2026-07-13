from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from typing import Any

from .config import get_settings
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


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arxiv_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            authors_json TEXT NOT NULL,
            abstract TEXT NOT NULL,
            categories_json TEXT NOT NULL,
            primary_category TEXT NOT NULL,
            published_at TEXT NOT NULL,
            updated_at TEXT,
            pdf_url TEXT,
            arxiv_url TEXT,
            doi TEXT,
            title_hash TEXT UNIQUE NOT NULL,
            processing_status TEXT NOT NULL DEFAULT 'pending',
            reading_status TEXT NOT NULL DEFAULT 'unread',
            is_favorite INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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

        CREATE TABLE IF NOT EXISTS paper_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            source_url TEXT,
            chunk_index INTEGER NOT NULL,
            heading TEXT NOT NULL,
            content TEXT NOT NULL,
            char_start INTEGER NOT NULL,
            char_end INTEGER NOT NULL,
            token_count INTEGER NOT NULL,
            embedding_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(paper_id, chunk_index)
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

        CREATE INDEX IF NOT EXISTS idx_papers_category ON papers(primary_category);
        CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published_at);
        CREATE INDEX IF NOT EXISTS idx_wiki_sections_section ON wiki_sections(section);
        CREATE INDEX IF NOT EXISTS idx_paper_chunks_paper ON paper_chunks(paper_id, chunk_index);
        CREATE INDEX IF NOT EXISTS idx_paper_chunks_source ON paper_chunks(source_type);
        CREATE INDEX IF NOT EXISTS idx_notes_paper ON notes(paper_id);
        """
    )
    if supports_fts5(conn):
        init_paper_chunks_fts(conn)
        rebuild_paper_chunks_fts(conn)
    conn.commit()


def supports_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp._fts5_probe USING fts5(value)")
        conn.execute("DROP TABLE IF EXISTS temp._fts5_probe")
    except sqlite3.Error:
        return False
    return True


def init_paper_chunks_fts(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?",
            (PAPER_CHUNKS_FTS_TABLE,),
        ).fetchone()
        if row is not None and "tokenize='trigram'" not in str(row["sql"] or "").lower():
            disable_paper_chunks_fts(conn)
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS paper_chunks_fts USING fts5(
                chunk_id UNINDEXED,
                paper_id UNINDEXED,
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
                SELECT pc.id, pc.paper_id, pc.chunk_index, pc.heading, pc.content, p.title AS paper_title
                FROM paper_chunks pc
                JOIN papers p ON p.id = pc.paper_id
                ORDER BY pc.id
                """
            ).fetchall()
        else:
            conn.execute("DELETE FROM paper_chunks_fts WHERE paper_id = ?", (paper_id,))
            rows = conn.execute(
                """
                SELECT pc.id, pc.paper_id, pc.chunk_index, pc.heading, pc.content, p.title AS paper_title
                FROM paper_chunks pc
                JOIN papers p ON p.id = pc.paper_id
                WHERE pc.paper_id = ?
                ORDER BY pc.id
                """,
                (paper_id,),
            ).fetchall()
        for row in rows:
            insert_paper_chunk_fts_row(conn, row)
    except sqlite3.Error:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        return False
    conn.execute(f"RELEASE {savepoint}")
    return True


def insert_paper_chunk_fts_row(conn: sqlite3.Connection, row: sqlite3.Row | dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO paper_chunks_fts (
            rowid, chunk_id, paper_id, chunk_index, heading, content, paper_title
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(row["id"]),
            int(row["id"]),
            int(row["paper_id"]),
            int(row["chunk_index"]),
            str(row["heading"] or ""),
            str(row["content"] or ""),
            str(row["paper_title"] or ""),
        ),
    )


def delete_paper_chunks_fts(conn: sqlite3.Connection, paper_id: int) -> None:
    if paper_chunks_fts_ready(conn):
        conn.execute("DELETE FROM paper_chunks_fts WHERE paper_id = ?", (paper_id,))


def disable_paper_chunks_fts(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("DROP TRIGGER IF EXISTS trg_paper_chunks_delete_fts")
        conn.execute("DROP TABLE IF EXISTS paper_chunks_fts")
    except sqlite3.Error:
        pass


def init_db(path: Path | str | None = None) -> None:
    with connect(path) as conn:
        init_schema(conn)
        from .seed_data import seed_database

        seed_database(conn)


def row_to_paper(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "arxiv_id": row["arxiv_id"],
        "title": row["title"],
        "authors": json.loads(row["authors_json"]),
        "abstract": row["abstract"],
        "categories": json.loads(row["categories_json"]),
        "primary_category": row["primary_category"],
        "published_at": row["published_at"],
        "updated_at": row["updated_at"],
        "pdf_url": row["pdf_url"],
        "arxiv_url": row["arxiv_url"],
        "doi": row["doi"],
        "processing_status": row["processing_status"],
        "reading_status": row["reading_status"],
        "is_favorite": bool(row["is_favorite"]),
        "created_at": row["created_at"],
    }


def paper_exists(conn: sqlite3.Connection, paper_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return row is not None


def find_existing_paper_id(conn: sqlite3.Connection, paper: dict[str, Any]) -> int | None:
    hash_value = paper.get("title_hash") or title_hash(paper["title"])
    row = conn.execute(
        """
        SELECT id FROM papers
        WHERE arxiv_id = ? OR title_hash = ?
        ORDER BY CASE WHEN arxiv_id = ? THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (paper["arxiv_id"], hash_value, paper["arxiv_id"]),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def upsert_paper(conn: sqlite3.Connection, paper: dict[str, Any], commit: bool = True) -> int:
    authors = paper.get("authors", [])
    categories = paper.get("categories", [])
    primary_category = paper.get("primary_category") or (categories[0] if categories else "cs.AI")
    hash_value = paper.get("title_hash") or title_hash(paper["title"])
    existing_id = find_existing_paper_id(conn, paper)
    if existing_id is not None:
        identity_row = conn.execute(
            "SELECT arxiv_id FROM papers WHERE id = ?",
            (existing_id,),
        ).fetchone()
        same_arxiv_id = identity_row is not None and identity_row["arxiv_id"] == paper["arxiv_id"]
        conn.execute(
            """
            UPDATE papers SET
                title = ?,
                title_hash = CASE
                    WHEN NOT EXISTS (
                        SELECT 1 FROM papers AS other
                        WHERE other.title_hash = ? AND other.id != ?
                    )
                    THEN ?
                    ELSE title_hash
                END,
                authors_json = ?,
                abstract = ?,
                categories_json = ?,
                primary_category = ?,
                published_at = ?,
                updated_at = ?,
                pdf_url = CASE WHEN ? THEN ? ELSE pdf_url END,
                arxiv_url = CASE WHEN ? THEN ? ELSE arxiv_url END,
                doi = COALESCE(?, doi)
            WHERE id = ?
            """,
            (
                paper["title"],
                hash_value,
                existing_id,
                hash_value,
                json.dumps(authors, ensure_ascii=False),
                paper["abstract"],
                json.dumps(categories, ensure_ascii=False),
                primary_category,
                paper["published_at"],
                paper.get("updated_at"),
                1 if same_arxiv_id else 0,
                paper.get("pdf_url"),
                1 if same_arxiv_id else 0,
                paper.get("arxiv_url"),
                paper.get("doi"),
                existing_id,
            ),
        )
        rebuild_paper_chunks_fts(conn, existing_id)
        if commit:
            conn.commit()
        return existing_id

    conn.execute(
        """
        INSERT INTO papers (
            arxiv_id, title, authors_json, abstract, categories_json, primary_category,
            published_at, updated_at, pdf_url, arxiv_url, doi, title_hash,
            processing_status, reading_status, is_favorite
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(arxiv_id) DO UPDATE SET
            title = excluded.title,
            authors_json = excluded.authors_json,
            abstract = excluded.abstract,
            categories_json = excluded.categories_json,
            primary_category = excluded.primary_category,
            published_at = excluded.published_at,
            updated_at = excluded.updated_at,
            pdf_url = excluded.pdf_url,
            arxiv_url = excluded.arxiv_url,
            doi = excluded.doi,
            title_hash = CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM papers AS other
                    WHERE other.title_hash = excluded.title_hash AND other.id != papers.id
                )
                THEN excluded.title_hash
                ELSE papers.title_hash
            END
        """,
        (
            paper["arxiv_id"],
            paper["title"],
            json.dumps(authors, ensure_ascii=False),
            paper["abstract"],
            json.dumps(categories, ensure_ascii=False),
            primary_category,
            paper["published_at"],
            paper.get("updated_at"),
            paper.get("pdf_url"),
            paper.get("arxiv_url"),
            paper.get("doi"),
            hash_value,
            paper.get("processing_status", "pending"),
            paper.get("reading_status", "unread"),
            1 if paper.get("is_favorite") else 0,
        ),
    )
    row = conn.execute("SELECT id FROM papers WHERE arxiv_id = ?", (paper["arxiv_id"],)).fetchone()
    if row is not None:
        rebuild_paper_chunks_fts(conn, int(row["id"]))
    if commit:
        conn.commit()
    return int(row["id"])


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
                json.dumps(deterministic_embedding(content)),
            ),
        )
    if commit:
        conn.commit()


def replace_paper_chunks(
    conn: sqlite3.Connection,
    paper_id: int,
    chunks: list[dict[str, Any]],
    commit: bool = True,
) -> None:
    savepoint = "replace_paper_chunks"
    fts_ready = paper_chunks_fts_ready(conn)
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        _replace_paper_chunks(conn, paper_id, chunks, sync_fts=fts_ready)
    except sqlite3.IntegrityError:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise
    except sqlite3.Error:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        if not fts_ready:
            raise
        disable_paper_chunks_fts(conn)
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            _replace_paper_chunks(conn, paper_id, chunks, sync_fts=False)
        except sqlite3.Error:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
            raise
        else:
            conn.execute(f"RELEASE {savepoint}")
    else:
        conn.execute(f"RELEASE {savepoint}")
    if commit:
        conn.commit()


def _replace_paper_chunks(
    conn: sqlite3.Connection,
    paper_id: int,
    chunks: list[dict[str, Any]],
    sync_fts: bool,
) -> None:
    paper_row = conn.execute("SELECT title FROM papers WHERE id = ?", (paper_id,)).fetchone()
    paper_title = paper_row["title"] if paper_row is not None else ""
    if sync_fts:
        delete_paper_chunks_fts(conn, paper_id)
    conn.execute("DELETE FROM paper_chunks WHERE paper_id = ?", (paper_id,))
    for index, chunk in enumerate(chunks):
        content = str(chunk.get("content", "")).strip()
        if not content:
            continue
        chunk_index = int(chunk.get("chunk_index", index))
        cursor = conn.execute(
            """
            INSERT INTO paper_chunks (
                paper_id, source_type, source_url, chunk_index, heading, content,
                char_start, char_end, token_count, embedding_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                str(chunk.get("source_type", "metadata")),
                chunk.get("source_url") or "",
                chunk_index,
                str(chunk.get("heading", f"Chunk {chunk_index + 1}")),
                content,
                int(chunk.get("char_start", 0)),
                int(chunk.get("char_end", len(content))),
                int(chunk.get("token_count", 0)),
                json.dumps(deterministic_embedding(content)),
            ),
        )
        if sync_fts:
            chunk_id = int(cursor.lastrowid)
            insert_paper_chunk_fts_row(
                conn,
                {
                    "id": chunk_id,
                    "paper_id": paper_id,
                    "chunk_index": chunk_index,
                    "heading": str(chunk.get("heading", f"Chunk {chunk_index + 1}")),
                    "content": content,
                    "paper_title": paper_title,
                },
            )


def list_paper_chunks(
    conn: sqlite3.Connection,
    paper_id: int,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    total = conn.execute(
        "SELECT COUNT(*) AS count FROM paper_chunks WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()["count"]
    rows = conn.execute(
        """
        SELECT id, paper_id, source_type, source_url, chunk_index, heading, content,
               char_start, char_end, token_count, created_at
        FROM paper_chunks
        WHERE paper_id = ?
        ORDER BY chunk_index
        LIMIT ? OFFSET ?
        """,
        (paper_id, limit, offset),
    ).fetchall()
    return [dict(row) for row in rows], int(total)


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
            (name, description, json.dumps(deterministic_embedding(name + " " + description))),
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
                    INSERT OR IGNORE INTO concept_edges (
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
) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM papers ORDER BY published_at DESC").fetchall()
    query = q.strip().lower()
    author_query = author.strip().lower()
    concept_query = concept.strip().lower()
    results: list[dict[str, Any]] = []
    for row in rows:
        paper = row_to_paper(row)
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


def get_paper_detail(conn: sqlite3.Connection, paper_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if row is None:
        return None
    paper = row_to_paper(row)
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
    chunk_count = conn.execute(
        "SELECT COUNT(*) AS count FROM paper_chunks WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()["count"]
    paper["wiki"] = [dict(item) for item in sections]
    paper["concepts"] = [dict(item) for item in concepts]
    paper["notes"] = [dict(item) for item in notes]
    paper["chunk_count"] = int(chunk_count)
    return paper


def set_favorite(conn: sqlite3.Connection, paper_id: int, favorite: bool) -> dict[str, Any]:
    cursor = conn.execute("UPDATE papers SET is_favorite = ? WHERE id = ?", (1 if favorite else 0, paper_id))
    if cursor.rowcount == 0:
        conn.rollback()
        raise ValueError("paper not found")
    conn.execute(
        "INSERT INTO reading_history (paper_id, action) VALUES (?, ?)",
        (paper_id, "收藏" if favorite else "取消收藏"),
    )
    conn.commit()
    detail = get_paper_detail(conn, paper_id)
    if detail is None:
        raise ValueError("paper not found")
    return detail


def add_note(conn: sqlite3.Connection, paper_id: int, note: str, comment: str = "") -> dict[str, Any]:
    cursor = conn.execute(
        "INSERT INTO notes (paper_id, note, comment) VALUES (?, ?, ?)",
        (paper_id, note, comment),
    )
    conn.execute("UPDATE papers SET reading_status = 'reading' WHERE id = ?", (paper_id,))
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

from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from typing import Any

from .config import get_settings
from .services.text_utils import deterministic_embedding, title_hash


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path is not None else get_settings().database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
        CREATE INDEX IF NOT EXISTS idx_notes_paper ON notes(paper_id);
        """
    )
    conn.commit()


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


def upsert_paper(conn: sqlite3.Connection, paper: dict[str, Any]) -> int:
    authors = paper.get("authors", [])
    categories = paper.get("categories", [])
    primary_category = paper.get("primary_category") or (categories[0] if categories else "cs.AI")
    hash_value = paper.get("title_hash") or title_hash(paper["title"])
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
            doi = excluded.doi
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
    conn.commit()
    return int(row["id"])


def replace_wiki_sections(conn: sqlite3.Connection, paper_id: int, sections: dict[str, str]) -> None:
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
    conn.commit()


def attach_concepts(conn: sqlite3.Connection, paper_id: int, concepts: list[dict[str, Any]]) -> None:
    for concept in concepts:
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
    for left, right in zip(concepts, concepts[1:]):
        left_id = conn.execute("SELECT id FROM concepts WHERE name = ?", (left["name"],)).fetchone()["id"]
        right_id = conn.execute("SELECT id FROM concepts WHERE name = ?", (right["name"],)).fetchone()["id"]
        conn.execute(
            """
            INSERT OR IGNORE INTO concept_edges (source_concept_id, target_concept_id, relation, weight)
            VALUES (?, ?, ?, ?)
            """,
            (left_id, right_id, "共同出现在论文中", 0.75),
        )
    conn.commit()


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
    paper["wiki"] = [dict(item) for item in sections]
    paper["concepts"] = [dict(item) for item in concepts]
    paper["notes"] = [dict(item) for item in notes]
    return paper


def set_favorite(conn: sqlite3.Connection, paper_id: int, favorite: bool) -> dict[str, Any]:
    conn.execute("UPDATE papers SET is_favorite = ? WHERE id = ?", (1 if favorite else 0, paper_id))
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

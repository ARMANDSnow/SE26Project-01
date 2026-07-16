from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..db.schema import rebuild_paper_chunks_fts
from ..models import AssetId, PaperCandidate, PaperId, PaperRecord, PaperSource
from ..services.text_utils import deterministic_embedding


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
        processing_status=str(row["processing_status"]),
        created_at=str(row["created_at"]),
    )


def row_to_paper(
    row: sqlite3.Row,
    is_favorite: bool | None = None,
    upload: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        "upload": upload,
        "created_at": paper.created_at,
    }


def find_existing_paper_id(conn: sqlite3.Connection, paper: PaperCandidate) -> PaperId | None:
    row = conn.execute(
        "SELECT id FROM papers WHERE source = ? AND source_id = ?",
        (paper.source.value, paper.source_id),
    ).fetchone()
    return PaperId(int(row["id"])) if row is not None else None


def upsert_paper(conn: sqlite3.Connection, paper: PaperCandidate, commit: bool = True) -> PaperId:
    # A single UPSERT closes the SELECT-then-INSERT race between concurrent
    # Research Runs importing the same source identity.
    row = conn.execute(
        """
        INSERT INTO papers (
            source, source_id, source_url, venue, pdf_url, asset_id,
            title, authors_json, abstract, categories_json, primary_category,
            published_at, updated_at, processing_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_id) DO UPDATE SET
            title = excluded.title,
            authors_json = excluded.authors_json,
            abstract = excluded.abstract,
            categories_json = excluded.categories_json,
            primary_category = excluded.primary_category,
            published_at = excluded.published_at,
            updated_at = excluded.updated_at,
            pdf_url = COALESCE(excluded.pdf_url, papers.pdf_url),
            source_url = COALESCE(excluded.source_url, papers.source_url),
            venue = COALESCE(excluded.venue, papers.venue)
        RETURNING id, asset_id
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
            paper.processing_status,
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("paper upsert did not return an id")
    paper_id = PaperId(int(row["id"]))
    if paper.asset_id and row["asset_id"] != str(paper.asset_id):
        set_paper_asset_id(conn, paper_id, paper.asset_id, commit=False)
    if commit:
        conn.commit()
    return paper_id


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
    if row["asset_id"] == next_asset_id:
        if commit:
            conn.commit()
        return

    savepoint = "set_paper_asset_id"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        conn.execute("DELETE FROM paper_documents WHERE paper_id = ?", (int(paper_id),))
        conn.execute("UPDATE summary_versions SET is_active = 0 WHERE paper_id = ?", (int(paper_id),))
        conn.execute("DELETE FROM wiki_sections WHERE paper_id = ?", (int(paper_id),))
        conn.execute("DELETE FROM paper_concepts WHERE paper_id = ?", (int(paper_id),))
        rebuild_concept_edges(conn)
        cursor = conn.execute(
            "UPDATE papers SET asset_id = ?, processing_status = 'pending' WHERE id = ?",
            (next_asset_id, int(paper_id)),
        )
        if cursor.rowcount == 0:
            raise ValueError("paper not found")
    except Exception:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise
    conn.execute(f"RELEASE {savepoint}")
    if commit:
        conn.commit()


def paper_exists(conn: sqlite3.Connection, paper_id: int) -> bool:
    return conn.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone() is not None


def existing_paper_ids(conn: sqlite3.Connection, paper_ids: list[int]) -> set[int]:
    if not paper_ids:
        return set()
    placeholders = ",".join("?" for _ in paper_ids)
    rows = conn.execute(
        f"SELECT id FROM papers WHERE id IN ({placeholders})",
        tuple(paper_ids),
    ).fetchall()
    return {int(row["id"]) for row in rows}


def get_paper_title(conn: sqlite3.Connection, paper_id: int) -> str | None:
    row = conn.execute("SELECT title FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return str(row["title"]) if row is not None else None


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
    from .library import ensure_user_library
    from .uploads import accessible_paper_condition, upload_metadata_for_user

    ensure_user_library(conn, user_id)
    saved_ids = {
        int(row["paper_id"])
        for row in conn.execute("SELECT paper_id FROM library_items WHERE user_id = ?", (user_id,)).fetchall()
    }
    access_condition, access_params = accessible_paper_condition("p", user_id)
    rows = conn.execute(
        f"SELECT p.* FROM papers p WHERE {access_condition} ORDER BY p.published_at DESC",
        access_params,
    ).fetchall()
    query = q.strip().lower()
    author_query = author.strip().lower()
    concept_query = concept.strip().lower()
    results: list[dict[str, Any]] = []
    for row in rows:
        paper_id = int(row["id"])
        paper = row_to_paper(
            row,
            paper_id in saved_ids,
            upload_metadata_for_user(conn, paper_id, user_id),
        )
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
    from .uploads import paper_is_accessible, upload_metadata_for_user

    if not paper_is_accessible(conn, paper_id, user_id):
        return None
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if row is None:
        return None
    saved = conn.execute(
        "SELECT 1 FROM library_items WHERE user_id = ? AND paper_id = ?",
        (user_id, paper_id),
    ).fetchone() is not None
    paper = row_to_paper(row, saved, upload_metadata_for_user(conn, paper_id, user_id))
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
        """
        SELECT id, note, comment, created_at, updated_at
        FROM notes WHERE paper_id = ? AND user_id = ? ORDER BY created_at DESC
        """,
        (paper_id, user_id),
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

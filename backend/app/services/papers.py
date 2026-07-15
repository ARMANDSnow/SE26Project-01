from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import AssetId, PaperCandidate
from ..repositories.learning import add_reading_history
from ..repositories.papers import (
    get_paper_detail,
    get_paper_title,
    list_paper_chunks,
    list_papers,
    paper_exists,
    upsert_paper,
)
from .remote_pdf import PaperPdfService


@dataclass(frozen=True)
class PaperPdf:
    asset_id: AssetId
    path: Path
    title: str


def register_uploaded_paper(
    conn: sqlite3.Connection,
    paper: PaperCandidate,
) -> dict[str, Any]:
    paper_id = upsert_paper(conn, paper, commit=False)
    detail = get_paper_detail(conn, paper_id)
    if detail is None:
        conn.rollback()
        raise RuntimeError("paper could not be loaded after insert")
    conn.commit()
    return detail


def list_catalog(
    conn: sqlite3.Connection,
    *,
    q: str,
    category: str,
    concept: str,
    author: str,
    favorite: bool | None,
    limit: int,
    offset: int,
    user_id: int,
) -> list[dict[str, Any]]:
    return list_papers(
        conn,
        q=q,
        category=category,
        concept=concept,
        author=author,
        favorite=favorite,
        limit=limit,
        offset=offset,
        user_id=user_id,
    )


def read_detail(
    conn: sqlite3.Connection,
    paper_id: int,
    user_id: int,
) -> dict[str, Any] | None:
    detail = get_paper_detail(conn, paper_id, user_id=user_id)
    if detail is None:
        return None
    add_reading_history(conn, paper_id, "阅读论文详情", user_id=user_id, commit=False)
    conn.commit()
    return detail


def read_chunks(
    conn: sqlite3.Connection,
    paper_id: int,
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int] | None:
    if not paper_exists(conn, paper_id):
        return None
    return list_paper_chunks(conn, paper_id, limit=limit, offset=offset)


def resolve_pdf(conn: sqlite3.Connection, paper_id: int) -> PaperPdf | None:
    title = get_paper_title(conn, paper_id)
    if title is None:
        return None
    pdf_service = PaperPdfService(conn)
    asset = pdf_service.ensure(paper_id)
    return PaperPdf(
        asset_id=asset.id,
        path=pdf_service.store.path_for(asset.id),
        title=title,
    )

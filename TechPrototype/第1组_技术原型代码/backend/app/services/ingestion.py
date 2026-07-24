from __future__ import annotations

import sqlite3
from typing import Any

from ..db.connection import connect
from ..models import PaperCandidate
from ..repositories.paper_processing import enqueue_paper_processing
from ..repositories.papers import find_existing_paper_id, upsert_paper


class IngestionPersistenceError(RuntimeError):
    pass


def save_ingested_papers(
    papers: list[PaperCandidate],
    *,
    requested_by_user_id: int,
) -> dict[str, Any]:
    paper_ids: list[int] = []
    duplicate_count = 0
    queued_count = 0
    active_count = 0
    ready_count = 0
    try:
        with connect() as conn:
            for paper in papers:
                if find_existing_paper_id(conn, paper) is not None:
                    duplicate_count += 1
                paper_id = upsert_paper(conn, paper, commit=False)
                if paper_id not in paper_ids:
                    paper_ids.append(paper_id)
                disposition = enqueue_paper_processing(
                    conn,
                    paper_id=int(paper_id),
                    requested_by_user_id=requested_by_user_id,
                )
                queued_count += int(disposition == "queued")
                active_count += int(disposition == "active")
                ready_count += int(disposition == "ready")
            conn.commit()
    except sqlite3.Error as exc:
        raise IngestionPersistenceError(f"论文入库失败：{exc}") from exc
    return {
        "count": max(0, len(papers) - duplicate_count),
        "fetched_count": len(papers),
        "duplicate_count": duplicate_count,
        "paper_ids": paper_ids,
        "queued_count": queued_count,
        "active_count": active_count,
        "ready_count": ready_count,
    }

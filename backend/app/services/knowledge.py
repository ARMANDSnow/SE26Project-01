from __future__ import annotations

import sqlite3
from typing import Any

from ..repositories.papers import existing_paper_ids
from .qa_agent import run_qa_agent


class PapersNotFoundError(ValueError):
    def __init__(self, paper_ids: list[int]) -> None:
        super().__init__(f"papers not found: {paper_ids}")
        self.paper_ids = paper_ids


def answer_question(
    conn: sqlite3.Connection,
    question: str,
    paper_ids: list[int],
    *,
    mode: str,
) -> dict[str, Any]:
    if paper_ids:
        found = existing_paper_ids(conn, paper_ids)
        missing = [paper_id for paper_id in paper_ids if paper_id not in found]
        if missing:
            raise PapersNotFoundError(missing)
    return run_qa_agent(conn, question, paper_ids or None, mode=mode)

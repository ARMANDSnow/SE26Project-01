from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import get_settings
from backend.app.database import init_schema, upsert_paper
from backend.app.services.agents import process_paper
from backend.app.services.llm import LLMProviderError
from backend.app.services.qa_agent import run_qa_agent
from backend.app.services.sources import fetch_arxiv_papers


def main() -> int:
    if os.getenv("RUN_REAL_LLM_TESTS", "").lower() not in {"1", "true", "yes"}:
        print("SKIP: set RUN_REAL_LLM_TESTS=1 to run the paid real-model smoke.")
        return 0
    get_settings.cache_clear()
    settings = get_settings()
    if not settings.llm_available:
        print("FAIL: real-model smoke requires a non-empty LLM_API_KEY.")
        return 2

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    stage = "arxiv_fetch"
    try:
        papers = fetch_arxiv_papers(["cs.AI"], ["agent"], 2)
        if len(papers) < 2:
            print("FAIL: arXiv returned fewer than two papers.")
            return 3
        paper_ids = [upsert_paper(conn, paper) for paper in papers[:2]]
        process_results = []
        for index, paper_id in enumerate(paper_ids, start=1):
            stage = f"paper_process_{index}"
            process_results.append(process_paper(conn, paper_id))
        if any(item.get("status") != "processed" for item in process_results):
            print("FAIL: at least one real-model paper processing request failed.")
            return 4
        chunk_count = conn.execute(
            "SELECT COUNT(*) AS count FROM paper_chunks WHERE paper_id IN (?, ?)",
            tuple(paper_ids),
        ).fetchone()["count"]
        if int(chunk_count) == 0:
            print("FAIL: Docling did not produce any current-document chunks.")
            return 5
        titles = [paper["title"] for paper in papers[:2]]
        question = (
            "请分别检索并打开这两篇论文的证据，比较它们的研究问题和方法，必须引用两篇论文："
            f"《{titles[0]}》与《{titles[1]}》。"
        )
        stage = "agentic_qa"
        result = run_qa_agent(conn, question, paper_ids)
        cited_papers = {int(item["paper_id"]) for item in result["citations"]}
        execution = result["execution"]
        checks = [
            execution["mode"] == "agentic_real",
            execution["status"] == "completed",
            int(execution["tool_call_count"]) >= 3,
            set(paper_ids).issubset(cited_papers),
            bool(result["answer"].strip()),
            all(f"[{item['evidence_id']}]" in result["answer"] for item in result["citations"]),
        ]
        if not all(checks):
            print(
                "FAIL: agentic assertions failed "
                f"(mode={execution['mode']}, status={execution['status']}, "
                f"tool_calls={execution['tool_call_count']}, cited_papers={len(cited_papers)})."
            )
            return 6
        print(
            "PASS: real agent smoke completed "
            f"(tool_calls={execution['tool_call_count']}, cited_papers={len(cited_papers)}, "
            f"chunks={chunk_count})."
        )
        return 0
    except LLMProviderError as exc:
        print(f"FAIL: real agent smoke stopped at {stage} with {exc}.")
        return 7
    except Exception as exc:
        print(f"FAIL: real agent smoke stopped at {stage} with sanitized error type {type(exc).__name__}.")
        return 7
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

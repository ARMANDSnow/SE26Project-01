#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db.connection import connect
from backend.app.db.schema import SCHEMA_VERSION, init_db
from backend.app.models import PaperCandidate, PaperSource
from backend.app.repositories.papers import upsert_paper


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an isolated v9 database with deterministic public-paper-like fixtures."
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--papers", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database = args.database.expanduser().resolve()
    allowed_roots = (Path("/tmp").resolve(), Path("/private/tmp").resolve())
    if not any(database.is_relative_to(root) for root in allowed_roots):
        print("fixture database must be under /tmp or /private/tmp", file=sys.stderr)
        return 2
    if args.papers < 120:
        print("performance fixture requires at least 120 papers", file=sys.stderr)
        return 2

    init_db(database)
    with connect(database) as conn:
        for index in range(1, args.papers + 1):
            category = "cs.CL" if index % 2 else "cs.IR"
            upsert_paper(
                conn,
                PaperCandidate(
                    source=PaperSource.ARXIV,
                    source_id=f"2601.{index:05d}",
                    source_url=f"https://arxiv.org/abs/2601.{index:05d}",
                    pdf_url=f"https://arxiv.org/pdf/2601.{index:05d}",
                    title=f"Iter16 RAG Evaluation Fixture Paper {index:03d}",
                    authors=("Fixture Researcher", "Quality Reviewer"),
                    abstract=(
                        "Deterministic testing fixture about retrieval augmented generation, "
                        "citation evidence, graph relations, and reproducible evaluation."
                    ),
                    categories=(category, "cs.AI"),
                    primary_category=category,
                    published_at="2026-01-01",
                    updated_at="2026-01-02",
                    processing_status="processed",
                ),
                commit=False,
            )
        conn.commit()
        paper_count = int(conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0])
        schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if paper_count < args.papers or schema_version != SCHEMA_VERSION:
        print("fixture verification failed", file=sys.stderr)
        return 1
    print(
        f"prepared isolated schema v{schema_version} performance fixture with "
        f"{paper_count} papers at {database}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

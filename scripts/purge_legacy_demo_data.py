from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def legacy_demo_ids() -> list[str]:
    return [f"25{index // 10 + 1:02d}.{index + 1000:05d}" for index in range(100)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove the legacy runtime demo papers without touching imported papers.")
    parser.add_argument("--database", default="backend/data/arxiv_wiki.sqlite3")
    parser.add_argument("--apply", action="store_true", help="Apply the cleanup. Without this flag, only report matches.")
    args = parser.parse_args()
    path = Path(args.database)
    if not path.exists():
        print("Database does not exist; nothing to clean.")
        return 0

    ids = legacy_demo_ids()
    placeholders = ",".join("?" for _ in ids)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        matched = conn.execute(f"SELECT COUNT(*) FROM papers WHERE arxiv_id IN ({placeholders})", ids).fetchone()[0]
        print(f"Matched legacy demo papers: {matched}")
        if not args.apply or matched == 0:
            return 0
        conn.execute(f"DELETE FROM papers WHERE arxiv_id IN ({placeholders})", ids)
        conn.execute(
            """
            DELETE FROM concept_edges
            WHERE source_concept_id NOT IN (SELECT DISTINCT concept_id FROM paper_concepts)
               OR target_concept_id NOT IN (SELECT DISTINCT concept_id FROM paper_concepts)
            """
        )
        conn.execute("DELETE FROM concepts WHERE id NOT IN (SELECT DISTINCT concept_id FROM paper_concepts)")
        conn.commit()
        remaining = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    print(f"Cleanup complete. Remaining papers: {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

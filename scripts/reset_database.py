from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.database import SCHEMA_VERSION, init_db


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Destructively rebuild the application database with the current schema."
    )
    parser.add_argument("--database", default="backend/data/arxiv_wiki.sqlite3")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete the database and create an empty current-schema database.",
    )
    args = parser.parse_args()

    raw_path = Path(args.database).expanduser()
    if raw_path.is_symlink():
        raise SystemExit("Refusing to reset a database through a symbolic link.")
    path = raw_path.resolve(strict=False)
    if not args.apply:
        print(f"Would rebuild database: {path}")
        print("No files changed. Re-run with --apply to confirm destructive reset.")
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            candidate.unlink()
    init_db(path)
    print(f"Created empty schema version {SCHEMA_VERSION}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

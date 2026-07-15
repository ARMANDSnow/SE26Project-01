from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass


MigrationBody = Callable[[sqlite3.Connection], None]


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: MigrationBody


def apply_migrations(
    conn: sqlite3.Connection,
    migrations: Sequence[Migration],
    *,
    target_version: int,
) -> list[int]:
    """Apply a contiguous migration sequence in one transaction."""

    current_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current_version > target_version:
        raise MigrationError(
            f"database version {current_version} is newer than target {target_version}"
        )

    pending = sorted(
        (migration for migration in migrations if current_version < migration.version <= target_version),
        key=lambda migration: migration.version,
    )
    expected = list(range(current_version + 1, target_version + 1))
    actual = [migration.version for migration in pending]
    if actual != expected:
        raise MigrationError(f"migration chain is incomplete: expected {expected}, got {actual}")

    applied: list[int] = []
    savepoint = "schema_migrations"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        for migration in pending:
            migration.apply(conn)
            conn.execute(f"PRAGMA user_version = {migration.version}")
            applied.append(migration.version)
    except Exception:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise
    conn.execute(f"RELEASE {savepoint}")
    conn.commit()
    return applied

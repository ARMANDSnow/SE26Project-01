from __future__ import annotations

import sqlite3
from typing import Any, cast


def accessible_paper_condition(alias: str, user_id: int) -> tuple[str, tuple[int]]:
    condition = f"""
        (
            (
                {alias}.source != 'upload'
                AND NOT EXISTS (
                    SELECT 1 FROM paper_uploads access_upload
                    WHERE access_upload.paper_id = {alias}.id
                )
            )
            OR EXISTS (
                SELECT 1 FROM paper_uploads access_upload
                WHERE access_upload.paper_id = {alias}.id
                  AND (
                      access_upload.owner_user_id = ?
                      OR (
                          access_upload.visibility = 'public'
                          AND access_upload.moderation_status != 'rejected'
                      )
                  )
            )
        )
    """
    return condition, (user_id,)


def paper_is_accessible(conn: sqlite3.Connection, paper_id: int, user_id: int) -> bool:
    condition, params = accessible_paper_condition("p", user_id)
    row = conn.execute(
        f"SELECT 1 FROM papers p WHERE p.id = ? AND {condition}",
        (paper_id, *params),
    ).fetchone()
    return row is not None


def existing_accessible_paper_ids(
    conn: sqlite3.Connection,
    paper_ids: list[int],
    user_id: int,
) -> set[int]:
    if not paper_ids:
        return set()
    condition, access_params = accessible_paper_condition("p", user_id)
    placeholders = ",".join("?" for _ in paper_ids)
    rows = conn.execute(
        f"SELECT p.id FROM papers p WHERE p.id IN ({placeholders}) AND {condition}",
        (*paper_ids, *access_params),
    ).fetchall()
    return {int(row["id"]) for row in rows}


def create_upload_record(
    conn: sqlite3.Connection,
    *,
    paper_id: int,
    owner_user_id: int,
    visibility: str,
    original_filename: str | None,
) -> None:
    if visibility not in {"private", "public"}:
        raise ValueError("invalid upload visibility")
    conn.execute(
        """
        INSERT INTO paper_uploads(
            paper_id, owner_user_id, visibility, provenance,
            moderation_status, original_filename
        ) VALUES (?, ?, ?, 'user_upload', 'unreviewed', ?)
        """,
        (paper_id, owner_user_id, visibility, original_filename),
    )


def get_upload_row(conn: sqlite3.Connection, paper_id: int) -> sqlite3.Row | None:
    return cast(
        sqlite3.Row | None,
        conn.execute(
            """
            SELECT paper_id, owner_user_id, visibility, provenance, moderation_status,
                   original_filename, created_at, updated_at
            FROM paper_uploads WHERE paper_id = ?
            """,
            (paper_id,),
        ).fetchone(),
    )


def upload_metadata_for_user(
    conn: sqlite3.Connection,
    paper_id: int,
    user_id: int,
) -> dict[str, Any] | None:
    row = get_upload_row(conn, paper_id)
    if row is None:
        return None
    is_owner = row["owner_user_id"] is not None and int(row["owner_user_id"]) == user_id
    return {
        "visibility": str(row["visibility"]),
        "provenance": str(row["provenance"]),
        "moderation_status": str(row["moderation_status"]),
        "owned_by_current_user": is_owner,
        "original_filename": str(row["original_filename"])
        if is_owner and row["original_filename"] is not None
        else None,
    }


def update_upload_visibility(
    conn: sqlite3.Connection,
    paper_id: int,
    owner_user_id: int,
    visibility: str,
    *,
    commit: bool = True,
) -> None:
    if visibility not in {"private", "public"}:
        raise ValueError("invalid upload visibility")
    cursor = conn.execute(
        """
        UPDATE paper_uploads
        SET visibility = ?, moderation_status = 'unreviewed',
            updated_at = CURRENT_TIMESTAMP
        WHERE paper_id = ? AND owner_user_id = ?
        """,
        (visibility, paper_id, owner_user_id),
    )
    if cursor.rowcount == 0:
        conn.rollback()
        raise ValueError("owned upload not found")
    if commit:
        conn.commit()

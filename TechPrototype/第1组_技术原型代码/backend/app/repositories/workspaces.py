from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _workspace(conn: sqlite3.Connection, workspace_id: str, user_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM workspaces WHERE id = ? AND owner_user_id = ?",
        (workspace_id, user_id),
    ).fetchone()
    if row is None:
        raise ValueError("workspace not found")
    return row


def list_workspaces(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT w.*, p.title AS project_title, f.name AS folder_name
        FROM workspaces w
        LEFT JOIN research_projects p ON p.id = w.project_id
        LEFT JOIN library_folders f ON f.id = w.folder_id
        WHERE w.owner_user_id = ?
        ORDER BY w.updated_at DESC, w.created_at DESC
        """,
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_workspace(conn: sqlite3.Connection, workspace_id: str, user_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT w.*, p.title AS project_title, f.name AS folder_name
        FROM workspaces w
        LEFT JOIN research_projects p ON p.id = w.project_id
        LEFT JOIN library_folders f ON f.id = w.folder_id
        WHERE w.id = ? AND w.owner_user_id = ?
        """,
        (workspace_id, user_id),
    ).fetchone()
    if row is None:
        raise ValueError("workspace not found")
    return dict(row)


def create_workspace(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    title: str,
    description: str,
    project_id: str | None = None,
    folder_id: int | None = None,
) -> dict[str, Any]:
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("workspace title is required")
    if (project_id is None) == (folder_id is None):
        raise ValueError("workspace must bind exactly one project or folder")
    if project_id is not None:
        if conn.execute(
            "SELECT 1 FROM research_projects WHERE id = ? AND owner_user_id = ?",
            (project_id, user_id),
        ).fetchone() is None:
            raise ValueError("project not found")
    if folder_id is not None:
        if conn.execute(
            "SELECT 1 FROM library_folders WHERE id = ? AND user_id = ?",
            (folder_id, user_id),
        ).fetchone() is None:
            raise ValueError("folder not found")
    workspace_id = f"workspace_{uuid4().hex}"
    try:
        conn.execute(
            """
            INSERT INTO workspaces(id, owner_user_id, title, description, project_id, folder_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (workspace_id, user_id, clean_title, description.strip(), project_id, folder_id),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError("workspace title already exists") from exc
    return get_workspace(conn, workspace_id, user_id)


def update_workspace(
    conn: sqlite3.Connection,
    workspace_id: str,
    user_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    current = _workspace(conn, workspace_id, user_id)
    next_title = current["title"] if title is None else title.strip()
    next_description = current["description"] if description is None else description.strip()
    if not next_title:
        raise ValueError("workspace title is required")
    try:
        conn.execute(
            "UPDATE workspaces SET title = ?, description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (next_title, next_description, workspace_id),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError("workspace title already exists") from exc
    return get_workspace(conn, workspace_id, user_id)


def delete_workspace(conn: sqlite3.Connection, workspace_id: str, user_id: int) -> None:
    _workspace(conn, workspace_id, user_id)
    conn.execute("DELETE FROM workspaces WHERE id = ? AND owner_user_id = ?", (workspace_id, user_id))
    conn.commit()


def workspace_context(conn: sqlite3.Connection, workspace_id: str, user_id: int) -> dict[str, Any]:
    workspace = get_workspace(conn, workspace_id, user_id)
    if workspace["project_id"] is not None:
        items = conn.execute(
            """
            SELECT i.item_type, i.run_id, i.paper_id, i.artifact_id, i.artifact_version, i.position,
                   p.title, p.abstract
            FROM research_project_items i
            LEFT JOIN papers p ON p.id = i.paper_id
            WHERE i.project_id = ?
            ORDER BY i.position, i.added_at
            """,
            (workspace["project_id"],),
        ).fetchall()
    else:
        items = conn.execute(
            """
            SELECT 'paper' AS item_type, NULL AS run_id, i.paper_id,
                   NULL AS artifact_id, NULL AS artifact_version, i.id AS position,
                   p.title, p.abstract
            FROM library_items i JOIN papers p ON p.id = i.paper_id
            WHERE i.user_id = ? AND i.folder_id = ?
            ORDER BY i.updated_at DESC
            """,
            (user_id, workspace["folder_id"]),
        ).fetchall()
    workspace["items"] = [dict(item) for item in items]
    return workspace

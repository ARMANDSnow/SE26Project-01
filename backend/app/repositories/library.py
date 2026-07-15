from __future__ import annotations

import sqlite3
from typing import Any, cast

from .papers import get_paper_detail, row_to_paper
from .uploads import (
    accessible_paper_condition,
    paper_is_accessible,
    upload_metadata_for_user,
)


def set_favorite(
    conn: sqlite3.Connection,
    paper_id: int,
    favorite: bool,
    user_id: int = 1,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    if not paper_is_accessible(conn, paper_id, user_id):
        conn.rollback()
        raise ValueError("paper not found")
    folders = ensure_user_library(conn, user_id)
    if favorite:
        conn.execute(
            "INSERT OR IGNORE INTO library_items (user_id, paper_id, folder_id) VALUES (?, ?, ?)",
            (user_id, paper_id, folders["inbox_id"]),
        )
    else:
        conn.execute("DELETE FROM library_items WHERE user_id = ? AND paper_id = ?", (user_id, paper_id))
    conn.execute(
        "INSERT INTO reading_history (user_id, paper_id, action) VALUES (?, ?, ?)",
        (user_id, paper_id, "收藏" if favorite else "取消收藏"),
    )
    if commit:
        conn.commit()
    detail = get_paper_detail(conn, paper_id, user_id=user_id)
    if detail is None:
        raise ValueError("paper not found")
    return detail


def ensure_user_library(conn: sqlite3.Connection, user_id: int) -> dict[str, int]:
    root = conn.execute(
        "SELECT id FROM library_folders WHERE user_id = ? AND parent_id IS NULL AND is_system = 1",
        (user_id,),
    ).fetchone()
    if root is None:
        cursor = conn.execute(
            "INSERT INTO library_folders (user_id, parent_id, name, description, is_system) VALUES (?, NULL, ?, ?, 1)",
            (user_id, "我的资料库", "个人论文资料库根目录"),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("failed to create root library folder")
        root_id = int(cursor.lastrowid)
    else:
        root_id = int(root["id"])
    inbox = conn.execute(
        "SELECT id FROM library_folders WHERE user_id = ? AND parent_id = ? AND is_system = 1",
        (user_id, root_id),
    ).fetchone()
    if inbox is None:
        cursor = conn.execute(
            "INSERT INTO library_folders (user_id, parent_id, name, description, is_system) VALUES (?, ?, ?, ?, 1)",
            (user_id, root_id, "待整理", "新收藏的论文默认放在这里"),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("failed to create inbox library folder")
        inbox_id = int(cursor.lastrowid)
    else:
        inbox_id = int(inbox["id"])
    return {"root_id": root_id, "inbox_id": inbox_id}


def list_library_folders(conn: sqlite3.Connection, user_id: int = 1) -> list[dict[str, Any]]:
    defaults = ensure_user_library(conn, user_id)
    access_condition, access_params = accessible_paper_condition("p", user_id)
    rows = conn.execute(
        f"""
        SELECT f.*, COUNT(i.id) AS item_count
        FROM library_folders f
        LEFT JOIN library_items i
          ON i.folder_id = f.id AND i.user_id = f.user_id
         AND EXISTS (
             SELECT 1 FROM papers p
             WHERE p.id = i.paper_id AND {access_condition}
         )
        WHERE f.user_id = ?
        GROUP BY f.id
        ORDER BY f.is_system DESC, lower(f.name), f.id
        """,
        (*access_params, user_id),
    ).fetchall()
    by_id = {int(row["id"]): row for row in rows}

    def path_for(folder_id: int) -> str:
        names: list[str] = []
        current = by_id.get(folder_id)
        seen: set[int] = set()
        while current is not None and int(current["id"]) not in seen:
            seen.add(int(current["id"]))
            names.append(str(current["name"]))
            current = by_id.get(int(current["parent_id"])) if current["parent_id"] is not None else None
        return " / ".join(reversed(names))

    payload = [
        {
            "id": int(row["id"]),
            "parent_id": int(row["parent_id"]) if row["parent_id"] is not None else None,
            "name": row["name"],
            "description": row["description"],
            "is_system": bool(row["is_system"]),
            "item_count": int(row["item_count"]),
            "path": path_for(int(row["id"])),
            "is_root": int(row["id"]) == defaults["root_id"],
        }
        for row in rows
    ]
    children: dict[int | None, list[dict[str, Any]]] = {}
    for folder in payload:
        children.setdefault(folder["parent_id"], []).append(folder)
    for entries in children.values():
        entries.sort(key=lambda folder: (not folder["is_system"], folder["name"].casefold(), folder["id"]))
    ordered: list[dict[str, Any]] = []

    def visit(parent_id: int | None) -> None:
        for folder in children.get(parent_id, []):
            ordered.append(folder)
            visit(folder["id"])

    visit(None)
    return ordered


def create_library_folder(
    conn: sqlite3.Connection,
    name: str,
    parent_id: int | None = None,
    description: str = "",
    user_id: int = 1,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("folder name is required")
    defaults = ensure_user_library(conn, user_id)
    target_parent = parent_id or defaults["root_id"]
    parent = conn.execute(
        "SELECT id FROM library_folders WHERE id = ? AND user_id = ?",
        (target_parent, user_id),
    ).fetchone()
    if parent is None:
        raise ValueError("folder not found")
    try:
        cursor = conn.execute(
            "INSERT INTO library_folders (user_id, parent_id, name, description) VALUES (?, ?, ?, ?)",
            (user_id, target_parent, clean_name, description.strip()),
        )
        if commit:
            conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError("folder already exists") from exc
    return next(folder for folder in list_library_folders(conn, user_id) if folder["id"] == cursor.lastrowid)


def delete_library_folder(
    conn: sqlite3.Connection,
    folder_id: int,
    user_id: int = 1,
    *,
    commit: bool = True,
) -> None:
    folder = conn.execute(
        "SELECT is_system FROM library_folders WHERE id = ? AND user_id = ?",
        (folder_id, user_id),
    ).fetchone()
    if folder is None:
        raise ValueError("folder not found")
    if folder["is_system"]:
        raise ValueError("system folder cannot be deleted")
    has_content = conn.execute(
        "SELECT 1 FROM library_items WHERE folder_id = ? UNION SELECT 1 FROM library_folders WHERE parent_id = ? LIMIT 1",
        (folder_id, folder_id),
    ).fetchone()
    if has_content is not None:
        raise ValueError("folder is not empty")
    conn.execute("DELETE FROM library_folders WHERE id = ? AND user_id = ?", (folder_id, user_id))
    if commit:
        conn.commit()


def list_library_items(conn: sqlite3.Connection, folder_id: int | None = None, user_id: int = 1) -> list[dict[str, Any]]:
    ensure_user_library(conn, user_id)
    access_condition, access_params = accessible_paper_condition("p", user_id)
    params: list[Any] = [user_id, *access_params]
    where = f"i.user_id = ? AND {access_condition}"
    if folder_id is not None:
        where += " AND i.folder_id = ?"
        params.append(folder_id)
    rows = conn.execute(
        f"""
        SELECT i.id AS library_item_id, i.folder_id, i.created_at AS saved_at, p.*
        FROM library_items i JOIN papers p ON p.id = i.paper_id
        WHERE {where}
        ORDER BY i.updated_at DESC, i.id DESC
        """,
        params,
    ).fetchall()
    items = []
    for row in rows:
        paper_id = int(row["id"])
        paper = row_to_paper(
            row,
            True,
            upload_metadata_for_user(conn, paper_id, user_id),
        )
        paper.update({"library_item_id": int(row["library_item_id"]), "folder_id": int(row["folder_id"]), "saved_at": row["saved_at"]})
        items.append(paper)
    return items


def move_library_item(
    conn: sqlite3.Connection,
    item_id: int,
    folder_id: int,
    user_id: int = 1,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    item = conn.execute(
        "SELECT paper_id FROM library_items WHERE id = ? AND user_id = ?",
        (item_id, user_id),
    ).fetchone()
    if item is None or not paper_is_accessible(conn, int(item["paper_id"]), user_id):
        raise ValueError("library item not found")
    folder = conn.execute(
        "SELECT id FROM library_folders WHERE id = ? AND user_id = ?",
        (folder_id, user_id),
    ).fetchone()
    if folder is None:
        raise ValueError("folder not found")
    cursor = conn.execute(
        "UPDATE library_items SET folder_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
        (folder_id, item_id, user_id),
    )
    if cursor.rowcount == 0:
        conn.rollback()
        raise ValueError("library item not found")
    if commit:
        conn.commit()
    return next(item for item in list_library_items(conn, user_id=user_id) if item["library_item_id"] == item_id)


def get_library_item_for_recommendation(
    conn: sqlite3.Connection,
    item_id: int,
    user_id: int,
) -> sqlite3.Row | None:
    access_condition, access_params = accessible_paper_condition("p", user_id)
    return cast(
        sqlite3.Row | None,
        conn.execute(
            f"""
            SELECT i.id, i.folder_id, p.title, p.abstract, p.categories_json,
                   p.primary_category
            FROM library_items i JOIN papers p ON p.id = i.paper_id
            WHERE i.id = ? AND i.user_id = ? AND {access_condition}
            """,
            (item_id, user_id, *access_params),
        ).fetchone(),
    )

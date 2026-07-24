from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..repositories import learning as learning_repository
from ..repositories import library as library_repository
from ..repositories.papers import get_paper_detail
from .llm import LLMClient, LLMServiceError


def recommend_folder(conn: sqlite3.Connection, item_id: int, user_id: int = 1) -> dict[str, Any]:
    item = library_repository.get_library_item_for_recommendation(conn, item_id, user_id)
    if item is None:
        raise ValueError("library item not found")
    folders = [
        folder
        for folder in library_repository.list_library_folders(conn, user_id)
        if not folder["is_root"] and not folder["is_system"]
    ]
    if not folders:
        raise ValueError("no candidate folders")
    candidates = [
        {"folder_id": folder["id"], "path": folder["path"], "description": folder["description"]}
        for folder in folders
    ]
    prompt = (
        "请从候选目录中为这篇论文推荐最合适的一个目录。只能返回候选目录中的 folder_id。"
        "只返回 JSON，不要使用 Markdown。格式："
        '{"folder_id": 123, "reason": "一句简短理由"}'
        f"\n\n论文标题：{item['title']}"
        f"\n分类：{item['primary_category']} / {', '.join(json.loads(item['categories_json']))}"
        f"\n摘要：{item['abstract']}"
        f"\n\n候选目录：{json.dumps(candidates, ensure_ascii=False)}"
    )
    raw = LLMClient().complete(
        "你是论文资料库整理助手。你只负责推荐已有目录，不执行移动，也不创建目录。",
        prompt,
        json_mode=True,
    )
    payload = _parse_json(raw)
    try:
        folder_id = int(payload["folder_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise LLMServiceError("LLM 未返回有效的 folder_id") from exc
    selected = next((folder for folder in folders if folder["id"] == folder_id), None)
    if selected is None:
        raise LLMServiceError("LLM 推荐了候选范围之外的目录")
    reason = str(payload.get("reason", "与该目录的主题最匹配")).strip()
    return {"folder_id": folder_id, "folder_name": selected["name"], "folder_path": selected["path"], "reason": reason}


def favorite_paper(
    conn: sqlite3.Connection,
    paper_id: int,
    favorite: bool,
    user_id: int,
) -> dict[str, Any]:
    result = library_repository.set_favorite(
        conn, paper_id, favorite, user_id=user_id, commit=False
    )
    conn.commit()
    return result


def list_folders(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    return library_repository.list_library_folders(conn, user_id=user_id)


def create_folder(
    conn: sqlite3.Connection,
    name: str,
    parent_id: int | None,
    description: str,
    user_id: int,
) -> dict[str, Any]:
    result = library_repository.create_library_folder(
        conn,
        name,
        parent_id,
        description,
        user_id=user_id,
        commit=False,
    )
    conn.commit()
    return result


def delete_folder(conn: sqlite3.Connection, folder_id: int, user_id: int) -> None:
    library_repository.delete_library_folder(
        conn, folder_id, user_id=user_id, commit=False
    )
    conn.commit()


def list_items(
    conn: sqlite3.Connection,
    folder_id: int | None,
    user_id: int,
) -> list[dict[str, Any]]:
    return library_repository.list_library_items(conn, folder_id=folder_id, user_id=user_id)


def move_item(
    conn: sqlite3.Connection,
    item_id: int,
    folder_id: int,
    user_id: int,
) -> dict[str, Any]:
    result = library_repository.move_library_item(
        conn, item_id, folder_id, user_id=user_id, commit=False
    )
    conn.commit()
    return result


def create_note(
    conn: sqlite3.Connection,
    paper_id: int,
    note: str,
    comment: str,
    user_id: int,
) -> dict[str, Any]:
    if get_paper_detail(conn, paper_id, user_id=user_id) is None:
        raise ValueError("paper not found")
    result = learning_repository.add_note(
        conn, paper_id, note, comment, user_id=user_id, commit=False
    )
    conn.commit()
    return result


def list_history(conn: sqlite3.Connection, limit: int, user_id: int) -> list[dict[str, Any]]:
    return learning_repository.get_history(conn, limit=limit, user_id=user_id)


def list_subscriptions(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    return learning_repository.get_subscriptions(conn, user_id=user_id)


def subscribe(conn: sqlite3.Connection, topic: str, user_id: int) -> dict[str, Any]:
    result = learning_repository.upsert_subscription(
        conn, topic, user_id=user_id, commit=False
    )
    conn.commit()
    return result


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise LLMServiceError("LLM 未返回有效 JSON")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMServiceError("LLM 未返回有效 JSON") from exc
    if not isinstance(payload, dict):
        raise LLMServiceError("LLM 返回格式错误")
    return payload

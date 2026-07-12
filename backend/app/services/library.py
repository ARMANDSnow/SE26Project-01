from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..database import list_library_folders
from .llm import LLMClient, LLMServiceError


def recommend_folder(conn: sqlite3.Connection, item_id: int, user_id: int = 1) -> dict[str, Any]:
    item = conn.execute(
        """
        SELECT i.id, i.folder_id, p.title, p.abstract, p.categories_json, p.primary_category
        FROM library_items i JOIN papers p ON p.id = i.paper_id
        WHERE i.id = ? AND i.user_id = ?
        """,
        (item_id, user_id),
    ).fetchone()
    if item is None:
        raise ValueError("library item not found")
    folders = [folder for folder in list_library_folders(conn, user_id) if not folder["is_root"] and not folder["is_system"]]
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

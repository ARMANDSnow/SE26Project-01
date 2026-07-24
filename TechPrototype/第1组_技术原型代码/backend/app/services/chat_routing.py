from __future__ import annotations

import json
import re
import sqlite3
from typing import Literal, Protocol

from pydantic import BaseModel, ValidationError

from ..repositories.research import (
    ResearchNotFoundError,
    get_run_snapshot,
    insert_topic_research_run,
)
from .chat_parts import decode_parts, encode_parts, research_run_parts, text_parts
from .conversations import get_thread
from .documents import estimate_tokens
from .llm import LLMClient, LLMConfigurationError, LLMServiceError


ChatRoute = Literal["normal_chat", "research_run"]
ChatRouteReason = Literal["explicit", "deterministic", "model"]

_RESEARCH_PATTERNS = (
    re.compile(r"(调研|文献综述|论文综述|研究进展|研究脉络|系统综述)"),
    re.compile(r"(搜索|查找|收集|比较|对比).{0,12}(论文|文献|papers?)", re.IGNORECASE),
    re.compile(r"(literature review|research survey|survey papers?|compare papers?)", re.IGNORECASE),
)
_NORMAL_PATTERNS = (
    re.compile(r"^(你好|您好|嗨|谢谢|多谢|再见)[！!。,.\s]*$"),
    re.compile(r"^(解释|什么是|如何理解|翻译|润色)"),
    re.compile(r"^(what is|explain|translate)\b", re.IGNORECASE),
)


class ChatRoutingUnavailable(RuntimeError):
    pass


class ChatRouteConflict(RuntimeError):
    pass


class _ModelDecision(BaseModel):
    route: Literal["normal_chat", "research_run"]


class ChatRouteClassifier(Protocol):
    def classify(self, content: str) -> ChatRoute: ...


class LLMChatRouteClassifier:
    def classify(self, content: str) -> ChatRoute:
        prompt = (
            "Classify whether the user is asking for a multi-step paper research workflow "
            "or an ordinary chat response. Return JSON only with route equal to "
            '"research_run" or "normal_chat". Do not include reasoning.'
        )
        try:
            raw = LLMClient().complete(
                prompt,
                content,
                json_mode=True,
                timeout_seconds=10,
                max_attempts=1,
            )
            return _ModelDecision.model_validate(json.loads(raw)).route
        except (LLMConfigurationError, LLMServiceError, ValidationError, json.JSONDecodeError) as exc:
            raise ChatRoutingUnavailable("routing_unavailable") from exc


def get_chat_route_classifier() -> ChatRouteClassifier:
    return LLMChatRouteClassifier()


def deterministic_chat_route(content: str) -> ChatRoute | None:
    normalized = " ".join(content.strip().split())
    if any(pattern.search(normalized) for pattern in _RESEARCH_PATTERNS):
        return "research_run"
    if any(pattern.search(normalized) for pattern in _NORMAL_PATTERNS):
        return "normal_chat"
    return None


def choose_chat_route(
    mode: Literal["auto", "normal", "deep_research"],
    content: str,
    classifier: ChatRouteClassifier,
) -> tuple[ChatRoute, ChatRouteReason]:
    if mode == "normal":
        return "normal_chat", "explicit"
    if mode == "deep_research":
        return "research_run", "explicit"
    normalized = " ".join(content.strip().split())
    deterministic = deterministic_chat_route(normalized)
    if deterministic is not None:
        return deterministic, "deterministic"
    return classifier.classify(normalized), "model"


def _title_from_content(content: str) -> str:
    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "新建研究")
    return first_line if len(first_line) <= 80 else f"{first_line[:79]}…"


def _research_run_id(parts_json: str, fallback_text: str) -> str | None:
    for part in decode_parts(parts_json, fallback_text):
        if part.get("type") == "data" and part.get("name") == "research-run":
            data = part.get("data")
            if isinstance(data, dict) and isinstance(data.get("run_id"), str):
                return str(data["run_id"])
    return None


def _replayed_run(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    thread_id: str,
    user_message: dict[str, object],
    assistant_message_id: str,
) -> str | None:
    user_row = conn.execute(
        """
        SELECT m.* FROM chat_messages m
        JOIN chat_threads t ON t.id = m.thread_id
        WHERE m.id = ? AND m.thread_id = ? AND t.user_id = ?
        """,
        (str(user_message["id"]), thread_id, user_id),
    ).fetchone()
    card_row = conn.execute(
        """
        SELECT m.* FROM chat_messages m
        JOIN chat_threads t ON t.id = m.thread_id
        WHERE m.id = ? AND m.thread_id = ? AND t.user_id = ?
        """,
        (assistant_message_id, thread_id, user_id),
    ).fetchone()
    if user_row is None and card_row is None:
        return None
    if user_row is None or card_row is None:
        raise ChatRouteConflict("message id already exists")
    expected_parent = user_message.get("parent_id")
    expected_source = user_message.get("source_message_id")
    if (
        user_row["role"] != "user"
        or user_row["content"] != str(user_message["content"]).strip()
        or user_row["parent_id"] != expected_parent
        or user_row["source_message_id"] != expected_source
        or user_row["status"] != "complete"
        or card_row["role"] != "assistant"
        or card_row["parent_id"] != user_row["id"]
        or card_row["source_message_id"] is not None
        or card_row["status"] != "complete"
    ):
        raise ChatRouteConflict("message id already exists")
    run_id = _research_run_id(str(card_row["content_parts_json"]), str(card_row["content"]))
    if run_id is None:
        raise ChatRouteConflict("message id already exists")
    owned_run = conn.execute(
        "SELECT thread_id, title, goal, mode FROM research_runs WHERE id = ? AND user_id = ?",
        (run_id, user_id),
    ).fetchone()
    expected_label = ""
    if owned_run is not None:
        expected_label = (
            f"已创建主题调研任务「{owned_run['title']}」。Workflow 将只展示数据库中真实完成的检索、筛选、正文与阅读卡数据。"
            if str(owned_run["mode"]) == "topic"
            else f"已创建调研任务「{owned_run['title']}」。当前仅执行可恢复 Harness 骨架，尚未检索论文。"
        )
    thread_head = conn.execute(
        "SELECT active_leaf_id FROM chat_threads WHERE id = ? AND user_id = ?",
        (thread_id, user_id),
    ).fetchone()
    if (
        owned_run is None
        or owned_run["thread_id"] != thread_id
        or owned_run["goal"] != str(user_message["content"]).strip()
        or card_row["content"] != expected_label
        or thread_head is None
        or thread_head["active_leaf_id"] != assistant_message_id
    ):
        raise ChatRouteConflict("message id already exists")
    return run_id


def find_replayed_chat_research_run(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    thread_id: str,
    user_message: dict[str, object],
    assistant_message_id: str,
) -> dict[str, object] | None:
    """Read-only replay check used before any optional model classification."""

    replayed_run_id = _replayed_run(
        conn,
        user_id=user_id,
        thread_id=thread_id,
        user_message=user_message,
        assistant_message_id=assistant_message_id,
    )
    if replayed_run_id is None:
        return None
    return get_run_snapshot(conn, replayed_run_id, user_id)


def create_chat_research_run(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    thread_id: str,
    user_message: dict[str, object],
    assistant_message_id: str,
    message_token_limit: int,
) -> dict[str, object]:
    content = str(user_message.get("content", "")).strip()
    if not content:
        raise ValueError("message is empty")
    if get_thread(conn, thread_id, user_id) is None:
        raise ResearchNotFoundError("conversation not found")

    conn.execute("BEGIN IMMEDIATE")
    try:
        replayed_run_id = _replayed_run(
            conn,
            user_id=user_id,
            thread_id=thread_id,
            user_message=user_message,
            assistant_message_id=assistant_message_id,
        )
        if replayed_run_id is not None:
            conn.commit()
            return get_run_snapshot(conn, replayed_run_id, user_id)

        parent_id = user_message.get("parent_id")
        source_id = user_message.get("source_message_id")
        for message_id, label in ((parent_id, "parent"), (source_id, "source")):
            if message_id is None:
                continue
            exists = conn.execute(
                "SELECT 1 FROM chat_messages WHERE id = ? AND thread_id = ?",
                (message_id, thread_id),
            ).fetchone()
            if exists is None:
                raise ValueError(f"{label} message not found")

        user_message_id = str(user_message["id"])
        conn.execute(
            """
            INSERT INTO chat_messages(
                id, thread_id, parent_id, source_message_id, role, content,
                content_parts_json, status, token_count, completed_at
            ) VALUES (?, ?, ?, ?, 'user', ?, ?, 'complete', ?, CURRENT_TIMESTAMP)
            """,
            (
                user_message_id,
                thread_id,
                parent_id,
                source_id,
                content,
                encode_parts(text_parts(content)),
                estimate_tokens(content),
            ),
        )
        title = _title_from_content(content)
        run_id = insert_topic_research_run(
            conn,
            user_id=user_id,
            title=title,
            goal=content,
            thread_id=thread_id,
        )
        label = f"已创建主题调研任务「{title}」。Workflow 将只展示数据库中真实完成的检索、筛选、正文与阅读卡数据。"
        conn.execute(
            """
            INSERT INTO chat_messages(
                id, thread_id, parent_id, role, content, content_parts_json,
                status, token_count, completed_at
            ) VALUES (?, ?, ?, 'assistant', ?, ?, 'complete', ?, CURRENT_TIMESTAMP)
            """,
            (
                assistant_message_id,
                thread_id,
                user_message_id,
                label,
                encode_parts(research_run_parts(label, run_id)),
                estimate_tokens(label),
            ),
        )
        conn.execute(
            """
            UPDATE chat_threads
            SET active_leaf_id = ?, message_token_limit = ?,
                title = CASE WHEN title = '新对话' THEN ? ELSE title END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
            """,
            (assistant_message_id, message_token_limit, title, thread_id, user_id),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ChatRouteConflict("message id already exists") from exc
    except Exception:
        conn.rollback()
        raise
    return get_run_snapshot(conn, run_id, user_id)

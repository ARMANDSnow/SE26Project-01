from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from ..config import get_settings
from .documents import estimate_tokens
from .llm import LLMClient


SYSTEM_PROMPT = """你是单篇科研论文阅读助手。下面会提供论文的完整解析正文。
只能依据论文正文和当前对话回答；如果论文没有提供所需信息，应明确说明。
回答使用中文，涉及实验结果或关键结论时标注对应章节或页码（如果正文中可识别）。
不要声称使用了外部搜索、知识库或未提供的论文。"""


def create_thread(
    conn: sqlite3.Connection,
    paper_id: int | None,
    user_id: int = 1,
    title: str = "新对话",
) -> dict[str, Any]:
    if paper_id is not None and conn.execute(
        "SELECT 1 FROM papers WHERE id = ?", (paper_id,)
    ).fetchone() is None:
        raise ValueError("paper not found")
    thread_id = f"thread_{uuid4().hex}"
    conn.execute(
        "INSERT INTO chat_threads (id, user_id, paper_id, title) VALUES (?, ?, ?, ?)",
        (thread_id, user_id, paper_id, title.strip() or "新对话"),
    )
    conn.commit()
    return get_thread(conn, thread_id, user_id) or {}


def list_threads(conn: sqlite3.Connection, paper_id: int, user_id: int = 1) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, paper_id, title, active_leaf_id, message_token_limit, archived,
               created_at, updated_at
        FROM chat_threads WHERE user_id = ? AND paper_id = ?
        ORDER BY archived, updated_at DESC
        """,
        (user_id, paper_id),
    ).fetchall()
    return [dict(row) for row in rows]


def get_thread(conn: sqlite3.Connection, thread_id: str, user_id: int = 1) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, paper_id, title, active_leaf_id, message_token_limit, archived,
               created_at, updated_at
        FROM chat_threads WHERE id = ? AND user_id = ?
        """,
        (thread_id, user_id),
    ).fetchone()
    return dict(row) if row else None


def update_thread_head(conn: sqlite3.Connection, thread_id: str, head_id: str | None, user_id: int = 1) -> dict[str, Any]:
    thread = get_thread(conn, thread_id, user_id)
    if thread is None:
        raise ValueError("thread not found")
    if head_id is not None:
        row = conn.execute(
            "SELECT 1 FROM chat_messages WHERE id = ? AND thread_id = ?",
            (head_id, thread_id),
        ).fetchone()
        if row is None:
            raise ValueError("message not found")
    conn.execute(
        "UPDATE chat_threads SET active_leaf_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (head_id, thread_id),
    )
    conn.commit()
    return get_thread(conn, thread_id, user_id) or {}


def get_message_repository(conn: sqlite3.Connection, thread_id: str, user_id: int = 1) -> dict[str, Any]:
    thread = get_thread(conn, thread_id, user_id)
    if thread is None:
        raise ValueError("thread not found")
    rows = conn.execute(
        """
        SELECT id, parent_id, source_message_id, role, content, status, created_at
        FROM chat_messages WHERE thread_id = ? ORDER BY created_at, rowid
        """,
        (thread_id,),
    ).fetchall()
    return {
        "headId": thread["active_leaf_id"],
        "messages": [dict(row) for row in rows],
    }


def _assert_parent(conn: sqlite3.Connection, thread_id: str, parent_id: str | None) -> None:
    if parent_id is None:
        return
    if conn.execute(
        "SELECT 1 FROM chat_messages WHERE id = ? AND thread_id = ?",
        (parent_id, thread_id),
    ).fetchone() is None:
        raise ValueError("parent message not found")


def _assert_source_message(conn: sqlite3.Connection, thread_id: str, source_id: str | None) -> None:
    if source_id is None:
        return
    if conn.execute(
        "SELECT 1 FROM chat_messages WHERE id = ? AND thread_id = ?",
        (source_id, thread_id),
    ).fetchone() is None:
        raise ValueError("source message not found")


def prepare_run(
    conn: sqlite3.Connection,
    *,
    thread_id: str,
    user_message: dict[str, Any] | None,
    parent_message_id: str | None,
    assistant_message_id: str,
    source_message_id: str | None,
    message_token_limit: int,
    user_id: int = 1,
) -> dict[str, Any]:
    thread = get_thread(conn, thread_id, user_id)
    if thread is None:
        raise ValueError("thread not found")

    savepoint = "prepare_chat_run"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        input_message_id: str
        if user_message is not None:
            input_message_id = str(user_message["id"])
            parent_id = user_message.get("parent_id")
            user_source_id = user_message.get("source_message_id")
            _assert_parent(conn, thread_id, parent_id)
            _assert_source_message(conn, thread_id, user_source_id)
            content = str(user_message.get("content", "")).strip()
            if not content:
                raise ValueError("message is empty")
            conn.execute(
                """
                INSERT INTO chat_messages
                    (id, thread_id, parent_id, source_message_id, role, content, status, token_count, completed_at)
                VALUES (?, ?, ?, ?, 'user', ?, 'complete', ?, CURRENT_TIMESTAMP)
                """,
                (
                    input_message_id,
                    thread_id,
                    parent_id,
                    user_source_id,
                    content,
                    estimate_tokens(content),
                ),
            )
        else:
            input_message_id = str(parent_message_id or "")
            row = conn.execute(
                "SELECT role FROM chat_messages WHERE id = ? AND thread_id = ?",
                (input_message_id, thread_id),
            ).fetchone()
            if row is None or row["role"] != "user":
                raise ValueError("regenerate parent must be a user message")

        _assert_parent(conn, thread_id, input_message_id)
        _assert_source_message(conn, thread_id, source_message_id)
        conn.execute(
            """
            INSERT INTO chat_messages
                (id, thread_id, parent_id, source_message_id, role, content, status)
            VALUES (?, ?, ?, ?, 'assistant', '', 'running')
            """,
            (assistant_message_id, thread_id, input_message_id, source_message_id),
        )
        run_id = f"run_{uuid4().hex}"
        settings = get_settings()
        conn.execute(
            """
            INSERT INTO chat_runs (id, thread_id, input_message_id, output_message_id, model)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, thread_id, input_message_id, assistant_message_id, settings.llm_chat_model),
        )
        conn.execute(
            """
            UPDATE chat_threads SET active_leaf_id = ?, message_token_limit = ?,
                updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """,
            (assistant_message_id, message_token_limit, thread_id),
        )
    except sqlite3.IntegrityError as exc:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise ValueError("message id already exists") from exc
    except Exception:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise
    conn.execute(f"RELEASE {savepoint}")
    conn.commit()
    return {
        "run_id": run_id,
        "thread_id": thread_id,
        "paper_id": thread["paper_id"],
        "input_message_id": input_message_id,
        "assistant_message_id": assistant_message_id,
        "message_token_limit": message_token_limit,
    }


def _lineage(conn: sqlite3.Connection, thread_id: str, leaf_id: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    current: str | None = leaf_id
    seen: set[str] = set()
    while current:
        if current in seen:
            raise ValueError("message cycle detected")
        seen.add(current)
        row = conn.execute(
            """
            SELECT id, parent_id, role, content FROM chat_messages
            WHERE id = ? AND thread_id = ?
            """,
            (current, thread_id),
        ).fetchone()
        if row is None:
            raise ValueError("message not found")
        messages.append(dict(row))
        current = row["parent_id"]
    messages.reverse()
    return messages


def build_model_messages(conn: sqlite3.Connection, run: dict[str, Any]) -> list[dict[str, str]]:
    if run["paper_id"] is None:
        raise ValueError("library chat is not implemented")
    document = conn.execute(
        """
        SELECT content_markdown, token_count, status FROM paper_documents WHERE paper_id = ?
        """,
        (run["paper_id"],),
    ).fetchone()
    if document is None or document["status"] != "completed" or not document["content_markdown"]:
        raise ValueError("paper document is not parsed")

    settings = get_settings()
    immutable_tokens = (
        estimate_tokens(SYSTEM_PROMPT)
        + int(document["token_count"])
        + settings.llm_max_output_tokens
        + 1024
    )
    if immutable_tokens >= settings.llm_context_window:
        raise ValueError(
            f"paper exceeds model context: paper={document['token_count']}, context={settings.llm_context_window}"
        )
    history_budget = min(run["message_token_limit"], settings.llm_context_window - immutable_tokens)
    lineage = _lineage(conn, run["thread_id"], run["input_message_id"])
    current = lineage[-1]
    older = lineage[:-1]
    selected: list[dict[str, Any]] = []
    used = 0
    for message in reversed(older):
        cost = estimate_tokens(message["content"]) + 8
        if used + cost > history_budget:
            break
        selected.append(message)
        used += cost
    selected.reverse()

    paper_prompt = (
        "以下是当前论文的完整解析正文。正文开始：\n\n"
        + document["content_markdown"]
        + "\n\n正文结束。"
    )
    model_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": paper_prompt},
        {"role": "assistant", "content": "已读取论文完整正文，请继续提问。"},
    ]
    model_messages.extend({"role": item["role"], "content": item["content"]} for item in selected if item["role"] in {"user", "assistant"})
    model_messages.append({"role": "user", "content": current["content"]})
    return model_messages


def _update_running_output(
    conn: sqlite3.Connection,
    run: dict[str, Any],
    *,
    content: str,
) -> None:
    cursor = conn.execute(
        """
        UPDATE chat_messages SET content = ?, token_count = ?
        WHERE id = ? AND thread_id = ? AND status = 'running'
          AND EXISTS (
              SELECT 1 FROM chat_runs
              WHERE id = ? AND thread_id = ? AND output_message_id = chat_messages.id
                AND status = 'running'
          )
        """,
        (
            content,
            estimate_tokens(content),
            run["assistant_message_id"],
            run["thread_id"],
            run["run_id"],
            run["thread_id"],
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("run output message is not writable")


def _fail_running_output(conn: sqlite3.Connection, run: dict[str, Any]) -> None:
    conn.execute(
        """
        UPDATE chat_messages SET status = 'failed'
        WHERE id = ? AND thread_id = ? AND status = 'running'
          AND EXISTS (
              SELECT 1 FROM chat_runs
              WHERE id = ? AND thread_id = ? AND output_message_id = chat_messages.id
          )
        """,
        (
            run["assistant_message_id"],
            run["thread_id"],
            run["run_id"],
            run["thread_id"],
        ),
    )


def stream_run(conn: sqlite3.Connection, run: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    accumulated = ""
    completed = False
    try:
        messages = build_model_messages(conn, run)
        yield "run.started", {"run_id": run["run_id"], "message_id": run["assistant_message_id"]}
        for delta in LLMClient().stream(messages):
            accumulated += delta
            _update_running_output(conn, run, content=accumulated)
            conn.commit()
            yield "text.delta", {"delta": delta}
        savepoint = "complete_chat_run"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            message_cursor = conn.execute(
                """
                UPDATE chat_messages SET status = 'complete', completed_at = CURRENT_TIMESTAMP
                WHERE id = ? AND thread_id = ? AND status = 'running'
                  AND EXISTS (
                      SELECT 1 FROM chat_runs
                      WHERE id = ? AND thread_id = ? AND output_message_id = chat_messages.id
                        AND status = 'running'
                  )
                """,
                (
                    run["assistant_message_id"],
                    run["thread_id"],
                    run["run_id"],
                    run["thread_id"],
                ),
            )
            run_cursor = conn.execute(
                """
                UPDATE chat_runs SET status = 'complete', completed_at = CURRENT_TIMESTAMP
                WHERE id = ? AND thread_id = ? AND output_message_id = ? AND status = 'running'
                """,
                (run["run_id"], run["thread_id"], run["assistant_message_id"]),
            )
            if message_cursor.rowcount != 1 or run_cursor.rowcount != 1:
                raise ValueError("run output message is not writable")
        except Exception:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
            raise
        conn.execute(f"RELEASE {savepoint}")
        conn.commit()
        completed = True
        yield "message.completed", {"message_id": run["assistant_message_id"], "content": accumulated}
    except Exception as exc:
        _fail_running_output(conn, run)
        conn.execute(
            """
            UPDATE chat_runs SET status = 'failed', error = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND thread_id = ? AND output_message_id = ?
            """,
            (
                str(exc)[:1000],
                run["run_id"],
                run["thread_id"],
                run["assistant_message_id"],
            ),
        )
        conn.commit()
        yield "run.failed", {"message": str(exc)}
    finally:
        if not completed:
            _fail_running_output(conn, run)
            conn.execute(
                """
                UPDATE chat_runs SET status = CASE WHEN status = 'running' THEN 'cancelled' ELSE status END,
                    completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
                WHERE id = ? AND thread_id = ? AND output_message_id = ?
                """,
                (run["run_id"], run["thread_id"], run["assistant_message_id"]),
            )
            conn.commit()


def create_summary(conn: sqlite3.Connection, paper_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT p.title, d.content_markdown, d.source_hash, d.status
        FROM papers p LEFT JOIN paper_documents d ON d.paper_id = p.id WHERE p.id = ?
        """,
        (paper_id,),
    ).fetchone()
    if row is None:
        raise ValueError("paper not found")
    if row["status"] != "completed" or not row["content_markdown"]:
        raise ValueError("paper document is not parsed")
    prompt = f"""请根据下面论文全文生成中文阅读概要，使用 Markdown，严格包含以下部分：
# 一句话结论
# 研究问题
# 主要贡献
# 方法
# 实验设计与结果
# 局限性
# 值得进一步思考的问题

论文标题：{row['title']}

论文全文：
{row['content_markdown']}
    """
    settings = get_settings()
    required_tokens = (
        estimate_tokens(prompt)
        + estimate_tokens("你是严谨的科研论文阅读助手，只能依据提供的论文全文总结。")
        + settings.llm_max_output_tokens
        + 512
    )
    if required_tokens > settings.llm_context_window:
        raise ValueError(
            f"paper exceeds model context: required={required_tokens}, context={settings.llm_context_window}"
        )
    content = LLMClient().complete("你是严谨的科研论文阅读助手，只能依据提供的论文全文总结。", prompt)
    conn.execute("UPDATE summary_versions SET is_active = 0 WHERE paper_id = ?", (paper_id,))
    cursor = conn.execute(
        """
        INSERT INTO summary_versions (paper_id, content, model, source_hash, is_active)
        VALUES (?, ?, ?, ?, 1)
        """,
        (paper_id, content.strip(), settings.llm_chat_model, row["source_hash"]),
    )
    conn.commit()
    result = conn.execute(
        """
        SELECT id, paper_id, content, model, prompt_version, source_hash, is_active, created_at
        FROM summary_versions WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return dict(result)

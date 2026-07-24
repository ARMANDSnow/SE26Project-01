from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from ..config import get_settings
from ..repositories.uploads import paper_is_accessible
from ..repositories.workspaces import workspace_context
from .chat_parts import decode_parts, encode_parts, text_parts
from .documents import estimate_tokens
from .llm import LLMClient, LLMConfigurationError


DEFAULT_THREAD_TITLE = "\u65b0\u5bf9\u8bdd"


SYSTEM_PROMPT = """你是单篇科研论文阅读助手。下面会提供论文的完整解析正文。
只能依据论文正文和当前对话回答；如果论文没有提供所需信息，应明确说明。
回答使用中文，涉及实验结果或关键结论时标注对应章节或页码（如果正文中可识别）。
不要声称使用了外部搜索、知识库或未提供的论文。"""

GENERAL_SYSTEM_PROMPT = """You are a rigorous, clear research assistant.
Use only information supplied in the conversation and your own background knowledge.
You do not have web search or external tools. Do not claim to call them.
Answer in Chinese by default and state uncertainty when information is insufficient."""


def _message_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    raw_parts = str(result.pop("content_parts_json", "[]"))
    result["content_parts"] = decode_parts(raw_parts, str(result["content"]))
    return result


def create_thread(
    conn: sqlite3.Connection,
    paper_id: int | None,
    user_id: int = 1,
    title: str = DEFAULT_THREAD_TITLE,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    if paper_id is not None and workspace_id is not None:
        raise ValueError("paper chat cannot bind a workspace")
    if paper_id is not None and not paper_is_accessible(conn, paper_id, user_id):
        raise ValueError("paper not found")
    if workspace_id is not None:
        workspace_context(conn, workspace_id, user_id)
    thread_id = f"thread_{uuid4().hex}"
    conn.execute(
        "INSERT INTO chat_threads (id, user_id, paper_id, workspace_id, title) VALUES (?, ?, ?, ?, ?)",
        (thread_id, user_id, paper_id, workspace_id, title.strip() or DEFAULT_THREAD_TITLE),
    )
    conn.commit()
    return get_thread(conn, thread_id, user_id) or {}


def list_threads(conn: sqlite3.Connection, paper_id: int | None, user_id: int = 1) -> list[dict[str, Any]]:
    scope_clause = "paper_id IS NULL" if paper_id is None else "paper_id = ?"
    params: tuple[Any, ...] = (user_id,) if paper_id is None else (user_id, paper_id)
    rows = conn.execute(
        f"""
        SELECT id, paper_id, workspace_id, title, active_leaf_id, message_token_limit, archived,
               created_at, updated_at
        FROM chat_threads WHERE user_id = ? AND {scope_clause}
        ORDER BY archived, updated_at DESC
        """,
        params,
    ).fetchall()
    return [
        dict(row)
        for row in rows
        if (row["paper_id"] is None or paper_is_accessible(conn, int(row["paper_id"]), user_id))
        and (row["workspace_id"] is None or _workspace_is_accessible(conn, str(row["workspace_id"]), user_id))
    ]


def _workspace_is_accessible(conn: sqlite3.Connection, workspace_id: str, user_id: int) -> bool:
    try:
        workspace_context(conn, workspace_id, user_id)
    except ValueError:
        return False
    return True


def get_thread(conn: sqlite3.Connection, thread_id: str, user_id: int = 1) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, paper_id, workspace_id, title, active_leaf_id, message_token_limit, archived,
               created_at, updated_at
        FROM chat_threads WHERE id = ? AND user_id = ?
        """,
        (thread_id, user_id),
    ).fetchone()
    if row is None:
        return None
    if row["paper_id"] is not None and not paper_is_accessible(
        conn, int(row["paper_id"]), user_id
    ):
        return None
    if row["workspace_id"] is not None and not _workspace_is_accessible(
        conn, str(row["workspace_id"]), user_id
    ):
        return None
    return dict(row)


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


def update_thread_workspace(
    conn: sqlite3.Connection, thread_id: str, workspace_id: str | None, user_id: int = 1
) -> dict[str, Any]:
    thread = get_thread(conn, thread_id, user_id)
    if thread is None:
        raise ValueError("thread not found")
    if thread["paper_id"] is not None:
        raise ValueError("paper chat cannot bind a workspace")
    if conn.execute("SELECT 1 FROM chat_messages WHERE thread_id = ? LIMIT 1", (thread_id,)).fetchone():
        raise ValueError("workspace is locked after the first message")
    if workspace_id is not None:
        workspace_context(conn, workspace_id, user_id)
    conn.execute(
        "UPDATE chat_threads SET workspace_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (workspace_id, thread_id),
    )
    conn.commit()
    return get_thread(conn, thread_id, user_id) or {}


def update_thread_title(
    conn: sqlite3.Connection, thread_id: str, title: str, user_id: int = 1
) -> dict[str, Any]:
    if get_thread(conn, thread_id, user_id) is None:
        raise ValueError("thread not found")
    cleaned = title.strip()
    if not cleaned:
        raise ValueError("thread title must not be blank")
    conn.execute(
        "UPDATE chat_threads SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (cleaned, thread_id),
    )
    conn.commit()
    return get_thread(conn, thread_id, user_id) or {}


def get_message_repository(conn: sqlite3.Connection, thread_id: str, user_id: int = 1) -> dict[str, Any]:
    thread = get_thread(conn, thread_id, user_id)
    if thread is None:
        raise ValueError("thread not found")
    rows = conn.execute(
        """
        SELECT id, parent_id, source_message_id, role, content, content_parts_json,
               status, created_at
        FROM chat_messages WHERE thread_id = ? ORDER BY created_at, rowid
        """,
        (thread_id,),
    ).fetchall()
    return {
        "headId": thread["active_leaf_id"],
        "messages": [_message_row(row) for row in rows],
    }


def _generated_thread_title(content: str) -> str:
    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    normalized = " ".join(first_line.split())
    return normalized if len(normalized) <= 40 else f"{normalized[:39]}..."


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
    operation: str = "append",
    user_id: int = 1,
) -> dict[str, Any]:
    thread = get_thread(conn, thread_id, user_id)
    if thread is None:
        raise ValueError("thread not found")
    if operation not in {"append", "edit", "regenerate"}:
        raise ValueError("unsupported chat operation")
    if operation == "regenerate" and user_message is not None:
        raise ValueError("regenerate must reuse an existing user message")
    if operation != "regenerate" and user_message is None:
        raise ValueError(f"{operation} requires a user message")

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
                    (id, thread_id, parent_id, source_message_id, role, content,
                     content_parts_json, status, token_count, completed_at)
                VALUES (?, ?, ?, ?, 'user', ?, ?, 'complete', ?, CURRENT_TIMESTAMP)
                """,
                (
                    input_message_id,
                    thread_id,
                    parent_id,
                    user_source_id,
                    content,
                    encode_parts(text_parts(content)),
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
                (id, thread_id, parent_id, source_message_id, role, content,
                 content_parts_json, status)
            VALUES (?, ?, ?, ?, 'assistant', '', ?, 'running')
            """,
            (
                assistant_message_id,
                thread_id,
                input_message_id,
                source_message_id,
                encode_parts(text_parts("")),
            ),
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
        generated_title = (
            _generated_thread_title(str(user_message.get("content", "")))
            if user_message is not None and thread["title"] == DEFAULT_THREAD_TITLE
            else ""
        )
        conn.execute(
            """
            UPDATE chat_threads SET active_leaf_id = ?, message_token_limit = ?,
                title = CASE WHEN ? <> '' THEN ? ELSE title END,
                updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """,
            (assistant_message_id, message_token_limit, generated_title, generated_title, thread_id),
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
        "workspace_id": thread["workspace_id"],
        "user_id": user_id,
        "input_message_id": input_message_id,
        "assistant_message_id": assistant_message_id,
        "message_token_limit": message_token_limit,
        "operation": operation,
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
    settings = get_settings()
    lineage = _lineage(conn, run["thread_id"], run["input_message_id"])
    current = lineage[-1]

    if run["paper_id"] is None:
        system_prompt = GENERAL_SYSTEM_PROMPT
        if run.get("workspace_id"):
            context = workspace_context(conn, str(run["workspace_id"]), int(run["user_id"]))
            item_lines = []
            for item in context.get("items", [])[:40]:
                title = str(item.get("title") or "Untitled item").strip()
                abstract = str(item.get("abstract") or "").strip()
                item_lines.append(f"- {title}" + (f": {abstract[:600]}" if abstract else ""))
            source_label = "research project" if context.get("project_id") else "library folder"
            system_prompt += (
                f"\n\nWorkspace context is available in this conversation.\n"
                f"Workspace name: {context['title']}\n"
                f"Bound source type: {source_label}\n"
                + (
                    f"Workspace description: {context['description']}\n"
                    if context.get("description")
                    else ""
                )
                + "The item list below was supplied by the application. You may use it, but do not claim filesystem, database, network, or tool access. Do not say that the Workspace lacks content merely because its optional description is empty. Answer from the listed items and conversation; distinguish supplied evidence from your own background knowledge.\n"
                + ("\n".join(item_lines) if item_lines else "No Workspace items were supplied for this turn.")
            )

        immutable_tokens = (
            estimate_tokens(system_prompt)
            + estimate_tokens(current["content"])
            + settings.llm_max_output_tokens
            + 512
        )
        if immutable_tokens >= settings.llm_context_window:
            raise ValueError(
                f"message exceeds model context: required={immutable_tokens}, context={settings.llm_context_window}"
            )
        history_budget = min(run["message_token_limit"], settings.llm_context_window - immutable_tokens)
        selected = _select_history(lineage[:-1], history_budget)
        model_messages = [{"role": "system", "content": system_prompt}]
        model_messages.extend(
            {"role": item["role"], "content": item["content"]}
            for item in selected
            if item["role"] in {"user", "assistant"}
        )
        model_messages.append({"role": "user", "content": current["content"]})
        return model_messages

    document = conn.execute(
        """
        SELECT content_markdown, token_count, status FROM paper_documents WHERE paper_id = ?
        """,
        (run["paper_id"],),
    ).fetchone()
    if document is None or document["status"] != "completed" or not document["content_markdown"]:
        raise ValueError("paper document is not parsed")

    immutable_tokens = (
        estimate_tokens(SYSTEM_PROMPT)
        + int(document["token_count"])
        + estimate_tokens(current["content"])
        + settings.llm_max_output_tokens
        + 1024
    )
    if immutable_tokens >= settings.llm_context_window:
        raise ValueError(
            f"paper exceeds model context: paper={document['token_count']}, context={settings.llm_context_window}"
        )
    history_budget = min(run["message_token_limit"], settings.llm_context_window - immutable_tokens)
    selected = _select_history(lineage[:-1], history_budget)

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


def _select_history(messages: list[dict[str, Any]], token_budget: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used = 0
    for message in reversed(messages):
        cost = estimate_tokens(message["content"]) + 8
        if used + cost > token_budget:
            break
        selected.append(message)
        used += cost
    selected.reverse()
    return selected


def _update_running_output(
    conn: sqlite3.Connection,
    run: dict[str, Any],
    *,
    content: str,
) -> None:
    cursor = conn.execute(
        """
        UPDATE chat_messages SET content = ?, content_parts_json = ?, token_count = ?
        WHERE id = ? AND thread_id = ? AND status = 'running'
          AND EXISTS (
              SELECT 1 FROM chat_runs
              WHERE id = ? AND thread_id = ? AND output_message_id = chat_messages.id
                AND status = 'running'
          )
        """,
        (
            content,
            encode_parts(text_parts(content)),
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
    except LLMConfigurationError:
        _fail_running_output(conn, run)
        conn.execute(
            """
            UPDATE chat_runs SET status = 'failed', error = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND thread_id = ? AND output_message_id = ?
            """,
            (
                "llm_configuration_unavailable",
                run["run_id"],
                run["thread_id"],
                run["assistant_message_id"],
            ),
        )
        conn.commit()
        yield "run.failed", {"message": "\u6a21\u578b\u5c1a\u672a\u914d\u7f6e\u3002\u8bf7\u5728\u542f\u52a8\u540e\u7aef\u7684\u73af\u5883\u4e2d\u8bbe\u7f6e LLM_API_KEY \u540e\u91cd\u542f\u670d\u52a1\u3002"}
    except Exception:
        _fail_running_output(conn, run)
        conn.execute(
            """
            UPDATE chat_runs SET status = 'failed', error = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND thread_id = ? AND output_message_id = ?
            """,
            (
                "chat_generation_failed",
                run["run_id"],
                run["thread_id"],
                run["assistant_message_id"],
            ),
        )
        conn.commit()
        yield "run.failed", {"message": "\u56de\u7b54\u751f\u6210\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"}
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


def create_summary(
    conn: sqlite3.Connection,
    paper_id: int,
    user_id: int = 1,
) -> dict[str, Any]:
    if not paper_is_accessible(conn, paper_id, user_id):
        raise ValueError("paper not found")
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

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, cast

from .uploads import paper_is_accessible


RUN_STATUSES = {
    "queued",
    "running",
    "waiting_input",
    "paused",
    "completed",
    "failed",
    "cancelling",
    "cancelled",
}
TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


class ResearchNotFoundError(LookupError):
    pass


class ResearchConflictError(RuntimeError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decoded(value: str | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _run_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["budget"] = _decoded(result.pop("budget_json", "{}"), {})
    result["usage"] = _decoded(result.pop("usage_json", "{}"), {})
    return result


def _step_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["depends_on"] = _decoded(result.pop("depends_on_json", "[]"), [])
    result["input"] = _decoded(result.pop("input_json", "{}"), {})
    result["output"] = _decoded(result.pop("output_json", "{}"), {})
    return result


def _public_step_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "step_key": row["step_key"],
        "step_type": row["step_type"],
        "title": row["title"],
        "agent_name": row["agent_name"],
        "status": row["status"],
        "position": row["position"],
        "plan_version": row["plan_version"],
        "attempt_count": row["attempt_count"],
        "max_attempts": row["max_attempts"],
        "output": _decoded(row["output_json"], {}),
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _event_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["payload"] = _decoded(result.pop("payload_json", "{}"), {})
    return result


def _decision_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["options"] = _decoded(result.pop("options_json", "[]"), [])
    result["answer"] = _decoded(result.pop("answer_json", None), None)
    return result


def _insert_event(
    conn: sqlite3.Connection,
    run_id: str,
    event_type: str,
    summary: str,
    *,
    step_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    from .research_data import assert_safe_research_payload

    assert_safe_research_payload(summary)
    assert_safe_research_payload(payload or {})
    cursor = conn.execute(
        """
        INSERT INTO research_events(run_id, step_id, event_type, summary, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, step_id, event_type, summary[:500], _json(payload or {})),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("research event insert did not return an id")
    return int(cursor.lastrowid)


def create_harness_run(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    title: str,
    goal: str,
    thread_id: str | None = None,
) -> dict[str, Any]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        run_id = insert_harness_run(
            conn,
            user_id=user_id,
            title=title,
            goal=goal,
            thread_id=thread_id,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_run_snapshot(conn, run_id, user_id)


def insert_harness_run(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    title: str,
    goal: str,
    thread_id: str | None = None,
    run_id: str | None = None,
) -> str:
    """Insert a Harness and its initial event inside the caller's transaction."""

    if thread_id is not None:
        owner = conn.execute(
            "SELECT 1 FROM chat_threads WHERE id = ? AND user_id = ?",
            (thread_id, user_id),
        ).fetchone()
        if owner is None:
            raise ResearchNotFoundError("conversation not found")
    run_id = run_id or str(uuid.uuid4())
    steps: tuple[tuple[str, str, str, str, list[str]], ...] = (
        ("normalize", "harness.normalize", "规范化任务", "Harness", []),
        ("plan", "harness.plan", "创建骨架计划", "Harness", ["normalize"]),
        ("finalize", "harness.finalize", "确认 Harness 就绪", "Harness", ["plan"]),
    )
    conn.execute(
        """
        INSERT INTO research_runs(id, user_id, thread_id, title, goal, budget_json, usage_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            user_id,
            thread_id,
            title,
            goal,
            _json({"kind": "harness", "external_calls": 0}),
            _json({"external_calls": 0}),
        ),
    )
    for position, (key, step_type, step_title, agent, dependencies) in enumerate(steps):
        conn.execute(
            """
            INSERT INTO research_steps(
                id, run_id, step_key, step_type, title, agent_name, position,
                depends_on_json, input_json, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                run_id,
                key,
                step_type,
                step_title,
                agent,
                position,
                _json(dependencies),
                _json({"goal": goal} if position == 0 else {}),
                f"harness:{key}:v1",
            ),
        )
    _insert_event(
        conn,
        run_id,
        "run.created",
        "Research Harness 已创建",
        payload={"mode": "harness", "external_calls": 0},
    )
    return run_id


def insert_topic_research_run(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    title: str,
    goal: str,
    thread_id: str,
    run_id: str | None = None,
) -> str:
    """Insert a real topic-research workflow inside the caller's transaction."""

    owner = conn.execute(
        "SELECT 1 FROM chat_threads WHERE id = ? AND user_id = ? AND paper_id IS NULL",
        (thread_id, user_id),
    ).fetchone()
    if owner is None:
        raise ResearchNotFoundError("conversation not found")
    from .research_data import DEFAULT_TOPIC_BUDGET, DEFAULT_TOPIC_USAGE

    run_id = run_id or str(uuid.uuid4())
    steps: tuple[tuple[str, str, str, str, list[str], int], ...] = (
        ("brief", "topic.brief", "理解研究目标", "研究任务整理", [], 1),
        ("query_planning", "topic.query_planning", "制定检索计划", "检索规划", ["brief"], 1),
        ("local_search", "topic.local_search", "检索本地论文库", "本地论文检索", ["query_planning"], 2),
        ("arxiv_search", "topic.arxiv_search", "搜索 arXiv 候选", "arXiv 检索", ["query_planning"], 3),
        ("dedup_import", "topic.dedup_import", "去重并导入候选", "论文导入", ["local_search", "arxiv_search"], 2),
        ("screening", "topic.screening", "筛选候选论文", "候选论文筛选", ["dedup_import"], 2),
        ("fulltext_acquisition", "topic.fulltext", "获取并解析全文", "全文准备", ["screening"], 3),
        ("reading", "topic.reading", "检索正文与定位证据", "正文证据检索", ["fulltext_acquisition"], 2),
        ("extraction", "topic.extraction", "抽取结构化阅读卡", "论文阅读卡抽取", ["reading"], 2),
        ("finalize_dataset", "topic.finalize", "完成调研数据集", "调研数据整理", ["extraction"], 1),
        ("synthesis_planning", "topic.synthesis_planning", "制定综合计划", "综合计划生成", ["finalize_dataset"], 1),
        ("comparison_matrix", "topic.comparison_matrix", "构建论文对比矩阵", "论文对比矩阵生成", ["synthesis_planning"], 1),
        ("cross_paper_claims", "topic.cross_paper_claims", "分析跨论文主张与分歧", "跨论文综合", ["comparison_matrix"], 1),
        ("citation_registry", "topic.citation_registry", "登记 Run 引用证据", "引用登记", ["cross_paper_claims"], 1),
        ("citation_verification", "topic.citation_verification", "严格校验引用", "引用校验", ["citation_registry"], 1),
        ("report_generation", "topic.report_generation", "生成可追溯研究报告", "研究报告生成", ["citation_verification"], 1),
        ("finalize_cited_report", "topic.finalize_cited_report", "完成引用报告", "引用报告整理", ["report_generation"], 1),
    )
    conn.execute(
        """
        INSERT INTO research_runs(
            id, user_id, thread_id, title, goal, mode, budget_json, usage_json
        ) VALUES (?, ?, ?, ?, ?, 'topic', ?, ?)
        """,
        (run_id, user_id, thread_id, title, goal, _json(DEFAULT_TOPIC_BUDGET), _json(DEFAULT_TOPIC_USAGE)),
    )
    for position, (key, step_type, step_title, agent, dependencies, max_attempts) in enumerate(steps):
        conn.execute(
            """
            INSERT INTO research_steps(
                id, run_id, step_key, step_type, title, agent_name, position,
                depends_on_json, input_json, max_attempts, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                run_id,
                key,
                step_type,
                step_title,
                agent,
                position,
                _json(dependencies),
                _json({"goal": goal} if key == "brief" else {}),
                max_attempts,
                f"topic:{key}:v1",
            ),
        )
    _insert_event(
        conn,
        run_id,
        "run.created",
        "主题调研任务已创建",
        payload={"mode": "topic", "step_count": len(steps)},
    )
    return run_id


def list_runs(conn: sqlite3.Connection, user_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM research_runs
        WHERE user_id = ?
        ORDER BY updated_at DESC, created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [_run_row(row) for row in rows]


def _owned_run(conn: sqlite3.Connection, run_id: str, user_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM research_runs WHERE id = ? AND user_id = ?",
        (run_id, user_id),
    ).fetchone()
    if row is None:
        raise ResearchNotFoundError("research run not found")
    return cast(sqlite3.Row, row)


def get_run_snapshot(conn: sqlite3.Connection, run_id: str, user_id: int) -> dict[str, Any]:
    conn.execute("BEGIN")
    try:
        run = _owned_run(conn, run_id, user_id)
        steps = conn.execute(
            "SELECT * FROM research_steps WHERE run_id = ? ORDER BY position, created_at",
            (run_id,),
        ).fetchall()
        decisions = conn.execute(
            """
            SELECT d.* FROM research_decisions d
            JOIN research_runs r ON r.id = d.run_id
            WHERE d.run_id = ? AND r.user_id = ?
            ORDER BY d.created_at
            """,
            (run_id, user_id),
        ).fetchall()
        latest = conn.execute(
            """
            SELECT COALESCE(MAX(e.id), 0) AS latest_event_id
            FROM research_events e JOIN research_runs r ON r.id = e.run_id
            WHERE e.run_id = ? AND r.user_id = ?
            """,
            (run_id, user_id),
        ).fetchone()
        result = _run_row(run)
        public_steps = [_public_step_row(row) for row in steps]
        for step in public_steps:
            output = step["output"]
            evidence_refs = output.get("evidence_refs") if isinstance(output, dict) else None
            if isinstance(evidence_refs, dict):
                output["evidence_refs"] = {
                    paper_id: refs
                    for paper_id, refs in evidence_refs.items()
                    if str(paper_id).isdigit()
                    and paper_is_accessible(conn, int(paper_id), user_id)
                }
        result["steps"] = public_steps
        result["decisions"] = [_decision_row(row) for row in decisions]
        result["latest_event_id"] = int(latest["latest_event_id"] if latest else 0)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def list_events(
    conn: sqlite3.Connection,
    run_id: str,
    user_id: int,
    *,
    after_id: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _owned_run(conn, run_id, user_id)
    rows = conn.execute(
        """
        SELECT e.* FROM research_events e
        JOIN research_runs r ON r.id = e.run_id
        WHERE e.run_id = ? AND r.user_id = ? AND e.id > ?
        ORDER BY e.id ASC LIMIT ?
        """,
        (run_id, user_id, after_id, limit),
    ).fetchall()
    events = [_event_row(row) for row in rows]
    for event in events:
        payload = event.get("payload", {})
        paper_id = payload.get("paper_id") if isinstance(payload, dict) else None
        if isinstance(paper_id, int) and not paper_is_accessible(conn, paper_id, user_id):
            event["payload"] = {"paper_withdrawn": True}
    return events


def request_action(
    conn: sqlite3.Connection,
    run_id: str,
    user_id: int,
    action: str,
) -> dict[str, Any]:
    if action not in {"pause", "cancel"}:
        raise ValueError("unsupported requested action")
    conn.execute("BEGIN IMMEDIATE")
    try:
        run = _owned_run(conn, run_id, user_id)
        if str(run["status"]) in TERMINAL_RUN_STATUSES:
            raise ResearchConflictError("research run is already terminal")
        if action == "pause" and str(run["status"]) not in {"queued", "running"}:
            raise ResearchConflictError("only a queued or running run can be paused")
        if action == "pause" and (
            str(run["status"]) == "cancelling" or str(run["requested_action"] or "") == "cancel"
        ):
            raise ResearchConflictError("a cancelling run cannot be paused")
        next_status = "cancelling" if action == "cancel" else str(run["status"])
        cursor = conn.execute(
            f"""
            UPDATE research_runs
            SET requested_action = ?, status = ?, state_version = state_version + 1,
                updated_at = {_NOW}
            WHERE id = ? AND user_id = ? AND state_version = ?
            """,
            (action, next_status, run_id, user_id, int(run["state_version"])),
        )
        if cursor.rowcount != 1:
            raise ResearchConflictError("research run changed; retry the request")
        _insert_event(
            conn,
            run_id,
            f"run.{action}_requested",
            "已请求安全暂停" if action == "pause" else "已请求安全取消",
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_run_snapshot(conn, run_id, user_id)


def resume_run(conn: sqlite3.Connection, run_id: str, user_id: int) -> dict[str, Any]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        run = _owned_run(conn, run_id, user_id)
        if str(run["status"]) != "paused":
            raise ResearchConflictError("only a paused run can resume")
        conn.execute(
            f"""
            UPDATE research_steps SET status = 'queued', updated_at = {_NOW}
            WHERE run_id = ? AND status = 'paused'
            """,
            (run_id,),
        )
        cursor = conn.execute(
            f"""
            UPDATE research_runs
            SET status = 'queued', requested_action = NULL,
                state_version = state_version + 1, updated_at = {_NOW}
            WHERE id = ? AND user_id = ? AND state_version = ?
            """,
            (run_id, user_id, int(run["state_version"])),
        )
        if cursor.rowcount != 1:
            raise ResearchConflictError("research run changed; retry the request")
        _insert_event(
            conn,
            run_id,
            "run.resumed",
            "主题调研已继续" if str(run["mode"]) == "topic" else "Research Harness 已继续",
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_run_snapshot(conn, run_id, user_id)


def retry_run(conn: sqlite3.Connection, run_id: str, user_id: int) -> dict[str, Any]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        run = _owned_run(conn, run_id, user_id)
        if str(run["status"]) != "failed":
            raise ResearchConflictError("only a failed run can retry")
        retry_generation = uuid.uuid4().hex
        conn.execute(
            f"""
            UPDATE research_steps
            SET status = 'queued', output_json = '{{}}', lease_owner = NULL,
                lease_expires_at = NULL, heartbeat_at = NULL, completed_at = NULL,
                max_attempts = max_attempts + 1,
                idempotency_key = idempotency_key || ':manual:' || ?,
                updated_at = {_NOW}
            WHERE run_id = ? AND status = 'failed'
            """,
            (retry_generation, run_id),
        )
        cursor = conn.execute(
            f"""
            UPDATE research_runs
            SET status = 'queued', requested_action = NULL, error_code = NULL,
                error_message = NULL, completed_at = NULL,
                state_version = state_version + 1, updated_at = {_NOW}
            WHERE id = ? AND user_id = ? AND state_version = ?
            """,
            (run_id, user_id, int(run["state_version"])),
        )
        if cursor.rowcount != 1:
            raise ResearchConflictError("research run changed; retry the request")
        _insert_event(
            conn,
            run_id,
            "run.retried",
            "主题调研已从检查点重试" if str(run["mode"]) == "topic" else "Research Harness 已重试",
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_run_snapshot(conn, run_id, user_id)


def resolve_decision(
    conn: sqlite3.Connection,
    decision_id: str,
    user_id: int,
    option_id: str,
) -> dict[str, Any]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            """
            SELECT d.*, r.status AS run_status FROM research_decisions d
            JOIN research_runs r ON r.id = d.run_id
            WHERE d.id = ? AND r.user_id = ?
            """,
            (decision_id, user_id),
        ).fetchone()
        if row is None:
            raise ResearchNotFoundError("decision not found")
        if str(row["status"]) != "pending":
            raise ResearchConflictError("decision is already resolved")
        if str(row["run_status"]) != "waiting_input":
            raise ResearchConflictError("research run is not waiting for input")
        options = _decoded(str(row["options_json"]), [])
        valid_ids = {str(item.get("id")) for item in options if isinstance(item, dict)}
        if option_id not in valid_ids:
            raise ValueError("unknown decision option")
        selected_option = next(
            (item for item in options if isinstance(item, dict) and str(item.get("id")) == option_id),
            None,
        )
        if not isinstance(selected_option, dict):
            raise ValueError("unknown decision option")
        normalized_option = cast(dict[str, Any], selected_option)
        decision_action = "resume"
        selected_action = str(normalized_option.get("action", ""))
        if selected_action.startswith("project_"):
            from .projects import apply_project_coverage_decision

            decision_action = apply_project_coverage_decision(
                conn, decision_row=row, option=normalized_option
            )
        elif selected_action.startswith("coverage_"):
            from .research_data import apply_coverage_decision

            decision_action = apply_coverage_decision(conn, decision_row=row, option=normalized_option)
        elif normalized_option.get("action") is not None:
            # Local import avoids a repository module cycle while keeping the
            # state transition and budget mutation in this transaction.
            from .research_data import apply_budget_decision

            decision_action = apply_budget_decision(
                conn,
                decision_row=row,
                option=normalized_option,
            )
        cursor = conn.execute(
            f"""
            UPDATE research_decisions
            SET status = 'resolved', answer_json = ?, resolved_at = {_NOW}
            WHERE id = ? AND status = 'pending'
            """,
            (_json({"option_id": option_id}), decision_id),
        )
        if cursor.rowcount != 1:
            raise ResearchConflictError("decision changed; retry the request")
        run_id = str(row["run_id"])
        if decision_action in {"stop", "edit_project"}:
            conn.execute(
                f"""
                UPDATE research_steps
                SET status = 'cancelled', lease_owner = NULL, lease_expires_at = NULL,
                    heartbeat_at = NULL, completed_at = {_NOW}, updated_at = {_NOW}
                WHERE run_id = ? AND status IN ('queued', 'waiting_input', 'paused')
                """,
                (run_id,),
            )
            conn.execute(
                f"""
                UPDATE research_runs
                SET status = 'cancelled', requested_action = NULL,
                    state_version = state_version + 1, updated_at = {_NOW}, completed_at = {_NOW}
                WHERE id = ? AND user_id = ? AND status = 'waiting_input'
                """,
                (run_id, user_id),
            )
            _insert_event(
                conn,
                run_id,
                "run.cancelled",
                "项目分析已返回编辑" if decision_action == "edit_project" else "调研任务已按决策停止",
                step_id=str(row["step_id"]) if row["step_id"] else None,
                payload={"decision_id": decision_id, "option_id": option_id},
            )
            conn.commit()
            return get_run_snapshot(conn, run_id, user_id)
        if row["step_id"] is not None:
            step_cursor = conn.execute(
                f"""
                UPDATE research_steps
                SET status = 'queued', max_attempts = max_attempts + 1, updated_at = {_NOW}
                WHERE id = ? AND run_id = ? AND status = 'waiting_input'
                """,
                (row["step_id"], run_id),
            )
            if step_cursor.rowcount != 1:
                raise ResearchConflictError("decision step is not waiting for input")
        run_cursor = conn.execute(
            f"""
            UPDATE research_runs
            SET status = 'queued', requested_action = NULL,
                state_version = state_version + 1, updated_at = {_NOW}
            WHERE id = ? AND user_id = ? AND status = 'waiting_input'
            """,
            (run_id, user_id),
        )
        if run_cursor.rowcount != 1:
            raise ResearchConflictError("research run is not waiting for input")
        _insert_event(
            conn,
            run_id,
            "decision.resolved",
            "已记录关键决策",
            step_id=str(row["step_id"]) if row["step_id"] else None,
            payload={"decision_id": decision_id, "option_id": option_id},
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_run_snapshot(conn, str(row["run_id"]), user_id)


def reconcile_requested_actions(conn: sqlite3.Connection) -> int:
    conn.execute("BEGIN IMMEDIATE")
    changed = 0
    try:
        rows = conn.execute(
            """
            SELECT r.* FROM research_runs r
            WHERE r.requested_action IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM research_steps s
                  WHERE s.run_id = r.id AND s.status = 'running'
              )
            """
        ).fetchall()
        for row in rows:
            run_id = str(row["id"])
            action = str(row["requested_action"])
            status = "cancelled" if action == "cancel" else "paused"
            step_status = "cancelled" if action == "cancel" else "paused"
            if action == "cancel":
                conn.execute(
                    f"""
                    UPDATE research_steps SET status = 'cancelled', updated_at = {_NOW},
                        completed_at = {_NOW}
                    WHERE run_id = ? AND status IN ('queued', 'paused', 'waiting_input')
                    """,
                    (run_id,),
                )
                conn.execute(
                    """
                    UPDATE research_decisions SET status = 'cancelled'
                    WHERE run_id = ? AND status = 'pending'
                    """,
                    (run_id,),
                )
            else:
                conn.execute(
                    f"""
                    UPDATE research_steps SET status = 'paused', updated_at = {_NOW}
                    WHERE run_id = ? AND status = 'queued'
                    """,
                    (run_id,),
                )
            conn.execute(
                f"""
                UPDATE research_runs SET status = ?, requested_action = NULL,
                    state_version = state_version + 1, updated_at = {_NOW},
                    completed_at = CASE WHEN ? = 'cancelled' THEN {_NOW} ELSE completed_at END
                WHERE id = ?
                """,
                (status, status, run_id),
            )
            _insert_event(conn, run_id, f"run.{status}", f"Research Harness 已{'取消' if status == 'cancelled' else '暂停'}")
            changed += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return changed


def recover_expired_leases(conn: sqlite3.Connection) -> int:
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = conn.execute(
            f"""
            SELECT id, run_id FROM research_steps
            WHERE status = 'running' AND lease_expires_at IS NOT NULL
              AND lease_expires_at <= {_NOW}
            """
        ).fetchall()
        for row in rows:
            conn.execute(
                f"""
                UPDATE research_steps
                SET status = 'queued', lease_owner = NULL, lease_expires_at = NULL,
                    heartbeat_at = NULL, max_attempts = max_attempts + 1, updated_at = {_NOW}
                WHERE id = ? AND status = 'running' AND lease_expires_at <= {_NOW}
                """,
                (row["id"],),
            )
            _insert_event(
                conn,
                str(row["run_id"]),
                "step.lease_recovered",
                "过期任务已回收",
                step_id=str(row["id"]),
            )
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise


def claim_next_step(
    conn: sqlite3.Connection,
    *,
    worker_id: str,
    lease_seconds: int,
) -> dict[str, Any] | None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            """
            SELECT s.* FROM research_steps s
            JOIN research_runs r ON r.id = s.run_id
            WHERE s.status = 'queued'
              AND s.attempt_count < s.max_attempts
              AND r.status IN ('queued', 'running')
              AND r.requested_action IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM json_each(s.depends_on_json) dependency
                  LEFT JOIN research_steps prior
                    ON prior.run_id = s.run_id
                   AND prior.plan_version = s.plan_version
                   AND prior.step_key = dependency.value
                  WHERE prior.id IS NULL OR prior.status != 'completed'
              )
            ORDER BY r.created_at, s.position
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        step_id = str(row["id"])
        generation = int(row["lease_generation"]) + 1
        cursor = conn.execute(
            f"""
            UPDATE research_steps
            SET status = 'running', attempt_count = attempt_count + 1,
                lease_owner = ?, lease_generation = ?, heartbeat_at = {_NOW},
                lease_expires_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?),
                started_at = COALESCE(started_at, {_NOW}), updated_at = {_NOW}
            WHERE id = ? AND status = 'queued' AND lease_generation = ?
            """,
            (worker_id, generation, f"+{lease_seconds} seconds", step_id, int(row["lease_generation"])),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return None
        run_id = str(row["run_id"])
        conn.execute(
            f"""
            UPDATE research_runs
            SET status = 'running', started_at = COALESCE(started_at, {_NOW}),
                state_version = state_version + 1, updated_at = {_NOW}
            WHERE id = ? AND status = 'queued' AND requested_action IS NULL
            """,
            (run_id,),
        )
        _insert_event(
            conn,
            run_id,
            "step.started",
            f"{row['title']} 已开始",
            step_id=step_id,
            payload={"step_key": row["step_key"], "attempt": int(row["attempt_count"]) + 1},
        )
        conn.commit()
        result = _step_row(row)
        result["status"] = "running"
        result["attempt_count"] = int(row["attempt_count"]) + 1
        result["lease_owner"] = worker_id
        result["lease_generation"] = generation
        return result
    except Exception:
        conn.rollback()
        raise


def heartbeat_step(
    conn: sqlite3.Connection,
    *,
    step_id: str,
    worker_id: str,
    lease_generation: int,
    lease_seconds: int,
) -> bool:
    cursor = conn.execute(
        f"""
        UPDATE research_steps
        SET heartbeat_at = {_NOW},
            lease_expires_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?),
            updated_at = {_NOW}
        WHERE id = ? AND status = 'running' AND lease_owner = ? AND lease_generation = ?
          AND lease_expires_at > {_NOW}
        """,
        (f"+{lease_seconds} seconds", step_id, worker_id, lease_generation),
    )
    conn.commit()
    return cursor.rowcount == 1


def finish_step(
    conn: sqlite3.Connection,
    *,
    step_id: str,
    worker_id: str,
    lease_generation: int,
    output: dict[str, Any],
) -> bool:
    from .research_data import assert_safe_research_payload

    assert_safe_research_payload(output)
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            f"""
            SELECT s.*, r.requested_action, r.mode AS run_mode FROM research_steps s
            JOIN research_runs r ON r.id = s.run_id
            WHERE s.id = ? AND s.status = 'running' AND s.lease_owner = ?
              AND s.lease_generation = ? AND s.lease_expires_at > {_NOW}
            """,
            (step_id, worker_id, lease_generation),
        ).fetchone()
        if row is None:
            conn.rollback()
            return False
        if (
            str(row["status"]) != "running"
            or str(row["lease_owner"]) != worker_id
            or int(row["lease_generation"]) != lease_generation
        ):
            conn.rollback()
            return False
        run_id = str(row["run_id"])
        requested_action = row["requested_action"]
        if requested_action is not None:
            step_status = "cancelled" if requested_action == "cancel" else "paused"
            run_status = "cancelled" if requested_action == "cancel" else "paused"
            conn.execute(
                f"""
                UPDATE research_steps SET status = ?, lease_owner = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL, updated_at = {_NOW},
                    completed_at = CASE WHEN ? = 'cancelled' THEN {_NOW} ELSE completed_at END
                WHERE id = ? AND status = 'running' AND lease_owner = ? AND lease_generation = ?
                  AND lease_expires_at > {_NOW}
                """,
                (step_status, step_status, step_id, worker_id, lease_generation),
            )
            conn.execute(
                f"""
                UPDATE research_steps SET status = ?, updated_at = {_NOW},
                    completed_at = CASE WHEN ? = 'cancelled' THEN {_NOW} ELSE completed_at END
                WHERE run_id = ? AND status = 'queued'
                """,
                (step_status, step_status, run_id),
            )
            if requested_action == "cancel":
                conn.execute(
                    """
                    UPDATE research_decisions SET status = 'cancelled'
                    WHERE run_id = ? AND status = 'pending'
                    """,
                    (run_id,),
                )
            conn.execute(
                f"""
                UPDATE research_runs SET status = ?, requested_action = NULL,
                    state_version = state_version + 1, updated_at = {_NOW},
                    completed_at = CASE WHEN ? = 'cancelled' THEN {_NOW} ELSE completed_at END
                WHERE id = ?
                """,
                (run_status, run_status, run_id),
            )
            _insert_event(
                conn,
                run_id,
                f"run.{run_status}",
                (
                    f"主题调研已{'取消' if run_status == 'cancelled' else '暂停'}"
                    if str(row["run_mode"]) == "topic"
                    else f"Research Harness 已{'取消' if run_status == 'cancelled' else '暂停'}"
                ),
                step_id=step_id,
            )
            conn.commit()
            return True
        cursor = conn.execute(
            f"""
            UPDATE research_steps
            SET status = 'completed', output_json = ?, lease_owner = NULL,
                lease_expires_at = NULL, heartbeat_at = NULL,
                completed_at = {_NOW}, updated_at = {_NOW}
            WHERE id = ? AND status = 'running' AND lease_owner = ? AND lease_generation = ?
              AND lease_expires_at > {_NOW}
            """,
            (_json(output), step_id, worker_id, lease_generation),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return False
        _insert_event(
            conn,
            run_id,
            "step.completed",
            f"{row['title']} 已完成",
            step_id=step_id,
            payload={
                "step_key": row["step_key"],
                "mode": str(row["run_mode"]),
                "scaffold_only": str(row["run_mode"]) == "harness",
            },
        )
        remaining = conn.execute(
            "SELECT COUNT(*) AS count FROM research_steps WHERE run_id = ? AND status != 'completed'",
            (run_id,),
        ).fetchone()
        if remaining is not None and int(remaining["count"]) == 0:
            conn.execute(
                f"""
                UPDATE research_runs
                SET status = 'completed', state_version = state_version + 1,
                    updated_at = {_NOW}, completed_at = {_NOW}
                WHERE id = ? AND requested_action IS NULL
                """,
                (run_id,),
            )
            _insert_event(
                conn,
                run_id,
                "run.completed",
                "Research Harness 骨架流程已完成"
                if str(row["run_mode"]) == "harness"
                else "主题调研数据集已完成",
                payload={
                    "mode": str(row["run_mode"]),
                    "scaffold_only": str(row["run_mode"]) == "harness",
                },
            )
        else:
            conn.execute(
                f"UPDATE research_runs SET state_version = state_version + 1, updated_at = {_NOW} WHERE id = ?",
                (run_id,),
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def fail_step(
    conn: sqlite3.Connection,
    *,
    step_id: str,
    worker_id: str,
    lease_generation: int,
    error_code: str,
    error_message: str,
) -> bool:
    # Provider bodies, local paths and credentials must not become durable
    # Research state. Keep the public failure useful without echoing the cause.
    del error_message
    public_messages = {
        "llm_configuration_unavailable": "主题调研需要真实模型配置；当前 LLM_API_KEY 未配置。",
        "structured_model_output_invalid": "模型输出未通过严格结构校验，未写入调研数据。",
        "tool_timeout": "研究工具执行超时，可从检查点重试。",
        "research_dataset_empty": "没有有效 Paper Brief，不能完成调研数据集。",
    }
    safe_message = public_messages.get(
        error_code,
        "Research step failed; retry the run or inspect the safe error code.",
    )
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            f"""
            SELECT s.run_id, s.title, r.requested_action, r.mode AS run_mode
            FROM research_steps s JOIN research_runs r ON r.id = s.run_id
            WHERE s.id = ? AND s.status = 'running' AND s.lease_owner = ?
              AND s.lease_generation = ? AND s.lease_expires_at > {_NOW}
            """,
            (step_id, worker_id, lease_generation),
        ).fetchone()
        if row is None:
            conn.rollback()
            return False
        if row["requested_action"] is not None:
            requested_action = str(row["requested_action"])
            step_status = "cancelled" if requested_action == "cancel" else "paused"
            run_status = "cancelled" if requested_action == "cancel" else "paused"
            cursor = conn.execute(
                f"""
                UPDATE research_steps SET status = ?, lease_owner = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL, updated_at = {_NOW},
                    completed_at = CASE WHEN ? = 'cancelled' THEN {_NOW} ELSE completed_at END
                WHERE id = ? AND status = 'running' AND lease_owner = ? AND lease_generation = ?
                  AND lease_expires_at > {_NOW}
                """,
                (step_status, step_status, step_id, worker_id, lease_generation),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return False
            run_id = str(row["run_id"])
            conn.execute(
                f"""
                UPDATE research_steps SET status = ?, updated_at = {_NOW},
                    completed_at = CASE WHEN ? = 'cancelled' THEN {_NOW} ELSE completed_at END
                WHERE run_id = ? AND status = 'queued'
                """,
                (step_status, step_status, run_id),
            )
            if requested_action == "cancel":
                conn.execute(
                    """
                    UPDATE research_decisions SET status = 'cancelled'
                    WHERE run_id = ? AND status = 'pending'
                    """,
                    (run_id,),
                )
            conn.execute(
                f"""
                UPDATE research_runs SET status = ?, requested_action = NULL,
                    state_version = state_version + 1, updated_at = {_NOW},
                    completed_at = CASE WHEN ? = 'cancelled' THEN {_NOW} ELSE completed_at END
                WHERE id = ?
                """,
                (run_status, run_status, run_id),
            )
            _insert_event(
                conn,
                run_id,
                f"run.{run_status}",
                (
                    f"主题调研已{'取消' if run_status == 'cancelled' else '暂停'}"
                    if str(row["run_mode"]) == "topic"
                    else f"Research Harness 已{'取消' if run_status == 'cancelled' else '暂停'}"
                ),
                step_id=step_id,
            )
            conn.commit()
            return True
        cursor = conn.execute(
            f"""
            UPDATE research_steps SET status = 'failed', lease_owner = NULL,
                lease_expires_at = NULL, heartbeat_at = NULL, completed_at = {_NOW},
                updated_at = {_NOW}
            WHERE id = ? AND status = 'running' AND lease_owner = ? AND lease_generation = ?
              AND lease_expires_at > {_NOW}
            """,
            (step_id, worker_id, lease_generation),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return False
        run_id = str(row["run_id"])
        conn.execute(
            f"""
            UPDATE research_runs SET status = 'failed', error_code = ?, error_message = ?,
                state_version = state_version + 1, updated_at = {_NOW}, completed_at = {_NOW}
            WHERE id = ?
            """,
            (error_code[:80], safe_message, run_id),
        )
        _insert_event(
            conn,
            run_id,
            "run.failed",
            f"{row['title']} 执行失败",
            step_id=step_id,
            payload={"error_code": error_code[:80]},
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise

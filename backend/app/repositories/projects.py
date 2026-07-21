from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from typing import Any, cast

from .research import (
    ResearchConflictError,
    ResearchNotFoundError,
    get_run_snapshot,
)
from .research_citations import _citation_status, _evidence_status
from .research_data import (
    _active_lease,
    _artifact_integrity_valid,
    _artifact_is_current,
    _artifact_row,
    assert_safe_research_payload,
)
from .uploads import paper_is_accessible


_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
_HASH = re.compile(r"^[0-9a-f]{64}$")
PROJECT_ARTIFACT_TYPES = {
    "research_landscape_plan",
    "topic_clusters",
    "research_timeline",
    "research_graph",
    "project_analysis_validation",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _decoded(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _owned_project(
    conn: sqlite3.Connection,
    project_id: str,
    user_id: int,
    *,
    writable: bool = False,
) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM research_projects WHERE id = ? AND owner_user_id = ?",
        (project_id, user_id),
    ).fetchone()
    if row is None:
        raise ResearchNotFoundError("research project not found")
    if writable and str(row["status"]) != "active":
        raise ResearchConflictError("archived research project is read-only")
    return cast(sqlite3.Row, row)


def _project_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "owner_user_id": int(row["owner_user_id"]),
        "title": str(row["title"]),
        "description": str(row["description"]),
        "status": str(row["status"]),
        "items_revision": int(row["items_revision"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _validate_project_text(title: str, description: str) -> tuple[str, str]:
    clean_title = title.strip()
    clean_description = description.strip()
    if not 1 <= len(clean_title) <= 200:
        raise ValueError("project title must contain 1 to 200 characters")
    if len(clean_description) > 4_000:
        raise ValueError("project description must not exceed 4000 characters")
    return clean_title, clean_description


def create_project(
    conn: sqlite3.Connection,
    user_id: int,
    title: str,
    description: str = "",
) -> dict[str, Any]:
    clean_title, clean_description = _validate_project_text(title, description)
    project_id = str(uuid.uuid4())
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            INSERT INTO research_projects(id, owner_user_id, title, description)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, user_id, clean_title, clean_description),
        )
        row = conn.execute(
            "SELECT * FROM research_projects WHERE id = ?", (project_id,)
        ).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if row is None:
        raise RuntimeError("research project disappeared")
    return {**_project_payload(row), "items": []}


def list_projects(
    conn: sqlite3.Connection,
    user_id: int,
    status: str | None = None,
) -> list[dict[str, Any]]:
    if status is not None and status not in {"active", "archived"}:
        raise ValueError("unsupported project status")
    where = "owner_user_id = ?"
    params: list[Any] = [user_id]
    if status is not None:
        where += " AND status = ?"
        params.append(status)
    rows = conn.execute(
        f"SELECT * FROM research_projects WHERE {where} ORDER BY updated_at DESC, created_at DESC",
        tuple(params),
    ).fetchall()
    return [_project_payload(row) for row in rows]


def get_project(
    conn: sqlite3.Connection,
    project_id: str,
    user_id: int,
    include_items: bool = True,
) -> dict[str, Any]:
    row = _owned_project(conn, project_id, user_id)
    result = _project_payload(row)
    if include_items:
        result["items"] = list_project_items(conn, project_id, user_id)
    return result


def update_project(
    conn: sqlite3.Connection,
    project_id: str,
    user_id: int,
    *,
    title: str,
    description: str,
) -> dict[str, Any]:
    clean_title, clean_description = _validate_project_text(title, description)
    conn.execute("BEGIN IMMEDIATE")
    try:
        _owned_project(conn, project_id, user_id, writable=True)
        conn.execute(
            f"UPDATE research_projects SET title = ?, description = ?, "
            f"items_revision = items_revision + 1, updated_at = {_NOW} WHERE id = ?",
            (clean_title, clean_description, project_id),
        )
        _fence_active_project_analysis(conn, project_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_project(conn, project_id, user_id)


def set_project_status(
    conn: sqlite3.Connection,
    project_id: str,
    user_id: int,
    status: str,
) -> dict[str, Any]:
    if status not in {"active", "archived"}:
        raise ValueError("unsupported project status")
    conn.execute("BEGIN IMMEDIATE")
    try:
        project = _owned_project(conn, project_id, user_id)
        if str(project["status"]) != status:
            conn.execute(
                f"UPDATE research_projects SET status = ?, items_revision = items_revision + 1, updated_at = {_NOW} WHERE id = ?",
                (status, project_id),
            )
            if status == "archived":
                _fence_active_project_analysis(conn, project_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_project(conn, project_id, user_id)


def delete_project(conn: sqlite3.Connection, project_id: str, user_id: int) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        project = _owned_project(conn, project_id, user_id)
        if str(project["status"]) != "archived":
            raise ResearchConflictError("research project must be archived before deletion")
        # Membership is removed explicitly. Only project-owned analysis runs and
        # their derived artifacts are removed; source Runs/Papers/Reports remain.
        conn.execute("DELETE FROM research_project_items WHERE project_id = ?", (project_id,))
        # Dependency rows deliberately RESTRICT deletion of their upstream
        # artifacts. Project deletion is the one explicit owner operation that
        # removes the whole project-local DAG, so detach those project-local
        # ledger rows before deleting the owning analysis runs.
        conn.execute(
            """
            DELETE FROM research_artifact_dependencies
            WHERE artifact_id IN (
                SELECT id FROM research_artifacts WHERE project_id = ?
            )
            """,
            (project_id,),
        )
        conn.execute(
            "DELETE FROM research_runs WHERE project_id = ? AND mode = 'project'",
            (project_id,),
        )
        cursor = conn.execute(
            "DELETE FROM research_projects WHERE id = ? AND owner_user_id = ?",
            (project_id, user_id),
        )
        if cursor.rowcount != 1:
            raise ResearchConflictError("research project changed during deletion")
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ResearchConflictError("research project is still referenced") from exc
    except Exception:
        conn.rollback()
        raise


def _fence_active_project_analysis(
    conn: sqlite3.Connection, project_id: str
) -> None:
    """Invalidate every outstanding project lease inside the caller transaction."""
    conn.execute(
        f"""
        UPDATE research_runs
        SET requested_action = 'cancel', status = 'cancelling',
            state_version = state_version + 1, updated_at = {_NOW}
        WHERE project_id = ? AND mode = 'project'
          AND status IN ('queued', 'running', 'waiting_input', 'paused')
        """,
        (project_id,),
    )


def _paper_snapshot(
    conn: sqlite3.Connection, paper_id: int, user_id: int
) -> tuple[str, dict[str, Any]]:
    if not paper_is_accessible(conn, paper_id, user_id):
        raise ResearchNotFoundError("research paper not found")
    row = conn.execute(
        """
        SELECT p.id, p.source, p.source_id, p.title, p.authors_json, p.abstract,
               p.published_at, p.updated_at, p.asset_id, p.processing_status,
               d.source_hash AS document_hash, d.status AS document_status
        FROM papers p LEFT JOIN paper_documents d ON d.paper_id = p.id
        WHERE p.id = ?
        """,
        (paper_id,),
    ).fetchone()
    if row is None:
        raise ResearchNotFoundError("research paper not found")
    metadata = {
        "paper_id": paper_id,
        "source": str(row["source"]),
        "source_id": str(row["source_id"]),
        "title": str(row["title"]),
        "authors": _decoded(str(row["authors_json"]), []),
        "abstract": str(row["abstract"]),
        "published_at": str(row["published_at"]),
        "updated_at": str(row["updated_at"] or ""),
    }
    metadata_hash = _digest(metadata)
    asset_hash = str(row["asset_id"] or "").removeprefix("sha256:")
    document_hash = str(row["document_hash"] or "")
    current_hash = (
        asset_hash
        if _HASH.fullmatch(asset_hash)
        and asset_hash == document_hash
        and str(row["document_status"] or "") == "completed"
        else metadata_hash
    )
    return current_hash, {
        **metadata,
        "metadata_hash": metadata_hash,
        "source_hash": current_hash,
        "processing_status": str(row["processing_status"]),
    }


def _run_snapshot(
    conn: sqlite3.Connection, run_id: str, user_id: int
) -> tuple[str, dict[str, Any]]:
    row = conn.execute(
        """
        SELECT id, title, goal, mode, status, state_version, plan_version, updated_at
        FROM research_runs WHERE id = ? AND user_id = ?
        """,
        (run_id, user_id),
    ).fetchone()
    if row is None:
        raise ResearchNotFoundError("research run not found")
    latest_artifacts = conn.execute(
        """
        SELECT a.artifact_type, a.id, a.version, a.status, a.content_hash,
               a.paper_id, a.source_hash
        FROM research_artifacts a
        JOIN (
            SELECT artifact_type, MAX(version) AS version
            FROM research_artifacts WHERE run_id = ? GROUP BY artifact_type
        ) latest ON latest.artifact_type = a.artifact_type
                AND latest.version = a.version
        WHERE a.run_id = ?
        ORDER BY a.artifact_type
        """,
        (run_id, run_id),
    ).fetchall()
    versions = {
        str(item["artifact_type"]): {
            "artifact_id": str(item["id"]),
            "version": int(item["version"]),
            "status": str(item["status"]),
            "content_hash": str(item["content_hash"]),
            "paper_id": int(item["paper_id"]) if item["paper_id"] is not None else None,
            "source_hash": str(item["source_hash"] or ""),
        }
        for item in latest_artifacts
    }
    run_papers: list[dict[str, Any]] = []
    for relation in conn.execute(
        "SELECT paper_id, stage, source_hash FROM research_run_papers WHERE run_id = ? ORDER BY paper_id",
        (run_id,),
    ).fetchall():
        paper_id = int(relation["paper_id"])
        try:
            paper_hash, _ = _paper_snapshot(conn, paper_id, user_id)
            paper_status = "valid"
        except ResearchNotFoundError:
            paper_hash = ""
            paper_status = "inaccessible"
        run_papers.append(
            {
                "paper_id": paper_id,
                "stage": str(relation["stage"]),
                "relation_source_hash": str(relation["source_hash"] or ""),
                "current_source_hash": paper_hash,
                "status": paper_status,
            }
        )
    snapshot = {
        "run_id": run_id,
        "title": str(row["title"]),
        "goal": str(row["goal"]),
        "mode": str(row["mode"]),
        "status": str(row["status"]),
        "state_version": int(row["state_version"]),
        "plan_version": int(row["plan_version"]),
        "artifact_versions": versions,
        "papers": run_papers,
    }
    return _digest(snapshot), snapshot


def _report_snapshot(
    conn: sqlite3.Connection,
    artifact_id: str,
    artifact_version: int,
    user_id: int,
) -> tuple[str, dict[str, Any]]:
    row = conn.execute(
        """
        SELECT a.*, r.user_id FROM research_artifacts a
        JOIN research_runs r ON r.id = a.run_id
        WHERE a.id = ? AND a.version = ? AND a.artifact_type = 'research_report'
          AND r.user_id = ?
        """,
        (artifact_id, artifact_version, user_id),
    ).fetchone()
    if row is None or not _artifact_integrity_valid(row):
        raise ResearchNotFoundError("research report not found")
    latest = conn.execute(
        """
        SELECT MAX(version) AS version FROM research_artifacts
        WHERE run_id = ? AND artifact_type = 'research_report' AND status = 'completed'
        """,
        (str(row["run_id"]),),
    ).fetchone()
    is_latest = latest is not None and int(latest["version"] or 0) == artifact_version
    content = cast(dict[str, Any], _decoded(str(row["content_json"]), {}))
    generated_versions = content.get("generated_from_artifact_versions", {})
    registry_version = (
        generated_versions.get("citation_registry")
        if isinstance(generated_versions, dict)
        else None
    )
    citation_statuses: list[str] = []
    if isinstance(registry_version, int):
        registry = conn.execute(
            """
            SELECT id FROM research_artifacts
            WHERE run_id = ? AND artifact_type = 'citation_registry' AND version = ?
            """,
            (str(row["run_id"]), registry_version),
        ).fetchone()
        if registry is None:
            citation_statuses.append("stale")
        else:
            citation_statuses = [
                _citation_status(conn, citation, user_id)
                for citation in conn.execute(
                    "SELECT * FROM research_citations WHERE artifact_id = ?",
                    (str(registry["id"]),),
                ).fetchall()
            ]
            if not citation_statuses:
                citation_statuses.append("stale")
    if "inaccessible" in citation_statuses:
        raise ResearchNotFoundError("research report not found")
    report_current = is_latest and _artifact_is_current(conn, row, user_id)
    snapshot = {
        "artifact_id": artifact_id,
        "artifact_version": artifact_version,
        "run_id": str(row["run_id"]),
        "content_hash": str(row["content_hash"]),
        "status": str(row["status"]),
        "is_latest": is_latest,
        "is_current": report_current,
        "citation_statuses": citation_statuses,
        "content": content,
    }
    return str(row["content_hash"]), snapshot


def _item_source_snapshot(
    conn: sqlite3.Connection,
    *,
    item_type: str,
    user_id: int,
    run_id: str | None,
    paper_id: int | None,
    artifact_id: str | None,
    artifact_version: int | None,
) -> tuple[str, dict[str, Any]]:
    if item_type == "run" and run_id and paper_id is None and artifact_id is None:
        return _run_snapshot(conn, run_id, user_id)
    if item_type == "paper" and paper_id and run_id is None and artifact_id is None:
        return _paper_snapshot(conn, paper_id, user_id)
    if (
        item_type == "research_report"
        and artifact_id
        and artifact_version is not None
        and run_id is None
        and paper_id is None
    ):
        return _report_snapshot(conn, artifact_id, artifact_version, user_id)
    raise ValueError("project item target does not match item_type")


def add_project_item(
    conn: sqlite3.Connection,
    project_id: str,
    user_id: int,
    item_type: str,
    run_id: str | None = None,
    paper_id: int | None = None,
    artifact_id: str | None = None,
    artifact_version: int | None = None,
) -> dict[str, Any]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        _owned_project(conn, project_id, user_id, writable=True)
        source_hash, _ = _item_source_snapshot(
            conn,
            item_type=item_type,
            user_id=user_id,
            run_id=run_id,
            paper_id=paper_id,
            artifact_id=artifact_id,
            artifact_version=artifact_version,
        )
        position_row = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS position FROM research_project_items WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        item_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO research_project_items(
                id, project_id, item_type, run_id, paper_id, artifact_id,
                artifact_version, source_hash_snapshot, position
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                project_id,
                item_type,
                run_id,
                paper_id,
                artifact_id,
                artifact_version,
                source_hash,
                int(position_row["position"] if position_row else 0),
            ),
        )
        conn.execute(
            f"""
            UPDATE research_projects
            SET items_revision = items_revision + 1, updated_at = {_NOW}
            WHERE id = ?
            """,
            (project_id,),
        )
        _fence_active_project_analysis(conn, project_id)
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ResearchConflictError("project item already exists or is invalid") from exc
    except Exception:
        conn.rollback()
        raise
    return next(
        item
        for item in list_project_items(conn, project_id, user_id)
        if item["id"] == item_id
    )


def _project_item_projection(
    conn: sqlite3.Connection, row: sqlite3.Row, user_id: int
) -> dict[str, Any]:
    item_id = str(row["id"])
    item_type = str(row["item_type"])
    try:
        current_hash, source = _item_source_snapshot(
            conn,
            item_type=item_type,
            user_id=user_id,
            run_id=str(row["run_id"]) if row["run_id"] is not None else None,
            paper_id=int(row["paper_id"]) if row["paper_id"] is not None else None,
            artifact_id=str(row["artifact_id"]) if row["artifact_id"] is not None else None,
            artifact_version=int(row["artifact_version"])
            if row["artifact_version"] is not None
            else None,
        )
    except ResearchNotFoundError:
        return {"id": item_id, "item_type": item_type, "status": "inaccessible"}
    status = (
        "valid"
        if current_hash == str(row["source_hash_snapshot"])
        and bool(source.get("is_latest", True))
        and bool(source.get("is_current", True))
        else "stale"
    )
    return {
        "id": item_id,
        "project_id": str(row["project_id"]),
        "item_type": item_type,
        "run_id": str(row["run_id"]) if row["run_id"] is not None else None,
        "paper_id": int(row["paper_id"]) if row["paper_id"] is not None else None,
        "artifact_id": str(row["artifact_id"]) if row["artifact_id"] is not None else None,
        "artifact_version": int(row["artifact_version"])
        if row["artifact_version"] is not None
        else None,
        "source_hash_snapshot": str(row["source_hash_snapshot"]),
        "position": int(row["position"]),
        "added_at": str(row["added_at"]),
        "updated_at": str(row["updated_at"]),
        "status": status,
        "source": source,
    }


def list_project_items(
    conn: sqlite3.Connection, project_id: str, user_id: int
) -> list[dict[str, Any]]:
    _owned_project(conn, project_id, user_id)
    rows = conn.execute(
        "SELECT * FROM research_project_items WHERE project_id = ? ORDER BY position, added_at, id",
        (project_id,),
    ).fetchall()
    return [_project_item_projection(conn, row, user_id) for row in rows]


def remove_project_item(
    conn: sqlite3.Connection, project_id: str, user_id: int, item_id: str
) -> dict[str, Any]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        _owned_project(conn, project_id, user_id, writable=True)
        cursor = conn.execute(
            "DELETE FROM research_project_items WHERE id = ? AND project_id = ?",
            (item_id, project_id),
        )
        if cursor.rowcount != 1:
            raise ResearchNotFoundError("research project item not found")
        rows = conn.execute(
            "SELECT id FROM research_project_items WHERE project_id = ? ORDER BY position, added_at, id",
            (project_id,),
        ).fetchall()
        for position, row in enumerate(rows):
            conn.execute(
                f"UPDATE research_project_items SET position = ?, updated_at = {_NOW} WHERE id = ?",
                (position, str(row["id"])),
            )
        conn.execute(
            f"UPDATE research_projects SET items_revision = items_revision + 1, updated_at = {_NOW} WHERE id = ?",
            (project_id,),
        )
        _fence_active_project_analysis(conn, project_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_project(conn, project_id, user_id)


def reorder_project_items(
    conn: sqlite3.Connection,
    project_id: str,
    user_id: int,
    ordered_item_ids: list[str],
) -> list[dict[str, Any]]:
    if len(ordered_item_ids) != len(set(ordered_item_ids)):
        raise ValueError("project item order contains duplicates")
    conn.execute("BEGIN IMMEDIATE")
    try:
        _owned_project(conn, project_id, user_id, writable=True)
        existing = {
            str(row["id"])
            for row in conn.execute(
                "SELECT id FROM research_project_items WHERE project_id = ?", (project_id,)
            ).fetchall()
        }
        if existing != set(ordered_item_ids):
            raise ResearchConflictError("project item order must include every current item")
        for position, item_id in enumerate(ordered_item_ids):
            conn.execute(
                f"UPDATE research_project_items SET position = ?, updated_at = {_NOW} WHERE id = ? AND project_id = ?",
                (position, item_id, project_id),
            )
        conn.execute(
            f"UPDATE research_projects SET items_revision = items_revision + 1, updated_at = {_NOW} WHERE id = ?",
            (project_id,),
        )
        _fence_active_project_analysis(conn, project_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return list_project_items(conn, project_id, user_id)


def validate_project_inputs(
    conn: sqlite3.Connection, project_id: str, user_id: int
) -> dict[str, Any]:
    project = _owned_project(conn, project_id, user_id)
    items = list_project_items(conn, project_id, user_id)
    valid = [item for item in items if item["status"] == "valid"]
    stale = [str(item["id"]) for item in items if item["status"] == "stale"]
    inaccessible = [str(item["id"]) for item in items if item["status"] == "inaccessible"]
    canonical = [
        {
            "id": item["id"],
            "item_type": item["item_type"],
            "status": item["status"],
            "source_hash_snapshot": item.get("source_hash_snapshot"),
            "position": item.get("position"),
        }
        for item in items
    ]
    fingerprint = _digest(
        {
            "project_id": project_id,
            "items_revision": int(project["items_revision"]),
            "items": canonical,
        }
    )
    unique_papers: set[int] = set()
    valid_citations: set[str] = set()
    for item in valid:
        if item["item_type"] == "paper" and item.get("paper_id") is not None:
            unique_papers.add(int(item["paper_id"]))
        elif item["item_type"] == "run" and item.get("run_id") is not None:
            for paper in conn.execute(
                "SELECT paper_id FROM research_run_papers WHERE run_id = ?",
                (str(item["run_id"]),),
            ).fetchall():
                paper_id = int(paper["paper_id"])
                if paper_is_accessible(conn, paper_id, user_id):
                    unique_papers.add(paper_id)
            for citation in conn.execute(
                "SELECT * FROM research_citations WHERE run_id = ?",
                (str(item["run_id"]),),
            ).fetchall():
                if _citation_status(conn, citation, user_id) == "valid":
                    valid_citations.add(str(citation["id"]))
                    unique_papers.add(int(citation["paper_id"]))
        elif item["item_type"] == "research_report":
            report = cast(dict[str, Any], item.get("source", {}))
            versions = cast(dict[str, Any], report.get("content", {})).get(
                "generated_from_artifact_versions", {}
            )
            registry_version = versions.get("citation_registry") if isinstance(versions, dict) else None
            if isinstance(registry_version, int):
                registry = conn.execute(
                    "SELECT id FROM research_artifacts WHERE run_id = ? AND artifact_type = 'citation_registry' AND version = ?",
                    (str(report.get("run_id", "")), registry_version),
                ).fetchone()
                if registry is not None:
                    for citation in conn.execute(
                        "SELECT * FROM research_citations WHERE artifact_id = ?",
                        (str(registry["id"]),),
                    ).fetchall():
                        if _citation_status(conn, citation, user_id) == "valid":
                            valid_citations.add(str(citation["id"]))
                            unique_papers.add(int(citation["paper_id"]))
    ready = len(unique_papers) >= 2 and len(valid_citations) >= 1
    counts = {
        "total": len(items),
        "valid": len(valid),
        "stale": len(stale),
        "inaccessible": len(inaccessible),
        "runs": sum(item["item_type"] == "run" for item in valid),
        "papers": sum(item["item_type"] == "paper" for item in valid),
        "reports": sum(item["item_type"] == "research_report" for item in valid),
        "unique_papers": len(unique_papers),
        "valid_citations": len(valid_citations),
        "ready": ready,
    }
    return {
        "project_id": project_id,
        "project_revision": int(project["items_revision"]),
        "input_fingerprint": fingerprint,
        "items": items,
        "coverage": counts,
        "stale_dependencies": stale,
        "inaccessible_dependencies": inaccessible,
        "can_analyze": ready,
        "can_generate_limited": len(valid) > 0,
    }


def get_latest_project_analysis(
    conn: sqlite3.Connection, project_id: str, user_id: int
) -> dict[str, Any] | None:
    _owned_project(conn, project_id, user_id)
    row = conn.execute(
        """
        SELECT id FROM research_runs
        WHERE project_id = ? AND user_id = ? AND mode = 'project'
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (project_id, user_id),
    ).fetchone()
    return get_run_snapshot(conn, str(row["id"]), user_id) if row is not None else None


def _report_claims_for_snapshot(
    conn: sqlite3.Connection, report: dict[str, Any], user_id: int
) -> list[dict[str, Any]]:
    content = cast(dict[str, Any], report.get("content", {}))
    versions = content.get("generated_from_artifact_versions", {})
    claims_version = versions.get("synthesis_claims") if isinstance(versions, dict) else None
    if not isinstance(claims_version, int):
        return []
    row = conn.execute(
        """
        SELECT a.* FROM research_artifacts a JOIN research_runs r ON r.id = a.run_id
        WHERE a.run_id = ? AND a.artifact_type = 'synthesis_claims'
          AND a.version = ? AND r.user_id = ?
        """,
        (str(report["run_id"]), claims_version, user_id),
    ).fetchone()
    if row is None or not _artifact_integrity_valid(row):
        return []
    claims = _decoded(str(row["content_json"]), {}).get("claims", [])
    return [item for item in claims if isinstance(item, dict)]


def _run_analysis_sources(
    conn: sqlite3.Connection, run_id: str, user_id: int
) -> dict[str, Any]:
    run_hash, run = _run_snapshot(conn, run_id, user_id)
    papers: list[dict[str, Any]] = []
    paper_briefs: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []
    for relation in conn.execute(
        "SELECT paper_id FROM research_run_papers WHERE run_id = ? ORDER BY paper_id",
        (run_id,),
    ).fetchall():
        paper_id = int(relation["paper_id"])
        try:
            paper_hash, paper = _paper_snapshot(conn, paper_id, user_id)
        except ResearchNotFoundError:
            continue
        papers.append(paper)
        dependencies.append(
            {
                "dependency_type": "paper_metadata",
                "dependency_key": f"paper:{paper_id}",
                "paper_id": paper_id,
                "source_hash_snapshot": paper_hash,
                "dependency_hash": str(paper["metadata_hash"]),
            }
        )
        brief = conn.execute(
            """
            SELECT * FROM research_artifacts
            WHERE run_id = ? AND paper_id = ? AND artifact_type = 'paper_brief'
              AND status = 'completed'
            ORDER BY version DESC LIMIT 1
            """,
            (run_id, paper_id),
        ).fetchone()
        if brief is not None and _artifact_integrity_valid(brief):
            content = _decoded(str(brief["content_json"]), {})
            if str(brief["source_hash"] or "") == paper_hash:
                paper_briefs.append(
                    {
                        "artifact_id": str(brief["id"]),
                        "artifact_version": int(brief["version"]),
                        "content_hash": str(brief["content_hash"]),
                        "content": content,
                    }
                )
                dependencies.append(
                    {
                        "dependency_type": "artifact",
                        "dependency_key": f"artifact:{brief['id']}:{brief['version']}",
                        "upstream_artifact_id": str(brief["id"]),
                        "upstream_artifact_version": int(brief["version"]),
                        "source_hash_snapshot": str(brief["source_hash"]),
                        "dependency_hash": str(brief["content_hash"]),
                    }
                )

    report_row = conn.execute(
        """
        SELECT * FROM research_artifacts
        WHERE run_id = ? AND artifact_type = 'research_report' AND status = 'completed'
        ORDER BY version DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    report: dict[str, Any] | None = None
    claims: list[dict[str, Any]] = []
    citation_sources: list[dict[str, Any]] = []
    if report_row is not None and _artifact_integrity_valid(report_row):
        _, report = _report_snapshot(
            conn, str(report_row["id"]), int(report_row["version"]), user_id
        )
        dependencies.append(
            {
                "dependency_type": "artifact",
                "dependency_key": f"artifact:{report_row['id']}:{report_row['version']}",
                "upstream_artifact_id": str(report_row["id"]),
                "upstream_artifact_version": int(report_row["version"]),
                "dependency_hash": str(report_row["content_hash"]),
            }
        )
        report_content = cast(dict[str, Any], report["content"])
        versions = report_content.get("generated_from_artifact_versions", {})
        if isinstance(versions, dict):
            claims_version = versions.get("synthesis_claims")
            registry_version = versions.get("citation_registry")
            validation_version = versions.get("citation_validation_result")
            for artifact_type, version in (
                ("synthesis_claims", claims_version),
                ("citation_registry", registry_version),
                ("citation_validation_result", validation_version),
            ):
                if not isinstance(version, int):
                    continue
                upstream = conn.execute(
                    """
                    SELECT * FROM research_artifacts
                    WHERE run_id = ? AND artifact_type = ? AND version = ?
                    """,
                    (run_id, artifact_type, version),
                ).fetchone()
                if upstream is None or not _artifact_integrity_valid(upstream):
                    continue
                dependencies.append(
                    {
                        "dependency_type": "artifact",
                        "dependency_key": f"artifact:{upstream['id']}:{upstream['version']}",
                        "upstream_artifact_id": str(upstream["id"]),
                        "upstream_artifact_version": int(upstream["version"]),
                        "dependency_hash": str(upstream["content_hash"]),
                    }
                )
                if artifact_type == "synthesis_claims":
                    claims = [
                        {**item, "source_artifact_id": str(upstream["id"]), "source_artifact_version": int(upstream["version"])}
                        for item in _decoded(str(upstream["content_json"]), {}).get("claims", [])
                        if isinstance(item, dict)
                    ]
                elif artifact_type == "citation_registry":
                    for citation in conn.execute(
                        "SELECT * FROM research_citations WHERE artifact_id = ? ORDER BY citation_key",
                        (str(upstream["id"]),),
                    ).fetchall():
                        status = _citation_status(conn, citation, user_id)
                        if status != "valid":
                            continue
                        citation_sources.append(
                            {
                                "source_run_id": run_id,
                                "source_report_artifact_id": str(report_row["id"]),
                                "source_report_artifact_version": int(report_row["version"]),
                                "source_registry_artifact_id": str(upstream["id"]),
                                "source_registry_artifact_version": int(upstream["version"]),
                                "source_citation_id": str(citation["id"]),
                                "source_citation_key": str(citation["citation_key"]),
                                "source_claim_id": str(citation["claim_id"]),
                                "evidence_id": str(citation["evidence_id"]),
                                "paper_id": int(citation["paper_id"]),
                                "source_hash": str(citation["source_hash"]),
                                "status": status,
                            }
                        )
                        dependencies.append(
                            {
                                "dependency_type": "citation",
                                "dependency_key": f"citation:{citation['id']}",
                                "citation_id": str(citation["id"]),
                                "source_hash_snapshot": str(citation["source_hash"]),
                                "dependency_hash": _digest(
                                    {
                                        "id": str(citation["id"]),
                                        "evidence_id": str(citation["evidence_id"]),
                                        "source_hash": str(citation["source_hash"]),
                                        "quote_hash": str(citation["quote_hash"]),
                                    }
                                ),
                            }
                        )
    return {
        "run": {**run, "source_hash": run_hash},
        "papers": papers,
        "paper_briefs": paper_briefs,
        "report": report,
        "claims": claims,
        "citation_sources": citation_sources,
        "dependencies": dependencies,
    }


def get_project_analysis_inputs(
    conn: sqlite3.Connection,
    project_id: str,
    user_id: int,
    run_id: str | None = None,
) -> dict[str, Any]:
    validation = validate_project_inputs(conn, project_id, user_id)
    if run_id is not None:
        run = conn.execute(
            "SELECT 1 FROM research_runs WHERE id = ? AND project_id = ? AND user_id = ? AND mode = 'project'",
            (run_id, project_id, user_id),
        ).fetchone()
        if run is None:
            raise ResearchNotFoundError("project analysis run not found")
    papers: dict[int, dict[str, Any]] = {}
    reports: dict[tuple[str, int], dict[str, Any]] = {}
    runs: list[dict[str, Any]] = []
    citation_sources: dict[str, dict[str, Any]] = {}
    dependencies: dict[tuple[str, str], dict[str, Any]] = {}
    for item in validation["items"]:
        if item["status"] != "valid":
            continue
        source = cast(dict[str, Any], item["source"])
        dependencies[("project_item", f"project-item:{item['id']}")] = {
            "dependency_type": "project_item",
            "dependency_key": f"project-item:{item['id']}",
            "project_item_id": str(item["id"]),
            "source_hash_snapshot": str(item["source_hash_snapshot"]),
            "dependency_hash": _digest(source),
        }
        if item["item_type"] == "paper":
            papers[int(source["paper_id"])] = source
            dependencies[("paper_metadata", f"paper:{source['paper_id']}")] = {
                "dependency_type": "paper_metadata",
                "dependency_key": f"paper:{source['paper_id']}",
                "paper_id": int(source["paper_id"]),
                "source_hash_snapshot": str(source["source_hash"]),
                "dependency_hash": str(source["metadata_hash"]),
            }
        elif item["item_type"] == "run":
            resolved = _run_analysis_sources(conn, str(item["run_id"]), user_id)
            runs.append(cast(dict[str, Any], resolved["run"]))
            for paper in resolved["papers"]:
                papers[int(paper["paper_id"])] = paper
            if resolved["report"] is not None:
                resolved_report = cast(dict[str, Any], resolved["report"])
                reports[
                    (str(resolved_report["artifact_id"]), int(resolved_report["artifact_version"]))
                ] = {
                        **cast(dict[str, Any], resolved["report"]),
                        "claims": resolved["claims"],
                        "paper_briefs": resolved["paper_briefs"],
                    }
            for citation in resolved["citation_sources"]:
                citation_sources[str(citation["source_citation_id"])] = citation
            for dependency in resolved["dependencies"]:
                dependencies[(str(dependency["dependency_type"]), str(dependency["dependency_key"]))] = dependency
        else:
            claims = _report_claims_for_snapshot(conn, source, user_id)
            report_input = {**source, "claims": claims}
            reports[(str(source["artifact_id"]), int(source["artifact_version"]))] = report_input
            dependencies[("artifact", f"artifact:{source['artifact_id']}:{source['artifact_version']}")] = {
                "dependency_type": "artifact",
                "dependency_key": f"artifact:{source['artifact_id']}:{source['artifact_version']}",
                "upstream_artifact_id": str(source["artifact_id"]),
                "upstream_artifact_version": int(source["artifact_version"]),
                "dependency_hash": str(source["content_hash"]),
            }
            versions = cast(dict[str, Any], source.get("content", {})).get(
                "generated_from_artifact_versions", {}
            )
            registry_version = versions.get("citation_registry") if isinstance(versions, dict) else None
            if isinstance(registry_version, int):
                registry = conn.execute(
                    """
                    SELECT id FROM research_artifacts
                    WHERE run_id = ? AND artifact_type = 'citation_registry' AND version = ?
                    """,
                    (str(source["run_id"]), registry_version),
                ).fetchone()
                if registry is not None:
                    citation_rows = conn.execute(
                        "SELECT * FROM research_citations WHERE artifact_id = ? ORDER BY citation_key",
                        (str(registry["id"]),),
                    ).fetchall()
                    for citation in citation_rows:
                        status = _citation_status(conn, citation, user_id)
                        if status != "valid":
                            continue
                        citation_id = str(citation["id"])
                        citation_sources[citation_id] = {
                            "source_run_id": str(source["run_id"]),
                            "source_report_artifact_id": str(source["artifact_id"]),
                            "source_report_artifact_version": int(source["artifact_version"]),
                            "source_registry_artifact_id": str(registry["id"]),
                            "source_registry_artifact_version": registry_version,
                            "source_citation_id": citation_id,
                            "source_citation_key": str(citation["citation_key"]),
                            "source_claim_id": str(citation["claim_id"]),
                            "evidence_id": str(citation["evidence_id"]),
                            "paper_id": int(citation["paper_id"]),
                            "source_hash": str(citation["source_hash"]),
                            "status": status,
                        }
                        dependencies[("citation", f"citation:{citation_id}")] = {
                            "dependency_type": "citation",
                            "dependency_key": f"citation:{citation_id}",
                            "citation_id": citation_id,
                            "source_hash_snapshot": str(citation["source_hash"]),
                            "dependency_hash": _digest(
                                {
                                    "id": citation_id,
                                    "evidence_id": str(citation["evidence_id"]),
                                    "source_hash": str(citation["source_hash"]),
                                    "quote_hash": str(citation["quote_hash"]),
                                }
                            ),
                        }
    safe_items = [
        {"id": item["id"], "item_type": item["item_type"], "status": item["status"]}
        for item in validation["items"]
    ]
    return {
        "project_id": project_id,
        "project_revision": validation["project_revision"],
        "input_fingerprint": validation["input_fingerprint"],
        "items": safe_items,
        "papers": list(papers.values()),
        "runs": runs,
        "reports": list(reports.values()),
        "citation_sources": list(citation_sources.values()),
        "dependencies": list(dependencies.values()),
        "coverage": validation["coverage"],
        "stale_dependencies": validation["stale_dependencies"],
        "inaccessible_dependencies": validation["inaccessible_dependencies"],
    }


def create_project_analysis_run(
    conn: sqlite3.Connection, project_id: str, user_id: int
) -> dict[str, Any]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        project = _owned_project(conn, project_id, user_id, writable=True)
        validation = validate_project_inputs(conn, project_id, user_id)
        run_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO research_runs(
                id, user_id, project_id, project_revision, input_fingerprint,
                title, goal, mode, budget_json, usage_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'project', ?, ?)
            """,
            (
                run_id,
                user_id,
                project_id,
                validation["project_revision"],
                validation["input_fingerprint"],
                f"{project['title']} · 研究脉络",
                f"生成项目「{project['title']}」的可追溯研究脉络",
                _json(
                    {
                        "kind": "project",
                        "max_model_calls": 3,
                        "max_tool_calls": 20,
                        "max_wall_clock_seconds": 900,
                    }
                ),
                _json(
                    {
                        "model_calls": 0,
                        "tool_calls": 0,
                        "successful_calls": 0,
                        "failed_calls": 0,
                        "wall_clock_seconds": 0,
                    }
                ),
            ),
        )
        steps: tuple[tuple[str, str, str, str, list[str]], ...] = (
            ("validate_project_inputs", "project.validate", "校验项目资料", "项目资料校验", []),
            ("landscape_planning", "project.plan", "制定脉络计划", "研究脉络规划", ["validate_project_inputs"]),
            ("topic_clustering", "project.clusters", "生成主题簇", "主题簇生成", ["landscape_planning"]),
            ("timeline_construction", "project.timeline", "构建研究时间线", "研究时间线生成", ["landscape_planning"]),
            ("graph_construction", "project.graph", "构建研究关系图", "研究关系图生成", ["topic_clustering", "timeline_construction"]),
            ("graph_citation_validation", "project.validation", "校验图谱与引用", "研究关系图校验", ["graph_construction"]),
            ("finalize_research_landscape", "project.finalize", "完成研究脉络", "研究脉络整理", ["graph_citation_validation"]),
        )
        for position, (key, step_type, title, agent, dependencies) in enumerate(steps):
            conn.execute(
                """
                INSERT INTO research_steps(
                    id, run_id, step_key, step_type, title, agent_name, position,
                    depends_on_json, input_json, max_attempts, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 2, ?)
                """,
                (
                    str(uuid.uuid4()),
                    run_id,
                    key,
                    step_type,
                    title,
                    agent,
                    position,
                    _json(dependencies),
                    _json(
                        {
                            "project_id": project_id,
                            "project_revision": validation["project_revision"],
                            "input_fingerprint": validation["input_fingerprint"],
                        }
                        if position == 0
                        else {}
                    ),
                    f"project:{project_id}:{key}:{run_id}",
                ),
            )
        conn.execute(
            """
            INSERT INTO research_events(run_id, event_type, summary, payload_json)
            VALUES (?, 'run.created', '项目研究脉络任务已创建', ?)
            """,
            (run_id, _json({"mode": "project", "project_id": project_id, "step_count": 7})),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ResearchConflictError("project already has an active analysis run") from exc
    except Exception:
        conn.rollback()
        raise
    return get_run_snapshot(conn, run_id, user_id)


def _snapshot_hash(input_snapshot: dict[str, Any], dependency_snapshot: list[dict[str, Any]]) -> str:
    return _digest({"input": input_snapshot, "dependencies": dependency_snapshot})


def create_project_artifact(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    source_step_id: str,
    worker_id: str,
    lease_generation: int,
    project_id: str,
    artifact_type: str,
    content: dict[str, Any],
    idempotency_key: str,
    input_snapshot: dict[str, Any],
    dependency_snapshot: list[dict[str, Any]],
    dependencies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if artifact_type not in PROJECT_ARTIFACT_TYPES:
        raise ValueError("unsupported project artifact type")
    if not dependencies:
        raise ValueError("project artifact requires normalized dependencies")
    if _digest(dependency_snapshot) != _digest(dependencies):
        raise ValueError("project artifact dependency snapshot mismatch")
    from ..services.research_contracts import validate_artifact_content

    validated = validate_artifact_content(artifact_type, content)
    assert_safe_research_payload(validated)
    assert_safe_research_payload(input_snapshot)
    assert_safe_research_payload(dependency_snapshot)
    content_json = _json(validated)
    content_hash = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
    input_json = _json(input_snapshot)
    dependency_json = _json(dependency_snapshot)
    snapshot_hash = _snapshot_hash(input_snapshot, dependency_snapshot)
    conn.execute("BEGIN IMMEDIATE")
    try:
        lease = _active_lease(
            conn,
            run_id=run_id,
            step_id=source_step_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        run = conn.execute(
            """
            SELECT project_id, project_revision, input_fingerprint, mode
            FROM research_runs WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        if (
            run is None
            or str(run["mode"]) != "project"
            or str(run["project_id"]) != project_id
        ):
            raise ResearchConflictError("project artifact run identity mismatch")
        _owned_project(conn, project_id, int(lease["user_id"]), writable=True)
        current = validate_project_inputs(conn, project_id, int(lease["user_id"]))
        if (
            int(run["project_revision"] or -1) != int(current["project_revision"])
            or str(run["input_fingerprint"] or "") != str(current["input_fingerprint"])
            or int(input_snapshot.get("project_revision", -1))
            != int(current["project_revision"])
            or str(input_snapshot.get("input_fingerprint", ""))
            != str(current["input_fingerprint"])
        ):
            raise ResearchConflictError("project inputs changed during analysis")
        for dependency in dependencies:
            dependency_row = dict(dependency)
            for nullable_key in (
                "project_item_id",
                "upstream_artifact_id",
                "upstream_artifact_version",
                "citation_id",
                "evidence_id",
                "paper_id",
                "source_hash_snapshot",
            ):
                dependency_row.setdefault(nullable_key, None)
            status = _dependency_status(
                conn,
                cast(Any, dependency_row),
                project_id=project_id,
                user_id=int(lease["user_id"]),
                visited_artifact_ids=set(),
            )
            if status != "current":
                raise ResearchConflictError(
                    f"project artifact dependency is {status}"
                )
        existing = conn.execute(
            "SELECT * FROM research_artifacts WHERE run_id = ? AND idempotency_key = ?",
            (run_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["project_id"] or "") != project_id
                or str(existing["artifact_type"]) != artifact_type
                or str(existing["content_hash"]) != content_hash
                or str(existing["snapshot_hash"] or "") != snapshot_hash
            ):
                raise ResearchConflictError("project artifact operation identity conflict")
            conn.commit()
            return _artifact_row(existing)
        version_row = conn.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1 AS version
            FROM research_artifacts WHERE project_id = ? AND artifact_type = ?
            """,
            (project_id, artifact_type),
        ).fetchone()
        version = int(version_row["version"] if version_row else 1)
        artifact_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO research_artifacts(
                id, run_id, project_id, artifact_type, schema_version,
                source_step_id, version, status, content_json, input_snapshot_json,
                dependency_snapshot_json, snapshot_hash, idempotency_key, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                run_id,
                project_id,
                artifact_type,
                int(validated.get("schema_version", 1)),
                source_step_id,
                version,
                content_json,
                input_json,
                dependency_json,
                snapshot_hash,
                idempotency_key,
                content_hash,
            ),
        )
        for dependency in dependencies or []:
            assert_safe_research_payload(dependency)
            conn.execute(
                """
                INSERT INTO research_artifact_dependencies(
                    id, artifact_id, dependency_type, dependency_key,
                    project_item_id, upstream_artifact_id, upstream_artifact_version,
                    citation_id, evidence_id, paper_id, source_hash_snapshot,
                    dependency_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    artifact_id,
                    dependency["dependency_type"],
                    dependency["dependency_key"],
                    dependency.get("project_item_id"),
                    dependency.get("upstream_artifact_id"),
                    dependency.get("upstream_artifact_version"),
                    dependency.get("citation_id"),
                    dependency.get("evidence_id"),
                    dependency.get("paper_id"),
                    dependency.get("source_hash_snapshot"),
                    dependency["dependency_hash"],
                ),
            )
        conn.execute(
            """
            INSERT INTO research_events(run_id, step_id, event_type, summary, payload_json)
            VALUES (?, ?, 'artifact.created', ?, ?)
            """,
            (
                run_id,
                source_step_id,
                f"{artifact_type} v{version} 已保存",
                _json(
                    {
                        "artifact_id": artifact_id,
                        "artifact_type": artifact_type,
                        "project_id": project_id,
                        "version": version,
                    }
                ),
            ),
        )
        conn.execute(
            f"UPDATE research_runs SET state_version = state_version + 1, updated_at = {_NOW} WHERE id = ?",
            (run_id,),
        )
        row = conn.execute(
            "SELECT * FROM research_artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if row is None:
        raise RuntimeError("project artifact disappeared")
    return _artifact_row(row)


def _dependency_status(
    conn: sqlite3.Connection,
    dependency: sqlite3.Row,
    *,
    project_id: str,
    user_id: int,
    visited_artifact_ids: set[str],
) -> str:
    dependency_type = str(dependency["dependency_type"])
    expected_hash = str(dependency["dependency_hash"])
    expected_source_hash = str(dependency["source_hash_snapshot"] or "")
    if dependency_type == "project_item":
        item = conn.execute(
            "SELECT * FROM research_project_items WHERE id = ? AND project_id = ?",
            (str(dependency["project_item_id"]), project_id),
        ).fetchone()
        if item is None:
            return "stale"
        projected = _project_item_projection(conn, item, user_id)
        if projected["status"] == "inaccessible":
            return "inaccessible"
        if projected["status"] != "valid":
            return "stale"
        source = cast(dict[str, Any], projected.get("source", {}))
        if (
            expected_source_hash != str(projected["source_hash_snapshot"])
            or _digest(source) != expected_hash
        ):
            return "stale"
        return "current"

    if dependency_type == "paper_metadata":
        try:
            current_source_hash, paper = _paper_snapshot(
                conn, int(dependency["paper_id"]), user_id
            )
        except ResearchNotFoundError:
            return "inaccessible"
        if (
            current_source_hash != expected_source_hash
            or str(paper["metadata_hash"]) != expected_hash
        ):
            return "stale"
        return "current"

    if dependency_type == "citation":
        citation = conn.execute(
            """
            SELECT c.* FROM research_citations c
            JOIN research_runs r ON r.id = c.run_id
            WHERE c.id = ? AND r.user_id = ?
            """,
            (str(dependency["citation_id"]), user_id),
        ).fetchone()
        if citation is None:
            return "inaccessible"
        status = _citation_status(conn, citation, user_id)
        if status == "inaccessible":
            return "inaccessible"
        current_hash = _digest(
            {
                "id": str(citation["id"]),
                "evidence_id": str(citation["evidence_id"]),
                "source_hash": str(citation["source_hash"]),
                "quote_hash": str(citation["quote_hash"]),
            }
        )
        if (
            status != "valid"
            or str(citation["source_hash"]) != expected_source_hash
            or current_hash != expected_hash
        ):
            return "stale"
        return "current"

    if dependency_type == "evidence":
        evidence = conn.execute(
            """
            SELECT e.* FROM research_evidence e
            JOIN research_runs r ON r.id = e.run_id
            WHERE e.id = ? AND r.user_id = ?
            """,
            (str(dependency["evidence_id"]), user_id),
        ).fetchone()
        if evidence is None:
            return "inaccessible"
        status = _evidence_status(conn, evidence, user_id)
        if status == "inaccessible":
            return "inaccessible"
        current_hash = _digest(
            {
                "id": str(evidence["id"]),
                "paper_id": int(evidence["paper_id"]),
                "chunk_id": int(evidence["chunk_id"]),
                "source_hash": str(evidence["source_hash"]),
                "quote_hash": str(evidence["quote_hash"]),
            }
        )
        if (
            status != "valid"
            or str(evidence["source_hash"]) != expected_source_hash
            or current_hash != expected_hash
        ):
            return "stale"
        return "current"

    if dependency_type == "artifact":
        upstream = conn.execute(
            """
            SELECT a.*, r.user_id FROM research_artifacts a
            JOIN research_runs r ON r.id = a.run_id
            WHERE a.id = ? AND a.version = ?
            """,
            (
                str(dependency["upstream_artifact_id"]),
                int(dependency["upstream_artifact_version"]),
            ),
        ).fetchone()
        if upstream is None or int(upstream["user_id"]) != user_id:
            return "inaccessible"
        if (
            str(upstream["status"]) != "completed"
            or not _artifact_integrity_valid(upstream)
            or str(upstream["content_hash"]) != expected_hash
        ):
            return "stale"
        if expected_source_hash:
            if str(upstream["source_hash"] or "") != expected_source_hash:
                return "stale"
            if upstream["paper_id"] is not None:
                try:
                    current_source_hash, _ = _paper_snapshot(
                        conn, int(upstream["paper_id"]), user_id
                    )
                except ResearchNotFoundError:
                    return "inaccessible"
                if current_source_hash != expected_source_hash:
                    return "stale"
        upstream_project_id = str(upstream["project_id"] or "")
        if upstream_project_id:
            if upstream_project_id != project_id:
                return "inaccessible"
            latest = conn.execute(
                """
                SELECT MAX(version) AS version
                FROM research_artifacts
                WHERE project_id = ? AND artifact_type = ?
                """,
                (project_id, str(upstream["artifact_type"])),
            ).fetchone()
            if latest is None or int(latest["version"] or 0) != int(upstream["version"]):
                return "stale"
            return _artifact_dependency_status(
                conn,
                upstream,
                project_id=project_id,
                user_id=user_id,
                visited_artifact_ids=visited_artifact_ids,
            )
        return "current"

    return "stale"


def _artifact_dependency_status(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    project_id: str,
    user_id: int,
    visited_artifact_ids: set[str] | None = None,
) -> str:
    visited = set(visited_artifact_ids or set())
    artifact_id = str(row["id"])
    if artifact_id in visited:
        return "stale"
    visited.add(artifact_id)
    dependencies = conn.execute(
        """
        SELECT * FROM research_artifact_dependencies
        WHERE artifact_id = ? ORDER BY dependency_type, dependency_key
        """,
        (artifact_id,),
    ).fetchall()
    if not dependencies:
        return "stale"
    statuses = [
        _dependency_status(
            conn,
            dependency,
            project_id=project_id,
            user_id=user_id,
            visited_artifact_ids=visited,
        )
        for dependency in dependencies
    ]
    if "inaccessible" in statuses:
        return "inaccessible"
    if any(status != "current" for status in statuses):
        return "stale"
    return "current"


def _project_artifact_projection(
    conn: sqlite3.Connection, row: sqlite3.Row, user_id: int
) -> dict[str, Any]:
    result = _artifact_row(row, is_current=False)
    if not _artifact_integrity_valid(row):
        result["status"] = "stale"
        result["dependency_status"] = "stale"
        result["content"] = {}
        return result
    snapshot = _decoded(str(row["input_snapshot_json"]), {})
    expected = snapshot.get("input_fingerprint") if isinstance(snapshot, dict) else None
    validation = validate_project_inputs(conn, str(row["project_id"]), user_id)
    dependency_status = _artifact_dependency_status(
        conn,
        row,
        project_id=str(row["project_id"]),
        user_id=user_id,
    )
    inaccessible = bool(validation["inaccessible_dependencies"]) or dependency_status == "inaccessible"
    stale = (
        bool(validation["stale_dependencies"])
        or expected != validation["input_fingerprint"]
        or dependency_status != "current"
    )
    if inaccessible:
        result["dependency_status"] = "inaccessible"
        result["content"] = {}
    elif stale or str(row["status"]) != "completed":
        result["dependency_status"] = "stale"
    else:
        result["dependency_status"] = "current"
        result["is_current"] = True
    result["input_fingerprint"] = expected
    return result


def list_project_artifacts(
    conn: sqlite3.Connection,
    project_id: str,
    user_id: int,
    artifact_type: str | None = None,
) -> list[dict[str, Any]]:
    _owned_project(conn, project_id, user_id)
    params: list[Any] = [project_id]
    where = "project_id = ?"
    if artifact_type is not None:
        if artifact_type not in PROJECT_ARTIFACT_TYPES:
            raise ValueError("unsupported project artifact type")
        where += " AND artifact_type = ?"
        params.append(artifact_type)
    rows = conn.execute(
        f"SELECT * FROM research_artifacts WHERE {where} ORDER BY artifact_type, version DESC",
        tuple(params),
    ).fetchall()
    result: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for row in rows:
        projected = _project_artifact_projection(conn, row, user_id)
        artifact_type_value = str(row["artifact_type"])
        if artifact_type_value in seen_types:
            projected["is_current"] = False
        else:
            # Only the highest version may be current. If it is stale or
            # inaccessible, callers must not fall back to an older completed row.
            seen_types.add(artifact_type_value)
        result.append(projected)
    return result


def get_project_artifact(
    conn: sqlite3.Connection,
    project_id: str,
    artifact_id: str,
    user_id: int,
) -> dict[str, Any]:
    _owned_project(conn, project_id, user_id)
    row = conn.execute(
        "SELECT * FROM research_artifacts WHERE id = ? AND project_id = ?",
        (artifact_id, project_id),
    ).fetchone()
    if row is None:
        raise ResearchNotFoundError("project artifact not found")
    projected = _project_artifact_projection(conn, row, user_id)
    latest = conn.execute(
        "SELECT MAX(version) AS version FROM research_artifacts WHERE project_id = ? AND artifact_type = ?",
        (project_id, str(row["artifact_type"])),
    ).fetchone()
    if latest is None or int(row["version"]) != int(latest["version"]):
        projected["is_current"] = False
    return projected


def find_project_artifact_checkpoint(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    run_id: str,
    source_step_id: str,
    idempotency_key: str,
    input_fingerprint: str,
    user_id: int,
) -> dict[str, Any] | None:
    _owned_project(conn, project_id, user_id)
    row = conn.execute(
        """
        SELECT * FROM research_artifacts
        WHERE project_id = ? AND run_id = ? AND source_step_id = ?
          AND idempotency_key = ?
        """,
        (project_id, run_id, source_step_id, idempotency_key),
    ).fetchone()
    if row is None:
        return None
    projected = _project_artifact_projection(conn, row, user_id)
    if (
        projected.get("dependency_status") != "current"
        or projected.get("input_fingerprint") != input_fingerprint
    ):
        return None
    return projected


def create_project_citation_ref(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    analysis_run_id: str,
    user_id: int,
    step_id: str,
    worker_id: str,
    lease_generation: int,
    citation_id: str | None = None,
    evidence_id: str | None = None,
) -> dict[str, Any]:
    if (citation_id is None) == (evidence_id is None):
        raise ValueError("exactly one citation or evidence id is required")
    conn.execute("BEGIN IMMEDIATE")
    try:
        lease = _active_lease(
            conn,
            run_id=analysis_run_id,
            step_id=step_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        if int(lease["user_id"]) != user_id:
            raise ResearchNotFoundError("project analysis run not found")
        _owned_project(conn, project_id, user_id)
        run = conn.execute(
            "SELECT 1 FROM research_runs WHERE id = ? AND project_id = ? AND user_id = ? AND mode = 'project'",
            (analysis_run_id, project_id, user_id),
        ).fetchone()
        if run is None:
            raise ResearchNotFoundError("project analysis run not found")
        if citation_id is not None:
            source = conn.execute(
                """
                SELECT c.* FROM research_citations c
                JOIN research_runs r ON r.id = c.run_id
                WHERE c.id = ? AND r.user_id = ?
                """,
                (citation_id, user_id),
            ).fetchone()
            if source is None or _citation_status(conn, source, user_id) != "valid":
                raise ResearchNotFoundError("project citation source not found")
            reference_type = "citation"
            paper_id = int(source["paper_id"])
            source_hash = str(source["source_hash"])
        else:
            source = conn.execute(
                """
                SELECT e.* FROM research_evidence e
                JOIN research_runs r ON r.id = e.run_id
                WHERE e.id = ? AND r.user_id = ?
                """,
                (evidence_id, user_id),
            ).fetchone()
            if source is None or _evidence_status(conn, source, user_id) != "valid":
                raise ResearchNotFoundError("project evidence source not found")
            reference_type = "evidence"
            paper_id = int(source["paper_id"])
            source_hash = str(source["source_hash"])
        existing = conn.execute(
            f"""
            SELECT * FROM research_project_citation_refs
            WHERE analysis_run_id = ? AND {reference_type}_id = ?
            """,
            (analysis_run_id, citation_id or evidence_id),
        ).fetchone()
        if existing is not None:
            conn.commit()
            return dict(existing)
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM research_project_citation_refs WHERE analysis_run_id = ?",
            (analysis_run_id,),
        ).fetchone()
        citation_key = f"PC{int(count['count'] if count else 0) + 1}"
        reference_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO research_project_citation_refs(
                id, project_id, analysis_run_id, citation_key, reference_type,
                citation_id, evidence_id, paper_id, source_hash_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference_id,
                project_id,
                analysis_run_id,
                citation_key,
                reference_type,
                citation_id,
                evidence_id,
                paper_id,
                source_hash,
            ),
        )
        row = conn.execute(
            "SELECT * FROM research_project_citation_refs WHERE id = ?", (reference_id,)
        ).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if row is None:
        raise RuntimeError("project citation reference disappeared")
    return dict(row)


def list_project_citation_refs(
    conn: sqlite3.Connection, project_id: str, analysis_run_id: str, user_id: int
) -> list[dict[str, Any]]:
    _owned_project(conn, project_id, user_id)
    run = conn.execute(
        "SELECT 1 FROM research_runs WHERE id = ? AND project_id = ? AND user_id = ?",
        (analysis_run_id, project_id, user_id),
    ).fetchone()
    if run is None:
        raise ResearchNotFoundError("project analysis run not found")
    rows = conn.execute(
        "SELECT * FROM research_project_citation_refs WHERE analysis_run_id = ? ORDER BY citation_key",
        (analysis_run_id,),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        if str(row["reference_type"]) == "citation":
            source = conn.execute(
                "SELECT * FROM research_citations WHERE id = ?", (str(row["citation_id"]),)
            ).fetchone()
            status = _citation_status(conn, source, user_id) if source is not None else "invalid"
        else:
            source = conn.execute(
                "SELECT * FROM research_evidence WHERE id = ?", (str(row["evidence_id"]),)
            ).fetchone()
            status = _evidence_status(conn, source, user_id) if source is not None else "invalid"
        if status == "inaccessible":
            result.append(
                {"id": str(row["id"]), "reference_type": str(row["reference_type"]), "status": status}
            )
        else:
            item = dict(row)
            item["status"] = status
            result.append(item)
    return result


def get_project_citation_evidence(
    conn: sqlite3.Connection,
    project_id: str,
    analysis_run_id: str,
    reference_id: str,
    user_id: int,
) -> dict[str, Any]:
    refs = list_project_citation_refs(conn, project_id, analysis_run_id, user_id)
    projected = next((item for item in refs if item["id"] == reference_id), None)
    if projected is None or projected.get("status") == "inaccessible":
        raise ResearchNotFoundError("project citation reference not found")
    if projected["status"] != "valid":
        return {**projected, "excerpt": None}
    evidence_id = projected.get("evidence_id")
    if evidence_id is None:
        citation = conn.execute(
            "SELECT evidence_id FROM research_citations WHERE id = ?",
            (projected["citation_id"],),
        ).fetchone()
        evidence_id = str(citation["evidence_id"]) if citation is not None else None
    evidence = conn.execute(
        "SELECT * FROM research_evidence WHERE id = ?", (evidence_id,)
    ).fetchone()
    if evidence is None or _evidence_status(conn, evidence, user_id) != "valid":
        return {**projected, "status": "stale", "excerpt": None}
    chunk = conn.execute(
        """
        SELECT pc.content, p.title AS paper_title
        FROM paper_chunks pc
        JOIN papers p ON p.id = pc.paper_id
        WHERE pc.id = ? AND pc.paper_id = ? AND pc.source_hash = ?
        """,
        (int(evidence["chunk_id"]), int(evidence["paper_id"]), str(evidence["source_hash"])),
    ).fetchone()
    if chunk is None:
        return {**projected, "status": "stale", "excerpt": None}
    content = str(chunk["content"])
    char_start = int(evidence["char_start"])
    char_end = int(evidence["char_end"])
    if char_start < 0 or char_end <= char_start:
        return {**projected, "status": "stale", "excerpt": None}
    return {
        **projected,
        "paper_id": int(evidence["paper_id"]),
        "paper_title": str(chunk["paper_title"]),
        "heading": str(evidence["heading"] or ""),
        "chunk_id": int(evidence["chunk_id"]),
        "char_start": char_start,
        "char_end": char_end,
        "excerpt": content,
    }


def project_backlinks(
    conn: sqlite3.Connection,
    user_id: int,
    item_type: str,
    *,
    run_id: str | None = None,
    paper_id: int | None = None,
    artifact_id: str | None = None,
    artifact_version: int | None = None,
) -> list[dict[str, Any]]:
    _item_source_snapshot(
        conn,
        item_type=item_type,
        user_id=user_id,
        run_id=run_id,
        paper_id=paper_id,
        artifact_id=artifact_id,
        artifact_version=artifact_version,
    )
    params: tuple[Any, ...]
    if item_type == "run":
        where, params = "i.item_type = 'run' AND i.run_id = ?", (run_id,)
    elif item_type == "paper":
        where, params = "i.item_type = 'paper' AND i.paper_id = ?", (paper_id,)
    elif item_type == "research_report":
        where, params = (
            "i.item_type = 'research_report' AND i.artifact_id = ? AND i.artifact_version = ?",
            (artifact_id, artifact_version),
        )
    else:
        raise ValueError("unsupported backlink item type")
    rows = conn.execute(
        f"""
        SELECT p.id, p.title, p.description, p.status, p.updated_at, i.id AS item_id
        FROM research_project_items i JOIN research_projects p ON p.id = i.project_id
        WHERE p.owner_user_id = ? AND {where}
        ORDER BY p.updated_at DESC
        """,
        (user_id, *params),
    ).fetchall()
    return [dict(row) for row in rows]


def wait_for_project_coverage(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    step_id: str,
    worker_id: str,
    lease_generation: int,
    validation: dict[str, Any],
) -> None:
    assert_safe_research_payload(validation)
    conn.execute("BEGIN IMMEDIATE")
    try:
        lease = _active_lease(
            conn,
            run_id=run_id,
            step_id=step_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        run = conn.execute(
            "SELECT mode, project_id FROM research_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if run is None or str(run["mode"]) != "project" or run["project_id"] is None:
            raise ResearchConflictError("project coverage decision run mismatch")
        existing = conn.execute(
            "SELECT 1 FROM research_decisions WHERE run_id = ? AND status = 'pending'",
            (run_id,),
        ).fetchone()
        if existing is None:
            decision_id = str(uuid.uuid4())
            options = [
                {"id": "add_more_sources", "label": "添加更多 Run 或论文", "action": "project_add_more_sources"},
                {"id": "remove_invalid", "label": "移除过期或不可访问资料", "action": "project_remove_invalid"},
                {"id": "generate_limited", "label": "生成有限脉络", "action": "project_generate_limited"},
                {"id": "reduce_dimensions", "label": "减少聚类维度", "action": "project_reduce_dimensions"},
                {"id": "deterministic_timeline", "label": "仅生成确定性时间线", "action": "project_deterministic_timeline"},
                {"id": "edit_project", "label": "返回项目编辑", "action": "project_edit"},
                {"id": "stop", "label": "停止", "action": "project_stop"},
            ]
            conn.execute(
                """
                INSERT INTO research_decisions(
                    id, run_id, step_id, question, options_json, recommended_option
                ) VALUES (?, ?, ?, '当前项目资料覆盖不足，请选择下一步。', ?, 'generate_limited')
                """,
                (decision_id, run_id, step_id, _json(options)),
            )
            conn.execute(
                """
                INSERT INTO research_events(run_id, step_id, event_type, summary, payload_json)
                VALUES (?, ?, 'decision.requested', '项目分析覆盖需要确认', ?)
                """,
                (
                    run_id,
                    step_id,
                    _json(
                        {
                            "kind": "project_coverage",
                            "valid_count": int(validation.get("coverage", {}).get("valid", 0)),
                            "stale_count": len(validation.get("stale_dependencies", [])),
                            "inaccessible_count": len(
                                validation.get("inaccessible_dependencies", [])
                            ),
                        }
                    ),
                ),
            )
        conn.execute(
            f"""
            UPDATE research_steps SET status = 'waiting_input', lease_owner = NULL,
                lease_expires_at = NULL, heartbeat_at = NULL, updated_at = {_NOW}
            WHERE id = ? AND lease_owner = ? AND lease_generation = ?
            """,
            (step_id, str(lease["lease_owner"]), int(lease["lease_generation"])),
        )
        conn.execute(
            f"UPDATE research_runs SET status = 'waiting_input', state_version = state_version + 1, updated_at = {_NOW} WHERE id = ?",
            (run_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def apply_project_coverage_decision(
    conn: sqlite3.Connection, *, decision_row: sqlite3.Row, option: dict[str, Any]
) -> str:
    action = str(option.get("action", ""))
    if action == "project_stop":
        return "stop"
    if action in {"project_add_more_sources", "project_remove_invalid", "project_edit"}:
        return "edit_project"
    flags = {
        "project_generate_limited": {"limited_scope": True},
        "project_reduce_dimensions": {"reduce_dimensions": True},
        "project_deterministic_timeline": {"deterministic_timeline_only": True},
    }
    if action not in flags:
        raise ResearchConflictError("project coverage decision action is invalid")
    step_id = str(decision_row["step_id"] or "")
    row = conn.execute("SELECT input_json FROM research_steps WHERE id = ?", (step_id,)).fetchone()
    if row is None:
        raise ResearchConflictError("project coverage decision step is missing")
    input_data = cast(dict[str, Any], _decoded(str(row["input_json"]), {}))
    input_data.update(flags[action])
    conn.execute(
        f"UPDATE research_steps SET input_json = ?, updated_at = {_NOW} WHERE id = ?",
        (_json(input_data), step_id),
    )
    return "resume"

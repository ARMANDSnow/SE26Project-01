from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from typing import Any, cast

from ..repositories.uploads import accessible_paper_condition, paper_is_accessible
from ..services.research_contracts import PaperBrief, validate_artifact_content
from .research import ResearchConflictError, ResearchNotFoundError


_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
_STAGE_ORDER = {
    "candidate": 0,
    "selected": 1,
    "fulltext_ready": 2,
    "read": 3,
    "extracted": 4,
}
DEFAULT_TOPIC_BUDGET: dict[str, int | str] = {
    "kind": "topic",
    "max_candidates": 50,
    "max_fulltext_papers": 12,
    "max_model_calls": 40,
    "max_tool_calls": 100,
    "max_wall_clock_seconds": 1_800,
}
DEFAULT_TOPIC_USAGE: dict[str, int] = {
    "candidate_papers": 0,
    "fulltext_papers": 0,
    "model_calls": 0,
    "tool_calls": 0,
    "successful_calls": 0,
    "failed_calls": 0,
    "wall_clock_seconds": 0,
}
_LIMIT_KEYS = {
    "candidate_papers": "max_candidates",
    "fulltext_papers": "max_fulltext_papers",
    "model_calls": "max_model_calls",
    "tool_calls": "max_tool_calls",
}
_SECRET_TEXT = re.compile(
    r"(?:authorization\s*[:=]|bearer\s+[a-z0-9._~+/=-]+|"
    r"x-api-key\s*[:=]|\bsk-[a-z0-9_-]{12,}|"
    r"/(?:users|home|private|etc|var|tmp|opt|usr|root|volumes)/|\\\\[^\\]+\\|[a-z]:\\)",
    re.IGNORECASE,
)
_SECRET_KEYS = re.compile(
    r"(?:authorization|api[_-]?key|x[_-]?api[_-]?key|access[_-]?token|secret|credential|provider[_-]?(?:body|response)|local[_-]?path)",
    re.IGNORECASE,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _decoded(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def assert_safe_research_payload(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _SECRET_KEYS.search(str(key)):
                raise ValueError(f"unsafe research field at {path}")
            assert_safe_research_payload(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_safe_research_payload(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and _SECRET_TEXT.search(value):
        raise ValueError(f"unsafe research text at {path}")


def _owned_run(conn: sqlite3.Connection, run_id: str, user_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM research_runs WHERE id = ? AND user_id = ?",
        (run_id, user_id),
    ).fetchone()
    if row is None:
        raise ResearchNotFoundError("research run not found")
    return cast(sqlite3.Row, row)


def _active_lease(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    step_id: str,
    worker_id: str,
    lease_generation: int,
) -> sqlite3.Row:
    row = conn.execute(
        f"""
        SELECT s.*, r.user_id, r.budget_json, r.usage_json, r.created_at AS run_created_at
        FROM research_steps s JOIN research_runs r ON r.id = s.run_id
        WHERE s.id = ? AND s.run_id = ? AND s.status = 'running'
          AND s.lease_owner = ? AND s.lease_generation = ?
          AND s.lease_expires_at > {_NOW} AND r.requested_action IS NULL
        """,
        (step_id, run_id, worker_id, lease_generation),
    ).fetchone()
    if row is None:
        raise ResearchConflictError("research step lease is no longer active")
    return cast(sqlite3.Row, row)


def _artifact_row(row: sqlite3.Row, *, is_current: bool | None = None) -> dict[str, Any]:
    result = dict(row)
    result["content"] = _decoded(str(result.pop("content_json")), {})
    result.pop("content_hash", None)
    result.pop("idempotency_key", None)
    if is_current is not None:
        result["is_current"] = is_current
    return result


def _artifact_integrity_valid(row: sqlite3.Row) -> bool:
    encoded = str(row["content_json"])
    if hashlib.sha256(encoded.encode("utf-8")).hexdigest() != str(row["content_hash"]):
        return False
    try:
        validate_artifact_content(str(row["artifact_type"]), cast(dict[str, Any], json.loads(encoded)))
    except (TypeError, ValueError, AttributeError, json.JSONDecodeError):
        return False
    return True


def create_artifact(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    source_step_id: str,
    worker_id: str,
    lease_generation: int,
    artifact_type: str,
    content: dict[str, Any],
    idempotency_key: str,
    paper_id: int | None = None,
    source_hash: str | None = None,
    status: str = "completed",
) -> dict[str, Any]:
    validated = validate_artifact_content(artifact_type, content)
    assert_safe_research_payload(validated)
    if artifact_type == "paper_brief" and (paper_id is None or source_hash is None):
        raise ResearchConflictError("paper brief requires a paper relation and source hash")
    encoded = _json(validated)
    schema_version = int(validated.get("schema_version", 1))
    content_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    conn.execute("BEGIN IMMEDIATE")
    try:
        lease = _active_lease(
            conn,
            run_id=run_id,
            step_id=source_step_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        existing = conn.execute(
            "SELECT * FROM research_artifacts WHERE run_id = ? AND idempotency_key = ?",
            (run_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            if str(existing["content_hash"]) != content_hash:
                raise ResearchConflictError("artifact idempotency key has different content")
            conn.commit()
            return _artifact_row(existing)
        if paper_id is not None:
            _validate_paper_artifact(
                conn,
                user_id=int(lease["user_id"]),
                run_id=run_id,
                paper_id=paper_id,
                artifact_type=artifact_type,
                content=validated,
                source_hash=source_hash,
            )
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS version FROM research_artifacts WHERE run_id = ? AND artifact_type = ?",
            (run_id, artifact_type),
        ).fetchone()
        version = int(row["version"])
        artifact_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO research_artifacts(
                id, run_id, paper_id, artifact_type, schema_version, source_step_id,
                version, status, content_json, source_hash, idempotency_key, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                run_id,
                paper_id,
                artifact_type,
                schema_version,
                source_step_id,
                version,
                status,
                encoded,
                source_hash,
                idempotency_key,
                content_hash,
            ),
        )
        if artifact_type == "paper_brief":
            downstream_types = (
                "synthesis_plan", "comparison_matrix", "synthesis_claims",
                "citation_registry", "citation_validation_result", "research_report",
            )
            placeholders = ",".join("?" for _ in downstream_types)
            conn.execute(
                f"UPDATE research_artifacts SET status = 'stale', updated_at = {_NOW} "
                f"WHERE run_id = ? AND artifact_type IN ({placeholders}) AND status = 'completed'",
                (run_id, *downstream_types),
            )
            conn.execute(
                f"UPDATE research_citations SET status = 'stale', updated_at = {_NOW} WHERE run_id = ?",
                (run_id,),
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
                _json({"artifact_id": artifact_id, "artifact_type": artifact_type, "version": version}),
            ),
        )
        conn.execute(
            f"UPDATE research_runs SET state_version = state_version + 1, updated_at = {_NOW} WHERE id = ?",
            (run_id,),
        )
        created = conn.execute(
            "SELECT * FROM research_artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        conn.commit()
        if created is None:
            raise RuntimeError("artifact disappeared")
        return _artifact_row(created)
    except Exception:
        conn.rollback()
        raise


def find_artifact_checkpoint(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    source_step_id: str,
    idempotency_key: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM research_artifacts
        WHERE run_id = ? AND source_step_id = ? AND idempotency_key = ?
        """,
        (run_id, source_step_id, idempotency_key),
    ).fetchone()
    return _artifact_row(row) if row is not None else None


def _validate_paper_artifact(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    run_id: str,
    paper_id: int,
    artifact_type: str,
    content: dict[str, Any],
    source_hash: str | None,
) -> None:
    if not paper_is_accessible(conn, paper_id, user_id):
        raise ResearchNotFoundError("research paper not found")
    paper = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    relation = conn.execute(
        "SELECT * FROM research_run_papers WHERE run_id = ? AND paper_id = ?",
        (run_id, paper_id),
    ).fetchone()
    document = conn.execute(
        "SELECT source_hash, status FROM paper_documents WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if paper is None or relation is None:
        raise ResearchNotFoundError("research paper not found")
    if artifact_type != "paper_brief":
        return
    brief = PaperBrief.model_validate(content)
    expected_hash = str(source_hash or "")
    if (
        document is None
        or str(document["status"]) != "completed"
        or not expected_hash
        or str(paper["asset_id"] or "").removeprefix("sha256:") != expected_hash
        or str(document["source_hash"]) != expected_hash
        or str(relation["source_hash"] or "") != expected_hash
        or brief.source_hash != expected_hash
        or brief.paper_id != paper_id
        or brief.source != str(paper["source"])
        or brief.source_id != str(paper["source_id"])
        or brief.title != str(paper["title"])
        or brief.authors != list(_decoded(str(paper["authors_json"]), []))
        or brief.year != int(str(paper["published_at"])[:4])
    ):
        raise ResearchConflictError("paper brief identity or source hash is stale")
    for evidence in brief.evidence_ids:
        if evidence.paper_id != paper_id or evidence.source_hash != expected_hash or evidence.evidence_id is None:
            raise ResearchConflictError("paper brief evidence identity is stale or out of scope")
        chunk = conn.execute(
            """
            SELECT id, heading, char_start, char_end, content FROM paper_chunks
            WHERE id = ? AND paper_id = ? AND source_hash = ? AND chunk_index = ?
              AND char_start = ? AND char_end = ?
            """,
            (
                evidence.chunk_id,
                paper_id,
                expected_hash,
                evidence.chunk_index,
                evidence.char_start,
                evidence.char_end,
            ),
        ).fetchone()
        if chunk is None or str(chunk["heading"]) != evidence.heading:
            raise ResearchConflictError("paper brief evidence is stale or out of scope")
        opened = conn.execute(
            """
            SELECT source_hash, heading, char_start, char_end, quote_hash, status FROM research_evidence
            WHERE id = ? AND run_id = ? AND paper_id = ? AND chunk_id = ?
              AND source_hash = ? AND heading = ? AND char_start = ? AND char_end = ?
            """,
            (
                evidence.evidence_id, run_id, paper_id, evidence.chunk_id,
                expected_hash, evidence.heading, evidence.char_start, evidence.char_end,
            ),
        ).fetchone()
        if (
            opened is None
            or str(opened["status"]) != "valid"
            or str(opened["source_hash"]) != expected_hash
            or str(opened["heading"]) != str(chunk["heading"])
            or int(opened["char_start"]) != int(chunk["char_start"])
            or int(opened["char_end"]) != int(chunk["char_end"])
            or str(opened["quote_hash"]) != hashlib.sha256(str(chunk["content"]).encode("utf-8")).hexdigest()
        ):
            raise ResearchConflictError("paper brief evidence was not opened for this run")


def list_artifacts(
    conn: sqlite3.Connection,
    run_id: str,
    user_id: int,
    *,
    artifact_type: str | None = None,
) -> list[dict[str, Any]]:
    _owned_run(conn, run_id, user_id)
    clauses = ["a.run_id = ?", "(a.paper_id IS NULL OR " + accessible_paper_condition("p", user_id)[0] + ")"]
    params: list[Any] = [run_id, *accessible_paper_condition("p", user_id)[1]]
    if artifact_type is not None:
        clauses.append("a.artifact_type = ?")
        params.append(artifact_type)
    rows = conn.execute(
        f"""
        SELECT a.* FROM research_artifacts a
        LEFT JOIN papers p ON p.id = a.paper_id
        WHERE {' AND '.join(clauses)}
        ORDER BY a.artifact_type, a.version DESC
        """,
        tuple(params),
    ).fetchall()
    return [_artifact_for_user(conn, row, user_id) for row in rows]


def get_artifact(
    conn: sqlite3.Connection,
    run_id: str,
    artifact_id: str,
    user_id: int,
) -> dict[str, Any]:
    _owned_run(conn, run_id, user_id)
    row = conn.execute(
        "SELECT * FROM research_artifacts WHERE id = ? AND run_id = ?",
        (artifact_id, run_id),
    ).fetchone()
    if row is None or (row["paper_id"] is not None and not paper_is_accessible(conn, int(row["paper_id"]), user_id)):
        raise ResearchNotFoundError("research artifact not found")
    return _artifact_for_user(conn, row, user_id)


def _artifact_for_user(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    user_id: int,
) -> dict[str, Any]:
    if not _artifact_integrity_valid(row):
        if str(row["status"]) == "completed":
            conn.execute(
                f"UPDATE research_artifacts SET status = 'stale', updated_at = {_NOW} WHERE id = ? AND status = 'completed'",
                (str(row["id"]),),
            )
        result = _artifact_row(row, is_current=False)
        result["status"] = "stale"
        result["content"] = {}
        return result
    result = _artifact_row(row, is_current=_artifact_is_current(conn, row, user_id))
    content = cast(dict[str, Any], result["content"])
    artifact_type = str(result["artifact_type"])
    if artifact_type == "candidate_papers":
        content["items"] = [
            item
            for item in content.get("items", [])
            if isinstance(item, dict)
            and (
                item.get("paper_id") is None
                and str(item.get("source", "")) != "upload"
                or isinstance(item.get("paper_id"), int)
                and paper_is_accessible(conn, int(item["paper_id"]), user_id)
            )
        ]
    elif artifact_type == "screening_result":
        content["items"] = [
            item
            for item in content.get("items", [])
            if isinstance(item, dict)
            and isinstance(item.get("paper_id"), int)
            and paper_is_accessible(conn, int(item["paper_id"]), user_id)
        ]
    elif artifact_type == "extraction_result":
        allowed_ids = {
            int(paper_id)
            for paper_id in content.get("extracted_paper_ids", [])
            if isinstance(paper_id, int) and paper_is_accessible(conn, paper_id, user_id)
        }
        content["extracted_paper_ids"] = [
            paper_id for paper_id in content.get("extracted_paper_ids", []) if paper_id in allowed_ids
        ]
        allowed_artifacts = conn.execute(
            """
            SELECT id, paper_id FROM research_artifacts
            WHERE run_id = ? AND artifact_type = 'paper_brief'
            """,
            (str(result["run_id"]),),
        ).fetchall()
        allowed_artifact_ids = {
            str(item["id"])
            for item in allowed_artifacts
            if item["paper_id"] is not None
            and int(item["paper_id"]) in allowed_ids
        }
        content["paper_brief_artifact_ids"] = [
            artifact_id
            for artifact_id in content.get("paper_brief_artifact_ids", [])
            if artifact_id in allowed_artifact_ids
        ]
    elif artifact_type == "comparison_matrix":
        from .research_citations import _citation_status

        citation_rows = conn.execute("SELECT c.* FROM research_citations c JOIN research_artifacts a ON a.id = c.artifact_id WHERE c.run_id = ? AND a.status = 'completed'", (str(result["run_id"]),)).fetchall()
        matrix_status_by_key: dict[str, set[str]] = {}
        for citation_row in citation_rows:
            matrix_status_by_key.setdefault(str(citation_row["citation_key"]), set()).add(_citation_status(conn, citation_row, user_id))
        inaccessible_keys = {key for key, statuses in matrix_status_by_key.items() if "inaccessible" in statuses}
        nonvalid_keys = {key for key, statuses in matrix_status_by_key.items() if statuses != {"valid"}}
        allowed_papers = {
            int(cast(int, item["paper_id"])) for item in content.get("papers", [])
            if isinstance(item, dict) and isinstance(item.get("paper_id"), int)
            and paper_is_accessible(conn, int(item["paper_id"]), user_id)
        }
        original_papers = {int(cast(int, item["paper_id"])) for item in content.get("papers", []) if isinstance(item, dict) and isinstance(item.get("paper_id"), int)}
        content["papers"] = [item for item in content.get("papers", []) if isinstance(item, dict) and item.get("paper_id") in allowed_papers]
        content["cells"] = [item for item in content.get("cells", []) if isinstance(item, dict) and item.get("paper_id") in allowed_papers and not inaccessible_keys.intersection(item.get("citation_keys", []))]
        content["missing_evidence"] = [item for item in content.get("missing_evidence", []) if isinstance(item, dict) and (item.get("paper_id") is None or item.get("paper_id") in allowed_papers)]
        for field in ("agreements", "disagreements"):
            content[field] = [item for item in content.get(field, []) if isinstance(item, dict) and not inaccessible_keys.intersection(item.get("citation_keys", []))]
        if any(nonvalid_keys.intersection(item.get("citation_keys", [])) for field in ("cells", "agreements", "disagreements") for item in content.get(field, []) if isinstance(item, dict)):
            result["is_current"] = False
        if allowed_papers != original_papers:
            content["agreements"] = []
            content["disagreements"] = []
            result["is_current"] = False
    elif artifact_type == "synthesis_claims":
        from .research_citations import _citation_status

        citation_rows = conn.execute("SELECT c.* FROM research_citations c JOIN research_artifacts a ON a.id = c.artifact_id WHERE c.run_id = ? AND a.status = 'completed'", (str(result["run_id"]),)).fetchall()
        claim_status_by_key: dict[str, set[str]] = {}
        for citation_row in citation_rows:
            claim_status_by_key.setdefault(str(citation_row["citation_key"]), set()).add(_citation_status(conn, citation_row, user_id))
        claims = []
        for item in content.get("claims", []):
            paper_ids = item.get("covered_paper_ids", []) if isinstance(item, dict) else []
            citation_keys = [*item.get("supporting_citations", []), *item.get("contradicting_citations", [])] if isinstance(item, dict) else []
            statuses = {status for key in citation_keys for status in claim_status_by_key.get(str(key), set())}
            factual = isinstance(item, dict) and item.get("claim_type") in {"finding", "agreement", "disagreement"}
            if factual and (not paper_ids or not citation_keys):
                result["is_current"] = False
                continue
            if "inaccessible" not in statuses and all(isinstance(paper_id, int) and paper_is_accessible(conn, paper_id, user_id) for paper_id in paper_ids):
                claims.append(item)
                if statuses and statuses != {"valid"}:
                    result["is_current"] = False
            else:
                result["is_current"] = False
        content["claims"] = claims
    elif artifact_type in {"citation_registry", "research_report"}:
        from .research_citations import _citation_status

        if artifact_type == "citation_registry":
            citation_rows = conn.execute("SELECT * FROM research_citations WHERE artifact_id = ?", (str(result["id"]),)).fetchall()
        else:
            registry_version = int(content.get("generated_from_artifact_versions", {}).get("citation_registry", 0))
            registry = conn.execute("SELECT id FROM research_artifacts WHERE run_id = ? AND artifact_type = 'citation_registry' AND version = ?", (str(result["run_id"]), registry_version)).fetchone()
            citation_rows = conn.execute("SELECT * FROM research_citations WHERE artifact_id = ?", (str(registry["id"]),)).fetchall() if registry else []
        status_by_key = {str(item["citation_key"]): _citation_status(conn, item, user_id) for item in citation_rows}
        inaccessible = {key for key, status in status_by_key.items() if status == "inaccessible"}
        if artifact_type == "citation_registry":
            content["entries"] = [item for item in content.get("entries", []) if isinstance(item, dict) and item.get("citation_key") not in inaccessible]
        elif inaccessible:
            for field in ("executive_summary", "findings", "agreements", "disagreements", "conclusion"):
                content[field] = [item for item in content.get(field, []) if isinstance(item, dict) and not inaccessible.intersection(item.get("citation_keys", []))]
            content["limitations"] = []
            content["research_gaps"] = []
            result["is_current"] = False
    if artifact_type in {"synthesis_plan", "comparison_matrix", "synthesis_claims", "citation_registry", "citation_validation_result", "research_report"} and not result.get("is_current") and result.get("status") == "completed":
        run = conn.execute("SELECT status FROM research_runs WHERE id = ?", (str(result["run_id"]),)).fetchone()
        if run is not None and str(run["status"]) in {"completed", "failed", "cancelled"}:
            conn.execute(f"UPDATE research_artifacts SET status = 'stale', updated_at = {_NOW} WHERE id = ? AND status = 'completed'", (str(result["id"]),))
            result["status"] = "stale"
    return result


def _run_dataset_is_current(conn: sqlite3.Connection, run_id: str, user_id: int) -> bool:
    rows = conn.execute(
        """
        SELECT rp.paper_id, rp.source_hash, p.asset_id, d.source_hash AS document_hash,
               d.status AS document_status
        FROM research_run_papers rp
        JOIN papers p ON p.id = rp.paper_id
        LEFT JOIN paper_documents d ON d.paper_id = p.id
        WHERE rp.run_id = ? AND rp.stage = 'extracted'
        """,
        (run_id,),
    ).fetchall()
    if not rows:
        return False
    for item in rows:
        source_hash = str(item["source_hash"] or "")
        if (
            not paper_is_accessible(conn, int(item["paper_id"]), user_id)
            or str(item["asset_id"] or "").removeprefix("sha256:") != source_hash
            or str(item["document_status"] or "") != "completed"
            or str(item["document_hash"] or "") != source_hash
        ):
            return False
        brief = conn.execute(
            """
            SELECT 1 FROM research_artifacts
            WHERE run_id = ? AND paper_id = ? AND artifact_type = 'paper_brief'
              AND source_hash = ? AND status = 'completed' LIMIT 1
            """,
            (run_id, int(item["paper_id"]), source_hash),
        ).fetchone()
        if brief is None:
            return False
    return True


def _artifact_is_current(conn: sqlite3.Connection, row: sqlite3.Row, user_id: int) -> bool:
    if str(row["status"]) != "completed" or not _artifact_integrity_valid(row):
        return False
    artifact_type = str(row["artifact_type"])
    if artifact_type in {"synthesis_plan", "comparison_matrix", "synthesis_claims", "citation_registry", "citation_validation_result", "research_report"}:
        if not _run_dataset_is_current(conn, str(row["run_id"]), user_id):
            return False
        content = cast(dict[str, Any], _decoded(str(row["content_json"]), {}))
        if artifact_type in {"comparison_matrix", "synthesis_claims"}:
            if artifact_type == "comparison_matrix":
                required_keys = {
                    str(key)
                    for field in ("cells", "agreements", "disagreements")
                    for item in content.get(field, [])
                    if isinstance(item, dict)
                    for key in item.get("citation_keys", [])
                }
            else:
                required_keys = {
                    str(key)
                    for item in content.get("claims", [])
                    if isinstance(item, dict) and item.get("claim_type") in {"finding", "agreement", "disagreement"}
                    for key in [*item.get("supporting_citations", []), *item.get("contradicting_citations", [])]
                }
            registry = conn.execute(
                "SELECT * FROM research_artifacts WHERE run_id = ? AND artifact_type = 'citation_registry' AND status = 'completed' ORDER BY version DESC LIMIT 1",
                (str(row["run_id"]),),
            ).fetchone()
            validation = conn.execute(
                "SELECT * FROM research_artifacts WHERE run_id = ? AND artifact_type = 'citation_validation_result' AND status = 'completed' ORDER BY version DESC LIMIT 1",
                (str(row["run_id"]),),
            ).fetchone()
            if registry is None or validation is None or not _artifact_integrity_valid(registry) or not _artifact_integrity_valid(validation):
                return False
            from .research_citations import _citation_status

            citation_rows = conn.execute(
                "SELECT * FROM research_citations WHERE artifact_id = ?",
                (str(registry["id"]),),
            ).fetchall()
            status_by_key = {str(item["citation_key"]): _citation_status(conn, item, user_id) for item in citation_rows}
            validated_keys = {
                str(key)
                for key in cast(dict[str, Any], _decoded(str(validation["content_json"]), {})).get("valid_citation_keys", [])
            }
            if not required_keys or not required_keys.issubset(validated_keys) or any(status_by_key.get(key) != "valid" for key in required_keys):
                return False
        if artifact_type == "research_report":
            versions = content.get("generated_from_artifact_versions", {})
            if not isinstance(versions, dict):
                return False
            for dependency_type in (
                "synthesis_plan", "comparison_matrix", "synthesis_claims",
                "citation_registry", "citation_validation_result",
            ):
                dependency_version = versions.get(dependency_type)
                if not isinstance(dependency_version, int):
                    return False
                dependency = conn.execute(
                    "SELECT * FROM research_artifacts WHERE run_id = ? AND artifact_type = ? AND version = ?",
                    (str(row["run_id"]), dependency_type, dependency_version),
                ).fetchone()
                latest = conn.execute(
                    "SELECT MAX(version) AS version FROM research_artifacts WHERE run_id = ? AND artifact_type = ? AND status = 'completed'",
                    (str(row["run_id"]), dependency_type),
                ).fetchone()
                if (
                    dependency is None
                    or str(dependency["status"]) != "completed"
                    or not _artifact_integrity_valid(dependency)
                    or latest is None
                    or latest["version"] is None
                    or int(latest["version"]) != dependency_version
                ):
                    return False
        if artifact_type in {"citation_registry", "citation_validation_result", "research_report"}:
            from .research_citations import _citation_status

            if artifact_type == "citation_registry":
                registry_id = str(row["id"])
            else:
                registry_version = int(content.get("generated_from_artifact_versions", {}).get("citation_registry", 0)) if artifact_type == "research_report" else 0
                registry = conn.execute(
                    "SELECT id FROM research_artifacts WHERE run_id = ? AND artifact_type = 'citation_registry' AND version = ?",
                    (str(row["run_id"]), registry_version),
                ).fetchone() if registry_version else None
                if artifact_type == "research_report" and registry is None:
                    return False
                if registry is None:
                    registry = conn.execute(
                        "SELECT id FROM research_artifacts WHERE run_id = ? AND artifact_type = 'citation_registry' ORDER BY version DESC LIMIT 1",
                        (str(row["run_id"]),),
                    ).fetchone()
                if registry is None:
                    return False
                registry_id = str(registry["id"])
            citations = conn.execute("SELECT * FROM research_citations WHERE artifact_id = ?", (registry_id,)).fetchall()
            if not citations or any(_citation_status(conn, item, user_id) != "valid" for item in citations):
                return False
        return True
    if row["paper_id"] is None or row["source_hash"] is None:
        return True
    document = conn.execute(
        """
        SELECT d.source_hash, d.status, p.asset_id
        FROM paper_documents d JOIN papers p ON p.id = d.paper_id
        WHERE d.paper_id = ?
        """,
        (int(row["paper_id"]),),
    ).fetchone()
    return bool(
        str(row["status"]) == "completed"
        and document is not None
        and str(document["status"]) == "completed"
        and str(document["asset_id"] or "").removeprefix("sha256:") == str(row["source_hash"])
        and str(document["source_hash"] or "") == str(row["source_hash"])
    )


def get_paper_brief(
    conn: sqlite3.Connection,
    run_id: str,
    paper_id: int,
    user_id: int,
) -> dict[str, Any]:
    _owned_run(conn, run_id, user_id)
    if not paper_is_accessible(conn, paper_id, user_id):
        raise ResearchNotFoundError("research paper not found")
    row = conn.execute(
        """
        SELECT * FROM research_artifacts
        WHERE run_id = ? AND paper_id = ? AND artifact_type = 'paper_brief'
        ORDER BY version DESC LIMIT 1
        """,
        (run_id, paper_id),
    ).fetchone()
    if row is None:
        raise ResearchNotFoundError("paper brief not found")
    return _artifact_row(row, is_current=_artifact_is_current(conn, row, user_id))


def upsert_run_paper(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    source_step_id: str,
    worker_id: str,
    lease_generation: int,
    paper_id: int,
    stage: str,
    rank: int | None = None,
    score: float | None = None,
    inclusion_reason: str | None = None,
    exclusion_reason: str | None = None,
    source_hash: str | None = None,
    manage_transaction: bool = True,
) -> dict[str, Any]:
    if stage not in {*_STAGE_ORDER, "excluded"}:
        raise ValueError("unsupported research paper stage")
    if score is not None and not 0 <= score <= 1:
        raise ValueError("research paper score must be between zero and one")
    if stage == "excluded" and not (exclusion_reason or "").strip():
        raise ValueError("excluded research paper requires a reason")
    if stage in {"fulltext_ready", "read", "extracted"} and not re.fullmatch(r"[0-9a-f]{64}", source_hash or ""):
        raise ValueError("research paper source hash is invalid")
    assert_safe_research_payload(inclusion_reason or "")
    assert_safe_research_payload(exclusion_reason or "")
    if manage_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        lease = _active_lease(
            conn,
            run_id=run_id,
            step_id=source_step_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        if not paper_is_accessible(conn, paper_id, int(lease["user_id"])):
            raise ResearchNotFoundError("research paper not found")
        paper = conn.execute(
            "SELECT source, source_id, asset_id FROM papers WHERE id = ?",
            (paper_id,),
        ).fetchone()
        if paper is None:
            raise ResearchNotFoundError("research paper not found")
        if stage in {"fulltext_ready", "read", "extracted"}:
            document = conn.execute(
                "SELECT source_hash, status FROM paper_documents WHERE paper_id = ?",
                (paper_id,),
            ).fetchone()
            chunk = conn.execute(
                "SELECT 1 FROM paper_chunks WHERE paper_id = ? AND source_hash = ? LIMIT 1",
                (paper_id, source_hash),
            ).fetchone()
            if (
                str(paper["asset_id"] or "").removeprefix("sha256:") != source_hash
                or document is None
                or str(document["status"]) != "completed"
                or str(document["source_hash"] or "") != source_hash
                or chunk is None
            ):
                raise ResearchConflictError("research paper document hash is stale")
        existing = conn.execute(
            "SELECT * FROM research_run_papers WHERE run_id = ? AND paper_id = ?",
            (run_id, paper_id),
        ).fetchone()
        effective_inclusion = inclusion_reason or (str(existing["inclusion_reason"]) if existing and existing["inclusion_reason"] else "")
        if stage in {"selected", "fulltext_ready", "read", "extracted"} and not effective_inclusion.strip():
            raise ValueError("selected research paper requires a reason")
        if existing is not None:
            current_stage = str(existing["stage"])
            if current_stage == "excluded" and stage != "excluded":
                raise ResearchConflictError("excluded research paper cannot advance")
            if stage == "excluded" and current_stage != "candidate":
                raise ResearchConflictError("only a candidate paper can be excluded")
            if stage != "excluded" and current_stage != "excluded":
                stage = current_stage if _STAGE_ORDER[current_stage] > _STAGE_ORDER[stage] else stage
            target_values = (
                source_step_id,
                stage,
                rank if rank is not None else existing["rank"],
                score if score is not None else existing["score"],
                inclusion_reason if inclusion_reason is not None else existing["inclusion_reason"],
                exclusion_reason if exclusion_reason is not None else existing["exclusion_reason"],
                source_hash if source_hash is not None else existing["source_hash"],
            )
            current_values = (
                str(existing["source_step_id"] or ""),
                current_stage,
                existing["rank"],
                existing["score"],
                existing["inclusion_reason"],
                existing["exclusion_reason"],
                existing["source_hash"],
            )
            if target_values == current_values:
                if manage_transaction:
                    conn.commit()
                return dict(existing)
            conn.execute(
                f"""
                UPDATE research_run_papers
                SET source_step_id = ?, stage = ?, rank = COALESCE(?, rank),
                    score = COALESCE(?, score),
                    inclusion_reason = COALESCE(?, inclusion_reason),
                    exclusion_reason = COALESCE(?, exclusion_reason),
                    source_hash = COALESCE(?, source_hash), updated_at = {_NOW}
                WHERE run_id = ? AND paper_id = ?
                """,
                (
                    source_step_id,
                    stage,
                    rank,
                    score,
                    inclusion_reason,
                    exclusion_reason,
                    source_hash,
                    run_id,
                    paper_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO research_run_papers(
                    run_id, paper_id, source_step_id, stage, rank, score,
                    inclusion_reason, exclusion_reason, source, source_id, source_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    paper_id,
                    source_step_id,
                    stage,
                    rank,
                    score,
                    inclusion_reason,
                    exclusion_reason,
                    str(paper["source"]),
                    str(paper["source_id"]),
                    source_hash,
                ),
            )
        row = conn.execute(
            "SELECT * FROM research_run_papers WHERE run_id = ? AND paper_id = ?",
            (run_id, paper_id),
        ).fetchone()
        count_row = conn.execute(
            "SELECT COUNT(*) AS count FROM research_run_papers WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        usage = _decoded(str(lease["usage_json"]), dict(DEFAULT_TOPIC_USAGE))
        usage["candidate_papers"] = int(count_row["count"] if count_row else 0)
        fulltext_row = conn.execute(
            """
            SELECT COUNT(*) AS count FROM research_run_papers
            WHERE run_id = ? AND stage IN ('fulltext_ready', 'read', 'extracted')
            """,
            (run_id,),
        ).fetchone()
        usage["fulltext_papers"] = int(fulltext_row["count"] if fulltext_row else 0)
        conn.execute(
            f"UPDATE research_runs SET usage_json = ?, state_version = state_version + 1, updated_at = {_NOW} WHERE id = ?",
            (_json(usage), run_id),
        )
        conn.execute(
            """
            INSERT INTO research_events(run_id, step_id, event_type, summary, payload_json)
            VALUES (?, ?, 'paper.updated', '调研论文阶段已更新', ?)
            """,
            (run_id, source_step_id, _json({"paper_id": paper_id, "stage": stage})),
        )
        if manage_transaction:
            conn.commit()
        if row is None:
            raise RuntimeError("research paper association disappeared")
        return dict(row)
    except Exception:
        if manage_transaction:
            conn.rollback()
        raise


def list_run_papers(
    conn: sqlite3.Connection,
    run_id: str,
    user_id: int,
    *,
    stage: str | None = None,
) -> list[dict[str, Any]]:
    _owned_run(conn, run_id, user_id)
    access_sql, access_params = accessible_paper_condition("p", user_id)
    clauses = ["rp.run_id = ?", access_sql]
    params: list[Any] = [run_id, *access_params]
    if stage is not None:
        clauses.append("rp.stage = ?")
        params.append(stage)
    rows = conn.execute(
        f"""
        SELECT rp.*, p.title, p.authors_json, p.abstract, p.published_at,
               p.primary_category, p.source_url, p.processing_status
        FROM research_run_papers rp JOIN papers p ON p.id = rp.paper_id
        WHERE {' AND '.join(clauses)}
        ORDER BY CASE WHEN rp.rank IS NULL THEN 1 ELSE 0 END, rp.rank, rp.score DESC, rp.paper_id
        """,
        tuple(params),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["authors"] = _decoded(str(item.pop("authors_json")), [])
        result.append(item)
    return result


def reserve_budget(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    step_id: str,
    worker_id: str,
    lease_generation: int,
    kind: str,
    amount: int = 1,
) -> bool:
    if kind not in _LIMIT_KEYS or amount < 1:
        raise ValueError("unsupported budget kind")
    conn.execute("BEGIN IMMEDIATE")
    try:
        lease = _active_lease(
            conn,
            run_id=run_id,
            step_id=step_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        budget = _decoded(str(lease["budget_json"]), dict(DEFAULT_TOPIC_BUDGET))
        usage = _decoded(str(lease["usage_json"]), dict(DEFAULT_TOPIC_USAGE))
        elapsed_row = conn.execute(
            "SELECT MAX(0, CAST((julianday('now') - julianday(created_at)) * 86400 AS INTEGER)) AS seconds FROM research_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        elapsed = int(elapsed_row["seconds"] if elapsed_row else 0)
        usage["wall_clock_seconds"] = elapsed
        limit_key = _LIMIT_KEYS[kind]
        if elapsed >= int(budget.get("max_wall_clock_seconds", 1_800)) or int(usage.get(kind, 0)) + amount > int(budget.get(limit_key, 0)):
            _wait_for_budget(conn, lease, kind, budget, usage)
            conn.commit()
            return False
        usage[kind] = int(usage.get(kind, 0)) + amount
        conn.execute(
            f"UPDATE research_runs SET usage_json = ?, state_version = state_version + 1, updated_at = {_NOW} WHERE id = ?",
            (_json(usage), run_id),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def authorize_budget_item(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    step_id: str,
    worker_id: str,
    lease_generation: int,
    kind: str,
) -> bool:
    if kind not in {"candidate_papers", "fulltext_papers"}:
        raise ValueError("unsupported item budget kind")
    conn.execute("BEGIN IMMEDIATE")
    try:
        lease = _active_lease(
            conn,
            run_id=run_id,
            step_id=step_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        budget = _decoded(str(lease["budget_json"]), dict(DEFAULT_TOPIC_BUDGET))
        usage = _decoded(str(lease["usage_json"]), dict(DEFAULT_TOPIC_USAGE))
        if kind == "candidate_papers":
            count_row = conn.execute(
                "SELECT COUNT(*) AS count FROM research_run_papers WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        else:
            count_row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM research_run_papers
                WHERE run_id = ? AND stage IN ('fulltext_ready', 'read', 'extracted')
                """,
                (run_id,),
            ).fetchone()
        count = int(count_row["count"] if count_row else 0)
        usage[kind] = count
        limit = int(budget.get(_LIMIT_KEYS[kind], 0))
        if count + 1 > limit:
            _wait_for_budget(conn, lease, kind, budget, usage)
            conn.commit()
            return False
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def assert_active_tool_context(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    step_id: str,
    worker_id: str,
    lease_generation: int,
    user_id: int,
) -> None:
    lease = _active_lease(
        conn,
        run_id=run_id,
        step_id=step_id,
        worker_id=worker_id,
        lease_generation=lease_generation,
    )
    if int(lease["user_id"]) != user_id:
        raise ResearchNotFoundError("research run not found")


def settle_budget_call(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    step_id: str,
    worker_id: str,
    lease_generation: int,
    succeeded: bool,
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        lease = _active_lease(
            conn,
            run_id=run_id,
            step_id=step_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        usage = _decoded(str(lease["usage_json"]), dict(DEFAULT_TOPIC_USAGE))
        key = "successful_calls" if succeeded else "failed_calls"
        usage[key] = int(usage.get(key, 0)) + 1
        conn.execute(
            f"UPDATE research_runs SET usage_json = ?, state_version = state_version + 1, updated_at = {_NOW} WHERE id = ?",
            (_json(usage), run_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def begin_model_call(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    step_id: str,
    worker_id: str,
    lease_generation: int,
    idempotency_key: str,
    model_name: str,
    input_payload: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    assert_safe_research_payload(input_payload)
    input_hash = hashlib.sha256(_json(input_payload).encode("utf-8")).hexdigest()
    conn.execute("BEGIN IMMEDIATE")
    try:
        lease = _active_lease(conn, run_id=run_id, step_id=step_id, worker_id=worker_id, lease_generation=lease_generation)
        existing = conn.execute("SELECT * FROM research_model_calls WHERE run_id = ? AND idempotency_key = ?", (run_id, idempotency_key)).fetchone()
        if existing is not None:
            if str(existing["model_name"]) != model_name or str(existing["input_hash"]) != input_hash:
                raise ResearchConflictError("model operation identity conflict")
            status = str(existing["status"])
            if status == "completed":
                conn.commit()
                return "completed", cast(dict[str, Any], _decoded(str(existing["result_json"]), {}))
            if status in {"started", "ambiguous"}:
                conn.execute(f"UPDATE research_model_calls SET status = 'ambiguous', updated_at = {_NOW} WHERE id = ?", (str(existing["id"]),))
                conn.commit()
                raise ResearchConflictError("model call outcome is ambiguous; automatic retry is blocked")
            raise ResearchConflictError("failed model call slot cannot be dispatched twice")
        budget = _decoded(str(lease["budget_json"]), dict(DEFAULT_TOPIC_BUDGET))
        usage = _decoded(str(lease["usage_json"]), dict(DEFAULT_TOPIC_USAGE))
        elapsed_row = conn.execute(
            "SELECT MAX(0, CAST((julianday('now') - julianday(created_at)) * 86400 AS INTEGER)) AS seconds FROM research_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        elapsed = int(elapsed_row["seconds"] if elapsed_row else 0)
        usage["wall_clock_seconds"] = elapsed
        if elapsed >= int(budget.get("max_wall_clock_seconds", 1_800)) or int(usage.get("model_calls", 0)) + 1 > int(budget.get("max_model_calls", 0)):
            _wait_for_budget(conn, lease, "model_calls", budget, usage)
            conn.commit()
            return "waiting", None
        usage["model_calls"] = int(usage.get("model_calls", 0)) + 1
        conn.execute(
            "INSERT INTO research_model_calls(id, run_id, step_id, idempotency_key, model_name, input_hash, status) VALUES (?, ?, ?, ?, ?, ?, 'started')",
            (str(uuid.uuid4()), run_id, step_id, idempotency_key, model_name, input_hash),
        )
        conn.execute(
            f"UPDATE research_runs SET usage_json = ?, state_version = state_version + 1, updated_at = {_NOW} WHERE id = ?",
            (_json(usage), run_id),
        )
        conn.commit()
        return "started", None
    except Exception:
        conn.rollback()
        raise


def complete_model_call(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    step_id: str,
    worker_id: str,
    lease_generation: int,
    idempotency_key: str,
    result: dict[str, Any] | None,
    succeeded: bool,
) -> None:
    if result is not None:
        assert_safe_research_payload(result)
    conn.execute("BEGIN IMMEDIATE")
    try:
        _active_lease(conn, run_id=run_id, step_id=step_id, worker_id=worker_id, lease_generation=lease_generation)
        cursor = conn.execute(
            f"UPDATE research_model_calls SET status = ?, result_json = ?, updated_at = {_NOW} WHERE run_id = ? AND idempotency_key = ? AND status = 'started'",
            ("completed" if succeeded else "failed", _json(result) if result is not None else None, run_id, idempotency_key),
        )
        if cursor.rowcount != 1:
            raise ResearchConflictError("model call slot is no longer writable")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _wait_for_budget(
    conn: sqlite3.Connection,
    lease: sqlite3.Row,
    kind: str,
    budget: dict[str, Any],
    usage: dict[str, Any],
) -> None:
    run_id = str(lease["run_id"])
    step_id = str(lease["id"])
    existing = conn.execute(
        "SELECT id FROM research_decisions WHERE run_id = ? AND status = 'pending'",
        (run_id,),
    ).fetchone()
    if existing is None:
        decision_id = str(uuid.uuid4())
        options = [
            {"id": "continue", "label": "继续并提高预算", "description": "仅提高本项受控上限后从当前检查点继续。", "action": "increase_budget", "budget_kind": kind},
            {"id": "narrow_scope", "label": "缩小范围（推荐）", "description": "冻结当前候选/全文规模，只允许完成当前收尾。", "action": "narrow_scope", "budget_kind": kind},
            {"id": "stop", "label": "停止任务", "description": "安全停止未开始步骤，保留已完成数据。", "action": "stop", "budget_kind": kind},
        ]
        conn.execute(
            """
            INSERT INTO research_decisions(
                id, run_id, step_id, question, options_json, recommended_option
            ) VALUES (?, ?, ?, ?, ?, 'narrow_scope')
            """,
            (decision_id, run_id, step_id, "继续执行将超过本次调研预算，请选择下一步。", _json(options)),
        )
        conn.execute(
            """
            INSERT INTO research_events(run_id, step_id, event_type, summary, payload_json)
            VALUES (?, ?, 'decision.requested', '调研预算需要确认', ?)
            """,
            (run_id, step_id, _json({"decision_id": decision_id, "budget_kind": kind})),
        )
    conn.execute(
        f"""
        UPDATE research_steps
        SET status = 'waiting_input', lease_owner = NULL, lease_expires_at = NULL,
            heartbeat_at = NULL, updated_at = {_NOW}
        WHERE id = ? AND status = 'running' AND lease_owner = ? AND lease_generation = ?
        """,
        (step_id, str(lease["lease_owner"]), int(lease["lease_generation"])),
    )
    conn.execute(
        f"""
        UPDATE research_runs
        SET status = 'waiting_input', usage_json = ?, state_version = state_version + 1,
            updated_at = {_NOW}
        WHERE id = ?
        """,
        (_json(usage), run_id),
    )


def apply_budget_decision(
    conn: sqlite3.Connection,
    *,
    decision_row: sqlite3.Row,
    option: dict[str, Any],
) -> str:
    run_id = str(decision_row["run_id"])
    action = str(option.get("action", ""))
    kind = str(option.get("budget_kind", ""))
    row = conn.execute(
        "SELECT budget_json, usage_json FROM research_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None or kind not in _LIMIT_KEYS:
        raise ResearchConflictError("budget decision is invalid")
    budget = _decoded(str(row["budget_json"]), dict(DEFAULT_TOPIC_BUDGET))
    usage = _decoded(str(row["usage_json"]), dict(DEFAULT_TOPIC_USAGE))
    limit_key = _LIMIT_KEYS[kind]
    if action == "stop":
        return "stop"
    if action == "increase_budget":
        increments = {"candidate_papers": 10, "fulltext_papers": 3, "model_calls": 10, "tool_calls": 25}
        budget[limit_key] = int(budget.get(limit_key, 0)) + increments[kind]
        elapsed_row = conn.execute(
            "SELECT MAX(0, CAST((julianday('now') - julianday(created_at)) * 86400 AS INTEGER)) AS seconds FROM research_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        elapsed = int(elapsed_row["seconds"] if elapsed_row else 0)
        budget["max_wall_clock_seconds"] = max(
            int(budget.get("max_wall_clock_seconds", 1_800)) + 900,
            elapsed + 900,
        )
    elif action == "narrow_scope":
        budget["max_candidates"] = max(1, int(usage.get("candidate_papers", 0)))
        budget["max_fulltext_papers"] = max(1, int(usage.get("fulltext_papers", 0)))
        budget[limit_key] = int(usage.get(kind, 0)) + 1
    else:
        raise ResearchConflictError("budget decision action is invalid")
    conn.execute(
        f"UPDATE research_runs SET budget_json = ?, updated_at = {_NOW} WHERE id = ?",
        (_json(budget), run_id),
    )
    return "resume"


def wait_for_evidence_coverage(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    step_id: str,
    worker_id: str,
    lease_generation: int,
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        lease = _active_lease(conn, run_id=run_id, step_id=step_id, worker_id=worker_id, lease_generation=lease_generation)
        existing = conn.execute("SELECT 1 FROM research_decisions WHERE run_id = ? AND status = 'pending'", (run_id,)).fetchone()
        if existing is None:
            decision_id = str(uuid.uuid4())
            options = [
                {"id": "continue_reading", "label": "继续读取论文（推荐）", "description": "从当前 source hash 重新打开证据并抽取 PaperBrief。", "action": "coverage_continue_reading"},
                {"id": "stop", "label": "停止任务", "description": "保留已完成数据，不生成无证据报告。", "action": "coverage_stop"},
            ]
            conn.execute(
                "INSERT INTO research_decisions(id, run_id, step_id, question, options_json, recommended_option) VALUES (?, ?, ?, '当前没有足够的有效 Citation 生成研究报告，请选择下一步。', ?, 'continue_reading')",
                (decision_id, run_id, step_id, _json(options)),
            )
            conn.execute(
                "INSERT INTO research_events(run_id, step_id, event_type, summary, payload_json) VALUES (?, ?, 'decision.requested', '引用覆盖需要确认', ?)",
                (run_id, step_id, _json({"decision_id": decision_id, "kind": "evidence_coverage"})),
            )
        conn.execute(
            f"UPDATE research_steps SET status = 'waiting_input', lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = NULL, updated_at = {_NOW} WHERE id = ? AND lease_owner = ? AND lease_generation = ?",
            (step_id, str(lease["lease_owner"]), int(lease["lease_generation"])),
        )
        conn.execute(f"UPDATE research_runs SET status = 'waiting_input', state_version = state_version + 1, updated_at = {_NOW} WHERE id = ?", (run_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def apply_coverage_decision(conn: sqlite3.Connection, *, decision_row: sqlite3.Row, option: dict[str, Any]) -> str:
    run_id = str(decision_row["run_id"])
    action = str(option.get("action", ""))
    if action == "coverage_stop":
        return "stop"
    if action != "coverage_continue_reading":
        raise ResearchConflictError("evidence coverage decision action is invalid")
    generation = uuid.uuid4().hex[:12]
    conn.execute(
        f"""
        UPDATE research_steps SET status = 'queued', completed_at = NULL, output_json = '{{}}',
            idempotency_key = 'topic:' || step_key || ':coverage:{generation}',
            max_attempts = max_attempts + 1, updated_at = {_NOW}
        WHERE run_id = ? AND step_key IN ('reading', 'extraction', 'finalize_dataset')
        """,
        (run_id,),
    )
    conn.execute(
        f"UPDATE research_run_papers SET stage = 'fulltext_ready', updated_at = {_NOW} WHERE run_id = ? AND stage IN ('read', 'extracted')",
        (run_id,),
    )
    conn.execute(
        f"UPDATE research_artifacts SET status = 'stale', updated_at = {_NOW} WHERE run_id = ? AND artifact_type IN ('paper_brief', 'extraction_result', 'synthesis_plan', 'comparison_matrix', 'synthesis_claims', 'citation_registry', 'citation_validation_result', 'research_report') AND status = 'completed'",
        (run_id,),
    )
    conn.execute(f"UPDATE research_citations SET status = 'stale', updated_at = {_NOW} WHERE run_id = ?", (run_id,))
    return "resume"

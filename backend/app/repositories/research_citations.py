from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any, cast

from ..repositories.uploads import paper_is_accessible
from ..services.research_contracts import CitationRegistry
from .research import ResearchConflictError, ResearchNotFoundError
from .research_data import _active_lease, _artifact_row, _json, _owned_run, assert_safe_research_payload


_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


def _quote_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _evidence_status(conn: sqlite3.Connection, row: sqlite3.Row, user_id: int) -> str:
    paper_id = int(row["paper_id"])
    if not paper_is_accessible(conn, paper_id, user_id):
        return "inaccessible"
    current = conn.execute(
        """
        SELECT p.source, p.source_id, p.asset_id, d.id AS document_id, d.source_hash AS document_hash,
               d.status AS document_status, rp.source_hash AS run_hash,
               pc.document_id AS chunk_document_id, pc.source_hash AS chunk_hash,
               pc.heading, pc.char_start, pc.char_end, pc.content
        FROM papers p
        JOIN paper_documents d ON d.paper_id = p.id
        JOIN research_run_papers rp ON rp.paper_id = p.id AND rp.run_id = ?
        JOIN paper_chunks pc ON pc.id = ? AND pc.paper_id = p.id
        WHERE p.id = ?
        """,
        (str(row["run_id"]), int(row["chunk_id"]), paper_id),
    ).fetchone()
    if current is None:
        return "stale"
    expected_hash = str(row["source_hash"])
    if (
        str(current["source"]) != str(row["source"])
        or str(current["source_id"]) != str(row["source_id"])
        or str(current["asset_id"] or "").removeprefix("sha256:") != expected_hash
        or str(current["document_status"]) != "completed"
        or str(current["document_hash"] or "") != expected_hash
        or str(current["run_hash"] or "") != expected_hash
        or int(current["chunk_document_id"]) != int(current["document_id"])
        or str(current["chunk_hash"] or "") != expected_hash
        or str(current["heading"]) != str(row["heading"])
        or int(current["char_start"]) != int(row["char_start"])
        or int(current["char_end"]) != int(row["char_end"])
        or _quote_hash(str(current["content"])) != str(row["quote_hash"])
    ):
        return "stale"
    return "valid"


def register_opened_evidence(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    step_id: str,
    worker_id: str,
    lease_generation: int,
    user_id: int,
    chunk_id: int,
) -> dict[str, Any]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        lease = _active_lease(
            conn, run_id=run_id, step_id=step_id, worker_id=worker_id,
            lease_generation=lease_generation,
        )
        if int(lease["user_id"]) != user_id:
            raise ResearchNotFoundError("research evidence not found")
        row = conn.execute(
            """
            SELECT pc.*, p.source, p.source_id, p.asset_id,
                   d.source_hash AS document_hash, d.status AS document_status,
                   rp.source_hash AS run_hash
            FROM paper_chunks pc
            JOIN papers p ON p.id = pc.paper_id
            JOIN paper_documents d ON d.paper_id = p.id
            JOIN research_run_papers rp ON rp.paper_id = p.id AND rp.run_id = ?
            WHERE pc.id = ? AND rp.stage IN ('fulltext_ready', 'read', 'extracted')
            """,
            (run_id, chunk_id),
        ).fetchone()
        if row is None or not paper_is_accessible(conn, int(row["paper_id"]), user_id):
            raise ResearchNotFoundError("research evidence not found")
        source_hash = str(row["source_hash"])
        if (
            str(row["asset_id"] or "").removeprefix("sha256:") != source_hash
            or str(row["document_status"]) != "completed"
            or str(row["document_hash"] or "") != source_hash
            or str(row["run_hash"] or "") != source_hash
        ):
            raise ResearchConflictError("research evidence source hash is stale")
        fingerprint = f"{run_id}:{chunk_id}:{source_hash}:{int(row['char_start'])}:{int(row['char_end'])}"
        evidence_id = f"EV-{hashlib.sha256(fingerprint.encode()).hexdigest()[:24]}"
        quote_hash = _quote_hash(str(row["content"]))
        conn.execute(
            """
            INSERT INTO research_evidence(
                id, run_id, opened_by_step_id, paper_id, chunk_id, source, source_id,
                source_hash, heading, char_start, char_end, quote_hash, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'valid')
            ON CONFLICT(run_id, chunk_id, source_hash, char_start, char_end) DO UPDATE SET
                opened_by_step_id = excluded.opened_by_step_id,
                quote_hash = excluded.quote_hash, status = 'valid', updated_at = CURRENT_TIMESTAMP
            """,
            (
                evidence_id, run_id, step_id, int(row["paper_id"]), chunk_id,
                str(row["source"]), str(row["source_id"]), source_hash,
                str(row["heading"]), int(row["char_start"]), int(row["char_end"]), quote_hash,
            ),
        )
        stored = conn.execute("SELECT * FROM research_evidence WHERE id = ?", (evidence_id,)).fetchone()
        conn.commit()
        if stored is None:
            raise RuntimeError("research evidence disappeared")
        result = dict(stored)
        result["chunk_index"] = int(row["chunk_index"])
        result["content"] = str(row["content"])
        return result
    except Exception:
        conn.rollback()
        raise


def list_current_evidence(conn: sqlite3.Connection, run_id: str, user_id: int) -> list[dict[str, Any]]:
    _owned_run(conn, run_id, user_id)
    rows = conn.execute("SELECT * FROM research_evidence WHERE run_id = ? ORDER BY paper_id, chunk_id", (run_id,)).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        status = _evidence_status(conn, row, user_id)
        if status != str(row["status"]):
            conn.execute(f"UPDATE research_evidence SET status = ?, updated_at = {_NOW} WHERE id = ?", (status, str(row["id"])))
        item = dict(row)
        item["status"] = status
        result.append(item)
    conn.commit()
    return result


def create_citation_registry(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    source_step_id: str,
    worker_id: str,
    lease_generation: int,
    content: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    registry = CitationRegistry.model_validate(content)
    validated = registry.model_dump(mode="json")
    assert_safe_research_payload(validated)
    encoded = _json(validated)
    content_hash = hashlib.sha256(encoded.encode()).hexdigest()
    conn.execute("BEGIN IMMEDIATE")
    try:
        lease = _active_lease(
            conn, run_id=run_id, step_id=source_step_id, worker_id=worker_id,
            lease_generation=lease_generation,
        )
        user_id = int(lease["user_id"])
        existing = conn.execute(
            "SELECT * FROM research_artifacts WHERE run_id = ? AND idempotency_key = ?",
            (run_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            if str(existing["content_hash"]) != content_hash:
                raise ResearchConflictError("citation registry idempotency content conflict")
            conn.commit()
            return _artifact_row(existing)
        evidence_by_id: dict[str, sqlite3.Row] = {}
        for entry in registry.entries:
            evidence = conn.execute(
                "SELECT * FROM research_evidence WHERE id = ? AND run_id = ? AND paper_id = ?",
                (entry.evidence_id, run_id, entry.paper_id),
            ).fetchone()
            if evidence is None or _evidence_status(conn, evidence, user_id) != "valid":
                raise ResearchConflictError("citation evidence is not current and valid")
            evidence_by_id[entry.evidence_id] = cast(sqlite3.Row, evidence)
        version = int(conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM research_artifacts WHERE run_id = ? AND artifact_type = 'citation_registry'",
            (run_id,),
        ).fetchone()[0])
        artifact_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO research_artifacts(
                id, run_id, artifact_type, schema_version, source_step_id, version,
                status, content_json, idempotency_key, content_hash
            ) VALUES (?, ?, 'citation_registry', 1, ?, ?, 'completed', ?, ?, ?)
            """,
            (artifact_id, run_id, source_step_id, version, encoded, idempotency_key, content_hash),
        )
        for entry in registry.entries:
            evidence = evidence_by_id[entry.evidence_id]
            conn.execute(
                """
                INSERT INTO research_citations(
                    id, run_id, artifact_id, artifact_version, citation_key, claim_id,
                    paper_id, chunk_id, evidence_id, source, source_id, source_hash,
                    heading, char_start, char_end, quote_hash, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'valid')
                """,
                (
                    str(uuid.uuid4()), run_id, artifact_id, version, entry.citation_key,
                    entry.claim_id, entry.paper_id, int(evidence["chunk_id"]), entry.evidence_id,
                    str(evidence["source"]), str(evidence["source_id"]), str(evidence["source_hash"]),
                    str(evidence["heading"]), int(evidence["char_start"]), int(evidence["char_end"]),
                    str(evidence["quote_hash"]),
                ),
            )
        conn.execute(
            "INSERT INTO research_events(run_id, step_id, event_type, summary, payload_json) VALUES (?, ?, 'citation.registered', ?, ?)",
            (run_id, source_step_id, f"已登记 {len(registry.entries)} 条可追溯引用", _json({"artifact_id": artifact_id, "version": version, "citation_count": len(registry.entries)})),
        )
        conn.execute(f"UPDATE research_runs SET state_version = state_version + 1, updated_at = {_NOW} WHERE id = ?", (run_id,))
        created = conn.execute("SELECT * FROM research_artifacts WHERE id = ?", (artifact_id,)).fetchone()
        conn.commit()
        if created is None:
            raise RuntimeError("citation registry disappeared")
        return _artifact_row(created)
    except Exception:
        conn.rollback()
        raise


def _citation_status(conn: sqlite3.Connection, row: sqlite3.Row, user_id: int) -> str:
    evidence = conn.execute("SELECT * FROM research_evidence WHERE id = ?", (str(row["evidence_id"]),)).fetchone()
    if evidence is None:
        return "invalid"
    status = _evidence_status(conn, evidence, user_id)
    if status != "valid":
        return status
    for key in ("run_id", "paper_id", "chunk_id", "source", "source_id", "source_hash", "heading", "char_start", "char_end", "quote_hash"):
        if str(row[key]) != str(evidence[key]):
            return "invalid"
    artifact = conn.execute("SELECT run_id, artifact_type, version, status, content_json, content_hash FROM research_artifacts WHERE id = ?", (str(row["artifact_id"]),)).fetchone()
    if artifact is None or str(artifact["run_id"]) != str(row["run_id"]) or str(artifact["artifact_type"]) != "citation_registry" or int(artifact["version"]) != int(row["artifact_version"]):
        return "invalid"
    encoded = str(artifact["content_json"])
    if hashlib.sha256(encoded.encode("utf-8")).hexdigest() != str(artifact["content_hash"]):
        return "invalid"
    try:
        registry = CitationRegistry.model_validate_json(encoded)
    except Exception:
        return "invalid"
    entry = next((item for item in registry.entries if item.citation_key == str(row["citation_key"])), None)
    if entry is None or entry.claim_id != str(row["claim_id"]) or entry.paper_id != int(row["paper_id"]) or entry.evidence_id != str(row["evidence_id"]):
        return "invalid"
    if str(artifact["status"]) == "stale":
        return "stale"
    if str(artifact["status"]) != "completed":
        return "invalid"
    return "valid"


def list_citations(conn: sqlite3.Connection, run_id: str, user_id: int) -> list[dict[str, Any]]:
    _owned_run(conn, run_id, user_id)
    rows = conn.execute("SELECT * FROM research_citations WHERE run_id = ? ORDER BY artifact_version DESC, citation_key", (run_id,)).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        status = _citation_status(conn, row, user_id)
        if status != str(row["status"]):
            conn.execute(f"UPDATE research_citations SET status = ?, updated_at = {_NOW} WHERE id = ?", (status, str(row["id"])))
        if status == "inaccessible":
            result.append({"id": str(row["id"]), "status": status})
        else:
            item = dict(row)
            item["status"] = status
            result.append(item)
    conn.commit()
    return result


def get_citation(conn: sqlite3.Connection, run_id: str, citation_id: str, user_id: int) -> dict[str, Any]:
    _owned_run(conn, run_id, user_id)
    row = conn.execute("SELECT * FROM research_citations WHERE id = ? AND run_id = ?", (citation_id, run_id)).fetchone()
    if row is None or _citation_status(conn, row, user_id) == "inaccessible":
        raise ResearchNotFoundError("research citation not found")
    item = dict(row)
    item["status"] = _citation_status(conn, row, user_id)
    return item


def get_citation_evidence(conn: sqlite3.Connection, run_id: str, citation_id: str, user_id: int) -> dict[str, Any]:
    conn.execute("BEGIN")
    try:
        _owned_run(conn, run_id, user_id)
        row = conn.execute("SELECT * FROM research_citations WHERE id = ? AND run_id = ?", (citation_id, run_id)).fetchone()
        if row is None:
            raise ResearchNotFoundError("research citation not found")
        status = _citation_status(conn, row, user_id)
        if status == "inaccessible":
            raise ResearchNotFoundError("research citation not found")
        citation = dict(row)
        citation["status"] = status
        if status != "valid":
            conn.commit()
            return {**citation, "excerpt": None}
        chunk = conn.execute("SELECT content FROM paper_chunks WHERE id = ? AND paper_id = ? AND source_hash = ?", (int(row["chunk_id"]), int(row["paper_id"]), str(row["source_hash"]))).fetchone()
        if chunk is None or _quote_hash(str(chunk["content"])) != str(row["quote_hash"]):
            conn.commit()
            return {**citation, "status": "stale", "excerpt": None}
        excerpt = str(chunk["content"])[:2400]
        conn.commit()
        return {**citation, "excerpt": excerpt}
    except Exception:
        conn.rollback()
        raise


def request_report_regeneration(conn: sqlite3.Connection, run_id: str, user_id: int) -> dict[str, Any]:
    generation = uuid.uuid4().hex[:16]
    downstream = (
        "synthesis_planning", "comparison_matrix", "cross_paper_claims", "citation_registry",
        "citation_verification", "report_generation", "finalize_cited_report",
    )
    conn.execute("BEGIN IMMEDIATE")
    try:
        run = _owned_run(conn, run_id, user_id)
        if str(run["mode"]) != "topic" or str(run["status"]) not in {"completed", "failed"}:
            raise ResearchConflictError("research report can only be regenerated from a terminal topic run")
        placeholders = ",".join("?" for _ in downstream)
        conn.execute(
            f"""
            UPDATE research_steps
            SET status = 'queued', output_json = '{{}}',
                lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                idempotency_key = 'topic:' || step_key || ':regen:{generation}',
                completed_at = NULL, max_attempts = max_attempts + 1, updated_at = {_NOW}
            WHERE run_id = ? AND step_key IN ({placeholders})
            """,
            (run_id, *downstream),
        )
        artifact_types = ("synthesis_plan", "comparison_matrix", "synthesis_claims", "citation_registry", "citation_validation_result", "research_report")
        type_placeholders = ",".join("?" for _ in artifact_types)
        conn.execute(
            f"UPDATE research_artifacts SET status = 'stale', updated_at = {_NOW} WHERE run_id = ? AND artifact_type IN ({type_placeholders}) AND status = 'completed'",
            (run_id, *artifact_types),
        )
        conn.execute(f"UPDATE research_citations SET status = 'stale', updated_at = {_NOW} WHERE run_id = ?", (run_id,))
        conn.execute(
            f"""
            UPDATE research_runs SET status = 'queued', requested_action = NULL,
                error_code = NULL, error_message = NULL, completed_at = NULL,
                state_version = state_version + 1, updated_at = {_NOW}
            WHERE id = ? AND user_id = ?
            """,
            (run_id, user_id),
        )
        conn.execute(
            "INSERT INTO research_events(run_id, event_type, summary, payload_json) VALUES (?, 'report.regeneration_requested', '已请求生成新的引用报告版本', ?)",
            (run_id, _json({"generation": generation})),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    from .research import get_run_snapshot

    return get_run_snapshot(conn, run_id, user_id)

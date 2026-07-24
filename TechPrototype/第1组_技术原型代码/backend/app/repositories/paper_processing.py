from __future__ import annotations

import hashlib
import sqlite3
import uuid
from typing import Any, cast

from ..models import PaperId


_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


class PaperProcessingConflict(RuntimeError):
    pass


def _fingerprint(pdf_url: str | None, asset_id: str | None) -> str:
    identity = f"asset:{asset_id}" if asset_id else f"source:{pdf_url or ''}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def get_processing_job(conn: sqlite3.Connection, paper_id: int) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            "SELECT * FROM paper_processing_jobs WHERE paper_id = ?",
            (paper_id,),
        ).fetchone()
    )


def get_processing_job_by_id(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            "SELECT * FROM paper_processing_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    )


def _document_is_current(conn: sqlite3.Connection, paper_id: int, asset_id: str | None) -> bool:
    if not asset_id:
        return False
    row = conn.execute(
        "SELECT status, source_hash FROM paper_documents WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    return bool(
        row is not None
        and row["status"] == "completed"
        and row["source_hash"] == asset_id.removeprefix("sha256:")
    )


def enqueue_paper_processing(
    conn: sqlite3.Connection,
    *,
    paper_id: int,
    requested_by_user_id: int,
    reset_failed: bool = True,
) -> str:
    paper = conn.execute(
        "SELECT id, pdf_url, asset_id FROM papers WHERE id = ?",
        (paper_id,),
    ).fetchone()
    if paper is None:
        raise ValueError("paper not found")
    asset_id = str(paper["asset_id"]) if paper["asset_id"] is not None else None
    fingerprint = _fingerprint(
        str(paper["pdf_url"]) if paper["pdf_url"] is not None else None,
        asset_id,
    )
    if _document_is_current(conn, paper_id, asset_id):
        existing = get_processing_job(conn, paper_id)
        if existing is not None and existing["status"] != "completed":
            conn.execute(
                f"""
                UPDATE paper_processing_jobs
                SET status = 'completed', phase = 'completed', input_fingerprint = ?,
                    lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                    error_code = NULL, error_message = NULL, completed_at = {_NOW},
                    last_progress_at = {_NOW}, updated_at = {_NOW}
                WHERE paper_id = ? AND status != 'running'
                """,
                (fingerprint, paper_id),
            )
        return "ready"

    existing = get_processing_job(conn, paper_id)
    if existing is None:
        conn.execute(
            """
            INSERT INTO paper_processing_jobs(
                id, paper_id, requested_by_user_id, input_fingerprint
            ) VALUES (?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), paper_id, requested_by_user_id, fingerprint),
        )
        return "queued"
    if existing["status"] == "running":
        return "active"
    if existing["status"] in {"queued", "retry_wait"} and existing["input_fingerprint"] == fingerprint:
        conn.execute(
            f"""
            UPDATE paper_processing_jobs
            SET requested_by_user_id = ?, updated_at = {_NOW}
            WHERE paper_id = ? AND status IN ('queued', 'retry_wait')
            """,
            (requested_by_user_id, paper_id),
        )
        return "active"
    if existing["status"] == "failed" and not reset_failed and existing["input_fingerprint"] == fingerprint:
        return "failed"
    conn.execute(
        f"""
        UPDATE paper_processing_jobs
        SET requested_by_user_id = ?, input_fingerprint = ?, status = 'queued',
            phase = 'queued', attempt_count = 0, next_attempt_at = {_NOW},
            lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
            error_code = NULL, error_message = NULL, started_at = NULL,
            completed_at = NULL, last_progress_at = {_NOW}, updated_at = {_NOW}
        WHERE paper_id = ? AND status != 'running'
        """,
        (requested_by_user_id, fingerprint, paper_id),
    )
    return "queued"


def recover_expired_processing_jobs(conn: sqlite3.Connection) -> int:
    conn.execute("BEGIN IMMEDIATE")
    try:
        expired = conn.execute(
            f"""
            SELECT id, attempt_count, max_attempts FROM paper_processing_jobs
            WHERE status = 'running' AND lease_expires_at <= {_NOW}
            """
        ).fetchall()
        for job in expired:
            terminal = int(job["attempt_count"]) >= int(job["max_attempts"])
            conn.execute(
                f"""
                UPDATE paper_processing_jobs
                SET status = ?, phase = 'queued', next_attempt_at = {_NOW},
                    lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                    error_code = 'worker_lease_expired',
                    error_message = '论文加工进程中断。', updated_at = {_NOW},
                    completed_at = CASE WHEN ? THEN {_NOW} ELSE NULL END
                WHERE id = ? AND status = 'running'
                """,
                ("failed" if terminal else "retry_wait", terminal, str(job["id"])),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(expired)


def claim_next_processing_job(
    conn: sqlite3.Connection,
    *,
    worker_id: str,
    lease_seconds: int,
) -> dict[str, Any] | None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            f"""
            SELECT j.* FROM paper_processing_jobs j
            JOIN users u ON u.id = j.requested_by_user_id AND u.is_active = 1
            WHERE j.status IN ('queued', 'retry_wait')
              AND j.attempt_count < j.max_attempts
              AND j.next_attempt_at <= {_NOW}
            ORDER BY j.next_attempt_at, j.created_at, j.id
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        cursor = conn.execute(
            f"""
            UPDATE paper_processing_jobs
            SET status = 'running', phase = 'download', attempt_count = attempt_count + 1,
                lease_owner = ?, lease_generation = lease_generation + 1,
                lease_expires_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?),
                heartbeat_at = {_NOW}, last_progress_at = {_NOW},
                error_code = NULL, error_message = NULL,
                started_at = COALESCE(started_at, {_NOW}), updated_at = {_NOW}
            WHERE id = ? AND status IN ('queued', 'retry_wait')
            """,
            (worker_id, f"+{lease_seconds} seconds", str(row["id"])),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return None
        claimed = conn.execute(
            "SELECT * FROM paper_processing_jobs WHERE id = ?",
            (str(row["id"]),),
        ).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return _row(claimed)


def assert_active_processing_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    worker_id: str,
    lease_generation: int,
) -> sqlite3.Row:
    row = conn.execute(
        f"""
        SELECT * FROM paper_processing_jobs
        WHERE id = ? AND status = 'running' AND lease_owner = ?
          AND lease_generation = ? AND lease_expires_at > {_NOW}
        """,
        (job_id, worker_id, lease_generation),
    ).fetchone()
    if row is None:
        raise PaperProcessingConflict("paper processing lease lost")
    return cast(sqlite3.Row, row)


def update_processing_phase(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    worker_id: str,
    lease_generation: int,
    phase: str,
) -> None:
    if phase not in {"download", "parse", "index"}:
        raise ValueError("invalid processing phase")
    conn.execute("BEGIN IMMEDIATE")
    try:
        assert_active_processing_job(
            conn,
            job_id=job_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        conn.execute(
            f"""
            UPDATE paper_processing_jobs SET phase = ?, last_progress_at = {_NOW},
                updated_at = {_NOW} WHERE id = ?
            """,
            (phase, job_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def heartbeat_processing_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    worker_id: str,
    lease_generation: int,
    lease_seconds: int,
) -> bool:
    cursor = conn.execute(
        f"""
        UPDATE paper_processing_jobs
        SET lease_expires_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?),
            heartbeat_at = {_NOW}, updated_at = {_NOW}
        WHERE id = ? AND status = 'running' AND lease_owner = ?
          AND lease_generation = ? AND lease_expires_at > {_NOW}
        """,
        (f"+{lease_seconds} seconds", job_id, worker_id, lease_generation),
    )
    conn.commit()
    return cursor.rowcount == 1


def finish_processing_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    worker_id: str,
    lease_generation: int,
) -> bool:
    conn.execute("BEGIN IMMEDIATE")
    try:
        assert_active_processing_job(
            conn,
            job_id=job_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        cursor = conn.execute(
            f"""
            UPDATE paper_processing_jobs
            SET status = 'completed', phase = 'completed', lease_owner = NULL,
                lease_expires_at = NULL, heartbeat_at = NULL, error_code = NULL,
                error_message = NULL, last_progress_at = {_NOW},
                completed_at = {_NOW}, updated_at = {_NOW}
            WHERE id = ? AND status = 'running' AND lease_owner = ?
              AND lease_generation = ?
            """,
            (job_id, worker_id, lease_generation),
        )
        conn.commit()
    except PaperProcessingConflict:
        conn.rollback()
        return False
    except Exception:
        conn.rollback()
        raise
    return cursor.rowcount == 1


def fail_processing_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    worker_id: str,
    lease_generation: int,
    error_code: str,
    error_message: str,
    retryable: bool,
    retry_delay_seconds: int,
) -> bool:
    conn.execute("BEGIN IMMEDIATE")
    try:
        job = assert_active_processing_job(
            conn,
            job_id=job_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        should_retry = retryable and int(job["attempt_count"]) < int(job["max_attempts"])
        status = "retry_wait" if should_retry else "failed"
        cursor = conn.execute(
            f"""
            UPDATE paper_processing_jobs
            SET status = ?, phase = 'queued',
                next_attempt_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?),
                lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                error_code = ?, error_message = ?, updated_at = {_NOW},
                completed_at = CASE WHEN ? = 'failed' THEN {_NOW} ELSE NULL END
            WHERE id = ? AND status = 'running' AND lease_owner = ?
              AND lease_generation = ?
            """,
            (
                status,
                f"+{max(0, retry_delay_seconds)} seconds",
                error_code[:100],
                error_message[:500],
                status,
                job_id,
                worker_id,
                lease_generation,
            ),
        )
        conn.commit()
    except PaperProcessingConflict:
        conn.rollback()
        return False
    except Exception:
        conn.rollback()
        raise
    return cursor.rowcount == 1


def processing_projection(conn: sqlite3.Connection, paper_id: int) -> dict[str, Any]:
    document = conn.execute(
        "SELECT status, source_hash, error, updated_at FROM paper_documents WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    job = conn.execute(
        """
        SELECT status, phase, attempt_count, max_attempts, error_code, error_message,
               last_progress_at, updated_at
        FROM paper_processing_jobs WHERE paper_id = ?
        """,
        (paper_id,),
    ).fetchone()
    if document is not None and document["status"] == "completed":
        status = "ready"
    elif job is not None:
        status = {
            "queued": "queued",
            "retry_wait": "retry_wait",
            "running": str(job["phase"]),
            "failed": "failed",
            "completed": "ready",
        }[str(job["status"])]
    elif document is not None and document["status"] == "failed":
        status = "failed"
    else:
        status = "not_queued"
    return {
        "status": status,
        "attempt_count": int(job["attempt_count"]) if job is not None else 0,
        "max_attempts": int(job["max_attempts"]) if job is not None else 0,
        "error_code": str(job["error_code"]) if job is not None and job["error_code"] else None,
        "error_message": str(job["error_message"]) if job is not None and job["error_message"] else None,
        "updated_at": str(job["updated_at"]) if job is not None else str(document["updated_at"]) if document is not None else None,
    }


def paper_id_for_job(job: dict[str, Any]) -> PaperId:
    return PaperId(int(job["paper_id"]))

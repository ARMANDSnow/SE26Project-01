from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend.app.config import get_settings
from backend.app.database import IncompatibleSchemaError, connect, init_db, init_schema, upsert_paper
from backend.app.models import PaperCandidate, PaperSource
from backend.app.repositories.paper_processing import (
    claim_next_processing_job,
    enqueue_paper_processing,
    fail_processing_job,
    finish_processing_job,
    get_processing_job,
    recover_expired_processing_jobs,
)
from backend.app.services.paper_processing import (
    PaperProcessingError,
    PaperProcessingExecutor,
)


def _slow_parse_process(_pdf_path: str, _result_path: str) -> None:
    time.sleep(10)


@pytest.fixture()
def processing_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    database_path = tmp_path / "processing.sqlite3"
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    get_settings.cache_clear()
    init_db(database_path)
    with connect(database_path) as conn:
        conn.execute(
            "INSERT INTO users(id, name, username, password_hash, is_active) "
            "VALUES (1, 'Worker User', 'worker', '!', 1)"
        )
        conn.commit()
    yield database_path
    get_settings.cache_clear()


def _paper(conn, source_id: str) -> int:
    return upsert_paper(
        conn,
        PaperCandidate(
            source=PaperSource.ARXIV,
            source_id=source_id,
            source_url=f"https://arxiv.org/abs/{source_id}",
            pdf_url=f"https://arxiv.org/pdf/{source_id}.pdf",
            title=f"Paper {source_id}",
            authors=("Ada",),
            abstract="Background processing test paper.",
            categories=("cs.SE",),
            primary_category="cs.SE",
            published_at="2026-07-21",
        ),
    )


def test_enqueue_is_idempotent_per_paper(processing_database: Path) -> None:
    with connect(processing_database) as conn:
        paper_id = _paper(conn, "2607.00001")
        first = enqueue_paper_processing(
            conn, paper_id=paper_id, requested_by_user_id=1
        )
        second = enqueue_paper_processing(
            conn, paper_id=paper_id, requested_by_user_id=1
        )
        conn.commit()

        assert first == "queued"
        assert second == "active"
        assert conn.execute(
            "SELECT COUNT(*) FROM paper_processing_jobs WHERE paper_id = ?",
            (paper_id,),
        ).fetchone()[0] == 1


def test_active_user_can_take_over_a_queued_request(processing_database: Path) -> None:
    with connect(processing_database) as conn:
        conn.execute(
            "INSERT INTO users(id, name, username, password_hash, is_active) "
            "VALUES (2, 'Second User', 'second', '!', 1)"
        )
        paper_id = _paper(conn, "2607.00007")
        enqueue_paper_processing(conn, paper_id=paper_id, requested_by_user_id=1)
        conn.execute("UPDATE users SET is_active = 0 WHERE id = 1")

        assert enqueue_paper_processing(
            conn, paper_id=paper_id, requested_by_user_id=2
        ) == "active"
        conn.commit()

        job = get_processing_job(conn, paper_id)
        assert job is not None
        assert job["requested_by_user_id"] == 2
        assert claim_next_processing_job(
            conn, worker_id="worker-b", lease_seconds=60
        ) is not None


def test_v9_database_migrates_to_durable_processing_jobs(processing_database: Path) -> None:
    with connect(processing_database) as conn:
        conn.execute("DROP TABLE paper_processing_jobs")
        conn.execute("PRAGMA user_version = 9")
        conn.commit()

        init_schema(conn)

        assert conn.execute("PRAGMA user_version").fetchone()[0] == 10
        assert {
            row[1] for row in conn.execute("PRAGMA table_info(paper_processing_jobs)")
        } >= {"paper_id", "status", "lease_owner", "lease_generation", "max_attempts"}


def test_forged_v10_processing_schema_fails_closed(processing_database: Path) -> None:
    with connect(processing_database) as conn:
        conn.execute("DROP TABLE paper_processing_jobs")
        conn.execute("CREATE TABLE paper_processing_jobs(id TEXT PRIMARY KEY)")
        conn.execute("PRAGMA user_version = 10")
        conn.commit()

        with pytest.raises(IncompatibleSchemaError, match="paper processing schema"):
            init_schema(conn)


def test_lease_generation_fences_stale_worker(processing_database: Path) -> None:
    with connect(processing_database) as conn:
        paper_id = _paper(conn, "2607.00002")
        enqueue_paper_processing(conn, paper_id=paper_id, requested_by_user_id=1)
        conn.commit()
        first = claim_next_processing_job(conn, worker_id="worker-a", lease_seconds=60)
        assert first is not None
        conn.execute(
            "UPDATE paper_processing_jobs SET lease_expires_at = '2000-01-01T00:00:00.000Z' "
            "WHERE id = ?",
            (first["id"],),
        )
        conn.commit()
        assert recover_expired_processing_jobs(conn) == 1
        second = claim_next_processing_job(conn, worker_id="worker-b", lease_seconds=60)
        assert second is not None

        assert finish_processing_job(
            conn,
            job_id=str(first["id"]),
            worker_id="worker-a",
            lease_generation=int(first["lease_generation"]),
        ) is False
        assert finish_processing_job(
            conn,
            job_id=str(second["id"]),
            worker_id="worker-b",
            lease_generation=int(second["lease_generation"]),
        ) is True


def test_retry_cap_becomes_terminal_failure(processing_database: Path) -> None:
    with connect(processing_database) as conn:
        paper_id = _paper(conn, "2607.00003")
        enqueue_paper_processing(conn, paper_id=paper_id, requested_by_user_id=1)
        conn.execute(
            "UPDATE paper_processing_jobs SET max_attempts = 1 WHERE paper_id = ?",
            (paper_id,),
        )
        conn.commit()
        job = claim_next_processing_job(conn, worker_id="worker-a", lease_seconds=60)
        assert job is not None

        assert fail_processing_job(
            conn,
            job_id=str(job["id"]),
            worker_id="worker-a",
            lease_generation=int(job["lease_generation"]),
            error_code="injected",
            error_message="Injected failure",
            retryable=True,
            retry_delay_seconds=0,
        ) is True
        settled = get_processing_job(conn, paper_id)
        assert settled is not None
        assert settled["status"] == "failed"
        assert settled["attempt_count"] == 1


def test_executor_failure_does_not_block_next_paper(processing_database: Path) -> None:
    with connect(processing_database) as conn:
        first_id = _paper(conn, "2607.00004")
        second_id = _paper(conn, "2607.00005")
        enqueue_paper_processing(conn, paper_id=first_id, requested_by_user_id=1)
        enqueue_paper_processing(conn, paper_id=second_id, requested_by_user_id=1)
        conn.execute(
            "UPDATE paper_processing_jobs SET max_attempts = 1 WHERE paper_id = ?",
            (first_id,),
        )
        conn.commit()

    def runner(job: dict, _worker_id: str, _generation: int) -> None:
        if int(job["paper_id"]) == first_id:
            raise PaperProcessingError("injected", "Injected failure", retryable=False)

    executor = PaperProcessingExecutor(runner=runner)
    assert executor.run_once() is True
    assert executor.run_once() is True

    with connect(processing_database) as conn:
        assert get_processing_job(conn, first_id)["status"] == "failed"
        assert get_processing_job(conn, second_id)["status"] == "completed"


def test_write_fence_rechecks_requester_access(processing_database: Path) -> None:
    executor = PaperProcessingExecutor()
    with connect(processing_database) as conn:
        paper_id = _paper(conn, "2607.00008")
        enqueue_paper_processing(conn, paper_id=paper_id, requested_by_user_id=1)
        conn.commit()
        job = claim_next_processing_job(
            conn, worker_id=executor.worker_id, lease_seconds=60
        )
        assert job is not None
        conn.execute("UPDATE users SET is_active = 0 WHERE id = 1")
        conn.commit()

        with pytest.raises(PaperProcessingError) as captured:
            executor._fence(
                job, executor.worker_id, int(job["lease_generation"])
            )(conn)
        assert captured.value.code == "paper_access_revoked"


def test_docling_child_process_has_hard_timeout(processing_database: Path, tmp_path: Path) -> None:
    with connect(processing_database) as conn:
        paper_id = _paper(conn, "2607.00006")
        enqueue_paper_processing(conn, paper_id=paper_id, requested_by_user_id=1)
        conn.execute(
            "UPDATE paper_processing_jobs SET max_attempts = 1 WHERE paper_id = ?",
            (paper_id,),
        )
        conn.commit()
        job = claim_next_processing_job(conn, worker_id="timeout-worker", lease_seconds=10)
        assert job is not None

    pdf_path = tmp_path / "timeout.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    executor = PaperProcessingExecutor(
        lease_seconds=10,
        heartbeat_seconds=1,
        parse_timeout_seconds=1,
        parse_target=_slow_parse_process,
    )
    executor.worker_id = "timeout-worker"
    started = time.monotonic()
    with pytest.raises(PaperProcessingError) as captured:
        executor._parse_with_hard_timeout(
            job,
            pdf_path,
            "timeout-worker",
            int(job["lease_generation"]),
        )
    assert captured.value.code == "paper_parse_timeout"
    assert time.monotonic() - started < 5
    assert executor._active_process is None
    executor._settle_failure(job, captured.value)

    with connect(processing_database) as conn:
        conn.execute("UPDATE users SET is_active = 1 WHERE id = 1")
        second_id = _paper(conn, "2607.00009")
        enqueue_paper_processing(conn, paper_id=second_id, requested_by_user_id=1)
        conn.commit()
    executor.runner = lambda _job, _worker_id, _generation: None
    assert executor.run_once() is True
    with connect(processing_database) as conn:
        assert get_processing_job(conn, paper_id)["status"] == "failed"
        assert get_processing_job(conn, second_id)["status"] == "completed"

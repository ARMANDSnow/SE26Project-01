from __future__ import annotations

import json
import logging
import multiprocessing
from multiprocessing.process import BaseProcess
import tempfile
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from ..config import get_settings
from ..db.connection import connect
from ..repositories.paper_processing import (
    PaperProcessingConflict,
    assert_active_processing_job,
    claim_next_processing_job,
    fail_processing_job,
    finish_processing_job,
    heartbeat_processing_job,
    recover_expired_processing_jobs,
    update_processing_phase,
)
from ..repositories.uploads import paper_is_accessible
from .asset_store import LocalAssetStore
from .documents import (
    ParsedPaperDocument,
    commit_parsed_document,
    extract_pdf_document,
    mark_document_failed,
    mark_document_processing,
)
from .remote_pdf import PaperPdfService, RemotePdfError


logger = logging.getLogger(__name__)
ProcessingRunner = Callable[[dict[str, Any], str, int], None]
ParseProcessTarget = Callable[[str, str], None]
MAX_PARSE_RESULT_BYTES = 128 * 1024 * 1024


class PaperProcessingError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.retryable = retryable


def _parse_process_entry(pdf_path: str, result_path: str) -> None:
    parsed = extract_pdf_document(Path(pdf_path))
    encoded = json.dumps(asdict(parsed), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_PARSE_RESULT_BYTES:
        raise RuntimeError("paper parse result exceeded the size limit")
    Path(result_path).write_bytes(encoded)


class PaperProcessingExecutor:
    """Durable single-slot supervisor; Docling itself runs in a killable process."""

    def __init__(
        self,
        *,
        lease_seconds: int = 90,
        heartbeat_seconds: int = 15,
        poll_seconds: float = 1.0,
        parse_timeout_seconds: int | None = None,
        runner: ProcessingRunner | None = None,
        parse_target: ParseProcessTarget = _parse_process_entry,
    ) -> None:
        settings = get_settings()
        self.worker_id = f"paper-processing-{uuid.uuid4()}"
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.poll_seconds = poll_seconds
        self.parse_timeout_seconds = (
            parse_timeout_seconds
            if parse_timeout_seconds is not None
            else settings.paper_processing_timeout_seconds
        )
        self.database_path = settings.database_path
        self.upload_dir = settings.upload_dir
        self.runner = runner or self._run_isolated_pipeline
        self.parse_target = parse_target
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._supervisor: threading.Thread | None = None
        self._active_process: BaseProcess | None = None

    def start(self) -> None:
        if self._supervisor is not None and self._supervisor.is_alive():
            return
        self._stop.clear()
        with connect(self.database_path) as conn:
            recover_expired_processing_jobs(conn)
        self._supervisor = threading.Thread(
            target=self._run,
            name="paperwiki-paper-processing-supervisor",
            daemon=True,
        )
        self._supervisor.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        process = self._active_process
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=2)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=1)
        if self._supervisor is not None:
            self._supervisor.join(timeout=timeout)
        self._supervisor = None
        self._active_process = None

    def run_once(self) -> bool:
        with connect(self.database_path) as conn:
            recover_expired_processing_jobs(conn)
            job = claim_next_processing_job(
                conn,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
        if job is None:
            return False
        self._execute_claim(job)
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = self.run_once()
            except Exception as exc:
                logger.error(
                    "Paper processing supervisor iteration failed (%s)",
                    type(exc).__name__,
                )
                self._stop.wait(min(2.0, self.poll_seconds * 2))
                continue
            if not processed:
                self._wake.wait(self.poll_seconds)
                self._wake.clear()

    def _execute_claim(self, job: dict[str, Any]) -> None:
        try:
            self.runner(job, self.worker_id, int(job["lease_generation"]))
        except PaperProcessingConflict:
            return
        except PaperProcessingError as exc:
            self._settle_failure(job, exc)
        except Exception:
            self._settle_failure(
                job,
                PaperProcessingError(
                    "paper_processing_failed",
                    "论文后台加工失败。",
                    retryable=True,
                ),
            )
        else:
            with connect(self.database_path) as conn:
                finish_processing_job(
                    conn,
                    job_id=str(job["id"]),
                    worker_id=self.worker_id,
                    lease_generation=int(job["lease_generation"]),
                )

    def _settle_failure(self, job: dict[str, Any], error: PaperProcessingError) -> None:
        delay = min(60, 2 ** max(0, int(job["attempt_count"]) - 1))
        with connect(self.database_path) as conn:
            fail_processing_job(
                conn,
                job_id=str(job["id"]),
                worker_id=self.worker_id,
                lease_generation=int(job["lease_generation"]),
                error_code=error.code,
                error_message=error.public_message,
                retryable=error.retryable,
                retry_delay_seconds=delay,
            )

    def _fence(self, job: dict[str, Any], worker_id: str, generation: int) -> Callable[[Any], None]:
        def check(conn: Any) -> None:
            assert_active_processing_job(
                conn,
                job_id=str(job["id"]),
                worker_id=worker_id,
                lease_generation=generation,
            )
            requester = int(job["requested_by_user_id"])
            active = conn.execute(
                "SELECT 1 FROM users WHERE id = ? AND is_active = 1",
                (requester,),
            ).fetchone()
            if active is None or not paper_is_accessible(conn, int(job["paper_id"]), requester):
                raise PaperProcessingError(
                    "paper_access_revoked",
                    "论文已不可访问，后台加工已停止。",
                    retryable=False,
                )

        return check

    def _run_isolated_pipeline(
        self,
        job: dict[str, Any],
        worker_id: str,
        generation: int,
    ) -> None:
        fence = self._fence(job, worker_id, generation)
        paper_id = int(job["paper_id"])
        store = LocalAssetStore(self.upload_dir)
        next_download_heartbeat = time.monotonic() + self.heartbeat_seconds

        def download_progress() -> None:
            nonlocal next_download_heartbeat
            if self._stop.is_set():
                raise PaperProcessingError(
                    "paper_worker_stopped",
                    "论文加工服务已停止。",
                    retryable=True,
                )
            if time.monotonic() < next_download_heartbeat:
                return
            with connect(self.database_path) as heartbeat_conn:
                fence(heartbeat_conn)
                owned = heartbeat_processing_job(
                    heartbeat_conn,
                    job_id=str(job["id"]),
                    worker_id=worker_id,
                    lease_generation=generation,
                    lease_seconds=self.lease_seconds,
                )
            if not owned:
                raise PaperProcessingConflict("paper processing lease lost")
            next_download_heartbeat = time.monotonic() + self.heartbeat_seconds

        try:
            with connect(self.database_path) as conn:
                fence(conn)
                update_processing_phase(
                    conn,
                    job_id=str(job["id"]),
                    worker_id=worker_id,
                    lease_generation=generation,
                    phase="download",
                )
                try:
                    asset = PaperPdfService(conn, store=store).ensure(
                        paper_id,
                        before_attach=fence,
                        progress=download_progress,
                    )
                except RemotePdfError as exc:
                    missing = str(exc) == "paper has no PDF source"
                    raise PaperProcessingError(
                        "paper_pdf_unavailable" if missing else "paper_pdf_download_failed",
                        "论文没有可用 PDF 来源。" if missing else "论文 PDF 下载失败。",
                        retryable=not missing,
                    ) from exc
                source_hash = str(asset.id).removeprefix("sha256:")
                pdf_path = store.path_for(asset.id)
                mark_document_processing(
                    conn,
                    paper_id,
                    source_hash,
                    fence=fence,
                )
                update_processing_phase(
                    conn,
                    job_id=str(job["id"]),
                    worker_id=worker_id,
                    lease_generation=generation,
                    phase="parse",
                )

            try:
                parsed = self._parse_with_hard_timeout(job, pdf_path, worker_id, generation)
            except PaperProcessingError as exc:
                try:
                    with connect(self.database_path) as conn:
                        mark_document_failed(
                            conn,
                            paper_id,
                            source_hash,
                            exc.public_message,
                            fence=fence,
                        )
                except PaperProcessingConflict:
                    raise
                except Exception:
                    logger.warning("Could not persist paper parse failure for paper %s", paper_id)
                raise

            with connect(self.database_path) as conn:
                update_processing_phase(
                    conn,
                    job_id=str(job["id"]),
                    worker_id=worker_id,
                    lease_generation=generation,
                    phase="index",
                )
                commit_parsed_document(
                    conn,
                    paper_id,
                    source_hash,
                    parsed,
                    fence=fence,
                    before_write=lambda: self._refresh_lease_for_final_write(
                        job,
                        worker_id,
                        generation,
                    ),
                )
        except PaperProcessingError:
            raise
        except PaperProcessingConflict:
            raise
        except Exception as exc:
            try:
                with connect(self.database_path) as conn:
                    record = conn.execute(
                        "SELECT asset_id FROM papers WHERE id = ?",
                        (paper_id,),
                    ).fetchone()
                    if record is not None and record["asset_id"]:
                        mark_document_failed(
                            conn,
                            paper_id,
                            str(record["asset_id"]).removeprefix("sha256:"),
                            "论文 PDF 解析失败。",
                            fence=fence,
                        )
            except Exception:
                pass
            raise PaperProcessingError(
                "paper_parse_failed",
                "论文 PDF 解析失败。",
                retryable=True,
            ) from exc

    def _refresh_lease_for_final_write(
        self,
        job: dict[str, Any],
        worker_id: str,
        generation: int,
    ) -> None:
        with connect(self.database_path) as conn:
            self._fence(job, worker_id, generation)(conn)
            owned = heartbeat_processing_job(
                conn,
                job_id=str(job["id"]),
                worker_id=worker_id,
                lease_generation=generation,
                lease_seconds=max(self.lease_seconds, 300),
            )
        if not owned:
            raise PaperProcessingConflict("paper processing lease lost")

    def _parse_with_hard_timeout(
        self,
        job: dict[str, Any],
        pdf_path: Path,
        worker_id: str,
        generation: int,
    ) -> ParsedPaperDocument:
        result_dir = self.upload_dir / "tmp"
        result_dir.mkdir(parents=True, exist_ok=True)
        task_dir = Path(tempfile.mkdtemp(prefix="paper-parse-", dir=result_dir))
        result_path = task_dir / "result.json"
        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=self.parse_target,
            args=(str(pdf_path), str(result_path)),
            name=f"paperwiki-docling-{job['paper_id']}",
            daemon=False,
        )
        self._active_process = process
        started = False
        try:
            process.start()
            started = True
            deadline = time.monotonic() + self.parse_timeout_seconds
            next_heartbeat = time.monotonic() + self.heartbeat_seconds
            while process.is_alive():
                if self._stop.is_set():
                    raise PaperProcessingError(
                        "paper_worker_stopped",
                        "论文加工服务已停止。",
                        retryable=True,
                    )
                now = time.monotonic()
                if now >= deadline:
                    raise PaperProcessingError(
                        "paper_parse_timeout",
                        "论文 PDF 解析超时。",
                        retryable=True,
                    )
                process.join(timeout=min(0.2, max(0.01, next_heartbeat - now)))
                if process.is_alive() and time.monotonic() >= next_heartbeat:
                    with connect(self.database_path) as conn:
                        self._fence(job, worker_id, generation)(conn)
                        owned = heartbeat_processing_job(
                            conn,
                            job_id=str(job["id"]),
                            worker_id=worker_id,
                            lease_generation=generation,
                            lease_seconds=self.lease_seconds,
                        )
                    if not owned:
                        raise PaperProcessingConflict("paper processing lease lost")
                    next_heartbeat = time.monotonic() + self.heartbeat_seconds
            process.join(timeout=0)
            if process.exitcode != 0 or not result_path.is_file():
                raise PaperProcessingError(
                    "paper_parse_process_failed",
                    "论文 PDF 解析进程失败。",
                    retryable=True,
                )
            if result_path.stat().st_size > MAX_PARSE_RESULT_BYTES:
                raise PaperProcessingError(
                    "paper_parse_result_too_large",
                    "论文 PDF 解析结果过大。",
                    retryable=False,
                )
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            return ParsedPaperDocument(
                parser_version=str(payload["parser_version"]),
                content_markdown=str(payload["content_markdown"]),
                structure_json=str(payload["structure_json"]),
                token_count=int(payload["token_count"]),
            )
        finally:
            if started and process.is_alive():
                process.terminate()
                process.join(timeout=2)
                if process.is_alive() and hasattr(process, "kill"):
                    process.kill()
                    process.join(timeout=1)
            result_path.unlink(missing_ok=True)
            try:
                task_dir.rmdir()
            except OSError:
                logger.warning("Could not remove paper parse result directory %s", task_dir.name)
            self._active_process = None

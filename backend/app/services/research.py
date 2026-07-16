from __future__ import annotations

import threading
import time
import uuid
import logging
from collections.abc import Callable
from typing import Any

from ..db.connection import connect
from ..repositories.research import (
    claim_next_step,
    fail_step,
    finish_step,
    heartbeat_step,
    reconcile_requested_actions,
    recover_expired_leases,
)
from .research_contracts import ResearchStepError, ResearchWaitingInput
from .topic_research import TopicResearchPipeline


HarnessHandler = Callable[[dict[str, Any]], dict[str, Any]]
logger = logging.getLogger(__name__)


def run_harness_step(step: dict[str, Any]) -> dict[str, Any]:
    """Execute the deterministic scaffold without external research claims."""

    step_key = str(step["step_key"])
    if step_key == "normalize":
        goal = str(step.get("input", {}).get("goal", "")).strip()
        return {
            "scaffold_only": True,
            "normalized_goal": goal,
            "external_calls": 0,
        }
    if step_key == "plan":
        return {
            "scaffold_only": True,
            "plan": ["normalize", "plan", "finalize"],
            "research_claims": [],
            "external_calls": 0,
        }
    if step_key == "finalize":
        return {
            "scaffold_only": True,
            "message": "Research Harness is ready; no paper research was performed.",
            "research_claims": [],
            "external_calls": 0,
        }
    raise ValueError("unknown harness step")


class ResearchExecutor:
    """Database-backed single-worker supervisor with fenced step completion."""

    def __init__(
        self,
        *,
        lease_seconds: int = 60,
        heartbeat_seconds: int = 15,
        poll_seconds: float = 1.0,
        handler: HarnessHandler | None = None,
        topic_pipeline: TopicResearchPipeline | None = None,
    ) -> None:
        self.worker_id = f"research-{uuid.uuid4()}"
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.poll_seconds = poll_seconds
        self.topic_pipeline = topic_pipeline or TopicResearchPipeline()
        self.handler = handler or self._dispatch_step
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._supervisor: threading.Thread | None = None

    def _dispatch_step(self, step: dict[str, Any]) -> dict[str, Any]:
        if str(step.get("step_type", "")).startswith("topic."):
            return self.topic_pipeline.handle(step)
        return run_harness_step(step)

    def start(self) -> None:
        if self._supervisor is not None and self._supervisor.is_alive():
            return
        self._stop.clear()
        with connect() as conn:
            recover_expired_leases(conn)
            reconcile_requested_actions(conn)
        self._supervisor = threading.Thread(
            target=self._run,
            name="paperwiki-research-supervisor",
            daemon=True,
        )
        self._supervisor.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._supervisor is not None:
            self._supervisor.join(timeout=timeout)
        self._supervisor = None

    def _run(self) -> None:
        next_recovery = 0.0
        while not self._stop.is_set():
            try:
                with connect() as conn:
                    now = time.monotonic()
                    if now >= next_recovery:
                        recover_expired_leases(conn)
                        next_recovery = now + max(5.0, self.lease_seconds / 2)
                    reconcile_requested_actions(conn)
                    step = claim_next_step(
                        conn,
                        worker_id=self.worker_id,
                        lease_seconds=self.lease_seconds,
                    )
            except Exception as exc:
                logger.error("Research executor supervisor iteration failed (%s)", type(exc).__name__)
                self._stop.wait(min(2.0, self.poll_seconds * 2))
                continue
            if step is None:
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
                continue
            try:
                self._execute_claim(step)
            except Exception as exc:
                logger.error("Research executor step finalization failed (%s)", type(exc).__name__)

    def _execute_claim(self, step: dict[str, Any]) -> None:
        result: dict[str, Any] = {}
        failure: BaseException | None = None

        def work() -> None:
            nonlocal result, failure
            try:
                result = self.handler(step)
            except BaseException as exc:  # keep the supervisor alive after handler failure
                failure = exc

        worker = threading.Thread(target=work, name="paperwiki-research-worker", daemon=True)
        worker.start()
        next_heartbeat = time.monotonic() + self.heartbeat_seconds
        while worker.is_alive():
            if self._stop.is_set():
                return
            worker.join(timeout=min(0.1, max(0.01, next_heartbeat - time.monotonic())))
            if worker.is_alive() and time.monotonic() >= next_heartbeat:
                with connect() as conn:
                    owned = heartbeat_step(
                        conn,
                        step_id=str(step["id"]),
                        worker_id=self.worker_id,
                        lease_generation=int(step["lease_generation"]),
                        lease_seconds=self.lease_seconds,
                    )
                if not owned:
                    return
                next_heartbeat = time.monotonic() + self.heartbeat_seconds
        worker.join(timeout=0)
        if self._stop.is_set() and worker.is_alive():
            return
        with connect() as conn:
            if failure is None:
                finish_step(
                    conn,
                    step_id=str(step["id"]),
                    worker_id=self.worker_id,
                    lease_generation=int(step["lease_generation"]),
                    output=result,
                )
            elif isinstance(failure, ResearchWaitingInput):
                # The budget repository atomically released this lease and
                # persisted Run/Step/Decision as waiting_input.
                return
            elif isinstance(failure, ResearchStepError):
                fail_step(
                    conn,
                    step_id=str(step["id"]),
                    worker_id=self.worker_id,
                    lease_generation=int(step["lease_generation"]),
                    error_code=failure.code,
                    error_message=failure.public_message,
                )
            else:
                fail_step(
                    conn,
                    step_id=str(step["id"]),
                    worker_id=self.worker_id,
                    lease_generation=int(step["lease_generation"]),
                    error_code="harness_step_failed",
                    error_message=str(failure),
                )

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, cast

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from ...auth.dependencies import CurrentUser
from ...db.connection import connect
from ...repositories.research import (
    ResearchConflictError,
    ResearchNotFoundError,
    create_harness_run,
    get_run_snapshot,
    list_events,
    list_runs,
    request_action,
    resolve_decision,
    resume_run,
    retry_run,
)
from ...repositories.research_data import (
    get_artifact,
    get_paper_brief,
    list_artifacts,
    list_run_papers,
)
from ...repositories.research_citations import (
    get_citation,
    get_citation_evidence,
    list_citations,
    request_report_regeneration,
)
from ...services.research import ResearchExecutor
from ..schemas import ResearchDecisionResolveRequest, ResearchRunCreateRequest


router = APIRouter(prefix="/api/research", tags=["research"])
MAX_EVENT_ID = 9_223_372_036_854_775_807
PRIVATE_NO_STORE = "private, no-store"


def _executor(request: Request) -> ResearchExecutor:
    return cast(ResearchExecutor, request.app.state.research_executor)


def _not_found(exc: ResearchNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Research object not found",
        headers={"Cache-Control": PRIVATE_NO_STORE},
    )


def _conflict(exc: ResearchConflictError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def create_research_run(
    payload: ResearchRunCreateRequest,
    request: Request,
    user: CurrentUser,
) -> dict[str, Any]:
    if payload.thread_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Chat-associated Research Runs must be created through /api/chat/route",
        )
    with connect() as conn:
        try:
            result = create_harness_run(
                conn,
                user_id=user.id,
                title=payload.title,
                goal=payload.goal,
                thread_id=payload.thread_id,
            )
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc
    _executor(request).wake()
    return result


@router.get("/runs")
def research_runs(
    response: Response,
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    with connect() as conn:
        return {"items": list_runs(conn, user.id, limit=limit)}


@router.get("/runs/{run_id}")
def research_run(run_id: str, response: Response, user: CurrentUser) -> dict[str, Any]:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    with connect() as conn:
        try:
            return get_run_snapshot(conn, run_id, user.id)
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc


@router.get("/runs/{run_id}/artifacts")
def research_run_artifacts(
    run_id: str,
    response: Response,
    user: CurrentUser,
    artifact_type: str | None = Query(default=None, max_length=80),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    with connect() as conn:
        try:
            return {"items": list_artifacts(conn, run_id, user.id, artifact_type=artifact_type)}
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc


@router.get("/runs/{run_id}/artifacts/{artifact_id}")
def research_artifact(run_id: str, artifact_id: str, response: Response, user: CurrentUser) -> dict[str, Any]:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    with connect() as conn:
        try:
            return get_artifact(conn, run_id, artifact_id, user.id)
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc


@router.get("/runs/{run_id}/papers")
def research_run_papers(
    run_id: str,
    response: Response,
    user: CurrentUser,
    stage: str | None = Query(default=None, max_length=40),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    allowed = {"candidate", "selected", "excluded", "fulltext_ready", "read", "extracted"}
    if stage is not None and stage not in allowed:
        raise HTTPException(status_code=422, detail="unknown research paper stage")
    with connect() as conn:
        try:
            return {"items": list_run_papers(conn, run_id, user.id, stage=stage)}
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc


@router.get("/runs/{run_id}/papers/{paper_id}/brief")
def research_paper_brief(run_id: str, paper_id: int, response: Response, user: CurrentUser) -> dict[str, Any]:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    with connect() as conn:
        try:
            return get_paper_brief(conn, run_id, paper_id, user.id)
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc


@router.get("/runs/{run_id}/citations")
def research_citation_registry(run_id: str, response: Response, user: CurrentUser) -> dict[str, Any]:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    with connect() as conn:
        try:
            return {"items": list_citations(conn, run_id, user.id)}
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc


@router.get("/runs/{run_id}/citations/{citation_id}")
def research_citation(run_id: str, citation_id: str, response: Response, user: CurrentUser) -> dict[str, Any]:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    with connect() as conn:
        try:
            return get_citation(conn, run_id, citation_id, user.id)
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc


@router.get("/runs/{run_id}/citations/{citation_id}/evidence")
def research_citation_evidence(run_id: str, citation_id: str, response: Response, user: CurrentUser) -> dict[str, Any]:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    with connect() as conn:
        try:
            return get_citation_evidence(conn, run_id, citation_id, user.id)
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc


@router.get("/runs/{run_id}/reports")
def research_report_versions(run_id: str, response: Response, user: CurrentUser) -> dict[str, Any]:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    with connect() as conn:
        try:
            return {"items": list_artifacts(conn, run_id, user.id, artifact_type="research_report")}
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc


@router.get("/reports")
def research_report_library(response: Response, user: CurrentUser) -> dict[str, Any]:
    """List pinned report versions without exposing stale report facts."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    with connect() as conn:
        run_rows = conn.execute(
            """
            SELECT DISTINCT r.id, r.title
            FROM research_runs r JOIN research_artifacts a ON a.run_id = r.id
            WHERE r.user_id = ? AND a.artifact_type = 'research_report'
            ORDER BY r.updated_at DESC, r.id DESC
            """,
            (user.id,),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for run_row in run_rows:
            for artifact in list_artifacts(
                conn,
                str(run_row["id"]),
                user.id,
                artifact_type="research_report",
            ):
                current = bool(artifact.get("is_current")) and artifact.get("status") == "completed"
                content: dict[str, Any] = (
                    artifact["content"]
                    if current and isinstance(artifact.get("content"), dict)
                    else {}
                )
                result.append(
                    {
                        "artifact_id": str(artifact["id"]),
                        "artifact_version": int(artifact["version"]),
                        "run_id": str(run_row["id"]),
                        "run_title": str(run_row["title"]),
                        "title": str(content.get("title", "历史报告（内容已失效）")),
                        "topic": str(content.get("topic", "")),
                        "status": "completed" if current else "stale",
                        "is_current": current,
                        "created_at": str(artifact.get("created_at", "")),
                        "updated_at": str(artifact.get("updated_at", "")),
                    }
                )
    result.sort(key=lambda item: (item["updated_at"], item["artifact_version"]), reverse=True)
    return {"items": result}


@router.get("/runs/{run_id}/reports/{version}")
def research_report_version(run_id: str, version: int, response: Response, user: CurrentUser) -> dict[str, Any]:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    with connect() as conn:
        try:
            items = list_artifacts(conn, run_id, user.id, artifact_type="research_report")
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc
    selected = next((item for item in items if int(item["version"]) == version), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="Research object not found")
    return selected


@router.get("/runs/{run_id}/comparison-matrix")
def research_comparison_matrix(run_id: str, response: Response, user: CurrentUser) -> dict[str, Any]:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    with connect() as conn:
        try:
            items = list_artifacts(conn, run_id, user.id, artifact_type="comparison_matrix")
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc
    selected = next((item for item in items if item.get("is_current")), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="Research object not found")
    return selected


@router.post("/runs/{run_id}/report-regeneration")
def regenerate_research_report(run_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            result = request_report_regeneration(conn, run_id, user.id)
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc
        except ResearchConflictError as exc:
            raise _conflict(exc) from exc
    _executor(request).wake()
    return result


@router.post("/runs/{run_id}/pause")
def pause_research_run(run_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    return _request_run_action(run_id, "pause", request, user)


@router.post("/runs/{run_id}/cancel")
def cancel_research_run(run_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    return _request_run_action(run_id, "cancel", request, user)


def _request_run_action(
    run_id: str,
    action: str,
    request: Request,
    user: CurrentUser,
) -> dict[str, Any]:
    with connect() as conn:
        try:
            result = request_action(conn, run_id, user.id, action)
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc
        except ResearchConflictError as exc:
            raise _conflict(exc) from exc
    _executor(request).wake()
    return result


@router.post("/runs/{run_id}/resume")
def resume_research_run(run_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            result = resume_run(conn, run_id, user.id)
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc
        except ResearchConflictError as exc:
            raise _conflict(exc) from exc
    _executor(request).wake()
    return result


@router.post("/runs/{run_id}/retry")
def retry_research_run(run_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            result = retry_run(conn, run_id, user.id)
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc
        except ResearchConflictError as exc:
            raise _conflict(exc) from exc
    _executor(request).wake()
    return result


@router.post("/decisions/{decision_id}/resolve")
def answer_research_decision(
    decision_id: str,
    payload: ResearchDecisionResolveRequest,
    request: Request,
    user: CurrentUser,
) -> dict[str, Any]:
    with connect() as conn:
        try:
            result = resolve_decision(conn, decision_id, user.id, payload.option_id)
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc
        except ResearchConflictError as exc:
            raise _conflict(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    _executor(request).wake()
    return result


def _event_cursor(last_event_id: str | None, after: int | None) -> int:
    if last_event_id is not None:
        try:
            cursor = int(last_event_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be a non-negative integer") from exc
    else:
        cursor = after or 0
    if cursor < 0 or cursor > MAX_EVENT_ID:
        raise HTTPException(status_code=400, detail="event cursor is outside the supported range")
    return cursor


@router.get("/runs/{run_id}/events")
def research_run_events(
    run_id: str,
    request: Request,
    user: CurrentUser,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    after: int | None = Query(default=None, ge=0),
) -> StreamingResponse:
    cursor = _event_cursor(last_event_id, after)
    with connect() as conn:
        try:
            snapshot = get_run_snapshot(conn, run_id, user.id)
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc

    async def stream() -> AsyncIterator[str]:
        current = cursor
        idle_ticks = 0
        terminal = str(snapshot["status"]) in {"completed", "failed", "cancelled"}
        while True:
            if await request.is_disconnected():
                return
            with connect() as event_conn:
                try:
                    events = list_events(event_conn, run_id, user.id, after_id=current, limit=100)
                    current_snapshot = get_run_snapshot(event_conn, run_id, user.id)
                except ResearchNotFoundError:
                    return
            for event in events:
                current = int(event["id"])
                yield (
                    f"id: {current}\n"
                    f"event: {event['event_type']}\n"
                    f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
                )
            terminal = str(current_snapshot["status"]) in {"completed", "failed", "cancelled"}
            if terminal and not events:
                return
            if not events:
                idle_ticks += 1
                if idle_ticks >= 15:
                    yield ": heartbeat\n\n"
                    idle_ticks = 0
                await asyncio.sleep(1.0)
            else:
                idle_ticks = 0

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "private, no-store", "X-Accel-Buffering": "no"},
    )

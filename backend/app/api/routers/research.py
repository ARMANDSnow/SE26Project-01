from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, cast

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
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
from ...services.research import ResearchExecutor
from ..schemas import ResearchDecisionResolveRequest, ResearchRunCreateRequest


router = APIRouter(prefix="/api/research", tags=["research"])
MAX_EVENT_ID = 9_223_372_036_854_775_807


def _executor(request: Request) -> ResearchExecutor:
    return cast(ResearchExecutor, request.app.state.research_executor)


def _not_found(exc: ResearchNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research object not found")


def _conflict(exc: ResearchConflictError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def create_research_run(
    payload: ResearchRunCreateRequest,
    request: Request,
    user: CurrentUser,
) -> dict[str, Any]:
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
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    with connect() as conn:
        return {"items": list_runs(conn, user.id, limit=limit)}


@router.get("/runs/{run_id}")
def research_run(run_id: str, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            return get_run_snapshot(conn, run_id, user.id)
        except ResearchNotFoundError as exc:
            raise _not_found(exc) from exc


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

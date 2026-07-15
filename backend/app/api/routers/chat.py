from __future__ import annotations

import json
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ...auth.dependencies import CurrentUser
from ...config import get_settings
from ...db.connection import connect
from ...services.conversations import (
    create_thread,
    get_message_repository,
    get_thread,
    list_threads,
    prepare_run,
    stream_run,
    update_thread_head,
)
from ..schemas import ChatRunRequest, ThreadCreateRequest, ThreadHeadRequest


router = APIRouter(tags=["chat"])


@router.get("/api/papers/{paper_id}/chat/threads")
def paper_chat_threads(paper_id: int, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        return {"items": list_threads(conn, paper_id, user.id)}


@router.post("/api/papers/{paper_id}/chat/threads")
def add_paper_chat_thread(
    paper_id: int,
    payload: ThreadCreateRequest,
    user: CurrentUser,
) -> dict[str, Any]:
    with connect() as conn:
        try:
            return create_thread(conn, paper_id, user.id, payload.title)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="论文不存在") from exc


@router.get("/api/chat/threads")
def general_chat_threads(user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        return {"items": list_threads(conn, None, user.id)}


@router.post("/api/chat/threads")
def add_general_chat_thread(
    payload: ThreadCreateRequest,
    user: CurrentUser,
) -> dict[str, Any]:
    with connect() as conn:
        return create_thread(conn, None, user.id, payload.title)


@router.get("/api/chat/threads/{thread_id}")
def chat_thread(thread_id: str, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        result = get_thread(conn, thread_id, user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return result


@router.get("/api/chat/threads/{thread_id}/messages")
def chat_messages(thread_id: str, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            return get_message_repository(conn, thread_id, user.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="对话不存在") from exc


@router.patch("/api/chat/threads/{thread_id}/head")
def set_chat_thread_head(
    thread_id: str,
    payload: ThreadHeadRequest,
    user: CurrentUser,
) -> dict[str, Any]:
    with connect() as conn:
        try:
            return update_thread_head(conn, thread_id, payload.head_id, user.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/chat/runs")
def start_chat_run(payload: ChatRunRequest, user: CurrentUser) -> StreamingResponse:
    if not get_settings().llm_available:
        raise HTTPException(status_code=503, detail="LLM 未配置")
    with connect() as conn:
        try:
            run = prepare_run(
                conn,
                thread_id=payload.thread_id,
                user_message=payload.user_message.model_dump() if payload.user_message else None,
                parent_message_id=payload.parent_message_id,
                assistant_message_id=payload.assistant_message_id,
                source_message_id=payload.source_message_id,
                message_token_limit=payload.message_token_limit,
                operation=payload.operation,
                user_id=user.id,
            )
        except ValueError as exc:
            status_code = 409 if str(exc) == "message id already exists" else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    def event_stream() -> Iterator[str]:
        with connect() as stream_conn:
            for event, data in stream_run(stream_conn, run):
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

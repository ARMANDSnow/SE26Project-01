from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ...auth.dependencies import CurrentUser
from ...db.connection import connect
from ...services.library import (
    create_folder,
    create_note,
    delete_folder,
    favorite_paper,
    list_folders,
    list_history,
    list_items,
    list_subscriptions,
    move_item as move_library_item,
    recommend_folder,
    subscribe as subscribe_topic,
)
from ...services.llm import LLMConfigurationError, LLMServiceError
from ..schemas import FavoriteRequest, FolderRequest, MoveLibraryItemRequest, NoteRequest, SubscriptionRequest


router = APIRouter(tags=["library"])


@router.post("/api/library/favorites")
def favorites(payload: FavoriteRequest, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            return favorite_paper(conn, payload.paper_id, payload.favorite, user_id=user.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="论文不存在") from exc


@router.get("/api/library/folders")
def library_folders(user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        return {"items": list_folders(conn, user_id=user.id)}


@router.post("/api/library/folders")
def add_library_folder(payload: FolderRequest, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            return create_folder(
                conn, payload.name, payload.parent_id, payload.description, user_id=user.id
            )
        except ValueError as exc:
            status_code = 409 if str(exc) == "folder already exists" else 404
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/api/library/folders/{folder_id}")
def remove_library_folder(folder_id: int, user: CurrentUser) -> dict[str, bool]:
    with connect() as conn:
        try:
            delete_folder(conn, folder_id, user_id=user.id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"deleted": True}


@router.get("/api/library/items")
def library_items(user: CurrentUser, folder_id: int | None = None) -> dict[str, Any]:
    with connect() as conn:
        items = list_items(conn, folder_id=folder_id, user_id=user.id)
        return {"items": items, "count": len(items)}


@router.post("/api/library/items/{item_id}/move")
def move_item(
    item_id: int,
    payload: MoveLibraryItemRequest,
    user: CurrentUser,
) -> dict[str, Any]:
    with connect() as conn:
        try:
            return move_library_item(conn, item_id, payload.folder_id, user_id=user.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/library/items/{item_id}/recommend-folder")
def recommend_item_folder(item_id: int, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            return recommend_folder(conn, item_id, user_id=user.id)
        except ValueError as exc:
            status_code = 422 if str(exc) == "no candidate folders" else 404
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=f"LLM 未配置：{exc}") from exc
        except LLMServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/api/notes")
def notes(payload: NoteRequest, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            return create_note(conn, payload.paper_id, payload.note, payload.comment, user.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="论文不存在")


@router.get("/api/history")
def history(user: CurrentUser, limit: int = Query(default=30, ge=1, le=100)) -> dict[str, Any]:
    with connect() as conn:
        return {"items": list_history(conn, limit=limit, user_id=user.id)}


@router.get("/api/subscriptions")
def subscriptions(user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        return {"items": list_subscriptions(conn, user_id=user.id)}


@router.post("/api/subscriptions")
def subscribe(payload: SubscriptionRequest, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        return subscribe_topic(conn, payload.topic, user_id=user.id)

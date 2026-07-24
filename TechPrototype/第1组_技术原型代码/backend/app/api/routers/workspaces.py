from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...auth.dependencies import CurrentUser
from ...db.connection import connect
from ...repositories.workspaces import create_workspace, delete_workspace, get_workspace, list_workspaces, update_workspace

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4_000)
    project_id: str | None = Field(default=None, max_length=100)
    folder_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def one_source(self) -> "WorkspaceCreateRequest":
        if (self.project_id is None) == (self.folder_id is None):
            raise ValueError("workspace must bind exactly one project or folder")
        return self


class WorkspaceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4_000)

    @model_validator(mode="after")
    def has_change(self) -> "WorkspaceUpdateRequest":
        if self.title is None and self.description is None:
            raise ValueError("workspace update requires a title or description")
        return self


@router.get("")
def workspaces(user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        return {"items": list_workspaces(conn, user.id)}


@router.post("", status_code=status.HTTP_201_CREATED)
def workspace_create(payload: WorkspaceCreateRequest, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            return create_workspace(conn, user_id=user.id, **payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{workspace_id}")
def workspace_detail(workspace_id: str, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            return get_workspace(conn, workspace_id, user.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="workspace not found") from exc


@router.patch("/{workspace_id}")
def workspace_update(workspace_id: str, payload: WorkspaceUpdateRequest, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            return update_workspace(conn, workspace_id, user.id, **payload.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status_code=404 if str(exc) == "workspace not found" else 422, detail=str(exc)) from exc


@router.delete("/{workspace_id}")
def workspace_delete(workspace_id: str, user: CurrentUser) -> dict[str, bool]:
    with connect() as conn:
        try:
            delete_workspace(conn, workspace_id, user.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="workspace not found") from exc
    return {"deleted": True}

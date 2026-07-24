from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status

from ...auth.dependencies import CurrentUser, get_session_store
from ...config import get_settings
from ...db.connection import connect
from ...services.auth import InvalidCredentialsError, authenticate_user, register_user
from ..schemas import LoginRequest, RegisterRequest


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, session_id: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, response: Response) -> dict[str, Any]:
    with connect() as conn:
        try:
            user = register_user(conn, payload.username, payload.password.get_secret_value())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session_id = get_session_store(request).create(int(user["id"]))
    _set_session_cookie(response, session_id)
    return user


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    settings = get_settings()
    old_session_id = request.cookies.get(settings.session_cookie_name)
    store = get_session_store(request)
    with connect() as conn:
        try:
            user = authenticate_user(conn, payload.username, payload.password.get_secret_value())
        except InvalidCredentialsError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid username or password",
            ) from exc
    if old_session_id:
        store.delete(old_session_id)
    session_id = store.create(int(user["id"]))
    _set_session_cookie(response, session_id)
    return user


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    settings = get_settings()
    session_id = request.cookies.get(settings.session_cookie_name)
    if session_id:
        get_session_store(request).delete(session_id)
    response.delete_cookie(key=settings.session_cookie_name, path="/", samesite="lax")
    return {"logged_out": True}


@router.get("/me")
def me(user: CurrentUser) -> dict[str, Any]:
    return {"id": user.id, "username": user.username}

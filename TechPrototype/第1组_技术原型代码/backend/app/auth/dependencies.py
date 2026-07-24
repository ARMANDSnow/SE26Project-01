from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status

from ..config import get_settings
from ..db.connection import connect
from ..repositories.users import get_active_user_by_id
from .session import SessionStore


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    username: str


def get_session_store(request: Request) -> SessionStore:
    return cast(SessionStore, request.app.state.session_store)


def require_user(request: Request) -> AuthenticatedUser:
    settings = get_settings()
    cookie_value = request.cookies.get(settings.session_cookie_name)
    if not cookie_value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    store = get_session_store(request)
    session = store.get(cookie_value)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session expired")
    with connect() as conn:
        row = get_active_user_by_id(conn, session.user_id)
    if row is None:
        store.delete(cookie_value)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    return AuthenticatedUser(id=int(row["id"]), username=str(row["username"]))


CurrentUser = Annotated[AuthenticatedUser, Depends(require_user)]

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...auth.dependencies import CurrentUser
from ...db.connection import connect
from ...services.system import health_status, stats as get_stats


router = APIRouter(tags=["system"])


@router.get("/api/health")
def health() -> dict[str, Any]:
    with connect() as conn:
        return health_status(conn)


@router.get("/api/stats")
def stats(user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        return get_stats(conn, user.id)

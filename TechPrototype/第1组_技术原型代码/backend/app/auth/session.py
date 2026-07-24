from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from threading import RLock
from typing import Protocol


@dataclass(frozen=True)
class SessionRecord:
    user_id: int
    expires_at: float


class SessionStore(Protocol):
    def create(self, user_id: int) -> str: ...

    def get(self, session_id: str) -> SessionRecord | None: ...

    def delete(self, session_id: str) -> None: ...


class MemorySessionStore:
    """Thread-safe, process-local session storage with sliding expiration."""

    def __init__(self, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("session ttl must be positive")
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = RLock()

    def create(self, user_id: int) -> str:
        session_id = secrets.token_urlsafe(32)
        with self._lock:
            self._remove_expired(time.time())
            self._sessions[session_id] = SessionRecord(
                user_id=user_id,
                expires_at=time.time() + self._ttl_seconds,
            )
        return session_id

    def get(self, session_id: str) -> SessionRecord | None:
        now = time.time()
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                return None
            if record.expires_at <= now:
                self._sessions.pop(session_id, None)
                return None
            refreshed = SessionRecord(
                user_id=record.user_id,
                expires_at=now + self._ttl_seconds,
            )
            self._sessions[session_id] = refreshed
            return refreshed

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _remove_expired(self, now: float) -> None:
        expired = [
            session_id
            for session_id, record in self._sessions.items()
            if record.expires_at <= now
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)

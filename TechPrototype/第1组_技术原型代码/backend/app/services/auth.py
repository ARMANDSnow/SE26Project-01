from __future__ import annotations

import sqlite3
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..repositories.library import ensure_user_library
from ..repositories.users import create_user, get_user_by_username, update_password_hash


class InvalidCredentialsError(ValueError):
    pass


_PASSWORD_HASHER = PasswordHasher()
_DUMMY_PASSWORD_HASH = _PASSWORD_HASHER.hash("paperwiki-dummy-password")


def register_user(conn: sqlite3.Connection, username: str, password: str) -> dict[str, Any]:
    clean_username = username.strip()
    password_hash = _PASSWORD_HASHER.hash(password)
    user = create_user(conn, clean_username, password_hash, commit=False)
    ensure_user_library(conn, int(user["id"]))
    conn.commit()
    return public_user(user)


def authenticate_user(conn: sqlite3.Connection, username: str, password: str) -> dict[str, Any]:
    row = get_user_by_username(conn, username.strip())
    encoded = str(row["password_hash"]) if row is not None else _DUMMY_PASSWORD_HASH
    valid = False
    try:
        valid = bool(_PASSWORD_HASHER.verify(encoded, password))
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        valid = False
        if encoded != _DUMMY_PASSWORD_HASH:
            try:
                _PASSWORD_HASHER.verify(_DUMMY_PASSWORD_HASH, password)
            except (InvalidHashError, VerificationError, VerifyMismatchError):
                pass
    if row is None or not valid or not bool(row["is_active"]):
        raise InvalidCredentialsError("invalid username or password")
    if _PASSWORD_HASHER.check_needs_rehash(encoded):
        update_password_hash(conn, int(row["id"]), _PASSWORD_HASHER.hash(password))
    return public_user(dict(row))


def public_user(user: dict[str, Any] | sqlite3.Row) -> dict[str, Any]:
    return {"id": int(user["id"]), "username": str(user["username"])}

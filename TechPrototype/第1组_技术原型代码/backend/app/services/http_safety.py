from __future__ import annotations

from typing import AbstractSet, Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class UnsafeUrlError(ValueError):
    """Raised before a request is sent to an untrusted URL."""


def validate_trusted_https_url(url: str, allowed_hosts: AbstractSet[str]) -> str:
    candidate = url.strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError("URL has an invalid host or port") from exc

    host = (parsed.hostname or "").lower()
    trusted_hosts = {item.lower() for item in allowed_hosts}
    if parsed.scheme.lower() != "https" or host not in trusted_hosts:
        raise UnsafeUrlError("URL is not a trusted HTTPS source")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("URL user information is not allowed")
    if port not in (None, 443):
        raise UnsafeUrlError("URL port is not allowed")
    return candidate


class _TrustedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: AbstractSet[str]) -> None:
        super().__init__()
        self.allowed_hosts = frozenset(item.lower() for item in allowed_hosts)

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        safe_url = validate_trusted_https_url(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, safe_url)


def open_trusted_url(
    request: Request | str,
    *,
    allowed_hosts: AbstractSet[str],
    timeout: float,
) -> Any:
    initial_url = request.full_url if isinstance(request, Request) else request
    validate_trusted_https_url(initial_url, allowed_hosts)
    opener = build_opener(_TrustedRedirectHandler(allowed_hosts))
    return opener.open(request, timeout=timeout)

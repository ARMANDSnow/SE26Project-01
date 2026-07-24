from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookies import SimpleCookie
from statistics import quantiles
from time import perf_counter
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import argparse
import json
import os
import sys
import uuid


REQUESTS = [
    {"method": "GET", "path": "/api/papers?limit=20"},
    {"method": "GET", "path": "/api/wiki/search?q=RAG&limit=8"},
    {"method": "GET", "path": "/api/history?limit=20"},
    {"method": "GET", "path": "/api/graph?topic=RAG&limit=42"},
    {"method": "GET", "path": "/api/research/runs?limit=20"},
    {"method": "GET", "path": "/api/research/projects"},
]


def request(
    base_url: str,
    request_spec: dict[str, object],
    *,
    cookie: str | None = None,
) -> tuple[float, int, bytes, str | None]:
    start = perf_counter()
    body = request_spec.get("body")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    url_request = Request(
        base_url.rstrip("/") + str(request_spec["path"]),
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers=headers,
        method=str(request_spec["method"]),
    )
    try:
        with urlopen(url_request, timeout=5) as response:
            payload = response.read()
            status = response.status
            set_cookie = response.headers.get("Set-Cookie")
    except HTTPError as exc:
        payload = exc.read()
        status = exc.code
        set_cookie = exc.headers.get("Set-Cookie")
    return perf_counter() - start, status, payload, set_cookie


def session_cookie(set_cookie: str | None) -> str:
    if not set_cookie:
        raise RuntimeError("registration did not return a session cookie")
    parsed = SimpleCookie()
    parsed.load(set_cookie)
    if not parsed:
        raise RuntimeError("registration returned an invalid session cookie")
    morsel = next(iter(parsed.values()))
    return f"{morsel.key}={morsel.value}"


def require_success(
    base_url: str,
    request_spec: dict[str, object],
    *,
    cookie: str | None = None,
) -> tuple[float, bytes, str | None]:
    latency, status, payload, set_cookie = request(base_url, request_spec, cookie=cookie)
    if status >= 400:
        raise RuntimeError(f"{request_spec['method']} {request_spec['path']} returned HTTP {status}")
    return latency, payload, set_cookie


def main() -> int:
    parser = argparse.ArgumentParser(description="Local API concurrency smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--workers", type=int, default=100)
    parser.add_argument("--threshold", type=float, default=3.0)
    parser.add_argument("--create-threshold", type=float, default=0.5)
    parser.add_argument("--minimum-papers", type=int, default=120)
    args = parser.parse_args()

    suffix = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
    try:
        _, _, set_cookie = require_success(
            args.base_url,
            {
                "method": "POST",
                "path": "/api/auth/register",
                "body": {"username": f"perf_{suffix}", "password": f"perf-pass-{suffix}"},
            },
        )
        cookie = session_cookie(set_cookie)
        _, paper_payload, _ = require_success(
            args.base_url,
            {"method": "GET", "path": "/api/papers?limit=200"},
            cookie=cookie,
        )
        paper_count = len(json.loads(paper_payload)["items"])
        if paper_count < args.minimum_papers:
            raise RuntimeError(
                f"isolated performance fixture requires at least {args.minimum_papers} papers; got {paper_count}"
            )
        require_success(
            args.base_url,
            {
                "method": "POST",
                "path": "/api/research/projects",
                "body": {"title": "Iter16 performance project", "description": "isolated fixture"},
            },
            cookie=cookie,
        )
        create_latency, _, _ = require_success(
            args.base_url,
            {
                "method": "POST",
                "path": "/api/research/runs",
                "body": {
                    "title": "Iter16 performance run",
                    "goal": "Measure authenticated Run creation latency without external calls.",
                },
            },
            cookie=cookie,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "setup_error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    latencies: list[float] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                request,
                args.base_url,
                REQUESTS[index % len(REQUESTS)],
                cookie=cookie,
            )
            for index in range(args.requests)
        ]
        for future in as_completed(futures):
            try:
                latency, status, _, _ = future.result()
                latencies.append(latency)
                if status >= 400:
                    failures.append(f"HTTP {status}")
            except Exception as exc:
                failures.append(str(exc))

    if not latencies:
        print(json.dumps({"ok": False, "failures": failures[:5]}, ensure_ascii=False, indent=2))
        return 1

    p95 = quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
    max_latency = max(latencies)
    result = {
        "ok": (
            not failures
            and p95 < args.threshold
            and max_latency < args.threshold
            and create_latency < args.create_threshold
        ),
        "authenticated": True,
        "fixture_papers": paper_count,
        "requests": args.requests,
        "failures": len(failures),
        "p95_seconds": round(p95, 4),
        "max_seconds": round(max_latency, 4),
        "threshold_seconds": args.threshold,
        "run_create_seconds": round(create_latency, 4),
        "run_create_threshold_seconds": args.create_threshold,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

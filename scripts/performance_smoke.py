from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import quantiles
from time import perf_counter
from urllib.request import urlopen
import argparse
import json
import sys


PATHS = [
    "/api/papers?limit=20",
    "/api/wiki/search?q=RAG&limit=8",
    "/api/history?limit=20",
    "/api/graph?topic=RAG&limit=42",
]


def fetch(base_url: str, path: str) -> tuple[float, int]:
    start = perf_counter()
    with urlopen(base_url.rstrip("/") + path, timeout=5) as response:
        response.read()
        status = response.status
    return perf_counter() - start, status


def main() -> int:
    parser = argparse.ArgumentParser(description="Local API concurrency smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--workers", type=int, default=100)
    parser.add_argument("--threshold", type=float, default=3.0)
    args = parser.parse_args()

    latencies: list[float] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(fetch, args.base_url, PATHS[index % len(PATHS)])
            for index in range(args.requests)
        ]
        for future in as_completed(futures):
            try:
                latency, status = future.result()
                latencies.append(latency)
                if status >= 400:
                    failures.append(f"HTTP {status}")
            except Exception as exc:
                failures.append(str(exc))

    if not latencies:
        print(json.dumps({"ok": False, "failures": failures[:5]}, ensure_ascii=False, indent=2))
        return 1

    p95 = quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
    result = {
        "ok": not failures and max(latencies) < args.threshold,
        "requests": args.requests,
        "failures": len(failures),
        "p95_seconds": round(p95, 4),
        "max_seconds": round(max(latencies), 4),
        "threshold_seconds": args.threshold,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

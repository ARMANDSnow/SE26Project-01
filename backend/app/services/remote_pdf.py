from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..config import get_settings


MAX_REMOTE_PDF_BYTES = 30 * 1024 * 1024
REMOTE_PDF_TIMEOUT_SECONDS = 20
ALLOWED_REMOTE_PDF_HOSTS = {
    "arxiv.org",
    "dl.acm.org",
    "export.arxiv.org",
    "sigops.org",
    "www.sigops.org",
    "usenix.org",
    "www.usenix.org",
}
DOWNLOAD_CHUNK_SIZE = 64 * 1024
_download_lock = threading.Lock()


class RemotePdfError(ValueError):
    """Raised when a remote PDF cannot be safely downloaded."""


def _validate_pdf_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in ALLOWED_REMOTE_PDF_HOSTS:
        raise RemotePdfError("PDF 地址不是受信任的 HTTPS 来源")
    return parsed.geturl()


def _local_file(settings: Any, file_path: str | None) -> Path | None:
    if not file_path:
        return None
    upload_dir = settings.upload_dir.resolve()
    path = (settings.upload_dir / file_path).resolve()
    if upload_dir not in path.parents or not path.is_file():
        return None
    return path


def _download_pdf(url: str, target: Path) -> None:
    request = Request(
        url,
        headers={
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.1",
            "User-Agent": "PaperWiki/0.2 (+PDF cache)",
        },
    )
    temporary_path: Path | None = None
    try:
        with urlopen(request, timeout=REMOTE_PDF_TIMEOUT_SECONDS) as response:
            final_url = _validate_pdf_url(response.geturl())
            content_length = response.headers.get("Content-Length")
            try:
                declared_size = int(content_length) if content_length else 0
            except ValueError:
                declared_size = 0
            if declared_size > MAX_REMOTE_PDF_BYTES:
                raise RemotePdfError("远程 PDF 超过 30 MB 限制")

            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{target.stem}-",
                suffix=".part",
                dir=target.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                total = 0
                first_chunk = b""
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    if not first_chunk:
                        first_chunk = chunk[:5]
                    total += len(chunk)
                    if total > MAX_REMOTE_PDF_BYTES:
                        raise RemotePdfError("远程 PDF 超过 30 MB 限制")
                    temporary.write(chunk)
                if not first_chunk.startswith(b"%PDF-"):
                    raise RemotePdfError(f"远程地址未返回有效 PDF（最终地址：{final_url}）")
            os.replace(temporary_path, target)
            temporary_path = None
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RemotePdfError(f"远程 PDF 下载失败：{exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def ensure_local_pdf(conn: Any, paper_id: int) -> Path:
    """Return a safe local PDF path, downloading a trusted remote PDF once."""
    row = conn.execute(
        "SELECT file_path, pdf_url FROM papers WHERE id = ?",
        (paper_id,),
    ).fetchone()
    if row is None:
        raise RemotePdfError("paper not found")

    settings = get_settings()
    local_path = _local_file(settings, row["file_path"])
    if local_path is not None:
        return local_path
    if not row["pdf_url"]:
        raise RemotePdfError("paper has no PDF source")

    source_url = _validate_pdf_url(str(row["pdf_url"]))
    remote_dir = settings.upload_dir / "remote"
    filename = f"{hashlib.sha256(source_url.encode('utf-8')).hexdigest()}.pdf"
    target = (remote_dir / filename).resolve()
    if settings.upload_dir.resolve() not in target.parents:
        raise RemotePdfError("PDF 缓存路径无效")

    with _download_lock:
        if not target.is_file():
            _download_pdf(source_url, target)
    relative_path = target.relative_to(settings.upload_dir.resolve()).as_posix()
    conn.execute("UPDATE papers SET file_path = ? WHERE id = ?", (relative_path, paper_id))
    conn.commit()
    return target

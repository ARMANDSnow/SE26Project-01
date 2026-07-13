from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..config import get_settings
from ..database import get_paper_record, set_paper_asset_id
from ..models import AssetInfo, PaperId
from .asset_store import AssetNotFoundError, AssetStore, AssetStoreError, LocalAssetStore


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
_download_lock = threading.Lock()


class RemotePdfError(ValueError):
    pass


def _validate_pdf_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in ALLOWED_REMOTE_PDF_HOSTS:
        raise RemotePdfError("PDF URL is not a trusted HTTPS source")
    return parsed.geturl()


def default_asset_store() -> LocalAssetStore:
    return LocalAssetStore(get_settings().upload_dir)


class PaperPdfService:
    """Resolve paper IDs to immutable PDF assets without exposing storage paths."""

    def __init__(self, conn: sqlite3.Connection, store: AssetStore | None = None) -> None:
        self.conn = conn
        self.store = store or default_asset_store()

    def get(self, paper_id: PaperId | int) -> AssetInfo | None:
        paper = get_paper_record(self.conn, paper_id)
        if paper is None:
            raise RemotePdfError("paper not found")
        if paper.asset_id is None:
            return None
        try:
            return self.store.stat(paper.asset_id)
        except AssetNotFoundError:
            return None

    def ensure(self, paper_id: PaperId | int) -> AssetInfo:
        existing = self.get(paper_id)
        if existing is not None:
            return existing

        with _download_lock:
            existing = self.get(paper_id)
            if existing is not None:
                return existing
            paper = get_paper_record(self.conn, paper_id)
            if paper is None:
                raise RemotePdfError("paper not found")
            if not paper.pdf_url:
                raise RemotePdfError("paper has no PDF source")

            source_url = _validate_pdf_url(paper.pdf_url)
            request = Request(
                source_url,
                headers={
                    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.1",
                    "User-Agent": "PaperWiki/0.3 (+content-addressed PDF storage)",
                },
            )
            try:
                with urlopen(request, timeout=REMOTE_PDF_TIMEOUT_SECONDS) as response:
                    _validate_pdf_url(response.geturl())
                    asset = self.store.put_pdf(response)
            except (HTTPError, URLError, TimeoutError, OSError, AssetStoreError) as exc:
                raise RemotePdfError(f"remote PDF download failed: {exc}") from exc

            set_paper_asset_id(self.conn, paper_id, asset.id)
            return asset

    def attach(self, paper_id: PaperId | int, source: BinaryIO) -> AssetInfo:
        if get_paper_record(self.conn, paper_id) is None:
            raise RemotePdfError("paper not found")
        asset = self.store.put_pdf(source)
        set_paper_asset_id(self.conn, paper_id, asset.id)
        return asset

    def detach(self, paper_id: PaperId | int) -> None:
        set_paper_asset_id(self.conn, paper_id, None)

    def path_for(self, paper_id: PaperId | int) -> Path:
        asset = self.ensure(paper_id)
        return self.store.path_for(asset.id)


def ensure_local_pdf(conn: sqlite3.Connection, paper_id: PaperId | int) -> Path:
    return PaperPdfService(conn).path_for(paper_id)

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import BinaryIO, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request

from ..config import get_settings
from ..repositories.papers import get_paper_record, set_paper_asset_id
from ..models import AssetInfo, PaperId, PaperSource
from .asset_store import AssetNotFoundError, AssetStore, AssetStoreError, LocalAssetStore
from .http_safety import UnsafeUrlError, open_trusted_url, validate_trusted_https_url


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


def _has_pdf_eof(store: AssetStore, asset: AssetInfo) -> bool:
    try:
        with store.open(asset.id) as source:
            source.seek(max(0, asset.size_bytes - 4096))
            return b"%%EOF" in source.read()
    except (AssetNotFoundError, OSError):
        return False


def _validate_pdf_url(url: str) -> str:
    try:
        return validate_trusted_https_url(url, ALLOWED_REMOTE_PDF_HOSTS)
    except UnsafeUrlError as exc:
        raise RemotePdfError(str(exc)) from exc


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
            asset = self.store.stat(paper.asset_id)
        except AssetNotFoundError:
            return None
        if paper.source == PaperSource.UPLOAD:
            return asset
        return asset if _has_pdf_eof(self.store, asset) else None

    def ensure(
        self,
        paper_id: PaperId | int,
        *,
        before_attach: Callable[[sqlite3.Connection], None] | None = None,
    ) -> AssetInfo:
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
                with open_trusted_url(
                    request,
                    allowed_hosts=ALLOWED_REMOTE_PDF_HOSTS,
                    timeout=REMOTE_PDF_TIMEOUT_SECONDS,
                ) as response:
                    content_length = response.headers.get("Content-Length")
                    asset = self.store.put_pdf(response)
                    if content_length is not None and asset.size_bytes != int(content_length):
                        self.store.delete(asset.id)
                        raise RemotePdfError("remote PDF download was incomplete")
                    if not _has_pdf_eof(self.store, asset):
                        self.store.delete(asset.id)
                        raise RemotePdfError("remote PDF is missing its EOF marker")
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, AssetStoreError, UnsafeUrlError) as exc:
                raise RemotePdfError("remote PDF download failed") from exc

            if before_attach is None:
                set_paper_asset_id(self.conn, paper_id, asset.id)
            else:
                self.conn.execute("BEGIN IMMEDIATE")
                try:
                    before_attach(self.conn)
                    set_paper_asset_id(self.conn, paper_id, asset.id, commit=False)
                    self.conn.commit()
                except Exception:
                    self.conn.rollback()
                    raise
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

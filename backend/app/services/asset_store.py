from __future__ import annotations

from contextlib import AbstractContextManager
import hashlib
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import BinaryIO, Protocol

from ..models import AssetId, AssetInfo


MAX_PDF_BYTES = 30 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
_ASSET_ID_PATTERN = re.compile(r"^sha256:([0-9a-f]{64})$")


class AssetStoreError(ValueError):
    pass


class AssetNotFoundError(AssetStoreError):
    pass


class InvalidPdfError(AssetStoreError):
    pass


class AssetStore(Protocol):
    def put_pdf(self, source: BinaryIO) -> AssetInfo: ...

    def open(self, asset_id: AssetId) -> AbstractContextManager[BinaryIO]: ...

    def path_for(self, asset_id: AssetId) -> Path: ...

    def stat(self, asset_id: AssetId) -> AssetInfo: ...

    def exists(self, asset_id: AssetId) -> bool: ...

    def delete(self, asset_id: AssetId) -> None: ...


class LocalAssetStore:
    """Immutable, content-addressed PDF storage rooted in one local directory."""

    def __init__(self, root: Path, max_pdf_bytes: int = MAX_PDF_BYTES) -> None:
        self.root = root.resolve()
        self.max_pdf_bytes = max_pdf_bytes
        self._commit_lock = threading.Lock()

    @staticmethod
    def _digest(asset_id: AssetId) -> str:
        match = _ASSET_ID_PATTERN.fullmatch(str(asset_id))
        if match is None:
            raise AssetStoreError("invalid asset id")
        return match.group(1)

    def _path(self, asset_id: AssetId) -> Path:
        digest = self._digest(asset_id)
        path = (self.root / "blobs" / "sha256" / digest[:2] / digest[2:4] / f"{digest}.pdf").resolve()
        if self.root not in path.parents:
            raise AssetStoreError("invalid asset path")
        return path

    def put_pdf(self, source: BinaryIO) -> AssetInfo:
        temporary_dir = self.root / "tmp"
        temporary_dir.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        digest = hashlib.sha256()
        total = 0
        first_bytes = b""
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix="asset-",
                suffix=".part",
                dir=temporary_dir,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                while chunk := source.read(CHUNK_SIZE):
                    if not isinstance(chunk, bytes):
                        raise InvalidPdfError("PDF source did not return bytes")
                    if not first_bytes:
                        first_bytes = chunk[:5]
                    total += len(chunk)
                    if total > self.max_pdf_bytes:
                        raise InvalidPdfError("PDF cannot exceed 30 MB")
                    digest.update(chunk)
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())

            if not first_bytes.startswith(b"%PDF-"):
                raise InvalidPdfError("file is not a valid PDF")

            asset_id = AssetId(f"sha256:{digest.hexdigest()}")
            target = self._path(asset_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            with self._commit_lock:
                if target.is_file():
                    temporary_path.unlink(missing_ok=True)
                else:
                    os.replace(temporary_path, target)
                temporary_path = None
            return AssetInfo(id=asset_id, size_bytes=total)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def open(self, asset_id: AssetId) -> AbstractContextManager[BinaryIO]:
        return self.path_for(asset_id).open("rb")

    def path_for(self, asset_id: AssetId) -> Path:
        path = self._path(asset_id)
        if not path.is_file():
            raise AssetNotFoundError("asset not found")
        return path

    def stat(self, asset_id: AssetId) -> AssetInfo:
        path = self.path_for(asset_id)
        return AssetInfo(id=asset_id, size_bytes=path.stat().st_size)

    def exists(self, asset_id: AssetId) -> bool:
        try:
            return self._path(asset_id).is_file()
        except AssetStoreError:
            return False

    def delete(self, asset_id: AssetId) -> None:
        self._path(asset_id).unlink(missing_ok=True)

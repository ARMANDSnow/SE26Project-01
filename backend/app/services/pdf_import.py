from __future__ import annotations

from dataclasses import dataclass

from fastapi import UploadFile

from ..models import AssetInfo
from .asset_store import AssetStore


@dataclass(frozen=True, slots=True)
class SavedPdfUpload:
    asset: AssetInfo


def save_uploaded_pdf(upload: UploadFile, store: AssetStore) -> SavedPdfUpload:
    """Persist a bounded PDF without parsing untrusted content in the request worker."""
    filename = upload.filename or "paper.pdf"
    if not filename.lower().endswith(".pdf"):
        raise ValueError("only PDF files are supported")

    asset = store.put_pdf(upload.file)
    return SavedPdfUpload(asset=asset)

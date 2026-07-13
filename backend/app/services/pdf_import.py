from __future__ import annotations

from dataclasses import dataclass
import re

from fastapi import UploadFile
from pypdf import PdfReader

from ..models import AssetInfo
from .asset_store import AssetStore


@dataclass(frozen=True, slots=True)
class ExtractedPdf:
    asset: AssetInfo
    title: str
    text: str


def save_and_extract_pdf(upload: UploadFile, store: AssetStore) -> ExtractedPdf:
    filename = upload.filename or "paper.pdf"
    if not filename.lower().endswith(".pdf"):
        raise ValueError("only PDF files are supported")

    asset = store.put_pdf(upload.file)
    reader = PdfReader(str(store.path_for(asset.id)))
    metadata_title = str(reader.metadata.title or "").strip() if reader.metadata else ""
    text = "\n".join((page.extract_text() or "") for page in reader.pages[:2])
    text = re.sub(r"\s+", " ", text).strip()
    return ExtractedPdf(asset=asset, title=metadata_title, text=text[:6000])

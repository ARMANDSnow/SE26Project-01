from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType


PaperId = NewType("PaperId", int)
AssetId = NewType("AssetId", str)


class PaperSource(StrEnum):
    ARXIV = "arxiv"
    USENIX = "usenix"
    SIGOPS = "sigops"
    UPLOAD = "upload"


@dataclass(frozen=True, slots=True)
class PaperCandidate:
    source: PaperSource
    source_id: str
    title: str
    authors: tuple[str, ...]
    abstract: str
    categories: tuple[str, ...]
    primary_category: str
    published_at: str
    source_url: str | None = None
    pdf_url: str | None = None
    venue: str | None = None
    updated_at: str | None = None
    asset_id: AssetId | None = None
    processing_status: str = "pending"


@dataclass(frozen=True, slots=True)
class PaperRecord:
    id: PaperId
    source: PaperSource
    source_id: str
    title: str
    authors: tuple[str, ...]
    abstract: str
    categories: tuple[str, ...]
    primary_category: str
    published_at: str
    source_url: str | None
    pdf_url: str | None
    venue: str | None
    updated_at: str | None
    asset_id: AssetId | None
    title_hash: str
    processing_status: str
    created_at: str


@dataclass(frozen=True, slots=True)
class AssetInfo:
    id: AssetId
    size_bytes: int
    mime_type: str = "application/pdf"

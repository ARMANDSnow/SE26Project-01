from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
import re
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..config import get_settings
from .text_utils import tokenize


MIN_EXTRACTED_CHARS = 400
DEFAULT_CHUNK_CHARS = 1200
DEFAULT_CHUNK_OVERLAP = 160
MAX_SOURCE_BYTES = 12 * 1024 * 1024
MAX_PDF_PAGES = 24
MAX_EXTRACTED_TEXT_CHARS = 120_000


@dataclass(frozen=True)
class FullTextDocument:
    source_type: str
    source_url: str
    text: str


class _VisibleTextParser(HTMLParser):
    block_tags = {"article", "section", "p", "div", "li", "br", "h1", "h2", "h3", "h4", "tr"}
    hidden_tags = {"script", "style", "noscript", "svg", "math"}

    def __init__(self) -> None:
        super().__init__()
        self._hidden_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.hidden_tags:
            self._hidden_depth += 1
        if tag in self.block_tags:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.hidden_tags and self._hidden_depth:
            self._hidden_depth -= 1
        if tag in self.block_tags:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self._parts.append(data)

    def text(self) -> str:
        return normalize_fulltext(" ".join(self._parts))


def normalize_fulltext(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.replace("\r", "\n").splitlines()]
    cleaned = [line for line in lines if line]
    return "\n".join(cleaned).strip()


def metadata_document(paper: dict[str, Any]) -> FullTextDocument:
    authors = "、".join(paper.get("authors", []))
    categories = "、".join(paper.get("categories", []))
    text = normalize_fulltext(
        "\n".join(
            [
                f"Title: {paper.get('title', '')}",
                f"Authors: {authors}",
                f"Categories: {categories}",
                f"Abstract: {paper.get('abstract', '')}",
            ]
        )
    )
    return FullTextDocument(
        source_type="metadata",
        source_url=paper.get("arxiv_url") or paper.get("pdf_url") or "",
        text=text,
    )


def html_url_for_paper(paper: dict[str, Any]) -> str:
    arxiv_id = str(paper.get("arxiv_id", "")).strip()
    arxiv_url = str(paper.get("arxiv_url") or "")
    if "/abs/" in arxiv_url:
        return arxiv_url.replace("/abs/", "/html/")
    return f"https://arxiv.org/html/{arxiv_id}" if arxiv_id else arxiv_url


def extract_fulltext_document(paper: dict[str, Any]) -> FullTextDocument:
    settings = get_settings()
    if settings.should_fetch_fulltext:
        for source_type, source_url in (
            ("html", html_url_for_paper(paper)),
            ("pdf", paper.get("pdf_url") or ""),
        ):
            if not source_url:
                continue
            if not _is_allowed_arxiv_url(source_url):
                continue
            try:
                document = _extract_source(source_type, source_url)
            except Exception:
                continue
            if len(document.text) >= MIN_EXTRACTED_CHARS:
                return document
    return metadata_document(paper)


def _extract_source(source_type: str, source_url: str) -> FullTextDocument:
    request = Request(source_url, headers={"User-Agent": "arxiv-paper-wiki-mvp/0.2"})
    with urlopen(request, timeout=12) as response:
        if not _is_allowed_arxiv_url(response.geturl()):
            raise ValueError("fulltext fetch redirected outside arxiv.org")
        _validate_response(source_type, response.headers.get("Content-Type", ""))
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_SOURCE_BYTES:
            raise ValueError("fulltext source is too large")
        data = _read_limited(response, MAX_SOURCE_BYTES)
    if source_type == "html":
        text = extract_text_from_html(data.decode("utf-8", errors="ignore"))
    elif source_type == "pdf":
        text = extract_text_from_pdf(data)
    else:
        text = ""
    if len(text) < MIN_EXTRACTED_CHARS:
        raise ValueError(f"{source_type} source did not contain enough text")
    return FullTextDocument(source_type=source_type, source_url=source_url, text=text)


def _is_allowed_arxiv_url(source_url: str) -> bool:
    parsed = urlparse(source_url)
    host = parsed.netloc.lower()
    return parsed.scheme == "https" and (host == "arxiv.org" or host.endswith(".arxiv.org"))


def extract_text_from_html(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    return parser.text()[:MAX_EXTRACTED_TEXT_CHARS]


def extract_text_from_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    pages: list[str] = []
    for index, page in enumerate(reader.pages):
        if index >= MAX_PDF_PAGES:
            break
        pages.append(page.extract_text() or "")
        if sum(len(item) for item in pages) >= MAX_EXTRACTED_TEXT_CHARS:
            break
    text = normalize_fulltext("\n".join(pages))
    return text[:MAX_EXTRACTED_TEXT_CHARS]


def _validate_response(source_type: str, content_type: str) -> None:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if not normalized:
        return
    allowed = {
        "html": {"text/html", "application/xhtml+xml"},
        "pdf": {"application/pdf", "application/octet-stream"},
    }
    if normalized not in allowed.get(source_type, set()):
        raise ValueError(f"unexpected {source_type} content type: {normalized}")


def _read_limited(response: Any, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining > 0:
        chunk = response.read(min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > limit:
        raise ValueError("fulltext source exceeded max download size")
    return data


def chunk_document(
    document: FullTextDocument,
    max_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    text = normalize_fulltext(document.text)
    if not text:
        return []
    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = _find_boundary(text, start, end)
            if boundary > start:
                end = boundary
        raw = text[start:end]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        char_start = start + leading
        char_end = start + trailing
        content = text[char_start:char_end]
        if content:
            index = len(chunks)
            chunks.append(
                {
                    "source_type": document.source_type,
                    "source_url": document.source_url,
                    "chunk_index": index,
                    "heading": _chunk_heading(document.source_type, index),
                    "content": content,
                    "char_start": char_start,
                    "char_end": char_end,
                    "token_count": len(tokenize(content)),
                }
            )
        if end >= len(text):
            break
        next_start = max(0, end - overlap)
        start = end if next_start <= start else next_start
    return chunks


def chunks_for_paper(paper: dict[str, Any]) -> list[dict[str, Any]]:
    document = extract_fulltext_document(paper)
    chunks = chunk_document(document)
    if chunks:
        return chunks
    fallback = metadata_document(paper)
    return chunk_document(fallback)


def chunk_excerpt(chunks: list[dict[str, Any]], limit: int = 3600) -> str:
    excerpt = "\n\n".join(chunk["content"] for chunk in chunks[:3])
    return excerpt[:limit].strip()


def _find_boundary(text: str, start: int, end: int) -> int:
    minimum = start + max(200, (end - start) // 2)
    candidates = [text.rfind(mark, minimum, end) for mark in ["\n", "。", ".", " "]]
    boundary = max(candidates)
    return boundary + 1 if boundary > minimum else end


def _chunk_heading(source_type: str, index: int) -> str:
    labels = {
        "html": "HTML 正文",
        "pdf": "PDF 正文",
        "metadata": "Metadata",
    }
    return f"{labels.get(source_type, source_type)} #{index + 1}"

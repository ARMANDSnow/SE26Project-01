from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from pypdf import PdfReader


PDF_TEXT_PARSER_NAME = "pypdf_text"
PDF_TEXT_PARSER_VERSION = "pypdf-text-v1"
MIN_FAST_PDF_TEXT_CHARS = 8_000


@dataclass(frozen=True, slots=True)
class ParsedPdfTextDocument:
    parser_name: str
    parser_version: str
    markdown: str
    structure: dict[str, Any]


def parse_pdf_text(path: Path) -> ParsedPdfTextDocument | None:
    reader = PdfReader(str(path))
    page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
    markdown = _pages_to_markdown(page_texts)
    if len(markdown) < MIN_FAST_PDF_TEXT_CHARS:
        return None
    return ParsedPdfTextDocument(
        parser_name=PDF_TEXT_PARSER_NAME,
        parser_version=PDF_TEXT_PARSER_VERSION,
        markdown=markdown,
        structure={
            "source": "pdf_text",
            "pages": len(reader.pages),
            "extractor": "pypdf",
        },
    )


def _pages_to_markdown(page_texts: list[str]) -> str:
    sections: list[str] = []
    for index, raw_text in enumerate(page_texts, start=1):
        text = _normalize_pdf_text(raw_text)
        if not text:
            continue
        sections.append(f"## Page {index}\n\n{text}")
    return "\n\n".join(sections).strip()


def _normalize_pdf_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r", "\n").splitlines()]
    paragraphs: list[str] = []
    buffer: list[str] = []
    for line in lines:
        if not line:
            if buffer:
                paragraphs.append(" ".join(buffer))
                buffer = []
            continue
        if _looks_like_heading(line):
            if buffer:
                paragraphs.append(" ".join(buffer))
                buffer = []
            paragraphs.append(f"### {line}")
            continue
        buffer.append(line)
    if buffer:
        paragraphs.append(" ".join(buffer))
    return "\n\n".join(paragraphs)


def _looks_like_heading(line: str) -> bool:
    if len(line) > 100:
        return False
    if re.match(r"^(abstract|introduction|related work|methods?|experiments?|results?|discussion|conclusion|references)\b", line, re.I):
        return True
    return bool(re.match(r"^\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z0-9 ,:;()/-]{3,}$", line))

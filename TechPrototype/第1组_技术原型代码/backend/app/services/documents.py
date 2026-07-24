from __future__ import annotations

import importlib.metadata
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..repositories.papers import get_paper_record, replace_paper_chunks
from ..repositories.uploads import paper_is_accessible
from .fulltext import chunk_markdown
from .asset_store import AssetStore
from .remote_pdf import ensure_local_pdf
from .text_utils import deterministic_embedding


@dataclass(frozen=True, slots=True)
class ParsedPaperDocument:
    parser_version: str
    content_markdown: str
    structure_json: str
    token_count: int


def estimate_tokens(text: str) -> int:
    """Conservative tokenizer-independent estimate used for context admission."""
    if not text:
        return 0
    ascii_count = sum(1 for char in text if ord(char) < 128)
    non_ascii_count = len(text) - ascii_count
    return max(1, (ascii_count + 3) // 4 + non_ascii_count)


def extract_pdf_document(path: Path | str) -> ParsedPaperDocument:
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = PdfPipelineOptions(do_ocr=False)
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                backend=PyPdfiumDocumentBackend,
                pipeline_options=pipeline_options,
            )
        }
    )
    result = converter.convert(str(path))
    document = result.document
    markdown = document.export_to_markdown().strip()
    if not markdown:
        raise RuntimeError("Docling 未提取到正文")
    return ParsedPaperDocument(
        parser_version=importlib.metadata.version("docling"),
        content_markdown=markdown,
        structure_json=json.dumps(document.export_to_dict(), ensure_ascii=False),
        token_count=estimate_tokens(markdown),
    )


def mark_document_processing(
    conn: sqlite3.Connection,
    paper_id: int,
    source_hash: str,
    *,
    fence: Callable[[sqlite3.Connection], None] | None = None,
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        if fence is not None:
            fence(conn)
        conn.execute(
            """
            INSERT INTO paper_documents (paper_id, source_hash, status, error)
            VALUES (?, ?, 'processing', NULL)
            ON CONFLICT(paper_id) DO UPDATE SET source_hash = excluded.source_hash,
                status = 'processing', error = NULL,
                updated_at = CURRENT_TIMESTAMP
            """,
            (paper_id, source_hash),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def commit_parsed_document(
    conn: sqlite3.Connection,
    paper_id: int,
    source_hash: str,
    parsed: ParsedPaperDocument,
    *,
    fence: Callable[[sqlite3.Connection], None] | None = None,
    before_write: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if before_write is not None:
        before_write()
    chunks = chunk_markdown(parsed.content_markdown)
    for chunk in chunks:
        chunk["embedding_json"] = json.dumps(
            deterministic_embedding(str(chunk["content"])),
            ensure_ascii=False,
        )
    if before_write is not None:
        before_write()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if fence is not None:
            fence(conn)
        cursor = conn.execute(
            """
            UPDATE paper_documents
            SET parser_name = 'docling', parser_version = ?, source_hash = ?,
                content_markdown = ?, structure_json = ?, token_count = ?,
                status = 'completed', error = NULL, parsed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE paper_id = ? AND source_hash = ?
              AND EXISTS (
                  SELECT 1 FROM papers p
                  WHERE p.id = paper_documents.paper_id AND p.asset_id = ?
              )
            """,
            (
                parsed.parser_version,
                source_hash,
                parsed.content_markdown,
                parsed.structure_json,
                parsed.token_count,
                paper_id,
                source_hash,
                f"sha256:{source_hash}",
            ),
        )
        if cursor.rowcount == 0:
            raise RuntimeError("paper document row disappeared during parsing")
        replace_paper_chunks(conn, paper_id, source_hash, chunks, commit=False)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_paper_document(conn, paper_id) or {}


def mark_document_failed(
    conn: sqlite3.Connection,
    paper_id: int,
    source_hash: str,
    message: str,
    *,
    fence: Callable[[sqlite3.Connection], None] | None = None,
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        if fence is not None:
            fence(conn)
        conn.execute(
            """
            UPDATE paper_documents SET status = 'failed', error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE paper_id = ? AND source_hash = ?
              AND EXISTS (
                  SELECT 1 FROM papers p
                  WHERE p.id = paper_documents.paper_id AND p.asset_id = ?
              )
            """,
            (message[:500], paper_id, source_hash, f"sha256:{source_hash}"),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def parse_paper_document(
    conn: sqlite3.Connection,
    paper_id: int,
    user_id: int = 1,
    fence: Callable[[sqlite3.Connection], None] | None = None,
    store: AssetStore | None = None,
) -> dict[str, Any]:
    if not paper_is_accessible(conn, paper_id, user_id):
        raise ValueError("paper not found")
    paper = get_paper_record(conn, paper_id)
    if paper is None:
        raise ValueError("paper not found")

    path = ensure_local_pdf(conn, paper_id, store=store)
    source = str(path)
    paper = get_paper_record(conn, paper_id)
    if paper is None or paper.asset_id is None:
        raise ValueError("paper has no stored PDF asset")
    source_hash = str(paper.asset_id).removeprefix("sha256:")

    mark_document_processing(conn, paper_id, source_hash, fence=fence)

    try:
        parsed = extract_pdf_document(source)
        return commit_parsed_document(conn, paper_id, source_hash, parsed, fence=fence)
    except Exception as exc:
        try:
            mark_document_failed(conn, paper_id, source_hash, str(exc), fence=fence)
        except Exception:
            pass
        raise RuntimeError(f"Docling 解析失败：{exc}") from exc


def get_paper_document(conn: sqlite3.Connection, paper_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT paper_id, parser_name, parser_version, source_hash, content_markdown,
               token_count, status, error, parsed_at, updated_at
        FROM paper_documents WHERE paper_id = ?
        """,
        (paper_id,),
    ).fetchone()
    return dict(row) if row else None

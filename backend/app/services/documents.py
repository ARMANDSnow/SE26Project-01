from __future__ import annotations

import importlib.metadata
import json
import sqlite3
from typing import Any

from ..database import get_paper_record, replace_paper_chunks
from .fulltext import chunk_markdown
from .remote_pdf import ensure_local_pdf


def estimate_tokens(text: str) -> int:
    """Conservative tokenizer-independent estimate used for context admission."""
    if not text:
        return 0
    ascii_count = sum(1 for char in text if ord(char) < 128)
    non_ascii_count = len(text) - ascii_count
    return max(1, (ascii_count + 3) // 4 + non_ascii_count)


def parse_paper_document(conn: sqlite3.Connection, paper_id: int) -> dict[str, Any]:
    paper = get_paper_record(conn, paper_id)
    if paper is None:
        raise ValueError("paper not found")

    path = ensure_local_pdf(conn, paper_id)
    source = str(path)
    paper = get_paper_record(conn, paper_id)
    if paper is None or paper.asset_id is None:
        raise ValueError("paper has no stored PDF asset")
    source_hash = str(paper.asset_id).removeprefix("sha256:")

    conn.execute(
        """
        INSERT INTO paper_documents (paper_id, status, error)
        VALUES (?, 'processing', NULL)
        ON CONFLICT(paper_id) DO UPDATE SET status = 'processing', error = NULL,
            updated_at = CURRENT_TIMESTAMP
        """,
        (paper_id,),
    )
    conn.commit()

    try:
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
        result = converter.convert(source)
        document = result.document
        markdown = document.export_to_markdown().strip()
        if not markdown:
            raise RuntimeError("Docling 未提取到正文")
        structure = json.dumps(document.export_to_dict(), ensure_ascii=False)
        parser_version = importlib.metadata.version("docling")
        token_count = estimate_tokens(markdown)
        cursor = conn.execute(
            """
            UPDATE paper_documents
            SET parser_name = 'docling', parser_version = ?, source_hash = ?,
                content_markdown = ?, structure_json = ?, token_count = ?,
                status = 'completed', error = NULL, parsed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE paper_id = ?
            """,
            (parser_version, source_hash, markdown, structure, token_count, paper_id),
        )
        if cursor.rowcount == 0:
            raise RuntimeError("paper document row disappeared during parsing")
        replace_paper_chunks(
            conn,
            paper_id,
            source_hash,
            chunk_markdown(markdown),
            commit=False,
        )
        conn.commit()
    except Exception as exc:
        conn.execute(
            """
            UPDATE paper_documents SET status = 'failed', error = ?,
                updated_at = CURRENT_TIMESTAMP WHERE paper_id = ?
            """,
            (str(exc)[:1000], paper_id),
        )
        conn.commit()
        raise RuntimeError(f"Docling 解析失败：{exc}") from exc

    return get_paper_document(conn, paper_id) or {}


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

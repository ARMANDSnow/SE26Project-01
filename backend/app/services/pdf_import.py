from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from uuid import uuid4

from fastapi import UploadFile
from pypdf import PdfReader


MAX_PDF_BYTES = 30 * 1024 * 1024


@dataclass
class ExtractedPdf:
    path: str
    title: str
    text: str


def save_and_extract_pdf(upload: UploadFile, upload_dir: Path) -> ExtractedPdf:
    filename = upload.filename or "paper.pdf"
    if not filename.lower().endswith(".pdf"):
        raise ValueError("仅支持 PDF 文件")
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / f"{uuid4().hex}.pdf"
    total = 0
    try:
        with target.open("wb") as output:
            while chunk := upload.file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise ValueError("PDF 不能超过 30 MB")
                output.write(chunk)
        with target.open("rb") as source:
            if source.read(5) != b"%PDF-":
                raise ValueError("上传的文件不是有效 PDF")
        reader = PdfReader(str(target))
        metadata_title = str((reader.metadata or {}).get("/Title") or "").strip()
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:2])
        text = re.sub(r"\s+", " ", text).strip()
        return ExtractedPdf(path=target.name, title=metadata_title, text=text[:6000])
    except Exception:
        target.unlink(missing_ok=True)
        raise

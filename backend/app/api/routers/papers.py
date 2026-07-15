from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from ...auth.dependencies import CurrentUser, require_user
from ...config import get_settings
from ...db.connection import connect
from ...models import PaperCandidate, PaperSource
from ...services.agents import process_paper
from ...services.asset_store import AssetStoreError
from ...services.conversations import create_summary
from ...services.documents import parse_paper_document
from ...services.llm import LLMConfigurationError, LLMServiceError
from ...services.pdf_import import save_and_extract_pdf
from ...services.papers import list_catalog, read_chunks, read_detail, register_uploaded_paper, resolve_pdf
from ...services.remote_pdf import RemotePdfError, default_asset_store


router = APIRouter(
    prefix="/api/papers",
    tags=["papers"],
    dependencies=[Depends(require_user)],
)


@router.post("/upload")
def upload_paper(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    authors: str = Form(default=""),
    year: int = Form(default_factory=lambda: date.today().year),
) -> dict[str, Any]:
    try:
        extracted = save_and_extract_pdf(file, default_asset_store())
    except (ValueError, AssetStoreError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"PDF 读取失败：{exc}") from exc
    paper_title = title.strip() or extracted.title or Path(file.filename or "paper.pdf").stem
    paper = PaperCandidate(
        source=PaperSource.UPLOAD,
        source_id=uuid4().hex,
        source_url=None,
        venue="手动上传",
        asset_id=extracted.asset.id,
        title=paper_title,
        authors=tuple(item.strip() for item in authors.split(",") if item.strip()),
        abstract=extracted.text or "用户上传的 PDF，尚未提取到可用摘要。",
        categories=("manual",),
        primary_category="manual",
        published_at=f"{year}-01-01",
    )
    with connect() as conn:
        try:
            return register_uploaded_paper(conn, paper)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail="论文入库后无法读取") from exc


@router.get("")
def papers(
    user: CurrentUser,
    q: str = "",
    category: str = "",
    concept: str = "",
    author: str = "",
    favorite: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    with connect() as conn:
        items = list_catalog(
            conn,
            q=q,
            category=category,
            concept=concept,
            author=author,
            favorite=favorite,
            limit=limit,
            offset=offset,
            user_id=user.id,
        )
    return {"items": items, "count": len(items)}


@router.get("/{paper_id}")
def paper_detail(paper_id: int, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        detail = read_detail(conn, paper_id, user.id)
    if detail is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    return detail


@router.get("/{paper_id}/chunks")
def paper_chunks(
    paper_id: int,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    with connect() as conn:
        result = read_chunks(conn, paper_id, limit=limit, offset=offset)
        if result is None:
            raise HTTPException(status_code=404, detail="论文不存在")
        items, total = result
    return {"items": items, "count": len(items), "total": total}


PDF_CACHE_CONTROL = "private, max-age=3600, must-revalidate"


def _etag_matches(header_value: str | None, etag: str) -> bool:
    if not header_value:
        return False
    return any(candidate.strip() in {"*", etag} for candidate in header_value.split(","))


def _paper_pdf_response(
    paper_id: int,
    *,
    disposition: str,
    if_none_match: str | None = None,
) -> Response:
    try:
        with connect() as conn:
            pdf = resolve_pdf(conn, paper_id)
            if pdf is None:
                raise HTTPException(status_code=404, detail="论文不存在")
    except RemotePdfError as exc:
        if str(exc) == "paper not found":
            raise HTTPException(status_code=404, detail="论文不存在") from exc
        if str(exc) == "paper has no PDF source":
            raise HTTPException(status_code=404, detail="论文没有可用的 PDF") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AssetStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    etag = f'"{pdf.asset_id}"'
    cache_headers = {
        "Cache-Control": PDF_CACHE_CONTROL,
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if disposition == "inline" and _etag_matches(if_none_match, etag):
        return Response(status_code=304, headers=cache_headers)
    return FileResponse(
        pdf.path,
        media_type="application/pdf",
        filename=f"{pdf.title}.pdf",
        content_disposition_type=disposition,
        headers=cache_headers,
    )


@router.get("/{paper_id}/pdf")
def paper_pdf(
    paper_id: int,
    if_none_match: str | None = Header(default=None),
) -> Response:
    """Serve a same-origin PDF, downloading trusted remote sources on demand."""
    return _paper_pdf_response(paper_id, disposition="inline", if_none_match=if_none_match)


@router.get("/{paper_id}/pdf/download")
def download_paper_pdf(paper_id: int) -> Response:
    return _paper_pdf_response(paper_id, disposition="attachment")


@router.post("/{paper_id}/process")
def process(paper_id: int, user: CurrentUser) -> Any:
    if not get_settings().llm_available:
        raise HTTPException(status_code=503, detail="LLM 未配置")
    with connect() as conn:
        try:
            result = process_paper(conn, paper_id, user_id=user.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="论文不存在") from exc
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=f"LLM 未配置：{exc}") from exc
        except LLMServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result.get("status") == "failed":
        return JSONResponse(status_code=422, content=result)
    return result


@router.post("/{paper_id}/document/parse")
def parse_document(paper_id: int) -> dict[str, Any]:
    with connect() as conn:
        try:
            return parse_paper_document(conn, paper_id)
        except ValueError as exc:
            status_code = 404 if str(exc) == "paper not found" else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{paper_id}/summaries")
def generate_summary(paper_id: int) -> dict[str, Any]:
    with connect() as conn:
        try:
            return create_summary(conn, paper_id)
        except ValueError as exc:
            status_code = 404 if str(exc) == "paper not found" else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=f"LLM 未配置：{exc}") from exc
        except LLMServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

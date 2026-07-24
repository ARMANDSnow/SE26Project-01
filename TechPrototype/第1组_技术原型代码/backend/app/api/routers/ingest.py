from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ...auth.dependencies import CurrentUser, require_user
from ...config import get_settings
from ...services.http_safety import UnsafeUrlError
from ...services.ingestion import IngestionPersistenceError, save_ingested_papers
from ...services.sources import fetch_arxiv_papers, fetch_sigops_papers, fetch_usenix_papers
from ..schemas import IngestRequest, SourceIngestRequest


router = APIRouter(
    prefix="/api/ingest", tags=["ingest"], dependencies=[Depends(require_user)]
)


@router.post("/arxiv")
def ingest_arxiv(
    payload: IngestRequest,
    request: Request,
    user: CurrentUser,
) -> dict[str, Any]:
    settings = get_settings()
    categories = payload.categories or settings.default_categories
    try:
        papers = fetch_arxiv_papers(categories, payload.keywords, payload.max_results)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"arXiv 抓取失败：{exc}") from exc
    try:
        result = save_ingested_papers(papers, requested_by_user_id=user.id)
    except IngestionPersistenceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    executor = getattr(request.app.state, "paper_processing_executor", None)
    if executor is not None:
        executor.wake()
    return {**result, "categories": categories, "keywords": payload.keywords}


@router.post("/{source}")
def ingest_source(
    source: str,
    payload: SourceIngestRequest,
    request: Request,
    user: CurrentUser,
) -> dict[str, Any]:
    normalized_source = source.strip().lower()
    try:
        if normalized_source == "usenix":
            papers = fetch_usenix_papers(payload.venue or "osdi", payload.year, payload.max_results)
        elif normalized_source == "sigops":
            papers = fetch_sigops_papers(
                payload.venue or "sosp", payload.year, payload.max_results, payload.proceedings_url
            )
        else:
            raise HTTPException(status_code=404, detail="不支持的论文来源")
    except HTTPException:
        raise
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{normalized_source} 抓取失败：{exc}") from exc
    try:
        result = save_ingested_papers(papers, requested_by_user_id=user.id)
    except IngestionPersistenceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    executor = getattr(request.app.state, "paper_processing_executor", None)
    if executor is not None:
        executor.wake()
    return {**result, "source": normalized_source, "venue": payload.venue, "year": payload.year}

from __future__ import annotations

import sqlite3
import json
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from .config import get_settings
from .models import PaperCandidate, PaperSource
from .database import (
    add_note,
    connect,
    create_library_folder,
    delete_library_folder,
    find_existing_paper_id,
    get_history,
    get_paper_detail,
    get_subscriptions,
    init_db,
    list_library_folders,
    list_library_items,
    list_paper_chunks,
    list_papers,
    move_library_item,
    set_favorite,
    upsert_paper,
    upsert_subscription,
)
from .services.agents import process_paper
from .services.asset_store import AssetStoreError
from .services.pdf_import import save_and_extract_pdf
from .services.llm import LLMConfigurationError, LLMServiceError
from .services.qa_agent import run_qa_agent
from .services.search import build_graph, search_wiki
from .services.library import recommend_folder
from .services.remote_pdf import PaperPdfService, RemotePdfError, default_asset_store
from .services.sources import fetch_arxiv_papers, fetch_sigops_papers, fetch_usenix_papers
from .services.documents import parse_paper_document
from .services.conversations import (
    create_summary,
    create_thread,
    get_message_repository,
    get_thread,
    list_threads,
    prepare_run,
    stream_run,
    update_thread_head,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="论文阅读工具 API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:5174", "http://localhost:5174"],
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class IngestRequest(BaseModel):
    categories: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    max_results: int = Field(default=10, ge=1, le=50)


class SourceIngestRequest(IngestRequest):
    venue: str = ""
    year: int = Field(default_factory=lambda: date.today().year, ge=2000, le=2100)
    proceedings_url: str = ""


class FavoriteRequest(BaseModel):
    paper_id: int
    favorite: bool = True


class NoteRequest(BaseModel):
    paper_id: int
    note: str = Field(min_length=1, max_length=20_000)
    comment: str = Field(default="", max_length=2_000)


class SubscriptionRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=120)


class QARequest(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)
    paper_ids: list[int] = Field(default_factory=list)
    mode: Literal["agentic", "classic"] = "agentic"

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question must not be blank")
        return cleaned

    @field_validator("paper_ids")
    @classmethod
    def validate_paper_ids(cls, value: list[int]) -> list[int]:
        if len(value) > 20 or any(item <= 0 for item in value):
            raise ValueError("paper_ids must contain at most 20 positive IDs")
        return list(dict.fromkeys(value))


class FolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    parent_id: int | None = None
    description: str = Field(default="", max_length=300)


class MoveLibraryItemRequest(BaseModel):
    folder_id: int


class ThreadCreateRequest(BaseModel):
    title: str = Field(default="新对话", max_length=100)


class ThreadHeadRequest(BaseModel):
    head_id: str | None = None


class ChatUserMessage(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    parent_id: str | None = None
    source_message_id: str | None = None
    content: str = Field(min_length=1)


class ChatRunRequest(BaseModel):
    thread_id: str
    operation: str = Field(default="append", pattern="^(append|edit|regenerate)$")
    user_message: ChatUserMessage | None = None
    parent_message_id: str | None = None
    source_message_id: str | None = None
    assistant_message_id: str = Field(min_length=1, max_length=100)
    message_token_limit: int = Field(default=12000, ge=0, le=100000)


@app.get("/api/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM papers").fetchone()["count"]
    return {
        "ok": True,
        "papers": count,
        "llm_available": settings.llm_available,
        "llm_model": settings.llm_chat_model if settings.llm_available else None,
    }


@app.get("/api/stats")
def stats(x_user_id: int = Header(default=1)) -> dict[str, Any]:
    with connect() as conn:
        paper_count = conn.execute("SELECT COUNT(*) AS count FROM papers").fetchone()["count"]
        processed_count = conn.execute("SELECT COUNT(*) AS count FROM papers WHERE processing_status = 'processed'").fetchone()["count"]
        favorite_count = conn.execute("SELECT COUNT(*) AS count FROM library_items WHERE user_id = ?", (x_user_id,)).fetchone()["count"]
        concept_count = conn.execute("SELECT COUNT(*) AS count FROM concepts").fetchone()["count"]
        notes_count = conn.execute("SELECT COUNT(*) AS count FROM notes").fetchone()["count"]
        categories = conn.execute(
            "SELECT primary_category AS category, COUNT(*) AS count FROM papers GROUP BY primary_category ORDER BY count DESC"
        ).fetchall()
    return {
        "papers": paper_count,
        "processed": processed_count,
        "favorites": favorite_count,
        "concepts": concept_count,
        "notes": notes_count,
        "categories": [dict(row) for row in categories],
    }


def _save_ingested_papers(papers: list[PaperCandidate]) -> dict[str, Any]:
    paper_ids: list[int] = []
    duplicate_count = 0
    try:
        with connect() as conn:
            for paper in papers:
                if find_existing_paper_id(conn, paper) is not None:
                    duplicate_count += 1
                paper_id = upsert_paper(conn, paper, commit=False)
                if paper_id not in paper_ids:
                    paper_ids.append(paper_id)
            conn.commit()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"论文入库失败：{exc}") from exc
    return {
        "count": max(0, len(papers) - duplicate_count),
        "fetched_count": len(papers),
        "duplicate_count": duplicate_count,
        "paper_ids": paper_ids,
    }


@app.post("/api/ingest/arxiv")
def ingest_arxiv(payload: IngestRequest) -> dict[str, Any]:
    settings = get_settings()
    categories = payload.categories or settings.default_categories
    try:
        papers = fetch_arxiv_papers(categories, payload.keywords, payload.max_results)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"arXiv 抓取失败：{exc}") from exc
    return {
        **_save_ingested_papers(papers),
        "categories": categories,
        "keywords": payload.keywords,
    }


@app.post("/api/ingest/{source}")
def ingest_source(source: str, payload: SourceIngestRequest) -> dict[str, Any]:
    normalized_source = source.strip().lower()
    try:
        if normalized_source == "usenix":
            papers = fetch_usenix_papers(payload.venue or "osdi", payload.year, payload.max_results)
        elif normalized_source == "sigops":
            papers = fetch_sigops_papers(payload.venue or "sosp", payload.year, payload.max_results, payload.proceedings_url)
        else:
            raise HTTPException(status_code=404, detail="不支持的论文来源")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{normalized_source} 抓取失败：{exc}") from exc
    return {
        **_save_ingested_papers(papers),
        "source": normalized_source,
        "venue": payload.venue,
        "year": payload.year,
    }


@app.post("/api/papers/upload")
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
        paper_id = upsert_paper(conn, paper)
        detail = get_paper_detail(conn, paper_id)
    if detail is None:
        raise HTTPException(status_code=500, detail="论文入库后无法读取")
    return detail


@app.get("/api/papers")
def papers(
    q: str = "",
    category: str = "",
    concept: str = "",
    author: str = "",
    favorite: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_user_id: int = Header(default=1),
) -> dict[str, Any]:
    with connect() as conn:
        items = list_papers(conn, q=q, category=category, concept=concept, author=author, favorite=favorite, limit=limit, offset=offset, user_id=x_user_id)
    return {"items": items, "count": len(items)}


@app.get("/api/papers/{paper_id}")
def paper_detail(paper_id: int, x_user_id: int = Header(default=1)) -> dict[str, Any]:
    with connect() as conn:
        detail = get_paper_detail(conn, paper_id, user_id=x_user_id)
        if detail is not None:
            conn.execute("INSERT INTO reading_history (paper_id, action) VALUES (?, ?)", (paper_id, "阅读论文详情"))
            conn.commit()
    if detail is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    return detail


@app.get("/api/papers/{paper_id}/chunks")
def paper_chunks(
    paper_id: int,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    with connect() as conn:
        if get_paper_detail(conn, paper_id) is None:
            raise HTTPException(status_code=404, detail="论文不存在")
        items, total = list_paper_chunks(conn, paper_id, limit=limit, offset=offset)
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
            row = conn.execute("SELECT title FROM papers WHERE id = ?", (paper_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="论文不存在")
            service = PaperPdfService(conn)
            asset = service.ensure(paper_id)
            file_path = service.store.path_for(asset.id)
            title = str(row["title"])
    except RemotePdfError as exc:
        if str(exc) == "paper not found":
            raise HTTPException(status_code=404, detail="论文不存在") from exc
        if str(exc) == "paper has no PDF source":
            raise HTTPException(status_code=404, detail="论文没有可用的 PDF") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AssetStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    etag = f'"{asset.id}"'
    cache_headers = {
        "Cache-Control": PDF_CACHE_CONTROL,
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if disposition == "inline" and _etag_matches(if_none_match, etag):
        return Response(status_code=304, headers=cache_headers)
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=f"{title}.pdf",
        content_disposition_type=disposition,
        headers=cache_headers,
    )


@app.get("/api/papers/{paper_id}/pdf")
def paper_pdf(
    paper_id: int,
    if_none_match: str | None = Header(default=None),
) -> Response:
    """Serve a same-origin PDF, downloading trusted remote sources on demand."""
    return _paper_pdf_response(paper_id, disposition="inline", if_none_match=if_none_match)


@app.get("/api/papers/{paper_id}/pdf/download")
def download_paper_pdf(paper_id: int) -> Response:
    return _paper_pdf_response(paper_id, disposition="attachment")


@app.post("/api/papers/{paper_id}/process")
def process(paper_id: int) -> Any:
    if not get_settings().llm_available:
        raise HTTPException(status_code=503, detail="LLM 未配置")
    with connect() as conn:
        try:
            result = process_paper(conn, paper_id)
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


@app.post("/api/papers/{paper_id}/document/parse")
def parse_document(paper_id: int) -> dict[str, Any]:
    with connect() as conn:
        try:
            return parse_paper_document(conn, paper_id)
        except ValueError as exc:
            status = 404 if str(exc) == "paper not found" else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/papers/{paper_id}/summaries")
def generate_summary(paper_id: int) -> dict[str, Any]:
    with connect() as conn:
        try:
            return create_summary(conn, paper_id)
        except ValueError as exc:
            status = 404 if str(exc) == "paper not found" else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=f"LLM 未配置：{exc}") from exc
        except LLMServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/papers/{paper_id}/chat/threads")
def paper_chat_threads(paper_id: int, x_user_id: int = Header(default=1)) -> dict[str, Any]:
    with connect() as conn:
        return {"items": list_threads(conn, paper_id, x_user_id)}


@app.post("/api/papers/{paper_id}/chat/threads")
def add_paper_chat_thread(
    paper_id: int,
    payload: ThreadCreateRequest,
    x_user_id: int = Header(default=1),
) -> dict[str, Any]:
    with connect() as conn:
        try:
            return create_thread(conn, paper_id, x_user_id, payload.title)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="论文不存在") from exc


@app.get("/api/chat/threads/{thread_id}")
def chat_thread(thread_id: str, x_user_id: int = Header(default=1)) -> dict[str, Any]:
    with connect() as conn:
        result = get_thread(conn, thread_id, x_user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return result


@app.get("/api/chat/threads/{thread_id}/messages")
def chat_messages(thread_id: str, x_user_id: int = Header(default=1)) -> dict[str, Any]:
    with connect() as conn:
        try:
            return get_message_repository(conn, thread_id, x_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="对话不存在") from exc


@app.patch("/api/chat/threads/{thread_id}/head")
def set_chat_thread_head(
    thread_id: str,
    payload: ThreadHeadRequest,
    x_user_id: int = Header(default=1),
) -> dict[str, Any]:
    with connect() as conn:
        try:
            return update_thread_head(conn, thread_id, payload.head_id, x_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/chat/runs")
def start_chat_run(payload: ChatRunRequest, x_user_id: int = Header(default=1)) -> StreamingResponse:
    if not get_settings().llm_available:
        raise HTTPException(status_code=503, detail="LLM 未配置")
    with connect() as conn:
        try:
            run = prepare_run(
                conn,
                thread_id=payload.thread_id,
                user_message=payload.user_message.model_dump() if payload.user_message else None,
                parent_message_id=payload.parent_message_id,
                assistant_message_id=payload.assistant_message_id,
                source_message_id=payload.source_message_id,
                message_token_limit=payload.message_token_limit,
                user_id=x_user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def event_stream() -> Iterator[str]:
        with connect() as stream_conn:
            for event, data in stream_run(stream_conn, run):
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/wiki/search")
def wiki_search(q: str = "", limit: int = Query(default=8, ge=1, le=50)) -> dict[str, Any]:
    with connect() as conn:
        results = search_wiki(conn, q, limit=limit)
    return {"items": results, "count": len(results)}


@app.get("/api/graph")
def graph(topic: str = "", limit: int = Query(default=42, ge=8, le=80)) -> dict[str, Any]:
    with connect() as conn:
        return build_graph(conn, topic=topic, limit=limit)


@app.post("/api/qa")
def qa(payload: QARequest) -> dict[str, Any]:
    with connect() as conn:
        try:
            if payload.paper_ids:
                placeholders = ",".join("?" for _ in payload.paper_ids)
                found = {
                    int(row["id"])
                    for row in conn.execute(
                        f"SELECT id FROM papers WHERE id IN ({placeholders})",
                        tuple(payload.paper_ids),
                    ).fetchall()
                }
                missing = [item for item in payload.paper_ids if item not in found]
                if missing:
                    raise HTTPException(status_code=404, detail=f"论文不存在：{missing}")
            return run_qa_agent(conn, payload.question, payload.paper_ids or None, mode=payload.mode)
        except HTTPException:
            raise
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=f"LLM 未配置：{exc}") from exc
        except LLMServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/library/favorites")
def favorites(payload: FavoriteRequest, x_user_id: int = Header(default=1)) -> dict[str, Any]:
    with connect() as conn:
        try:
            return set_favorite(conn, payload.paper_id, payload.favorite, user_id=x_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="论文不存在") from exc


@app.get("/api/library/folders")
def library_folders(x_user_id: int = Header(default=1)) -> dict[str, Any]:
    with connect() as conn:
        return {"items": list_library_folders(conn, user_id=x_user_id)}


@app.post("/api/library/folders")
def add_library_folder(payload: FolderRequest, x_user_id: int = Header(default=1)) -> dict[str, Any]:
    with connect() as conn:
        try:
            return create_library_folder(conn, payload.name, payload.parent_id, payload.description, user_id=x_user_id)
        except ValueError as exc:
            status = 409 if str(exc) == "folder already exists" else 404
            raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.delete("/api/library/folders/{folder_id}")
def remove_library_folder(folder_id: int, x_user_id: int = Header(default=1)) -> dict[str, bool]:
    with connect() as conn:
        try:
            delete_library_folder(conn, folder_id, user_id=x_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"deleted": True}


@app.get("/api/library/items")
def library_items(folder_id: int | None = None, x_user_id: int = Header(default=1)) -> dict[str, Any]:
    with connect() as conn:
        items = list_library_items(conn, folder_id=folder_id, user_id=x_user_id)
        return {"items": items, "count": len(items)}


@app.post("/api/library/items/{item_id}/move")
def move_item(item_id: int, payload: MoveLibraryItemRequest, x_user_id: int = Header(default=1)) -> dict[str, Any]:
    with connect() as conn:
        try:
            return move_library_item(conn, item_id, payload.folder_id, user_id=x_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/library/items/{item_id}/recommend-folder")
def recommend_item_folder(item_id: int, x_user_id: int = Header(default=1)) -> dict[str, Any]:
    with connect() as conn:
        try:
            return recommend_folder(conn, item_id, user_id=x_user_id)
        except ValueError as exc:
            status = 422 if str(exc) == "no candidate folders" else 404
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=f"LLM 未配置：{exc}") from exc
        except LLMServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/notes")
def notes(payload: NoteRequest) -> dict[str, Any]:
    with connect() as conn:
        detail = get_paper_detail(conn, payload.paper_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="论文不存在")
        return add_note(conn, payload.paper_id, payload.note, payload.comment)


@app.get("/api/history")
def history(limit: int = Query(default=30, ge=1, le=100)) -> dict[str, Any]:
    with connect() as conn:
        return {"items": get_history(conn, limit=limit)}


@app.get("/api/subscriptions")
def subscriptions() -> dict[str, Any]:
    with connect() as conn:
        return {"items": get_subscriptions(conn)}


@app.post("/api/subscriptions")
def subscribe(payload: SubscriptionRequest) -> dict[str, Any]:
    with connect() as conn:
        return upsert_subscription(conn, payload.topic)

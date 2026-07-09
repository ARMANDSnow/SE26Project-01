from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .database import (
    add_note,
    connect,
    find_existing_paper_id,
    get_history,
    get_paper_detail,
    get_subscriptions,
    init_db,
    list_papers,
    set_favorite,
    upsert_paper,
    upsert_subscription,
)
from .services.agents import process_paper
from .services.arxiv_client import fetch_arxiv_papers
from .services.search import answer_question, build_graph, search_wiki


app = FastAPI(title="arXiv 智能论文阅读工具 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class IngestRequest(BaseModel):
    categories: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    max_results: int = Field(default=10, ge=1, le=50)


class FavoriteRequest(BaseModel):
    paper_id: int
    favorite: bool = True


class NoteRequest(BaseModel):
    paper_id: int
    note: str = Field(min_length=1)
    comment: str = ""


class SubscriptionRequest(BaseModel):
    topic: str = Field(min_length=1)


class QARequest(BaseModel):
    question: str = Field(min_length=1)
    paper_ids: list[int] = Field(default_factory=list)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM papers").fetchone()["count"]
    return {"ok": True, "papers": count, "mock_llm": settings.should_use_mock_llm}


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    with connect() as conn:
        paper_count = conn.execute("SELECT COUNT(*) AS count FROM papers").fetchone()["count"]
        processed_count = conn.execute("SELECT COUNT(*) AS count FROM papers WHERE processing_status = 'processed'").fetchone()["count"]
        favorite_count = conn.execute("SELECT COUNT(*) AS count FROM papers WHERE is_favorite = 1").fetchone()["count"]
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


@app.post("/api/ingest/arxiv")
def ingest_arxiv(payload: IngestRequest) -> dict[str, Any]:
    settings = get_settings()
    categories = payload.categories or settings.default_categories
    try:
        papers = fetch_arxiv_papers(categories, payload.keywords, payload.max_results)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"arXiv 抓取失败：{exc}") from exc
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
        "categories": categories,
        "keywords": payload.keywords,
    }


@app.get("/api/papers")
def papers(
    q: str = "",
    category: str = "",
    concept: str = "",
    author: str = "",
    favorite: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    with connect() as conn:
        items = list_papers(conn, q=q, category=category, concept=concept, author=author, favorite=favorite, limit=limit, offset=offset)
    return {"items": items, "count": len(items)}


@app.get("/api/papers/{paper_id}")
def paper_detail(paper_id: int) -> dict[str, Any]:
    with connect() as conn:
        detail = get_paper_detail(conn, paper_id)
        if detail is not None:
            conn.execute("INSERT INTO reading_history (paper_id, action) VALUES (?, ?)", (paper_id, "阅读论文详情"))
            conn.commit()
    if detail is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    return detail


@app.post("/api/papers/{paper_id}/process")
def process(paper_id: int) -> Any:
    with connect() as conn:
        try:
            result = process_paper(conn, paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="论文不存在") from exc
    if result.get("status") == "failed":
        return JSONResponse(status_code=422, content=result)
    return result


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
        return answer_question(conn, payload.question, payload.paper_ids or None)


@app.post("/api/library/favorites")
def favorites(payload: FavoriteRequest) -> dict[str, Any]:
    with connect() as conn:
        try:
            return set_favorite(conn, payload.paper_id, payload.favorite)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="论文不存在") from exc


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

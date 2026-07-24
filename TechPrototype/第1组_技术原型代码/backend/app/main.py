from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routers import auth, chat, ingest, knowledge, library, papers, projects, research, system, workspaces
from .auth.session import MemorySessionStore
from .config import get_settings
from .db.schema import init_db
from .services.research import ResearchExecutor
from .services.paper_processing import PaperProcessingExecutor


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    init_db()
    executor = ResearchExecutor()
    application.state.research_executor = executor
    executor.start()
    settings = get_settings()
    paper_executor = PaperProcessingExecutor() if settings.paper_processing_enabled else None
    application.state.paper_processing_executor = paper_executor
    if paper_executor is not None:
        paper_executor.start()
    try:
        yield
    finally:
        if paper_executor is not None:
            paper_executor.stop()
        executor.stop()


def create_app() -> FastAPI:
    application = FastAPI(title="论文阅读工具 API", version="0.2.0", lifespan=lifespan)
    application.state.session_store = MemorySessionStore(get_settings().session_ttl_seconds)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(auth.router)
    application.include_router(system.router)
    application.include_router(ingest.router)
    application.include_router(papers.router)
    application.include_router(chat.router)
    application.include_router(knowledge.router)
    application.include_router(library.router)
    application.include_router(research.router)
    application.include_router(projects.router)
    application.include_router(workspaces.router)
    return application


app = create_app()

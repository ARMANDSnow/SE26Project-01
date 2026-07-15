from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...auth.dependencies import require_user
from ...db.connection import connect
from ...services.knowledge import PapersNotFoundError, answer_question
from ...services.llm import LLMConfigurationError, LLMServiceError
from ...services.search import build_graph, search_wiki
from ..schemas import QARequest


router = APIRouter(tags=["knowledge"], dependencies=[Depends(require_user)])


@router.get("/api/wiki/search")
def wiki_search(q: str = "", limit: int = Query(default=8, ge=1, le=50)) -> dict[str, Any]:
    with connect() as conn:
        results = search_wiki(conn, q, limit=limit)
    return {"items": results, "count": len(results)}


@router.get("/api/graph")
def graph(topic: str = "", limit: int = Query(default=42, ge=8, le=80)) -> dict[str, Any]:
    with connect() as conn:
        return build_graph(conn, topic=topic, limit=limit)


@router.post("/api/qa")
def qa(payload: QARequest) -> dict[str, Any]:
    with connect() as conn:
        try:
            return answer_question(
                conn,
                payload.question,
                payload.paper_ids,
                mode=payload.mode,
            )
        except PapersNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"论文不存在：{exc.paper_ids}") from exc
        except HTTPException:
            raise
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=f"LLM 未配置：{exc}") from exc
        except LLMServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

from __future__ import annotations

from typing import Any, Callable, TypeVar

from ..db.connection import connect
from ..repositories.research_data import (
    assert_safe_research_payload,
    authorize_budget_item,
    create_artifact,
    find_artifact_checkpoint,
    list_artifacts,
    list_run_papers,
    reserve_budget,
    settle_budget_call,
    upsert_run_paper,
)
from .research_agents import (
    CoordinatorAgent,
    ExtractionAgent,
    LLMStructuredResearchModel,
    ReaderAgent,
    ScreeningAgent,
    SearchAgent,
    StructuredResearchModel,
)
from .research_contracts import (
    CandidatePaper,
    CandidatePapersArtifact,
    ExtractionResult,
    ResearchBrief,
    ResearchStepError,
    ScreeningResult,
    SearchQueries,
    StrictResearchModel,
    ToolCallSummary,
)
from .research_tools import (
    ArxivSearchOutput,
    ChunkSearchOutput,
    FetchDocumentOutput,
    ImportPapersOutput,
    LocalSearchOutput,
    OpenEvidenceOutput,
    ParseDocumentOutput,
    ToolContext,
    ToolRegistry,
    build_research_tool_registry,
)


ModelT = TypeVar("ModelT", bound=StrictResearchModel)


class TopicResearchPipeline:
    def __init__(
        self,
        *,
        model: StructuredResearchModel | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        structured_model = model or LLMStructuredResearchModel()
        self.coordinator = CoordinatorAgent(structured_model)
        self.search_agent = SearchAgent(structured_model)
        self.screening_agent = ScreeningAgent(structured_model)
        self.reader_agent = ReaderAgent()
        self.extraction_agent = ExtractionAgent(structured_model)
        self.tools = tools or build_research_tool_registry()

    def handle(self, step: dict[str, Any]) -> dict[str, Any]:
        if not str(step.get("step_type", "")).startswith("topic."):
            raise ResearchStepError("unknown_topic_step", "未知的主题调研步骤。")
        with connect() as conn:
            run = conn.execute(
                "SELECT * FROM research_runs WHERE id = ? AND mode = 'topic'",
                (str(step["run_id"]),),
            ).fetchone()
        if run is None:
            raise ResearchStepError("topic_run_not_found", "主题调研任务不存在或模式不匹配。")
        context = ToolContext(
            run_id=str(step["run_id"]),
            step_id=str(step["id"]),
            user_id=int(run["user_id"]),
            worker_id=str(step["lease_owner"]),
            lease_generation=int(step["lease_generation"]),
        )
        handlers: dict[str, Callable[[dict[str, Any], ToolContext], dict[str, Any]]] = {
            "brief": self._brief,
            "query_planning": self._query_planning,
            "local_search": self._local_search,
            "arxiv_search": self._arxiv_search,
            "dedup_import": self._dedup_import,
            "screening": self._screening,
            "fulltext_acquisition": self._fulltext,
            "reading": self._reading,
            "extraction": self._extraction,
            "finalize_dataset": self._finalize,
        }
        try:
            handler = handlers[str(step["step_key"])]
        except KeyError as exc:
            raise ResearchStepError("unknown_topic_step", "未知的主题调研步骤。") from exc
        return handler(step, context)

    def _model_call(self, context: ToolContext, callback: Callable[[], ModelT]) -> ModelT:
        with connect() as conn:
            allowed = reserve_budget(
                conn,
                run_id=context.run_id,
                step_id=context.step_id,
                worker_id=context.worker_id,
                lease_generation=context.lease_generation,
                kind="model_calls",
            )
        if not allowed:
            from .research_contracts import ResearchWaitingInput

            raise ResearchWaitingInput("model budget requires input")
        succeeded = False
        try:
            result = callback()
            succeeded = True
            return result
        finally:
            with connect() as conn:
                settle_budget_call(
                    conn,
                    run_id=context.run_id,
                    step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    succeeded=succeeded,
                )

    @staticmethod
    def _checkpoint(step: dict[str, Any], key: str) -> dict[str, Any] | None:
        with connect() as conn:
            return find_artifact_checkpoint(
                conn,
                run_id=str(step["run_id"]),
                source_step_id=str(step["id"]),
                idempotency_key=key,
            )

    @staticmethod
    def _latest_artifact(run_id: str, user_id: int, artifact_type: str) -> dict[str, Any]:
        with connect() as conn:
            artifacts = list_artifacts(conn, run_id, user_id, artifact_type=artifact_type)
        if not artifacts:
            raise ResearchStepError("artifact_dependency_missing", "上游结构化产物不存在。")
        return artifacts[0]

    @staticmethod
    def _tool_summaries(items: list[ToolCallSummary]) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in items]

    def _brief(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = "topic:research_brief:v1"
        checkpoint = self._checkpoint(step, key)
        if checkpoint:
            return {"artifact_id": checkpoint["id"], "reused_checkpoint": True}
        goal = str(step.get("input", {}).get("goal", "")).strip()
        brief = self._model_call(context, lambda: self.coordinator.build_brief(goal))
        with connect() as conn:
            artifact = create_artifact(
                conn,
                run_id=context.run_id,
                source_step_id=context.step_id,
                worker_id=context.worker_id,
                lease_generation=context.lease_generation,
                artifact_type="research_brief",
                content=brief.model_dump(mode="json"),
                idempotency_key=key,
            )
        return {"artifact_id": artifact["id"], "topic": brief.topic, "schema_version": 1}

    def _query_planning(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = "topic:search_queries:v1"
        checkpoint = self._checkpoint(step, key)
        if checkpoint:
            return {"artifact_id": checkpoint["id"], "reused_checkpoint": True}
        brief = ResearchBrief.model_validate(
            self._latest_artifact(context.run_id, context.user_id, "research_brief")["content"]
        )
        queries = self._model_call(context, lambda: self.search_agent.plan_queries(brief))
        with connect() as conn:
            artifact = create_artifact(
                conn,
                run_id=context.run_id,
                source_step_id=context.step_id,
                worker_id=context.worker_id,
                lease_generation=context.lease_generation,
                artifact_type="search_queries",
                content=queries.model_dump(mode="json"),
                idempotency_key=key,
            )
        return {"artifact_id": artifact["id"], "query_count": len(queries.queries), "schema_version": 1}

    def _local_search(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = "topic:local_candidates:v1"
        checkpoint = self._checkpoint(step, key)
        if checkpoint:
            return {"artifact_id": checkpoint["id"], "candidate_count": len(checkpoint["content"]["items"]), "reused_checkpoint": True}
        plan = SearchQueries.model_validate(
            self._latest_artifact(context.run_id, context.user_id, "search_queries")["content"]
        )
        output, summary = self.tools.invoke(
            "local_paper_search",
            {"query": plan.queries[0], "category": plan.categories[0] if plan.categories else "", "limit": 20},
            context,
        )
        local = LocalSearchOutput.model_validate(output)
        candidates = CandidatePapersArtifact(
            items=[
                CandidatePaper(
                    paper_id=item.paper_id,
                    source=item.source,
                    source_id=item.source_id,
                    title=item.title,
                    authors=item.authors,
                    abstract=item.abstract,
                    categories=[item.primary_category],
                    primary_category=item.primary_category,
                    published_at=item.published_at,
                )
                for item in local.items
            ]
        )
        with connect() as conn:
            artifact = create_artifact(
                conn,
                run_id=context.run_id,
                source_step_id=context.step_id,
                worker_id=context.worker_id,
                lease_generation=context.lease_generation,
                artifact_type="candidate_papers",
                content=candidates.model_dump(mode="json"),
                idempotency_key=key,
            )
        return {"artifact_id": artifact["id"], "candidate_count": local.count, "tool_calls": self._tool_summaries([summary])}

    def _arxiv_search(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = "topic:arxiv_candidates:v1"
        checkpoint = self._checkpoint(step, key)
        if checkpoint:
            return {"artifact_id": checkpoint["id"], "candidate_count": len(checkpoint["content"]["items"]), "reused_checkpoint": True}
        plan = SearchQueries.model_validate(
            self._latest_artifact(context.run_id, context.user_id, "search_queries")["content"]
        )
        output, summary = self.tools.invoke(
            "arxiv_search",
            {"queries": plan.queries, "categories": plan.categories, "max_results": 30},
            context,
        )
        arxiv = ArxivSearchOutput.model_validate(output)
        content = CandidatePapersArtifact(items=arxiv.items)
        with connect() as conn:
            artifact = create_artifact(
                conn,
                run_id=context.run_id,
                source_step_id=context.step_id,
                worker_id=context.worker_id,
                lease_generation=context.lease_generation,
                artifact_type="candidate_papers",
                content=content.model_dump(mode="json"),
                idempotency_key=key,
            )
        return {"artifact_id": artifact["id"], "candidate_count": arxiv.count, "tool_calls": self._tool_summaries([summary])}

    def _dedup_import(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = "topic:imported_candidates:v1"
        checkpoint = self._checkpoint(step, key)
        if checkpoint:
            return {"artifact_id": checkpoint["id"], "candidate_count": len(checkpoint["content"]["items"]), "reused_checkpoint": True}
        with connect() as conn:
            artifacts = list_artifacts(conn, context.run_id, context.user_id, artifact_type="candidate_papers")
        candidates: dict[tuple[str, str], CandidatePaper] = {}
        for artifact in reversed(artifacts):
            for raw in artifact["content"].get("items", []):
                item = CandidatePaper.model_validate(raw)
                candidates[(item.source, item.source_id)] = item
        bounded = list(candidates.values())[:50]
        output, summary = self.tools.invoke(
            "deduplicated_import",
            {"items": [item.model_dump(mode="json") for item in bounded]},
            context,
        )
        imported = ImportPapersOutput.model_validate(output)
        identities = {(item.source, item.source_id): item.paper_id for item in imported.items}
        resolved = [item.model_copy(update={"paper_id": identities[(item.source, item.source_id)]}) for item in bounded]
        content = CandidatePapersArtifact(items=resolved)
        with connect() as conn:
            artifact = create_artifact(
                conn,
                run_id=context.run_id,
                source_step_id=context.step_id,
                worker_id=context.worker_id,
                lease_generation=context.lease_generation,
                artifact_type="candidate_papers",
                content=content.model_dump(mode="json"),
                idempotency_key=key,
            )
        return {
            "artifact_id": artifact["id"],
            "candidate_count": len(resolved),
            "imported_count": imported.imported_count,
            "reused_count": imported.reused_count,
            "tool_calls": self._tool_summaries([summary]),
        }

    def _screening(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = "topic:screening_result:v1"
        checkpoint = self._checkpoint(step, key)
        if checkpoint:
            result = ScreeningResult.model_validate(checkpoint["content"])
            return {"artifact_id": checkpoint["id"], "selected_count": sum(item.selected for item in result.items), "reused_checkpoint": True}
        brief = ResearchBrief.model_validate(
            self._latest_artifact(context.run_id, context.user_id, "research_brief")["content"]
        )
        candidates = CandidatePapersArtifact.model_validate(
            self._latest_artifact(context.run_id, context.user_id, "candidate_papers")["content"]
        ).items
        result = self._model_call(context, lambda: self.screening_agent.screen(brief, candidates))
        assert_safe_research_payload(result.model_dump(mode="json"))
        selected = sorted((item for item in result.items if item.selected), key=lambda item: item.score, reverse=True)
        ranks = {item.paper_id: index + 1 for index, item in enumerate(selected)}
        for item in result.items:
            with connect() as conn:
                upsert_run_paper(
                    conn,
                    run_id=context.run_id,
                    source_step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    paper_id=item.paper_id,
                    stage="selected" if item.selected else "excluded",
                    rank=ranks.get(item.paper_id),
                    score=item.score,
                    inclusion_reason=item.inclusion_reason,
                    exclusion_reason=item.exclusion_reason,
                )
        with connect() as conn:
            artifact = create_artifact(
                conn,
                run_id=context.run_id,
                source_step_id=context.step_id,
                worker_id=context.worker_id,
                lease_generation=context.lease_generation,
                artifact_type="screening_result",
                content=result.model_dump(mode="json"),
                idempotency_key=key,
            )
        return {"artifact_id": artifact["id"], "selected_count": len(selected), "excluded_count": len(result.items) - len(selected)}

    def _fulltext(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        papers = list_run_papers_for_context(context)
        summaries: list[ToolCallSummary] = []
        completed = 0
        reused = 0
        for paper in papers:
            if paper["stage"] not in {"selected", "fulltext_ready"}:
                continue
            if paper["stage"] == "fulltext_ready":
                completed += 1
                reused += 1
                continue
            with connect() as conn:
                allowed = authorize_budget_item(
                    conn,
                    run_id=context.run_id,
                    step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    kind="fulltext_papers",
                )
            if not allowed:
                from .research_contracts import ResearchWaitingInput

                raise ResearchWaitingInput("fulltext budget requires input")
            fetched_raw, fetched_summary = self.tools.invoke("fetch_document", {"paper_id": paper["paper_id"]}, context)
            parsed_raw, parsed_summary = self.tools.invoke("parse_document", {"paper_id": paper["paper_id"]}, context)
            fetched = FetchDocumentOutput.model_validate(fetched_raw)
            parsed = ParseDocumentOutput.model_validate(parsed_raw)
            if fetched.source_hash != parsed.source_hash:
                raise ResearchStepError("document_hash_changed", "PDF 在解析期间发生变化，未推进论文阶段。")
            with connect() as conn:
                upsert_run_paper(
                    conn,
                    run_id=context.run_id,
                    source_step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    paper_id=int(paper["paper_id"]),
                    stage="fulltext_ready",
                    source_hash=parsed.source_hash,
                )
            summaries.extend([fetched_summary, parsed_summary])
            completed += 1
            reused += int(fetched.reused and parsed.reused)
        if completed < 1:
            raise ResearchStepError("no_fulltext_ready", "没有论文完成全文准备。")
        return {"fulltext_ready_count": completed, "reused_count": reused, "tool_calls": self._tool_summaries(summaries)}

    def _reading(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        brief = ResearchBrief.model_validate(
            self._latest_artifact(context.run_id, context.user_id, "research_brief")["content"]
        )
        query = self.reader_agent.evidence_query(brief)
        summaries: list[ToolCallSummary] = []
        read_count = 0
        for paper in list_run_papers_for_context(context):
            if paper["stage"] not in {"fulltext_ready", "read"}:
                continue
            search_raw, search_summary = self.tools.invoke(
                "chunk_search",
                {"query": query, "paper_ids": [paper["paper_id"]], "limit": 4},
                context,
            )
            search = ChunkSearchOutput.model_validate(search_raw)
            if not search.items:
                raise ResearchStepError("paper_evidence_missing", "已解析论文没有匹配的正文证据。")
            refs: list[dict[str, Any]] = []
            for item in search.items[:2]:
                opened_raw, opened_summary = self.tools.invoke("open_evidence", {"ref_id": item.ref_id, "max_chars": 800}, context)
                opened = OpenEvidenceOutput.model_validate(opened_raw)
                refs.append(opened.evidence.model_dump(mode="json"))
                summaries.append(opened_summary)
            read_count += 1
            with connect() as conn:
                upsert_run_paper(
                    conn,
                    run_id=context.run_id,
                    source_step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    paper_id=int(paper["paper_id"]),
                    stage="read",
                    source_hash=str(paper["source_hash"]),
                )
            summaries.append(search_summary)
        return {"read_count": read_count, "tool_calls": self._tool_summaries(summaries)}

    def _extraction(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        brief = ResearchBrief.model_validate(
            self._latest_artifact(context.run_id, context.user_id, "research_brief")["content"]
        )
        query = self.reader_agent.evidence_query(brief)
        summaries: list[ToolCallSummary] = []
        artifact_ids: list[str] = []
        extracted_ids: list[int] = []
        for row in list_run_papers_for_context(context):
            if row["stage"] not in {"read", "extracted"}:
                continue
            paper_id = int(row["paper_id"])
            source_hash = str(row["source_hash"])
            paper_key = f"topic:paper_brief:{paper_id}:{source_hash}"
            checkpoint = self._checkpoint(step, paper_key)
            if checkpoint is not None:
                with connect() as conn:
                    upsert_run_paper(
                        conn,
                        run_id=context.run_id,
                        source_step_id=context.step_id,
                        worker_id=context.worker_id,
                        lease_generation=context.lease_generation,
                        paper_id=paper_id,
                        stage="extracted",
                        source_hash=source_hash,
                    )
                artifact_ids.append(str(checkpoint["id"]))
                extracted_ids.append(paper_id)
                continue
            search_raw, search_summary = self.tools.invoke(
                "chunk_search",
                {"query": query, "paper_ids": [paper_id], "limit": 6},
                context,
            )
            search = ChunkSearchOutput.model_validate(search_raw)
            opened_items: list[dict[str, Any]] = []
            for item in search.items[:3]:
                opened_raw, opened_summary = self.tools.invoke("open_evidence", {"ref_id": item.ref_id, "max_chars": 2_000}, context)
                opened = OpenEvidenceOutput.model_validate(opened_raw)
                opened_items.append(opened.model_dump(mode="json"))
                summaries.append(opened_summary)
            if not opened_items:
                raise ResearchStepError("paper_evidence_missing", "Paper Brief 缺少可追溯正文证据。")
            candidate = candidate_from_run_paper(row)
            paper_brief = self._model_call(
                context,
                lambda: self.extraction_agent.extract(
                    brief=brief,
                    paper=candidate,
                    source_hash=source_hash,
                    evidence=opened_items,
                ),
            )
            with connect() as conn:
                artifact = create_artifact(
                    conn,
                    run_id=context.run_id,
                    source_step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    artifact_type="paper_brief",
                    content=paper_brief.model_dump(mode="json"),
                    idempotency_key=paper_key,
                    paper_id=paper_id,
                    source_hash=source_hash,
                )
            with connect() as conn:
                upsert_run_paper(
                    conn,
                    run_id=context.run_id,
                    source_step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    paper_id=paper_id,
                    stage="extracted",
                    source_hash=source_hash,
                )
            artifact_ids.append(str(artifact["id"]))
            extracted_ids.append(paper_id)
            summaries.append(search_summary)
        result = ExtractionResult(paper_brief_artifact_ids=artifact_ids, extracted_paper_ids=extracted_ids)
        result_key = "topic:extraction_result:v1"
        with connect() as conn:
            artifact = create_artifact(
                conn,
                run_id=context.run_id,
                source_step_id=context.step_id,
                worker_id=context.worker_id,
                lease_generation=context.lease_generation,
                artifact_type="extraction_result",
                content=result.model_dump(mode="json"),
                idempotency_key=result_key,
            )
        return {"artifact_id": artifact["id"], "extracted_count": len(extracted_ids), "tool_calls": self._tool_summaries(summaries)}

    def _finalize(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del step
        papers = list_run_papers_for_context(context)
        with connect() as conn:
            artifacts = list_artifacts(conn, context.run_id, context.user_id)
        extracted = sum(item["stage"] == "extracted" for item in papers)
        if extracted < 1:
            raise ResearchStepError("research_dataset_empty", "没有有效 Paper Brief，不能完成调研数据集。")
        return {
            "dataset_ready": True,
            "candidate_count": len(papers),
            "selected_count": sum(item["stage"] in {"selected", "fulltext_ready", "read", "extracted"} for item in papers),
            "excluded_count": sum(item["stage"] == "excluded" for item in papers),
            "fulltext_count": sum(item["stage"] in {"fulltext_ready", "read", "extracted"} for item in papers),
            "paper_brief_count": extracted,
            "artifact_count": len(artifacts),
        }


def list_run_papers_for_context(context: ToolContext) -> list[dict[str, Any]]:
    with connect() as conn:
        return list_run_papers(conn, context.run_id, context.user_id)


def candidate_from_run_paper(row: dict[str, Any]) -> CandidatePaper:
    return CandidatePaper.model_validate(
        {
            "paper_id": int(row["paper_id"]),
            "source": str(row["source"]),
            "source_id": str(row["source_id"]),
            "title": str(row["title"]),
            "authors": list(row["authors"]),
            "abstract": str(row["abstract"]),
            "categories": [str(row["primary_category"])],
            "primary_category": str(row["primary_category"]),
            "published_at": str(row["published_at"]),
            "source_url": str(row["source_url"]) if row.get("source_url") else None,
        }
    )

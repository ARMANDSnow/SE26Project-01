from __future__ import annotations

import re
from typing import Any, Callable, TypeVar

from ..db.connection import connect
from ..repositories.research_data import (
    assert_safe_research_payload,
    authorize_budget_item,
    begin_model_call,
    complete_model_call,
    create_artifact,
    find_artifact_checkpoint,
    list_artifacts,
    list_run_papers,
    settle_budget_call,
    upsert_run_paper,
    wait_for_evidence_coverage,
)
from ..repositories.research_citations import (
    create_citation_registry,
    list_citations,
    list_current_evidence,
)
from .research_agents import (
    CoordinatorAgent,
    CitationVerifierAgent,
    ComparisonAgent,
    ExtractionAgent,
    LLMStructuredResearchModel,
    ReaderAgent,
    ReportAgent,
    ScreeningAgent,
    SearchAgent,
    SynthesisAgent,
    StructuredResearchModel,
)
from .research_contracts import (
    CandidatePaper,
    CandidatePapersArtifact,
    CitationRegistry,
    CitationRegistryEntry,
    CitationValidationResult,
    ComparisonMatrix,
    ExtractionResult,
    PaperBrief,
    ResearchBrief,
    ResearchReport,
    ResearchStepError,
    ScreeningResult,
    SearchQueries,
    SynthesisClaims,
    SynthesisPlan,
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


def _valid_arxiv_categories(categories: list[str]) -> list[str]:
    return [
        category.strip()
        for category in categories
        if re.fullmatch(r"[a-z]+(?:-[a-z]+)?\.[A-Za-z][A-Za-z.-]*", category.strip())
    ]


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
        self.synthesis_agent = SynthesisAgent(structured_model)
        self.comparison_agent = ComparisonAgent(structured_model)
        self.citation_verifier = CitationVerifierAgent()
        self.report_agent = ReportAgent(structured_model)
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
            "synthesis_planning": self._synthesis_planning,
            "comparison_matrix": self._comparison_matrix,
            "cross_paper_claims": self._cross_paper_claims,
            "citation_registry": self._citation_registry,
            "citation_verification": self._citation_verification,
            "report_generation": self._report_generation,
            "finalize_cited_report": self._finalize_cited_report,
        }
        try:
            handler = handlers[str(step["step_key"])]
        except KeyError as exc:
            raise ResearchStepError("unknown_topic_step", "未知的主题调研步骤。") from exc
        return handler(step, context)

    def _model_call(
        self,
        context: ToolContext,
        operation_key: str,
        model_type: type[ModelT],
        input_payload: dict[str, Any],
        callback: Callable[[], ModelT],
    ) -> ModelT:
        with connect() as conn:
            start_status, stored = begin_model_call(
                conn,
                run_id=context.run_id,
                step_id=context.step_id,
                worker_id=context.worker_id,
                lease_generation=context.lease_generation,
                idempotency_key=operation_key,
                model_name=model_type.__name__,
                input_payload=input_payload,
            )
        if start_status == "completed":
            return model_type.model_validate(stored)
        if start_status == "waiting":
            from .research_contracts import ResearchWaitingInput

            raise ResearchWaitingInput("model budget requires input")
        succeeded = False
        result: ModelT | None = None
        try:
            result = callback()
            safe_result = result.model_dump(mode="json")
            assert_safe_research_payload(safe_result)
            succeeded = True
            with connect() as conn:
                complete_model_call(
                    conn, run_id=context.run_id, step_id=context.step_id,
                    worker_id=context.worker_id, lease_generation=context.lease_generation,
                    idempotency_key=operation_key, result=safe_result, succeeded=True,
                )
            return result
        except Exception:
            with connect() as conn:
                complete_model_call(
                    conn, run_id=context.run_id, step_id=context.step_id,
                    worker_id=context.worker_id, lease_generation=context.lease_generation,
                    idempotency_key=operation_key, result=None, succeeded=False,
                )
            raise
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
        current = next((artifact for artifact in artifacts if artifact.get("is_current")), None)
        if current is None:
            current = next((artifact for artifact in artifacts if artifact.get("status") == "completed"), None)
        if current is None:
            raise ResearchStepError("artifact_dependency_missing", "上游结构化产物不存在。")
        return current

    @staticmethod
    def _tool_summaries(items: list[ToolCallSummary]) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in items]

    def _brief(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = "topic:research_brief:v1"
        checkpoint = self._checkpoint(step, key)
        if checkpoint:
            return {"artifact_id": checkpoint["id"], "reused_checkpoint": True}
        goal = str(step.get("input", {}).get("goal", "")).strip()
        brief = self._model_call(context, key, ResearchBrief, {"goal": goal}, lambda: self.coordinator.build_brief(goal))
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
        queries = self._model_call(context, key, SearchQueries, brief.model_dump(mode="json"), lambda: self.search_agent.plan_queries(brief))
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
            {
                "query": plan.queries[0],
                "category": (_valid_arxiv_categories(plan.categories) or [""])[0],
                "limit": 20,
            },
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
            {
                "queries": plan.queries,
                "categories": _valid_arxiv_categories(plan.categories),
                "max_results": 30,
            },
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
        screening_input = {"brief": brief.model_dump(mode="json"), "candidates": [item.model_dump(mode="json") for item in candidates]}
        result = self._model_call(context, key, ScreeningResult, screening_input, lambda: self.screening_agent.screen(brief, candidates))
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
            paper_key = f"{step['idempotency_key']}:paper_brief:{paper_id}:{source_hash}"
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
            extraction_input = {"research_brief": brief.model_dump(mode="json"), "paper": candidate.model_dump(mode="json"), "source_hash": source_hash, "opened_evidence": opened_items}
            paper_brief = self._model_call(
                context,
                paper_key,
                PaperBrief,
                extraction_input,
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
        result_key = f"{step['idempotency_key']}:extraction_result"
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

    def _current_paper_briefs(self, context: ToolContext) -> list[PaperBrief]:
        with connect() as conn:
            artifacts = list_artifacts(conn, context.run_id, context.user_id, artifact_type="paper_brief")
            evidence = list_current_evidence(conn, context.run_id, context.user_id)
        valid_evidence = {str(item["id"]) for item in evidence if item["status"] == "valid"}
        latest: dict[int, PaperBrief] = {}
        for artifact in artifacts:
            if not artifact.get("is_current"):
                continue
            parsed = PaperBrief.model_validate(artifact["content"])
            evidence_ids = {item.evidence_id for item in parsed.evidence_ids}
            if None in evidence_ids or not evidence_ids or not evidence_ids.issubset(valid_evidence):
                continue
            latest.setdefault(parsed.paper_id, parsed)
        if not latest:
            with connect() as conn:
                wait_for_evidence_coverage(
                    conn, run_id=context.run_id, step_id=context.step_id,
                    worker_id=context.worker_id, lease_generation=context.lease_generation,
                )
            from .research_contracts import ResearchWaitingInput

            raise ResearchWaitingInput("evidence coverage requires input")
        return list(latest.values())

    def _citation_candidates(self, context: ToolContext) -> list[dict[str, Any]]:
        briefs = self._current_paper_briefs(context)
        requested = {str(ref.evidence_id) for brief in briefs for ref in brief.evidence_ids if ref.evidence_id}
        with connect() as conn:
            evidence = list_current_evidence(conn, context.run_id, context.user_id)
        current = [item for item in evidence if item["status"] == "valid" and str(item["id"]) in requested]
        current.sort(key=lambda item: (int(item["paper_id"]), int(item["chunk_id"]), str(item["id"])))
        return [
            {
                "citation_key": f"C{index}", "evidence_id": str(item["id"]),
                "paper_id": int(item["paper_id"]), "heading": str(item["heading"]),
                "source_hash": str(item["source_hash"]),
            }
            for index, item in enumerate(current, start=1)
        ]

    @staticmethod
    def _validate_matrix(matrix: ComparisonMatrix, candidates: list[dict[str, Any]], briefs: list[PaperBrief]) -> None:
        candidate_by_key = {str(item["citation_key"]): item for item in candidates}
        allowed_papers = {item.paper_id: item.title for item in briefs}
        matrix_papers = {item.paper_id: item.title for item in matrix.papers}
        if matrix_papers != allowed_papers:
            raise ResearchStepError("comparison_identity_invalid", "对比矩阵包含 Run 之外的论文。")
        for cell in matrix.cells:
            if cell.paper_id not in allowed_papers or any(key not in candidate_by_key for key in cell.citation_keys):
                raise ResearchStepError("comparison_citation_invalid", "对比矩阵包含未知论文或引用。")
            cited = [candidate_by_key[key] for key in cell.citation_keys]
            expected_evidence = {str(item["evidence_id"]) for item in cited}
            if any(int(item["paper_id"]) != cell.paper_id for item in cited) or set(cell.evidence_ids) != expected_evidence:
                raise ResearchStepError("comparison_evidence_invalid", "对比矩阵 Evidence 与 Citation 不一致。")
        for item in [*matrix.agreements, *matrix.disagreements]:
            if any(key not in candidate_by_key for key in item.citation_keys):
                raise ResearchStepError("comparison_citation_invalid", "对比结论包含未知引用。")

    def _synthesis_planning(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = f"{step['idempotency_key']}:artifact"
        checkpoint = self._checkpoint(step, key)
        if checkpoint:
            return {"artifact_id": checkpoint["id"], "reused_checkpoint": True}
        brief = ResearchBrief.model_validate(self._latest_artifact(context.run_id, context.user_id, "research_brief")["content"])
        paper_briefs = self._current_paper_briefs(context)
        plan_input = {"research_brief": brief.model_dump(mode="json"), "paper_briefs": [item.model_dump(mode="json") for item in paper_briefs]}
        plan = self._model_call(context, key, SynthesisPlan, plan_input, lambda: self.synthesis_agent.plan(brief, paper_briefs))
        with connect() as conn:
            artifact = create_artifact(conn, run_id=context.run_id, source_step_id=context.step_id,
                worker_id=context.worker_id, lease_generation=context.lease_generation,
                artifact_type="synthesis_plan", content=plan.model_dump(mode="json"), idempotency_key=key)
        return {"artifact_id": artifact["id"], "dimension_count": len(plan.comparison_dimensions)}

    def _comparison_matrix(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = f"{step['idempotency_key']}:artifact"
        checkpoint = self._checkpoint(step, key)
        if checkpoint:
            return {"artifact_id": checkpoint["id"], "reused_checkpoint": True}
        plan = SynthesisPlan.model_validate(self._latest_artifact(context.run_id, context.user_id, "synthesis_plan")["content"])
        briefs = self._current_paper_briefs(context)
        candidates = self._citation_candidates(context)
        matrix_input = {"plan": plan.model_dump(mode="json"), "paper_briefs": [item.model_dump(mode="json") for item in briefs], "citation_candidates": candidates}
        matrix = self._model_call(context, key, ComparisonMatrix, matrix_input, lambda: self.comparison_agent.compare(plan, briefs, candidates))
        self._validate_matrix(matrix, candidates, briefs)
        with connect() as conn:
            artifact = create_artifact(conn, run_id=context.run_id, source_step_id=context.step_id,
                worker_id=context.worker_id, lease_generation=context.lease_generation,
                artifact_type="comparison_matrix", content=matrix.model_dump(mode="json"), idempotency_key=key)
        return {"artifact_id": artifact["id"], "cell_count": len(matrix.cells)}

    def _cross_paper_claims(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = f"{step['idempotency_key']}:artifact"
        checkpoint = self._checkpoint(step, key)
        if checkpoint:
            return {"artifact_id": checkpoint["id"], "reused_checkpoint": True}
        plan = SynthesisPlan.model_validate(self._latest_artifact(context.run_id, context.user_id, "synthesis_plan")["content"])
        matrix = ComparisonMatrix.model_validate(self._latest_artifact(context.run_id, context.user_id, "comparison_matrix")["content"])
        candidates = self._citation_candidates(context)
        allowed_keys = {str(item["citation_key"]) for item in candidates}
        paper_by_key = {str(item["citation_key"]): int(item["paper_id"]) for item in candidates}
        allowed_papers = set(paper_by_key.values())
        claims_input = {"plan": plan.model_dump(mode="json"), "comparison_matrix": matrix.model_dump(mode="json"), "citation_candidates": candidates}
        claims = self._model_call(context, key, SynthesisClaims, claims_input, lambda: self.synthesis_agent.claims(plan, matrix, candidates))
        for claim in claims.claims:
            cited_keys = [*claim.supporting_citations, *claim.contradicting_citations]
            if any(citation_key not in allowed_keys for citation_key in cited_keys):
                raise ResearchStepError("synthesis_citation_invalid", "跨论文主张包含未知引用。")
            covered = set(claim.covered_paper_ids)
            cited_papers = {paper_by_key[citation_key] for citation_key in cited_keys}
            if not covered.issubset(allowed_papers) or not cited_papers.issubset(covered):
                raise ResearchStepError("synthesis_identity_invalid", "跨论文主张的论文覆盖与引用身份不一致。")
        with connect() as conn:
            artifact = create_artifact(conn, run_id=context.run_id, source_step_id=context.step_id,
                worker_id=context.worker_id, lease_generation=context.lease_generation,
                artifact_type="synthesis_claims", content=claims.model_dump(mode="json"), idempotency_key=key)
        return {"artifact_id": artifact["id"], "claim_count": len(claims.claims)}

    def _citation_registry(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = f"{step['idempotency_key']}:artifact"
        checkpoint = self._checkpoint(step, key)
        if checkpoint:
            return {"artifact_id": checkpoint["id"], "citation_count": len(checkpoint["content"]["entries"]), "reused_checkpoint": True}
        matrix = ComparisonMatrix.model_validate(self._latest_artifact(context.run_id, context.user_id, "comparison_matrix")["content"])
        claims = SynthesisClaims.model_validate(self._latest_artifact(context.run_id, context.user_id, "synthesis_claims")["content"])
        candidates = {str(item["citation_key"]): item for item in self._citation_candidates(context)}
        claims_for_key: dict[str, list[str]] = {}
        def register_relation(citation_key: str, relation_id: str) -> None:
            relations = claims_for_key.setdefault(citation_key, [])
            if relation_id not in relations:
                relations.append(relation_id)
        for claim in claims.claims:
            for citation_key in [*claim.supporting_citations, *claim.contradicting_citations]:
                register_relation(citation_key, claim.claim_id)
        for statement in [*matrix.agreements, *matrix.disagreements]:
            for citation_key in statement.citation_keys:
                register_relation(citation_key, statement.statement_id)
        for cell in matrix.cells:
            for citation_key in cell.citation_keys:
                register_relation(citation_key, cell.cell_id)
        entries = [
            CitationRegistryEntry(citation_key=key_name, claim_id=claims_for_key[key_name][0], claim_ids=claims_for_key[key_name],
                paper_id=int(candidates[key_name]["paper_id"]), evidence_id=str(candidates[key_name]["evidence_id"]))
            for key_name in sorted(claims_for_key, key=lambda value: int(value[1:]))
            if key_name in candidates
        ]
        if len(entries) != len(claims_for_key) or not entries:
            raise ResearchStepError("citation_registry_incomplete", "引用登记缺少合法 Evidence。")
        registry = CitationRegistry(entries=entries)
        with connect() as conn:
            artifact = create_citation_registry(conn, run_id=context.run_id, source_step_id=context.step_id,
                worker_id=context.worker_id, lease_generation=context.lease_generation,
                content=registry.model_dump(mode="json"), idempotency_key=key)
        return {"artifact_id": artifact["id"], "citation_count": len(entries)}

    def _citation_verification(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = f"{step['idempotency_key']}:artifact"
        checkpoint = self._checkpoint(step, key)
        if checkpoint:
            return {"artifact_id": checkpoint["id"], "reused_checkpoint": True}
        registry_artifact = self._latest_artifact(context.run_id, context.user_id, "citation_registry")
        registry = CitationRegistry.model_validate(registry_artifact["content"])
        claims = SynthesisClaims.model_validate(self._latest_artifact(context.run_id, context.user_id, "synthesis_claims")["content"])
        with connect() as conn:
            citations = [item for item in list_citations(conn, context.run_id, context.user_id) if item.get("artifact_id") == registry_artifact["id"]]
        citation_by_key = {str(item["citation_key"]): item for item in citations}
        registry_by_key = {item.citation_key: item for item in registry.entries}
        if set(citation_by_key) != set(registry_by_key):
            raise ResearchStepError("citation_registry_incomplete", "Citation Registry 与持久化引用不一致。")
        for key_name, entry in registry_by_key.items():
            row = citation_by_key[key_name]
            if int(row.get("paper_id", 0)) != entry.paper_id or str(row.get("evidence_id", "")) != entry.evidence_id or str(row.get("claim_id", "")) != entry.claim_id:
                raise ResearchStepError("citation_registry_invalid", "Citation Registry 的主张、论文或 Evidence 关系不一致。")
        for claim in claims.claims:
            cited_keys = [*claim.supporting_citations, *claim.contradicting_citations]
            if any(key_name not in citation_by_key for key_name in cited_keys):
                raise ResearchStepError("citation_claim_invalid", "事实性主张引用了 Registry 之外的 Citation。")
            if any(claim.claim_id not in registry_by_key[key_name].claim_ids for key_name in cited_keys):
                raise ResearchStepError("citation_claim_invalid", "Citation Registry 缺少主张与引用的审计关系。")
            cited_papers = {int(citation_by_key[key_name].get("paper_id", 0)) for key_name in cited_keys}
            if not cited_papers.issubset(set(claim.covered_paper_ids)):
                raise ResearchStepError("citation_claim_invalid", "主张覆盖论文与 Citation 身份不一致。")
        statuses = {str(item["citation_key"]): str(item["status"]) for item in citations}
        result = self.citation_verifier.result(statuses=statuses, claims=claims)
        required_claims = {claim.claim_id for claim in claims.claims if claim.claim_type in {"finding", "agreement", "disagreement"}}
        if set(result.verified_claim_ids) != required_claims or result.stale_citation_keys or result.inaccessible_citation_keys or result.invalid_citation_keys:
            raise ResearchStepError("citation_validation_failed", "事实性主张的引用未全部通过严格校验。")
        with connect() as conn:
            artifact = create_artifact(conn, run_id=context.run_id, source_step_id=context.step_id,
                worker_id=context.worker_id, lease_generation=context.lease_generation,
                artifact_type="citation_validation_result", content=result.model_dump(mode="json"), idempotency_key=key)
        return {"artifact_id": artifact["id"], "valid_citation_count": len(result.valid_citation_keys)}

    @staticmethod
    def _report_citation_keys(report: ResearchReport) -> set[str]:
        statements = [*report.executive_summary, *report.findings, *report.agreements, *report.disagreements, *report.conclusion]
        return {key for item in statements for key in item.citation_keys}

    @staticmethod
    def _validate_report_statement_pairs(
        report: ResearchReport,
        claims: SynthesisClaims,
        matrix: ComparisonMatrix,
    ) -> None:
        allowed_statement_pairs: set[tuple[str, tuple[str, ...]]] = set()
        for claim in claims.claims:
            if claim.claim_type in {"finding", "agreement", "disagreement"}:
                allowed_statement_pairs.add(
                    (claim.claim, tuple([*claim.supporting_citations, *claim.contradicting_citations]))
                )
        for cell in matrix.cells:
            allowed_statement_pairs.add((cell.value, tuple(cell.citation_keys)))
        for statement in [*matrix.agreements, *matrix.disagreements]:
            allowed_statement_pairs.add((statement.text, tuple(statement.citation_keys)))
        for statement in [*report.executive_summary, *report.findings, *report.agreements, *report.disagreements, *report.conclusion]:
            if (statement.text, tuple(statement.citation_keys)) not in allowed_statement_pairs:
                raise ResearchStepError("report_statement_unverified", "研究报告包含未验证的事实性陈述。")

    def _report_generation(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = f"{step['idempotency_key']}:artifact"
        checkpoint = self._checkpoint(step, key)
        if checkpoint:
            return {"artifact_id": checkpoint["id"], "version": checkpoint["version"], "reused_checkpoint": True}
        plan_artifact = self._latest_artifact(context.run_id, context.user_id, "synthesis_plan")
        matrix_artifact = self._latest_artifact(context.run_id, context.user_id, "comparison_matrix")
        claims_artifact = self._latest_artifact(context.run_id, context.user_id, "synthesis_claims")
        registry_artifact = self._latest_artifact(context.run_id, context.user_id, "citation_registry")
        validation_artifact = self._latest_artifact(context.run_id, context.user_id, "citation_validation_result")
        plan = SynthesisPlan.model_validate(plan_artifact["content"])
        matrix = ComparisonMatrix.model_validate(matrix_artifact["content"])
        claims = SynthesisClaims.model_validate(claims_artifact["content"])
        validation = CitationValidationResult.model_validate(validation_artifact["content"])
        versions = {"synthesis_plan": int(plan_artifact["version"]), "comparison_matrix": int(matrix_artifact["version"]), "synthesis_claims": int(claims_artifact["version"]), "citation_registry": int(registry_artifact["version"]), "citation_validation_result": int(validation_artifact["version"])}
        report_input = {"plan": plan.model_dump(mode="json"), "comparison_matrix": matrix.model_dump(mode="json"), "verified_claims": claims.model_dump(mode="json"), "valid_citation_keys": validation.valid_citation_keys, "generated_from_artifact_versions": versions}
        report = self._model_call(context, key, ResearchReport, report_input, lambda: self.report_agent.write(plan=plan, matrix=matrix, claims=claims,
            valid_citation_keys=validation.valid_citation_keys, generated_from_artifact_versions=versions))
        used = self._report_citation_keys(report)
        if not used or used != set(report.citation_keys) or not used.issubset(set(validation.valid_citation_keys)) or report.generated_from_artifact_versions != versions:
            raise ResearchStepError("report_citation_invalid", "研究报告包含未验证引用或伪造上游版本。")
        self._validate_report_statement_pairs(report, claims, matrix)
        if report.research_questions != plan.research_questions:
            raise ResearchStepError("report_question_invalid", "研究报告篡改了综合计划中的研究问题。")
        with connect() as conn:
            artifact = create_artifact(conn, run_id=context.run_id, source_step_id=context.step_id,
                worker_id=context.worker_id, lease_generation=context.lease_generation,
                artifact_type="research_report", content=report.model_dump(mode="json"), idempotency_key=key)
        return {"artifact_id": artifact["id"], "version": artifact["version"], "citation_count": len(used)}

    def _finalize_cited_report(self, step: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del step
        report = self._latest_artifact(context.run_id, context.user_id, "research_report")
        if not report.get("is_current"):
            raise ResearchStepError("research_report_stale", "研究报告依赖已失效，不能标记为当前有效。")
        return {"cited_report_ready": True, "artifact_id": report["id"], "version": report["version"]}


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

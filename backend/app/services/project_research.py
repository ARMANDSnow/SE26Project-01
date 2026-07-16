from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from ..db.connection import connect
from ..repositories.projects import (
    create_project_citation_ref,
    create_project_artifact,
    find_project_artifact_checkpoint,
    get_project,
    get_project_analysis_inputs,
    list_project_artifacts,
    validate_project_inputs,
    wait_for_project_coverage,
)
from ..repositories.research import ResearchConflictError
from ..repositories.research_data import (
    assert_safe_research_payload,
    begin_model_call,
    complete_model_call_and_settle,
)
from .research_agents import (
    GraphValidationAgent,
    LLMStructuredResearchModel,
    LandscapePlannerAgent,
    StructuredResearchModel,
    TimelineAgent,
    TopicClusteringAgent,
)
from .research_contracts import (
    ProjectAnalysisValidation,
    ProjectCoverageSummary,
    ResearchGraph,
    ResearchGraphEdge,
    ResearchGraphNode,
    ResearchLandscapePlan,
    ResearchStepError,
    ResearchTimeline,
    ResearchWaitingInput,
    TimelineEvent,
    TopicClusters,
)
from .research_tools import ToolContext


ModelT = TypeVar("ModelT", bound=BaseModel)
PROJECT_ARTIFACT_TYPES = {
    "research_landscape_plan",
    "topic_clusters",
    "research_timeline",
    "research_graph",
    "project_analysis_validation",
}


class ProjectResearchPipeline:
    """Seven-step project workflow over a revision-fenced server whitelist."""

    def __init__(self, *, model: StructuredResearchModel | None = None) -> None:
        structured_model = model or LLMStructuredResearchModel()
        self.planner = LandscapePlannerAgent(structured_model)
        self.clustering_agent = TopicClusteringAgent(structured_model)
        self.timeline_agent = TimelineAgent(structured_model)
        self.graph_validator = GraphValidationAgent()

    def handle(self, step: dict[str, Any]) -> dict[str, Any]:
        if not str(step.get("step_type", "")).startswith("project."):
            raise ResearchStepError("unknown_project_step", "未知的项目分析步骤。")
        with connect() as conn:
            run = conn.execute(
                "SELECT id, user_id, project_id, mode FROM research_runs WHERE id = ?",
                (str(step["run_id"]),),
            ).fetchone()
        if run is None or str(run["mode"]) != "project" or run["project_id"] is None:
            raise ResearchStepError("project_run_not_found", "项目分析任务不存在或模式不匹配。")
        context = ToolContext(
            run_id=str(run["id"]),
            step_id=str(step["id"]),
            user_id=int(run["user_id"]),
            worker_id=str(step["lease_owner"]),
            lease_generation=int(step["lease_generation"]),
        )
        project_id = str(run["project_id"])
        handlers: dict[str, Callable[[dict[str, Any], ToolContext, str], dict[str, Any]]] = {
            "validate_project_inputs": self._validate_inputs,
            "landscape_planning": self._landscape_planning,
            "topic_clustering": self._topic_clustering,
            "timeline_construction": self._timeline_construction,
            "graph_construction": self._graph_construction,
            "graph_citation_validation": self._graph_citation_validation,
            "finalize_research_landscape": self._finalize,
        }
        try:
            handler = handlers[str(step["step_key"])]
        except KeyError as exc:
            raise ResearchStepError("unknown_project_step", "未知的项目分析步骤。") from exc
        return handler(step, context, project_id)

    def _model_call(
        self,
        context: ToolContext,
        operation_key: str,
        model_type: type[ModelT],
        input_payload: dict[str, Any],
        callback: Callable[[], ModelT],
    ) -> ModelT:
        with connect() as conn:
            status, stored = begin_model_call(
                conn,
                run_id=context.run_id,
                step_id=context.step_id,
                worker_id=context.worker_id,
                lease_generation=context.lease_generation,
                idempotency_key=operation_key,
                model_name=model_type.__name__,
                input_payload=input_payload,
            )
        if status == "completed":
            return model_type.model_validate(stored)
        if status == "waiting":
            raise ResearchWaitingInput("project model budget requires input")
        try:
            result = callback()
            safe_result = result.model_dump(mode="json")
            assert_safe_research_payload(safe_result)
            with connect() as conn:
                complete_model_call_and_settle(
                    conn,
                    run_id=context.run_id,
                    step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    idempotency_key=operation_key,
                    result=safe_result,
                    succeeded=True,
                )
            return result
        except Exception:
            with connect() as conn:
                try:
                    complete_model_call_and_settle(
                        conn,
                        run_id=context.run_id,
                        step_id=context.step_id,
                        worker_id=context.worker_id,
                        lease_generation=context.lease_generation,
                        idempotency_key=operation_key,
                        result=None,
                        succeeded=False,
                    )
                except ResearchConflictError:
                    # A lost lease must not be converted into a second provider request.
                    pass
            raise

    @staticmethod
    def _analysis_options(run_id: str) -> dict[str, Any]:
        with connect() as conn:
            row = conn.execute(
                "SELECT input_json FROM research_steps WHERE run_id = ? AND step_key = 'validate_project_inputs'",
                (run_id,),
            ).fetchone()
        if row is None:
            return {}
        try:
            value = json.loads(str(row["input_json"]))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _validation(
        project_id: str,
        user_id: int,
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        with connect() as conn:
            basic = validate_project_inputs(conn, project_id, user_id)
            project = get_project(conn, project_id, user_id, include_items=False)
            if context is not None:
                run = conn.execute(
                    """
                    SELECT project_revision, input_fingerprint
                    FROM research_runs
                    WHERE id = ? AND project_id = ? AND user_id = ? AND mode = 'project'
                    """,
                    (context.run_id, project_id, user_id),
                ).fetchone()
                if (
                    run is None
                    or int(run["project_revision"] or -1) != int(basic["project_revision"])
                    or str(run["input_fingerprint"] or "") != str(basic["input_fingerprint"])
                ):
                    raise ResearchConflictError("project inputs changed during analysis")
            inputs = get_project_analysis_inputs(
                conn,
                project_id,
                user_id,
                run_id=context.run_id if context is not None else None,
            )
        aliases: dict[tuple[str, str], str] = {}
        citations: list[dict[str, Any]] = []
        for source in inputs.get("citation_sources", []):
            if not isinstance(source, dict) or source.get("status") != "valid":
                continue
            if context is None:
                continue
            with connect() as conn:
                ref = create_project_citation_ref(
                    conn,
                    project_id=project_id,
                    analysis_run_id=context.run_id,
                    user_id=user_id,
                    step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    citation_id=str(source["source_citation_id"]),
                )
            run_id = str(source.get("source_run_id", ""))
            source_key = str(source.get("source_citation_key", ""))
            project_key = str(ref["citation_key"])
            aliases[(run_id, source_key)] = project_key
            citations.append(
                {
                    "reference_id": str(ref["id"]),
                    "citation_key": project_key,
                    "source_run_id": run_id,
                    "source_citation_id": str(source["source_citation_id"]),
                    "source_citation_key": source_key,
                    "source_claim_id": str(source.get("source_claim_id", "")),
                    "paper_id": int(source["paper_id"]),
                    "source_hash": str(source["source_hash"]),
                    "status": "valid",
                }
            )

        claims: list[dict[str, Any]] = []
        claim_aliases: dict[tuple[str, str], str] = {}
        reports: list[dict[str, Any]] = []
        allowed_papers = {
            int(paper["paper_id"])
            for paper in inputs.get("papers", [])
            if isinstance(paper, dict) and isinstance(paper.get("paper_id"), int)
        }
        for report in inputs.get("reports", []):
            if not isinstance(report, dict):
                continue
            run_id = str(report.get("run_id", ""))
            safe_claims: list[dict[str, Any]] = []
            for raw_claim in report.get("claims", []):
                if not isinstance(raw_claim, dict) or not isinstance(raw_claim.get("claim_id"), str):
                    continue
                source_keys = [
                    str(key)
                    for field in ("supporting_citations", "contradicting_citations")
                    for key in raw_claim.get(field, [])
                    if isinstance(raw_claim.get(field), list)
                ]
                if any((run_id, key) not in aliases for key in source_keys):
                    continue
                supporting = [aliases[(run_id, str(key))] for key in raw_claim.get("supporting_citations", [])]
                contradicting = [aliases[(run_id, str(key))] for key in raw_claim.get("contradicting_citations", [])]
                if raw_claim.get("claim_type") in {"finding", "agreement", "disagreement"} and not supporting:
                    continue
                scoped_id = "claim-" + hashlib.sha256(
                    f"{run_id}:{report.get('artifact_id')}:{raw_claim['claim_id']}".encode("utf-8")
                ).hexdigest()[:24]
                safe_claim = {
                    **raw_claim,
                    "claim_id": scoped_id,
                    "supporting_citations": supporting,
                    "contradicting_citations": contradicting,
                    "covered_paper_ids": [
                        int(paper_id)
                        for paper_id in raw_claim.get("covered_paper_ids", [])
                        if isinstance(paper_id, int) and paper_id in allowed_papers
                    ],
                }
                safe_claim.pop("source_artifact_id", None)
                safe_claim.pop("source_artifact_version", None)
                claim_aliases[(run_id, str(raw_claim["claim_id"]))] = scoped_id
                safe_claims.append(safe_claim)
                claims.append(safe_claim)
            reports.append(
                {
                    key: report[key]
                    for key in ("artifact_id", "artifact_version", "run_id", "content_hash")
                    if key in report
                }
                | {"claims": safe_claims}
            )
        for citation in citations:
            scoped_claim_id = claim_aliases.get(
                (str(citation["source_run_id"]), str(citation["source_claim_id"]))
            )
            citation["claim_id"] = scoped_claim_id
            citation.pop("source_claim_id", None)
        safe_project_items: list[dict[str, Any]] = []
        for item in basic["items"]:
            if not isinstance(item, dict):
                continue
            safe_item = {
                key: item[key]
                for key in (
                    "id", "item_type", "run_id", "paper_id", "artifact_id",
                    "artifact_version", "source_hash_snapshot", "position", "status",
                )
                if key in item
            }
            if item.get("status") != "inaccessible" and isinstance(item.get("source"), dict):
                source = cast(dict[str, Any], item["source"])
                if item.get("item_type") == "research_report":
                    report_content = source.get("content") if isinstance(source.get("content"), dict) else {}
                    safe_item["title"] = report_content.get("topic") or report_content.get("title") or "研究报告"
                    safe_item["source_run_id"] = source.get("run_id")
                else:
                    safe_item["title"] = source.get("title") or item.get("item_type")
            safe_project_items.append(safe_item)
        validation = {
            **basic,
            **inputs,
            "items": safe_project_items,
            "title": project["title"],
            "description": project["description"],
            "citations": citations,
            "claims": claims,
            "reports": reports,
            "can_analyze": basic["can_analyze"],
            "can_generate_limited": basic.get("can_generate_limited", False),
        }
        assert_safe_research_payload(validation)
        return validation

    @staticmethod
    def _safe_items(validation: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            cast(dict[str, Any], item)
            for item in validation.get("items", [])
            if isinstance(item, dict) and item.get("status", "valid") == "valid"
        ]

    @classmethod
    def _scope(cls, validation: dict[str, Any]) -> dict[str, Any]:
        items = cls._safe_items(validation)
        return {
            "items": items,
            "papers": [item for item in validation.get("papers", []) if isinstance(item, dict)],
            "claims": [item for item in validation.get("claims", []) if isinstance(item, dict)],
            "citations": [item for item in validation.get("citations", []) if isinstance(item, dict)],
            "reports": [item for item in validation.get("reports", []) if isinstance(item, dict)],
            "runs": [item for item in validation.get("runs", []) if isinstance(item, dict)],
        }

    @staticmethod
    def _input_snapshot(validation: dict[str, Any]) -> dict[str, Any]:
        result: list[dict[str, Any]] = []
        for item in validation.get("items", []):
            if not isinstance(item, dict):
                continue
            result.append(
                {
                    key: item[key]
                    for key in (
                        "id",
                        "item_type",
                        "run_id",
                        "paper_id",
                        "artifact_id",
                        "artifact_version",
                        "source_hash_snapshot",
                        "status",
                    )
                    if key in item
                }
            )
        return {
            "project_id": str(validation["project_id"]),
            "project_revision": int(validation["project_revision"]),
            "input_fingerprint": str(validation["input_fingerprint"]),
            "items": result,
        }

    @staticmethod
    def _dependencies(validation: dict[str, Any]) -> list[dict[str, Any]]:
        value = validation.get("dependencies", [])
        return [cast(dict[str, Any], item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _coverage(validation: dict[str, Any]) -> ProjectCoverageSummary:
        raw = validation.get("coverage", {})
        raw = raw if isinstance(raw, dict) else {}
        items = ProjectResearchPipeline._safe_items(validation)
        scope = ProjectResearchPipeline._scope(validation)
        valid_citations = scope["citations"]
        return ProjectCoverageSummary(
            accessible_item_count=int(raw.get("valid", len(items))),
            paper_count=int(raw.get("unique_papers", len(scope["papers"]))),
            report_count=int(raw.get("reports", len(scope["reports"]))),
            valid_citation_count=int(raw.get("valid_citations", len(valid_citations))),
            limited=not bool(raw.get("ready", validation.get("can_analyze", False))),
        )

    @staticmethod
    def _latest_current(project_id: str, user_id: int, artifact_type: str) -> dict[str, Any]:
        if artifact_type not in PROJECT_ARTIFACT_TYPES:
            raise ValueError("unsupported project artifact type")
        with connect() as conn:
            artifacts = list_project_artifacts(
                conn,
                project_id,
                user_id,
                artifact_type=artifact_type,
            )
        if not artifacts:
            raise ResearchStepError("project_artifact_missing", "项目分析上游产物不存在。")
        latest = max(artifacts, key=lambda item: int(item["version"]))
        if not latest.get("is_current") or latest.get("status") != "completed":
            raise ResearchStepError("project_artifact_stale", "项目分析上游产物已失效。")
        return latest

    @staticmethod
    def _artifact_key(step: dict[str, Any]) -> str:
        step_key = str(step["idempotency_key"])
        canonical_step_key = step_key.split(":manual:", 1)[0]
        return f"{canonical_step_key}:artifact"

    def _save_artifact(
        self,
        *,
        step: dict[str, Any],
        context: ToolContext,
        project_id: str,
        validation: dict[str, Any],
        artifact_type: str,
        content: dict[str, Any],
        upstream_artifact_types: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        key = self._artifact_key(step)
        dependencies = self._dependencies(validation)
        for upstream_type in upstream_artifact_types:
            upstream = self._latest_current(project_id, context.user_id, upstream_type)
            with connect() as conn:
                upstream_row = conn.execute(
                    "SELECT content_hash FROM research_artifacts WHERE id = ? AND project_id = ? AND version = ?",
                    (str(upstream["id"]), project_id, int(upstream["version"])),
                ).fetchone()
            if upstream_row is None:
                raise ResearchStepError("project_artifact_missing", "项目分析上游产物不存在。")
            dependencies.append(
                {
                    "dependency_type": "artifact",
                    "dependency_key": f"artifact:{upstream['id']}:{upstream['version']}",
                    "upstream_artifact_id": str(upstream["id"]),
                    "upstream_artifact_version": int(upstream["version"]),
                    "dependency_hash": str(upstream_row["content_hash"]),
                }
            )
        with connect() as conn:
            checkpoint = find_project_artifact_checkpoint(
                conn,
                project_id=project_id,
                run_id=context.run_id,
                source_step_id=context.step_id,
                idempotency_key=key,
                input_fingerprint=str(validation["input_fingerprint"]),
                user_id=context.user_id,
            )
            if checkpoint is not None:
                return checkpoint
            return create_project_artifact(
                conn,
                run_id=context.run_id,
                source_step_id=context.step_id,
                worker_id=context.worker_id,
                lease_generation=context.lease_generation,
                project_id=project_id,
                artifact_type=artifact_type,
                content=content,
                idempotency_key=key,
                input_snapshot=self._input_snapshot(validation),
                dependency_snapshot=dependencies,
                dependencies=dependencies,
            )

    def _validate_inputs(
        self, step: dict[str, Any], context: ToolContext, project_id: str
    ) -> dict[str, Any]:
        validation = self._validation(project_id, context.user_id, context)
        step_input = step.get("input", {}) if isinstance(step.get("input"), dict) else {}
        limited_approved = bool(
            validation.get("can_generate_limited")
            and int(validation.get("coverage", {}).get("unique_papers", 0)) >= 1
            and any(
                step_input.get(flag)
                for flag in ("limited_scope", "reduce_dimensions", "deterministic_timeline_only")
            )
        )
        if not validation.get("can_analyze") and not limited_approved:
            with connect() as conn:
                wait_for_project_coverage(
                    conn,
                    run_id=context.run_id,
                    step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    validation=validation,
                )
            raise ResearchWaitingInput("project coverage requires input")
        coverage = self._coverage(validation)
        return {
            "project_id": project_id,
            "project_revision": int(validation["project_revision"]),
            "input_fingerprint": str(validation["input_fingerprint"]),
            "accessible_item_count": coverage.accessible_item_count,
            "paper_count": coverage.paper_count,
            "report_count": coverage.report_count,
            "valid_citation_count": coverage.valid_citation_count,
            "limited": coverage.limited,
            "limited_approved": limited_approved,
        }

    def _landscape_planning(
        self, step: dict[str, Any], context: ToolContext, project_id: str
    ) -> dict[str, Any]:
        validation = self._validation(project_id, context.user_id, context)
        scope = self._scope(validation)
        item_ids = [str(item["id"]) for item in scope["items"]]
        model_input = {
            "topic": str(validation.get("title", "研究项目")),
            "description": str(validation.get("description", "")),
            "selected_item_ids": item_ids,
            "available_relation_types": [
                "contains", "generated_from", "cites", "supports", "contradicts",
                "belongs_to_cluster", "precedes", "influences",
            ],
            "constraints": [
                "Use only current accessible project inputs",
                "Semantic relations require supplied citations",
                "Publication order does not imply influence",
            ],
        }
        options = self._analysis_options(context.run_id)
        if options.get("deterministic_timeline_only"):
            plan = ResearchLandscapePlan(
                project_id=project_id,
                topic=str(validation.get("title", "研究项目")),
                research_questions=["当前有效论文按已验证发布日期呈现怎样的时间顺序？"],
                selected_item_ids=item_ids,
                clustering_dimensions=["不生成语义主题簇"],
                timeline_dimensions=["论文发布日期"],
                graph_relation_types=["contains", "generated_from", "precedes"],
                constraints=["仅生成确定性时间排序，不推断思想影响关系。"],
            )
        else:
            if options.get("reduce_dimensions"):
                model_input["constraints"] = [
                    *cast(list[str], model_input["constraints"]),
                    "Use one clustering dimension and one timeline dimension only",
                ]
            key = f"{self._artifact_key(step)}:model"
            plan = self._model_call(
                context,
                key,
                ResearchLandscapePlan,
                model_input,
                lambda: self.planner.plan(project_id=project_id, inputs=model_input),
            )
        if plan.project_id != project_id or set(plan.selected_item_ids) != set(item_ids):
            raise ResearchStepError("project_plan_identity_invalid", "项目分析计划篡改了输入范围。")
        artifact = self._save_artifact(
            step=step,
            context=context,
            project_id=project_id,
            validation=validation,
            artifact_type="research_landscape_plan",
            content=plan.model_dump(mode="json"),
        )
        return {"artifact_id": artifact["id"], "version": artifact["version"]}

    def _topic_clustering(
        self, step: dict[str, Any], context: ToolContext, project_id: str
    ) -> dict[str, Any]:
        validation = self._validation(project_id, context.user_id, context)
        scope = self._scope(validation)
        plan = ResearchLandscapePlan.model_validate(
            self._latest_current(project_id, context.user_id, "research_landscape_plan")["content"]
        )
        model_input = {
            "papers": scope["papers"],
            "claims": scope["claims"],
            "citations": scope["citations"],
        }
        if self._analysis_options(context.run_id).get("deterministic_timeline_only"):
            clusters = TopicClusters(
                clusters=[],
                unclassified_paper_ids=sorted(
                    int(item["paper_id"])
                    for item in scope["papers"]
                    if isinstance(item.get("paper_id"), int)
                ),
                uncertainties=["用户选择仅生成确定性时间线，未执行语义聚类。"],
                citation_keys=[],
            )
        else:
            key = f"{self._artifact_key(step)}:model"
            clusters = self._model_call(
                context,
                key,
                TopicClusters,
                {"plan": plan.model_dump(mode="json"), **model_input},
                lambda: self.clustering_agent.cluster(plan=plan, inputs=model_input),
            )
        allowed_papers = {int(item["paper_id"]) for item in scope["papers"] if isinstance(item.get("paper_id"), int)}
        allowed_claims = {str(item["claim_id"]) for item in scope["claims"] if isinstance(item.get("claim_id"), str)}
        citation_papers = {
            str(item["citation_key"]): int(item["paper_id"])
            for item in scope["citations"]
            if isinstance(item.get("citation_key"), str) and isinstance(item.get("paper_id"), int)
        }
        citation_claims = {
            str(item["citation_key"]): str(item["claim_id"])
            for item in scope["citations"]
            if isinstance(item.get("citation_key"), str) and isinstance(item.get("claim_id"), str)
        }
        for cluster in clusters.clusters:
            if not set(cluster.paper_ids).issubset(allowed_papers) or not set(cluster.claim_ids).issubset(allowed_claims):
                raise ResearchStepError("project_cluster_identity_invalid", "主题簇包含未授权论文或主张。")
            if not set(cluster.citation_keys).issubset(citation_papers):
                raise ResearchStepError("project_cluster_citation_invalid", "主题簇包含未授权引用。")
            cited_papers = {citation_papers[key_name] for key_name in cluster.citation_keys}
            if not set(cluster.paper_ids).issubset(cited_papers):
                raise ResearchStepError("project_cluster_membership_unverified", "主题簇论文归属缺少可验证依据。")
            cited_claims = {
                citation_claims[key_name]
                for key_name in cluster.citation_keys
                if key_name in citation_claims
            }
            if not set(cluster.claim_ids).issubset(cited_claims):
                raise ResearchStepError("project_cluster_claim_unverified", "主题簇主张归属缺少可验证依据。")
        if not set(clusters.unclassified_paper_ids).issubset(allowed_papers):
            raise ResearchStepError("project_cluster_identity_invalid", "未分类列表包含未授权论文。")
        artifact = self._save_artifact(
            step=step,
            context=context,
            project_id=project_id,
            validation=validation,
            artifact_type="topic_clusters",
            content=clusters.model_dump(mode="json"),
            upstream_artifact_types=("research_landscape_plan",),
        )
        return {"artifact_id": artifact["id"], "version": artifact["version"], "cluster_count": len(clusters.clusters)}

    def _timeline_construction(
        self, step: dict[str, Any], context: ToolContext, project_id: str
    ) -> dict[str, Any]:
        validation = self._validation(project_id, context.user_id, context)
        scope = self._scope(validation)
        plan = ResearchLandscapePlan.model_validate(
            self._latest_current(project_id, context.user_id, "research_landscape_plan")["content"]
        )
        model_input = {
            "publication_metadata": [
                {
                    "paper_id": item.get("paper_id"),
                    "title": item.get("title"),
                    "published_at": item.get("published_at"),
                }
                for item in scope["papers"]
            ],
            "claims": scope["claims"],
            "citations": scope["citations"],
        }
        if self._analysis_options(context.run_id).get("deterministic_timeline_only"):
            publication_papers = [
                item
                for item in scope["papers"]
                if isinstance(item.get("paper_id"), int) and item.get("published_at")
            ]
            timeline = ResearchTimeline(
                events=[
                    TimelineEvent(
                        event_id=f"publication-{int(item['paper_id'])}",
                        date=str(item["published_at"]),
                        event_type="publication",
                        title=str(item.get("title", "论文发布")),
                        description="已验证论文元数据中的发布日期。",
                        paper_ids=[int(item["paper_id"])],
                        claim_ids=[],
                        citation_keys=[],
                        confidence=1.0,
                    )
                    for item in sorted(
                        publication_papers,
                        key=lambda value: (str(value["published_at"]), int(value["paper_id"])),
                    )
                ],
                periods=[],
                turning_points=[],
                unresolved_questions=["确定性时间排序不表达论文之间的思想继承或影响。"],
                citation_keys=[],
            )
        else:
            key = f"{self._artifact_key(step)}:model"
            timeline = self._model_call(
                context,
                key,
                ResearchTimeline,
                {"plan": plan.model_dump(mode="json"), **model_input},
                lambda: self.timeline_agent.build(plan=plan, inputs=model_input),
            )
        allowed_papers = {int(item["paper_id"]) for item in scope["papers"] if isinstance(item.get("paper_id"), int)}
        allowed_claims = {str(item["claim_id"]) for item in scope["claims"] if isinstance(item.get("claim_id"), str)}
        allowed_citations = {str(item["citation_key"]) for item in scope["citations"] if isinstance(item.get("citation_key"), str)}
        citation_claims = {
            str(item["citation_key"]): str(item["claim_id"])
            for item in scope["citations"]
            if isinstance(item.get("citation_key"), str) and isinstance(item.get("claim_id"), str)
        }
        dates = {int(item["paper_id"]): str(item.get("published_at", "")) for item in scope["papers"] if isinstance(item.get("paper_id"), int)}
        titles = {int(item["paper_id"]): str(item.get("title", "论文发布")) for item in scope["papers"] if isinstance(item.get("paper_id"), int)}
        normalized_events: list[TimelineEvent] = []
        for event in timeline.events:
            if not set(event.paper_ids).issubset(allowed_papers) or not set(event.claim_ids).issubset(allowed_claims):
                raise ResearchStepError("project_timeline_identity_invalid", "时间线包含未授权论文或主张。")
            if not set(event.citation_keys).issubset(allowed_citations):
                raise ResearchStepError("project_timeline_citation_invalid", "时间线包含未授权引用。")
            if event.event_type == "publication":
                paper_id = event.paper_ids[0]
                expected = dates.get(paper_id, "")
                if not expected or event.date != expected:
                    raise ResearchStepError("project_timeline_date_invalid", "论文发布日期与已验证元数据不一致。")
                event = event.model_copy(
                    update={
                        "title": titles[paper_id],
                        "description": "已验证论文元数据中的发布日期。",
                        "citation_keys": [],
                        "confidence": 1.0,
                    }
                )
            elif event.claim_ids:
                cited_claims = {
                    citation_claims[key_name]
                    for key_name in event.citation_keys
                    if key_name in citation_claims
                }
                if not set(event.claim_ids).issubset(cited_claims):
                    raise ResearchStepError("project_timeline_claim_unverified", "时间线主张缺少对应引用依据。")
            normalized_events.append(event)
        for period in timeline.periods:
            if not set(period.citation_keys).issubset(allowed_citations):
                raise ResearchStepError("project_timeline_citation_invalid", "时间线阶段包含未授权引用。")
        for turning_point in timeline.turning_points:
            if not set(turning_point.citation_keys).issubset(allowed_citations):
                raise ResearchStepError("project_timeline_citation_invalid", "时间线转折点包含未授权引用。")
        timeline = ResearchTimeline.model_validate(
            timeline.model_dump(mode="json") | {
                "events": [event.model_dump(mode="json") for event in normalized_events]
            }
        )
        artifact = self._save_artifact(
            step=step,
            context=context,
            project_id=project_id,
            validation=validation,
            artifact_type="research_timeline",
            content=timeline.model_dump(mode="json"),
            upstream_artifact_types=("research_landscape_plan",),
        )
        return {"artifact_id": artifact["id"], "version": artifact["version"], "event_count": len(timeline.events)}

    @staticmethod
    def _build_graph(
        project_id: str,
        validation: dict[str, Any],
        clusters: TopicClusters,
        timeline: ResearchTimeline,
    ) -> ResearchGraph:
        scope = ProjectResearchPipeline._scope(validation)
        project_node_id = f"project:{project_id}"
        nodes = [
            ResearchGraphNode(
                node_id=project_node_id,
                node_type="project",
                label=str(validation.get("title", "研究项目")),
                entity_ref=project_id,
            )
        ]
        edges: list[ResearchGraphEdge] = []
        item_node_by_id: dict[str, str] = {}
        paper_node_by_id: dict[int, str] = {}
        run_node_by_id: dict[str, str] = {}
        report_node_by_id: dict[tuple[str, int], str] = {}
        claim_node_by_id: dict[str, str] = {}
        for item in scope["items"]:
            item_id = str(item["id"])
            item_type = str(item.get("item_type", ""))
            if item_type == "paper" and isinstance(item.get("paper_id"), int):
                paper_id = int(item["paper_id"])
                node_id = f"paper:{paper_id}"
                entity_ref = node_id
                paper_node_by_id[paper_id] = node_id
                node_type = "paper"
            elif item_type == "run" and item.get("run_id") is not None:
                node_id = f"run:{item['run_id']}"
                entity_ref = node_id
                run_node_by_id[str(item["run_id"])] = node_id
                node_type = "run"
            elif item_type == "research_report" and item.get("artifact_id") is not None:
                node_id = f"report:{item['artifact_id']}:{item['artifact_version']}"
                entity_ref = f"report:{item.get('source_run_id', '')}:{item['artifact_version']}"
                report_node_by_id[(str(item["artifact_id"]), int(item["artifact_version"]))] = node_id
                node_type = "report"
            else:
                continue
            item_node_by_id[item_id] = node_id
            nodes.append(
                ResearchGraphNode(
                    node_id=node_id,
                    node_type=cast(Any, node_type),
                    label=str(item.get("title") or item.get("label") or item_type),
                    entity_ref=entity_ref,
                )
            )
            edges.append(
                ResearchGraphEdge(
                    edge_id=f"contains:{len(edges) + 1}",
                    source_node_id=project_node_id,
                    target_node_id=node_id,
                    relation_type="contains",
                    citation_keys=[],
                )
            )
        for report in scope["reports"]:
            artifact_id = report.get("artifact_id")
            artifact_version = report.get("artifact_version")
            source_run_id = report.get("run_id")
            if (
                not isinstance(artifact_id, str)
                or not isinstance(artifact_version, int)
                or not isinstance(source_run_id, str)
                or not source_run_id
            ):
                continue
            report_key = (artifact_id, artifact_version)
            report_node = report_node_by_id.get(report_key)
            if report_node is None:
                report_node = f"report:{artifact_id}:{artifact_version}"
                report_node_by_id[report_key] = report_node
                nodes.append(
                    ResearchGraphNode(
                        node_id=report_node,
                        node_type="report",
                        label=f"研究报告 v{artifact_version}",
                        entity_ref=f"report:{source_run_id}:{artifact_version}",
                    )
                )
            run_node = run_node_by_id.get(source_run_id)
            if run_node is None:
                run_node = f"run:{source_run_id}"
                run_node_by_id[source_run_id] = run_node
                nodes.append(
                    ResearchGraphNode(
                        node_id=run_node,
                        node_type="run",
                        label="生成该报告的研究任务",
                        entity_ref=run_node,
                    )
                )
            edges.append(
                ResearchGraphEdge(
                    edge_id=f"generated-from:{len(edges) + 1}",
                    source_node_id=run_node,
                    target_node_id=report_node,
                    relation_type="generated_from",
                    citation_keys=[],
                )
            )
        for paper in scope["papers"]:
            if not isinstance(paper.get("paper_id"), int):
                continue
            paper_id = int(paper["paper_id"])
            if paper_id in paper_node_by_id:
                continue
            node_id = f"paper:{paper_id}"
            paper_node_by_id[paper_id] = node_id
            nodes.append(
                ResearchGraphNode(
                    node_id=node_id,
                    node_type="paper",
                    label=str(paper.get("title", "论文")),
                    entity_ref=node_id,
                )
            )
        for claim in scope["claims"]:
            if not isinstance(claim.get("claim_id"), str):
                continue
            claim_id = str(claim["claim_id"])
            node_id = f"claim:{len(claim_node_by_id) + 1}"
            claim_node_by_id[claim_id] = node_id
            nodes.append(
                ResearchGraphNode(
                    node_id=node_id,
                    node_type="synthesis_claim",
                    label=str(claim.get("claim", "综合主张")),
                    entity_ref=claim_id,
                )
            )
        cluster_node_by_id: dict[str, str] = {}
        for index, cluster in enumerate(clusters.clusters, start=1):
            node_id = f"cluster:{index}"
            cluster_node_by_id[cluster.cluster_id] = node_id
            nodes.append(
                ResearchGraphNode(
                    node_id=node_id,
                    node_type="topic_cluster",
                    label=cluster.label,
                    entity_ref=cluster.cluster_id,
                )
            )
            for paper_id in cluster.paper_ids:
                paper_node = paper_node_by_id.get(paper_id)
                if paper_node:
                    edges.append(
                        ResearchGraphEdge(
                            edge_id=f"cluster-membership:{len(edges) + 1}",
                            source_node_id=paper_node,
                            target_node_id=node_id,
                            relation_type="belongs_to_cluster",
                            citation_keys=cluster.citation_keys,
                        )
                    )
        citation_by_key = {
            str(item["citation_key"]): item
            for item in scope["citations"]
            if isinstance(item.get("citation_key"), str)
        }
        for claim in scope["claims"]:
            claim_id = str(claim.get("claim_id", ""))
            claim_node = claim_node_by_id.get(claim_id)
            if claim_node is None:
                continue
            for relation_type, field in (
                ("supports", "supporting_citations"),
                ("contradicts", "contradicting_citations"),
            ):
                grouped: dict[int, list[str]] = {}
                for key_name in claim.get(field, []) if isinstance(claim.get(field), list) else []:
                    citation = citation_by_key.get(str(key_name))
                    if citation is not None and isinstance(citation.get("paper_id"), int):
                        grouped.setdefault(int(citation["paper_id"]), []).append(str(key_name))
                for paper_id, keys in grouped.items():
                    paper_node = paper_node_by_id.get(paper_id)
                    if paper_node:
                        edges.append(
                            ResearchGraphEdge(
                                edge_id=f"{relation_type}:{len(edges) + 1}",
                                source_node_id=paper_node,
                                target_node_id=claim_node,
                                relation_type=cast(Any, relation_type),
                                citation_keys=keys,
                            )
                        )
        publication_events = sorted(
            (event for event in timeline.events if event.event_type == "publication" and event.date),
            key=lambda event: (str(event.date), event.paper_ids[0]),
        )
        for earlier, later in zip(publication_events, publication_events[1:]):
            source = paper_node_by_id.get(earlier.paper_ids[0])
            target = paper_node_by_id.get(later.paper_ids[0])
            if source and target and source != target:
                edges.append(
                    ResearchGraphEdge(
                        edge_id=f"precedes:{len(edges) + 1}",
                        source_node_id=source,
                        target_node_id=target,
                        relation_type="precedes",
                        citation_keys=[],
                    )
                )
        citation_keys = sorted({key for edge in edges for key in edge.citation_keys})
        return ResearchGraph(nodes=nodes, edges=edges, citation_keys=citation_keys)

    def _graph_construction(
        self, step: dict[str, Any], context: ToolContext, project_id: str
    ) -> dict[str, Any]:
        validation = self._validation(project_id, context.user_id, context)
        clusters = TopicClusters.model_validate(
            self._latest_current(project_id, context.user_id, "topic_clusters")["content"]
        )
        timeline = ResearchTimeline.model_validate(
            self._latest_current(project_id, context.user_id, "research_timeline")["content"]
        )
        graph = self._build_graph(project_id, validation, clusters, timeline)
        artifact = self._save_artifact(
            step=step,
            context=context,
            project_id=project_id,
            validation=validation,
            artifact_type="research_graph",
            content=graph.model_dump(mode="json"),
            upstream_artifact_types=("topic_clusters", "research_timeline"),
        )
        return {"artifact_id": artifact["id"], "version": artifact["version"], "node_count": len(graph.nodes), "edge_count": len(graph.edges)}

    def _graph_citation_validation(
        self, step: dict[str, Any], context: ToolContext, project_id: str
    ) -> dict[str, Any]:
        validation = self._validation(project_id, context.user_id, context)
        scope = self._scope(validation)
        clusters = TopicClusters.model_validate(
            self._latest_current(project_id, context.user_id, "topic_clusters")["content"]
        )
        timeline = ResearchTimeline.model_validate(
            self._latest_current(project_id, context.user_id, "research_timeline")["content"]
        )
        graph = ResearchGraph.model_validate(
            self._latest_current(project_id, context.user_id, "research_graph")["content"]
        )
        expected_graph = self._build_graph(project_id, validation, clusters, timeline)
        result = self.graph_validator.validate(
            graph,
            allowed_node_ids={item.node_id for item in expected_graph.nodes},
            allowed_citation_keys={str(item["citation_key"]) for item in scope["citations"] if isinstance(item.get("citation_key"), str)},
            allowed_paper_ids={int(item["paper_id"]) for item in scope["papers"] if isinstance(item.get("paper_id"), int)},
            allowed_claim_ids={str(item["claim_id"]) for item in scope["claims"] if isinstance(item.get("claim_id"), str)},
            clusters=clusters,
            timeline=timeline,
            coverage_summary=self._coverage(validation),
            stale_dependencies=[str(item) for item in validation.get("stale_dependencies", [])],
            inaccessible_dependencies=[str(item) for item in validation.get("inaccessible_dependencies", [])],
        )
        artifact = self._save_artifact(
            step=step,
            context=context,
            project_id=project_id,
            validation=validation,
            artifact_type="project_analysis_validation",
            content=result.model_dump(mode="json"),
            upstream_artifact_types=("topic_clusters", "research_timeline", "research_graph"),
        )
        return {"artifact_id": artifact["id"], "version": artifact["version"], "validated_edge_count": len(result.validated_edge_ids)}

    def _finalize(
        self, step: dict[str, Any], context: ToolContext, project_id: str
    ) -> dict[str, Any]:
        del step
        validation = ProjectAnalysisValidation.model_validate(
            self._latest_current(project_id, context.user_id, "project_analysis_validation")["content"]
        )
        return {
            "research_landscape_ready": True,
            "validated_cluster_count": len(validation.validated_cluster_ids),
            "validated_timeline_event_count": len(validation.validated_timeline_event_ids),
            "validated_edge_count": len(validation.validated_edge_ids),
            "limited": validation.coverage_summary.limited,
        }

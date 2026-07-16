from __future__ import annotations

import json
from typing import Any, Protocol, TypeVar

from pydantic import ValidationError

from .llm import LLMClient, LLMConfigurationError, LLMServiceError
from .research_contracts import (
    CandidatePaper,
    CitationValidationResult,
    ComparisonMatrix,
    PaperBrief,
    ProjectAnalysisValidation,
    ProjectCoverageSummary,
    ResearchBrief,
    ResearchGraph,
    ResearchLandscapePlan,
    ResearchTimeline,
    ResearchStepError,
    ScreeningResult,
    SearchQueries,
    SynthesisClaims,
    SynthesisPlan,
    TopicClusters,
    ResearchReport,
    StrictResearchModel,
)


ModelT = TypeVar("ModelT", bound=StrictResearchModel)


class StructuredResearchModel(Protocol):
    def generate(
        self,
        model: type[ModelT],
        *,
        system_prompt: str,
        input_data: dict[str, Any],
    ) -> ModelT: ...


class LLMStructuredResearchModel:
    def generate(
        self,
        model: type[ModelT],
        *,
        system_prompt: str,
        input_data: dict[str, Any],
    ) -> ModelT:
        try:
            contract_prompt = (
                f"{system_prompt}\n"
                "Return exactly one JSON object and no markdown or commentary. "
                "The object must satisfy this JSON Schema:\n"
                f"{json.dumps(model.model_json_schema(), ensure_ascii=False, separators=(',', ':'))}"
            )
            client = LLMClient()
            raw = client.complete(
                contract_prompt,
                json.dumps(input_data, ensure_ascii=False, separators=(",", ":")),
                json_mode=client.settings.llm_json_response_format,
                timeout_seconds=120,
                max_attempts=1,
            )
            return model.model_validate_json(raw)
        except LLMConfigurationError as exc:
            raise ResearchStepError(
                "llm_configuration_unavailable",
                "主题调研需要真实模型配置；当前 LLM_API_KEY 未配置。",
            ) from exc
        except (LLMServiceError, ValidationError, json.JSONDecodeError) as exc:
            raise ResearchStepError(
                "structured_model_output_invalid",
                "模型输出未通过严格结构校验，未写入调研数据。",
            ) from exc


class CoordinatorAgent:
    name = "Coordinator Agent"

    def __init__(self, model: StructuredResearchModel) -> None:
        self.model = model

    def build_brief(self, goal: str) -> ResearchBrief:
        return self.model.generate(
            ResearchBrief,
            system_prompt=(
                "Convert the user's paper-research goal into ResearchBrief schema version 1. "
                "Use only local and arxiv preferred_sources. Do not claim that research ran."
            ),
            input_data={"goal": goal},
        )


class SearchAgent:
    name = "Search Agent"

    def __init__(self, model: StructuredResearchModel) -> None:
        self.model = model

    def plan_queries(self, brief: ResearchBrief) -> SearchQueries:
        return self.model.generate(
            SearchQueries,
            system_prompt=(
                "Create concise paper metadata search queries for the supplied ResearchBrief. "
                "Return SearchQueries schema version 1 only."
            ),
            input_data=brief.model_dump(mode="json"),
        )


class ScreeningAgent:
    name = "Screening Agent"

    def __init__(self, model: StructuredResearchModel) -> None:
        self.model = model

    def screen(self, brief: ResearchBrief, candidates: list[CandidatePaper]) -> ScreeningResult:
        result = self.model.generate(
            ScreeningResult,
            system_prompt=(
                "Score each supplied candidate against the ResearchBrief. Select at most 12. "
                "Every selected/excluded paper needs a concise auditable reason. Return each paper exactly once."
            ),
            input_data={
                "brief": brief.model_dump(mode="json"),
                "candidates": [item.model_dump(mode="json") for item in candidates],
            },
        )
        expected = {int(item.paper_id) for item in candidates if item.paper_id is not None}
        actual = [item.paper_id for item in result.items]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ResearchStepError(
                "screening_identity_invalid",
                "筛选结果包含未知、重复或遗漏的论文，未更新数据库。",
            )
        selected = [item for item in result.items if item.selected]
        if len(selected) > 12:
            raise ResearchStepError("screening_budget_invalid", "筛选结果超过 12 篇全文上限。")
        return result


class ReaderAgent:
    name = "Reader Agent"

    @staticmethod
    def evidence_query(brief: ResearchBrief) -> str:
        return " ".join([brief.topic, *brief.research_questions[:2]])[:500]


class ExtractionAgent:
    name = "Extraction Agent"

    def __init__(self, model: StructuredResearchModel) -> None:
        self.model = model

    def extract(
        self,
        *,
        brief: ResearchBrief,
        paper: CandidatePaper,
        source_hash: str,
        evidence: list[dict[str, Any]],
    ) -> PaperBrief:
        return self.model.generate(
            PaperBrief,
            system_prompt=(
                "Extract a PaperBrief schema version 1 using only the opened evidence. "
                "Copy the authoritative paper identity, source_hash and evidence references exactly. "
                "Do not invent experiments, datasets or findings not supported by evidence."
            ),
            input_data={
                "research_brief": brief.model_dump(mode="json"),
                "paper": paper.model_dump(mode="json"),
                "source_hash": source_hash,
                "opened_evidence": evidence,
            },
        )


class SynthesisAgent:
    name = "Synthesis Agent"

    def __init__(self, model: StructuredResearchModel) -> None:
        self.model = model

    def plan(self, brief: ResearchBrief, paper_briefs: list[PaperBrief]) -> SynthesisPlan:
        return self.model.generate(
            SynthesisPlan,
            system_prompt=(
                "Plan a cross-paper synthesis. Use only the supplied current PaperBrief dataset. "
                "Comparison dimensions must be answerable from the supplied briefs. Return schema version 1."
            ),
            input_data={"research_brief": brief.model_dump(mode="json"), "paper_briefs": [item.model_dump(mode="json") for item in paper_briefs]},
        )

    def claims(
        self,
        plan: SynthesisPlan,
        matrix: ComparisonMatrix,
        citation_candidates: list[dict[str, Any]],
    ) -> SynthesisClaims:
        return self.model.generate(
            SynthesisClaims,
            system_prompt=(
                "Produce cross-paper claims using only supplied comparison cells and citation candidates. "
                "Every finding/agreement/disagreement needs supporting citation keys copied exactly. "
                "Unsupported content may only be limitation or gap."
            ),
            input_data={"plan": plan.model_dump(mode="json"), "comparison_matrix": matrix.model_dump(mode="json"), "citation_candidates": citation_candidates},
        )


class ComparisonAgent:
    name = "Comparison Agent"

    def __init__(self, model: StructuredResearchModel) -> None:
        self.model = model

    def compare(
        self,
        plan: SynthesisPlan,
        paper_briefs: list[PaperBrief],
        citation_candidates: list[dict[str, Any]],
    ) -> ComparisonMatrix:
        return self.model.generate(
            ComparisonMatrix,
            system_prompt=(
                "Build a structured comparison matrix. Every factual cell, agreement and disagreement "
                "must copy one or more citation_key and evidence_id values from the supplied candidates. "
                "Record unsupported dimensions only in missing_evidence."
            ),
            input_data={"plan": plan.model_dump(mode="json"), "paper_briefs": [item.model_dump(mode="json") for item in paper_briefs], "citation_candidates": citation_candidates},
        )


class CitationVerifierAgent:
    name = "Citation Verifier Agent"

    @staticmethod
    def result(
        *,
        statuses: dict[str, str],
        claims: SynthesisClaims,
    ) -> CitationValidationResult:
        valid = sorted(key for key, status in statuses.items() if status == "valid")
        verified = [
            claim.claim_id for claim in claims.claims
            if claim.claim_type in {"finding", "agreement", "disagreement"}
            and all(key in valid for key in [*claim.supporting_citations, *claim.contradicting_citations])
        ]
        return CitationValidationResult(
            valid_citation_keys=valid,
            stale_citation_keys=sorted(key for key, status in statuses.items() if status == "stale"),
            inaccessible_citation_keys=sorted(key for key, status in statuses.items() if status == "inaccessible"),
            invalid_citation_keys=sorted(key for key, status in statuses.items() if status == "invalid"),
            verified_claim_ids=verified,
        )


class ReportAgent:
    name = "Report Agent"

    def __init__(self, model: StructuredResearchModel) -> None:
        self.model = model

    def write(
        self,
        *,
        plan: SynthesisPlan,
        matrix: ComparisonMatrix,
        claims: SynthesisClaims,
        valid_citation_keys: list[str],
        generated_from_artifact_versions: dict[str, int],
    ) -> ResearchReport:
        reportable_statements = [
            {
                "text": claim.claim,
                "citation_keys": [*claim.supporting_citations, *claim.contradicting_citations],
            }
            for claim in claims.claims
            if claim.claim_type in {"finding", "agreement", "disagreement"}
        ]
        reportable_statements.extend(
            {"text": cell.value, "citation_keys": cell.citation_keys}
            for cell in matrix.cells
        )
        reportable_statements.extend(
            {"text": statement.text, "citation_keys": statement.citation_keys}
            for statement in [*matrix.agreements, *matrix.disagreements]
        )
        return self.model.generate(
            ResearchReport,
            system_prompt=(
                "Write a structured cited research report using only the verified claims, comparison matrix "
                "and valid citation keys supplied. For every executive summary, finding, agreement, disagreement "
                "and conclusion item, copy both text and citation_keys exactly from one reportable_statements "
                "entry. Never paraphrase, merge, split, or synthesize factual statement text. It is acceptable "
                "to reuse an exact entry in more than one report section. Put unsupported content only in "
                "limitations or research_gaps. Copy generated_from_artifact_versions exactly."
            ),
            input_data={
                "plan": plan.model_dump(mode="json"),
                "comparison_matrix": matrix.model_dump(mode="json"),
                "verified_claims": claims.model_dump(mode="json"),
                "reportable_statements": reportable_statements,
                "valid_citation_keys": valid_citation_keys,
                "generated_from_artifact_versions": generated_from_artifact_versions,
            },
        )


class LandscapePlannerAgent:
    name = "Landscape Planner Agent"

    def __init__(self, model: StructuredResearchModel) -> None:
        self.model = model

    def plan(self, *, project_id: str, inputs: dict[str, Any]) -> ResearchLandscapePlan:
        return self.model.generate(
            ResearchLandscapePlan,
            system_prompt=(
                "Create a project research-landscape plan using only the supplied server-authorized items. "
                "Copy project_id and selected_item_ids exactly from the whitelist. Do not add database IDs, "
                "facts, papers, claims, citations, or relation types that are not supplied."
            ),
            input_data={"project_id": project_id, **inputs},
        )


class TopicClusteringAgent:
    name = "Topic Clustering Agent"

    def __init__(self, model: StructuredResearchModel) -> None:
        self.model = model

    def cluster(self, *, plan: ResearchLandscapePlan, inputs: dict[str, Any]) -> TopicClusters:
        return self.model.generate(
            TopicClusters,
            system_prompt=(
                "Build topic clusters using only the supplied paper, claim, and citation aliases. Every factual "
                "summary and distinguishing feature must cite one or more supplied valid citation aliases. A paper "
                "may belong to multiple clusters only when citations support the membership. Put unsupported papers "
                "in unclassified_paper_ids and uncertainty text; never infer relationships from title similarity. "
                "You may leave claim_ids empty. If a cluster includes a claim_id, at least one citation alias in that "
                "same cluster must have exactly that claim_id. Do not attach a cross-paper claim to a single-paper "
                "cluster unless the cluster citations directly map to that claim."
            ),
            input_data={"plan": plan.model_dump(mode="json"), **inputs},
        )


class TimelineAgent:
    name = "Timeline Agent"

    def __init__(self, model: StructuredResearchModel) -> None:
        self.model = model

    def build(self, *, plan: ResearchLandscapePlan, inputs: dict[str, Any]) -> ResearchTimeline:
        return self.model.generate(
            ResearchTimeline,
            system_prompt=(
                "Build a research timeline using only supplied publication metadata and valid citation aliases. "
                "Publication events may use authoritative dates without a citation. Claims that work proposed, "
                "improved, contradicted, continued, influenced, or became a turning point require supplied citations. "
                "Do not infer influence from publication order. For each publication event, copy exactly one supplied "
                "paper_id and its published_at into date; use no claim_ids or citation_keys. For every other event, "
                "each claim_id must equal the claim_id of at least one citation alias on that same event. Periods and "
                "turning points require supplied citation aliases; omit them when the evidence is insufficient. "
                "Write every user-facing narrative field in Simplified Chinese, while preserving paper titles, "
                "proper names, metrics, and technical terms when translation would reduce precision."
            ),
            input_data={"plan": plan.model_dump(mode="json"), **inputs},
        )


class GraphValidationAgent:
    """Deterministic post-validator; it never asks a model to authorize relations."""

    name = "Graph Validation Agent"

    @staticmethod
    def validate(
        graph: ResearchGraph,
        *,
        allowed_node_ids: set[str],
        allowed_citation_keys: set[str],
        allowed_paper_ids: set[int],
        allowed_claim_ids: set[str],
        clusters: TopicClusters,
        timeline: ResearchTimeline,
        coverage_summary: ProjectCoverageSummary,
        stale_dependencies: list[str] | None = None,
        inaccessible_dependencies: list[str] | None = None,
    ) -> ProjectAnalysisValidation:
        actual_node_ids = {node.node_id for node in graph.nodes}
        if not actual_node_ids.issubset(allowed_node_ids):
            raise ResearchStepError("project_graph_node_invalid", "研究图谱包含未授权节点。")
        cluster_ids = {cluster.cluster_id for cluster in clusters.clusters}
        timeline_ids = {event.event_id for event in timeline.events}
        if any(not set(cluster.paper_ids).issubset(allowed_paper_ids) for cluster in clusters.clusters):
            raise ResearchStepError("project_cluster_paper_invalid", "主题簇包含未授权论文。")
        if any(not set(cluster.claim_ids).issubset(allowed_claim_ids) for cluster in clusters.clusters):
            raise ResearchStepError("project_cluster_claim_invalid", "主题簇包含未授权主张。")
        if any(not set(event.paper_ids).issubset(allowed_paper_ids) for event in timeline.events):
            raise ResearchStepError("project_timeline_paper_invalid", "研究时间线包含未授权论文。")
        if any(not set(event.claim_ids).issubset(allowed_claim_ids) for event in timeline.events):
            raise ResearchStepError("project_timeline_claim_invalid", "研究时间线包含未授权主张。")
        referenced_citations = {
            *graph.citation_keys,
            *clusters.citation_keys,
            *timeline.citation_keys,
        }
        if not referenced_citations.issubset(allowed_citation_keys):
            raise ResearchStepError("project_citation_invalid", "项目分析包含未授权引用。")
        semantic_types = {"supports", "contradicts", "belongs_to_cluster", "influences"}
        for edge in graph.edges:
            if edge.source_node_id not in actual_node_ids or edge.target_node_id not in actual_node_ids:
                raise ResearchStepError("project_graph_edge_invalid", "研究图谱边指向未授权节点。")
            if edge.relation_type in semantic_types and not edge.citation_keys:
                raise ResearchStepError("project_graph_citation_required", "语义图谱边缺少引用。")
            if not set(edge.citation_keys).issubset(allowed_citation_keys):
                raise ResearchStepError("project_graph_citation_invalid", "研究图谱边引用未通过校验。")
        return ProjectAnalysisValidation(
            validated_cluster_ids=sorted(cluster_ids),
            validated_timeline_event_ids=sorted(timeline_ids),
            validated_edge_ids=sorted(edge.edge_id for edge in graph.edges),
            stale_dependencies=sorted(set(stale_dependencies or [])),
            inaccessible_dependencies=sorted(set(inaccessible_dependencies or [])),
            coverage_summary=coverage_summary,
            warnings=(
                ["当前研究脉络仅覆盖项目中当前有效资料。"]
                if coverage_summary.limited
                else []
            ),
        )

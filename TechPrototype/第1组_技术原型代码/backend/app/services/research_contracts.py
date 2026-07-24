from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResearchWaitingInput(RuntimeError):
    """The durable Run/Step state already moved to waiting_input."""


class ResearchStepError(RuntimeError):
    def __init__(self, code: str, public_message: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.public_message = public_message
        self.retryable = retryable


class StrictResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResearchDateRange(StrictResearchModel):
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)

    @model_validator(mode="after")
    def valid_order(self) -> ResearchDateRange:
        if self.start_year is not None and self.end_year is not None:
            if self.start_year > self.end_year:
                raise ValueError("start_year must not exceed end_year")
        return self


class ResearchBrief(StrictResearchModel):
    topic: str = Field(min_length=1, max_length=500)
    research_questions: list[str] = Field(min_length=1, max_length=12)
    scope: str = Field(min_length=1, max_length=2_000)
    inclusion_criteria: list[str] = Field(min_length=1, max_length=20)
    exclusion_criteria: list[str] = Field(default_factory=list, max_length=20)
    date_range: ResearchDateRange
    preferred_sources: list[Literal["local", "arxiv"]] = Field(min_length=1, max_length=2)
    output_language: str = Field(min_length=1, max_length=40)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    schema_version: Literal[1] = 1


class SearchQueries(StrictResearchModel):
    queries: list[str] = Field(min_length=1, max_length=8)
    categories: list[str] = Field(default_factory=list, max_length=12)
    schema_version: Literal[1] = 1


class CandidatePaper(StrictResearchModel):
    paper_id: int | None = Field(default=None, ge=1)
    source: Literal["arxiv", "usenix", "sigops", "upload"]
    source_id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=2_000)
    authors: list[str] = Field(default_factory=list, max_length=200)
    abstract: str = Field(default="", max_length=30_000)
    categories: list[str] = Field(default_factory=list, max_length=100)
    primary_category: str = Field(default="cs.AI", max_length=100)
    published_at: str = Field(min_length=4, max_length=40)
    updated_at: str | None = Field(default=None, max_length=40)
    source_url: str | None = Field(default=None, max_length=2_048)
    pdf_url: str | None = Field(default=None, max_length=2_048)
    venue: str | None = Field(default=None, max_length=200)


class CandidatePapersArtifact(StrictResearchModel):
    items: list[CandidatePaper] = Field(default_factory=list, max_length=50)
    schema_version: Literal[1] = 1


class ScreeningItem(StrictResearchModel):
    paper_id: int = Field(ge=1)
    selected: bool
    score: float = Field(ge=0, le=1)
    rank: int | None = Field(default=None, ge=1)
    inclusion_reason: str | None = Field(default=None, max_length=2_000)
    exclusion_reason: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def reason_matches_selection(self) -> ScreeningItem:
        if self.selected and not (self.inclusion_reason or "").strip():
            raise ValueError("selected paper requires inclusion_reason")
        if not self.selected and not (self.exclusion_reason or "").strip():
            raise ValueError("excluded paper requires exclusion_reason")
        return self


class ScreeningResult(StrictResearchModel):
    items: list[ScreeningItem] = Field(default_factory=list, max_length=50)
    schema_version: Literal[1] = 1


class ChunkEvidenceRef(StrictResearchModel):
    evidence_id: str | None = Field(default=None, pattern=r"^EV-[0-9a-f]{24}$")
    chunk_id: int = Field(ge=1)
    paper_id: int = Field(ge=1)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_index: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    heading: str = Field(default="", max_length=1_000)

    @model_validator(mode="after")
    def valid_offsets(self) -> ChunkEvidenceRef:
        if self.char_end < self.char_start:
            raise ValueError("char_end must not precede char_start")
        return self


class PaperBrief(StrictResearchModel):
    paper_id: int = Field(ge=1)
    source: Literal["arxiv", "usenix", "sigops", "upload"]
    source_id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=2_000)
    authors: list[str] = Field(default_factory=list, max_length=200)
    year: int = Field(ge=1900, le=2100)
    research_question: str = Field(min_length=1, max_length=8_000)
    method: str = Field(min_length=1, max_length=12_000)
    dataset: str = Field(default="", max_length=12_000)
    experiments: str = Field(default="", max_length=16_000)
    key_findings: list[str] = Field(min_length=1, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    relevance: str = Field(min_length=1, max_length=8_000)
    evidence_ids: list[ChunkEvidenceRef] = Field(min_length=1, max_length=40)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: Literal[1] = 1


class ExtractionResult(StrictResearchModel):
    paper_brief_artifact_ids: list[str] = Field(default_factory=list, max_length=12)
    extracted_paper_ids: list[int] = Field(default_factory=list, max_length=12)
    schema_version: Literal[1] = 1


class ToolCallSummary(StrictResearchModel):
    tool: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    status: Literal["completed", "failed", "reused"]
    attempt: int = Field(ge=1, le=20)
    summary: str = Field(min_length=1, max_length=500)
    duration_ms: int = Field(ge=0)
    error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,79}$")


class SynthesisPlan(StrictResearchModel):
    topic: str = Field(min_length=1, max_length=500)
    research_questions: list[str] = Field(min_length=1, max_length=12)
    comparison_dimensions: list[str] = Field(min_length=1, max_length=12)
    synthesis_strategy: str = Field(min_length=1, max_length=4_000)
    expected_outputs: list[str] = Field(min_length=1, max_length=12)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    schema_version: Literal[1] = 1


class CitedStatement(StrictResearchModel):
    statement_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$")
    text: str = Field(min_length=1, max_length=12_000)
    citation_keys: list[str] = Field(min_length=1, max_length=40)


class ComparisonPaper(StrictResearchModel):
    paper_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=2_000)


class ComparisonCell(StrictResearchModel):
    cell_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$")
    dimension: str = Field(min_length=1, max_length=500)
    paper_id: int = Field(ge=1)
    value: str = Field(min_length=1, max_length=12_000)
    citation_keys: list[str] = Field(min_length=1, max_length=20)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)


class MissingEvidence(StrictResearchModel):
    dimension: str = Field(min_length=1, max_length=500)
    paper_id: int | None = Field(default=None, ge=1)
    uncertainty: str = Field(min_length=1, max_length=4_000)


class ComparisonMatrix(StrictResearchModel):
    dimensions: list[str] = Field(min_length=1, max_length=12)
    papers: list[ComparisonPaper] = Field(min_length=1, max_length=12)
    cells: list[ComparisonCell] = Field(min_length=1, max_length=144)
    agreements: list[CitedStatement] = Field(default_factory=list, max_length=30)
    disagreements: list[CitedStatement] = Field(default_factory=list, max_length=30)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list, max_length=100)
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def unique_matrix_identity(self) -> ComparisonMatrix:
        if len(self.dimensions) != len(set(self.dimensions)):
            raise ValueError("comparison dimensions must be unique")
        paper_ids = [item.paper_id for item in self.papers]
        cell_ids = [item.cell_id for item in self.cells]
        statement_ids = [item.statement_id for item in [*self.agreements, *self.disagreements]]
        if len(paper_ids) != len(set(paper_ids)) or len(cell_ids) != len(set(cell_ids)):
            raise ValueError("comparison paper and cell identities must be unique")
        if len(statement_ids) != len(set(statement_ids)):
            raise ValueError("comparison statement identities must be unique")
        allowed_papers = set(paper_ids)
        allowed_dimensions = set(self.dimensions)
        if any(item.paper_id not in allowed_papers or item.dimension not in allowed_dimensions for item in self.cells):
            raise ValueError("comparison cells must reference declared papers and dimensions")
        return self


class SynthesisClaim(StrictResearchModel):
    claim_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$")
    claim: str = Field(min_length=1, max_length=12_000)
    claim_type: Literal["finding", "agreement", "disagreement", "limitation", "gap"]
    confidence: float = Field(ge=0, le=1)
    supporting_citations: list[str] = Field(default_factory=list, max_length=40)
    contradicting_citations: list[str] = Field(default_factory=list, max_length=40)
    covered_paper_ids: list[int] = Field(default_factory=list, max_length=12)
    caveats: list[str] = Field(default_factory=list, max_length=20)
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def factual_claims_have_citations(self) -> SynthesisClaim:
        if self.claim_type in {"finding", "agreement", "disagreement"} and not self.supporting_citations:
            raise ValueError("factual synthesis claim requires supporting citations")
        if self.claim_type in {"finding", "agreement", "disagreement"} and not self.covered_paper_ids:
            raise ValueError("factual synthesis claim requires covered papers")
        citations = [*self.supporting_citations, *self.contradicting_citations]
        if len(citations) != len(set(citations)) or len(self.covered_paper_ids) != len(set(self.covered_paper_ids)):
            raise ValueError("claim citation and paper identities must be unique")
        return self


class SynthesisClaims(StrictResearchModel):
    claims: list[SynthesisClaim] = Field(min_length=1, max_length=100)
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def unique_claim_identity(self) -> SynthesisClaims:
        claim_ids = [item.claim_id for item in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("synthesis claim identities must be unique")
        return self


class CitationRegistryEntry(StrictResearchModel):
    citation_key: str = Field(pattern=r"^C[1-9][0-9]*$")
    claim_id: str = Field(min_length=1, max_length=80)
    claim_ids: list[str] = Field(default_factory=list, min_length=0, max_length=200)
    paper_id: int = Field(ge=1)
    evidence_id: str = Field(pattern=r"^EV-[0-9a-f]{24}$")

    @model_validator(mode="after")
    def complete_claim_relations(self) -> CitationRegistryEntry:
        if not self.claim_ids:
            self.claim_ids = [self.claim_id]
        if self.claim_id not in self.claim_ids or len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("citation registry claim relations must be unique and include the primary claim")
        return self


class CitationRegistry(StrictResearchModel):
    entries: list[CitationRegistryEntry] = Field(min_length=1, max_length=480)
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def unique_citation_keys(self) -> CitationRegistry:
        keys = [item.citation_key for item in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("citation keys must be unique within an artifact version")
        return self


class CitationValidationResult(StrictResearchModel):
    valid_citation_keys: list[str] = Field(default_factory=list, max_length=480)
    stale_citation_keys: list[str] = Field(default_factory=list, max_length=480)
    inaccessible_citation_keys: list[str] = Field(default_factory=list, max_length=480)
    invalid_citation_keys: list[str] = Field(default_factory=list, max_length=480)
    verified_claim_ids: list[str] = Field(default_factory=list, max_length=100)
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def disjoint_statuses(self) -> CitationValidationResult:
        groups = [self.valid_citation_keys, self.stale_citation_keys, self.inaccessible_citation_keys, self.invalid_citation_keys]
        flattened = [item for group in groups for item in group]
        if len(flattened) != len(set(flattened)):
            raise ValueError("citation validation statuses must be disjoint")
        if len(self.verified_claim_ids) != len(set(self.verified_claim_ids)):
            raise ValueError("verified claim identities must be unique")
        return self


class ResearchReport(StrictResearchModel):
    title: str = Field(min_length=1, max_length=2_000)
    topic: str = Field(min_length=1, max_length=500)
    executive_summary: list[CitedStatement] = Field(min_length=1, max_length=20)
    research_questions: list[str] = Field(min_length=1, max_length=12)
    findings: list[CitedStatement] = Field(min_length=1, max_length=60)
    agreements: list[CitedStatement] = Field(default_factory=list, max_length=30)
    disagreements: list[CitedStatement] = Field(default_factory=list, max_length=30)
    limitations: list[str] = Field(default_factory=list, max_length=40)
    research_gaps: list[str] = Field(default_factory=list, max_length=40)
    conclusion: list[CitedStatement] = Field(min_length=1, max_length=20)
    citation_keys: list[str] = Field(min_length=1, max_length=480)
    generated_from_artifact_versions: dict[str, int] = Field(min_length=1, max_length=20)
    schema_version: Literal[1] = 1


class LandscapeCitedStatement(StrictResearchModel):
    """A project-level fact whose support can be redacted independently."""

    text: str = Field(min_length=1, max_length=12_000)
    citation_keys: list[str] = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def unique_citations(self) -> LandscapeCitedStatement:
        if len(self.citation_keys) != len(set(self.citation_keys)):
            raise ValueError("landscape statement citation identities must be unique")
        return self


class ResearchLandscapePlan(StrictResearchModel):
    project_id: str = Field(min_length=1, max_length=100)
    topic: str = Field(min_length=1, max_length=500)
    research_questions: list[str] = Field(min_length=1, max_length=12)
    selected_item_ids: list[str] = Field(min_length=1, max_length=200)
    clustering_dimensions: list[str] = Field(min_length=1, max_length=12)
    timeline_dimensions: list[str] = Field(min_length=1, max_length=12)
    graph_relation_types: list[
        Literal[
            "contains",
            "generated_from",
            "cites",
            "supports",
            "contradicts",
            "belongs_to_cluster",
            "precedes",
            "influences",
        ]
    ] = Field(min_length=1, max_length=8)
    constraints: list[str] = Field(default_factory=list, max_length=30)
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def unique_plan_identity(self) -> ResearchLandscapePlan:
        for values in (
            self.selected_item_ids,
            self.clustering_dimensions,
            self.timeline_dimensions,
            self.graph_relation_types,
        ):
            if len(values) != len(set(values)):
                raise ValueError("landscape plan identities and dimensions must be unique")
        return self


class TopicCluster(StrictResearchModel):
    cluster_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")
    label: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=12_000)
    summary_citation_keys: list[str] = Field(min_length=1, max_length=80)
    paper_ids: list[int] = Field(default_factory=list, max_length=200)
    claim_ids: list[str] = Field(default_factory=list, max_length=200)
    citation_keys: list[str] = Field(default_factory=list, max_length=200)
    distinguishing_features: list[LandscapeCitedStatement] = Field(default_factory=list, max_length=40)
    uncertainties: list[str] = Field(default_factory=list, max_length=40)
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def complete_cluster_support(self) -> TopicCluster:
        if not self.paper_ids and not self.claim_ids:
            raise ValueError("topic cluster requires at least one paper or claim")
        for values in (
            self.summary_citation_keys,
            self.paper_ids,
            self.claim_ids,
            self.citation_keys,
        ):
            if len(values) != len(set(values)):
                raise ValueError("topic cluster identities must be unique")
        used = {
            *self.summary_citation_keys,
            *(key for feature in self.distinguishing_features for key in feature.citation_keys),
        }
        if not used.issubset(set(self.citation_keys)):
            raise ValueError("topic cluster factual statements must use declared citations")
        return self


class TopicClusters(StrictResearchModel):
    clusters: list[TopicCluster] = Field(default_factory=list, max_length=80)
    unclassified_paper_ids: list[int] = Field(default_factory=list, max_length=200)
    uncertainties: list[str] = Field(default_factory=list, max_length=100)
    citation_keys: list[str] = Field(default_factory=list, max_length=480)
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def consistent_clusters(self) -> TopicClusters:
        cluster_ids = [item.cluster_id for item in self.clusters]
        if len(cluster_ids) != len(set(cluster_ids)):
            raise ValueError("topic cluster identities must be unique")
        if len(self.unclassified_paper_ids) != len(set(self.unclassified_paper_ids)):
            raise ValueError("unclassified paper identities must be unique")
        if len(self.citation_keys) != len(set(self.citation_keys)):
            raise ValueError("topic cluster citations must be unique")
        used = {key for item in self.clusters for key in item.citation_keys}
        if used != set(self.citation_keys):
            raise ValueError("topic cluster citation summary is incomplete")
        return self


class TimelineDateRange(StrictResearchModel):
    start: str = Field(min_length=4, max_length=40)
    end: str = Field(min_length=4, max_length=40)


class TimelineEvent(StrictResearchModel):
    event_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")
    date: str | None = Field(default=None, min_length=4, max_length=40)
    date_range: TimelineDateRange | None = None
    event_type: Literal[
        "publication",
        "method_proposed",
        "improvement",
        "contradiction",
        "continuation",
        "turning_point",
    ]
    title: str = Field(min_length=1, max_length=2_000)
    description: str = Field(min_length=1, max_length=12_000)
    paper_ids: list[int] = Field(default_factory=list, max_length=200)
    claim_ids: list[str] = Field(default_factory=list, max_length=200)
    citation_keys: list[str] = Field(default_factory=list, max_length=200)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def valid_event_support(self) -> TimelineEvent:
        if (self.date is None) == (self.date_range is None):
            raise ValueError("timeline event requires exactly one date or date_range")
        for values in (self.paper_ids, self.claim_ids, self.citation_keys):
            if len(values) != len(set(values)):
                raise ValueError("timeline event identities must be unique")
        semantic_types = {
            "method_proposed",
            "improvement",
            "contradiction",
            "continuation",
            "turning_point",
        }
        if self.event_type in semantic_types and not self.citation_keys:
            raise ValueError("semantic timeline event requires citations")
        if self.event_type == "publication" and (len(self.paper_ids) != 1 or self.claim_ids):
            raise ValueError("publication event must identify exactly one paper")
        return self


class TimelinePeriod(StrictResearchModel):
    period_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")
    date_range: TimelineDateRange
    title: str = Field(min_length=1, max_length=1_000)
    description: str = Field(min_length=1, max_length=12_000)
    event_ids: list[str] = Field(min_length=1, max_length=200)
    citation_keys: list[str] = Field(min_length=1, max_length=200)


class ResearchTimeline(StrictResearchModel):
    events: list[TimelineEvent] = Field(min_length=1, max_length=300)
    periods: list[TimelinePeriod] = Field(default_factory=list, max_length=80)
    turning_points: list[LandscapeCitedStatement] = Field(default_factory=list, max_length=40)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=100)
    citation_keys: list[str] = Field(default_factory=list, max_length=480)
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def consistent_timeline(self) -> ResearchTimeline:
        event_ids = [item.event_id for item in self.events]
        period_ids = [item.period_id for item in self.periods]
        if len(event_ids) != len(set(event_ids)) or len(period_ids) != len(set(period_ids)):
            raise ValueError("timeline identities must be unique")
        known_events = set(event_ids)
        if any(not set(period.event_ids).issubset(known_events) for period in self.periods):
            raise ValueError("timeline period contains unknown events")
        used = {
            *(key for item in self.events for key in item.citation_keys),
            *(key for item in self.periods for key in item.citation_keys),
            *(key for item in self.turning_points for key in item.citation_keys),
        }
        if used != set(self.citation_keys):
            raise ValueError("timeline citation summary is incomplete")
        return self


class ResearchGraphNode(StrictResearchModel):
    node_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9:_.-]{0,159}$")
    node_type: Literal["project", "run", "paper", "report", "topic_cluster", "synthesis_claim"]
    label: str = Field(min_length=1, max_length=2_000)
    entity_ref: str = Field(min_length=1, max_length=240)
    status: Literal["valid", "stale", "inaccessible"] = "valid"


class ResearchGraphEdge(StrictResearchModel):
    edge_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9:_.-]{0,159}$")
    source_node_id: str = Field(min_length=1, max_length=160)
    target_node_id: str = Field(min_length=1, max_length=160)
    relation_type: Literal[
        "contains",
        "generated_from",
        "cites",
        "supports",
        "contradicts",
        "belongs_to_cluster",
        "precedes",
        "influences",
    ]
    citation_keys: list[str] = Field(default_factory=list, max_length=200)
    status: Literal["valid", "stale", "inaccessible"] = "valid"

    @model_validator(mode="after")
    def semantic_edges_are_cited(self) -> ResearchGraphEdge:
        if self.source_node_id == self.target_node_id:
            raise ValueError("research graph self edges are not allowed")
        if self.relation_type in {
            "supports",
            "contradicts",
            "belongs_to_cluster",
            "influences",
        } and not self.citation_keys:
            raise ValueError("semantic graph edge requires citations")
        if len(self.citation_keys) != len(set(self.citation_keys)):
            raise ValueError("graph edge citations must be unique")
        return self


class ResearchGraph(StrictResearchModel):
    nodes: list[ResearchGraphNode] = Field(min_length=1, max_length=500)
    edges: list[ResearchGraphEdge] = Field(default_factory=list, max_length=1_000)
    citation_keys: list[str] = Field(default_factory=list, max_length=480)
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def consistent_graph(self) -> ResearchGraph:
        node_ids = [item.node_id for item in self.nodes]
        edge_ids = [item.edge_id for item in self.edges]
        if len(node_ids) != len(set(node_ids)) or len(edge_ids) != len(set(edge_ids)):
            raise ValueError("research graph node and edge identities must be unique")
        allowed_nodes = set(node_ids)
        if any(
            edge.source_node_id not in allowed_nodes or edge.target_node_id not in allowed_nodes
            for edge in self.edges
        ):
            raise ValueError("research graph edge references an unknown node")
        used = {key for edge in self.edges for key in edge.citation_keys}
        if used != set(self.citation_keys):
            raise ValueError("research graph citation summary is incomplete")
        return self


class ProjectCoverageSummary(StrictResearchModel):
    accessible_item_count: int = Field(ge=0)
    paper_count: int = Field(ge=0)
    report_count: int = Field(ge=0)
    valid_citation_count: int = Field(ge=0)
    limited: bool


class ProjectAnalysisValidation(StrictResearchModel):
    validated_cluster_ids: list[str] = Field(default_factory=list, max_length=80)
    validated_timeline_event_ids: list[str] = Field(default_factory=list, max_length=300)
    validated_edge_ids: list[str] = Field(default_factory=list, max_length=2_000)
    stale_dependencies: list[str] = Field(default_factory=list, max_length=500)
    inaccessible_dependencies: list[str] = Field(default_factory=list, max_length=500)
    coverage_summary: ProjectCoverageSummary
    warnings: list[str] = Field(default_factory=list, max_length=100)
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def unique_validation_identity(self) -> ProjectAnalysisValidation:
        for values in (
            self.validated_cluster_ids,
            self.validated_timeline_event_ids,
            self.validated_edge_ids,
            self.stale_dependencies,
            self.inaccessible_dependencies,
        ):
            if len(values) != len(set(values)):
                raise ValueError("project validation identities must be unique")
        return self


ARTIFACT_MODELS: dict[str, type[StrictResearchModel]] = {
    "research_brief": ResearchBrief,
    "search_queries": SearchQueries,
    "candidate_papers": CandidatePapersArtifact,
    "screening_result": ScreeningResult,
    "paper_brief": PaperBrief,
    "extraction_result": ExtractionResult,
    "synthesis_plan": SynthesisPlan,
    "comparison_matrix": ComparisonMatrix,
    "synthesis_claims": SynthesisClaims,
    "citation_registry": CitationRegistry,
    "citation_validation_result": CitationValidationResult,
    "research_report": ResearchReport,
    "research_landscape_plan": ResearchLandscapePlan,
    "topic_clusters": TopicClusters,
    "research_timeline": ResearchTimeline,
    "research_graph": ResearchGraph,
    "project_analysis_validation": ProjectAnalysisValidation,
}


def validate_artifact_content(artifact_type: str, content: dict[str, Any]) -> dict[str, Any]:
    model = ARTIFACT_MODELS.get(artifact_type)
    if model is None:
        raise ValueError("unsupported artifact type")
    return model.model_validate(content).model_dump(mode="json")


def canonical_arxiv_id(value: str) -> str:
    cleaned = value.strip()
    if "/abs/" in cleaned:
        cleaned = cleaned.split("/abs/", 1)[1]
    elif cleaned.startswith("http://") or cleaned.startswith("https://"):
        cleaned = cleaned.rstrip("/").rsplit("/", 1)[-1]
    cleaned = cleaned.strip("/")
    cleaned = re.sub(r"v\d+$", "", cleaned, flags=re.IGNORECASE)
    if not cleaned or len(cleaned) > 100 or not re.fullmatch(r"[A-Za-z0-9./-]+", cleaned):
        raise ValueError("invalid arXiv identifier")
    return cleaned

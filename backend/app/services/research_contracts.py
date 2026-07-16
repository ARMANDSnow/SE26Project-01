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

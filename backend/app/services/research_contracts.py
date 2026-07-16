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


ARTIFACT_MODELS: dict[str, type[StrictResearchModel]] = {
    "research_brief": ResearchBrief,
    "search_queries": SearchQueries,
    "candidate_papers": CandidatePapersArtifact,
    "screening_result": ScreeningResult,
    "paper_brief": PaperBrief,
    "extraction_result": ExtractionResult,
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

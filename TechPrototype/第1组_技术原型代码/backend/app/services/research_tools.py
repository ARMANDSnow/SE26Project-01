from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from ..db.connection import connect
from ..models import PaperCandidate, PaperSource
from ..repositories.papers import get_paper_record, upsert_paper
from ..repositories.research import ResearchConflictError, ResearchNotFoundError
from ..repositories.research_citations import register_opened_evidence
from ..repositories.research_data import (
    assert_active_tool_context,
    assert_safe_research_payload,
    authorize_budget_item,
    reserve_budget,
    settle_budget_call,
    upsert_run_paper,
)
from ..repositories.uploads import paper_is_accessible
from .documents import get_paper_document, parse_paper_document
from .paper_tools import PaperToolbox
from .remote_pdf import PaperPdfService, RemotePdfError
from .research_contracts import (
    CandidatePaper,
    ChunkEvidenceRef,
    ResearchStepError,
    ResearchWaitingInput,
    StrictResearchModel,
    ToolCallSummary,
    canonical_arxiv_id,
)
from .search import search_chunks
from .sources.arxiv import fetch_arxiv_papers


_ARXIV_DISCOVERY_STOPWORDS = {
    "and", "arxiv", "for", "from", "in", "of", "or", "the", "to", "with",
}


def _arxiv_discovery_terms(queries: list[str]) -> list[str]:
    """Keep one real arXiv request broad enough for LLM-written discovery queries."""
    primary = queries[0]
    phrase_match = re.search(r"retrieval[- ]augmented generation", primary, re.IGNORECASE)
    acronym_match = next(
        (
            match
            for query in queries
            for match in re.findall(r"\b[A-Z][A-Z0-9-]{1,9}\b", query)
            if match.casefold() != "arxiv"
        ),
        None,
    )
    core = phrase_match.group(0).replace("-", " ") if phrase_match else acronym_match
    terms: list[str] = []
    seen: set[str] = set()
    if core:
        terms.append(core)
        seen.update(re.findall(r"[a-z]+", core.casefold()))
    for token in re.findall(r"[A-Za-z][A-Za-z-]{1,}", primary):
        normalized = token.casefold()
        if normalized in _ARXIV_DISCOVERY_STOPWORDS or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(token)
        if len(terms) == 8:
            break
    return terms or [queries[0]]


class ToolTransientError(RuntimeError):
    pass


class ToolInput(StrictResearchModel):
    pass


class ToolOutput(StrictResearchModel):
    pass


class LocalSearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=500)
    category: str = Field(default="", max_length=80)
    limit: int = Field(default=20, ge=1, le=50)


class LocalPaper(ToolOutput):
    paper_id: int = Field(ge=1)
    source: Literal["arxiv", "usenix", "sigops", "upload"]
    source_id: str
    title: str
    authors: list[str]
    abstract: str
    primary_category: str
    published_at: str


class LocalSearchOutput(ToolOutput):
    items: list[LocalPaper] = Field(default_factory=list, max_length=50)
    count: int = Field(ge=0, le=50)


class ArxivSearchInput(ToolInput):
    queries: list[str] = Field(min_length=1, max_length=8)
    categories: list[str] = Field(default_factory=list, max_length=12)
    max_results: int = Field(default=30, ge=1, le=50)


class ArxivSearchOutput(ToolOutput):
    items: list[CandidatePaper] = Field(default_factory=list, max_length=50)
    count: int = Field(ge=0, le=50)


class ImportPapersInput(ToolInput):
    items: list[CandidatePaper] = Field(default_factory=list, max_length=50)


class ImportedPaper(ToolOutput):
    paper_id: int = Field(ge=1)
    source: str
    source_id: str
    reused: bool


class ImportPapersOutput(ToolOutput):
    items: list[ImportedPaper] = Field(default_factory=list, max_length=50)
    imported_count: int = Field(ge=0)
    reused_count: int = Field(ge=0)


class PaperIdInput(ToolInput):
    paper_id: int = Field(ge=1)


class FetchDocumentOutput(ToolOutput):
    paper_id: int = Field(ge=1)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reused: bool


class ParseDocumentOutput(FetchDocumentOutput):
    status: Literal["completed"]
    chunk_count: int = Field(ge=1)


class ChunkSearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=500)
    paper_ids: list[int] = Field(min_length=1, max_length=12)
    limit: int = Field(default=8, ge=1, le=12)


class ChunkSearchItem(ToolOutput):
    ref_id: str
    paper_id: int
    paper_title: str
    heading: str
    snippet: str
    score: float


class ChunkSearchOutput(ToolOutput):
    items: list[ChunkSearchItem] = Field(default_factory=list, max_length=12)
    count: int = Field(ge=0, le=12)


class OpenEvidenceInput(ToolInput):
    ref_id: str = Field(pattern=r"^chunk:[1-9][0-9]*$")
    max_chars: int = Field(default=2_400, ge=200, le=4_000)


class OpenEvidenceOutput(ToolOutput):
    evidence: ChunkEvidenceRef
    excerpt: str = Field(min_length=1, max_length=4_000)


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_attempts: int = Field(ge=1, le=5)
    backoff_seconds: float = Field(ge=0, le=10)
    retryable_error_codes: tuple[str, ...] = ()


@dataclass(slots=True)
class ToolContext:
    run_id: str
    step_id: str
    user_id: int
    worker_id: str
    lease_generation: int
    search_refs: set[str] = field(default_factory=set)


InputT = TypeVar("InputT", bound=ToolInput)
OutputT = TypeVar("OutputT", bound=ToolOutput)
ToolHandler = Callable[[ToolContext, InputT], OutputT]
SummaryBuilder = Callable[[OutputT], str]


@dataclass(frozen=True, slots=True)
class ToolDefinition(Generic[InputT, OutputT]):
    name: str
    input_model: type[InputT]
    output_model: type[OutputT]
    owner_scope: Literal["run_owner", "paper_access"]
    idempotent: bool
    timeout_seconds: float
    retry_policy: RetryPolicy
    external_network: bool
    external_model: bool
    safe_summary: SummaryBuilder[OutputT]
    error_codes: tuple[str, ...]
    redaction_strategy: str
    handler: ToolHandler[InputT, OutputT]


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition[Any, Any]] = {}

    def register(self, definition: ToolDefinition[Any, Any]) -> None:
        if definition.name in self._definitions:
            raise ValueError("tool is already registered")
        self._definitions[definition.name] = definition

    def definition(self, name: str) -> ToolDefinition[Any, Any]:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise ResearchStepError("unknown_tool", "请求的研究工具不可用。") from exc

    def definitions(self) -> tuple[ToolDefinition[Any, Any], ...]:
        return tuple(self._definitions.values())

    def invoke(
        self,
        name: str,
        raw_input: dict[str, Any],
        context: ToolContext,
    ) -> tuple[ToolOutput, ToolCallSummary]:
        definition = self.definition(name)
        try:
            payload = definition.input_model.model_validate(raw_input)
        except Exception as exc:
            raise ResearchStepError("tool_input_invalid", "研究工具输入未通过结构校验。") from exc
        try:
            with connect() as permission_conn:
                assert_active_tool_context(
                    permission_conn,
                    run_id=context.run_id,
                    step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    user_id=context.user_id,
                )
                paper_ids: list[int] = []
                if definition.owner_scope == "paper_access":
                    if hasattr(payload, "paper_id"):
                        paper_ids.append(int(payload.paper_id))
                    if hasattr(payload, "paper_ids"):
                        paper_ids.extend(int(item) for item in payload.paper_ids)
                    if any(not paper_is_accessible(permission_conn, paper_id, context.user_id) for paper_id in paper_ids):
                        raise ResearchNotFoundError("research paper not found")
        except (ResearchNotFoundError, ResearchConflictError) as exc:
            raise ResearchStepError("tool_permission_or_state", "研究工具无权访问对象或状态已变化。") from exc
        last_code = "tool_failed"
        for attempt in range(1, definition.retry_policy.max_attempts + 1):
            with connect() as conn:
                allowed = reserve_budget(
                    conn,
                    run_id=context.run_id,
                    step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    kind="tool_calls",
                )
            if not allowed:
                raise ResearchWaitingInput("research budget requires input")
            started = time.monotonic()
            succeeded = False
            try:
                if name == "arxiv_search":
                    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tool-{name}")
                    future = executor.submit(definition.handler, context, payload)
                    try:
                        raw_output = future.result(timeout=definition.timeout_seconds)
                    finally:
                        executor.shutdown(wait=False, cancel_futures=True)
                else:
                    # Side-effecting adapters use their own bounded network/parse
                    # controls and execute once. Python threads cannot be killed
                    # safely after a timeout, so Registry retries never overlap them.
                    raw_output = definition.handler(context, payload)
                output = definition.output_model.model_validate(raw_output)
                public = output.model_dump(mode="json")
                assert_safe_research_payload(public)
                summary_text = definition.safe_summary(output)
                assert_safe_research_payload(summary_text)
                succeeded = True
                status: Literal["completed", "reused", "failed"] = (
                    "reused" if bool(getattr(output, "reused", False)) else "completed"
                )
                duration_ms = max(0, int((time.monotonic() - started) * 1_000))
                return output, ToolCallSummary(
                    tool=name,
                    status=status,
                    attempt=attempt,
                    summary=summary_text,
                    duration_ms=duration_ms,
                )
            except FutureTimeoutError:
                last_code = "tool_timeout"
                if not definition.idempotent:
                    raise ResearchStepError(last_code, "研究工具执行超时，未自动重试非幂等操作。")
            except ResearchWaitingInput:
                raise
            except (ResearchNotFoundError, ResearchConflictError) as exc:
                raise ResearchStepError("tool_permission_or_state", "研究工具无权访问对象或状态已变化。") from exc
            except ToolTransientError:
                last_code = "tool_temporarily_unavailable"
            except ResearchStepError:
                raise
            except Exception as exc:
                last_code = "tool_failed"
                if last_code not in definition.retry_policy.retryable_error_codes:
                    raise ResearchStepError(last_code, "研究工具执行失败，仅保留安全错误摘要。") from exc
            finally:
                try:
                    with connect() as conn:
                        settle_budget_call(
                            conn,
                            run_id=context.run_id,
                            step_id=context.step_id,
                            worker_id=context.worker_id,
                            lease_generation=context.lease_generation,
                            succeeded=succeeded,
                        )
                except ResearchConflictError:
                    if succeeded:
                        raise
            if attempt < definition.retry_policy.max_attempts:
                time.sleep(definition.retry_policy.backoff_seconds * (2 ** (attempt - 1)))
        raise ResearchStepError(last_code, "研究工具在受控重试后仍不可用。")


def _local_search(context: ToolContext, payload: LocalSearchInput) -> LocalSearchOutput:
    with connect() as conn:
        result = PaperToolbox(conn, user_id=context.user_id).search_metadata(
            query=payload.query,
            category=payload.category,
            limit=min(payload.limit, 20),
        )
    items = [
        LocalPaper(
            paper_id=int(item["paper_id"]),
            source=item["source"],
            source_id=str(item["source_id"]),
            title=str(item["title"]),
            authors=list(item["authors"]),
            abstract=str(item["abstract_snippet"]),
            primary_category=str(item["category"]),
            published_at=str(item["published_at"]),
        )
        for item in result["items"]
    ]
    return LocalSearchOutput(items=items, count=len(items))


def _arxiv_search(context: ToolContext, payload: ArxivSearchInput) -> ArxivSearchOutput:
    del context
    try:
        fetched = fetch_arxiv_papers(
            payload.categories,
            _arxiv_discovery_terms(payload.queries),
            payload.max_results,
            True,
            True,
        )
    except Exception as exc:
        raise ToolTransientError("arxiv_search_unavailable") from exc
    seen: set[str] = set()
    items: list[CandidatePaper] = []
    for paper in fetched:
        source_id = canonical_arxiv_id(paper.source_id)
        if source_id in seen:
            continue
        seen.add(source_id)
        items.append(
            CandidatePaper(
                source="arxiv",
                source_id=source_id,
                title=paper.title,
                authors=list(paper.authors),
                abstract=paper.abstract,
                categories=list(paper.categories),
                primary_category=paper.primary_category,
                published_at=paper.published_at,
                updated_at=paper.updated_at,
                source_url=f"https://arxiv.org/abs/{source_id}",
                pdf_url=f"https://arxiv.org/pdf/{source_id}",
                venue=paper.venue,
            )
        )
    return ArxivSearchOutput(items=items, count=len(items))


def _import_papers(context: ToolContext, payload: ImportPapersInput) -> ImportPapersOutput:
    results: list[ImportedPaper] = []
    imported = 0
    reused = 0
    for item in payload.items:
        source_id = canonical_arxiv_id(item.source_id) if item.source == "arxiv" else item.source_id
        with connect() as conn:
            existing = None
            if item.paper_id is not None:
                existing = get_paper_record(conn, item.paper_id)
                if existing is not None and (str(existing.source) != item.source or existing.source_id != source_id):
                    raise ResearchStepError("paper_identity_mismatch", "论文 ID 与来源身份不一致。")
            else:
                existing_row = conn.execute(
                    "SELECT id FROM papers WHERE source = ? AND source_id = ?",
                    (item.source, source_id),
                ).fetchone()
                existing = get_paper_record(conn, int(existing_row["id"])) if existing_row else None
            relation = conn.execute(
                "SELECT paper_id FROM research_run_papers WHERE run_id = ? AND source = ? AND source_id = ?",
                (context.run_id, item.source, source_id),
            ).fetchone()
        if relation is None:
            with connect() as budget_conn:
                allowed = authorize_budget_item(
                    budget_conn,
                    run_id=context.run_id,
                    step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    kind="candidate_papers",
                )
            if not allowed:
                raise ResearchWaitingInput("candidate budget requires input")
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                assert_active_tool_context(
                    conn,
                    run_id=context.run_id,
                    step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    user_id=context.user_id,
                )
                if existing is None:
                    if item.source != "arxiv":
                        raise ResearchStepError("untrusted_source_identity", "只能从受信来源结果导入新论文。")
                    candidate = PaperCandidate(
                        source=PaperSource(item.source),
                        source_id=source_id,
                        title=item.title,
                        authors=tuple(item.authors),
                        abstract=item.abstract,
                        categories=tuple(item.categories),
                        primary_category=item.primary_category,
                        published_at=item.published_at,
                        updated_at=item.updated_at,
                        source_url=f"https://arxiv.org/abs/{source_id}",
                        pdf_url=f"https://arxiv.org/pdf/{source_id}",
                        venue=item.venue,
                    )
                    paper_id = int(upsert_paper(conn, candidate, commit=False))
                    imported += 1
                else:
                    paper_id = int(existing.id)
                    reused += 1
                upsert_run_paper(
                    conn,
                    run_id=context.run_id,
                    source_step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    paper_id=paper_id,
                    stage="candidate",
                    manage_transaction=False,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        results.append(ImportedPaper(paper_id=paper_id, source=item.source, source_id=source_id, reused=existing is not None))
    return ImportPapersOutput(items=results, imported_count=imported, reused_count=reused)


def _fetch_document(context: ToolContext, payload: PaperIdInput) -> FetchDocumentOutput:
    with connect() as conn:
        if not paper_is_accessible(conn, payload.paper_id, context.user_id):
            raise ResearchNotFoundError("research paper not found")
        paper = get_paper_record(conn, payload.paper_id)
        if paper is None:
            raise ResearchNotFoundError("research paper not found")
        reused = paper.asset_id is not None
        try:
            asset = PaperPdfService(conn).ensure(
                payload.paper_id,
                before_attach=lambda active_conn: assert_active_tool_context(
                    active_conn,
                    run_id=context.run_id,
                    step_id=context.step_id,
                    worker_id=context.worker_id,
                    lease_generation=context.lease_generation,
                    user_id=context.user_id,
                ),
            )
        except RemotePdfError as exc:
            raise ResearchStepError("document_fetch_failed", "论文正文获取失败。") from exc
    return FetchDocumentOutput(
        paper_id=payload.paper_id,
        source_hash=str(asset.id).removeprefix("sha256:"),
        reused=reused,
    )


def _parse_document(context: ToolContext, payload: PaperIdInput) -> ParseDocumentOutput:
    with connect() as conn:
        if not paper_is_accessible(conn, payload.paper_id, context.user_id):
            raise ResearchNotFoundError("research paper not found")
        paper = get_paper_record(conn, payload.paper_id)
        if paper is None or paper.asset_id is None:
            raise ResearchStepError("document_not_fetched", "论文 PDF 尚未安全获取。")
        source_hash = str(paper.asset_id).removeprefix("sha256:")
        current = get_paper_document(conn, payload.paper_id)
        reused = bool(current and current.get("status") == "completed" and current.get("source_hash") == source_hash)
        if not reused:
            try:
                current = parse_paper_document(
                    conn,
                    payload.paper_id,
                    context.user_id,
                    fence=lambda active_conn: assert_active_tool_context(
                        active_conn,
                        run_id=context.run_id,
                        step_id=context.step_id,
                        worker_id=context.worker_id,
                        lease_generation=context.lease_generation,
                        user_id=context.user_id,
                    ),
                )
            except Exception as exc:
                raise ResearchStepError("document_parse_failed", "Docling 解析失败，仅保留安全错误摘要。") from exc
        count_row = conn.execute(
            "SELECT COUNT(*) AS count FROM paper_chunks WHERE paper_id = ? AND source_hash = ?",
            (payload.paper_id, source_hash),
        ).fetchone()
        count = int(count_row["count"] if count_row else 0)
    if count < 1:
        raise ResearchStepError("document_chunks_missing", "解析结果没有可检索正文片段。")
    return ParseDocumentOutput(
        paper_id=payload.paper_id,
        source_hash=source_hash,
        reused=reused,
        status="completed",
        chunk_count=count,
    )


def _chunk_search(context: ToolContext, payload: ChunkSearchInput) -> ChunkSearchOutput:
    with connect() as conn:
        allowed = conn.execute(
            f"SELECT paper_id FROM research_run_papers WHERE run_id = ? AND paper_id IN ({','.join('?' for _ in payload.paper_ids)}) AND stage IN ('fulltext_ready', 'read', 'extracted')",
            (context.run_id, *payload.paper_ids),
        ).fetchall()
        allowed_ids = {int(row["paper_id"]) for row in allowed if paper_is_accessible(conn, int(row["paper_id"]), context.user_id)}
        if allowed_ids != set(payload.paper_ids):
            raise ResearchNotFoundError("research paper not found")
        results = search_chunks(
            conn,
            payload.query,
            limit=payload.limit,
            paper_ids=payload.paper_ids,
            user_id=context.user_id,
        )
    items: list[ChunkSearchItem] = []
    for result in results:
        ref_id = f"chunk:{int(result['id'])}"
        context.search_refs.add(ref_id)
        items.append(
            ChunkSearchItem(
                ref_id=ref_id,
                paper_id=int(result["paper_id"]),
                paper_title=str(result["paper_title"]),
                heading=str(result["section_title"]),
                snippet=str(result["content"])[:420],
                score=float(result["score"]),
            )
        )
    return ChunkSearchOutput(items=items, count=len(items))


def _open_evidence(context: ToolContext, payload: OpenEvidenceInput) -> OpenEvidenceOutput:
    if payload.ref_id not in context.search_refs:
        raise ResearchStepError("evidence_not_whitelisted", "只能打开本步骤检索结果中的证据。")
    chunk_id = int(payload.ref_id.split(":", 1)[1])
    with connect() as conn:
        registered = register_opened_evidence(
            conn,
            run_id=context.run_id,
            step_id=context.step_id,
            worker_id=context.worker_id,
            lease_generation=context.lease_generation,
            user_id=context.user_id,
            chunk_id=chunk_id,
        )
    evidence = ChunkEvidenceRef(
        evidence_id=str(registered["id"]),
        chunk_id=chunk_id,
        paper_id=int(registered["paper_id"]),
        source_hash=str(registered["source_hash"]),
        chunk_index=int(registered["chunk_index"]),
        char_start=int(registered["char_start"]),
        char_end=int(registered["char_end"]),
        heading=str(registered["heading"]),
    )
    return OpenEvidenceOutput(evidence=evidence, excerpt=str(registered["content"])[: payload.max_chars])


def build_research_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    definitions: list[ToolDefinition[Any, Any]] = [
        ToolDefinition("local_paper_search", LocalSearchInput, LocalSearchOutput, "run_owner", True, 10, RetryPolicy(max_attempts=1, backoff_seconds=0), False, False, lambda output: f"本地检索返回 {output.count} 篇论文", ("tool_input_invalid", "tool_failed"), "typed allowlist; no raw SQL or paths", _local_search),
        ToolDefinition("arxiv_search", ArxivSearchInput, ArxivSearchOutput, "run_owner", True, 20, RetryPolicy(max_attempts=2, backoff_seconds=0.25, retryable_error_codes=("tool_temporarily_unavailable", "tool_timeout")), True, False, lambda output: f"arXiv 检索返回 {output.count} 篇候选", ("tool_temporarily_unavailable", "tool_timeout"), "stable network codes; provider body discarded", _arxiv_search),
        ToolDefinition("deduplicated_import", ImportPapersInput, ImportPapersOutput, "run_owner", True, 20, RetryPolicy(max_attempts=1, backoff_seconds=0), False, False, lambda output: f"导入 {output.imported_count} 篇，复用 {output.reused_count} 篇", ("untrusted_upload_identity", "tool_permission_or_state"), "trusted source identity only", _import_papers),
        ToolDefinition("fetch_document", PaperIdInput, FetchDocumentOutput, "paper_access", True, 30, RetryPolicy(max_attempts=1, backoff_seconds=0), True, False, lambda output: f"论文 PDF {'已复用' if output.reused else '已获取'}", ("document_fetch_failed", "tool_timeout"), "asset hash only; local path discarded", _fetch_document),
        ToolDefinition("parse_document", PaperIdInput, ParseDocumentOutput, "paper_access", True, 300, RetryPolicy(max_attempts=1, backoff_seconds=0), False, False, lambda output: f"论文正文 {'已复用' if output.reused else '已解析'}，{output.chunk_count} 个片段", ("document_parse_failed", "document_chunks_missing"), "Docling body/path discarded", _parse_document),
        ToolDefinition("chunk_search", ChunkSearchInput, ChunkSearchOutput, "paper_access", True, 15, RetryPolicy(max_attempts=1, backoff_seconds=0), False, False, lambda output: f"正文检索返回 {output.count} 条可打开证据", ("tool_permission_or_state",), "bounded snippets only", _chunk_search),
        ToolDefinition("open_evidence", OpenEvidenceInput, OpenEvidenceOutput, "paper_access", True, 10, RetryPolicy(max_attempts=1, backoff_seconds=0), False, False, lambda output: "已打开白名单内的正文证据", ("evidence_not_whitelisted",), "whitelisted current chunk only", _open_evidence),
    ]
    for definition in definitions:
        registry.register(definition)
    return registry

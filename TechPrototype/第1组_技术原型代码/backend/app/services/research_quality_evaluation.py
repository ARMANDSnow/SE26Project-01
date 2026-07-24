from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .llm import LLMClient, LLMConfigurationError, LLMServiceError


EVALUATOR_VERSION: Literal["research-quality-evaluator-v1"] = "research-quality-evaluator-v1"
PROMPT_VERSION: Literal["rag-entailment-judge-v1"] = "rag-entailment-judge-v1"
DATASET_VERSION: Literal["rag-citation-entailment-v1"] = "rag-citation-entailment-v1"

EntailmentLabel = Literal["supported", "contradicted", "insufficient"]
ArtifactKind = Literal[
    "research_report",
    "comparison_matrix",
    "topic_clusters",
    "research_timeline",
    "research_graph",
]
EvaluationStatus = Literal["not_evaluated", "passed", "below_threshold"]
EvaluationMode = Literal["validation", "prediction_file", "llm_judge"]

LABELS: tuple[EntailmentLabel, ...] = (
    "supported",
    "contradicted",
    "insufficient",
)
ARTIFACT_KINDS: tuple[ArtifactKind, ...] = (
    "research_report",
    "comparison_matrix",
    "topic_clusters",
    "research_timeline",
    "research_graph",
)


class EvaluationError(RuntimeError):
    """A sanitized, fail-closed evaluation error."""


class StrictEvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PublicPaperIdentity(StrictEvaluationModel):
    arxiv_id: str = Field(pattern=r"^\d{4}\.\d{4,5}$")
    title: str = Field(min_length=3, max_length=500)
    source_url: str = Field(pattern=r"^https://arxiv\.org/abs/\d{4}\.\d{4,5}$")
    published_date: str = Field(pattern=r"^20\d{2}-\d{2}-\d{2}$")


class EvidenceLocator(StrictEvaluationModel):
    section: str = Field(min_length=1, max_length=200)
    paragraph: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,79}$")


class GoldCase(StrictEvaluationModel):
    dataset_version: Literal["rag-citation-entailment-v1"]
    case_id: str = Field(pattern=r"^rag-v1-\d{3}$")
    paper: PublicPaperIdentity
    artifact_kind: ArtifactKind
    fact_statement: str = Field(min_length=8, max_length=1000)
    evidence: str = Field(min_length=8, max_length=1500)
    locator: EvidenceLocator
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_label: EntailmentLabel
    annotation_status: Literal["adjudicated", "draft"]
    annotation_notes: str = Field(min_length=3, max_length=1000)
    coverage_required: bool
    citation_present: bool
    deterministic_relation: bool

    @model_validator(mode="after")
    def validate_case_semantics(self) -> GoldCase:
        actual_hash = hashlib.sha256(self.evidence.encode("utf-8")).hexdigest()
        if actual_hash != self.evidence_sha256:
            raise ValueError("evidence_sha256 does not match evidence")
        if self.deterministic_relation and self.coverage_required:
            raise ValueError("deterministic relations cannot count as semantic citation coverage")
        return self


class Prediction(StrictEvaluationModel):
    case_id: str = Field(pattern=r"^rag-v1-\d{3}$")
    predicted_label: EntailmentLabel


class EntailmentJudgment(Prediction):
    schema_version: Literal[1]


class EvaluationMetadata(StrictEvaluationModel):
    dataset_version: Literal["rag-citation-entailment-v1"]
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluator_version: Literal["research-quality-evaluator-v1"]
    prompt_version: Literal["rag-entailment-judge-v1"]
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_identifier: str = Field(min_length=1, max_length=200)
    evaluation_mode: EvaluationMode
    judge_json_mode: bool | None
    judge_max_attempts: int | None = Field(default=None, ge=1, le=1)
    threshold: float = Field(ge=0.0, le=1.0)


class LabelMetrics(StrictEvaluationModel):
    precision: float
    recall: float
    f1: float
    support: int = Field(ge=0)


class CoverageMetrics(StrictEvaluationModel):
    eligible: int = Field(ge=0)
    cited: int = Field(ge=0)
    ratio: float
    deterministic_relations: int = Field(ge=0)


class ArtifactMetrics(StrictEvaluationModel):
    cases: int = Field(ge=0)
    accuracy: float | None
    macro_f1: float | None
    coverage: CoverageMetrics


class FailedCase(StrictEvaluationModel):
    case_id: str
    artifact_kind: ArtifactKind
    expected_label: EntailmentLabel
    predicted_label: EntailmentLabel


class EvaluationReport(StrictEvaluationModel):
    metadata: EvaluationMetadata
    status: EvaluationStatus
    status_text: str
    threshold_met: bool | None
    adjudicated_cases: int = Field(ge=0)
    paper_count: int = Field(ge=0)
    label_distribution: dict[str, int]
    confusion_matrix: dict[str, dict[str, int]] | None
    label_metrics: dict[str, LabelMetrics] | None
    accuracy: float | None
    macro_f1: float | None
    supported_precision: float | None
    false_accept_rate: float | None
    coverage: CoverageMetrics
    artifact_results: dict[str, ArtifactMetrics]
    failed_cases: list[FailedCase]
    predictions: list[Prediction]


class CompletionClient(Protocol):
    settings: Any

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
        *,
        timeout_seconds: float = 120,
        max_attempts: int = 3,
    ) -> str: ...


JUDGE_SYSTEM_PROMPT = (
    "You are a strict three-way entailment judge for public research-paper evidence. "
    "Classify whether the evidence supports, contradicts, or is insufficient for the exact "
    "fact statement. Do not use outside knowledge. Return exactly one JSON object and no "
    "markdown. The object must satisfy this JSON Schema: "
    + json.dumps(EntailmentJudgment.model_json_schema(), sort_keys=True, separators=(",", ":"))
)

_SENSITIVE_OUTPUT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)authorization\s*[:=]"),
    re.compile(r"(?i)bearer\s+[a-z0-9._-]{8,}"),
    re.compile(r"(?i)(?:api[_-]?key|llm_api_key)\s*[:=]"),
    re.compile(r"/(?:Users|home|private|var|tmp)/[^\s\"']+"),
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def dataset_sha256(cases: Sequence[GoldCase]) -> str:
    payload = [case.model_dump(mode="json") for case in sorted(cases, key=lambda item: item.case_id)]
    return _sha256_text(_canonical_json(payload))


def load_gold_cases(path: Path, *, enforce_release_rules: bool = True) -> list[GoldCase]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvaluationError("dataset_unreadable") from exc
    cases: list[GoldCase] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            cases.append(GoldCase.model_validate_json(line))
        except (ValidationError, ValueError) as exc:
            raise EvaluationError(f"dataset_invalid_line_{line_number}") from exc
    validate_gold_cases(cases, enforce_release_rules=enforce_release_rules)
    return cases


def validate_gold_cases(
    cases: Sequence[GoldCase], *, enforce_release_rules: bool = True
) -> None:
    if not cases:
        raise EvaluationError("dataset_empty")
    identifiers = [case.case_id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise EvaluationError("dataset_duplicate_case_id")
    adjudicated = [case for case in cases if case.annotation_status == "adjudicated"]
    if not enforce_release_rules:
        return
    if len(adjudicated) < 60:
        raise EvaluationError("dataset_requires_60_adjudicated_cases")
    paper_ids = {case.paper.arxiv_id for case in adjudicated}
    if len(paper_ids) < 5:
        raise EvaluationError("dataset_requires_5_public_papers")
    labels = Counter(case.expected_label for case in adjudicated)
    if any(labels[label] < 15 for label in LABELS):
        raise EvaluationError("dataset_label_distribution_insufficient")
    artifacts = Counter(case.artifact_kind for case in adjudicated)
    if any(artifacts[kind] < 8 for kind in ARTIFACT_KINDS):
        raise EvaluationError("dataset_artifact_distribution_insufficient")


def _parse_prediction_document(raw: str) -> list[Prediction]:
    stripped = raw.strip()
    if not stripped:
        raise EvaluationError("predictions_empty")
    if stripped.startswith("{"):
        try:
            document = json.loads(stripped)
        except json.JSONDecodeError:
            document = None
        if isinstance(document, dict) and isinstance(document.get("predictions"), list):
            raw_predictions = document["predictions"]
            try:
                return [Prediction.model_validate(item) for item in raw_predictions]
            except ValidationError as exc:
                raise EvaluationError("predictions_schema_invalid") from exc
        if document is not None:
            try:
                return [Prediction.model_validate(document)]
            except ValidationError as exc:
                raise EvaluationError("predictions_document_invalid") from exc
    predictions: list[Prediction] = []
    for line_number, line in enumerate(stripped.splitlines(), start=1):
        try:
            predictions.append(Prediction.model_validate_json(line))
        except ValidationError as exc:
            raise EvaluationError(f"predictions_invalid_line_{line_number}") from exc
    return predictions


def load_predictions(path: Path, cases: Sequence[GoldCase]) -> list[Prediction]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvaluationError("predictions_unreadable") from exc
    predictions = _parse_prediction_document(raw)
    validate_predictions(predictions, cases)
    return predictions


def validate_predictions(predictions: Sequence[Prediction], cases: Sequence[GoldCase]) -> None:
    prediction_ids = [item.case_id for item in predictions]
    if len(prediction_ids) != len(set(prediction_ids)):
        raise EvaluationError("predictions_duplicate_case_id")
    expected_ids = {
        case.case_id for case in cases if case.annotation_status == "adjudicated"
    }
    actual_ids = set(prediction_ids)
    if actual_ids - expected_ids:
        raise EvaluationError("predictions_unknown_case_id")
    if expected_ids - actual_ids:
        raise EvaluationError("predictions_missing_case_id")


def _safe_divide(numerator: float | int, denominator: float | int) -> float:
    return numerator / denominator if denominator else 0.0


def _coverage(cases: Sequence[GoldCase]) -> CoverageMetrics:
    eligible = [case for case in cases if case.coverage_required]
    cited = sum(1 for case in eligible if case.citation_present)
    deterministic = sum(1 for case in cases if case.deterministic_relation)
    return CoverageMetrics(
        eligible=len(eligible),
        cited=cited,
        ratio=_safe_divide(cited, len(eligible)),
        deterministic_relations=deterministic,
    )


def _score_subset(
    cases: Sequence[GoldCase], prediction_map: dict[str, EntailmentLabel]
) -> tuple[float, float]:
    if not cases:
        return 0.0, 0.0
    matrix: dict[str, dict[str, int]] = {
        expected: {predicted: 0 for predicted in LABELS}
        for expected in LABELS
    }
    for case in cases:
        matrix[case.expected_label][prediction_map[case.case_id]] += 1
    correct = sum(matrix[label][label] for label in LABELS)
    f1_values: list[float] = []
    for label in LABELS:
        true_positive = matrix[label][label]
        predicted_positive = sum(matrix[expected][label] for expected in LABELS)
        actual_positive = sum(matrix[label][predicted] for predicted in LABELS)
        precision = _safe_divide(true_positive, predicted_positive)
        recall = _safe_divide(true_positive, actual_positive)
        f1_values.append(
            0.0
            if precision + recall == 0
            else 2 * precision * recall / (precision + recall)
        )
    return _safe_divide(correct, len(cases)), sum(f1_values) / len(f1_values)


def score_predictions(
    cases: Sequence[GoldCase],
    predictions: Sequence[Prediction] | None,
    *,
    threshold: float,
    model_identifier: str,
    evaluation_mode: EvaluationMode | None = None,
    judge_json_mode: bool | None = None,
) -> EvaluationReport:
    if not 0.0 <= threshold <= 1.0:
        raise EvaluationError("threshold_out_of_range")
    adjudicated = [case for case in cases if case.annotation_status == "adjudicated"]
    resolved_mode: EvaluationMode = evaluation_mode or (
        "validation" if predictions is None else "prediction_file"
    )
    if predictions is None and resolved_mode != "validation":
        raise EvaluationError("evaluation_mode_invalid")
    if predictions is not None and resolved_mode == "validation":
        raise EvaluationError("evaluation_mode_invalid")
    metadata = EvaluationMetadata(
        dataset_version=DATASET_VERSION,
        dataset_sha256=dataset_sha256(cases),
        evaluator_version=EVALUATOR_VERSION,
        prompt_version=PROMPT_VERSION,
        prompt_sha256=_sha256_text(JUDGE_SYSTEM_PROMPT),
        model_identifier=model_identifier,
        evaluation_mode=resolved_mode,
        judge_json_mode=judge_json_mode if resolved_mode == "llm_judge" else None,
        judge_max_attempts=1 if resolved_mode == "llm_judge" else None,
        threshold=threshold,
    )
    overall_coverage = _coverage(adjudicated)
    label_distribution: dict[str, int] = dict(
        sorted(Counter(case.expected_label for case in adjudicated).items())
    )
    if predictions is None:
        validation_artifact_results: dict[str, ArtifactMetrics] = {
            kind: ArtifactMetrics(
                cases=len(subset := [case for case in adjudicated if case.artifact_kind == kind]),
                accuracy=None,
                macro_f1=None,
                coverage=_coverage(subset),
            )
            for kind in ARTIFACT_KINDS
        }
        return EvaluationReport(
            metadata=metadata,
            status="not_evaluated",
            status_text="未验证：仅完成数据集校验，未运行真实 judge 或提供 prediction。",
            threshold_met=None,
            adjudicated_cases=len(adjudicated),
            paper_count=len({case.paper.arxiv_id for case in adjudicated}),
            label_distribution=label_distribution,
            confusion_matrix=None,
            label_metrics=None,
            accuracy=None,
            macro_f1=None,
            supported_precision=None,
            false_accept_rate=None,
            coverage=overall_coverage,
            artifact_results=validation_artifact_results,
            failed_cases=[],
            predictions=[],
        )
    validate_predictions(predictions, cases)
    prediction_map: dict[str, EntailmentLabel] = {
        item.case_id: item.predicted_label for item in predictions
    }
    matrix: dict[str, dict[str, int]] = {
        expected: {predicted: 0 for predicted in LABELS}
        for expected in LABELS
    }
    failed_cases: list[FailedCase] = []
    for case in adjudicated:
        predicted = prediction_map[case.case_id]
        matrix[case.expected_label][predicted] += 1
        if predicted != case.expected_label:
            failed_cases.append(
                FailedCase(
                    case_id=case.case_id,
                    artifact_kind=case.artifact_kind,
                    expected_label=case.expected_label,
                    predicted_label=predicted,
                )
            )
    metrics: dict[str, LabelMetrics] = {}
    for label in LABELS:
        true_positive = matrix[label][label]
        predicted_positive = sum(matrix[expected][label] for expected in LABELS)
        actual_positive = sum(matrix[label][predicted] for predicted in LABELS)
        precision = _safe_divide(true_positive, predicted_positive)
        recall = _safe_divide(true_positive, actual_positive)
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        metrics[label] = LabelMetrics(
            precision=precision,
            recall=recall,
            f1=f1,
            support=actual_positive,
        )
    correct = sum(matrix[label][label] for label in LABELS)
    accuracy = _safe_divide(correct, len(adjudicated))
    macro_f1 = sum(item.f1 for item in metrics.values()) / len(LABELS)
    supported_precision = metrics["supported"].precision
    supported_predictions = sum(matrix[label]["supported"] for label in LABELS)
    false_accepts = supported_predictions - matrix["supported"]["supported"]
    false_accept_rate = _safe_divide(false_accepts, supported_predictions)
    artifact_results: dict[str, ArtifactMetrics] = {}
    for kind in ARTIFACT_KINDS:
        subset = [case for case in adjudicated if case.artifact_kind == kind]
        subset_accuracy, subset_macro_f1 = _score_subset(subset, prediction_map)
        artifact_results[kind] = ArtifactMetrics(
            cases=len(subset),
            accuracy=subset_accuracy,
            macro_f1=subset_macro_f1,
            coverage=_coverage(subset),
        )
    passed = (
        macro_f1 >= threshold
        and supported_precision >= threshold
        and overall_coverage.ratio >= threshold
    )
    if not passed:
        status: EvaluationStatus = "below_threshold"
        status_text = "未达标：至少一项固定 gold set 指标低于阈值。"
    elif resolved_mode == "llm_judge":
        status = "passed"
        status_text = "已达标：本次真实 judge 在固定 gold set 上的 macro-F1、supported precision 与 coverage 均达到阈值。"
    else:
        status = "not_evaluated"
        status_text = "未验证：prediction 文件指标达到阈值，但本次未运行真实 judge。"
    return EvaluationReport(
        metadata=metadata,
        status=status,
        status_text=status_text,
        threshold_met=passed,
        adjudicated_cases=len(adjudicated),
        paper_count=len({case.paper.arxiv_id for case in adjudicated}),
        label_distribution=label_distribution,
        confusion_matrix=matrix,
        label_metrics=metrics,
        accuracy=accuracy,
        macro_f1=macro_f1,
        supported_precision=supported_precision,
        false_accept_rate=false_accept_rate,
        coverage=overall_coverage,
        artifact_results=artifact_results,
        failed_cases=failed_cases,
        predictions=sorted(predictions, key=lambda item: item.case_id),
    )


def _contains_sensitive_output(raw: str) -> bool:
    return any(pattern.search(raw) for pattern in _SENSITIVE_OUTPUT_PATTERNS)


def generate_predictions(
    cases: Sequence[GoldCase], *, client: CompletionClient | None = None
) -> tuple[list[Prediction], str, bool]:
    judge = client or LLMClient()
    model_identifier = str(getattr(judge.settings, "llm_chat_model", "unknown-model"))
    json_mode = bool(getattr(judge.settings, "llm_json_response_format", True))
    predictions: list[Prediction] = []
    for case in cases:
        if case.annotation_status != "adjudicated":
            continue
        input_data = {
            "case_id": case.case_id,
            "fact_statement": case.fact_statement,
            "evidence": case.evidence,
            "locator": case.locator.model_dump(mode="json"),
        }
        try:
            raw = judge.complete(
                JUDGE_SYSTEM_PROMPT,
                _canonical_json(input_data),
                json_mode=json_mode,
                timeout_seconds=120,
                max_attempts=1,
            )
        except LLMConfigurationError as exc:
            raise EvaluationError("llm_configuration_unavailable") from exc
        except LLMServiceError as exc:
            raise EvaluationError("llm_provider_failure") from exc
        if _contains_sensitive_output(raw):
            raise EvaluationError("judge_sensitive_output_rejected")
        try:
            judgment = EntailmentJudgment.model_validate_json(raw)
        except ValidationError as exc:
            raise EvaluationError("judge_schema_invalid") from exc
        if judgment.case_id != case.case_id:
            raise EvaluationError("judge_case_id_mismatch")
        predictions.append(
            Prediction(case_id=judgment.case_id, predicted_label=judgment.predicted_label)
        )
    validate_predictions(predictions, cases)
    return predictions, model_identifier, json_mode


def render_markdown(report: EvaluationReport) -> str:
    def metric(value: float | None) -> str:
        return "—" if value is None else f"{value:.3f}"

    lines = [
        "# Research Quality Evaluation",
        "",
        f"**状态：{report.status_text}**",
        "",
        "## Provenance",
        "",
        f"- Dataset: `{report.metadata.dataset_version}` / `{report.metadata.dataset_sha256}`",
        f"- Evaluator: `{report.metadata.evaluator_version}`",
        f"- Prompt: `{report.metadata.prompt_version}` / `{report.metadata.prompt_sha256}`",
        f"- Model: `{report.metadata.model_identifier}`",
        f"- Evaluation mode: `{report.metadata.evaluation_mode}`",
        f"- Judge JSON mode: `{report.metadata.judge_json_mode if report.metadata.judge_json_mode is not None else 'n/a'}`",
        f"- Judge max attempts: `{report.metadata.judge_max_attempts if report.metadata.judge_max_attempts is not None else 'n/a'}`",
        f"- Threshold: `{report.metadata.threshold:.2f}`",
        "",
        "## Metrics",
        "",
        f"- Adjudicated cases: {report.adjudicated_cases}",
        f"- Public papers: {report.paper_count}",
        f"- Accuracy: {metric(report.accuracy)}",
        f"- Macro-F1: {metric(report.macro_f1)}",
        f"- Supported precision: {metric(report.supported_precision)}",
        f"- False-accept rate: {metric(report.false_accept_rate)}",
        f"- Citation coverage: {report.coverage.cited}/{report.coverage.eligible} ({report.coverage.ratio:.3f})",
        f"- Deterministic/publication relations (separate): {report.coverage.deterministic_relations}",
        "",
        "## Artifact results",
        "",
        "| Artifact | Cases | Accuracy | Macro-F1 | Coverage | Deterministic |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for kind in ARTIFACT_KINDS:
        item = report.artifact_results[kind]
        lines.append(
            f"| {kind} | {item.cases} | {metric(item.accuracy)} | {metric(item.macro_f1)} | "
            f"{item.coverage.ratio:.3f} | {item.coverage.deterministic_relations} |"
        )
    lines.extend(["", "## Failed cases", ""])
    if report.failed_cases:
        lines.extend(
            f"- `{item.case_id}` ({item.artifact_kind}): expected `{item.expected_label}`, got `{item.predicted_label}`"
            for item in report.failed_cases
        )
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def write_report(report: EvaluationReport, *, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")

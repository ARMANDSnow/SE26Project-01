from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.services.llm import LLMConfigurationError, LLMProviderError
from backend.app.services.research_quality_evaluation import (
    ARTIFACT_KINDS,
    EvaluationError,
    GoldCase,
    Prediction,
    generate_predictions,
    load_gold_cases,
    load_predictions,
    render_markdown,
    score_predictions,
    write_report,
)


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evaluation" / "gold" / "rag_citation_entailment_v1.jsonl"


def released_cases() -> list[GoldCase]:
    return load_gold_cases(DATASET)


def representative_cases() -> list[GoldCase]:
    cases = released_cases()
    return [cases[0], cases[4], cases[8]]


def test_released_gold_set_has_required_distribution_and_stable_hashes() -> None:
    cases = released_cases()

    assert len(cases) == 60
    assert len({case.case_id for case in cases}) == 60
    assert len({case.paper.arxiv_id for case in cases}) == 5
    assert {label: sum(case.expected_label == label for case in cases) for label in (
        "supported",
        "contradicted",
        "insufficient",
    )} == {"supported": 20, "contradicted": 20, "insufficient": 20}
    assert all(sum(case.artifact_kind == kind for case in cases) >= 10 for kind in ARTIFACT_KINDS)
    assert sum(case.coverage_required for case in cases) == 50
    assert sum(case.deterministic_relation for case in cases) == 10
    assert all(case.annotation_status == "adjudicated" for case in cases)


def test_gold_set_rejects_tampered_evidence(tmp_path: Path) -> None:
    first = json.loads(DATASET.read_text(encoding="utf-8").splitlines()[0])
    first["evidence"] += " tampered"
    path = tmp_path / "tampered.jsonl"
    path.write_text(json.dumps(first) + "\n", encoding="utf-8")

    with pytest.raises(EvaluationError, match="dataset_invalid_line_1"):
        load_gold_cases(path, enforce_release_rules=False)


@pytest.mark.parametrize(
    "mutation",
    [
        {"unexpected": "field"},
        {"locator": {"section": "", "paragraph": "abstract-evidence-summary"}},
        {"annotation_status": "drafting"},
    ],
)
def test_gold_set_rejects_unknown_fields_bad_locator_and_unknown_status(
    tmp_path: Path, mutation: dict[str, object]
) -> None:
    first = json.loads(DATASET.read_text(encoding="utf-8").splitlines()[0])
    first.update(mutation)
    path = tmp_path / "invalid.jsonl"
    path.write_text(json.dumps(first) + "\n", encoding="utf-8")

    with pytest.raises(EvaluationError, match="dataset_invalid_line_1"):
        load_gold_cases(path, enforce_release_rules=False)


def test_duplicate_gold_case_id_is_rejected(tmp_path: Path) -> None:
    first = DATASET.read_text(encoding="utf-8").splitlines()[0]
    path = tmp_path / "duplicate.jsonl"
    path.write_text(first + "\n" + first + "\n", encoding="utf-8")

    with pytest.raises(EvaluationError, match="dataset_duplicate_case_id"):
        load_gold_cases(path, enforce_release_rules=False)


def test_prediction_alignment_rejects_missing_duplicate_unknown_and_unknown_label(
    tmp_path: Path,
) -> None:
    cases = representative_cases()
    valid = [
        {"case_id": case.case_id, "predicted_label": case.expected_label}
        for case in cases
    ]
    variants = {
        "missing": valid[:-1],
        "duplicate": [*valid, valid[0]],
        "unknown": [*valid[:-1], {"case_id": "rag-v1-999", "predicted_label": "supported"}],
        "unknown_label": [*valid[:-1], {"case_id": valid[-1]["case_id"], "predicted_label": "maybe"}],
    }
    expected_errors = {
        "missing": "predictions_missing_case_id",
        "duplicate": "predictions_duplicate_case_id",
        "unknown": "predictions_unknown_case_id",
        "unknown_label": "predictions_invalid_line_3",
    }
    for name, rows in variants.items():
        path = tmp_path / f"{name}.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        with pytest.raises(EvaluationError, match=expected_errors[name]):
            load_predictions(path, cases)


def test_scorer_reports_confusion_false_accept_coverage_and_artifact_results() -> None:
    cases = representative_cases()
    predictions = [
        Prediction(case_id=case.case_id, predicted_label="supported") for case in cases
    ]

    report = score_predictions(
        cases,
        predictions,
        threshold=0.90,
        model_identifier="fixture-judge",
    )

    assert report.status == "below_threshold"
    assert report.confusion_matrix == {
        "supported": {"supported": 1, "contradicted": 0, "insufficient": 0},
        "contradicted": {"supported": 1, "contradicted": 0, "insufficient": 0},
        "insufficient": {"supported": 1, "contradicted": 0, "insufficient": 0},
    }
    assert report.supported_precision == pytest.approx(1 / 3)
    assert report.false_accept_rate == pytest.approx(2 / 3)
    assert report.coverage.eligible == 2
    assert report.coverage.deterministic_relations == 1
    assert set(report.artifact_results) == set(ARTIFACT_KINDS)
    assert [item.case_id for item in report.failed_cases] == [cases[1].case_id, cases[2].case_id]


def test_threshold_boundary_and_draft_exclusion() -> None:
    cases = representative_cases()
    draft = released_cases()[1].model_copy(update={"annotation_status": "draft"})
    scored_cases = [*cases, draft]
    predictions = [
        Prediction(case_id=case.case_id, predicted_label=case.expected_label)
        for case in cases
    ]

    report = score_predictions(
        scored_cases,
        predictions,
        threshold=1.0,
        model_identifier="perfect-fixture",
        evaluation_mode="llm_judge",
        judge_json_mode=True,
    )

    assert report.status == "passed"
    assert report.adjudicated_cases == 3
    assert report.macro_f1 == 1.0
    assert report.supported_precision == 1.0
    assert "已达标" in report.status_text


def test_prediction_file_cannot_claim_real_judge_threshold() -> None:
    cases = representative_cases()
    report = score_predictions(
        cases,
        [Prediction(case_id=case.case_id, predicted_label=case.expected_label) for case in cases],
        threshold=0.90,
        model_identifier="external-predictions",
        evaluation_mode="prediction_file",
    )

    assert report.threshold_met is True
    assert report.status == "not_evaluated"
    assert "未验证" in report.status_text


def test_validate_only_report_is_explicitly_unverified() -> None:
    report = score_predictions(
        representative_cases(),
        None,
        threshold=0.90,
        model_identifier="not-run",
    )

    assert report.status == "not_evaluated"
    assert report.macro_f1 is None
    assert "未验证" in report.status_text
    assert "未验证" in render_markdown(report)


def test_normalized_report_predictions_are_reproducible_input(tmp_path: Path) -> None:
    cases = representative_cases()
    predictions = [
        Prediction(case_id=case.case_id, predicted_label=case.expected_label)
        for case in cases
    ]
    report = score_predictions(
        cases,
        predictions,
        threshold=0.90,
        model_identifier="roundtrip-fixture",
    )
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    write_report(report, json_path=json_path, markdown_path=markdown_path)

    assert load_predictions(json_path, cases) == predictions
    serialized = json_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in serialized
    assert "roundtrip-fixture" in serialized
    assert report.metadata.dataset_sha256 in markdown_path.read_text(encoding="utf-8")


class FakeJudge:
    def __init__(self, *, result: str | Exception) -> None:
        self.settings = SimpleNamespace(
            llm_chat_model="fake-strict-judge",
            llm_json_response_format=False,
        )
        self.result = result
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
        *,
        timeout_seconds: float = 120,
        max_attempts: int = 3,
    ) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "json_mode": json_mode,
                "timeout_seconds": timeout_seconds,
                "max_attempts": max_attempts,
            }
        )
        if isinstance(self.result, Exception):
            raise self.result
        case_id = json.loads(user_prompt)["case_id"]
        return self.result.replace("CASE_ID", case_id)


def test_judge_uses_strict_schema_and_never_hides_retries() -> None:
    cases = [representative_cases()[0]]
    judge = FakeJudge(
        result='{"schema_version":1,"case_id":"CASE_ID","predicted_label":"supported"}'
    )

    predictions, model_identifier, json_mode = generate_predictions(cases, client=judge)

    assert predictions == [Prediction(case_id=cases[0].case_id, predicted_label="supported")]
    assert model_identifier == "fake-strict-judge"
    assert json_mode is False
    assert len(judge.calls) == 1
    assert judge.calls[0]["max_attempts"] == 1
    assert judge.calls[0]["json_mode"] is False


@pytest.mark.parametrize(
    ("result", "error"),
    [
        ('{"case_id":"CASE_ID","predicted_label":"supported"}', "judge_schema_invalid"),
        (
            '{"schema_version":1,"case_id":"CASE_ID","predicted_label":"supported","authorization":"Bearer secret-token"}',
            "judge_sensitive_output_rejected",
        ),
        (LLMConfigurationError("missing"), "llm_configuration_unavailable"),
        (LLMProviderError("provider_http_500"), "llm_provider_failure"),
    ],
)
def test_judge_fails_closed_for_schema_sensitive_config_and_provider_errors(
    result: str | Exception, error: str
) -> None:
    judge = FakeJudge(result=result)

    with pytest.raises(EvaluationError, match=error):
        generate_predictions([representative_cases()[0]], client=judge)

    assert len(judge.calls) == 1

from __future__ import annotations

import json
from typing import Any, Protocol, TypeVar

from pydantic import ValidationError

from .llm import LLMClient, LLMConfigurationError, LLMServiceError
from .research_contracts import (
    CandidatePaper,
    PaperBrief,
    ResearchBrief,
    ResearchStepError,
    ScreeningResult,
    SearchQueries,
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

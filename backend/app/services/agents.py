from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..repositories.papers import attach_concepts, get_paper_detail, get_paper_record, replace_wiki_sections
from .documents import get_paper_document, parse_paper_document
from .llm import LLMClient, LLMConfigurationError, LLMServiceError


class ReaderAgent:
    name = "ReaderAgent"

    def read(self, paper: dict[str, Any]) -> dict[str, str]:
        document = paper.get("document") or {}
        return {
            "title": paper["title"],
            "abstract": paper["abstract"],
            "authors": ", ".join(paper["authors"]),
            "categories": ", ".join(paper["categories"]),
            "content": str(document.get("content_markdown") or "")[:80_000],
        }


class SummaryAgent:
    name = "SummaryAgent"

    def summarize(self, reading: dict[str, str]) -> tuple[dict[str, str], list[dict[str, Any]]]:
        return self._summarize_with_llm(LLMClient(), reading)

    def _summarize_with_llm(
        self,
        client: LLMClient,
        reading: dict[str, str],
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        prompt = (
            "请阅读下面的论文正文，生成可沉淀到论文 Wiki 的结构化 JSON。"
            "只返回 JSON，不要返回 Markdown 代码块。JSON schema: "
            '{"sections":{"summary":"# 摘要\\n\\n...","concepts":"# 核心概念\\n\\n...",'
            '"methods":"# 方法\\n\\n...","experiments":"# 实验结论\\n\\n..."},'
            '"concepts":[{"name":"概念名","description":"解释","relation":"关系","weight":0.8}]}'
            f"\n\n标题：{reading['title']}\n作者：{reading['authors']}\n分类：{reading['categories']}"
            f"\n摘要：{reading['abstract']}\n\n已解析正文：\n{reading['content']}"
        )
        try:
            payload = _parse_json_object(
                client.complete(
                    "你是科研论文阅读助手。必须输出可解析 JSON，并确保内容可追溯到给定论文正文。",
                    prompt,
                    json_mode=True,
                )
            )
        except LLMConfigurationError:
            raise
        except (LLMServiceError, ValueError, json.JSONDecodeError) as exc:
            raise LLMServiceError(f"无法生成有效的论文 Wiki：{exc}") from exc
        sections = payload.get("sections", {})
        concepts = payload.get("concepts", [])
        if not isinstance(sections, dict) or not isinstance(concepts, list):
            raise LLMServiceError("LLM 返回的 JSON 不符合 Wiki schema")
        normalized_sections = {
            key: str(sections.get(key, "")).strip()
            for key in ValidatorAgent.required_sections
        }
        normalized_concepts = [
            {
                "name": str(item.get("name", "")).strip(),
                "description": str(item.get("description", "")).strip(),
                "relation": str(item.get("relation", "涉及")).strip() or "涉及",
                "weight": _safe_weight(item.get("weight", 1.0)),
            }
            for item in concepts
            if isinstance(item, dict)
        ]
        return normalized_sections, normalized_concepts


class ValidatorAgent:
    name = "ValidatorAgent"
    required_sections = {"summary", "concepts", "methods", "experiments"}

    def validate(self, sections: dict[str, str], concepts: list[dict[str, Any]]) -> list[str]:
        errors: list[str] = []
        missing = self.required_sections.difference(sections)
        if missing:
            errors.append("缺少 Wiki 分区：" + "、".join(sorted(missing)))
        for section, content in sections.items():
            if len(content.strip()) < 40:
                errors.append(f"{section} 内容过短")
        if not [concept for concept in concepts if concept.get("name", "").strip()]:
            errors.append("至少需要一个概念")
        return errors


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM 输出不是 JSON 对象")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM 输出不是 JSON 对象")
    return payload


def _safe_weight(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 1.0


def process_paper(conn: sqlite3.Connection, paper_id: int, user_id: int = 1) -> dict[str, Any]:
    paper = get_paper_detail(conn, paper_id, user_id=user_id)
    if paper is None:
        raise ValueError("paper not found")
    try:
        record = get_paper_record(conn, paper_id)
        document = get_paper_document(conn, paper_id)
        expected_hash = str(record.asset_id).removeprefix("sha256:") if record and record.asset_id else None
        if (
            document is None
            or document.get("status") != "completed"
            or document.get("source_hash") != expected_hash
        ):
            parse_paper_document(conn, paper_id, user_id=user_id)
            paper = get_paper_detail(conn, paper_id, user_id=user_id)
            if paper is None:
                raise ValueError("paper not found")
        reading = ReaderAgent().read(paper)
        if not reading["content"].strip():
            raise LLMServiceError("论文正文解析结果为空")
        sections, concepts = SummaryAgent().summarize(reading)
    except (LLMConfigurationError, LLMServiceError, RuntimeError):
        conn.execute("UPDATE papers SET processing_status = 'failed' WHERE id = ?", (paper_id,))
        conn.commit()
        raise
    errors = ValidatorAgent().validate(sections, concepts)
    if errors:
        conn.execute("UPDATE papers SET processing_status = 'failed' WHERE id = ?", (paper_id,))
        conn.commit()
        return {"status": "failed", "errors": errors, "agents": ["ReaderAgent", "SummaryAgent", "ValidatorAgent"]}
    replace_wiki_sections(conn, paper_id, sections, commit=False)
    attach_concepts(conn, paper_id, concepts, commit=False)
    conn.execute("UPDATE papers SET processing_status = 'processed' WHERE id = ?", (paper_id,))
    conn.execute(
        "INSERT INTO reading_history (user_id, paper_id, action) VALUES (?, ?, ?)",
        (user_id, paper_id, "完成结构化解析"),
    )
    conn.commit()
    return {
        "status": "processed",
        "agents": ["ReaderAgent", "SummaryAgent", "ValidatorAgent"],
        "paper": get_paper_detail(conn, paper_id, user_id=user_id),
    }

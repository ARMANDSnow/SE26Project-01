from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..database import attach_concepts, get_paper_detail, replace_wiki_sections
from .llm import LLMClient


class ReaderAgent:
    name = "ReaderAgent"

    def read(self, paper: dict[str, Any]) -> dict[str, str]:
        return {
            "title": paper["title"],
            "abstract": paper["abstract"],
            "authors": "、".join(paper["authors"]),
            "categories": "、".join(paper["categories"]),
        }


class SummaryAgent:
    name = "SummaryAgent"

    def summarize(self, reading: dict[str, str]) -> tuple[dict[str, str], list[dict[str, Any]]]:
        client = LLMClient()
        if not client.settings.should_use_mock_llm:
            return self._summarize_with_llm(client, reading)
        return self._summarize_with_rules(reading)

    def _summarize_with_rules(self, reading: dict[str, str]) -> tuple[dict[str, str], list[dict[str, Any]]]:
        title = reading["title"]
        abstract = reading["abstract"]
        words = [item for item in title.replace("：", " ").replace(":", " ").split(" ") if item]
        concept_a = words[0] if words else "Paper Understanding"
        concept_b = reading["categories"].split("、")[0] if reading["categories"] else "cs.AI"
        method = "结构化论文解析"
        if "RAG" in title or "检索" in title:
            method = "retrieval-augmented generation"
        elif "图" in title or "Graph" in title:
            method = "knowledge graph"
        elif "Agent" in title or "智能体" in title:
            method = "multi-agent workflow"
        sections = {
            "summary": (
                f"# 摘要\n\n{title} 关注的研究问题是如何从论文内容中抽象稳定知识。"
                f"论文摘要指出：{abstract[:260]}。MVP 将其沉淀为可检索 Wiki，并保留 arXiv 来源。"
            ),
            "concepts": (
                "# 核心概念\n\n"
                f"- {concept_a}：论文标题和摘要中最突出的研究主题。\n"
                f"- {concept_b}：arXiv 学科分类，用于主题聚合。\n"
                f"- Evidence Grounding：问答时必须返回论文出处和相关片段。"
            ),
            "methods": (
                "# 方法\n\n"
                f"系统将论文元数据和摘要输入阅读流水线，经 ReaderAgent 清洗后由 SummaryAgent 生成 Wiki。"
                f"方法标签暂定为 {method}，并通过概念边与相似论文连接。"
            ),
            "experiments": (
                "# 实验结论\n\n"
                "MVP 阶段使用摘要和结构化片段替代完整 PDF 实验表格抽取。"
                "校验重点是答案可追溯、概念抽取稳定和检索响应时间。"
            ),
        }
        concepts = [
            {"name": concept_a, "description": "从论文标题中抽取的主题概念", "relation": "主题", "weight": 0.95},
            {"name": concept_b, "description": "arXiv 学科分类", "relation": "研究方向", "weight": 0.82},
            {"name": "Evidence Grounding", "description": "答案绑定论文出处和片段", "relation": "问答约束", "weight": 0.76},
            {"name": method, "description": "论文处理或建模方法", "relation": "方法", "weight": 0.72},
        ]
        return sections, concepts

    def _summarize_with_llm(
        self,
        client: LLMClient,
        reading: dict[str, str],
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        prompt = (
            "请阅读下面的 arXiv 论文元数据和摘要，生成可沉淀到论文 Wiki 的结构化 JSON。"
            "只返回 JSON，不要返回 Markdown 代码块。JSON schema: "
            '{"sections":{"summary":"# 摘要\\n\\n...","concepts":"# 核心概念\\n\\n...",'
            '"methods":"# 方法\\n\\n...","experiments":"# 实验结论\\n\\n..."},'
            '"concepts":[{"name":"概念名","description":"解释","relation":"关系","weight":0.8}]}。'
            f"\n\n标题：{reading['title']}\n作者：{reading['authors']}\n分类：{reading['categories']}\n摘要：{reading['abstract']}"
        )
        try:
            raw = client.complete(
                "你是科研论文阅读助手，必须输出可解析 JSON，并确保每个 Wiki 分区内容可追溯到论文摘要。",
                prompt,
            )
            payload = _parse_json_object(raw)
        except Exception:
            return {}, []
        sections = payload.get("sections", {})
        concepts = payload.get("concepts", [])
        if not isinstance(sections, dict) or not isinstance(concepts, list):
            return {}, []
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
        raise ValueError("LLM output is not a JSON object")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM output is not a JSON object")
    return payload


def _safe_weight(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 1.0


def process_paper(conn: sqlite3.Connection, paper_id: int) -> dict[str, Any]:
    paper = get_paper_detail(conn, paper_id)
    if paper is None:
        raise ValueError("paper not found")
    reading = ReaderAgent().read(paper)
    sections, concepts = SummaryAgent().summarize(reading)
    errors = ValidatorAgent().validate(sections, concepts)
    if errors:
        conn.execute("UPDATE papers SET processing_status = 'failed' WHERE id = ?", (paper_id,))
        conn.commit()
        return {"status": "failed", "errors": errors, "agents": ["ReaderAgent", "SummaryAgent", "ValidatorAgent"]}
    replace_wiki_sections(conn, paper_id, sections, commit=False)
    attach_concepts(conn, paper_id, concepts, commit=False)
    conn.execute("UPDATE papers SET processing_status = 'processed' WHERE id = ?", (paper_id,))
    conn.execute("INSERT INTO reading_history (paper_id, action) VALUES (?, ?)", (paper_id, "完成结构化解析"))
    conn.commit()
    return {
        "status": "processed",
        "agents": ["ReaderAgent", "SummaryAgent", "ValidatorAgent"],
        "paper": get_paper_detail(conn, paper_id),
    }

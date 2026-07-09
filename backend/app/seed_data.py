from __future__ import annotations

from datetime import date, timedelta
import sqlite3

from .database import attach_concepts, replace_paper_chunks, replace_wiki_sections, row_to_paper, upsert_paper
from .services.fulltext import chunk_document, metadata_document


THEMES = [
    ("大语言模型检索增强", "RAG", "retrieval-augmented generation", "cs.CL"),
    ("多智能体论文阅读", "Multi-Agent", "agent collaboration", "cs.AI"),
    ("长上下文推理", "Long Context", "context compression", "cs.CL"),
    ("图神经网络知识表示", "Graph Neural Network", "knowledge graph", "cs.LG"),
    ("医学影像迁移学习", "Domain Adaptation", "clinical AI", "cs.CV"),
    ("强化学习安全校验", "Safe RL", "policy verification", "cs.AI"),
    ("代码生成评测", "Code LLM", "program synthesis", "cs.SE"),
    ("多模态表征学习", "Multimodal Learning", "vision-language", "cs.CV"),
    ("联邦学习隐私保护", "Federated Learning", "privacy preserving", "cs.LG"),
    ("因果发现与科学假设", "Causal Discovery", "scientific discovery", "cs.AI"),
]


def seed_database(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS count FROM papers").fetchone()["count"]
    if count >= 100:
        seed_missing_metadata_chunks(conn)
        return

    base_day = date(2025, 1, 3)
    for index in range(100):
        theme, concept, method, category = THEMES[index % len(THEMES)]
        variant = index // len(THEMES) + 1
        arxiv_id = f"25{variant:02d}.{index + 1000:05d}"
        title = f"{theme}的结构化学习框架 {variant}"
        authors = [
            f"Chen {chr(65 + index % 20)}.",
            f"Wang {chr(65 + (index + 4) % 20)}.",
            f"Li {chr(65 + (index + 8) % 20)}.",
        ]
        published = base_day + timedelta(days=index * 3)
        abstract = (
            f"本文研究{theme}在科研论文学习场景中的应用，围绕{concept}、{method}和知识沉淀展开。"
            f"方法包含元数据检索、结构化摘要、概念关联和带出处问答，并在公开论文集合上验证检索准确率、"
            f"答案可追溯性和学习效率。实验结果显示，该框架能帮助用户快速定位研究问题、方法路线和代表性结论。"
        )
        paper_id = upsert_paper(
            conn,
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "categories": [category, "cs.IR" if index % 3 == 0 else "cs.AI"],
                "primary_category": category,
                "published_at": published.isoformat(),
                "updated_at": (published + timedelta(days=2)).isoformat(),
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
                "doi": f"10.48550/arXiv.{arxiv_id}",
                "processing_status": "processed" if index < 60 else "pending",
                "reading_status": "reading" if index % 7 == 0 else "unread",
                "is_favorite": index % 9 == 0,
            },
        )
        if index < 60:
            sections = {
                "summary": (
                    f"# 摘要\n\n这篇论文聚焦{theme}，核心问题是如何把{concept}转化为可检索、可追溯的论文知识。"
                    f"作者提出以{method}为中心的处理流程，将论文元数据、摘要、方法和实验结论沉淀为 Wiki。"
                ),
                "concepts": (
                    f"# 核心概念\n\n- {concept}：用于组织论文知识的核心标签。\n"
                    f"- {method}：论文采用的主要技术路线。\n"
                    "- Evidence Grounding：问答答案需要绑定到论文片段与来源。"
                ),
                "methods": (
                    "# 方法\n\n系统先抓取 arXiv 元数据，再抽取摘要、研究问题、方法和实验结论。"
                    f"随后使用{method}构建检索索引，并通过概念边连接相关论文。"
                ),
                "experiments": (
                    "# 实验结论\n\n实验关注检索召回、答案出处完整性和用户阅读效率。"
                    "结果表明结构化 Wiki 能减少重复阅读，并提升跨论文比较的速度。"
                ),
            }
            replace_wiki_sections(conn, paper_id, sections)
            attach_concepts(
                conn,
                paper_id,
                [
                    {"name": concept, "description": f"{theme}中的关键研究对象", "relation": "核心概念", "weight": 1.0},
                    {"name": method, "description": "论文采用或比较的主要方法", "relation": "方法", "weight": 0.86},
                    {"name": "Evidence Grounding", "description": "将答案绑定到出处和片段", "relation": "评测维度", "weight": 0.74},
                ],
            )
        if index in (0, 9, 18):
            conn.execute(
                "INSERT INTO notes (paper_id, note, comment) VALUES (?, ?, ?)",
                (paper_id, f"重点关注{concept}和实验设置。", "适合放入研究脉络对比。"),
            )
        if index in (0, 1, 2, 12, 24):
            conn.execute(
                "INSERT INTO reading_history (paper_id, action) VALUES (?, ?)",
                (paper_id, "阅读论文详情"),
            )

    for topic in ["大语言模型", "RAG", "多智能体", "知识图谱"]:
        conn.execute("INSERT OR IGNORE INTO subscriptions (topic) VALUES (?)", (topic,))
    seed_missing_metadata_chunks(conn)
    conn.commit()


def seed_missing_metadata_chunks(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT p.*
        FROM papers p
        LEFT JOIN paper_chunks pc ON pc.paper_id = p.id
        WHERE p.processing_status = 'processed'
        GROUP BY p.id
        HAVING COUNT(pc.id) = 0
        """
    ).fetchall()
    for row in rows:
        paper = row_to_paper(row)
        replace_paper_chunks(conn, paper["id"], chunk_document(metadata_document(paper)), commit=False)
    if rows:
        conn.commit()

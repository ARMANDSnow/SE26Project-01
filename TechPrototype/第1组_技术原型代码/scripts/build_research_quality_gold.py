#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evaluation" / "gold" / "rag_citation_entailment_v1.jsonl"
ARTIFACTS = (
    "research_timeline",
    "research_graph",
    "research_report",
    "comparison_matrix",
    "topic_clusters",
    "research_timeline",
    "research_graph",
    "research_report",
    "comparison_matrix",
    "topic_clusters",
    "research_timeline",
    "research_graph",
)


@dataclass(frozen=True)
class PaperSpec:
    arxiv_id: str
    title: str
    published_date: str
    evidence: str
    supported: tuple[str, str, str, str]
    contradicted: tuple[str, str, str, str]
    insufficient: tuple[str, str, str, str]


PAPERS = (
    PaperSpec(
        arxiv_id="2309.15217",
        title="RAGAS: Automated Evaluation of Retrieval Augmented Generation",
        published_date="2023-09-26",
        evidence=(
            "Curator summary of the arXiv abstract: RAGAS introduces reference-free evaluation "
            "for RAG pipelines, covering retrieval focus, faithful evidence use, and answer quality."
        ),
        supported=(
            "RAGAS was first submitted to arXiv in 2023.",
            "The gold-set corpus includes the public paper RAGAS under arXiv identity 2309.15217.",
            "RAGAS proposes reference-free evaluation for retrieval-augmented generation pipelines.",
            "Its evaluation dimensions include retrieval quality and faithful use of retrieved evidence.",
        ),
        contradicted=(
            "RAGAS requires a human-written reference answer for every evaluation example.",
            "RAGAS evaluates only serving latency and ignores answer quality.",
            "The framework deliberately excludes assessment of retrieved context.",
            "RAGAS is presented as a recursive tree-indexing algorithm for document retrieval.",
        ),
        insufficient=(
            "RAGAS was trained on exactly ten million biomedical documents.",
            "The paper proves a thirty-percent accuracy gain on every evaluated dataset.",
            "The abstract specifies that the implementation is released under Apache 2.0.",
            "RAGAS requires Redis as its evaluation result store.",
        ),
    ),
    PaperSpec(
        arxiv_id="2310.11511",
        title="Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
        published_date="2023-10-17",
        evidence=(
            "Curator summary of the arXiv abstract: Self-RAG retrieves on demand and uses reflection "
            "tokens to critique generations; the paper studies 7B and 13B models."
        ),
        supported=(
            "Self-RAG was first submitted to arXiv in 2023.",
            "The gold-set corpus includes Self-RAG under public arXiv identity 2310.11511.",
            "Self-RAG makes retrieval adaptive rather than retrieving a fixed number of passages every time.",
            "The paper uses reflection tokens to let the model critique retrieval and generation behavior.",
        ),
        contradicted=(
            "Self-RAG always retrieves exactly five passages for every generated sentence.",
            "Self-RAG removes all self-critique signals from generation.",
            "The paper evaluates only a proprietary 70B model and no smaller model.",
            "Self-RAG is described as a database transaction scheduler rather than a language-model method.",
        ),
        insufficient=(
            "Self-RAG uses a specific commercial vector database for every experiment.",
            "The abstract reports that training required exactly 128 GPUs for fourteen days.",
            "The paper guarantees zero hallucinations in medical deployments.",
            "Self-RAG's source code is stated to use the GPLv3 license.",
        ),
    ),
    PaperSpec(
        arxiv_id="2401.15884",
        title="Corrective Retrieval Augmented Generation",
        published_date="2024-01-29",
        evidence=(
            "Curator summary of the arXiv abstract: CRAG adds a lightweight retrieval evaluator, "
            "chooses corrective retrieval actions, can extend retrieval with web search, and filters knowledge."
        ),
        supported=(
            "Corrective Retrieval Augmented Generation was first submitted to arXiv in 2024.",
            "The gold-set corpus includes CRAG under public arXiv identity 2401.15884.",
            "CRAG uses a lightweight evaluator to estimate the quality of retrieved documents.",
            "CRAG can trigger corrective retrieval actions and extend retrieval with web search.",
        ),
        contradicted=(
            "CRAG assumes retrieved documents are always correct and performs no quality assessment.",
            "CRAG forbids any external retrieval action when local evidence is weak.",
            "The method retains every retrieved sentence without filtering or recomposition.",
            "CRAG is evaluated as a computer-vision object detector rather than a RAG method.",
        ),
        insufficient=(
            "CRAG's web-search component is implemented exclusively with one named search provider.",
            "The abstract states an exact monthly production cost for corrective retrieval.",
            "CRAG guarantees compliance with every national privacy regulation.",
            "The authors report a ten-year longitudinal user study.",
        ),
    ),
    PaperSpec(
        arxiv_id="2401.18059",
        title="RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval",
        published_date="2024-01-31",
        evidence=(
            "Curator summary of the arXiv abstract: RAPTOR recursively embeds, clusters, and "
            "summarizes text into a tree so retrieval can operate across multiple abstraction levels."
        ),
        supported=(
            "RAPTOR was first submitted to arXiv in 2024.",
            "The gold-set corpus includes RAPTOR under public arXiv identity 2401.18059.",
            "RAPTOR builds a tree through recursive embedding, clustering, and summarization.",
            "Its retrieval design can select information at different levels of abstraction.",
        ),
        contradicted=(
            "RAPTOR represents every document only as one flat, unsummarized chunk list.",
            "RAPTOR prohibits retrieval from higher-level summaries.",
            "The method does not use clustering at any stage of index construction.",
            "RAPTOR is introduced as a citation-style formatter with no retrieval component.",
        ),
        insufficient=(
            "RAPTOR's tree always has exactly seven levels for every corpus.",
            "The abstract mandates a particular proprietary embedding API.",
            "RAPTOR was deployed to one million daily enterprise users before publication.",
            "The paper reports a fixed carbon cost per generated summary node.",
        ),
    ),
    PaperSpec(
        arxiv_id="2408.08067",
        title="RAGChecker: A Fine-grained Framework for Diagnosing Retrieval-Augmented Generation",
        published_date="2024-08-15",
        evidence=(
            "Curator summary of the arXiv abstract: RAGChecker provides claim-level diagnostic "
            "metrics for retrieval and generation, compares eight RAG systems, and checks human correlation."
        ),
        supported=(
            "RAGChecker was first submitted to arXiv in 2024.",
            "The gold-set corpus includes RAGChecker under public arXiv identity 2408.08067.",
            "RAGChecker diagnoses both the retrieval and generation components of RAG systems.",
            "The reported evaluation compares eight RAG systems and examines correlation with human judgments.",
        ),
        contradicted=(
            "RAGChecker reports only one aggregate score and offers no component-level diagnosis.",
            "RAGChecker evaluates generation while explicitly ignoring retrieval behavior.",
            "The study compares exactly two RAG systems rather than eight.",
            "The framework avoids any comparison with human judgments.",
        ),
        insufficient=(
            "RAGChecker requires a specific GPU model to calculate every metric.",
            "The paper states that all evaluated systems use an identical proprietary retriever.",
            "RAGChecker guarantees perfect agreement with human reviewers.",
            "The abstract provides a fixed service-level objective for production deployments.",
        ),
    ),
)


def build_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    case_number = 1
    for paper in PAPERS:
        statements = (
            *(("supported", statement) for statement in paper.supported),
            *(("contradicted", statement) for statement in paper.contradicted),
            *(("insufficient", statement) for statement in paper.insufficient),
        )
        for index, (label, statement) in enumerate(statements):
            deterministic = index < 2
            cases.append(
                {
                    "dataset_version": "rag-citation-entailment-v1",
                    "case_id": f"rag-v1-{case_number:03d}",
                    "paper": {
                        "arxiv_id": paper.arxiv_id,
                        "title": paper.title,
                        "source_url": f"https://arxiv.org/abs/{paper.arxiv_id}",
                        "published_date": paper.published_date,
                    },
                    "artifact_kind": ARTIFACTS[index],
                    "fact_statement": statement,
                    "evidence": paper.evidence,
                    "locator": {
                        "section": "arXiv abstract metadata and curator summary",
                        "paragraph": "abstract-evidence-summary",
                    },
                    "evidence_sha256": hashlib.sha256(paper.evidence.encode("utf-8")).hexdigest(),
                    "expected_label": label,
                    "annotation_status": "adjudicated",
                    "annotation_notes": (
                        "Curator-reviewed against the cited public arXiv abstract metadata; "
                        "the label applies only to the exact statement and supplied evidence."
                    ),
                    "coverage_required": not deterministic,
                    "citation_present": True,
                    "deterministic_relation": deterministic,
                }
            )
            case_number += 1
    return cases


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True) for case in build_cases()
    )
    OUTPUT.write_text(payload + "\n", encoding="utf-8")
    print(f"wrote {len(build_cases())} cases to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

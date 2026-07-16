from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.config import get_settings
from backend.app.database import connect
from backend.app.main import app
from backend.app.services.research_agents import GraphValidationAgent
from backend.app.services.research_contracts import (
    ProjectCoverageSummary,
    ResearchGraph,
    ResearchGraphEdge,
    ResearchGraphNode,
    ResearchStepError,
    ResearchTimeline,
    TimelineDateRange,
    TimelineEvent,
    TimelinePeriod,
    TopicCluster,
    TopicClusters,
)
from backend.tests.fixtures import populate_test_library


@pytest.fixture()
def project_api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "project-api.sqlite3"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.post(
            "/api/auth/register",
            json={"username": "project_owner", "password": "test-password"},
        ).status_code == 201
        with connect() as conn:
            paper_ids = populate_test_library(conn)
        yield client, paper_ids
    get_settings.cache_clear()


def test_project_contracts_require_citations_for_factual_cluster_and_semantic_edges() -> None:
    with pytest.raises(ValidationError, match="summary_citation_keys"):
        TopicCluster.model_validate(
            {
                "cluster_id": "cluster-1",
                "label": "Grounded retrieval",
                "summary": "The papers share a retrieval method.",
                "summary_citation_keys": [],
                "paper_ids": [1],
                "claim_ids": [],
                "citation_keys": [],
                "distinguishing_features": [],
                "uncertainties": [],
                "schema_version": 1,
            }
        )

    with pytest.raises(ValidationError, match="semantic graph edge requires citations"):
        ResearchGraphEdge(
            edge_id="edge-1",
            source_node_id="paper:1",
            target_node_id="cluster:1",
            relation_type="belongs_to_cluster",
            citation_keys=[],
        )


def test_timeline_separates_metadata_publication_from_semantic_evolution() -> None:
    publication = TimelineEvent(
        event_id="publication-1",
        date="2025-01-01",
        event_type="publication",
        title="Paper published",
        description="Authoritative paper metadata publication date.",
        paper_ids=[1],
        claim_ids=[],
        citation_keys=[],
        confidence=1.0,
    )
    timeline = ResearchTimeline(
        events=[publication],
        periods=[],
        turning_points=[],
        unresolved_questions=[],
        citation_keys=[],
    )
    assert timeline.events[0].event_type == "publication"

    with pytest.raises(ValidationError, match="semantic timeline event requires citations"):
        TimelineEvent(
            event_id="influence-1",
            date="2025-02-01",
            event_type="improvement",
            title="Improved method",
            description="The later work improved the earlier method.",
            paper_ids=[1, 2],
            claim_ids=["claim:1"],
            citation_keys=[],
            confidence=0.8,
        )
    with pytest.raises(ValidationError, match="at least 1 item"):
        TimelinePeriod(
            period_id="period-1",
            date_range=TimelineDateRange(start="2025-01-01", end="2025-12-31"),
            title="Uncited period",
            description="A free-text factual period is not accepted.",
            event_ids=["publication-1"],
            citation_keys=[],
        )


def test_graph_validation_rejects_model_ids_and_cross_scope_citations() -> None:
    clusters = TopicClusters(
        clusters=[
            TopicCluster(
                cluster_id="cluster-1",
                label="Grounding",
                summary="Grounded summary",
                summary_citation_keys=["PC1"],
                paper_ids=[1],
                claim_ids=["claim:1"],
                citation_keys=["PC1"],
                distinguishing_features=[],
                uncertainties=[],
            )
        ],
        unclassified_paper_ids=[],
        uncertainties=[],
        citation_keys=["PC1"],
    )
    timeline = ResearchTimeline(
        events=[
            TimelineEvent(
                event_id="publication-1",
                date="2025-01-01",
                event_type="publication",
                title="Published",
                description="Metadata date",
                paper_ids=[1],
                claim_ids=[],
                citation_keys=[],
                confidence=1.0,
            )
        ],
        periods=[],
        turning_points=[],
        unresolved_questions=[],
        citation_keys=[],
    )
    graph = ResearchGraph(
        nodes=[
            ResearchGraphNode(
                node_id="paper:1",
                node_type="paper",
                label="Allowed paper",
                entity_ref="paper:1",
            ),
            ResearchGraphNode(
                node_id="model:invented",
                node_type="paper",
                label="Invented paper",
                entity_ref="paper:999",
            ),
        ],
        edges=[],
        citation_keys=[],
    )
    with pytest.raises(ResearchStepError) as exc_info:
        GraphValidationAgent.validate(
            graph,
            allowed_node_ids={"paper:1"},
            allowed_citation_keys={"PC1"},
            allowed_paper_ids={1},
            allowed_claim_ids={"claim:1"},
            clusters=clusters,
            timeline=timeline,
            coverage_summary=ProjectCoverageSummary(
                accessible_item_count=1,
                paper_count=1,
                report_count=0,
                valid_citation_count=1,
                limited=False,
            ),
        )
    assert exc_info.value.code == "project_graph_node_invalid"


def test_project_api_partial_update_item_dto_reorder_coverage_and_owner_isolation(
    project_api_client,
) -> None:
    client, paper_ids = project_api_client
    created = client.post(
        "/api/research/projects",
        json={"title": "Traceable RAG", "description": "Initial"},
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    partial = client.patch(
        f"/api/research/projects/{project_id}",
        json={"description": "Updated only"},
    )
    assert partial.status_code == 200
    assert partial.json()["title"] == "Traceable RAG"
    assert partial.json()["description"] == "Updated only"

    first = client.post(
        f"/api/research/projects/{project_id}/items",
        json={"item_type": "paper", "paper_id": paper_ids[0]},
    )
    second = client.post(
        f"/api/research/projects/{project_id}/items",
        json={"item_type": "paper", "paper_id": paper_ids[1]},
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["dependency_status"] == "current"
    assert first.json()["title"]
    reordered = client.post(
        f"/api/research/projects/{project_id}/items/reorder",
        json={"item_ids": [second.json()["id"], first.json()["id"]]},
    )
    assert reordered.status_code == 200
    assert [item["id"] for item in reordered.json()["items"]] == [
        second.json()["id"],
        first.json()["id"],
    ]

    coverage = client.get(f"/api/research/projects/{project_id}/coverage")
    assert coverage.status_code == 200
    assert coverage.headers["cache-control"] == "private, no-store"
    assert coverage.json()["status"] == "limited"
    assert coverage.json()["paper_count"] == 2
    assert coverage.json()["valid_citation_count"] == 0
    assert coverage.json()["can_analyze"] is True

    no_analysis = client.get(f"/api/research/projects/{project_id}/analysis")
    assert no_analysis.status_code == 200
    assert no_analysis.json() == {
        "project_id": project_id,
        "run": None,
        "tool_summaries": [],
    }
    started = client.post(f"/api/research/projects/{project_id}/analysis")
    assert started.status_code == 202
    assert started.json()["run"]["mode"] == "project"
    assert len(started.json()["run"]["steps"]) == 7
    waiting_run = None
    for _ in range(100):
        snapshot = client.get(f"/api/research/projects/{project_id}/analysis").json()["run"]
        if snapshot["status"] == "waiting_input":
            waiting_run = snapshot
            break
        time.sleep(0.01)
    assert waiting_run is not None
    decision = next(item for item in waiting_run["decisions"] if item["status"] == "pending")
    assert {item["id"] for item in decision["options"]} >= {
        "add_more_sources",
        "generate_limited",
        "deterministic_timeline",
        "stop",
    }
    resolved = client.post(
        f"/api/research/decisions/{decision['id']}/resolve",
        json={"option_id": "deterministic_timeline"},
    )
    assert resolved.status_code == 200
    completed_run = None
    for _ in range(200):
        snapshot = client.get(f"/api/research/projects/{project_id}/analysis").json()["run"]
        if snapshot["status"] in {"completed", "failed"}:
            completed_run = snapshot
            break
        time.sleep(0.01)
    assert completed_run is not None
    assert completed_run["status"] == "completed", completed_run.get("error_message")
    timeline = client.get(
        f"/api/research/projects/{project_id}/artifacts/research_timeline"
    )
    graph = client.get(f"/api/research/projects/{project_id}/artifacts/research_graph")
    assert timeline.status_code == graph.status_code == 200
    assert len(timeline.json()["content"]["events"]) == 2
    assert any(edge["relation_type"] == "precedes" for edge in graph.json()["content"]["edges"])

    assert client.post("/api/auth/logout").status_code == 200
    assert client.post(
        "/api/auth/register",
        json={"username": "different_owner", "password": "test-password"},
    ).status_code == 201
    hidden = client.get(f"/api/research/projects/{project_id}")
    assert hidden.status_code == 404
    assert hidden.headers["cache-control"] == "private, no-store"

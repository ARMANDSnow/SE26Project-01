import json
import sqlite3

from backend.app.database import init_schema
from backend.app.seed_data import seed_database
from backend.app.services.paper_tools import PaperToolbox, ToolInputError
from backend.app.services.qa_agent import run_qa_agent


def seeded_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    seed_database(conn)
    return conn


class ScriptedToolCallingLLM:
    def __init__(self) -> None:
        self.turn = 0

    def chat(self, messages, tools=None, tool_choice=None):
        self.turn += 1
        if self.turn == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "search-1",
                        "type": "function",
                        "function": {"name": "search_text", "arguments": json.dumps({"query": "RAG Evidence Grounding", "limit": 10})},
                    }
                ],
            }
        if self.turn == 2:
            search_payload = json.loads(messages[-1]["content"])
            selected = []
            seen_papers = set()
            for item in search_payload["items"]:
                if item["paper_id"] in seen_papers:
                    continue
                seen_papers.add(item["paper_id"])
                selected.append(item)
                if len(selected) == 2:
                    break
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"open-{index}",
                        "type": "function",
                        "function": {"name": "open_evidence", "arguments": json.dumps({"ref_id": item["ref_id"]})},
                    }
                    for index, item in enumerate(selected, start=1)
                ],
            }
        return {
            "role": "assistant",
            "content": json.dumps(
                {
                    "answer": "两篇论文都强调可追溯证据 [E1][E2]。",
                    "citation_ids": ["E1", "E2"],
                    "confidence": 0.82,
                },
                ensure_ascii=False,
            ),
        }


def test_real_agent_state_machine_opens_cross_paper_evidence_and_filters_citations():
    conn = seeded_db()
    result = run_qa_agent(conn, "比较 RAG 的证据策略", client=ScriptedToolCallingLLM())

    assert result["execution"]["mode"] == "agentic_real"
    assert result["execution"]["status"] == "completed"
    assert result["execution"]["tool_call_count"] == 3
    assert len({item["paper_id"] for item in result["citations"]}) == 2
    assert [item["evidence_id"] for item in result["citations"]] == ["E1", "E2"]


def test_mock_agent_runs_search_open_answer_without_network():
    conn = seeded_db()
    result = run_qa_agent(conn, "RAG Evidence Grounding")

    assert result["execution"]["mode"] == "agentic_mock"
    assert result["execution"]["tool_call_count"] >= 2
    assert len({item["paper_id"] for item in result["citations"]}) >= 2
    assert all(item.get("evidence_id", "").startswith("E") for item in result["citations"])


def test_toolbox_rejects_out_of_scope_and_unsearched_evidence():
    conn = seeded_db()
    paper_ids = [row["id"] for row in conn.execute("SELECT id FROM papers ORDER BY id LIMIT 2").fetchall()]
    toolbox = PaperToolbox(conn, [paper_ids[0]])

    empty_scope = toolbox.search_text("RAG", paper_ids=[])
    assert empty_scope == {"items": [], "count": 0}

    try:
        toolbox.search_text("RAG", paper_ids=[paper_ids[1]])
    except ToolInputError as exc:
        assert str(exc) == "paper_out_of_scope"
    else:
        raise AssertionError("out-of-scope search must fail")

    try:
        toolbox.open_evidence("chunk:999999")
    except ToolInputError as exc:
        assert str(exc) == "ref_not_in_search_results"
    else:
        raise AssertionError("unsearched evidence must fail")

    assert toolbox.citations([]) == []


class PrematureAnswerLLM:
    def chat(self, messages, tools=None, tool_choice=None):
        return {"role": "assistant", "content": '{"answer":"猜测","citation_ids":[],"confidence":0.9}'}


def test_agent_refuses_answer_when_model_never_opens_evidence():
    conn = seeded_db()
    result = run_qa_agent(conn, "没有检索就回答", client=PrematureAnswerLLM())

    assert result["execution"]["status"] == "failed"
    assert result["execution"]["stop_reason"] == "no_opened_evidence"
    assert result["citations"] == []


class InvalidCitationLLM(ScriptedToolCallingLLM):
    def chat(self, messages, tools=None, tool_choice=None):
        if self.turn < 2:
            return super().chat(messages, tools, tool_choice)
        self.turn += 1
        return {
            "role": "assistant",
            "content": json.dumps(
                {"answer": "伪造引用 [E999]", "citation_ids": ["E999"], "confidence": 0.99},
                ensure_ascii=False,
            ),
        }


def test_invalid_answer_citation_triggers_grounded_fallback():
    conn = seeded_db()
    result = run_qa_agent(conn, "比较 RAG", client=InvalidCitationLLM())

    assert result["execution"]["status"] == "fallback"
    assert result["execution"]["stop_reason"] == "citation_validation_fallback"
    assert "E999" not in result["answer"]
    assert result["citations"]


class FourCallsLLM:
    def __init__(self):
        self.turn = 0
        self.selected = []

    def chat(self, messages, tools=None, tool_choice=None):
        self.turn += 1
        if self.turn == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "search",
                        "type": "function",
                        "function": {"name": "search_text", "arguments": '{"query":"RAG","limit":8}'},
                    }
                ],
            }
        if self.turn == 2:
            payload = json.loads(messages[-1]["content"])
            self.selected = payload["items"][:4]
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"open-{index}",
                        "type": "function",
                        "function": {"name": "open_evidence", "arguments": json.dumps({"ref_id": item["ref_id"]})},
                    }
                    for index, item in enumerate(self.selected, start=1)
                ],
            }
        tool_responses = [item for item in messages if item.get("role") == "tool" and item.get("tool_call_id", "").startswith("open-")]
        assert [item["tool_call_id"] for item in tool_responses] == ["open-1", "open-2", "open-3", "open-4"]
        assert json.loads(tool_responses[-1]["content"])["error"] == "tool_budget_exceeded"
        return {
            "role": "assistant",
            "content": json.dumps(
                {
                    "answer": "已完成引用 [E1][E2][E3]。",
                    "citation_ids": ["E1", "E2", "E3"],
                    "confidence": 0.7,
                },
                ensure_ascii=False,
            ),
        }


def test_per_turn_budget_pairs_every_declared_tool_call_before_finalizing():
    conn = seeded_db()
    result = run_qa_agent(conn, "RAG", client=FourCallsLLM())

    assert result["execution"]["status"] == "completed"
    assert result["execution"]["tool_call_count"] == 4
    assert len(result["citations"]) == 3

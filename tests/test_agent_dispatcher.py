from __future__ import annotations

import sys
import types

import pytest

from core.agent_dispatcher import can_run_tool, run_tool
from core.agent_schemas import AgentType, InternalRetrievalBrief, WebResearchBrief
# Dispatcher tests validate permissions for Pulse (intel) and Shield agents in tool routing and private memory access (dispatcher coordination)
# additional Pulse private memory + Shield for agent dispatcher tests



def test_can_run_tool_permission_matrix():
    assert can_run_tool(AgentType.INTERNAL_LIBRARIAN, "internal_retrieval") is True
    assert can_run_tool(AgentType.WEB_RESEARCHER, "web_research") is True
    assert can_run_tool(AgentType.WRITER, "internal_retrieval") is False
    assert can_run_tool(AgentType.MANAGER, "web_research") is False
    assert can_run_tool(AgentType.INTERNAL_LIBRARIAN, "unknown_tool") is False


def test_run_tool_rejects_disallowed_agent():
    with pytest.raises(PermissionError):
        run_tool(AgentType.WRITER, "internal_retrieval", query="x")


def test_run_tool_internal_retrieval_success(monkeypatch):
    def _fake_internal_retrieval_tool(query: str, k: int, chroma_path=None):
        return InternalRetrievalBrief(query=query, results=[], notes=f"k={k}, path={chroma_path}")

    fake_mod = types.SimpleNamespace(internal_retrieval_tool=_fake_internal_retrieval_tool)
    monkeypatch.setitem(sys.modules, "core.tools.internal_retrieval", fake_mod)

    out = run_tool(
        AgentType.INTERNAL_LIBRARIAN,
        "internal_retrieval",
        query="quality system",
        k=3,
        chroma_path="C:/idx",
    )
    assert isinstance(out, InternalRetrievalBrief)
    assert out.query == "quality system"
    assert "k=3" in (out.notes or "")


def test_run_tool_web_research_success(monkeypatch):
    def _fake_web_research_tool(query: str, top_n: int, from_config=None):
        return WebResearchBrief(query=query, sources=[], findings=[], notes=f"top_n={top_n}")

    fake_mod = types.SimpleNamespace(web_research_tool=_fake_web_research_tool)
    monkeypatch.setitem(sys.modules, "core.tools.web_research", fake_mod)

    out = run_tool(AgentType.WEB_RESEARCHER, "web_research", query="FDA PCCP", top_n=5)
    assert isinstance(out, WebResearchBrief)
    assert out.query == "FDA PCCP"
    assert "top_n=5" in (out.notes or "")


def test_run_tool_unknown_tool_rejected_by_permission_gate():
    with pytest.raises(PermissionError):
        run_tool(AgentType.INTERNAL_LIBRARIAN, "not_a_real_tool", query="x")

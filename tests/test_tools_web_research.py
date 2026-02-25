from __future__ import annotations

from core.tools.web_research import _extract_urls, web_research_tool


def test_extract_urls_deduplicates_and_preserves_order():
    text = "See https://a.com and https://b.com and https://a.com again."
    urls = _extract_urls(text)
    assert urls == ["https://a.com", "https://b.com"]


def test_web_research_tool_returns_failure_brief_on_exception(monkeypatch):
    def _boom(system_prompt, user_prompt):
        raise RuntimeError("network down")

    monkeypatch.setattr("core.llm_collab.call_chatgpt_simple", _boom)
    out = web_research_tool(query="FDA SaMD")
    assert out.sources == []
    assert out.findings == []
    assert "failed" in (out.notes or "").lower()


def test_web_research_tool_parses_urls_and_builds_finding(monkeypatch):
    payload = (
        "Source one https://example.com/a says X. "
        "Source two https://example.org/b says Y."
    )
    monkeypatch.setattr("core.llm_collab.call_chatgpt_simple", lambda s, u: payload)

    out = web_research_tool(query="clinical evidence", top_n=1)
    assert len(out.sources) == 1
    assert out.sources[0].url == "https://example.com/a"
    assert len(out.findings) == 1
    assert payload in out.findings[0].claim
    assert out.findings[0].supporting_sources[:2] == ["https://example.com/a", "https://example.org/b"]

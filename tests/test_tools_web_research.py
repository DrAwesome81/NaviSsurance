from __future__ import annotations

from core.tools.web_research import _extract_urls, web_research_tool
# Web research tool tests support Pulse private memory and 🛡️ Shield regulatory research (web research tests)


def test_extract_urls_deduplicates_and_preserves_order():
    text = "See https://a.com and https://b.com and https://a.com again."
    urls = _extract_urls(text)
    assert urls == ["https://a.com", "https://b.com"]


def test_web_research_tool_returns_failure_brief_on_exception(monkeypatch):
    def _boom_web(system_prompt, user_prompt, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("core.llm_collab.call_chatgpt_web_search", _boom_web)
    monkeypatch.setattr("core.llm_collab.call_chatgpt_simple", _boom_web)
    out = web_research_tool(query="FDA SaMD", max_rounds=1)
    assert out.sources == []
    assert out.findings == []
    assert "failed" in (out.notes or "").lower()


def test_web_research_tool_parses_urls_and_builds_finding(monkeypatch):
    payload = "Source one says X. Source two says Y."
    monkeypatch.setattr(
        "core.llm_collab.call_chatgpt_web_search",
        lambda s, u, **kwargs: (
            payload,
            [
                {"url": "https://example.com/a", "title": "A"},
                {"url": "https://example.org/b", "title": "B"},
            ],
        ),
    )

    out = web_research_tool(query="clinical evidence", top_n=1, max_rounds=1)
    assert len(out.sources) == 1
    assert out.sources[0].url == "https://example.com/a"
    assert len(out.findings) == 1
    assert payload in out.findings[0].claim
    assert out.findings[0].supporting_sources[:2] == ["https://example.com/a", "https://example.org/b"]


def test_web_research_tool_stops_after_two_rounds_without_new_sources(monkeypatch):
    calls = {"n": 0}

    def _fake_web_search(system, user, **kwargs):
        calls["n"] += 1
        return (
            f"Round {calls['n']} text",
            [
                {"url": "https://example.com/a", "title": "A"},
                {"url": "https://example.org/b", "title": "B"},
            ],
        )

    monkeypatch.setattr("core.llm_collab.call_chatgpt_web_search", _fake_web_search)

    msgs: list[str] = []
    out = web_research_tool(
        query="device validation",
        top_n=10,
        progress_callback=msgs.append,
        max_rounds=5,
        timebox_seconds=999,
    )

    # Round 1 adds sources; rounds 2 and 3 add none; then stop.
    assert len(out.findings) == 3
    assert any("no new sources in 2 rounds" in m.lower() for m in msgs)

# additional Pulse private memory + Shield for web research tests

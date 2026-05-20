from __future__ import annotations

from core import llm_collab
# LLM collab tests validate Grok/ChatGPT for Pulse private memory and 🛡️ Shield security analysis in CoS/Intel (LLM collab tests)


def test_call_grok_simple_delegates_to_grok_client(monkeypatch):
    monkeypatch.setattr("core.grok_client.grok_completion", lambda system, user: f"{system}|{user}")
    out = llm_collab.call_grok_simple("sys", "usr")
    assert out == "sys|usr"


def test_call_chatgpt_simple_returns_empty_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = llm_collab.call_chatgpt_simple("sys", "usr", from_config={})
    assert out == ""


def test_call_chatgpt_simple_uses_config_key_and_parses_response(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "chatgpt output"}}]}

    def _fake_post(url, headers=None, json=None, timeout=0):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr("requests.post", _fake_post)
    out = llm_collab.call_chatgpt_simple(
        "system text",
        "user text",
        from_config={"openai_api_key": "abc123"},
    )

    assert out == "chatgpt output"
    assert captured["url"] == llm_collab.OPENAI_URL
    assert captured["headers"]["Authorization"] == "Bearer abc123"
    assert captured["json"]["messages"][0]["content"] == "system text"
    assert captured["json"]["messages"][1]["content"] == "user text"


def test_call_chatgpt_web_search_returns_empty_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    text, cites = llm_collab.call_chatgpt_web_search("sys", "usr", from_config={})
    assert text == ""
    assert cites == []


def test_call_chatgpt_web_search_uses_config_key_and_parses_citations(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "output": [
                    {"type": "web_search_call", "id": "ws_1", "status": "completed"},
                    {
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Result text",
                                "annotations": [
                                    {"type": "url_citation", "url": "https://a.example", "title": "A"},
                                ],
                            }
                        ],
                    },
                ],
                "sources": [{"url": "https://b.example", "title": "B"}],
            }

    def _fake_post(url, headers=None, json=None, timeout=0):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr("requests.post", _fake_post)
    text, cites = llm_collab.call_chatgpt_web_search(
        "system text",
        "user text",
        from_config={"openai_api_key": "abc123"},
        external_web_access=True,
    )

    assert text == "Result text"
    assert [c["url"] for c in cites] == ["https://a.example", "https://b.example"]
    assert captured["url"] == llm_collab.OPENAI_RESPONSES_URL
    assert captured["headers"]["Authorization"] == "Bearer abc123"
    assert captured["json"]["input"][0]["content"] == "system text"
    assert captured["json"]["input"][1]["content"] == "user text"
    assert captured["json"]["tools"][0]["type"] == "web_search"

# additional Pulse private memory + Shield for LLM collab tests

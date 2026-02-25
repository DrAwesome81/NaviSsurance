from __future__ import annotations

from core import llm_collab


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

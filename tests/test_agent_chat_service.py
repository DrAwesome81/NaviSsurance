from __future__ import annotations

import json

from core import agent_chat_service as svc


class _DbStub:
    def __init__(self):
        self.touch_calls: list[tuple[int, bool]] = []

    def agent_get(self, code: str):
        if code == "atlas":
            return {"code": "atlas", "display_name": "Atlas", "role_title": "Deep Researcher"}
        return None

    def agent_resolve_by_name(self, name: str):
        if str(name).strip().lower() == "atlas":
            return {"code": "atlas", "display_name": "Atlas", "role_title": "Deep Researcher"}
        return None

    def agent_get_assignment(self, assignment_id: int):
        if assignment_id != 7:
            return None
        return {
            "id": 7,
            "title": "Regulatory synthesis",
            "status": "in_progress",
            "requester_code": "navi",
            "assignee_code": "atlas",
            "priority": 2,
            "due_date": "2026-03-01",
            "brief_md": "Summarize key changes.",
        }

    def agent_list_artifacts(self, assignment_id: int, limit: int = 5):
        if assignment_id != 7:
            return []
        return [
            {
                "title": "Prior summary",
                "artifact_type": "agent_reply",
                "content_md": "A" * 300,
                "content_json": "",
            }
        ]

    def agent_get_thread(self, thread_id: int):
        if thread_id != 9:
            return None
        ctx = {"project": "NaviSsurance", "focus": "CoS automation"}
        return (9, "atlas", "Thread", "session", json.dumps(ctx), "", "", "")

    def agent_touch_thread(self, thread_id: int, bump_last_message: bool = False):
        self.touch_calls.append((int(thread_id), bool(bump_last_message)))


def test_coerce_history_accepts_only_valid_user_assistant_pairs():
    hist = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "system", "content": "drop"},
        ("user", "tuple works"),
        ("assistant", "tuple reply"),
        ("tool", "drop"),
        {"role": "user", "content": ""},
    ]
    out = svc._coerce_history(hist)
    assert out == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "tuple works"},
        {"role": "assistant", "content": "tuple reply"},
    ]


def test_format_assignment_context_includes_truncated_artifact_snippet():
    text = svc._format_assignment_context(_DbStub(), 7)
    assert "Assignment context:" in text
    assert "Recent linked artifacts:" in text
    assert "Prior summary" in text
    assert "..." in text  # truncation marker


def test_format_thread_context_handles_json_payload():
    text = svc._format_thread_context(_DbStub(), 9)
    assert text.startswith("Thread context:")
    assert "NaviSsurance" in text


def test_system_prompt_for_unknown_agent_uses_default_base():
    prompt = svc._system_prompt_for("unknown", display_name="X", role_title="Y")
    assert "You are X (Y)." in prompt
    assert "specialist assistant" in prompt.lower()
    assert "Do not invent source facts." in prompt


def test_agent_chat_response_unknown_agent_returns_error():
    out = svc.agent_chat_response(_DbStub(), agent_code="missing", user_message="hello")
    assert "Unknown agent" in out


def test_agent_chat_response_unavailable_when_grok_missing(monkeypatch):
    monkeypatch.setattr(svc, "grok_available", lambda: (False, "API key not configured"))
    out = svc.agent_chat_response(_DbStub(), agent_code="atlas", user_message="hello")
    assert "unavailable" in out
    assert "API key not configured" in out


def test_agent_chat_response_builds_messages_and_dedupes_last_user(monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(svc, "grok_available", lambda: (True, "ok"))

    def _fake_completion(messages, model):
        captured["messages"] = messages
        captured["model"] = model
        return "done"

    monkeypatch.setattr(svc, "grok_completion_messages", _fake_completion)

    db = _DbStub()
    out = svc.agent_chat_response(
        db,
        agent_code="atlas",
        user_message="Same user turn",
        conversation_history=[
            {"role": "assistant", "content": "prior"},
            {"role": "user", "content": "Same user turn"},
        ],
        thread_id=9,
        assignment_id=7,
    )

    assert out == "done"
    msgs = captured["messages"]
    # Includes base system prompt + reference context block.
    assert msgs[0]["role"] == "system"
    assert any(m["role"] == "system" and "Reference context" in m["content"] for m in msgs)
    # User turn should appear once (deduped against history tail).
    assert [m for m in msgs if m["role"] == "user" and m["content"] == "Same user turn"].__len__() == 1
    # Touch thread side-effect runs after response.
    assert db.touch_calls == [(9, True)]


def test_agent_chat_response_empty_output_uses_fallback(monkeypatch):
    monkeypatch.setattr(svc, "grok_available", lambda: (True, "ok"))
    monkeypatch.setattr(svc, "grok_completion_messages", lambda messages, model: "   ")
    out = svc.agent_chat_response(_DbStub(), agent_code="atlas", user_message="hello")
    assert "no output right now" in out.lower()


def test_agent_chat_response_includes_runtime_context(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(svc, "grok_available", lambda: (True, "ok"))

    def _fake_completion(messages, model):
        captured["messages"] = messages
        return "done"

    monkeypatch.setattr(svc, "grok_completion_messages", _fake_completion)

    out = svc.agent_chat_response(
        _DbStub(),
        agent_code="atlas",
        user_message="Please revise",
        runtime_context="Current draft: hello world",
    )

    assert out == "done"
    assert any(
        m["role"] == "system" and "Runtime context:" in m["content"] and "hello world" in m["content"]
        for m in captured["messages"]
    )

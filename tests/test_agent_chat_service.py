from __future__ import annotations

import json

from core import agent_chat_service as svc


class _DbStub:
    def __init__(self):
        self.touch_calls: list[tuple[int, bool]] = []
        self.saved_messages: list[tuple[str, str, str]] = []
        self.link_calls: list[tuple[int, int, str | None, str | None]] = []
        self.created_threads: list[dict] = []

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
            if thread_id == 12:
                ctx = {"source": "chief_of_staff_assign", "assignment_id": 7}
                return (12, "atlas", "A-0007: Regulatory synthesis", "session-12", json.dumps(ctx), "", "", "")
            return None
        ctx = {"project": "NaviSsurance", "focus": "CoS automation"}
        return (9, "atlas", "Thread", "session", json.dumps(ctx), "", "", "")

    def agent_touch_thread(self, thread_id: int, bump_last_message: bool = False):
        self.touch_calls.append((int(thread_id), bool(bump_last_message)))

    def agent_create_thread(self, *, agent_code: str, title: str | None = None, context_json=None, session_id=None):
        self.created_threads.append(
            {
                "agent_code": agent_code,
                "title": title,
                "context_json": context_json,
                "session_id": session_id,
            }
        )
        return 12

    def agent_link_assignment_thread(
        self,
        *,
        assignment_id: int,
        thread_id: int,
        actor_code: str | None = None,
        note: str | None = None,
    ):
        self.link_calls.append((int(assignment_id), int(thread_id), actor_code, note))
        return True

    def save_message(self, session_id, role, content):
        self.saved_messages.append((str(session_id), str(role), str(content)))

    def get_chat_history(self, session_id="main_session", limit=50):
        rows = [(role, content) for sid, role, content in self.saved_messages if sid == session_id]
        return rows[-int(limit):]


def test_coerce_history_accepts_only_valid_user_assistant_pairs():
    hist = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "navi", "content": "kickoff"},
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
        {"role": "user", "content": "kickoff"},
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


def test_create_assignment_thread_links_thread_with_assignment_context():
    db = _DbStub()
    tid = svc.create_assignment_thread(
        db,
        assignment_id=7,
        assignee_code="atlas",
        reason="chief_of_staff_assign",
        actor_code="navi",
        context_json={"source": "chief_of_staff_assign", "cos_chat_id": 5},
    )

    assert tid == 12
    assert db.created_threads[0]["agent_code"] == "atlas"
    assert db.created_threads[0]["title"].startswith("A-0007:")
    assert db.created_threads[0]["context_json"]["assignment_id"] == 7
    assert db.link_calls == [
        (7, 12, "navi", "Linked to atlas thread after chief of staff assign")
    ]


def test_prime_assignment_handoff_seeds_navi_and_agent_messages(monkeypatch):
    db = _DbStub()
    monkeypatch.setattr(
        svc,
        "agent_chat_response",
        lambda *args, **kwargs: "I can start now. Please upload the source packet and answer two scope questions.",
    )

    reply = svc.prime_assignment_handoff(db, assignment_id=7, thread_id=12)

    assert "Please upload the source packet" in reply
    history = db.get_chat_history("session-12", limit=10)
    assert len(history) == 2
    assert history[0][0] == "navi"
    assert "Assignment kickoff from Navi" in history[0][1]
    assert history[1][0] == "assistant"
    assert "scope questions" in history[1][1]

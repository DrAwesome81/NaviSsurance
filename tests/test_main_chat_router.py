from types import SimpleNamespace

from core.main_chat_router import (
    LOCAL_FAST_UNSUPPORTED,
    _build_local_fast_messages,
    is_dashboard_chat_session,
    run_main_chat_turn,
    select_main_chat_route_details,
    select_main_chat_route,
)


class _FakeDB:
    def __init__(self, dashboard_chat_id=7):
        self._dashboard_chat_id = dashboard_chat_id
        self.updated_chat_ids = []
        self.user_memory_rows = []
        self.user_memory_added = []

    def get_setting(self, key, default=None):
        if key == "cos_dashboard_chat_id":
            return str(self._dashboard_chat_id)
        return default

    def cos_update_chat(self, chat_id):
        self.updated_chat_ids.append(int(chat_id))

    def user_memory_add(self, *, kind, content, source="unknown", confidence=1.0, approval_status="approved", json_data=None, entity_refs=None):
        payload = dict(json_data or {}) if isinstance(json_data, dict) else json_data
        if isinstance(payload, dict) and entity_refs is not None:
            payload["entity_refs"] = entity_refs
        row = (len(self.user_memory_added) + 1, kind, content, source, confidence, approval_status, payload, "now", "now")
        self.user_memory_added.append(row)
        self.user_memory_rows.insert(0, row)
        return row[0]

    def user_memory_add_many(self, *, items):
        added = 0
        for item in items:
            self.user_memory_add(**item)
            added += 1
        return added

    def user_memory_search(self, *, query, kind=None, source=None, approval_status=None, limit=10):
        matches = [row for row in self.user_memory_rows if query.lower() in str(row[2]).lower()]
        if kind is not None:
            matches = [row for row in matches if row[1] == kind]
        if source is not None:
            matches = [row for row in matches if row[3] == source]
        if approval_status is not None:
            matches = [row for row in matches if row[5] == approval_status]
        return matches[:limit]

    def user_memory_recent(self, *, kind=None, source=None, approval_status=None, limit=20):
        rows = list(self.user_memory_rows)
        if kind is not None:
            rows = [row for row in rows if row[1] == kind]
        if source is not None:
            rows = [row for row in rows if row[3] == source]
        if approval_status is not None:
            rows = [row for row in rows if row[5] == approval_status]
        return rows[:limit]


class _FakeHandler:
    def __init__(self, db):
        self.db = db
        self.saved = []

    def save_message(self, session_id, role, content):
        self.saved.append((session_id, role, content))


def test_is_dashboard_chat_session_matches_saved_dashboard_chat_id():
    db = _FakeDB(dashboard_chat_id=7)
    assert is_dashboard_chat_session(db, "cos_7")
    assert is_dashboard_chat_session(db, "main_session")
    assert not is_dashboard_chat_session(db, "cos_8")


def test_select_main_chat_route_prefers_local_for_self_contained_rewrite():
    db = _FakeDB(dashboard_chat_id=7)
    route = select_main_chat_route(
        db,
        "Rewrite this client note into three concise bullets.",
        "cos_7",
        [("assistant", "Previous reply")],
    )
    assert route == "local_fast"


def test_select_main_chat_route_details_reports_reason_for_local_fast():
    db = _FakeDB(dashboard_chat_id=7)
    route, reason = select_main_chat_route_details(
        db,
        "Rewrite this client note into three concise bullets.",
        "cos_7",
        [("assistant", "Previous reply")],
    )
    assert route == "local_fast"
    assert reason == "self_contained_text_turn"


def test_select_main_chat_route_keeps_cos_for_work_state_question():
    db = _FakeDB(dashboard_chat_id=7)
    route = select_main_chat_route(
        db,
        "What should I focus on today?",
        "cos_7",
        [("assistant", "Previous reply")],
    )
    assert route == "cos"


def test_select_main_chat_route_details_reports_reason_for_non_dashboard_cos():
    db = _FakeDB(dashboard_chat_id=7)
    route, reason = select_main_chat_route_details(
        db,
        "Rewrite this.",
        "cos_9",
        [],
    )
    assert route == "cos"
    assert reason == "non_dashboard_cos_session"


def test_select_main_chat_route_prefers_local_for_multiline_pasted_draft_request():
    db = _FakeDB(dashboard_chat_id=7)
    route = select_main_chat_route(
        db,
        "Can you rewrite this email to sound more direct?\n\nHi team,\nJust checking in again on the protocol draft.",
        "cos_7",
        [("assistant", "Previous reply")],
    )
    assert route == "local_fast"


def test_select_main_chat_route_prefers_local_for_help_me_write_request():
    db = _FakeDB(dashboard_chat_id=7)
    route = select_main_chat_route(
        db,
        "Help me write a short reply to this client saying we can review it tomorrow.",
        "cos_7",
        [],
    )
    assert route == "local_fast"


def test_select_main_chat_route_prefers_local_for_conversational_joke_followup():
    db = _FakeDB(dashboard_chat_id=7)
    route = select_main_chat_route(
        db,
        "I like it. tell me another joke.",
        "cos_7",
        [("assistant", "Why did the scarecrow win an award? Because he was outstanding in his field!")],
    )
    assert route == "local_fast"


def test_select_main_chat_route_prefers_local_for_general_question_with_leading_filler():
    db = _FakeDB(dashboard_chat_id=7)
    route = select_main_chat_route(
        db,
        "Cool. What's 2+2?",
        "cos_7",
        [("assistant", "Previous reply")],
    )
    assert route == "local_fast"


def test_build_local_fast_messages_drops_history_for_standalone_turn():
    messages = _build_local_fast_messages(
        "Rewrite this into a cleaner client email.",
        [
            ("user", "Long prior ask"),
            ("assistant", "Long prior answer"),
        ],
    )
    roles = [m["role"] for m in messages]
    assert roles.count("assistant") == 0
    assert roles[-1] == "user"


def test_build_local_fast_messages_keeps_only_latest_assistant_for_followup():
    messages = _build_local_fast_messages(
        "Make that warmer.",
        [
            ("user", "Draft a reply about the scope change."),
            ("assistant", "Here is a firm version."),
            ("user", "Another note."),
            ("assistant", "Here is the latest version to soften."),
        ],
    )
    non_system = [m for m in messages if m["role"] != "system"]
    assert non_system == [
        {"role": "assistant", "content": "Here is the latest version to soften."},
        {"role": "user", "content": "Make that warmer."},
    ]


def test_build_local_fast_messages_includes_user_memory_context():
    messages = _build_local_fast_messages(
        "Rewrite this into a cleaner client email.",
        [],
        memory_context="Relevant durable user memory:\n- (preference) Prefer concise bullets.",
    )
    assert "Durable User Memory" in messages[0]["content"]
    assert "Prefer concise bullets." in messages[0]["content"]


def test_select_main_chat_route_keeps_cos_for_this_week_workload_question():
    db = _FakeDB(dashboard_chat_id=7)
    route = select_main_chat_route(
        db,
        "What should I do this week?",
        "cos_7",
        [],
    )
    assert route == "cos"


def test_select_main_chat_route_keeps_cos_for_task_creation_request():
    db = _FakeDB(dashboard_chat_id=7)
    route = select_main_chat_route(
        db,
        "Add a task to remind me to send the signed SOW tomorrow.",
        "cos_7",
        [],
    )
    assert route == "cos"


def test_select_main_chat_route_keeps_cos_for_long_task_planning_request():
    db = _FakeDB(dashboard_chat_id=7)
    route = select_main_chat_route(
        db,
        "I have a lot going on today with client tasks, deadlines, and calendar blocks. Help me prioritize what I should work on first and what can wait until next week.",
        "cos_7",
        [],
    )
    assert route == "cos"


def test_run_main_chat_turn_uses_local_fast_and_persists(monkeypatch):
    db = _FakeDB(dashboard_chat_id=7)
    handler = _FakeHandler(db)
    monkeypatch.setattr(
        "core.main_chat_router.run_local_completion",
        lambda messages, session_id: "Local answer",
    )
    monkeypatch.setattr(
        "core.main_chat_router.cos_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("CoS should not be called")),
    )

    out = run_main_chat_turn(
        handler,
        "Rewrite this as a cleaner reply.",
        "cos_7",
        [("assistant", "Earlier answer")],
    )

    assert out == "Local answer"
    assert handler.saved == [("cos_7", "assistant", "Local answer")]
    assert db.updated_chat_ids == [7]


def test_run_main_chat_turn_falls_back_to_cos_when_local_errors(monkeypatch):
    db = _FakeDB(dashboard_chat_id=7)
    handler = _FakeHandler(db)
    monkeypatch.setattr(
        "core.main_chat_router.run_local_completion",
        lambda messages, session_id: (_ for _ in ()).throw(RuntimeError("local failed")),
    )
    monkeypatch.setattr(
        "core.main_chat_router.cos_response",
        lambda db, message, conversation_history=None, chat_id=None: "CoS fallback",
    )

    out = run_main_chat_turn(handler, "Draft a short reply.", "cos_7", [("user", "Earlier turn")])

    assert out == "CoS fallback"
    assert handler.saved == [("cos_7", "assistant", "CoS fallback")]
    assert db.updated_chat_ids == [7]


def test_run_main_chat_turn_falls_back_when_local_marks_turn_unsupported(monkeypatch):
    db = _FakeDB(dashboard_chat_id=7)
    handler = _FakeHandler(db)
    monkeypatch.setattr(
        "core.main_chat_router.run_local_completion",
        lambda messages, session_id: LOCAL_FAST_UNSUPPORTED,
    )
    monkeypatch.setattr(
        "core.main_chat_router.cos_response",
        lambda db, message, conversation_history=None, chat_id=None: "CoS fallback",
    )

    out = run_main_chat_turn(handler, "Rewrite this note.", "cos_7", [])

    assert out == "CoS fallback"
    assert handler.saved == [("cos_7", "assistant", "CoS fallback")]


def test_run_main_chat_turn_keeps_non_dashboard_cos_on_cos(monkeypatch):
    db = _FakeDB(dashboard_chat_id=7)
    handler = _FakeHandler(db)
    local_called = []
    monkeypatch.setattr(
        "core.main_chat_router.run_local_completion",
        lambda messages, session_id: local_called.append(True) or "Local answer",
    )
    monkeypatch.setattr(
        "core.main_chat_router.cos_response",
        lambda db, message, conversation_history=None, chat_id=None: f"CoS:{chat_id}",
    )

    out = run_main_chat_turn(handler, "Rewrite this.", "cos_9", [("user", "Earlier turn")])

    assert out == "CoS:9"
    assert local_called == []
    assert handler.saved == [("cos_9", "assistant", "CoS:9")]
    assert db.updated_chat_ids == [9]


def test_run_main_chat_turn_handles_teach_navi_without_model_calls(monkeypatch):
    db = _FakeDB(dashboard_chat_id=7)
    handler = _FakeHandler(db)
    monkeypatch.setattr(
        "core.main_chat_router.run_local_completion",
        lambda messages, session_id: (_ for _ in ()).throw(AssertionError("local should not run")),
    )
    monkeypatch.setattr(
        "core.main_chat_router.cos_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("CoS should not run")),
    )

    out = run_main_chat_turn(handler, "Teach Navi: I prefer concise bullets.", "main_session", [])

    assert "I'll remember that" in out
    assert db.user_memory_added[0][1] == "taught"
    assert "concise bullets" in db.user_memory_added[0][2]
    assert handler.saved == [("main_session", "assistant", out)]


def test_run_main_chat_turn_handles_teach_navi_alias_without_model_calls(monkeypatch):
    db = _FakeDB(dashboard_chat_id=7)
    handler = _FakeHandler(db)
    monkeypatch.setattr(
        "core.main_chat_router.run_local_completion",
        lambda messages, session_id: (_ for _ in ()).throw(AssertionError("local should not run")),
    )
    monkeypatch.setattr(
        "core.main_chat_router.cos_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("CoS should not run")),
    )

    out = run_main_chat_turn(handler, "Teach Navi: Q-sub means quality submission.", "main_session", [])

    assert "I'll remember that alias" in out
    assert db.user_memory_added[0][1] == "alias"
    assert db.user_memory_added[0][2] == "Q-sub means quality submission."
    assert "Q-sub" in str(db.user_memory_added[0][6])
    assert handler.saved == [("main_session", "assistant", out)]


def test_run_main_chat_turn_skips_memory_context_for_teach_navi(monkeypatch):
    db = _FakeDB(dashboard_chat_id=7)
    handler = _FakeHandler(db)
    monkeypatch.setattr(
        "core.main_chat_router.build_user_memory_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("memory context should not be built")),
    )
    monkeypatch.setattr(
        "core.main_chat_router.run_local_completion",
        lambda messages, session_id: (_ for _ in ()).throw(AssertionError("local should not run")),
    )
    monkeypatch.setattr(
        "core.main_chat_router.cos_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("CoS should not run")),
    )

    out = run_main_chat_turn(handler, "Teach Navi: I prefer concise bullets.", "main_session", [])

    assert "I'll remember that" in out


def test_run_main_chat_turn_auto_stores_durable_memory(monkeypatch):
    db = _FakeDB(dashboard_chat_id=7)
    handler = _FakeHandler(db)
    handler.response_handler = SimpleNamespace(
        chat_with_llama=lambda messages, session_id: '{"preferences":["Prefer concise bullets."]}'
    )
    monkeypatch.setattr(
        "core.main_chat_router.run_local_completion",
        lambda messages, session_id: "Local answer",
    )
    monkeypatch.setattr(
        "core.main_chat_router.cos_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("CoS should not be called")),
    )

    out = run_main_chat_turn(handler, "Rewrite this email.", "main_session", [])

    assert out == "Local answer"
    assert any(row[1] == "preference" and "concise bullets" in row[2] for row in db.user_memory_added)
    pending = db.user_memory_added[-1]
    assert pending[5] == "pending"
    assert pending[6]["source_session_id"] == "main_session"
    assert pending[6]["route"] == "local_fast"
    assert pending[6]["extraction_version"] == "passive_memory_v2"


def test_run_main_chat_turn_injects_db_user_memory_into_local_prompt(monkeypatch):
    db = _FakeDB(dashboard_chat_id=7)
    db.user_memory_add(kind="preference", content="Prefer concise bullets.", source="teach_navi")
    db.user_memory_add(
        kind="alias",
        content="Q-sub means quality submission.",
        source="teach_navi",
        confidence=1.0,
        approval_status="approved",
        json_data={"alias": {"term": "Q-sub", "canonical": "quality submission", "synonyms": []}},
    )
    db.user_memory_add(
        kind="alias",
        content="Q-sub means quality submission.",
        source="auto_chat",
        confidence=0.65,
        approval_status="pending",
    )
    handler = _FakeHandler(db)
    captured = []
    monkeypatch.setattr(
        "core.main_chat_router.run_local_completion",
        lambda messages, session_id: captured.append(messages) or "Local answer",
    )
    monkeypatch.setattr(
        "core.main_chat_router.cos_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("CoS should not be called")),
    )

    run_main_chat_turn(handler, "Rewrite this email.", "main_session", [])

    assert captured
    assert "Approved aliases / glossary" in captured[0][0]["content"]
    assert "Q-sub means quality submission." in captured[0][0]["content"]
    assert "Prefer concise bullets." in captured[0][0]["content"]
    assert captured[0][0]["content"].count("Q-sub means quality submission.") == 1

from __future__ import annotations

from types import SimpleNamespace

from core.response_handler import ResponseHandler


def _rh() -> ResponseHandler:
    rh = ResponseHandler.__new__(ResponseHandler)
    rh.process = None
    rh.model_loaded = False
    rh.chat_handler = SimpleNamespace(
        db=SimpleNamespace(
            get_tasks=lambda: [],
            user_memory_search=lambda **kw: [],
            user_memory_recent=lambda **kw: [],
            user_memory_add=lambda **kw: 1,
            user_memory_add_many=lambda **kw: 0,
        )
    )
    return rh


def test_is_task_query_yes_no_paths(monkeypatch):
    rh = _rh()
    monkeypatch.setattr(rh, "chat_with_llama", lambda messages, session_id: "YES")
    assert rh._is_task_query("what's due today?")
    monkeypatch.setattr(rh, "chat_with_llama", lambda messages, session_id: "NO")
    assert not rh._is_task_query("tell me a joke")


def test_is_task_query_fallback_keyword_detection(monkeypatch):
    rh = _rh()

    def _boom(messages, session_id):
        raise RuntimeError("worker unavailable")

    monkeypatch.setattr(rh, "chat_with_llama", _boom)
    assert rh._is_task_query("show my tasks")
    assert not rh._is_task_query("what is the weather")


def test_format_tasks_for_llm_includes_summary_lines():
    rh = _rh()
    tasks = [
        (1, "Task A", "01-01-2020", "Business", "None", 0),
        (2, "Task B", "12-31-2099", "Business", "None", 1),
    ]
    out = rh._format_tasks_for_llm(tasks)
    assert "Task Summary:" in out
    assert "Total tasks: 2" in out
    assert "Pending: 1" in out
    assert "Completed: 1" in out
    assert "Task A" in out and "Task B" in out


def test_handle_task_query_empty_and_nonempty(monkeypatch):
    rh = _rh()
    # Empty branch
    rh.chat_handler.db.get_tasks = lambda: []
    assert "don't have any tasks" in rh._handle_task_query("what are my tasks").lower()

    # Non-empty branch
    rh.chat_handler.db.get_tasks = lambda: [
        (1, "Review FDA memo", "02-26-2026", "Business", "None", 0)
    ]
    monkeypatch.setattr(rh, "chat_with_llama", lambda messages, session_id: "You have one pending task.")
    assert "one pending task" in rh._handle_task_query("what are my tasks").lower()


# --- Navi tasks/projects context (_get_navi_tasks_projects_context) ---


def _rh_with_rich_db():
    """ResponseHandler with db that has list_tasks_rich and cos_get_projects."""
    rh = ResponseHandler.__new__(ResponseHandler)
    rh.process = None
    rh.model_loaded = False
    memory_rows = []

    def _user_memory_add(*, kind, content, source="unknown", confidence=1.0, json_data=None):
        row = (len(memory_rows) + 1, kind, content, source, confidence, json_data, "now", "now")
        memory_rows.insert(0, row)
        return row[0]

    def _user_memory_add_many(*, items):
        added = 0
        for item in items:
            _user_memory_add(**item)
            added += 1
        return added

    db = SimpleNamespace(
        get_tasks=lambda: [],
        list_tasks_rich=lambda **kw: [],
        cos_get_projects=lambda status=None, client=None: [],
        user_memory_search=lambda **kw: [],
        user_memory_recent=lambda **kw: [],
        user_memory_add=_user_memory_add,
        user_memory_add_many=_user_memory_add_many,
        _memory_rows=memory_rows,
    )
    rh.chat_handler = SimpleNamespace(db=db)
    return rh


def test_get_navi_tasks_projects_context_empty():
    rh = _rh_with_rich_db()
    out = rh._get_navi_tasks_projects_context()
    assert "Tasks (id, text, priority" in out
    assert "  (none)" in out
    assert "Projects (id, name, client" in out
    assert out.count("(none)") >= 1


def test_get_navi_tasks_projects_context_with_tasks():
    rh = _rh_with_rich_db()
    rh.chat_handler.db.list_tasks_rich = lambda **kw: [
        {
            "id": 1,
            "task_text": "Review FDA memo",
            "priority": 4,
            "due_date": "02-26-2026",
            "next_action_date": "02-25-2026",
            "category": "Business",
        },
    ]
    out = rh._get_navi_tasks_projects_context()
    assert "Tasks (id, text, priority" in out
    assert "Review FDA memo" in out
    assert "P4" in out
    assert "02-26-2026" in out
    assert "02-25-2026" in out
    assert "Business" in out


def test_get_navi_tasks_projects_context_with_projects():
    rh = _rh_with_rich_db()
    # cos_get_projects returns rows: id, name, client, description, status, priority, deadline, ...
    rh.chat_handler.db.cos_get_projects = lambda status=None, client=None: [
        (10, "Acme QMS", "Acme Corp", "desc", "Active", 1, "2026-03-01", None, None, None, None, None, None),
    ]
    out = rh._get_navi_tasks_projects_context()
    assert "Projects (id, name, client" in out
    assert "Acme QMS" in out
    assert "Acme Corp" in out
    assert "Active" in out
    assert "2026-03-01" in out


def test_get_navi_tasks_projects_context_on_error_returns_empty(monkeypatch):
    rh = _rh_with_rich_db()
    rh.chat_handler.db.list_tasks_rich = lambda **kw: (_ for _ in ()).throw(RuntimeError("db gone"))
    out = rh._get_navi_tasks_projects_context()
    assert out == ""


def test_get_response_injects_navi_context_when_nonempty(monkeypatch):
    rh = _rh_with_rich_db()
    rh.chat_handler.db.list_tasks_rich = lambda **kw: [
        {"id": 1, "task_text": "Ship report", "priority": 3, "due_date": "02-28-2026", "next_action_date": "", "category": "Business"},
    ]
    captured = []

    def capture_hybrid(messages, session_id):
        captured.append(messages)
        return "All set."

    monkeypatch.setattr(rh, "hybrid_wrapper", capture_hybrid)
    # Avoid task-query path and other special paths: use a generic message that goes to main chat
    monkeypatch.setattr(rh, "_is_task_query", lambda msg: False)
    history = [{"role": "user", "content": "What should I focus on today?"}]
    rh.get_response("What should I focus on today?", "main_session", history)
    assert len(captured) == 1
    msgs = captured[0]
    assert len(msgs) >= 2
    assert msgs[0]["role"] == "system"
    assert "Current tasks and projects" in msgs[0]["content"]
    assert "Ship report" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert "What should I focus on today?" in msgs[1]["content"]


def test_get_response_injects_user_memory_context(monkeypatch):
    rh = _rh_with_rich_db()
    rh.chat_handler.db.user_memory_search = lambda **kw: [
        (1, "preference", "Prefer concise bullets.", "teach_navi", 1.0, None, "now", "now"),
    ]
    captured = []

    def capture_hybrid(messages, session_id):
        captured.append(messages)
        return "All set."

    monkeypatch.setattr(rh, "hybrid_wrapper", capture_hybrid)
    monkeypatch.setattr(rh, "_is_task_query", lambda msg: False)

    rh.get_response("Draft a client reply.", "main_session", [])

    msgs = captured[0]
    assert any(m["role"] == "system" and "Relevant durable user memory" in m["content"] for m in msgs)
    assert any(m["role"] == "system" and "Prefer concise bullets." in m["content"] for m in msgs)


def test_get_response_no_injection_when_context_empty(monkeypatch):
    rh = _rh_with_rich_db()
    rh.chat_handler.db.list_tasks_rich = lambda **kw: []
    rh.chat_handler.db.cos_get_projects = lambda status=None, client=None: []
    # When context is empty we still get a non-empty string (headers + "(none)"), so we force empty
    monkeypatch.setattr(rh, "_get_navi_tasks_projects_context", lambda: "")
    captured = []

    def capture_hybrid(messages, session_id):
        captured.append(messages)
        return "Hi."

    monkeypatch.setattr(rh, "hybrid_wrapper", capture_hybrid)
    monkeypatch.setattr(rh, "_is_task_query", lambda msg: False)
    history = []  # get_response appends the new user message
    rh.get_response("Hello", "main_session", history)
    assert len(captured) == 1
    msgs = captured[0]
    # No system injection when context is empty: only the user message (appended in get_response)
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "Hello"


def test_get_response_handles_teach_navi_deterministically(monkeypatch):
    rh = _rh_with_rich_db()
    monkeypatch.setattr(
        rh,
        "hybrid_wrapper",
        lambda messages, session_id: (_ for _ in ()).throw(AssertionError("LLM should not run")),
    )

    out = rh.get_response("Teach Navi: My preferred format is bullets.", "main_session", [])

    assert "I'll remember that" in out
    assert any(row[1] == "taught" and "preferred format" in row[2] for row in rh.chat_handler.db._memory_rows)


def test_get_response_auto_stores_user_memory(monkeypatch):
    rh = _rh_with_rich_db()
    monkeypatch.setattr(rh, "_is_task_query", lambda msg: False)
    monkeypatch.setattr(rh, "hybrid_wrapper", lambda messages, session_id: "Sure, here's a draft.")
    monkeypatch.setattr(rh, "chat_with_llama", lambda messages, session_id: '{"aliases":["Q-sub means quality submission."]}')

    out = rh.get_response("Help me rewrite this.", "main_session", [])

    assert out == "Sure, here's a draft."
    assert any(row[1] == "alias" and "quality submission" in row[2] for row in rh.chat_handler.db._memory_rows)


def test_chat_with_llama_restarts_worker_once_on_comm_error(monkeypatch):
    rh = _rh()
    rh.model_loaded = True

    class _Stdout:
        def readline(self):
            return '{"response": "Recovered"}\n'

    class _Stdin:
        def __init__(self):
            self.calls = 0

        def write(self, text):
            self.calls += 1
            if self.calls == 1:
                raise OSError(22, "Invalid argument")

        def flush(self):
            return None

    rh.process = SimpleNamespace(stdin=_Stdin(), stdout=_Stdout(), poll=lambda: None)
    restarted = []

    def _restart():
        restarted.append(True)
        rh.model_loaded = True

    monkeypatch.setattr(rh, "_restart_worker", _restart)
    rh.worker_lock = SimpleNamespace(__enter__=lambda self: None, __exit__=lambda self, exc_type, exc, tb: False)

    class _Lock:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    rh.worker_lock = _Lock()
    out = rh.chat_with_llama([{"role": "user", "content": "hi"}], "notes_session")
    assert out == "Recovered"
    assert restarted == [True]

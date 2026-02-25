from __future__ import annotations

from types import SimpleNamespace

from core.response_handler import ResponseHandler


def _rh() -> ResponseHandler:
    rh = ResponseHandler.__new__(ResponseHandler)
    rh.process = None
    rh.model_loaded = False
    rh.chat_handler = SimpleNamespace(db=SimpleNamespace(get_tasks=lambda: []))
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

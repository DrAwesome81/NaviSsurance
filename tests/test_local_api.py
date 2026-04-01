from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


fastapi = pytest.importorskip("fastapi")
_ = fastapi
from fastapi.testclient import TestClient
from pydantic import BaseModel

from core.db import DatabaseManager

api_app = importlib.import_module("api.app")


class _ToolResult(BaseModel):
    value: str


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(str(tmp_path / "api.db"))


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(api_app, "_db", lambda: db)
    with TestClient(api_app.app) as test_client:
        yield test_client


def test_local_api_health_and_tools(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert "capabilities" in health.json()
    assert "browser_tools" in health.json()["capabilities"]

    tools = client.get("/tools")
    assert tools.status_code == 200
    names = {item["name"] for item in tools.json()["tools"]}
    assert "web_research" in names
    assert "browser_fetch" in names
    browser_fetch = next(item for item in tools.json()["tools"] if item["name"] == "browser_fetch")
    assert browser_fetch["side_effect_class"] == "browser"
    assert browser_fetch["approval_required"] is False


def test_local_api_main_turn_saves_user_message_and_returns_response(client, db, monkeypatch):
    class _ChatManager:
        def __init__(self, _db):
            self.chat_handler = object()

    seen = {}

    def _fake_run_main_chat_turn(chat_handler, message, session_id, history):
        seen["chat_handler"] = chat_handler
        seen["message"] = message
        seen["session_id"] = session_id
        seen["history"] = history
        return "assistant reply"

    monkeypatch.setattr(api_app, "ChatManager", _ChatManager)
    monkeypatch.setattr(api_app, "run_main_chat_turn", _fake_run_main_chat_turn)

    response = client.post(
        "/chat/main-turn",
        json={"message": "hello from api", "session_id": "api_test_session"},
    )
    assert response.status_code == 200
    assert response.json() == {"response": "assistant reply", "session_id": "api_test_session"}

    assert seen["message"] == "hello from api"
    assert seen["session_id"] == "api_test_session"
    assert seen["history"] == []

    history = db.get_chat_history("api_test_session", limit=5)
    assert history[-1] == ("user", "hello from api")


def test_local_api_jobs_round_trip(client, db, monkeypatch):
    processed = {"count": 0, "db_name": None}

    class _RuntimeStub:
        def __init__(self, runtime_db):
            self.db = runtime_db

        def process_due_jobs(self):
            processed["count"] += 1
            processed["db_name"] = self.db.db_name
            return 1

    monkeypatch.setattr(api_app, "get_runtime_service", lambda db: _RuntimeStub(db))

    create = client.post(
        "/jobs",
        json={
            "job_type": "daily_briefing_refresh",
            "payload": {"force": True},
            "priority": 77,
            "unique_key": "job:one",
        },
    )
    assert create.status_code == 200
    job_id = int(create.json()["job_id"])
    assert job_id > 0
    assert processed["count"] == 1
    assert processed["db_name"] == db.db_name

    jobs = client.get("/jobs")
    assert jobs.status_code == 200
    rows = jobs.json()["jobs"]
    assert len(rows) == 1
    assert rows[0]["id"] == job_id
    assert rows[0]["job_type"] == "daily_briefing_refresh"
    assert rows[0]["priority"] == 77

    filtered = client.get("/jobs", params={"status": "queued"})
    assert filtered.status_code == 200
    assert len(filtered.json()["jobs"]) == 1


def test_local_api_invoke_tool_returns_model_dump(client, monkeypatch):
    monkeypatch.setattr(
        api_app,
        "get_tool",
        lambda tool_name: SimpleNamespace(name=tool_name) if tool_name == "fake_tool" else None,
    )
    monkeypatch.setattr(
        api_app,
        "invoke_tool",
        lambda *args, **kwargs: _ToolResult(value=f"{kwargs['caller_type']}:{kwargs['caller_id']}:{kwargs['session_id']}"),
    )

    response = client.post(
        "/tools/fake_tool",
        json={
            "caller_type": "api",
            "caller_id": "pytest",
            "session_id": "s-1",
            "kwargs": {"query": "ignored"},
        },
    )
    assert response.status_code == 200
    assert response.json() == {"result": {"value": "api:pytest:s-1"}}


def test_local_api_invoke_tool_404_for_unknown_tool(client, monkeypatch):
    monkeypatch.setattr(api_app, "get_tool", lambda _tool_name: None)

    response = client.post("/tools/missing_tool", json={"kwargs": {}})
    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown tool: missing_tool"

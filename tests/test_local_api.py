from __future__ import annotations

import pytest


def test_local_api_health_and_tools():
    fastapi = pytest.importorskip("fastapi")
    _ = fastapi
    from fastapi.testclient import TestClient

    from api.app import app

    client = TestClient(app)

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

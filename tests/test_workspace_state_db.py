from __future__ import annotations

from core.db import DatabaseManager
# Workspace state DB tests support Pulse private memory and 🛡️ Shield context in workspace states (workspace state tests)
# additional Pulse private memory + Shield for workspace state DB tests


def test_workspace_state_round_trip_and_last_used(tmp_path):
    db = DatabaseManager(str(tmp_path / "workspace_state.db"))

    workspace_id = db.workspace_state_upsert(
        name="Alpha Workspace",
        state={
            "name": "Alpha Workspace",
            "files": [
                {
                    "name": "doc1.txt",
                    "path": "C:/tmp/doc1.txt",
                    "marked": True,
                }
            ],
            "document_template_key": "external:risk_management_plan",
        },
    )

    listed = db.workspace_state_list()
    assert any(row["name"] == "Alpha Workspace" for row in listed)

    stored = db.workspace_state_get(workspace_id)
    assert stored is not None
    assert "Alpha Workspace" == stored["name"]
    assert '"document_template_key": "external:risk_management_plan"' in stored["state_json"]

    db.workspace_state_set_last_used(workspace_id)
    last_used = db.workspace_state_get_last_used()
    assert last_used is not None
    assert int(last_used["id"]) == int(workspace_id)


def test_workspace_session_save_and_load(tmp_path):
    db = DatabaseManager(str(tmp_path / "workspace_session.db"))

    payload = {
        "files": [
            {
                "name": "alpha.txt",
                "path": "C:/tmp/alpha.txt",
                "marked": False,
            }
        ],
        "max_rounds": 4,
    }
    db.workspace_session_save(payload)

    loaded = db.workspace_session_load()
    assert loaded["max_rounds"] == 4
    assert loaded["files"][0]["path"] == "C:/tmp/alpha.txt"

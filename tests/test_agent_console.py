from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import patch

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QFileDialog

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def cos_db(temp_db_path):
    import config as config_mod
    import core.db as core_db

    with patch.object(config_mod, "DATABASE_PATH", temp_db_path):
        with patch.object(core_db, "DATABASE_PATH", temp_db_path):
            db = core_db.DatabaseManager()
            yield db


def test_agent_console_upload_artifact_links_file_to_assignment(qapp, cos_db, monkeypatch, tmp_path):
    from gui.agent_console import AgentConsole

    aid = cos_db.agent_create_assignment(
        title="Review uploaded packet",
        brief_md="Look at the attached material and ask follow-up questions.",
        requester_code="navi",
        assignee_code="atlas",
        priority=3,
        status="queued",
    )
    assert aid

    upload_path = tmp_path / "packet.txt"
    upload_path.write_text("Source packet\nKey requirement\nOpen issue", encoding="utf-8")

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(upload_path)], "Text Files (*.txt)"),
    )

    console = AgentConsole(cos_db, agent_code="atlas")
    assert console.focus_assignment(int(aid)) is True

    console._upload_assignment_artifacts()

    arts = cos_db.agent_list_artifacts(assignment_id=int(aid), limit=20)
    assert any(str(a.get("artifact_type") or "") == "uploaded_file" for a in arts)
    assert any(str(a.get("file_path") or "").endswith("packet.txt") for a in arts)
    assert any("Source packet" in str(a.get("content_md") or "") for a in arts)

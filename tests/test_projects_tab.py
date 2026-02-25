"""
Qt/UI tests for Projects tab local behaviors.

Disabled by default. Enable with RUN_QT_TESTS=1.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

if not os.getenv("RUN_QT_TESTS"):
    pytest.skip(
        "Qt/UI tests are disabled by default (set RUN_QT_TESTS=1 to enable).",
        allow_module_level=True,
    )

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.workflow_engine import STATUS_AWAITING_RESEARCH_REVIEW
from gui.projects_tab import ProjectsTab, _format_artifact_for_display


class _DbStub:
    def __init__(self):
        self.projects: dict[int, tuple] = {}
        self.artifacts: dict[int, list[tuple]] = {}
        self._next_id = 1

    def create_project(self, name: str, mode: str):
        pid = self._next_id
        self._next_id += 1
        self.projects[pid] = (pid, name, mode, "running", "2026-01-01", None)
        return pid

    def get_project(self, project_id: int):
        return self.projects.get(int(project_id))

    def get_artifacts_for_project(self, project_id: int):
        return self.artifacts.get(int(project_id), [])


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def projects_tab(monkeypatch, qapp):
    class _StubAgentConsole(QWidget):
        def __init__(self, db, agent_code="atlas", parent=None):
            super().__init__(parent)

    monkeypatch.setattr("gui.projects_tab.AgentConsole", _StubAgentConsole)
    db = _DbStub()
    tab = ProjectsTab(db=db)
    return tab


def test_format_artifact_for_display_handles_known_types():
    internal = {
        "query": "fda",
        "results": [{"title": "Doc", "excerpt": "Excerpt text"}],
    }
    out = _format_artifact_for_display("internal_retrieval_brief", json.dumps(internal))
    assert "Query: fda" in out
    assert "Result 1" in out

    draft = {"markdown_body": "# Final\n\nBody"}
    out_draft = _format_artifact_for_display("draft", json.dumps(draft))
    assert "# Final" in out_draft


def test_refresh_artifact_display_populates_tabs_and_draft(projects_tab):
    pid = 1
    projects_tab.db.projects[pid] = (pid, "Proj", "internal_web", STATUS_AWAITING_RESEARCH_REVIEW, "", None)
    projects_tab.db.artifacts[pid] = [
        (1, "internal_retrieval_brief", json.dumps({"query": "q1", "results": []}), None, ""),
        (2, "web_research_brief", json.dumps({"query": "q2", "findings": [], "sources": []}), None, ""),
        (3, "synthesis_grok", json.dumps({"content": "grok summary"}), None, ""),
        (4, "synthesis_chatgpt", json.dumps({"content": "chatgpt summary"}), None, ""),
        (5, "draft", json.dumps({"markdown_body": "final draft body"}), None, ""),
    ]

    projects_tab.refresh_artifact_display(pid)

    assert "Query: q1" in projects_tab.artifact_tabs.widget(0).toPlainText()
    assert "Query: q2" in projects_tab.artifact_tabs.widget(1).toPlainText()
    assert "grok summary" in projects_tab.artifact_tabs.widget(2).toPlainText()
    assert "chatgpt summary" in projects_tab.artifact_tabs.widget(3).toPlainText()
    assert "final draft body" in projects_tab.draft_browser.toPlainText()


def test_on_continue_to_draft_requires_project_selection(monkeypatch, projects_tab):
    projects_tab._current_project_id = None

    captured = {"called": False}

    def _warn(*args, **kwargs):
        captured["called"] = True
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", _warn)
    projects_tab.on_continue_to_draft()
    assert captured["called"] is True


def test_on_continue_to_draft_rejects_wrong_status(monkeypatch, projects_tab):
    pid = 2
    projects_tab._current_project_id = pid
    projects_tab.db.projects[pid] = (pid, "Proj", "internal_web", "running", "", None)

    captured = {"called": False}

    def _warn(*args, **kwargs):
        captured["called"] = True
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", _warn)
    projects_tab.on_continue_to_draft()
    assert captured["called"] is True


def test_on_continue_to_draft_project_not_found_warns(monkeypatch, projects_tab):
    projects_tab._current_project_id = 999
    called = {"warning": 0}

    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: called.__setitem__("warning", called["warning"] + 1),
    )
    projects_tab.on_continue_to_draft()
    assert called["warning"] == 1


def test_on_pipeline_finished_enables_continue_for_review_state(projects_tab):
    pid = 3
    projects_tab.db.projects[pid] = (pid, "Proj", "internal_web", STATUS_AWAITING_RESEARCH_REVIEW, "", None)
    projects_tab.on_pipeline_finished(pid)

    assert projects_tab._current_project_id == pid
    assert projects_tab.continue_btn.isEnabled() is True
    assert "Research ready for review" in projects_tab.status_label.text()


def test_on_pipeline_finished_missing_project_row_returns_cleanly(projects_tab):
    projects_tab.continue_btn.setEnabled(False)
    projects_tab.start_btn.setEnabled(False)
    projects_tab.progress_bar.setVisible(True)
    projects_tab.on_pipeline_finished(12345)
    assert projects_tab._current_project_id == 12345
    assert projects_tab.start_btn.isEnabled() is True
    assert projects_tab.progress_bar.isVisible() is False
    assert projects_tab.continue_btn.isEnabled() is False


def test_on_pipeline_error_resets_controls(monkeypatch, projects_tab):
    projects_tab.progress_bar.setVisible(True)
    projects_tab.start_btn.setEnabled(False)
    projects_tab.continue_btn.setEnabled(True)

    called = {"critical": False}

    def _critical(*args, **kwargs):
        called["critical"] = True
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", _critical)
    projects_tab.on_pipeline_error("boom")

    assert called["critical"] is True
    assert projects_tab.progress_bar.isVisible() is False
    assert projects_tab.start_btn.isEnabled() is True
    assert projects_tab.continue_btn.isEnabled() is False
    assert "Pipeline failed" in projects_tab.status_label.text()


def test_on_draft_error_reenables_continue(monkeypatch, projects_tab):
    projects_tab.progress_bar.setVisible(True)
    projects_tab.continue_btn.setEnabled(False)

    called = {"critical": False}

    def _critical(*args, **kwargs):
        called["critical"] = True
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", _critical)
    projects_tab.on_draft_error("draft exploded")

    assert called["critical"] is True
    assert projects_tab.progress_bar.isVisible() is False
    assert projects_tab.continue_btn.isEnabled() is True
    assert "Draft failed" in projects_tab.status_label.text()


def test_on_start_project_creates_worker_and_disables_controls(monkeypatch, projects_tab):
    class _Signal:
        def connect(self, _fn):
            return None

    class _Worker:
        def __init__(self, db, project_id, goals, mode):
            self.db = db
            self.project_id = project_id
            self.goals = goals
            self.mode = mode
            self.started = False
            self.finished_signal = _Signal()
            self.error_signal = _Signal()
            self.status_signal = _Signal()

        def start(self):
            self.started = True

    monkeypatch.setattr("gui.projects_tab.PipelineWorker", _Worker)
    projects_tab.name_edit.setText("My Project")
    projects_tab.goals_edit.setPlainText("Validate project flow")
    projects_tab.mode_combo.setCurrentText("internal_web")

    projects_tab.on_start_project()

    assert projects_tab._current_project_id is not None
    assert projects_tab.start_btn.isEnabled() is False
    assert projects_tab.continue_btn.isEnabled() is False
    assert projects_tab.progress_bar.isHidden() is False
    assert projects_tab._pipeline_worker is not None
    assert projects_tab._pipeline_worker.started is True
    assert "Running pipeline" in projects_tab.status_label.text()


def test_on_start_project_db_error_shows_critical(monkeypatch, projects_tab):
    monkeypatch.setattr(projects_tab.db, "create_project", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db boom")))
    called = {"critical": False}

    def _critical(*args, **kwargs):
        called["critical"] = True
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", _critical)
    projects_tab.on_start_project()
    assert called["critical"] is True


def test_on_draft_finished_updates_status_and_refreshes(monkeypatch, projects_tab):
    called = {"refresh": 0}
    monkeypatch.setattr(projects_tab, "refresh_artifact_display", lambda _pid: called.__setitem__("refresh", called["refresh"] + 1))

    projects_tab._draft_worker = object()
    projects_tab.progress_bar.setVisible(True)
    projects_tab.continue_btn.setEnabled(True)

    projects_tab.on_draft_finished(42)

    assert projects_tab._draft_worker is None
    assert projects_tab.progress_bar.isVisible() is False
    assert projects_tab.continue_btn.isEnabled() is False
    assert "Done (project 42)" in projects_tab.status_label.text()
    assert called["refresh"] == 1


def test_on_continue_to_draft_ready_starts_worker(monkeypatch, projects_tab):
    class _Signal:
        def connect(self, _fn):
            return None

    class _Worker:
        def __init__(self, db, project_id, user_feedback=None):
            self.db = db
            self.project_id = project_id
            self.user_feedback = user_feedback
            self.started = False
            self.finished_signal = _Signal()
            self.error_signal = _Signal()
            self.status_signal = _Signal()

        def start(self):
            self.started = True

    monkeypatch.setattr("gui.projects_tab.ContinueDraftWorker", _Worker)
    pid = 77
    projects_tab._current_project_id = pid
    projects_tab.db.projects[pid] = (pid, "Proj", "internal_web", STATUS_AWAITING_RESEARCH_REVIEW, "", None)
    projects_tab.feedback_edit.setPlainText("Please prioritize FDA risk language.")

    projects_tab.on_continue_to_draft()

    assert projects_tab.continue_btn.isEnabled() is False
    assert projects_tab.progress_bar.isHidden() is False
    assert "Drafting..." in projects_tab.status_label.text()
    assert projects_tab._draft_worker is not None
    assert projects_tab._draft_worker.project_id == pid
    assert projects_tab._draft_worker.user_feedback == "Please prioritize FDA risk language."
    assert projects_tab._draft_worker.started is True

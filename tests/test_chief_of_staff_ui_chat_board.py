from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import patch

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import QApplication, QListWidgetItem, QMessageBox

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


def test_on_new_chat_clears_state(qapp, cos_db):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    tab = ChiefOfStaffTab(cos_db)
    tab._current_chat_id = 123
    tab.ask_input.setPlainText("hello")
    tab.chat_display.setHtml("<p>existing</p>")

    tab._on_new_chat()
    assert tab._current_chat_id is None
    assert tab.ask_input.toPlainText() == ""


def test_on_chat_clicked_sets_current_chat_and_clears_input(qapp, cos_db):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    cid = cos_db.cos_create_chat(title="Planning")
    cos_db.save_message(f"cos_{int(cid)}", "user", "first")

    tab = ChiefOfStaffTab(cos_db)
    item = QListWidgetItem("Planning")
    item.setData(Qt.ItemDataRole.UserRole, int(cid))
    tab.ask_input.setPlainText("draft text")

    tab._on_chat_clicked(item)
    assert int(tab._current_chat_id or 0) == int(cid)
    assert tab.ask_input.toPlainText() == ""
    assert "You:" in tab.chat_display.toHtml()


def test_on_send_creates_chat_and_starts_worker(qapp, cos_db, monkeypatch):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    class _Signal:
        def connect(self, _fn):
            return None

    class _Worker:
        def __init__(self, db, user_message, conversation_history, chat_id=None):
            self.finished_signal = _Signal()
            self.error_signal = _Signal()
            self.started = False
            self._running = False
            self.chat_id = chat_id
            self.user_message = user_message
            self.history = conversation_history

        def isRunning(self):
            return self._running

        def start(self):
            self.started = True
            self._running = True

    monkeypatch.setattr("gui.chief_of_staff_tab.CosAskWorker", _Worker)

    tab = ChiefOfStaffTab(cos_db)
    tab.ask_input.setPlainText("What should I focus on?")
    tab._on_send()

    assert tab._current_chat_id is not None
    assert tab.ask_btn.isEnabled() is False
    assert tab.ask_progress.isHidden() is False
    assert tab.ask_input.toPlainText() == ""
    assert tab._ask_worker is not None and tab._ask_worker.started is True

    history = cos_db.get_chat_history(f"cos_{int(tab._current_chat_id)}", limit=10)
    assert any(role == "user" and "focus" in str(content).lower() for role, content in history)


def test_am_sweep_reuses_existing_chat_and_does_not_rerun_if_output_exists(qapp, cos_db, monkeypatch):
    """AM Sweep should focus today's chat and avoid duplicate runs when output already exists."""
    from datetime import datetime
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    today = datetime.now().strftime("%Y-%m-%d")
    title = f"AM Sweep {today}"
    cid = cos_db.cos_create_chat(title=title)
    session_id = f"cos_{int(cid)}"
    cos_db.save_message(session_id, "user", "AM Sweep")
    cos_db.save_message(session_id, "assistant", "## Executive summary\n- ok\n\n## Actions (machine)\n")

    started = {"count": 0}

    class _Signal:
        def connect(self, _fn):
            return None

    class _Worker:
        def __init__(self, db, conversation_history, chat_id=None):
            self.finished_signal = _Signal()
            self.error_signal = _Signal()
            self._running = False

        def isRunning(self):
            return self._running

        def start(self):
            started["count"] += 1
            self._running = True

    monkeypatch.setattr("gui.chief_of_staff_tab.CosAmSweepWorker", _Worker)

    tab = ChiefOfStaffTab(cos_db)
    tab._current_chat_id = None
    before = cos_db.get_chat_history(session_id, limit=50)
    tab._on_am_sweep()
    after = cos_db.get_chat_history(session_id, limit=50)

    assert int(tab._current_chat_id or 0) == int(cid)
    assert started["count"] == 0
    assert after == before  # no extra "AM Sweep" trigger appended


def test_am_sweep_rerun_always_appends_trigger_and_starts_worker(qapp, cos_db, monkeypatch):
    """AM Sweep (Run again) should always queue a run even if output exists."""
    from datetime import datetime
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    today = datetime.now().strftime("%Y-%m-%d")
    title = f"AM Sweep {today}"
    cid = cos_db.cos_create_chat(title=title)
    session_id = f"cos_{int(cid)}"
    cos_db.save_message(session_id, "user", "AM Sweep")
    cos_db.save_message(session_id, "assistant", "prior output")

    started = {"count": 0}

    class _Signal:
        def connect(self, _fn):
            return None

    class _Worker:
        def __init__(self, db, conversation_history, chat_id=None):
            self.finished_signal = _Signal()
            self.error_signal = _Signal()
            self._running = False

        def isRunning(self):
            return self._running

        def start(self):
            started["count"] += 1
            self._running = True

    monkeypatch.setattr("gui.chief_of_staff_tab.CosAmSweepWorker", _Worker)

    tab = ChiefOfStaffTab(cos_db)
    tab._current_chat_id = None
    tab._on_am_sweep_rerun()

    assert int(tab._current_chat_id or 0) == int(cid)
    assert started["count"] == 1
    history = cos_db.get_chat_history(session_id, limit=10)
    assert sum(1 for role, content in history if role == "user" and str(content) == "AM Sweep") >= 2


def test_on_ask_error_resets_controls_and_appends_error(qapp, cos_db):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    tab = ChiefOfStaffTab(cos_db)
    tab.ask_btn.setEnabled(False)
    tab.ask_progress.setVisible(True)
    tab._ask_worker = object()

    tab._on_ask_error("network timeout")
    assert tab._ask_worker is None
    assert tab.ask_btn.isEnabled() is True
    assert tab.ask_progress.isVisible() is False
    assert "network timeout" in tab.chat_display.toHtml()


def test_chat_assignment_link_not_found_shows_message(qapp, cos_db, monkeypatch):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    tab = ChiefOfStaffTab(cos_db)
    monkeypatch.setattr(tab, "_focus_assignment_by_id", lambda _aid: False)

    called = {"info": False}

    def _info(*args, **kwargs):
        called["info"] = True
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", _info)
    class _AssignmentUrl:
        def toString(self):
            return "assignment://17"

    tab._on_chat_link_clicked(_AssignmentUrl())
    assert called["info"] is True


def test_open_assignment_in_assignee_console_unknown_route_shows_info(qapp, cos_db, monkeypatch):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    aid = cos_db.agent_create_assignment(
        title="Atlas routing target",
        brief_md="Brief",
        requester_code="navi",
        assignee_code="atlas",
    )
    tab = ChiefOfStaffTab(cos_db)
    tab._current_assignment_id = int(aid)

    # Keep route guard deterministic regardless of host wiring.
    monkeypatch.setattr("gui.chief_of_staff_tab.route_for_agent", lambda _assignee: None)
    monkeypatch.setattr(tab, "_resolve_host_with_tab_widget", lambda: (tab, object()))

    called = {"info": False}

    def _info(*args, **kwargs):
        called["info"] = True
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", _info)
    tab._open_assignment_in_assignee_console()
    assert called["info"] is True


def test_bulk_due_date_dialog_none_returns_none(qapp, cos_db):
    from gui.chief_of_staff_tab import BulkDueDateDialog

    dlg = BulkDueDateDialog()
    dlg.none_check.setChecked(True)
    dlg.manual_edit.setText("")
    dlg._on_ok()
    assert dlg.due_date() is None


def test_bulk_due_date_dialog_manual_override_parses(qapp, cos_db):
    from gui.chief_of_staff_tab import BulkDueDateDialog

    dlg = BulkDueDateDialog()
    dlg.none_check.setChecked(False)
    dlg.manual_edit.setText("2030-12-25")
    dlg._on_ok()
    assert dlg.due_date() == "2030-12-25"


def test_bulk_due_date_dialog_date_picker_returns_iso(qapp, cos_db):
    from PyQt6.QtCore import QDate
    from gui.chief_of_staff_tab import BulkDueDateDialog

    dlg = BulkDueDateDialog()
    dlg.none_check.setChecked(False)
    dlg.manual_edit.setText("")
    dlg.date_edit.setDate(QDate(2031, 1, 2))
    dlg._on_ok()
    assert dlg.due_date() == "2031-01-02"


def test_cos_tab_refresh_task_views_best_effort_calls_dashboard_and_tasks(qapp, cos_db, monkeypatch):
    from gui.chief_of_staff_tab import ChiefOfStaffTab
    from PyQt6.QtWidgets import QWidget
    from PyQt6.QtCore import QTimer

    calls = {"dash": 0, "tasks": 0}

    class _Dash:
        def load_tasks_filtered(self):
            calls["dash"] += 1

    class _Tasks:
        def refresh_tasks(self):
            calls["tasks"] += 1

    class _Host(QWidget):
        def __init__(self):
            super().__init__()
            self.dashboard_tab = _Dash()
            self.tasks_tab = _Tasks()

    # Make QTimer.singleShot execute immediately in test.
    monkeypatch.setattr(QTimer, "singleShot", lambda _ms, fn: fn())

    host = _Host()
    tab = ChiefOfStaffTab(cos_db, parent=host)
    tab._refresh_task_views()
    assert calls["dash"] == 1
    assert calls["tasks"] == 1

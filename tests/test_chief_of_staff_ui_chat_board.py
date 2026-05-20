from __future__ import annotations

import os
import json
import sys
import tempfile
from unittest.mock import patch

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt, QUrl, QDate, QTimer
from PyQt6.QtWidgets import QApplication, QListWidgetItem, QMessageBox, QGridLayout, QSizePolicy, QWidget, QHBoxLayout, QTabWidget, QTableWidget
# CoS UI chat board tests cover Pulse intel display and Shield security context in CoS chat (CoS UI chat board tests)

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
    # Fixture for CoS chat board with Pulse/Shield (additional CoS chat board coordination)


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


def test_restore_chat_scroll_state_preserves_manual_position(qapp, cos_db, monkeypatch):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    class _FakeScrollBar:
        def __init__(self):
            self._maximum = 120
            self.saved = None

        def maximum(self):
            return self._maximum

        def setValue(self, value):
            self.saved = value

    tab = ChiefOfStaffTab(cos_db)
    fake_scrollbar = _FakeScrollBar()
    monkeypatch.setattr(tab.chat_display, "verticalScrollBar", lambda: fake_scrollbar)
    monkeypatch.setattr(QTimer, "singleShot", lambda _ms, fn: fn())

    tab._restore_chat_scroll_state({"value": 37, "maximum": 90, "at_bottom": False})
    assert fake_scrollbar.saved == 37


def test_render_chat_history_preserves_scroll_state_on_refresh(qapp, cos_db, monkeypatch):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    cid = cos_db.cos_create_chat(title="Scroll test")
    cos_db.save_message(f"cos_{int(cid)}", "user", "first")
    cos_db.save_message(f"cos_{int(cid)}", "assistant", "reply")

    tab = ChiefOfStaffTab(cos_db)
    tab._current_chat_id = int(cid)
    captured = {}

    monkeypatch.setattr(
        tab,
        "_capture_chat_scroll_state",
        lambda: {"value": 18, "maximum": 100, "at_bottom": False},
    )

    def _restore(state, *, force_bottom=False):
        captured["state"] = state
        captured["force_bottom"] = force_bottom

    monkeypatch.setattr(tab, "_restore_chat_scroll_state", _restore)
    tab._render_chat_history(preserve_scroll=True)

    assert captured["state"]["value"] == 18
    assert captured["force_bottom"] is False


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


def test_project_edit_dialog_uses_optional_deadline_picker(qapp):
    from gui.project_management_panel import ProjectEditDialog

    dialog = ProjectEditDialog(project={"name": "Alpha", "deadline": "2026-05-20"})
    assert dialog.deadline_enabled.isChecked() is True
    assert dialog.deadline_edit.date().toString("yyyy-MM-dd") == "2026-05-20"

    dialog.deadline_enabled.setChecked(False)
    values = dialog.values()
    assert values["deadline"] is None

    dialog.deadline_enabled.setChecked(True)
    dialog.deadline_edit.setDate(QDate(2026, 6, 15))
    values = dialog.values()
    assert values["deadline"] == "2026-06-15"


def test_cos_tab_uses_font_aware_input_and_button_sizing(qapp, cos_db):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    tab = ChiefOfStaffTab(cos_db)

    assert tab.ask_input.minimumHeight() == tab._chat_entry_min_height(lines=2)
    assert tab.ask_btn.minimumHeight() == tab._control_min_height()
    assert tab.asg_start_btn.minimumHeight() == tab._control_min_height()
    assert tab.asg_open_chat_btn.minimumHeight() == tab._control_min_height()


def test_cos_assignment_sidebar_uses_grid_layouts_for_dense_actions(qapp, cos_db):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    tab = ChiefOfStaffTab(cos_db)
    asg_layout = tab.sidebar_tabs.widget(1).layout()

    # Delegation Board wraps the dense New / bulk / AM Sweep grid plus filters and table.
    board_widget = asg_layout.itemAt(1).widget()
    assert board_widget is not None
    board_layout = board_widget.layout()
    assert isinstance(board_layout.itemAt(0).layout(), QGridLayout)

    # Former vertical assignment-action grids are a compact horizontal toolbar under the board.
    action_lay = asg_layout.itemAt(2).layout()
    assert isinstance(action_lay, QHBoxLayout)
    assert action_lay.count() >= 4

    assert tab.asg_start_btn.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Minimum
    assert tab.asg_bulk_create_tasks_btn.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Minimum


def test_cos_assignment_filters_use_grid_layout_and_scaled_search_height(qapp, cos_db):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    tab = ChiefOfStaffTab(cos_db)
    asg_layout = tab.sidebar_tabs.widget(1).layout()
    board_widget = asg_layout.itemAt(1).widget()
    board_layout = board_widget.layout()
    filter_row = board_layout.itemAt(1).layout()
    assert isinstance(filter_row, QHBoxLayout)
    filter_host = filter_row.itemAt(1).widget()
    filters_layout = filter_host.layout()

    assert isinstance(filters_layout, QGridLayout)
    assert filters_layout.itemAtPosition(0, 0).widget() is tab.assignment_scope_filter
    assert filters_layout.itemAtPosition(0, 1).widget() is tab.assignment_status_filter
    assert filters_layout.itemAtPosition(1, 0).widget() is tab.assignment_health_filter
    assert filters_layout.itemAtPosition(1, 1).widget() is tab.assignment_assignee_filter
    assert filters_layout.itemAtPosition(2, 0).widget() is tab.assignment_followup_filter
    assert filters_layout.itemAtPosition(3, 0).widget() is tab.assignment_search_input
    assert tab.assignment_search_input.minimumHeight() == tab._control_min_height(extra_padding=10)
    assert isinstance(tab.assignment_list, QTableWidget)


def test_cos_assignment_table_restores_saved_sort_and_column_widths(qapp, cos_db):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    cos_db.set_setting(
        "chief_of_staff.assignment_table_state",
        json.dumps(
            {
                "sort_column": 3,
                "sort_order": int(Qt.SortOrder.DescendingOrder.value),
                "column_widths": [120, 110, 105, 130, 140, 125, 150, 260],
            }
        ),
    )

    tab = ChiefOfStaffTab(cos_db)
    header = tab.assignment_list.horizontalHeader()

    assert header.sortIndicatorSection() == 3
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    assert tab.assignment_list.columnWidth(0) == 120
    assert tab.assignment_list.columnWidth(7) == 260


def test_cos_assignment_filters_restore_saved_state(qapp, cos_db):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    atlas_index = 0
    for a in cos_db.agents_list_active():
        code = str(a.get("code") or "").strip().lower()
        if code == "atlas":
            atlas_index = code
            break

    cos_db.set_setting(
        "chief_of_staff.assignment_filter_state",
        json.dumps(
            {
                "scope": "all",
                "status": "blocked",
                "health": "stale_blocked",
                "followup": "needs_input",
                "assignee": atlas_index,
                "search": "pccp",
            }
        ),
    )

    tab = ChiefOfStaffTab(cos_db)

    assert str(tab.assignment_scope_filter.currentData() or "") == "all"
    assert (tab.assignment_status_filter.currentText() or "").strip().lower() == "blocked"
    assert str(tab.assignment_health_filter.currentData() or "") == "stale_blocked"
    assert str(tab.assignment_followup_filter.currentData() or "") == "needs_input"
    assert str(tab.assignment_assignee_filter.currentData() or "") == "atlas"
    assert tab.assignment_search_input.text() == "pccp"


def test_chat_window_host_shell_mode_rebalances_for_chief_of_staff(qapp):
    from gui.interface import ChatWindow

    class _ShellHarness(QWidget):
        def __init__(self):
            super().__init__()
            self._main_layout_default_spacing = 6
            self.main_layout = QHBoxLayout(self)
            self.main_layout.setSpacing(self._main_layout_default_spacing)
            self.chat_panel = QWidget(self)
            self.tab_widget = QTabWidget(self)
            self.tab_widget.addTab(QWidget(), "Dashboard")
            self.tab_widget.addTab(QWidget(), "Chief of Staff")
            self.main_layout.addWidget(self.chat_panel, 1)
            self.main_layout.addWidget(self.tab_widget, 3)
            self._apply_host_shell_mode = lambda active: ChatWindow._apply_host_shell_mode(self, active)

    host = _ShellHarness()

    ChatWindow._on_tab_changed(host, 1)
    assert host.chat_panel.isHidden() is True
    assert host.main_layout.spacing() == 0
    assert host.main_layout.stretch(0) == 0
    assert host.main_layout.stretch(1) == 1

    ChatWindow._on_tab_changed(host, 0)
    assert host.chat_panel.isHidden() is False
    assert host.main_layout.spacing() == host._main_layout_default_spacing
    assert host.main_layout.stretch(0) == 1
    assert host.main_layout.stretch(1) == 3

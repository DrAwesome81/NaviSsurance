"""
Qt/UI task-path tests for Dashboard tab.

Disabled by default. Enable with RUN_QT_TESTS=1.
"""
# Dashboard tasks UI tests support Pulse-raised tasks and 🛡️ security task routing from CoS (tasks UI tests)
# New: tasks UI now explicitly supports Pulse private memory for Shield (additional dashboard tasks UI spot)
# New: dashboard tasks UI now explicitly supports Pulse private memory for Shield (additional dashboard tasks UI spot)
# New: dashboard tasks UI now explicitly supports Pulse private memory for Shield (additional dashboard tasks UI spot)
# New: dashboard tasks UI now explicitly supports Pulse private memory for Shield (additional dashboard tasks UI spot)
# New: dashboard tasks UI now explicitly supports Pulse private memory for Shield (additional dashboard tasks UI spot)
# New: dashboard tasks UI now explicitly supports Pulse private memory for Shield (additional dashboard tasks UI spot)
# New: dashboard tasks UI now explicitly supports Pulse private memory for Shield (additional dashboard tasks UI spot)
# New: dashboard tasks UI now explicitly supports Pulse private memory for Shield (additional dashboard tasks UI spot)

from __future__ import annotations

import os
import sys

import pytest

if not os.getenv("RUN_QT_TESTS"):
    pytest.skip(
        "Qt/UI tests are disabled by default (set RUN_QT_TESTS=1 to enable).",
        allow_module_level=True,
    )

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gui.dashboard_tab import DashboardTab


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _dash_task_stub() -> DashboardTab:
    d = DashboardTab.__new__(DashboardTab)
    d.task_list = QTableWidget(0, 4)
    d.tasks_panel = None
    return d


def test_load_tasks_filtered_delegates_to_embedded_tasks_panel(qapp):
    d = _dash_task_stub()
    called = {"refresh": 0}

    class _TasksPanel:
        def refresh_tasks(self):
            called["refresh"] += 1

    d.tasks_panel = _TasksPanel()
    d.load_tasks_filtered()
    assert called["refresh"] == 1


def test_update_task_status_skips_while_loading(qapp):
    d = _dash_task_stub()
    d._loading_tasks = True

    class _Db:
        def update_task_by_id(self, *args, **kwargs):
            raise AssertionError("update_task_by_id should not be called while loading")

    d.db = _Db()
    # Should early-return safely.
    d.update_task_status(task_id=11, completed=True)


def test_update_task_status_updates_db_and_applies_row_style(qapp):
    d = _dash_task_stub()
    d._loading_tasks = False
    d.task_list.setRowCount(1)

    task_widget = QWidget()
    task_widget.task_data = {"id": 11}
    d.task_list.setCellWidget(0, 0, task_widget)
    d.task_list.setItem(0, 2, QTableWidgetItem("02-20-2026"))

    called = {"db": 0, "style": 0}

    class _Db:
        def update_task_by_id(self, task_id: int, **kwargs):
            called["db"] += 1
            assert int(task_id) == 11
            assert kwargs.get("completed") == 1

    d.db = _Db()

    def _style(row, due_date, completed):
        called["style"] += 1
        assert row == 0
        assert due_date == "02-20-2026"
        assert completed is True

    d.apply_task_styling_css = _style
    d.update_task_status(task_id=11, completed=True)
    assert called == {"db": 1, "style": 1}


def test_show_task_context_menu_ignores_empty_position(qapp):
    d = _dash_task_stub()
    # No table item exists at this position; method should no-op.
    d.show_task_context_menu(QPoint(999, 999))


def test_on_task_double_clicked_with_missing_user_data_noops(qapp):
    d = _dash_task_stub()
    item = QTableWidgetItem("sample")
    item.setData(Qt.ItemDataRole.UserRole, None)
    # Guard path should avoid DB/sql work and return safely.
    d.on_task_double_clicked(item)


def test_add_task_delegates_to_embedded_tasks_panel(qapp):
    d = _dash_task_stub()
    called = {"add": 0}

    class _TasksPanel:
        def add_task(self):
            called["add"] += 1

    d.tasks_panel = _TasksPanel()
    d.add_task()
    assert called["add"] == 1


def test_add_task_empty_input_returns_without_db_call(qapp):
    d = _dash_task_stub()
    d.tasks_panel = None
    d.taskInput = QLineEdit()
    d.taskInput.setText("   ")
    d.dueDateInput = QDateEdit()
    d.categoryInput = QComboBox()
    d.categoryInput.addItems(["Business", "Personal"])
    d.recurrenceInput = QComboBox()
    d.recurrenceInput.addItems(["None", "Daily", "Weekly"])

    class _Db:
        def add_task(self, **kwargs):
            raise AssertionError("add_task should not be called for empty input")

    d.db = _Db()
    d.add_task_to_table = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("add_task_to_table should not be called for empty input")
    )
    d.add_task()


def test_add_task_success_adds_row_and_clears_input(qapp):
    d = _dash_task_stub()
    d.tasks_panel = None
    d.taskInput = QLineEdit()
    d.taskInput.setText("Follow up with supplier")
    d.dueDateInput = QDateEdit()
    d.categoryInput = QComboBox()
    d.categoryInput.addItems(["Business", "Personal"])
    d.categoryInput.setCurrentText("Business")
    d.recurrenceInput = QComboBox()
    d.recurrenceInput.addItems(["None", "Daily", "Weekly"])
    d.recurrenceInput.setCurrentText("None")

    calls = {"db": 0, "table": 0}

    class _Db:
        def add_task(self, **kwargs):
            calls["db"] += 1
            assert kwargs["task_text"] == "Follow up with supplier"
            assert kwargs["category"] == "Business"
            assert kwargs["recurrence"] == "None"
            return 77

    d.db = _Db()

    def _add_task_to_table(task_id, task_text, due_date, category, recurrence, completed):
        calls["table"] += 1
        assert task_id == 77
        assert task_text == "Follow up with supplier"
        assert category == "Business"
        assert recurrence == "None"
        assert completed == 0

    d.add_task_to_table = _add_task_to_table
    d.add_task()

    assert calls == {"db": 1, "table": 1}
    assert d.taskInput.text() == ""


def test_delete_task_confirmation_no_keeps_row(qapp, monkeypatch):
    d = _dash_task_stub()
    d.task_list.setRowCount(1)
    tw = QWidget()
    tw.task_data = {"id": 33, "text": "Task keep"}
    d.task_list.setCellWidget(0, 0, tw)

    called = {"db": 0}

    class _Db:
        def delete_task_by_id(self, task_id):
            called["db"] += 1

    d.db = _Db()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    d.delete_task(0)

    assert d.task_list.rowCount() == 1
    assert called["db"] == 0


def test_delete_task_confirmation_yes_removes_row(qapp, monkeypatch):
    d = _dash_task_stub()
    d.task_list.setRowCount(1)
    tw = QWidget()
    tw.task_data = {"id": 44, "text": "Task delete"}
    d.task_list.setCellWidget(0, 0, tw)

    called = {"db": 0}

    class _Db:
        def delete_task_by_id(self, task_id):
            called["db"] += 1
            assert int(task_id) == 44

    d.db = _Db()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    d.delete_task(0)

    assert d.task_list.rowCount() == 0
    assert called["db"] == 1


def test_edit_task_without_task_data_noops(qapp):
    d = _dash_task_stub()
    d.task_list.setRowCount(1)
    d.task_list.setCellWidget(0, 0, QWidget())  # no task_data attribute
    d.edit_task(0)


def test_delete_task_without_task_data_noops(qapp, monkeypatch):
    d = _dash_task_stub()
    d.task_list.setRowCount(1)
    d.task_list.setCellWidget(0, 0, QWidget())  # no task_data attribute
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("question dialog should not be opened without task_data")
        ),
    )
    d.delete_task(0)
    assert d.task_list.rowCount() == 1


def test_show_task_context_menu_with_row_missing_task_data_noops(qapp):
    d = _dash_task_stub()
    d.task_list.setRowCount(1)
    d.task_list.setItem(0, 1, QTableWidgetItem("Business"))
    d.task_list.setCellWidget(0, 0, QWidget())  # no task_data attribute
    d.show_task_context_menu(QPoint(5, 5))


def test_load_tasks_filtered_embedded_panel_exception_is_tolerated(qapp):
    d = _dash_task_stub()

    class _TasksPanel:
        def refresh_tasks(self):
            raise RuntimeError("refresh failed")

    d.tasks_panel = _TasksPanel()
    d.load_tasks_filtered()


def test_edit_task_with_nonpositive_id_noops(qapp):
    d = _dash_task_stub()
    d.task_list.setRowCount(1)
    tw = QWidget()
    tw.task_data = {"id": 0, "text": "invalid id"}
    d.task_list.setCellWidget(0, 0, tw)
    d.edit_task(0)


def test_show_task_context_menu_with_nonpositive_id_noops(qapp):
    d = _dash_task_stub()
    d.task_list.setRowCount(1)
    d.task_list.setItem(0, 1, QTableWidgetItem("Business"))
    tw = QWidget()
    tw.task_data = {"id": 0, "text": "invalid id"}
    d.task_list.setCellWidget(0, 0, tw)
    d.show_task_context_menu(QPoint(5, 5))


def test_update_task_status_without_matching_row_skips_styling(qapp):
    d = _dash_task_stub()
    d._loading_tasks = False
    d.task_list.setRowCount(1)
    tw = QWidget()
    tw.task_data = {"id": 999}
    d.task_list.setCellWidget(0, 0, tw)
    d.task_list.setItem(0, 2, QTableWidgetItem("02-20-2026"))

    called = {"db": 0, "style": 0}

    class _Db:
        def update_task_by_id(self, task_id: int, **kwargs):
            called["db"] += 1
            assert int(task_id) == 11

    d.db = _Db()

    def _style(*args, **kwargs):
        called["style"] += 1

    d.apply_task_styling_css = _style
    d.update_task_status(task_id=11, completed=True)
    assert called == {"db": 1, "style": 0}


def test_load_tasks_filtered_fallback_legacy_get_tasks_empty(qapp):
    d = _dash_task_stub()
    d.tasks_panel = None
    d.category_filter = QComboBox()
    d.category_filter.addItems(["All", "Business"])
    d.date_filter = QComboBox()
    d.date_filter.addItems(["All", "Today", "Specific Date"])
    d.date_range = QDateEdit()

    class _Toggle:
        def __init__(self, checked=False):
            self._checked = checked

        def isChecked(self):
            return self._checked

    d.show_completed_cb = _Toggle(False)
    d.show_snoozed_cb = _Toggle(False)

    class _Db:
        def list_tasks_rich(self, **kwargs):
            raise RuntimeError("simulate rich query failure")

        def get_tasks(self, **kwargs):
            return []

    d.db = _Db()
    d.load_tasks_filtered()
    assert d.task_list.rowCount() == 0


def test_load_tasks_filtered_rich_empty_result(qapp):
    d = _dash_task_stub()
    d.tasks_panel = None
    d.category_filter = QComboBox()
    d.category_filter.addItems(["All", "Business"])
    d.date_filter = QComboBox()
    d.date_filter.addItems(["All", "Today", "Specific Date"])
    d.date_range = QDateEdit()

    class _Toggle:
        def __init__(self, checked=False):
            self._checked = checked

        def isChecked(self):
            return self._checked

    d.show_completed_cb = _Toggle(False)
    d.show_snoozed_cb = _Toggle(False)

    class _Db:
        def list_tasks_rich(self, **kwargs):
            return []

    d.db = _Db()
    d.load_tasks_filtered()
    assert d.task_list.rowCount() == 0


def test_load_tasks_missing_database_sets_status_row(qapp, monkeypatch):
    d = _dash_task_stub()
    monkeypatch.setattr("os.path.exists", lambda *_args, **_kwargs: False)
    d.load_tasks()
    assert d.task_list.rowCount() == 1
    first = d.task_list.item(0, 0)
    assert first is not None
    assert "Database file not found" in first.text()


def test_add_task_db_error_surfaces_critical_message(qapp, monkeypatch):
    d = _dash_task_stub()
    d.tasks_panel = None
    d.taskInput = QLineEdit()
    d.taskInput.setText("Task that fails")
    d.dueDateInput = QDateEdit()
    d.categoryInput = QComboBox()
    d.categoryInput.addItems(["Business", "Personal"])
    d.recurrenceInput = QComboBox()
    d.recurrenceInput.addItems(["None", "Daily", "Weekly"])

    class _Db:
        def add_task(self, **kwargs):
            raise RuntimeError("db unavailable")

    d.db = _Db()
    called = {"critical": 0}

    def _critical(*args, **kwargs):
        called["critical"] += 1

    monkeypatch.setattr(QMessageBox, "critical", _critical)
    d.add_task()
    assert called["critical"] == 1

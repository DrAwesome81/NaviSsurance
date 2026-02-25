"""
Qt/UI tests for the local Tasks tab (SQLite-backed).

Disabled by default. Enable with RUN_QT_TESTS=1.
"""

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

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.db import DatabaseManager
from gui.tasks_tab import TasksTab, _parse_due_date


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def tmp_db(tmp_path):
    db = DatabaseManager()
    db.db_name = str(tmp_path / "tasks_tab.db")
    db.setup_db()
    return db


class _Parent(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db


def test_tasks_tab_initializes(qapp, tmp_db):
    tab = TasksTab(_Parent(tmp_db))
    assert tab.table is not None
    assert tab.new_task_input is not None


def test_tasks_tab_add_task_shows_in_table(qapp, tmp_db):
    tab = TasksTab(_Parent(tmp_db))
    tab.new_task_input.setText("Review FDA guidance")
    tab.new_task_due.setText("")
    tab.add_task()
    assert tab.table.rowCount() == 1
    assert "Review FDA guidance" in (tab.table.item(0, 1).text() or "")


@pytest.mark.parametrize(
    ("raw_due", "expected"),
    [
        ("", None),
        ("02-28-2026", "02-28-2026"),
        ("2026-02-28", "02-28-2026"),
    ],
)
def test_parse_due_date_accepts_supported_formats(raw_due, expected):
    assert _parse_due_date(raw_due) == expected


def test_tasks_tab_complete_and_undo(qapp, tmp_db):
    tab = TasksTab(_Parent(tmp_db))
    tab.new_task_input.setText("Complete me")
    tab.add_task()
    assert tab.table.rowCount() == 1

    task_id = int(tab.table.item(0, 0).text())
    tab._toggle_done(task_id, 0)  # mark complete

    # Completed tasks are hidden by default.
    assert tab.table.rowCount() == 0

    # Show completed to validate state and then undo.
    tab.show_completed.setChecked(True)
    tab.refresh_tasks()
    assert tab.table.rowCount() == 1
    assert (tab.table.item(0, 7).text() or "").strip() == "Yes"

    tab._toggle_done(task_id, 1)  # undo complete
    tab.refresh_tasks()
    assert tab.table.rowCount() == 1
    assert (tab.table.item(0, 7).text() or "").strip() == ""


def test_tasks_tab_delete_task(qapp, tmp_db, monkeypatch):
    tab = TasksTab(_Parent(tmp_db))
    tab.new_task_input.setText("Delete me")
    tab.add_task()
    assert tab.table.rowCount() == 1
    task_id = int(tab.table.item(0, 0).text())

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    tab._delete_task(task_id)
    assert tab.table.rowCount() == 0


def test_tasks_tab_persists_between_instances(qapp, tmp_db):
    tab1 = TasksTab(_Parent(tmp_db))
    tab1.new_task_input.setText("Persisted task")
    tab1.add_task()
    assert tab1.table.rowCount() == 1

    # New tab instance over same DB should load existing task.
    tab2 = TasksTab(_Parent(tmp_db))
    assert tab2.table.rowCount() == 1
    assert "Persisted task" in (tab2.table.item(0, 1).text() or "")


def test_tasks_tab_edit_task_updates_text(qapp, tmp_db, monkeypatch):
    tab = TasksTab(_Parent(tmp_db))
    tab.new_task_input.setText("Before edit")
    tab.add_task()
    assert tab.table.rowCount() == 1
    task_id = int(tab.table.item(0, 0).text())

    class _StubEditDialog:
        def __init__(self, parent=None, task=None):
            self._task = task or {}

        def exec(self):
            from PyQt6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def values(self):
            return {
                "task_text": "After edit",
                "due_date": None,
                "category": "Business",
                "priority": 0,
                "tags_json": "[]",
                "next_action_date": None,
                "snoozed_until": None,
                "completed": 0,
            }

    monkeypatch.setattr("gui.tasks_tab.TaskEditDialog", _StubEditDialog)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    tab._edit_task({"id": task_id, "task_text": "Before edit"})
    tab.refresh_tasks()

    assert tab.table.rowCount() == 1
    assert "After edit" in (tab.table.item(0, 1).text() or "")


def test_tasks_tab_snooze_sets_snoozed_until(qapp, tmp_db):
    tab = TasksTab(_Parent(tmp_db))
    tab.new_task_input.setText("Snooze task")
    tab.add_task()
    assert tab.table.rowCount() == 1
    task_id = int(tab.table.item(0, 0).text())

    tab._snooze_task(task_id, days=1)
    # Validate via rich list API that snooze date is persisted.
    rich_rows = tmp_db.list_tasks_rich(include_completed=True, include_snoozed=True, limit=100)
    rich = next((r for r in rich_rows if int(r.get("id") or 0) == task_id), None)
    assert rich is not None
    assert str(rich.get("snoozed_until") or "").strip() != ""


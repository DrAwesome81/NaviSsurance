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

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget, QCheckBox, QDialog

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
    tab.new_task_assigned_to.setEditText("Mason")
    tab.new_task_due.setText("")
    tab.add_task()
    assert tab.table.rowCount() == 1
    assert "Review FDA guidance" in (tab.table.item(0, 1).text() or "")
    assignee_widget = tab.table.cellWidget(0, 2)
    assert assignee_widget is not None
    assert assignee_widget.currentText() == "Mason"


def test_tasks_tab_due_picker_preserves_selected_date(qapp, tmp_db, monkeypatch):
    tab = TasksTab(_Parent(tmp_db))
    tab.new_task_due.setText("02-28-2026")
    monkeypatch.setattr("gui.tasks_tab.QDialog.exec", lambda _self: QDialog.DialogCode.Accepted)
    tab._pick_new_task_due_date()
    assert tab.new_task_due.text() == "02-28-2026"


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


def _done_column_index(tab):
    """Column index for Done (resilient to column order changes)."""
    for c in range(tab.table.columnCount()):
        h = tab.table.horizontalHeaderItem(c)
        if h and h.text() == "Done":
            return c
    return 8  # fallback: Done is 8th visible col (ID, Task, Priority, Tags, Next action, Due, Category, Project, Done, Actions)


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
    done_col = _done_column_index(tab)
    assert (tab.table.item(0, done_col).text() or "").strip() == "Yes"

    tab._toggle_done(task_id, 1)  # undo complete
    tab.refresh_tasks()
    assert tab.table.rowCount() == 1
    assert (tab.table.item(0, done_col).text() or "").strip() == ""


def test_tasks_tab_compact_done_column_uses_checkbox(qapp, tmp_db):
    tab = TasksTab(_Parent(tmp_db), show_header=False, compact=True)
    tab.new_task_input.setText("Compact complete me")
    tab.add_task()
    assert tab.table.rowCount() == 1

    done_col = _done_column_index(tab)
    done_widget = tab.table.cellWidget(0, done_col)
    assert done_widget is not None
    checkbox = done_widget.findChild(QCheckBox)
    assert checkbox is not None
    assert checkbox.isChecked() is False

    checkbox.setChecked(True)
    qapp.processEvents()

    # Completed tasks are hidden by default after refresh.
    assert tab.table.rowCount() == 0


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
                "assigned_to": "Atlas",
                "snoozed_until": None,
                "completed": 0,
            }

    monkeypatch.setattr("gui.tasks_tab.TaskEditDialog", _StubEditDialog)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    tab._edit_task({"id": task_id, "task_text": "Before edit"})
    tab.refresh_tasks()

    assert tab.table.rowCount() == 1
    assert "After edit" in (tab.table.item(0, 1).text() or "")


def test_tasks_tab_assignee_cell_updates_db(qapp, tmp_db):
    tab = TasksTab(_Parent(tmp_db))
    tab.new_task_input.setText("Delegate me")
    tab.add_task()
    assert tab.table.rowCount() == 1
    task_id = int(tab.table.item(0, 0).text())

    assignee_widget = tab.table.cellWidget(0, 2)
    assert assignee_widget is not None
    assignee_widget.setEditText("Quill")
    qapp.processEvents()

    row = tmp_db.get_task_by_id(task_id)
    assert row is not None
    assert row["assigned_to"] == "Quill"


def test_tasks_tab_snooze_bumps_due_date(qapp, tmp_db):
    from core.db import bump_task_due_date_mmddyyyy

    tab = TasksTab(_Parent(tmp_db))
    tab.new_task_input.setText("Due bump task")
    tab.add_task()
    assert tab.table.rowCount() == 1
    task_id = int(tab.table.item(0, 0).text())

    tab._snooze_task(task_id, days=1)
    row = tmp_db.get_task_by_id(task_id)
    assert row is not None
    expected = bump_task_due_date_mmddyyyy(None, days=1)
    assert (row.get("due_date") or "").strip() == expected
    assert not str(row.get("snoozed_until") or "").strip()


# --- Mason (Project Manager) context and command parsing ---


def test_mason_tasks_context_empty(qapp, tmp_db):
    """Mason context includes task/project headers and command docs when db is empty."""
    tab = TasksTab(_Parent(tmp_db))
    ctx = tab._mason_tasks_context()
    assert "Task snapshot" in ctx
    assert "(none)" in ctx
    assert "Projects" in ctx
    assert "ADD_TASK:" in ctx
    assert "TASK_UPDATE_PRIORITY:" in ctx
    assert "TASK_COMPLETE:" in ctx
    assert "PROJECT_UPDATE_STATUS:" in ctx


def test_mason_tasks_context_includes_tasks(qapp, tmp_db):
    """Mason context includes current task list from list_tasks_rich."""
    tmp_db.add_task("test", "Review FDA memo", "02-28-2026", category="Business")
    tab = TasksTab(_Parent(tmp_db))
    ctx = tab._mason_tasks_context()
    assert "Review FDA memo" in ctx
    assert "02-28-2026" in ctx
    assert "Business" in ctx


def test_parse_mason_task_commands_add_task(qapp, tmp_db):
    """Parsing ADD_TASK creates a task in the DB."""
    tab = TasksTab(_Parent(tmp_db))
    out = tab._parse_mason_task_commands("ADD_TASK: New item from Mason | 03-01-2026 | Business")
    rows = tmp_db.list_tasks_rich(include_completed=True, include_snoozed=True, limit=10)
    match = next((r for r in rows if "New item from Mason" in (r.get("task_text") or "")), None)
    assert match is not None
    assert (match.get("due_date") or "").strip() == "03-01-2026"
    assert (match.get("category") or "").strip() == "Business"
    assert "ADD_TASK:" not in out or "New item" not in out


def test_parse_mason_task_commands_update_priority(qapp, tmp_db):
    """Parsing TASK_UPDATE_PRIORITY updates task priority."""
    tid = tmp_db.add_task("test", "Priority task", "02-28-2026", category="Business")
    tab = TasksTab(_Parent(tmp_db))
    tab._parse_mason_task_commands(f"TASK_UPDATE_PRIORITY: {tid} | 4")
    rows = tmp_db.list_tasks_rich(include_completed=True, include_snoozed=True, limit=10)
    match = next((r for r in rows if int(r.get("id") or 0) == int(tid)), None)
    assert match is not None
    assert int(match.get("priority") or 0) == 4


def test_parse_mason_task_commands_complete(qapp, tmp_db):
    """Parsing TASK_COMPLETE marks task completed."""
    tid = tmp_db.add_task("test", "Complete me", "02-28-2026", category="Business")
    tab = TasksTab(_Parent(tmp_db))
    tab._parse_mason_task_commands(f"TASK_COMPLETE: {tid}")
    rows = tmp_db.list_tasks_rich(include_completed=True, include_snoozed=True, limit=10)
    match = next((r for r in rows if int(r.get("id") or 0) == int(tid)), None)
    assert match is not None
    assert int(match.get("completed") or 0) == 1


def test_parse_mason_task_commands_strips_commands_from_response(qapp, tmp_db):
    """Response processor removes command lines and returns the rest (or fallback)."""
    tab = TasksTab(_Parent(tmp_db))
    response = "Here's what I did.\nADD_TASK: Done | 03-01-2026 | Personal\nHope that helps."
    out = tab._parse_mason_task_commands(response)
    assert "ADD_TASK:" not in out
    assert "Here's what I did" in out
    assert "Hope that helps" in out


def test_mason_task_delete_requires_confirm(qapp, tmp_db):
    tid = tmp_db.add_task("test", "Delete me", "03-01-2026", category="Business")
    tab = TasksTab(_Parent(tmp_db))

    out = tab._parse_mason_task_commands(f"TASK_DELETE: {tid}")
    assert "Proposed (not executed)" in out

    rows = tmp_db.list_tasks_rich(include_completed=True, include_snoozed=True, limit=50)
    assert any(int(r.get("id") or 0) == int(tid) for r in rows)

    tab._parse_mason_task_commands(f"CONFIRM: TASK_DELETE: {tid}")
    rows2 = tmp_db.list_tasks_rich(include_completed=True, include_snoozed=True, limit=50)
    assert not any(int(r.get("id") or 0) == int(tid) for r in rows2)


def test_mason_project_delete_requires_confirm(qapp, tmp_db):
    pid = tmp_db.cos_insert_project(name="Project X", client="Client", status="Active")
    tab = TasksTab(_Parent(tmp_db))

    out = tab._parse_mason_task_commands(f"PROJECT_DELETE: {pid}")
    assert "Proposed (not executed)" in out

    prows = tmp_db.cos_get_projects() or []
    assert any(int(r[0] or 0) == int(pid) for r in prows)

    tab._parse_mason_task_commands(f"CONFIRM: PROJECT_DELETE: {pid}")
    prows2 = tmp_db.cos_get_projects() or []
    assert not any(int(r[0] or 0) == int(pid) for r in prows2)


from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import QApplication, QComboBox

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.task_extract import SuggestedTask
# Task import dialog tests support Pulse-raised tasks and 🛡️ security task import from CoS (task import dialog tests)
# additional Pulse private memory + Shield for task import dialog tests
from gui.task_import_dialog import OptionalDateCell, TaskImportDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_task_import_dialog_uses_checkbox_cell_and_calendar_date_widget(qapp):
    dlg = TaskImportDialog(
        tasks=[SuggestedTask(title="Review packet", due_mmddyyyy="none", category="Business", priority=2)]
    )

    import_item = dlg.table.item(0, 0)
    assert import_item is not None
    assert bool(import_item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
    assert import_item.checkState() == Qt.CheckState.Checked

    due_widget = dlg.table.cellWidget(0, 2)
    assert isinstance(due_widget, OptionalDateCell)
    assert due_widget.none_checkbox.isChecked() is True
    assert due_widget.date_edit.calendarPopup() is True

    priority_widget = dlg.table.cellWidget(0, 4)
    assert isinstance(priority_widget, QComboBox)
    assert priority_widget.currentData() == 2


def test_task_import_dialog_collects_due_date_and_priority(qapp):
    dlg = TaskImportDialog(
        tasks=[SuggestedTask(title="Review packet", due_mmddyyyy="none", category="Business", priority=0)]
    )

    due_widget = dlg.table.cellWidget(0, 2)
    assert isinstance(due_widget, OptionalDateCell)
    due_widget.none_checkbox.setChecked(False)
    due_widget.date_edit.setDate(QDate(2026, 4, 15))

    category_widget = dlg.table.cellWidget(0, 3)
    assert isinstance(category_widget, QComboBox)
    category_widget.setCurrentText("Personal")

    priority_widget = dlg.table.cellWidget(0, 4)
    assert isinstance(priority_widget, QComboBox)
    priority_widget.setCurrentIndex(5)

    dlg._on_apply()

    assert dlg.selected_tasks() == [
        SuggestedTask(
            title="Review packet",
            due_mmddyyyy="04-15-2026",
            category="Personal",
            priority=5,
        )
    ]

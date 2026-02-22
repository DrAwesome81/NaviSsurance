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

from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.db import DatabaseManager
from gui.tasks_tab import TasksTab


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


class _Parent:
    def __init__(self, db):
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


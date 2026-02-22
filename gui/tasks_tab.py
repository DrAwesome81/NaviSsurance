"""
Tasks tab (local).

This replaces the previous Vikunja integration. Tasks are stored in SQLite via
core.db.DatabaseManager (same task store used by Dashboard + CoS task capture).
"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QCheckBox,
    QMessageBox,
)

from core.db import DatabaseManager

logger = logging.getLogger(__name__)


def _parse_due_date(value: str) -> str | None:
    """
    Accept empty (None) or a date-like string. Persist in MM-DD-YYYY (project convention).
    """
    s = (value or "").strip()
    if not s:
        return None
    # allow already-canonical MM-DD-YYYY
    try:
        dt = datetime.strptime(s, "%m-%d-%Y")
        return dt.strftime("%m-%d-%Y")
    except Exception:
        pass
    # allow YYYY-MM-DD
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.strftime("%m-%d-%Y")
    except Exception:
        pass
    # best-effort: let dateutil parse if available
    try:
        from dateutil import parser  # type: ignore

        dt = parser.parse(s, default=datetime.now())
        return dt.strftime("%m-%d-%Y")
    except Exception:
        return "unknown"


class TasksTab(QWidget):
    """Local SQLite-backed tasks manager."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent = parent
        self.db = getattr(parent, "db", None) if parent is not None else None
        if self.db is None:
            # Fallback: create our own DB manager (same path via config.DATABASE_PATH)
            self.db = DatabaseManager()
        self._setup_ui()
        self.refresh_tasks()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QLabel("Tasks")
        header.setStyleSheet("color: #e8eaed; font-weight: 700; font-size: 14px; margin: 0;")
        layout.addWidget(header)

        # Filters row
        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search tasks…")
        self.search_input.textChanged.connect(self.refresh_tasks)
        filters.addWidget(self.search_input, 2)

        filters.addWidget(QLabel("Category:"))
        self.category_filter = QComboBox()
        self.category_filter.addItems(["All", "Business", "Personal"])
        self.category_filter.currentTextChanged.connect(self.refresh_tasks)
        filters.addWidget(self.category_filter)

        filters.addWidget(QLabel("Date:"))
        self.date_filter = QComboBox()
        self.date_filter.addItems(["All", "Today", "Overdue", "No Date"])
        self.date_filter.currentTextChanged.connect(self.refresh_tasks)
        filters.addWidget(self.date_filter)

        self.show_completed = QCheckBox("Show completed")
        self.show_completed.stateChanged.connect(self.refresh_tasks)
        filters.addWidget(self.show_completed)

        filters.addStretch(1)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_tasks)
        filters.addWidget(self.refresh_btn)

        layout.addLayout(filters)

        # Quick add row
        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 0, 0, 0)
        add_row.setSpacing(8)

        self.new_task_input = QLineEdit()
        self.new_task_input.setPlaceholderText("New task…")
        self.new_task_input.returnPressed.connect(self.add_task)
        add_row.addWidget(self.new_task_input, 2)

        self.new_task_category = QComboBox()
        self.new_task_category.addItems(["Business", "Personal"])
        add_row.addWidget(self.new_task_category)

        self.new_task_due = QLineEdit()
        self.new_task_due.setPlaceholderText("Due (MM-DD-YYYY, optional)")
        self.new_task_due.returnPressed.connect(self.add_task)
        add_row.addWidget(self.new_task_due)

        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self.add_task)
        add_row.addWidget(self.add_btn)

        layout.addLayout(add_row)

        # Table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Task", "Category", "Due", "Done", "Actions"])
        self.table.setColumnHidden(0, True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        self.table.setSortingEnabled(False)  # we do stable ordering in code

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self.table, 1)

        self.setLayout(layout)

    def add_task(self):
        text = (self.new_task_input.text() or "").strip()
        if not text:
            return
        due = _parse_due_date(self.new_task_due.text())
        category = (self.new_task_category.currentText() or "Business").strip() or "Business"
        try:
            # session_id not currently used by UI; keep a stable value.
            self.db.add_task("tasks_tab", text, due, category=category)
        except Exception as e:
            QMessageBox.warning(self, "Tasks", f"Could not add task:\n\n{type(e).__name__}: {e}")
            return
        self.new_task_input.clear()
        self.new_task_due.clear()
        self.refresh_tasks()

    def refresh_tasks(self):
        try:
            category = self.category_filter.currentText()
            category_val = None if category == "All" else category

            date = self.date_filter.currentText()
            date_val = None if date == "All" else date

            rows = self.db.get_tasks(category=category_val, date_filter=date_val)

            query = (self.search_input.text() or "").strip().lower()
            show_done = self.show_completed.isChecked()

            tasks = []
            for (task_id, task_text, due_date, cat, recurrence, completed) in rows:
                if not show_done and int(completed or 0) == 1:
                    continue
                if query and query not in str(task_text or "").lower():
                    continue
                tasks.append((int(task_id), str(task_text or ""), due_date, str(cat or ""), str(recurrence or ""), int(completed or 0)))

            # Stable ordering: incomplete first, then due_date (None last), then id desc
            def _k(t):
                _id, _txt, _due, _cat, _rec, _done = t
                due_sort = _due if _due else "99-99-9999"
                return (_done, due_sort, -_id)

            tasks.sort(key=_k)

            self.table.setRowCount(0)
            for t in tasks:
                task_id, task_text, due_date, cat, _rec, done = t
                r = self.table.rowCount()
                self.table.insertRow(r)

                it_id = QTableWidgetItem(str(task_id))
                it_id.setData(Qt.ItemDataRole.UserRole, task_id)
                self.table.setItem(r, 0, it_id)

                it_task = QTableWidgetItem(task_text)
                it_task.setFlags(it_task.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 1, it_task)

                it_cat = QTableWidgetItem(cat)
                it_cat.setFlags(it_cat.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 2, it_cat)

                it_due = QTableWidgetItem(due_date or "")
                it_due.setFlags(it_due.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 3, it_due)

                it_done = QTableWidgetItem("Yes" if done else "")
                it_done.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it_done.setFlags(it_done.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 4, it_done)

                # Actions
                actions = QWidget()
                row = QHBoxLayout(actions)
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(6)
                btn_toggle = QPushButton("Undo" if done else "Complete")
                btn_toggle.clicked.connect(lambda _=False, tid=task_id, cur=done: self._toggle_done(tid, cur))
                row.addWidget(btn_toggle)
                btn_del = QPushButton("Delete")
                btn_del.clicked.connect(lambda _=False, tid=task_id: self._delete_task(tid))
                row.addWidget(btn_del)
                self.table.setCellWidget(r, 5, actions)

            self.table.resizeRowsToContents()
        except Exception as e:
            logger.exception("refresh_tasks failed: %s", e)

    def _toggle_done(self, task_id: int, current_done: int):
        try:
            self.db.update_task_completed_by_id(int(task_id), 0 if int(current_done) else 1)
        except Exception as e:
            QMessageBox.warning(self, "Tasks", f"Could not update task:\n\n{type(e).__name__}: {e}")
            return
        self.refresh_tasks()

    def _delete_task(self, task_id: int):
        reply = QMessageBox.question(
            self,
            "Delete Task",
            "Delete this task? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.delete_task_by_id(int(task_id))
        except Exception as e:
            QMessageBox.warning(self, "Tasks", f"Could not delete task:\n\n{type(e).__name__}: {e}")
            return
        self.refresh_tasks()


"""
Tasks tab (local).

This replaces the previous Vikunja integration. Tasks are stored in SQLite via
core.db.DatabaseManager (same task store used by Dashboard + CoS task capture).
"""

from __future__ import annotations

import json
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
    QDialog,
    QDateEdit,
)

from core.db import DatabaseManager
from gui.task_edit_dialog import TaskEditDialog

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
        self.date_filter.addItems(["All", "Today", "Overdue", "No Date", "Specific Date"])
        self.date_filter.currentTextChanged.connect(self.refresh_tasks)
        filters.addWidget(self.date_filter)

        self.specific_date = QDateEdit()
        self.specific_date.setCalendarPopup(True)
        try:
            from PyQt6.QtCore import QDate

            self.specific_date.setDate(QDate.currentDate())
        except Exception:
            pass
        self.specific_date.dateChanged.connect(self.refresh_tasks)
        self.specific_date.setVisible(False)
        filters.addWidget(self.specific_date)

        self.show_completed = QCheckBox("Show completed")
        self.show_completed.stateChanged.connect(self.refresh_tasks)
        filters.addWidget(self.show_completed)

        self.show_snoozed = QCheckBox("Show snoozed")
        self.show_snoozed.stateChanged.connect(self.refresh_tasks)
        filters.addWidget(self.show_snoozed)

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
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Task", "Priority", "Tags", "Next action", "Due", "Category", "Done", "Actions"]
        )
        self.table.setColumnHidden(0, True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        self.table.setSortingEnabled(False)  # we do stable ordering in code

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in range(2, 9):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

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
            # Toggle specific date control
            try:
                self.specific_date.setVisible(self.date_filter.currentText() == "Specific Date")
            except Exception:
                pass

            category = self.category_filter.currentText()
            category_val = None if category == "All" else category

            date = self.date_filter.currentText()
            date_val = None if date == "All" else date
            specific_date = self.specific_date.date().toString("MM-dd-yyyy") if date == "Specific Date" else None

            query = (self.search_input.text() or "").strip().lower()
            show_done = self.show_completed.isChecked()
            show_snoozed = self.show_snoozed.isChecked()

            tasks = self.db.list_tasks_rich(
                category=category_val,
                date_filter=date_val,
                specific_date=specific_date,
                include_completed=bool(show_done),
                include_snoozed=bool(show_snoozed),
                search=query or None,
                limit=500,
            )

            self.table.setRowCount(0)
            for rdict in tasks:
                task_id = int(rdict.get("id") or 0)
                task_text = str(rdict.get("task_text") or "")
                due_date = rdict.get("due_date") or ""
                cat = str(rdict.get("category") or "")
                done = int(rdict.get("completed") or 0)
                priority = int(rdict.get("priority") or 0)
                tags_json = str(rdict.get("tags_json") or "[]")
                tags_display = tags_json
                try:
                    arr = json.loads(tags_json)
                    if isinstance(arr, list):
                        tags_display = ", ".join(str(x) for x in arr if str(x).strip())
                except Exception:
                    pass
                next_action = rdict.get("next_action_date") or ""

                r = self.table.rowCount()
                self.table.insertRow(r)

                it_id = QTableWidgetItem(str(task_id))
                it_id.setData(Qt.ItemDataRole.UserRole, task_id)
                self.table.setItem(r, 0, it_id)

                it_task = QTableWidgetItem(task_text)
                it_task.setFlags(it_task.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 1, it_task)

                it_pr = QTableWidgetItem(str(priority))
                it_pr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it_pr.setFlags(it_pr.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 2, it_pr)

                it_tags = QTableWidgetItem(tags_display)
                it_tags.setFlags(it_tags.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 3, it_tags)

                it_next = QTableWidgetItem(next_action)
                it_next.setFlags(it_next.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 4, it_next)

                it_due = QTableWidgetItem(due_date)
                it_due.setFlags(it_due.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 5, it_due)

                it_cat = QTableWidgetItem(cat)
                it_cat.setFlags(it_cat.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 6, it_cat)

                it_done = QTableWidgetItem("Yes" if done else "")
                it_done.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it_done.setFlags(it_done.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 7, it_done)

                # Actions
                actions = QWidget()
                row = QHBoxLayout(actions)
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(6)
                btn_edit = QPushButton("Edit")
                btn_edit.clicked.connect(lambda _=False, rr=rdict: self._edit_task(rr))
                row.addWidget(btn_edit)
                btn_toggle = QPushButton("Undo" if done else "Complete")
                btn_toggle.clicked.connect(lambda _=False, tid=task_id, cur=done: self._toggle_done(tid, cur))
                row.addWidget(btn_toggle)
                btn_snooze = QPushButton("Snooze 1d")
                btn_snooze.clicked.connect(lambda _=False, tid=task_id: self._snooze_task(tid, days=1))
                row.addWidget(btn_snooze)
                btn_del = QPushButton("Delete")
                btn_del.clicked.connect(lambda _=False, tid=task_id: self._delete_task(tid))
                row.addWidget(btn_del)
                self.table.setCellWidget(r, 8, actions)

            self.table.resizeRowsToContents()
        except Exception as e:
            logger.exception("refresh_tasks failed: %s", e)

    def _toggle_done(self, task_id: int, current_done: int):
        try:
            self.db.update_task_by_id(int(task_id), completed=0 if int(current_done) else 1)
        except Exception as e:
            QMessageBox.warning(self, "Tasks", f"Could not update task:\n\n{type(e).__name__}: {e}")
            return
        self.refresh_tasks()

    def _snooze_task(self, task_id: int, days: int = 1):
        try:
            from datetime import timedelta

            d = (datetime.now() + timedelta(days=int(days))).strftime("%m-%d-%Y")
            self.db.update_task_by_id(int(task_id), snoozed_until=d)
        except Exception as e:
            QMessageBox.warning(self, "Tasks", f"Could not snooze task:\n\n{type(e).__name__}: {e}")
            return
        self.refresh_tasks()

    def _edit_task(self, task_row: dict):
        try:
            dlg = TaskEditDialog(parent=self, task=task_row)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            vals = dlg.values()
            if not vals.get("task_text"):
                return
            self.db.update_task_by_id(int(task_row["id"]), **vals)
        except Exception as e:
            QMessageBox.warning(self, "Tasks", f"Could not edit task:\n\n{type(e).__name__}: {e}")
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


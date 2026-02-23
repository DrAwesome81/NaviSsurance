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

    def __init__(self, parent=None, *, show_header: bool = True, compact: bool = False):
        super().__init__(parent)
        self._parent = parent
        self._show_header = bool(show_header)
        self._compact = bool(compact)
        self.db = getattr(parent, "db", None) if parent is not None else None
        if self.db is None:
            # Fallback: create our own DB manager (same path via config.DATABASE_PATH)
            self.db = DatabaseManager()
        self._setup_ui()
        self.refresh_tasks()

    def _setup_ui(self):
        base_margin = 6 if self._compact else 8
        base_spacing = 6 if self._compact else 8

        layout = QVBoxLayout(self)
        layout.setContentsMargins(base_margin, base_margin, base_margin, base_margin)
        layout.setSpacing(base_spacing)

        if self._show_header:
            header = QLabel("Tasks")
            header.setStyleSheet("color: #e8eaed; font-weight: 700; font-size: 14px; margin: 0;")
            layout.addWidget(header)

        # Filters row
        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(base_spacing)

        label_style = "color: #b0b5bd; font-size: 12px;"
        field_style = (
            "QLineEdit, QComboBox, QDateEdit {"
            "background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; "
            "padding: 6px 8px; border-radius: 6px; }"
            "QLineEdit:focus, QComboBox:focus, QDateEdit:focus { border: 1px solid #6b8cae; }"
        )
        button_style = (
            "QPushButton { background-color: #3a3b3e; color: #e8eaed; border: 1px solid #2e2f32; "
            "padding: 6px 10px; border-radius: 6px; font-weight: 500; }"
            "QPushButton:hover { background-color: #4a4a4e; }"
        )
        primary_button_style = (
            "QPushButton { background-color: #FD6262; color: white; border: none; "
            "padding: 6px 12px; border-radius: 6px; font-weight: 600; }"
            "QPushButton:hover { background-color: #e85555; }"
        )

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search tasks…")
        self.search_input.setStyleSheet(field_style)
        self.search_input.textChanged.connect(self.refresh_tasks)
        filters.addWidget(self.search_input, 2)

        lbl_category = QLabel("Category:")
        lbl_category.setStyleSheet(label_style)
        filters.addWidget(lbl_category)
        self.category_filter = QComboBox()
        self.category_filter.addItems(["All", "Business", "Personal"])
        self.category_filter.setStyleSheet(field_style)
        self.category_filter.currentTextChanged.connect(self.refresh_tasks)
        filters.addWidget(self.category_filter)

        lbl_date = QLabel("Date:")
        lbl_date.setStyleSheet(label_style)
        filters.addWidget(lbl_date)
        self.date_filter = QComboBox()
        self.date_filter.addItems(["All", "Today", "Overdue", "No Date", "Specific Date"])
        self.date_filter.setStyleSheet(field_style)
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
        self.specific_date.setStyleSheet(field_style)
        filters.addWidget(self.specific_date)

        self.show_completed = QCheckBox("Show completed")
        self.show_completed.setStyleSheet("QCheckBox { color: #b0b5bd; font-size: 12px; }")
        self.show_completed.stateChanged.connect(self.refresh_tasks)
        filters.addWidget(self.show_completed)

        self.show_snoozed = QCheckBox("Show snoozed")
        self.show_snoozed.setStyleSheet("QCheckBox { color: #b0b5bd; font-size: 12px; }")
        self.show_snoozed.stateChanged.connect(self.refresh_tasks)
        filters.addWidget(self.show_snoozed)

        filters.addStretch(1)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setStyleSheet(button_style)
        self.refresh_btn.clicked.connect(self.refresh_tasks)
        filters.addWidget(self.refresh_btn)

        layout.addLayout(filters)

        # Quick add row
        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 0, 0, 0)
        add_row.setSpacing(base_spacing)

        self.new_task_input = QLineEdit()
        self.new_task_input.setPlaceholderText("New task…")
        self.new_task_input.setStyleSheet(field_style)
        self.new_task_input.returnPressed.connect(self.add_task)
        add_row.addWidget(self.new_task_input, 2)

        self.new_task_category = QComboBox()
        self.new_task_category.addItems(["Business", "Personal"])
        self.new_task_category.setStyleSheet(field_style)
        add_row.addWidget(self.new_task_category)

        self.new_task_due = QLineEdit()
        self.new_task_due.setPlaceholderText("Due (MM-DD-YYYY, optional)")
        self.new_task_due.setStyleSheet(field_style)
        self.new_task_due.returnPressed.connect(self.add_task)
        add_row.addWidget(self.new_task_due)

        self.add_btn = QPushButton("Add")
        self.add_btn.setStyleSheet(primary_button_style)
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
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget { background-color: #1c1e24; color: #e8eaed; "
            "gridline-color: #2e2f32; border: 1px solid #2e2f32; border-radius: 6px; }"
            "QTableWidget::item { padding: 6px; }"
            "QTableWidget::item:selected { background-color: #2b313c; color: #ffffff; }"
            "QHeaderView::section { background-color: #22252c; color: #e8eaed; "
            "padding: 7px; border: 1px solid #2e2f32; font-weight: 600; }"
        )

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
                btn_edit.setStyleSheet(
                    "QPushButton { background-color: #3a3b3e; color: #e8eaed; border: 1px solid #2e2f32; "
                    "padding: 4px 8px; border-radius: 5px; font-size: 12px; }"
                    "QPushButton:hover { background-color: #4a4a4e; }"
                )
                btn_edit.clicked.connect(lambda _=False, rr=rdict: self._edit_task(rr))
                row.addWidget(btn_edit)
                btn_toggle = QPushButton("Undo" if done else "Complete")
                btn_toggle.setStyleSheet(
                    "QPushButton { background-color: #FD6262; color: white; border: none; "
                    "padding: 4px 9px; border-radius: 5px; font-size: 12px; font-weight: 600; }"
                    "QPushButton:hover { background-color: #e85555; }"
                )
                btn_toggle.clicked.connect(lambda _=False, tid=task_id, cur=done: self._toggle_done(tid, cur))
                row.addWidget(btn_toggle)
                btn_snooze = QPushButton("Snooze 1d")
                btn_snooze.setStyleSheet(
                    "QPushButton { background-color: #3a3b3e; color: #e8eaed; border: 1px solid #2e2f32; "
                    "padding: 4px 8px; border-radius: 5px; font-size: 12px; }"
                    "QPushButton:hover { background-color: #4a4a4e; }"
                )
                btn_snooze.clicked.connect(lambda _=False, tid=task_id: self._snooze_task(tid, days=1))
                row.addWidget(btn_snooze)
                btn_del = QPushButton("Delete")
                btn_del.setStyleSheet(
                    "QPushButton { background-color: #502a2a; color: #ffdede; border: 1px solid #6a3535; "
                    "padding: 4px 8px; border-radius: 5px; font-size: 12px; }"
                    "QPushButton:hover { background-color: #6a3535; }"
                )
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


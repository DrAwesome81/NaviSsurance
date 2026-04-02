from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QDateEdit,
)

from core.task_extract import SuggestedTask


def _qdate_from_mmddyyyy(value: str) -> QDate | None:
    text = (value or "").strip()
    if not text or text.lower() == "none":
        return None
    try:
        dt = datetime.strptime(text, "%m-%d-%Y")
    except Exception:
        return None
    return QDate(dt.year, dt.month, dt.day)


def _mmddyyyy_from_qdate(value: QDate) -> str:
    return value.toString("MM-dd-yyyy")


class OptionalDateCell(QWidget):
    """Calendar-backed due date widget that can also represent 'none'."""

    def __init__(self, due_value: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        parsed = _qdate_from_mmddyyyy(due_value)

        self.none_checkbox = QCheckBox("None", self)
        self.none_checkbox.setStyleSheet("color: #e8eaed;")
        self.none_checkbox.setChecked(parsed is None)
        layout.addWidget(self.none_checkbox)

        self.date_edit = QDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("MM-dd-yyyy")
        self.date_edit.setDate(parsed if parsed else QDate.currentDate())
        self.date_edit.setEnabled(parsed is not None)
        layout.addWidget(self.date_edit, 1)

        self.none_checkbox.toggled.connect(lambda checked: self.date_edit.setEnabled(not checked))

    def value(self) -> str:
        if self.none_checkbox.isChecked():
            return "none"
        return _mmddyyyy_from_qdate(self.date_edit.date())


class TaskImportDialog(QDialog):
    """
    Review/edit/accept suggested tasks before inserting them into SQLite.
    Returns selected tasks via selected_tasks().
    """

    def __init__(self, tasks: List[SuggestedTask], warnings: Optional[List[str]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Suggested Tasks")
        self._tasks = list(tasks or [])
        self._selected: List[SuggestedTask] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QLabel("Review the extracted tasks. Edit titles, due dates, categories, and priorities, then Apply.")
        header.setStyleSheet("color: #e8eaed; font-weight: 600;")
        layout.addWidget(header)

        if warnings:
            warn_btn = QPushButton(f"Show {len(warnings)} warning(s)…")
            warn_btn.setStyleSheet(
                "background-color: #3a3b3e; color: #e8eaed; border: 1px solid #2e2f32; "
                "padding: 6px 10px; border-radius: 6px;"
            )
            warn_btn.clicked.connect(lambda: QMessageBox.information(self, "Task extraction warnings", "\n".join(warnings)))
            layout.addWidget(warn_btn)

        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Import", "Task", "Due Date", "Category", "Priority"])
        self.table.setRowCount(len(self._tasks))
        self.table.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32;")
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked)

        for r, t in enumerate(self._tasks):
            import_item = QTableWidgetItem()
            import_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            import_item.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(r, 0, import_item)

            title_item = QTableWidgetItem(t.title)
            title_item.setFlags(title_item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 1, title_item)

            self.table.setCellWidget(r, 2, OptionalDateCell(t.due_mmddyyyy, parent=self.table))

            cat = QComboBox()
            cat.addItems(["Business", "Personal"])
            cat.setCurrentText(t.category if t.category in {"Business", "Personal"} else "Business")
            cat.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32;")
            self.table.setCellWidget(r, 3, cat)

            priority = QComboBox()
            for value in range(0, 6):
                priority.addItem(f"P{value}", value)
            current_priority = max(0, min(5, int(getattr(t, "priority", 0) or 0)))
            priority.setCurrentIndex(current_priority)
            priority.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32;")
            self.table.setCellWidget(r, 4, priority)

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(1, max(420, self.table.columnWidth(1)))
        self.table.setColumnWidth(2, max(220, self.table.columnWidth(2)))
        self.table.setColumnWidth(4, max(92, self.table.columnWidth(4)))
        layout.addWidget(self.table)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent=self)
        apply_btn = QPushButton("Apply")
        apply_btn.setDefault(True)
        apply_btn.setStyleSheet("background-color: #FD6262; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600;")
        apply_btn.clicked.connect(self._on_apply)

        btns.addButton(apply_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.setMinimumWidth(900)
        self.setMinimumHeight(520)

    def selected_tasks(self) -> List[SuggestedTask]:
        return list(self._selected)

    def _on_apply(self) -> None:
        selected: List[SuggestedTask] = []
        problems: List[str] = []

        for r in range(self.table.rowCount()):
            import_item = self.table.item(r, 0)
            if import_item is not None and import_item.checkState() != Qt.CheckState.Checked:
                continue

            title = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()

            due_widget = self.table.cellWidget(r, 2)
            due = "none"
            if isinstance(due_widget, OptionalDateCell):
                due = due_widget.value()

            cat_widget = self.table.cellWidget(r, 3)
            category = "Business"
            if isinstance(cat_widget, QComboBox):
                category = (cat_widget.currentText() or "Business").strip()

            priority_widget = self.table.cellWidget(r, 4)
            priority = 0
            if isinstance(priority_widget, QComboBox):
                priority = int(priority_widget.currentData() or 0)

            if not title:
                problems.append(f"Row {r+1}: empty task title.")
                continue

            if category not in {"Business", "Personal"}:
                problems.append(f"Row {r+1} ('{title}'): category must be Business or Personal.")
                continue

            if priority < 0 or priority > 5:
                problems.append(f"Row {r+1} ('{title}'): priority must be between P0 and P5.")
                continue

            selected.append(
                SuggestedTask(
                    title=title,
                    due_mmddyyyy=due,
                    category=category,
                    priority=priority,
                )
            )

        if problems:
            QMessageBox.warning(self, "Fix issues before importing", "\n".join(problems[:25]))
            return

        if not selected:
            QMessageBox.information(self, "Nothing to import", "No tasks selected.")
            return

        self._selected = selected
        self.accept()


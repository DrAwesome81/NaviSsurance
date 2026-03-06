from __future__ import annotations

from dataclasses import asdict
from typing import List, Optional

from PyQt6.QtCore import Qt
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
)

from core.task_extract import SuggestedTask


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

        header = QLabel("Review the extracted tasks. Edit titles/due dates/categories, then Apply.")
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
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Import", "Task", "Due (MM-DD-YYYY or none)", "Category"])
        self.table.setRowCount(len(self._tasks))
        self.table.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32;")
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked)

        for r, t in enumerate(self._tasks):
            cb = QCheckBox()
            cb.setChecked(True)
            cb.setStyleSheet("color: #e8eaed;")
            self.table.setCellWidget(r, 0, cb)

            title_item = QTableWidgetItem(t.title)
            title_item.setFlags(title_item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 1, title_item)

            due_item = QTableWidgetItem(t.due_mmddyyyy)
            due_item.setFlags(due_item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 2, due_item)

            cat = QComboBox()
            cat.addItems(["Business", "Personal"])
            cat.setCurrentText(t.category if t.category in {"Business", "Personal"} else "Business")
            cat.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32;")
            self.table.setCellWidget(r, 3, cat)

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(1, max(420, self.table.columnWidth(1)))
        self.table.setColumnWidth(2, max(200, self.table.columnWidth(2)))
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
            cb = self.table.cellWidget(r, 0)
            if isinstance(cb, QCheckBox) and not cb.isChecked():
                continue

            title = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
            due = (self.table.item(r, 2).text() if self.table.item(r, 2) else "").strip()

            cat_widget = self.table.cellWidget(r, 3)
            category = "Business"
            if isinstance(cat_widget, QComboBox):
                category = (cat_widget.currentText() or "Business").strip()

            if not title:
                problems.append(f"Row {r+1}: empty task title.")
                continue

            if not due:
                due = "none"
            if due.lower() not in {"none"}:
                # Keep validation lightweight here; core parser normalizes too.
                if not _looks_like_mmddyyyy(due):
                    problems.append(f"Row {r+1} ('{title}'): due date must be MM-DD-YYYY or 'none'.")
                    continue

            if category not in {"Business", "Personal"}:
                problems.append(f"Row {r+1} ('{title}'): category must be Business or Personal.")
                continue

            selected.append(SuggestedTask(title=title, due_mmddyyyy=due, category=category))

        if problems:
            QMessageBox.warning(self, "Fix issues before importing", "\n".join(problems[:25]))
            return

        if not selected:
            QMessageBox.information(self, "Nothing to import", "No tasks selected.")
            return

        self._selected = selected
        self.accept()


def _looks_like_mmddyyyy(s: str) -> bool:
    return bool(__import__("re").match(r"^\d{2}-\d{2}-\d{4}$", (s or "").strip()))


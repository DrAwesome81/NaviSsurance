from __future__ import annotations

import json
from datetime import datetime

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QDateEdit,
    QCheckBox,
    QDialogButtonBox,
)


def _qdate_from_mmddyyyy(s: str | None) -> QDate | None:
    ss = (s or "").strip()
    if not ss or ss.lower() == "unknown":
        return None
    try:
        dt = datetime.strptime(ss, "%m-%d-%Y")
        return QDate(dt.year, dt.month, dt.day)
    except Exception:
        return None


def _mmddyyyy_from_qdate(d: QDate) -> str:
    return d.toString("MM-dd-yyyy")


class TaskEditDialog(QDialog):
    def __init__(self, *, parent=None, task: dict):
        super().__init__(parent)
        self.setWindowTitle("Edit Task")
        self._task = task or {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Task:"))
        self.task_text = QLineEdit()
        self.task_text.setText(str(self._task.get("task_text") or self._task.get("text") or "").strip())
        layout.addWidget(self.task_text)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QLabel("Category:"))
        self.category = QComboBox()
        self.category.addItems(["Business", "Personal"])
        cur_cat = str(self._task.get("category") or "Business")
        self.category.setCurrentText(cur_cat if cur_cat in {"Business", "Personal"} else "Business")
        row1.addWidget(self.category)
        row1.addWidget(QLabel("Priority:"))
        self.priority = QSpinBox()
        self.priority.setRange(0, 5)
        try:
            self.priority.setValue(int(self._task.get("priority") or 0))
        except Exception:
            self.priority.setValue(0)
        row1.addWidget(self.priority)
        row1.addStretch(1)
        layout.addLayout(row1)

        layout.addWidget(QLabel("Tags (comma-separated):"))
        self.tags = QLineEdit()
        tags_json = self._task.get("tags_json")
        tags_val = ""
        try:
            if tags_json:
                arr = json.loads(tags_json)
                if isinstance(arr, list):
                    tags_val = ", ".join(str(x) for x in arr if str(x).strip())
        except Exception:
            tags_val = str(tags_json or "")
        self.tags.setText(tags_val)
        layout.addWidget(self.tags)

        # Dates
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        self.due_enabled = QCheckBox("Due:")
        self.due_enabled.setChecked(bool((self._task.get("due_date") or "").strip()))
        row2.addWidget(self.due_enabled)
        self.due_date = QDateEdit()
        self.due_date.setCalendarPopup(True)
        qd = _qdate_from_mmddyyyy(self._task.get("due_date"))
        self.due_date.setDate(qd if qd else QDate.currentDate())
        row2.addWidget(self.due_date)

        self.next_enabled = QCheckBox("Next action:")
        self.next_enabled.setChecked(bool((self._task.get("next_action_date") or "").strip()))
        row2.addWidget(self.next_enabled)
        self.next_action = QDateEdit()
        self.next_action.setCalendarPopup(True)
        qn = _qdate_from_mmddyyyy(self._task.get("next_action_date"))
        self.next_action.setDate(qn if qn else QDate.currentDate())
        row2.addWidget(self.next_action)

        self.snooze_enabled = QCheckBox("Snoozed until:")
        self.snooze_enabled.setChecked(bool((self._task.get("snoozed_until") or "").strip()))
        row2.addWidget(self.snooze_enabled)
        self.snoozed_until = QDateEdit()
        self.snoozed_until.setCalendarPopup(True)
        qs = _qdate_from_mmddyyyy(self._task.get("snoozed_until"))
        self.snoozed_until.setDate(qs if qs else QDate.currentDate())
        row2.addWidget(self.snoozed_until)

        layout.addLayout(row2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        text = (self.task_text.text() or "").strip()
        category = (self.category.currentText() or "Business").strip() or "Business"
        priority = int(self.priority.value() or 0)

        tags_raw = (self.tags.text() or "").strip()
        tags = []
        if tags_raw:
            for t in tags_raw.split(","):
                tt = t.strip()
                if tt:
                    tags.append(tt)
        tags_json = json.dumps(tags, ensure_ascii=False)

        due = _mmddyyyy_from_qdate(self.due_date.date()) if self.due_enabled.isChecked() else None
        next_action = _mmddyyyy_from_qdate(self.next_action.date()) if self.next_enabled.isChecked() else None
        snoozed = _mmddyyyy_from_qdate(self.snoozed_until.date()) if self.snooze_enabled.isChecked() else None

        return {
            "task_text": text,
            "category": category,
            "priority": priority,
            "tags_json": tags_json,
            "due_date": due,
            "next_action_date": next_action,
            "snoozed_until": snoozed,
        }


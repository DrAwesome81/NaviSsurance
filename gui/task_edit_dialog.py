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

        row1b = QHBoxLayout()
        row1b.addWidget(QLabel("Assigned To:"))
        self.assigned_to = QComboBox()
        self.assigned_to.setEditable(True)
        self.assigned_to.addItem("")
        if self.assigned_to.lineEdit() is not None:
            self.assigned_to.lineEdit().setPlaceholderText("Assigned to (optional)")
        db = getattr(self.parent(), "db", None)
        if db is not None:
            try:
                for row in (db.agents_list_active() or []):
                    label = str(row.get("display_name") or row.get("code") or "").strip()
                    if label:
                        self.assigned_to.addItem(label)
            except Exception:
                pass
        cur_assignee = str(self._task.get("assigned_to") or "").strip()
        if cur_assignee:
            idx = self.assigned_to.findText(cur_assignee)
            if idx >= 0:
                self.assigned_to.setCurrentIndex(idx)
            else:
                self.assigned_to.setEditText(cur_assignee)
        row1b.addWidget(self.assigned_to)

        row1b.addWidget(QLabel("Project:"))
        self.project_combo = QComboBox()
        self.project_combo.addItem("(None)", None)
        if db is not None:
            try:
                for row in (db.cos_get_projects() or []):
                    pid, name = row[0], (row[1] or "").strip() or f"Project {row[0]}"
                    self.project_combo.addItem(name, int(pid))
            except Exception:
                pass
        cur_proj = self._task.get("cos_project_id")
        if cur_proj is not None:
            try:
                idx = self.project_combo.findData(int(cur_proj))
                if idx >= 0:
                    self.project_combo.setCurrentIndex(idx)
            except Exception:
                pass
        row1b.addWidget(self.project_combo)
        row1b.addStretch(1)
        layout.addLayout(row1b)

        # Scheduling / effort / dependencies
        row_effort = QHBoxLayout()
        row_effort.setSpacing(8)
        row_effort.addWidget(QLabel("Estimate (minutes):"))
        self.estimate_minutes = QSpinBox()
        self.estimate_minutes.setRange(0, 100000)
        try:
            self.estimate_minutes.setValue(int(self._task.get("estimate_minutes") or 0))
        except Exception:
            self.estimate_minutes.setValue(0)
        row_effort.addWidget(self.estimate_minutes)

        self.start_enabled = QCheckBox("Start:")
        self.start_enabled.setChecked(bool((self._task.get("start_date") or "").strip()))
        row_effort.addWidget(self.start_enabled)
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        qs0 = _qdate_from_mmddyyyy(self._task.get("start_date"))
        self.start_date.setDate(qs0 if qs0 else QDate.currentDate())
        row_effort.addWidget(self.start_date)
        row_effort.addStretch(1)
        layout.addLayout(row_effort)

        layout.addWidget(QLabel("Blockers (free text):"))
        self.blockers = QLineEdit()
        self.blockers.setText(str(self._task.get("blockers") or "").strip())
        layout.addWidget(self.blockers)

        layout.addWidget(QLabel("Dependencies (task IDs, comma-separated):"))
        self.depends_on = QLineEdit()
        dep_val = ""
        dep_json = self._task.get("depends_on_json")
        try:
            if dep_json:
                arr = json.loads(dep_json)
                if isinstance(arr, list):
                    dep_val = ", ".join(str(int(x)) for x in arr if str(x).strip())
        except Exception:
            dep_val = str(dep_json or "")
        self.depends_on.setText(dep_val)
        layout.addWidget(self.depends_on)

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
        snoozed = _mmddyyyy_from_qdate(self.snoozed_until.date()) if self.snooze_enabled.isChecked() else None
        start_date = _mmddyyyy_from_qdate(self.start_date.date()) if self.start_enabled.isChecked() else None

        blockers = (self.blockers.text() or "").strip() or None
        assigned_to = (self.assigned_to.currentText() or "").strip() or None

        depends_raw = (self.depends_on.text() or "").strip()
        depends_ids: list[int] = []
        if depends_raw:
            for part in depends_raw.split(","):
                p = part.strip()
                if not p:
                    continue
                try:
                    depends_ids.append(int(p))
                except Exception:
                    continue
        depends_on_json = json.dumps(sorted(set(depends_ids)), ensure_ascii=False)

        cos_project_id = self.project_combo.currentData()
        return {
            "task_text": text,
            "category": category,
            "priority": priority,
            "tags_json": tags_json,
            "assigned_to": assigned_to,
            "due_date": due,
            "start_date": start_date,
            "estimate_minutes": int(self.estimate_minutes.value() or 0),
            "blockers": blockers,
            "depends_on_json": depends_on_json,
            "snoozed_until": snoozed,
            "cos_project_id": int(cos_project_id) if cos_project_id is not None else None,
        }


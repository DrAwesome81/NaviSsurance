"""
Project management panel: project list (cos_projects) and Gantt chart.
Used as a sub-tab inside the Tasks tab.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta
from typing import Any

from PyQt6.QtCore import Qt, QRectF, QDate
from PyQt6.QtGui import QPainter, QColor, QFont, QPen
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QComboBox,
    QDateEdit,
    QCheckBox,
    QFormLayout,
    QSplitter,
    QFrame,
    QScrollArea,
)

from core.db import DatabaseManager

logger = logging.getLogger(__name__)

# cos_get_projects row indices (match SELECT order in db.py)
_COS_ID, _COS_NAME, _COS_CLIENT, _COS_DESC, _COS_STATUS, _COS_PRIORITY, _COS_DEADLINE, _COS_NEXT_ACTION = 0, 1, 2, 3, 4, 5, 6, 7
_COS_BLOCKERS, _COS_TAGS, _COS_LAST_TOUCHED, _COS_CREATED_AT, _COS_UPDATED_AT = 8, 9, 10, 11, 12


def _row_to_dict(row: tuple) -> dict[str, Any]:
    if not row or len(row) < 13:
        return {}
    return {
        "id": row[_COS_ID],
        "name": row[_COS_NAME] or "",
        "client": row[_COS_CLIENT] or "",
        "description": row[_COS_DESC] or "",
        "status": row[_COS_STATUS] or "",
        "priority": row[_COS_PRIORITY],
        "deadline": row[_COS_DEADLINE] or "",
        "next_action": row[_COS_NEXT_ACTION] or "",
        "blockers": row[_COS_BLOCKERS] or "",
        "tags": row[_COS_TAGS] or "",
        "last_touched": row[_COS_LAST_TOUCHED] or "",
        "created_at": row[_COS_CREATED_AT] or "",
        "updated_at": row[_COS_UPDATED_AT] or "",
        "client_id": row[-1] if len(row) >= 23 else None,
    }


def _parse_date(s: str | None) -> datetime | None:
    if not (s or "").strip():
        return None
    s = s.strip()
    # ISO with T
    if "T" in s:
        try:
            return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            pass
    # date only
    for fmt in ("%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(s[:10], fmt)
        except Exception:
            continue
    return None


class GanttChartWidget(QWidget):
    """Simple Gantt: timeline (x = dates), one row per project, bar from start to end."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setStyleSheet("background-color: #1c1e24; border: 1px solid #2e2f32; border-radius: 6px;")
        self._projects: list[dict] = []  # [{id, name, start_date, end_date}, ...]
        self._day_width = 14
        self._row_height = 28
        self._header_height = 32
        self._label_width = 160
        self._min_chart_width = 0

    def set_projects(self, projects: list[dict]):
        self._projects = list(projects)
        min_d = max_d = None
        for proj in self._projects:
            start = proj.get("start_date")
            end = proj.get("end_date")
            if start:
                d = start.date() if hasattr(start, "date") else start
                min_d = min(min_d, d) if min_d else d
            if end:
                d = end.date() if hasattr(end, "date") else end
                max_d = max(max_d, d) if max_d else d
        if min_d and max_d:
            total_days = max(1, (max_d - min_d).days + 1)
            self._min_chart_width = self._label_width + total_days * self._day_width
        else:
            self._min_chart_width = self._label_width + 90 * self._day_width
        self.setMinimumWidth(min(self._min_chart_width, 1200))
        self.update()

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        h = self._header_height + len(self._projects) * self._row_height if self._projects else 220
        return QSize(self._min_chart_width or 600, max(220, h))

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._projects:
            p = QPainter(self)
            p.setPen(QColor("#9aa0a6"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No projects with dates to display")
            return

        # Compute date range from all projects
        min_d = max_d = None
        for proj in self._projects:
            start = proj.get("start_date")
            end = proj.get("end_date")
            if start:
                min_d = min(min_d, start) if min_d else start
            if end:
                max_d = max(max_d, end) if max_d else end
        if not min_d:
            min_d = datetime.now().date()
        if not max_d:
            max_d = (datetime.now() + timedelta(days=30)).date()
        if hasattr(min_d, "date"):
            min_d = min_d.date()
        if hasattr(max_d, "date"):
            max_d = max_d.date()
        total_days = max(1, (max_d - min_d).days + 1)
        chart_width = total_days * self._day_width
        total_width = self._label_width + chart_width

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont()
        font.setPointSize(9)
        p.setFont(font)

        # Header: date labels
        p.fillRect(0, 0, total_width, self._header_height, QColor("#22252c"))
        p.setPen(QColor("#e8eaed"))
        for i in range(0, total_days, max(1, total_days // 12)):
            d = min_d + timedelta(days=i)
            x = self._label_width + i * self._day_width
            p.drawText(int(x) + 2, self._header_height - 6, d.strftime("%m/%d"))

        # Grid and bars
        for row_idx, proj in enumerate(self._projects):
            y = self._header_height + row_idx * self._row_height
            # Row background
            if row_idx % 2 == 1:
                p.fillRect(0, int(y), total_width, self._row_height, QColor("#25272e"))
            # Name label
            p.setPen(QColor("#e8eaed"))
            name = (proj.get("name") or "")[:22]
            p.drawText(8, int(y + self._row_height - 8), name)
            # Bar
            start_d = proj.get("start_date")
            end_d = proj.get("end_date")
            if hasattr(start_d, "date"):
                start_d = start_d.date()
            if hasattr(end_d, "date"):
                end_d = end_d.date()
            if start_d and end_d and start_d <= end_d:
                try:
                    left = self._label_width + (start_d - min_d).days * self._day_width
                    w = max(4, (end_d - start_d).days * self._day_width)
                    bar_rect = QRectF(left, y + 4, w, self._row_height - 8)
                    p.fillRect(bar_rect, QColor("#4a7c9e"))
                    p.setPen(QPen(QColor("#6b8cae"), 1))
                    p.drawRect(bar_rect)
                except Exception:
                    pass
            p.setPen(QColor("#2e2f32"))
            p.drawLine(0, int(y + self._row_height), total_width, int(y + self._row_height))

        p.end()


class TaskGanttChartWidget(QWidget):
    """
    Task-level Gantt for one project.

    Rows are tasks. Uses:
    - start_date (preferred) or derived from due_date - duration
    - due_date (preferred end) or start + duration
    - estimate_minutes for rough duration (>= 1 day)
    - depends_on_json for dependency arrows (task_id list)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setStyleSheet("background-color: #1c1e24; border: 1px solid #2e2f32; border-radius: 6px;")
        self._tasks: list[dict[str, Any]] = []
        self._day_width = 14
        self._row_height = 28
        self._header_height = 32
        self._label_width = 260
        self._min_chart_width = 0

    def set_day_width(self, day_width: int) -> None:
        self._day_width = int(max(6, min(60, day_width)))
        self.set_tasks(self._tasks)

    def set_tasks(self, tasks: list[dict[str, Any]]):
        self._tasks = list(tasks or [])
        min_d = max_d = None
        for t in self._tasks:
            start = t.get("start_date")
            end = t.get("end_date")
            if start:
                d = start.date() if hasattr(start, "date") else start
                min_d = min(min_d, d) if min_d else d
            if end:
                d = end.date() if hasattr(end, "date") else end
                max_d = max(max_d, d) if max_d else d
        if min_d and max_d:
            total_days = max(1, (max_d - min_d).days + 1)
            self._min_chart_width = self._label_width + total_days * self._day_width
        else:
            self._min_chart_width = self._label_width + 60 * self._day_width
        self.setMinimumWidth(min(self._min_chart_width, 1600))
        self.update()

    def sizeHint(self):
        from PyQt6.QtCore import QSize

        h = self._header_height + len(self._tasks) * self._row_height if self._tasks else 220
        return QSize(self._min_chart_width or 600, max(220, h))

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._tasks:
            p = QPainter(self)
            p.setPen(QColor("#9aa0a6"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Select a project to view its tasks timeline")
            return

        # Compute date range
        min_d = max_d = None
        for t in self._tasks:
            start = t.get("start_date")
            end = t.get("end_date")
            if start:
                min_d = min(min_d, start) if min_d else start
            if end:
                max_d = max(max_d, end) if max_d else end
        if not min_d:
            min_d = datetime.now().date()
        if not max_d:
            max_d = (datetime.now() + timedelta(days=30)).date()
        if hasattr(min_d, "date"):
            min_d = min_d.date()
        if hasattr(max_d, "date"):
            max_d = max_d.date()
        # Pad range slightly for readability
        min_d = min_d - timedelta(days=1)
        max_d = max_d + timedelta(days=1)

        total_days = max(1, (max_d - min_d).days + 1)
        chart_width = total_days * self._day_width
        total_width = self._label_width + chart_width

        today = datetime.now().date()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont()
        font.setPointSize(9)
        p.setFont(font)

        # Header
        p.fillRect(0, 0, total_width, self._header_height, QColor("#22252c"))
        p.setPen(QColor("#e8eaed"))
        # Use more frequent ticks when zoomed in
        tick_every = max(1, total_days // (14 if self._day_width >= 18 else 10))
        for i in range(0, total_days, tick_every):
            d = min_d + timedelta(days=i)
            x = self._label_width + i * self._day_width
            p.drawText(int(x) + 2, self._header_height - 6, d.strftime("%m/%d"))

        # Today line
        if min_d <= today <= max_d:
            x_today = self._label_width + (today - min_d).days * self._day_width
            p.setPen(QPen(QColor("#FD6262"), 2))
            p.drawLine(int(x_today), 0, int(x_today), self._header_height + len(self._tasks) * self._row_height)
            p.setPen(QColor("#FD6262"))
            p.drawText(int(x_today) + 4, 12, "Today")

        # Bars + record positions for dependency drawing
        pos: dict[int, dict[str, float]] = {}
        for row_idx, t in enumerate(self._tasks):
            y = self._header_height + row_idx * self._row_height
            if row_idx % 2 == 1:
                p.fillRect(0, int(y), total_width, self._row_height, QColor("#25272e"))

            task_id = int(t.get("id") or 0)
            label = t.get("label") or ""
            if not label:
                label = f"#{task_id}"
            label = str(label)
            if len(label) > 40:
                label = label[:37] + "…"

            p.setPen(QColor("#e8eaed"))
            p.drawText(8, int(y + self._row_height - 8), label)

            start_d = t.get("start_date")
            end_d = t.get("end_date")
            if hasattr(start_d, "date"):
                start_d = start_d.date()
            if hasattr(end_d, "date"):
                end_d = end_d.date()

            if start_d and end_d and start_d <= end_d:
                left = self._label_width + (start_d - min_d).days * self._day_width
                # Inclusive end for visibility
                w = max(4, ((end_d - start_d).days + 1) * self._day_width)
                bar_rect = QRectF(left, y + 4, w, self._row_height - 8)

                completed = bool(t.get("completed"))
                overdue = bool(t.get("overdue"))
                due_soon = bool(t.get("due_soon"))
                unscheduled = bool(t.get("unscheduled"))

                if completed:
                    fill = QColor("#2e7d32")
                    stroke = QColor("#52b45a")
                elif overdue:
                    fill = QColor("#8d2b2b")
                    stroke = QColor("#FD6262")
                elif due_soon:
                    fill = QColor("#6f5b1a")
                    stroke = QColor("#f6c343")
                elif unscheduled:
                    fill = QColor("#3a3b3e")
                    stroke = QColor("#9aa0a6")
                else:
                    fill = QColor("#4a7c9e")
                    stroke = QColor("#6b8cae")

                p.fillRect(bar_rect, fill)
                p.setPen(QPen(stroke, 1))
                p.drawRect(bar_rect)

                pos[task_id] = {
                    "x1": float(bar_rect.left()),
                    "x2": float(bar_rect.right()),
                    "y": float(y + self._row_height / 2),
                }

            p.setPen(QColor("#2e2f32"))
            p.drawLine(0, int(y + self._row_height), total_width, int(y + self._row_height))

        # Dependency arrows (draw after bars so they appear on top)
        p.setPen(QPen(QColor("#9aa0a6"), 1))
        for t in self._tasks:
            to_id = int(t.get("id") or 0)
            to_pos = pos.get(to_id)
            if not to_pos:
                continue
            deps = t.get("depends_on_ids") or []
            for from_id in deps:
                try:
                    from_id_i = int(from_id)
                except Exception:
                    continue
                from_pos = pos.get(from_id_i)
                if not from_pos:
                    continue
                x1 = from_pos["x2"]
                y1 = from_pos["y"]
                x2 = to_pos["x1"]
                y2 = to_pos["y"]
                mid_x = (x1 + x2) / 2.0
                p.drawLine(int(x1), int(y1), int(mid_x), int(y1))
                p.drawLine(int(mid_x), int(y1), int(mid_x), int(y2))
                p.drawLine(int(mid_x), int(y2), int(x2), int(y2))
                # arrow head
                ah = 5
                p.drawLine(int(x2), int(y2), int(x2 - ah), int(y2 - ah))
                p.drawLine(int(x2), int(y2), int(x2 - ah), int(y2 + ah))

        p.end()


class ProjectEditDialog(QDialog):
    """Simple add/edit project dialog (name, client, status, deadline)."""

    def __init__(self, parent=None, project: dict | None = None, db: DatabaseManager | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit project" if project else "Add project")
        self._project = project or {}
        self._db = db
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Project name")
        self.name_edit.setText(self._project.get("name") or "")
        form.addRow("Name:", self.name_edit)
        self.client_combo = QComboBox()
        self.client_combo.addItem("Unlinked", None)
        try:
            clients = self._db.clients_list(active_only=True) if self._db is not None else []
        except Exception:
            clients = []
        current_client_id = self._project.get("client_id")
        for client in clients:
            try:
                cid = int(client.get("id"))
                cname = str(client.get("name") or "").strip()
            except Exception:
                continue
            self.client_combo.addItem(cname or f"Client {cid}", cid)
            if current_client_id is not None and cid == int(current_client_id):
                self.client_combo.setCurrentIndex(self.client_combo.count() - 1)
        form.addRow("Linked client:", self.client_combo)
        self.client_edit = QLineEdit()
        self.client_edit.setPlaceholderText("Client (optional)")
        self.client_edit.setText(self._project.get("client") or "")
        self.client_combo.currentIndexChanged.connect(self._sync_client_text_from_combo)
        form.addRow("Client:", self.client_edit)
        self.status_combo = QComboBox()
        self.status_combo.addItems(["Active", "Waiting", "On Hold", "Done", "Cancelled"])
        self.status_combo.setCurrentText(self._project.get("status") or "Active")
        form.addRow("Status:", self.status_combo)
        deadline_row = QHBoxLayout()
        self.deadline_enabled = QCheckBox("Set deadline")
        deadline_row.addWidget(self.deadline_enabled)
        self.deadline_edit = QDateEdit()
        self.deadline_edit.setCalendarPopup(True)
        self.deadline_edit.setDisplayFormat("yyyy-MM-dd")
        self.deadline_edit.setDate(QDate.currentDate())
        deadline_row.addWidget(self.deadline_edit)
        deadline_row.addStretch(1)
        dl = self._project.get("deadline") or ""
        if dl and len(dl) >= 10:
            try:
                dt = datetime.strptime(dl[:10], "%Y-%m-%d")
                self.deadline_edit.setDate(QDate(dt.year, dt.month, dt.day))
                self.deadline_enabled.setChecked(True)
            except Exception:
                self.deadline_enabled.setChecked(False)
        else:
            self.deadline_enabled.setChecked(False)
        self.deadline_edit.setEnabled(bool(self.deadline_enabled.isChecked()))
        self.deadline_enabled.toggled.connect(lambda checked: self.deadline_edit.setEnabled(bool(checked)))
        form.addRow("Deadline:", deadline_row)
        layout.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _sync_client_text_from_combo(self):
        current_text = self.client_combo.currentText() or ""
        if current_text and current_text != "Unlinked" and not (self.client_edit.text() or "").strip():
            self.client_edit.setText(current_text)

    def values(self) -> dict:
        deadline = self.deadline_edit.date().toString("yyyy-MM-dd") if self.deadline_enabled.isChecked() else None
        return {
            "name": (self.name_edit.text() or "").strip(),
            "client": (self.client_edit.text() or "").strip(),
            "client_id": self.client_combo.currentData(),
            "status": self.status_combo.currentText() or "Active",
            "deadline": deadline,
        }


class ProjectManagementPanel(QWidget):
    """Project list table + Gantt chart. Uses cos_projects."""

    def __init__(self, parent=None, db: DatabaseManager | None = None):
        super().__init__(parent)
        self.db = db or getattr(parent, "db", None)
        if self.db is None:
            self.db = DatabaseManager()
        self._setup_ui()
        self.refresh_projects()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()
        btn_style = (
            "QPushButton { background-color: #3a3b3e; color: #e8eaed; border: 1px solid #2e2f32; "
            "padding: 6px 10px; border-radius: 6px; }"
            "QPushButton:hover { background-color: #4a4a4e; }"
        )
        primary_style = (
            "QPushButton { background-color: #FD6262; color: white; border: none; "
            "padding: 6px 12px; border-radius: 6px; font-weight: 600; }"
            "QPushButton:hover { background-color: #e85555; }"
        )
        self.add_btn = QPushButton("Add project")
        self.add_btn.setStyleSheet(primary_style)
        self.add_btn.clicked.connect(self._add_project)
        toolbar.addWidget(self.add_btn)
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setStyleSheet(btn_style)
        self.edit_btn.clicked.connect(self._edit_selected)
        toolbar.addWidget(self.edit_btn)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setStyleSheet(btn_style)
        self.delete_btn.clicked.connect(self._delete_selected)
        toolbar.addWidget(self.delete_btn)
        toolbar.addStretch(1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setStyleSheet(btn_style)
        self.refresh_btn.clicked.connect(self.refresh_projects)
        toolbar.addWidget(self.refresh_btn)
        layout.addLayout(toolbar)

        # Filter / sort row
        filter_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter by name, client, or status…")
        self.search_input.setStyleSheet(
            "QLineEdit { background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; "
            "padding: 6px 8px; border-radius: 6px; }"
        )
        self.search_input.textChanged.connect(self.refresh_projects)
        filter_row.addWidget(self.search_input, 2)
        filter_row.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Last touched", "Deadline", "Name", "Priority"])
        self.sort_combo.setStyleSheet(
            "QComboBox { background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; padding: 6px 8px; }"
        )
        self.sort_combo.currentIndexChanged.connect(self.refresh_projects)
        filter_row.addWidget(self.sort_combo)
        layout.addLayout(filter_row)

        # Splitter: table top, Gantt bottom
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Project table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Name", "Client", "Status", "Deadline", "Next action"])
        self.table.setColumnHidden(0, True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(
            "QTableWidget { background-color: #1c1e24; color: #e8eaed; "
            "gridline-color: #2e2f32; border: 1px solid #2e2f32; border-radius: 6px; }"
            "QHeaderView::section { background-color: #22252c; color: #e8eaed; padding: 7px; }"
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        splitter.addWidget(self.table)

        # Gantt chart(s)
        gantt_frame = QFrame()
        gantt_layout = QVBoxLayout(gantt_frame)
        gantt_layout.setContentsMargins(0, 8, 0, 0)
        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("Gantt:"))
        self.gantt_view = QComboBox()
        self.gantt_view.addItems(["Projects (created → deadline)", "Selected project tasks"])
        self.gantt_view.setStyleSheet(
            "QComboBox { background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; padding: 6px 8px; }"
        )
        self.gantt_view.currentIndexChanged.connect(self._refresh_gantt_view)
        header_row.addWidget(self.gantt_view)

        header_row.addStretch(1)
        header_row.addWidget(QLabel("Zoom:"))
        self.zoom_combo = QComboBox()
        self.zoom_combo.addItems(["Compact", "Normal", "Wide"])
        self.zoom_combo.setCurrentText("Normal")
        self.zoom_combo.setStyleSheet(
            "QComboBox { background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; padding: 6px 8px; }"
        )
        self.zoom_combo.currentIndexChanged.connect(self._apply_gantt_zoom)
        header_row.addWidget(self.zoom_combo)
        gantt_layout.addLayout(header_row)

        self.project_gantt = GanttChartWidget(self)
        self.task_gantt = TaskGanttChartWidget(self)

        self._project_scroll = QScrollArea()
        self._project_scroll.setWidget(self.project_gantt)
        self._project_scroll.setWidgetResizable(True)
        self._project_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._project_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        gantt_layout.addWidget(self._project_scroll)

        self._task_scroll = QScrollArea()
        self._task_scroll.setWidget(self.task_gantt)
        self._task_scroll.setWidgetResizable(True)
        self._task_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._task_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self._task_scroll.setVisible(False)
        gantt_layout.addWidget(self._task_scroll)

        splitter.addWidget(gantt_frame)
        splitter.setSizes([320, 280])

        layout.addWidget(splitter)
        self.table.itemSelectionChanged.connect(self._refresh_task_gantt_if_visible)

        self._apply_gantt_zoom()

    def _apply_gantt_zoom(self):
        z = (self.zoom_combo.currentText() or "Normal").strip().lower()
        if z == "compact":
            day_w = 10
        elif z == "wide":
            day_w = 22
        else:
            day_w = 14
        try:
            self.project_gantt._day_width = day_w  # noqa: SLF001 (local widget field)
            self.project_gantt.set_projects(getattr(self.project_gantt, "_projects", []))
        except Exception:
            pass
        try:
            self.task_gantt.set_day_width(day_w)
        except Exception:
            pass

    def _refresh_gantt_view(self):
        is_tasks = int(self.gantt_view.currentIndex() or 0) == 1
        self._project_scroll.setVisible(not is_tasks)
        self._task_scroll.setVisible(is_tasks)
        if is_tasks:
            self._refresh_task_gantt()

    def _selected_project_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        try:
            return int(self.table.item(row, 0).text())
        except Exception:
            return None

    def _refresh_task_gantt_if_visible(self):
        if self._task_scroll.isVisible():
            self._refresh_task_gantt()

    def _refresh_task_gantt(self):
        pid = self._selected_project_id()
        if not pid:
            self.task_gantt.set_tasks([])
            return
        try:
            tasks = self.db.list_tasks_rich(
                include_completed=False,
                include_snoozed=True,
                cos_project_id=int(pid),
                limit=500,
            )
        except Exception:
            tasks = []

        today = datetime.now().date()
        prepared: list[dict[str, Any]] = []
        for r in tasks:
            tid = int(r.get("id") or 0)
            text = str(r.get("task_text") or "").strip()
            due = _parse_date(r.get("due_date"))
            start = _parse_date(r.get("start_date"))
            completed = bool(int(r.get("completed") or 0))
            est_min = int(r.get("estimate_minutes") or 0)
            duration_days = max(1, int(math.ceil((est_min or 0) / (8 * 60))) if est_min else 1)

            # derive schedule
            start_d = start.date() if start else None
            due_d = due.date() if due else None
            if start_d is None and due_d is not None:
                start_d = due_d - timedelta(days=max(0, duration_days - 1))
            if start_d is None:
                start_d = today
            end_d = due_d if due_d is not None else (start_d + timedelta(days=max(0, duration_days - 1)))

            depends_ids: list[int] = []
            try:
                arr = json.loads(r.get("depends_on_json") or "[]")
                if isinstance(arr, list):
                    depends_ids = [int(x) for x in arr if str(x).strip().isdigit()]
            except Exception:
                depends_ids = []

            overdue = bool((due_d is not None) and (due_d < today) and (not completed))
            due_soon = bool((due_d is not None) and (not overdue) and (0 <= (due_d - today).days <= 7) and (not completed))
            unscheduled = bool((r.get("due_date") or "").strip() == "" and (r.get("start_date") or "").strip() == "")

            prepared.append(
                {
                    "id": tid,
                    "label": f"#{tid} {text}",
                    "start_date": start_d,
                    "end_date": end_d,
                    "completed": completed,
                    "overdue": overdue,
                    "due_soon": due_soon,
                    "unscheduled": unscheduled,
                    "depends_on_ids": depends_ids,
                }
            )

        # stable sort: earlier start, then due, then id
        prepared.sort(key=lambda t: (t.get("start_date"), t.get("end_date"), int(t.get("id") or 0)))
        self.task_gantt.set_tasks(prepared)

    def refresh_projects(self):
        try:
            rows = self.db.cos_get_projects()
            search_l = (self.search_input.text() or "").strip().lower()
            sort_by = (self.sort_combo.currentText() or "Last touched").strip().lower()
            dicts = [_row_to_dict(row) for row in rows]
            dicts = [d for d in dicts if d]
            if search_l:
                dicts = [
                    d for d in dicts
                    if search_l in (d.get("name") or "").lower()
                    or search_l in (d.get("client") or "").lower()
                    or search_l in (d.get("status") or "").lower()
                ]
            if sort_by == "deadline":
                dicts.sort(key=lambda d: (d.get("deadline") or "") or "z")
            elif sort_by == "name":
                dicts.sort(key=lambda d: (d.get("name") or "").lower())
            elif sort_by == "priority":
                dicts.sort(key=lambda d: (-(d.get("priority") or 0), (d.get("name") or "")))
            else:
                dicts.sort(key=lambda d: (d.get("last_touched") or ""), reverse=True)
            self.table.setRowCount(0)
            gantt_projects = []
            for d in dicts:
                r = self.table.rowCount()
                self.table.insertRow(r)
                self.table.setItem(r, 0, QTableWidgetItem(str(d.get("id", ""))))
                self.table.setItem(r, 1, QTableWidgetItem(d.get("name", "")))
                self.table.setItem(r, 2, QTableWidgetItem(d.get("client", "")))
                self.table.setItem(r, 3, QTableWidgetItem(d.get("status", "")))
                self.table.setItem(r, 4, QTableWidgetItem((d.get("deadline") or "")[:10] if d.get("deadline") else ""))
                self.table.setItem(r, 5, QTableWidgetItem((d.get("next_action") or "")[:40]))
                # Gantt: start from created_at, end from deadline
                created = _parse_date(d.get("created_at"))
                deadline = _parse_date(d.get("deadline"))
                if created:
                    start_d = created.date() if hasattr(created, "date") else created
                else:
                    start_d = datetime.now().date()
                if deadline:
                    end_d = deadline.date() if hasattr(deadline, "date") else deadline
                else:
                    end_d = (datetime.now() + timedelta(days=14)).date()
                if start_d and end_d and end_d < start_d:
                    end_d = start_d
                gantt_projects.append({
                    "id": d.get("id"),
                    "name": d.get("name", ""),
                    "start_date": start_d,
                    "end_date": end_d,
                })
            self.project_gantt.set_projects(gantt_projects)
            # Keep a selection so "Selected project tasks" shows something immediately.
            if self.table.rowCount() > 0 and self.table.currentRow() < 0:
                self.table.selectRow(0)
            self._refresh_task_gantt_if_visible()
        except Exception as e:
            logger.exception("refresh_projects failed: %s", e)
            QMessageBox.warning(self, "Projects", f"Could not load projects:\n{e}")

    def _add_project(self):
        dlg = ProjectEditDialog(self, project=None, db=self.db)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.values()
        if not vals.get("name"):
            QMessageBox.warning(self, "Projects", "Name is required.")
            return
        try:
            self.db.cos_insert_project(
                name=vals["name"],
                client=vals["client"] or None,
                status=vals["status"],
                deadline=vals["deadline"],
            )
            self.refresh_projects()
        except Exception as e:
            QMessageBox.warning(self, "Projects", f"Could not add project:\n{e}")

    def _edit_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Projects", "Select a project to edit.")
            return
        pid = self.table.item(row, 0).text()
        try:
            proj_id = int(pid)
        except Exception:
            return
        raw = self.db.cos_get_project(proj_id)
        if not raw:
            QMessageBox.warning(self, "Projects", "Project not found.")
            return
        d = _row_to_dict(raw)
        d["deadline"] = (d.get("deadline") or "")[:10] if d.get("deadline") else ""
        dlg = ProjectEditDialog(self, project=d, db=self.db)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.values()
        try:
            self.db.cos_update_project(proj_id, **vals)
            self.refresh_projects()
        except Exception as e:
            QMessageBox.warning(self, "Projects", f"Could not update project:\n{e}")

    def _delete_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Projects", "Select a project to delete.")
            return
        pid = self.table.item(row, 0).text()
        name = self.table.item(row, 1).text()
        if QMessageBox.question(
            self, "Delete project", f"Delete project \"{name}\"?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.cos_delete_project(int(pid))
            self.refresh_projects()
        except Exception as e:
            QMessageBox.warning(self, "Projects", f"Could not delete project:\n{e}")

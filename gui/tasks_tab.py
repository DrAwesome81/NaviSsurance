"""
Tasks tab (local).

This replaces the previous Vikunja integration. Tasks are stored in SQLite via
core.db.DatabaseManager (same task store used by Dashboard + CoS task capture).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QSettings, QTimer
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
    QGroupBox,
    QTabWidget,
)

from core.db import DatabaseManager
from gui.agent_console import AgentConsole
from gui.task_edit_dialog import TaskEditDialog
from gui.project_management_panel import ProjectManagementPanel

logger = logging.getLogger(__name__)

# Mason task command patterns (one per line); applied when Mason replies in Tasks tab
_ADD_TASK_PATTERN = re.compile(
    r"ADD_TASK:\s*(.+?)\s*\|\s*([^|]+?)\s*\|\s*(Business|Personal)(?:\s*\|\s*(\d+|none))?",
    re.IGNORECASE,
)
_TASK_UPDATE_PRIORITY_PATTERN = re.compile(
    r"TASK_UPDATE_PRIORITY:\s*(\d+)\s*\|\s*([0-5])",
    re.IGNORECASE,
)
_TASK_COMPLETE_PATTERN = re.compile(r"TASK_COMPLETE:\s*(\d+)", re.IGNORECASE)
_TASK_SET_DUE_PATTERN = re.compile(
    r"TASK_SET_DUE:\s*(\d+)\s*\|\s*([^|\n]+)",
    re.IGNORECASE,
)
_TASK_SET_NEXT_ACTION_PATTERN = re.compile(
    r"TASK_SET_NEXT_ACTION:\s*(\d+)\s*\|\s*([^|\n]+)",
    re.IGNORECASE,
)
_TASK_SNOOZE_PATTERN = re.compile(
    r"TASK_SNOOZE:\s*(\d+)\s*\|\s*(\d+)",
    re.IGNORECASE,
)
_TASK_DELETE_PATTERN = re.compile(r"TASK_DELETE:\s*(\d+)", re.IGNORECASE)
_TASK_SET_PROJECT_PATTERN = re.compile(r"TASK_SET_PROJECT:\s*(\d+)\s*\|\s*(\d+|none)", re.IGNORECASE)
_ADD_PROJECT_PATTERN = re.compile(r"ADD_PROJECT:\s*(.+?)\s*\|\s*([^|]*)\s*\|\s*(Active|Waiting|On Hold|Done|Cancelled)", re.IGNORECASE)
_PROJECT_UPDATE_STATUS_PATTERN = re.compile(r"PROJECT_UPDATE_STATUS:\s*(\d+)\s*\|\s*(Active|Waiting|On Hold|Done|Cancelled)", re.IGNORECASE)
_PROJECT_SET_DEADLINE_PATTERN = re.compile(r"PROJECT_SET_DEADLINE:\s*(\d+)\s*\|\s*([^|\n]+)", re.IGNORECASE)
_PROJECT_DELETE_PATTERN = re.compile(r"PROJECT_DELETE:\s*(\d+)", re.IGNORECASE)


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
        self._settings = QSettings("NaviSsurance", "TasksTab")
        self._setup_ui()
        self.refresh_tasks()

    def _setup_ui(self):
        base_margin = 6 if self._compact else 8
        base_spacing = 6 if self._compact else 8

        layout = QVBoxLayout(self)
        layout.setContentsMargins(base_margin, base_margin, base_margin, base_margin)
        layout.setSpacing(base_spacing)

        # Sub-tabs: Task list | Projects (list + Gantt)
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet(
            "QTabWidget::pane { background-color: #1c1e24; border: 1px solid #2e2f32; border-radius: 6px; }"
            "QTabBar::tab { background-color: #22252c; color: #e8eaed; padding: 8px 16px; margin-right: 2px; }"
            "QTabBar::tab:selected { background-color: #3a3b3e; font-weight: 600; }"
            "QTabBar::tab:hover:!selected { background-color: #2e2f32; }"
        )

        # ----- Tab 1: Task list (existing content) -----
        task_list_page = QWidget()
        task_list_layout = QVBoxLayout(task_list_page)
        task_list_layout.setContentsMargins(0, 0, 0, 0)
        task_list_layout.setSpacing(base_spacing)

        if self._show_header:
            header = QLabel("Tasks")
            header.setStyleSheet("color: #e8eaed; font-weight: 700; font-size: 14px; margin: 0;")
            task_list_layout.addWidget(header)

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

        lbl_project = QLabel("Project:")
        lbl_project.setStyleSheet(label_style)
        filters.addWidget(lbl_project)
        self.project_filter = QComboBox()
        self.project_filter.setStyleSheet(field_style)
        self.project_filter.setMinimumWidth(140)
        self._refresh_project_filter_combo()
        self.project_filter.currentIndexChanged.connect(self.refresh_tasks)
        filters.addWidget(self.project_filter)

        lbl_sort = QLabel("Sort:")
        lbl_sort.setStyleSheet(label_style)
        filters.addWidget(lbl_sort)
        self.sort_filter = QComboBox()
        self.sort_filter.setStyleSheet(field_style)
        self.sort_filter.addItems(["Priority", "Due date", "Next action", "Newest"])
        self.sort_filter.currentIndexChanged.connect(self.refresh_tasks)
        filters.addWidget(self.sort_filter)

        filters.addStretch(1)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setStyleSheet(button_style)
        self.refresh_btn.clicked.connect(self._refresh_tasks_with_projects)
        filters.addWidget(self.refresh_btn)

        if not self._compact:
            task_list_layout.addLayout(filters)

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

        if not self._compact:
            task_list_layout.addLayout(add_row)

        # Table: Tasks-tab-only layout. Task column gets most space; Priority and Actions have room.
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Task", "Priority", "Tags", "Next action date", "Due", "Category", "Project", "Done", "Actions"]
        )
        self.table.setColumnHidden(0, True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.verticalHeader().setMinimumSectionSize(52)
        self.table.setWordWrap(True)
        self.table.setSortingEnabled(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget { background-color: #1c1e24; color: #e8eaed; "
            "gridline-color: #2e2f32; border: 1px solid #2e2f32; border-radius: 6px; }"
            "QTableWidget::item { padding: 5px 6px; }"
            "QTableWidget::item:selected { background-color: #2b313c; color: #ffffff; }"
            "QHeaderView::section { background-color: #22252c; color: #e8eaed; "
            "padding: 6px; border: 1px solid #2e2f32; font-weight: 600; }"
        )

        hdr = self.table.horizontalHeader()
        if self._compact:
            # Dashboard focus view: no action buttons; allow user-resizable columns.
            self.table.setColumnHidden(9, True)
            for c in range(self.table.columnCount()):
                if c == 0:
                    continue
                hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
            # Keep task as the flex column so the table naturally fills available width.
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            hdr.setStretchLastSection(False)
            hdr.resizeSection(1, 360)  # Task
            hdr.resizeSection(2, 85)   # Priority
            hdr.resizeSection(5, 110)  # Due
            hdr.resizeSection(6, 100)  # Category
        else:
            # Task column: stretch to use remaining space (main content)
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            # Priority: fixed width so P0–P5 combo is fully visible (Tasks tab footprint)
            hdr.resizeSection(2, 80)
            hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            # Tags, Next action, Due, Category, Project, Done: size to content
            for c in (3, 4, 5, 6, 7, 8):
                hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
            # Actions: size to content so buttons aren’t squished (width comes from button layout)
            hdr.setSectionResizeMode(9, QHeaderView.ResizeMode.ResizeToContents)
        # Persist user-adjusted column widths/order.
        hdr.setSectionsMovable(True)
        hdr.sectionResized.connect(lambda *_: self._save_header_state())
        hdr.sectionMoved.connect(lambda *_: self._save_header_state())
        QTimer.singleShot(0, self._restore_header_state)
        # Tooltip for header (Next action date = when you plan to act on the task)
        self.table.horizontalHeader().setToolTip(
            "Next action date: when you plan to take the next step on this task (e.g. follow-up, review)."
        )

        task_list_layout.addWidget(self.table, 1)

        if not self._compact:
            self.mason_chat_group = QGroupBox(
                "Direct chat with Mason (Project Manager) — Mason sees your current task list"
            )
            self.mason_chat_group.setCheckable(True)
            self.mason_chat_group.setChecked(False)
            chat_layout = QVBoxLayout(self.mason_chat_group)
            self.mason_console = AgentConsole(
                self.db,
                agent_code="mason",
                parent=self,
                context_provider=self._mason_tasks_context,
                response_processor=self._parse_mason_task_commands,
            )
            self.mason_console.setVisible(False)
            chat_layout.addWidget(self.mason_console)
            self.mason_chat_group.toggled.connect(
                lambda checked: self.mason_console.setVisible(bool(checked))
            )
            task_list_layout.addWidget(self.mason_chat_group)

        tab_widget.addTab(task_list_page, "Task list")

        # Dashboard compact view is task-focus only; keep Projects tab in full Tasks page.
        if not self._compact:
            # ----- Tab 2: Project management (list + Gantt) -----
            self.project_panel = ProjectManagementPanel(self, db=self.db)
            tab_widget.addTab(self.project_panel, "Projects")

        layout.addWidget(tab_widget)

    def _refresh_project_filter_combo(self):
        """Reload project filter dropdown from cos_projects."""
        try:
            current = self.project_filter.currentData()
            self.project_filter.clear()
            self.project_filter.addItem("All projects", None)
            for row in self.db.cos_get_projects() or []:
                pid, name = row[0], (row[1] or "").strip() or f"Project {row[0]}"
                self.project_filter.addItem(name, int(pid))
            idx = self.project_filter.findData(current)
            if idx >= 0:
                self.project_filter.setCurrentIndex(idx)
        except Exception:
            self.project_filter.clear()
            self.project_filter.addItem("All projects", None)

    def _refresh_tasks_with_projects(self):
        """Refresh project dropdown then task list (so new projects appear in filter)."""
        self._refresh_project_filter_combo()
        self.refresh_tasks()

    def _selected_project_id(self) -> int | None:
        try:
            v = self.project_filter.currentData()
            return int(v) if v is not None else None
        except Exception:
            return None

    def _project_id_to_name(self, project_id: int | None) -> str:
        if project_id is None:
            return ""
        try:
            row = self.db.cos_get_project(int(project_id))
            return (row[1] or "").strip() if row and len(row) > 1 else ""
        except Exception:
            return ""

    def add_task(self):
        text = (self.new_task_input.text() or "").strip()
        if not text:
            return
        due = _parse_due_date(self.new_task_due.text())
        category = (self.new_task_category.currentText() or "Business").strip() or "Business"
        proj_id = self._selected_project_id()
        try:
            self.db.add_task("tasks_tab", text, due, category=category, cos_project_id=proj_id)
        except Exception as e:
            QMessageBox.warning(self, "Tasks", f"Could not add task:\n\n{type(e).__name__}: {e}")
            return
        self.new_task_input.clear()
        self.new_task_due.clear()
        self.refresh_tasks()

    def refresh_tasks(self):
        try:
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
            project_id = self._selected_project_id()
            sort_map = {"Priority": "priority", "Due date": "due_date", "Next action": "next_action", "Newest": "newest"}
            sort_by = sort_map.get(self.sort_filter.currentText() or "Priority", "priority")

            tasks = self.db.list_tasks_rich(
                category=category_val,
                date_filter=date_val,
                specific_date=specific_date,
                include_completed=bool(show_done),
                include_snoozed=bool(show_snoozed),
                search=query or None,
                cos_project_id=project_id,
                sort_by=sort_by,
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
                proj_id = rdict.get("cos_project_id")
                project_name = self._project_id_to_name(proj_id) if proj_id else ""

                r = self.table.rowCount()
                self.table.insertRow(r)

                it_id = QTableWidgetItem(str(task_id))
                it_id.setData(Qt.ItemDataRole.UserRole, task_id)
                self.table.setItem(r, 0, it_id)

                it_task = QTableWidgetItem(task_text)
                it_task.setFlags(it_task.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 1, it_task)

                # Priority: combo fits in 80px column (Tasks tab), no right-side clip
                priority_widget = QWidget()
                priority_layout = QHBoxLayout(priority_widget)
                priority_layout.setContentsMargins(2, 1, 2, 1)
                priority_layout.setSpacing(0)
                priority_combo = QComboBox()
                priority_combo.setMinimumWidth(72)
                priority_combo.setMaximumWidth(76)
                priority_combo.setStyleSheet(
                    "QComboBox { background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; "
                    "padding: 2px 4px; border-radius: 4px; font-size: 12px; min-height: 22px; }"
                    "QComboBox:hover { border-color: #4a4a4e; }"
                    "QComboBox::drop-down { width: 14px; border: none; }"
                )
                for p in range(6):
                    priority_combo.addItem(f"P{p}", p)
                try:
                    priority_combo.setCurrentIndex(min(max(0, int(priority)), 5))
                except Exception:
                    priority_combo.setCurrentIndex(0)
                priority_combo.currentIndexChanged.connect(
                    lambda idx, tid=task_id: self._on_priority_changed(tid, idx)
                )
                priority_layout.addWidget(priority_combo)
                self.table.setCellWidget(r, 2, priority_widget)

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

                it_project = QTableWidgetItem(project_name)
                it_project.setFlags(it_project.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 7, it_project)

                it_done = QTableWidgetItem("Yes" if done else "")
                it_done.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it_done.setFlags(it_done.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 8, it_done)

                if not self._compact:
                    # Actions: spaced buttons so column isn’t a barcode (Tasks tab)
                    actions = QWidget()
                    row = QHBoxLayout(actions)
                    row.setContentsMargins(4, 2, 4, 2)
                    row.setSpacing(10)
                    _btn_style = (
                        "QPushButton { background-color: #3a3b3e; color: #e8eaed; border: 1px solid #2e2f32; "
                        "padding: 4px 8px; border-radius: 4px; font-size: 12px; }"
                        "QPushButton:hover { background-color: #4a4a4e; }"
                    )
                    btn_edit = QPushButton("Edit")
                    btn_edit.setStyleSheet(_btn_style)
                    btn_edit.setMinimumWidth(52)
                    btn_edit.clicked.connect(lambda _=False, rr=rdict: self._edit_task(rr))
                    row.addWidget(btn_edit)
                    btn_toggle = QPushButton("Undo" if done else "Complete")
                    btn_toggle.setStyleSheet(
                        "QPushButton { background-color: #FD6262; color: white; border: none; "
                        "padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }"
                        "QPushButton:hover { background-color: #e85555; }"
                    )
                    btn_toggle.setMinimumWidth(68)
                    btn_toggle.clicked.connect(lambda _=False, tid=task_id, cur=done: self._toggle_done(tid, cur))
                    row.addWidget(btn_toggle)
                    btn_snooze = QPushButton("Snooze 1d")
                    btn_snooze.setStyleSheet(_btn_style)
                    btn_snooze.setMinimumWidth(72)
                    btn_snooze.clicked.connect(lambda _=False, tid=task_id: self._snooze_task(tid, days=1))
                    row.addWidget(btn_snooze)
                    btn_del = QPushButton("Delete")
                    btn_del.setStyleSheet(
                        "QPushButton { background-color: #502a2a; color: #ffdede; border: 1px solid #6a3535; "
                        "padding: 4px 8px; border-radius: 4px; font-size: 12px; }"
                        "QPushButton:hover { background-color: #6a3535; }"
                    )
                    btn_del.setMinimumWidth(52)
                    btn_del.clicked.connect(lambda _=False, tid=task_id: self._delete_task(tid))
                    row.addWidget(btn_del)
                    self.table.setCellWidget(r, 9, actions)

            self.table.resizeRowsToContents()
            # Keep startup and refresh row heights stable.
            # On first paint, Qt can over-estimate row heights before final column sizing.
            fixed_row_h = 52
            for rx in range(self.table.rowCount()):
                self.table.setRowHeight(rx, fixed_row_h)
        except Exception as e:
            logger.exception("refresh_tasks failed: %s", e)

    def _header_state_key(self) -> str:
        return "dashboard_table_header_state_v1" if self._compact else "tasks_table_header_state_v1"

    def _save_header_state(self) -> None:
        try:
            state = self.table.horizontalHeader().saveState()
            self._settings.setValue(self._header_state_key(), state)
        except Exception:
            pass

    def _restore_header_state(self) -> None:
        try:
            state = self._settings.value(self._header_state_key())
            if state:
                self.table.horizontalHeader().restoreState(state)
        except Exception:
            pass

    def _on_priority_changed(self, task_id: int, combo_index: int):
        """Update task priority when the row's priority combo is changed."""
        try:
            self.db.update_task_by_id(int(task_id), priority=combo_index)
        except Exception as e:
            QMessageBox.warning(self, "Tasks", f"Could not update priority:\n\n{type(e).__name__}: {e}")

    def _parse_mason_task_commands(self, response: str) -> str:
        """
        Parse Mason's reply for task command lines, apply them via the DB, and return
        the response with those lines removed so the user sees clean text.
        """
        if not (response or "").strip():
            return response or ""
        cleaned_lines = []
        for line in response.splitlines():
            stripped = line.strip()
            applied = False

            m = _ADD_TASK_PATTERN.search(stripped)
            if m:
                task_text = m.group(1).strip()
                due_part = m.group(2).strip().lower()
                category = m.group(3).strip()
                proj_part = (m.group(4) or "").strip().lower() if m.lastindex >= 4 else ""
                due_date = None if due_part == "none" or not due_part else due_part
                if due_date and len(due_date) == 10 and due_date[4] == "-":
                    parts = due_date.split("-")
                    if len(parts) == 3:
                        due_date = f"{parts[1]}-{parts[2]}-{parts[0]}"
                cos_project_id = None
                if proj_part and proj_part != "none":
                    try:
                        cos_project_id = int(proj_part)
                    except ValueError:
                        pass
                try:
                    self.db.add_task(
                        "mason_tasks_tab",
                        task_text=task_text,
                        due_date=due_date or "",
                        category=category or "Business",
                        recurrence="None",
                        completed=0,
                        cos_project_id=cos_project_id,
                    )
                    applied = True
                except Exception as e:
                    logger.warning("Mason ADD_TASK failed: %s", e)
                continue

            m = _TASK_UPDATE_PRIORITY_PATTERN.search(stripped)
            if m:
                try:
                    tid, prio = int(m.group(1)), int(m.group(2))
                    self.db.update_task_by_id(tid, priority=prio)
                    applied = True
                except Exception as e:
                    logger.warning("Mason TASK_UPDATE_PRIORITY failed: %s", e)
                continue

            m = _TASK_COMPLETE_PATTERN.search(stripped)
            if m:
                try:
                    self.db.update_task_by_id(int(m.group(1)), completed=1)
                    applied = True
                except Exception as e:
                    logger.warning("Mason TASK_COMPLETE failed: %s", e)
                continue

            m = _TASK_SET_DUE_PATTERN.search(stripped)
            if m:
                try:
                    tid, due_part = int(m.group(1)), (m.group(2) or "").strip().lower()
                    due_date = None if due_part == "none" or not due_part else due_part
                    if due_date and len(due_date) == 10 and due_date[4] == "-":
                        parts = due_date.split("-")
                        if len(parts) == 3:
                            due_date = f"{parts[1]}-{parts[2]}-{parts[0]}"
                    self.db.update_task_by_id(tid, due_date=due_date)
                    applied = True
                except Exception as e:
                    logger.warning("Mason TASK_SET_DUE failed: %s", e)
                continue

            m = _TASK_SET_NEXT_ACTION_PATTERN.search(stripped)
            if m:
                try:
                    tid, date_part = int(m.group(1)), (m.group(2) or "").strip().lower()
                    next_action = None if date_part == "none" or not date_part else date_part
                    if next_action and len(next_action) == 10 and next_action[4] == "-":
                        parts = next_action.split("-")
                        if len(parts) == 3:
                            next_action = f"{parts[1]}-{parts[2]}-{parts[0]}"
                    self.db.update_task_by_id(tid, next_action_date=next_action)
                    applied = True
                except Exception as e:
                    logger.warning("Mason TASK_SET_NEXT_ACTION failed: %s", e)
                continue

            m = _TASK_SNOOZE_PATTERN.search(stripped)
            if m:
                try:
                    tid, days = int(m.group(1)), int(m.group(2))
                    until = (datetime.now() + timedelta(days=max(1, days))).strftime("%m-%d-%Y")
                    self.db.update_task_by_id(tid, snoozed_until=until)
                    applied = True
                except Exception as e:
                    logger.warning("Mason TASK_SNOOZE failed: %s", e)
                continue

            m = _TASK_DELETE_PATTERN.search(stripped)
            if m:
                try:
                    self.db.delete_task_by_id(int(m.group(1)))
                    applied = True
                except Exception as e:
                    logger.warning("Mason TASK_DELETE failed: %s", e)
                continue

            m = _TASK_SET_PROJECT_PATTERN.search(stripped)
            if m:
                try:
                    tid, proj_part = int(m.group(1)), (m.group(2) or "").strip().lower()
                    cos_project_id = None if proj_part == "none" or not proj_part else int(proj_part)
                    self.db.update_task_by_id(tid, cos_project_id=cos_project_id)
                    applied = True
                except Exception as e:
                    logger.warning("Mason TASK_SET_PROJECT failed: %s", e)
                continue

            m = _ADD_PROJECT_PATTERN.search(stripped)
            if m:
                try:
                    name, client, status = m.group(1).strip(), (m.group(2) or "").strip(), m.group(3).strip()
                    self.db.cos_insert_project(name=name, client=client or None, status=status)
                    applied = True
                except Exception as e:
                    logger.warning("Mason ADD_PROJECT failed: %s", e)
                continue

            m = _PROJECT_UPDATE_STATUS_PATTERN.search(stripped)
            if m:
                try:
                    pid, status = int(m.group(1)), m.group(2).strip()
                    self.db.cos_update_project(pid, status=status)
                    applied = True
                except Exception as e:
                    logger.warning("Mason PROJECT_UPDATE_STATUS failed: %s", e)
                continue

            m = _PROJECT_SET_DEADLINE_PATTERN.search(stripped)
            if m:
                try:
                    pid, date_part = int(m.group(1)), (m.group(2) or "").strip().lower()
                    deadline = None if date_part == "none" or not date_part else date_part
                    if deadline and len(deadline) == 10:
                        parts = deadline.split("-")
                        if len(parts) == 3 and len(parts[0]) == 2 and len(parts[2]) == 4:
                            deadline = f"{parts[2]}-{parts[0]}-{parts[1]}"
                    self.db.cos_update_project(pid, deadline=deadline)
                    applied = True
                except Exception as e:
                    logger.warning("Mason PROJECT_SET_DEADLINE failed: %s", e)
                continue

            m = _PROJECT_DELETE_PATTERN.search(stripped)
            if m:
                try:
                    self.db.cos_delete_project(int(m.group(1)))
                    applied = True
                except Exception as e:
                    logger.warning("Mason PROJECT_DELETE failed: %s", e)
                continue

            cleaned_lines.append(line)
        try:
            self.refresh_tasks()
            if getattr(self, "project_panel", None) is not None:
                self.project_panel.refresh_projects()
        except Exception:
            pass
        return "\n".join(cleaned_lines).strip() or "(Updates applied.)"

    def _mason_tasks_context(self) -> str:
        """Build task list and command instructions for Mason (Project Manager)."""
        try:
            tasks = self.db.list_tasks_rich(
                category=None,
                date_filter=None,
                specific_date=None,
                include_completed=True,
                include_snoozed=True,
                search=None,
                limit=100,
            )
            lines = ["Current tasks (id, text, priority, due, next action, category, status):"]
            if not tasks:
                lines.append("  (none)")
            else:
                for t in tasks:
                    tid = t.get("id") or ""
                    text = (str(t.get("task_text") or "").strip() or "(no text)")[:80]
                    prio = t.get("priority", 0)
                    due = t.get("due_date") or "—"
                    next_act = t.get("next_action_date") or "—"
                    cat = t.get("category") or "—"
                    done = " [DONE]" if t.get("completed") else ""
                    snoozed = " [snoozed]" if (t.get("snoozed_until") or "").strip() else ""
                    proj = t.get("cos_project_id")
                    proj_s = f" project={proj}" if proj else ""
                    lines.append(f"  {tid}: {text} | P{prio} | due {due} | next {next_act} | {cat}{proj_s}{done}{snoozed}")
            lines.append("")
            try:
                proj_rows = self.db.cos_get_projects() or []
                lines.append("Current projects (id, name, client, status, deadline):")
                if not proj_rows:
                    lines.append("  (none)")
                else:
                    for row in proj_rows:
                        pid, name, client, status = row[0], row[1] or "", row[2] or "", row[4] or ""
                        deadline = (row[6] or "")[:10] if len(row) > 6 and row[6] else "—"
                        lines.append(f"  {pid}: {name} | {client} | {status} | {deadline}")
            except Exception:
                pass
            lines.append("")
            lines.append(
                "You can change tasks and projects by outputting exactly these lines (one per action); they will be executed and removed from your reply."
            )
            lines.append("Tasks: ADD_TASK: <description> | <MM-DD-YYYY or none> | Business|Personal [| project_id]")
            lines.append("TASK_UPDATE_PRIORITY: <task_id> | <0-5>")
            lines.append("TASK_COMPLETE: <task_id>")
            lines.append("TASK_SET_DUE: <task_id> | <MM-DD-YYYY or none>")
            lines.append("TASK_SET_NEXT_ACTION: <task_id> | <MM-DD-YYYY or none>")
            lines.append("TASK_SNOOZE: <task_id> | <days>")
            lines.append("TASK_DELETE: <task_id>")
            lines.append("TASK_SET_PROJECT: <task_id> | <project_id or none>")
            lines.append("Projects: ADD_PROJECT: <name> | <client> | Active|Waiting|On Hold|Done|Cancelled")
            lines.append("PROJECT_UPDATE_STATUS: <project_id> | Active|Waiting|On Hold|Done|Cancelled")
            lines.append("PROJECT_SET_DEADLINE: <project_id> | YYYY-MM-DD or none")
            lines.append("PROJECT_DELETE: <project_id>")
            return "\n".join(lines)
        except Exception as e:
            logger.warning("Mason tasks context failed: %s", e)
            return "Current tasks: (unable to load)"

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


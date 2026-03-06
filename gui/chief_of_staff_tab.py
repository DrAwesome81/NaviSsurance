"""
Chief of Staff tab: chat on the left (≥70%), sidebar on the right with chat list by project.
All chats save automatically. Layout like Grok/ChatGPT but sidebar on the right.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton, QLabel, QTextEdit,
    QTextBrowser, QListWidget, QListWidgetItem, QFormLayout, QSpinBox, QTabWidget,
    QMessageBox, QProgressBar, QDialog, QDialogButtonBox, QMenu, QToolButton,
    QSizePolicy, QComboBox, QLineEdit, QInputDialog, QFileDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QAction, QKeyEvent


class ChatEntryEdit(QTextEdit):
    """QTextEdit that sends on Enter, newline on Shift+Enter."""
    returnPressed = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.returnPressed.emit()
                event.accept()
        else:
            super().keyPressEvent(event)

from core.db import DatabaseManager
from core.chief_of_staff_service import cos_response
from gui.agent_routing import route_for_agent

logger = logging.getLogger(__name__)
ASSIGNMENT_REF_PATTERN = re.compile(r"\bA-(\d{1,8})\b")

try:
    import markdown
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False


def _md_to_html(md_text: str) -> str:
    if not md_text:
        return "<p style='color: #9aa0a6;'>(No content)</p>"
    if HAS_MARKDOWN:
        return markdown.markdown(md_text, extensions=["extra"])
    return "<pre style='color: #9aa0a6;'>" + md_text.replace("<", "&lt;").replace(">", "&gt;") + "</pre>"


def _normalize_iso_due_date_input(value: str) -> tuple[bool, Optional[str]]:
    """Validate YYYY-MM-DD due-date input and return normalized YYYY-MM-DD."""
    raw = (value or "").strip()
    if not raw or raw.lower() in {"none", "null", "n/a"}:
        return True, None
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return False, None
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d")
    except Exception:
        return False, None
    return True, dt.strftime("%Y-%m-%d")


def _normalize_mmddyyyy_due_date_input(value: str) -> tuple[bool, Optional[str]]:
    """Validate MM-DD-YYYY due-date input and return normalized MM-DD-YYYY."""
    raw = (value or "").strip()
    if not raw or raw.lower() in {"none", "null", "n/a"}:
        return True, None
    if not re.match(r"^\d{2}-\d{2}-\d{4}$", raw):
        return False, None
    try:
        dt = datetime.strptime(raw, "%m-%d-%Y")
    except Exception:
        return False, None
    return True, dt.strftime("%m-%d-%Y")


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    """Parse common ISO datetime strings into naive local datetime."""
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        return None
    if dt.tzinfo is not None:
        try:
            dt = dt.astimezone().replace(tzinfo=None)
        except Exception:
            dt = dt.replace(tzinfo=None)
    return dt


def _assignment_health_flags(row: dict, *, now: Optional[datetime] = None) -> list[str]:
    """Return health flags like overdue/stale_blocked/stale_review for an assignment row."""
    now_dt = now or datetime.now()
    flags: list[str] = []
    status = str(row.get("status") or "").strip().lower()
    is_closed = status in {"done", "cancelled"}

    due_raw = str(row.get("due_date") or "").strip()
    due_dt = None
    if due_raw:
        try:
            due_dt = datetime.strptime(due_raw, "%Y-%m-%d")
        except Exception:
            due_dt = None
    if due_dt is not None and not is_closed and due_dt.date() < now_dt.date():
        flags.append("overdue")

    ref_ts = _parse_iso_datetime(str(row.get("updated_at") or "")) or _parse_iso_datetime(
        str(row.get("created_at") or "")
    )
    if ref_ts is not None and not is_closed:
        age = now_dt - ref_ts
        if status == "blocked" and age >= timedelta(days=3):
            flags.append("stale_blocked")
        if status == "awaiting_review" and age >= timedelta(days=3):
            flags.append("stale_review")
    return flags


class CosAskWorker(QThread):
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, db: DatabaseManager, user_message: str, conversation_history: list, chat_id: int = None):
        super().__init__()
        self.db = db
        self.user_message = user_message
        self.conversation_history = conversation_history or []
        self.chat_id = chat_id

    def run(self):
        try:
            result = cos_response(self.db, self.user_message, self.conversation_history, chat_id=self.chat_id)
            if result.startswith("Error"):
                self.error_signal.emit(result)
                return
            self.finished_signal.emit(result)
        except Exception as e:
            logger.exception("CoS Ask: %s", e)
            self.error_signal.emit(str(e))


class CosPreferencesDialog(QDialog):
    """Preferences window opened from Options menu."""
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Chief of Staff — Preferences")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Optional: constraints the CoS uses (time, boundaries, etc.)"))
        layout.addWidget(QLabel("Operating system / constraints (markdown):"))
        self.prefs_os_edit = QTextEdit()
        self.prefs_os_edit.setPlaceholderText("Optimization order, acceptable stress, family boundaries, etc.")
        self.prefs_os_edit.setMinimumHeight(100)
        layout.addWidget(self.prefs_os_edit)
        layout.addWidget(QLabel("Blocked times (JSON):"))
        self.prefs_blocked_edit = QTextEdit()
        self.prefs_blocked_edit.setMaximumHeight(60)
        self.prefs_blocked_edit.setPlaceholderText('[]')
        layout.addWidget(self.prefs_blocked_edit)
        layout.addWidget(QLabel("Deep work hours per day:"))
        self.prefs_deep_work_spin = QSpinBox()
        self.prefs_deep_work_spin.setRange(0, 12)
        self.prefs_deep_work_spin.setValue(2)
        layout.addWidget(self.prefs_deep_work_spin)
        layout.addWidget(QLabel("Behavior prefs (JSON):"))
        self.prefs_behavior_edit = QTextEdit()
        self.prefs_behavior_edit.setMaximumHeight(50)
        self.prefs_behavior_edit.setPlaceholderText("{}")
        layout.addWidget(self.prefs_behavior_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._load()

    def _load(self):
        row = self.db.cos_get_preferences()
        if not row:
            return
        operating_system_md, blocked_times_json, deep_work_hours, behavior_prefs_json, _ = row
        self.prefs_os_edit.setPlainText(operating_system_md or "")
        self.prefs_blocked_edit.setPlainText(blocked_times_json or "[]")
        self.prefs_deep_work_spin.setValue(deep_work_hours if deep_work_hours is not None else 2)
        self.prefs_behavior_edit.setPlainText(behavior_prefs_json or "{}")

    def _save(self):
        os_md = self.prefs_os_edit.toPlainText().strip()
        blocked = self.prefs_blocked_edit.toPlainText().strip() or "[]"
        try:
            json.loads(blocked)
        except json.JSONDecodeError:
            QMessageBox.warning(self, "Preferences", "Blocked times must be valid JSON (e.g. []).")
            return
        behavior = self.prefs_behavior_edit.toPlainText().strip() or "{}"
        try:
            json.loads(behavior)
        except json.JSONDecodeError:
            QMessageBox.warning(self, "Preferences", "Behavior prefs must be valid JSON (e.g. {}).")
            return
        self.db.cos_set_preferences(
            operating_system_md=os_md,
            blocked_times_json=blocked,
            deep_work_hours=self.prefs_deep_work_spin.value(),
            behavior_prefs_json=behavior,
        )
        QMessageBox.information(self, "Preferences", "Saved.")
        self.accept()


class CosAssignmentDialog(QDialog):
    """Create a delegation assignment from the CoS board."""

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("New Assignment")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Assignment title")
        form.addRow("Title:", self.title_edit)

        self.assignee_combo = QComboBox()
        self._assignees: list[dict] = []
        for a in self.db.agents_list_active():
            code = str(a.get("code") or "").strip().lower()
            if code == "navi":
                continue
            label = f"{a.get('display_name') or code} ({code})"
            self.assignee_combo.addItem(label, code)
            self._assignees.append(a)
        form.addRow("Assignee:", self.assignee_combo)

        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(1, 5)
        self.priority_spin.setValue(3)
        form.addRow("Priority (P1-P5, P5 highest urgency):", self.priority_spin)

        self.due_edit = QLineEdit()
        self.due_edit.setPlaceholderText("YYYY-MM-DD or leave blank")
        form.addRow("Due date:", self.due_edit)

        self.brief_edit = QTextEdit()
        self.brief_edit.setPlaceholderText("Task brief and expected output")
        self.brief_edit.setMinimumHeight(120)
        form.addRow("Brief:", self.brief_edit)

        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_then_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_then_accept(self):
        title = (self.title_edit.text() or "").strip()
        brief = (self.brief_edit.toPlainText() or "").strip()
        if not title:
            QMessageBox.warning(self, "Assignment", "Title is required.")
            return
        if not brief:
            QMessageBox.warning(self, "Assignment", "Brief is required.")
            return
        due = (self.due_edit.text() or "").strip()
        due_ok, _due_norm = _normalize_iso_due_date_input(due)
        if not due_ok:
            QMessageBox.warning(
                self,
                "Assignment",
                "Due date must be a real calendar date in YYYY-MM-DD or blank.",
            )
            return
        self.accept()

    def values(self) -> dict:
        due_raw = (self.due_edit.text() or "").strip()
        due_ok, due_norm = _normalize_iso_due_date_input(due_raw)
        due = due_norm if due_ok else None
        return {
            "title": (self.title_edit.text() or "").strip(),
            "brief_md": (self.brief_edit.toPlainText() or "").strip(),
            "assignee_code": (self.assignee_combo.currentData() or "").strip().lower(),
            "priority": int(self.priority_spin.value()),
            "due_date": due,
        }


class ChiefOfStaffTab(QWidget):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self._ask_worker = None
        self._current_chat_id = None
        self._current_assignment_id = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)
        splitter.addWidget(self._build_chat_panel())
        sidebar = self._build_sidebar()
        sidebar.setMinimumWidth(220)
        splitter.addWidget(sidebar)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([700, 300])
        layout.addWidget(splitter)

    def _build_chat_panel(self):
        """Left: chat window + entry box only. Options in a menu."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        # Top row: optional options button (right-aligned)
        top_row = QHBoxLayout()
        top_row.addStretch()
        options_btn = QToolButton()
        options_btn.setText("⋮ Options")
        options_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        options_btn.setStyleSheet(
            "QToolButton { color: #e8eaed; background-color: #22252c; border: 1px solid #2e2f32; padding: 6px 12px; border-radius: 6px; }"
            "QToolButton:hover { background-color: #3a3b3e; color: #e8eaed; }"
        )
        menu = QMenu()
        prefs_action = QAction("Preferences…", self)
        prefs_action.triggered.connect(self._open_preferences)
        menu.addAction(prefs_action)
        commands_action = QAction("Action Commands…", self)
        commands_action.triggered.connect(self._open_command_cheatsheet)
        menu.addAction(commands_action)
        options_btn.setMenu(menu)
        top_row.addWidget(options_btn)
        layout.addLayout(top_row)
        # Chat messages
        self.chat_display = QTextBrowser()
        self.chat_display.setOpenExternalLinks(False)
        self.chat_display.setOpenLinks(False)
        self.chat_display.anchorClicked.connect(self._on_chat_link_clicked)
        self.chat_display.setPlaceholderText("New chat — type below and press Send, or pick a chat on the right.")
        layout.addWidget(self.chat_display)
        # Entry row: input + Send (Enter = send, Shift+Enter = new line)
        entry_row = QHBoxLayout()
        self.ask_input = ChatEntryEdit()
        self.ask_input.setPlaceholderText("What you're working on and what has come up… (Enter to send, Shift+Enter for new line)")
        self.ask_input.setMaximumHeight(80)
        self.ask_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ask_input.returnPressed.connect(self._on_send)
        entry_row.addWidget(self.ask_input)
        self.ask_btn = QPushButton("Send")
        self.ask_btn.clicked.connect(self._on_send)
        self.ask_progress = QProgressBar()
        self.ask_progress.setRange(0, 0)
        self.ask_progress.setVisible(False)
        entry_row.addWidget(self.ask_btn)
        entry_row.addWidget(self.ask_progress)
        layout.addLayout(entry_row)
        return panel

    def _open_preferences(self):
        d = CosPreferencesDialog(self.db, self)
        d.exec()

    def _open_command_cheatsheet(self):
        md = """
## Chief of Staff Action Commands

Use these exact line formats in Navi responses:

- Priority scale: for assignments, P1 is lowest urgency and P5 is highest urgency.

- `ASSIGN: <AgentName> | <Title> | <Brief> | <P1-P5> | <YYYY-MM-DD or none>`
- `UPDATE_ASSIGNMENT_STATUS: <A-0007 or 7> | <queued|in_progress|awaiting_review|blocked|done|cancelled> | <optional note>`
- `BULK_UPDATE_ASSIGNMENT_STATUS: <status> | <AgentName or all> | <open or all (optional)> | <optional note>`
- `BULK_UPDATE_ASSIGNMENT_PRIORITY: <P1-P5> | <AgentName or all> | <open or all (optional)> | <optional note>`
- `BULK_UPDATE_ASSIGNMENT_DUE: <YYYY-MM-DD or none> | <AgentName or all> | <open or all (optional)> | <optional note>`
- `UPDATE_ASSIGNMENT_PRIORITY: <A-0007 or 7> | <P1-P5> | <optional note>`
- `UPDATE_ASSIGNMENT_DUE: <A-0007 or 7> | <YYYY-MM-DD or none> | <optional note>`
- `RETITLE_ASSIGNMENT: <A-0007 or 7> | <new title> | <optional note>`
- `UPDATE_ASSIGNMENT_BRIEF: <A-0007 or 7> | <new brief markdown> | <optional note>`
- `UPDATE_ASSIGNMENT_SUMMARY: <A-0007 or 7> | <summary markdown>`
- `REASSIGN: <A-0007 or 7> | <AgentName> | <optional note>`
- `BULK_REASSIGN_ASSIGNMENTS: <AgentName or all> | <AgentName target> | <open or all (optional)> | <optional note>`
- `ADD_ASSIGNMENT_ARTIFACT: <A-0007 or 7> | <artifact_type> | <title> | <content markdown>`
- `ADD_TASK_FROM_ASSIGNMENT: <A-0007 or 7> | <MM-DD-YYYY or none> | <Business or Personal>`
- `BULK_ADD_TASKS_FROM_ASSIGNMENTS: <AgentName or all> | <Business or Personal> | <open or all (optional)>`

Calendar and task actions:

- Priority scale: for dashboard tasks, P0 is lowest urgency and P5 is highest urgency.

- `ADD_TASK: <task description> | <MM-DD-YYYY or none> | <Business or Personal>`
- `ADD_CAL_BLOCK: <title> | <start datetime> | <end datetime> | <calendar id or primary>`
""".strip()

        d = QDialog(self)
        d.setWindowTitle("Chief of Staff — Action Command Cheat Sheet")
        layout = QVBoxLayout(d)
        viewer = QTextBrowser()
        viewer.setMarkdown(md)
        layout.addWidget(viewer)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(d.accept)
        buttons.rejected.connect(d.reject)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(d.accept)
        layout.addWidget(buttons)
        d.resize(760, 560)
        d.exec()

    def _build_sidebar(self):
        """Right side: chats and delegation assignments."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        tabs = QTabWidget()
        self.sidebar_tabs = tabs

        # Chats tab
        chats_panel = QWidget()
        chats_layout = QVBoxLayout(chats_panel)
        chats_layout.setContentsMargins(0, 0, 0, 0)
        chats_layout.addWidget(QLabel("Chats"))
        new_btn = QPushButton("New chat")
        new_btn.clicked.connect(self._on_new_chat)
        chats_layout.addWidget(new_btn)
        self.chat_list = QListWidget()
        self.chat_list.itemClicked.connect(self._on_chat_clicked)
        chats_layout.addWidget(self.chat_list)
        tabs.addTab(chats_panel, "Chats")

        # Assignments tab
        asg_panel = QWidget()
        asg_layout = QVBoxLayout(asg_panel)
        asg_layout.setContentsMargins(0, 0, 0, 0)
        asg_head = QHBoxLayout()
        asg_head.addWidget(QLabel("Delegation Board"))
        asg_head.addStretch()
        new_asg_btn = QPushButton("New")
        new_asg_btn.clicked.connect(self._create_assignment_from_board)
        asg_head.addWidget(new_asg_btn)
        reassign_btn = QPushButton("Reassign")
        reassign_btn.clicked.connect(self._reassign_selected_assignment)
        asg_head.addWidget(reassign_btn)
        bulk_status_btn = QPushButton("Bulk Status")
        bulk_status_btn.clicked.connect(self._bulk_set_filtered_status)
        asg_head.addWidget(bulk_status_btn)
        bulk_priority_btn = QPushButton("Bulk Priority")
        bulk_priority_btn.clicked.connect(self._bulk_set_filtered_priority)
        asg_head.addWidget(bulk_priority_btn)
        bulk_due_btn = QPushButton("Bulk Due")
        bulk_due_btn.clicked.connect(self._bulk_set_filtered_due)
        asg_head.addWidget(bulk_due_btn)
        bulk_reassign_btn = QPushButton("Bulk Reassign")
        bulk_reassign_btn.clicked.connect(self._bulk_reassign_filtered_assignments)
        asg_head.addWidget(bulk_reassign_btn)
        export_btn = QPushButton("Export")
        export_btn.clicked.connect(self._export_assignment_board_markdown)
        asg_head.addWidget(export_btn)
        refresh_asg_btn = QPushButton("Refresh")
        refresh_asg_btn.clicked.connect(self._refresh_assignment_list)
        asg_head.addWidget(refresh_asg_btn)
        asg_layout.addLayout(asg_head)

        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(6)
        self.assignment_status_filter = QComboBox()
        self.assignment_status_filter.addItems(
            ["All", "queued", "in_progress", "awaiting_review", "blocked", "done", "cancelled"]
        )
        self.assignment_status_filter.currentTextChanged.connect(lambda _t: self._refresh_assignment_list())
        filters.addWidget(self.assignment_status_filter)

        self.assignment_health_filter = QComboBox()
        self.assignment_health_filter.addItem("Health: All", "")
        self.assignment_health_filter.addItem("Overdue", "overdue")
        self.assignment_health_filter.addItem("Blocked 3d+", "stale_blocked")
        self.assignment_health_filter.addItem("Awaiting Review 3d+", "stale_review")
        self.assignment_health_filter.addItem("Needs Attention", "needs_attention")
        self.assignment_health_filter.currentTextChanged.connect(lambda _t: self._refresh_assignment_list())
        filters.addWidget(self.assignment_health_filter)

        self.assignment_assignee_filter = QComboBox()
        self.assignment_assignee_filter.addItem("All assignees", "")
        for a in self.db.agents_list_active():
            code = str(a.get("code") or "").strip().lower()
            if not code or code == "navi":
                continue
            label = f"{a.get('display_name') or code} ({code})"
            self.assignment_assignee_filter.addItem(label, code)
        self.assignment_assignee_filter.currentTextChanged.connect(lambda _t: self._refresh_assignment_list())
        filters.addWidget(self.assignment_assignee_filter)

        self.assignment_search_input = QLineEdit()
        self.assignment_search_input.setPlaceholderText("Search title / brief / A-####")
        self.assignment_search_input.textChanged.connect(lambda _t: self._refresh_assignment_list())
        filters.addWidget(self.assignment_search_input, 1)
        asg_layout.addLayout(filters)

        self.assignment_count_label = QLabel("")
        self.assignment_count_label.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        asg_layout.addWidget(self.assignment_count_label)

        self.assignment_list = QListWidget()
        self.assignment_list.itemClicked.connect(self._on_assignment_clicked)
        asg_layout.addWidget(self.assignment_list, 1)
        self.assignment_details = QTextBrowser()
        self.assignment_details.setPlaceholderText("Select an assignment to view details.")
        asg_layout.addWidget(self.assignment_details, 1)
        btn_row = QHBoxLayout()
        self.asg_start_btn = QPushButton("Start")
        self.asg_start_btn.clicked.connect(lambda: self._set_assignment_status("in_progress"))
        btn_row.addWidget(self.asg_start_btn)
        self.asg_set_priority_btn = QPushButton("Set Priority")
        self.asg_set_priority_btn.clicked.connect(self._set_assignment_priority)
        btn_row.addWidget(self.asg_set_priority_btn)
        self.asg_set_due_btn = QPushButton("Set Due")
        self.asg_set_due_btn.clicked.connect(self._set_assignment_due)
        btn_row.addWidget(self.asg_set_due_btn)
        self.asg_review_btn = QPushButton("Awaiting Review")
        self.asg_review_btn.clicked.connect(lambda: self._set_assignment_status("awaiting_review"))
        btn_row.addWidget(self.asg_review_btn)
        self.asg_block_btn = QPushButton("Block")
        self.asg_block_btn.clicked.connect(lambda: self._set_assignment_status("blocked"))
        btn_row.addWidget(self.asg_block_btn)
        self.asg_done_btn = QPushButton("Done")
        self.asg_done_btn.clicked.connect(lambda: self._set_assignment_status("done"))
        btn_row.addWidget(self.asg_done_btn)
        self.asg_cancel_btn = QPushButton("Cancel")
        self.asg_cancel_btn.clicked.connect(lambda: self._set_assignment_status("cancelled"))
        btn_row.addWidget(self.asg_cancel_btn)
        asg_layout.addLayout(btn_row)
        edit_row = QHBoxLayout()
        self.asg_reopen_btn = QPushButton("Reopen")
        self.asg_reopen_btn.clicked.connect(lambda: self._set_assignment_status("queued"))
        edit_row.addWidget(self.asg_reopen_btn)
        self.asg_edit_title_btn = QPushButton("Edit Title")
        self.asg_edit_title_btn.clicked.connect(self._edit_assignment_title)
        edit_row.addWidget(self.asg_edit_title_btn)
        self.asg_edit_brief_btn = QPushButton("Edit Brief")
        self.asg_edit_brief_btn.clicked.connect(self._edit_assignment_brief)
        edit_row.addWidget(self.asg_edit_brief_btn)
        self.asg_edit_summary_btn = QPushButton("Edit Summary")
        self.asg_edit_summary_btn.clicked.connect(self._edit_assignment_summary)
        edit_row.addWidget(self.asg_edit_summary_btn)
        edit_row.addStretch()
        asg_layout.addLayout(edit_row)
        artifact_row = QHBoxLayout()
        self.asg_create_task_btn = QPushButton("Create Task")
        self.asg_create_task_btn.clicked.connect(self._create_task_from_assignment)
        artifact_row.addWidget(self.asg_create_task_btn)
        self.asg_bulk_create_tasks_btn = QPushButton("Bulk Create Tasks")
        self.asg_bulk_create_tasks_btn.clicked.connect(self._bulk_create_tasks_from_filtered_assignments)
        artifact_row.addWidget(self.asg_bulk_create_tasks_btn)
        self.asg_view_artifact_btn = QPushButton("View Artifact")
        self.asg_view_artifact_btn.clicked.connect(self._view_selected_assignment_artifact)
        artifact_row.addWidget(self.asg_view_artifact_btn)
        artifact_row.addStretch()
        asg_layout.addLayout(artifact_row)
        self.asg_open_chat_btn = QPushButton("Open Assignee Chat")
        self.asg_open_chat_btn.clicked.connect(self._open_assignment_in_assignee_console)
        asg_layout.addWidget(self.asg_open_chat_btn)
        tabs.addTab(asg_panel, "Assignments")

        layout.addWidget(tabs)
        self._refresh_chat_list()
        self._refresh_assignment_list()
        return panel

    def _create_assignment_from_board(self):
        d = CosAssignmentDialog(self.db, self)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        vals = d.values()
        assignee = str(vals.get("assignee_code") or "").strip().lower()
        title = str(vals.get("title") or "").strip()
        brief = str(vals.get("brief_md") or "").strip()
        priority = int(vals.get("priority") or 3)
        due_date = vals.get("due_date")
        if not assignee or not title or not brief:
            QMessageBox.warning(self, "Assignments", "Missing required assignment fields.")
            return

        context_obj = {"source": "manual_cos_board"}
        if self._current_chat_id is not None:
            context_obj["cos_chat_id"] = int(self._current_chat_id)
        thread_id = None
        try:
            thread_id = self.db.agent_create_thread(
                agent_code=assignee,
                title=title,
                context_json=context_obj,
            )
        except Exception:
            thread_id = None

        aid = self.db.agent_create_assignment(
            title=title,
            brief_md=brief,
            requester_code="navi",
            assignee_code=assignee,
            priority=priority,
            due_date=due_date,
            source_thread_id=(int(thread_id) if thread_id else None),
            context_json=context_obj,
        )
        if not aid:
            QMessageBox.warning(self, "Assignments", "Could not create assignment.")
            return
        self._refresh_assignment_list()
        self._focus_assignment_by_id(int(aid))

    def _reassign_selected_assignment(self):
        if not self._current_assignment_id:
            QMessageBox.information(self, "Assignments", "Select an assignment first.")
            return
        current = self.db.agent_get_assignment(int(self._current_assignment_id))
        if not current:
            QMessageBox.warning(self, "Assignments", "Assignment not found.")
            return

        options: list[tuple[str, str]] = []
        for a in self.db.agents_list_active():
            code = str(a.get("code") or "").strip().lower()
            if not code or code == "navi":
                continue
            label = f"{a.get('display_name') or code} ({code})"
            options.append((label, code))
        if not options:
            QMessageBox.information(self, "Assignments", "No assignees available.")
            return

        current_assignee = str(current.get("assignee_code") or "").strip().lower()
        labels = [x[0] for x in options]
        default_idx = 0
        for i, (_label, code) in enumerate(options):
            if code == current_assignee:
                default_idx = i
                break

        picked, ok = QInputDialog.getItem(
            self,
            "Reassign Assignment",
            "Assign to:",
            labels,
            default_idx,
            False,
        )
        if not ok or not picked:
            return
        new_code = ""
        for label, code in options:
            if label == picked:
                new_code = code
                break
        if not new_code:
            return
        if new_code == current_assignee:
            return
        ok = self.db.agent_reassign_assignment(
            assignment_id=int(self._current_assignment_id),
            new_assignee_code=new_code,
            actor_code="navi",
            note="Reassigned from CoS board",
        )
        if not ok:
            QMessageBox.warning(self, "Assignments", "Could not reassign assignment.")
            return
        self._ensure_assignment_thread_for_assignee(
            assignment_id=int(self._current_assignment_id),
            assignee_code=new_code,
            reason="cos_board_reassign",
        )
        self._refresh_assignment_list()
        self._focus_assignment_by_id(int(self._current_assignment_id))

    def _ensure_assignment_thread_for_assignee(self, *, assignment_id: int, assignee_code: str, reason: str):
        """Best-effort thread relink after reassignment."""
        try:
            row = self.db.agent_get_assignment(int(assignment_id)) or {}
            source_thread_id = row.get("source_thread_id")
            relink = True
            if source_thread_id:
                src = self.db.agent_get_thread(int(source_thread_id))
                if src and str(src[1] or "").strip().lower() == str(assignee_code).strip().lower():
                    relink = False
            if relink:
                title = str(row.get("title") or f"A-{int(assignment_id):04d}")
                tid = self.db.agent_create_thread(
                    agent_code=str(assignee_code).strip().lower(),
                    title=title,
                    context_json={"source": reason, "assignment_id": int(assignment_id)},
                )
                if tid:
                    self.db.agent_link_assignment_thread(
                        assignment_id=int(assignment_id),
                        thread_id=int(tid),
                        actor_code="navi",
                        note=f"Thread relinked after {reason}",
                    )
        except Exception:
            return

    def _prompt_optional_bulk_note(self, title: str) -> tuple[bool, Optional[str]]:
        """Prompt for optional audit note. Returns (ok_clicked, note_or_none)."""
        text, ok = QInputDialog.getText(
            self,
            title,
            "Optional note for assignment event log (leave blank for default):",
            text="",
        )
        if not ok:
            return False, None
        return True, (text or "").strip() or None

    def _bulk_set_filtered_status(self):
        rows = self._filtered_assignment_rows()
        if not rows:
            QMessageBox.information(self, "Assignments", "No assignments match the current filters.")
            return
        statuses = ["queued", "in_progress", "awaiting_review", "blocked", "done", "cancelled"]
        picked, ok = QInputDialog.getItem(
            self,
            "Bulk Update Status",
            "Set status for filtered assignments:",
            statuses,
            0,
            False,
        )
        if not ok or not picked:
            return
        to_status = (picked or "").strip().lower()
        note_ok, custom_note = self._prompt_optional_bulk_note("Bulk Update Status")
        if not note_ok:
            return
        count = len(rows)
        confirm = QMessageBox.question(
            self,
            "Confirm Bulk Update",
            f"Update status to '{to_status}' for {count} assignment(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        updated = 0
        failed = 0
        for r in rows:
            aid = int(r.get("id") or 0)
            if aid <= 0:
                failed += 1
                continue
            ok = self.db.agent_update_assignment_status(
                assignment_id=aid,
                to_status=to_status,
                actor_code="navi",
                note=custom_note or "Bulk status update from CoS board",
            )
            if ok:
                updated += 1
            else:
                failed += 1
        self._refresh_assignment_list()
        QMessageBox.information(self, "Bulk Update", f"Updated: {updated}\nFailed: {failed}")

    def _bulk_set_filtered_priority(self):
        rows = self._filtered_assignment_rows()
        if not rows:
            QMessageBox.information(self, "Assignments", "No assignments match the current filters.")
            return
        val, ok = QInputDialog.getInt(
            self,
            "Bulk Update Priority",
            "Priority (1-5):",
            3,
            1,
            5,
            1,
        )
        if not ok:
            return
        note_ok, custom_note = self._prompt_optional_bulk_note("Bulk Update Priority")
        if not note_ok:
            return
        confirm = QMessageBox.question(
            self,
            "Confirm Bulk Update",
            f"Set priority to P{int(val)} for {len(rows)} assignment(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        updated = 0
        failed = 0
        for r in rows:
            aid = int(r.get("id") or 0)
            if aid <= 0:
                failed += 1
                continue
            ok = self.db.agent_update_assignment_fields(
                assignment_id=aid,
                actor_code="navi",
                priority=int(val),
                note=custom_note or "Bulk priority update from CoS board",
            )
            if ok:
                updated += 1
            else:
                failed += 1
        self._refresh_assignment_list()
        QMessageBox.information(self, "Bulk Update", f"Updated: {updated}\nFailed: {failed}")

    def _bulk_set_filtered_due(self):
        rows = self._filtered_assignment_rows()
        if not rows:
            QMessageBox.information(self, "Assignments", "No assignments match the current filters.")
            return
        text, ok = QInputDialog.getText(
            self,
            "Bulk Update Due Date",
            "Due date (YYYY-MM-DD or none):",
            text="none",
        )
        if not ok:
            return
        due_ok, due = _normalize_iso_due_date_input((text or "").strip())
        if not due_ok:
            QMessageBox.warning(
                self,
                "Assignments",
                "Due date must be a real calendar date in YYYY-MM-DD or none.",
            )
            return
        note_ok, custom_note = self._prompt_optional_bulk_note("Bulk Update Due Date")
        if not note_ok:
            return
        confirm = QMessageBox.question(
            self,
            "Confirm Bulk Update",
            f"Set due date to '{due or '(none)'}' for {len(rows)} assignment(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        updated = 0
        failed = 0
        for r in rows:
            aid = int(r.get("id") or 0)
            if aid <= 0:
                failed += 1
                continue
            ok = self.db.agent_update_assignment_fields(
                assignment_id=aid,
                actor_code="navi",
                due_date=due,
                note=custom_note or "Bulk due-date update from CoS board",
            )
            if ok:
                updated += 1
            else:
                failed += 1
        self._refresh_assignment_list()
        QMessageBox.information(self, "Bulk Update", f"Updated: {updated}\nFailed: {failed}")

    def _bulk_reassign_filtered_assignments(self):
        rows = self._filtered_assignment_rows()
        if not rows:
            QMessageBox.information(self, "Assignments", "No assignments match the current filters.")
            return
        options: list[tuple[str, str]] = []
        for a in self.db.agents_list_active():
            code = str(a.get("code") or "").strip().lower()
            if not code or code == "navi":
                continue
            options.append((f"{a.get('display_name') or code} ({code})", code))
        if not options:
            QMessageBox.information(self, "Assignments", "No assignees available.")
            return
        labels = [x[0] for x in options]
        picked, ok = QInputDialog.getItem(
            self,
            "Bulk Reassign",
            "Reassign filtered assignments to:",
            labels,
            0,
            False,
        )
        if not ok or not picked:
            return
        new_code = ""
        for label, code in options:
            if label == picked:
                new_code = code
                break
        if not new_code:
            return
        note_ok, custom_note = self._prompt_optional_bulk_note("Bulk Reassign")
        if not note_ok:
            return
        confirm = QMessageBox.question(
            self,
            "Confirm Bulk Reassign",
            f"Reassign {len(rows)} filtered assignment(s) to {picked}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        updated = 0
        failed = 0
        for r in rows:
            aid = int(r.get("id") or 0)
            if aid <= 0:
                failed += 1
                continue
            current_assignee = str(r.get("assignee_code") or "").strip().lower()
            if current_assignee == new_code:
                continue
            ok = self.db.agent_reassign_assignment(
                assignment_id=aid,
                new_assignee_code=new_code,
                actor_code="navi",
                note=custom_note or "Bulk reassignment from CoS board",
            )
            if ok:
                self._ensure_assignment_thread_for_assignee(
                    assignment_id=aid,
                    assignee_code=new_code,
                    reason="cos_board_bulk_reassign",
                )
                updated += 1
            else:
                failed += 1
        self._refresh_assignment_list()
        QMessageBox.information(self, "Bulk Reassign", f"Updated: {updated}\nFailed: {failed}")

    def _refresh_chat_list(self):
        """Reload sidebar: list all CoS chats, optionally grouped by project."""
        self.chat_list.clear()
        rows = self.db.cos_get_chats(limit=100)
        for (id_, title, project, created_at, updated_at) in rows:
            label = (title or "New chat")[:50]
            if project:
                label = f"[{project}] " + label
            date_str = (updated_at or created_at or "")[:10]
            if date_str:
                label += f"  ({date_str})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, id_)
            self.chat_list.addItem(item)

    def _assistant_html_with_assignment_links(self, content: str) -> str:
        raw_html = _md_to_html(content or "")

        def _repl(match: re.Match) -> str:
            digits = match.group(1)
            # Keep visible text unchanged (e.g., A-0007) but normalize link target to int id.
            try:
                assignment_id = int(digits)
            except Exception:
                assignment_id = 0
            if assignment_id <= 0:
                return match.group(0)
            return f"<a href='assignment://{assignment_id}'>{match.group(0)}</a>"

        return ASSIGNMENT_REF_PATTERN.sub(_repl, raw_html)

    def _render_chat_history(self):
        if self._current_chat_id is None:
            self.chat_display.setHtml("<p style='color:#9aa0a6;'>(No chat selected.)</p>")
            return
        history = self.db.get_chat_history(f"cos_{self._current_chat_id}", limit=100)
        html_parts = []
        for role, content in history:
            safe = (content or "").replace("<", "&lt;").replace(">", "&gt;")
            if role == "user":
                html_parts.append(f"<p><b>You:</b></p><p>{safe}</p>")
            else:
                html_parts.append(f"<p><b>Navi:</b></p>{self._assistant_html_with_assignment_links(content)}")
        self.chat_display.setHtml("<br>".join(html_parts) if html_parts else "<p style='color:#9aa0a6;'>(No messages yet.)</p>")
        self.ask_output = self.chat_display  # for tests that expect ask_output

    def _assignment_filters(self) -> tuple[Optional[str], Optional[str], str, Optional[str]]:
        status = None
        health = None
        assignee = None
        query = ""
        if hasattr(self, "assignment_status_filter"):
            st = (self.assignment_status_filter.currentText() or "").strip().lower()
            status = None if st in ("", "all") else st
        if hasattr(self, "assignment_health_filter"):
            health = (self.assignment_health_filter.currentData() or "").strip().lower() or None
        if hasattr(self, "assignment_assignee_filter"):
            assignee = (self.assignment_assignee_filter.currentData() or "").strip().lower() or None
        if hasattr(self, "assignment_search_input"):
            query = (self.assignment_search_input.text() or "").strip().lower()
        return status, assignee, query, health

    def _filtered_assignment_rows(self):
        status, assignee, query, health = self._assignment_filters()
        rows = self.db.agent_list_assignments(status=status, assignee_code=assignee, limit=500)
        if query:
            qnorm = query.replace("a-", "").lstrip("0")
            filtered = []
            for r in rows:
                aid = int(r.get("id") or 0)
                title = str(r.get("title") or "").lower()
                brief = str(r.get("brief_md") or "").lower()
                if query in title or query in brief:
                    filtered.append(r)
                    continue
                if qnorm and qnorm.isdigit() and int(qnorm) == aid:
                    filtered.append(r)
                    continue
            rows = filtered

        if health:
            filtered = []
            now = datetime.now()
            for r in rows:
                flags = _assignment_health_flags(r, now=now)
                if health == "overdue" and "overdue" in flags:
                    filtered.append(r)
                    continue
                if health == "stale_blocked" and "stale_blocked" in flags:
                    filtered.append(r)
                    continue
                if health == "stale_review" and "stale_review" in flags:
                    filtered.append(r)
                    continue
                if health == "needs_attention" and any(
                    f in flags for f in ("overdue", "stale_blocked", "stale_review")
                ):
                    filtered.append(r)
                    continue
            rows = filtered
        return rows

    def _refresh_assignment_list(self):
        if not hasattr(self, "assignment_list"):
            return
        self.assignment_list.clear()
        rows = self._filtered_assignment_rows()
        now = datetime.now()

        for r in rows:
            aid = int(r.get("id") or 0)
            title = str(r.get("title") or "Untitled")
            assignee = str(r.get("assignee_code") or "agent")
            status = str(r.get("status") or "queued")
            pr = int(r.get("priority") or 3)
            due = str(r.get("due_date") or "")
            label = f"A-{aid:04d} [{status}] P{pr} {title} → {assignee}"
            if due:
                label += f" (due {due})"
            health_flags = _assignment_health_flags(r, now=now)
            if health_flags:
                tag_map = {
                    "overdue": "OVERDUE",
                    "stale_blocked": "BLOCKED_3D",
                    "stale_review": "REVIEW_3D",
                }
                tags = [tag_map[h] for h in ("overdue", "stale_blocked", "stale_review") if h in health_flags]
                if tags:
                    label += f" [{' | '.join(tags)}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, aid)
            self.assignment_list.addItem(item)
        if hasattr(self, "assignment_count_label"):
            self.assignment_count_label.setText(f"{len(rows)} assignment(s)")

    def _export_assignment_board_markdown(self):
        rows = self._filtered_assignment_rows()
        now = datetime.now()
        default_name = f"delegation_board_{now.strftime('%Y%m%d_%H%M%S')}.md"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Delegation Board (Markdown)",
            default_name,
            "Markdown Files (*.md);;All Files (*)",
        )
        if not file_path:
            return

        st, asg, query, health = self._assignment_filters()
        status_str = st or "all"
        health_str = health or "all"
        assignee_str = asg or "all"
        query_str = query or "(none)"

        def _esc(v) -> str:
            s = str(v or "").replace("\n", " ").replace("|", "\\|").strip()
            return s

        lines = [
            "# Delegation Board Snapshot",
            "",
            f"- Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- Filter status: {status_str}",
            f"- Filter health: {health_str}",
            f"- Filter assignee: {assignee_str}",
            f"- Search query: {query_str}",
            f"- Total rows: {len(rows)}",
            "",
            "| Assignment | Status | Health | Priority | Assignee | Due | Title |",
            "|---|---|---|---:|---|---|---|",
        ]
        now_dt = datetime.now()
        for r in rows:
            aid = int(r.get("id") or 0)
            st_row = _esc(r.get("status") or "")
            flags = _assignment_health_flags(r, now=now_dt)
            health_row = _esc(", ".join(flags))
            pr = int(r.get("priority") or 3)
            assignee = _esc(r.get("assignee_code") or "")
            due = _esc(r.get("due_date") or "")
            title = _esc(r.get("title") or "Untitled")
            lines.append(
                f"| A-{aid:04d} | {st_row} | {health_row} | {pr} | {assignee} | {due} | {title} |"
            )

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines).strip() + "\n")
        except Exception as e:
            QMessageBox.warning(self, "Export", f"Could not export delegation board:\n{e}")
            return
        QMessageBox.information(self, "Export", f"Delegation board exported:\n{file_path}")

    def _on_assignment_clicked(self, item):
        aid = item.data(Qt.ItemDataRole.UserRole)
        if aid is None:
            return
        self._current_assignment_id = int(aid)
        row = self.db.agent_get_assignment(self._current_assignment_id)
        if not row:
            self.assignment_details.setPlainText("Assignment not found.")
            return
        health_flags = _assignment_health_flags(row, now=datetime.now())
        events = self.db.agent_get_assignment_events(assignment_id=self._current_assignment_id, limit=40)
        artifacts = self.db.agent_list_artifacts(assignment_id=self._current_assignment_id, limit=10)
        lines = [
            f"ID: A-{int(row.get('id') or 0):04d}",
            f"Title: {row.get('title') or ''}",
            f"Status: {row.get('status') or ''}",
            f"Requester: {row.get('requester_code') or ''}",
            f"Assignee: {row.get('assignee_code') or ''}",
            f"Priority: P{int(row.get('priority') or 3)}",
            f"Due: {row.get('due_date') or '(none)'}",
            f"Health: {', '.join(health_flags) if health_flags else '(ok)'}",
            f"Linked thread: {row.get('source_thread_id') or '(none)'}",
            "",
            "Brief:",
            str(row.get("brief_md") or "").strip(),
        ]
        result_summary = str(row.get("result_summary_md") or "").strip()
        if result_summary:
            lines.extend(["", "Result summary:", result_summary])
        lines.extend(["", f"Artifacts ({len(artifacts)}):"])
        for a in artifacts[:5]:
            art_id = int(a.get("id") or 0)
            art_type = str(a.get("artifact_type") or "artifact")
            art_title = str(a.get("title") or "").strip() or "(untitled)"
            art_ts = str(a.get("created_at") or "")
            lines.append(f"- #{art_id} [{art_type}] {art_title} ({art_ts})")
        lines.extend(["", "Events:"])
        for ev in events:
            et = str(ev.get("event_type") or "")
            fr = str(ev.get("from_status") or "")
            to = str(ev.get("to_status") or "")
            actor = str(ev.get("actor_code") or "")
            note = str(ev.get("note") or "")
            ts = str(ev.get("created_at") or "")
            move = f"{fr} → {to}" if (fr or to) else ""
            tail = f" | {note}" if note else ""
            lines.append(f"- {ts} | {et} {move} | {actor}{tail}".strip())
        self.assignment_details.setPlainText("\n".join(lines).strip())

    def _set_assignment_status(self, to_status: str):
        if not self._current_assignment_id:
            QMessageBox.information(self, "Assignments", "Select an assignment first.")
            return
        ok = self.db.agent_update_assignment_status(
            assignment_id=int(self._current_assignment_id),
            to_status=str(to_status),
            actor_code="navi",
        )
        if not ok:
            QMessageBox.warning(self, "Assignments", f"Could not set status to '{to_status}'.")
            return
        self._refresh_assignment_list()
        # Refresh details panel to reflect new status.
        for i in range(self.assignment_list.count()):
            it = self.assignment_list.item(i)
            if it and int(it.data(Qt.ItemDataRole.UserRole) or 0) == int(self._current_assignment_id):
                self._on_assignment_clicked(it)
                break

    def _set_assignment_priority(self):
        if not self._current_assignment_id:
            QMessageBox.information(self, "Assignments", "Select an assignment first.")
            return
        row = self.db.agent_get_assignment(int(self._current_assignment_id))
        if not row:
            QMessageBox.warning(self, "Assignments", "Assignment not found.")
            return
        current = int(row.get("priority") or 3)
        val, ok = QInputDialog.getInt(
            self,
            "Set Assignment Priority",
            "Priority (1-5):",
            current,
            1,
            5,
            1,
        )
        if not ok:
            return
        updated = self.db.agent_update_assignment_fields(
            assignment_id=int(self._current_assignment_id),
            actor_code="navi",
            priority=int(val),
            note="Updated from CoS board",
        )
        if not updated:
            QMessageBox.warning(self, "Assignments", "Could not update priority.")
            return
        self._refresh_assignment_list()
        self._focus_assignment_by_id(int(self._current_assignment_id))

    def _set_assignment_due(self):
        if not self._current_assignment_id:
            QMessageBox.information(self, "Assignments", "Select an assignment first.")
            return
        row = self.db.agent_get_assignment(int(self._current_assignment_id))
        if not row:
            QMessageBox.warning(self, "Assignments", "Assignment not found.")
            return
        current_due = str(row.get("due_date") or "").strip()
        text, ok = QInputDialog.getText(
            self,
            "Set Assignment Due Date",
            "Due date (YYYY-MM-DD or none):",
            text=current_due,
        )
        if not ok:
            return
        due_ok, due = _normalize_iso_due_date_input((text or "").strip())
        if not due_ok:
            QMessageBox.warning(
                self,
                "Assignments",
                "Due date must be a real calendar date in YYYY-MM-DD or none.",
            )
            return
        updated = self.db.agent_update_assignment_fields(
            assignment_id=int(self._current_assignment_id),
            actor_code="navi",
            due_date=due,
            note="Updated from CoS board",
        )
        if not updated:
            QMessageBox.warning(self, "Assignments", "Could not update due date.")
            return
        self._refresh_assignment_list()
        self._focus_assignment_by_id(int(self._current_assignment_id))

    def _edit_assignment_title(self):
        if not self._current_assignment_id:
            QMessageBox.information(self, "Assignments", "Select an assignment first.")
            return
        row = self.db.agent_get_assignment(int(self._current_assignment_id))
        if not row:
            QMessageBox.warning(self, "Assignments", "Assignment not found.")
            return
        current = str(row.get("title") or "").strip()
        text, ok = QInputDialog.getText(
            self,
            "Edit Assignment Title",
            "Title:",
            text=current,
        )
        if not ok:
            return
        new_title = (text or "").strip()
        if not new_title:
            QMessageBox.warning(self, "Assignments", "Title cannot be empty.")
            return
        updated = self.db.agent_update_assignment_fields(
            assignment_id=int(self._current_assignment_id),
            actor_code="navi",
            title=new_title,
            note="Updated title from CoS board",
        )
        if not updated:
            QMessageBox.warning(self, "Assignments", "Could not update title.")
            return
        self._refresh_assignment_list()
        self._focus_assignment_by_id(int(self._current_assignment_id))

    def _edit_assignment_brief(self):
        if not self._current_assignment_id:
            QMessageBox.information(self, "Assignments", "Select an assignment first.")
            return
        row = self.db.agent_get_assignment(int(self._current_assignment_id))
        if not row:
            QMessageBox.warning(self, "Assignments", "Assignment not found.")
            return
        current = str(row.get("brief_md") or "").strip()
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Edit Assignment Brief",
            "Brief:",
            current,
        )
        if not ok:
            return
        new_brief = (text or "").strip()
        if not new_brief:
            QMessageBox.warning(self, "Assignments", "Brief cannot be empty.")
            return
        updated = self.db.agent_update_assignment_fields(
            assignment_id=int(self._current_assignment_id),
            actor_code="navi",
            brief_md=new_brief,
            note="Updated brief from CoS board",
        )
        if not updated:
            QMessageBox.warning(self, "Assignments", "Could not update brief.")
            return
        self._refresh_assignment_list()
        self._focus_assignment_by_id(int(self._current_assignment_id))

    def _edit_assignment_summary(self):
        if not self._current_assignment_id:
            QMessageBox.information(self, "Assignments", "Select an assignment first.")
            return
        row = self.db.agent_get_assignment(int(self._current_assignment_id))
        if not row:
            QMessageBox.warning(self, "Assignments", "Assignment not found.")
            return
        current = str(row.get("result_summary_md") or "").strip()
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Edit Assignment Summary",
            "Summary:",
            current,
        )
        if not ok:
            return
        saved = self.db.agent_set_assignment_result_summary(
            assignment_id=int(self._current_assignment_id),
            summary_md=(text or "").strip(),
            actor_code="navi",
            note="Updated summary from CoS board",
        )
        if not saved:
            QMessageBox.warning(self, "Assignments", "Could not update summary.")
            return
        self._focus_assignment_by_id(int(self._current_assignment_id))

    def _existing_assignment_task_ids(self) -> set[int]:
        ids: set[int] = set()
        try:
            tasks = self.db.get_tasks(category=None, date_filter=None, specific_date=None)
            for t in tasks:
                text = str(t[1] or "").strip()
                m = re.match(r"^\s*\[A-(\d{1,10})\]", text, flags=re.IGNORECASE)
                if not m:
                    continue
                try:
                    ids.add(int(m.group(1)))
                except Exception:
                    continue
        except Exception:
            return set()
        return ids

    def _create_task_from_assignment(self):
        if not self._current_assignment_id:
            QMessageBox.information(self, "Assignments", "Select an assignment first.")
            return
        row = self.db.agent_get_assignment(int(self._current_assignment_id))
        if not row:
            QMessageBox.warning(self, "Assignments", "Assignment not found.")
            return

        aid = int(row.get("id") or 0)
        existing_assignment_task_ids = self._existing_assignment_task_ids()
        if aid in existing_assignment_task_ids:
            QMessageBox.information(
                self,
                "Assignments",
                f"A dashboard task for A-{aid:04d} already exists.",
            )
            return
        title = str(row.get("title") or "").strip() or f"Assignment A-{aid:04d}"
        task_text = f"[A-{aid:04d}] {title}"

        current_due = str(row.get("due_date") or "").strip()
        due_seed = ""
        if re.match(r"^\d{4}-\d{2}-\d{2}$", current_due):
            yyyy, mm, dd = current_due.split("-")
            due_seed = f"{mm}-{dd}-{yyyy}"
        due_text, ok = QInputDialog.getText(
            self,
            "Create Task from Assignment",
            "Due date (MM-DD-YYYY or none):",
            text=due_seed,
        )
        if not ok:
            return
        due_ok, due_mmddyyyy = _normalize_mmddyyyy_due_date_input((due_text or "").strip())
        if not due_ok:
            QMessageBox.warning(
                self,
                "Assignments",
                "Due date must be a real calendar date in MM-DD-YYYY or none.",
            )
            return
        due = due_mmddyyyy or ""

        category, ok = QInputDialog.getItem(
            self,
            "Create Task from Assignment",
            "Category:",
            ["Business", "Personal"],
            0,
            False,
        )
        if not ok or not category:
            return

        try:
            self.db.add_task(
                session_id=f"cos_assignment_{aid}",
                task_text=task_text,
                due_date=due,
                category=str(category),
                recurrence="None",
                completed=0,
            )
            self.db.agent_add_event(
                assignment_id=aid,
                event_type="task_created",
                actor_code="navi",
                note=f"Created dashboard task: {task_text}",
            )
        except Exception as e:
            QMessageBox.warning(self, "Assignments", f"Could not create task: {e}")
            return

        QMessageBox.information(self, "Assignments", "Dashboard task created from assignment.")
        self._focus_assignment_by_id(int(self._current_assignment_id))

    def _bulk_create_tasks_from_filtered_assignments(self):
        rows = self._filtered_assignment_rows()
        if not rows:
            QMessageBox.information(self, "Assignments", "No assignments match the current filters.")
            return

        category, ok = QInputDialog.getItem(
            self,
            "Bulk Create Tasks",
            "Category:",
            ["Business", "Personal"],
            0,
            False,
        )
        if not ok or not category:
            return

        mode_label, ok = QInputDialog.getItem(
            self,
            "Bulk Create Tasks",
            "Include closed assignments?",
            ["Open only", "All (include done/cancelled)"],
            0,
            False,
        )
        if not ok or not mode_label:
            return
        include_closed = mode_label.startswith("All")
        note_ok, custom_note = self._prompt_optional_bulk_note("Bulk Create Tasks")
        if not note_ok:
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Bulk Create Tasks",
            f"Create dashboard tasks from {len(rows)} filtered assignment(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        existing_assignment_task_ids = self._existing_assignment_task_ids()

        created = 0
        skipped_existing = 0
        skipped_closed = 0
        failed = 0
        session_id = f"cos_bulk_assignment_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        for r in rows:
            aid = int(r.get("id") or 0)
            if aid <= 0:
                failed += 1
                continue
            st = str(r.get("status") or "").strip().lower()
            if (not include_closed) and st in {"done", "cancelled"}:
                skipped_closed += 1
                continue
            title = str(r.get("title") or "").strip() or f"Assignment A-{aid:04d}"
            task_text = f"[A-{aid:04d}] {title}"
            if aid in existing_assignment_task_ids:
                skipped_existing += 1
                continue
            due_iso = str(r.get("due_date") or "").strip()
            due_date = ""
            if re.match(r"^\d{4}-\d{2}-\d{2}$", due_iso):
                yyyy, mm, dd = due_iso.split("-")
                due_date = f"{mm}-{dd}-{yyyy}"
            try:
                self.db.add_task(
                    session_id=session_id,
                    task_text=task_text,
                    due_date=due_date,
                    category=str(category),
                    recurrence="None",
                    completed=0,
                )
                existing_assignment_task_ids.add(aid)
                created += 1
                try:
                    self.db.agent_add_event(
                        assignment_id=aid,
                        event_type="task_created",
                        actor_code="navi",
                        note=(
                            f"Created dashboard task from assignment (bulk): {task_text}"
                            if not custom_note
                            else f"{custom_note} | task: {task_text}"
                        ),
                    )
                except Exception:
                    pass
            except Exception:
                failed += 1

        QMessageBox.information(
            self,
            "Bulk Create Tasks",
            (
                f"Created: {created}\n"
                f"Skipped existing: {skipped_existing}\n"
                f"Skipped closed: {skipped_closed}\n"
                f"Failed: {failed}"
            ),
        )
        if self._current_assignment_id:
            self._focus_assignment_by_id(int(self._current_assignment_id))

    def _view_selected_assignment_artifact(self):
        if not self._current_assignment_id:
            QMessageBox.information(self, "Artifacts", "Select an assignment first.")
            return
        arts = self.db.agent_list_artifacts(assignment_id=int(self._current_assignment_id), limit=100)
        if not arts:
            QMessageBox.information(self, "Artifacts", "No artifacts linked to this assignment yet.")
            return

        labels = []
        for a in arts:
            aid = int(a.get("id") or 0)
            art_type = str(a.get("artifact_type") or "artifact")
            title = str(a.get("title") or "").strip() or "(untitled)"
            ts = str(a.get("created_at") or "")
            labels.append(f"#{aid} [{art_type}] {title} ({ts})")

        picked, ok = QInputDialog.getItem(
            self,
            "Select Artifact",
            "Artifact:",
            labels,
            0,
            False,
        )
        if not ok or not picked:
            return
        index = labels.index(picked)
        art = arts[index]
        art_id = int(art.get("id") or 0)
        art_type = str(art.get("artifact_type") or "artifact")
        art_title = str(art.get("title") or "").strip() or "(untitled)"

        body = str(art.get("content_md") or "").strip()
        if not body:
            body = str(art.get("content_json") or "").strip()
        if not body:
            fp = str(art.get("file_path") or "").strip()
            body = f"(No inline content)\nfile_path: {fp or '(none)'}"

        d = QDialog(self)
        d.setWindowTitle(f"Artifact #{art_id} — {art_type}")
        layout = QVBoxLayout(d)
        layout.addWidget(QLabel(art_title))
        viewer = QTextBrowser()
        viewer.setPlainText(body)
        layout.addWidget(viewer)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(d.reject)
        buttons.accepted.connect(d.accept)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(d.accept)
        layout.addWidget(buttons)
        d.resize(760, 520)
        d.exec()

    def _focus_assignment_by_id(self, assignment_id: int) -> bool:
        aid = int(assignment_id)
        self._refresh_assignment_list()
        if hasattr(self, "sidebar_tabs"):
            self.sidebar_tabs.setCurrentIndex(1)  # Assignments tab
        for i in range(self.assignment_list.count()):
            item = self.assignment_list.item(i)
            if item and int(item.data(Qt.ItemDataRole.UserRole) or 0) == aid:
                self.assignment_list.setCurrentItem(item)
                self._on_assignment_clicked(item)
                return True
        # If filters hide the target assignment, reset filters and retry once.
        if hasattr(self, "assignment_status_filter"):
            self.assignment_status_filter.setCurrentText("All")
        if hasattr(self, "assignment_assignee_filter"):
            self.assignment_assignee_filter.setCurrentIndex(0)
        if hasattr(self, "assignment_search_input"):
            self.assignment_search_input.clear()
        self._refresh_assignment_list()
        for i in range(self.assignment_list.count()):
            item = self.assignment_list.item(i)
            if item and int(item.data(Qt.ItemDataRole.UserRole) or 0) == aid:
                self.assignment_list.setCurrentItem(item)
                self._on_assignment_clicked(item)
                return True
        return False

    def _on_chat_link_clicked(self, url: QUrl):
        href = (url.toString() or "").strip()
        if not href.startswith("assignment://"):
            return
        try:
            aid = int(href.split("assignment://", 1)[1].strip())
        except Exception:
            return
        if aid <= 0:
            return
        ok = self._focus_assignment_by_id(aid)
        if not ok:
            QMessageBox.information(self, "Assignments", f"Could not find assignment A-{aid:04d}.")

    def _resolve_host_with_tab_widget(self):
        """Find the ancestor/window that owns the main tab widget."""
        node = self
        for _ in range(40):
            if node is None:
                break
            tw = getattr(node, "tab_widget", None)
            if isinstance(tw, QTabWidget):
                return node, tw
            next_node = None
            if hasattr(node, "parentWidget"):
                next_node = node.parentWidget()
            if next_node is None and hasattr(node, "parent"):
                next_node = node.parent()
            if next_node is node:
                break
            node = next_node

        win = self.window()
        tw = getattr(win, "tab_widget", None) if win is not None else None
        if isinstance(tw, QTabWidget):
            return win, tw
        return None, None

    def _open_assignment_in_assignee_console(self):
        if not self._current_assignment_id:
            QMessageBox.information(self, "Assignments", "Select an assignment first.")
            return
        row = self.db.agent_get_assignment(int(self._current_assignment_id))
        if not row:
            QMessageBox.warning(self, "Assignments", "Assignment not found.")
            return
        assignee = str(row.get("assignee_code") or "").strip().lower()

        host, tw = self._resolve_host_with_tab_widget()
        if tw is None:
            QMessageBox.information(self, "Assignments", "Could not open assignee tab in this context.")
            return

        route = route_for_agent(assignee)
        if not route:
            QMessageBox.information(
                self,
                "Assignments",
                f"No direct-chat panel is wired yet for assignee '{assignee}'.",
            )
            return

        tab_attr, group_attr, console_attr, tab_label = route
        target_tab = getattr(host, tab_attr, None)
        if target_tab is None:
            QMessageBox.warning(self, "Assignments", f"Could not open tab: {tab_label}.")
            return
        idx = tw.indexOf(target_tab)
        if idx >= 0:
            tw.setCurrentIndex(idx)
        if group_attr:
            group = getattr(target_tab, group_attr, None)
            if group is not None and hasattr(group, "setChecked"):
                group.setChecked(True)
        console = getattr(target_tab, console_attr, None)
        if console is None or not hasattr(console, "focus_assignment"):
            QMessageBox.warning(self, "Assignments", f"{tab_label} chat panel is unavailable.")
            return
        focused = bool(console.focus_assignment(int(self._current_assignment_id)))
        if not focused:
            QMessageBox.warning(self, "Assignments", "Could not focus assignee console on this assignment.")

    def _on_new_chat(self):
        self._current_chat_id = None
        self.chat_display.clear()
        self.ask_input.clear()
        self.chat_display.setPlaceholderText("Type a message below and click Send to start.")

    def _on_chat_clicked(self, item):
        chat_id = item.data(Qt.ItemDataRole.UserRole)
        if chat_id is None:
            return
        self._current_chat_id = chat_id
        self._render_chat_history()
        self.ask_input.clear()

    def _on_send(self):
        if self._ask_worker and self._ask_worker.isRunning():
            return
        msg = self.ask_input.toPlainText().strip()
        if not msg:
            return
        if self._current_chat_id is None:
            # Create new chat and use first message as title
            title = msg[:50] + ("..." if len(msg) > 50 else "")
            self._current_chat_id = self.db.cos_create_chat(title=title)
        session_id = f"cos_{self._current_chat_id}"
        self.db.save_message(session_id, "user", msg)
        history = self.db.get_chat_history(session_id, limit=50)
        self._ask_worker = CosAskWorker(self.db, msg, history, chat_id=self._current_chat_id)
        self._ask_worker.finished_signal.connect(self._on_ask_finished)
        self._ask_worker.error_signal.connect(self._on_ask_error)
        self.ask_btn.setEnabled(False)
        self.ask_progress.setVisible(True)
        self.ask_input.clear()
        self._ask_worker.start()

    def _on_ask_finished(self, result: str):
        self._ask_worker = None
        self.ask_btn.setEnabled(True)
        self.ask_progress.setVisible(False)
        if self._current_chat_id is not None:
            session_id = f"cos_{self._current_chat_id}"
            self.db.save_message(session_id, "assistant", result)
            self.db.cos_update_chat(self._current_chat_id)
        self._refresh_chat_list()
        self._refresh_assignment_list()
        self._render_chat_history()

    def _on_ask_error(self, err: str):
        self._ask_worker = None
        self.ask_btn.setEnabled(True)
        self.ask_progress.setVisible(False)
        self.chat_display.append(f"<p style='color: #e07a7a;'>Error: {err}</p>")

"""
Chief of Staff tab: chat on the left (≥70%), sidebar on the right with chat list by project.
All chats save automatically. Layout like Grok/ChatGPT but sidebar on the right.
"""

import json
import logging
import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton, QLabel, QTextEdit,
    QTextBrowser, QListWidget, QListWidgetItem, QFormLayout, QSpinBox, QTabWidget,
    QMessageBox, QProgressBar, QDialog, QDialogButtonBox, QMenu, QToolButton,
    QSizePolicy, QComboBox, QLineEdit, QInputDialog
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
        form.addRow("Priority (P1-P5):", self.priority_spin)

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
        if due and not re.match(r"^\d{4}-\d{2}-\d{2}$", due):
            QMessageBox.warning(self, "Assignment", "Due date must be YYYY-MM-DD or blank.")
            return
        self.accept()

    def values(self) -> dict:
        due = (self.due_edit.text() or "").strip()
        return {
            "title": (self.title_edit.text() or "").strip(),
            "brief_md": (self.brief_edit.toPlainText() or "").strip(),
            "assignee_code": (self.assignee_combo.currentData() or "").strip().lower(),
            "priority": int(self.priority_spin.value()),
            "due_date": due if due else None,
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
        artifact_row = QHBoxLayout()
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
        self._refresh_assignment_list()
        self._focus_assignment_by_id(int(self._current_assignment_id))

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

    def _refresh_assignment_list(self):
        if not hasattr(self, "assignment_list"):
            return
        self.assignment_list.clear()
        status = None
        assignee = None
        query = ""
        if hasattr(self, "assignment_status_filter"):
            st = (self.assignment_status_filter.currentText() or "").strip().lower()
            status = None if st in ("", "all") else st
        if hasattr(self, "assignment_assignee_filter"):
            assignee = (self.assignment_assignee_filter.currentData() or "").strip().lower() or None
        if hasattr(self, "assignment_search_input"):
            query = (self.assignment_search_input.text() or "").strip().lower()

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
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, aid)
            self.assignment_list.addItem(item)
        if hasattr(self, "assignment_count_label"):
            self.assignment_count_label.setText(f"{len(rows)} assignment(s)")

    def _on_assignment_clicked(self, item):
        aid = item.data(Qt.ItemDataRole.UserRole)
        if aid is None:
            return
        self._current_assignment_id = int(aid)
        row = self.db.agent_get_assignment(self._current_assignment_id)
        if not row:
            self.assignment_details.setPlainText("Assignment not found.")
            return
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

    def _open_assignment_in_assignee_console(self):
        if not self._current_assignment_id:
            QMessageBox.information(self, "Assignments", "Select an assignment first.")
            return
        row = self.db.agent_get_assignment(int(self._current_assignment_id))
        if not row:
            QMessageBox.warning(self, "Assignments", "Assignment not found.")
            return
        assignee = str(row.get("assignee_code") or "").strip().lower()

        host = self.parent()
        tw = getattr(host, "tab_widget", None) if host is not None else None
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

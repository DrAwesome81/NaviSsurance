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
    QSizePolicy
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
        refresh_asg_btn = QPushButton("Refresh")
        refresh_asg_btn.clicked.connect(self._refresh_assignment_list)
        asg_head.addWidget(refresh_asg_btn)
        asg_layout.addLayout(asg_head)
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
        self.asg_open_chat_btn = QPushButton("Open Assignee Chat")
        self.asg_open_chat_btn.clicked.connect(self._open_assignment_in_assignee_console)
        asg_layout.addWidget(self.asg_open_chat_btn)
        tabs.addTab(asg_panel, "Assignments")

        layout.addWidget(tabs)
        self._refresh_chat_list()
        self._refresh_assignment_list()
        return panel

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
        rows = self.db.agent_list_assignments(limit=300)
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
        lines = [
            f"ID: A-{int(row.get('id') or 0):04d}",
            f"Title: {row.get('title') or ''}",
            f"Status: {row.get('status') or ''}",
            f"Requester: {row.get('requester_code') or ''}",
            f"Assignee: {row.get('assignee_code') or ''}",
            f"Priority: P{int(row.get('priority') or 3)}",
            f"Due: {row.get('due_date') or '(none)'}",
            "",
            "Brief:",
            str(row.get("brief_md") or "").strip(),
            "",
            "Events:",
        ]
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

        # agent_code -> (tab_attr, group_attr_or_none, console_attr, tab_label)
        route = {
            "atlas": ("projects_tab", "atlas_chat_group", "atlas_console", "AI Projects"),
            "quill": ("workspace_tab", "quill_chat_group", "quill_console", "Workspace"),
            "sentinel": ("compliance_tab", "sentinel_chat_group", "sentinel_console", "Compliance"),
            "lex": ("compliance_tab", "lex_chat_group", "lex_console", "Compliance"),
            "scout": ("leads_tab", "scout_chat_group", "scout_console", "Leads"),
            "mason": ("tasks_tab", "mason_chat_group", "mason_console", "Tasks"),
            "ledger": ("billing_tab", None, "agent_console", "Billing"),
            "archive": ("library_tab", None, "agent_console", "Library"),
            "pulse": ("intel_tab", None, "agent_console", "Intel"),
            "shield": ("security_tab", None, "agent_console", "Security"),
        }.get(assignee)
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

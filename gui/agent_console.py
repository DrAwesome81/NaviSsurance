from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextBrowser,
    QTextEdit,
    QPushButton,
    QProgressBar,
    QListWidget,
    QListWidgetItem,
    QSplitter,
)

from core.agent_chat_service import agent_chat_response
from core.db import DatabaseManager

logger = logging.getLogger(__name__)


class AgentChatInput(QTextEdit):
    """Enter to send, Shift+Enter for newline."""

    returnPressed = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.returnPressed.emit()
                event.accept()
            return
        super().keyPressEvent(event)


class AgentAskWorker(QThread):
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        *,
        db: DatabaseManager,
        agent_code: str,
        user_message: str,
        conversation_history: list,
        thread_id: int,
        assignment_id: int | None,
    ):
        super().__init__()
        self.db = db
        self.agent_code = (agent_code or "").strip().lower()
        self.user_message = user_message
        self.conversation_history = conversation_history or []
        self.thread_id = int(thread_id)
        self.assignment_id = int(assignment_id) if assignment_id is not None else None

    def run(self):
        try:
            result = agent_chat_response(
                self.db,
                agent_code=self.agent_code,
                user_message=self.user_message,
                conversation_history=self.conversation_history,
                thread_id=self.thread_id,
                assignment_id=self.assignment_id,
            )
            self.finished_signal.emit(result or "")
        except Exception as e:
            logger.exception("AgentAskWorker failed: %s", e)
            self.error_signal.emit(str(e))


class AgentConsole(QWidget):
    """Reusable direct-chat console for named agents."""

    def __init__(self, db: DatabaseManager, *, agent_code: str, parent=None):
        super().__init__(parent)
        self.db = db
        self.agent_code = (agent_code or "").strip().lower()
        self.agent = self.db.agent_get(self.agent_code) or self.db.agent_resolve_by_name(self.agent_code) or {}
        if self.agent:
            self.agent_code = str(self.agent.get("code") or self.agent_code).strip().lower()
        self._current_thread_id: int | None = None
        self._current_assignment_id: int | None = None
        self._worker: AgentAskWorker | None = None
        self._setup_ui()
        self._refresh_threads()
        self._refresh_inbox()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        display_name = str(self.agent.get("display_name") or self.agent_code or "Agent")
        role_title = str(self.agent.get("role_title") or "Specialist")
        title = QLabel(f"{display_name} — {role_title}")
        title.setStyleSheet("color: #e8eaed; font-weight: 600; font-size: 13px;")
        root.addWidget(title)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)
        root.addWidget(splitter)

        # Left: chat transcript + composer.
        chat_panel = QWidget()
        chat_layout = QVBoxLayout(chat_panel)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(8)

        self.chat_display = QTextBrowser()
        self.chat_display.setPlaceholderText("Direct agent chat appears here.")
        chat_layout.addWidget(self.chat_display, 1)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(8)
        self.input_edit = AgentChatInput()
        self.input_edit.setPlaceholderText("Ask this agent directly… (Enter to send, Shift+Enter newline)")
        self.input_edit.setMaximumHeight(90)
        self.input_edit.returnPressed.connect(self._on_send)
        input_row.addWidget(self.input_edit, 1)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self.send_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        input_row.addWidget(self.progress)
        chat_layout.addLayout(input_row)

        splitter.addWidget(chat_panel)

        # Right: threads + inbox.
        side_panel = QWidget()
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)

        threads_head = QHBoxLayout()
        threads_head.addWidget(QLabel("Threads"))
        threads_head.addStretch()
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self._on_new_thread)
        threads_head.addWidget(new_btn)
        side_layout.addLayout(threads_head)

        self.threads_list = QListWidget()
        self.threads_list.itemClicked.connect(self._on_thread_clicked)
        side_layout.addWidget(self.threads_list, 1)

        inbox_head = QHBoxLayout()
        inbox_head.addWidget(QLabel("Inbox"))
        inbox_head.addStretch()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_inbox)
        inbox_head.addWidget(refresh_btn)
        side_layout.addLayout(inbox_head)

        self.inbox_list = QListWidget()
        self.inbox_list.itemClicked.connect(self._on_inbox_clicked)
        side_layout.addWidget(self.inbox_list, 1)

        splitter.addWidget(side_panel)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([700, 300])

    def _thread_session_id(self, thread_id: int) -> str:
        row = self.db.agent_get_thread(int(thread_id))
        if not row:
            return ""
        # (id, agent_code, title, session_id, context_json, created_at, updated_at, last_message_at)
        return str(row[3] or "").strip()

    def _refresh_threads(self):
        self.threads_list.clear()
        rows = self.db.agent_list_threads(agent_code=self.agent_code, limit=100)
        for row in rows:
            tid, _agent_code, title, _session_id, _ctx, _created, _updated, last_msg = row
            label = (str(title or "New thread")).strip()[:60]
            if last_msg:
                label += f"  ({str(last_msg)[:10]})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, int(tid))
            self.threads_list.addItem(item)

        if self._current_thread_id is None and rows:
            self._current_thread_id = int(rows[0][0])
            self._load_current_history()

    def _refresh_inbox(self):
        self.inbox_list.clear()
        rows = self.db.agent_list_assignments(assignee_code=self.agent_code, limit=200)
        for r in rows:
            st = str(r.get("status") or "").strip().lower()
            if st in {"done", "cancelled"}:
                continue
            aid = int(r.get("id") or 0)
            pr = int(r.get("priority") or 3)
            title = str(r.get("title") or "Untitled")
            item = QListWidgetItem(f"A-{aid:04d} [{st}] P{pr} {title}")
            item.setData(Qt.ItemDataRole.UserRole, aid)
            self.inbox_list.addItem(item)

    def _on_new_thread(self):
        tid = self.db.agent_create_thread(agent_code=self.agent_code, title="New thread")
        if tid:
            self._current_thread_id = int(tid)
            self._refresh_threads()
            self._load_current_history()

    def _on_thread_clicked(self, item: QListWidgetItem):
        tid = item.data(Qt.ItemDataRole.UserRole)
        if tid is None:
            return
        self._current_thread_id = int(tid)
        self._load_current_history()

    def _on_inbox_clicked(self, item: QListWidgetItem):
        aid = item.data(Qt.ItemDataRole.UserRole)
        if aid is None:
            return
        self._current_assignment_id = int(aid)
        row = self.db.agent_get_assignment(self._current_assignment_id)
        if not row:
            return
        st = str(row.get("status") or "")
        title = str(row.get("title") or "")
        self.chat_display.append(f"<p style='color:#9aa0a6;'><i>Using assignment A-{int(aid):04d} [{st}] — {title}</i></p>")
        source_thread_id = row.get("source_thread_id")
        if source_thread_id:
            try:
                src = self.db.agent_get_thread(int(source_thread_id))
                if src and str(src[1] or "").strip().lower() == self.agent_code:
                    self._current_thread_id = int(source_thread_id)
                    self._load_current_history()
            except Exception:
                pass

    def _load_current_history(self):
        if self._current_thread_id is None:
            self.chat_display.setHtml("<p style='color:#9aa0a6;'>(No thread selected.)</p>")
            return
        session_id = self._thread_session_id(self._current_thread_id)
        if not session_id:
            self.chat_display.setHtml("<p style='color:#9aa0a6;'>(Thread has no session id.)</p>")
            return
        history = self.db.get_chat_history(session_id, limit=100)
        html_parts: list[str] = []
        for role, content in history:
            safe = (content or "").replace("<", "&lt;").replace(">", "&gt;")
            if role == "user":
                html_parts.append(f"<p><b>You:</b></p><p>{safe}</p>")
            else:
                html_parts.append(f"<p><b>{self.agent.get('display_name') or 'Agent'}:</b></p><p>{safe}</p>")
        self.chat_display.setHtml(
            "<br>".join(html_parts) if html_parts else "<p style='color:#9aa0a6;'>(No messages yet.)</p>"
        )

    def _on_send(self):
        if self._worker and self._worker.isRunning():
            return
        msg = (self.input_edit.toPlainText() or "").strip()
        if not msg:
            return
        if self._current_thread_id is None:
            self._on_new_thread()
            if self._current_thread_id is None:
                return
        session_id = self._thread_session_id(self._current_thread_id)
        if not session_id:
            return

        self.db.save_message(session_id, "user", msg)
        history = self.db.get_chat_history(session_id, limit=80)
        self._worker = AgentAskWorker(
            db=self.db,
            agent_code=self.agent_code,
            user_message=msg,
            conversation_history=history,
            thread_id=int(self._current_thread_id),
            assignment_id=self._current_assignment_id,
        )
        self._worker.finished_signal.connect(self._on_ask_finished)
        self._worker.error_signal.connect(self._on_ask_error)
        self.send_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.input_edit.clear()
        self._worker.start()

    def _on_ask_finished(self, result: str):
        try:
            if self._current_thread_id is not None:
                session_id = self._thread_session_id(self._current_thread_id)
                if session_id:
                    self.db.save_message(session_id, "assistant", result or "")
                    self.db.agent_touch_thread(int(self._current_thread_id), bump_last_message=True)
        finally:
            self._worker = None
            self.send_btn.setEnabled(True)
            self.progress.setVisible(False)
            self._refresh_threads()
            self._refresh_inbox()
            self._load_current_history()

    def _on_ask_error(self, err: str):
        self._worker = None
        self.send_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.chat_display.append(f"<p style='color:#e07a7a;'>Error: {err}</p>")


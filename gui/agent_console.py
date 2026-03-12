from __future__ import annotations

import logging
from typing import Callable

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
    QMessageBox,
    QInputDialog,
    QDialog,
    QDialogButtonBox,
)

from core.agent_chat_service import agent_chat_response
from core.db import DatabaseManager
from gui.notifications import notify_chat_response

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
        runtime_context: str = "",
    ):
        super().__init__()
        self.db = db
        self.agent_code = (agent_code or "").strip().lower()
        self.user_message = user_message
        self.conversation_history = conversation_history or []
        self.thread_id = int(thread_id)
        self.assignment_id = int(assignment_id) if assignment_id is not None else None
        self.runtime_context = str(runtime_context or "")

    def run(self):
        try:
            result = agent_chat_response(
                self.db,
                agent_code=self.agent_code,
                user_message=self.user_message,
                conversation_history=self.conversation_history,
                thread_id=self.thread_id,
                assignment_id=self.assignment_id,
                runtime_context=self.runtime_context,
            )
            self.finished_signal.emit(result or "")
        except Exception as e:
            logger.exception("AgentAskWorker failed: %s", e)
            self.error_signal.emit(str(e))


class AgentConsole(QWidget):
    """Reusable direct-chat console for named agents."""

    def __init__(
        self,
        db: DatabaseManager,
        *,
        agent_code: str,
        parent=None,
        context_provider: Callable[[], str] | None = None,
        response_processor: Callable[[str], str] | None = None,
    ):
        super().__init__(parent)
        self.db = db
        self.agent_code = (agent_code or "").strip().lower()
        self._context_provider = context_provider
        self._response_processor = response_processor
        self.agent = self.db.agent_get(self.agent_code) or self.db.agent_resolve_by_name(self.agent_code) or {}
        if self.agent:
            self.agent_code = str(self.agent.get("code") or self.agent_code).strip().lower()
        self._current_thread_id: int | None = None
        self._current_assignment_id: int | None = None
        self._last_assistant_message: str = ""
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

        self.assignment_label = QLabel("Assignment: (none selected)")
        self.assignment_label.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        self.assignment_label.setWordWrap(True)
        root.addWidget(self.assignment_label)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(lambda: self._set_assignment_status("in_progress"))
        action_row.addWidget(self.start_btn)
        self.review_btn = QPushButton("Review")
        self.review_btn.clicked.connect(lambda: self._set_assignment_status("awaiting_review"))
        action_row.addWidget(self.review_btn)
        self.block_btn = QPushButton("Block")
        self.block_btn.clicked.connect(lambda: self._set_assignment_status("blocked"))
        action_row.addWidget(self.block_btn)
        self.done_btn = QPushButton("Done")
        self.done_btn.clicked.connect(lambda: self._set_assignment_status("done"))
        action_row.addWidget(self.done_btn)
        self.save_artifact_btn = QPushButton("Save Reply Artifact")
        self.save_artifact_btn.clicked.connect(self._save_latest_reply_artifact)
        action_row.addWidget(self.save_artifact_btn)
        self.view_artifacts_btn = QPushButton("View Artifacts")
        self.view_artifacts_btn.clicked.connect(self._view_assignment_artifacts)
        action_row.addWidget(self.view_artifacts_btn)
        self.edit_summary_btn = QPushButton("Edit Summary")
        self.edit_summary_btn.clicked.connect(self._edit_assignment_summary)
        action_row.addWidget(self.edit_summary_btn)
        action_row.addStretch()
        root.addLayout(action_row)

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
        self.focus_assignment(int(aid))

    def focus_assignment(self, assignment_id: int) -> bool:
        """
        Focus this console on a given assignment.
        Selects/creates a linked thread and refreshes transcript + inbox.
        """
        aid = int(assignment_id)
        row = self.db.agent_get_assignment(aid)
        if not row:
            return False
        assignee = str(row.get("assignee_code") or "").strip().lower()
        if assignee != self.agent_code:
            return False

        self._current_assignment_id = aid
        st = str(row.get("status") or "")
        title = str(row.get("title") or "")

        selected_thread: int | None = None
        source_thread_id = row.get("source_thread_id")
        if source_thread_id:
            try:
                src = self.db.agent_get_thread(int(source_thread_id))
                if src and str(src[1] or "").strip().lower() == self.agent_code:
                    selected_thread = int(source_thread_id)
            except Exception:
                selected_thread = None

        if selected_thread is None:
            try:
                selected_thread = self.db.agent_create_thread(
                    agent_code=self.agent_code,
                    title=f"A-{aid:04d}: {title}"[:100],
                    context_json={"assignment_id": aid},
                )
            except Exception:
                selected_thread = None
            if selected_thread:
                try:
                    self.db.agent_link_assignment_thread(
                        assignment_id=aid,
                        thread_id=int(selected_thread),
                        actor_code=self.agent_code,
                        note="Linked from agent console",
                    )
                except Exception:
                    pass

        if selected_thread is not None:
            self._current_thread_id = int(selected_thread)

        self._refresh_threads()
        self._refresh_inbox()
        self._load_current_history()
        self._refresh_assignment_label()
        self.chat_display.append(
            f"<p style='color:#9aa0a6;'><i>Using assignment A-{aid:04d} [{st}] — {title}</i></p>"
        )
        return True

    def _refresh_assignment_label(self):
        if self._current_assignment_id is None:
            self.assignment_label.setText("Assignment: (none selected)")
            return
        row = self.db.agent_get_assignment(int(self._current_assignment_id))
        if not row:
            self.assignment_label.setText("Assignment: (not found)")
            return
        aid = int(row.get("id") or 0)
        status = str(row.get("status") or "")
        title = str(row.get("title") or "Untitled")
        due = str(row.get("due_date") or "")
        due_part = f" | due {due}" if due else ""
        summary_exists = bool(str(row.get("result_summary_md") or "").strip())
        artifacts = self.db.agent_list_artifacts(assignment_id=aid, limit=200)
        meta = []
        if summary_exists:
            meta.append("summary")
        if artifacts:
            meta.append(f"{len(artifacts)} artifact(s)")
        meta_part = f" | {', '.join(meta)}" if meta else ""
        self.assignment_label.setText(f"Assignment A-{aid:04d} [{status}] — {title}{due_part}{meta_part}")

    def _set_assignment_status(self, to_status: str):
        if self._current_assignment_id is None:
            QMessageBox.information(self, "Assignment", "Select an assignment from Inbox first.")
            return
        ok = self.db.agent_update_assignment_status(
            assignment_id=int(self._current_assignment_id),
            to_status=str(to_status),
            actor_code=self.agent_code,
        )
        if not ok:
            QMessageBox.warning(self, "Assignment", f"Could not set status to '{to_status}'.")
            return
        if str(to_status).strip().lower() == "done" and self._last_assistant_message:
            try:
                self.db.agent_set_assignment_result_summary(
                    assignment_id=int(self._current_assignment_id),
                    summary_md=self._last_assistant_message,
                    actor_code=self.agent_code,
                    note="Auto summary from latest assistant reply",
                )
            except Exception:
                pass
        self._refresh_inbox()
        self._refresh_assignment_label()

    def _save_latest_reply_artifact(self):
        if self._current_assignment_id is None:
            QMessageBox.information(self, "Artifacts", "Select an assignment first.")
            return
        if not self._last_assistant_message.strip():
            QMessageBox.information(self, "Artifacts", "No assistant reply available to save yet.")
            return
        aid = int(self._current_assignment_id)
        tid = int(self._current_thread_id) if self._current_thread_id is not None else None
        try:
            art_id = self.db.agent_add_artifact(
                artifact_type="agent_reply",
                assignment_id=aid,
                thread_id=tid,
                title=f"{self.agent.get('display_name') or self.agent_code} update A-{aid:04d}",
                content_md=self._last_assistant_message,
            )
            self.chat_display.append(
                f"<p style='color:#9aa0a6;'><i>Saved reply artifact #{int(art_id)} for A-{aid:04d}.</i></p>"
            )
        except Exception as e:
            QMessageBox.warning(self, "Artifacts", f"Could not save artifact: {e}")

    def _view_assignment_artifacts(self):
        if self._current_assignment_id is None:
            QMessageBox.information(self, "Artifacts", "Select an assignment first.")
            return
        aid = int(self._current_assignment_id)
        arts = self.db.agent_list_artifacts(assignment_id=aid, limit=200)
        if not arts:
            QMessageBox.information(self, "Artifacts", f"No artifacts linked to A-{aid:04d}.")
            return

        labels = []
        for a in arts:
            art_id = int(a.get("id") or 0)
            art_type = str(a.get("artifact_type") or "artifact")
            title = str(a.get("title") or "").strip() or "(untitled)"
            ts = str(a.get("created_at") or "")
            labels.append(f"#{art_id} [{art_type}] {title} ({ts})")
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
        art = arts[labels.index(picked)]
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
        view = QTextBrowser()
        view.setPlainText(body)
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(d.accept)
        buttons.rejected.connect(d.reject)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(d.accept)
        layout.addWidget(buttons)
        d.resize(760, 520)
        d.exec()

    def _edit_assignment_summary(self):
        if self._current_assignment_id is None:
            QMessageBox.information(self, "Summary", "Select an assignment first.")
            return
        aid = int(self._current_assignment_id)
        row = self.db.agent_get_assignment(aid)
        if not row:
            QMessageBox.warning(self, "Summary", "Assignment not found.")
            return
        current = str(row.get("result_summary_md") or "").strip()
        text, ok = QInputDialog.getMultiLineText(
            self,
            f"Edit Summary — A-{aid:04d}",
            "Result summary:",
            current,
        )
        if not ok:
            return
        try:
            saved = self.db.agent_set_assignment_result_summary(
                assignment_id=aid,
                summary_md=(text or "").strip(),
                actor_code=self.agent_code,
                note="Updated from agent console",
            )
        except Exception as e:
            saved = False
            QMessageBox.warning(self, "Summary", f"Could not save summary: {e}")
        if not saved:
            QMessageBox.warning(self, "Summary", "Could not save summary.")
            return
        self._refresh_assignment_label()

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

        # If this thread is linked to an assignment, first transition to in_progress.
        if self._current_assignment_id is not None:
            try:
                row = self.db.agent_get_assignment(int(self._current_assignment_id))
            except Exception:
                row = None
            if row:
                st = str(row.get("status") or "").strip().lower()
                if st in {"queued", "blocked"}:
                    try:
                        self.db.agent_update_assignment_status(
                            assignment_id=int(self._current_assignment_id),
                            to_status="in_progress",
                            actor_code=self.agent_code,
                            note="Started from agent console chat",
                        )
                    except Exception:
                        pass

        self.db.save_message(session_id, "user", msg)
        history = self.db.get_chat_history(session_id, limit=80)
        runtime_context = ""
        if callable(self._context_provider):
            try:
                runtime_context = str(self._context_provider() or "")
            except Exception as e:
                logger.warning("Agent context provider failed: %s", e)
        self._worker = AgentAskWorker(
            db=self.db,
            agent_code=self.agent_code,
            user_message=msg,
            conversation_history=history,
            thread_id=int(self._current_thread_id),
            assignment_id=self._current_assignment_id,
            runtime_context=runtime_context,
        )
        self._worker.finished_signal.connect(self._on_ask_finished)
        self._worker.error_signal.connect(self._on_ask_error)
        self.send_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.input_edit.clear()
        self._worker.start()

    def _on_ask_finished(self, result: str):
        try:
            # Optional processor can parse commands from the reply and apply side effects (e.g. task updates)
            display_result = result or ""
            if callable(self._response_processor):
                try:
                    display_result = self._response_processor(display_result)
                except Exception as e:
                    logger.warning("Response processor failed: %s", e)
            if self._current_thread_id is not None:
                session_id = self._thread_session_id(self._current_thread_id)
                if session_id:
                    self.db.save_message(session_id, "assistant", display_result or "")
                    self.db.agent_touch_thread(int(self._current_thread_id), bump_last_message=True)
            self._last_assistant_message = (display_result or "").strip()
            if self._current_assignment_id is not None and self._last_assistant_message:
                try:
                    aid = int(self._current_assignment_id)
                    tid = int(self._current_thread_id) if self._current_thread_id is not None else None
                    self.db.agent_add_artifact(
                        artifact_type="agent_reply",
                        assignment_id=aid,
                        thread_id=tid,
                        title=f"{self.agent.get('display_name') or self.agent_code} reply A-{aid:04d}",
                        content_md=self._last_assistant_message,
                    )
                except Exception:
                    pass
        finally:
            self._worker = None
            self.send_btn.setEnabled(True)
            self.progress.setVisible(False)
            self._refresh_threads()
            self._refresh_inbox()
            self._refresh_assignment_label()
            self._load_current_history()
            notify_chat_response(self, str(self.agent.get("display_name") or self.agent_code or "Agent"))

    def _on_ask_error(self, err: str):
        self._worker = None
        self.send_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.chat_display.append(f"<p style='color:#e07a7a;'>Error: {err}</p>")


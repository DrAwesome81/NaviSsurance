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
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter, QPushButton, QLabel, QTextEdit,
    QTextBrowser, QListWidget, QListWidgetItem, QFormLayout, QSpinBox, QTabWidget,
    QMessageBox, QProgressBar, QDialog, QDialogButtonBox, QMenu, QToolButton,
    QSizePolicy, QComboBox, QLineEdit, QInputDialog, QFileDialog, QDateEdit, QCheckBox,
    QDoubleSpinBox, QTimeEdit, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl, QDate, QTimer
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
from core.chief_of_staff_service import cos_response, cos_am_sweep
from gui.agent_routing import route_for_agent
from core.agent_chat_service import create_assignment_thread, prime_assignment_handoff
from gui.notifications import notify_chat_response

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


BLOCKED_TIME_DAY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Every day", "daily"),
    ("Weekdays", "weekday"),
    ("Weekends", "weekend"),
    ("Monday", "monday"),
    ("Tuesday", "tuesday"),
    ("Wednesday", "wednesday"),
    ("Thursday", "thursday"),
    ("Friday", "friday"),
    ("Saturday", "saturday"),
    ("Sunday", "sunday"),
)


def _blocked_time_day_label(value: str) -> str:
    needle = str(value or "").strip().lower()
    for label, key in BLOCKED_TIME_DAY_OPTIONS:
        if key == needle:
            return label
    return needle or "Unspecified"


def _normalize_blocked_time_entry(entry: object) -> Optional[dict]:
    if not isinstance(entry, dict):
        return None
    day = str(entry.get("day") or "").strip().lower()
    start = str(entry.get("start") or "").strip()
    end = str(entry.get("end") or "").strip()
    label = str(entry.get("label") or entry.get("title") or "").strip()
    if not day or not start or not end:
        return None
    try:
        datetime.strptime(start, "%H:%M")
        datetime.strptime(end, "%H:%M")
    except Exception:
        return None
    return {
        "day": day,
        "start": start,
        "end": end,
        "label": label,
    }


def _blocked_time_entry_label(entry: dict) -> str:
    day_label = _blocked_time_day_label(str(entry.get("day") or ""))
    start = str(entry.get("start") or "")
    end = str(entry.get("end") or "")
    label = str(entry.get("label") or "").strip()
    if label:
        return f"{day_label} {start}-{end} ({label})"
    return f"{day_label} {start}-{end}"


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


_AGENT_REQUEST_KEYWORDS: tuple[str, ...] = (
    "need ",
    "needs ",
    "please upload",
    "upload ",
    "send ",
    "provide ",
    "provide me",
    "can you share",
    "can you send",
    "clarify",
    "clarification",
    "question",
    "questions",
    "answer ",
    "missing",
    "blocked",
    "waiting on",
    "cannot proceed",
    "can't proceed",
    "unable to proceed",
    "document",
    "documents",
    "file",
    "files",
)


def _single_line_preview(text: str, limit: int = 180) -> str:
    cleaned = " ".join(str(text or "").strip().split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)] + "..."


def _extract_request_lines(text: str, *, limit: int = 3) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    segments: list[str] = []
    for part in re.split(r"(?:\r?\n+|(?<=[\.\?!])\s+)", raw):
        cleaned = " ".join(part.strip().split())
        if cleaned:
            segments.append(cleaned)
    requests: list[str] = []
    seen: set[str] = set()
    for seg in segments:
        seg_l = seg.lower()
        if "?" in seg or any(k in seg_l for k in _AGENT_REQUEST_KEYWORDS):
            key = seg_l.strip()
            if key in seen:
                continue
            seen.add(key)
            requests.append(seg)
            if len(requests) >= limit:
                break
    return requests


def _assignment_agent_followup_snapshot(db: DatabaseManager, row: dict) -> dict:
    """
    Summarize latest agent-side follow-up visible from the linked thread/artifacts so the
    CoS board can show whether the assignee is waiting on user input.
    """
    base = {
        "has_thread": False,
        "latest_agent_reply": "",
        "needs_input": False,
        "request_lines": [],
        "uploaded_files": [],
    }
    if not isinstance(row, dict):
        return base
    aid = int(row.get("id") or 0)
    source_thread_id = int(row.get("source_thread_id") or 0)
    artifacts = db.agent_list_artifacts(assignment_id=aid, limit=50) if aid > 0 else []
    uploaded_files = [
        str(a.get("title") or "").strip() or str(a.get("file_path") or "").strip()
        for a in artifacts
        if str(a.get("artifact_type") or "").strip() == "uploaded_file"
    ]
    base["uploaded_files"] = [x for x in uploaded_files if x]
    if source_thread_id <= 0:
        return base
    thread = db.agent_get_thread(source_thread_id)
    if not thread:
        return base
    base["has_thread"] = True
    session_id = str(thread[3] or "").strip()
    if not session_id:
        return base
    history = db.get_chat_history(session_id, limit=80)
    latest_agent_reply = ""
    for role, content in reversed(history):
        role_s = str(role or "").strip().lower()
        if role_s == "assistant" and str(content or "").strip():
            latest_agent_reply = str(content or "").strip()
            break
    if not latest_agent_reply:
        for art in sorted(artifacts, key=lambda a: str(a.get("created_at") or "")):
            if str(art.get("artifact_type") or "").strip() != "agent_reply":
                continue
            content_md = str(art.get("content_md") or "").strip()
            if content_md:
                latest_agent_reply = content_md
    request_lines = _extract_request_lines(latest_agent_reply)
    base["latest_agent_reply"] = latest_agent_reply
    base["request_lines"] = request_lines
    base["needs_input"] = bool(request_lines)
    return base


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


class CosAmSweepWorker(QThread):
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, db: DatabaseManager, conversation_history: list, chat_id: int = None):
        super().__init__()
        self.db = db
        self.conversation_history = conversation_history or []
        self.chat_id = chat_id

    def run(self):
        try:
            result = cos_am_sweep(self.db, conversation_history=self.conversation_history, chat_id=self.chat_id)
            if result.startswith("Error"):
                self.error_signal.emit(result)
                return
            self.finished_signal.emit(result)
        except Exception as e:
            logger.exception("CoS AM Sweep: %s", e)
            self.error_signal.emit(str(e))


class CosPreferencesDialog(QDialog):
    """Preferences window opened from Options menu."""

    class BlockedTimeDialog(QDialog):
        def __init__(self, *, parent=None, entry: Optional[dict] = None):
            super().__init__(parent)
            self.setWindowTitle("Edit Blocked Time" if entry else "Add Blocked Time")
            layout = QVBoxLayout(self)
            form = QFormLayout()

            self.day_combo = QComboBox()
            for label, value in BLOCKED_TIME_DAY_OPTIONS:
                self.day_combo.addItem(label, value)
            form.addRow("Applies to:", self.day_combo)

            self.start_time_edit = QTimeEdit()
            self.start_time_edit.setDisplayFormat("HH:mm")
            self.start_time_edit.setTime(QDate.currentDate().startOfDay().time())
            form.addRow("Start time:", self.start_time_edit)

            self.end_time_edit = QTimeEdit()
            self.end_time_edit.setDisplayFormat("HH:mm")
            self.end_time_edit.setTime(QDate.currentDate().startOfDay().time().addSecs(3600))
            form.addRow("End time:", self.end_time_edit)

            self.label_edit = QLineEdit()
            self.label_edit.setPlaceholderText("Optional label, e.g. school pickup or gym")
            form.addRow("Label:", self.label_edit)

            layout.addLayout(form)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(self._on_save)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

            normalized = _normalize_blocked_time_entry(entry or {})
            if normalized:
                self.day_combo.setCurrentIndex(max(0, self.day_combo.findData(normalized["day"])))
                try:
                    start_dt = datetime.strptime(normalized["start"], "%H:%M")
                    self.start_time_edit.setTime(start_dt.time())
                except Exception:
                    pass
                try:
                    end_dt = datetime.strptime(normalized["end"], "%H:%M")
                    self.end_time_edit.setTime(end_dt.time())
                except Exception:
                    pass
                self.label_edit.setText(normalized["label"])

        def _on_save(self):
            start_s = self.start_time_edit.time().toString("HH:mm")
            end_s = self.end_time_edit.time().toString("HH:mm")
            if start_s == end_s:
                QMessageBox.warning(self, "Preferences", "Blocked time start and end cannot be identical.")
                return
            self.accept()

        def values(self) -> dict:
            return {
                "day": (self.day_combo.currentData() or "weekday").strip(),
                "start": self.start_time_edit.time().toString("HH:mm"),
                "end": self.end_time_edit.time().toString("HH:mm"),
                "label": (self.label_edit.text() or "").strip(),
            }

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self._extra_behavior_prefs: dict = {}
        self._extra_blocked_entries: list = []
        self.setWindowTitle("Chief of Staff — Preferences")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Optional: constraints the CoS uses (time, boundaries, etc.)"))
        layout.addWidget(QLabel("Operating system / constraints (markdown):"))
        self.prefs_os_edit = QTextEdit()
        self.prefs_os_edit.setPlaceholderText("Optimization order, acceptable stress, family boundaries, etc.")
        self.prefs_os_edit.setMinimumHeight(100)
        layout.addWidget(self.prefs_os_edit)

        layout.addWidget(QLabel("Blocked times:"))
        layout.addWidget(QLabel("Add recurring windows where the CoS should avoid optional meetings or work blocks."))
        self.prefs_blocked_list = QListWidget()
        self.prefs_blocked_list.setMinimumHeight(96)
        layout.addWidget(self.prefs_blocked_list)
        blocked_btn_row = QHBoxLayout()
        self.prefs_blocked_add_btn = QPushButton("Add Block")
        self.prefs_blocked_add_btn.clicked.connect(self._add_blocked_time)
        blocked_btn_row.addWidget(self.prefs_blocked_add_btn)
        self.prefs_blocked_edit_btn = QPushButton("Edit Selected")
        self.prefs_blocked_edit_btn.clicked.connect(self._edit_blocked_time)
        blocked_btn_row.addWidget(self.prefs_blocked_edit_btn)
        self.prefs_blocked_delete_btn = QPushButton("Delete Selected")
        self.prefs_blocked_delete_btn.clicked.connect(self._delete_blocked_time)
        blocked_btn_row.addWidget(self.prefs_blocked_delete_btn)
        blocked_btn_row.addStretch()
        layout.addLayout(blocked_btn_row)

        layout.addWidget(QLabel("Deep work hours per day:"))
        self.prefs_deep_work_spin = QSpinBox()
        self.prefs_deep_work_spin.setRange(0, 12)
        self.prefs_deep_work_spin.setValue(2)
        layout.addWidget(self.prefs_deep_work_spin)

        layout.addWidget(QLabel("Behavior preferences:"))
        behavior_form = QFormLayout()
        self.behavior_tone_combo = QComboBox()
        self.behavior_tone_combo.addItem("Direct", "direct")
        self.behavior_tone_combo.addItem("Balanced", "balanced")
        self.behavior_tone_combo.addItem("Gentle", "gentle")
        behavior_form.addRow("Tone:", self.behavior_tone_combo)

        self.behavior_planning_combo = QComboBox()
        self.behavior_planning_combo.addItem("Concise", "concise")
        self.behavior_planning_combo.addItem("Balanced", "balanced")
        self.behavior_planning_combo.addItem("Detailed", "detailed")
        behavior_form.addRow("Planning detail:", self.behavior_planning_combo)

        self.behavior_scheduling_combo = QComboBox()
        self.behavior_scheduling_combo.addItem("Always ask first", "ask_first")
        self.behavior_scheduling_combo.addItem("Draft first, then confirm", "draft_first")
        self.behavior_scheduling_combo.addItem("Go ahead when the request is clear", "can_schedule_when_clear")
        behavior_form.addRow("Scheduling autonomy:", self.behavior_scheduling_combo)

        self.behavior_evenings_check = QCheckBox("Protect evenings from optional work")
        behavior_form.addRow("", self.behavior_evenings_check)
        self.behavior_weekends_check = QCheckBox("Protect weekends from optional work")
        behavior_form.addRow("", self.behavior_weekends_check)
        self.behavior_confirm_tasks_check = QCheckBox("Ask before creating tasks when intent is ambiguous")
        behavior_form.addRow("", self.behavior_confirm_tasks_check)
        layout.addLayout(behavior_form)

        self.legacy_notice = QLabel("")
        self.legacy_notice.setWordWrap(True)
        self.legacy_notice.setVisible(False)
        layout.addWidget(self.legacy_notice)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._load()

    def _blocked_time_row(self, item: Optional[QListWidgetItem] = None) -> Optional[dict]:
        row_item = item or self.prefs_blocked_list.currentItem()
        if row_item is None:
            return None
        row = row_item.data(Qt.ItemDataRole.UserRole)
        return dict(row) if isinstance(row, dict) else None

    def _set_blocked_time_item(self, entry: dict, *, item: Optional[QListWidgetItem] = None):
        normalized = _normalize_blocked_time_entry(entry)
        if not normalized:
            return
        target = item or QListWidgetItem()
        target.setData(Qt.ItemDataRole.UserRole, normalized)
        target.setText(_blocked_time_entry_label(normalized))
        if item is None:
            self.prefs_blocked_list.addItem(target)

    def _refresh_legacy_notice(self):
        notes: list[str] = []
        if self._extra_blocked_entries:
            notes.append(f"{len(self._extra_blocked_entries)} legacy blocked-time entr{'y' if len(self._extra_blocked_entries) == 1 else 'ies'} will be preserved.")
        if self._extra_behavior_prefs:
            notes.append(f"{len(self._extra_behavior_prefs)} unrecognized behavior preference entr{'y' if len(self._extra_behavior_prefs) == 1 else 'ies'} will be preserved.")
        self.legacy_notice.setVisible(bool(notes))
        self.legacy_notice.setText(" ".join(notes))

    def _add_blocked_time(self):
        dialog = self.BlockedTimeDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._set_blocked_time_item(dialog.values())
        self.prefs_blocked_list.setCurrentRow(self.prefs_blocked_list.count() - 1)

    def _edit_blocked_time(self):
        row = self._blocked_time_row()
        item = self.prefs_blocked_list.currentItem()
        if not row or item is None:
            QMessageBox.information(self, "Preferences", "Select a blocked time first.")
            return
        dialog = self.BlockedTimeDialog(parent=self, entry=row)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._set_blocked_time_item(dialog.values(), item=item)

    def _delete_blocked_time(self):
        current_row = self.prefs_blocked_list.currentRow()
        if current_row < 0:
            QMessageBox.information(self, "Preferences", "Select a blocked time first.")
            return
        self.prefs_blocked_list.takeItem(current_row)

    def _load(self):
        row = self.db.cos_get_preferences()
        if not row:
            return
        operating_system_md, blocked_times_json, deep_work_hours, behavior_prefs_json, _ = row
        self.prefs_os_edit.setPlainText(operating_system_md or "")
        self.prefs_deep_work_spin.setValue(deep_work_hours if deep_work_hours is not None else 2)
        self.prefs_blocked_list.clear()
        self._extra_blocked_entries = []
        try:
            blocked_rows = json.loads(blocked_times_json or "[]")
            if not isinstance(blocked_rows, list):
                blocked_rows = []
        except Exception:
            blocked_rows = []
        for raw in blocked_rows:
            normalized = _normalize_blocked_time_entry(raw)
            if normalized:
                self._set_blocked_time_item(normalized)
            else:
                self._extra_blocked_entries.append(raw)

        try:
            behavior = json.loads(behavior_prefs_json or "{}")
            if not isinstance(behavior, dict):
                behavior = {}
        except Exception:
            behavior = {}
        known_behavior_keys = {
            "tone",
            "planning_detail",
            "scheduling_autonomy",
            "protect_evenings",
            "protect_weekends",
            "confirm_ambiguous_tasks",
        }
        self._extra_behavior_prefs = {
            key: value for key, value in behavior.items() if key not in known_behavior_keys
        }
        self.behavior_tone_combo.setCurrentIndex(
            max(0, self.behavior_tone_combo.findData(str(behavior.get("tone") or "balanced").strip()))
        )
        self.behavior_planning_combo.setCurrentIndex(
            max(0, self.behavior_planning_combo.findData(str(behavior.get("planning_detail") or "balanced").strip()))
        )
        self.behavior_scheduling_combo.setCurrentIndex(
            max(
                0,
                self.behavior_scheduling_combo.findData(
                    str(behavior.get("scheduling_autonomy") or "draft_first").strip()
                ),
            )
        )
        self.behavior_evenings_check.setChecked(bool(behavior.get("protect_evenings")))
        self.behavior_weekends_check.setChecked(bool(behavior.get("protect_weekends")))
        self.behavior_confirm_tasks_check.setChecked(bool(behavior.get("confirm_ambiguous_tasks")))
        self._refresh_legacy_notice()

    def _save(self):
        os_md = self.prefs_os_edit.toPlainText().strip()
        blocked_rows = []
        for idx in range(self.prefs_blocked_list.count()):
            item = self.prefs_blocked_list.item(idx)
            row = self._blocked_time_row(item)
            if row:
                blocked_rows.append(row)
        blocked_rows.extend(self._extra_blocked_entries)
        blocked = json.dumps(blocked_rows)

        behavior = dict(self._extra_behavior_prefs)
        behavior["tone"] = (self.behavior_tone_combo.currentData() or "balanced").strip()
        behavior["planning_detail"] = (self.behavior_planning_combo.currentData() or "balanced").strip()
        behavior["scheduling_autonomy"] = (
            self.behavior_scheduling_combo.currentData() or "draft_first"
        ).strip()
        behavior["protect_evenings"] = bool(self.behavior_evenings_check.isChecked())
        behavior["protect_weekends"] = bool(self.behavior_weekends_check.isChecked())
        behavior["confirm_ambiguous_tasks"] = bool(self.behavior_confirm_tasks_check.isChecked())
        self.db.cos_set_preferences(
            operating_system_md=os_md,
            blocked_times_json=blocked,
            deep_work_hours=self.prefs_deep_work_spin.value(),
            behavior_prefs_json=json.dumps(behavior),
        )
        QMessageBox.information(self, "Preferences", "Saved.")
        self.accept()


class GlobalMemoryDialog(QDialog):
    """Inspect and prune global durable memory entries."""


    class EditDialog(QDialog):
        def __init__(self, *, parent=None, row: Optional[tuple] = None):
            super().__init__(parent)
            self._memory_id = int(row[0]) if row else None
            self.setWindowTitle("Edit Global Memory" if row else "Add Global Memory")
            layout = QVBoxLayout(self)
            form = QFormLayout()

            self.kind_combo = QComboBox()
            for label, value in (
                ("Taught", "taught"),
                ("Fact", "fact"),
                ("Preference", "preference"),
                ("Alias", "alias"),
                ("Note", "note"),
            ):
                self.kind_combo.addItem(label, value)
            form.addRow("Kind:", self.kind_combo)

            self.source_edit = QLineEdit()
            self.source_edit.setPlaceholderText("teach_navi, auto_chat, manual, etc.")
            form.addRow("Source:", self.source_edit)

            self.confidence_spin = QDoubleSpinBox()
            self.confidence_spin.setRange(0.0, 1.0)
            self.confidence_spin.setDecimals(2)
            self.confidence_spin.setSingleStep(0.05)
            self.confidence_spin.setValue(1.0)
            form.addRow("Confidence:", self.confidence_spin)

            self.status_combo = QComboBox()
            for label, value in (
                ("Approved", "approved"),
                ("Pending Review", "pending"),
                ("Rejected", "rejected"),
            ):
                self.status_combo.addItem(label, value)
            form.addRow("Status:", self.status_combo)

            self.content_edit = QTextEdit()
            self.content_edit.setMinimumHeight(100)
            form.addRow("Content:", self.content_edit)

            self.json_edit = QTextEdit()
            self.json_edit.setPlaceholderText("Optional JSON metadata")
            self.json_edit.setMinimumHeight(90)
            form.addRow("JSON data:", self.json_edit)

            layout.addLayout(form)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(self._on_save)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

            if row:
                _mem_id, kind, content, source, confidence, approval_status, json_data, _created_at, _updated_at = row
                idx = max(0, self.kind_combo.findData(str(kind or "").strip()))
                self.kind_combo.setCurrentIndex(idx)
                self.source_edit.setText(str(source or ""))
                self.confidence_spin.setValue(float(confidence or 0))
                self.status_combo.setCurrentIndex(max(0, self.status_combo.findData(str(approval_status or "").strip())))
                self.content_edit.setPlainText(str(content or ""))
                self.json_edit.setPlainText("" if json_data is None else str(json_data))
            else:
                self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData("fact")))
                self.source_edit.setText("manual")
                self.status_combo.setCurrentIndex(max(0, self.status_combo.findData("approved")))

        def _on_save(self):
            content = (self.content_edit.toPlainText() or "").strip()
            if not content:
                QMessageBox.warning(self, "Global Memory", "Content is required.")
                return
            json_text = (self.json_edit.toPlainText() or "").strip()
            if json_text:
                try:
                    json.loads(json_text)
                except json.JSONDecodeError:
                    QMessageBox.warning(self, "Global Memory", "JSON data must be valid JSON.")
                    return
            self.accept()

        def values(self) -> dict:
            json_text = (self.json_edit.toPlainText() or "").strip()
            return {
                "id": self._memory_id,
                "kind": (self.kind_combo.currentData() or "note").strip(),
                "source": (self.source_edit.text() or "").strip() or "manual",
                "confidence": float(self.confidence_spin.value()),
                "approval_status": (self.status_combo.currentData() or "approved").strip(),
                "content": (self.content_edit.toPlainText() or "").strip(),
                "json_data": json_text or None,
            }

    def __init__(self, db: DatabaseManager, parent=None, *, initial_status: Optional[str] = None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Navi Global Memory")
        self.resize(860, 540)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Inspect what Navi has stored globally. You can search, filter, add, edit, refresh, and delete entries."))

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search memory content...")
        self.search_edit.returnPressed.connect(self._reload)
        controls.addWidget(self.search_edit, 1)
        controls.addWidget(QLabel("Kind:"))
        self.kind_filter = QComboBox()
        self.kind_filter.addItem("All", "")
        self.kind_filter.addItem("Taught", "taught")
        self.kind_filter.addItem("Fact", "fact")
        self.kind_filter.addItem("Preference", "preference")
        self.kind_filter.addItem("Alias", "alias")
        self.kind_filter.currentIndexChanged.connect(self._reload)
        controls.addWidget(self.kind_filter)
        controls.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("All", "")
        self.status_filter.addItem("Approved", "approved")
        self.status_filter.addItem("Pending", "pending")
        self.status_filter.addItem("Rejected", "rejected")
        self.status_filter.currentIndexChanged.connect(self._reload)
        controls.addWidget(self.status_filter)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._reload)
        controls.addWidget(self.refresh_btn)
        layout.addLayout(controls)

        body = QHBoxLayout()
        self.memory_list = QListWidget()
        self.memory_list.currentItemChanged.connect(self._update_detail)
        body.addWidget(self.memory_list, 2)
        self.detail_browser = QTextBrowser()
        self.detail_browser.setPlaceholderText("Select a memory entry to inspect it.")
        body.addWidget(self.detail_browser, 3)
        layout.addLayout(body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.add_btn = QPushButton("Add Memory")
        self.add_btn.clicked.connect(self._add_memory)
        buttons.addButton(self.add_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.edit_btn = QPushButton("Edit Selected")
        self.edit_btn.clicked.connect(self._edit_selected)
        buttons.addButton(self.edit_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.approve_btn = QPushButton("Approve Selected")
        self.approve_btn.clicked.connect(lambda: self._set_selected_status("approved"))
        buttons.addButton(self.approve_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.reject_btn = QPushButton("Reject Selected")
        self.reject_btn.clicked.connect(lambda: self._set_selected_status("rejected"))
        buttons.addButton(self.reject_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.clicked.connect(self._delete_selected)
        buttons.addButton(self.delete_btn, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        if initial_status:
            idx = self.status_filter.findData(str(initial_status).strip())
            if idx >= 0:
                self.status_filter.blockSignals(True)
                self.status_filter.setCurrentIndex(idx)
                self.status_filter.blockSignals(False)
        self._reload()

    @staticmethod
    def _json_payload(json_data) -> Optional[dict]:
        if isinstance(json_data, dict):
            return json_data
        text = str(json_data or "").strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    @classmethod
    def _alias_payload(cls, row: tuple) -> Optional[dict]:
        payload = cls._json_payload(row[6] if len(row) > 6 else None)
        alias_payload = payload.get("alias") if isinstance(payload, dict) else None
        if isinstance(alias_payload, dict):
            term = str(alias_payload.get("term") or "").strip()
            canonical = str(alias_payload.get("canonical") or "").strip()
            if term and canonical:
                synonyms = alias_payload.get("synonyms") or []
                if not isinstance(synonyms, list):
                    synonyms = []
                return {
                    "term": term,
                    "canonical": canonical,
                    "synonyms": [str(item).strip() for item in synonyms if str(item).strip()],
                }
        return None

    def _row_label(self, row: tuple) -> str:
        _mem_id, kind, content, source, confidence, approval_status, _json_data, created_at, _updated_at = row
        alias_payload = self._alias_payload(row) if str(kind or "").strip() == "alias" else None
        if alias_payload:
            text = f"{alias_payload['term']} -> {alias_payload['canonical']}"
        else:
            text = (str(content or "").strip() or "(empty)").replace("\n", " ")
        if len(text) > 88:
            text = text[:85] + "..."
        kind_s = str(kind or "note").strip() or "note"
        source_s = str(source or "unknown").strip() or "unknown"
        status_s = str(approval_status or "approved").strip() or "approved"
        return f"[{status_s}/{kind_s}] {text} ({source_s}, {float(confidence or 0):.2f})"

    def _reload(self):
        query = (self.search_edit.text() or "").strip()
        kind = (self.kind_filter.currentData() or "").strip() or None
        approval_status = (self.status_filter.currentData() or "").strip() or None
        try:
            if query:
                rows = self.db.user_memory_search(
                    query=query,
                    kind=kind,
                    approval_status=approval_status,
                    limit=200,
                )
            else:
                rows = self.db.user_memory_recent(kind=kind, approval_status=approval_status, limit=200)
        except Exception as e:
            QMessageBox.warning(self, "Global Memory", f"Could not load memory entries.\n\n{e}")
            return
        self.memory_list.clear()
        for row in rows:
            item = QListWidgetItem(self._row_label(row))
            item.setData(Qt.ItemDataRole.UserRole, row)
            self.memory_list.addItem(item)
        if self.memory_list.count() > 0:
            self.memory_list.setCurrentRow(0)
        else:
            self.detail_browser.setHtml("<p style='color: #9aa0a6;'>(No matching memory entries.)</p>")

    def _update_detail(self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem] = None):
        if current is None:
            self.detail_browser.setHtml("<p style='color: #9aa0a6;'>(No selection)</p>")
            return
        row = current.data(Qt.ItemDataRole.UserRole)
        if not row:
            self.detail_browser.setHtml("<p style='color: #9aa0a6;'>(No selection)</p>")
            return
        mem_id, kind, content, source, confidence, approval_status, json_data, created_at, updated_at = row
        alias_payload = self._alias_payload(row) if str(kind or "").strip() == "alias" else None
        json_html = ""
        if json_data:
            json_html = (
                "<p><b>JSON data</b></p><pre>"
                + str(json_data).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                + "</pre>"
            )
        alias_html = ""
        if alias_payload:
            alias_html = (
                "<p><b>Alias fields</b><br>"
                f"<b>Term:</b> {str(alias_payload['term']).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}<br>"
                f"<b>Canonical:</b> {str(alias_payload['canonical']).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}"
            )
            synonyms = alias_payload.get("synonyms") or []
            if synonyms:
                alias_html += (
                    "<br><b>Synonyms:</b> "
                    + ", ".join(
                        str(item).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        for item in synonyms
                    )
                )
            alias_html += "</p>"
        html = (
            f"<p><b>ID:</b> {mem_id}<br>"
            f"<b>Kind:</b> {kind}<br>"
            f"<b>Source:</b> {source}<br>"
            f"<b>Confidence:</b> {float(confidence or 0):.2f}<br>"
            f"<b>Status:</b> {approval_status}<br>"
            f"<b>Created:</b> {created_at}<br>"
            f"<b>Updated:</b> {updated_at}</p>"
            f"{alias_html}"
            f"<p><b>Content</b></p><pre>{str(content or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}</pre>"
            f"{json_html}"
        )
        self.detail_browser.setHtml(html)

    def _selected_row(self) -> Optional[tuple]:
        item = self.memory_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _add_memory(self):
        d = self.EditDialog(parent=self)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        values = d.values()
        self.db.user_memory_add(
            kind=values["kind"],
            content=values["content"],
            source=values["source"],
            confidence=values["confidence"],
            approval_status=values["approval_status"],
            json_data=values["json_data"],
        )
        self._reload()

    def _edit_selected(self):
        row = self._selected_row()
        if not row:
            QMessageBox.information(self, "Global Memory", "Select a memory entry first.")
            return
        d = self.EditDialog(parent=self, row=row)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        values = d.values()
        ok = self.db.user_memory_update(
            int(values["id"]),
            kind=values["kind"],
            content=values["content"],
            source=values["source"],
            confidence=values["confidence"],
            approval_status=values["approval_status"],
            json_data=values["json_data"],
        )
        if not ok:
            QMessageBox.warning(self, "Global Memory", "That memory entry could not be updated.")
            return
        self._reload()

    def _set_selected_status(self, approval_status: str):
        row = self._selected_row()
        if not row:
            QMessageBox.information(self, "Global Memory", "Select a memory entry first.")
            return
        if not self.db.user_memory_set_approval_status(int(row[0]), approval_status):
            QMessageBox.warning(self, "Global Memory", "That memory entry could not be updated.")
            return
        self._reload()

    def _delete_selected(self):
        row = self._selected_row()
        if not row:
            QMessageBox.information(self, "Global Memory", "Select a memory entry first.")
            return
        mem_id = int(row[0])
        kind = str(row[1] or "note")
        content = str(row[2] or "").strip()
        preview = content if len(content) <= 120 else content[:117] + "..."
        reply = QMessageBox.question(
            self,
            "Delete Memory",
            f"Delete this {kind} memory?\n\n{preview}",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self.db.user_memory_delete(mem_id):
            QMessageBox.warning(self, "Global Memory", "That memory entry could not be deleted.")
            return
        self._reload()


class BulkDueDateDialog(QDialog):
    """Pick a due date (YYYY-MM-DD) or set to none, with manual override."""

    def __init__(self, *, parent=None, default_due: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("Bulk Update Due Date")
        self._due_value: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Pick a due date, choose none, or type a manual ISO value."))

        form = QFormLayout()
        self.none_check = QCheckBox("No due date (none)")
        form.addRow("", self.none_check)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
        if default_due:
            try:
                dt = datetime.strptime(str(default_due).strip(), "%Y-%m-%d")
                self.date_edit.setDate(QDate(dt.year, dt.month, dt.day))
            except Exception:
                pass
        form.addRow("Pick date:", self.date_edit)

        self.manual_edit = QLineEdit()
        self.manual_edit.setPlaceholderText("YYYY-MM-DD or none (optional manual override)")
        form.addRow("Manual override:", self.manual_edit)

        layout.addLayout(form)

        def _sync_enabled():
            is_none = bool(self.none_check.isChecked())
            self.date_edit.setEnabled(not is_none)

        self.none_check.stateChanged.connect(lambda _v: _sync_enabled())
        _sync_enabled()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_ok(self):
        raw = (self.manual_edit.text() or "").strip()
        if raw:
            ok, due = _normalize_iso_due_date_input(raw)
            if not ok:
                QMessageBox.warning(self, "Assignments", "Due date must be YYYY-MM-DD or none.")
                return
            self._due_value = due
            self.accept()
            return

        if self.none_check.isChecked():
            self._due_value = None
            self.accept()
            return

        qd = self.date_edit.date()
        self._due_value = qd.toString("yyyy-MM-dd")
        self.accept()

    def due_date(self) -> Optional[str]:
        return self._due_value


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
        self._am_sweep_worker = None
        self._current_chat_id = None
        self._current_assignment_id = None
        self._assignment_table_state_restoring = True
        self._assignment_filter_state_restoring = True
        self._setup_ui()
        self._restore_assignment_filter_state()
        self._restore_assignment_table_state()
        self._assignment_table_state_restoring = False
        self._assignment_filter_state_restoring = False
        self._memory_badge_timer = QTimer(self)
        self._memory_badge_timer.setInterval(15000)
        self._memory_badge_timer.timeout.connect(self._refresh_pending_memory_indicator)
        self._memory_badge_timer.start()
        self._refresh_pending_memory_indicator()

    def _control_min_height(self, *, extra_padding: int = 14) -> int:
        metrics = self.fontMetrics()
        return max(30, metrics.height() + int(extra_padding))

    def _chat_entry_min_height(self, *, lines: int = 2) -> int:
        metrics = self.ask_input.fontMetrics() if hasattr(self, "ask_input") else self.fontMetrics()
        return max(48, metrics.lineSpacing() * int(lines) + 18)

    def _assignment_table_state_key(self) -> str:
        return "chief_of_staff.assignment_table_state"

    def _assignment_filter_state_key(self) -> str:
        return "chief_of_staff.assignment_filter_state"

    def _save_assignment_table_state(self, *_args) -> None:
        if self._assignment_table_state_restoring:
            return
        table = getattr(self, "assignment_list", None)
        if table is None or not hasattr(self.db, "set_setting"):
            return
        try:
            header = table.horizontalHeader()
            payload = {
                "sort_column": int(header.sortIndicatorSection()),
                "sort_order": int(header.sortIndicatorOrder().value),
                "column_widths": [int(table.columnWidth(i)) for i in range(table.columnCount())],
            }
            self.db.set_setting(self._assignment_table_state_key(), json.dumps(payload))
        except Exception:
            logger.debug("Could not persist assignment table state.", exc_info=True)

    def _restore_assignment_table_state(self) -> None:
        table = getattr(self, "assignment_list", None)
        if table is None or not hasattr(self.db, "get_setting"):
            return
        raw = str(self.db.get_setting(self._assignment_table_state_key(), "") or "").strip()
        if not raw:
            return
        try:
            payload = json.loads(raw)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        widths = payload.get("column_widths")
        sort_column = payload.get("sort_column")
        sort_order = payload.get("sort_order")
        self._assignment_table_state_restoring = True
        try:
            header = table.horizontalHeader()
            if isinstance(widths, list):
                for i, width in enumerate(widths[: table.columnCount()]):
                    try:
                        width_int = int(width)
                    except Exception:
                        continue
                    if width_int > 24:
                        header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                        table.setColumnWidth(i, width_int)
            if sort_column is not None:
                try:
                    col = int(sort_column)
                except Exception:
                    col = 0
                order = Qt.SortOrder.AscendingOrder
                try:
                    if int(sort_order) == int(Qt.SortOrder.DescendingOrder.value):
                        order = Qt.SortOrder.DescendingOrder
                except Exception:
                    order = Qt.SortOrder.AscendingOrder
                if 0 <= col < table.columnCount():
                    header.setSortIndicator(col, order)
                    table.sortByColumn(col, order)
        finally:
            self._assignment_table_state_restoring = False

    def _save_assignment_filter_state(self, *_args) -> None:
        if self._assignment_filter_state_restoring:
            return
        if not hasattr(self.db, "set_setting"):
            return
        try:
            payload = {
                "scope": str(self.assignment_scope_filter.currentData() or ""),
                "status": str(self.assignment_status_filter.currentText() or ""),
                "health": str(self.assignment_health_filter.currentData() or ""),
                "followup": str(self.assignment_followup_filter.currentData() or ""),
                "assignee": str(self.assignment_assignee_filter.currentData() or ""),
                "search": str(self.assignment_search_input.text() or ""),
            }
            self.db.set_setting(self._assignment_filter_state_key(), json.dumps(payload))
        except Exception:
            logger.debug("Could not persist assignment filter state.", exc_info=True)

    def _restore_assignment_filter_state(self) -> None:
        if not hasattr(self.db, "get_setting"):
            return
        raw = str(self.db.get_setting(self._assignment_filter_state_key(), "") or "").strip()
        if not raw:
            return
        try:
            payload = json.loads(raw)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        try:
            self.assignment_scope_filter.blockSignals(True)
            self.assignment_status_filter.blockSignals(True)
            self.assignment_health_filter.blockSignals(True)
            self.assignment_followup_filter.blockSignals(True)
            self.assignment_assignee_filter.blockSignals(True)
            self.assignment_search_input.blockSignals(True)

            idx = self.assignment_scope_filter.findData(str(payload.get("scope") or ""))
            if idx >= 0:
                self.assignment_scope_filter.setCurrentIndex(idx)

            status_text = str(payload.get("status") or "").strip()
            if status_text:
                idx = self.assignment_status_filter.findText(status_text)
                if idx >= 0:
                    self.assignment_status_filter.setCurrentIndex(idx)

            idx = self.assignment_health_filter.findData(str(payload.get("health") or ""))
            if idx >= 0:
                self.assignment_health_filter.setCurrentIndex(idx)

            idx = self.assignment_followup_filter.findData(str(payload.get("followup") or ""))
            if idx >= 0:
                self.assignment_followup_filter.setCurrentIndex(idx)

            idx = self.assignment_assignee_filter.findData(str(payload.get("assignee") or ""))
            if idx >= 0:
                self.assignment_assignee_filter.setCurrentIndex(idx)

            self.assignment_search_input.setText(str(payload.get("search") or ""))
        finally:
            self.assignment_scope_filter.blockSignals(False)
            self.assignment_status_filter.blockSignals(False)
            self.assignment_health_filter.blockSignals(False)
            self.assignment_followup_filter.blockSignals(False)
            self.assignment_assignee_filter.blockSignals(False)
            self.assignment_search_input.blockSignals(False)

    def _apply_button_metrics(
        self,
        button: QPushButton | QToolButton,
        *,
        width_padding: int = 26,
        min_width: int = 0,
    ) -> None:
        metrics = button.fontMetrics()
        text = button.text() or ""
        button.setMinimumHeight(self._control_min_height())
        try:
            target_width = metrics.horizontalAdvance(text) + int(width_padding)
        except Exception:
            target_width = int(min_width or 0)
        button.setMinimumWidth(max(int(min_width), int(target_width)))

    def _refresh_task_views(self) -> None:
        """Best-effort refresh of Tasks tab + Dashboard task list."""
        try:
            win = self.window()
        except Exception:
            win = None
        if win is None:
            return
        try:
            if hasattr(win, "dashboard_tab") and hasattr(win.dashboard_tab, "load_tasks_filtered"):
                QTimer.singleShot(0, win.dashboard_tab.load_tasks_filtered)
        except Exception:
            pass
        try:
            if hasattr(win, "tasks_tab") and hasattr(win.tasks_tab, "refresh_tasks"):
                QTimer.singleShot(0, win.tasks_tab.refresh_tasks)
        except Exception:
            pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)
        splitter.addWidget(self._build_chat_panel())
        sidebar = self._build_sidebar()
        sidebar.setMinimumWidth(420)
        splitter.addWidget(sidebar)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([880, 520])
        layout.addWidget(splitter)

    def _build_chat_panel(self):
        """Left: chat window + entry box only. Options in a menu."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        # Top row: optional options button (right-aligned)
        top_row = QHBoxLayout()
        top_row.addStretch()
        self.pending_memory_btn = QPushButton("Review pending memory")
        self.pending_memory_btn.setVisible(False)
        self.pending_memory_btn.clicked.connect(self._open_pending_memory_review)
        self.pending_memory_btn.setStyleSheet(
            "QPushButton { color: #fce8b2; background-color: #3b2c10; border: 1px solid #8a6d1d; padding: 6px 12px; border-radius: 6px; }"
            "QPushButton:hover { background-color: #4a3612; color: #fff3cd; }"
        )
        self._apply_button_metrics(self.pending_memory_btn, min_width=178)
        top_row.addWidget(self.pending_memory_btn)
        self.options_btn = QToolButton()
        self.options_btn.setText("⋮ Options")
        self.options_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.options_btn.setStyleSheet(
            "QToolButton { color: #e8eaed; background-color: #22252c; border: 1px solid #2e2f32; padding: 6px 12px; border-radius: 6px; }"
            "QToolButton:hover { background-color: #3a3b3e; color: #e8eaed; }"
        )
        self._apply_button_metrics(self.options_btn, min_width=108)
        menu = QMenu()
        am_sweep_action = QAction("AM Sweep", self)
        am_sweep_action.triggered.connect(self._on_am_sweep)
        menu.addAction(am_sweep_action)
        am_sweep_rerun_action = QAction("AM Sweep (Run again)", self)
        am_sweep_rerun_action.triggered.connect(self._on_am_sweep_rerun)
        menu.addAction(am_sweep_rerun_action)
        prefs_action = QAction("Preferences…", self)
        prefs_action.triggered.connect(self._open_preferences)
        menu.addAction(prefs_action)
        self.pending_memory_action = QAction("Review Pending Memory…", self)
        self.pending_memory_action.triggered.connect(self._open_pending_memory_review)
        menu.addAction(self.pending_memory_action)
        self.memory_action = QAction("Global Memory…", self)
        self.memory_action.triggered.connect(self._open_global_memory)
        menu.addAction(self.memory_action)
        commands_action = QAction("Action Commands…", self)
        commands_action.triggered.connect(self._open_command_cheatsheet)
        menu.addAction(commands_action)
        menu.aboutToShow.connect(self._refresh_pending_memory_indicator)
        self.options_btn.setMenu(menu)
        top_row.addWidget(self.options_btn)
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
        self.ask_input.setMaximumHeight(120)
        self.ask_input.setMinimumHeight(self._chat_entry_min_height(lines=2))
        self.ask_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ask_input.returnPressed.connect(self._on_send)
        entry_row.addWidget(self.ask_input)
        self.ask_btn = QPushButton("Send")
        self.ask_btn.clicked.connect(self._on_send)
        self._apply_button_metrics(self.ask_btn, min_width=88)
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

    def _pending_user_memory_count(self) -> int:
        try:
            return int(self.db.user_memory_count(approval_status="pending"))
        except Exception:
            logger.exception("Could not count pending global memory entries.")
            return 0

    def _refresh_pending_memory_indicator(self):
        count = self._pending_user_memory_count()
        if hasattr(self, "pending_memory_btn"):
            self.pending_memory_btn.setVisible(count > 0)
            if count == 1:
                self.pending_memory_btn.setText("Review 1 pending memory")
            else:
                self.pending_memory_btn.setText(f"Review {count} pending memories")
        if hasattr(self, "pending_memory_action"):
            if count == 1:
                self.pending_memory_action.setText("Review Pending Memory… (1)")
            else:
                self.pending_memory_action.setText(f"Review Pending Memory… ({count})")
            self.pending_memory_action.setEnabled(count > 0)
        if hasattr(self, "memory_action"):
            if count > 0:
                self.memory_action.setText(f"Global Memory… ({count} pending)")
            else:
                self.memory_action.setText("Global Memory…")

    def _open_global_memory(self, checked: bool = False, *, initial_status: Optional[str] = None):
        _ = checked
        d = GlobalMemoryDialog(self.db, self, initial_status=initial_status)
        d.exec()
        self._refresh_pending_memory_indicator()

    def _open_pending_memory_review(self, checked: bool = False):
        _ = checked
        self._open_global_memory(initial_status="pending")

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
        self._apply_button_metrics(new_btn, min_width=96)
        chats_layout.addWidget(new_btn)
        self.chat_list = QListWidget()
        self.chat_list.itemClicked.connect(self._on_chat_clicked)
        chats_layout.addWidget(self.chat_list)
        tabs.addTab(chats_panel, "Chats")

        # Assignments tab
        asg_panel = QWidget()
        asg_layout = QVBoxLayout(asg_panel)
        asg_layout.setContentsMargins(0, 0, 0, 0)
        asg_title_row = QHBoxLayout()
        asg_title_row.setSpacing(8)
        asg_title_row.addWidget(QLabel("Delegation Board"))
        asg_title_row.addStretch()
        asg_layout.addLayout(asg_title_row)
        asg_head = QGridLayout()
        asg_head.setHorizontalSpacing(6)
        asg_head.setVerticalSpacing(6)
        new_asg_btn = QPushButton("New")
        new_asg_btn.clicked.connect(self._create_assignment_from_board)
        self._apply_button_metrics(new_asg_btn, min_width=72)
        new_asg_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        asg_head.addWidget(new_asg_btn, 0, 0)
        reassign_btn = QPushButton("Reassign")
        reassign_btn.clicked.connect(self._reassign_selected_assignment)
        self._apply_button_metrics(reassign_btn, min_width=96)
        reassign_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        asg_head.addWidget(reassign_btn, 0, 1)
        bulk_status_btn = QPushButton("Bulk Status")
        bulk_status_btn.clicked.connect(self._bulk_set_filtered_status)
        self._apply_button_metrics(bulk_status_btn, min_width=110)
        bulk_status_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        asg_head.addWidget(bulk_status_btn, 0, 2)
        bulk_priority_btn = QPushButton("Bulk Priority")
        bulk_priority_btn.clicked.connect(self._bulk_set_filtered_priority)
        self._apply_button_metrics(bulk_priority_btn, min_width=116)
        bulk_priority_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        asg_head.addWidget(bulk_priority_btn, 0, 3)
        bulk_due_btn = QPushButton("Bulk Due")
        bulk_due_btn.clicked.connect(self._bulk_set_filtered_due)
        self._apply_button_metrics(bulk_due_btn, min_width=92)
        bulk_due_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        asg_head.addWidget(bulk_due_btn, 1, 0)
        bulk_reassign_btn = QPushButton("Bulk Reassign")
        bulk_reassign_btn.clicked.connect(self._bulk_reassign_filtered_assignments)
        self._apply_button_metrics(bulk_reassign_btn, min_width=126)
        bulk_reassign_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        asg_head.addWidget(bulk_reassign_btn, 1, 1)
        export_btn = QPushButton("Export")
        export_btn.clicked.connect(self._export_assignment_board_markdown)
        self._apply_button_metrics(export_btn, min_width=84)
        export_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        asg_head.addWidget(export_btn, 1, 2)
        refresh_asg_btn = QPushButton("Refresh")
        refresh_asg_btn.clicked.connect(self._refresh_assignment_list)
        self._apply_button_metrics(refresh_asg_btn, min_width=88)
        refresh_asg_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        asg_head.addWidget(refresh_asg_btn, 1, 3)
        asg_layout.addLayout(asg_head)

        filters = QGridLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setHorizontalSpacing(6)
        filters.setVerticalSpacing(6)
        self.assignment_scope_filter = QComboBox()
        self.assignment_scope_filter.addItem("Open only", "open")
        self.assignment_scope_filter.addItem("All (include done/cancelled)", "all")
        self.assignment_scope_filter.currentTextChanged.connect(lambda _t: self._refresh_assignment_list())
        self.assignment_scope_filter.currentIndexChanged.connect(self._save_assignment_filter_state)
        self.assignment_scope_filter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        filters.addWidget(self.assignment_scope_filter, 0, 0)

        self.assignment_status_filter = QComboBox()
        self.assignment_status_filter.addItems(
            ["All", "queued", "in_progress", "awaiting_review", "blocked", "done", "cancelled"]
        )
        self.assignment_status_filter.currentTextChanged.connect(lambda _t: self._refresh_assignment_list())
        self.assignment_status_filter.currentIndexChanged.connect(self._save_assignment_filter_state)
        self.assignment_status_filter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        filters.addWidget(self.assignment_status_filter, 0, 1)

        self.assignment_health_filter = QComboBox()
        self.assignment_health_filter.addItem("Health: All", "")
        self.assignment_health_filter.addItem("Overdue", "overdue")
        self.assignment_health_filter.addItem("Blocked 3d+", "stale_blocked")
        self.assignment_health_filter.addItem("Awaiting Review 3d+", "stale_review")
        self.assignment_health_filter.addItem("Needs Attention", "needs_attention")
        self.assignment_health_filter.currentTextChanged.connect(lambda _t: self._refresh_assignment_list())
        self.assignment_health_filter.currentIndexChanged.connect(self._save_assignment_filter_state)
        self.assignment_health_filter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        filters.addWidget(self.assignment_health_filter, 1, 0)

        self.assignment_assignee_filter = QComboBox()
        self.assignment_assignee_filter.addItem("All assignees", "")
        for a in self.db.agents_list_active():
            code = str(a.get("code") or "").strip().lower()
            if not code or code == "navi":
                continue
            label = f"{a.get('display_name') or code} ({code})"
            self.assignment_assignee_filter.addItem(label, code)
        self.assignment_assignee_filter.currentTextChanged.connect(lambda _t: self._refresh_assignment_list())
        self.assignment_assignee_filter.currentIndexChanged.connect(self._save_assignment_filter_state)
        self.assignment_assignee_filter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        filters.addWidget(self.assignment_assignee_filter, 1, 1)

        self.assignment_followup_filter = QComboBox()
        self.assignment_followup_filter.addItem("Follow-up: All", "")
        self.assignment_followup_filter.addItem("Needs Input", "needs_input")
        self.assignment_followup_filter.addItem("No Input Needed", "clear")
        self.assignment_followup_filter.currentTextChanged.connect(lambda _t: self._refresh_assignment_list())
        self.assignment_followup_filter.currentIndexChanged.connect(self._save_assignment_filter_state)
        self.assignment_followup_filter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        filters.addWidget(self.assignment_followup_filter, 2, 0)

        self.assignment_search_input = QLineEdit()
        self.assignment_search_input.setPlaceholderText("Search title / brief / A-####")
        self.assignment_search_input.textChanged.connect(lambda _t: self._refresh_assignment_list())
        self.assignment_search_input.textChanged.connect(self._save_assignment_filter_state)
        self.assignment_search_input.setMinimumHeight(self._control_min_height(extra_padding=10))
        filters.addWidget(self.assignment_search_input, 3, 0, 1, 2)
        asg_layout.addLayout(filters)

        self.assignment_count_label = QLabel("")
        self.assignment_count_label.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        asg_layout.addWidget(self.assignment_count_label)

        self.assignment_list = QTableWidget(0, 8)
        self.assignment_list.setHorizontalHeaderLabels(
            ["Assignment", "Status", "Needs Input", "Priority", "Assignee", "Due", "Health", "Title"]
        )
        self.assignment_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.assignment_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.assignment_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.assignment_list.setAlternatingRowColors(True)
        self.assignment_list.setSortingEnabled(True)
        self.assignment_list.verticalHeader().setVisible(False)
        self.assignment_list.itemSelectionChanged.connect(self._on_assignment_selection_changed)
        header = self.assignment_list.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSortIndicatorShown(True)
        header.sectionResized.connect(self._save_assignment_table_state)
        header.sortIndicatorChanged.connect(self._save_assignment_table_state)
        asg_layout.addWidget(self.assignment_list, 1)
        self.assignment_details = QTextBrowser()
        self.assignment_details.setPlaceholderText("Select an assignment to view details.")
        asg_layout.addWidget(self.assignment_details, 1)
        btn_row = QGridLayout()
        btn_row.setHorizontalSpacing(6)
        btn_row.setVerticalSpacing(6)
        self.asg_start_btn = QPushButton("Start")
        self.asg_start_btn.clicked.connect(lambda: self._set_assignment_status("in_progress"))
        self._apply_button_metrics(self.asg_start_btn, min_width=92)
        self.asg_start_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_row.addWidget(self.asg_start_btn, 0, 0)
        self.asg_set_priority_btn = QPushButton("Set Priority")
        self.asg_set_priority_btn.clicked.connect(self._set_assignment_priority)
        self._apply_button_metrics(self.asg_set_priority_btn, min_width=110)
        self.asg_set_priority_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_row.addWidget(self.asg_set_priority_btn, 0, 1)
        self.asg_set_due_btn = QPushButton("Set Due")
        self.asg_set_due_btn.clicked.connect(self._set_assignment_due)
        self._apply_button_metrics(self.asg_set_due_btn, min_width=96)
        self.asg_set_due_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_row.addWidget(self.asg_set_due_btn, 0, 2)
        self.asg_review_btn = QPushButton("Awaiting Review")
        self.asg_review_btn.clicked.connect(lambda: self._set_assignment_status("awaiting_review"))
        self._apply_button_metrics(self.asg_review_btn, min_width=138)
        self.asg_review_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_row.addWidget(self.asg_review_btn, 1, 0)
        self.asg_block_btn = QPushButton("Block")
        self.asg_block_btn.clicked.connect(lambda: self._set_assignment_status("blocked"))
        self._apply_button_metrics(self.asg_block_btn, min_width=92)
        self.asg_block_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_row.addWidget(self.asg_block_btn, 1, 1)
        self.asg_done_btn = QPushButton("Done")
        self.asg_done_btn.clicked.connect(lambda: self._set_assignment_status("done"))
        self._apply_button_metrics(self.asg_done_btn, min_width=92)
        self.asg_done_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_row.addWidget(self.asg_done_btn, 1, 2)
        self.asg_cancel_btn = QPushButton("Cancel")
        self.asg_cancel_btn.clicked.connect(lambda: self._set_assignment_status("cancelled"))
        self._apply_button_metrics(self.asg_cancel_btn, min_width=92)
        self.asg_cancel_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_row.addWidget(self.asg_cancel_btn, 2, 0, 1, 3)
        asg_layout.addLayout(btn_row)
        edit_row = QGridLayout()
        edit_row.setHorizontalSpacing(6)
        edit_row.setVerticalSpacing(6)
        self.asg_reopen_btn = QPushButton("Reopen")
        self.asg_reopen_btn.clicked.connect(lambda: self._set_assignment_status("queued"))
        self._apply_button_metrics(self.asg_reopen_btn, min_width=92)
        self.asg_reopen_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        edit_row.addWidget(self.asg_reopen_btn, 0, 0)
        self.asg_edit_title_btn = QPushButton("Edit Title")
        self.asg_edit_title_btn.clicked.connect(self._edit_assignment_title)
        self._apply_button_metrics(self.asg_edit_title_btn, min_width=108)
        self.asg_edit_title_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        edit_row.addWidget(self.asg_edit_title_btn, 0, 1)
        self.asg_edit_brief_btn = QPushButton("Edit Brief")
        self.asg_edit_brief_btn.clicked.connect(self._edit_assignment_brief)
        self._apply_button_metrics(self.asg_edit_brief_btn, min_width=108)
        self.asg_edit_brief_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        edit_row.addWidget(self.asg_edit_brief_btn, 1, 0)
        self.asg_edit_summary_btn = QPushButton("Edit Summary")
        self.asg_edit_summary_btn.clicked.connect(self._edit_assignment_summary)
        self._apply_button_metrics(self.asg_edit_summary_btn, min_width=122)
        self.asg_edit_summary_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        edit_row.addWidget(self.asg_edit_summary_btn, 1, 1)
        asg_layout.addLayout(edit_row)
        artifact_row = QGridLayout()
        artifact_row.setHorizontalSpacing(6)
        artifact_row.setVerticalSpacing(6)
        self.asg_create_task_btn = QPushButton("Create Task")
        self.asg_create_task_btn.clicked.connect(self._create_task_from_assignment)
        self._apply_button_metrics(self.asg_create_task_btn, min_width=116)
        self.asg_create_task_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        artifact_row.addWidget(self.asg_create_task_btn, 0, 0)
        self.asg_bulk_create_tasks_btn = QPushButton("Bulk Create Tasks")
        self.asg_bulk_create_tasks_btn.clicked.connect(self._bulk_create_tasks_from_filtered_assignments)
        self._apply_button_metrics(self.asg_bulk_create_tasks_btn, min_width=152)
        self.asg_bulk_create_tasks_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        artifact_row.addWidget(self.asg_bulk_create_tasks_btn, 0, 1)
        self.asg_view_artifact_btn = QPushButton("View Artifact")
        self.asg_view_artifact_btn.clicked.connect(self._view_selected_assignment_artifact)
        self._apply_button_metrics(self.asg_view_artifact_btn, min_width=118)
        self.asg_view_artifact_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        artifact_row.addWidget(self.asg_view_artifact_btn, 1, 0, 1, 2)
        asg_layout.addLayout(artifact_row)
        self.asg_open_chat_btn = QPushButton("Open Assignee Chat")
        self.asg_open_chat_btn.clicked.connect(self._open_assignment_in_assignee_console)
        self._apply_button_metrics(self.asg_open_chat_btn, min_width=160)
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

        aid = self.db.agent_create_assignment(
            title=title,
            brief_md=brief,
            requester_code="navi",
            assignee_code=assignee,
            priority=priority,
            due_date=due_date,
            context_json=context_obj,
        )
        if not aid:
            QMessageBox.warning(self, "Assignments", "Could not create assignment.")
            return
        try:
            thread_id = create_assignment_thread(
                self.db,
                assignment_id=int(aid),
                assignee_code=assignee,
                reason="manual_cos_board_assign",
                actor_code="navi",
                context_json=context_obj,
            )
            if thread_id:
                prime_assignment_handoff(
                    self.db,
                    assignment_id=int(aid),
                    thread_id=int(thread_id),
                )
        except Exception:
            pass
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
                tid = create_assignment_thread(
                    self.db,
                    assignment_id=int(assignment_id),
                    assignee_code=str(assignee_code).strip().lower(),
                    reason=reason,
                    actor_code="navi",
                    context_json={"source": reason},
                )
                if tid:
                    prime_assignment_handoff(
                        self.db,
                        assignment_id=int(assignment_id),
                        thread_id=int(tid),
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
        dlg = BulkDueDateDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        due = dlg.due_date()
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

    def _scroll_chat_to_bottom(self):
        try:
            scrollbar = self.chat_display.verticalScrollBar()
            QTimer.singleShot(0, lambda: scrollbar.setValue(scrollbar.maximum()))
        except Exception:
            pass

    def _capture_chat_scroll_state(self) -> dict | None:
        try:
            scrollbar = self.chat_display.verticalScrollBar()
            value = int(scrollbar.value())
            maximum = int(scrollbar.maximum())
            return {
                "value": value,
                "maximum": maximum,
                "at_bottom": (maximum - value) <= 24,
            }
        except Exception:
            return None

    def _restore_chat_scroll_state(self, state: Optional[dict], *, force_bottom: bool = False):
        if force_bottom or not state:
            self._scroll_chat_to_bottom()
            return
        if bool(state.get("at_bottom")):
            self._scroll_chat_to_bottom()
            return
        try:
            scrollbar = self.chat_display.verticalScrollBar()
            target = max(0, min(int(state.get("value") or 0), int(scrollbar.maximum())))
            QTimer.singleShot(0, lambda: scrollbar.setValue(target))
        except Exception:
            pass

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

    def _render_chat_history(self, *, preserve_scroll: bool = False, force_bottom: bool = False):
        scroll_state = self._capture_chat_scroll_state() if preserve_scroll else None
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
        self._restore_chat_scroll_state(scroll_state, force_bottom=(force_bottom or not preserve_scroll))

    def _assignment_filters(self) -> tuple[Optional[str], Optional[str], str, Optional[str], Optional[str], bool]:
        status = None
        health = None
        followup = None
        assignee = None
        query = ""
        include_closed = False
        if hasattr(self, "assignment_scope_filter"):
            include_closed = str(self.assignment_scope_filter.currentData() or "").strip().lower() == "all"
        if hasattr(self, "assignment_status_filter"):
            st = (self.assignment_status_filter.currentText() or "").strip().lower()
            status = None if st in ("", "all") else st
        if hasattr(self, "assignment_health_filter"):
            health = (self.assignment_health_filter.currentData() or "").strip().lower() or None
        if hasattr(self, "assignment_followup_filter"):
            followup = (self.assignment_followup_filter.currentData() or "").strip().lower() or None
        if hasattr(self, "assignment_assignee_filter"):
            assignee = (self.assignment_assignee_filter.currentData() or "").strip().lower() or None
        if hasattr(self, "assignment_search_input"):
            query = (self.assignment_search_input.text() or "").strip().lower()
        return status, assignee, query, health, followup, include_closed

    def _filtered_assignment_rows(self):
        status, assignee, query, health, followup, include_closed = self._assignment_filters()
        rows = self.db.agent_list_assignments(status=status, assignee_code=assignee, limit=500)
        if not include_closed:
            rows = [
                r for r in rows if str(r.get("status") or "").strip().lower() not in {"done", "cancelled"}
            ]
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
        if followup:
            filtered = []
            for r in rows:
                snap = _assignment_agent_followup_snapshot(self.db, r)
                needs_input = bool(snap.get("needs_input"))
                if followup == "needs_input" and needs_input:
                    filtered.append(r)
                elif followup == "clear" and not needs_input:
                    filtered.append(r)
            rows = filtered
        return rows

    def _refresh_assignment_list(self):
        if not hasattr(self, "assignment_list"):
            return
        current_aid = int(self._current_assignment_id or 0)
        header = self.assignment_list.horizontalHeader()
        sort_col = int(header.sortIndicatorSection()) if header is not None else 0
        sort_order = header.sortIndicatorOrder() if header is not None else Qt.SortOrder.AscendingOrder
        self.assignment_list.setSortingEnabled(False)
        self.assignment_list.clearContents()
        rows = self._filtered_assignment_rows()
        now = datetime.now()
        self.assignment_list.setRowCount(len(rows))

        for row_idx, r in enumerate(rows):
            aid = int(r.get("id") or 0)
            title = str(r.get("title") or "Untitled")
            assignee = str(r.get("assignee_code") or "agent")
            status = str(r.get("status") or "queued")
            pr = int(r.get("priority") or 3)
            due = str(r.get("due_date") or "")
            try:
                followup = _assignment_agent_followup_snapshot(self.db, r)
            except Exception:
                followup = {}
            health_flags = _assignment_health_flags(r, now=now)
            tag_map = {
                "overdue": "OVERDUE",
                "stale_blocked": "BLOCKED_3D",
                "stale_review": "REVIEW_3D",
            }
            health_text = " | ".join(
                [tag_map[h] for h in ("overdue", "stale_blocked", "stale_review") if h in health_flags]
            )
            needs_input = "Yes" if followup.get("needs_input") else ""

            values = [
                (f"A-{aid:04d}", aid),
                (status, status),
                (needs_input, 1 if needs_input else 0),
                (f"P{pr}", pr),
                (assignee, assignee),
                (due or "", due or "9999-12-31"),
                (health_text, health_text),
                (title, title.lower()),
            ]
            for col, (display, sort_value) in enumerate(values):
                item = QTableWidgetItem(str(display))
                item.setData(Qt.ItemDataRole.UserRole, aid)
                item.setData(Qt.ItemDataRole.EditRole, sort_value)
                self.assignment_list.setItem(row_idx, col, item)
        if hasattr(self, "assignment_count_label"):
            self.assignment_count_label.setText(f"{len(rows)} assignment(s)")
        self.assignment_list.setSortingEnabled(True)
        if 0 <= sort_col < self.assignment_list.columnCount():
            self.assignment_list.sortByColumn(sort_col, sort_order)
        if current_aid > 0:
            self._select_assignment_row(current_aid)

    def _selected_assignment_id(self) -> int:
        if not hasattr(self, "assignment_list"):
            return 0
        row = int(self.assignment_list.currentRow())
        if row < 0:
            return 0
        item = self.assignment_list.item(row, 0)
        return int(item.data(Qt.ItemDataRole.UserRole) or 0) if item is not None else 0

    def _select_assignment_row(self, assignment_id: int) -> bool:
        aid = int(assignment_id or 0)
        if aid <= 0 or not hasattr(self, "assignment_list"):
            return False
        for row in range(self.assignment_list.rowCount()):
            item = self.assignment_list.item(row, 0)
            if item is None:
                continue
            if int(item.data(Qt.ItemDataRole.UserRole) or 0) == aid:
                self.assignment_list.selectRow(row)
                self.assignment_list.setCurrentCell(row, 0)
                return True
        return False

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

        st, asg, query, health, followup, _include_closed = self._assignment_filters()
        status_str = st or "all"
        health_str = health or "all"
        followup_str = followup or "all"
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
            f"- Filter follow-up: {followup_str}",
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

    def _on_assignment_selection_changed(self):
        aid = self._selected_assignment_id()
        if aid <= 0:
            return
        self._on_assignment_clicked(aid)

    def _on_assignment_clicked(self, item_or_id):
        aid = item_or_id
        if isinstance(item_or_id, QTableWidgetItem):
            aid = item_or_id.data(Qt.ItemDataRole.UserRole)
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
        followup = _assignment_agent_followup_snapshot(self.db, row)
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
        latest_reply = str(followup.get("latest_agent_reply") or "").strip()
        request_lines = [str(x).strip() for x in (followup.get("request_lines") or []) if str(x).strip()]
        uploaded_files = [str(x).strip() for x in (followup.get("uploaded_files") or []) if str(x).strip()]
        lines.extend(
            [
                "",
                "Agent follow-up:",
                f"Needs input: {'yes' if followup.get('needs_input') else 'no'}",
            ]
        )
        if latest_reply:
            lines.extend(["Latest agent update:", _single_line_preview(latest_reply, limit=500)])
        else:
            lines.append("Latest agent update: (none yet)")
        if request_lines:
            lines.append("Requested from you:")
            for req in request_lines:
                lines.append(f"- {req}")
        if uploaded_files:
            lines.append(f"Uploaded files ({len(uploaded_files)}):")
            for name in uploaded_files[:5]:
                lines.append(f"- {name}")
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
        if self._current_assignment_id:
            self._focus_assignment_by_id(int(self._current_assignment_id))

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
        self._refresh_task_views()
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
        self._refresh_task_views()
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
        if self._select_assignment_row(aid):
            self._on_assignment_clicked(aid)
            return True
        # If filters hide the target assignment, reset filters and retry once.
        if hasattr(self, "assignment_scope_filter"):
            self.assignment_scope_filter.setCurrentIndex(1)
        if hasattr(self, "assignment_status_filter"):
            self.assignment_status_filter.setCurrentText("All")
        if hasattr(self, "assignment_followup_filter"):
            self.assignment_followup_filter.setCurrentIndex(0)
        if hasattr(self, "assignment_assignee_filter"):
            self.assignment_assignee_filter.setCurrentIndex(0)
        if hasattr(self, "assignment_search_input"):
            self.assignment_search_input.clear()
        self._refresh_assignment_list()
        if self._select_assignment_row(aid):
            self._on_assignment_clicked(aid)
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
        self._render_chat_history(force_bottom=True)
        self.ask_input.clear()

    def _on_send(self):
        if self._ask_worker and self._ask_worker.isRunning():
            return
        if self._am_sweep_worker and self._am_sweep_worker.isRunning():
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
        self._refresh_chat_list()
        self._render_chat_history(force_bottom=True)
        history = self.db.get_chat_history(session_id, limit=50)
        self._ask_worker = CosAskWorker(self.db, msg, history, chat_id=self._current_chat_id)
        self._ask_worker.finished_signal.connect(self._on_ask_finished)
        self._ask_worker.error_signal.connect(self._on_ask_error)
        self.ask_btn.setEnabled(False)
        self.ask_progress.setVisible(True)
        self.ask_input.clear()
        self._ask_worker.start()

    def _on_am_sweep(self):
        """Run AM Sweep if not already run today; otherwise focus today's sweep chat."""
        if self._ask_worker and self._ask_worker.isRunning():
            return
        if self._am_sweep_worker and self._am_sweep_worker.isRunning():
            return

        today = datetime.now().strftime("%Y-%m-%d")
        title = f"AM Sweep {today}"
        existing_id = None
        try:
            if hasattr(self.db, "cos_find_chat_by_title"):
                existing_id = self.db.cos_find_chat_by_title(title)
        except Exception:
            existing_id = None

        # Ensure we have a deterministic per-day chat for persistence across restart.
        if existing_id is not None:
            self._current_chat_id = int(existing_id)
        elif self._current_chat_id is None:
            self._current_chat_id = self.db.cos_create_chat(title=title)

        # Focus the chosen chat in the UI.
        try:
            self._refresh_chat_list()
        except Exception:
            pass
        self._render_chat_history(force_bottom=True)

        # If this chat already contains an AM Sweep run (AM Sweep -> assistant output), do not re-run.
        session_id = f"cos_{self._current_chat_id}"
        history_all = self.db.get_chat_history(session_id, limit=200)
        last_trigger_idx = -1
        for i, (role, content) in enumerate(history_all):
            if str(role or "").strip().lower() == "user" and str(content or "").strip() == "AM Sweep":
                last_trigger_idx = i
        already_has_output = False
        if last_trigger_idx >= 0:
            for role, _content in history_all[last_trigger_idx + 1 :]:
                if str(role or "").strip().lower() == "assistant":
                    already_has_output = True
                    break
        if already_has_output:
            # Just focus existing output; user can choose "Run again" if they want a refresh.
            return

        # Persist the sweep trigger as a user message for auditability and run it.
        self.db.save_message(session_id, "user", "AM Sweep")
        history = self.db.get_chat_history(session_id, limit=50)

        self._am_sweep_worker = CosAmSweepWorker(self.db, history, chat_id=self._current_chat_id)
        self._am_sweep_worker.finished_signal.connect(self._on_ask_finished)
        self._am_sweep_worker.error_signal.connect(self._on_ask_error)

        self.ask_btn.setEnabled(False)
        self.ask_progress.setVisible(True)
        self.ask_input.clear()
        self._am_sweep_worker.start()

    def _on_am_sweep_rerun(self):
        """Always run AM Sweep (creates/uses today's sweep chat)."""
        if self._ask_worker and self._ask_worker.isRunning():
            return
        if self._am_sweep_worker and self._am_sweep_worker.isRunning():
            return

        today = datetime.now().strftime("%Y-%m-%d")
        title = f"AM Sweep {today}"
        existing_id = None
        try:
            if hasattr(self.db, "cos_find_chat_by_title"):
                existing_id = self.db.cos_find_chat_by_title(title)
        except Exception:
            existing_id = None

        if existing_id is not None:
            self._current_chat_id = int(existing_id)
        elif self._current_chat_id is None:
            self._current_chat_id = self.db.cos_create_chat(title=title)

        session_id = f"cos_{self._current_chat_id}"
        self.db.save_message(session_id, "user", "AM Sweep")
        history = self.db.get_chat_history(session_id, limit=50)

        self._am_sweep_worker = CosAmSweepWorker(self.db, history, chat_id=self._current_chat_id)
        self._am_sweep_worker.finished_signal.connect(self._on_ask_finished)
        self._am_sweep_worker.error_signal.connect(self._on_ask_error)

        self.ask_btn.setEnabled(False)
        self.ask_progress.setVisible(True)
        self.ask_input.clear()
        self._am_sweep_worker.start()

    def _on_ask_finished(self, result: str):
        self._ask_worker = None
        self._am_sweep_worker = None
        self.ask_btn.setEnabled(True)
        self.ask_progress.setVisible(False)
        if self._current_chat_id is not None:
            session_id = f"cos_{self._current_chat_id}"
            self.db.save_message(session_id, "assistant", result)
            self.db.cos_update_chat(self._current_chat_id)
        self._refresh_chat_list()
        self._refresh_assignment_list()
        self._render_chat_history(preserve_scroll=True)
        self._refresh_task_views()
        notify_chat_response(self, "Navi")

    def _on_ask_error(self, err: str):
        self._ask_worker = None
        self._am_sweep_worker = None
        self.ask_btn.setEnabled(True)
        self.ask_progress.setVisible(False)
        scroll_state = self._capture_chat_scroll_state()
        self.chat_display.append(f"<p style='color: #e07a7a;'>Error: {err}</p>")
        self._restore_chat_scroll_state(scroll_state)

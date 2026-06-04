"""
Chief of Staff tab: chat on the left (≥70%), sidebar on the right with chat list by project.
All chats save automatically. Layout like Grok/ChatGPT but sidebar on the right.
"""

import html
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
    QDoubleSpinBox, QTimeEdit, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QPlainTextEdit, QGroupBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl, QDate, QTimer
from PyQt6.QtGui import QAction, QKeyEvent, QColor, QBrush, QFont


class ChatEntryEdit(QTextEdit):
    """QTextEdit that sends on Enter, newline on Shift+Enter."""
    returnPressed = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent):
        # keyPressEvent for Pulse private memory + Shield CoS input handling
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.returnPressed.emit()
                event.accept()
        else:
            super().keyPressEvent(event)

from core.db import DatabaseManager
from core.chief_of_staff_service import (
    ChiefOfStaffService,
    cos_response,
    cos_am_sweep,
    propose_work_plan,
    approve_and_delegate_work_plan,
    get_work_plan_checkpoint_report,
)
from core.intel import IntelService, IntelFinding
from core.file_handler import get_relevant_past_documents  # Phase 1 retrieval (now baseline) — Relevant Past Docs in CoS sidebar + raw_context bias support
from core.grok_client import is_user_facing_llm_failure_message
from core.agent_memory import promote_agent_memory_to_global, promote_assignment_memory_to_agent
from core.user_memory import auto_store_user_memory, default_user_memory_llm, store_teach_memory
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


def _normalize_proposal_due_for_db(value: str) -> tuple[bool, Optional[str]]:
    """Accept YYYY-MM-DD, MM-DD-YYYY, or none; return canonical YYYY-MM-DD or None for DB."""
    raw = (value or "").strip()
    if not raw or raw.lower() in {"none", "null", "n/a"}:
        return True, None
    ok, d = _normalize_iso_due_date_input(raw)
    if ok and d:
        return True, d
    ok_mm, mm = _normalize_mmddyyyy_due_date_input(raw)
    if ok_mm and mm:
        try:
            dt = datetime.strptime(mm, "%m-%d-%Y")
        except Exception:
            return False, None
        return True, dt.strftime("%Y-%m-%d")
    return False, None


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
            teach_response = store_teach_memory(self.db, self.user_message)
            if teach_response:
                self.finished_signal.emit(teach_response)
                return
            result = cos_response(self.db, self.user_message, self.conversation_history, chat_id=self.chat_id)
            if is_user_facing_llm_failure_message(result):
                self.error_signal.emit(result)
                return
            session_id = f"cos_{int(self.chat_id)}" if self.chat_id is not None else None
            auto_store_user_memory(
                self.db,
                user_message=self.user_message,
                assistant_message=result,
                llm_callable=default_user_memory_llm,
                session_id=session_id,
                chat_id=self.chat_id,
                route="chief_of_staff_tab",
            )
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
            if is_user_facing_llm_failure_message(result):
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

        # Energy & Working Style (Phase 7)
        layout.addWidget(QLabel("Energy & Working Style:"))
        energy_form = QFormLayout()
        self.energy_peak_edit = QLineEdit()
        self.energy_peak_edit.setPlaceholderText("e.g. 8-11, 14-16")
        energy_form.addRow("Peak focus hours:", self.energy_peak_edit)
        self.energy_low_edit = QLineEdit()
        self.energy_low_edit.setPlaceholderText("e.g. 13-14, after 17")
        energy_form.addRow("Low energy windows:", self.energy_low_edit)
        layout.addLayout(energy_form)

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
        # _blocked_time_row for Pulse private memory + Shield CoS blocked time
        row_item = item or self.prefs_blocked_list.currentItem()
        if row_item is None:
            return None
        row = row_item.data(Qt.ItemDataRole.UserRole)
        return dict(row) if isinstance(row, dict) else None

    def _set_blocked_time_item(self, entry: dict, *, item: Optional[QListWidgetItem] = None):
        # _set_blocked_time_item for Pulse private memory + Shield CoS blocked time
        normalized = _normalize_blocked_time_entry(entry)
        if not normalized:
            return
        target = item or QListWidgetItem()
        target.setData(Qt.ItemDataRole.UserRole, normalized)
        target.setText(_blocked_time_entry_label(normalized))
        if item is None:
            self.prefs_blocked_list.addItem(target)

    def _refresh_legacy_notice(self):
        # CoS legacy notice for Pulse private memory + Shield context preservation
        notes: list[str] = []
        if self._extra_blocked_entries:
            notes.append(f"{len(self._extra_blocked_entries)} legacy blocked-time entr{'y' if len(self._extra_blocked_entries) == 1 else 'ies'} will be preserved.")
        if self._extra_behavior_prefs:
            notes.append(f"{len(self._extra_behavior_prefs)} unrecognized behavior preference entr{'y' if len(self._extra_behavior_prefs) == 1 else 'ies'} will be preserved.")
        self.legacy_notice.setVisible(bool(notes))
        self.legacy_notice.setText(" ".join(notes))

    def _add_blocked_time(self):
        # _add_blocked_time for Pulse private memory + Shield CoS prefs
        dialog = self.BlockedTimeDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._set_blocked_time_item(dialog.values())
        self.prefs_blocked_list.setCurrentRow(self.prefs_blocked_list.count() - 1)

    def _edit_blocked_time(self):
        # _edit_blocked_time for Pulse private memory + Shield CoS prefs
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
        # _delete_blocked_time for Pulse private memory + Shield CoS prefs
        current_row = self.prefs_blocked_list.currentRow()
        if current_row < 0:
            QMessageBox.information(self, "Preferences", "Select a blocked time first.")
            return
        self.prefs_blocked_list.takeItem(current_row)

    def _load(self):
        # _load for Pulse private memory + Shield CoS prefs loading
        row = self.db.cos_get_preferences()
        if not row:
            return
        operating_system_md, blocked_times_json, deep_work_hours, behavior_prefs_json, energy_profile_json, _ = row
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
        try:
            energy = json.loads(energy_profile_json or "{}")
            if not isinstance(energy, dict):
                energy = {}
        except Exception:
            energy = {}
        self.energy_peak_edit.setText(str(energy.get("peak_hours") or energy.get("peak") or "").strip())
        self.energy_low_edit.setText(str(energy.get("low_energy_windows") or energy.get("low_energy") or "").strip())
        self._refresh_legacy_notice()

    def _save(self):
        # _save for Pulse private memory + Shield CoS prefs saving
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
        energy_profile_json = json.dumps(
            {
                "peak_hours": (self.energy_peak_edit.text() or "").strip(),
                "low_energy_windows": (self.energy_low_edit.text() or "").strip(),
            },
            ensure_ascii=False,
        )
        self.db.cos_set_preferences(
            operating_system_md=os_md,
            blocked_times_json=blocked,
            deep_work_hours=self.prefs_deep_work_spin.value(),
            behavior_prefs_json=json.dumps(behavior),
            energy_profile_json=energy_profile_json,
        )
        QMessageBox.information(self, "Preferences", "Saved.")
        self.accept()


class GlobalMemoryDialog(QDialog):
    """Inspect and prune global or agent durable memory entries."""


    class EditDialog(QDialog):
        def __init__(
            self,
            *,
            parent=None,
            row: Optional[tuple] = None,
            scope: str = "global",
            agent_code: Optional[str] = None,
            agents: Optional[list[dict]] = None,
        ):
            super().__init__(parent)
            self._memory_id = int(row[0]) if row else None
            self._scope = str(scope or "global").strip().lower() or "global"
            self._agents = list(agents or [])
            self.setWindowTitle("Edit Memory" if row else "Add Memory")
            layout = QVBoxLayout(self)
            form = QFormLayout()

            self.scope_combo = QComboBox()
            self.scope_combo.addItem("Global", "global")
            self.scope_combo.addItem("Agent", "agent")
            self.scope_combo.addItem("Assignment", "assignment")
            self.scope_combo.setCurrentIndex(max(0, self.scope_combo.findData(self._scope)))
            form.addRow("Scope:", self.scope_combo)

            self.agent_combo = QComboBox()
            self.agent_combo.addItem("Select agent", "")
            for agent in self._agents:
                code = str(agent.get("code") or "").strip().lower()
                label = str(agent.get("display_name") or code).strip() or code
                if code:
                    self.agent_combo.addItem(label, code)
            if agent_code:
                idx = self.agent_combo.findData(str(agent_code).strip().lower())
                if idx >= 0:
                    self.agent_combo.setCurrentIndex(idx)
            form.addRow("Agent:", self.agent_combo)

            self.assignment_edit = QLineEdit()
            self.assignment_edit.setPlaceholderText("A-0007 or 7")
            form.addRow("Assignment:", self.assignment_edit)

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

            def _sync_scope_fields():
                scope = (self.scope_combo.currentData() or "global")
                is_agent = scope == "agent"
                is_assignment = scope == "assignment"
                self.agent_combo.setEnabled(is_agent)
                self.assignment_edit.setEnabled(is_assignment)

            self.scope_combo.currentIndexChanged.connect(_sync_scope_fields)

            if row:
                if self._scope == "agent":
                    _mem_id, row_agent_code, kind, content, source, confidence, approval_status, json_data, _created_at, _updated_at = row
                    idx = self.agent_combo.findData(str(row_agent_code or "").strip().lower())
                    if idx >= 0:
                        self.agent_combo.setCurrentIndex(idx)
                elif self._scope == "assignment":
                    _mem_id, row_assignment_id, _row_thread_id, row_agent_code, kind, content, source, json_data, _created_at = row
                    if row_assignment_id is not None:
                        self.assignment_edit.setText(f"A-{int(row_assignment_id):04d}")
                    idx = self.agent_combo.findData(str(row_agent_code or "").strip().lower())
                    if idx >= 0:
                        self.agent_combo.setCurrentIndex(idx)
                else:
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
            _sync_scope_fields()

        def _on_save(self):
            content = (self.content_edit.toPlainText() or "").strip()
            if not content:
                QMessageBox.warning(self, "Memory", "Content is required.")
                return
            if (self.scope_combo.currentData() or "global") == "agent" and not (self.agent_combo.currentData() or "").strip():
                QMessageBox.warning(self, "Memory", "Select an agent for agent memory.")
                return
            if (self.scope_combo.currentData() or "global") == "assignment":
                assignment_raw = (self.assignment_edit.text() or "").strip()
                if assignment_raw:
                    assignment_value = assignment_raw.upper()
                    if assignment_value.startswith("A-"):
                        assignment_value = assignment_value[2:]
                    if not assignment_value.isdigit():
                        QMessageBox.warning(self, "Memory", "Assignment must be entered as A-0007 or 7.")
                        return
            json_text = (self.json_edit.toPlainText() or "").strip()
            if json_text:
                try:
                    json.loads(json_text)
                except json.JSONDecodeError:
                    QMessageBox.warning(self, "Memory", "JSON data must be valid JSON.")
                    return
            self.accept()

        def values(self) -> dict:
            json_text = (self.json_edit.toPlainText() or "").strip()
            return {
                "id": self._memory_id,
                "scope": (self.scope_combo.currentData() or "global").strip(),
                "agent_code": (self.agent_combo.currentData() or "").strip().lower() or None,
                "assignment_id": (self.assignment_edit.text() or "").strip() or None,
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
        try:
            self._agents = self.db.agents_list_active()
        except Exception:
            self._agents = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Inspect what Navi or a named agent has stored durably. You can search, filter, add, edit, refresh, and delete entries."))

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
        self.kind_filter.addItem("Note", "note")
        self.kind_filter.currentIndexChanged.connect(self._reload)
        controls.addWidget(self.kind_filter)
        controls.addWidget(QLabel("Scope:"))
        self.scope_filter = QComboBox()
        self.scope_filter.addItem("Global", "global")
        self.scope_filter.addItem("Agent", "agent")
        self.scope_filter.addItem("Assignment", "assignment")
        self.scope_filter.currentIndexChanged.connect(self._reload)
        controls.addWidget(self.scope_filter)
        controls.addWidget(QLabel("Agent:"))
        self.agent_filter = QComboBox()
        self.agent_filter.addItem("All agents", "")
        for agent in self._agents:
            code = str(agent.get("code") or "").strip().lower()
            label = str(agent.get("display_name") or code).strip() or code
            if code:
                self.agent_filter.addItem(label, code)
        self.agent_filter.currentIndexChanged.connect(self._reload)
        controls.addWidget(self.agent_filter)
        controls.addWidget(QLabel("Assignment:"))
        self.assignment_filter = QLineEdit()
        self.assignment_filter.setPlaceholderText("A-0007 or 7")
        self.assignment_filter.returnPressed.connect(self._reload)
        controls.addWidget(self.assignment_filter)
        controls.addWidget(QLabel("Source:"))
        self.source_filter = QComboBox()
        self.source_filter.addItem("All", "")
        self.source_filter.addItem("Auto chat", "auto_chat")
        self.source_filter.addItem("Teach Navi", "teach_navi")
        self.source_filter.addItem("Teach Agent", "teach_agent")
        self.source_filter.addItem("Agent chat", "agent_chat")
        self.source_filter.addItem("Manual", "manual")
        self.source_filter.currentIndexChanged.connect(self._reload)
        controls.addWidget(self.source_filter)
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
        self.memory_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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
        self.promote_btn = QPushButton("Promote to Navi")
        self.promote_btn.clicked.connect(self._promote_selected_to_global)
        buttons.addButton(self.promote_btn, QDialogButtonBox.ButtonRole.ActionRole)
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

    @staticmethod
    def _record_scope(record) -> str:
        return str((record or {}).get("scope") or "global").strip().lower() or "global"

    @staticmethod
    def _record_row(record):
        return (record or {}).get("row")

    @classmethod
    def _alias_payload(cls, record) -> Optional[dict]:
        row = cls._record_row(record)
        scope = cls._record_scope(record)
        json_idx = 7 if scope == "agent" else 6
        payload = cls._json_payload(row[json_idx] if row and len(row) > json_idx else None)
        alias_payload = payload.get("alias") if isinstance(payload, dict) else None
        if isinstance(alias_payload, dict):
            term = str(alias_payload.get("term") or "").strip()
            canonical = str(alias_payload.get("canonical") or "").strip()
            if term and canonical:
                synonyms = alias_payload.get("synonyms") or []
                if not isinstance(synonyms, list):
                    synonyms = []
                scope = alias_payload.get("scope") or {}
                if not isinstance(scope, dict):
                    scope = {}
                return {
                    "term": term,
                    "canonical": canonical,
                    "synonyms": [str(item).strip() for item in synonyms if str(item).strip()],
                    "scope": {str(k).strip(): str(v).strip() for k, v in scope.items() if str(k).strip() and str(v).strip()},
                }
        return None

    @staticmethod
    def _escape_html(text: object) -> str:
        return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @classmethod
    def _provenance_html(cls, record) -> str:
        row = cls._record_row(record)
        scope = cls._record_scope(record)
        json_idx = 7 if scope == "agent" else 6
        payload = cls._json_payload(row[json_idx] if row and len(row) > json_idx else None)
        if not payload:
            return ""
        provenance_bits: list[str] = []
        for label, key in (
            ("Session", "source_session_id"),
            ("Chat id", "chat_id"),
            ("Route", "route"),
            ("Extractor", "extraction_version"),
        ):
            value = payload.get(key)
            if value in (None, ""):
                continue
            provenance_bits.append(f"<b>{label}:</b> {cls._escape_html(value)}")
        previews: list[str] = []
        for label, key in (
            ("User preview", "user_message_preview"),
            ("Assistant preview", "assistant_message_preview"),
        ):
            value = str(payload.get(key) or "").strip()
            if not value:
                continue
            previews.append(f"<b>{label}:</b><br><pre>{cls._escape_html(value)}</pre>")
        if not provenance_bits and not previews:
            return ""
        html = "<p><b>Passive memory provenance</b><br>" + "<br>".join(provenance_bits) + "</p>"
        if previews:
            html += "".join(f"<p>{block}</p>" for block in previews)
        return html

    def _row_label(self, record) -> str:
        row = self._record_row(record)
        scope = self._record_scope(record)
        if scope == "agent":
            _mem_id, agent_code, kind, content, source, confidence, approval_status, _json_data, created_at, _updated_at = row
            owner = str(agent_code or "").strip().lower()
        elif scope == "assignment":
            _mem_id, assignment_id, thread_id, agent_code, kind, content, source, _json_data, created_at = row
            owner_bits = []
            if assignment_id is not None:
                owner_bits.append(f"A-{int(assignment_id):04d}")
            if thread_id is not None:
                owner_bits.append(f"thread {int(thread_id)}")
            if str(agent_code or "").strip():
                owner_bits.append(str(agent_code or "").strip().lower())
            owner = "/".join(owner_bits) or "assignment"
        else:
            _mem_id, kind, content, source, confidence, approval_status, _json_data, created_at, _updated_at = row
            owner = "navi"
        alias_payload = self._alias_payload(record) if str(kind or "").strip() == "alias" else None
        if alias_payload:
            text = f"{alias_payload['term']} -> {alias_payload['canonical']}"
        else:
            text = (str(content or "").strip() or "(empty)").replace("\n", " ")
        if len(text) > 88:
            text = text[:85] + "..."
        kind_s = str(kind or "note").strip() or "note"
        source_s = str(source or "unknown").strip() or "unknown"
        status_s = str(approval_status or "approved").strip() or "approved"
        return f"[{owner}/{status_s}/{kind_s}] {text} ({source_s}, {float(confidence or 0):.2f})"

    def _reload(self):
        query = (self.search_edit.text() or "").strip()
        kind = (self.kind_filter.currentData() or "").strip() or None
        source = (self.source_filter.currentData() or "").strip() or None
        approval_status = (self.status_filter.currentData() or "").strip() or None
        scope = (self.scope_filter.currentData() or "global").strip() or "global"
        agent_code = (self.agent_filter.currentData() or "").strip().lower() or None
        assignment_raw = (self.assignment_filter.text() or "").strip()
        assignment_id = None
        if assignment_raw:
            assignment_token = assignment_raw.upper()
            if assignment_token.startswith("A-"):
                assignment_token = assignment_token[2:]
            if assignment_token.isdigit():
                assignment_id = int(assignment_token)
        self.agent_filter.setEnabled(scope in {"agent", "assignment"})
        self.assignment_filter.setEnabled(scope == "assignment")
        try:
            records = []
            if scope == "agent":
                agent_codes = [agent_code] if agent_code else [str(a.get("code") or "").strip().lower() for a in self._agents if str(a.get("code") or "").strip()]
                for code in agent_codes:
                    if query:
                        rows = self.db.agent_memory_search(
                            agent_code=code,
                            query=query,
                            kind=kind,
                            source=source,
                            approval_status=approval_status,
                            limit=100,
                        )
                    else:
                        rows = self.db.agent_memory_recent(
                            agent_code=code,
                            kind=kind,
                            source=source,
                            approval_status=approval_status,
                            limit=100,
                        )
                    records.extend({"scope": "agent", "row": row} for row in rows)
            elif scope == "assignment":
                if query:
                    rows = self.db.assignment_memory_search(
                        query=query,
                        assignment_id=assignment_id,
                        agent_code=agent_code,
                        limit=200,
                    )
                else:
                    rows = self.db.assignment_memory_recent(
                        assignment_id=assignment_id,
                        agent_code=agent_code,
                        limit=200,
                    )
                records = [{"scope": "assignment", "row": row} for row in rows]
            else:
                if query:
                    rows = self.db.user_memory_search(
                        query=query,
                        kind=kind,
                        source=source,
                        approval_status=approval_status,
                        limit=200,
                    )
                else:
                    rows = self.db.user_memory_recent(kind=kind, source=source, approval_status=approval_status, limit=200)
                records = [{"scope": "global", "row": row} for row in rows]
        except Exception as e:
            QMessageBox.warning(self, "Memory", f"Could not load memory entries.\n\n{e}")
            return
        self.memory_list.clear()
        for record in records:
            item = QListWidgetItem(self._row_label(record))
            item.setData(Qt.ItemDataRole.UserRole, record)
            self.memory_list.addItem(item)
        if self.memory_list.count() > 0:
            self.memory_list.setCurrentRow(0)
        else:
            self.detail_browser.setHtml("<p style='color: #9aa0a6;'>(No matching memory entries.)</p>")
        self.add_btn.setEnabled(scope != "assignment")
        self.edit_btn.setEnabled(scope != "assignment")
        self.approve_btn.setEnabled(scope != "assignment")
        self.reject_btn.setEnabled(scope != "assignment")
        if scope == "assignment":
            self.promote_btn.setText("Promote to Agent")
        else:
            self.promote_btn.setText("Promote to Navi")
        self.promote_btn.setEnabled(scope in {"agent", "assignment"} and self.memory_list.count() > 0)

    def _update_detail(self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem] = None):
        if current is None:
            self.detail_browser.setHtml("<p style='color: #9aa0a6;'>(No selection)</p>")
            return
        record = current.data(Qt.ItemDataRole.UserRole)
        if not record:
            self.detail_browser.setHtml("<p style='color: #9aa0a6;'>(No selection)</p>")
            return
        row = self._record_row(record)
        scope = self._record_scope(record)
        if scope == "agent":
            mem_id, agent_code, kind, content, source, confidence, approval_status, json_data, created_at, updated_at = row
            owner_html = f"<b>Agent:</b> {self._escape_html(agent_code)}<br>"
        elif scope == "assignment":
            mem_id, assignment_id, thread_id, agent_code, kind, content, source, json_data, created_at = row
            owner_html = ""
            if assignment_id is not None:
                owner_html += f"<b>Assignment:</b> A-{int(assignment_id):04d}<br>"
            if thread_id is not None:
                owner_html += f"<b>Thread:</b> {int(thread_id)}<br>"
            if str(agent_code or "").strip():
                owner_html += f"<b>Agent:</b> {self._escape_html(agent_code)}<br>"
            confidence = 1.0
            approval_status = "task-local"
            updated_at = created_at
        else:
            mem_id, kind, content, source, confidence, approval_status, json_data, created_at, updated_at = row
            owner_html = ""
        alias_payload = self._alias_payload(record) if str(kind or "").strip() == "alias" else None
        json_html = ""
        if json_data:
            json_html = (
                "<p><b>JSON data</b></p><pre>"
                + self._escape_html(json_data)
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
            scope = alias_payload.get("scope") or {}
            if isinstance(scope, dict) and scope:
                alias_html += (
                    "<br><b>Scope:</b> "
                    + ", ".join(
                        f"{self._escape_html(k)}={self._escape_html(v)}"
                        for k, v in scope.items()
                    )
                )
            alias_html += "</p>"
        html = (
            f"<p><b>ID:</b> {mem_id}<br>"
            f"{owner_html}"
            f"<b>Kind:</b> {kind}<br>"
            f"<b>Source:</b> {source}<br>"
            f"<b>Confidence:</b> {float(confidence or 0):.2f}<br>"
            f"<b>Status:</b> {approval_status}<br>"
            f"<b>Created:</b> {created_at}<br>"
            f"<b>Updated:</b> {updated_at}</p>"
            f"{alias_html}"
            f"{self._provenance_html(record)}"
            f"<p><b>Content</b></p><pre>{self._escape_html(content)}</pre>"
            f"{json_html}"
        )
        self.detail_browser.setHtml(html)

    def _selected_rows(self) -> list[dict]:
        rows: list[dict] = []
        for item in self.memory_list.selectedItems():
            row = item.data(Qt.ItemDataRole.UserRole)
            if row:
                rows.append(row)
        if rows:
            return rows
        item = self.memory_list.currentItem()
        if item is None:
            return []
        row = item.data(Qt.ItemDataRole.UserRole)
        return [row] if row else []

    def _selected_row(self) -> Optional[dict]:
        rows = self._selected_rows()
        return rows[0] if rows else None

    def _add_memory(self):
        d = self.EditDialog(
            parent=self,
            scope=(self.scope_filter.currentData() or "global"),
            agent_code=(self.agent_filter.currentData() or "").strip() or None,
            agents=self._agents,
        )
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        values = d.values()
        if values["scope"] == "agent":
            self.db.agent_memory_add(
                agent_code=values["agent_code"] or "",
                kind=values["kind"],
                content=values["content"],
                source=values["source"],
                confidence=values["confidence"],
                approval_status=values["approval_status"],
                json_data=values["json_data"],
            )
        else:
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
        record = self._selected_row()
        if not record:
            QMessageBox.information(self, "Memory", "Select a memory entry first.")
            return
        row = self._record_row(record)
        scope = self._record_scope(record)
        agent_code = str(row[1] or "").strip().lower() if scope == "agent" else None
        d = self.EditDialog(parent=self, row=row, scope=scope, agent_code=agent_code, agents=self._agents)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        values = d.values()
        if values["scope"] == "agent":
            ok = self.db.agent_memory_update(
                int(values["id"]),
                kind=values["kind"],
                content=values["content"],
                source=values["source"],
                confidence=values["confidence"],
                approval_status=values["approval_status"],
                json_data=values["json_data"],
            )
        else:
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
            QMessageBox.warning(self, "Memory", "That memory entry could not be updated.")
            return
        self._reload()

    def _set_selected_status(self, approval_status: str):
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "Memory", "Select one or more memory entries first.")
            return
        failures = 0
        for record in rows:
            row = self._record_row(record)
            scope = self._record_scope(record)
            ok = (
                self.db.agent_memory_set_approval_status(int(row[0]), approval_status)
                if scope == "agent"
                else self.db.user_memory_set_approval_status(int(row[0]), approval_status)
            )
            if not ok:
                failures += 1
        self._reload()
        if failures:
            QMessageBox.warning(
                self,
                "Memory",
                f"{failures} selected entr{'y' if failures == 1 else 'ies'} could not be updated.",
            )

    def _promote_selected_to_global(self):
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "Memory", "Select one or more memory entries first.")
            return
        created = 0
        reused = 0
        failed = 0
        scope = self._record_scope(rows[0])
        if scope == "agent":
            selected_rows = [record for record in rows if self._record_scope(record) == "agent"]
            if not selected_rows:
                QMessageBox.information(self, "Memory", "Promotion only applies to agent memory entries.")
                return
            for record in selected_rows:
                row = self._record_row(record)
                try:
                    _new_id, was_created = promote_agent_memory_to_global(self.db, memory_id=int(row[0]))
                    if was_created:
                        created += 1
                    else:
                        reused += 1
                except Exception:
                    failed += 1
        elif scope == "assignment":
            selected_rows = [record for record in rows if self._record_scope(record) == "assignment"]
            if not selected_rows:
                QMessageBox.information(self, "Memory", "Promotion only applies to assignment memory entries.")
                return
            for record in selected_rows:
                row = self._record_row(record)
                try:
                    _new_id, was_created = promote_assignment_memory_to_agent(self.db, memory_id=int(row[0]))
                    if was_created:
                        created += 1
                    else:
                        reused += 1
                except Exception:
                    failed += 1
        else:
            QMessageBox.information(self, "Memory", "Promotion is only available for agent or assignment memory entries.")
            return
        self._reload()
        if failed:
            QMessageBox.warning(
                self,
                "Memory",
                f"Promoted {created}, reused {reused}, failed {failed}.",
            )
        else:
            QMessageBox.information(
                self,
                "Memory",
                (
                    f"Promoted {created} entr{'y' if created == 1 else 'ies'} to Navi global memory; reused {reused} existing match{'es' if reused != 1 else ''}."
                    if scope == "agent"
                    else f"Promoted {created} entr{'y' if created == 1 else 'ies'} to durable agent memory; reused {reused} existing match{'es' if reused != 1 else ''}."
                ),
            )

    def _delete_selected(self):
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "Memory", "Select one or more memory entries first.")
            return
        record = rows[0]
        row = self._record_row(record)
        mem_id = int(row[0])
        scope = self._record_scope(record)
        if scope == "agent":
            kind = str(row[2] or "note")
            content = str(row[3] or "").strip()
        else:
            kind = str(row[1] or "note")
            content = str(row[2] or "").strip()
        preview = content if len(content) <= 120 else content[:117] + "..."
        message = f"Delete this {kind} memory?\n\n{preview}"
        if len(rows) > 1:
            message = f"Delete {len(rows)} selected memory entries?\n\nFirst entry preview:\n{preview}"
        reply = QMessageBox.question(
            self,
            "Delete Memory",
            message,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        failures = 0
        for selected in rows:
            row = self._record_row(selected)
            scope = self._record_scope(selected)
            ok = (
                self.db.agent_memory_delete(int(row[0]))
                if scope == "agent"
                else self.db.assignment_memory_delete(int(row[0]))
                if scope == "assignment"
                else self.db.user_memory_delete(int(row[0]))
            )
            if not ok:
                failures += 1
        self._reload()
        if failures:
            QMessageBox.warning(
                self,
                "Memory",
                f"{failures} selected entr{'y' if failures == 1 else 'ies'} could not be deleted.",
            )


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
    """Create a delegation assignment from the CoS board (or from Clients dossier)."""

    def __init__(self, db: DatabaseManager, parent=None, *, client_id: int | None = None, client_name: str | None = None):
        super().__init__(parent)
        self.db = db
        self._client_id = client_id
        self._client_name = client_name
        title = "New Assignment"
        if client_name:
            title = f"New Assignment for {client_name}"
        self.setWindowTitle(title)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Optional client context (read-only when coming from Clients tab)
        if client_name:
            client_label = QLabel(f"<b>{client_name}</b> (Client #{client_id})")
            client_label.setStyleSheet("color: #6b8cae; padding: 4px 0;")
            form.addRow("Client:", client_label)
            # Tiny Pulse awareness + View in assignment dialog (high-frequency client workflow from Clients tab)
            try:
                from core.intel import IntelService
                isvc = IntelService(self.db)
                w_list = [w for w in (isvc.list_watch_topics() or []) if getattr(w, 'client_id', None) == client_id]
                recent = isvc.list_findings(client_id=client_id, raised_only=True, limit=1)
                txt = ""
                if w_list: txt = f"👤 {len(w_list)} watches"
                if recent: txt += ("; " if txt else "") + f"recent: {getattr(recent[0],'title','')[:20]}"
                suggestion = getattr(recent[0], 'title', '')[:60] if recent else ""
                if txt:
                    pnote = QLabel("📡 " + txt)
                    pnote.setStyleSheet("font-size: 9px; color: #7aa0d6;")
                    form.addRow("", pnote)
                    vbtn = QPushButton("View")
                    vbtn.setStyleSheet("font-size: 8px; padding: 1px 3px;")
                    vbtn.clicked.connect(lambda: self._on_view_pulse_for_assignment(client_id, pnote, suggestion))
                    form.addRow("", vbtn)
            except Exception:
                pass

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
        # Tiny Pulse placeholder hint in assignment dialog for client context (new surface awareness)
        if getattr(self, '_client_id', None):
            try:
                from core.intel import IntelService
                isvc = IntelService(self.db)
                w_list = [w for w in (isvc.list_watch_topics() or []) if getattr(w, 'client_id', None) == self._client_id]
                recent = isvc.list_findings(client_id=self._client_id, raised_only=True, limit=1)
                sug = getattr(recent[0], 'title', '')[:40] if recent else ""
                if w_list or sug:
                    ph = self.brief_edit.placeholderText()
                    self.brief_edit.setPlaceholderText(ph + (f"  📡 Pulse: {sug or f'{len(w_list)} watches'} | 🛡️ sec-rel triage in Shield" if sug or w_list else ""))
            except Exception:
                pass

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
        vals = {
            "title": (self.title_edit.text() or "").strip(),
            "brief_md": (self.brief_edit.toPlainText() or "").strip(),
            "assignee_code": (self.assignee_combo.currentData() or "").strip().lower(),
            "priority": int(self.priority_spin.value()),
            "due_date": due,
        }
        if self._client_id is not None:
            vals["client_id"] = int(self._client_id)
            vals["client_name"] = self._client_name
        return vals

    def _on_view_pulse_for_assignment(self, client_id, pnote_label, suggestion):
        """Tiny: after View, confirm + inject suggested line from recent raised intel into the brief (makes confirmation useful for assignment creation). Security-relevant suggestions include Shield triage note."""
        try:
            if hasattr(self.parent(), 'focus_intel_tab'):
                self.parent().focus_intel_tab(client_id=client_id)
            if pnote_label and "✓ viewed" not in pnote_label.text():
                pnote_label.setText(pnote_label.text() + " ✓ viewed")
            if suggestion and hasattr(self, 'brief_edit'):
                current = self.brief_edit.toPlainText() or ""
                if suggestion not in current:
                    sec_note = " (🛡️ triage in Shield tab)" if "[Security-Relevant]" in suggestion else ""
                    self.brief_edit.setPlainText(current + f"\n\nSuggested from recent Pulse: {suggestion}{sec_note}")
        except Exception:
            pass


class ChiefOfStaffTab(QWidget):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        # ChiefOfStaffTab integrates Pulse private memory + Shield surface for CoS
        self.intel = IntelService(db)
        self._ask_worker = None
        self._am_sweep_worker = None
        self._current_chat_id = None
        self._current_assignment_id = None
        self._current_proposal: dict | None = None
        self._current_workplan: dict | None = None
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
        # Initial load of raised Intel in sidebar
        self._refresh_raised_intel()
        self._last_focused_client_name = None
        self._refresh_relevant_past_docs()  # Phase 1 surface

    def _refresh_raised_intel(self):
        """Reload the compact list of raised Pulse findings in the CoS sidebar. # 🛡️ security-relevant items highlighted for Shield triage"""
        if not hasattr(self, "raised_intel_list"):
            return
        self.raised_intel_list.clear()
        # CoS tab refreshes raised Pulse for Shield sidebar visibility
        try:
            findings = self.intel.list_findings(raised_only=True, limit=12)
            # Small proactive note if no client monitoring at all (encourages use of new features)
            try:
                any_mon = False
                for c in (self.db.list_clients(active_only=True, limit=20) or []):
                    cid = c.get('id')
                    if any(getattr(w, 'client_id', None) == cid for w in (self.intel.list_watch_topics() or [])) or bool(self.intel.list_findings(client_id=cid, raised_only=True, limit=1)):
                        any_mon = True
                        break
                if not any_mon:
                    note = QListWidgetItem("(no active client watches/raised - start via Billing +Watch or Intel)")
                    note.setForeground(QColor("#9aa0a6"))
                    self.raised_intel_list.addItem(note)
            except Exception:
                pass
            # When CoS has client context (opened from Clients tab), put client-linked raised findings first (proactive integration)
            if getattr(self, '_client_id', None) is not None:
                cfind = [f for f in findings if getattr(self, '_client_id', None) in (getattr(f, 'linked_clients', None) or [])]
                ofind = [f for f in findings if getattr(self, '_client_id', None) not in (getattr(f, 'linked_clients', None) or [])]
                findings = cfind + ofind
                # Small awareness note for watches when client focused in CoS
                try:
                    w_for_c = [w for w in (self.intel.list_watch_topics() or []) if getattr(w, 'client_id', None) == getattr(self, '_client_id', None)]
                    if w_for_c:
                        note = QListWidgetItem(f"👤 {len(w_for_c)} client watches active (see Intel tab)")
                        note.setForeground(QColor("#7aa0d6"))
                        self.raised_intel_list.addItem(note)
                    # Tiny Pulse contribution badge in CoS when client focused (high-visibility surface)
                    try:
                        p_ents = [e for e in (self.db.time_entries_list(client_id=self._client_id, limit=50) or []) if "Pulse-influenced" in str(e.get("description") or "") or "from Pulse" in str(e.get("description") or "")]
                        p_c = len(p_ents)
                        if p_c > 0:
                            note = QListWidgetItem(f"💰 {p_c} Pulse time entries (see Billing for ROI)")
                            note.setForeground(QColor("#4a9eff"))
                            self.raised_intel_list.addItem(note)
                    except Exception:
                        pass
                except Exception:
                    pass
            for f in findings:
                clients = ""
                if f.linked_clients:
                    clients = f" | clients={f.linked_clients}"
                if getattr(f, 'linked_projects', None):
                    clients += f" | projs={f.linked_projects}"
                text = f"[{f.importance}] {f.title}{clients}"  # Phase 2: shows project links in CoS intel sidebar too
                if "[Security-Relevant]" in (getattr(f, 'title', '') or ""):
                    text = "🛡️ " + text
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, f.id)
                # Color high importance
                if f.importance == "high":
                    item.setForeground(QColor("#ffcc00"))
                if "[Security-Relevant]" in (getattr(f, 'title', '') or ""):
                    item.setForeground(QColor("#4fc3f7"))  # blue for security-relevant in CoS sidebar
                self.raised_intel_list.addItem(item)
            if not findings:
                self.raised_intel_list.addItem(QListWidgetItem("(no raised findings)"))
        except Exception as e:
            self.raised_intel_list.addItem(QListWidgetItem(f"(error loading: {e})"))

    def _get_selected_raised_intel_id(self) -> Optional[int]:
        item = self.raised_intel_list.currentItem() if hasattr(self, "raised_intel_list") else None
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_raised_intel_double_clicked(self, item):
        # 🛡️ security-relevant items route to Shield triage in detail view
        fid = item.data(Qt.ItemDataRole.UserRole)
        if fid:
            self._show_raised_intel_detail(fid)

    def _refresh_relevant_past_docs(self, client_name: str | None = None):
        """Populate the Relevant Past Documents list in CoS sidebar (Phase 1 retrieval core, baseline complete). # 🛡️ security-relevant for Shield/Compliance"""
        if not hasattr(self, "relevant_past_docs_list"):
            return
        self.relevant_past_docs_list.clear()
        try:
            if not client_name:
                # Try to infer from current chat or last focus (lightweight)
                client_name = getattr(self, "_last_focused_client_name", None)
            if not client_name:
                self.relevant_past_docs_list.addItem(QListWidgetItem("(no client context)"))
                return
            # Make refresh use improved reference-biased scoring from get_relevant_past_documents
            q = ""
            try:
                if hasattr(self, "ask_input"):
                    q = self.ask_input.toPlainText()[:120]
                    # Defensive: if ask_input has reference pattern, ensure it's passed for bias
                    if "[Historical reference" in q or "reference:" in q.lower():
                        q = q  # already passed, function handles central bias
            except Exception:
                pass
            docs = get_relevant_past_documents(client_hint=client_name, query=q, raw_context=(self.ask_input.toPlainText() if hasattr(self, "ask_input") else q), limit=5)
            if not docs:
                self.relevant_past_docs_list.addItem(QListWidgetItem("(no relevant past docs for client)"))
                return
            for d in docs:
                reason_parts = []
                if d.doc_type:
                    reason_parts.append(d.doc_type)
                if d.regulatory_tags:
                    reason_parts.append("reg")
                # Phase 1 ref bias surface: shows "ref" marker when query contained reference markers and name matched (centralized in get_relevant_past_documents).
                try:
                    if q and ("historical reference" in q.lower() or "reference:" in q.lower()):
                        if d.name and d.name.lower()[:20] in q.lower():
                            reason_parts.append("ref")
                except Exception:
                    pass
                # Put "ref" first for visibility if present
                if "ref" in reason_parts:
                    reason_parts = ["ref"] + [x for x in reason_parts if x != "ref"]
                text = f"{d.name[:40]} | {d.year or '?'} | {'+'.join(reason_parts)}"
                if "ref" in reason_parts:
                    text = "[ref] " + text  # (future polish: richer highlight; core Phase 1 done)
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, {
                    "name": d.name,
                    "client_hint": d.client_hint,
                    "doc_type": d.doc_type,
                    "year": d.year,
                    "source": d.source,
                    "source_id": d.source_id,
                    "source_path": d.source_path,
                    "project_hint": d.project_hint,
                    "regulatory_tags": d.regulatory_tags,
                    "ref_match": "ref" in reason_parts,  # symmetry with Workspace for bias visibility
                })
                if "ref" in reason_parts:
                    from PyQt6.QtGui import QColor
                    item.setForeground(QColor("#4fc3f7"))  # light blue for ref bias matches
                    from PyQt6.QtGui import QFont
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                # Small next micro: better tooltip for usability
                from core.file_handler import format_compact_historical_context
                item.setToolTip(format_compact_historical_context([d], max_items=1).strip())
                self.relevant_past_docs_list.addItem(item)
        except Exception as e:
            self.relevant_past_docs_list.addItem(QListWidgetItem(f"(error: {str(e)[:30]})"))

    def _on_relevant_past_doc_double_clicked(self, item):
        """Show basic details for the clicked historical document (lightweight dialog)."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
        dlg = QDialog(self)
        dlg.setWindowTitle("Relevant Past Document")
        dlg.setMinimumWidth(380)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"<b>{data.get('name', 'Unknown')}</b>"))
        lay.addWidget(QLabel(f"Client: {data.get('client_hint', 'N/A')} | Year: {data.get('year', '?')}"))
        lay.addWidget(QLabel(f"Type: {data.get('doc_type', 'N/A')} | Project: {data.get('project_hint', 'N/A')}"))
        tags = ", ".join(data.get('regulatory_tags', [])) or "—"
        lay.addWidget(QLabel(f"Regulatory: {tags}"))
        lay.addWidget(QLabel(f"Source: {data.get('source', '?')}"))

        # Phase 1 next micro: actionable "Inject reference into chat input"
        def _inject_reference():
            if hasattr(self, "ask_input"):
                ref = f"[Past: {data.get('name', '')} ({data.get('doc_type', '')}, {data.get('year', '')})]"
                current = self.ask_input.toPlainText()
                self.ask_input.setPlainText((current + " " + ref).strip())
                self.ask_input.setFocus()
            dlg.accept()

        inject_btn = QPushButton("Inject reference into next message")
        inject_btn.clicked.connect(_inject_reference)
        lay.addWidget(inject_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        lay.addWidget(close_btn)
        dlg.exec()

    def _show_relevant_past_docs_context_menu(self, pos):
        """Lightweight right-click menu on the CoS Relevant Past Documents list (consistent with tab patterns). # Security-relevant docs inform Shield/Compliance triage via Pulse context."""
        # Defensive refresh first (keeps list fresh on right-click)
        if getattr(self, "_last_focused_client_name", None):
            self._refresh_relevant_past_docs(self._last_focused_client_name)

        item = self.relevant_past_docs_list.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        # CoS relevant past docs context menu for Pulse private memory + Shield

        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction

        menu = QMenu(self)
        prefix = "[ref] " if data.get("ref_match") else ""
        inject_action = QAction(f"{prefix}Inject reference", self)
        inject_action.triggered.connect(lambda: self._inject_relevant_past_doc(data))
        menu.addAction(inject_action)

        details_action = QAction(f"{prefix}Show details", self)
        details_action.triggered.connect(lambda: self._show_relevant_past_doc_details(data))
        menu.addAction(details_action)

        copy_action = QAction(f"{prefix}Copy reference", self)
        copy_action.triggered.connect(lambda: self._copy_relevant_past_doc_reference(data))
        menu.addAction(copy_action)

        menu.exec(self.relevant_past_docs_list.viewport().mapToGlobal(pos))

    def _inject_relevant_past_doc(self, data):
        if hasattr(self, "ask_input"):
            ref = f"[Past: {data.get('name', '')} ({data.get('doc_type', '')}, {data.get('year', '')})]"
            current = self.ask_input.toPlainText()
            self.ask_input.setPlainText((current + " " + ref).strip())
            self.ask_input.setFocus()

    def _show_relevant_past_doc_details(self, data):
        # Reuse the same lightweight dialog logic
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
        dlg = QDialog(self)
        dlg.setWindowTitle("Relevant Past Document")
        dlg.setMinimumWidth(380)
        lay = QVBoxLayout(dlg)
        name = data.get('name', 'Unknown')
        if data.get("ref_match"):
            name = f"<font color='#4fc3f7'>[ref] {name}</font>"
        lay.addWidget(QLabel(f"<b>{name}</b>"))
        lay.addWidget(QLabel(f"Client: {data.get('client_hint', 'N/A')} | Year: {data.get('year', '?')}"))
        lay.addWidget(QLabel(f"Type: {data.get('doc_type', 'N/A')} | Project: {data.get('project_hint', 'N/A')}"))
        tags = ", ".join(data.get('regulatory_tags', [])) or "—"
        lay.addWidget(QLabel(f"Regulatory: {tags}"))
        lay.addWidget(QLabel(f"Source: {data.get('source', '?')}"))
        if data.get("ref_match"):
            lay.addWidget(QLabel("<b><font color='#4fc3f7'>Matched via reference bias</font></b>"))
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        lay.addWidget(close_btn)
        dlg.exec()

    def _copy_relevant_past_doc_reference(self, data):
        """Copy a compact reference using the Phase 1 formatter."""
        try:
            from core.file_handler import format_compact_historical_context
            from PyQt6.QtWidgets import QApplication
            # Reconstruct a minimal DocumentRecord-like for the formatter
            class _MiniRec:
                def __init__(self, d):
                    self.name = d.get("name", "")
                    self.doc_type = d.get("doc_type", "")
                    self.client_hint = d.get("client_hint", "")
                    self.project_hint = d.get("project_hint", "")
                    self.year = d.get("year", None)
                    self.regulatory_tags = d.get("regulatory_tags", [])
            mini = _MiniRec(data)
            text = format_compact_historical_context([mini], max_items=1).strip()
            if text:
                QApplication.clipboard().setText(text)
        except Exception:
            pass

    def _mark_selected_intel_reviewed(self):
        # 🛡️ security-relevant items remain for Shield triage even after mark reviewed
        fid = self._get_selected_raised_intel_id()
        if not fid:
            return
        self.intel.mark_raised(fid, False)
        self._refresh_raised_intel()
        # Also refresh the main Intel tab if it exists on the parent
        self._try_refresh_main_intel_tab()

    def _link_selected_intel_to_client(self):
        fid = self._get_selected_raised_intel_id()
        if not fid:
            return
        # Reuse a simple client picker (or minimal input for speed)
        try:
            # Simple approach: ask for client id (we can improve later with a real dialog)
            client_id_str, ok = QInputDialog.getText(self, "Link to Client", "Enter client ID:")
            if ok and client_id_str.strip():
                cid = int(client_id_str.strip())
                finding = self.intel.get_finding(fid)
                if finding:
                    current = set(finding.linked_clients or [])
                    current.add(cid)
                    # Phase 2: also preserve projects on this update path
                    projs = getattr(finding, 'linked_projects', None) or []
                    # We don't have a direct "set clients" — re-save via promotion path or direct update
                    # For simplicity, mark raised and note the link in a new note
                    self.intel.update_finding_notes(fid, (finding.notes or "") + f"\nLinked to client #{cid}")
                    # Best effort: also mark raised so it stays visible
                    self.intel.mark_raised(fid, True)
                    self._refresh_raised_intel()
        except Exception as e:
            QMessageBox.warning(self, "Intel", f"Could not link: {e}")

    def _open_selected_in_intel_tab(self):
        fid = self._get_selected_raised_intel_id()
        parent = self.parent()
        if parent and hasattr(parent, "intel_tab") and hasattr(parent, "tab_widget"):
            try:
                idx = parent.tab_widget.indexOf(parent.intel_tab)
                if idx >= 0:
                    parent.tab_widget.setCurrentIndex(idx)
                # The Intel tab will show the full list; user can find the item easily
            except Exception:
                pass

    def _show_raised_intel_detail(self, finding_id: int):
        finding = self.intel.get_finding(finding_id)
        if not finding:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Raised Intel #{finding_id}")
        if "[Security-Relevant]" in (finding.title or ""):
            dlg.setWindowTitle(f"Raised Intel #{finding_id} 🛡️ Security-relevant")
        dlg.resize(620, 420)
        lay = QVBoxLayout(dlg)

        info = QTextBrowser()
        info.setOpenExternalLinks(True)
        html = f"""<b>{finding.title}</b><br>
<b>Importance:</b> {finding.importance} &nbsp;&nbsp; <b>Raised:</b> {"Yes" if finding.raised else "No"}<br>
<b>Source:</b> {finding.source}<br>
<b>Linked Clients:</b> {finding.linked_clients or "—"}<br>
<b>Linked Projects:</b> {getattr(finding, 'linked_projects', None) or "—"}<br><br>  <!-- Phase 2 cross-link -->
{finding.summary}
"""
        if "[Security-Relevant]" in (finding.title or ""):
            html += "<br><b>🛡️ Security-relevant – triage in Shield tab recommended (see Security tab for dedicated risk analysis)</b>"
        if finding.notes:
            html += f"<br><br><b>Notes:</b><br>{finding.notes}"
        info.setHtml(html)
        lay.addWidget(info, 1)

        btn_row = QHBoxLayout()
        btn_review = QPushButton("Mark Reviewed (clear raised)")
        btn_review.setToolTip("Mark reviewed (clear raised); 🛡️ security-relevant items remain visible for Shield triage")
        btn_review.clicked.connect(lambda: (self.intel.mark_raised(finding_id, False), dlg.accept(), self._refresh_raised_intel(), self._try_refresh_main_intel_tab()))
        btn_row.addWidget(btn_review)

        btn_link = QPushButton("Link to Client")
        btn_link.setToolTip("Link to Client; 🛡️ security-relevant items for Shield triage")
        btn_link.clicked.connect(lambda: (self._link_selected_intel_to_client(), dlg.accept(), self._refresh_raised_intel()))
        btn_row.addWidget(btn_link)

        btn_open = QPushButton("Open full Intel tab")
        btn_open.setToolTip("Open full Intel tab; 🛡️ security-relevant items for Shield triage")
        btn_open.clicked.connect(lambda: (self._open_selected_in_intel_tab(), dlg.accept()))
        btn_row.addWidget(btn_open)

        btn_close = QPushButton("Close")
        btn_close.setToolTip("Close; 🛡️ security-relevant items for Shield triage")
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_close)

        sec_label = QLabel("🛡️")
        sec_label.setToolTip("Security-relevant – triage in Shield tab")
        sec_label.setStyleSheet("font-size: 12px; color: #4fc3f7;")
        btn_row.addWidget(sec_label)

        lay.addLayout(btn_row)

        dlg.exec()

    def _try_refresh_main_intel_tab(self):
        """Best-effort refresh of the main Intel tab if accessible via parent."""
        parent = self.parent()
        if parent and hasattr(parent, "intel_tab"):
            try:
                parent.intel_tab._refresh_findings()
            except Exception:
                pass

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
        self.am_sweep_queue_tasks_chat_btn = QPushButton("AM Sweep → tasks")
        self.am_sweep_queue_tasks_chat_btn.setToolTip(
            "Create dashboard tasks from the current assignment filters (same as Delegation Board). "
            "Business category, one confirmation."
        )
        self.am_sweep_queue_tasks_chat_btn.clicked.connect(self._bulk_create_tasks_am_sweep_quick)
        self.am_sweep_queue_tasks_chat_btn.setStyleSheet(
            "QPushButton { color: #e8f5e9; background-color: #1b5e20; border: 1px solid #2e7d32; "
            "padding: 6px 12px; border-radius: 6px; font-weight: 600; }"
            "QPushButton:hover { background-color: #2e7d32; color: #ffffff; }"
        )
        self._apply_button_metrics(self.am_sweep_queue_tasks_chat_btn, min_width=168)
        top_row.addWidget(self.am_sweep_queue_tasks_chat_btn)
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
        # Next micro: live refresh of past docs list when typing in ask_input (for reference bias)
        try:
            self.ask_input.textChanged.connect(lambda: self._refresh_relevant_past_docs(getattr(self, "_last_focused_client_name", None)) if getattr(self, "_last_focused_client_name", None) else None)
        except Exception:
            pass
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
        # NOTE: Per explicit rule ("at most two vertical panes for any given tab"), the sidebar is now
        # ruthlessly limited to only what the user actually uses for delegation: Chats + Assignments.
        # Removed: View Memories button, Raised Intel + Shield noise, Relevant Past Documents, Suggested,
        # Work Plans, and all micro button groups. These can be reintroduced only on explicit request.

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
        chats_layout.addWidget(self.chat_list, 1)
        tabs.addTab(chats_panel, "Chats")

        # Assignments tab — EXACTLY TWO vertical panes (QSplitter) per the rule.
        # Top pane: workload + filters + table + primary actions
        # Bottom pane: large readable staff results + Export / Memory / Link / Open Chat
        asg_panel = QWidget()
        asg_layout = QVBoxLayout(asg_panel)
        asg_layout.setContentsMargins(6, 6, 6, 6)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        # Old scaffolding removed. Building clean two-pane content below.

        # Work Plans section removed (not requested in this sidebar under the two-pane rule).

        # Full clean two-pane implementation
        # Top pane
        board_pane = QWidget()
        b_layout = QVBoxLayout(board_pane)
        b_layout.setContentsMargins(4, 4, 4, 4)
        b_layout.setSpacing(4)

        self.staff_workload_label = QLabel("")
        self.staff_workload_label.setStyleSheet(
            "QLabel { color: #c8d1e0; font-size: 11px; padding: 4px 6px; "
            "background-color: #1f232b; border: 1px solid #3a3f48; border-radius: 4px; }"
        )
        self.staff_workload_label.setWordWrap(True)
        self.staff_workload_label.setTextFormat(Qt.TextFormat.RichText)
        # Clickable chips temporarily disabled (handler not present in this minimal two-pane version).
        # Can be restored in a follow-up if desired.
        b_layout.addWidget(self.staff_workload_label)

        fl = QGridLayout()
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setHorizontalSpacing(4)
        fl.setVerticalSpacing(3)
        self.assignment_scope_filter = QComboBox()
        # Default to "All" so completed staff work (Atlas etc. results) is visible by default.
        # The old "Open only" default was hiding exactly the things users want to review in the Results pane.
        self.assignment_scope_filter.addItem("All", "all")
        self.assignment_scope_filter.addItem("Open only", "open")
        self.assignment_scope_filter.currentTextChanged.connect(lambda _t: self._refresh_assignment_list())
        self.assignment_scope_filter.currentIndexChanged.connect(self._save_assignment_filter_state)
        # Force "All" on first creation so completed staff work (with results) is visible
        self.assignment_scope_filter.setCurrentIndex(0)
        fl.addWidget(self.assignment_scope_filter, 0, 0)
        self.assignment_status_filter = QComboBox()
        self.assignment_status_filter.addItems(["All", "proposed", "queued", "in_progress", "awaiting_review", "blocked", "done", "cancelled"])
        self.assignment_status_filter.currentTextChanged.connect(lambda _t: self._refresh_assignment_list())
        self.assignment_status_filter.currentIndexChanged.connect(self._save_assignment_filter_state)
        fl.addWidget(self.assignment_status_filter, 0, 1)
        self.assignment_assignee_filter = QComboBox()
        self.assignment_assignee_filter.addItem("All assignees", "")
        for a in self.db.agents_list_active():
            code = str(a.get("code") or "").strip().lower()
            if code and code != "navi":
                self.assignment_assignee_filter.addItem(f"{a.get('display_name') or code} ({code})", code)
        self.assignment_assignee_filter.currentTextChanged.connect(lambda _t: self._refresh_assignment_list())
        self.assignment_assignee_filter.currentIndexChanged.connect(self._save_assignment_filter_state)
        fl.addWidget(self.assignment_assignee_filter, 0, 2)
        self.assignment_search_input = QLineEdit()
        self.assignment_search_input.setPlaceholderText("Search task text / assignee")
        self.assignment_search_input.textChanged.connect(lambda _t: self._refresh_assignment_list())
        self.assignment_search_input.textChanged.connect(self._save_assignment_filter_state)
        fl.addWidget(self.assignment_search_input, 1, 0, 1, 3)
        _fh = QWidget(); _fh.setLayout(fl)
        b_layout.addWidget(_fh)

        self.assignment_count_label = QLabel("Only showing tasks assigned to staff that need your input. (CoS Plans history in dropdown; full legacy board removed.)")
        self.assignment_count_label.setStyleSheet("color: #9aa0a6; font-size: 10px;")
        b_layout.addWidget(self.assignment_count_label)

        # Proposed plans now behind dropdown only (per "history from a dropdown; not always present")
        plans_bar = QHBoxLayout()
        self.plans_dropdown = QPushButton("CoS Proposed Plans History ▾")
        self.plans_dropdown.setStyleSheet("font-size: 10px; padding: 2px 6px;")
        self.plans_menu = QMenu(self.plans_dropdown)
        self.plans_dropdown.setMenu(self.plans_menu)
        self.plans_menu.aboutToShow.connect(self._populate_cos_plans_menu)
        plans_bar.addWidget(self.plans_dropdown)
        plans_bar.addStretch(1)
        b_layout.addLayout(plans_bar)

        self.assignment_list = QTableWidget(0, 7)
        self.assignment_list.setHorizontalHeaderLabels(["Task", "Status", "Needs Input", "Priority", "Assignee", "Due", "Title"])
        self.assignment_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.assignment_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.assignment_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.assignment_list.setAlternatingRowColors(True)
        self.assignment_list.setSortingEnabled(True)
        self.assignment_list.verticalHeader().setVisible(False)
        self.assignment_list.itemSelectionChanged.connect(self._on_assignment_selection_changed)
        self.assignment_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.assignment_list.customContextMenuRequested.connect(self._show_assignment_context_menu)
        h = self.assignment_list.horizontalHeader()
        h.setStretchLastSection(True)
        h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        b_layout.addWidget(self.assignment_list, 1)

        # Simplified controls: only refresh for now.
        # "New work" creation moves to CoS chat + CoS Plans (dropdown).
        # Full assignment creation / bulk management removed from this always-visible pane.
        act = QHBoxLayout()
        rb = QPushButton("Refresh Needs-Input Tasks")
        rb.clicked.connect(self._refresh_assignment_list)
        act.addWidget(rb)
        act.addStretch(1)
        b_layout.addLayout(act)

        splitter.addWidget(board_pane)

        # Bottom pane
        results_pane = QWidget()
        r_layout = QVBoxLayout(results_pane)
        r_layout.setContentsMargins(4, 4, 4, 4)
        r_layout.setSpacing(6)

        self.assignment_details = QTextBrowser()
        self.assignment_details.setPlaceholderText(
            "Select a task (assigned to staff like Atlas/Mason) in the table above to view its details here.\n\n"
            "Use the CoS chat (left pane) for delegation and replies to staff. Right-click for basic actions."
        )
        self.assignment_details.setStyleSheet(
            "QTextBrowser { font-family: 'Segoe UI', 'Helvetica Neue', sans-serif; font-size: 13px; "
            "line-height: 1.35; color: #e8eaed; background-color: #1f232b; border: 1px solid #3a3f48; "
            "border-radius: 4px; padding: 8px; } QTextBrowser h3 { color: #8ab4f8; }"
        )
        self.assignment_details.setOpenExternalLinks(False)
        self.assignment_details.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        r_layout.addWidget(self.assignment_details, 1)

        resb = QHBoxLayout()
        self.asg_export_results_btn = QPushButton("Export Board")
        self.asg_export_results_btn.clicked.connect(self._export_assignment_board_markdown)
        self.asg_export_results_btn.setEnabled(True)
        resb.addWidget(self.asg_export_results_btn)
        self.asg_add_memory_btn = QPushButton("Refresh Tasks View")
        self.asg_add_memory_btn.clicked.connect(self._refresh_task_views)
        self.asg_add_memory_btn.setEnabled(True)
        resb.addWidget(self.asg_add_memory_btn)
        self.asg_link_project_btn = QPushButton("Focus Tasks Tab")
        self.asg_link_project_btn.clicked.connect(lambda: self._refresh_task_views())
        self.asg_link_project_btn.setEnabled(True)
        resb.addWidget(self.asg_link_project_btn)
        self.asg_open_chat_btn = QPushButton("Reply to Staff via Chat")
        self.asg_open_chat_btn.clicked.connect(self._open_assignment_in_assignee_console)
        resb.addWidget(self.asg_open_chat_btn)

        # Dedicated refresh for the selected assignment details (critical for knowing if work is progressing)
        refresh_btn = QPushButton("Refresh Details")
        refresh_btn.setToolTip("Refresh the needs-input tasks board and details")
        refresh_btn.clicked.connect(self._refresh_selected_assignment_details)
        resb.addWidget(refresh_btn)

        resb.addStretch(1)
        r_layout.addLayout(resb)

        splitter.addWidget(results_pane)
        splitter.setSizes([280, 480])  # Give results pane more initial room

        asg_layout.addWidget(splitter, 1)

        tabs.addTab(asg_panel, "Assignments")

        layout.addWidget(tabs)
        self._refresh_chat_list()
        self._refresh_assignment_list()
        # _refresh_staff_workload stubbed for the minimal two-pane version
        if not hasattr(self, "_refresh_staff_workload"):
            self._refresh_staff_workload = lambda: None
        self._refresh_staff_workload()

        # Lightweight timer to help users see if "In Progress" assignments are actually moving
        # (directly addresses "now it says In Progress but I don't see anything happening")
        self._assignment_activity_timer = QTimer(self)
        self._assignment_activity_timer.setInterval(45000)  # 45 seconds
        self._assignment_activity_timer.timeout.connect(self._maybe_refresh_active_assignment_details)

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

    def _create_new_chat_for_client(self, client_id: int, client_name: str):
        """Strong mode: create a new CoS chat focused on this client so dossier context is immediately available."""
        try:
            title = f"{client_name} – Planning & Delegation"
            new_chat_id = self.db.cos_create_chat(title=title)
            self._current_chat_id = new_chat_id
            self._refresh_chat_list()
            self._render_chat_history(force_bottom=True)

            if hasattr(self, "ask_input"):
                self.ask_input.setPlainText(f"Review priorities and open work for {client_name}.")
                self.ask_input.setFocus()
        except Exception as e:
            logger.warning(f"Failed to create client-focused CoS chat: {e}")

    def focus_on_client(self, client_id: int, client_name: str):
        """Focus CoS on a specific client (used by strong navigation from Clients tab)."""
        self._last_focused_client_name = client_name  # for Phase 1 past docs refresh
        self._create_new_chat_for_client(client_id, client_name)
        self._refresh_relevant_past_docs(client_name)

    def focus_on_assignment(self, assignment_id: int):
        """Attempt to focus a specific assignment when jumping from the Client Dossier."""
        try:
            # Switch to the Assignments subtab in the sidebar
            if hasattr(self, "sidebar_tabs"):
                for i in range(self.sidebar_tabs.count()):
                    if "assignment" in self.sidebar_tabs.tabText(i).lower():
                        self.sidebar_tabs.setCurrentIndex(i)
                        break

            if hasattr(self, "_refresh_assignment_list"):
                self._refresh_assignment_list()

            if hasattr(self, "show_toast"):
                self.show_toast(f"Opened assignment A-{assignment_id} in Chief of Staff", 4000)
        except Exception as e:
            logger.warning(f"focus_on_assignment failed: {e}")

    def _reassign_selected_assignment(self):
        if not self._current_assignment_id:
            QMessageBox.information(self, "Assignments", "Select an assignment first.")
            return
        # Guard for task rows (CoS now uses Tasks for needs-input pane)
        try:
            last = getattr(self, "_last_task_rows", None) or []
            if any(int(r.get("id") or 0) == int(self._current_assignment_id) and r.get("_is_task") for r in last):
                QMessageBox.information(self, "Tasks", "Reassign for staff tasks is done via the Tasks tab or by asking in CoS chat (e.g. 'reassign task #123 to mason').")
                return
        except Exception:
            pass
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

        # Phase 1 reinforcement: auto-refresh "Relevant Past Documents" list on any history render/reload
        # when a client is in focus (exact lightweight pattern as raised intel refreshes)
        if getattr(self, "_last_focused_client_name", None):
            self._refresh_relevant_past_docs(self._last_focused_client_name)

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
        """Sources exclusively from Tasks assigned to agents for the visible CoS pane (needs-input only).
        This fulfills the model: use the main pane for tasks requiring input; full legacy board removed.
        agent_assignments still used by other legacy surfaces (work plans, proposed list, chat handlers) during transition.
        """
        # Active agents
        try:
            agents = self.db.agents_list_active()
            agent_codes = {str(a.get("code") or "").strip().lower() for a in agents if a.get("code")}
            agent_codes.discard("")
            agent_codes.discard("navi")
        except Exception:
            agent_codes = set()

        try:
            candidate_tasks = self.db.list_tasks_rich(include_completed=False, limit=400)
        except Exception:
            candidate_tasks = []

        rows = []
        for t in candidate_tasks:
            assigned = (t.get("assigned_to") or "").strip().lower()
            if not assigned or assigned == "navi":
                continue
            if agent_codes and assigned not in agent_codes:
                continue
            blockers = (t.get("blockers") or "").strip()
            prio = int(t.get("priority") or 0)
            # "requires input" = has explicit blockers (agent/user handoff) or high prio open task
            needs_input = bool(blockers) or prio >= 4
            # Normalize for downstream code (details, health, snapshots still expect some assignment-like keys)
            norm = {
                "id": int(t.get("id") or 0),
                "title": (t.get("task_text") or "Untitled task")[:200],
                "brief_md": blockers or (t.get("task_text") or ""),
                "assignee_code": t.get("assigned_to") or "",
                "status": "blocked" if blockers else "in_progress",
                "priority": prio,
                "due_date": t.get("due_date") or "",
                "result_summary_md": "",
                "_is_task": True,
                "_task_row": t,
                "needs_input": needs_input,
            }
            rows.append(norm)

        # The UI filter is locked to needs_input, so enforce it
        _, assignee, query, health, followup, include_closed = self._assignment_filters()
        if followup == "needs_input" or True:  # always enforce for this pane
            rows = [r for r in rows if r.get("needs_input")]
        if assignee:
            rows = [r for r in rows if str(r.get("assignee_code") or "").lower() == assignee.lower()]
        if query:
            q = query.lower()
            rows = [r for r in rows if q in str(r.get("title") or "").lower() or q in str(r.get("brief_md") or "").lower()]

        return rows[:150]

    def refresh_proposed_assignments(self) -> None:
        """Load and display assignments in ``proposed`` status (Suggested Assignments panel)."""
        if not hasattr(self, "proposed_list"):
            return
        self.proposed_list.clear()
        rows = self.db.agent_list_assignments(status="proposed", limit=30)
        for r in rows:
            aid = int(r.get("id") or 0)
            if aid <= 0:
                continue
            title = str(r.get("title") or "Untitled")[:80]
            assignee = str(r.get("assignee_code") or "").strip().capitalize() or "Unknown"
            prio = int(r.get("priority") or 3)
            due = r.get("due_date") or "none"
            item_text = f"P-{aid} | {title} → {assignee} | P{prio} | Due {due}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, dict(r))
            self.proposed_list.addItem(item)
        if not rows:
            self._current_proposal = None
            if hasattr(self, "proposal_status_label"):
                self.proposal_status_label.setText("")

    # ---------------- Work Plans (Staff Coordinator) methods ----------------

    def refresh_work_plans(self) -> None:
        """Load proposed + active work plans into the Staff Coordinator list."""
        if not hasattr(self, "workplan_list"):
            return
        self.workplan_list.clear()
        try:
            proposed = self.db.list_work_plans(status="proposed", limit=20)
            active = self.db.list_work_plans(status="active", limit=20)
            delegated = self.db.list_work_plans(status="delegated", limit=10)
            all_plans = proposed + active + delegated
        except Exception as e:
            self.workplan_list.addItem(f"Error loading work plans: {e}")
            return

        for p in all_plans:
            pid = int(p.get("id") or 0)
            title = str(p.get("title") or "Untitled plan")[:75]
            status = str(p.get("status") or "").upper()
            goal_preview = str(p.get("goal") or "")[:60]
            text = f"WP-{pid} | {status} | {title} — {goal_preview}"

            # Show latest auto-reported progress note if present (makes the "staff reports back" visible in the tab)
            summary = str(p.get("summary_md") or "")
            recent = [ln.strip() for ln in summary.splitlines() if ln.strip().startswith("[") and "A-" in ln]
            if recent:
                last = recent[-1][:70]
                text += f"  |  {last}"

            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, dict(p))
            # Color proposed green-ish, active blue
            if status == "PROPOSED":
                item.setForeground(QColor("#22C55E"))
            elif status in ("ACTIVE", "DELEGATED"):
                item.setForeground(QColor("#3B82F6"))
            self.workplan_list.addItem(item)

        if hasattr(self, "workplan_status_label"):
            self.workplan_status_label.setText(
                f"{len(proposed)} proposed • {len(active)} active • Double-click or use buttons below"
            )

    def create_new_work_plan_from_goal(self) -> None:
        """Primary entry point: user tells CoS a goal → CoS proposes a full multi-agent plan."""
        goal = (self.new_plan_goal_edit.text() or "").strip()
        if not goal:
            QMessageBox.information(self, "Tell CoS what to do", "Type the goal or outcome you need in the text box above, then click 'Propose Staff Plan'.")
            return

        self.create_plan_btn.setEnabled(False)
        self.create_plan_btn.setText("Planning...")
        try:
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()
        except Exception:
            pass

        try:
            proposal = propose_work_plan(
                self.db,
                goal=goal,
                thread_id=getattr(self, "_current_chat_id", None),
            )
            # Show a nice summary dialog so the user can immediately review
            dlg = QDialog(self)
            dlg.setWindowTitle(f"CoS Proposed Plan WP-{proposal.plan_id}")
            dlg.setMinimumSize(720, 520)
            lay = QVBoxLayout(dlg)

            header = QLabel(f"<b>Goal:</b> {proposal.goal}")
            header.setWordWrap(True)
            lay.addWidget(header)

            summary = QTextEdit()
            summary.setReadOnly(True)
            summary.setPlainText(proposal.summary_md + "\n\n" + proposal.rationale)
            lay.addWidget(summary, 2)

            if proposal.assignments:
                a_list = QTextEdit()
                a_list.setReadOnly(True)
                lines = ["Proposed assignments:"]
                for a in proposal.assignments:
                    lines.append(f"• {a.get('assignee_code','?').upper()}: {a.get('title','')}")
                a_list.setPlainText("\n".join(lines))
                lay.addWidget(a_list, 1)

            if proposal.mason_consultation:
                mason_box = QTextEdit()
                mason_box.setReadOnly(True)
                mason_box.setPlainText("Mason consultation:\n" + proposal.mason_consultation)
                lay.addWidget(mason_box, 1)

            btn_row = QHBoxLayout()
            approve_btn = QPushButton("Approve & Delegate Now")
            close_btn = QPushButton("Close (plan stays proposed)")
            btn_row.addStretch(1)
            btn_row.addWidget(approve_btn)
            btn_row.addWidget(close_btn)
            lay.addLayout(btn_row)

            def do_approve():
                ok, msg, aids = approve_and_delegate_work_plan(self.db, proposal.plan_id, actor="navi")
                QMessageBox.information(dlg, "Delegated", msg)
                dlg.accept()
                self.refresh_work_plans()
                if hasattr(self, "refresh_proposed_assignments"):
                    self.refresh_proposed_assignments()

            approve_btn.clicked.connect(do_approve)
            close_btn.clicked.connect(dlg.accept)

            dlg.exec()
            self.new_plan_goal_edit.clear()
            self.refresh_work_plans()
        except Exception as ex:
            QMessageBox.critical(self, "Planning Failed", f"CoS could not build the plan:\n{ex}")
        finally:
            self.create_plan_btn.setEnabled(True)
            self.create_plan_btn.setText("Propose Staff Plan")

    def _on_workplan_double_clicked(self, item: QListWidgetItem) -> None:
        row = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row, dict):
            return
        self._current_workplan = dict(row)
        pid = int(row.get("id") or 0)
        if hasattr(self, "workplan_status_label"):
            self.workplan_status_label.setText(f"Selected WP-{pid} — use Approve or Report buttons")

    def approve_selected_work_plan(self) -> None:
        if not getattr(self, "_current_workplan", None):
            # try the current list selection
            item = self.workplan_list.currentItem()
            if item:
                self._current_workplan = item.data(Qt.ItemDataRole.UserRole)
        if not self._current_workplan:
            QMessageBox.warning(self, "No Plan Selected", "Select a proposed work plan first (double-click or single-click then Approve).")
            return

        pid = int(self._current_workplan.get("id") or 0)
        status = str(self._current_workplan.get("status") or "").lower()
        if status != "proposed":
            QMessageBox.information(self, "Not Proposed", f"WP-{pid} is already {status}. Only 'proposed' plans can be approved.")
            return

        ok = QMessageBox.question(
            self,
            "Approve & Delegate Work Plan?",
            f"Approve WP-{pid}?\n\nCoS will delegate all assignments to the specialist agents (Pulse, Shield, Mason, …).\nCoS will then report progress back to you at key checkpoints.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return

        success, msg, aids = approve_and_delegate_work_plan(self.db, pid, actor="navi")
        if success:
            QMessageBox.information(self, "Work Plan Delegated", msg + f"\n\nAssignments: {aids}")
            self.refresh_work_plans()
            # Also refresh the lower-level assignment lists so the new work appears
            if hasattr(self, "refresh_proposed_assignments"):
                self.refresh_proposed_assignments()
        if hasattr(self, "refresh_work_plans"):
            self.refresh_work_plans()
            if hasattr(self, "refresh_work_plans"):
                self.refresh_work_plans()
            if hasattr(self, "refresh_assignment_board"):
                self.refresh_assignment_board()
        else:
            QMessageBox.warning(self, "Delegation Failed", msg)

    def show_work_plan_report(self) -> None:
        if not getattr(self, "_current_workplan", None):
            item = self.workplan_list.currentItem()
            if item:
                self._current_workplan = item.data(Qt.ItemDataRole.UserRole)
        if not self._current_workplan:
            QMessageBox.warning(self, "No Plan", "Select a work plan first.")
            return
        pid = int(self._current_workplan.get("id") or 0)
        report = get_work_plan_checkpoint_report(self.db, pid)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Checkpoint Report — WP-{pid}")
        dlg.setMinimumSize(620, 420)
        lay = QVBoxLayout(dlg)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(report)
        lay.addWidget(txt)
        btn = QPushButton("Close")
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn)
        dlg.exec()

    def on_proposed_clicked(self, item: QListWidgetItem) -> None:
        row = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row, dict):
            return
        self._current_proposal = dict(row)
        pid = int(row.get("id") or 0)
        if hasattr(self, "proposal_status_label"):
            self.proposal_status_label.setText(f"Selected proposal P-{pid}")

    def edit_selected_proposal(self) -> None:
        if not self._current_proposal:
            QMessageBox.warning(self, "No Selection", "Select a proposal first.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Proposal")
        dlg.setMinimumWidth(520)
        outer = QVBoxLayout(dlg)
        form = QFormLayout()
        title_edit = QLineEdit(str(self._current_proposal.get("title") or ""))
        brief_edit = QPlainTextEdit(str(self._current_proposal.get("brief_md") or ""))
        brief_edit.setMinimumHeight(160)
        assignee_edit = QLineEdit(str(self._current_proposal.get("assignee_code") or ""))
        due_edit = QLineEdit(str(self._current_proposal.get("due_date") or ""))
        due_edit.setPlaceholderText("YYYY-MM-DD, MM-DD-YYYY, or none")
        form.addRow("Title:", title_edit)
        form.addRow("Brief:", brief_edit)
        form.addRow("Assignee:", assignee_edit)
        form.addRow("Due date:", due_edit)
        outer.addLayout(form)
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save Changes")
        cancel_btn = QPushButton("Cancel")
        btn_row.addStretch(1)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        outer.addLayout(btn_row)
        save_btn.clicked.connect(
            lambda: self._save_proposal_edits_dialog(
                dlg, title_edit, brief_edit, assignee_edit, due_edit
            )
        )
        cancel_btn.clicked.connect(dlg.reject)
        dlg.exec()

    def _save_proposal_edits_dialog(
        self,
        dlg: QDialog,
        title_edit: QLineEdit,
        brief_edit: QPlainTextEdit,
        assignee_edit: QLineEdit,
        due_edit: QLineEdit,
    ) -> None:
        proposal_id = int(self._current_proposal.get("id") or 0)
        if proposal_id <= 0:
            dlg.reject()
            return
        title = title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "Invalid title", "Title cannot be empty.")
            return
        due_ok, due_norm = _normalize_proposal_due_for_db(due_edit.text())
        if not due_ok:
            QMessageBox.warning(
                self,
                "Invalid due date",
                "Use YYYY-MM-DD, MM-DD-YYYY, or leave empty / none.",
            )
            return
        assignee = assignee_edit.text().strip().lower()
        if not assignee or not self.db.agent_get(assignee):
            QMessageBox.warning(self, "Invalid assignee", "Unknown agent code.")
            return
        row = self.db.agent_get_assignment(proposal_id)
        if not row or str(row.get("status") or "").strip().lower() != "proposed":
            QMessageBox.warning(self, "Not editable", "This proposal is no longer in proposed status.")
            dlg.reject()
            self.refresh_proposed_assignments()
        if hasattr(self, "refresh_work_plans"):
            self.refresh_work_plans()
            self._refresh_assignment_list()
            return
        old_asg = str(row.get("assignee_code") or "").strip().lower()
        if old_asg != assignee:
            if not self.db.agent_reassign_assignment(
                assignment_id=proposal_id,
                new_assignee_code=assignee,
                actor_code="navi",
                note="Edited before approval",
            ):
                QMessageBox.warning(self, "Update failed", "Could not update assignee.")
                return
        if not self.db.agent_update_assignment_fields(
            assignment_id=proposal_id,
            actor_code="navi",
            title=title,
            brief_md=brief_edit.toPlainText(),
            due_date=due_norm,
            note="Proposal edited",
        ):
            QMessageBox.warning(self, "Update failed", "Could not save proposal fields.")
            return
        dlg.accept()
        self._current_proposal = self.db.agent_get_assignment(proposal_id) or self._current_proposal
        self.refresh_proposed_assignments()
        if hasattr(self, "refresh_work_plans"):
            self.refresh_work_plans()
        self._refresh_assignment_list()

    def approve_selected_proposal(self) -> None:
        if not self._current_proposal:
            QMessageBox.warning(self, "No Selection", "Select a proposal first.")
            return
        proposal_id = int(self._current_proposal.get("id") or 0)
        if proposal_id <= 0:
            return
        cos = ChiefOfStaffService(self.db, main_window=self.window())
        result = cos.approve_proposal(proposal_id)
        QMessageBox.information(self, "Approve proposal", result)
        self._current_proposal = None
        if hasattr(self, "proposal_status_label"):
            self.proposal_status_label.setText("")
        self.refresh_proposed_assignments()
        if hasattr(self, "refresh_work_plans"):
            self.refresh_work_plans()
        self.refresh_assignments_board()

    def reject_selected_proposal(self) -> None:
        if not self._current_proposal:
            QMessageBox.warning(self, "No Selection", "Select a proposal first.")
            return
        proposal_id = int(self._current_proposal.get("id") or 0)
        if proposal_id <= 0:
            return
        confirm = QMessageBox.question(
            self,
            "Reject proposal",
            f"Reject (cancel) proposal P-{proposal_id}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        cos = ChiefOfStaffService(self.db)
        result = cos.reject_proposal(proposal_id)
        QMessageBox.information(self, "Reject proposal", result)
        self._current_proposal = None
        if hasattr(self, "proposal_status_label"):
            self.proposal_status_label.setText("")
        self.refresh_proposed_assignments()
        if hasattr(self, "refresh_work_plans"):
            self.refresh_work_plans()
        self.refresh_assignments_board()

    def refresh_assignments_board(self) -> None:
        """Refresh the main delegation / assignment table (and proposed list via inner hook)."""
        self._refresh_assignment_list()

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
        self._last_task_rows = rows  # for details fallback when rows are task-based
        now = datetime.now()
        self.assignment_list.setRowCount(len(rows))

        for row_idx, r in enumerate(rows):
            tid = int(r.get("id") or 0)
            title = str(r.get("title") or "Untitled")
            assignee = str(r.get("assignee_code") or "agent")
            status = str(r.get("status") or "queued")
            pr = int(r.get("priority") or 3)
            due = str(r.get("due_date") or "")
            # Prefer the pre-computed needs_input from our task filter; fallback to snapshot (for legacy rows during migration)
            needs_input_flag = bool(r.get("needs_input"))
            if not needs_input_flag:
                try:
                    snap = _assignment_agent_followup_snapshot(self.db, r)
                    needs_input_flag = bool(snap.get("needs_input"))
                except Exception:
                    pass
            needs_display = "⚠️ NEEDS INPUT" if needs_input_flag else ""

            # 7 columns to match header: Task, Status, NeedsInput, Priority, Assignee, Due, Title
            values = [
                (f"T-{tid}", tid),
                (status, status),
                (needs_display, 1 if needs_input_flag else 0),
                (f"P{pr}", pr),
                (assignee, assignee),
                (due or "", due or "9999-12-31"),
                (title, title.lower()),
            ]
            needs_bg = QColor("#F59E0B")
            needs_fg = QColor("#1a1a1a")
            for col, (display, sort_value) in enumerate(values):
                disp_str = str(display)
                if needs_input_flag and col == 0:
                    disp_str = f"⚠️ NEEDS INPUT — {disp_str}"
                item = QTableWidgetItem(disp_str)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, tid)
                item.setData(Qt.ItemDataRole.EditRole, sort_value)
                item.setText(disp_str)
                if needs_input_flag:
                    item.setBackground(QBrush(needs_bg))
                    item.setForeground(QBrush(needs_fg))
                    bold_font = QFont(item.font())
                    bold_font.setBold(True)
                    item.setFont(bold_font)
                    item.setToolTip("This task requires your input before the assigned staff can proceed.")
                self.assignment_list.setItem(row_idx, col, item)
        if hasattr(self, "assignment_count_label"):
            if not rows:
                self.assignment_count_label.setText(
                    "No tasks requiring input. Delegate via CoS chat (e.g. 'have Atlas research X and report back')."
                )
            else:
                self.assignment_count_label.setText(f"{len(rows)} task(s) needing input")
        _, _, _, _, followup_filter, _ = self._assignment_filters()
        self.assignment_list.setSortingEnabled(True)
        if followup_filter == "needs_input":
            self.assignment_list.sortByColumn(2, Qt.SortOrder.DescendingOrder)
        elif 0 <= sort_col < self.assignment_list.columnCount():
            self.assignment_list.sortByColumn(sort_col, sort_order)
        if current_aid > 0:
            self._select_assignment_row(current_aid)
        # Legacy proposed/workplan refreshes guarded (may target widgets removed per two-pane + dropdown history rule)
        if hasattr(self, "proposed_list"):
            try:
                self.refresh_proposed_assignments()
            except Exception:
                pass
        if hasattr(self, "refresh_work_plans"):
            try:
                self.refresh_work_plans()
            except Exception:
                pass

    def _selected_assignment_id(self) -> int:
        if not hasattr(self, "assignment_list"):
            return 0
        row = int(self.assignment_list.currentRow())
        if row < 0:
            return 0
        item = self.assignment_list.item(row, 0)
        return int(item.data(Qt.ItemDataRole.UserRole) or 0) if item is not None else 0

    def _populate_cos_plans_menu(self):
        """Dynamically load proposed CoS Plans into the dropdown (history only; main board is needs-input tasks)."""
        if not hasattr(self, "plans_menu"):
            return
        self.plans_menu.clear()
        try:
            plans = self.db.list_proposed_daily_plans(limit=15)
        except Exception as e:
            act = self.plans_menu.addAction(f"(error loading plans: {e})")
            act.setEnabled(False)
            return
        if not plans:
            act = self.plans_menu.addAction("(no proposed CoS Plans yet — ask in chat e.g. 'plan my day')")
            act.setEnabled(False)
            return
        for p in plans:
            date = p.get("date") or ""
            status = p.get("status") or "proposed"
            gen = (p.get("generated_at") or "")[:16]
            text = f"{date} • {status} • {gen}"
            act = self.plans_menu.addAction(text)
            # capture p
            act.triggered.connect(lambda checked=False, plan=p: self._show_cos_plan(plan))
        self.plans_menu.addSeparator()
        refresh_act = self.plans_menu.addAction("Refresh list")
        refresh_act.triggered.connect(self._populate_cos_plans_menu)

    def _show_cos_plan(self, plan: dict):
        """Show a CoS proposed plan from history dropdown."""
        if not plan:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"CoS Plan — {plan.get('date', '')}")
        dlg.setMinimumSize(700, 500)
        lay = QVBoxLayout(dlg)
        info = QLabel(f"Status: {plan.get('status','proposed')} | Generated: {plan.get('generated_at','')}")
        lay.addWidget(info)
        content = QTextEdit()
        content.setReadOnly(True)
        # Prefer visual or json or md
        txt = plan.get("visual_html") or plan.get("plan_json") or plan.get("plan_md") or "(no content stored)"
        if isinstance(txt, (dict, list)):
            import json
            txt = json.dumps(txt, indent=2)
        content.setPlainText(str(txt))
        lay.addWidget(content, 1)
        btns = QHBoxLayout()
        approve_btn = QPushButton("Approve / Turn into Tasks")
        approve_btn.clicked.connect(lambda: (self._approve_cos_plan(plan.get("date")), dlg.accept()))
        btns.addWidget(approve_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        btns.addWidget(close_btn)
        btns.addStretch(1)
        lay.addLayout(btns)
        dlg.exec()

    def _approve_cos_plan(self, date_str: str):
        """Approve a CoS plan date -> mark approved and turn embedded tasks into real assigned Tasks (if not already)."""
        if not date_str:
            return
        try:
            plan = self.db.get_daily_plan(date_str) or {}
            ok = self.db.approve_daily_plan(date_str)
            created = 0
            plan_json = plan.get("plan_json") or {}
            if isinstance(plan_json, str):
                try:
                    import json
                    plan_json = json.loads(plan_json)
                except Exception:
                    plan_json = {}
            tasks = plan_json.get("tasks") or []
            for tspec in tasks:
                try:
                    # create if not exists - use add_task; it will be open by default
                    tid = self.db.add_task(
                        session_id=None,
                        task_text=tspec.get("title") or "CoS plan task",
                        due_date=tspec.get("due_date"),
                        category="Business",
                        assigned_to=tspec.get("assigned_to"),
                        blockers=tspec.get("blockers"),
                        priority=int(tspec.get("priority", 3)),
                    )
                    if tid:
                        created += 1
                except Exception:
                    pass
            msg = f"Plan for {date_str} marked approved."
            if created:
                msg += f" Created/ensured {created} task(s) with assigned_to."
            else:
                msg += " (No new tasks created from plan content this time.)"
            QMessageBox.information(self, "CoS Plan", msg)
        except Exception as e:
            QMessageBox.warning(self, "CoS Plan", f"Approve failed: {e}")

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
            "# CoS Needs-Input Tasks Snapshot (from Tasks table, assigned_to staff)",
            "",
            f"- Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- Filter status: {status_str}",
            f"- Filter follow-up: {followup_str}",
            f"- Filter assignee: {assignee_str}",
            f"- Search query: {query_str}",
            f"- Total rows: {len(rows)}",
            "",
            "| Task | Status | Needs Input | Priority | Assignee | Due | Title |",
            "|---|---|---|---:|---|---|---|",
        ]
        for r in rows:
            tid = int(r.get("id") or 0)
            st_row = _esc(r.get("status") or "")
            needs = "YES" if r.get("needs_input") else ""
            pr = int(r.get("priority") or 3)
            assignee = _esc(r.get("assignee_code") or "")
            due = _esc(r.get("due_date") or "")
            title = _esc(r.get("title") or "Untitled")
            lines.append(
                f"| T-{tid} | {st_row} | {needs} | {pr} | {assignee} | {due} | {title} |"
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
            if hasattr(self, "_assignment_activity_timer"):
                self._assignment_activity_timer.stop()
            return
        self._on_assignment_clicked(aid)

        # Skip legacy agent activity timer for task rows (new model uses chat for updates)
        try:
            last = getattr(self, "_last_task_rows", None) or []
            is_task_row = any(int(r.get("id") or 0) == aid and r.get("_is_task") for r in last)
            if is_task_row:
                if hasattr(self, "_assignment_activity_timer"):
                    self._assignment_activity_timer.stop()
                return
        except Exception:
            pass

        # Start/stop lightweight activity polling for "In Progress" style work (legacy assignments only)
        try:
            row = self.db.agent_get_assignment(int(aid))
            status = str(row.get("status") or "").lower() if row else ""
            active_statuses = {"in_progress", "awaiting_review", "blocked"}
            if status in active_statuses:
                if hasattr(self, "_assignment_activity_timer"):
                    if not self._assignment_activity_timer.isActive():
                        self._assignment_activity_timer.start()
            else:
                if hasattr(self, "_assignment_activity_timer"):
                    self._assignment_activity_timer.stop()
        except Exception:
            if hasattr(self, "_assignment_activity_timer"):
                self._assignment_activity_timer.stop()

    def _on_assignment_clicked(self, item_or_id):
        aid = item_or_id
        if isinstance(item_or_id, QTableWidgetItem):
            aid = item_or_id.data(Qt.ItemDataRole.UserRole)
        if aid is None:
            return
        self._current_assignment_id = int(aid)

        # Task-based row (new CoS needs-input source): show basic info; full details + chat link via CoS chat or Tasks tab
        # During migration some legacy paths still expect assignment rows.
        try:
            row = self.db.agent_get_assignment(self._current_assignment_id)
        except Exception:
            row = None

        if not row:
            # Assume it's a Task id now
            try:
                t = next((x for x in (getattr(self, "_last_task_rows", None) or []) if int(x.get("id") or 0) == self._current_assignment_id), None)
                if not t:
                    # fallback fetch
                    ts = self.db.list_tasks_rich(include_completed=False, limit=500)
                    t = next((x for x in ts if int(x.get("id") or 0) == self._current_assignment_id), None)
                if t:
                    lines = [
                        f"Task #{t.get('id')}",
                        f"Text: {t.get('task_text','')}",
                        f"Assigned to: {t.get('assigned_to','')}",
                        f"Priority: P{t.get('priority','')}",
                        f"Due: {t.get('due_date','')}",
                        f"Blockers / needs input: {t.get('blockers','') or '(none)'}",
                        "",
                        "Use CoS chat or the Tasks tab to update, reply to the assignee, or add notes.",
                        "This pane shows needs-input tasks assigned to staff (Atlas, Mason, etc.).",
                    ]
                    self.assignment_details.setPlainText("\n".join(lines))
                    for btn in (getattr(self, 'asg_export_results_btn', None), getattr(self, 'asg_add_memory_btn', None), getattr(self, 'asg_link_project_btn', None)):
                        if btn: btn.setEnabled(False)
                    return
            except Exception:
                pass
            self.assignment_details.setPlainText(f"Item #{aid} (legacy or not found in current view).")
            for btn in (getattr(self, 'asg_export_results_btn', None), getattr(self, 'asg_add_memory_btn', None), getattr(self, 'asg_link_project_btn', None)):
                if btn: btn.setEnabled(False)
            return

        # Enable result actions in the bottom pane
        for btn in (getattr(self, 'asg_export_results_btn', None),
                    getattr(self, 'asg_add_memory_btn', None),
                    getattr(self, 'asg_link_project_btn', None)):
            if btn: btn.setEnabled(True)
        health_flags = _assignment_health_flags(row, now=datetime.now())
        events = self.db.agent_get_assignment_events(assignment_id=self._current_assignment_id, limit=40)
        artifacts = self.db.agent_list_artifacts(assignment_id=self._current_assignment_id, limit=10)
        followup = _assignment_agent_followup_snapshot(self.db, row)
        status = str(row.get("status") or "").lower()

        # Header block (always first)
        lines = [
            f"ID: A-{int(row.get('id') or 0):04d}",
            f"Title: {row.get('title') or ''}",
            f"Status: {row.get('status') or ''}",
            f"Assignee: {row.get('assignee_code') or ''}",
            f"Last updated: {row.get('updated_at') or '(unknown)'}",
        ]

        latest_reply = str(followup.get("latest_agent_reply") or "").strip()
        request_lines = [str(x).strip() for x in (followup.get("request_lines") or []) if str(x).strip()]

        # For active work, put a very clear, scannable activity summary right at the top
        if status in ("in_progress", "awaiting_review", "blocked"):
            lines.append("")
            lines.append("=== CURRENT ACTIVITY STATUS ===")

            # Compute rough "last activity" from events
            last_event_ts = ""
            last_actor = ""
            if events:
                # events are returned oldest first in many queries; take the last one as most recent
                last_ev = events[-1]
                last_event_ts = str(last_ev.get("created_at") or "")
                last_actor = str(last_ev.get("actor_code") or "")

            if last_event_ts:
                lines.append(f"Last event: {last_event_ts} by {last_actor or 'agent'}")
            else:
                lines.append("Last event: (no events yet)")

            lines.append(f"Needs input from you: {'YES' if followup.get('needs_input') else 'no'}")
            if latest_reply:
                lines.append(f"Most recent message from agent: { _single_line_preview(latest_reply, limit=400) }")

            if request_lines:
                lines.append("Still waiting on you for:")
                for req in request_lines[:3]:
                    lines.append(f"  • {req}")

        # The rest of the details
        lines.append("")
        lines.append("Brief:")
        lines.append(str(row.get("brief_md") or "").strip())

        if latest_reply and status not in ("in_progress", "awaiting_review", "blocked"):
            # Show follow-up later only for non-active items
            lines.extend(["", "Agent follow-up:", f"Needs input: {'yes' if followup.get('needs_input') else 'no'}"])
            lines.append(f"Latest agent update: { _single_line_preview(latest_reply, limit=500) }")

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

        lines.extend(["", "Recent Events (newest last):"])
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

        # Make the Open Assignee Chat button context-sensitive when the assignment needs input
        if hasattr(self, "asg_open_chat_btn"):
            if followup.get("needs_input"):
                assignee = str(row.get("assignee_code") or "assignee").upper()
                self.asg_open_chat_btn.setText(f"Reply to {assignee} (provide input)")
                self.asg_open_chat_btn.setEnabled(True)
            else:
                self.asg_open_chat_btn.setText("Open Assignee Chat")

    def _refresh_selected_assignment_details(self):
        """Re-render the bottom pane for the currently selected assignment.
        Use this to check if an 'In Progress' item has produced new events/artifacts/replies."""
        if not getattr(self, "_current_assignment_id", None):
            return
        try:
            self._on_assignment_clicked(int(self._current_assignment_id))
            # Also refresh the table row so status etc. is up to date
            self._refresh_assignment_list()
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Assignments", f"Failed to refresh details: {e}")

    def _maybe_refresh_active_assignment_details(self):
        """Called by the activity timer. Only refreshes if the selected assignment looks active."""
        if not getattr(self, "_current_assignment_id", None):
            self._assignment_activity_timer.stop()
            return

        try:
            row = self.db.agent_get_assignment(int(self._current_assignment_id))
            if not row:
                self._assignment_activity_timer.stop()
                return

            status = str(row.get("status") or "").lower()
            active_statuses = {"in_progress", "awaiting_review", "blocked"}
            if status in active_statuses:
                # Silent refresh of just the details pane (don't spam the table)
                self._on_assignment_clicked(int(self._current_assignment_id))
            else:
                # No longer active, stop the timer
                self._assignment_activity_timer.stop()
        except Exception:
            # Don't let timer errors surface to the user
            pass

    def _show_assignment_context_menu(self, pos):
        """Right-click menu on the assignment table (keeps the UI to two vertical panes)."""
        table = self.assignment_list
        idx = table.indexAt(pos)
        if not idx.isValid():
            return
        # Ensure the clicked row is selected
        if not table.selectionModel().isRowSelected(idx.row(), idx.parent()):
            table.selectRow(idx.row())
        # For task-based rows (current CoS model), show a simplified menu; full legacy assignment actions are in other surfaces
        row = self._filtered_assignment_rows()[idx.row()] if idx.row() < len(self._filtered_assignment_rows() or []) else {}
        if row.get('_is_task'):
            menu = QMenu(self)
            menu.addAction("Open in Tasks tab (or use CoS chat to reply)").triggered.connect(lambda: self._refresh_task_views())
            menu.addAction("Refresh board").triggered.connect(self._refresh_assignment_list)
            menu.exec(table.viewport().mapToGlobal(pos))
            return

        menu = QMenu(self)
        menu.setStyleSheet("QMenu { font-size: 12px; }")

        reassign_act = menu.addAction("Reassign…")
        reassign_act.triggered.connect(self._reassign_selected_assignment)

        menu.addSeparator()

        status_menu = menu.addMenu("Set Status")
        for st in ["queued", "in_progress", "awaiting_review", "blocked", "done", "cancelled"]:
            act = status_menu.addAction(st.replace("_", " ").title())
            act.triggered.connect(lambda checked=False, s=st: self._set_assignment_status(s))

        cancel_act = menu.addAction("Cancel (soft delete)")
        cancel_act.triggered.connect(lambda: self._set_assignment_status("cancelled"))

        menu.addSeparator()

        chat_act = menu.addAction("Open Assignee Chat")
        chat_act.triggered.connect(self._open_assignment_in_assignee_console)

        # If the current selection needs input, surface a clear "Reply" action
        if self._current_assignment_id:
            try:
                cur_row = self.db.agent_get_assignment(int(self._current_assignment_id))
                if cur_row:
                    snap = _assignment_agent_followup_snapshot(self.db, cur_row)
                    if snap.get("needs_input"):
                        reply_act = menu.addAction("Reply / Provide Input to Assignee")
                        reply_act.triggered.connect(self._open_assignment_in_assignee_console)
            except Exception:
                pass

        menu.exec(table.viewport().mapToGlobal(pos))

    def _set_assignment_status(self, to_status: str):
        if not self._current_assignment_id:
            QMessageBox.information(self, "Assignments", "Select an assignment first.")
            return
        # Guard for task rows
        try:
            last = getattr(self, "_last_task_rows", None) or []
            if any(int(r.get("id") or 0) == int(self._current_assignment_id) and r.get("_is_task") for r in last):
                QMessageBox.information(self, "Tasks", "Status for staff tasks is managed in the Tasks tab (or tell CoS chat to update it).")
                return
        except Exception:
            pass
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
        # Guard for task rows (tasks support priority directly via Tasks tab)
        try:
            last = getattr(self, "_last_task_rows", None) or []
            if any(int(r.get("id") or 0) == int(self._current_assignment_id) and r.get("_is_task") for r in last):
                QMessageBox.information(self, "Tasks", "Edit priority for staff tasks in the Tasks tab (or ask in CoS chat).")
                return
        except Exception:
            pass
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

    def _bulk_create_tasks_execute(
        self,
        rows: list,
        *,
        category: str,
        include_closed: bool,
        custom_note: str,
    ) -> tuple[int, int, int, int]:
        """Returns (created, skipped_existing, skipped_closed, failed)."""
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
        return created, skipped_existing, skipped_closed, failed

    def _bulk_create_tasks_am_sweep_quick(self):
        """Default bulk path: Business, skip closed, no note—one confirmation."""
        rows = self._filtered_assignment_rows()
        if not rows:
            QMessageBox.information(
                self,
                "Dashboard tasks",
                "No assignments match the current filters. Adjust the board filters or run AM Sweep first.",
            )
            return
        confirm = QMessageBox.question(
            self,
            "Create dashboard tasks",
            f"Create dashboard tasks for up to {len(rows)} assignment(s) in the current filtered list?\n\n"
            "Category: Business\n"
            "Skips done/cancelled assignments and assignments that already have a linked dashboard task.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        created, skipped_existing, skipped_closed, failed = self._bulk_create_tasks_execute(
            rows,
            category="Business",
            include_closed=False,
            custom_note="",
        )
        QMessageBox.information(
            self,
            "Dashboard tasks",
            (
                f"Created: {created}\n"
                f"Skipped (already had task): {skipped_existing}\n"
                f"Skipped (done/cancelled): {skipped_closed}\n"
                f"Failed: {failed}"
            ),
        )
        self._refresh_task_views()
        if self._current_assignment_id:
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

        created, skipped_existing, skipped_closed, failed = self._bulk_create_tasks_execute(
            rows,
            category=str(category),
            include_closed=include_closed,
            custom_note=custom_note or "",
        )

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
            QMessageBox.information(self, "Assignments", "Select a task first.")
            return

        # Check if this is a task row (new model)
        is_task = False
        assignee = ""
        title = ""
        try:
            last_rows = getattr(self, "_last_task_rows", None) or []
            for r in last_rows:
                if int(r.get("id") or 0) == int(self._current_assignment_id):
                    is_task = bool(r.get("_is_task"))
                    assignee = str(r.get("assignee_code") or "").strip().lower()
                    title = str(r.get("title") or "")
                    break
        except Exception:
            pass

        if is_task:
            # For tasks, focus the main CoS chat (left pane in this tab) and prefill a reply prompt.
            # This keeps the "plain language chat" model for interacting with staff.
            try:
                # The CoS tab itself has the chat on the left via horizontal splitter in _setup_ui / _build_chat_panel
                # Switch focus to the ask_input if available.
                if hasattr(self, "ask_input"):
                    self.ask_input.setFocus()
                    prompt = f"Reply to {assignee or 'staff'} about task #{self._current_assignment_id} ({title}): "
                    self.ask_input.setText(prompt)
                    self.ask_input.setCursorPosition(len(prompt))
                    QMessageBox.information(self, "Reply to Staff", f"Focused CoS chat. Type your reply/instructions for {assignee or 'the assignee'}.")
                    return
            except Exception:
                pass
            # Fallback
            QMessageBox.information(self, "Reply to Staff", f"Use the chat on the left to reply to {assignee or 'staff'} about task #{self._current_assignment_id}.\n\nE.g. 'Atlas, provide update on task #{self._current_assignment_id}'")
            return

        # Legacy assignment path
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
        # Phase 1: refresh past docs when loading a chat (if client-focused)
        if getattr(self, "_last_focused_client_name", None):
            self._refresh_relevant_past_docs(self._last_focused_client_name)

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
        # Phase 1 light auto-refresh for Relevant Past Documents when client-focused
        if getattr(self, "_last_focused_client_name", None):
            self._refresh_relevant_past_docs(self._last_focused_client_name)
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
        # Phase 1 light auto-refresh for Relevant Past Documents on response (client-focused chats)
        if getattr(self, "_last_focused_client_name", None):
            self._refresh_relevant_past_docs(self._last_focused_client_name)

    def _on_ask_error(self, err: str):
        self._ask_worker = None
        self._am_sweep_worker = None
        self.ask_btn.setEnabled(True)
        self.ask_progress.setVisible(False)
        if self._current_chat_id is not None:
            session_id = f"cos_{self._current_chat_id}"
            try:
                self.db.save_message(session_id, "assistant", str(err or "").strip())
                self.db.cos_update_chat(self._current_chat_id)
            except Exception:
                logger.exception("CoS: failed to persist assistant error message")
        self._refresh_chat_list()
        scroll_state = self._capture_chat_scroll_state()
        self.chat_display.append(f"<p style='color: #e07a7a;'>{html.escape(str(err or ''))}</p>")
        # Phase 1: also refresh past docs on error paths for client chats (lightweight consistency)
        if getattr(self, "_last_focused_client_name", None):
            self._refresh_relevant_past_docs(self._last_focused_client_name)
        self._restore_chat_scroll_state(scroll_state)

import sqlite3
import logging
from collections import deque
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QSplashScreen,
    QTextBrowser, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QDateEdit, QTableWidget,
    QTableWidgetItem, QCheckBox, QComboBox, QLabel, QSplitter, QTextEdit, QDialog, QDialogButtonBox,
    QHeaderView, QMessageBox, QFileDialog, QMenu, QProgressBar, QApplication, QSizePolicy,
    QSystemTrayIcon, QStyle, QSpinBox, QGroupBox,
)
from PyQt6.QtCore import Qt, QDate, QTimer, pyqtSlot, QUrl, QThread, pyqtSignal, QMetaObject, Q_ARG
from PyQt6.QtGui import QPixmap, QAction, QDesktopServices, QColor, QPainter, QKeyEvent
from core.db import DatabaseManager
from gui.chat_window import ChatThread, sendMessage, saveChat, loadChat
from core.response_handler import ResponseHandler
from gui.todo_list import TodoList
from core.chat import ChatManager
import os
import json
from datetime import datetime, timedelta
from dateutil import parser
from bs4 import BeautifulSoup
import markdown
from core.compliance import ComplianceChecker, DocumentGenerator
import re
import requests
from gui.memory_viewer import MemoryViewerDialog
from gui.notes_tab import NoteTakingSystem, NoteProcessingThread
from gui.notifications import play_notification_sound
import html
from core.app_preferences import get_chat_history_render_limit, is_runtime_enabled
from core.chief_of_staff_service import get_cos_task_change_serial, set_cos_toast_callback
from core.agent_chat_service import (
    set_agent_grok_failure_toast_callback,
    set_agent_reply_toast_callback,
)
from core.grok_client import is_user_facing_llm_failure_message


class ChatEntryEdit(QTextEdit):
    """
    Multi-line chat input:
    - Enter sends
    - Shift+Enter inserts newline
    - Auto-grows up to a max number of lines
    """

    returnPressed = pyqtSignal()

    def __init__(self, *args, min_lines: int = 2, max_lines: int = 7, **kwargs):
        super().__init__(*args, **kwargs)
        self._min_lines = int(min_lines)
        self._max_lines = int(max_lines)

        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.document().contentsChanged.connect(self._update_height)
        self._update_height()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.returnPressed.emit()
                event.accept()
            return
        super().keyPressEvent(event)

    def _update_height(self):
        try:
            fm = self.fontMetrics()
            line_h = max(1, int(fm.lineSpacing()))
            min_h = int(line_h * max(1, self._min_lines) + 18)
            max_h = int(line_h * max(1, self._max_lines) + 18)

            doc_h = float(self.document().size().height())
            target = int(doc_h + 12)
            target = max(min_h, min(max_h, target))

            if self.height() != target:
                self.setFixedHeight(target)
        except Exception:
            return

def robust_json_parse(response_text, logger=None):
    """
    Robust JSON parsing that handles various API response formats.
    
    Args:
        response_text: Raw response text from API
        logger: Optional logger for debug messages
    
    Returns:
        tuple: (parsed_json_data, success_flag)
    """
    if logger is None:
        logger = print  # Fallback to print for debug messages
    
    # Step 1: Try direct JSON parsing first
    try:
        clean_response = response_text.strip()
        data = json.loads(clean_response)
        logger(f"Direct JSON parsing successful")
        return data, True
    except json.JSONDecodeError:
        logger(f"Direct JSON parsing failed, attempting extraction...")
    
    # Step 2: Try extracting JSON from markdown code blocks
    try:
        # Look for ```json...``` blocks
        json_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
        match = re.search(json_pattern, response_text, re.DOTALL | re.IGNORECASE)
        if match:
            json_str = match.group(1).strip()
            data = json.loads(json_str)
            logger(f"JSON extraction from code block successful")
            return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Code block extraction failed")
    
    # Step 3: Try regex extraction of JSON object
    try:
        # Look for first complete JSON object
        json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        match = re.search(json_pattern, response_text, re.DOTALL)
        if match:
            json_str = match.group(0).strip()
            data = json.loads(json_str)
            logger(f"Regex JSON extraction successful")
            return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Regex extraction failed")
    
    # Step 4: Try fixing common JSON issues
    try:
        clean_response = response_text.strip()
        
        # Remove common prefixes/suffixes
        clean_response = re.sub(r'^[^{]*', '', clean_response)  # Remove text before {
        clean_response = re.sub(r'[^}]*$', '', clean_response)  # Remove text after }
        
        # Fix common issues
        clean_response = re.sub(r',\s*}', '}', clean_response)  # Remove trailing commas
        clean_response = re.sub(r',\s*]', ']', clean_response)  # Remove trailing commas in arrays
        clean_response = re.sub(r'"\s*}', '}', clean_response)  # Remove trailing quotes
        clean_response = re.sub(r'"\s*]', ']', clean_response)  # Remove trailing quotes in arrays
        clean_response = re.sub(r'\s+', ' ', clean_response)   # Normalize whitespace
        
        # Ensure it starts and ends with braces
        if not clean_response.startswith('{'):
            clean_response = '{' + clean_response
        if not clean_response.endswith('}'):
            clean_response = clean_response + '}'
        
        data = json.loads(clean_response)
        logger(f"Fixed JSON parsing successful")
        return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Fixed JSON parsing failed")
    
    # Step 5: Try extracting partial JSON for truncated responses
    try:
        clean_response = response_text.strip()
        
        # Find the first { and last }
        start_idx = clean_response.find('{')
        end_idx = clean_response.rfind('}')
        
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = clean_response[start_idx:end_idx + 1]
            
            # Try to complete truncated JSON
            if json_str.count('{') > json_str.count('}'):
                json_str += '}' * (json_str.count('{') - json_str.count('}'))
            if json_str.count('"') % 2 != 0:
                json_str += '"'
            
            data = json.loads(json_str)
            logger(f"Partial JSON extraction successful")
            return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Partial JSON extraction failed")
    
    logger(f"All JSON parsing attempts failed")
    return None, False
from gui.dashboard_tab import DashboardTab
from gui.compliance_tab import ComplianceTab, ComplianceThread
from gui.meetings_tab import MeetingsTab
from gui.leads_tab import LeadsTab
from gui.workspace_tab import WorkspaceTab
from gui.deep_research_tab import DeepResearchTab
from gui.demo_full_cycle import (
    DEMO_RESEARCH_NAME,
    DEMO_WORKSPACE_PROMPT,
    DemoFullCycleResearchWorker,
)
from gui.chief_of_staff_tab import ChiefOfStaffTab
from gui.clients_tab import ClientsTab
from gui.agent_tab import AgentTab
from gui.billing_tab import BillingTab
from gui.team_directory_tab import TeamDirectoryTab
from gui.utils import *

logger = logging.getLogger(__name__)

# Try to import TasksTab - handle import errors gracefully
try:
    from gui.tasks_tab import TasksTab
    TASKS_TAB_AVAILABLE = True
    logger.info("TasksTab imported successfully")
except (ImportError, SyntaxError) as e:
    logger.warning(f"TasksTab not available: {e}")
    TASKS_TAB_AVAILABLE = False
    TasksTab = None

class EnhancedSplashScreen(QSplashScreen):
    """Enhanced splash screen with progress bar and status updates."""
    
    def __init__(self, pixmap):
        super().__init__(pixmap)
        self.setStyleSheet("""
            QSplashScreen {
                background-color: transparent;
                color: #e8eaed;
                font-size: 12px;
            }
        """)
        
        # Create progress bar
        self.progress_bar = QProgressBar(self)
        # Position progress bar at bottom center with some margin
        progress_width = min(300, pixmap.width() - 100)
        progress_x = (pixmap.width() - progress_width) // 2
        self.progress_bar.setGeometry(progress_x, pixmap.height() - 80, progress_width, 20)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #2e2f32;
                border-radius: 5px;
                text-align: center;
                background-color: #1c1e24;
                color: #e8eaed;
            }
            QProgressBar::chunk {
                background-color: #FD6262;
                border-radius: 3px;
            }
        """)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        
        # Create status label
        self.status_label = QLabel(self)
        # Center the status label
        label_width = min(400, pixmap.width() - 100)
        label_x = (pixmap.width() - label_width) // 2
        self.status_label.setGeometry(label_x, pixmap.height() - 50, label_width, 30)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #e8eaed;
                font-size: 10px;
                background-color: transparent;
            }
        """)
        self.status_label.setText("Initializing...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Create log display
        self.log_display = QTextBrowser(self)
        self.log_display.setGeometry(50, 50, pixmap.width() - 100, pixmap.height() - 150)
        self.log_display.setStyleSheet("""
            QTextBrowser {
                background-color: rgba(28, 30, 36, 0.75);
                color: #e8eaed;
                border: 1px solid rgba(46, 47, 50, 0.6);
                border-radius: 5px;
                font-size: 9px;
            }
        """)
        self.log_display.setMaximumHeight(200)
        
    def update_progress(self, value, status_text, log_message=None):
        """Update progress bar and status text."""
        self.progress_bar.setValue(value)
        self.status_label.setText(status_text)
        if log_message:
            self.log_display.append(f"[{datetime.now().strftime('%H:%M:%S')}] {log_message}")
            # Auto-scroll to bottom
            scrollbar = self.log_display.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._db = getattr(parent, "db", None)
        if self._db is None:
            self._db = DatabaseManager()

        from core import app_preferences as ap

        tabs = QTabWidget(self)

        # --- Lead gen tab ---
        lead_tab = QWidget()
        lead_layout = QVBoxLayout(lead_tab)
        self.system_message_input = QTextEdit(self)
        from config import CONFIG_DIR
        config_path = os.path.join(CONFIG_DIR, "lead_gen_config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.system_message_input.setText(cfg.get("system_message", ""))
            except Exception as e:
                logger.error("Error loading system message: %s", e)
                self.system_message_input.setText("")
        lead_layout.addWidget(QLabel("Grok system message (lead generation):"))
        lead_layout.addWidget(self.system_message_input)
        tabs.addTab(lead_tab, "Lead generation")

        # --- App preferences (stored in database, not .env) ---
        app_tab = QWidget()
        app_layout = QVBoxLayout(app_tab)
        app_layout.addWidget(
            QLabel(
                "Application preferences (saved in your database). "
                "Put only secrets (API keys, tokens) in config/.env."
            )
        )

        self.chk_runtime = QCheckBox("Enable background runtime scheduler")
        self.chk_runtime.setChecked(ap.is_runtime_enabled(self._db))
        app_layout.addWidget(self.chk_runtime)

        poll_row = QHBoxLayout()
        poll_row.addWidget(QLabel("Runtime poll interval (seconds):"))
        self.spin_runtime_poll = QSpinBox()
        self.spin_runtime_poll.setRange(5, 3600)
        self.spin_runtime_poll.setValue(ap.get_runtime_poll_interval_s(self._db))
        poll_row.addWidget(self.spin_runtime_poll)
        poll_row.addStretch()
        app_layout.addLayout(poll_row)

        lease_row = QHBoxLayout()
        lease_row.addWidget(QLabel("Runtime job lease (seconds):"))
        self.spin_runtime_lease = QSpinBox()
        self.spin_runtime_lease.setRange(30, 86400)
        self.spin_runtime_lease.setValue(ap.get_runtime_job_lease_s(self._db))
        lease_row.addWidget(self.spin_runtime_lease)
        lease_row.addStretch()
        app_layout.addLayout(lease_row)

        self.chk_local_api = QCheckBox("Enable local HTTP API")
        self.chk_local_api.setChecked(ap.is_local_api_enabled(self._db))
        app_layout.addWidget(self.chk_local_api)

        host_row = QHBoxLayout()
        host_row.addWidget(QLabel("Local API host:"))
        self.edit_api_host = QLineEdit(ap.get_local_api_host(self._db))
        host_row.addWidget(self.edit_api_host)
        app_layout.addLayout(host_row)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Local API port:"))
        self.spin_api_port = QSpinBox()
        self.spin_api_port.setRange(1, 65535)
        self.spin_api_port.setValue(ap.get_local_api_port(self._db))
        port_row.addWidget(self.spin_api_port)
        port_row.addStretch()
        app_layout.addLayout(port_row)

        log_row = QHBoxLayout()
        log_row.addWidget(QLabel("Local API log level:"))
        self.combo_api_log = QComboBox()
        self.combo_api_log.addItems(["critical", "error", "warning", "info", "debug", "trace"])
        cur_log = ap.get_local_api_log_level(self._db).lower()
        idx = self.combo_api_log.findText(cur_log)
        self.combo_api_log.setCurrentIndex(idx if idx >= 0 else 2)
        log_row.addWidget(self.combo_api_log)
        log_row.addStretch()
        app_layout.addLayout(log_row)

        self.chk_telegram = QCheckBox("Enable Telegram bot (requires local API + token in .env)")
        self.chk_telegram.setChecked(ap.is_telegram_bot_feature_enabled(self._db))
        app_layout.addWidget(self.chk_telegram)

        tg_row = QHBoxLayout()
        tg_row.addWidget(QLabel("Telegram allowed chat IDs (comma-separated, empty = allow all):"))
        self.edit_tg_chats = QLineEdit(",".join(ap.get_telegram_allowed_chat_ids(self._db)))
        tg_row.addWidget(self.edit_tg_chats)
        app_layout.addLayout(tg_row)

        self.chk_cos_memory = QCheckBox("Chief of Staff: passive memory extraction (extra model call)")
        self.chk_cos_memory.setChecked(ap.is_cos_passive_memory_extraction_enabled(self._db))
        app_layout.addWidget(self.chk_cos_memory)

        cos_perf = QGroupBox("Chief of Staff — performance (context + output limits)")
        cos_form = QVBoxLayout()
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Max output tokens (CoS replies):"))
        self.spin_cos_out_tok = QSpinBox()
        self.spin_cos_out_tok.setRange(256, 32768)
        self.spin_cos_out_tok.setSingleStep(256)
        self.spin_cos_out_tok.setValue(ap.get_cos_max_output_tokens(self._db))
        r1.addWidget(self.spin_cos_out_tok)
        r1.addStretch()
        cos_form.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Max output tokens (memory extraction pass):"))
        self.spin_cos_mem_tok = QSpinBox()
        self.spin_cos_mem_tok.setRange(256, 8192)
        self.spin_cos_mem_tok.setSingleStep(128)
        self.spin_cos_mem_tok.setValue(ap.get_cos_memory_max_output_tokens(self._db))
        r2.addWidget(self.spin_cos_mem_tok)
        r2.addStretch()
        cos_form.addLayout(r2)
        r3 = QHBoxLayout()
        r3.addWidget(
            QLabel(
                "Context budget (chars; AM Sweep includes email list; shrinks memory/prefs/calendar first):"
            )
        )
        self.spin_cos_budget = QSpinBox()
        self.spin_cos_budget.setRange(4000, 120000)
        self.spin_cos_budget.setSingleStep(1000)
        self.spin_cos_budget.setValue(ap.get_cos_context_budget_chars(self._db))
        r3.addWidget(self.spin_cos_budget)
        r3.addStretch()
        cos_form.addLayout(r3)
        r4 = QHBoxLayout()
        r4.addWidget(QLabel("Multi-turn: max history messages / max chars per message:"))
        self.spin_cos_hist_msg = QSpinBox()
        self.spin_cos_hist_msg.setRange(2, 24)
        self.spin_cos_hist_msg.setValue(ap.get_cos_history_max_messages(self._db))
        self.spin_cos_hist_chars = QSpinBox()
        self.spin_cos_hist_chars.setRange(200, 8000)
        self.spin_cos_hist_chars.setSingleStep(100)
        self.spin_cos_hist_chars.setValue(ap.get_cos_history_max_chars_per_message(self._db))
        r4.addWidget(self.spin_cos_hist_msg)
        r4.addWidget(self.spin_cos_hist_chars)
        r4.addStretch()
        cos_form.addLayout(r4)
        r5 = QHBoxLayout()
        r5.addWidget(QLabel("Max chars: preferences / calendar / memory block:"))
        self.spin_cos_prefs = QSpinBox()
        self.spin_cos_prefs.setRange(500, 50000)
        self.spin_cos_prefs.setSingleStep(500)
        self.spin_cos_prefs.setValue(ap.get_cos_preferences_max_chars(self._db))
        self.spin_cos_cal = QSpinBox()
        self.spin_cos_cal.setRange(500, 50000)
        self.spin_cos_cal.setSingleStep(500)
        self.spin_cos_cal.setValue(ap.get_cos_calendar_max_chars(self._db))
        self.spin_cos_mem_block = QSpinBox()
        self.spin_cos_mem_block.setRange(500, 80000)
        self.spin_cos_mem_block.setSingleStep(500)
        self.spin_cos_mem_block.setValue(ap.get_cos_memory_context_max_chars(self._db))
        r5.addWidget(self.spin_cos_prefs)
        r5.addWidget(self.spin_cos_cal)
        r5.addWidget(self.spin_cos_mem_block)
        r5.addStretch()
        cos_form.addLayout(r5)
        r6 = QHBoxLayout()
        r6.addWidget(QLabel("Max lines: dashboard tasks / open assignments:"))
        self.spin_cos_task_lines = QSpinBox()
        self.spin_cos_task_lines.setRange(5, 80)
        self.spin_cos_task_lines.setValue(ap.get_cos_max_task_lines(self._db))
        self.spin_cos_assign_lines = QSpinBox()
        self.spin_cos_assign_lines.setRange(5, 100)
        self.spin_cos_assign_lines.setValue(ap.get_cos_max_assignment_lines(self._db))
        r6.addWidget(self.spin_cos_task_lines)
        r6.addWidget(self.spin_cos_assign_lines)
        r6.addStretch()
        cos_form.addLayout(r6)
        r7 = QHBoxLayout()
        r7.addWidget(QLabel("Max chars (AM Sweep important-email context):"))
        self.spin_cos_emails = QSpinBox()
        self.spin_cos_emails.setRange(500, 50000)
        self.spin_cos_emails.setSingleStep(500)
        self.spin_cos_emails.setValue(ap.get_cos_emails_context_max_chars(self._db))
        r7.addWidget(self.spin_cos_emails)
        r7.addStretch()
        cos_form.addLayout(r7)
        cos_perf.setLayout(cos_form)
        app_layout.addWidget(cos_perf)

        self.chk_briefing_off = QCheckBox("Disable daily briefing and email fetch")
        self.chk_briefing_off.setChecked(ap.is_briefing_and_email_disabled(self._db))
        app_layout.addWidget(self.chk_briefing_off)

        gpu_row = QHBoxLayout()
        gpu_row.addWidget(QLabel("Local LLM GPU layers:"))
        self.spin_llm_gpu = QSpinBox()
        self.spin_llm_gpu.setRange(0, 999)
        self.spin_llm_gpu.setValue(ap.get_local_llm_gpu_layers(self._db))
        gpu_row.addWidget(self.spin_llm_gpu)
        gpu_row.addStretch()
        app_layout.addLayout(gpu_row)

        ctx_row = QHBoxLayout()
        ctx_row.addWidget(QLabel("Local LLM context size:"))
        self.spin_llm_ctx = QSpinBox()
        self.spin_llm_ctx.setRange(512, 131072)
        self.spin_llm_ctx.setSingleStep(256)
        self.spin_llm_ctx.setValue(ap.get_local_llm_ctx_size(self._db))
        ctx_row.addWidget(self.spin_llm_ctx)
        ctx_row.addStretch()
        app_layout.addLayout(ctx_row)

        to_row = QHBoxLayout()
        to_row.addWidget(QLabel("Local LLM timeout (seconds):"))
        self.spin_llm_timeout = QSpinBox()
        self.spin_llm_timeout.setRange(30, 3600)
        self.spin_llm_timeout.setValue(ap.get_local_llm_timeout_s(self._db))
        to_row.addWidget(self.spin_llm_timeout)
        to_row.addStretch()
        app_layout.addLayout(to_row)

        chat_row = QHBoxLayout()
        chat_row.addWidget(QLabel("Chat history render limit (messages):"))
        self.spin_chat_limit = QSpinBox()
        self.spin_chat_limit.setRange(10, 500)
        self.spin_chat_limit.setValue(ap.get_chat_history_render_limit(self._db))
        chat_row.addWidget(self.spin_chat_limit)
        chat_row.addStretch()
        app_layout.addLayout(chat_row)

        app_layout.addWidget(
            QLabel(
                "Note: changes to the runtime scheduler, local API, or Telegram take effect after you restart the app."
            )
        )
        app_layout.addStretch()
        tabs.addTab(app_tab, "App preferences")

        layout = QVBoxLayout()
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def accept(self):
        """Persist lead-gen file and app preferences."""
        try:
            from config import CONFIG_DIR
            from core import app_preferences as ap

            os.makedirs(CONFIG_DIR, exist_ok=True)
            config_path = os.path.join(CONFIG_DIR, "lead_gen_config.json")
            payload = {"system_message": (self.system_message_input.toPlainText() or "").strip()}
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

            def _tf(checked: bool) -> str:
                return "1" if checked else "0"

            self._db.set_setting(ap.KEY_RUNTIME_ENABLED, _tf(self.chk_runtime.isChecked()))
            self._db.set_setting(ap.KEY_RUNTIME_POLL_S, str(int(self.spin_runtime_poll.value())))
            self._db.set_setting(ap.KEY_RUNTIME_LEASE_S, str(int(self.spin_runtime_lease.value())))
            self._db.set_setting(ap.KEY_LOCAL_API_ENABLED, _tf(self.chk_local_api.isChecked()))
            self._db.set_setting(ap.KEY_LOCAL_API_HOST, (self.edit_api_host.text() or "").strip() or "127.0.0.1")
            self._db.set_setting(ap.KEY_LOCAL_API_PORT, str(int(self.spin_api_port.value())))
            self._db.set_setting(ap.KEY_LOCAL_API_LOG_LEVEL, self.combo_api_log.currentText().strip() or "warning")
            self._db.set_setting(ap.KEY_TELEGRAM_ENABLED, _tf(self.chk_telegram.isChecked()))
            self._db.set_setting(ap.KEY_TELEGRAM_CHAT_IDS, (self.edit_tg_chats.text() or "").strip())
            self._db.set_setting(ap.KEY_COS_PASSIVE_MEMORY, _tf(self.chk_cos_memory.isChecked()))
            self._db.set_setting(ap.KEY_COS_MAX_OUTPUT_TOKENS, str(int(self.spin_cos_out_tok.value())))
            self._db.set_setting(ap.KEY_COS_MEMORY_MAX_OUTPUT_TOKENS, str(int(self.spin_cos_mem_tok.value())))
            self._db.set_setting(ap.KEY_COS_CONTEXT_BUDGET_CHARS, str(int(self.spin_cos_budget.value())))
            self._db.set_setting(ap.KEY_COS_HISTORY_MAX_MESSAGES, str(int(self.spin_cos_hist_msg.value())))
            self._db.set_setting(ap.KEY_COS_HISTORY_MAX_CHARS, str(int(self.spin_cos_hist_chars.value())))
            self._db.set_setting(ap.KEY_COS_PREFS_MAX_CHARS, str(int(self.spin_cos_prefs.value())))
            self._db.set_setting(ap.KEY_COS_CALENDAR_MAX_CHARS, str(int(self.spin_cos_cal.value())))
            self._db.set_setting(ap.KEY_COS_MEMORY_BLOCK_MAX_CHARS, str(int(self.spin_cos_mem_block.value())))
            self._db.set_setting(ap.KEY_COS_MAX_TASK_LINES, str(int(self.spin_cos_task_lines.value())))
            self._db.set_setting(ap.KEY_COS_MAX_ASSIGNMENT_LINES, str(int(self.spin_cos_assign_lines.value())))
            self._db.set_setting(ap.KEY_COS_EMAILS_MAX_CHARS, str(int(self.spin_cos_emails.value())))
            self._db.set_setting(ap.KEY_BRIEFING_DISABLED, _tf(self.chk_briefing_off.isChecked()))
            self._db.set_setting(ap.KEY_LOCAL_LLM_GPU, str(int(self.spin_llm_gpu.value())))
            self._db.set_setting(ap.KEY_LOCAL_LLM_CTX, str(int(self.spin_llm_ctx.value())))
            self._db.set_setting(ap.KEY_LOCAL_LLM_TIMEOUT, str(int(self.spin_llm_timeout.value())))
            self._db.set_setting(ap.KEY_CHAT_HISTORY_RENDER_LIMIT, str(int(self.spin_chat_limit.value())))
        except Exception as e:
            try:
                QMessageBox.warning(self, "Save Error", f"Could not save settings:\n{e}")
            except Exception:
                pass
            return
        super().accept()

class ChatWindow(QMainWindow):
    task_added_signal = pyqtSignal(str, str)

    def __init__(self, *, defer_dashboard_initial_load: bool = False):
        super().__init__()
        self.db = DatabaseManager()
        self.chat_handler = ChatManager(self)  # Pass self (ChatWindow) to ChatManager
        self._defer_dashboard_initial_load = bool(defer_dashboard_initial_load)
        try:
            self._chat_history_render_limit = get_chat_history_render_limit(self.db)
        except Exception:
            self._chat_history_render_limit = 40
        self.todoList = QListWidget()
        self.todoList.setStyleSheet("QListWidget::item { border: none; padding: 0; }")
        self.todo_list = TodoList(self)
        self.notification_tray: QSystemTrayIcon | None = None
        self.chat_thread = None
        self._dashboard_chat_queue = deque()
        self._dashboard_chat_in_flight = False
        self.initUI()
        # Create tabs first so tasks_tab is available
        self.create_tabs()
        
        # Reuse ChatManager's ResponseHandler to avoid spawning duplicate llama_worker subprocess
        self.response_handler = self.chat_handler.response_handler
        self.chat_handler.task_added_signal.connect(self.response_handler.handle_task_added)
        
        self.load_chat_history()
        self._setup_notification_tray()
        self._toast_overlay: QLabel | None = None
        self._last_cos_task_change_serial = get_cos_task_change_serial()
        set_cos_toast_callback(lambda msg: self.show_toast(msg, duration=3000))
        set_agent_reply_toast_callback(self._on_agent_assignment_reply_toast)
        set_agent_grok_failure_toast_callback(
            lambda msg: self.show_toast(msg, color="#EF4444", duration=8000)
        )
        self._billing_autorun_worker = None
        self._init_billing_autorun_scheduler()
        self._demo_full_cycle_active = False
        self._demo_full_cycle_worker = None

    def _setup_notification_tray(self) -> None:
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                self.notification_tray = None
                return
            icon = self.windowIcon()
            if icon.isNull():
                icon = QApplication.windowIcon()
            if icon.isNull():
                icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
            self.notification_tray = QSystemTrayIcon(icon, self)
            self.notification_tray.setToolTip("NaviSsurance")
            self.notification_tray.show()
        except Exception:
            self.notification_tray = None

    def play_app_sound(self, kind: str = "complete") -> None:
        play_notification_sound(kind)

    def _on_agent_assignment_reply_toast(self, assignment_id: int | None, reply: str) -> None:
        """Toast + refresh Chief of Staff when a sub-agent replies in an assignment thread."""
        if assignment_id is None:
            return
        aid = int(assignment_id)
        text = (reply or "").strip()
        if not text or text.lower().startswith("error:"):
            return
        low = text.lower()
        if "needs input" in low or "awaiting" in low:
            self.show_toast(
                f"Agent needs input on A-{aid:04d}",
                duration=5000,
                color="#F59E0B",
            )
        else:
            self.show_toast(
                f"Agent completed work on A-{aid:04d}",
                duration=4000,
                color="#22C55E",
            )
        tab = getattr(self, "chief_of_staff_tab", None)
        if tab is not None:
            try:
                tab.refresh_proposed_assignments()
                tab._refresh_assignment_list()
            except Exception:
                pass

    def show_toast(
        self,
        message: str,
        *,
        duration: int = 3000,
        duration_ms: int | None = None,
        color: str | None = None,
    ) -> None:
        """Brief on-window toast (bottom-center overlay); also mirrors to the status bar."""
        text = str(message or "").strip()
        if not text:
            return
        ms = int(duration_ms) if duration_ms is not None else int(duration)
        try:
            self.statusBar().showMessage(text, max(500, ms))
        except Exception:
            pass
        prev = getattr(self, "_toast_overlay", None)
        if prev is not None:
            try:
                self._toast_overlay = None
                prev.deleteLater()
            except Exception:
                pass
        try:
            toast = QLabel(text, self)
            toast.setObjectName("app_toast")
            bg = (color or "#333").strip()
            toast.setStyleSheet(
                f"QLabel#app_toast {{ background-color: {bg}; color: white; padding: 10px 16px; "
                "border-radius: 6px; font-size: 13px; }}"
            )
            toast.setWordWrap(True)
            toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
            max_w = max(280, self.width() - 48)
            toast.setMaximumWidth(max_w)
            toast.adjustSize()
            sb_h = 0
            try:
                sb = self.statusBar()
                if sb is not None and sb.isVisible():
                    sb_h = sb.sizeHint().height()
            except Exception:
                sb_h = 0
            y = self.height() - toast.height() - 16 - sb_h
            x = (self.width() - toast.width()) // 2
            toast.move(max(8, x), max(8, y))
            toast.show()
            toast.raise_()
            self._toast_overlay = toast
            ms = max(500, ms)

            def _hide_toast() -> None:
                if getattr(self, "_toast_overlay", None) is not toast:
                    return
                self._toast_overlay = None
                try:
                    toast.deleteLater()
                except Exception:
                    pass

            QTimer.singleShot(ms, _hide_toast)
        except Exception:
            pass

    def notify_background_complete(self, title: str, message: str) -> None:
        self.play_app_sound("complete")
        try:
            if self.notification_tray is not None:
                self.notification_tray.showMessage(
                    title,
                    message,
                    QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
                return
        except Exception:
            pass
        try:
            self.statusBar().showMessage(f"{title}: {message}", 5000)
        except Exception:
            pass

    def notify_chat_response(self, source: str = "Navi") -> None:
        _ = source
        self.play_app_sound("chat")

    def _focus_workspace_tab(self) -> None:
        tw = getattr(self, "tab_widget", None)
        if tw is None:
            return
        for i in range(tw.count()):
            if str(tw.tabText(i) or "").strip() == "Workspace":
                tw.setCurrentIndex(i)
                return

    def _clear_demo_full_cycle_worker_slot(self) -> None:
        self._demo_full_cycle_worker = None

    def _on_demo_full_cycle_research_failed(self, msg: str) -> None:
        self._demo_full_cycle_active = False
        self.show_toast("Demo: Full Cycle failed during research.", duration=5000)
        QMessageBox.warning(self, "Demo: Full Cycle", str(msg or "Unknown error"))

    def _on_demo_full_cycle_research_done(self, brief_md: str, project_id: int) -> None:
        wt = self.workspace_tab
        try:
            wt.add_virtual_file(
                name="CEO Demo — Research Brief.md",
                content=brief_md,
                source_type="demo_full_cycle",
                source_assignment_id=int(project_id),
                source_title=DEMO_RESEARCH_NAME,
                marked=True,
                path_slug="demo_full_cycle_brief",
            )
            cb = getattr(wt, "include_task_suggestions_checkbox", None)
            if cb is not None:
                cb.setChecked(True)
            wt._demo_full_cycle_pending_assignment = True
            self._focus_workspace_tab()
            wt.run_ai_collaboration_workflow(
                initial_instructions=DEMO_WORKSPACE_PROMPT,
                prompt_source="Demo: Full Cycle",
            )
        except Exception as e:
            self._demo_full_cycle_active = False
            wt._demo_full_cycle_pending_assignment = False
            logger.exception("Demo full cycle: handoff to Workspace failed: %s", e)
            QMessageBox.critical(
                self,
                "Demo: Full Cycle",
                f"Research finished but Workspace handoff failed:\n{e}",
            )

    def run_demo_full_cycle(self) -> None:
        """Hidden dev/demo entry: Deep Research → Workspace draft → task import → sample CoS assignment."""
        if getattr(self, "_demo_full_cycle_active", False):
            QMessageBox.information(
                self,
                "Demo: Full Cycle",
                "A demo full cycle is already in progress.",
            )
            return
        wt = self.workspace_tab
        cw = getattr(wt, "_collaboration_worker", None)
        if cw is not None and cw.isRunning():
            QMessageBox.information(
                self,
                "Demo: Full Cycle",
                "Workspace is already running a draft. Wait for it to finish.",
            )
            return
        dw = getattr(self, "_demo_full_cycle_worker", None)
        if dw is not None and dw.isRunning():
            QMessageBox.information(
                self,
                "Demo: Full Cycle",
                "Deep research for the demo is already running.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Demo: Full Cycle",
            "Run the full demo chain? This uses live APIs: Deep Research (can take several minutes), "
            "then a Workspace CEO memo draft with automatic task import, then a sample Chief of Staff "
            "assignment to Atlas.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._demo_full_cycle_active = True
        self.show_toast("Demo: Full Cycle — deep research starting…", duration=5000)

        worker = DemoFullCycleResearchWorker(self.db)
        self._demo_full_cycle_worker = worker
        worker.status_message.connect(lambda m: self.show_toast(str(m), duration=6000))
        worker.finished_ok.connect(self._on_demo_full_cycle_research_done)
        worker.failed.connect(self._on_demo_full_cycle_research_failed)
        worker.finished.connect(self._clear_demo_full_cycle_worker_slot)
        worker.start()

    def _init_billing_autorun_scheduler(self) -> None:
        """
        In-app monthly billing auto-run.

        Notes:
        - When the shared runtime scheduler is available, recurring enqueue is owned by the runtime;
          the GUI timer only drains due jobs and shows review prompts (shorter interval than legacy).
        - If APScheduler is missing or runtime is disabled, this uses the older in-thread generation path.
        """
        try:
            from core.runtime.service import runtime_scheduler_available

            runtime_ok, _ = runtime_scheduler_available()
            use_runtime_tick = bool(is_runtime_enabled(self.db)) and bool(runtime_ok)

            self._billing_autorun_timer = QTimer(self)
            self._billing_autorun_timer.setInterval(
                30 * 60 * 1000 if use_runtime_tick else 6 * 60 * 60 * 1000
            )
            slot = self._billing_autorun_runtime_tick if use_runtime_tick else self._maybe_run_billing_autorun
            self._billing_autorun_timer.timeout.connect(slot)
            self._billing_autorun_timer.start()
            QTimer.singleShot(15_000, slot)
        except Exception:
            pass

    def _open_billing_tab(self) -> None:
        try:
            if hasattr(self, "tab_widget"):
                for i in range(self.tab_widget.count()):
                    if str(self.tab_widget.tabText(i) or "").strip().lower() == "billing":
                        self.tab_widget.setCurrentIndex(i)
                        return
        except Exception:
            return

    def _billing_autorun_runtime_tick(self) -> None:
        """Drain runtime jobs and surface billing review prompts; enqueue only if the scheduler never started."""
        if self._billing_autorun_worker is not None:
            return
        try:
            from datetime import date as _date
            from core.runtime.jobs import enqueue_billing_autorun
            from core.runtime.service import get_runtime_service

            today = _date.today()
            yyyymm = f"{today.year:04d}-{today.month:02d}"
            last_prompt = str(self.db.get_setting("billing.last_prompt_yyyymm", "") or "").strip()

            runtime = get_runtime_service(db=self.db)
            if not getattr(runtime, "_started", False):
                try:
                    enqueue_billing_autorun(self.db)
                except Exception:
                    pass
            try:
                runtime.process_due_jobs()
            except Exception:
                pass

            # Billing dialog: at most once per calendar month after dismiss (other jobs still drain above).
            if last_prompt == yyyymm:
                return

            try:
                pending_count = int(str(self.db.get_setting("billing.pending_review_count", "0") or "0").strip())
            except Exception:
                pending_count = 0
            pending_notes = str(self.db.get_setting("billing.pending_review_notes", "") or "").strip()
            if pending_count > 0 or pending_notes:
                try:
                    self.db.set_setting("billing.last_prompt_yyyymm", yyyymm)
                except Exception:
                    pass
                msg = pending_notes or f"{pending_count} invoice draft(s) are ready for review."
                box = QMessageBox(self)
                box.setWindowTitle("Billing")
                box.setText(msg)
                open_btn = box.addButton("Open Billing", QMessageBox.ButtonRole.AcceptRole)
                box.addButton("Dismiss", QMessageBox.ButtonRole.RejectRole)
                box.exec()
                if box.clickedButton() == open_btn:
                    self._open_billing_tab()
        except Exception:
            pass

    def _maybe_run_billing_autorun(self) -> None:
        # Avoid overlapping runs.
        if self._billing_autorun_worker is not None:
            return

        try:
            from datetime import date as _date
            from core.billing.autorun import should_autorun, run_monthly_autodraft

            today = _date.today()

            # Guard: don't re-prompt multiple times in the same month if the user dismisses.
            yyyymm = f"{today.year:04d}-{today.month:02d}"
            last_prompt = str(self.db.get_setting("billing.last_prompt_yyyymm", "") or "").strip()
            if last_prompt == yyyymm:
                return

            if not should_autorun(self.db, today=today):
                return

            class _BillingAutoRunWorker(QThread):
                finished_signal = pyqtSignal(object)  # AutoRunResult
                error_signal = pyqtSignal(str)

                def __init__(self, db):
                    super().__init__()
                    self.db = db

                def run(self):
                    try:
                        out = run_monthly_autodraft(self.db)
                        self.finished_signal.emit(out)
                    except Exception as e:
                        self.error_signal.emit(str(e))

            self._billing_autorun_worker = _BillingAutoRunWorker(self.db)

            def _on_done(result):
                self._billing_autorun_worker = None
                try:
                    # Mark that we've prompted this month (even if zero drafts).
                    self.db.set_setting("billing.last_prompt_yyyymm", yyyymm)
                except Exception:
                    pass

                try:
                    draft_ids = getattr(result, "draft_ids", []) or []
                    notes = getattr(result, "notes", "") or ""
                    if notes:
                        msg = notes
                    elif draft_ids:
                        msg = f"{len(draft_ids)} invoice draft(s) are ready for review."
                    else:
                        msg = "No invoice drafts were generated."

                    box = QMessageBox(self)
                    box.setWindowTitle("Billing")
                    box.setText(msg)
                    open_btn = box.addButton("Open Billing", QMessageBox.ButtonRole.AcceptRole)
                    box.addButton("Dismiss", QMessageBox.ButtonRole.RejectRole)
                    box.exec()
                    if box.clickedButton() == open_btn:
                        self._open_billing_tab()
                except Exception:
                    pass

            def _on_err(err: str):
                self._billing_autorun_worker = None
                try:
                    QMessageBox.warning(self, "Billing autorun error", err)
                except Exception:
                    pass

            self._billing_autorun_worker.finished_signal.connect(_on_done)
            self._billing_autorun_worker.error_signal.connect(_on_err)
            self._billing_autorun_worker.start()
        except Exception:
            self._billing_autorun_worker = None
            return

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Handle saving
            pass

    def show_help(self):
        show_help(self)

    def close(self):
        super().close()

    def addTask(self):
        # Use the dashboard tab's task input instead of missing global fields
        if hasattr(self, 'dashboard_tab') and hasattr(self.dashboard_tab, 'add_task'):
            self.dashboard_tab.add_task()
        else:
            # Fallback: show a message that tasks should be added from the dashboard
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Add Task", "Please add tasks using the task input in the Dashboard tab.")

    def focus_search(self):
        if hasattr(self.leads_tab, 'focus_search'):
            self.leads_tab.focus_search()

    def refresh_leads(self):
        if hasattr(self.leads_tab, 'refresh_leads'):
            self.leads_tab.refresh_leads()

    def initUI(self):
        self.setWindowTitle('NaviSsurance AI Assistant')
        
        # Set minimum size for responsive layout
        self.setMinimumSize(800, 600)
        
        # Use smart geometry based on screen size
        screen = QApplication.primaryScreen().geometry()
        window_width = min(1600, screen.width() - 100)  # Leave margin
        window_height = min(900, screen.height() - 100)  # Leave margin
        x = (screen.width() - window_width) // 2
        y = (screen.height() - window_height) // 2
        self.setGeometry(x, y, window_width, window_height)

        # Load the main application stylesheet
        self.loadStylesheet("styles.qss")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)  # Changed to horizontal layout
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)
        self.main_layout = main_layout
        self._main_layout_default_spacing = 6

        # Left side - Chat Panel (hidden when Chief of Staff tab is active)
        self.chat_panel = QWidget()
        self.chat_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.chat_panel.setMinimumWidth(300)
        self.chat_panel.setMaximumWidth(560)
        chat_layout = QVBoxLayout(self.chat_panel)
        chat_layout.setContentsMargins(5, 5, 5, 5)
        chat_layout.setSpacing(0)

        # Add header to match tab bar height
        chat_header = QLabel("Navi Chat")
        chat_header.setStyleSheet("""
            QLabel {
                background-color: #15171c;
                color: #e8eaed;
                padding: 8px 12px;
                font-size: 13px;
                font-weight: 600;
                border-bottom: 1px solid #2e2f32;
            }
        """)
        chat_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chat_layout.addWidget(chat_header)

        self.chat_display = QTextBrowser()
        self.chat_display.setOpenExternalLinks(True)
        self.chat_display.setReadOnly(True)
        self.chat_display.document().setDocumentMargin(0)
        chat_layout.addWidget(self.chat_display)

        # Add spacing between chat display and input area
        chat_layout.addSpacing(5)

        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(5)
        
        self.chat_input = ChatEntryEdit(min_lines=2, max_lines=7)
        self.chat_input.setPlaceholderText("Type your message… (Enter to send, Shift+Enter for new line)")
        self.chat_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.chat_input.returnPressed.connect(self.sendMessage)
        self.chat_input.setStyleSheet(
            "QTextEdit { background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; border-radius: 6px; padding: 8px 10px; font-size: 13px; }"
        )
        input_layout.addWidget(self.chat_input, 1)

        self.send_button = QPushButton('Send')
        self.send_button.clicked.connect(self.sendMessage)
        input_layout.addWidget(self.send_button)

        chat_layout.addLayout(input_layout)
        chat_layout.addSpacing(4)
        
        # Use proper stretch factors instead of fixed percentages
        main_layout.addWidget(self.chat_panel, 1)  # Chat panel gets 1/4 of space

        # Right side - Tab Widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setUsesScrollButtons(True)
        self.tab_widget.tabBar().setExpanding(False)
        self.tab_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(self.tab_widget, 3)  # Tabs get 3/4 of space
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        setup_shortcuts(self)
        setup_status_bar(self)

        memory_menu = self.menuBar().addMenu("Memory")
        view_mem_action = QAction("View Memories", self)
        view_mem_action.triggered.connect(self.open_memory_viewer)
        memory_menu.addAction(view_mem_action)

    def open_memory_viewer(self):
        dialog = MemoryViewerDialog(self)
        dialog.exec()

    def create_tabs(self):
        """Create and add all tabs after the chat handler is fully initialized."""
        logger.info("Creating tabs...")
        self.dashboard_tab = DashboardTab(
            self.chat_handler,
            self.todo_list,
            self.db,
            self,
            defer_initial_loads=self._defer_dashboard_initial_load,
        )
        self.tab_widget.addTab(self.dashboard_tab, "Dashboard")
        logger.info("Dashboard tab added")
        
        # Try to create Tasks tab - handle errors gracefully
        logger.info(f"TASKS_TAB_AVAILABLE={TASKS_TAB_AVAILABLE}, TasksTab={TasksTab}")
        if TASKS_TAB_AVAILABLE and TasksTab is not None:
            try:
                logger.info("Attempting to create TasksTab...")
                self.tasks_tab = TasksTab(self)
                self.tab_widget.addTab(self.tasks_tab, "Tasks")
                logger.info("Tasks tab added successfully")
            except Exception as e:
                logger.error(f"Failed to create Tasks tab: {e}", exc_info=True)
                # Create a placeholder tab with error message
                error_widget = QWidget()
                error_layout = QVBoxLayout()
                error_label = QLabel(f"Tasks tab unavailable:\n{str(e)}")
                error_label.setWordWrap(True)
                error_layout.addWidget(error_label)
                error_widget.setLayout(error_layout)
                self.tab_widget.addTab(error_widget, "Tasks (Error)")
                logger.info("Tasks error tab added")
        else:
            # TasksTab import failed - create placeholder
            logger.warning("TasksTab not available, creating error placeholder")
            error_widget = QWidget()
            error_layout = QVBoxLayout()
            error_label = QLabel("Tasks tab unavailable: TasksTab could not be imported.\nCheck logs for details.")
            error_label.setWordWrap(True)
            error_layout.addWidget(error_label)
            error_widget.setLayout(error_layout)
            self.tab_widget.addTab(error_widget, "Tasks (Error)")
            logger.info("Tasks error placeholder tab added")
        
        self.workspace_tab = WorkspaceTab(self.db, self.chat_handler)
        self.tab_widget.addTab(self.workspace_tab, "Workspace")
        
        self.deep_research_tab = DeepResearchTab(
            self.db,
            workspace_tab=self.workspace_tab,
            main_tab_widget=self.tab_widget,
        )
        self.tab_widget.addTab(self.deep_research_tab, "Deep Research")
        # Backward-compat attribute name (some routing/tests used `projects_tab`)
        self.projects_tab = self.deep_research_tab
        
        self.compliance_tab = ComplianceTab(self.db, self.chat_handler)
        self.tab_widget.addTab(self.compliance_tab, "Compliance")
        
        self.meetings_tab = MeetingsTab(self.chat_handler)
        self.tab_widget.addTab(self.meetings_tab, "Meetings")
        
        self.leads_tab = LeadsTab(self.chat_handler, 'data', self)
        self.tab_widget.addTab(self.leads_tab, "Leads")

        self.billing_tab = BillingTab(self.db, parent=self)
        self.tab_widget.addTab(self.billing_tab, "Billing")

        self.library_tab = AgentTab(
            self.db,
            agent_code="archive",
            heading="Library — Archive",
            subtitle="Search and retrieval workspace for institutional knowledge.",
            parent=self,
        )
        self.tab_widget.addTab(self.library_tab, "Library")

        self.intel_tab = AgentTab(
            self.db,
            agent_code="pulse",
            heading="Intel — Pulse",
            subtitle="Market intelligence and competitor signal tracking.",
            parent=self,
        )
        self.tab_widget.addTab(self.intel_tab, "Intel")

        self.security_tab = AgentTab(
            self.db,
            agent_code="shield",
            heading="Security — Shield",
            subtitle="Security and privacy risk triage.",
            parent=self,
        )
        self.tab_widget.addTab(self.security_tab, "Security")

        self.team_tab = TeamDirectoryTab(self.db, self)
        self.tab_widget.addTab(self.team_tab, "Team")
        
        self.notes_tab = NoteTakingSystem(self.chat_handler)
        self.tab_widget.addTab(self.notes_tab, "Notes")
        
        self.clients_tab = ClientsTab(self.db, self)
        self.tab_widget.addTab(self.clients_tab, "Clients")

        self.chief_of_staff_tab = ChiefOfStaffTab(self.db, self)
        self.tab_widget.addTab(self.chief_of_staff_tab, "Chief of Staff")
        self._on_tab_changed(self.tab_widget.currentIndex())  # Apply visibility for initial tab

    def _on_tab_changed(self, index):
        """Hide Navi chat panel when Chief of Staff tab is active; show it for other tabs."""
        tab_name = self.tab_widget.tabText(index) if index >= 0 else ""
        self._apply_host_shell_mode(tab_name == "Chief of Staff")

    def _apply_host_shell_mode(self, chief_of_staff_active: bool) -> None:
        if chief_of_staff_active:
            self.chat_panel.hide()
            self.main_layout.setSpacing(0)
            self.main_layout.setStretch(0, 0)
            self.main_layout.setStretch(1, 1)
            self.tab_widget.setStyleSheet("")
        else:
            self.chat_panel.show()
            self.main_layout.setSpacing(self._main_layout_default_spacing)
            self.main_layout.setStretch(0, 1)
            self.main_layout.setStretch(1, 3)

    def _get_dashboard_cos_chat_id(self) -> int:
        """Return a stable cos_chat id used by the Dashboard chat panel."""
        try:
            existing = self.db.get_setting("cos_dashboard_chat_id", "") if hasattr(self.db, "get_setting") else ""
            if existing:
                try:
                    cid = int(str(existing).strip())
                    if cid > 0:
                        return cid
                except Exception:
                    pass
        except Exception:
            pass

        # Create a chat record and persist it.
        cid = self.db.cos_create_chat(title="Dashboard", project=None)
        try:
            if hasattr(self.db, "set_setting"):
                self.db.set_setting("cos_dashboard_chat_id", str(cid))
        except Exception:
            pass
        return cid

    def _dashboard_session_id(self) -> str:
        return f"cos_{self._get_dashboard_cos_chat_id()}"

    def _scroll_chat_to_bottom(self):
        try:
            scrollbar = self.chat_display.verticalScrollBar()
            QTimer.singleShot(0, lambda: scrollbar.setValue(scrollbar.maximum()))
        except Exception:
            pass

    def _update_dashboard_send_button(self) -> None:
        queued = len(self._dashboard_chat_queue)
        if queued > 0:
            self.send_button.setText(f"Send ({queued} queued)")
        else:
            self.send_button.setText("Send")

    def _start_next_dashboard_chat_message(self) -> None:
        if self._dashboard_chat_in_flight or not self._dashboard_chat_queue:
            self._update_dashboard_send_button()
            return

        message = str(self._dashboard_chat_queue.popleft() or "").strip()
        if not message:
            self._update_dashboard_send_button()
            QTimer.singleShot(0, self._start_next_dashboard_chat_message)
            return

        session_id = self._dashboard_session_id()
        try:
            self.db.save_message(session_id, "user", message)
        except Exception:
            pass

        history = []
        try:
            history = self.db.get_chat_history(session_id, limit=50)
        except Exception:
            history = []

        self._dashboard_chat_in_flight = True
        self.chat_thread = ChatThread(self.chat_handler, message, session_id, history)
        self.chat_thread.response_signal.connect(self.handle_response)
        self.chat_thread.start()
        self._update_dashboard_send_button()

    def sendMessage(self):
        message = (self.chat_input.toPlainText() or "").strip()
        if message:
            safe = html.escape(message).replace("\n", "<br>")
            self.chat_display.append(f"<b>You:</b> {safe}<br>")
            self._scroll_chat_to_bottom()
            self.chat_input.clear()
            try:
                self.chat_input._update_height()
            except Exception:
                pass

            self._dashboard_chat_queue.append(message)
            self._update_dashboard_send_button()
            self._start_next_dashboard_chat_message()

    def handle_response(self, response):
        # Use thread-safe UI update
        QTimer.singleShot(0, lambda: self._handle_response_safe(response))

    def _format_chat_response_html(self, response: str) -> str:
        """
        Format assistant text for readable chat rendering.
        Handles markdown and common one-line LLM outputs that contain headings/bullets.
        """
        text = str(response or "")
        if not text.strip():
            return ""

        # If model returns a long single-line "markdown-like" response, recover structure.
        if (
            "\n" not in text
            and "###" in text
            and len(re.findall(r"\|\s*\d{2}-\d{2}-\d{4}\s*\|\s*(Business|Personal)\b", text, re.IGNORECASE)) >= 2
        ):
            # Separate headings and list bullets for markdown parser.
            text = re.sub(r"\s+(#{1,6}\s)", r"\n\n\1", text)
            text = re.sub(r"\s-\s(?=[A-Za-z0-9])", r"\n- ", text)

        # Render markdown into HTML for QTextBrowser.
        html = markdown.markdown(text, extensions=["extra", "nl2br", "sane_lists"])
        return html or text.replace("\n", "<br>")
    
    def _handle_response_safe(self, response):
        """Thread-safe version of handle_response."""
        self._dashboard_chat_in_flight = False
        self.chat_thread = None
        rendered = self._format_chat_response_html(response) if isinstance(response, str) else str(response)
        self.chat_display.append(f"<b>Navi:</b> {rendered}<br>")
        self._scroll_chat_to_bottom()
        if isinstance(response, str) and not is_user_facing_llm_failure_message(response):
            self.notify_chat_response("Navi")
        # If Navi changed tasks via CoS chat, refresh task views immediately.
        try:
            current_task_change_serial = get_cos_task_change_serial()
            if current_task_change_serial > int(getattr(self, "_last_cos_task_change_serial", 0)):
                self._last_cos_task_change_serial = current_task_change_serial
                if hasattr(self, "dashboard_tab") and hasattr(self.dashboard_tab, "load_tasks_filtered"):
                    QTimer.singleShot(0, self.dashboard_tab.load_tasks_filtered)
                if hasattr(self, "tasks_tab") and hasattr(self.tasks_tab, "refresh_tasks"):
                    QTimer.singleShot(0, self.tasks_tab.refresh_tasks)
        except Exception:
            pass
        self._update_dashboard_send_button()
        QTimer.singleShot(0, self._start_next_dashboard_chat_message)

    def load_chat_history(self):
        # Load Dashboard chat history from the persistent CoS session.
        session_id = self._dashboard_session_id()
        history = self.db.get_chat_history(session_id, limit=self._chat_history_render_limit)
        for role, message in history:
            label = "You" if role == "user" else "Navi"
            if role == "assistant":
                rendered = self._format_chat_response_html(str(message or ""))
                self.chat_display.append(f"<b>{label}:</b> {rendered}<br>")
            else:
                self.chat_display.append(f"<b>{label}:</b> {message}<br>")
        self._scroll_chat_to_bottom()

    def closeEvent(self, event):
        if hasattr(self, "deep_research_tab") and hasattr(self.deep_research_tab, "save_state"):
            self.deep_research_tab.save_state()
        self.db.close()
        super().closeEvent(event)

    def loadStylesheet(self, filename):
        try:
            with open(filename, "r", encoding='utf-8') as f:
                self.setStyleSheet(f.read())
        except FileNotFoundError:
            print(f"Stylesheet {filename} not found.")
        except Exception as e:
            print(f"Error loading stylesheet: {str(e)}")

    def load_dashboard_news(self):
        """Load news feed for the dashboard."""
        try:
            # Use the same intelligent news query approach as the chat system
            news_query_prompt = [{"role": "user", "content": "Create a query for up-to-date MedTech news within the past 7 days, focused on AI/ML, IVDs, SaMD, DTC devices."}]
            
            # Get the AI-generated query first
            news_query = self.chat_handler.get_response(
                f"WEB_SEARCH:{news_query_prompt[0]['content']}", 
                session_id="dashboard_news_query", 
                conversation_history=[]
            )
            
            # Clean up the query if it contains WEB_SEARCH: prefix
            if "WEB_SEARCH:" in news_query:
                news_query = news_query.split("WEB_SEARCH:")[1].strip()
            else:
                # Fallback to a good default if AI query fails
                news_query = "latest MedTech news AI ML IVD SaMD medical device regulatory FDA within past 7 days"
            
            # Now search with the refined query
            news_results = self.chat_handler.get_response(
                f"WEB_SEARCH:{news_query}", 
                session_id="dashboard_news", 
                conversation_history=[]
            )
            
            if news_results and "WEB_SEARCH:" not in news_results:
                # Process and store news results
                self.process_and_store_news(news_results)
                
                # Display stored news with hyperlinks
                self.display_stored_news()
            else:
                # If no new results, just display stored news
                self.display_stored_news()
                
        except Exception as e:
            print(f"Error loading news: {str(e)}")

    def load_dashboard_schedule(self):
        """Load schedule for the dashboard."""
        try:
            # Check if we have access to calendar data
            if hasattr(self.chat_handler, 'data_fetcher'):
                data_fetcher = self.chat_handler.data_fetcher
            elif hasattr(self.chat_handler, 'chat_handler') and hasattr(self.chat_handler.chat_handler, 'data_fetcher'):
                data_fetcher = self.chat_handler.chat_handler.data_fetcher
            else:
                print("No data_fetcher found in chat_handler")
                return
            
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow = today + timedelta(days=1)
            time_min = today.strftime('%Y-%m-%dT%H:%M:%SZ')
            time_max = tomorrow.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            events = data_fetcher.get_calendar_events(time_min, time_max)
            
            if events:
                schedule_html = "<div style='font-family: Segoe UI, Arial, sans-serif; color: #e8eaed;'>"
                schedule_html += "<h3 style='color: #6b8cae; margin-bottom: 8px;'>Today's Events</h3><ul style='list-style-type: none; padding: 0;'>"
                for event in events:
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    if isinstance(start, str):
                        try:
                            parsed = parser.parse(start)
                            if 'T' in start:
                                start_time = parsed.strftime('%I:%M %p')
                            else:
                                start_time = 'All Day - ' + parsed.strftime('%b %d')
                        except:
                            start_time = start  # Fallback
                    else:
                        start_time = 'Unknown time'
                    summary = event.get('summary', 'No title')
                    schedule_html += f"<li style='margin-bottom: 10px;'><b>{start_time}:</b> {summary}</li>"
                schedule_html += "</ul>"
                schedule_html += "</div>"
                print(f"Schedule loaded: {len(events)} events")
            else:
                schedule_html = "<div style='color: #e8eaed;'>No events scheduled for today</div>"
                print("No events found")
        except Exception as e:
            schedule_html = f"<div style='color: #e8eaed;'>Error loading schedule: {str(e)}</div>"
            print(f"Error loading schedule: {str(e)}")

    def process_and_store_news(self, news_results):
        """Process news results and store them in the database, avoiding duplicates."""
        try:
            # Split news results into individual items (assuming they're separated by newlines or other delimiters)
            news_items = news_results.split('\n\n')  # Split by double newlines
            
            for item in news_items:
                if item.strip():
                    # Extract title and content (this is a simplified approach)
                    lines = item.strip().split('\n')
                    if len(lines) >= 2:
                        title = lines[0].strip()
                        content = '\n'.join(lines[1:]).strip()
                        
                        # Try to extract URL if present (look for http/https links)
                        url = None
                        source = None
                        published_date = None
                        
                        # Look for URLs in the content
                        url_match = re.search(r'https?://[^\s]+', content)
                        if url_match:
                            url = url_match.group(0)
                            # Remove the URL from content for cleaner display
                            content = re.sub(r'https?://[^\s]+', '', content).strip()
                        
                        # Check if this news item already exists
                        if not self.db.check_news_exists(title, url):
                            # Store the news item
                            self.db.store_news_item(title, content, url, source, published_date)
                            
        except Exception as e:
            print(f"Error processing news: {e}")

    def display_stored_news(self):
        """Display stored news items with hyperlinks."""
        try:
            # Get recent news from database
            recent_news = self.db.get_recent_news(days=7)
            
            if recent_news:
                news_text = "<div style='color: #e8eaed; font-family: Segoe UI, Arial, sans-serif;'>"
                news_text += "<h3 style='color: #6b8cae; margin-bottom: 15px;'>Latest News</h3>"
                
                for title, content, url, source, published_date, created_at in recent_news:
                    news_text += "<div style='margin-bottom: 20px; padding: 12px; background-color: #22252c; border: 1px solid #2e2f32; border-radius: 6px;'>"
                    news_text += f"<h4 style='color: #e8eaed; margin: 0 0 8px 0; font-size: 13px;'>{title}</h4>"
                    if content:
                        news_text += f"<p style='margin: 0 0 8px 0; line-height: 1.5; color: #9aa0a6;'>{content}</p>"
                    if url:
                        news_text += f'<p style="margin: 0 0 5px 0;"><a href="{url}" style="color: #6b8cae; text-decoration: underline;">🔗 Read full article</a></p>'
                    if published_date:
                        news_text += f"<small style='color: #5f6368;'>Published: {published_date}</small>"
                    news_text += "</div>"
                
                news_text += "</div>"
                print(f"News displayed: {len(recent_news)} items")
            else:
                news_text = "<div style='color: #e8eaed;'>No recent news available</div>"
                print("No news items found")
        except Exception as e:
            news_text = f"<div style='color: #e8eaed;'>Error displaying news: {str(e)}</div>"
            print(f"Error displaying news: {str(e)}")

    def refresh_news_feed(self):
        """Refresh the news feed."""
        self.load_dashboard_news()
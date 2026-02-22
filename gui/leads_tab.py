from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QCheckBox,
    QMessageBox,
    QLabel,
    QComboBox,
    QSpinBox,
    QDialog,
    QTextBrowser,
    QApplication,
    QTextEdit,
    QLineEdit,
)
from PyQt6.QtCore import Qt, QUrl, QThread, pyqtSignal
import os
import json
import requests
import logging
import re
from PyQt6.QtGui import QColor

# Setup logging (centralized in main.py)
logger = logging.getLogger(__name__)
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QHeaderView
from datetime import datetime

def robust_json_parse_array(response_text, logger=None):
    """
    Robust JSON parsing for arrays that handles various API response formats.
    
    Args:
        response_text: Raw response text from API
        logger: Optional logger for debug messages
    
    Returns:
        tuple: (parsed_json_array, success_flag)
    """
    def _log(msg: str) -> None:
        if logger is None:
            print(msg)
            return
        if callable(logger):
            logger(msg)
            return
        if hasattr(logger, "info"):
            try:
                logger.info(msg)
                return
            except Exception:
                pass
        print(msg)
    
    # Step 1: Try direct JSON parsing first
    try:
        clean_response = response_text.strip()
        data = json.loads(clean_response)
        if isinstance(data, list):
            _log("Direct JSON array parsing successful")
            return data, True
    except json.JSONDecodeError:
        _log("Direct JSON array parsing failed, attempting extraction...")
    
    # Step 2: Try extracting JSON from markdown code blocks
    try:
        # Look for ```json...``` blocks
        json_pattern = r'```(?:json)?\s*(\[.*?\])\s*```'
        match = re.search(json_pattern, response_text, re.DOTALL | re.IGNORECASE)
        if match:
            json_str = match.group(1).strip()
            data = json.loads(json_str)
            if isinstance(data, list):
                _log("JSON array extraction from code block successful")
                return data, True
    except (json.JSONDecodeError, AttributeError):
        _log("Code block array extraction failed")
    
    # Step 3: Try regex extraction of JSON array
    try:
        # Look for first complete JSON array
        json_pattern = r'\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]'
        match = re.search(json_pattern, response_text, re.DOTALL)
        if match:
            json_str = match.group(0).strip()
            data = json.loads(json_str)
            if isinstance(data, list):
                _log("Regex JSON array extraction successful")
                return data, True
    except (json.JSONDecodeError, AttributeError):
        _log("Regex array extraction failed")
    
    # Step 4: Try finding array boundaries manually
    try:
        start_idx = response_text.find('[')
        end_idx = response_text.rfind(']')
        
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = response_text[start_idx:end_idx + 1].strip()
            
            # Clean up common issues
            json_str = json_str.replace('```json', '').replace('```', '')
            json_str = re.sub(r',\s*]', ']', json_str)  # Remove trailing commas
            json_str = re.sub(r'\s+', ' ', json_str)   # Normalize whitespace
            
            data = json.loads(json_str)
            if isinstance(data, list):
                _log("Manual array extraction successful")
                return data, True
    except (json.JSONDecodeError, AttributeError):
        _log("Manual array extraction failed")
    
    _log("All JSON array parsing attempts failed")
    return None, False


class _LeadsSearchWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(int)  # stored count
    error = pyqtSignal(str)

    def __init__(self, *, db, data_dir: str, user_system_message: str):
        super().__init__()
        self._db = db
        self._data_dir = data_dir
        self._user_system_message = (user_system_message or "").strip()

    @staticmethod
    def _friendly_error(e: Exception) -> str:
        s = str(e)
        sl = s.lower()
        if "deadline_exceeded" in sl or "deadline exceeded" in sl:
            return "Grok request timed out (deadline exceeded). Please try again."
        if "api key" in sl or "not set" in sl:
            return "Grok API key is missing or not configured (XAI_API_KEY / GROK_API_KEY)."
        return f"Lead search failed: {type(e).__name__}: {s}"

    def run(self):
        try:
            if self._db is None:
                self.error.emit("Database is not available; cannot store leads.")
                return

            from core.grok_client import grok_available, grok_web_search, grok_completion, MODEL_WEB

            ok, msg = grok_available()
            if not ok:
                self.error.emit(msg or "Grok is not available.")
                return

            user_system_message = self._user_system_message or (
                "You are a lead generation assistant for a medical device regulatory consulting firm. "
                "Focus on companies in the AI SaMD and/or IVD/LDT space."
            )

            # Two-pass pipeline:
            # A) Discover candidate leads (verifiable, but minimal fields)
            # B) Verify/enrich: tighten evidence, add personalized message, incorporate openFDA signals
            discover_prompt = f"""{user_system_message}

Use web search to find *verifiable* leads. Only include leads where you found evidence in sources.

Return ONLY a JSON array of 8-20 CANDIDATE leads. Each lead object must include:
- name
- company
- title
- rationale
- linkedin_url (or empty string)
- company_url (or empty string)
- sources: [url1, url2] (must have at least 1)

Optional:
- signals: ["signal 1", "signal 2"]

Hard rules:
- Do not invent people, titles, or URLs.
- If you can’t find sources for a lead, omit it.
"""

            self.progress.emit("Searching for candidate leads (web)…")
            response_content = ""
            try:
                response_content = grok_web_search(
                    discover_prompt,
                    model=MODEL_WEB,
                    timeout=900,
                    retries=0,
                )
            except Exception:
                response_content = ""

            if not response_content:
                self.progress.emit("Searching for candidate leads (fallback)…")
                try:
                    response_content = grok_completion(
                        system="You are a lead generation assistant. Return only JSON as instructed.",
                        user=discover_prompt,
                        model=MODEL_WEB,
                    )
                except Exception as e:
                    self.error.emit(self._friendly_error(e))
                    return

            if not response_content:
                self.error.emit("Grok returned no content (check XAI_API_KEY / GROK_API_KEY).")
                return

            # Persist raw response for debugging (best-effort)
            try:
                os.makedirs(self._data_dir, exist_ok=True)
                response_file = os.path.join(self._data_dir, "grok_response.txt")
                with open(response_file, "w", encoding="utf-8") as f:
                    f.write("Response content:\n")
                    f.write(response_content + "\n")
            except Exception:
                pass

            self.progress.emit("Parsing candidate leads…")
            candidates, success = robust_json_parse_array(response_content, logger)
            if not success or not isinstance(candidates, list) or not candidates:
                self.error.emit("No JSON array of candidate leads found in response.")
                return

            # Enrich with openFDA signals before verification pass
            self.progress.emit("Enriching candidates with openFDA signals…")
            enriched_candidates = []
            try:
                from core.openfda import search_510k_by_applicant, summarize_510k_records
            except Exception:
                search_510k_by_applicant = None
                summarize_510k_records = None

            for idx, lead in enumerate(candidates[:50], start=1):
                if not isinstance(lead, dict):
                    continue
                if not all(k in lead for k in ["name", "company", "title", "rationale"]):
                    continue

                sources = lead.get("sources") or []
                if not isinstance(sources, list):
                    sources = []
                if len(sources) == 0:
                    continue

                lead.setdefault("signals", [])
                lead.setdefault("linkedin_url", "")
                lead.setdefault("company_url", "")
                lead.setdefault("status", "new")
                lead.setdefault("contacted", False)
                lead.setdefault("contact_date", None)
                lead.setdefault("next_action_date", None)
                lead.setdefault("notes", "")

                company = str(lead.get("company") or "").strip()
                if company and search_510k_by_applicant and summarize_510k_records:
                    try:
                        self.progress.emit(f"openFDA lookup ({idx}/{min(len(candidates),50)}): {company}")
                        recs, req_url = search_510k_by_applicant(company, limit=5)
                        summ = summarize_510k_records(company, recs, req_url)
                        lead["signals"] = list(
                            dict.fromkeys((lead.get("signals") or []) + (summ.get("signals") or []))
                        )
                        lead["sources"] = list(
                            dict.fromkeys((lead.get("sources") or []) + (summ.get("sources") or []))
                        )
                        lead["openfda_meta"] = summ.get("meta") or {}
                    except Exception:
                        pass

                enriched_candidates.append(lead)

            self.progress.emit("Verifying and enriching final leads (web)…")
            verify_prompt = f"""{user_system_message}

You will be given a JSON array of candidate leads (with some sources and possible openFDA signals).

Task:
- Verify each lead is real and current using web search.
- Keep only leads with strong evidence.
- Produce a FINAL JSON array of up to 15 leads with:
  - name, company, title, rationale, linkedin_url, company_url
  - signals: [..]
  - sources: [..] (must have at least 2 when possible; never empty)
  - message: personalized LinkedIn message (2-5 sentences) referencing a specific signal and offering help

Hard rules:
- Do not invent. If not verifiable, omit the lead.
- Return ONLY the JSON array.

Candidates JSON:
{json.dumps(enriched_candidates, ensure_ascii=False)}
"""

            final_text = ""
            try:
                final_text = grok_web_search(
                    verify_prompt,
                    model=MODEL_WEB,
                    timeout=900,
                    retries=0,
                )
            except Exception:
                final_text = ""
            if not final_text:
                self.progress.emit("Verifying and enriching final leads (fallback)…")
                try:
                    final_text = grok_completion(
                        system="You are a lead generation assistant. Return only JSON as instructed.",
                        user=verify_prompt,
                        model=MODEL_WEB,
                    )
                except Exception as e:
                    self.error.emit(self._friendly_error(e))
                    return

            final_leads = []
            if final_text:
                final_leads, ok2 = robust_json_parse_array(final_text, logger)
                if not ok2 or not isinstance(final_leads, list):
                    final_leads = []

            try:
                from core.lead_scoring import score_lead
            except Exception:
                score_lead = None

            self.progress.emit("Storing leads…")
            stored = 0
            for lead in (final_leads or []):
                if not isinstance(lead, dict):
                    continue
                if not all(k in lead for k in ["name", "company", "title", "rationale", "message"]):
                    continue
                sources = lead.get("sources") or []
                if not isinstance(sources, list) or len(sources) == 0:
                    continue

                lead.setdefault("signals", [])
                lead.setdefault("linkedin_url", "")
                lead.setdefault("company_url", "")
                lead.setdefault("status", "new")
                lead.setdefault("contacted", False)
                lead.setdefault("contact_date", None)
                lead.setdefault("next_action_date", None)
                lead.setdefault("notes", "")

                if score_lead:
                    try:
                        lead.update(score_lead(lead))
                    except Exception:
                        pass
                try:
                    self._db.upsert_lead(lead)
                    stored += 1
                except Exception:
                    continue

            self.finished.emit(int(stored))
        except Exception as e:
            self.error.emit(self._friendly_error(e))

class LeadsTab(QWidget):
    def __init__(self, chat_handler, data_dir, parent=None):
        super().__init__()
        self.chat_handler = chat_handler
        self.data_dir = data_dir
        self.parent = parent
        self._search_worker: _LeadsSearchWorker | None = None
        # Prefer the app's DatabaseManager (ChatWindow.db) if available.
        try:
            if self.parent is not None and hasattr(self.parent, "db"):
                self.db = self.parent.db
            else:
                from core.db import DatabaseManager
                self.db = DatabaseManager()
        except Exception:
            self.db = None
        self.setup_ui()

    class _HtmlDialog(QDialog):
        def __init__(self, parent, title: str, html: str):
            super().__init__(parent)
            self.setWindowTitle(title)
            layout = QVBoxLayout(self)
            view = QTextBrowser(self)
            view.setOpenExternalLinks(True)
            view.setHtml(html)
            layout.addWidget(view)
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(self.accept)
            btn_row.addWidget(close_btn)
            layout.addLayout(btn_row)

    class _EditLeadDialog(QDialog):
        def __init__(self, parent, lead: dict):
            super().__init__(parent)
            self.setWindowTitle("Edit Lead")
            self._lead = lead

            layout = QVBoxLayout(self)
            layout.addWidget(QLabel(f"{lead.get('name','')} — {lead.get('company','')}"))

            row1 = QHBoxLayout()
            row1.addWidget(QLabel("Status:"))
            self.status = QComboBox()
            self.status.addItems(["new", "contacted", "nurturing", "disqualified"])
            cur = (lead.get("status") or "new").strip()
            if cur in {"new", "contacted", "nurturing", "disqualified"}:
                self.status.setCurrentText(cur)
            row1.addWidget(self.status)
            row1.addStretch()
            layout.addLayout(row1)

            row2 = QHBoxLayout()
            row2.addWidget(QLabel("Next action (YYYY-MM-DD):"))
            self.next_action = QLineEdit()
            self.next_action.setPlaceholderText("e.g. 2026-02-28")
            self.next_action.setText(lead.get("next_action_date") or "")
            row2.addWidget(self.next_action)
            layout.addLayout(row2)

            layout.addWidget(QLabel("Notes:"))
            self.notes = QTextEdit()
            self.notes.setPlainText(lead.get("notes") or "")
            self.notes.setMinimumHeight(120)
            layout.addWidget(self.notes)

            btns = QHBoxLayout()
            btns.addStretch()
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(self.reject)
            save_btn = QPushButton("Save")
            save_btn.clicked.connect(self.accept)
            btns.addWidget(cancel_btn)
            btns.addWidget(save_btn)
            layout.addLayout(btns)

        def values(self) -> dict:
            return {
                "status": (self.status.currentText() or "new").strip(),
                "next_action_date": (self.next_action.text() or "").strip() or None,
                "notes": (self.notes.toPlainText() or "").strip(),
            }

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        leads_button_layout = QHBoxLayout()
        self.settingsButton = QPushButton("Settings", self)
        if self.parent and hasattr(self.parent, 'open_settings'):
            self.settingsButton.clicked.connect(self.parent.open_settings)
        else:
            self.settingsButton.clicked.connect(self.open_settings)  # Fallback or define if needed
        self.settingsButton.setToolTip("Open application settings (Ctrl+,)")
        leads_button_layout.addWidget(self.settingsButton)
        
        self.runSearchButton = QPushButton("Run Search", self)
        self.runSearchButton.clicked.connect(self.search_leads)
        self.runSearchButton.setToolTip("Search for new leads (F5)")
        leads_button_layout.addWidget(self.runSearchButton)

        self.refreshButton = QPushButton("Refresh", self)
        self.refreshButton.clicked.connect(self.refresh_leads)
        leads_button_layout.addWidget(self.refreshButton)
        
        layout.addLayout(leads_button_layout)

        # Lightweight status line for long-running searches
        self.search_status_label = QLabel("")
        self.search_status_label.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        layout.addWidget(self.search_status_label)

        # Filters (DB-backed)
        filters_layout = QHBoxLayout()
        filters_layout.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "new", "contacted", "nurturing", "disqualified"])
        self.status_filter.currentTextChanged.connect(self.refresh_leads)
        filters_layout.addWidget(self.status_filter)

        filters_layout.addWidget(QLabel("Min score:"))
        self.min_score_filter = QSpinBox()
        self.min_score_filter.setRange(0, 999)
        self.min_score_filter.setValue(0)
        self.min_score_filter.valueChanged.connect(self.refresh_leads)
        filters_layout.addWidget(self.min_score_filter)

        self.hide_contacted = QCheckBox("Hide contacted")
        self.hide_contacted.stateChanged.connect(self.refresh_leads)
        filters_layout.addWidget(self.hide_contacted)

        filters_layout.addStretch()
        layout.addLayout(filters_layout)
        
        # Configure the leads table
        self.leadsTable = QTableWidget(0, 14)
        self.leadsTable.setHorizontalHeaderLabels([
            "Name",
            "Company",
            "Title",
            "Score",
            "Status",
            "Contacted",
            "Contact Date",
            "Next Action",
            "Message",
            "Sources",
            "Follow-up Task",
            "Edit",
            "Delete",
            "Rationale",
        ])
        
        # Set column widths and behavior
        self.leadsTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.leadsTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.leadsTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.leadsTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.leadsTable.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.leadsTable.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.leadsTable.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.leadsTable.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.leadsTable.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self.leadsTable.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)
        self.leadsTable.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeMode.Fixed)
        self.leadsTable.horizontalHeader().setSectionResizeMode(11, QHeaderView.ResizeMode.Fixed)
        self.leadsTable.horizontalHeader().setSectionResizeMode(12, QHeaderView.ResizeMode.Fixed)
        self.leadsTable.horizontalHeader().setSectionResizeMode(13, QHeaderView.ResizeMode.Stretch)
        
        self.leadsTable.setColumnWidth(3, 65)
        self.leadsTable.setColumnWidth(5, 80)
        self.leadsTable.setColumnWidth(6, 100)
        self.leadsTable.setColumnWidth(7, 95)
        self.leadsTable.setColumnWidth(8, 120)
        self.leadsTable.setColumnWidth(9, 90)
        self.leadsTable.setColumnWidth(10, 110)
        self.leadsTable.setColumnWidth(11, 70)
        self.leadsTable.setColumnWidth(12, 70)
        
        self.leadsTable.setWordWrap(True)
        self.leadsTable.setSortingEnabled(True)
        layout.addWidget(self.leadsTable)

        self.leadsTable.cellClicked.connect(self.on_cell_clicked)
        self.refresh_leads()

    def _maybe_import_legacy_json(self):
        """Best-effort import of legacy data/leads.json into SQLite if DB is empty."""
        if not self.db:
            return
        try:
            if self.db.list_leads(limit=1):
                return
        except Exception:
            return

        leads_file = os.path.join(self.data_dir, "leads.json")
        if not os.path.exists(leads_file):
            return
        try:
            with open(leads_file, "r", encoding="utf-8") as f:
                leads = json.load(f)
            if not isinstance(leads, list):
                return
            for lead in leads:
                if not isinstance(lead, dict):
                    continue
                lead.setdefault("sources", [])
                lead.setdefault("signals", [])
                try:
                    self.db.upsert_lead(lead)
                except Exception:
                    continue
        except Exception:
            return

    def refresh_leads(self):
        """Reload leads from SQLite using current filter settings."""
        if not self.db:
            return

        self._maybe_import_legacy_json()

        status = self.status_filter.currentText()
        if status == "All":
            status = None
        min_score = int(self.min_score_filter.value() or 0)
        contacted = 0 if self.hide_contacted.isChecked() else None

        try:
            leads = self.db.list_leads(status=status, contacted=contacted, min_score=min_score, limit=500)
        except Exception as e:
            logger.error(f"Error loading leads: {e}")
            leads = []
        self.update_leads_table(leads)

    def search_leads(self):
        """Run lead search in a background thread (non-blocking)."""
        if self._search_worker is not None and self._search_worker.isRunning():
            return
        if not self.db:
            QMessageBox.warning(self, "Leads", "Database is not available; cannot run lead search.")
            return

        def _set_tab_title(title: str) -> None:
            try:
                tw = getattr(self.parent, "tab_widget", None)
                if tw is None:
                    return
                idx = tw.indexOf(self)
                if idx >= 0:
                    tw.setTabText(idx, title)
            except Exception:
                return

        def _status(msg: str, timeout_ms: int = 15000) -> None:
            try:
                from gui.utils import update_status
                if self.parent is not None:
                    update_status(self.parent, msg, timeout=timeout_ms)
            except Exception:
                return

        # Load system message from config (quick; keep on UI thread)
        user_system_message = ""
        try:
            from config import CONFIG_DIR
            config_path = os.path.join(CONFIG_DIR, "lead_gen_config.json")
            config = {}
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            user_system_message = (config.get("system_message") or "").strip()
            if not user_system_message:
                user_system_message = (
                    "You are a lead generation assistant for a medical device regulatory consulting firm. "
                    "Focus on companies in the AI SaMD and/or IVD/LDT space."
                )
                # Best-effort: create a default config file so the UI works out of the box.
                try:
                    os.makedirs(CONFIG_DIR, exist_ok=True)
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump({"system_message": user_system_message}, f, indent=2)
                except Exception:
                    pass
        except Exception:
            user_system_message = (
                "You are a lead generation assistant for a medical device regulatory consulting firm. "
                "Focus on companies in the AI SaMD and/or IVD/LDT space."
            )

        self.runSearchButton.setEnabled(False)
        self.refreshButton.setEnabled(False)
        self.search_status_label.setText("Searching…")
        _set_tab_title("Leads (searching…)")  # visible even if user switches tabs
        _status("Lead search started…", timeout_ms=8000)

        self._search_worker = _LeadsSearchWorker(
            db=self.db,
            data_dir=self.data_dir,
            user_system_message=user_system_message,
        )
        self._search_worker.progress.connect(self.search_status_label.setText)

        def _on_done(stored: int):
            self.runSearchButton.setEnabled(True)
            self.refreshButton.setEnabled(True)
            self.search_status_label.setText(f"Stored {stored} lead(s).")
            _set_tab_title("Leads (done)")
            _status(f"Lead search finished: stored {stored} lead(s).", timeout_ms=20000)
            self.refresh_leads()
            try:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(20000, lambda: _set_tab_title("Leads"))
            except Exception:
                pass

        def _on_err(msg: str):
            self.runSearchButton.setEnabled(True)
            self.refreshButton.setEnabled(True)
            self.search_status_label.setText("Lead search failed.")
            _set_tab_title("Leads")
            _status("Lead search failed (see dialog).", timeout_ms=20000)
            QMessageBox.warning(self, "Lead Search", msg or "Lead search failed.")

        self._search_worker.finished.connect(_on_done)
        self._search_worker.error.connect(_on_err)
        self._search_worker.start()

    def update_leads_table(self, leads):
        self.leadsTable.setRowCount(len(leads))
        for row, lead in enumerate(leads):
            self.leadsTable.setRowHeight(row, 40)

            lead_id = lead.get("id")

            name_item = QTableWidgetItem(lead.get('name', ''))
            name_item.setData(Qt.ItemDataRole.UserRole + 2, lead_id)
            if lead.get('linkedin_url'):
                name_item.setData(Qt.ItemDataRole.UserRole, lead.get('linkedin_url', ''))
                name_item.setForeground(QColor("#0077B5"))
            self.leadsTable.setItem(row, 0, name_item)

            self.leadsTable.setItem(row, 1, QTableWidgetItem(lead.get('company', '')))
            self.leadsTable.setItem(row, 2, QTableWidgetItem(lead.get('title', '')))

            score = int(lead.get("total_score", 0) or 0)
            score_item = QTableWidgetItem(str(score))
            score_item.setData(Qt.ItemDataRole.EditRole, score)
            self.leadsTable.setItem(row, 3, score_item)

            self.leadsTable.setItem(row, 4, QTableWidgetItem(lead.get("status", "new")))

            contacted_checkbox = QCheckBox()
            contacted_checkbox.setChecked(bool(lead.get('contacted', False)))
            contacted_checkbox.stateChanged.connect(
                lambda state, lid=lead_id: self.toggle_contacted_by_id(lid, state == Qt.CheckState.Checked.value)
            )
            self.leadsTable.setCellWidget(row, 5, contacted_checkbox)

            self.leadsTable.setItem(row, 6, QTableWidgetItem(lead.get('contact_date', '') or ''))
            self.leadsTable.setItem(row, 7, QTableWidgetItem(lead.get('next_action_date', '') or ''))

            message_btn = QPushButton("View Message")
            message_btn.clicked.connect(lambda _, msg=lead.get('message', ''): self.show_message_dialog(msg))
            self.leadsTable.setCellWidget(row, 8, message_btn)

            sources_btn = QPushButton("Sources")
            sources_btn.clicked.connect(lambda _, l=lead: self.show_sources_dialog(l))
            self.leadsTable.setCellWidget(row, 9, sources_btn)

            task_btn = QPushButton("Create Task")
            task_btn.clicked.connect(lambda _, l=lead: self.create_followup_task(l))
            self.leadsTable.setCellWidget(row, 10, task_btn)

            edit_btn = QPushButton("Edit")
            edit_btn.clicked.connect(lambda _, l=lead: self.edit_lead(l))
            self.leadsTable.setCellWidget(row, 11, edit_btn)

            delete_btn = QPushButton("Delete")
            delete_btn.clicked.connect(lambda _, lid=lead_id: self.delete_lead_by_id(lid))
            self.leadsTable.setCellWidget(row, 12, delete_btn)

            rationale_item = QTableWidgetItem(lead.get('rationale', ''))
            rationale_item.setToolTip(lead.get('rationale', ''))
            self.leadsTable.setItem(row, 13, rationale_item)

    def on_cell_clicked(self, row, column):
        if column == 0:
            item = self.leadsTable.item(row, column)
            url = item.data(Qt.ItemDataRole.UserRole)
            if url:
                QDesktopServices.openUrl(QUrl(url))

    def toggle_contacted_by_id(self, lead_id, checked: bool):
        if not self.db or lead_id is None:
            return
        try:
            self.db.set_lead_contacted(int(lead_id), bool(checked))
        except Exception as e:
            logger.error(f"Failed to update lead contacted state: {e}")
        self.refresh_leads()

    def show_message_dialog(self, message):
        msg = QMessageBox(self)
        msg.setWindowTitle("LinkedIn Message")
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Copy)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ret = msg.exec()
        if ret == QMessageBox.StandardButton.Copy:
            try:
                QApplication.clipboard().setText(message or "")
            except Exception:
                pass

    def delete_lead_by_id(self, lead_id):
        if not self.db or lead_id is None:
            return
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            "Are you sure you want to delete this lead?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.delete_lead_by_id(int(lead_id))
        except Exception as e:
            logger.error(f"Failed to delete lead: {e}")
        self.refresh_leads()

    def show_sources_dialog(self, lead: dict):
        sources = lead.get("sources") or []
        signals = lead.get("signals") or []
        html = "<div style='font-family: Segoe UI, Arial; font-size: 12px;'>"
        html += f"<h3>{lead.get('name','')} — {lead.get('company','')}</h3>"
        if signals:
            html += "<b>Signals</b><ul>"
            for s in signals[:20]:
                html += f"<li>{str(s)}</li>"
            html += "</ul>"
        if sources:
            html += "<b>Sources</b><ul>"
            for u in sources[:30]:
                uu = str(u)
                html += f"<li><a href='{uu}'>{uu}</a></li>"
            html += "</ul>"
        else:
            html += "<p><i>No sources stored.</i></p>"
        html += "</div>"
        dlg = self._HtmlDialog(self, "Lead Evidence", html)
        dlg.resize(720, 520)
        dlg.exec()

    def edit_lead(self, lead: dict):
        if not self.db:
            return
        dlg = self._EditLeadDialog(self, lead)
        dlg.resize(640, 420)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.values()
        lead_id = lead.get("id")
        if lead_id is None:
            return
        try:
            self.db.update_lead_by_id(
                int(lead_id),
                status=vals.get("status"),
                next_action_date=vals.get("next_action_date"),
                notes=vals.get("notes"),
            )
        except Exception as e:
            logger.error(f"Failed updating lead: {e}")
        self.refresh_leads()

    def create_followup_task(self, lead: dict):
        """
        Create a local task to do outreach/follow-up.
        LinkedIn DM sending is not automated here; this is the scheduling hook.
        """
        if not self.db:
            return
        name = (lead.get("name") or "").strip()
        company = (lead.get("company") or "").strip()
        if not name or not company:
            return

        # Tasks table expects MM-dd-YYYY in several UI paths; keep consistent.
        due_iso = (lead.get("next_action_date") or "").strip()
        try:
            if due_iso:
                dt = datetime.strptime(due_iso[:10], "%Y-%m-%d").date()
            else:
                dt = datetime.now().date()
        except Exception:
            dt = datetime.now().date()
        # Default: 2 days from now if no next_action_date
        if not due_iso:
            from datetime import timedelta
            dt = dt + timedelta(days=2)
            due_iso = dt.isoformat()

        due_mmddyyyy = dt.strftime("%m-%d-%Y")
        task_text = f"Lead gen: reach out to {name} at {company} (LinkedIn)"
        try:
            self.db.add_task("lead_gen", task_text, due_mmddyyyy, category="Business")
            # Keep lead's next_action_date in sync (ISO)
            lead_id = lead.get("id")
            if lead_id is not None:
                self.db.update_lead_by_id(int(lead_id), next_action_date=due_iso)
        except Exception as e:
            logger.error(f"Failed creating follow-up task: {e}")
            return
        self.refresh_leads()

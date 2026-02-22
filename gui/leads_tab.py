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
)
from PyQt6.QtCore import Qt, QUrl
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
    if logger is None:
        logger = print  # Fallback to print for debug messages
    
    # Step 1: Try direct JSON parsing first
    try:
        clean_response = response_text.strip()
        data = json.loads(clean_response)
        if isinstance(data, list):
            logger(f"Direct JSON array parsing successful")
            return data, True
    except json.JSONDecodeError:
        logger(f"Direct JSON array parsing failed, attempting extraction...")
    
    # Step 2: Try extracting JSON from markdown code blocks
    try:
        # Look for ```json...``` blocks
        json_pattern = r'```(?:json)?\s*(\[.*?\])\s*```'
        match = re.search(json_pattern, response_text, re.DOTALL | re.IGNORECASE)
        if match:
            json_str = match.group(1).strip()
            data = json.loads(json_str)
            if isinstance(data, list):
                logger(f"JSON array extraction from code block successful")
                return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Code block array extraction failed")
    
    # Step 3: Try regex extraction of JSON array
    try:
        # Look for first complete JSON array
        json_pattern = r'\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]'
        match = re.search(json_pattern, response_text, re.DOTALL)
        if match:
            json_str = match.group(0).strip()
            data = json.loads(json_str)
            if isinstance(data, list):
                logger(f"Regex JSON array extraction successful")
                return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Regex array extraction failed")
    
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
                logger(f"Manual array extraction successful")
                return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Manual array extraction failed")
    
    logger(f"All JSON array parsing attempts failed")
    return None, False

class LeadsTab(QWidget):
    def __init__(self, chat_handler, data_dir, parent=None):
        super().__init__()
        self.chat_handler = chat_handler
        self.data_dir = data_dir
        self.parent = parent
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
        self.leadsTable = QTableWidget(0, 12)
        self.leadsTable.setHorizontalHeaderLabels([
            "Name", "Company", "Title", "Score", "Status", "Contacted", "Contact Date", "Next Action", "Message", "Sources", "Delete", "Rationale"
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
        self.leadsTable.horizontalHeader().setSectionResizeMode(11, QHeaderView.ResizeMode.Stretch)
        
        self.leadsTable.setColumnWidth(3, 65)
        self.leadsTable.setColumnWidth(5, 80)
        self.leadsTable.setColumnWidth(6, 100)
        self.leadsTable.setColumnWidth(7, 95)
        self.leadsTable.setColumnWidth(8, 120)
        self.leadsTable.setColumnWidth(9, 90)
        self.leadsTable.setColumnWidth(10, 70)
        
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
        """Run Grok API search for leads based on system message."""
        try:
            # Load system message from config
            from config import CONFIG_DIR
            config_path = os.path.join(CONFIG_DIR, "lead_gen_config.json")
            config = {}
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

            user_system_message = (config.get('system_message') or "").strip()
            
            if not user_system_message:
                user_system_message = "You are a lead generation assistant for a medical device regulatory consulting firm. Focus on companies in the AI SaMD and/or IVD/LDT space."
                # Best-effort: create a default config file so the UI works out of the box.
                try:
                    os.makedirs(CONFIG_DIR, exist_ok=True)
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump({"system_message": user_system_message}, f, indent=2)
                except Exception:
                    pass

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
- signals: [\"signal 1\", \"signal 2\"]

Hard rules:
- Do not invent people, titles, or URLs.
- If you can’t find sources for a lead, omit it.
"""

            response_content = ""
            try:
                from core.grok_client import grok_available, grok_web_search, grok_completion, MODEL_WEB
                ok, msg = grok_available()
                if not ok:
                    logger.error(msg)
                    return
                try:
                    response_content = grok_web_search(discover_prompt, model=MODEL_WEB)
                except Exception:
                    response_content = ""
                if not response_content:
                    # Fallback without web_search tool
                    response_content = grok_completion(
                        system="You are a lead generation assistant. Return only JSON as instructed.",
                        user=discover_prompt,
                        model=MODEL_WEB,
                    )
            except Exception as e:
                logger.error(f"Grok lead generation failed: {e}")
                response_content = ""

            if not response_content:
                logger.error("Grok API returned no content (check XAI_API_KEY or GROK_API_KEY).")
                return

            logger.info("Grok API Response:")
            logger.info(f"Response content: {response_content}")

            response_file = os.path.join(self.data_dir, 'grok_response.txt')
            with open(response_file, 'w', encoding='utf-8') as f:
                f.write("Response content:\n")
                f.write(response_content + "\n")
            logger.info(f"Raw response written to {response_file}")

            # Use robust JSON parsing for leads array (candidates)
            candidates, success = robust_json_parse_array(response_content, logger)
            
            if success and candidates:
                logger.info(f"Parsed leads: {candidates}")

                if isinstance(candidates, list):
                    logger.info(f"Successfully parsed JSON array with {len(candidates)} candidate leads")

                    # Enrich with openFDA signals before verification pass
                    enriched_candidates = []
                    try:
                        from core.openfda import search_510k_by_applicant, summarize_510k_records
                    except Exception:
                        search_510k_by_applicant = None
                        summarize_510k_records = None

                    for lead in candidates:
                        if not isinstance(lead, dict):
                            continue
                        if not all(k in lead for k in ['name', 'company', 'title', 'rationale']):
                            logger.warning(f"Skipping lead with missing required fields: {lead}")
                            continue

                        sources = lead.get("sources") or []
                        if not isinstance(sources, list):
                            sources = []
                        # Enforce evidence: no sources, no lead.
                        if len(sources) == 0:
                            logger.warning(f"Skipping unverifiable lead (no sources): {lead.get('name')} @ {lead.get('company')}")
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
                                recs, req_url = search_510k_by_applicant(company, limit=5)
                                summ = summarize_510k_records(company, recs, req_url)
                                # Merge signals and sources (dedup)
                                lead["signals"] = list(dict.fromkeys((lead.get("signals") or []) + (summ.get("signals") or [])))
                                lead["sources"] = list(dict.fromkeys((lead.get("sources") or []) + (summ.get("sources") or [])))
                                lead["openfda_meta"] = summ.get("meta") or {}
                            except Exception:
                                pass

                        enriched_candidates.append(lead)

                    # Verification / enrichment pass: add message + tighten evidence
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
                        from core.grok_client import grok_web_search, MODEL_WEB
                        final_text = grok_web_search(verify_prompt, model=MODEL_WEB)
                    except Exception:
                        final_text = ""
                    if not final_text:
                        try:
                            from core.grok_client import grok_completion, MODEL_WEB
                            final_text = grok_completion(
                                system="You are a lead generation assistant. Return only JSON as instructed.",
                                user=verify_prompt,
                                model=MODEL_WEB,
                            )
                        except Exception:
                            final_text = ""

                    final_leads = []
                    if final_text:
                        final_leads, ok2 = robust_json_parse_array(final_text, logger)
                        if not ok2 or not isinstance(final_leads, list):
                            final_leads = []

                    stored = 0
                    try:
                        from core.lead_scoring import score_lead
                    except Exception:
                        score_lead = None

                    for lead in (final_leads or []):
                        if not isinstance(lead, dict):
                            continue
                        if not all(k in lead for k in ['name', 'company', 'title', 'rationale', 'message']):
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
                            lead.update(score_lead(lead))

                        if self.db:
                            try:
                                self.db.upsert_lead(lead)
                                stored += 1
                            except Exception as e:
                                logger.warning(f"Failed to store lead: {e}")
                                continue

                    self.refresh_leads()
                    logger.info(f"Stored {stored} leads")
                    return
            else:
                logger.error("No JSON array found in response")
                logger.error(f"Raw response: {response_content[:500]}...")  # Truncate for logging
        except Exception as e:
            logger.error(f"Search leads error: {e}")
            QMessageBox.warning(self, "API Error", "The Grok API is currently experiencing issues. Please try again in a few minutes.")

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

            delete_btn = QPushButton("Delete")
            delete_btn.clicked.connect(lambda _, lid=lead_id: self.delete_lead_by_id(lid))
            self.leadsTable.setCellWidget(row, 10, delete_btn)

            rationale_item = QTableWidgetItem(lead.get('rationale', ''))
            rationale_item.setToolTip(lead.get('rationale', ''))
            self.leadsTable.setItem(row, 11, rationale_item)

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

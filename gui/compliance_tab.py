from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QListWidget, QTextEdit, QProgressBar, QMenu, QFileDialog, QMessageBox, QGroupBox
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from core.compliance import ComplianceChecker
import os
import json
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QSplitter
from gui.agent_console import AgentConsole
from docx import Document

class ComplianceThread(QThread):
    result_signal = pyqtSignal(dict)

    def __init__(self, checker, ref_items, assess_items, session_id, conversation_history):
        super().__init__()
        self.checker = checker
        self.ref_items = ref_items
        self.assess_items = assess_items
        self.session_id = session_id
        self.conversation_history = conversation_history

    def run(self):
        try:
            result = self.checker.check_compliance(self.ref_items, self.assess_items, self.session_id, self.conversation_history)
            # The checker already returns the final result envelope.
            self.result_signal.emit(result)
        except Exception as e:
            self.result_signal.emit({"success": False, "error": str(e)})

class ComplianceTab(QWidget):
    """Compliance / Security surface.
    Phase 2 (Intelligence & Coordination): cross-linked to Phase 1 Document Memory (VERIFIED COMPLETE; Load from Document Memory button)
    + to Pulse/Intel (Load from Pulse (Raised Intel) button). Strengthens Security/Compliance surface
    with real historical work + live raised regulatory/market findings for the LLM checker.
    (Tab wired in main UI + agent routing; delivers cross-intel/ops value per roadmap.)
    """
    def __init__(self, db, chat_handler, session_id: str = "compliance_session", conversation_history=None):
        super().__init__()
        self.db = db
        self.chat_handler = chat_handler
        self.session_id = session_id
        self.conversation_history = conversation_history or []
        self.data_dir = 'data'
        os.makedirs(self.data_dir, exist_ok=True)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)
        layout.addWidget(splitter)
        
        # Column 1: Reference Documents
        ref_widget = QWidget()
        ref_layout = QVBoxLayout(ref_widget)
        ref_label = QLabel("Reference Documents (Regulations/Standards)")
        ref_layout.addWidget(ref_label)
        
        self.ref_url_input = QLineEdit()
        self.ref_url_input.setPlaceholderText("Enter URL (e.g., https://www.ecfr.gov/21-cfr-820.3)")
        self.ref_url_input.returnPressed.connect(self.add_ref_url)
        ref_layout.addWidget(self.ref_url_input)
        
        ref_upload_btn = QPushButton("Upload Reference")
        ref_upload_btn.clicked.connect(self.upload_ref_file)
        ref_layout.addWidget(ref_upload_btn)
        
        self.ref_list = QListWidget()
        self.ref_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ref_list.customContextMenuRequested.connect(self.show_ref_context_menu)
        ref_layout.addWidget(self.ref_list)
        splitter.addWidget(ref_widget)
        
        # Column 2: Documents to Assess
        assess_widget = QWidget()
        assess_layout = QVBoxLayout(assess_widget)
        assess_label = QLabel("Documents to Assess (e.g., SOPs)")
        assess_layout.addWidget(assess_label)
        
        self.assess_url_input = QLineEdit()
        self.assess_url_input.setPlaceholderText("Enter URL (e.g., https://navisure.com/sop.pdf)")
        self.assess_url_input.returnPressed.connect(self.add_assess_url)
        assess_layout.addWidget(self.assess_url_input)
        
        assess_upload_btn = QPushButton("Upload Document")
        assess_upload_btn.clicked.connect(self.upload_assess_file)
        assess_layout.addWidget(assess_upload_btn)

        # Phase 2 (Intelligence & Compliance cross-link): smallest addition to begin strengthening the
        # Security/Compliance surface with Phase 1 retrieval. Loads client-aware past docs directly
        # into assess list (no new architecture, leverages existing load_document_records + QInput).
        load_retrieval_btn = QPushButton("Load from Document Memory")
        load_retrieval_btn.setToolTip("Pull relevant past work (by client hint) from the unified Phase 1 retrieval store into the assess list. Strengthens compliance checks with your real archive.")
        load_retrieval_btn.clicked.connect(self.load_assess_from_retrieval)
        assess_layout.addWidget(load_retrieval_btn)

        # Phase 2 incremental (Intelligence & Coordination): second smallest cross-link. Pulls raised
        # Pulse/Intel findings (regulatory signals from background monitoring + model judgment) directly
        # into the assess list for the Compliance LLM checker. Strengthens the Security/Compliance
        # surface and closes the intel -> compliance loop without new storage or architecture.
        load_pulse_btn = QPushButton("Load from Pulse (Raised Intel)")
        load_pulse_btn.setToolTip("Append raised Pulse findings (titles + summaries) as assess items. Feeds live regulatory/market intel from Phase 2 Pulse maturation into compliance checks. (🛡️ [Security-Relevant] ones also route to Shield tab for privacy triage)")
        load_pulse_btn.clicked.connect(self.load_assess_from_pulse)
        assess_layout.addWidget(load_pulse_btn)

        view_intel_btn = QPushButton("View in Intel")
        view_intel_btn.setStyleSheet("font-size: 10px;")
        view_intel_btn.setToolTip("Open Intel tab (with any active project/client context from here). Security-relevant items route to Shield too.")
        view_intel_btn.clicked.connect(lambda: hasattr(self.parent(), 'focus_intel_tab') and self.parent().focus_intel_tab() or None)
        assess_layout.addWidget(view_intel_btn)
        
        self.assess_list = QListWidget()
        self.assess_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.assess_list.customContextMenuRequested.connect(self.show_assess_context_menu)
        assess_layout.addWidget(self.assess_list)
        splitter.addWidget(assess_widget)
        
        # Column 3: Results
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_label = QLabel("Compliance Results")
        results_layout.addWidget(results_label)
        
        self.results_text = QTextEdit()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate mode
        self.progress_bar.hide()
        results_layout.addWidget(self.progress_bar)
        self.results_text.setReadOnly(True)
        results_layout.addWidget(self.results_text)
        
        run_btn = QPushButton("Run Compliance Check")
        run_btn.clicked.connect(self.run_compliance_check)
        results_layout.addWidget(run_btn)
        
        save_btn = QPushButton("Save Report")
        save_btn.clicked.connect(self.save_compliance_report)
        results_layout.addWidget(save_btn)
        
        clear_dataset_btn = QPushButton("Clear Dataset")
        clear_dataset_btn.clicked.connect(self.clear_dataset)
        results_layout.addWidget(clear_dataset_btn)
        
        crm_btn = QPushButton("Link to CRM")
        crm_btn.clicked.connect(self.link_to_crm)
        results_layout.addWidget(crm_btn)
        splitter.addWidget(results_widget)

        # Proportions: results wider than inputs
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([320, 320, 640])

        self.sentinel_chat_group = QGroupBox("Direct chat with Sentinel (QA & Compliance) — 🛡️ security via Shield/Pulse")
        self.sentinel_chat_group.setCheckable(True)
        self.sentinel_chat_group.setChecked(False)
        sentinel_chat_layout = QVBoxLayout(self.sentinel_chat_group)
        self.sentinel_console = AgentConsole(self.db, agent_code="sentinel", parent=self)
        self.sentinel_console.setVisible(False)
        sentinel_chat_layout.addWidget(self.sentinel_console)
        self.sentinel_chat_group.toggled.connect(
            lambda checked: self.sentinel_console.setVisible(bool(checked))
        )
        layout.addWidget(self.sentinel_chat_group)

        self.lex_chat_group = QGroupBox("Direct chat with Lex (Contracts & Privacy/Security Specialist)")
        self.lex_chat_group.setCheckable(True)
        self.lex_chat_group.setChecked(False)
        lex_chat_layout = QVBoxLayout(self.lex_chat_group)
        self.lex_console = AgentConsole(self.db, agent_code="lex", parent=self)
        self.lex_console.setVisible(False)
        lex_chat_layout.addWidget(self.lex_console)
        self.lex_chat_group.toggled.connect(
            lambda checked: self.lex_console.setVisible(bool(checked))
        )
        layout.addWidget(self.lex_chat_group)
        
        # Load existing documents
        self.load_document_lists()

    def add_ref_url(self):
        url = self.ref_url_input.text().strip()
        if url:
            self.ref_list.addItem(url)
            self.save_document_lists()
            self.ref_url_input.clear()

    def upload_ref_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Reference File", "", "Documents (*.pdf *.docx *.txt);;All Files (*)"
        )
        if file_path:
            self.ref_list.addItem(file_path)
            self.save_document_lists()
            try:
                if self.db is not None and hasattr(self.db, "store_dataset_entry"):
                    self.db.store_dataset_entry(file_path)
            except Exception:
                pass

    def add_assess_url(self):
        url = self.assess_url_input.text().strip()
        if url:
            self.assess_list.addItem(url)
            self.save_document_lists()
            self.assess_url_input.clear()

    def upload_assess_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Document to Assess", "", "Documents (*.pdf *.docx *.txt);;All Files (*)"
        )
        if file_path:
            self.assess_list.addItem(file_path)
            self.save_document_lists()
            try:
                if self.db is not None and hasattr(self.db, "store_dataset_entry"):
                    self.db.store_dataset_entry(file_path)
            except Exception:
                pass

    def load_assess_from_retrieval(self):
        """Phase 2 (Intelligence & Coordination, COMPLETE): wire Compliance surface to Phase 1 Document Memory (VERIFIED COMPLETE).
        Prompts for client/doc hint, loads up to 8 records, adds their names/paths to assess list.
        Makes the existing Compliance tab immediately more valuable by reusing real indexed work
        (cross-link between Memory foundation and Security/Compliance layer). Pulse load path also blends Phase1 docs.
        """
        from PyQt6.QtWidgets import QInputDialog
        hint, ok = QInputDialog.getText(self, "Load from Retrieval", "Client or doc-type hint (e.g. Overjet, SOP, FDA):")
        if not ok or not hint.strip():
            return
        try:
            from core.file_handler import get_relevant_past_documents  # Phase 1 robust primitive (complete, incl. Client Dossier surface) for consistency across CoS/Workspace/Pulse/Compliance
            recs = get_relevant_past_documents(client_hint=hint.strip(), query=hint.strip(), limit=8) or []
            if not recs:
                recs = get_relevant_past_documents(limit=5) or []
            added = 0
            existing = {self.assess_list.item(i).text() for i in range(self.assess_list.count())}  # dedup (F7 fix)
            for r in recs[:8]:
                label = getattr(r, 'name', '') or getattr(r, 'source_path', '') or str(r)
                if label and label not in existing:
                    self.assess_list.addItem(label)
                    existing.add(label)
                    added += 1
            if added:
                self.save_document_lists()
            QMessageBox.information(self, "Retrieval Load", f"Added {added} items from Document Memory for hint '{hint}' (using Phase 1 scored retrieval).\n\nCompliance checks now use the same robust 'Relevant Past Work' logic as CoS/Workspace/Pulse.")
        except Exception as e:
            QMessageBox.warning(self, "Retrieval Error", f"Could not load from Document Memory: {e}")

    def load_assess_from_pulse(self):
        """Phase 2 (Intelligence & Coordination, matured): cross-link raised Pulse findings into Compliance.
        Pulls up to 8 currently-raised Intel findings (from background monitoring + matured raising logic using Phase1 terms),
        + auto-blends relevant historical docs from Phase 1 retrieval. Appends to assess list for LLM checker.
        Strengthens cross-surface (Intel <-> Compliance <-> Memory). Reuses existing patterns, tiniest safe increment.
        """
        from PyQt6.QtWidgets import QMessageBox
        try:
            from core.intel import IntelService
            intel = IntelService(self.db)
            findings = intel.list_findings(raised_only=True, limit=8) or []
            added = 0
            existing = {self.assess_list.item(i).text() for i in range(self.assess_list.count())}  # dedup across Pulse + retrieval blend (F7)
            for f in findings[:8]:
                title = getattr(f, "title", "") or ""
                summary = getattr(f, "summary", "") or ""
                label = f"{title} | {summary[:90]}".strip(" |")
                if label and label not in existing:
                    self.assess_list.addItem(label)
                    existing.add(label)
                    added += 1
            # Wire Pulse private memory themes into Compliance "Load from Pulse" (stronger cross-linking: themes now flow to compliance work)
            try:
                from core.intel import IntelService
                intel = IntelService(self.db)
                refs = intel.get_recent_pulse_reflections(limit=3)
                for r in refs:
                    c = str(r.get("content", ""))[:80].strip()
                    if c:
                        label = f"[Pulse Theme] {c}"
                        if label not in existing:
                            self.assess_list.addItem(label)
                            existing.add(label)
                            added += 1
            except Exception:
                pass
            # Phase 2 (Intelligence & Coordination) high-leverage: blend Phase 1 retrieval docs into Pulse->Compliance cross-link (Phase 1 now fully closed)
            # Reuses get_relevant_past_documents (regulatory boost) so compliance checks get real historical context automatically.
            try:
                from core.file_handler import get_relevant_past_documents
                extra_docs = get_relevant_past_documents(query="compliance regulatory risk audit dhf rmf", limit=3) or []
                for d in extra_docs:
                    dn = getattr(d, 'name', '') or ''
                    dt = getattr(d, 'doc_type', '') or ''
                    if dn:
                        label = f"[HIST REF from Phase1] {dn} | {dt}"
                        if label not in existing:
                            self.assess_list.addItem(label)
                            existing.add(label)
                            added += 1
            except Exception as e:
                print(f"[Compliance] Phase 1 retrieval blend for Pulse load skipped (non-fatal): {e}")  # improved observability (F5)
            if added:
                self.save_document_lists()
            QMessageBox.information(
                self, "Pulse Load",
                f"Added {added} raised Pulse findings (+ historical refs + private regulatory themes) to assess list.\n\n"
                "Compliance checks can now incorporate live intel from Pulse + Phase 1 memory + Pulse private themes (Phase 2 Intelligence cross-link)."
            )
        except Exception as e:
            QMessageBox.warning(self, "Pulse Load Error", f"Could not load from Pulse: {e}")

    def save_document_lists(self):
        ref_items = [self.ref_list.item(i).text() for i in range(self.ref_list.count())]
        assess_items = [self.assess_list.item(i).text() for i in range(self.assess_list.count())]
        data = {
            "reference_documents": ref_items,
            "assessed_documents": assess_items
        }
        config_path = os.path.join(self.data_dir, "compliance_documents.json")
        with open(config_path, "w") as f:
            json.dump(data, f, indent=2)

    def load_document_lists(self):
        config_path = os.path.join(self.data_dir, "compliance_documents.json")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = json.load(f)
            for item in data.get("reference_documents", []):
                self.ref_list.addItem(item)
            for item in data.get("assessed_documents", []):
                self.assess_list.addItem(item)

    def show_ref_context_menu(self, position):
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.ref_list.mapToGlobal(position))
        if action == remove_action:
            item = self.ref_list.itemAt(position)
            if item:
                self.ref_list.takeItem(self.ref_list.row(item))
                self.save_document_lists()

    def show_assess_context_menu(self, position):
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.assess_list.mapToGlobal(position))
        if action == remove_action:
            item = self.assess_list.itemAt(position)
            if item:
                self.assess_list.takeItem(self.assess_list.row(item))
                self.save_document_lists()

    def run_compliance_check(self):
        ref_items = [self.ref_list.item(i).text() for i in range(self.ref_list.count())]
        assess_items = [self.assess_list.item(i).text() for i in range(self.assess_list.count())]
        
        if not ref_items or not assess_items:
            self.results_text.setText("Error: Add at least one reference and assessed document.")
            return
        
        self.progress_bar.show()
        self.results_text.setText("Running compliance check...")
        run_btn = self.sender()
        run_btn.setEnabled(False)
        
        self.compliance_thread = ComplianceThread(
            ComplianceChecker(self.chat_handler), ref_items, assess_items, self.session_id, self.conversation_history
        )
        self.compliance_thread.result_signal.connect(self.on_compliance_complete)
        self.compliance_thread.start()

    def on_compliance_complete(self, result):
        # Use thread-safe UI update
        QTimer.singleShot(0, lambda: self._on_compliance_complete_safe(result))
    
    def _on_compliance_complete_safe(self, result):
        """Thread-safe version of on_compliance_complete."""
        self.progress_bar.hide()
        if result["success"]:
            data = result["data"]
            raw_response = str(result.get("raw_response") or "").strip()
            formatted_results = []
            
            if 'overview' in data and data['overview'].strip():
                overview = data['overview'].strip().replace('\n', '<br>')
                formatted_results.append(f"<b>Overview:</b><br>{overview}<br><br>")
            
            if 'key_alignments' in data and data['key_alignments'].strip():
                alignments = data['key_alignments'].strip().replace('\n', '<br>')
                formatted_results.append(f"<b>Key Alignments:</b><br>{alignments}<br><br>")
            
            if 'improvements' in data:
                for r in data['improvements']:
                    issue = r['issue'].strip().replace('\n', '<br>')
                    fix = r['fix'].strip().replace('\n', '<br>')
                    ref = r['reference'].strip().replace('\n', '<br>')
                    formatted_results.append(
                        f"<b>Section {r['section']}:</b> {issue}<br>"
                        f"<b>Fix:</b> {fix}<br>"
                        f"<b>Reference:</b> {ref}<br><br>"
                    )
            
            if 'recommendations' in data and data['recommendations'].strip():
                recs = data['recommendations'].strip().replace('\n', '<br>')
                formatted_results.append(f"<b>Recommendations:</b><br>{recs}<br><br>")
            
            if formatted_results:
                formatted_results.append("<br><b>🛡️ Shield:</b> Security/privacy items from Pulse loads are best triaged in the dedicated Security tab.")
                self.results_text.setHtml("".join(formatted_results))
            else:
                if raw_response:
                    self.results_text.setPlainText(
                        "Compliance check returned no structured sections.\n\n"
                        "Raw response:\n"
                        f"{raw_response}"
                    )
                else:
                    self.results_text.setText("No results found.")
        else:
            self.results_text.setText(f"Error: {result['error']}")

    def save_compliance_report(self):
        if not self.results_text.toPlainText():
            self.results_text.setText("No results to save.")
            return
        timestamp = QDate.currentDate().toString("yyyyMMdd")
        default_filename = f"compliance_report_{timestamp}.txt"
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Compliance Report",
            default_filename,
            "Text Files (*.txt);;Word Documents (*.docx);;All Files (*)"
        )
        if file_path:
            try:
                plain_text = self.results_text.toPlainText()
                is_docx = file_path.lower().endswith(".docx") or "docx" in (selected_filter or "").lower()
                if is_docx:
                    if not file_path.lower().endswith(".docx"):
                        file_path += ".docx"
                    doc = Document()
                    for block in plain_text.splitlines():
                        doc.add_paragraph(block)
                    doc.save(file_path)
                else:
                    if not os.path.splitext(file_path)[1]:
                        file_path += ".txt"
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(plain_text)
                self.results_text.append(f"Saved to {file_path}")
            except Exception as e:
                self.results_text.setText(f"Error saving report: {str(e)}")

    def clear_dataset(self):
        jsonl_path = "data/fine_tune.jsonl"
        if os.path.exists(jsonl_path):
            os.remove(jsonl_path)
            self.results_text.append("Dataset cleared. (🛡️ security-relevant Pulse findings stay available in Intel/Shield)")
        else:
            self.results_text.append("No dataset to clear.")

    def link_to_crm(self):
        self.results_text.append("CRM integration TBD: Save compliance issues to leads. (🛡️ security-relevant issues can also be triaged via Shield tab from Pulse loads)")

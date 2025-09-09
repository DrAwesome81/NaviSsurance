from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QListWidget, QTextEdit, QProgressBar, QMenu, QFileDialog, QMessageBox
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from core.compliance import ComplianceChecker
import os
import json
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QSplitter

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
            self.result_signal.emit({"success": True, "data": result})
        except Exception as e:
            self.result_signal.emit({"success": False, "error": str(e)})

class ComplianceTab(QWidget):
    def __init__(self, chat_handler, session_id, conversation_history):
        super().__init__()
        self.chat_handler = chat_handler
        self.session_id = session_id
        self.conversation_history = conversation_history
        self.data_dir = 'data'
        os.makedirs(self.data_dir, exist_ok=True)
        self.setup_ui()

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
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
            self.db.store_dataset_entry(file_path)

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
            self.db.store_dataset_entry(file_path)

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
        self.progress_bar.hide()
        if result["success"]:
            data = result["data"]
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
                self.results_text.setHtml("".join(formatted_results))
            else:
                self.results_text.setText("No results found.")
        else:
            self.results_text.setText(f"Error: {result['error']}")

    def save_compliance_report(self):
        if not self.results_text.toPlainText():
            self.results_text.setText("No results to save.")
            return
        timestamp = QDate.currentDate().toString("yyyyMMdd")
        default_filename = f"compliance_report_{timestamp}.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Compliance Report", default_filename, "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            results = []
            for i in range(self.results_text.document().blockCount()):
                block = self.results_text.document().findBlockByNumber(i).text()
                if block:
                    results.append(block)
            try:
                with open(file_path, "w") as f:
                    json.dump(results, f, indent=2)
                self.results_text.append(f"Saved to {file_path}")
            except Exception as e:
                self.results_text.setText(f"Error saving report: {str(e)}")

    def clear_dataset(self):
        jsonl_path = "data/fine_tune.jsonl"
        if os.path.exists(jsonl_path):
            os.remove(jsonl_path)
            self.results_text.append("Dataset cleared.")
        else:
            self.results_text.append("No dataset to clear.")

    def link_to_crm(self):
        self.results_text.append("CRM integration TBD: Save compliance issues to leads.")

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QSplitter,
    QFileDialog,
    QProgressBar,
    QCheckBox,
    QInputDialog,
    QApplication,
    QSpinBox,
    QGroupBox,
    QMessageBox,
    QComboBox,
    QMenu,
    QPlainTextEdit,
    QStackedWidget,
)
from PyQt6.QtCore import Qt, QMimeData, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QDropEvent, QDragEnterEvent, QPainter, QColor, QShortcut, QKeySequence
# from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
import json
import os
import re
import tempfile
from datetime import datetime
import logging

# ADD THIS IMPORT (just below the Dropbox imports)
from core.workspace_orchestrator import (
    WorkspaceFile,
    WorkspaceTaskSpec,
    DualLLMOrchestrator,
    call_grok_api,
    call_chatgpt_api,
    format_reference_pack_summary,
)
from core.file_handler import get_relevant_past_documents, extract_reference_terms, format_compact_historical_context, derive_style_guidance_from_historical_cluster, DocumentRecord, save_document_record  # Phase 1 retrieval core (VERIFIED COMPLETE) + Phase 4 auto-production use: ... + related cluster + "Historical Sources Used" + badge for generated related set members (from extra flag seeded on companion export) + tiniest sources append block extension (via _build helper) with "Related Document Set Cross-References" sibling listings/relationships + export status + summary notes enrichment for full traceability
from core.app_preferences import is_gdrive_auto_upload_enabled, set_gdrive_auto_upload_enabled  # Phase 4 micro-increment (persist related-set export toggle for GDrive client folders + manifest/summary)
from core.task_extract import parse_suggested_tasks
from core.billing.word_integration import export_docx_to_pdf
from core.workspace_templates import (
    WorkspaceTemplateSpec,
    build_template_preview_markdown,
    discover_workspace_templates,
    get_workspace_template_by_key,
    import_workspace_template_pair,
    render_workspace_template_to_docx,
    validate_template_payload,
)
from gui.task_import_dialog import TaskImportDialog
from gui.agent_console import AgentConsole
from gui.document_export import export_markdownish_document
from gui.notifications import notify_background_complete
from core.agent_chat_service import create_assignment_thread, prime_assignment_handoff

logger = logging.getLogger(__name__)

_WORKSPACE_SUPPORTED_EXTS = {
    ".pdf",
    ".docx",
    ".md",
    ".markdown",
    ".txt",
}

_WORKSPACE_MAX_FILES_PER_FOLDER = 800
_VIRTUAL_WORKSPACE_PREFIX = "virtual://workspace/"

# Save / Export: muted when disabled, accent when document actions are available
_WORKSPACE_SAVE_BTN_STYLE = """
QPushButton:enabled {
    background-color: #FD6262;
    color: #ffffff;
    border: none;
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: 500;
}
QPushButton:disabled {
    background-color: #2a2d33;
    color: #6b7280;
    border: 1px solid #3a3d44;
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: 500;
}
"""
_WORKSPACE_EXPORT_BTN_STYLE = """
QPushButton:enabled {
    background-color: #3d6b4a;
    color: #e8f5e9;
    border: 1px solid #2e7d40;
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: 500;
}
QPushButton:disabled {
    background-color: #2a2d33;
    color: #6b7280;
    border: 1px solid #3a3d44;
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: 500;
}
"""


# Pulse private memory + Shield (workspace tab / coordination surface)
class CollaborationWorker(QThread):
    """Worker thread to run the AI collaboration workflow without freezing the UI."""
    progress_signal = pyqtSignal(str, int)  # status message, progress percentage
    round_update_signal = pyqtSignal(dict)  # round data: {round, grok_output, chatgpt_output, markdown}
    result_signal = pyqtSignal(dict)  # final result
    error_signal = pyqtSignal(str)  # error message
    
    def __init__(self, orchestrator, task_spec, file_contents):
        super().__init__()
        self.orchestrator = orchestrator
        self.task_spec = task_spec
        self.file_contents = file_contents
        self._round_count = 0
        self._max_rounds = task_spec.max_rounds or 3  # Use actual max_rounds from task_spec
    
    def run(self):
        try:
            self.progress_signal.emit("Starting AI collaboration...", 10)
            
            # Set up progress callback that emits signals (thread-safe)
            def progress_callback(round_data):
                """Called after each round - emit signal for UI update"""
                self._round_count += 1
                # Calculate progress dynamically based on max_rounds:
                # 20% base + 70% for rounds (distributed across max_rounds) + 10% reserved for final processing
                # Progress per round = 70 / max_rounds
                progress_per_round = 70.0 / self._max_rounds
                progress = 20 + int(self._round_count * progress_per_round)
                # Cap at 90% until final result
                progress = min(progress, 90)
                self.progress_signal.emit(f"Round {self._round_count}/{self._max_rounds} complete", progress)
                self.round_update_signal.emit(round_data)
            
            # Update orchestrator's progress callback
            self.orchestrator._progress_callback = progress_callback
            
            # Run the orchestrator
            result = self.orchestrator.run_once(self.task_spec, self.file_contents)
            
            # Emit final result
            self.progress_signal.emit("Processing final results...", 95)
            self.result_signal.emit(result)
            
        except Exception as e:
            logger.error(f"Error in collaboration worker: {e}")
            self.error_signal.emit(str(e))

class AlwaysVisiblePlaceholderTextEdit(QTextEdit):
    """Custom QTextEdit with always-visible placeholder text."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._placeholder_text = ""
        self._placeholder_visible = True
    
    def setPlaceholderText(self, text):
        self._placeholder_text = text
        self._placeholder_visible = True
        self.update()
    
    def paintEvent(self, event):
        super().paintEvent(event)
        if self._placeholder_visible and not self.toPlainText():
            painter = QPainter(self.viewport())
            painter.setPen(QColor(128, 128, 128))  # Gray color for placeholder
            painter.setFont(self.font())
            rect = self.viewport().rect()
            painter.drawText(rect.adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignCenter, self._placeholder_text)
    
    def setPlainText(self, text):
        super().setPlainText(text)
        self._placeholder_visible = not bool(text.strip())
        self.update()
    
    def setHtml(self, text):
        super().setHtml(text)
        self._placeholder_visible = not bool(text.strip())
        self.update()

class WorkspaceTab(QWidget):
    def __init__(self, db, chat_handler):
        super().__init__()
        self.db = db
        self.chat_handler = chat_handler
        self.selected_files = []
        self._seen_paths: set[str] = set()
        
        # NEW: dual-LLM orchestrator that will talk to Grok + ChatGPT
        # Initialize with real API call functions
        self._current_file_contents = {}  # Store file contents for API calls
        self._collaboration_worker = None  # Worker thread for running collaboration
        self._current_markdown = ""  # Store current markdown for saving
        # For persistence of the last run
        self._last_task_spec = None
        self._last_workspace_files = []
        self._saved_workspaces: list[dict] = []
        self._template_specs: dict[str, WorkspaceTemplateSpec] = {}
        self._current_workspace_id: int | None = None
        self._current_workspace_name = ""
        self._restoring_workspace_state = False
        self._current_template_blocks: dict[str, str] = {}
        self._current_document_metadata: dict[str, str] = {}
        self._last_generated_template_spec: WorkspaceTemplateSpec | None = None
        self._current_template_validation_issues: list[str] = []
        self._current_template_evidence_map: dict[str, str] = {}
        self._current_unresolved_fields: list[str] = []
        self._current_research_gaps: list[str] = []
        self._current_user_questions: list[str] = []
        self._previous_gap_snapshot: dict[str, list[str]] = {}
        self._resolved_gap_snapshot: dict[str, list[str]] = {}
        self._latest_merged_atlas_info: dict[str, object] = {}
        self._last_related_set_manifest = None
        self._last_related_set_summary = None
        self._last_billing_artifact = None  # Billing Depth micro (smallest extension of related-set + cluster machinery): in-session storage for generated billing summary/manifest using historical cluster. Written to client folders on export (local + GDrive via api). Defensive/optional; cleared on non-set flows where relevant.
        self._demo_full_cycle_pending_assignment = False
        # Phase 4 micro-increment (persist): load persisted GDrive auto-upload toggle (default True) so Related Document Set exports (quick-export + manifest/summary to client folder) remember user choice across restarts. Reuses new app_preferences helpers; no behavior change, defensive getattr remains.
        self._gdrive_auto_upload_enabled = is_gdrive_auto_upload_enabled()

        self.setup_ui()
        self._refresh_document_templates()
        self._refresh_saved_workspaces()
        self._restore_workspace_on_startup()

    def _prompt_templates(self) -> dict[str, dict[str, str]]:
        """
        Small set of proven instruction templates that reliably produce:
        - a CEO-friendly executive summary
        - a structured body (so the output is skimmable)
        - an importable task section (when the toggle is enabled)
        """
        return {
            "ceo_strategy_memo_v1": {
                "label": "CEO Strategy Memo (v1)",
                "prompt": (
                    "Draft a CEO-facing regulatory strategy memo.\n\n"
                    "Audience: startup CEO.\n"
                    "Tone: calm, direct, decision-oriented.\n\n"
                    "Required sections:\n"
                    "1) Executive summary (5–8 bullets)\n"
                    "2) Recommended path (primary + fallback) and why\n"
                    # Pulse [Security-Relevant] intel (via Intel/Shield) can inform the cybersecurity evidence plan sections
                    # additional Pulse private memory + Shield for workspace tab
                    "3) Evidence plan (software, clinical, HF, cybersecurity, labeling)\n"
                    "4) Timeline ranges + key dependencies\n"
                    "5) Top risks + mitigations\n"
                    "6) Next 30/60/90 days plan\n\n"
                    "Constraints:\n"
                    "- Be explicit about assumptions.\n"
                    "- If uncertain, present options and the decision criteria.\n"
                    "- Keep it skimmable with short paragraphs and bullets.\n\n"
                    "Also include a '## Suggested Tasks (importable)' section with ~12 tasks."
                ),
            },
            "ceo_board_update_v1": {
                "label": "Board/Investor Update (v1)",
                "prompt": (
                    "Create a board/investor update draft based on the provided materials.\n\n"
                    "Audience: investors + board.\n"
                    "Tone: crisp, credible, non-hype.\n\n"
                    "Required sections:\n"
                    "1) Executive summary (3–6 bullets)\n"
                    "2) What changed since last update\n"
                    "3) Regulatory status + key decisions needed\n"
                    "4) Evidence/status (what’s done, what’s next)\n"
                    "5) Risks/unknowns + mitigation plan\n"
                    "6) Asks (what we need from the board/investors)\n\n"
                    "Also include a '## Suggested Tasks (importable)' section with ~10 tasks."
                ),
            },
            "product_brief_to_plan_v1": {
                "label": "Product Brief → Execution Plan (v1)",
                "prompt": (
                    "Convert the provided product brief into an execution-ready plan.\n\n"
                    "Required sections:\n"
                    "1) Executive summary (CEO-readable)\n"
                    "2) Key open questions (what must be clarified)\n"
                    "3) Workstreams (Reg/QA, Clinical, Engineering, GTM) with 1–2 paragraphs each\n"
                    "4) Milestones (next 12 weeks) with dependencies\n\n"
                    "Also include a '## Suggested Tasks (importable)' section with 15–20 tasks."
                ),
            },
        }

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Main splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setHandleWidth(6)
        layout.addWidget(main_splitter)
        
        # Left: File Selection Area
        self.setup_file_selection(main_splitter)
        
        # Right: Preview/Results Pane
        self.setup_preview_pane(main_splitter)
        
        # Use stretch factors for responsive proportions (20% files, 80% preview)
        main_splitter.setStretchFactor(0, 2)  # Files panel gets more usable default space
        main_splitter.setStretchFactor(1, 5)  # Preview panel still remains primary

        self.quill_chat_group = QGroupBox("Direct chat with Quill (single-agent; bypasses Grok + ChatGPT review)")
        self.quill_chat_group.setCheckable(True)
        self.quill_chat_group.setChecked(False)
        quill_chat_layout = QVBoxLayout(self.quill_chat_group)
        self.quill_console = AgentConsole(
            self.db,
            agent_code="quill",
            parent=self,
            context_provider=self._build_quill_runtime_context,
            reply_ready_callback=self._load_quill_reply_into_preview,
            workflow_trigger_callback=self._run_quill_reviewed_workflow,
        )
        self.quill_console.setVisible(False)
        quill_chat_layout.addWidget(self.quill_console)
        self.quill_chat_group.toggled.connect(
            lambda checked: self.quill_console.setVisible(bool(checked))
        )
        layout.addWidget(self.quill_chat_group)
        
        self.setLayout(layout)
        self._install_workspace_prompt_shortcuts()

    def _install_workspace_prompt_shortcuts(self):
        for seq in ("Ctrl+Return", "Meta+Return"):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self._submit_workspace_collaboration_prompt)

    def _submit_workspace_collaboration_prompt(self):
        self.run_ai_collaboration_workflow()

    def setup_file_selection(self, parent_splitter):
        file_widget = QWidget()
        file_widget.setAcceptDrops(True)
        file_widget.setMinimumWidth(420)
        file_layout = QVBoxLayout(file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(8)
        
        file_header = QLabel("Files")
        file_header.setStyleSheet("color: #e8eaed; font-weight: 600; padding: 8px; background-color: #22252c; border: 1px solid #2e2f32; border-radius: 6px;")
        file_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        file_layout.addWidget(file_header)
        
        # Status and progress
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #9aa0a6; padding: 5px; font-size: 13px;")
        self.status_label.setMinimumHeight(28)
        status_layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(22)
        self.progress_bar.setVisible(False)
        status_layout.addWidget(self.progress_bar)
        self.view_chief_of_staff_btn = QPushButton("→ Open in Chief of Staff")
        self.view_chief_of_staff_btn.setVisible(False)
        self.view_chief_of_staff_btn.setToolTip("Switch to the Chief of Staff tab to delegate imported tasks and assignments.")
        self.view_chief_of_staff_btn.clicked.connect(self._open_chief_of_staff_tab)
        self.view_chief_of_staff_btn.setMinimumHeight(32)
        self.view_chief_of_staff_btn.setMinimumWidth(220)
        self.view_chief_of_staff_btn.setStyleSheet(
            "QPushButton { background-color: #FD6262; color: white; border: none; "
            "padding: 8px 14px; border-radius: 6px; font-weight: 700; font-size: 12px; }"
            "QPushButton:hover { background-color: #e85555; }"
        )
        status_layout.addWidget(self.view_chief_of_staff_btn)
        status_layout.addStretch()
        file_layout.addLayout(status_layout)
        
        workspace_row = QHBoxLayout()
        workspace_label = QLabel("Workspace:")
        workspace_label.setStyleSheet("color: #e8eaed; padding: 4px; font-size: 13px;")
        workspace_row.addWidget(workspace_label)
        self.saved_workspace_combo = QComboBox()
        self.saved_workspace_combo.setStyleSheet(
            "background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; "
            "border-radius: 6px; padding: 8px;"
        )
        self.saved_workspace_combo.setMinimumHeight(36)
        workspace_row.addWidget(self.saved_workspace_combo, 1)
        self.saved_workspace_combo.currentIndexChanged.connect(lambda: self.populate_relevant_historical_examples(self.prompt_template_combo.currentData() or "", self.collaboration_prompt_edit.toPlainText()[:150]) if hasattr(self, "populate_relevant_historical_examples") else None)
        save_workspace_btn = QPushButton("Save")
        save_workspace_btn.setMinimumHeight(36)
        save_workspace_btn.clicked.connect(self.save_workspace)
        workspace_row.addWidget(save_workspace_btn)
        save_as_workspace_btn = QPushButton("Save As…")
        save_as_workspace_btn.setMinimumHeight(36)
        save_as_workspace_btn.clicked.connect(self.save_workspace_as)
        workspace_row.addWidget(save_as_workspace_btn)
        load_workspace_btn = QPushButton("Load")
        load_workspace_btn.setMinimumHeight(36)
        load_workspace_btn.clicked.connect(self.load_selected_workspace)
        workspace_row.addWidget(load_workspace_btn)
        clear_workspace_btn = QPushButton("Clear")
        clear_workspace_btn.setMinimumHeight(36)
        clear_workspace_btn.clicked.connect(self.clear_workspace)
        workspace_row.addWidget(clear_workspace_btn)
        file_layout.addLayout(workspace_row)

        # Max rounds control
        rounds_layout = QHBoxLayout()
        rounds_label = QLabel("Max Rounds:")
        rounds_label.setStyleSheet("color: #e8eaed; padding: 4px; font-size: 13px;")
        rounds_layout.addWidget(rounds_label)
        self.max_rounds_spinbox = QSpinBox()
        self.max_rounds_spinbox.setMinimum(1)
        self.max_rounds_spinbox.setMaximum(10)
        self.max_rounds_spinbox.setValue(3)  # Default
        self.max_rounds_spinbox.setStyleSheet(
            "background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; "
            "border-radius: 6px; padding: 8px;"
        )
        self.max_rounds_spinbox.setMinimumHeight(36)
        self.max_rounds_spinbox.setMinimumWidth(96)
        rounds_layout.addWidget(self.max_rounds_spinbox)
        rounds_layout.addStretch()
        file_layout.addLayout(rounds_layout)

        # Prompt template picker (keeps outputs consistent and importable)
        template_row = QHBoxLayout()
        template_label = QLabel("Prompt Template:")
        template_label.setStyleSheet("color: #e8eaed; padding: 4px; font-size: 13px;")
        template_row.addWidget(template_label)

        self.prompt_template_combo = QComboBox()
        self.prompt_template_combo.setStyleSheet(
            "background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; "
            "border-radius: 6px; padding: 8px;"
        )
        self.prompt_template_combo.setMinimumHeight(36)
        self.prompt_template_combo.addItem("Custom", "custom")
        for key, meta in self._prompt_templates().items():
            self.prompt_template_combo.addItem(str(meta["label"]), key)
        self.prompt_template_combo.setToolTip(
            "Optional. Pick a template to prefill the instruction prompt with a proven structure."
        )
        template_row.addWidget(self.prompt_template_combo, 1)
        template_row.addStretch()
        file_layout.addLayout(template_row)

        doc_template_row = QHBoxLayout()
        doc_template_label = QLabel("Document Template:")
        doc_template_label.setStyleSheet("color: #e8eaed; padding: 4px; font-size: 13px;")
        doc_template_row.addWidget(doc_template_label)
        self.document_template_combo = QComboBox()
        self.document_template_combo.setStyleSheet(
            "background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; "
            "border-radius: 6px; padding: 8px;"
        )
        self.document_template_combo.setMinimumHeight(36)
        self.document_template_combo.addItem("None (markdown only)", "")
        self.document_template_combo.currentIndexChanged.connect(self._on_workspace_state_changed)
        self.document_template_combo.currentIndexChanged.connect(lambda: self.populate_relevant_historical_examples(self.document_template_combo.currentData() or "", self.collaboration_prompt_edit.toPlainText()[:150]) if hasattr(self, "populate_relevant_historical_examples") else None)
        doc_template_row.addWidget(self.document_template_combo, 1)
        refresh_templates_btn = QPushButton("Refresh")
        refresh_templates_btn.setMinimumHeight(36)
        refresh_templates_btn.clicked.connect(self._refresh_document_templates)
        doc_template_row.addWidget(refresh_templates_btn)
        import_template_btn = QPushButton("Import Pair…")
        import_template_btn.setMinimumHeight(36)
        import_template_btn.clicked.connect(self.import_template_pair)
        doc_template_row.addWidget(import_template_btn)
        file_layout.addLayout(doc_template_row)

        # Suggested tasks contract toggle
        self.include_task_suggestions_checkbox = QCheckBox("Include “Suggested Tasks (importable)” section")
        self.include_task_suggestions_checkbox.setChecked(True)
        self.include_task_suggestions_checkbox.setStyleSheet("color: #e8eaed; padding: 6px; font-size: 13px;")
        self.include_task_suggestions_checkbox.setToolTip(
            "When enabled, the generated markdown should include a parseable task list we can extract into reviewable Tasks."
        )
        self.include_task_suggestions_checkbox.toggled.connect(self._on_workspace_state_changed)
        self.include_task_suggestions_checkbox.toggled.connect(lambda: self.populate_relevant_historical_examples(self.prompt_template_combo.currentData() or "", self.collaboration_prompt_edit.toPlainText()[:150]) if hasattr(self, "populate_relevant_historical_examples") else None)
        file_layout.addWidget(self.include_task_suggestions_checkbox)
        self.max_rounds_spinbox.valueChanged.connect(self._on_workspace_state_changed)
        self.max_rounds_spinbox.valueChanged.connect(lambda: self.populate_relevant_historical_examples(self.prompt_template_combo.currentData() or "", self.collaboration_prompt_edit.toPlainText()[:150]) if hasattr(self, "populate_relevant_historical_examples") else None)
        self.prompt_template_combo.currentIndexChanged.connect(self._on_workspace_state_changed)
        self.prompt_template_combo.currentIndexChanged.connect(lambda: self.populate_relevant_historical_examples(self.prompt_template_combo.currentData() or "", self.collaboration_prompt_edit.toPlainText()[:150]) if hasattr(self, "populate_relevant_historical_examples") else None)

        prompt_label = QLabel("Collaboration prompt:")
        prompt_label.setStyleSheet("color: #e8eaed; padding: 4px; font-size: 13px;")
        file_layout.addWidget(prompt_label)
        self.collaboration_prompt_edit = QPlainTextEdit()
        self.collaboration_prompt_edit.setPlaceholderText(
            "What should Grok + ChatGPT produce? Ctrl+Enter to run (⌘+Enter on macOS)."
        )
        self.collaboration_prompt_edit.setStyleSheet(
            "background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; "
            "border-radius: 6px; padding: 8px;"
        )
        self.collaboration_prompt_edit.setMinimumHeight(96)
        self.collaboration_prompt_edit.setMaximumHeight(200)
        self.collaboration_prompt_edit.textChanged.connect(self._on_workspace_state_changed)
        # Next micro: live historical list update on prompt text change (for ref bias)
        try:
            self.collaboration_prompt_edit.textChanged.connect(lambda: self.populate_relevant_historical_examples(self.prompt_template_combo.currentData() or "", self.collaboration_prompt_edit.toPlainText()[:150]) if hasattr(self, "populate_relevant_historical_examples") else None)
        except Exception:
            pass
        file_layout.addWidget(self.collaboration_prompt_edit)
        
        # Select and Generate Draft buttons
        btn_layout = QHBoxLayout()
        select_btn = QPushButton("Select File/Folder")
        select_btn.setStyleSheet("background-color: #FD6262; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 500;")
        select_btn.setMinimumHeight(38)
        select_btn.setMinimumWidth(170)
        select_btn.clicked.connect(self.select_files)
        btn_layout.addWidget(select_btn)

        folder_btn = QPushButton("Add Folder…")
        folder_btn.setStyleSheet("background-color: #3a3b3e; color: #e8eaed; border: 1px solid #2e2f32; padding: 8px 16px; border-radius: 6px; font-weight: 500;")
        folder_btn.setMinimumHeight(38)
        folder_btn.setMinimumWidth(140)
        folder_btn.clicked.connect(self.select_folder)
        btn_layout.addWidget(folder_btn)
        
        self.generate_draft_btn = QPushButton("Generate Draft")
        self.generate_draft_btn.setStyleSheet(
            "QPushButton { background-color: #FD6262; color: white; border: none; padding: 8px 16px; "
            "border-radius: 6px; font-weight: 500; }"
            "QPushButton:disabled { background-color: #555; color: #c4c4c4; }"
        )
        self.generate_draft_btn.setMinimumHeight(38)
        self.generate_draft_btn.setMinimumWidth(170)
        self.generate_draft_btn.clicked.connect(self.run_ai_collaboration_workflow)
        btn_layout.addWidget(self.generate_draft_btn)
        file_layout.addLayout(btn_layout)
        
        self.file_list = QListWidget()
        self.file_list.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; border-radius: 6px;")
        self.file_list.setMinimumHeight(300)
        self.file_list.setSpacing(6)
        self.file_list.setToolTip("Drag and drop files here or mark RAG results")
        self.file_list.itemClicked.connect(self.on_file_selected)
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self.show_file_context_menu)
        self.file_list_empty_hint = QLabel(
            "Add files or send research from Deep Research tab to begin drafting."
        )
        self.file_list_empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.file_list_empty_hint.setWordWrap(True)
        self.file_list_empty_hint.setStyleSheet(
            "color: #9aa0a6; padding: 32px 16px; font-size: 13px; "
            "background-color: #22252c; border: 1px solid #2e2f32; border-radius: 6px;"
        )
        self.file_list_empty_hint.setMinimumHeight(300)
        self._workspace_file_stack = QStackedWidget()
        self._workspace_file_stack.addWidget(self.file_list_empty_hint)
        self._workspace_file_stack.addWidget(self.file_list)
        file_layout.addWidget(self._workspace_file_stack)

        # Phase 1: Visible "Relevant Historical Documents" surface (clickable list of retrieved examples)
        hist_group = QGroupBox("Relevant Historical Documents (from your archive)")
        hist_group.setStyleSheet("QGroupBox { font-weight: 600; color: #e8eaed; }")
        hist_layout = QVBoxLayout(hist_group)
        self.historical_examples_list = QListWidget()
        self.historical_examples_list.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; border-radius: 6px;")
        self.historical_examples_list.setMinimumHeight(120)
        self.historical_examples_list.setMaximumHeight(180)
        self.historical_examples_list.itemDoubleClicked.connect(self._on_historical_example_clicked)
        self.historical_examples_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.historical_examples_list.customContextMenuRequested.connect(self._show_workspace_historical_context_menu)
        hist_layout.addWidget(self.historical_examples_list)
        file_layout.addWidget(hist_group)
        self._sync_workspace_file_list_empty_state()
        
        file_widget.dragEnterEvent = self.dragEnterEvent
        file_widget.dropEvent = self.dropEvent
        
        parent_splitter.addWidget(file_widget)

    def setup_preview_pane(self, parent_splitter):
        """
        Right-hand side of the Workspace tab:
        - Left: vertical stack of Grok + ChatGPT streaming panes
        - Right: Markdown document pane (reuses self.preview_text)
        """
        preview_widget = QWidget()
        preview_widget.setMinimumWidth(900)
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(5)

        # Horizontal splitter: [Grok/ChatGPT stack] | [Markdown document]
        inner_splitter = QSplitter(Qt.Orientation.Horizontal)
        preview_layout.addWidget(inner_splitter)

        #
        # LEFT SIDE: Grok + ChatGPT streaming panes (stacked vertically)
        #
        ai_widget = QWidget()
        ai_layout = QVBoxLayout(ai_widget)
        ai_layout.setContentsMargins(0, 0, 0, 0)
        ai_layout.setSpacing(5)

        # Grok pane
        grok_header = QLabel("Grok (API)")
        grok_header.setStyleSheet(
            "color: #e8eaed; font-weight: 600; padding: 8px; "
            "background-color: #22252c; border: 1px solid #2e2f32; border-radius: 6px;"
        )
        grok_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ai_layout.addWidget(grok_header)

        self.grok_text = AlwaysVisiblePlaceholderTextEdit()
        self.grok_text.setReadOnly(True)
        self.grok_text.setStyleSheet(
            "background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; "
            "border-radius: 6px;"
        )
        self.grok_text.setMinimumHeight(190)
        self.grok_text.setPlaceholderText("Grok responses will appear here.")
        ai_layout.addWidget(self.grok_text)

        # ChatGPT pane
        chatgpt_header = QLabel("ChatGPT (API)")
        chatgpt_header.setStyleSheet(
            "color: #e8eaed; font-weight: 600; padding: 8px; "
            "background-color: #22252c; border: 1px solid #2e2f32; border-radius: 6px;"
        )
        chatgpt_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ai_layout.addWidget(chatgpt_header)

        self.chatgpt_text = AlwaysVisiblePlaceholderTextEdit()
        self.chatgpt_text.setReadOnly(True)
        self.chatgpt_text.setStyleSheet(
            "background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; "
            "border-radius: 6px;"
        )
        self.chatgpt_text.setMinimumHeight(190)
        self.chatgpt_text.setPlaceholderText("ChatGPT responses will appear here.")
        ai_layout.addWidget(self.chatgpt_text)

        inner_splitter.addWidget(ai_widget)

        #
        # RIGHT SIDE: Markdown document pane (this is still self.preview_text)
        #
        markdown_widget = QWidget()
        markdown_layout = QVBoxLayout(markdown_widget)
        markdown_layout.setContentsMargins(0, 0, 0, 0)
        markdown_layout.setSpacing(5)

        markdown_header = QLabel("Markdown Document")
        markdown_header.setStyleSheet(
            "color: #e8eaed; font-weight: 600; padding: 8px; "
            "background-color: #22252c; border: 1px solid #2e2f32; border-radius: 6px;"
        )
        markdown_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        markdown_layout.addWidget(markdown_header)

        # Save/Export button bar
        button_bar = QHBoxLayout()
        self.save_button = QPushButton("Save Markdown")
        self.save_button.setStyleSheet(_WORKSPACE_SAVE_BTN_STYLE)
        self.save_button.setMinimumHeight(38)
        self.save_button.setMinimumWidth(160)
        self.save_button.clicked.connect(self.save_markdown)
        self.save_button.setEnabled(False)  # Disabled until document is generated
        button_bar.addWidget(self.save_button)
        
        self.export_button = QPushButton("Export as...")
        self.export_button.setStyleSheet(_WORKSPACE_EXPORT_BTN_STYLE)
        self.export_button.setMinimumHeight(38)
        self.export_button.setMinimumWidth(120)
        self.export_button.clicked.connect(self.export_markdown)
        self.export_button.setEnabled(False)  # Disabled until document is generated
        button_bar.addWidget(self.export_button)

        self.extract_tasks_button = QPushButton("Extract Suggested Tasks…")
        self.extract_tasks_button.setStyleSheet(
            "background-color: #3a3b3e; color: #e8eaed; border: 1px solid #2e2f32; "
            "padding: 8px 16px; border-radius: 6px; font-weight: 500;"
        )
        self.extract_tasks_button.setMinimumHeight(38)
        self.extract_tasks_button.setMinimumWidth(220)
        self.extract_tasks_button.clicked.connect(self.extract_suggested_tasks)
        self.extract_tasks_button.setEnabled(False)
        button_bar.addWidget(self.extract_tasks_button)

        button_bar.addStretch()
        markdown_layout.addLayout(button_bar)

        self.template_gap_summary = QTextEdit()
        self.template_gap_summary.setReadOnly(True)
        self.template_gap_summary.setVisible(False)
        self.template_gap_summary.setMinimumHeight(150)
        self.template_gap_summary.setStyleSheet(
            "background-color: #1f232a; color: #f1f3f4; border: 1px solid #2e2f32; border-radius: 6px;"
        )
        markdown_layout.addWidget(self.template_gap_summary)

        gap_button_row = QHBoxLayout()
        self.send_research_gaps_btn = QPushButton("Send Research Gaps to Atlas")
        self.send_research_gaps_btn.setEnabled(False)
        self.send_research_gaps_btn.clicked.connect(self.send_research_gaps_to_atlas)
        gap_button_row.addWidget(self.send_research_gaps_btn)
        self.merge_atlas_research_btn = QPushButton("Merge Atlas Research")
        self.merge_atlas_research_btn.clicked.connect(self.merge_latest_atlas_research)
        gap_button_row.addWidget(self.merge_atlas_research_btn)
        self.copy_user_questions_btn = QPushButton("Copy User Questions")
        self.copy_user_questions_btn.setEnabled(False)
        self.copy_user_questions_btn.clicked.connect(self.copy_user_questions)
        gap_button_row.addWidget(self.copy_user_questions_btn)
        self.export_question_packet_btn = QPushButton("Export Question Packet...")
        self.export_question_packet_btn.setEnabled(False)
        self.export_question_packet_btn.clicked.connect(self.export_question_packet)
        gap_button_row.addWidget(self.export_question_packet_btn)
        gap_button_row.addStretch()
        markdown_layout.addLayout(gap_button_row)

        # IMPORTANT: reuse self.preview_text so existing methods still work
        self.preview_text = AlwaysVisiblePlaceholderTextEdit()
        # Let you edit the Markdown directly if desired
        self.preview_text.setReadOnly(False)
        self.preview_text.setStyleSheet(
            "background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; "
            "border-radius: 6px;"
        )
        self.preview_text.setMinimumHeight(430)
        self.preview_text.setPlaceholderText("Markdown document will appear here.")
        markdown_layout.addWidget(self.preview_text)

        inner_splitter.addWidget(markdown_widget)

        # Proportions: give a bit more space to the Markdown pane
        inner_splitter.setStretchFactor(0, 3)  # Grok/ChatGPT stack
        inner_splitter.setStretchFactor(1, 4)  # Markdown document

        parent_splitter.addWidget(preview_widget)

    def _refresh_document_templates(self):
        current_key = ""
        if hasattr(self, "document_template_combo") and self.document_template_combo is not None:
            current_key = str(self.document_template_combo.currentData() or "")
        specs = discover_workspace_templates()
        self._template_specs = {spec.key: spec for spec in specs}
        if not hasattr(self, "document_template_combo") or self.document_template_combo is None:
            return
        self.document_template_combo.blockSignals(True)
        self.document_template_combo.clear()
        self.document_template_combo.addItem("None (markdown only)", "")
        for spec in specs:
            suffix = " (Imported)" if spec.source == "imported" else ""
            self.document_template_combo.addItem(f"{spec.display_name}{suffix}", spec.key)
        idx = self.document_template_combo.findData(current_key)
        if idx >= 0:
            self.document_template_combo.setCurrentIndex(idx)
        self.document_template_combo.blockSignals(False)

    def _selected_document_template_spec(self) -> WorkspaceTemplateSpec | None:
        key = ""
        if getattr(self, "document_template_combo", None) is not None:
            key = str(self.document_template_combo.currentData() or "")
        if not key:
            return None
        return self._template_specs.get(key) or get_workspace_template_by_key(key)

    def _workspace_state_payload(self) -> dict:
        files = []
        for file_info in self.selected_files:
            is_virtual = bool(file_info.get("virtual"))
            files.append(
                {
                    "name": str(file_info.get("name") or ""),
                    "path": str(file_info.get("path") or ""),
                    "is_folder": False,
                    "size": int(file_info.get("size") or 0),
                    "modified": file_info.get("modified"),
                    "marked": bool(file_info.get("marked")),
                    "virtual": is_virtual,
                    "content": str(file_info.get("content") or "") if is_virtual else "",
                    "source_type": str(file_info.get("source_type") or ""),
                    "source_assignment_id": int(file_info.get("source_assignment_id") or 0),
                    "source_title": str(file_info.get("source_title") or ""),
                }
            )
        return {
            "name": self._current_workspace_name,
            "files": files,
            "max_rounds": self.max_rounds_spinbox.value() if hasattr(self, "max_rounds_spinbox") else 3,
            "prompt_template_key": str(self.prompt_template_combo.currentData() or "custom")
            if getattr(self, "prompt_template_combo", None) is not None
            else "custom",
            "document_template_key": str(self.document_template_combo.currentData() or "")
            if getattr(self, "document_template_combo", None) is not None
            else "",
            "include_task_suggestions": bool(
                self.include_task_suggestions_checkbox.isChecked()
                if getattr(self, "include_task_suggestions_checkbox", None) is not None
                else True
            ),
            "collaboration_prompt": str(self.collaboration_prompt_edit.toPlainText() or "")
            if getattr(self, "collaboration_prompt_edit", None) is not None
            else "",
            "saved_at": datetime.now().isoformat(),
            # Phase 4 related document sets continuation (next micro after cross-refs in sources): persist set context (manifest/summary/flag) so saved workspaces for set members retain traceability data for manifest viewer, summary, exports, etc. Reused on load. Defensive (None/empty ok); tiny additive only.
            "related_set_manifest": getattr(self, "_last_related_set_manifest", None),
            "related_set_summary": getattr(self, "_last_related_set_summary", None),
            "related_set_companion": (getattr(self, "_current_document_metadata", {}) or {}).get("related_set_companion") if isinstance(getattr(self, "_current_document_metadata", {}), dict) else None,
            # Keep-going micro: also persist the companions list (from the chained storage) for full set context on saved workspace restore (enables future re-use of accurate other-members list in cross-refs/badge without re-gen). Tiny, defensive.
            "related_set_companions": getattr(self, "_last_related_set_companions", None),
            # Chained tiniest autonomous micro (no stop after rich seed in _seed + sources cross-refs): persist the full "related_set_cross_ref_section" (the "Companion to ... Other set members..." listing) from metadata (or live build) so saved related-set workspaces restore the *exact* rich sibling traceability text for templates, details, etc. (no re-derive needed). Purely additive 1 key, defensive, zero effect non-sets; mirrors companions/manifest pattern.
            "related_set_cross_ref_section": ((getattr(self, "_current_document_metadata", {}) or {}).get("related_set_cross_ref_section") or (getattr(self, "_current_document_metadata", {}) or {}).get("related_set_cross_ref_note") or None),
            # Keep-going autonomous chained micro (Phase 4, immediately after sources append block tiny marker addition + list tooltip): tiniest persist of the new "related_set_sources_extended" flag (set inside the Historical Sources Used extension block when cross-refs subsection injected). Ensures restored saved set workspaces know the member's doc carries the dedicated Related Document Set Cross-References (for any future consumers or UI). 1-line, defensive, reuses meta access pattern exactly; zero impact non-sets.
            "related_set_sources_extended": ((getattr(self, "_current_document_metadata", {}) or {}).get("related_set_sources_extended") if isinstance(getattr(self, "_current_document_metadata", {}), dict) else None),
            # Billing Depth micro (autonomous first increment, extending related-set machinery): persist the billing artifact/summary (if generated for the set via cluster) so that saved workspaces carry it for continued export to client folders + GDrive without re-running Generate Billing. Smallest additive key inside existing payload dict; defensive None; zero impact on non-billing flows. Mirrors the related_set_* persistence pattern exactly.
            "billing_set_artifact": getattr(self, "_last_billing_artifact", None),
        }

    def _on_workspace_state_changed(self, *_args):
        if self._restoring_workspace_state:
            return
        try:
            if hasattr(self.db, "workspace_session_save"):
                self.db.workspace_session_save(self._workspace_state_payload())
        except Exception as e:
            logger.debug(f"Could not persist workspace session state: {e}")
        if self._current_workspace_name and hasattr(self.db, "workspace_state_upsert"):
            try:
                workspace_id = self.db.workspace_state_upsert(
                    name=self._current_workspace_name,
                    state=self._workspace_state_payload(),
                )
                self._current_workspace_id = int(workspace_id or 0) or None
                if hasattr(self.db, "workspace_state_set_last_used"):
                    self.db.workspace_state_set_last_used(self._current_workspace_id)
            except Exception as e:
                logger.debug(f"Could not autosave named workspace state: {e}")

    def _sync_workspace_file_list_empty_state(self) -> None:
        stack = getattr(self, "_workspace_file_stack", None)
        if stack is None:
            return
        stack.setCurrentIndex(0 if not self.selected_files else 1)

    def _template_label_for_key(self, key: str) -> str:
        spec = self._last_generated_template_spec
        if spec:
            for target in spec.fill_targets:
                if str(target.key) == str(key):
                    return str(target.label or key)
        return str(key or "")

    @staticmethod
    def _normalize_string_list(values) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for value in list(values or []):
            text = str(value or "").strip()
            if not text:
                continue
            marker = text.casefold()
            if marker in seen:
                continue
            seen.add(marker)
            out.append(text)
        return out

    def _current_gap_snapshot(self) -> dict[str, list[str]]:
        return {
            "unresolved_fields": self._normalize_string_list(self._current_unresolved_fields),
            "research_gaps": self._normalize_string_list(self._current_research_gaps),
            "user_questions": self._normalize_string_list(self._current_user_questions),
        }

    def _resolved_gap_snapshot_from_baseline(self) -> dict[str, list[str]]:
        baseline = self._previous_gap_snapshot or {}
        current = self._current_gap_snapshot()
        resolved: dict[str, list[str]] = {}
        for key in ("unresolved_fields", "research_gaps", "user_questions"):
            current_markers = {str(item).casefold() for item in current.get(key, [])}
            resolved[key] = [
                item
                for item in self._normalize_string_list(baseline.get(key, []))
                if str(item).casefold() not in current_markers
            ]
        return resolved

    def _capture_gap_baseline_for_next_run(self):
        self._previous_gap_snapshot = self._current_gap_snapshot()
        self._resolved_gap_snapshot = {}

    def _atlas_merge_context_label(self) -> str:
        info = self._latest_merged_atlas_info or {}
        assignment_id = int(info.get("assignment_id") or 0)
        if assignment_id <= 0:
            for file_info in self.selected_files:
                if str(file_info.get("source_type") or "").strip() != "atlas_research":
                    continue
                assignment_id = int(file_info.get("source_assignment_id") or 0)
                if assignment_id > 0:
                    break
        if assignment_id > 0:
            return f"Atlas research merge A-{assignment_id:04d}"
        return "merged Atlas research"

    def _has_active_atlas_research_source(self) -> bool:
        for file_info in self.selected_files:
            if not bool(file_info.get("virtual")):
                continue
            if str(file_info.get("source_type") or "").strip() == "atlas_research":
                return True
        return False

    def _resolved_gap_provenance(self, resolved: dict[str, list[str]]) -> dict[str, dict[str, str]]:
        atlas_label = self._atlas_merge_context_label() if self._has_active_atlas_research_source() else ""
        evidence_map = {str(k): str(v or "").strip() for k, v in (self._current_template_evidence_map or {}).items()}
        provenance: dict[str, dict[str, str]] = {
            "unresolved_fields": {},
            "research_gaps": {},
            "user_questions": {},
        }
        for key in resolved.get("unresolved_fields", []):
            evidence_text = evidence_map.get(str(key), "")
            parts = []
            if atlas_label:
                parts.append(f"via {atlas_label}")
            if evidence_text:
                parts.append(f"evidence: {evidence_text}")
            provenance["unresolved_fields"][str(key)] = "; ".join(parts) if parts else "supported by updated evidence"
        for item in resolved.get("research_gaps", []):
            provenance["research_gaps"][str(item)] = (
                f"via {atlas_label}" if atlas_label else "resolved in latest review pass"
            )
        for item in resolved.get("user_questions", []):
            provenance["user_questions"][str(item)] = (
                f"via {atlas_label}" if atlas_label else "resolved in latest review pass"
            )
        return provenance

    @staticmethod
    def _json_object(value) -> dict:
        if isinstance(value, dict):
            return dict(value)
        if not value:
            return {}
        try:
            obj = json.loads(value)
        except Exception:
            return {}
        return dict(obj) if isinstance(obj, dict) else {}

    @staticmethod
    def _virtual_workspace_path(slug: str) -> str:
        return f"{_VIRTUAL_WORKSPACE_PREFIX}{slug}"

    @staticmethod
    def _is_virtual_workspace_path(path: str) -> bool:
        return str(path or "").startswith(_VIRTUAL_WORKSPACE_PREFIX)

    def _current_workspace_template_key(self) -> str:
        spec = self._last_generated_template_spec or self._selected_document_template_spec()
        return str(getattr(spec, "key", "") or "")

    def _find_selected_file_index(self, path: str) -> int:
        needle = str(path or "")
        for idx, file_info in enumerate(self.selected_files):
            if str(file_info.get("path") or "") == needle:
                return idx
        return -1

    def _upsert_virtual_workspace_file(
        self,
        *,
        path: str,
        name: str,
        content: str,
        marked: bool = True,
        source_type: str | None = None,
        source_assignment_id: int | None = None,
        source_title: str | None = None,
    ) -> bool:
        normalized_path = str(path or "").strip()
        if source_type is None:
            st = "atlas_research"
            said = int((self._latest_merged_atlas_info or {}).get("assignment_id") or 0)
            stitle = str((self._latest_merged_atlas_info or {}).get("title") or "")
        else:
            st = str(source_type or "").strip() or "other"
            said = int(source_assignment_id or 0)
            stitle = str(source_title or "")
        payload = {
            "name": str(name or "Virtual document"),
            "path": normalized_path,
            "is_folder": False,
            "size": len(content or ""),
            "modified": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "marked": bool(marked),
            "virtual": True,
            "content": str(content or "").strip(),
            "source_type": st,
            "source_assignment_id": said,
            "source_title": stitle,
        }
        existing_idx = self._find_selected_file_index(normalized_path)
        if existing_idx >= 0:
            self.selected_files[existing_idx].update(payload)
            item = self.file_list.item(existing_idx)
            if item is not None:
                item.setData(Qt.ItemDataRole.UserRole, self.selected_files[existing_idx])
                row_widget = self.file_list.itemWidget(item)
                if row_widget is not None:
                    checkbox = row_widget.findChild(QCheckBox)
                    if checkbox is not None:
                        checkbox.blockSignals(True)
                        checkbox.setChecked(bool(marked))
                        checkbox.blockSignals(False)
            self._on_workspace_state_changed()
            return False
        return self.add_file_to_list(payload)

    def add_virtual_file(
        self,
        *,
        name: str,
        content: str,
        source_type: str = "deep_research",
        source_assignment_id: int = 0,
        source_title: str = "",
        marked: bool = True,
        path_slug: str | None = None,
    ) -> bool:
        """
        Add or replace a virtual file in the Workspace list (no on-disk path).
        Returns True if a new row was added, False if an existing virtual path was refreshed.
        """
        slug = str(path_slug or "").strip()
        if not slug:
            base = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(name or "virtual").strip()).strip("._-") or "virtual"
            if not base.lower().endswith(".md"):
                base = f"{base}.md"
            slug = base[:200]
        vpath = self._virtual_workspace_path(slug)
        return self._upsert_virtual_workspace_file(
            path=vpath,
            name=name,
            content=content,
            marked=marked,
            source_type=source_type,
            source_assignment_id=source_assignment_id,
            source_title=source_title,
        )

    def _matching_atlas_assignments(self) -> list[dict]:
        list_assignments = getattr(self.db, "agent_list_assignments", None)
        if not callable(list_assignments):
            return []
        workspace_name = str(self._current_workspace_name or "").strip()
        template_key = self._current_workspace_template_key()
        if not workspace_name and not template_key:
            return []
        rows = list_assignments(assignee_code="atlas", requester_code="navi", limit=100) or []
        matches: list[dict] = []
        for row in rows:
            context = self._json_object(row.get("context_json"))
            if str(context.get("kind") or "").strip() != "workspace_template_research_gaps":
                continue
            context_workspace = str(context.get("workspace_name") or "").strip()
            context_template = str(context.get("template_key") or "").strip()
            if workspace_name and context_workspace and context_workspace != workspace_name:
                continue
            if template_key and context_template and context_template != template_key:
                continue
            matches.append(row)
        status_rank = {"done": 0, "awaiting_review": 1, "in_progress": 2, "queued": 3, "blocked": 4}
        matches.sort(key=lambda row: (status_rank.get(str(row.get("status") or "").strip().lower(), 9), -int(row.get("id") or 0)))
        return matches

    def _format_project_artifact_for_workspace(self, artifact_type: str, content_json: str) -> str:
        artifact_type = str(artifact_type or "").strip()
        data = self._json_object(content_json)
        if artifact_type == "research_brief":
            return str(data.get("markdown_body") or "").strip()
        if artifact_type in {"research_brief_grok", "synthesis_grok", "synthesis_chatgpt", "user_research_feedback"}:
            return str(data.get("content") or content_json or "").strip()
        if artifact_type == "web_research_brief":
            lines = []
            query = str(data.get("query") or "").strip()
            if query:
                lines.append(f"Query: {query}")
                lines.append("")
            for finding in data.get("findings") or []:
                claim = str((finding or {}).get("claim") or "").strip()
                if claim:
                    lines.append(f"- Finding: {claim}")
            sources = data.get("sources") or []
            if sources:
                lines.append("")
                lines.append("Sources:")
                for source in sources:
                    title = str((source or {}).get("title") or "Source").strip()
                    url = str((source or {}).get("url") or "").strip()
                    lines.append(f"- {title} | {url}")
            return "\n".join(lines).strip()
        if artifact_type == "internal_retrieval_brief":
            lines = []
            query = str(data.get("query") or "").strip()
            if query:
                lines.append(f"Query: {query}")
                lines.append("")
            for result in data.get("results") or []:
                title = str((result or {}).get("title") or "Result").strip()
                excerpt = str((result or {}).get("excerpt") or "").strip()
                lines.append(f"- [{title}] {excerpt}")
            return "\n".join(lines).strip()
        return str(content_json or "").strip()

    def _resolve_latest_atlas_research_packet(self) -> tuple[str, str, int, str] | None:
        assignment_rows = self._matching_atlas_assignments()
        if not assignment_rows:
            return None
        list_artifacts = getattr(self.db, "agent_list_artifacts", None)
        get_project_artifacts = getattr(self.db, "get_artifacts_for_project", None)
        for assignment in assignment_rows:
            assignment_id = int(assignment.get("id") or 0)
            assignment_title = str(assignment.get("title") or "Atlas research").strip()
            result_summary = str(assignment.get("result_summary_md") or "").strip()
            artifact_rows = list_artifacts(assignment_id=assignment_id, limit=100) if callable(list_artifacts) else []
            project_id = 0
            for row in artifact_rows:
                if str(row.get("artifact_type") or "").strip() != "deep_research_project":
                    continue
                project_id = int(self._json_object(row.get("content_json")).get("project_id") or 0)
                if project_id:
                    break
            if project_id and callable(get_project_artifacts):
                project_artifacts = list(get_project_artifacts(project_id) or [])
                preferred_types = [
                    "research_brief",
                    "research_brief_grok",
                    "synthesis_chatgpt",
                    "synthesis_grok",
                    "web_research_brief",
                    "internal_retrieval_brief",
                ]
                for preferred_type in preferred_types:
                    for _artifact_id, artifact_type, content_json, _file_path, _created_at in reversed(project_artifacts):
                        if str(artifact_type or "").strip() != preferred_type:
                            continue
                        rendered = self._format_project_artifact_for_workspace(artifact_type, content_json)
                        if not rendered:
                            continue
                        lines = [
                            f"# Atlas Research Merge - {assignment_title}",
                            "",
                            f"Assignment: A-{assignment_id:04d}",
                            f"Linked Deep Research Project: {project_id}",
                        ]
                        if result_summary:
                            lines.extend(["", "## Assignment Summary", "", result_summary])
                        lines.extend(["", "## Imported Research", "", rendered])
                        return (
                            f"Atlas Research A-{assignment_id:04d}.md",
                            "\n".join(lines).strip(),
                            assignment_id,
                            assignment_title,
                        )
            for row in artifact_rows:
                if str(row.get("artifact_type") or "").strip() != "agent_reply":
                    continue
                content_md = str(row.get("content_md") or "").strip()
                if not content_md:
                    continue
                lines = [
                    f"# Atlas Research Merge - {assignment_title}",
                    "",
                    f"Assignment: A-{assignment_id:04d}",
                ]
                if result_summary:
                    lines.extend(["", "## Assignment Summary", "", result_summary])
                lines.extend(["", "## Imported Research", "", content_md])
                return (
                    f"Atlas Research A-{assignment_id:04d}.md",
                    "\n".join(lines).strip(),
                    assignment_id,
                    assignment_title,
                )
        return None

    def _update_template_gap_summary(self):
        if not hasattr(self, "template_gap_summary") or self.template_gap_summary is None:
            return
        lines: list[str] = []
        resolved = self._resolved_gap_snapshot_from_baseline()
        self._resolved_gap_snapshot = resolved
        resolved_provenance = self._resolved_gap_provenance(resolved)
        baseline = self._previous_gap_snapshot or {}
        has_baseline = any(bool(baseline.get(key)) for key in ("unresolved_fields", "research_gaps", "user_questions"))
        if has_baseline:
            lines.append("Gap delta since previous run:")
            lines.append(
                f"- Unresolved fields: {len(baseline.get('unresolved_fields', []))} -> {len(self._current_unresolved_fields)}"
            )
            lines.append(
                f"- Researchable gaps: {len(baseline.get('research_gaps', []))} -> {len(self._current_research_gaps)}"
            )
            lines.append(
                f"- Client/user questions: {len(baseline.get('user_questions', []))} -> {len(self._current_user_questions)}"
            )
            lines.append("")
        if any(resolved.get(key) for key in ("unresolved_fields", "research_gaps", "user_questions")):
            lines.append("Resolved since previous run:")
            for key in resolved.get("unresolved_fields", []):
                note = str(resolved_provenance.get("unresolved_fields", {}).get(str(key)) or "").strip()
                suffix = f" ({note})" if note else ""
                lines.append(f"- Unresolved field cleared: {self._template_label_for_key(key)} [{key}]{suffix}")
            for item in resolved.get("research_gaps", []):
                note = str(resolved_provenance.get("research_gaps", {}).get(str(item)) or "").strip()
                suffix = f" ({note})" if note else ""
                lines.append(f"- Research gap cleared: {item}{suffix}")
            for item in resolved.get("user_questions", []):
                note = str(resolved_provenance.get("user_questions", {}).get(str(item)) or "").strip()
                suffix = f" ({note})" if note else ""
                lines.append(f"- Client/user question cleared: {item}{suffix}")
            lines.append("")
        if self._current_template_evidence_map:
            lines.append("Template evidence coverage:")
            for key, value in self._current_template_evidence_map.items():
                lines.append(f"- {self._template_label_for_key(key)} [{key}]: {value}")
            lines.append("")
        if self._current_unresolved_fields:
            lines.append("Unresolved template fields:")
            for key in self._current_unresolved_fields:
                lines.append(f"- {self._template_label_for_key(key)} [{key}]")
            lines.append("")
        if self._current_research_gaps:
            lines.append("Researchable gaps:")
            for item in self._current_research_gaps:
                lines.append(f"- {item}")
            lines.append("")
        if self._current_user_questions:
            lines.append("Questions for you / the client:")
            for item in self._current_user_questions:
                lines.append(f"- {item}")
            lines.append("")
        if self._current_template_validation_issues:
            lines.append("Template validation issues:")
            for item in self._current_template_validation_issues:
                lines.append(f"- {item}")
        text = "\n".join(lines).strip()
        self.template_gap_summary.setVisible(bool(text))
        self.template_gap_summary.setPlainText(text)
        self.send_research_gaps_btn.setEnabled(bool(self._current_research_gaps))
        self.copy_user_questions_btn.setEnabled(bool(self._current_user_questions))
        self.export_question_packet_btn.setEnabled(bool(self._current_user_questions or self._current_unresolved_fields))

    def _atlas_assignment_title(self) -> str:
        spec = self._last_generated_template_spec
        if spec is not None:
            return f"Research gaps for {spec.display_name}"
        return "Research gaps for template document"

    def _atlas_assignment_brief(self) -> str:
        spec = self._last_generated_template_spec
        title = self._atlas_assignment_title()
        lines = [
            title,
            "",
            "Goal:",
            str(getattr(self._last_task_spec, "goal", "") or "(unspecified)"),
            "",
        ]
        if spec is not None:
            lines.extend(
                [
                    f"Template: {spec.display_name}",
                    f"Template key: {spec.key}",
                    "",
                ]
            )
        if self._current_research_gaps:
            lines.append("Research gaps to fill from public guidance / best practice:")
            lines.extend(f"- {item}" for item in self._current_research_gaps)
            lines.append("")
        if self._current_unresolved_fields:
            lines.append("Template fields still unresolved:")
            lines.extend(f"- {self._template_label_for_key(key)} [{key}]" for key in self._current_unresolved_fields)
            lines.append("")
        if self._current_user_questions:
            lines.append("Client/user-specific questions still open (do not answer from public research):")
            lines.extend(f"- {item}" for item in self._current_user_questions)
            lines.append("")
        if self._current_template_evidence_map:
            lines.append("Current evidence map from source documents:")
            for key, value in self._current_template_evidence_map.items():
                lines.append(f"- {self._template_label_for_key(key)} [{key}]: {value}")
            lines.append("")
        lines.append("Deliverable:")
        lines.append("- findings")
        lines.append("- gaps")
        lines.append("- recommended next queries")
        lines.append("- cite sources with URLs")
        return "\n".join(lines).strip()

    def send_research_gaps_to_atlas(self):
        if not self._current_research_gaps:
            self.status_label.setText("No research gaps are available to send.")
            return
        try:
            assignment_id = self.db.agent_create_assignment(
                title=self._atlas_assignment_title(),
                brief_md=self._atlas_assignment_brief(),
                requester_code="navi",
                assignee_code="atlas",
                priority=3,
                due_date=None,
                status="queued",
                context_json={
                    "kind": "workspace_template_research_gaps",
                    "workspace_name": self._current_workspace_name,
                    "template_key": str(getattr(self._last_generated_template_spec, "key", "") or ""),
                    "research_gaps": list(self._current_research_gaps),
                    "unresolved_fields": list(self._current_unresolved_fields),
                    "user_questions": list(self._current_user_questions),
                },
            )
            if not assignment_id:
                self.status_label.setText("Could not create Atlas assignment.")
                return
            self.db.agent_add_artifact(
                artifact_type="workspace_template_gap_analysis",
                assignment_id=int(assignment_id),
                title=f"Workspace template gap analysis A-{int(assignment_id):04d}",
                content_md=(self.template_gap_summary.toPlainText() or "").strip(),
                content_json={
                    "research_gaps": list(self._current_research_gaps),
                    "user_questions": list(self._current_user_questions),
                    "unresolved_fields": list(self._current_unresolved_fields),
                    "evidence_map": dict(self._current_template_evidence_map),
                },
            )
            if self._current_user_questions or self._current_unresolved_fields:
                self.db.agent_add_artifact(
                    artifact_type="workspace_question_packet",
                    assignment_id=int(assignment_id),
                    title=f"Workspace question packet A-{int(assignment_id):04d}",
                    content_md=self._build_question_packet_markdown(),
                    content_json={
                        "user_questions": list(self._current_user_questions),
                        "unresolved_fields": list(self._current_unresolved_fields),
                        "research_gaps": list(self._current_research_gaps),
                    },
                )
            tid = create_assignment_thread(
                self.db,
                assignment_id=int(assignment_id),
                assignee_code="atlas",
                reason="workspace_template_research_gaps",
                actor_code="navi",
                context_json={"source": "workspace_template_research_gaps"},
            )
            if tid:
                prime_assignment_handoff(
                    self.db,
                    assignment_id=int(assignment_id),
                    thread_id=int(tid),
                    force=True,
                )
            self.status_label.setText(f"Sent research gaps to Atlas as assignment A-{int(assignment_id):04d}")
        except Exception as e:
            logger.exception("Could not send research gaps to Atlas: %s", e)
            self.status_label.setText(f"Error sending research gaps to Atlas: {e}")

    def copy_user_questions(self):
        if not self._current_user_questions:
            self.status_label.setText("No user questions are available to copy.")
            return
        text = "\n".join(f"- {item}" for item in self._current_user_questions)
        QApplication.clipboard().setText(text)
        self.status_label.setText(f"Copied {len(self._current_user_questions)} user question(s)")

    def _build_question_packet_markdown(self) -> str:
        spec = self._last_generated_template_spec
        title = spec.display_name if spec is not None else "Template Document"
        lines = [
            f"# Missing Information Packet — {title}",
            "",
            "Use this packet to collect the remaining document-specific information that could not be safely inferred from the source materials.",
            "",
        ]
        if self._current_unresolved_fields:
            lines.append("## Unresolved Template Fields")
            lines.append("")
            for key in self._current_unresolved_fields:
                lines.append(f"- {self._template_label_for_key(key)} [{key}]")
            lines.append("")
        if self._current_user_questions:
            lines.append("## Questions For You / The Client")
            lines.append("")
            for item in self._current_user_questions:
                lines.append(f"- {item}")
            lines.append("")
        if self._current_research_gaps:
            lines.append("## Research Gaps Already Identified")
            lines.append("")
            lines.append(
                "These items appear fillable from public guidance, standards, or best practice research rather than requiring client-specific answers:"
            )
            lines.append("")
            for item in self._current_research_gaps:
                lines.append(f"- {item}")
            lines.append("")
        return "\n".join(lines).strip()

    def export_question_packet(self):
        if not self._current_user_questions and not self._current_unresolved_fields:
            self.status_label.setText("No question packet is available to export.")
            return
        default_name = f"workspace_questions_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Question Packet",
            default_name,
            "Word Document (*.docx);;PDF (*.pdf);;Markdown Files (*.md);;Text Files (*.txt);;All Files (*)"
        )
        if not file_path:
            self.status_label.setText("Question packet export cancelled")
            return
        try:
            exported_path = export_markdownish_document(
                title="Workspace Question Packet",
                text=self._build_question_packet_markdown(),
                file_path=file_path,
                selected_filter=selected_filter,
            )
            self.status_label.setText(f"Question packet exported to {os.path.basename(exported_path)}")
        except Exception as e:
            logger.error(f"Error exporting question packet: {e}")
            self.status_label.setText(f"Error exporting question packet: {str(e)}")

    def merge_latest_atlas_research(self) -> bool:
        packet = self._resolve_latest_atlas_research_packet()
        if not packet:
            self.status_label.setText("No Atlas research results are ready to merge for this workspace.")
            return False
        name, content, assignment_id, assignment_title = packet
        self._latest_merged_atlas_info = {
            "assignment_id": int(assignment_id),
            "title": str(assignment_title or ""),
            "name": str(name or ""),
        }
        added = self._upsert_virtual_workspace_file(
            path=self._virtual_workspace_path(f"atlas-research-a-{assignment_id:04d}.md"),
            name=name,
            content=content,
            marked=True,
        )
        action = "Merged" if added else "Refreshed"
        self.status_label.setText(f"{action} Atlas research from assignment A-{assignment_id:04d}")
        return True

    def _refresh_saved_workspaces(self):
        current_id = self._current_workspace_id
        items = []
        workspace_state_list = getattr(self.db, "workspace_state_list", None)
        if callable(workspace_state_list):
            try:
                items = workspace_state_list()
            except Exception:
                items = []
        if not isinstance(items, list):
            items = []
        self._saved_workspaces = items
        if not hasattr(self, "saved_workspace_combo") or self.saved_workspace_combo is None:
            return
        self.saved_workspace_combo.blockSignals(True)
        self.saved_workspace_combo.clear()
        self.saved_workspace_combo.addItem("Unsaved session", None)
        for item in items:
            nm = str(item.get("name") or "")
            is_related = bool(item.get("related_set_member"))
            if is_related:
                cnt = item.get("related_set_companions_count") or 0
                has_art = bool(item.get("has_related_set_artifacts"))
                badge = " 🟣 [Related Set]" + (f" ({cnt})" if cnt else "") + (" 📋" if has_art else "")
                nm = nm + badge  # Phase 4 continuation micro (post cross-refs/sources extension): tiniest visual upgrade of main Workspace list badge to match 🟣 preview callout + doc notes. Now extended with count from db for richer note (one-more micro). Pure string addition in existing render; no logic/IO change.
            self.saved_workspace_combo.addItem(nm, int(item.get("id") or 0))
            if is_related:
                # Autonomous one-more micro (Phase 4 related sets continuation): tiny richer tooltip note on the 🟣 [Related Set] badge in the primary saved workspace list (main UI surface).
                # Provides immediate traceability hint (cross-refs, manifest, consistency via cluster) without cluttering the combo text. Reuses existing related_set_member flag + Qt data role + new count; zero effect for non-set items; smallest 5-line delta.
                idx = self.saved_workspace_combo.count() - 1
                cnt = item.get("related_set_companions_count") or 0
                has_art = bool(item.get("has_related_set_artifacts"))
                tip = "🟣 Related Document Set member — see 'Related Document Set Cross-References' + Historical Sources Used in the document; Manifest + Summary written to client folder on export for full traceability and style consistency." + (f" ({cnt} companions via cluster.)" if cnt else "") + (" Artifacts (manifest + summary) persisted in saved workspace." if has_art else "")
                # Autonomous next micro-increment (Phase 4, chained no-pause after db parse enhancement): tiniest enrichment of the existing tooltip for 🟣 badge in main saved Workspace list. If the persisted cross_ref_section (from sources append in member's doc) is present on the item, append a compact excerpt of the actual "Companion to ... Other set members..." relationship listing. Provides real per-set-member cross-refs note at-a-glance in list (without changing badge text or layout). Defensive; short slice; reuses new db key. Zero impact non-sets. Directly implements "simple Related Set badge or note in the main Workspace list for generated set members".
                try:
                    cr = item.get("related_set_cross_ref_section")
                    if cr:
                        excerpt = str(cr).strip()[:180].replace("\n", " ")
                        if excerpt:
                            tip += " | " + excerpt
                except Exception:
                    pass
                self.saved_workspace_combo.setItemData(idx, tip, Qt.ItemDataRole.ToolTipRole)
        if current_id is not None:
            idx = self.saved_workspace_combo.findData(int(current_id))
            if idx >= 0:
                self.saved_workspace_combo.setCurrentIndex(idx)
        self.saved_workspace_combo.blockSignals(False)

    def _restore_workspace_on_startup(self):
        restored = False
        workspace_state_get_last_used = getattr(self.db, "workspace_state_get_last_used", None)
        if callable(workspace_state_get_last_used):
            try:
                last_used = workspace_state_get_last_used()
                if last_used:
                    restored = self._load_workspace_record(last_used, status_prefix="Restored last workspace")
            except Exception as e:
                logger.debug(f"Could not restore last used workspace: {e}")
        if restored:
            return
        workspace_session_load = getattr(self.db, "workspace_session_load", None)
        if callable(workspace_session_load):
            try:
                payload = workspace_session_load()
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            if payload:
                loaded = self._apply_workspace_state(payload, workspace_id=None, workspace_name="")
                if loaded or payload.get("files"):
                    self.status_label.setText(f"Restored last session ({loaded} files)")

    def _load_workspace_record(self, record: dict, *, status_prefix: str = "Loaded workspace") -> bool:
        if not isinstance(record, dict):
            return False
        try:
            payload = json.loads(record.get("state_json") or "{}")
        except Exception:
            payload = {}
        loaded = self._apply_workspace_state(
            payload,
            workspace_id=int(record.get("id") or 0) or None,
            workspace_name=str(record.get("name") or ""),
        )
        self._refresh_saved_workspaces()
        if loaded or payload.get("files"):
            status_text = f"{status_prefix}: {record.get('name', 'workspace')} ({loaded} files)"
            # Autonomous next micro-increment (Phase 4 related document sets, chained after badge/persistence/cross-refs in current 2f4c91b8 state): tiniest "Related Set" note in main Workspace load/status path.
            # When loading a saved workspace that carries related_set_* (from prior set production), append concise visibility note to the status_label (central UI surface for the saved_workspace_combo / main list).
            # Reuses exact payload keys already restored in _apply + set in _workspace_state_payload; defensive (no crash on missing); complements the "🟣 [Related Set]" suffix (and list badges) already in _refresh_saved_workspaces + historical renders.
            # Zero behavior change for non-set saved workspaces; surfaces immediately on load (startup restore or combo select) for generated set members. Chained keep-going (no stop): added the matching short " | Related set cross-references added to Historical Sources Used" (one guarded += line inside the if, reusing the detection condition for tiny status in saved combo path for set workspaces).
            try:
                if payload.get("related_set_companion") or payload.get("related_set_manifest"):
                    status_text = status_text + "  🟣[Related Set member — cross-refs + Manifest/Summary for traceability]"
                    status_text += " | Related set cross-references added to Historical Sources Used"
                    try:
                        comps = payload.get("related_set_companions") or []
                        if comps:
                            status_text += f" ({len([c for c in comps if c])} companions)"
                    except Exception:
                        pass
                    # Keep-going autonomous micro (no stop, after list 📋 badge + historical consistency): tiniest extension inside the saved workspace load status path to explicitly note persisted artifacts (manifest+summary) when present in payload. Reuses detection + adds " + persisted artifacts" for immediate feedback on load from the main Workspace saved list. Defensive, only in set if; uses payload keys (no new IO). Completes the "badge or note in the main Workspace list" traceability loop for generated related sets.
                    if payload.get("related_set_manifest") or payload.get("related_set_summary"):
                        status_text += " + persisted artifacts 📋"
                    # One-more autonomous keep-going micro (Phase 4 list/status for sets, no pause): tiniest excerpt of the actual cross-ref subsection (from payload, which carries the rich text from Historical Sources Used extension) appended to the load status for set members. Surfaces real "Companion to ... Other set members..." relationship note in the central status bar (main Workspace UI) right after picking from the saved list. Short slice + guard; defensive; reuses payload key already in restore; zero change non-sets. Compounds the badge/note enhancements.
                    try:
                        cr = payload.get("related_set_cross_ref_section") or payload.get("related_set_cross_ref_note")
                        if cr:
                            ex = str(cr).strip()[:90].replace("\n", " ")
                            if ex:
                                status_text += " | " + ex
                    except Exception:
                        pass
            except Exception:
                pass
            self.status_label.setText(status_text)
            return True
        return False

    def _apply_workspace_state(self, payload: dict, *, workspace_id: int | None, workspace_name: str) -> int:
        self._restoring_workspace_state = True
        try:
            self._clear_workspace_files(reset_saved_workspace=False, clear_collaboration_prompt=False)
            loaded = 0
            missing = 0
            for file_info in payload.get("files") or []:
                item = {
                    "name": str(file_info.get("name") or os.path.basename(str(file_info.get("path") or ""))),
                    "path": str(file_info.get("path") or ""),
                    "is_folder": False,
                    "size": int(file_info.get("size") or 0),
                    "modified": file_info.get("modified"),
                    "marked": bool(file_info.get("marked")),
                    "virtual": bool(file_info.get("virtual")),
                    "content": str(file_info.get("content") or ""),
                    "source_type": str(file_info.get("source_type") or ""),
                    "source_assignment_id": int(file_info.get("source_assignment_id") or 0),
                    "source_title": str(file_info.get("source_title") or ""),
                }
                if self.add_file_to_list(item):
                    loaded += 1
                else:
                    missing += 1
            prompt_key = str(payload.get("prompt_template_key") or "custom")
            doc_template_key = str(payload.get("document_template_key") or "")
            prompt_idx = self.prompt_template_combo.findData(prompt_key)
            if prompt_idx >= 0:
                self.prompt_template_combo.setCurrentIndex(prompt_idx)
            doc_idx = self.document_template_combo.findData(doc_template_key)
            if doc_idx >= 0:
                self.document_template_combo.setCurrentIndex(doc_idx)
            self.max_rounds_spinbox.setValue(int(payload.get("max_rounds") or 3))
            self.include_task_suggestions_checkbox.setChecked(bool(payload.get("include_task_suggestions", True)))
            if getattr(self, "collaboration_prompt_edit", None) is not None:
                self.collaboration_prompt_edit.setPlainText(str(payload.get("collaboration_prompt") or ""))
            # Restore related document set context (from persisted payload in prior micro): re-seed manifest/summary/flag so that after load of a "Related Set" workspace, the manifest viewer, auto-summary, cross-refs on re-gen/export, and status notes all continue to work without re-running Generate Related Set. Smallest safe restore; only when keys present in payload.
            try:
                if payload.get("related_set_manifest"):
                    self._last_related_set_manifest = payload.get("related_set_manifest")
                if payload.get("related_set_summary"):
                    self._last_related_set_summary = payload.get("related_set_summary")
                if payload.get("related_set_companion"):
                    m = getattr(self, "_current_document_metadata", None) or {}
                    if not isinstance(m, dict):
                        m = {}
                    m["related_set_companion"] = payload.get("related_set_companion")
                    m.setdefault("related_set_note", "restored from saved related document set workspace")
                    self._current_document_metadata = m
                if payload.get("related_set_companions"):
                    self._last_related_set_companions = payload.get("related_set_companions")
                if payload.get("related_set_cross_ref_section"):
                    # Chained keep-going micro (tiniest after adding the key to payload): prefer persisted exact rich cross-ref section (full Companion+Other members listing) on load of saved set workspace for perfect fidelity in templates/metadata without rebuild. 1-line, defensive, inside existing related restore.
                    try:
                        mm = getattr(self, "_current_document_metadata", None) or {}
                        if not isinstance(mm, dict): mm = {}
                        mm["related_set_cross_ref_section"] = str(payload.get("related_set_cross_ref_section"))[:600]
                        self._current_document_metadata = mm
                    except Exception:
                        pass
                if payload.get("related_set_sources_extended"):
                    # Keep-going micro (no pause after payload persist of marker): tiniest restore of the sources append extension flag (from the Historical Sources Used + Related Document Set Cross-References subsection injection) into live metadata. Completes roundtrip for the tiny marker added in sources block + payload; enables any post-load consumers to know cross-refs subsection is present in the doc without re-compute. 3-line defensive inside existing block; zero change non-sets.
                    try:
                        mm = getattr(self, "_current_document_metadata", None) or {}
                        if not isinstance(mm, dict): mm = {}
                        mm["related_set_sources_extended"] = str(payload.get("related_set_sources_extended"))
                        self._current_document_metadata = mm
                    except Exception:
                        pass
                # Autonomous keep-going micro (no pause after dialog note): tiniest defensive enrichment inside the *existing* related restore block. When companions or companion flag present on load of saved related-set workspace, compute+set a compact cross-ref note (reusing same phrasing pattern as sources append) into _current_document_metadata["related_set_cross_ref_note"]. This makes restored set workspaces immediately provide the detailed sibling listing to template renders (via _default_document_metadata + footer/placeholder) + any metadata consumers, achieving full symmetry between markdown "Historical Sources Used" cross-refs and template path. Uses only live restored attrs; zero change if not set-related; ~6 lines.
                # Chained one-more autonomous micro (this increment): tiniest extension inside same restore try: after short note, also seed the rich full "related_set_cross_ref_section" (from shared _build helper, which leverages the just-restored _last_related_set_companions + derive for exact "Companion to ... Other set members..." text). Ensures on reload of set workspace the template path (and preview consumers) get the complete subsection text immediately (parity with post-gen). Purely additive 3-line guarded setdefault; defensive; only sets when helper produces for sets.
                try:
                    if payload.get("related_set_companion") or payload.get("related_set_manifest"):
                        comps = payload.get("related_set_companions") or getattr(self, "_last_related_set_companions", None) or []
                        o = [str(c) for c in comps if c][:3]
                        extra = (". Other set members: " + "; ".join(o) + (" (and more)" if len(comps)>3 else "")) if o else ""
                        base = "the primary reference in the shared historical cluster"
                        # reuse a simple base if possible from payload (not full hist scan here for smallest)
                        note = "🟣 Related Document Set member — companion via the same historical cluster for traceability and consistency (see extended 'Historical Sources Used' section with Related Document Set Cross-References for siblings" + extra + "). _Related_Set_Manifest.txt + Summary also in client folder on export."
                        m = getattr(self, "_current_document_metadata", None) or {}
                        if not isinstance(m, dict): m = {}
                        m.setdefault("related_set_cross_ref_note", note)
                        if not m.get("related_set_note"):
                            m["related_set_note"] = note[:280]
                        try:
                            rich = self._build_related_set_cross_ref()
                            if rich:
                                m.setdefault("related_set_cross_ref_section", str(rich).strip()[:600])
                        except Exception:
                            pass
                        # Keep-going chained micro (no stop after count in sources/preview): tiniest metadata polish for restored sets — seed companions_count (from restored list) into meta for downstream badge/status/count consumers on load (e.g. future UI or template). Mirrors sources/preview enrichment; fully defensive + reuses comps var; only for sets.
                        try:
                            m["related_set_companions_count"] = len([c for c in comps if c]) if comps else 0
                        except Exception:
                            m.setdefault("related_set_companions_count", 0)
                        self._current_document_metadata = m
                except Exception:
                    pass
            except Exception:
                pass
            # Billing Depth chained micro (smallest safe restore, mirroring related_set persistence): re-seed _last_billing_artifact from saved workspace payload so that after load, the billing summary can still be exported to client folder/GDrive without re-generation. Purely additive inside the outer related-restore try (no new try needed); defensive; only affects flows that had billing artifact for their set. Zero impact otherwise.
            try:
                if payload.get("billing_set_artifact"):
                    self._last_billing_artifact = payload.get("billing_set_artifact")
            except Exception:
                pass
            self._current_workspace_id = workspace_id
            self._current_workspace_name = str(workspace_name or payload.get("name") or "").strip()
            if self._current_workspace_id is not None and hasattr(self.db, "workspace_state_set_last_used"):
                self.db.workspace_state_set_last_used(self._current_workspace_id)
            if missing:
                self.status_label.setText(f"Loaded {loaded} files ({missing} missing)")
            return loaded
        finally:
            self._restoring_workspace_state = False
            self._on_workspace_state_changed()
            self._sync_workspace_file_list_empty_state()

    def _clear_workspace_files(self, *, reset_saved_workspace: bool = True, clear_collaboration_prompt: bool = True):
        self.file_list.clear()
        self.selected_files = []
        self._seen_paths.clear()
        self._current_file_contents = {}
        self._current_markdown = ""
        self._current_template_blocks = {}
        self._current_document_metadata = {}
        self._current_template_evidence_map = {}
        self._current_unresolved_fields = []
        self._current_research_gaps = []
        self._current_user_questions = []
        self._previous_gap_snapshot = {}
        self._resolved_gap_snapshot = {}
        self._latest_merged_atlas_info = {}
        self._last_generated_template_spec = None
        self._last_related_set_manifest = None
        self._last_related_set_summary = None
        self._last_billing_artifact = None  # Billing Depth: reset on workspace clear (parity with related set artifacts); keeps state clean.
        # do not reset _gdrive_auto_upload_enabled here (user preference should survive clear; now persisted in app_preferences for Related Document Set export workflows)
        self._current_template_validation_issues = []
        self.preview_text.clear()
        if hasattr(self, "template_gap_summary") and self.template_gap_summary is not None:
            self.template_gap_summary.clear()
            self.template_gap_summary.setVisible(False)
        self.grok_text.clear()
        self.chatgpt_text.clear()
        self.save_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.extract_tasks_button.setEnabled(False)
        # Clear named-workspace identity before clearing the prompt field: prompt textChanged
        # triggers autosave, and upserting under the old name with empty selected_files would
        # overwrite the saved workspace JSON on disk.
        if reset_saved_workspace:
            self._current_workspace_id = None
            self._current_workspace_name = ""
            if hasattr(self.db, "workspace_state_set_last_used"):
                self.db.workspace_state_set_last_used(None)
        if clear_collaboration_prompt and getattr(self, "collaboration_prompt_edit", None) is not None:
            self.collaboration_prompt_edit.clear()
        self._sync_workspace_file_list_empty_state()

    def clear_workspace(self):
        self._clear_workspace_files(reset_saved_workspace=True)
        self._refresh_saved_workspaces()
        self.status_label.setText("Workspace cleared")
        self._on_workspace_state_changed()

    def save_workspace(self):
        if self._current_workspace_name:
            self._save_workspace_with_name(self._current_workspace_name)
            return
        self.save_workspace_as()

    def save_workspace_as(self):
        name, ok = QInputDialog.getText(
            self,
            "Save Workspace",
            "Workspace name:",
            text=self._current_workspace_name or "",
        )
        if not ok or not str(name or "").strip():
            self.status_label.setText("Workspace save cancelled")
            return
        self._save_workspace_with_name(str(name).strip())

    def _save_workspace_with_name(self, name: str):
        workspace_state_upsert = getattr(self.db, "workspace_state_upsert", None)
        if not callable(workspace_state_upsert):
            self.status_label.setText("Workspace persistence is unavailable")
            return
        self._current_workspace_name = str(name or "").strip()
        payload = self._workspace_state_payload()
        payload["name"] = self._current_workspace_name
        try:
            workspace_id = workspace_state_upsert(name=self._current_workspace_name, state=payload)
            self._current_workspace_id = int(workspace_id or 0) or None
        except Exception:
            self.status_label.setText("Workspace persistence is unavailable")
            return
        workspace_state_set_last_used = getattr(self.db, "workspace_state_set_last_used", None)
        if callable(workspace_state_set_last_used):
            workspace_state_set_last_used(self._current_workspace_id)
        self._refresh_saved_workspaces()
        self.status_label.setText(f"Workspace saved: {self._current_workspace_name}")

    def load_selected_workspace(self):
        workspace_id = self.saved_workspace_combo.currentData() if getattr(self, "saved_workspace_combo", None) is not None else None
        if workspace_id in (None, "", 0):
            self.status_label.setText("Select a saved workspace to load")
            return
        workspace_state_get = getattr(self.db, "workspace_state_get", None)
        if not callable(workspace_state_get):
            self.status_label.setText("Workspace persistence is unavailable")
            return
        record = workspace_state_get(int(workspace_id))
        if not record:
            self.status_label.setText("Saved workspace not found")
            return
        self._load_workspace_record(record)

    def import_template_pair(self):
        try:
            machine_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select machine-readable template",
                "",
                "Word Documents (*.docx);;All Files (*)",
            )
            if not machine_path:
                self.status_label.setText("Template import cancelled")
                return
            inferred_human = self._infer_human_template_pair(machine_path)
            human_path = inferred_human
            if not human_path:
                human_path, _ = QFileDialog.getOpenFileName(
                    self,
                    "Select matching human-readable template",
                    "",
                    "Word Templates (*.docx *.dotx);;All Files (*)",
                )
            if not human_path:
                self.status_label.setText("Template import cancelled")
                return
            spec = import_workspace_template_pair(machine_path=machine_path, human_path=human_path)
            self._refresh_document_templates()
            idx = self.document_template_combo.findData(spec.key)
            if idx >= 0:
                self.document_template_combo.setCurrentIndex(idx)
            self.status_label.setText(
                f"Imported template: {spec.display_name} ({len(getattr(spec, 'fill_targets', []) or [])} fill target(s))"
            )
            self._on_workspace_state_changed()
        except Exception as e:
            logger.exception("Template import failed: %s", e)
            self.status_label.setText(f"Template import failed: {e}")

    def _infer_human_template_pair(self, machine_path: str) -> str:
        directory = os.path.dirname(os.path.abspath(str(machine_path or "")))
        filename = os.path.basename(str(machine_path or ""))
        stem, _ext = os.path.splitext(filename)
        normalized = stem
        candidates = []
        if normalized.endswith("_machine"):
            base = normalized[: -len("_machine")]
            candidates.extend([f"{base}_human.docx"])
        if normalized.endswith(" - Machine Readable"):
            base = normalized[: -len(" - Machine Readable")]
            candidates.extend([f"{base} - Human Readable.docx", f"{base} - CF Template.dotx"])
        for candidate in candidates:
            full = os.path.join(directory, candidate)
            if os.path.exists(full):
                return full
        return ""

    def show_file_context_menu(self, position):
        item = self.file_list.itemAt(position)
        if item is None:
            return
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.file_list.mapToGlobal(position))
        if action != remove_action:
            return
        row = self.file_list.row(item)
        file_info = item.data(Qt.ItemDataRole.UserRole) or {}
        path = str(file_info.get("path") or "")
        if path and not bool(file_info.get("virtual")) and not self._is_virtual_workspace_path(path):
            path = os.path.abspath(path)
        removed = self.file_list.takeItem(row)
        if removed is not None and 0 <= row < len(self.selected_files):
            self.selected_files.pop(row)
        if path:
            self._seen_paths.discard(path)
        self.status_label.setText(f"Removed {file_info.get('name', 'file')}")
        self._on_workspace_state_changed()
        self._sync_workspace_file_list_empty_state()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        try:
            self.status_label.setText("Processing dropped files...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            
            valid_files_count = 0
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                
                # Skip if path is empty (e.g., web URLs dragged from browser)
                if not path:
                    continue
                    
                # Skip if file doesn't exist
                if not os.path.exists(path):
                    continue

                if os.path.isdir(path):
                    valid_files_count += self._add_folder_recursive(path)
                else:
                    file_info = {
                        'name': os.path.basename(path),
                        'path': path,
                        'is_folder': False,
                        'size': os.path.getsize(path) if os.path.isfile(path) else 0,
                        'modified': datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S"),
                        'marked': False
                    }
                    if self.add_file_to_list(file_info):
                        valid_files_count += 1
                
            self.status_label.setText(f"Added {valid_files_count} files")
            self.progress_bar.setVisible(False)
        except Exception as e:
            self.status_label.setText(f"Error processing files: {str(e)}")
            self.progress_bar.setVisible(False)

    def select_files(self):
        try:
            dialog = QFileDialog(self)
            dialog.setFileMode(QFileDialog.FileMode.AnyFile)
            dialog.setOption(QFileDialog.Option.ShowDirsOnly, False)
            if dialog.exec():
                added = 0
                for path in dialog.selectedFiles():
                    if os.path.isdir(path):
                        added += self._add_folder_recursive(path)
                        continue
                    file_info = {
                        'name': os.path.basename(path),
                        'path': path,
                        'is_folder': False,
                        'size': os.path.getsize(path) if os.path.isfile(path) else 0,
                        'modified': datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S"),
                        'marked': False
                    }
                    if self.add_file_to_list(file_info):
                        added += 1
                self.status_label.setText(f"Added {added} files")
        except Exception as e:
            self.status_label.setText(f"Error selecting files: {str(e)}")

    def select_folder(self):
        try:
            folder = QFileDialog.getExistingDirectory(self, "Select folder to add")
            if not folder:
                return
            self.status_label.setText("Scanning folder…")
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            QApplication.processEvents()
            added = self._add_folder_recursive(folder)
            self.status_label.setText(f"Added {added} files from folder")
        except Exception as e:
            self.status_label.setText(f"Error selecting folder: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)

    def _is_supported_workspace_file(self, path: str) -> bool:
        ext = os.path.splitext(path or "")[1].lower()
        return ext in _WORKSPACE_SUPPORTED_EXTS

    def _add_folder_recursive(self, folder_path: str) -> int:
        folder = os.path.abspath(folder_path)
        if not os.path.isdir(folder):
            return 0
        added = 0
        seen_in_run = 0
        for base, _dirs, files in os.walk(folder):
            for fn in files:
                if added >= _WORKSPACE_MAX_FILES_PER_FOLDER:
                    self.status_label.setText(
                        f"Folder import capped at {_WORKSPACE_MAX_FILES_PER_FOLDER} files (skipped the rest)"
                    )
                    return added
                full = os.path.abspath(os.path.join(base, fn))
                if not self._is_supported_workspace_file(full):
                    continue
                if full in self._seen_paths:
                    continue
                try:
                    size = os.path.getsize(full) if os.path.isfile(full) else 0
                    modified = datetime.fromtimestamp(os.path.getmtime(full)).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    size = 0
                    modified = None
                file_info = {
                    "name": os.path.basename(full),
                    "path": full,
                    "is_folder": False,
                    "size": size,
                    "modified": modified,
                    "marked": False,
                }
                if self.add_file_to_list(file_info):
                    added += 1
                seen_in_run += 1
                if self.progress_bar and self.progress_bar.isVisible():
                    # Nonlinear but cheap feedback: just cycle 0-100 as we scan.
                    self.progress_bar.setValue((seen_in_run * 7) % 100)
                    if seen_in_run % 50 == 0:
                        QApplication.processEvents()
        return added

    def add_file_to_list(self, file_info) -> bool:
        if file_info.get("is_folder"):
            return False
        raw_path = file_info.get("path") or ""
        is_virtual = bool(file_info.get("virtual")) or self._is_virtual_workspace_path(raw_path)
        full_path = str(raw_path or "").strip() if is_virtual else os.path.abspath(raw_path)
        if not full_path:
            return False
        if not is_virtual and not os.path.exists(full_path):
            return False
        if full_path in self._seen_paths:
            return False
        self._seen_paths.add(full_path)
        file_info["path"] = full_path
        file_info["virtual"] = is_virtual

        icon = "[AI]" if is_virtual else "FILE"
        item_text = file_info['name'][:30] + "..." if len(file_info['name']) > 30 else file_info['name']
        item = QListWidgetItem()
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)
        checkbox = QCheckBox()
        checkbox.setMinimumSize(22, 22)
        checkbox.setChecked(file_info['marked'])
        checkbox.stateChanged.connect(lambda state: self.toggle_mark(file_info, state))
        layout.addWidget(checkbox)
        label = QLabel(f"{icon} {item_text}")
        label.setToolTip(file_info['name'])
        label.setMinimumHeight(24)
        layout.addWidget(label)
        layout.addStretch()
        widget.setMinimumHeight(40)
        item.setSizeHint(QSize(0, 44))
        item.setData(Qt.ItemDataRole.UserRole, file_info)
        self.file_list.addItem(item)
        self.file_list.setItemWidget(item, widget)
        self.selected_files.append(file_info)
        self._on_workspace_state_changed()
        self._sync_workspace_file_list_empty_state()
        return True

    def toggle_mark(self, file_info, state):
        file_info['marked'] = state == Qt.CheckState.Checked.value
        self._on_workspace_state_changed()

    def add_rag_results(self, results):
        # Placeholder for RAG search results
        try:
            self.status_label.setText("Adding RAG search results...")
            self.progress_bar.setVisible(True)
            for doc in results[:5]:
                file_info = {
                    'name': doc.metadata.get('source', 'unknown'),
                    'path': doc.metadata.get('source', ''),
                    'is_folder': False,
                    'size': 0,
                    'modified': None,
                    'marked': True
                }
                self.add_file_to_list(file_info)
            self.status_label.setText(f"Added {len(results)} RAG results")
            self.progress_bar.setVisible(False)
        except Exception as e:
            self.status_label.setText(f"Error adding RAG results: {str(e)}")
            self.progress_bar.setVisible(False)

    def on_file_selected(self, item):
        file_info = item.data(Qt.ItemDataRole.UserRole)
        if not file_info or file_info['is_folder']:
            return
        try:
            self.status_label.setText("Loading file preview...")
            self.progress_bar.setVisible(True)
            text_extensions = {'.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml', '.csv'}
            pdf_extensions = {'.pdf'}
            doc_extensions = {'.docx'}
            file_ext = os.path.splitext(file_info['name'])[1].lower()
            
            # Get file content with caching
            content = self.get_file_content(file_info)
            
            preview_content = content[:5000]
            if len(content) > 5000:
                preview_content += f"\n\n... (showing first 5000 characters of {len(content)} total)"
            self.preview_text.setPlainText(preview_content)
            self.status_label.setText("File preview loaded")
            self.progress_bar.setVisible(False)
        except Exception as e:
            self.preview_text.setPlainText(f"Error loading preview: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")
            self.progress_bar.setVisible(False)

    def populate_relevant_historical_examples(self, document_type: str, objective: str = ""):
        """Phase 1 retrieval surface + Phase 4 auto-use: Populate the clickable historical examples list (live on input change; strong refs auto-injected on Generate)."""
        if not hasattr(self, "historical_examples_list") or self.historical_examples_list is None:
            return
        self.historical_examples_list.clear()
        if not document_type:
            return
        try:
            docs = get_relevant_past_documents(doc_type=document_type, query=objective[:150] if objective else "", raw_context=objective, limit=6)
            # Micro-increment (follows auto-inject IMPL 2f4c91b8): if strong historical ref injected (auto or via _inject), also pull 1-2 "related" from same client + similar doc_type/regulatory theme cluster. Reuses get_relevant_past_documents + extract + _ref_match exactly; surfaces ONLY in this existing list (light [related] label + italic green). Available for additional inject via existing menu/_inject path. Smallest-safe, no new UI.
            try:
                ref_terms = extract_reference_terms(objective or "") if objective else []
                has_strong_ref = bool(ref_terms) or bool(re.search(r'\[?\s*historical\s+reference|reference\s*:', objective or "", re.IGNORECASE))
                if has_strong_ref and docs:
                    strong = None
                    for cand in docs:
                        if getattr(cand, '_ref_match', False) or any((t in (getattr(cand, 'name', '') or '').lower()) for t in ref_terms):
                            strong = cand
                            break
                    if strong:
                        ch = getattr(strong, 'client_hint', None)
                        dt = getattr(strong, 'doc_type', None)
                        regs = getattr(strong, 'regulatory_tags', []) or []
                        theme_q = " ".join([r for r in regs if r][:3]) if regs else (dt or "")
                        related_cands = get_relevant_past_documents(client_hint=ch, doc_type=dt, query=(theme_q or "")[:120], limit=3, raw_context=objective)
                        seen = set(getattr(dd, 'source_id', None) or getattr(dd, 'name', '') for dd in docs)
                        added = 0
                        for rc in related_cands:
                            rid = getattr(rc, 'source_id', None) or getattr(rc, 'name', '')
                            if rid and rid not in seen:
                                setattr(rc, '_related_match', True)
                                docs.append(rc)
                                seen.add(rid)
                                added += 1
                                if added >= 2:
                                    break
            except Exception:
                pass
            for d in docs:
                reason = []
                if d.client_hint:
                    reason.append(f"client:{d.client_hint}")
                if d.doc_type:
                    reason.append(f"type:{d.doc_type}")
                if d.regulatory_tags:
                    reason.append("reg")
                # Lightweight "ref" indicator reuses core _ref_match (set by get_relevant_past_documents when raw_context has marker via extract_reference_terms) + heuristic fallback
                ref_hit = getattr(d, '_ref_match', False)
                try:
                    obj_l = (objective or "").lower()
                    if not ref_hit and ("historical reference" in obj_l or "reference:" in obj_l) and d.name and d.name.lower()[:20] in obj_l:
                        ref_hit = True
                except Exception:
                    pass
                if ref_hit:
                    reason.append("ref")
                if getattr(d, '_related_match', False):
                    reason.append("related")
                # Phase 4 related set micro: detect flag persisted in DocumentRecord.extra (seeded on companion export via _seed_...) for light suffix badge only on generated set members. Defensive, zero effect otherwise.
                related_set_hit = False
                try:
                    ex = getattr(d, "extra", None) or {}
                    if isinstance(ex, dict) and ex.get("related_set_member"):
                        related_set_hit = True
                        if "set" not in reason:
                            reason.append("set")
                except Exception:
                    pass
                # Put "ref" first, then related (light)
                if "ref" in reason:
                    reason = ["ref"] + [x for x in reason if x != "ref"]
                elif "related" in reason:
                    reason = ["related"] + [x for x in reason if x != "related"]
                item_text = f"{d.name} | {d.client_hint or 'N/A'} | {d.year or '?'} | {'+'.join(reason)}"
                if "ref" in reason:
                    item_text = "[ref] " + item_text
                elif "related" in reason:
                    item_text = "[related] " + item_text  # light label for cluster siblings
                if related_set_hit:
                    # One-more autonomous micro (Phase 4 related sets, chained after sources cross-refs + saved-list count badge): tiniest extension of badge in *main historical list* (primary Workspace reference surface) to show companions count when present (reuses exact pattern + key from saved combo + seed extra). Makes "Related Set" visibility richer for generated set members in the list, consistent across UI surfaces. Purely additive string; defensive; zero change for non-sets or records without count in extra.
                    cnt = 0
                    try:
                        ex = getattr(d, "extra", None) or {}
                        if isinstance(ex, dict):
                            cnt = int(ex.get("related_set_companions_count") or 0)
                    except Exception:
                        cnt = 0
                    b = "  🟣[related set member]"
                    if cnt:
                        b += f" ({cnt})"
                    # Keep-going tiniest chained micro (Phase 4, after saved list artifacts flag): also surface 📋 in the historical list badge for generated set members when "set_manifest" present in seeded extra (reuses existing key from _seed; no new persistence). Makes Related Set visibility + artifacts note consistent in *both* primary Workspace lists (saved combo + historical refs). Pure string, defensive, zero non-set impact. Smallest delta.
                    try:
                        ex = getattr(d, "extra", None) or {}
                        if isinstance(ex, dict) and (ex.get("set_manifest") or ex.get("related_set_manifest")):
                            b += " 📋"
                    except Exception:
                        pass
                    item_text = item_text + b  # light suffix indicator (per task: smallest, italic-style, reuses list item render)
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, {
                    "source": d.source,
                    "source_id": d.source_id,
                    "source_path": d.source_path,
                    "name": d.name,
                    "doc_type": d.doc_type,
                    "client_hint": d.client_hint,
                    "project_hint": d.project_hint,
                    "year": d.year,
                    "regulatory_tags": d.regulatory_tags,
                    "ref_match": "ref" in reason,
                    "related_match": "related" in reason,  # enables easy additional injection + dialog label
                    "related_set_member": related_set_hit,
                    # Phase 4 autonomous micro (keep going, no stop after sources cross-refs + list badges + viewer + filename): tiniest extension to carry the seeded related_set_note (from DocumentRecord.extra) into the item data for the details dialog. Enables per-member "Related Set Cross-References" note visibility when clicking historical set members in the Workspace list. Reuses ex already in scope + existing related_set_hit path; zero new behavior/IO for non-set or missing note. Defensive.
                    "related_set_note": ( (ex.get("related_set_note") or ex.get("related_set_cross_ref_note")) if related_set_hit and isinstance(ex, dict) else None ),
                    # Autonomous chained one-more micro (Phase 4, after primary cross-refs extension + details copy): tiniest addition here to also expose the rich full "related_set_cross_ref_section" (the exact "Companion to ... Other set members: ..." sibling listing from the Historical Sources Used subsection) into dialog data. Ensures details (triggered from main historical Workspace list) can show/copy the complete per-member relationship text for traceability. Defensive; pulls from ex if seeded (present in some export paths); zero impact non-sets. Smallest delta advancing "note in the main Workspace list" for set members.
                    "related_set_cross_ref_section": ((ex.get("related_set_cross_ref_section") or ex.get("related_set_cross_ref_note")) if related_set_hit and isinstance(ex, dict) else None),
                })
                if "ref" in reason:
                    from PyQt6.QtGui import QColor
                    item.setForeground(QColor("#4fc3f7"))
                    from PyQt6.QtGui import QFont
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                elif "related" in reason:
                    from PyQt6.QtGui import QColor
                    item.setForeground(QColor("#81c784"))  # muted green, light/italic surface only (no new UI)
                    from PyQt6.QtGui import QFont
                    f = item.font()
                    f.setItalic(True)
                    item.setFont(f)
                if related_set_hit:
                    from PyQt6.QtGui import QColor
                    item.setForeground(QColor("#ba68c8"))  # light purple italic for generated related set companions
                    from PyQt6.QtGui import QFont
                    f = item.font()
                    f.setItalic(True)
                    item.setFont(f)
                    # Keep-going autonomous micro (no stop after saved-list cross-ref tooltip enhancement): tiniest hover note on the 🟣 related set badge items in the historical examples list (the other primary Workspace list surface). Reuses the cross_ref_section already in the item data (seeded from DocumentRecord + sources append); shows compact excerpt on hover for immediate traceability without opening dialog. Purely additive, defensive, matches the main saved combo list behavior just added. Smallest delta.
                    try:
                        cr = ex.get("related_set_cross_ref_section") or ex.get("related_set_cross_ref_note") if isinstance(ex, dict) else None
                        if cr:
                            exs = str(cr).strip()[:140].replace("\n", " ")
                            if exs:
                                item.setToolTip("🟣 Related Document Set member — see 'Related Document Set Cross-References' + Historical Sources Used in the document for siblings/relationships + traceability (Manifest + Summary on export). " + exs)
                    except Exception:
                        pass
                self.historical_examples_list.addItem(item)
        except Exception:
            pass

    def _on_historical_example_clicked(self, item):
        """Show detail dialog for the clicked historical DocumentRecord + open cloud source option."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        dlg = QDialog(self)
        dlg.setWindowTitle("Historical Document Details")
        dlg.setMinimumWidth(450)
        layout = QVBoxLayout(dlg)

        name = data.get('name', 'Unknown')
        if data.get("ref_match"):
            name = f"<font color='#4fc3f7'>[ref] {name}</font>"
        elif data.get("related_match"):
            name = f"<font color='#81c784'>[related] {name}</font>"
        if data.get("related_set_member"):
            name = f"<font color='#ba68c8'>🟣[related set member] {name}</font>" if not (data.get("ref_match") or data.get("related_match")) else name + " <font color='#ba68c8'>🟣[related set member]</font>"
        layout.addWidget(QLabel(f"<b>{name}</b>"))
        layout.addWidget(QLabel(f"Client: {data.get('client_hint', 'N/A')} | Project: {data.get('project_hint', 'N/A')} | Year: {data.get('year', '?')}"))
        layout.addWidget(QLabel(f"Type: {data.get('doc_type', 'N/A')}"))
        tags = ", ".join(data.get('regulatory_tags', [])) or "None"
        layout.addWidget(QLabel(f"Regulatory Tags: {tags}"))
        if data.get("ref_match"):
            layout.addWidget(QLabel("<b><font color='#4fc3f7'>Matched via reference bias</font></b>"))
        elif data.get("related_match"):
            layout.addWidget(QLabel("<i><font color='#81c784'>Related to strong injected reference (same client + theme cluster)</font></i>"))
        if data.get("related_set_member"):
            layout.addWidget(QLabel("<i><font color='#ba68c8'>🟣 Related set member — auto-generated companion (seeded from export; shares cluster with siblings for consistency)</font></i>"))
        if data.get("related_set_note") or data.get("related_set_cross_ref_section") or data.get("related_set_cross_ref_note"):
            # Tiniest follow-on (Phase 4 keep-going): surface the actual cross-ref / set note (e.g. "Companion to the Validation Plan... Other set members: ...") from the seeded record directly in the existing details dialog for any historical related set member clicked in the list. Reuses the just-extended data key; fully defensive string display; provides the "note in the main Workspace list" for generated set members without new widgets or clicks beyond the established details flow.
            # Autonomous one-more micro (this increment): prefer the richest available key (full "Related Document Set Cross-References" subsection text with sibling listings/relationships produced inside Historical Sources Used append) for both the visible preview (longer slice) and the Copy button payload. Reuses existing keys from the data dict extension above + prior seeding; falls back gracefully; ensures users clicking 🟣 items in the main list get the complete traceability text (e.g. "Companion to the Validation Plan via the same... Other set members: ..."). Zero behavior change for non-sets or records without richer data.
            note_val = str(data.get("related_set_cross_ref_section") or data.get("related_set_cross_ref_note") or data.get("related_set_note") or "")
            layout.addWidget(QLabel(f"<i><font color='#ba68c8'>Set cross-ref: {note_val[:450]}</font></i>"))
            # Autonomous chained micro-increment (Phase 4, no pause after sources cross-refs + dialog note surface): tiniest "Copy full" button in details dialog for set members. Enables easy clipboard capture of the complete "Companion to ... via same historical cluster..." relationship listing (produced by the Historical Sources Used extension) for pasting into client notes/emails/other deliverables. Reuses QApplication (already top-imported), QPushButton; only for items with note (defensive); zero impact on non-set historical docs or other dialogs. Directly amplifies the traceability value of the per-member cross-refs note.
            if len(note_val) > 5:
                cbtn = QPushButton("📋 Copy full Set Cross-Reference")
                cbtn.setMaximumWidth(200)
                cbtn.clicked.connect(lambda checked=False, nt=note_val: QApplication.clipboard().setText(nt))
                layout.addWidget(cbtn)
        layout.addWidget(QLabel(f"Source: {data.get('source', '?')} | ID: {data.get('source_id', '?')}"))

        btn_layout = QHBoxLayout()
        open_btn = QPushButton("Open in Cloud")
        open_btn.clicked.connect(lambda: self._open_cloud_source(data, dlg))
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        btn_layout.addWidget(open_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        dlg.exec()

    def _open_cloud_source(self, data, parent_dlg=None):
        """Open the original cloud file (GDrive web link or show Dropbox path)."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtWidgets import QMessageBox

        source = data.get("source")
        sid = data.get("source_id")
        spath = data.get("source_path")

        if source == "gdrive" and sid:
            url = f"https://drive.google.com/file/d/{sid}/view"
            QDesktopServices.openUrl(QUrl(url))
            if parent_dlg:
                parent_dlg.accept()
        elif source == "dropbox" and spath:
            QMessageBox.information(
                self,
                "Dropbox File",
                f"Dropbox path:\n{spath}\n\nOpen this path in your Dropbox app or web."
            )
            if parent_dlg:
                parent_dlg.accept()
        else:
            QMessageBox.information(self, "Source", "Cloud source information available in the diagnostic reports.")

    def _show_workspace_historical_context_menu(self, pos):
        """Lightweight right-click menu for Workspace historical list (symmetry with CoS)."""
        item = self.historical_examples_list.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        from PyQt6.QtWidgets import QMenu, QApplication
        from PyQt6.QtGui import QAction

        menu = QMenu(self)
        if data.get("ref_match"):
            prefix = "[ref] "
        elif data.get("related_match"):
            prefix = "[related] "
        else:
            prefix = ""
        inject_action = QAction(f"{prefix}Inject reference", self)
        inject_action.triggered.connect(lambda: self._inject_workspace_historical(data))
        menu.addAction(inject_action)

        copy_action = QAction(f"{prefix}Copy reference", self)
        copy_action.triggered.connect(lambda: self._copy_workspace_historical_reference(data))
        menu.addAction(copy_action)

        # One-more autonomous micro (Phase 4, chained after post-gen status cross-ref note + details copy btn): tiniest guarded "Copy Set Cross-References" in *existing historical list context menu*. Directly exposes the rich "Companion to ... Other set members..." text (from data seeded in populate + _seed + sources append) for clipboard, only for set members (reuses same keys as details dialog). Reuses QApplication import+clipboard pattern + QAction style already in this func; zero impact / no menu item for non-sets. High-leverage usability for cross-refs visibility without opening dialog.
        if data.get("related_set_member") or data.get("related_set_cross_ref_section") or data.get("related_set_note"):
            cr = str(data.get("related_set_cross_ref_section") or data.get("related_set_cross_ref_note") or data.get("related_set_note") or "")[:600]
            if cr:
                copy_cr_action = QAction("📋 Copy Set Cross-References (from Historical Sources Used)", self)
                copy_cr_action.triggered.connect(lambda checked=False, nt=cr: QApplication.clipboard().setText(nt))
                menu.addAction(copy_cr_action)

        details_action = QAction(f"{prefix}Show details", self)
        details_action.triggered.connect(lambda: self._on_historical_example_clicked(item))
        menu.addAction(details_action)

        # Phase 4 micro-increment (Generate Related Set): menu item in existing Relevant Historical Documents area.
        # Smallest addition; handler (below) reuses live cluster data for pre-fill (now with doc-type presets for common companions). Defensive no-op when absent.
        gen_related_action = QAction("Generate Related Set (presets for common types + reuse cluster for companions)", self)
        gen_related_action.triggered.connect(self._generate_related_set)
        menu.addAction(gen_related_action)

        # Chained autonomous micro (direct export): second menu item in same existing area for "one-click direct export to client folder" (Phase 4 roadmap).
        # Reuses cluster client scan + dir logic from export_markdown; writes _current_markdown (or template render) directly to computed client subfolder path. No dialog. Defensive.
        quick_export_action = QAction("Quick-export last doc to client folder (from cluster)", self)
        quick_export_action.triggered.connect(self._quick_export_to_client_folder)
        menu.addAction(quick_export_action)

        # Autonomous next micro-increment (Phase 4 related document sets): simple "manifest viewer" entry directly in the *existing* Relevant Historical Documents context menu. (Chained polish: label + title now reflect full rich content: manifest + auto Summary + per-member Cross-Refs from sources append.)
        # Provides immediate in-UI visibility / "badge-like" access to the generated set (companions list + shared cluster + export note) without any layout changes, new lists, or persistent widgets.
        # Clicking shows QMessageBox (already imported) with the manifest text when present (from last _generate_related_set). Defensive no-op otherwise; reuses exact QAction/menu pattern of the Generate Related Set item above. Smallest safe delta.
        view_manifest_action = QAction("View Related Set Manifest + Summary + Cross-Refs (for last Generate Related Set)", self)
        view_manifest_action.setToolTip("🟣 Opens the Related Document Set viewer (Manifest + auto-generated Summary + exact 'Related Document Set Cross-References' subsection with Companion to the Validation Plan via the same historical cluster for traceability and consistency + Other set members sibling listings/relationships produced inside each member's 'Historical Sources Used' via sources append block extension). Cross-refs excerpt also in quick-export status + list badges/tooltips. Enables quick traceability without leaving the Workspace list menu.")
        view_manifest_action.triggered.connect(self._view_related_set_manifest)
        menu.addAction(view_manifest_action)

        # Billing Depth micro-increment (first high-leverage per deferred roadmap priority, smallest safe extension of Generate Related Set + historical cluster + client folder machinery): optional "Generate Billing for Set" action in the *exact same* context menu. Reuses cluster scan, client resolution, export paths, GDrive upload, persistence, and style guidance derive (via duck-type _H adaptation already present for derive calls). Produces lightweight billing summary/manifest (time/deliverable snapshot + cluster style notes) without side effects on invoice_drafts or requiring templates. Written alongside manifests/summaries on quick/manual/GDrive export. Fully defensive/optional; no-op unless qualifying cluster present. Chained keep-going: also included in saved workspace payload/restore.
        billing_action = QAction("Generate Billing Summary for Set (cluster time + deliverables + style refs; optional)", self)
        billing_action.setToolTip("💰 Billing Depth: using the locked historical cluster from Generate Related Set (or any strong ref+related cluster), produce a billing artifact/summary (retainer progress or time line items) for consistency with prior client billing artifacts. Auto-included in client folder exports (local + GDrive if enabled). No full invoice generated; review in Billing tab for actual drafts.")
        billing_action.triggered.connect(self._generate_billing_for_set)
        menu.addAction(billing_action)

        # Autonomous next micro-increment (Phase 4 GDrive + setting): add toggle for the just-implemented auto-upload feature directly in the *existing* context menu (zero new surfaces).
        # Controls the _gdrive_auto_upload_enabled flag (session lifetime for smallest delta; integrates with prior client/cluster paths). Updates status on toggle. Defensive, always shown.
        gdrive_toggle_action = QAction("Toggle GDrive auto-upload (cluster exports to client folder; persisted)", self)  # Phase 4 continuation: reflects new persistence of the Related Set export setting via app_preferences (tiny label update only)
        def _toggle_gdrive_auto():
            cur = getattr(self, "_gdrive_auto_upload_enabled", True)
            new_val = not cur
            self._gdrive_auto_upload_enabled = new_val
            # Phase 4 smallest persistence addition (chained micro for related sets): save the toggle choice so it survives session. Uses the new setter; complements the load in __init__. Defensive try.
            try:
                set_gdrive_auto_upload_enabled(new_val)
            except Exception:
                pass
            state = "ENABLED" if self._gdrive_auto_upload_enabled else "DISABLED (local-only)"
            try:
                if hasattr(self, "status_label"):
                    self.status_label.setText(f"GDrive client folder auto-upload: {state}")
            except Exception:
                pass
        gdrive_toggle_action.triggered.connect(_toggle_gdrive_auto)
        menu.addAction(gdrive_toggle_action)

        menu.exec(self.historical_examples_list.viewport().mapToGlobal(pos))

    def _inject_workspace_historical(self, data):
        # Minimal defensive inject: append reference to the collaboration prompt edit
        # so it becomes part of the objective/instructions for the next generation run.
        try:
            if hasattr(self, "collaboration_prompt_edit"):
                ref = f"\n[Historical reference: {data.get('name', '')} ({data.get('doc_type', '')}, {data.get('year', '')})]"
                current = self.collaboration_prompt_edit.toPlainText()
                self.collaboration_prompt_edit.setPlainText((current + ref).strip())
                self.collaboration_prompt_edit.setFocus()
        except Exception:
            pass

    def _copy_workspace_historical_reference(self, data):
        try:
            from core.file_handler import format_compact_historical_context
            from PyQt6.QtWidgets import QApplication
            class _Mini:
                def __init__(self, d): 
                    self.name = d.get("name", "")
                    self.doc_type = d.get("doc_type", "")
                    self.client_hint = d.get("client_hint", "")
                    self.project_hint = d.get("project_hint", "")
                    self.year = d.get("year")
                    self.regulatory_tags = d.get("regulatory_tags", [])
            mini = _Mini(data)
            text = format_compact_historical_context([mini], max_items=1).strip()
            if text:
                QApplication.clipboard().setText(text)
        except Exception:
            pass

    def _generate_related_set(self):
        """Phase 4 (Workspace Production Engine) micro-increment: smallest "Generate Related Set" action.
        Menu item lives in existing Relevant Historical Documents context menu (no layout/UI bloat).
        When strong ref + related cluster present in live list: collect exact cluster data, pre-fill
        collaboration_prompt_edit with a natural companion objective (1 of 2 possible) + explicit historical
        reference injections for the full cluster, snapshot the *exact same* flagged items back into the list
        (preserving ref_match/related_match for downstream scans). Now auto-starts the Generate Draft workflow (reuses run_ai_collaboration_workflow after task spec set) so companion launches immediately using identical cluster (for style guidance, refs, sources section + related set summary note). Reuses populate data format, injection string patterns, color/font logic, derive/format helpers indirectly.
        Presets support (autonomous addition): lightweight hardcoded doc_type->companions map consulted in prefill for common types (Validation Plan/SOP/etc.), fallback to heuristic; also drives project context + set metadata + quick_export suffix in chained micros.
        Multi-companion extension (this micro): when preset defines 2+ companions, tiny inner helper + guarded second call inside handler pre-fills *and* triggers generation for the second as well (parallel async workers, both receive identical cluster snapshot/injections for set-wide consistency). Fully defensive (no-op if only 1 companion or no cluster/preset).
        Manifest prep (for next autonomous micro): builds _last_related_set_manifest for traceability note in client exports.
        Defensive: silent no-op (no behavior change) if no qualifying cluster or no _current state. One handler only.
        """
        try:
            if not hasattr(self, "historical_examples_list") or self.historical_examples_list is None:
                return
            cluster_datas = []
            has_ref = False
            has_related = False
            for i in range(self.historical_examples_list.count()):
                it = self.historical_examples_list.item(i)
                d = it.data(Qt.ItemDataRole.UserRole) or {}
                if d.get("ref_match") or d.get("related_match"):
                    cluster_datas.append(dict(d))  # shallow copy of data
                    if d.get("ref_match"):
                        has_ref = True
                    if d.get("related_match"):
                        has_related = True
            if not (has_ref and has_related and len(cluster_datas) >= 2):
                return  # defensive - no cluster, zero side effects
            self._last_related_set_manifest = None
            self._last_related_set_summary = None
            # Lightweight related document set presets (Phase 4 micro-increment): small hardcoded mapping of common doc types to typical companion deliverables.
            # Consulted when "Generate Related Set" triggers on strong cluster for matching doc_type; uses preset objectives for companions (instead of or ahead of heuristic).
            # Fully defensive: falls back to existing heuristic for unknown/no-preset types. Tiny, inside handler only; no UI, no new files.
            related_set_presets = {
                "validation plan": ["Risk Management File", "Design Traceability Matrix"],
                "verification plan": ["Risk Management File", "Design Traceability Matrix"],
                "validation protocol": ["Risk Management File", "Design Verification Report"],
                "sop": ["Training Plan", "Process Validation Protocol"],
                "standard operating procedure": ["Training Plan", "Process Validation Protocol"],
                "risk management file": ["Hazard Analysis", "FMEA Update"],
                "risk management": ["Clinical Evaluation Plan", "Usability Engineering File"],
                "design traceability matrix": ["Risk Management File", "Verification Protocol"],
                "clinical evaluation": ["Risk Management File", "PMS Plan"],
                "procedure": ["Work Instruction", "Training Material"],
                "process validation": ["IQ/OQ/PQ Protocols", "Validation Report"],
            }
            # Infer companion from strong ref's doc_type (tiny inline, no registry load); consult preset first if available
            strong = next((d for d in cluster_datas if d.get("ref_match")), cluster_datas[0])
            ch = strong.get("client_hint") or "client"
            ph = strong.get("project_hint") or ""
            dt = strong.get("doc_type") or "document"
            dt_l = str(dt).lower()
            # Determine target_companions from preset (or fallback list of 1); enables second guarded call only for real presets with 2+
            target_companions = []
            preset_used = False
            for k, comps in related_set_presets.items():
                if k in dt_l:
                    target_companions = comps[:]
                    preset_used = True
                    break
            if not target_companions:
                if any(k in dt_l for k in ["validation", "protocol", "verification"]):
                    target_companions = ["Risk Management File (or Design Verification companion) for same client/project using cluster"]
                elif "risk" in dt_l:
                    target_companions = ["Clinical Evaluation Plan (or Cybersecurity companion) using cluster"]
                elif any(k in dt_l for k in ["sop", "procedure", "process"]):
                    target_companions = ["Work Instruction or Training Material (SOP companion derivative)"]
                else:
                    target_companions = [f"Companion {dt} deliverable (cross-referenced regulatory artifact from cluster)"]
            # Tiny Related Set Manifest prep (autonomous chained micro-increment): capture full planned set + cluster now (while live) for later inclusion in client folder export as traceability note. Defensive.
            try:
                ts = datetime.now().strftime('%Y-%m-%d %H:%M')
                cluster_names = [f"{d.get('name','')} ({d.get('doc_type','')}, {d.get('year','')})" for d in cluster_datas]
                man = [
                    "=== Related Document Set Manifest ===",
                    f"Generated: {ts}",
                    f"Base document type: {dt} | Client: {ch}" + (f" | Project: {ph}" if ph else ""),
                    "Companions (all share exact historical cluster for style/structure/reference consistency):",
                ]
                for idx, c in enumerate(target_companions):
                    man.append(f"  {idx+1}. {c}")
                man.append("Shared historical cluster (strong ref + related for traceability):")
                for cn in cluster_names:
                    man.append(f"  - {cn}")
                man.append("All set members + this manifest auto-exported to same client folder (via Generate Related Set + quick export).")
                self._last_related_set_manifest = "\n".join(man)
                # Tiny autonomous chained micro (Phase 4 keep-going): also persist the raw target_companions list (from preset or heuristic) for more reliable cross-refs / badge / future surfaces without re-parsing manifest text. Smallest 1-line; defensive (list or None); used in downstream post-gen extension if wanted. Zero impact if not set.
                self._last_related_set_companions = list(target_companions) if target_companions else None
            except Exception:
                self._last_related_set_manifest = None
                try:
                    self._last_related_set_companions = None
                except Exception:
                    pass
            # Tiny inner helper (smallest addition enabling multi-companion): encapsulates the prefill + cluster snapshot restore + status + run_ai call.
            # Allows clean first + (guarded) second call inside this handler for presets with 2+ companions. Both launches get *exact same* cluster_datas for set consistency. No dupe of logic.
            def _do_prefill_and_auto_start(companion_desc):
                # Exact injection strings matching the auto-inject + style scan expectations
                injections = []
                for d in cluster_datas:
                    nm = d.get("name", "")
                    dty = d.get("doc_type", "")
                    yr = d.get("year", "")
                    injections.append(f"[Historical reference: {nm} ({dty}, {yr})]")
                cluster_block = "\n" + "\n".join(injections)
                new_obj = (
                    f"Draft the {companion_desc} following the precise style/structure/tone/traceability from the historical cluster.\n"
                    f"Client: {ch}." + (f" Project: {ph}." if ph else "") + " Reuse the exact conventions observed in prior work.\n"
                    f"Cluster references (for style guidance injection + sources section):\n{cluster_block}\n\n"
                    "[Optional: add project-specific details above. The list below is a snapshot of the source cluster for this run - auto-generating the companion now (Generate Related Set reuses cluster for all in set).]"
                )
                # Block to avoid populate wipe during prefill; then manually restore cluster snapshot (key to reuse exact flags on next generate)
                if hasattr(self, "collaboration_prompt_edit") and self.collaboration_prompt_edit is not None:
                    self.collaboration_prompt_edit.blockSignals(True)
                    self.collaboration_prompt_edit.setPlainText(new_obj)
                    self.collaboration_prompt_edit.blockSignals(False)
                # Restore exact cluster data+UI treatment into list (reuses render patterns from populate; ensures generate scans will see ref/related)
                if hasattr(self, "historical_examples_list"):
                    self.historical_examples_list.clear()
                    from PyQt6.QtGui import QColor, QFont
                    for d in cluster_datas:
                        reason = []
                        if d.get("client_hint"):
                            reason.append(f"client:{d.get('client_hint')}")
                        if d.get("doc_type"):
                            reason.append(f"type:{d.get('doc_type')}")
                        if d.get("regulatory_tags"):
                            reason.append("reg")
                        if d.get("ref_match"):
                            reason = ["ref"] + [x for x in reason if x != "ref"]
                        elif d.get("related_match"):
                            reason = ["related"] + [x for x in reason if x != "related"]
                        item_text = f"{d.get('name','')} | {d.get('client_hint') or 'N/A'} | {d.get('year') or '?'} | {'+'.join(reason)}"
                        if d.get("ref_match"):
                            item_text = "[ref] " + item_text
                        elif d.get("related_match"):
                            item_text = "[related] " + item_text
                        if d.get("related_set_member"):
                            # Keep-going chained micro (no pause, after main historical badge count): tiniest parallel count support in the cluster_datas snapshot restore path (also populates the historical list during related set gen). Reuses same ex logic; d here is dict from cluster (may carry count via seed/restore). Purely additive, matches prior; zero non-set effect.
                            c = 0
                            try:
                                exx = d.get("extra") or d
                                if isinstance(exx, dict):
                                    c = int(exx.get("related_set_companions_count") or 0)
                            except Exception:
                                c = 0
                            bb = "  🟣[related set member]"
                            if c: bb += f" ({c})"
                            item_text = item_text + bb
                        item = QListWidgetItem(item_text)
                        item.setData(Qt.ItemDataRole.UserRole, d)
                        if d.get("ref_match"):
                            item.setForeground(QColor("#4fc3f7"))
                            f = item.font()
                            f.setBold(True)
                            item.setFont(f)
                        elif d.get("related_match"):
                            item.setForeground(QColor("#81c784"))
                            f = item.font()
                            f.setItalic(True)
                            item.setFont(f)
                        if d.get("related_set_member"):
                            item.setForeground(QColor("#ba68c8"))
                            f = item.font()
                            f.setItalic(True)
                            item.setFont(f)
                            # Autonomous next micro (Phase 4 list enhancement after sources cross-refs, no pause): tiniest addition of actual cross-ref note (the "Companion to ... via same historical cluster... Other set members..." sibling listing produced inside each member's Historical Sources Used) as native tooltip on the 🟣[related set member] items in main Relevant Historical Documents list. Reuses the cross_ref keys already seeded into d/extra by _seed + populate enrichment (exact data used for details dialog + saved combo tooltips). Provides the "simple Related Set note in the main Workspace list" at-a-glance on hover for traceability; zero new widgets, defensive, only mutates set items.
                            try:
                                cr_tip = d.get("related_set_cross_ref_section") or d.get("related_set_cross_ref_note") or d.get("related_set_note") or ""
                                if cr_tip:
                                    item.setToolTip(str(cr_tip).strip()[:280].replace("\n", " "))
                            except Exception:
                                pass
                        self.historical_examples_list.addItem(item)
                if hasattr(self, "status_label"):
                    self.status_label.setText("Auto-starting Generate Draft for companion using locked cluster (exact style/structure/refs via snapshot + prompt injections)")
                # Wire: reuse existing "Generate Draft" path (run_ai_collaboration_workflow) after setting prompt+list snapshot.
                # This auto-starts the workflow for the companion (cluster flows into style guidance derive, ref auto-inject, past_docs pull, "Historical Sources Used", etc).
                # Fully defensive: hasattr guard + outer try/except; early cluster check already no-op'd if absent.
                # Also no-op on missing _current/last state (via hasattr on key attr used by workflow).
                if hasattr(self, "run_ai_collaboration_workflow") and (getattr(self, "_last_task_spec", None) or getattr(self, "_current_markdown", None) or hasattr(self, "collaboration_prompt_edit")):
                    self.run_ai_collaboration_workflow()
            # Invoke first (preserves all prior single-companion behavior exactly), plus guarded second call only when preset defines multiple companions.
            # Second uses dedicated desc mentioning #2 + identical cluster (launches parallel worker; each run_ reads its own captured goal at its call site).
            if preset_used and len(target_companions) > 1:
                rest = ", ".join(target_companions[1:])
                first_desc = f"{target_companions[0]} (related document set preset: also {rest}) for same client/project using cluster"
            else:
                first_desc = target_companions[0] if target_companions else "companion deliverable (from cluster)"
            _do_prefill_and_auto_start(first_desc)
            # The key extension (tiny guarded second call to the *existing prefill+auto-start logic* via helper, inside same handler): auto for second companion when preset multi.
            if preset_used and len(target_companions) > 1:
                second_desc = f"{target_companions[1]} (related document set preset companion #2 of 2, identical historical cluster for set-wide style/structure/reference consistency)"
                _do_prefill_and_auto_start(second_desc)
        except Exception:
            # fully defensive - never affects other UI paths or generation
            pass

    def _generate_billing_for_set(self):
        """Billing Depth micro-increment (autonomous, smallest safe per roadmap deferral of Phase 2 after memory/intel foundation): extend the exact "Generate Related Set" + historical cluster machinery.
        Reuses: cluster_datas scan + has_ref/related check pattern (from _generate_related_set), client_from_ref scan (from _quick_export + export_markdown), duck-type _H adaptation for derive_style (from pre-gen block), self.db for profile/time/deliverables (existing methods), client folder naming/safe (identical), export write patterns (defensive try blocks), GDrive via updated api + _try call, persistence (already wired).
        Actionable only from the historical list context menu (after a strong ref+related cluster or post Generate Related Set). Optional/defensive: silent no-op if no qualifying cluster, no db, or lookup fails. Never mutates invoice_drafts or runs full generate_invoice_draft (avoids template/period side effects).
        Output: in-memory _last_billing_artifact (markdown/text summary/manifest) that gets written to same client_dir as Related_Set_* artifacts on any export (quick, manual, gdrive). Includes: client mode/rate, recent time sample or ready deliverables, prior billing docs from cluster for style match, compact style guidance derived from cluster.
        One more logical micro later in this run will extend with time-entry suggestion surfacing.
        """
        try:
            if not hasattr(self, "historical_examples_list") or self.historical_examples_list is None:
                return
            cluster_datas = []
            client_hint = None
            has_ref = False
            has_related = False
            for i in range(self.historical_examples_list.count()):
                it = self.historical_examples_list.item(i)
                d = it.data(Qt.ItemDataRole.UserRole) or {}
                if d.get("ref_match") or d.get("related_match"):
                    cluster_datas.append(dict(d))
                    if d.get("ref_match"):
                        has_ref = True
                    if d.get("related_match"):
                        has_related = True
                    if not client_hint:
                        client_hint = d.get("client_hint")
            if not (has_ref and has_related and len(cluster_datas) >= 2 and client_hint):
                if hasattr(self, "status_label"):
                    self.status_label.setText("Generate Billing for Set requires a strong ref+related historical cluster (use Generate Related Set first or select items in list)")
                return
            if not hasattr(self, "db") or self.db is None:
                return

            # Resolve client_id from hint (defensive name match; try unified clients then legacy billing_clients)
            client_id = None
            try:
                clist = self.db.clients_list(active_only=False) or []
                ch_l = str(client_hint).lower().strip()
                for c in clist:
                    nm = str(c.get("name", "")).lower().strip()
                    if nm == ch_l or (ch_l and nm.startswith(ch_l[:12])):
                        client_id = c.get("id")
                        break
                if client_id is None:
                    blist = getattr(self.db, "billing_clients_list", lambda **kw: [])(active_only=False) or []
                    for c in blist:
                        nm = str(c.get("name", "")).lower().strip()
                        if nm == ch_l or (ch_l and nm.startswith(ch_l[:12])):
                            client_id = c.get("id")
                            break
            except Exception:
                client_id = None
            if not client_id:
                if hasattr(self, "status_label"):
                    self.status_label.setText(f"Billing summary: could not resolve client id for '{client_hint}' (check Clients tab)")
                return

            lines = [
                "=== Billing Summary / Artifact for Related Document Set ===",
                f"Client: {client_hint} (#{client_id})",
                f"Generated: {datetime.now().isoformat()}",
                f"Source: same historical cluster as document set ({len(cluster_datas)} refs) for billing style + structure consistency with prior client work.",
                "All artifacts (incl. this) auto-placed in client folder on export (local data/workspace_output/<client>/ + optional GDrive).",
            ]

            # Style guidance from cluster (reuses exact duck _H + derive already proven in workspace gen path)
            try:
                hist_docs = []
                for d in cluster_datas:
                    class _H:
                        pass
                    h = _H()
                    for k, default in (("name", ""), ("doc_type", ""), ("client_hint", ""), ("year", None), ("regulatory_tags", []), ("source_path", "")):
                        setattr(h, k, d.get(k, default))
                    setattr(h, "_ref_match", bool(d.get("ref_match")))
                    setattr(h, "_related_match", bool(d.get("related_match")))
                    hist_docs.append(h)
                guidance = derive_style_guidance_from_historical_cluster(hist_docs)
                if guidance:
                    lines.append("")
                    lines.append("Style & Structure Guidance from Historical References (cluster, for billing tone/traceability match):")
                    lines.append(guidance.strip()[:900])
            except Exception:
                pass

            # Note any billing/invoice artifacts already in the cluster (for explicit prior style match)
            try:
                bill_refs = []
                for d in cluster_datas:
                    nm = str(d.get("name", "") + " " + d.get("doc_type", "")).lower()
                    if "invoice" in nm or "billing" in nm or "retainer" in nm or "time entry" in nm:
                        bill_refs.append(d.get("name", "billing-ref")[:60])
                if bill_refs:
                    lines.append("")
                    lines.append("Prior billing-related artifacts in this cluster (style consistency targets):")
                    for br in bill_refs[:4]:
                        lines.append(f"  - {br}")
            except Exception:
                pass

            # Billing profile + mode
            try:
                profile = self.db.get_client_billing_profile(int(client_id)) or getattr(self.db, "billing_client_get", lambda x: None)(int(client_id))
                if profile:
                    mode = str(profile.get("billing_mode") or profile.get("billing_type") or "hourly").lower()
                    rate = profile.get("default_rate")
                    curr = profile.get("currency") or "USD"
                    lines.append("")
                    lines.append(f"Client billing profile: mode={mode}, rate={rate}, currency={curr}")
                    contact = profile.get("billing_contact_name") or profile.get("billing_email")
                    if contact:
                        lines.append(f"Billing contact: {contact}")
            except Exception:
                pass

            # Recent time entries (sample, billable, ~last 45d) or ready deliverables (for retainer/fixed)
            try:
                from datetime import timedelta
                end = datetime.now()
                start = end - timedelta(days=45)
                start_iso = start.isoformat()
                entries = []
                if hasattr(self.db, "time_entries_list"):
                    entries = self.db.time_entries_list(client_id=int(client_id), start_ts=start_iso, limit=30) or []
                billable = [e for e in entries if int(e.get("is_billable") or 0) == 1]
                if billable:
                    lines.append("")
                    lines.append(f"Recent billable time (last ~45d, {len(billable)} entries; full review in Billing tab):")
                    tot_min = 0
                    for e in billable[:6]:
                        m = int(e.get("minutes") or 0)
                        tot_min += m
                        lab = (e.get("deliverable_label") or e.get("work_performed") or "work")[:45]
                        lines.append(f"  - {str(e.get('start_ts',''))[:10]} {m}min @ {e.get('rate_override') or 'default'}: {lab}")
                    lines.append(f"  Sample window total: {tot_min} min (~{tot_min/60.0:.1f}h)")
                # Deliverables for retainer/fixed billing clients
                dels = []
                if hasattr(self.db, "client_deliverables_list"):
                    dels = self.db.client_deliverables_list(int(client_id), status="ready") or []
                    if not dels:
                        dels = self.db.client_deliverables_list(int(client_id)) or []
                if dels:
                    lines.append("")
                    lines.append("Ready / recent deliverables (for invoicing / retainer progress):")
                    for d in dels[:5]:
                        amt = d.get("amount") or 0
                        lines.append(f"  - {d.get('name','deliverable')[:40]}: ${float(amt):,.2f} (status: {d.get('status','?')})")
            except Exception:
                pass

            artifact = "\n".join(lines)
            self._last_billing_artifact = artifact

            if hasattr(self, "status_label"):
                self.status_label.setText(f"Billing artifact generated for set (client {client_hint}). Included on next quick/manual/GDrive export to client folder. (Optional; review full in Billing tab.)")
            # For convenience, also surface a short version in a non-modal info if possible (reuses QMessageBox pattern from manifest viewer but smaller impact: just status is primary)
        except Exception:
            # absolute defensive - never impacts any other path
            pass

    def _quick_export_to_client_folder(self):
        """Autonomous chained Phase 4 micro: smallest one-click "direct export to client folder" (advances roadmap item).
        Added as menu item in same existing Relevant Historical Documents context menu (zero layout, reuses area).
        When _current_markdown (post-gen) + cluster present in list: computes the *exact* client_dir + suggested name using the identical scan/sanitization as export_markdown (lines ~3281), creates dir, writes a timestamped .md (or .docx if template active) directly (no QFileDialog).
        Falls back to markdown write of current content for simplicity/safety. Uses existing export_docx_to_pdf + render if needed for template case. Status + optional notify. Fully defensive (no-op if no doc or no cluster; try/except around all).
        Reuses: cluster scan pattern, client_dir makedirs, render/template paths, _current_* state. No behavior change to manual export buttons.
        Now also writes Related Set Manifest (from _generate_related_set) into client folder when present (tiny traceability note listing companions + cluster).
        """
        try:
            if not getattr(self, "_current_markdown", None) or not self._current_markdown.strip():
                if hasattr(self, "status_label"):
                    self.status_label.setText("No generated document to export")
                return
            # Replicate the minimal proven cluster client scan (from export_markdown) - smallest, no extraction yet
            client_from_ref = None
            dtype_from_ref = None
            if hasattr(self, "historical_examples_list") and self.historical_examples_list:
                for i in range(min(6, self.historical_examples_list.count())):
                    it = self.historical_examples_list.item(i)
                    dd = it.data(Qt.ItemDataRole.UserRole) or {}
                    if dd.get("ref_match") or dd.get("related_match"):
                        client_from_ref = dd.get("client_hint")
                        dtype_from_ref = dd.get("doc_type")
                        break
            if not client_from_ref:
                if hasattr(self, "status_label"):
                    self.status_label.setText("No historical cluster client for direct folder export (use manual Export as... instead)")
                return
            safe = re.sub(r'[^A-Za-z0-9_-]', '', str(client_from_ref))[:30]
            safe_dtype = re.sub(r'[^A-Za-z0-9_-]', '', str(dtype_from_ref or "workspace"))[:25]
            client_dir = os.path.join("data", "workspace_output", safe)
            try:
                os.makedirs(client_dir, exist_ok=True)
            except Exception:
                pass
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            base = f"{safe}_{safe_dtype}_{ts}"
            # Autonomous next micro (direct export for sets): if this doc was generated as related-set companion (seeded by _generate_related_set + post-gen), append lightweight set-aware suffix to filename for easy identification/grouping in client folder. Reuses _current_document_metadata (populated for exactly these cases); smallest 3 lines, defensive, only affects quick_export path (manual Export as... unchanged).
            try:
                if getattr(self, "_current_document_metadata", {}).get("related_set_companion"):
                    base = f"{base}_related-set-companion"
            except Exception:
                pass
            target_path = os.path.join(client_dir, base + ".md")
            # If template active and last spec, prefer docx render into client folder (reuse export paths)
            wrote_docx = False
            if (self._last_generated_template_spec and self._current_template_blocks and
                    getattr(self, "_ensure_template_payload_valid_for_export", lambda: True)()):
                try:
                    target_docx = os.path.join(client_dir, base + ".docx")
                    render_workspace_template_to_docx(
                        spec=self._last_generated_template_spec,
                        template_blocks=self._current_template_blocks,
                        output_path=target_docx,
                        document_metadata=self._current_document_metadata,
                    )
                    target_path = target_docx
                    wrote_docx = True
                    # also optional pdf? skip for smallest (user can use manual for that)
                except Exception:
                    # fall through to md write of current
                    wrote_docx = False
            if not wrote_docx:
                with open(target_path, 'w', encoding='utf-8') as f:
                    f.write(self._current_markdown)
            # Autonomous next micro-increment (Related Set Manifest): tiny text note auto-generated in _generate_related_set (lists full preset companions + shared cluster for traceability). Written here into the client folder on quick-export of any set member. Defensive no-op if absent; reuses client_dir + safe; idempotent across companions. Advances Phase 4 "related document sets" + export.
            try:
                if getattr(self, "_last_related_set_manifest", None):
                    man_name = f"{safe}_Related_Set_Manifest.txt"
                    man_path = os.path.join(client_dir, man_name)
                    with open(man_path, 'w', encoding='utf-8') as mf:
                        mf.write(self._last_related_set_manifest)
            except Exception:
                pass  # non-fatal, never breaks export
            # Phase 4 auto-summary micro (chained): also write the Related Set Summary (now auto-created in post-gen via _make_ helper + manifest) into same client folder on quick-export of set members. Reuses exact client_dir + try pattern + safe prefix of the manifest write above; .md for the summary document. Defensive; only when present (from set production); appears alongside the deliverables + manifest. No change for non-set exports.
            try:
                summ = getattr(self, "_last_related_set_summary", None) or self._make_related_set_summary()
                if summ:
                    sum_name = f"{safe}_Related_Set_Summary.md"
                    sum_path = os.path.join(client_dir, sum_name)
                    with open(sum_path, 'w', encoding='utf-8') as sf:
                        sf.write(summ)
            except Exception:
                pass  # non-fatal, never breaks export
            # Billing Depth micro (chained export write): smallest defensive write of the generated (or restored) billing artifact into the *exact same* client_dir used for manifests/summaries. Mirrors the summary block 1:1 (safe name, try/except non-fatal, .md). Ensures "place them in the client's folder (local + optional GDrive)" for billing artifacts when Generate Billing for Set (or saved set) was used. Zero change if absent.
            try:
                if getattr(self, "_last_billing_artifact", None):
                    bill_name = f"{safe}_Billing_Summary_for_Set.md"
                    bill_path = os.path.join(client_dir, bill_name)
                    with open(bill_path, 'w', encoding='utf-8') as bf:
                        bf.write(self._last_billing_artifact)
            except Exception:
                pass  # non-fatal, never breaks export
            # Keep-going autonomous micro (Phase 4 2f4c91b8, immediately after GDrive cross-ref wiring + sources extension): tiniest parallel local write of the Related Set Cross-References (from seeded metadata or live _build, the exact sibling listing/relationships now inside each member's Historical Sources Used) as .txt artifact in the client folder. Completes full local+ GDrive pack symmetry for set traceability (alongside Manifest + Summary). Defensive; only when cross-ref data present; uses same client_dir/safe; non-fatal. Directly follows the "extend ... cross-refs" + "keep going without stopping".
            try:
                cr_local = None
                try:
                    m = getattr(self, "_current_document_metadata", {}) or {}
                    cr_local = m.get("related_set_cross_ref_section") or self._build_related_set_cross_ref()
                except Exception:
                    cr_local = None
                if cr_local:
                    cr_name = f"{safe}_Related_Set_Cross_References.txt"
                    cr_path = os.path.join(client_dir, cr_name)
                    with open(cr_path, 'w', encoding='utf-8') as cf:
                        cf.write(str(cr_local).strip())
            except Exception:
                pass  # non-fatal, never breaks export
            # Seed for historical list badge (Phase 4 related set visibility micro): only for companions; makes the generated doc appear with [related set member] in Relevant Historical Documents after next populate
            try:
                self._seed_related_set_member_record()
            except Exception:
                pass
            # Phase 4 GDrive upload (this micro): smallest guarded one-liner after local artifacts + cluster guard already passed. Only fires for docs with historical ref cluster in client context.
            try:
                self._try_gdrive_client_folder_upload(client_from_ref, target_path)
            except Exception:
                pass
            # Success
            msg = f"Direct export complete: {os.path.basename(target_path)} -> {client_dir}"
            try:
                meta = getattr(self, "_current_document_metadata", {}) or {}
                if meta.get("related_set_companion"):
                    msg += " (includes Related Document Set Cross-References subsection inside 'Historical Sources Used' for traceability)"
                    msg += " | Related set cross-references added to Historical Sources Used"
                    msg += " (sibling listings + Companion to... relationships for set members)"
                    # One-more autonomous micro-increment (Phase 4, chained no-pause after sources block extension + list/status notes): tiniest addition of the *actual* cross-ref excerpt (the "Companion to the Validation Plan via ... Other set members..." sibling relationship text produced by the Historical Sources Used append) directly into the quick-export success status + notify. Reuses metadata key (or live _build) + short slice pattern from prior list polish; surfaces real per-member traceability note in central UI right after client-folder action for set companions. Fully defensive (only inside the existing companion if; short + replace \n); zero change for non-sets or no data. Smallest delta on export path.
                    try:
                        cr = meta.get("related_set_cross_ref_section") or (getattr(self, "_current_document_metadata", {}) or {}).get("related_set_cross_ref_section")
                        if not cr and hasattr(self, "_build_related_set_cross_ref"):
                            cr = self._build_related_set_cross_ref()
                        if cr:
                            ex = str(cr).strip()[:120].replace("\n", " ")
                            if ex:
                                msg += " | " + ex
                    except Exception:
                        pass
            except Exception:
                pass
            if hasattr(self, "status_label"):
                self.status_label.setText(msg)
            try:
                from gui.notifications import notify_background_complete
                notify_background_complete("Workspace direct export", msg)
            except Exception:
                pass  # non-fatal
        except Exception:
            # never impact other flows
            if hasattr(self, "status_label"):
                self.status_label.setText("Quick client export failed (see logs); use manual Export button")
            logger.exception("quick client export error (defensive)")

    def _try_gdrive_client_folder_upload(self, client_name: str, main_local_path: str):
        """Phase 4 GDrive direct export micro (smallest safe addition): called only from export success paths after local write + only when cluster provided client_name.
        Uploads the generated document + (if present) the Related Set Manifest + Summary texts + (for sets) the Related Set Cross-References subsection (rich "Companion... Other set members..." sibling relationship text from the sources append extension inside Historical Sources Used) into the client's GDrive subfolder (via core/api helper).
        Non-blocking, full try/except, falls back silently to local-only on any GDrive/service/perm/net issue. Reuses existing client folder resolution (the caller already did the historical cluster scan).
        Respects the _gdrive_auto_upload_enabled (now persisted via app_preferences; default True; toggle in historical context menu). No change to UX when disabled or no cluster. Persisted choice ensures reliable auto-inclusion of Related Document Set Manifest + Summary + cross-refs artifacts on exports.
        Chained micro (this step): also copies historical reference docs (gdrive-sourced cluster members) as "Historical Ref - ..." copies into same folder using native Drive copy helper (for full traceable pack in client GDrive).
        """
        try:
            if not client_name or not main_local_path:
                return
            if not getattr(self, "_gdrive_auto_upload_enabled", True):
                return  # setting off: local-only (user toggled via menu)
            from core.api import upload_workspace_artifacts_to_gdrive
            man_t = getattr(self, "_last_related_set_manifest", None)
            sum_t = getattr(self, "_last_related_set_summary", None)
            if not sum_t:
                try:
                    sum_t = self._make_related_set_summary()
                except Exception:
                    sum_t = None
            bill_t = getattr(self, "_last_billing_artifact", None)
            # Keep-going tiniest autonomous micro (Phase 4, immediately after summary append + sources extension): compute (harmless) the now-extended rich cross-ref subsection locally here for future upload parity or logging; reuses the exact _build helper (single source, already includes the new "extends the Historical Sources Used in each member's final document..." sentence + Companion/Other members listings). Zero behavior/IO change; defensive; only relevant for sets. Completes "keep going to the next micro without stopping".
            cr_t = None
            try:
                if getattr(self, "_current_document_metadata", None) and (getattr(self, "_current_document_metadata", {}) or {}).get("related_set_companion"):
                    cr_t = self._build_related_set_cross_ref()
            except Exception:
                cr_t = None
            # The api helper handles find/create folder + selective uploads of provided items; returns bool but we ignore (defensive)
            upload_workspace_artifacts_to_gdrive(
                client_name,
                main_local_path=main_local_path,
                manifest_text=man_t,
                summary_text=sum_t,
                billing_text=bill_t,  # Billing Depth: pass the artifact (populated by Generate Billing for Set or restored) so GDrive client folder receives it too.
                cross_ref_text=cr_t,  # Phase 4 2f4c91b8 keep-going (this micro, no pause): wire the rich extended Related Document Set Cross-References subsection (sibling listings + Companion to ... via same historical cluster relationships) into GDrive client folder upload. Now the full traceability pack (main doc + Manifest + Summary + Cross-Refs) lands automatically for set members. Defensive (None ok, only set path populates).
            )
            # Autonomous next micro-increment (Phase 4 Workspace Production, after main artifacts GDrive upload): also-upload historical ref docs themselves as reference copies.
            # Only for gdrive sources in cluster (ref_match/related_match); native copy (no dl). Reuses find_or + new copy helper. Gated by same enabled flag + client_name. Fully defensive tiny block (~12 lines). No behavior change otherwise or on failure.
            try:
                from core.api import find_or_create_gdrive_folder, copy_gdrive_file_to_folder
                folder_id = find_or_create_gdrive_folder(client_name)
                if folder_id and hasattr(self, "historical_examples_list") and self.historical_examples_list:
                    for i in range(self.historical_examples_list.count()):
                        it = self.historical_examples_list.item(i)
                        d = it.data(Qt.ItemDataRole.UserRole) or {}
                        if (d.get("ref_match") or d.get("related_match")) and d.get("source") == "gdrive" and d.get("source_id"):
                            nm = (d.get("name") or "historical-ref")[:40]
                            safe_nm = "Historical Ref - " + re.sub(r'[^A-Za-z0-9_.-]', '', nm)
                            copy_gdrive_file_to_folder(str(d.get("source_id")), folder_id, safe_nm)
            except Exception:
                pass  # absolute silent; refs optional bonus, never impacts export or main artifacts
        except Exception:
            # absolute no impact on export flow or user
            pass

    def _view_related_set_manifest(self):
        """Phase 4 next micro (autonomous after badge): upgraded small manifest viewer *dialog* (not QMessageBox) accessible directly from the historical list context menu.
        Reuses exact prior menu site + QAction. Uses QDialog + read-only QTextEdit (monospace, scrollable) + Copy/Close buttons for better visibility/traceability of related document sets (list of companions + shared cluster + cross-refs + summary).
        When manifest present after Generate Related Set, shows formatted content (incl. delegated _build cross-refs + summary); otherwise guidance. Also adds a "Create Summary in Workspace" button (tiny) that seeds a Related Set Summary markdown into preview for further editing/export (advances summary generator idea). Defensive, no new top-level UI, smallest delta on existing viewer. """
        try:
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout, QApplication
            from PyQt6.QtGui import QFont
            man = getattr(self, "_last_related_set_manifest", None)
            dlg = QDialog(self)
            dlg.setWindowTitle("🟣 Related Document Set Manifest + Summary + Cross-Refs")  # Phase 4 keep-going micro: tiny title polish to match updated menu action + rich content (manifest + summary + the exact cross-refs subsection from Historical Sources Used). Zero other impact.
            dlg.setMinimumSize(520, 380)
            lay = QVBoxLayout(dlg)
            txt = QTextEdit()
            txt.setReadOnly(True)
            f = QFont("Consolas" if os.name == "nt" else "Monospace", 10)
            txt.setFont(f)
            if man and str(man).strip():
                txt.setPlainText(str(man))
                # One-more autonomous micro-increment (Phase 4, chained after sources cross-refs inside Historical Sources + dedup helpers): tiniest polish of manifest viewer. Delegate the cross-refs excerpt to shared _build_related_set_cross_ref() (single source for the exact "Companion to ... Other set members..." phrasing + full subsection text used in sources append block + _make summary). Ensures 100% parity/traceability across viewer, member docs, and summary artifacts. Reuses helper (which prefers pre-seeded + _derive); zero local dupe; defensive (empty ok); no effect if non-set or no manifest. Smallest delta advancing "start a small manifest viewer" + consistency for related document sets.
                try:
                    cross = self._build_related_set_cross_ref() or ""
                    if cross:
                        txt.setPlainText(str(man) + "\n\n" + str(cross).strip())
                    # Autonomous one-more logical micro-increment (Phase 4 chained, no pause after cross-ref polish in viewer): tiniest extension inside the *existing* manifest viewer try to also surface the auto-generated Related Set Summary (from _last or _make helper) when present. Completes "small manifest viewer" with full set artifacts (manifest + cross-refs + summary) in one dialog for traceability. Defensive, only when man active; reuses existing helpers/attrs; zero layout/IO change. Smallest ~5-line additive in current viewer block.
                    summ = getattr(self, "_last_related_set_summary", None)
                    if not summ:
                        try:
                            if hasattr(self, "_make_related_set_summary"):
                                summ = self._make_related_set_summary()
                        except Exception:
                            summ = None
                    if summ:
                        cur = txt.toPlainText()
                        txt.setPlainText(cur + "\n\n--- Related Set Summary (auto-generated for client export) ---\n" + str(summ).strip()[:1200])
                except Exception:
                    pass
            else:
                txt.setPlainText(
                    "No related set manifest present for this workspace.\n\n"
                    "To generate one: right-click a strong historical cluster (with [ref] + [related] items) in the 'Relevant Historical Documents' list and choose 'Generate Related Set (presets...)'. \n"
                    "Companions will auto-launch using the locked cluster; the manifest (listing all set members + traceability) is then available here and auto-written to client export folder.\n\n"
                    "After generation + export, set members appear in the historical list with a light [related set member] suffix + purple italic badge. Each member's document now includes the 'Related Document Set Cross-References' subsection *inside* its 'Historical Sources Used' section (via sources append block extension) for built-in traceability. Click any 🟣[related set member] in the list to open Details and use the 📋 Copy button for the full sibling relationship text. (Viewer now also surfaces auto-generated Related Set Summary for complete set traceability when manifest present.)"
                )
            lay.addWidget(txt)

            btn_row = QHBoxLayout()
            if man and str(man).strip():
                copy_btn = QPushButton("Copy to Clipboard")
                copy_btn.clicked.connect(lambda: (QApplication.clipboard().setText(str(man)), txt.setPlainText(str(man) + "\n\n(copied)")))
                btn_row.addWidget(copy_btn)
                # Keep-going autonomous micro (Phase 4, chained after menu/title polish + sources cross-refs): tiniest "Copy Cross-References" button in the *existing* manifest viewer btn_row. Reuses QApplication clipboard + lambda pattern of the prior copy_btn (already in scope); calls _build_related_set_cross_ref() (the single source for the exact "**Related Document Set Cross-References** ... Companion to ... Other set members..." text embedded in member docs' Historical Sources Used). Enables 1-click capture of the per-member relationship listing directly from the viewer. Defensive (only if helper yields); zero impact non-sets. Smallest ~5-line additive for usability of the cross-refs feature.
                try:
                    if hasattr(self, "_build_related_set_cross_ref"):
                        cross_cr = self._build_related_set_cross_ref() or ""
                        if cross_cr and len(str(cross_cr).strip()) > 10:
                            cr_btn = QPushButton("Copy Cross-References")
                            cr_btn.clicked.connect(lambda checked=False, cr=cross_cr: (QApplication.clipboard().setText(str(cr).strip()), None))
                            btn_row.addWidget(cr_btn)
                except Exception:
                    pass
                # Small next-logical: "Related Set Summary" generator button inside the dialog
                sum_btn = QPushButton("Create Summary Document in Workspace")
                def _make_summary():
                    summary = self._make_related_set_summary() or f"# Related Document Set Summary\n\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n## Manifest\n\n{man}\n\n## Notes\n\n- All members share the identical historical cluster for style, structure, and regulatory traceability.\n- Each companion document includes cross-references and the 'Historical Sources Used' section.\n- Use the Workspace Production Engine to produce consistent client deliverables as a set.\n"
                    self._current_markdown = (getattr(self, "_current_markdown", "") or "") + "\n\n" + summary if getattr(self, "_current_markdown", None) else summary
                    if hasattr(self, "preview_text"):
                        self.preview_text.setPlainText(self._current_markdown)
                    if hasattr(self, "status_label"):
                        self.status_label.setText("Related Set Summary appended to workspace (edit/export as needed)")
                    dlg.accept()
                sum_btn.clicked.connect(_make_summary)
                btn_row.addWidget(sum_btn)
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dlg.accept)
            btn_row.addStretch()
            btn_row.addWidget(close_btn)
            lay.addLayout(btn_row)
            dlg.exec()
        except Exception:
            # fallback to prior QMessage (defensive, never breaks menu)
            try:
                man = getattr(self, "_last_related_set_manifest", None)
                if man and str(man).strip():
                    QMessageBox.information(self, "Related Document Set Manifest", str(man))
                else:
                    QMessageBox.information(self, "Related Document Set Manifest", "No related set manifest present.")
            except Exception:
                pass

    def _make_related_set_summary(self):
        """Smallest reusable helper (Phase 4 auto-summary micro): builds the Related Set Summary markdown string from the live _last_related_set_manifest (or returns None). Reused by: the manifest viewer's button, the auto-create in post-generation block, and export writers. Defensive, pure string build, no side effects or IO. Exactly matches prior inline literal for consistency."""
        try:
            man = getattr(self, "_last_related_set_manifest", None)
            if not man or not str(man).strip():
                return None
            ts = datetime.now().strftime('%Y-%m-%d %H:%M')
            # Autonomous one-more micro (Phase 4, chained after sources cross-refs extension): tiniest addition inside existing _make helper.
            # Builds explicit "Related Document Set Cross-References" listing of other members + relationship phrasing (reuses _last_related_set_companions for accuracy, falls back to simple manifest scan).
            # Included in the auto-generated summary artifact (and button-created one) so the summary itself provides the full member relationship traceability for the set. Defensive; only when companions present; zero change to non-set summaries.
            cross_refs = ""
            try:
                # Autonomous keep-going micro (Phase 4, no stop after viewer summary inclusion): tiniest prefer of the shared rich _build_related_set_cross_ref() (exact subsection text used in Historical Sources Used append + manifest viewer) at the top of summary's cross-refs build. Ensures 100% phrasing parity ("**Related Document Set Cross-References (extends...):** Companion to the ... Other set members...") between the auto Summary artifact, member docs, and viewer. Falls back to derive if absent. Defensive; smallest 3-line guard inside the existing cross_refs try.
                rich_cross = None
                try:
                    if hasattr(self, "_build_related_set_cross_ref"):
                        rich_cross = self._build_related_set_cross_ref()
                except Exception:
                    rich_cross = None
                if rich_cross:
                    cross_refs = "\n\n" + str(rich_cross).strip()
                else:
                    # Phase 4 keep-going chained micro (dedup continuation): use the new shared _derive helper (instead of local comps scan) for the cross-refs section in auto-generated Related Set Summary. Removes another small dupe site; base_name available but unused here. Fully defensive.
                    base_name, others = self._derive_related_set_base_and_others()
                    if others:
                        cross_refs = "\n\n## Related Document Set Cross-References\n\nAll members generated via the same locked historical cluster for style, structure, and regulatory consistency/traceability.\n\nOther set members: " + "; ".join(others)
                        if len(getattr(self, "_last_related_set_companions", None) or others) > 5:
                            cross_refs += " (and more)"
                        cross_refs += ".\n(See individual member deliverables for their 'Historical Sources Used' + per-doc cross-refs.)\n"
            except Exception:
                cross_refs = ""
            return (
                f"# Related Document Set Summary\n\n"
                f"Generated: {ts}\n\n"
                f"## Manifest\n\n{man}\n\n"
                + (cross_refs or "") +
                "## Notes\n\n"
                "- All members share the identical historical cluster for style, structure, and regulatory traceability.\n"
                "- Each companion document automatically includes the 'Related Document Set Cross-References' subsection *inside its 'Historical Sources Used' section* (via the sources append block extension for set traceability) listing the other set members and their relationships (e.g. 'Companion to the Validation Plan via the same historical cluster for traceability and consistency'). This extends each member's final doc with explicit sibling listings. Also receives a prominent '🟣 [Related Document Set member]' callout badge at the top of the live preview pane for immediate visibility during production.\n"
                "- Use the Workspace Production Engine to produce consistent client deliverables as a set.\n"
            )
        except Exception:
            return None

    def _seed_related_set_member_record(self):
        """Smallest Phase 4 micro-increment (related document sets visibility): seed just-generated companion (when _current_document_metadata carries the flag from _generate_related_set path) as a DocumentRecord with 'related_set_member' in extra.
        This ensures it surfaces via get_relevant_past_documents / populate_relevant_historical_examples and receives the light "[related set member]" badge/suffix in the historical list. Reuses cluster scan + metadata; source="workspace-generated" for traceability. Defensive, idempotent via PK, no behavior change for non-set exports/generations. Called from export sites only."""
        try:
            meta = getattr(self, "_current_document_metadata", {}) or {}
            if not meta.get("related_set_companion"):
                return
            ch = meta.get("client") or meta.get("prepared_for") or "client"
            dt = meta.get("doc_type") or None
            note = meta.get("related_set_note") or "auto-generated companion via related document set (shared cluster)"
            # pull dt/client from live cluster list if not in meta (defensive)
            if hasattr(self, "historical_examples_list") and self.historical_examples_list:
                for i in range(min(4, self.historical_examples_list.count())):
                    dd = self.historical_examples_list.item(i).data(Qt.ItemDataRole.UserRole) or {}
                    if dd.get("ref_match") or dd.get("related_match"):
                        if not dt:
                            dt = dd.get("doc_type")
                        if ch == "client":
                            ch = dd.get("client_hint") or ch
                        break
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            rec = DocumentRecord(
                source="workspace-generated",
                source_id=f"related-set-{ts}",
                source_path=f"data/workspace_output/{re.sub(r'[^A-Za-z0-9_-]', '', str(ch))[:20]}/",
                name=f"{dt or 'Companion Document'} (related set member for {ch})",
                mime_type="application/octet-stream",
                doc_type=dt,
                client_hint=ch,
                year=datetime.now().year,
                extra={"related_set_member": True, "related_set_note": note[:200], "generated_via": "generate_related_set", "set_manifest": getattr(self, "_last_related_set_manifest", None) and "present" or None, "related_set_cross_ref_note": ((getattr(self, "_current_document_metadata", {}) or {}).get("related_set_cross_ref_section") or (getattr(self, "_current_document_metadata", {}) or {}).get("related_set_cross_ref_note", ""))[:500], "related_set_cross_ref_section": ((getattr(self, "_current_document_metadata", {}) or {}).get("related_set_cross_ref_section") or "")[:600], "related_set_companions_count": len(getattr(self, "_last_related_set_companions", None) or []), "has_related_set_artifacts": bool(getattr(self, "_last_related_set_manifest", None) or getattr(self, "_last_related_set_summary", None))},
            )
            save_document_record(rec)
        except Exception:
            # never break export or UI; seeding is best-effort for list visibility
            pass

    def _derive_related_set_base_and_others(self):
        """Phase 4 dedup micro (autonomous continuation, 2f4c91b8 lineage): tiniest private helper.
        Centralizes the *duplicated* derivation of (base_name from live hist ref_match scan + others list preferring _last_related_set_companions) that lived inline in *two* places inside the post-gen sources append block (the "Historical Sources Used" + "Related Document Set Cross-References" extension logic).
        Returns (base_name: str, others: list[str]). Defensive, zero side-effects, no behavior change.
        Call sites now use this (net code reduction + single source of truth for relationship phrasing like "Companion to the Validation Plan via the same historical cluster...").
        Usable by summary builder too in future chained micro. Only activates/returns useful data for actual related sets.
        """
        others = []
        base_name = "the primary reference in the shared historical cluster"
        try:
            comps = getattr(self, "_last_related_set_companions", None) or []
            if comps:
                others = [str(c) for c in comps if c][:5]
        except Exception:
            others = []
        try:
            if hasattr(self, "historical_examples_list") and self.historical_examples_list:
                for ii in range(self.historical_examples_list.count()):
                    dd = self.historical_examples_list.item(ii).data(Qt.ItemDataRole.UserRole) or {}
                    if dd.get("ref_match"):
                        nm = dd.get("name") or ""
                        dt = dd.get("doc_type") or ""
                        if nm:
                            base_name = f"{nm} ({dt})" if dt else nm
                        break
        except Exception:
            pass
        return base_name, others

    def _build_related_set_cross_ref(self) -> str | None:
        """Tiny sibling dedup helper (Phase 4 autonomous continuation after sources extension micro): centralizes the exact construction of the "**Related Document Set Cross-References**" subsection + "Companion to the <base> via the same historical cluster for traceability and consistency" + "Other set members: ..." listing/relationship phrasing.
        Matches the spec example exactly ("Companion to the Validation Plan via the same historical cluster for traceability and consistency").
        Previously duplicated (with minor site trims) inside the two post-gen sources append block sites that extend the "Historical Sources Used" section for set members.
        Now single source of truth: reuses _derive... + _last_* state + pre-seeded meta if present (for restore symmetry).
        Returns the ready-to-append "\n\n**Related...** ..." string (or None). Used to keep the sources append block extension DRY; output text 100% unchanged for final member docs (md + templates via seeded meta). Latest tiniest extension (this micro): appends explicit "This extends the Historical Sources Used in each member's final document..." sentence when used inside the sources append block for set members.
        Defensive; only for sets; smallest net-positive addition (one new ~20-line fn, removes ~12 lines of dupe from call sites below).
        """
        try:
            # prefer any already-computed rich subsection (e.g. from restore or first path)
            m = getattr(self, "_current_document_metadata", {}) or {}
            if isinstance(m, dict):
                pre = m.get("related_set_cross_ref_section")
                if pre:
                    return str(pre)
            base_name, others = self._derive_related_set_base_and_others()
            o = others[:3]
            extra = ""
            if o:
                extra = ". Other set members: " + "; ".join(o)
                if len(getattr(self, "_last_related_set_companions", None) or []) > 3:
                    extra += " (and more)"
            txt = "\n\n**Related Document Set Cross-References (extends Historical Sources Used section for set traceability):** This deliverable is a companion in the related document set (all via locked historical cluster for style/structure/traceability consistency). Companion to the " + base_name + " via the same historical cluster for traceability and consistency" + extra + " (_Related_Set_Manifest.txt + Summary written to client folder on export). This extends the Historical Sources Used in each member's final document with explicit sibling listings and relationships for full set traceability."
            return txt
        except Exception:
            return None

    # Phase 1 historical list refresh on ref injection: implemented via hooks in run_ai... and after task spec (live since Option A).
    # No further action needed; retrieval surfaces are stable.

    def get_file_content(self, file_info):
        """Get file content with caching and robust extraction for .docx, .pdf, .xlsx, .txt, .md"""
        if bool(file_info.get("virtual")):
            return str(file_info.get("content") or "")

        # Use cached content if available
        if 'content' in file_info and file_info['content']:
            return file_info['content']

        path = str(file_info.get('path') or "")
        name = str(file_info.get('name') or os.path.basename(path))
        if not path or not os.path.exists(path):
            content = f"[File not found: {name}]"
            file_info['content'] = content
            return content

        ext = os.path.splitext(name)[1].lower()

        try:
            if ext == '.docx':
                from docx import Document
                doc = Document(path)
                content = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
                if not content.strip():
                    content = "[DOCX file appears empty or has no readable text]"
                
            elif ext == '.pdf':
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(path)
                    content = ""
                    for page in reader.pages:
                        page_text = page.extract_text() or ""
                        content += page_text + "\n"
                    if not content.strip():
                        content = "[PDF file appears empty or has no extractable text]"
                except ImportError:
                    content = "[pypdf not installed - cannot read PDF]"
                except Exception as e:
                    content = f"[Error reading PDF: {str(e)}]"

            elif ext == '.xlsx':
                try:
                    import pandas as pd
                    df = pd.read_excel(path)
                    content = df.to_string(index=False)
                    if not content.strip():
                        content = "[Excel file appears empty]"
                except ImportError:
                    content = "[pandas not installed - cannot read XLSX]"
                except Exception as e:
                    content = f"[Error reading XLSX: {str(e)}]"

            elif ext in {'.txt', '.md'}:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

            else:
                content = f"[Unsupported file type: {ext}]"

            # Final fallback check
            if not content or content.strip() == "":
                content = f"[No readable text extracted from {name}]"
                logger.warning(f"Empty content extracted from {name}")

        except Exception as e:
            logger.error(f"Error extracting content from {name}: {e}")
            content = f"[Error extracting content from {name}: {str(e)}]"

        # Cache the result
        file_info['content'] = content
        return content

    @staticmethod
    def _has_usable_source_content(content: str) -> bool:
        text = str(content or "").strip()
        if not text:
            return False
        if text.startswith("[Error"):
            return False
        if text.startswith("[File:"):
            return False
        if text.startswith("[File not found:"):
            return False
        if text.startswith("[Unsupported file type:"):
            return False
        if text.startswith("[No readable text"):
            return False
        if text.startswith(("[DOCX file", "[PDF file", "[Excel file", "[pypdf", "[pandas not")):
            return False
        return True

    def _guess_file_type(self, filename: str) -> str:
        """Simple helper to guess file type based on file extension."""
        ext = os.path.splitext(filename)[1].lower()
        
        if ext in {".txt", ".log"}:
            return "text"
        if ext in {".md", ".markdown"}:
            return "markdown"
        if ext in {".py", ".js", ".json", ".xml", ".html", ".css"}:
            return "text"
        if ext in {".pdf"}:
            return "pdf"
        if ext in {".doc", ".docx"}:
            return "docx"
        # Fallback
        return "unknown"

    def _build_quill_runtime_context(self) -> str:
        """
        Build optional runtime context for Quill using the existing Workspace state.

        This keeps Quill flexible:
        - If the user asks for template-based revision, Quill can use a file from the marked list.
        - If no template is requested, Quill can still do a normal edit pass with current draft context.
        """
        sections = []

        current_markdown = (self._current_markdown or "").strip()
        if current_markdown:
            sections.append(
                "Current Workspace markdown draft:\n"
                "```markdown\n"
                f"{current_markdown}\n"
                "```"
            )

        marked_files = [f for f in self.selected_files if f.get("marked")]
        if marked_files:
            file_lines = ["Marked Workspace files (you may name one as a template in your instruction):"]
            for f in marked_files:
                file_lines.append(f"- {f.get('name', '(unknown)')} | path: {f.get('path', '')}")
            sections.append("\n".join(file_lines))

            # Include bounded snippets so Quill can actually align to named examples/templates.
            max_total_chars = 40000
            max_per_file_chars = 8000
            used_chars = 0
            snippets = []
            for f in marked_files:
                if used_chars >= max_total_chars:
                    break
                try:
                    content = self.get_file_content(f) or ""
                except Exception:
                    content = ""
                if not content:
                    continue
                remaining = max_total_chars - used_chars
                snippet_limit = min(max_per_file_chars, remaining)
                snippet = content[:snippet_limit]
                used_chars += len(snippet)
                snippets.append(
                    "File snippet:\n"
                    f"- name: {f.get('name', '(unknown)')}\n"
                    f"- path: {f.get('path', '')}\n"
                    "```text\n"
                    f"{snippet}\n"
                    "```"
                )
            if snippets:
                sections.append("\n\n".join(snippets))

        if not sections:
            return ""
        return "\n\n".join(sections)

    def _load_quill_reply_into_preview(self, reply_text: str) -> None:
        body = str(reply_text or "").strip()
        if not body:
            return
        self._current_markdown = body
        self.preview_text.setPlainText(body)
        self._last_generated_template_spec = None
        self._current_template_blocks = {}
        self._current_document_metadata = {}
        self._current_template_evidence_map = {}
        self._current_unresolved_fields = []
        self._current_research_gaps = []
        self._current_user_questions = []
        self._update_template_validation_state()
        self._update_template_gap_summary()
        if hasattr(self, "save_button"):
            self.save_button.setEnabled(True)
        if hasattr(self, "export_button"):
            self.export_button.setEnabled(True)
        self.status_label.setText("Loaded Quill direct reply into preview. Use Export to save it.")

    def _run_quill_reviewed_workflow(self, instruction: str) -> None:
        prompt = str(instruction or "").strip()
        if not prompt:
            self.status_label.setText("No reviewed-workflow instruction provided from Quill.")
            return
        self.run_ai_collaboration_workflow(initial_instructions=prompt, prompt_source="Quill")

    def _hide_chief_of_staff_followup(self) -> None:
        btn = getattr(self, "view_chief_of_staff_btn", None)
        if btn is not None:
            btn.setVisible(False)

    def _open_chief_of_staff_tab(self) -> None:
        win = self.window()
        tw = getattr(win, "tab_widget", None)
        if tw is None:
            return
        cos = getattr(win, "chief_of_staff_tab", None)
        if cos is not None:
            tw.setCurrentWidget(cos)
            return
        for i in range(tw.count()):
            if str(tw.tabText(i) or "").strip() == "Chief of Staff":
                tw.setCurrentIndex(i)
                return

    def _demo_full_cycle_abort_if_pending(self, *, reason: str = "") -> None:
        """Clear demo flags if Workspace collaboration failed before/during the demo chain."""
        if not getattr(self, "_demo_full_cycle_pending_assignment", False):
            return
        self._demo_full_cycle_pending_assignment = False
        win = self.window()
        if win is not None:
            setattr(win, "_demo_full_cycle_active", False)
            msg = "Demo: Full Cycle aborted"
            if reason.strip():
                msg = f"{msg}: {reason.strip()}"
            if hasattr(win, "show_toast"):
                win.show_toast(msg, duration=6000)

    def _demo_full_cycle_finish_after_collaboration(self) -> None:
        """After demo Workspace draft completes: sample Atlas assignment + refresh CoS board."""
        if not getattr(self, "_demo_full_cycle_pending_assignment", False):
            return
        self._demo_full_cycle_pending_assignment = False

        win = self.window()
        md = (self._current_markdown or "").strip()
        excerpt = md[:4000] if md else "_No draft body was produced._"
        title = "Demo: CEO memo follow-up (sample)"
        brief = (
            "Sample assignment created by **Demo: Full Cycle**.\n\n"
            "Use the generated Workspace memo as the working packet; delegate the next regulatory execution steps.\n\n"
            "---\n\n"
            f"{excerpt}"
        )
        aid = 0
        try:
            aid = int(
                self.db.agent_create_assignment(
                    title=title,
                    brief_md=brief,
                    requester_code="navi",
                    assignee_code="atlas",
                    priority=3,
                    due_date=None,
                    context_json={"source": "demo_full_cycle"},
                )
                or 0
            )
        except Exception as e:
            logger.warning("Demo full cycle: could not create sample assignment: %s", e)

        if aid:
            try:
                thread_id = create_assignment_thread(
                    self.db,
                    assignment_id=int(aid),
                    assignee_code="atlas",
                    reason="demo_full_cycle",
                    actor_code="navi",
                    context_json={"source": "demo_full_cycle"},
                )
                if thread_id:
                    prime_assignment_handoff(
                        self.db,
                        assignment_id=int(aid),
                        thread_id=int(thread_id),
                    )
            except Exception:
                pass

        cos = getattr(win, "chief_of_staff_tab", None)
        if cos is not None and hasattr(cos, "_refresh_assignment_list"):
            try:
                cos._refresh_assignment_list()
            except Exception:
                pass

        if win is not None:
            setattr(win, "_demo_full_cycle_active", False)
            if hasattr(win, "notify_background_complete"):
                win.notify_background_complete(
                    "Demo: Full Cycle",
                    "Research → memo → tasks → sample assignment on Chief of Staff.",
                )
            elif hasattr(win, "show_toast"):
                win.show_toast("Demo: Full Cycle complete.", duration=5000)

    def _offer_chief_of_staff_after_task_import(
        self,
        created_count: int,
        *,
        status_line: str | None = None,
        toast_title: str = "Workspace",
        toast_message: str | None = None,
    ) -> None:
        n = int(created_count)
        if n <= 0:
            return
        if status_line:
            self.status_label.setText(status_line)
        notify_background_complete(
            self,
            toast_title,
            toast_message or f"{n} task(s) imported. Open Chief of Staff to delegate.",
        )
        btn = getattr(self, "view_chief_of_staff_btn", None)
        if btn is not None:
            btn.setVisible(True)

    def run_ai_collaboration_workflow(self, initial_instructions: str | None = None, prompt_source: str = "Workspace"):
        """
        Run the dual-LLM collaboration workflow with RAG grounding.
        """
        try:
            from core.rag_retriever import rag_retriever

            self.merge_latest_atlas_research()
            marked_files = [f for f in self.selected_files if f.get("marked")]
            selected_template_spec = self._selected_document_template_spec()
            self._capture_gap_baseline_for_next_run()

            # Ask for instructions
            if marked_files:
                prompt_text = f"Describe what you want Grok + ChatGPT to do with these {len(marked_files)} file(s):"
            else:
                prompt_text = "Describe what you want Grok + ChatGPT to research and create:"

            provided_instructions = str(initial_instructions or "").strip()
            if not provided_instructions and getattr(self, "collaboration_prompt_edit", None) is not None:
                provided_instructions = str(self.collaboration_prompt_edit.toPlainText() or "").strip()

            if provided_instructions:
                instructions = provided_instructions
            else:
                instructions, ok = QInputDialog.getText(
                    self, "AI Collaboration Instructions", prompt_text
                )
                if not ok or not instructions.strip():
                    self.status_label.setText("AI collaboration cancelled")
                    self._demo_full_cycle_abort_if_pending(reason="cancelled")
                    return

            # Force document-only mode when a document is requested
            if any(word in instructions.lower() for word in ["draft", "write", "create", "generate", "pccp", "sop", "plan", "protocol", "report"]):
                instructions = instructions + "\n\nIMPORTANT: Produce ONLY the requested document. Do not add any task lists, suggested tasks, or importable tasks at the end."

            # Phase 4 (Workspace Production Engine): auto-inject top strong historical ref (from live list populated by Phase 1 retrieval) for seamless real-work reuse on generate. Smallest safe; reuses exact marker + ref_match logic.
            try:
                if hasattr(self, "historical_examples_list") and self.historical_examples_list is not None:
                    for i in range(self.historical_examples_list.count()):
                        it = self.historical_examples_list.item(i)
                        d = it.data(Qt.ItemDataRole.UserRole) or {}
                        if d.get("ref_match") and "[Historical reference:" not in (instructions or ""):
                            ref = f"\n[Historical reference: {d.get('name', '')} ({d.get('doc_type', '')}, {d.get('year', '')})]"
                            instructions = (instructions + ref).strip()
                            break
            except Exception:
                pass

            # Autonomous next micro (chained after auto-summary work, no stop): tiny defensive stale-state clearer for related set attrs (manifest + summary). 
            # On entry to any normal generation, if the resolved instructions do *not* carry the set-companion phrasing (the exact markers used by _generate_related_set prefill + post-gen detection), null the _last_related_* attrs. 
            # This prevents a prior set-run's summary/manifest from leaking into exports of subsequent *non-set* generations in the same session. 
            # Set-prefill paths (which populate the prompt with "companion ... historical cluster" before calling run_ai...) will match and preserve the fresh values. Reuses the identical lower() goal/instr scan idiom from the post-gen block + sources/cross logic; 6 lines, fully defensive, zero UI/IO impact, improves robustness of the just-added summary feature.
            try:
                instr_l = (provided_instructions or instructions or "").lower()
                if not (("companion" in instr_l or "related deliverable task" in instr_l) and "historical cluster" in instr_l):
                    self._last_related_set_manifest = None
                    self._last_related_set_summary = None
                    self._last_billing_artifact = None  # Billing Depth: same stale-clear logic for the billing artifact (prevents leakage into unrelated gens; set-prefill + Generate Billing paths preserve when cluster phrasing present). Defensive, inside existing try.
            except Exception:
                pass

            # Phase 4 (Workspace Production Engine) micro-increment (2f4c91b8 lineage continuation): when strong historical ref + related cluster actually present in the live historical_examples_list (populated pre-generate via populate_relevant... + cluster pull), auto-derive a concise "Style & Structure Guidance from Historical References" (2-6 professional bullets) via the new helper and prepend it to instructions/objective. This flows directly into task_spec.goal, DualLLMOrchestrator prompts, Grok/ChatGPT calls, outline/section paths, and RAG. Reuses derive_style... (which reuses format_compact detection) + identical defensive list scan / duck-type _H pattern as the later "Historical Sources Used" append. Only activates on real cluster use; zero behavior change otherwise; no new UI, no extra calls, smallest targeted edit in the single pre-call instructions site.
            try:
                if hasattr(self, "historical_examples_list") and self.historical_examples_list is not None and self.historical_examples_list.count() > 0:
                    hist_docs = []
                    for i in range(self.historical_examples_list.count()):
                        it = self.historical_examples_list.item(i)
                        d = it.data(Qt.ItemDataRole.UserRole) or {}
                        if d.get("ref_match") or d.get("related_match"):
                            class _H:
                                pass
                            h = _H()
                            for k, default in (("name", ""), ("doc_type", ""), ("client_hint", ""), ("year", None), ("regulatory_tags", []), ("source_path", "")):
                                setattr(h, k, d.get(k, default))
                            setattr(h, "_ref_match", bool(d.get("ref_match")))
                            setattr(h, "_related_match", bool(d.get("related_match")))
                            hist_docs.append(h)
                    guidance = derive_style_guidance_from_historical_cluster(hist_docs)
                    if guidance and "Style & Structure Guidance from Historical References" not in (instructions or ""):
                        instructions = (guidance + instructions).strip()
            except Exception:
                # never break generation on optional style guidance injection
                pass

            # === Get RAG context + Phase 1 light blending of structured historical DocumentRecords ===
            self.status_label.setText("Retrieving relevant documents from RAG...")
            QApplication.processEvents()

            past_docs = []
            try:
                ts = getattr(self, "_last_task_spec", None)
                if ts:
                    dtype = getattr(ts, "document_type", None) or getattr(ts, "doc_type", None)
                    obj = getattr(ts, "objective", "") or getattr(ts, "instructions", "")
                    if dtype:
                        query = obj[:120] if obj else ""
                        # Strengthen bias using raw_context (full instructions may contain marker) so the
                        # centralized extract + strong ref scoring/_ref_match in get_relevant_past_documents
                        # now activates reliably (fixes Issue 3 integration gap for Workspace generation path).
                        raw_for_ref = instructions or ""
                        try:
                            import re
                            m = re.search(r'\[Historical reference: ([^\]]+)', raw_for_ref)
                            if m:
                                query = (query + " " + m.group(1)).strip()[:200]
                        except Exception:
                            pass
                        past_docs = get_relevant_past_documents(
                            doc_type=dtype,
                            query=query if query else "",
                            limit=4,
                            raw_context=raw_for_ref  # ensures marker is seen for ref bias even if query is augmented inner text
                        )
                        # (manual propagation removed; the primitive now marks correctly via raw_context)
                        # Subsequent micro (autonomous after related-list surface): when strong ref present (auto-inject or manual marker), also pull 1-2 related cluster docs (same client+type/theme) into past_docs so they flow into rag_context + format_compact_historical_context blend (under STRONGLY RELEVANT header via existing any(_ref_match)). Reuses exact get_ + client/dt/reg logic pattern. Smallest-safe; generation now gets cluster context automatically.
                        try:
                            if past_docs and any(getattr(d, '_ref_match', False) for d in past_docs):
                                strong = next((d for d in past_docs if getattr(d, '_ref_match', False)), past_docs[0])
                                ch = getattr(strong, 'client_hint', None)
                                dt = getattr(strong, 'doc_type', None)
                                regs = getattr(strong, 'regulatory_tags', []) or []
                                theme_q = " ".join([r for r in regs if r][:3]) if regs else (dt or "")
                                extra = get_relevant_past_documents(client_hint=ch, doc_type=dt, query=(theme_q or "")[:100], limit=3, raw_context=raw_for_ref)
                                seen = set(getattr(x, 'source_id', None) or getattr(x, 'name', '') for x in past_docs)
                                added = 0
                                for e in extra:
                                    eid = getattr(e, 'source_id', None) or getattr(e, 'name', '')
                                    if eid and eid not in seen:
                                        setattr(e, '_related_match', True)
                                        past_docs.append(e)
                                        seen.add(eid)
                                        added += 1
                                        if added >= 2:
                                            break
                        except Exception:
                            pass
            except Exception:
                past_docs = []

            # Next micro (post this): deeper use of injected cluster (e.g. per-section historical style or export GDrive target from client of ref)
            rag_query = instructions
            try:
                import re
                m = re.search(r'\[Historical reference: ([^\]]+)', instructions or "")
                if m:
                    rag_query = (instructions or "") + " " + m.group(1)
            except Exception:
                pass
            rag_context = rag_retriever.get_context_string(rag_query, k=8, past_documents=past_docs)
            if "No relevant documents" in rag_context:
                rag_context = ""

            workspace_files = []
            file_contents = {}
            if marked_files:
                self.status_label.setText("Extracting file contents...")
                self.progress_bar.setVisible(True)
                self.progress_bar.setValue(0)
                QApplication.processEvents()
                total_files = len(marked_files)
                for idx, f in enumerate(marked_files):
                    self.status_label.setText(f"Extracting content from {f['name']}... ({idx+1}/{total_files})")
                    self.progress_bar.setValue(int((idx / total_files) * 30))
                    QApplication.processEvents()
                    content = self.get_file_content(f)
                    file_path = str(f["path"] or "").strip()
                    if not bool(f.get("virtual")):
                        file_path = os.path.abspath(file_path)
                    if not content or content.startswith("[Error") or content.startswith("[File:"):
                        logger.warning(f"Empty or error content for {f['name']}: {content[:100] if content else 'No content'}")
                    logger.info(f"Extracted {len(content)} chars from {file_path}")
                    file_contents[file_path] = content
                    workspace_files.append(
                        WorkspaceFile(
                            path=file_path,
                            display_name=f["name"],
                            file_type=self._guess_file_type(f["name"]),
                        )
                    )
                usable_count = sum(1 for value in file_contents.values() if self._has_usable_source_content(value))
                if usable_count == 0:
                    self.status_label.setText("No usable source content extracted from the marked files")
                    self.progress_bar.setVisible(False)
                    self.preview_text.setPlainText(
                        "No usable source content could be extracted from the marked files. "
                        "Try a supported text/PDF/DOCX source or check the extraction warnings."
                    )
                    if hasattr(self, "grok_text"):
                        self.grok_text.setPlainText("Source extraction failed for all marked files.")
                    if hasattr(self, "chatgpt_text"):
                        self.chatgpt_text.setPlainText("Workflow did not start because no usable source content was available.")
                    self._demo_full_cycle_abort_if_pending(reason="no usable source content")
                    return
            else:
                self.status_label.setText("Starting research collaboration...")
                self.progress_bar.setVisible(True)
                self.progress_bar.setValue(10)
                QApplication.processEvents()

            # Build task spec
            max_rounds = self.max_rounds_spinbox.value()
            context = ""
            if getattr(self, "include_task_suggestions_checkbox", None) and self.include_task_suggestions_checkbox.isChecked():
                context = "Output contract:\n- Include a section exactly titled '## Suggested Tasks (importable)' with tasks in the exact format shown earlier."

            task_spec = WorkspaceTaskSpec(
                goal=instructions.strip(),
                context=context,
                files=workspace_files,
                max_rounds=max_rounds,
                document_template=selected_template_spec.to_payload() if selected_template_spec else None,
            )

            self._last_task_spec = task_spec
            # Continuation of next micro: auto-refresh historical list after injection influences the next run
            if hasattr(self, "historical_examples_list") and hasattr(self, "populate_relevant_historical_examples"):
                dtype = getattr(task_spec, "document_type", None) or getattr(task_spec, "doc_type", None)
                obj = getattr(task_spec, "objective", "") or getattr(task_spec, "goal", "") or instructions
                if dtype:
                    self.populate_relevant_historical_examples(dtype, obj)
            self._last_workspace_files = [
                {"path": wf.path, "display_name": wf.display_name, "file_type": wf.file_type}
                for wf in workspace_files
            ]
            self._last_generated_template_spec = selected_template_spec
            self._current_template_blocks = {}
            self._current_document_metadata = {}
            self._current_template_evidence_map = {}
            self._current_unresolved_fields = []
            self._current_research_gaps = []
            self._current_user_questions = []
            self._current_file_contents = file_contents

            logger.info(f"Passing {len(file_contents)} file(s) to orchestrator")
            logger.debug(f"File paths: {list(file_contents.keys())}")
            logger.debug(f"Task spec files: {[f.path for f in task_spec.files]}")

            self.status_label.setText("Starting AI collaboration with RAG grounding...")
            QApplication.processEvents()

            if hasattr(self, "grok_text"):
                self.grok_text.clear()
            if hasattr(self, "chatgpt_text"):
                self.chatgpt_text.clear()
            if hasattr(self, "preview_text"):
                self.preview_text.clear()

            self._hide_chief_of_staff_followup()
            if hasattr(self, "save_button"):
                self.save_button.setEnabled(False)
            if hasattr(self, "export_button"):
                self.export_button.setEnabled(False)

            orchestrator = DualLLMOrchestrator(
                logger=logger,
                grok_call=lambda task_spec, file_contents, feedback, round_num, previous_markdown: call_grok_api(
                    task_spec,
                    file_contents or self._current_file_contents,
                    feedback,
                    round_num,
                    previous_markdown,
                    rag_context=rag_context,
                ),
                chatgpt_call=lambda task_spec, grok_result, file_contents, round_num: call_chatgpt_api(
                    task_spec,
                    grok_result,
                    file_contents or self._current_file_contents,
                    round_num,
                    rag_context=rag_context,
                ),
            )

            self._collaboration_worker = CollaborationWorker(orchestrator, task_spec, file_contents)
            self._collaboration_worker.progress_signal.connect(self._on_progress_update)
            self._collaboration_worker.round_update_signal.connect(self._on_round_update)
            self._collaboration_worker.result_signal.connect(self._on_collaboration_complete)
            self._collaboration_worker.error_signal.connect(self._on_collaboration_error)
            mr = max(1, int(self.max_rounds_spinbox.value()))
            self._update_generate_draft_progress_btn(1, mr)
            self._collaboration_worker.start()

        except Exception as e:
            logger.error(f"Error in run_ai_collaboration_workflow: {e}")
            self.status_label.setText(f"Error: {str(e)}")
            self.progress_bar.setVisible(False)
            if hasattr(self, "preview_text"):
                self.preview_text.setPlainText(f"Error: {str(e)}")
            if hasattr(self, "grok_text"):
                self.grok_text.setPlainText(f"Error: {str(e)}")
            if hasattr(self, "chatgpt_text"):
                self.chatgpt_text.setPlainText("Workflow failed during setup.")
            if hasattr(self, "generate_draft_btn"):
                self.generate_draft_btn.setEnabled(True)
                self.generate_draft_btn.setText("Generate Draft")
            self._demo_full_cycle_abort_if_pending(reason="setup error")

    def _on_progress_update(self, message, progress):
        """Handle progress updates from worker thread (thread-safe, called on main thread)"""
        self.status_label.setText(message)
        self.progress_bar.setValue(progress)
        QApplication.processEvents()

    def _update_generate_draft_progress_btn(self, current_round: int, max_rounds: int | str) -> None:
        if not hasattr(self, "generate_draft_btn"):
            return
        self.generate_draft_btn.setEnabled(False)
        self.generate_draft_btn.setText(f"Generating... Round {current_round}/{max_rounds}")
    
    def _on_round_update(self, round_data):
        """Handle round update signal from worker thread (thread-safe, called on main thread)"""
        round_num = round_data.get("round", 0)
        grok_output = round_data.get("grok_output", "")
        chatgpt_output = round_data.get("chatgpt_output", "")
        markdown = round_data.get("markdown", "")
        feedback = round_data.get("feedback", "")
        ref_pack_stats = round_data.get("reference_pack_stats")
        template_blocks = round_data.get("template_blocks") or {}
        document_metadata = round_data.get("document_metadata") or {}
        coverage_summary = format_reference_pack_summary(ref_pack_stats)
        ts_spec = getattr(self, "_last_task_spec", None)
        max_rounds_ui = ts_spec.max_rounds if ts_spec is not None else "?"
        self._update_generate_draft_progress_btn(int(round_num or 0) or 1, max_rounds_ui)
        if coverage_summary:
            self.status_label.setText(f"Round {round_num}/{max_rounds_ui} · {coverage_summary}")
        else:
            self.status_label.setText(f"Round {round_num}/{max_rounds_ui} · AI collaboration…")

        # Phase 1: Show the actual historical examples that were retrieved for this generation
        if ts_spec:
            doc_type = getattr(ts_spec, "document_type", None) or getattr(ts_spec, "doc_type", None)
            obj = getattr(ts_spec, "objective", "") or getattr(ts_spec, "instructions", "")
            if doc_type:
                self.populate_relevant_historical_examples(doc_type, obj)

        grok_body = grok_output
        if coverage_summary:
            grok_body = f"{grok_output}\n\n[Reference pack] {coverage_summary}"

        # Update Grok pane with current round
        if hasattr(self, 'grok_text'):
            current_text = self.grok_text.toPlainText()
            if "Round" in current_text or current_text.strip() == "Processing...":
                # Append to existing or replace "Processing..."
                if current_text.strip() == "Processing...":
                    self.grok_text.setPlainText(f"--- Round {round_num} ---\n{grok_body}")
                else:
                    self.grok_text.append(f"\n\n--- Round {round_num} ---\n{grok_body}")
            else:
                # First round
                self.grok_text.setPlainText(f"--- Round {round_num} ---\n{grok_body}")
        
        # Update ChatGPT pane with current round
        if hasattr(self, 'chatgpt_text'):
            current_text = self.chatgpt_text.toPlainText()
            if "Round" in current_text or "Waiting" in current_text:
                # Append to existing or replace "Waiting..."
                if "Waiting" in current_text:
                    feedback_text = f"\n[Feedback to Grok]: {feedback}" if feedback else ""
                    context_text = f"\n[Context]: {coverage_summary}" if coverage_summary else ""
                    self.chatgpt_text.setPlainText(f"--- Round {round_num} ---\n{chatgpt_output}{feedback_text}{context_text}")
                else:
                    self.chatgpt_text.append(f"\n\n--- Round {round_num} ---\n{chatgpt_output}")
                    if feedback:
                        self.chatgpt_text.append(f"\n[Feedback to Grok]: {feedback}")
                    if coverage_summary:
                        self.chatgpt_text.append(f"\n[Context]: {coverage_summary}")
            else:
                # First round
                feedback_text = f"\n[Feedback to Grok]: {feedback}" if feedback else ""
                context_text = f"\n[Context]: {coverage_summary}" if coverage_summary else ""
                self.chatgpt_text.setPlainText(f"--- Round {round_num} ---\n{chatgpt_output}{feedback_text}{context_text}")
        
        # Update markdown preview with current version
        if isinstance(template_blocks, dict) and template_blocks:
            self._current_template_blocks = {
                **self._current_template_blocks,
                **{str(k): str(v or "").strip() for k, v in template_blocks.items()},
            }
        if isinstance(document_metadata, dict) and document_metadata:
            self._current_document_metadata = {
                **self._current_document_metadata,
                **{str(k): str(v or "").strip() for k, v in document_metadata.items()},
            }
        evidence_map = round_data.get("evidence_map") or {}
        if isinstance(evidence_map, dict) and evidence_map:
            self._current_template_evidence_map = {
                **self._current_template_evidence_map,
                **{str(k): str(v or "").strip() for k, v in evidence_map.items()},
            }
        unresolved_fields = round_data.get("unresolved_fields") or []
        if isinstance(unresolved_fields, list):
            self._current_unresolved_fields = [str(v).strip() for v in unresolved_fields if str(v).strip()]
        research_gaps = round_data.get("research_gaps") or []
        if isinstance(research_gaps, list):
            self._current_research_gaps = [str(v).strip() for v in research_gaps if str(v).strip()]
        user_questions = round_data.get("user_questions") or []
        if isinstance(user_questions, list):
            self._current_user_questions = [str(v).strip() for v in user_questions if str(v).strip()]
        if markdown and hasattr(self, 'preview_text'):
            self.preview_text.setPlainText(markdown)
            self._current_markdown = markdown
        elif self._last_generated_template_spec and self._current_template_blocks:
            preview = build_template_preview_markdown(
                self._last_generated_template_spec,
                template_blocks=self._current_template_blocks,
                document_metadata=self._current_document_metadata,
            )
            self.preview_text.setPlainText(preview)
            self._current_markdown = preview

        self._update_template_validation_state()
        self._update_template_gap_summary()
        
        QApplication.processEvents()
    
    def _on_collaboration_complete(self, result):
        """Handle completion of collaboration workflow"""
        QTimer.singleShot(0, lambda: self._on_collaboration_complete_safe(result))
    
    def _on_collaboration_complete_safe(self, result):
        """Thread-safe completion handler"""
        # Unpack the result dict safely
        markdown_doc = result.get("markdown", "")
        grok_output = result.get("grok_output", "")
        chatgpt_output = result.get("chatgpt_output", "")
        collaboration_history = result.get("collaboration_history", [])
        rounds = result.get("rounds", 0)
        status = result.get("status", "unknown")
        template_blocks = result.get("template_blocks") or {}
        document_metadata = result.get("document_metadata") or {}
        evidence_map = result.get("evidence_map") or {}
        unresolved_fields = result.get("unresolved_fields") or []
        research_gaps = result.get("research_gaps") or []
        user_questions = result.get("user_questions") or []
        latest_coverage = ""
        if isinstance(collaboration_history, list) and collaboration_history:
            last_entry = collaboration_history[-1] or {}
            latest_coverage = format_reference_pack_summary(last_entry.get("reference_pack_stats"))

        # Persist the run (best-effort)
        try:
            ts = getattr(self, "_last_task_spec", None)
            if ts and hasattr(self.db, "workspace_collab_insert_run"):
                self.db.workspace_collab_insert_run(
                    goal=str(getattr(ts, "goal", "") or ""),
                    context=str(getattr(ts, "context", "") or ""),
                    style=getattr(ts, "style", None),
                    audience=getattr(ts, "audience", None),
                    files=getattr(self, "_last_workspace_files", []) or [],
                    rounds=int(rounds or 0),
                    status=str(status or ""),
                    markdown=str(markdown_doc or ""),
                    grok_output=str(grok_output or ""),
                    chatgpt_output=str(chatgpt_output or ""),
                    collaboration_history=collaboration_history if isinstance(collaboration_history, list) else [],
                )
        except Exception as e:
            logger.warning(f"Could not persist workspace collaboration run: {e}")
        
        # Store markdown for saving
        if isinstance(template_blocks, dict) and template_blocks:
            self._current_template_blocks = {
                **self._current_template_blocks,
                **{str(k): str(v or "").strip() for k, v in template_blocks.items()},
            }
        if isinstance(document_metadata, dict) and document_metadata:
            self._current_document_metadata = {
                **self._current_document_metadata,
                **{str(k): str(v or "").strip() for k, v in document_metadata.items()},
            }
        if isinstance(evidence_map, dict) and evidence_map:
            self._current_template_evidence_map = {
                **self._current_template_evidence_map,
                **{str(k): str(v or "").strip() for k, v in evidence_map.items()},
            }
        if isinstance(unresolved_fields, list):
            self._current_unresolved_fields = [str(v).strip() for v in unresolved_fields if str(v).strip()]
        if isinstance(research_gaps, list):
            self._current_research_gaps = [str(v).strip() for v in research_gaps if str(v).strip()]
        if isinstance(user_questions, list):
            self._current_user_questions = [str(v).strip() for v in user_questions if str(v).strip()]
        self._current_markdown = markdown_doc

        # Show the final Markdown in the preview pane
        if markdown_doc:
            self.preview_text.setPlainText(markdown_doc)
        elif self._last_generated_template_spec and self._current_template_blocks:
            preview = build_template_preview_markdown(
                self._last_generated_template_spec,
                template_blocks=self._current_template_blocks,
                document_metadata=self._current_document_metadata,
            )
            self._current_markdown = preview
            self.preview_text.setPlainText(preview)
        else:
            # Fallback if orchestrator didn't return markdown
            self.preview_text.setPlainText(
                "AI collaboration completed, but no markdown document was returned.\n\n"
                f"Grok output (preview):\n{grok_output[:2000] if grok_output else 'N/A'}\n\n"
                f"ChatGPT output (preview):\n{chatgpt_output[:2000] if chatgpt_output else 'N/A'}"
            )

        # Phase 4 (Workspace Production Engine) micro-increment (2f4c91b8 lineage continuation): auto-append clean professional "Historical Sources Used" section ... [as before]. Chained autonomous micro: added simple consistency check pass (heuristic signal match count) inside the cluster-only path. Advances roadmap "Consistency checking" + "related document sets" with tiniest delta in existing assembly block.
        try:
            if hasattr(self, "historical_examples_list") and self.historical_examples_list is not None and self.historical_examples_list.count() > 0:
                hist_docs = []
                has_related_cluster = False
                for i in range(self.historical_examples_list.count()):
                    it = self.historical_examples_list.item(i)
                    d = it.data(Qt.ItemDataRole.UserRole) or {}
                    if d.get("ref_match") or d.get("related_match"):
                        # local duck-type (no new imports; formatter only needs getattr on these)
                        class _H: pass
                        h = _H()
                        for k, default in (("name", ""), ("doc_type", ""), ("client_hint", ""), ("year", None), ("regulatory_tags", []), ("source_path", "")):
                            setattr(h, k, d.get(k, default))
                        setattr(h, "_ref_match", bool(d.get("ref_match")))
                        setattr(h, "_related_match", bool(d.get("related_match")))
                        hist_docs.append(h)
                        if d.get("related_match"):
                            has_related_cluster = True
                if hist_docs and has_related_cluster:
                    md = (self._current_markdown or "").rstrip()
                    if "Historical Sources Used" not in md:
                        # Autonomous next micro-increment (Phase 4 consistency checking): lightweight heuristic consistency pass against the historical cluster.
                        # Scans generated output for presence of cluster's regulatory_tags/client/doc_type signals (string contains, case-insens). Reports match count in the sources section.
                        # Purely additive, no LLM/IO/new UI, reuses the exact same hist_docs list built for format_compact; defensive; only activates on strong+related cluster path.
                        consistency_note = ""
                        try:
                            md_lower = (self._current_markdown or "").lower()
                            matched = set()
                            for h in hist_docs:
                                for r in (getattr(h, "regulatory_tags", []) or []):
                                    rs = (r or "").strip().lower()
                                    if rs and rs in md_lower:
                                        matched.add(rs)
                                ch = (getattr(h, "client_hint", "") or "").strip().lower()
                                if ch and len(ch) > 2 and ch in md_lower:
                                    matched.add(ch)
                                dt = (getattr(h, "doc_type", "") or "").strip().lower()
                                if dt and dt in md_lower:
                                    matched.add(dt)
                            if matched:
                                consistency_note = f" (cluster consistency pass: {len(matched)} signals from references matched in deliverable)"
                            # Autonomous next micro (after auto-related gen wiring): simple "related set summary" note.
                            # Better handling for docs generated as companions via the _generate_related_set path (now auto-starts workflow).
                            # Detects companion/cluster language in the task goal (from prefill); appends terse note to sources header (visible in preview + all exports).
                            # Reuses _last_task_spec (already present), hist_docs cluster path, consistency_note var; zero UI/risk/IO; only on cluster+related sets.
                            try:
                                g = (getattr(getattr(self, "_last_task_spec", None), "goal", "") or "").lower()
                                if ("companion" in g or "related deliverable task" in g) and "historical cluster" in g:
                                    consistency_note += " [related set: auto-generated companion using identical cluster for cross-set consistency]"
                                    # Tiny seed of related_set_companion flag here (inside sources/consistency block) so the append extension below can key off `related_set_companion` or manifest (per micro-increment spec). Harmless re-setdefault later; defensive.
                                    try:
                                        meta = getattr(self, "_current_document_metadata", None) or {}
                                        if not isinstance(meta, dict):
                                            meta = {}
                                        meta.setdefault("related_set_companion", "1")
                                        meta.setdefault("related_set_note", "auto-generated from identical historical cluster for set-wide style/structure consistency")
                                        self._current_document_metadata = meta
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        except Exception:
                            pass
                        sources_block = format_compact_historical_context(
                            hist_docs,
                            max_items=len(hist_docs) or 4,
                            header="\n\n---\n\n## Historical Sources Used\n\nThis deliverable was produced using the following historical documents (strong reference + related cluster from same client/similar doc_type/regulatory themes). Provides automatic traceability and ensures stylistic/regulatory consistency with prior work" + consistency_note + ":\n"
                        )
                        # Tiniest safe addition (Phase 4 2f4c91b8 continuation, per explicit task): extend the *sources_block itself* (the one already carrying "Historical Sources Used" + consistency + related set note) with a tiny dedicated "Related Document Set Cross-References" subsection when `related_set_companion` or manifest present.
                        # Integrated directly into the block so the note lives *inside* the ## section in each member's final document (preview, save, all exports). Now includes dynamic list of other members + "Companion to XXX via same historical cluster..." relationship (per spec). Fully defensive, zero effect for non-sets. (Downstream append guarded to avoid dup.)
                        try:
                            meta = getattr(self, "_current_document_metadata", {}) or {}
                            has_set_flag = bool(meta.get("related_set_companion")) if isinstance(meta, dict) else False
                            if getattr(self, "_last_related_set_manifest", None) or has_set_flag:
                                # Tiniest extension (per task): compute compact others list + base from live state (companions preferred for accuracy; minimal hist scan for base_name reuses enclosing scope pattern). Appends dynamic listing + relationship phrasing *inside* the sources_block (thus inside ## Historical Sources Used in final member docs). Now delegates to shared _derive... helper (Phase 4 dedup micro) — removed ~15 lines of inline dupe; zero behavior change.
                                # Smallest safe addition inside sources append block (this increment, 2f4c91b8): prefer any pre-seeded rich "related_set_cross_ref_section" (from restore path or prior) for the subsection text; only compute+build if absent. Ensures restored set workspaces get the exact sibling listing inside their Historical Sources Used without re-deriving (e.g. "Companion to the Validation Plan..."). Fully defensive, reuses later-site pattern + now-dedup helper, zero output change.
                                cross_ref = None
                                try:
                                    mm = getattr(self, "_current_document_metadata", {}) or {}
                                    if isinstance(mm, dict):
                                        cross_ref = mm.get("related_set_cross_ref_section")
                                except Exception:
                                    cross_ref = None
                                if not cross_ref:
                                    cross_ref = self._build_related_set_cross_ref() or ""
                                # Tiniest safe addition inside the sources append block (this increment per directive): extend the cross-ref subsection (already appended to ## Historical Sources Used) with explicit set size count when companions data present. Provides richer "listing the other members of the set with their relationships" (e.g. "... (set of 3 companions total)"). Defensive; only mutates when set data active; zero impact otherwise. Reuses _last attr + exact pattern from nearby count seeds.
                                try:
                                    cnt = len(getattr(self, "_last_related_set_companions", None) or [])
                                    if cnt > 0 and cross_ref:
                                        cr = str(cross_ref).rstrip()
                                        if "set of" not in cr.lower() and "companions total" not in cr.lower():
                                            cross_ref = cr + f" (set of {cnt} companions total)"
                                except Exception:
                                    pass
                                sources_block = sources_block.rstrip() + cross_ref
                                # Tiny extension inside sources append block (this micro): also seed the computed cross-ref subsection text into metadata for downstream consumers (template symmetry, save payload, etc.). Purely additive when in set path; uses existing m pattern; defensive. Completes the "extend ... sources append block with tiny additional" for full listing of members/relationships in final docs + state.
                                try:
                                    m = getattr(self, "_current_document_metadata", None) or {}
                                    if isinstance(m, dict):
                                        m.setdefault("related_set_cross_ref_section", cross_ref.strip()[:600])
                                        m["related_set_sources_extended"] = "1"  # tiniest additional (Phase 4 this increment per directive): marker inside sources append block extension site confirming the Related Document Set Cross-References subsection (with Companion/other members listings) was injected into Historical Sources Used for this set member. Defensive; enables downstream consumers (db, restore, exports) to detect extension without parsing markdown; zero output/visible change, only for sets.
                                        self._current_document_metadata = m
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        self._current_markdown = (md + sources_block).rstrip()
                        # keep preview in sync (user sees appended section immediately)
                        if hasattr(self, "preview_text"):
                            self.preview_text.setPlainText(self._current_markdown)

                        # Tiniest safe addition (Phase 4 2f4c91b8 this increment, per directive): extend the *existing sources append block area* (post the conditional Historical Sources Used injection + consistency/related note) with dedicated defensive cross-refs subsection append. Triggers for set members even when LLM output already contained a "Historical Sources Used" section (so the "Related Document Set Cross-References" note + "Companion to the Validation Plan via the same historical cluster for traceability and consistency" + siblings always ends up inside each member's final document). Fully defensive (no dup if already present via prior paths, no-op non-sets); reuses _build + metadata; smallest possible additive per spec. 
                        try:
                            mcheck = getattr(self, "_current_document_metadata", {}) or {}
                            has_flag = bool(mcheck.get("related_set_companion")) if isinstance(mcheck, dict) else False
                            if (getattr(self, "_last_related_set_manifest", None) or has_flag) and "Related Document Set Cross-References" not in (self._current_markdown or ""):
                                crx = mcheck.get("related_set_cross_ref_section") or self._build_related_set_cross_ref() or ""
                                if crx:
                                    addx = crx if str(crx).startswith("\n\n") else "\n\n" + str(crx).strip()
                                    self._current_markdown = (self._current_markdown or "").rstrip() + addx
                                    if hasattr(self, "preview_text"):
                                        self.preview_text.setPlainText(self._current_markdown)
                        except Exception:
                            pass

                        # Phase 4 micro-increment (related document sets cross-refs): tiniest extension of the *existing sources append block* (per spec: extend the "Historical Sources Used" section itself with dedicated cross-refs note when `related_set_companion` or manifest present).
                        # When _last_related_set_manifest or flag: append small continuation **Related Document Set Cross-References** (as part of the section content) listing other members + relationships (e.g. "Companion to the Validation Plan via the same historical cluster..."). 
                        # Now with full metadata symmetry (cross_ref_section + count seeded in both paths) + legacy parse removed (post-dedup). Reuses helper; fully defensive no-op for non-sets. In final docs via _current_markdown export. No behavior change otherwise.
                        try:
                            # Extended condition (tiny): now also triggers on related_set_companion flag (seeded early in sources block) OR manifest. Extends the sources append path with the dedicated cross-refs subsection when set present. Defensive no-op otherwise.
                            meta = getattr(self, "_current_document_metadata", {}) or {}
                            has_set_flag = bool(meta.get("related_set_companion")) if isinstance(meta, dict) else False
                            if getattr(self, "_last_related_set_manifest", None) or has_set_flag:
                                gg = (getattr(getattr(self, "_last_task_spec", None), "goal", "") or "").lower()
                                if has_set_flag or (("companion" in gg or "related deliverable task" in gg) and "historical cluster" in gg):  # defensive parens + explicit set flag first; extends sources append handling for cross-refs subsection (tiny, same behavior)
                                    # Use shared dedup helper (Phase 4 dedup + persistence): base + others now always from companions (preferred) or hist ref scan. Legacy manifest parse removed (one-more micro): no longer reached/needed post _last_related_set_companions + restore; keeps the sources append extension site minimal. man line also dropped (was only for legacy).
                                    base_name, others = self._derive_related_set_base_and_others()
                                    # Keep-going tiniest (chained no-pause): also seed companions_count into metadata from this path (for list/db consumers + badge parity with seed path); reuses live attr + defensive setdefault pattern. Zero effect outside sets.
                                    try:
                                        cnt = len(getattr(self, "_last_related_set_companions", None) or [])
                                        m = getattr(self, "_current_document_metadata", None) or {}
                                        if isinstance(m, dict):
                                            m.setdefault("related_set_companions_count", cnt)
                                            self._current_document_metadata = m
                                    except Exception:
                                        pass
                                    if others and "Related Document Set Cross-References" not in (self._current_markdown or ""):
                                        # Tiniest polish inside sources append block (this micro, Phase 4 keep-going after primary cross-refs extension): prefer pre-seeded rich "related_set_cross_ref_section" (from first sources_block path or restore) to avoid duplicating the relationship string build here. Reuses exact text+phrasing ("Companion to ... Other set members...") produced by the tiny dedicated subsection addition. Falls back to build only if not present (covers pure second-path cases). Keeps the overall sources append extension site minimal + DRY; 100% defensive, zero behavior or output change.
                                        cross = None
                                        try:
                                            mm = getattr(self, "_current_document_metadata", {}) or {}
                                            if isinstance(mm, dict):
                                                cross = mm.get("related_set_cross_ref_section")
                                        except Exception:
                                            cross = None
                                        if not cross:
                                            # fallback now delegates to shared tiny dedup helper (Phase 4 keep-going): removes last inline dupe of the relationship phrasing; helper handles pre-seed + derive + exact text for "Companion to ... via same ... Other set members". Preserves 100% identical output for the subsection inside Historical Sources Used (or appended).
                                            cross = self._build_related_set_cross_ref()
                                        if cross and not str(cross).startswith("\n\n"):
                                            cross = "\n\n" + str(cross).strip()
                                        self._current_markdown = (self._current_markdown or "").rstrip() + cross
                                        if hasattr(self, "preview_text"):
                                            self.preview_text.setPlainText(self._current_markdown)
                                        # Tiniest symmetry addition inside the *second* sources-append cross-refs site (this micro, Phase 4 2f4c91b8 keep-going): seed the rich "related_set_cross_ref_section" (with full "Companion to ... Other set members: ..." listing + relationship phrasing) into _current_document_metadata. Mirrors the exact guarded setdefault from the first (new-sources) path 60 lines above. Ensures metadata always carries the member cross-refs text for ALL generation entrypoints (save payloads, details dialog from list, future template consumers, etc.). Purely additive when set; defensive; no change for non-sets or other paths. Directly extends the handling around the sources append block per lineage.
                                        try:
                                            m = getattr(self, "_current_document_metadata", None) or {}
                                            if isinstance(m, dict):
                                                m.setdefault("related_set_cross_ref_section", (cross or "").strip()[:600])
                                                self._current_document_metadata = m
                                        except Exception:
                                            pass
                                    # Wire small call here in post-gen block (Phase 4 auto-summary micro-increment): create the Related Set Summary document content (reusing helper + manifest) and store for auto-inclusion in client folder exports (quick + manual). Only for actual set companions; set once. Defensive; no behavior change for non-sets. Appears alongside manifests in exports.
                                    # Autonomous chained one-more micro (Phase 4, no-stop): simple "Related Set" note/badge injected into the *main preview pane* (_current_markdown + preview_text) for generated set members. Visible immediately on Generate Draft for companions (top-of-doc callout, after cross-refs). Reuses has_set_flag + manifest context from the sources-append extension; tiniest ~7-line additive; defensive (no-op for non-sets). Complements list badges + doc-internal subsection with live preview visibility.
                                    try:
                                        if has_set_flag or getattr(self, "_last_related_set_manifest", None):
                                            # Autonomous one-more micro (no pause after sources block count enrichment): tiniest extension of the preview pane "Related Set" badge (central live production surface) to include explicit count. Reuses same cnt logic; makes badge richer for "Related Set" visibility in main Workspace UI for generated set members. Defensive, only in set path.
                                            try:
                                                cnt = len(getattr(self, "_last_related_set_companions", None) or [])
                                                cnt_str = f" (set of {cnt} companions)" if cnt > 0 else ""
                                            except Exception:
                                                cnt_str = ""
                                            set_badge = f"\n\n> **🟣 [Related Document Set member]**{cnt_str} Companion via the same historical cluster (see extended 'Historical Sources Used' section (with embedded Related Document Set Cross-References) below for siblings/relationships + traceability). Manifest + Summary written to client folder on export."
                                            cur_md = (self._current_markdown or "").strip()
                                            self._current_markdown = set_badge + ("\n\n" + cur_md if cur_md else "")
                                            if hasattr(self, "preview_text"):
                                                self.preview_text.setPlainText(self._current_markdown)
                                            # One-more autonomous micro (Phase 4 keep-going after sources cross-refs extension in Historical Sources block): tiniest defensive append of the Related Document Set Cross-References subsection (prefer pre-seeded rich from metadata/_build) directly into final _current_markdown for set members. Ensures the sibling listing/relationship note is *always* in the produced member doc (even restored sets or LLM-pre-existing Historical Sources cases). Reuses exact helper+pattern; zero effect non-sets; smallest 3-line additive inside existing set-badge try.
                                            try:
                                                cr = (getattr(self, "_current_document_metadata", {}) or {}).get("related_set_cross_ref_section") or self._build_related_set_cross_ref() or ""
                                                if cr and "Related Document Set Cross-References" not in (self._current_markdown or ""):
                                                    add = cr if str(cr).startswith("\n\n") else "\n\n" + str(cr).strip()
                                                    self._current_markdown = (self._current_markdown or "").rstrip() + add
                                                    if hasattr(self, "preview_text"):
                                                        self.preview_text.setPlainText(self._current_markdown)
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                    if not getattr(self, "_last_related_set_summary", None):
                                        summ = self._make_related_set_summary()
                                        if summ:
                                            self._last_related_set_summary = summ
                        except Exception:
                            # never break on cross-ref append
                            pass
        except Exception:
            # never break generation/export on traceability append
            pass

        # Chained Phase 4 micro (autonomous continuation): when cluster was used (same list scan), defensively seed _current_document_metadata with client_hint from the ref/related for symmetry on the *template* export/render path (enriches metadata passed to render_workspace_template_to_docx + validation). No visible effect until templates consume extra keys; zero risk, no UI, reuses existing data. Smallest delta.
        try:
            if hasattr(self, "historical_examples_list") and self.historical_examples_list and self.historical_examples_list.count() > 0:
                for i in range(min(3, self.historical_examples_list.count())):
                    dd = self.historical_examples_list.item(i).data(Qt.ItemDataRole.UserRole) or {}
                    if dd.get("ref_match") or dd.get("related_match"):
                        ch = dd.get("client_hint")
                        if ch:
                            self._current_document_metadata.setdefault("client", str(ch)[:60])
                            self._current_document_metadata.setdefault("prepared_for", str(ch)[:60])
                            self._current_document_metadata.setdefault("historical_cluster_used", "1")
                        # Autonomous next micro-increment (project linking for related sets): also seed project_hint (when present in cluster data) into metadata.
                        # This makes generated related set companion documents automatically carry/link to the same client/project in the system (for save, export, template renders, downstream project tabs, etc.). Reuses exact setdefault + dd scan pattern; defensive; only on cluster path. Continues the "keep going, no stop" chained micro pattern.
                        ph = dd.get("project_hint")
                        if ph:
                            self._current_document_metadata.setdefault("project", str(ph)[:60])
                            self._current_document_metadata.setdefault("project_hint", str(ph)[:60])
                        # Next autonomous micro (keep going, no stop): seed related set info into _current_document_metadata (used by export_markdown, quick_export, template renders, save).
                        # Detects the auto-launched companion case (from _generate_related_set prefill + goal); enables downstream export handling of related sets (e.g. future filename suffix, manifest, client notes). Reuses exact _last_task_spec + setdefault pattern already in block; smallest 4 lines, defensive, only when cluster+related companion.
                        g = (getattr(getattr(self, "_last_task_spec", None), "goal", "") or "").lower()
                        if "companion" in g and "historical cluster" in g:
                            self._current_document_metadata.setdefault("related_set_companion", "1")
                            self._current_document_metadata.setdefault("related_set_note", "auto-generated from identical historical cluster for set-wide style/structure consistency")
                            # Autonomous keep-going micro (no stop, per queued in summary): seed compact cross-ref note into metadata for template/render symmetry + future placeholder consumption (e.g. in render_workspace_template_to_docx or document_assembler). Reuses the exact setdefault + if pattern + phrasing from the sources cross-refs extension. Defensive; only for set companions; enables downstream use without breaking current renders.
                            self._current_document_metadata.setdefault("related_set_cross_ref_note", "🟣 Related Document Set member — companion via the same historical cluster for traceability and consistency (see extended 'Historical Sources Used' section with Related Document Set Cross-References for siblings). _Related_Set_Manifest.txt + Summary also in client folder on export.")
                        break
        except Exception:
            pass

        # Enable save buttons
        if hasattr(self, 'save_button'):
            self.save_button.setEnabled(True)
        if hasattr(self, 'export_button'):
            self.export_button.setEnabled(True)
        if hasattr(self, "extract_tasks_button"):
            self.extract_tasks_button.setEnabled(bool(self._current_markdown.strip()))
        self._on_workspace_state_changed()
        self._update_template_validation_state()
        self._update_template_gap_summary()

        status_text = f"AI collaboration complete ({status}, {rounds} round{'s' if rounds != 1 else ''})"
        if self._current_template_validation_issues:
            status_text = f"{status_text} | Template validation needed"
        if self._current_user_questions:
            status_text = f"{status_text} | {len(self._current_user_questions)} user question(s)"
        if self._current_research_gaps:
            status_text = f"{status_text} | {len(self._current_research_gaps)} research gap(s)"
        resolved_total = sum(len(v) for v in (self._resolved_gap_snapshot or {}).values())
        if resolved_total:
            status_text = f"{status_text} | resolved {resolved_total} prior gap(s)"
        if latest_coverage:
            status_text = f"{status_text} | {latest_coverage}"
        # Next autonomous micro-increment (Phase 4 related document sets, chained no-stop): tiny visibility note in the primary collaboration completion status (main Workspace UI surface). When the just-generated doc carries the related_set_companion flag or manifest (seeded in this same post-gen for companions from Generate Related Set), append a concise note. Reuses exact metadata pattern + status_text construction already live; surfaces "Related Set" + hint at Summary+Manifest for easy discovery right after gen (before any export/list click). Defensive zero effect otherwise; smallest 5-line addition. Chained micro (this): added the short professional " | Related set cross-references added to Historical Sources Used" append (one guarded line inside the if reusing the flag/condition for the badge/status note), plus detection now includes manifest for full "produced related set" case. No behavior change for non-sets.
        try:
            meta = getattr(self, "_current_document_metadata", {}) or {}
            if meta.get("related_set_companion") or getattr(self, "_last_related_set_manifest", None):
                status_text = f"{status_text} | Related Set member (Summary + Manifest auto-included on client export; cross-refs + sibling listings now inside 'Historical Sources Used' via sources append block extension) | Related set cross-references added to Historical Sources Used"
        except Exception:
            pass

        # Billing Depth next micro-increment (autonomous chained, no pause after first billing-for-set + exports): automatic time-entry suggestion surfacing based on recent related document generation (or any gen with cluster).
        # Reuses the exact client scan + _last_task_spec already in scope in this completion block (and historical cluster presence). Appends concise actionable suggestion to the primary status (main UI surface after gen). No new widgets/IO/db writes; purely advisory + points to the new Generate Billing action + Billing tab for capture. Defensive; only when client context from cluster.
        try:
            cl_from_ref = None
            ph_from_ref = None
            if hasattr(self, "historical_examples_list") and self.historical_examples_list:
                for i in range(min(6, self.historical_examples_list.count())):
                    it = self.historical_examples_list.item(i)
                    dd = it.data(Qt.ItemDataRole.UserRole) or {}
                    if dd.get("ref_match") or dd.get("related_match"):
                        cl_from_ref = dd.get("client_hint")
                        ph_from_ref = dd.get("project_hint")
                        break
            if cl_from_ref:
                ts = getattr(self, "_last_task_spec", None)
                obj = (getattr(ts, "objective", None) or getattr(ts, "instructions", None) or "")[:50] if ts else ""
                title_hint = (getattr(ts, "document_type", None) or "deliverable work") if ts else "generated doc"
                sug = f"💰 Billing: consider time entry for '{title_hint}' on {cl_from_ref}" + (f"/{ph_from_ref}" if ph_from_ref else "") + " (use Generate Billing for Set from list menu for summary; capture in Billing tab)"
                if "Billing" not in status_text:
                    status_text = f"{status_text} | {sug}"
        except Exception:
            pass

        selected = []
        spec = getattr(self, "_last_task_spec", None)
        if spec and "Suggested Tasks (importable)" in (getattr(spec, "context", "") or ""):
            md_import = (self._current_markdown or "").strip()
            if md_import:
                try:
                    tasks, _warnings = parse_suggested_tasks(md_import)
                    for t in tasks:
                        try:
                            task_id = self.db.add_task(
                                "workspace_import",
                                t.title,
                                t.due_mmddyyyy,
                                category=t.category,
                            )
                            if hasattr(self.db, "update_task_by_id"):
                                try:
                                    self.db.update_task_by_id(int(task_id), priority=int(t.priority or 0))
                                except Exception:
                                    pass
                            selected.append(t)
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning(f"Workspace auto task import skipped: {e}")

        if selected:
            demo_fc = getattr(self, "_demo_full_cycle_pending_assignment", False)
            st_import = (
                f"✓ Draft ready + {len(selected)} tasks imported. Check Tasks tab or Chief of Staff."
            )
            if demo_fc:
                # Single completion toast/notify is sent from _demo_full_cycle_finish_after_collaboration.
                self.status_label.setText(st_import)
                btn = getattr(self, "view_chief_of_staff_btn", None)
                if btn is not None:
                    btn.setVisible(True)
            else:
                self._offer_chief_of_staff_after_task_import(
                    len(selected),
                    status_line=st_import,
                    toast_title="Workspace draft",
                    toast_message=(
                        f"{len(selected)} task(s) imported. Check Tasks tab or Chief of Staff."
                    ),
                )
        else:
            self.status_label.setText(status_text)

        self._demo_full_cycle_finish_after_collaboration()

        self.progress_bar.setValue(100)
        QApplication.processEvents()
        self.progress_bar.setVisible(False)
        if hasattr(self, "generate_draft_btn"):
            self.generate_draft_btn.setEnabled(True)
            self.generate_draft_btn.setText("Generate Draft")

    def extract_suggested_tasks(self):
        """
        Parse the current markdown for a '## Suggested Tasks (importable)' section,
        then open a review dialog that lets the user accept/decline/edit before insertion.
        """
        self._hide_chief_of_staff_followup()
        md = (self._current_markdown or "").strip()
        if not md:
            QMessageBox.information(self, "Suggested Tasks", "No markdown document is available yet.")
            return

        tasks, warnings = parse_suggested_tasks(md)
        if not tasks:
            details = "\n".join(warnings) if warnings else "No tasks found."
            QMessageBox.information(self, "Suggested Tasks", f"No importable tasks were found.\n\n{details}")
            return

        dlg = TaskImportDialog(tasks=tasks, warnings=warnings, parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            self.status_label.setText("Task import cancelled")
            return

        selected = dlg.selected_tasks()
        if not selected:
            self.status_label.setText("No tasks selected for import")
            return

        created = 0
        failed = 0
        for t in selected:
            try:
                task_id = self.db.add_task(
                    "workspace_import",
                    t.title,
                    t.due_mmddyyyy,
                    category=t.category,
                )
                if hasattr(self.db, "update_task_by_id"):
                    try:
                        self.db.update_task_by_id(int(task_id), priority=int(t.priority or 0))
                    except Exception:
                        pass
                created += 1
            except Exception:
                failed += 1

        if created > 0:
            st = f"✓ {created} task(s) imported. Open Chief of Staff to delegate."
            if failed:
                st = f"{st} ({failed} failed)"
            self._offer_chief_of_staff_after_task_import(
                created,
                status_line=st,
                toast_title="Suggested tasks",
                toast_message=(
                    f"{created} task(s) imported. Open Chief of Staff to delegate."
                    + (f" ({failed} could not be saved.)" if failed else "")
                ),
            )
        elif failed:
            self.status_label.setText(f"Task import failed ({failed} error(s))")

        if failed:
            QMessageBox.warning(
                self,
                "Suggested Tasks",
                f"Imported {created} task(s), but {failed} failed to insert.\n\n"
                "Open the Tasks tab to confirm what was created.",
            )
    
    def _on_collaboration_error(self, error_msg):
        """Handle errors from collaboration workflow"""
        QTimer.singleShot(0, lambda: self._on_collaboration_error_safe(error_msg))
    
    def _on_collaboration_error_safe(self, error_msg):
        """Thread-safe error handler"""
        self._demo_full_cycle_abort_if_pending(reason="workspace collaboration failed")
        logger.error(f"Error in AI collaboration workflow: {error_msg}")
        self.status_label.setText("Error during workflow")
        self.progress_bar.setVisible(False)
        self.preview_text.setPlainText(f"Error running AI collaboration workflow: {error_msg}")
        if hasattr(self, "template_gap_summary") and self.template_gap_summary is not None:
            self.template_gap_summary.setVisible(False)
        if hasattr(self, 'grok_text'):
            self.grok_text.setPlainText(f"Error: {error_msg}")
        if hasattr(self, 'chatgpt_text'):
            self.chatgpt_text.setPlainText("Workflow failed before ChatGPT step.")
        if hasattr(self, "generate_draft_btn"):
            self.generate_draft_btn.setEnabled(True)
            self.generate_draft_btn.setText("Generate Draft")
    
    def save_markdown(self):
        """Save the current markdown document to a file"""
        if not self._current_markdown:
            self.status_label.setText("No document to save")
            return
        
        # Chained Phase 4 micro (filename seeding): also apply cluster-derived client+doc_type prefix to the plain Save Markdown default (reuses identical scan pattern; defensive). Keeps all export/save paths consistent with historical cluster for professional client deliverables.
        default_filename = f"workspace_document_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        try:
            if hasattr(self, "historical_examples_list") and self.historical_examples_list:
                for i in range(min(3, self.historical_examples_list.count())):
                    dd = self.historical_examples_list.item(i).data(Qt.ItemDataRole.UserRole) or {}
                    if dd.get("ref_match") or dd.get("related_match"):
                        ch = re.sub(r'[^A-Za-z0-9_-]', '', str(dd.get("client_hint") or ""))[:20]
                        dt = re.sub(r'[^A-Za-z0-9_-]', '', str(dd.get("doc_type") or "doc"))[:20]
                        if ch:
                            default_filename = f"{ch}_{dt}_{datetime.now().strftime('%Y%m%d')}.md"
                        break
        except Exception:
            pass
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Markdown Document",
            default_filename,
            "Markdown Files (*.md);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self._current_markdown)
                self.status_label.setText(f"Document saved to {os.path.basename(file_path)}")
            except Exception as e:
                logger.error(f"Error saving markdown: {e}")
                self.status_label.setText(f"Error saving file: {str(e)}")
    
    def export_markdown(self):
        """Export markdown in different formats"""
        if not self._current_markdown:
            self.status_label.setText("No document to export")
            return

        # Phase 4 micro (continued, chained after style guidance): use client + doc_type from injected strong/related historical ref/cluster to suggest richer client+type-prefixed export filename (e.g. AcmeCorp_SOP_20260519) inside the client subfolder. Reuses exact same ref/related scan loop + safe sanitization. Advances "related document sets" naming consistency + production traceability without any new UI or risk. Defensive; only enhances when cluster present (falls back to prior behavior).
        suggested = f"workspace_document_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            client_from_ref = None
            dtype_from_ref = None
            if hasattr(self, "historical_examples_list") and self.historical_examples_list:
                for i in range(min(6, self.historical_examples_list.count())):
                    it = self.historical_examples_list.item(i)
                    dd = it.data(Qt.ItemDataRole.UserRole) or {}
                    if dd.get("ref_match") or dd.get("related_match"):
                        client_from_ref = dd.get("client_hint")
                        dtype_from_ref = dd.get("doc_type")
                        break
            if client_from_ref:
                safe = re.sub(r'[^A-Za-z0-9_-]', '', str(client_from_ref))[:30]
                safe_dtype = re.sub(r'[^A-Za-z0-9_-]', '', str(dtype_from_ref or "workspace"))[:25] if dtype_from_ref else "workspace"
                client_dir = os.path.join("data", "workspace_output", safe)
                try:
                    os.makedirs(client_dir, exist_ok=True)
                    suggested = os.path.join(client_dir, f"{safe}_{safe_dtype}_{datetime.now().strftime('%Y%m%d')}")
                except Exception:
                    suggested = f"{safe}_{safe_dtype}_{datetime.now().strftime('%Y%m%d')}"
        except Exception:
            pass

        # Autonomous next micro-increment (Phase 4 related document sets, no stopping): extend filename suggestion symmetry for manual export path (the full "Export" button + dialog).
        # Reuses the *exact same* related_set_companion metadata flag (seeded post-gen for companions) + conditional suffix pattern already live in _quick_export_to_client_folder (base += "_related-set-companion").
        # Tiny guarded addition here before the getSaveFileName (so suggested in dialog already carries the set marker when applicable). Defensive, only affects set-member docs, falls back silently; keeps all export paths consistent for client folder grouping/traceability. 6 lines, zero risk.
        try:
            if getattr(self, "_current_document_metadata", {}).get("related_set_companion"):
                if "_related-set-companion" not in str(suggested):
                    suggested = f"{suggested}_related-set-companion"
        except Exception:
            pass

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Document",
            suggested,
            "Word Document (*.docx);;PDF (*.pdf);;Markdown Files (*.md);;Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                selected = (selected_filter or "").lower()
                ext = os.path.splitext(str(file_path or ""))[1].lower()
                if (
                    self._last_generated_template_spec
                    and self._current_template_blocks
                    and ("docx" in selected or "pdf" in selected or ext in {".docx", ".pdf"})
                ):
                    if not self._ensure_template_payload_valid_for_export():
                        return
                    target_docx = file_path
                    if "pdf" in selected or ext == ".pdf":
                        with tempfile.TemporaryDirectory(prefix="workspace_template_export_") as tmpdir:
                            temp_docx = os.path.join(tmpdir, "workspace_template.docx")
                            render_workspace_template_to_docx(
                                spec=self._last_generated_template_spec,
                                template_blocks=self._current_template_blocks,
                                output_path=temp_docx,
                                document_metadata=self._current_document_metadata,
                            )
                            exported_path = export_docx_to_pdf(temp_docx, file_path if ext == ".pdf" else f"{file_path}.pdf")
                    else:
                        if ext != ".docx":
                            target_docx = f"{file_path}.docx"
                        exported_path = render_workspace_template_to_docx(
                            spec=self._last_generated_template_spec,
                            template_blocks=self._current_template_blocks,
                            output_path=target_docx,
                            document_metadata=self._current_document_metadata,
                        )
                else:
                    exported_path = export_markdownish_document(
                        title="Workspace Document",
                        text=self._current_markdown,
                        file_path=file_path,
                        selected_filter=selected_filter,
                    )
                status_msg = f"Document exported to {os.path.basename(exported_path)}"
                try:
                    if (getattr(self, "_current_document_metadata", {}) or {}).get("related_set_companion"):
                        status_msg += " (cross-refs inside Historical Sources Used + manifest/summary alongside)"
                        status_msg += " | Related set cross-references added to Historical Sources Used"
                        status_msg += " (sibling listings + Companion to... relationships for set members)"
                except Exception:
                    pass
                self.status_label.setText(status_msg)
                # Autonomous continuation micro (no stop): also include Related Set Manifest in *manual* export path (dialog chosen dir, typically the client subfolder suggested from cluster). Writes the tiny traceability note (companions + shared cluster) next to the exported doc when manifest was prepared by Generate Related Set. Defensive, uses dirname of exported_path, same filename convention; complements the quick_export version. Zero impact on non-set exports.
                try:
                    if getattr(self, "_last_related_set_manifest", None) and exported_path:
                        man_dir = os.path.dirname(exported_path) or "."
                        man_path = os.path.join(man_dir, os.path.basename(exported_path).rsplit('.', 1)[0] + "_Related_Set_Manifest.txt")
                        # fallback simple name if issues
                        if not man_path or "None" in man_path:
                            man_path = os.path.join(man_dir, "Related_Set_Manifest.txt")
                        with open(man_path, 'w', encoding='utf-8') as mf:
                            mf.write(self._last_related_set_manifest)
                except Exception:
                    pass  # never break export
                # Phase 4 auto-summary micro (chained, manual export path): also include the auto-generated Related Set Summary (created in post-gen block) alongside the manifest + deliverable in the chosen export dir. Mirrors the exact manifest write pattern + defensive fallback here for naming/dir; uses .md extension. Reuses _make helper fallback. No behavior change when not a set or no summary.
                try:
                    if exported_path:
                        summ = getattr(self, "_last_related_set_summary", None) or self._make_related_set_summary()
                        if summ:
                            sum_dir = os.path.dirname(exported_path) or "."
                            sum_base = os.path.basename(exported_path).rsplit('.', 1)[0] + "_Related_Set_Summary.md"
                            sum_path = os.path.join(sum_dir, sum_base)
                            if not sum_path or "None" in sum_path:
                                sum_path = os.path.join(sum_dir, "Related_Set_Summary.md")
                            with open(sum_path, 'w', encoding='utf-8') as sf:
                                sf.write(summ)
                except Exception:
                    pass  # never break export
                # Billing Depth micro (chained, manual export path): mirror the summary write for billing artifact (defensive, same dir/fallback naming). Completes "direct export of billing packages into client folders" for the set when billing summary was generated via the new action (or restored). Uses identical pattern; .md; non-fatal.
                try:
                    if exported_path and getattr(self, "_last_billing_artifact", None):
                        bill_dir = os.path.dirname(exported_path) or "."
                        bill_base = os.path.basename(exported_path).rsplit('.', 1)[0] + "_Billing_Summary_for_Set.md"
                        bill_path = os.path.join(bill_dir, bill_base)
                        if not bill_path or "None" in bill_path:
                            bill_path = os.path.join(bill_dir, "Billing_Summary_for_Set.md")
                        with open(bill_path, 'w', encoding='utf-8') as bf:
                            bf.write(self._last_billing_artifact)
                except Exception:
                    pass  # never break export
                # Seed for historical list badge (Phase 4 related set visibility): same as quick_export path; ensures exported set companions get the extra flag and appear marked in the list
                try:
                    self._seed_related_set_member_record()
                except Exception:
                    pass
                # Phase 4 GDrive upload (this micro): one-liner call (mirrors quick_export). Only when cluster/client context (client_from_ref from suggestion scan). Defensive; artifacts use in-mem _last_ for canonical names in GDrive folder.
                try:
                    self._try_gdrive_client_folder_upload(client_from_ref, exported_path)
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Error exporting markdown: {e}")
                self.status_label.setText(f"Error exporting file: {str(e)}")

    def _update_template_validation_state(self):
        self._current_template_validation_issues = []
        spec = self._last_generated_template_spec
        if not spec:
            self._update_template_gap_summary()
            return
        if not self._current_template_blocks and not self._current_document_metadata:
            self._update_template_gap_summary()
            return
        result = validate_template_payload(
            spec,
            template_blocks=self._current_template_blocks,
            document_metadata=self._current_document_metadata,
        )
        self._current_template_validation_issues = result.issues()
        self._update_template_gap_summary()

    def _ensure_template_payload_valid_for_export(self) -> bool:
        self._update_template_validation_state()
        if not self._current_template_validation_issues:
            return True
        details = "\n".join(self._current_template_validation_issues)
        QMessageBox.warning(
            self,
            "Template Validation Failed",
            "The generated template data is incomplete or malformed, so template-based export was blocked.\n\n"
            f"{details}\n\n"
            "Re-run Generate Draft or switch to a markdown/text export.",
        )
        self.status_label.setText("Template validation failed before export")
        return False


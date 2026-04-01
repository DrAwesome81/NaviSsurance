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
)
from PyQt6.QtCore import Qt, QMimeData, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QDropEvent, QDragEnterEvent, QPainter, QColor
# from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
import json
import os
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
from core.file_handler import extract_text_from_file
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

        self.quill_chat_group = QGroupBox("Direct chat with Quill (Technical Writer)")
        self.quill_chat_group.setCheckable(True)
        self.quill_chat_group.setChecked(False)
        quill_chat_layout = QVBoxLayout(self.quill_chat_group)
        self.quill_console = AgentConsole(
            self.db,
            agent_code="quill",
            parent=self,
            context_provider=self._build_quill_runtime_context,
        )
        self.quill_console.setVisible(False)
        quill_chat_layout.addWidget(self.quill_console)
        self.quill_chat_group.toggled.connect(
            lambda checked: self.quill_console.setVisible(bool(checked))
        )
        layout.addWidget(self.quill_chat_group)
        
        self.setLayout(layout)

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
        file_layout.addWidget(self.include_task_suggestions_checkbox)
        self.max_rounds_spinbox.valueChanged.connect(self._on_workspace_state_changed)
        self.prompt_template_combo.currentIndexChanged.connect(self._on_workspace_state_changed)
        
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
        self.generate_draft_btn.setStyleSheet("background-color: #FD6262; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 500;")
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
        file_layout.addWidget(self.file_list)
        
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
        self.save_button.setStyleSheet(
            "background-color: #FD6262; color: white; border: none; padding: 8px 16px; "
            "border-radius: 6px; font-weight: 500;"
        )
        self.save_button.setMinimumHeight(38)
        self.save_button.setMinimumWidth(160)
        self.save_button.clicked.connect(self.save_markdown)
        self.save_button.setEnabled(False)  # Disabled until document is generated
        button_bar.addWidget(self.save_button)
        
        self.export_button = QPushButton("Export as...")
        self.export_button.setStyleSheet(
            "background-color: #3a3b3e; color: #e8eaed; border: 1px solid #2e2f32; "
            "padding: 8px 16px; border-radius: 6px; font-weight: 500;"
        )
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
            "saved_at": datetime.now().isoformat(),
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

    def _upsert_virtual_workspace_file(self, *, path: str, name: str, content: str, marked: bool = True) -> bool:
        normalized_path = str(path or "").strip()
        payload = {
            "name": str(name or "Atlas Research Notes"),
            "path": normalized_path,
            "is_folder": False,
            "size": len(content or ""),
            "modified": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "marked": bool(marked),
            "virtual": True,
            "content": str(content or "").strip(),
            "source_type": "atlas_research",
            "source_assignment_id": int((self._latest_merged_atlas_info or {}).get("assignment_id") or 0),
            "source_title": str((self._latest_merged_atlas_info or {}).get("title") or ""),
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
            self.saved_workspace_combo.addItem(str(item.get("name") or ""), int(item.get("id") or 0))
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
            self.status_label.setText(f"{status_prefix}: {record.get('name', 'workspace')} ({loaded} files)")
            return True
        return False

    def _apply_workspace_state(self, payload: dict, *, workspace_id: int | None, workspace_name: str) -> int:
        self._restoring_workspace_state = True
        try:
            self._clear_workspace_files(reset_saved_workspace=False)
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

    def _clear_workspace_files(self, *, reset_saved_workspace: bool = True):
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
        if reset_saved_workspace:
            self._current_workspace_id = None
            self._current_workspace_name = ""
            if hasattr(self.db, "workspace_state_set_last_used"):
                self.db.workspace_state_set_last_used(None)

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

    def get_file_content(self, file_info):
        """Get file content with caching to avoid repeated disk I/O."""
        if bool(file_info.get("virtual")):
            return str(file_info.get("content") or "")
        if 'content' not in file_info:
            try:
                # Use file_handler for proper extraction
                content = extract_text_from_file(file_info['path'])
                if not content or content.strip() == "":
                    # Fallback for unsupported file types
                    file_ext = os.path.splitext(file_info['name'])[1].lower()
                    if file_ext in {'.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml', '.csv'}:
                        with open(file_info['path'], 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                    else:
                        content = f"[File: {file_info['name']} - content extraction not available for this file type]"
                        logger.warning(f"Could not extract content from {file_info['name']} (type: {file_ext})")
                
                if not content or content.strip() == "":
                    logger.warning(f"Empty content extracted from {file_info['name']}")
                    
            except Exception as e:
                logger.error(f"Error extracting content from {file_info['path']}: {e}")
                content = f"[Error extracting content from {file_info['name']}: {str(e)}]"
            
            # Cache the content for future use
            file_info['content'] = content
        
        return file_info['content']

    @staticmethod
    def _has_usable_source_content(content: str) -> bool:
        text = str(content or "").strip()
        if not text:
            return False
        if text.startswith("[Error"):
            return False
        if text.startswith("[File:"):
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

    def run_ai_collaboration_workflow(self):
        """
        Run the dual-LLM collaboration workflow on the marked files.

        For now this:
        - Collects marked files
        - Asks the user what they want the AI to do
        - Calls DualLLMOrchestrator.run_once(...)
        - Shows the resulting Markdown in the preview pane
        - Shows Grok and ChatGPT outputs in their respective panes
        """
        try:
            self.merge_latest_atlas_research()
            marked_files = [f for f in self.selected_files if f.get("marked")]
            selected_template_spec = self._selected_document_template_spec()
            self._capture_gap_baseline_for_next_run()
            
            # Ask the user what they want Grok + ChatGPT to do
            if marked_files:
                prompt_text = f"Describe what you want Grok + ChatGPT to do with these {len(marked_files)} file(s):"
            else:
                prompt_text = "Describe what you want Grok + ChatGPT to research and create (no files uploaded):"

            default_instructions = ""
            try:
                template_key = None
                if getattr(self, "prompt_template_combo", None) is not None:
                    template_key = self.prompt_template_combo.currentData()
                if template_key and template_key != "custom":
                    default_instructions = str(self._prompt_templates().get(str(template_key), {}).get("prompt") or "")
            except Exception:
                default_instructions = ""
            
            instructions, ok = QInputDialog.getText(
                self,
                "AI Collaboration Instructions",
                prompt_text,
                text=default_instructions,
            )
            if not ok or not instructions.strip():
                self.status_label.setText("AI collaboration cancelled")
                return

            # Convert marked_files into WorkspaceFile objects and extract content (if any)
            workspace_files = []
            file_contents = {}  # Map file paths to their content
            
            if marked_files:
                self.status_label.setText("Extracting file contents...")
                self.progress_bar.setVisible(True)
                self.progress_bar.setValue(0)
                QApplication.processEvents()
                
                total_files = len(marked_files)
                for idx, f in enumerate(marked_files):
                    self.status_label.setText(f"Extracting content from {f['name']}... ({idx+1}/{total_files})")
                    self.progress_bar.setValue(int((idx / total_files) * 30))  # First 30% for extraction
                    QApplication.processEvents()
                    
                    # Extract and cache file content
                    content = self.get_file_content(f)
                    # Normalize file path for consistent matching
                    file_path = str(f["path"] or "").strip()
                    if not bool(f.get("virtual")):
                        file_path = os.path.abspath(file_path)
                    
                    # Validate content extraction
                    if not content or content.startswith("[Error") or content.startswith("[File:"):
                        logger.warning(f"Empty or error content for {f['name']}: {content[:100] if content else 'No content'}")
                    
                    logger.info(f"Extracted {len(content)} chars from {file_path}")
                    file_contents[file_path] = content
                    
                    workspace_files.append(
                        WorkspaceFile(
                            path=file_path,  # Use normalized path
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
                    if hasattr(self, 'grok_text'):
                        self.grok_text.setPlainText("Source extraction failed for all marked files.")
                    if hasattr(self, 'chatgpt_text'):
                        self.chatgpt_text.setPlainText("Workflow did not start because no usable source content was available.")
                    return
            else:
                # No files - just research request
                self.status_label.setText("Starting research collaboration...")
                self.progress_bar.setVisible(True)
                self.progress_bar.setValue(10)
                QApplication.processEvents()

            # Build the task spec with user-defined max_rounds
            max_rounds = self.max_rounds_spinbox.value()
            context = ""
            if getattr(self, "include_task_suggestions_checkbox", None) and self.include_task_suggestions_checkbox.isChecked():
                context = (
                    "Output contract:\n"
                    "- The markdown MUST include a section exactly titled: '## Suggested Tasks (importable)'.\n"
                    "- Under that header, include one task per line in this exact format:\n"
                    "  - [ ] <task title> | due: <MM-DD-YYYY or none> | category: <Business or Personal>\n"
                    "- Use realistic due dates; if unknown, use 'none'.\n"
                    "- Keep task titles short and action-oriented.\n"
                )
            task_spec = WorkspaceTaskSpec(
                goal=instructions.strip(),
                context=context,
                files=workspace_files,
                max_rounds=max_rounds,
                document_template=selected_template_spec.to_payload() if selected_template_spec else None,
            )

            # Save context for persistence on completion
            self._last_task_spec = task_spec
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

            # Store file contents for use in API calls
            self._current_file_contents = file_contents

            # Log file contents being passed to orchestrator
            logger.info(f"Passing {len(file_contents)} file(s) to orchestrator")
            logger.debug(f"File paths: {list(file_contents.keys())}")
            logger.debug(f"Task spec files: {[f.path for f in task_spec.files]}")

            # Update UI for API calls
            if marked_files:
                self.status_label.setText("Calling Grok API (Research Agent)...")
                self.progress_bar.setValue(30)
            else:
                self.status_label.setText("Starting AI collaboration (Research Mode)...")
                self.progress_bar.setValue(20)
            if selected_template_spec:
                self.status_label.setText(f"Generating structured draft with template: {selected_template_spec.display_name}")
            QApplication.processEvents()
            
            # Clear previous outputs
            if hasattr(self, 'grok_text'):
                self.grok_text.setPlainText("Processing...")
            if hasattr(self, 'chatgpt_text'):
                self.chatgpt_text.setPlainText("Waiting for Grok to complete...")
            if hasattr(self, 'preview_text'):
                self.preview_text.setPlainText("Generating document...")
            
            # Disable save buttons until document is ready
            if hasattr(self, 'save_button'):
                self.save_button.setEnabled(False)
            if hasattr(self, 'export_button'):
                self.export_button.setEnabled(False)

            # Create orchestrator (progress callback will be set by worker thread)
            orchestrator = DualLLMOrchestrator(
                logger=logger,
                grok_call=lambda task_spec, file_contents, feedback, round_num, previous_markdown: 
                    call_grok_api(task_spec, file_contents or self._current_file_contents, feedback, round_num, previous_markdown),
                chatgpt_call=lambda task_spec, grok_result, file_contents, round_num: 
                    call_chatgpt_api(task_spec, grok_result, file_contents or self._current_file_contents, round_num)
            )

            # Run orchestrator in background thread to prevent UI freezing
            self._collaboration_worker = CollaborationWorker(orchestrator, task_spec, file_contents)
            self._collaboration_worker.progress_signal.connect(self._on_progress_update)
            self._collaboration_worker.round_update_signal.connect(self._on_round_update)
            self._collaboration_worker.result_signal.connect(self._on_collaboration_complete)
            self._collaboration_worker.error_signal.connect(self._on_collaboration_error)
            self._collaboration_worker.start()
            
        except Exception as e:
            # Handle errors that occur before starting the worker thread
            logger.error(f"Error setting up AI collaboration workflow: {e}")
            error_msg = f"Error setting up AI collaboration workflow: {str(e)}"
            self.status_label.setText("Error during setup")
            self.progress_bar.setVisible(False)
            self.preview_text.setPlainText(error_msg)
            if hasattr(self, 'grok_text'):
                self.grok_text.setPlainText(f"Error: {str(e)}")
            if hasattr(self, 'chatgpt_text'):
                self.chatgpt_text.setPlainText("Workflow failed during setup.")

    def _on_progress_update(self, message, progress):
        """Handle progress updates from worker thread (thread-safe, called on main thread)"""
        self.status_label.setText(message)
        self.progress_bar.setValue(progress)
        QApplication.processEvents()
    
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
        
        # Update Grok pane with current round
        if hasattr(self, 'grok_text'):
            current_text = self.grok_text.toPlainText()
            if "Round" in current_text or current_text.strip() == "Processing...":
                # Append to existing or replace "Processing..."
                if current_text.strip() == "Processing...":
                    self.grok_text.setPlainText(f"--- Round {round_num} ---\n{grok_output}")
                else:
                    self.grok_text.append(f"\n\n--- Round {round_num} ---\n{grok_output}")
            else:
                # First round
                self.grok_text.setPlainText(f"--- Round {round_num} ---\n{grok_output}")
        
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
        self.status_label.setText(status_text)
        self.progress_bar.setValue(100)
        QApplication.processEvents()
        self.progress_bar.setVisible(False)

    def extract_suggested_tasks(self):
        """
        Parse the current markdown for a '## Suggested Tasks (importable)' section,
        then open a review dialog that lets the user accept/decline/edit before insertion.
        """
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
                self.db.add_task(
                    "workspace_import",
                    t.title,
                    t.due_mmddyyyy,
                    category=t.category,
                )
                created += 1
            except Exception:
                failed += 1

        if failed:
            QMessageBox.warning(
                self,
                "Suggested Tasks",
                f"Imported {created} task(s), but {failed} failed to insert.\n\n"
                "Open the Tasks tab to confirm what was created.",
            )
        else:
            QMessageBox.information(
                self,
                "Suggested Tasks",
                f"Imported {created} task(s).\n\nOpen the Tasks tab (or Dashboard) to view them.",
            )
        self.status_label.setText(f"Imported {created} task(s){' (some failed)' if failed else ''}")
    
    def _on_collaboration_error(self, error_msg):
        """Handle errors from collaboration workflow"""
        QTimer.singleShot(0, lambda: self._on_collaboration_error_safe(error_msg))
    
    def _on_collaboration_error_safe(self, error_msg):
        """Thread-safe error handler"""
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
    
    def save_markdown(self):
        """Save the current markdown document to a file"""
        if not self._current_markdown:
            self.status_label.setText("No document to save")
            return
        
        default_filename = f"workspace_document_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
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
        
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Document",
            f"workspace_document_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
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
                self.status_label.setText(f"Document exported to {os.path.basename(exported_path)}")
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


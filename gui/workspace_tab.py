from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                            QListWidget, QListWidgetItem, QTextEdit, QSplitter, 
                            QFileDialog, QProgressBar, QMenu, QCheckBox, QInputDialog, QApplication, QSpinBox, QGroupBox)
from PyQt6.QtCore import Qt, QMimeData, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QDropEvent, QDragEnterEvent, QPainter, QColor
from core.api import DropboxClient
from dropbox import files
# from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
import json
import os
from datetime import datetime
import logging

# ADD THIS IMPORT (just below the Dropbox imports)
from core.workspace_orchestrator import WorkspaceFile, WorkspaceTaskSpec, DualLLMOrchestrator, call_grok_api, call_chatgpt_api
from core.file_handler import extract_text_from_file
from gui.agent_console import AgentConsole

logger = logging.getLogger(__name__)

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
        self.dropbox_client = DropboxClient()
        self.selected_files = []
        
        # NEW: dual-LLM orchestrator that will talk to Grok + ChatGPT
        # Initialize with real API call functions
        self._current_file_contents = {}  # Store file contents for API calls
        self._collaboration_worker = None  # Worker thread for running collaboration
        self._current_markdown = ""  # Store current markdown for saving
        # For persistence of the last run
        self._last_task_spec = None
        self._last_workspace_files = []
        
        self.setup_ui()

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
        self.quill_console = AgentConsole(self.db, agent_code="quill", parent=self)
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
        
        # Select and Actions buttons
        btn_layout = QHBoxLayout()
        select_btn = QPushButton("Select File/Folder")
        select_btn.setStyleSheet("background-color: #FD6262; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 500;")
        select_btn.setMinimumHeight(38)
        select_btn.setMinimumWidth(170)
        select_btn.clicked.connect(self.select_files)
        btn_layout.addWidget(select_btn)
        
        actions_btn = QPushButton("Actions")
        actions_btn.setStyleSheet("background-color: #FD6262; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 500;")
        actions_btn.setMinimumHeight(38)
        actions_btn.setMinimumWidth(120)
        self.actions_menu = QMenu()
        
        # existing actions:
        self.actions_menu.addAction("Generate Document", self.generate_document)
        self.actions_menu.addAction("Compliance Analysis", self.run_compliance_analysis)
        self.actions_menu.addAction("Summarize", self.summarize_files)
        self.actions_menu.addAction("Save Results", self.save_results)
        
        # NEW: AI collab action that calls the dual-LLM orchestrator
        self.actions_menu.addAction("AI Collaboration Draft", self.run_ai_collaboration_workflow)
        
        actions_btn.setMenu(self.actions_menu)
        btn_layout.addWidget(actions_btn)
        file_layout.addLayout(btn_layout)
        
        self.file_list = QListWidget()
        self.file_list.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; border-radius: 6px;")
        self.file_list.setMinimumHeight(300)
        self.file_list.setSpacing(6)
        self.file_list.setToolTip("Drag and drop files here or mark RAG results")
        self.file_list.itemClicked.connect(self.on_file_selected)
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
        button_bar.addStretch()
        markdown_layout.addLayout(button_bar)

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
                    
                file_info = {
                    'name': os.path.basename(path),
                    'path': path,
                    'is_folder': os.path.isdir(path),
                    'size': os.path.getsize(path) if os.path.isfile(path) else 0,
                    'modified': datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S"),
                    'marked': False
                }
                self.add_file_to_list(file_info)
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
                for path in dialog.selectedFiles():
                    file_info = {
                        'name': os.path.basename(path),
                        'path': path,
                        'is_folder': os.path.isdir(path),
                        'size': os.path.getsize(path) if os.path.isfile(path) else 0,
                        'modified': datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S"),
                        'marked': False
                    }
                    self.add_file_to_list(file_info)
                self.status_label.setText(f"Added {len(dialog.selectedFiles())} files")
        except Exception as e:
            self.status_label.setText(f"Error selecting files: {str(e)}")

    def add_file_to_list(self, file_info):
        if not file_info['is_folder']:
            icon = "📄"
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

    def toggle_mark(self, file_info, state):
        file_info['marked'] = state == Qt.CheckState.Checked.value

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
            marked_files = [f for f in self.selected_files if f.get("marked")]
            
            # Ask the user what they want Grok + ChatGPT to do
            if marked_files:
                prompt_text = f"Describe what you want Grok + ChatGPT to do with these {len(marked_files)} file(s):"
            else:
                prompt_text = "Describe what you want Grok + ChatGPT to research and create (no files uploaded):"
            
            instructions, ok = QInputDialog.getText(
                self,
                "AI Collaboration Instructions",
                prompt_text
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
                    file_path = os.path.abspath(f["path"])
                    
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
            else:
                # No files - just research request
                self.status_label.setText("Starting research collaboration...")
                self.progress_bar.setVisible(True)
                self.progress_bar.setValue(10)
                QApplication.processEvents()

            # Build the task spec with user-defined max_rounds
            max_rounds = self.max_rounds_spinbox.value()
            task_spec = WorkspaceTaskSpec(
                goal=instructions.strip(),
                context="",  # Could be extended to ask for context
                files=workspace_files,
                max_rounds=max_rounds,
            )

            # Save context for persistence on completion
            self._last_task_spec = task_spec
            self._last_workspace_files = [
                {"path": wf.path, "display_name": wf.display_name, "file_type": wf.file_type}
                for wf in workspace_files
            ]

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
                    self.chatgpt_text.setPlainText(f"--- Round {round_num} ---\n{chatgpt_output}{feedback_text}")
                else:
                    self.chatgpt_text.append(f"\n\n--- Round {round_num} ---\n{chatgpt_output}")
                    if feedback:
                        self.chatgpt_text.append(f"\n[Feedback to Grok]: {feedback}")
            else:
                # First round
                feedback_text = f"\n[Feedback to Grok]: {feedback}" if feedback else ""
                self.chatgpt_text.setPlainText(f"--- Round {round_num} ---\n{chatgpt_output}{feedback_text}")
        
        # Update markdown preview with current version
        if markdown and hasattr(self, 'preview_text'):
            self.preview_text.setPlainText(markdown)
            self._current_markdown = markdown
        
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
        self._current_markdown = markdown_doc

        # Show the final Markdown in the preview pane
        if markdown_doc:
            self.preview_text.setPlainText(markdown_doc)
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

        self.status_label.setText(f"AI collaboration complete ({status}, {rounds} round{'s' if rounds != 1 else ''})")
        self.progress_bar.setValue(100)
        QApplication.processEvents()
        self.progress_bar.setVisible(False)
    
    def _on_collaboration_error(self, error_msg):
        """Handle errors from collaboration workflow"""
        QTimer.singleShot(0, lambda: self._on_collaboration_error_safe(error_msg))
    
    def _on_collaboration_error_safe(self, error_msg):
        """Thread-safe error handler"""
        logger.error(f"Error in AI collaboration workflow: {error_msg}")
        self.status_label.setText("Error during workflow")
        self.progress_bar.setVisible(False)
        self.preview_text.setPlainText(f"Error running AI collaboration workflow: {error_msg}")
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
            "Markdown Files (*.md);;Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self._current_markdown)
                self.status_label.setText(f"Document exported to {os.path.basename(file_path)}")
            except Exception as e:
                logger.error(f"Error exporting markdown: {e}")
                self.status_label.setText(f"Error exporting file: {str(e)}")

    def generate_document(self):
        marked_files = [f for f in self.selected_files if f['marked']]
        if not marked_files:
            self.status_label.setText("No files marked")
            # Show empty state in preview
            self.preview_text.setHtml('<div style="text-align: center; color: #9aa0a6; font-style: italic; padding: 40px;"><h3 style="color: #e8eaed;">No files selected</h3><p>Mark some files in the list to generate a document.</p></div>')
            return
        try:
            self.status_label.setText("Generating document...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            
            content = ""
            for file_info in marked_files:
                # Use cached content to avoid repeated disk I/O
                content += self.get_file_content(file_info) + "\n\n"
            
            # Placeholder RunPod API call
            response = {"document": "Placeholder: RunPod API call for document generation not implemented yet"}
            self.preview_text.setHtml(response['document'].replace('\n', '<br>'))
            self.status_label.setText("Document generated")
            self.progress_bar.setVisible(False)
        except Exception as e:
            self.preview_text.setPlainText(f"Error generating document: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")
            self.progress_bar.setVisible(False)

    def run_compliance_analysis(self):
        marked_files = [f for f in self.selected_files if f['marked']]
        if not marked_files:
            self.status_label.setText("No files marked")
            # Show empty state in preview
            self.preview_text.setHtml('<div style="text-align: center; color: #9aa0a6; font-style: italic; padding: 40px;"><h3 style="color: #e8eaed;">No files selected</h3><p>Mark some files in the list to run compliance analysis.</p></div>')
            return
        try:
            self.status_label.setText("Running compliance analysis...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            
            content = ""
            for file_info in marked_files:
                # Use cached content to avoid repeated disk I/O
                content += self.get_file_content(file_info) + "\n\n"
            
            # Placeholder RunPod API call
            response = {"compliance_report": "Placeholder: RunPod API call for compliance analysis not implemented yet"}
            self.preview_text.setHtml(response['compliance_report'].replace('\n', '<br>'))
            self.status_label.setText("Compliance analysis complete")
            self.progress_bar.setVisible(False)
        except Exception as e:
            self.preview_text.setPlainText(f"Error running compliance analysis: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")
            self.progress_bar.setVisible(False)

    def summarize_files(self):
        marked_files = [f for f in self.selected_files if f['marked']]
        if not marked_files:
            self.status_label.setText("No files marked")
            # Show empty state in preview
            self.preview_text.setHtml('<div style="text-align: center; color: #9aa0a6; font-style: italic; padding: 40px;"><h3 style="color: #e8eaed;">No files selected</h3><p>Mark some files in the list to generate a summary.</p></div>')
            return
        try:
            self.status_label.setText("Summarizing files...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            
            content = ""
            for file_info in marked_files:
                # Use cached content to avoid repeated disk I/O
                content += self.get_file_content(file_info) + "\n\n"
            
            # Placeholder RunPod API call
            response = {"summary": "Placeholder: RunPod API call for file summarization not implemented yet"}
            self.preview_text.setHtml(response['summary'].replace('\n', '<br>'))
            self.status_label.setText("Files summarized")
            self.progress_bar.setVisible(False)
        except Exception as e:
            self.preview_text.setPlainText(f"Error summarizing files: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")
            self.progress_bar.setVisible(False)

    def save_results(self):
        try:
            results = self.preview_text.toPlainText()
            if not results or results.startswith("Error"):
                self.status_label.setText("No results to save")
                return
            
            save_path, _ = QFileDialog.getSaveFileName(
                self, "Save Results", "results.txt", "Text Files (*.txt);;Word Documents (*.docx);;PDF Files (*.pdf)"
            )
            if save_path:
                dbx = self.dropbox_client.get_client()
                if save_path.endswith('.txt'):
                    with open(save_path, 'w', encoding='utf-8') as f:
                        f.write(results)
                elif save_path.endswith('.docx'):
                    from docx import Document
                    doc = Document()
                    doc.add_paragraph(results)
                    doc.save(save_path)
                elif save_path.endswith('.pdf'):
                    from fpdf import FPDF
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Arial", size=12)
                    pdf.multi_cell(0, 10, results)
                    pdf.output(save_path)
                self.status_label.setText(f"Results saved to {save_path}")
        except Exception as e:
            self.status_label.setText(f"Error saving results: {str(e)}")

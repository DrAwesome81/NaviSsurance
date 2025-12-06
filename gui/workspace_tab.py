from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                            QListWidget, QListWidgetItem, QTextEdit, QSplitter, 
                            QFileDialog, QProgressBar, QMenu, QCheckBox)
from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QDropEvent, QDragEnterEvent, QPainter, QColor
from core.api import DropboxClient
from dropbox import files
# from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
import json
import os
from datetime import datetime

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
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Main splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(main_splitter)
        
        # Left: File Selection Area
        self.setup_file_selection(main_splitter)
        
        # Right: Preview/Results Pane
        self.setup_preview_pane(main_splitter)
        
        # Use stretch factors for responsive proportions (20% files, 80% preview)
        main_splitter.setStretchFactor(0, 1)  # Files panel gets 1/5 of space
        main_splitter.setStretchFactor(1, 4)  # Preview panel gets 4/5 of space
        
        self.setLayout(layout)

    def setup_file_selection(self, parent_splitter):
        file_widget = QWidget()
        file_widget.setAcceptDrops(True)
        file_layout = QVBoxLayout(file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)
        
        file_header = QLabel("Files")
        file_header.setStyleSheet("color: white; font-weight: bold; padding: 8px; background-color: rgba(253, 98, 98, 0.8); border-radius: 3px;")
        file_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        file_layout.addWidget(file_header)
        
        # Status and progress
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: white; padding: 5px;")
        status_layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        status_layout.addWidget(self.progress_bar)
        status_layout.addStretch()
        file_layout.addLayout(status_layout)
        
        # Select and Actions buttons
        btn_layout = QHBoxLayout()
        select_btn = QPushButton("Select File/Folder")
        select_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 8px; border-radius: 3px;")
        select_btn.clicked.connect(self.select_files)
        btn_layout.addWidget(select_btn)
        
        actions_btn = QPushButton("Actions")
        actions_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 8px; border-radius: 3px;")
        self.actions_menu = QMenu()
        self.actions_menu.addAction("Generate Document", self.generate_document)
        self.actions_menu.addAction("Compliance Analysis", self.run_compliance_analysis)
        self.actions_menu.addAction("Summarize", self.summarize_files)
        self.actions_menu.addAction("Save Results", self.save_results)
        actions_btn.setMenu(self.actions_menu)
        btn_layout.addWidget(actions_btn)
        file_layout.addLayout(btn_layout)
        
        self.file_list = QListWidget()
        self.file_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px;")
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
            "color: white; font-weight: bold; padding: 6px; "
            "background-color: rgba(253, 98, 98, 0.6); border-radius: 3px;"
        )
        grok_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ai_layout.addWidget(grok_header)

        self.grok_text = AlwaysVisiblePlaceholderTextEdit()
        self.grok_text.setReadOnly(True)
        self.grok_text.setStyleSheet(
            "background-color: rgba(27, 28, 30, 0.8); "
            "color: white; border: 1px solid rgba(253, 98, 98, 0.3); "
            "border-radius: 3px;"
        )
        self.grok_text.setPlaceholderText("Grok responses will appear here.")
        ai_layout.addWidget(self.grok_text)

        # ChatGPT pane
        chatgpt_header = QLabel("ChatGPT (API)")
        chatgpt_header.setStyleSheet(
            "color: white; font-weight: bold; padding: 6px; "
            "background-color: rgba(253, 98, 98, 0.6); border-radius: 3px;"
        )
        chatgpt_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ai_layout.addWidget(chatgpt_header)

        self.chatgpt_text = AlwaysVisiblePlaceholderTextEdit()
        self.chatgpt_text.setReadOnly(True)
        self.chatgpt_text.setStyleSheet(
            "background-color: rgba(27, 28, 30, 0.8); "
            "color: white; border: 1px solid rgba(253, 98, 98, 0.3); "
            "border-radius: 3px;"
        )
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
            "color: white; font-weight: bold; padding: 6px; "
            "background-color: rgba(253, 98, 98, 0.6); border-radius: 3px;"
        )
        markdown_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        markdown_layout.addWidget(markdown_header)

        # IMPORTANT: reuse self.preview_text so existing methods still work
        self.preview_text = AlwaysVisiblePlaceholderTextEdit()
        # Let you edit the Markdown directly if desired
        self.preview_text.setReadOnly(False)
        self.preview_text.setStyleSheet(
            "background-color: rgba(27, 28, 30, 0.8); "
            "color: white; border: 1px solid rgba(253, 98, 98, 0.3); "
            "border-radius: 3px;"
        )
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
            checkbox = QCheckBox()
            checkbox.setChecked(file_info['marked'])
            checkbox.stateChanged.connect(lambda state: self.toggle_mark(file_info, state))
            layout.addWidget(checkbox)
            label = QLabel(f"{icon} {item_text}")
            label.setToolTip(file_info['name'])
            layout.addWidget(label)
            layout.addStretch()
            item.setSizeHint(widget.sizeHint())
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
            file_ext = os.path.splitext(file_info['name'])[1].lower()
            content = ""
            
            if file_ext in {'.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml', '.csv'}:
                with open(file_info['path'], 'r', encoding='utf-8') as f:
                    content = f.read()
            elif file_ext in {'.pdf'}:
                # loader = PyPDFLoader(file_info['path'])
                # pages = loader.load()
                # content = "\n\n".join(page.page_content for page in pages[:5])
                content = f"[PDF file: {file_info['name']} - content loading disabled]"
            elif file_ext in {'.docx'}:
                # loader = Docx2txtLoader(file_info['path'])
                # content = loader.load()[0].page_content
                content = f"[DOCX file: {file_info['name']} - content loading disabled]"
            
            # Cache the content for future use
            file_info['content'] = content
        
        return file_info['content']

    def generate_document(self):
        marked_files = [f for f in self.selected_files if f['marked']]
        if not marked_files:
            self.status_label.setText("No files marked")
            # Show empty state in preview
            self.preview_text.setHtml('<div style="text-align: center; color: #888; font-style: italic; padding: 40px;"><h3>No files selected</h3><p>Mark some files in the list to generate a document.</p></div>')
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
            self.preview_text.setHtml('<div style="text-align: center; color: #888; font-style: italic; padding: 40px;"><h3>No files selected</h3><p>Mark some files in the list to run compliance analysis.</p></div>')
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
            self.preview_text.setHtml('<div style="text-align: center; color: #888; font-style: italic; padding: 40px;"><h3>No files selected</h3><p>Mark some files in the list to generate a summary.</p></div>')
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

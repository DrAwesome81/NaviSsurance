import sqlite3
import logging
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QSplashScreen, 
                                            QTextBrowser, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QDateEdit, QTableWidget, 
                            QTableWidgetItem, QCheckBox, QComboBox, QLabel, QSplitter, QTextEdit, QDialog, QDialogButtonBox, QHeaderView, QMessageBox, QFileDialog, QMenu, QProgressBar)
from PyQt6.QtCore import Qt, QDate, QTimer, pyqtSlot, QUrl, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction, QDesktopServices, QColor
from core.db import DatabaseManager
from gui.chat_window import ChatThread, ResponseHandler, sendMessage, saveChat, loadChat
from gui.todo_list import TodoList
from core.chat import ChatManager
import os
import json
import requests
import re
from datetime import datetime, timedelta
from PyQt6.QtWidgets import QApplication
import PyPDF2
from bs4 import BeautifulSoup
import requests
import markdown
from core.compliance import ComplianceChecker, DocumentGenerator
from core.api import DropboxClient
from docx import Document
from fpdf import FPDF
from dropbox import files

logger = logging.getLogger(__name__)

class EnhancedSplashScreen(QSplashScreen):
    """Enhanced splash screen with progress bar and status updates."""
    
    def __init__(self, pixmap):
        super().__init__(pixmap)
        self.setStyleSheet("""
            QSplashScreen {
                background-color: rgb(27, 28, 30);
                color: white;
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
                border: 2px solid rgba(253, 98, 98, 0.8);
                border-radius: 5px;
                text-align: center;
                background-color: rgba(27, 28, 30, 0.8);
                color: white;
            }
            QProgressBar::chunk {
                background-color: rgba(253, 98, 98, 0.8);
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
                color: white;
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
                background-color: rgba(27, 28, 30, 0.9);
                color: white;
                border: 1px solid rgba(253, 98, 98, 0.5);
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
        layout = QVBoxLayout()
        
        # Style for the dialog
        # self.setStyleSheet("""
        #     QDialog {
        #         background-color: rgb(27, 28, 30);
        #         color: white;
        #     }
        #     QTextEdit {
        #         background-color: rgba(27, 28, 30, 0.8);
        #         color: white;
        #         border: 1px solid rgba(253, 98, 98, 0.8);
        #     }
        #     QLabel {
        #         color: white;
        #     }
        # """)
        
        self.system_message_input = QTextEdit(self)
        
        # Load existing system message from config
        config_path = 'C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/config/lead_gen_config.json'
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                self.system_message_input.setText(config.get('system_message', ''))
            except Exception as e:
                logger.error(f"Error loading system message: {e}")
                self.system_message_input.setText("")  # Default empty if load fails
        
        layout.addWidget(QLabel("Grok System Message:"))
        layout.addWidget(self.system_message_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        # buttons.setStyleSheet("""
        #     QPushButton {
        #         background-color: rgba(253, 98, 98, 0.8);
        #         color: white;
        #         border: none;
        #         padding: 5px 15px;
        #     }
        #     QPushButton:hover {
        #         background-color: rgba(253, 98, 98, 1);
        #     }
        # """)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)

class WorkspaceTab(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.dropbox_client = DropboxClient()
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Create main splitter for the workspace
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(main_splitter)
        
        # Left: Folder Tree View (Dropbox/Google Drive files)
        self.setup_folder_tree(main_splitter)
        
        # Center: Document Preview Pane
        self.setup_preview_pane(main_splitter)
        
        # Right: Generation/Compliance Tools Sidebar
        self.setup_tools_sidebar(main_splitter)
        
        # Set splitter proportions (30% left, 50% center, 20% right)
        main_splitter.setSizes([576, 960, 384])  # 1920 * 0.3, 0.5, 0.2
        
        # Add status bar at bottom
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: white; padding: 5px;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        
        # Add refresh button
        refresh_btn = QPushButton("Refresh Files")
        refresh_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 5px 10px; border-radius: 3px;")
        refresh_btn.clicked.connect(self.refresh_files)
        status_layout.addWidget(refresh_btn)
        
        layout.addLayout(status_layout)
        
        # Load initial files after UI is fully set up
        self.load_dropbox_files()
    
    def setup_folder_tree(self, parent_splitter):
        """Setup the left folder tree view for Dropbox files."""
        tree_widget = QWidget()
        tree_layout = QVBoxLayout(tree_widget)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        tree_header = QLabel("File Explorer")
        tree_header.setStyleSheet("color: white; font-weight: bold; padding: 8px; background-color: rgba(253, 98, 98, 0.8); border-radius: 3px;")
        tree_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tree_layout.addWidget(tree_header)
        
        # Search box
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search files...")
        self.search_box.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.5); padding: 5px; border-radius: 3px;")
        self.search_box.textChanged.connect(self.filter_files)
        tree_layout.addWidget(self.search_box)
        
        # File tree
        self.file_tree = QListWidget()
        self.file_tree.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px;")
        self.file_tree.itemClicked.connect(self.on_file_selected)
        tree_layout.addWidget(self.file_tree)
        
        parent_splitter.addWidget(tree_widget)
    
    def setup_preview_pane(self, parent_splitter):
        """Setup the center document preview pane."""
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        preview_header = QLabel("Document Preview")
        preview_header.setStyleSheet("color: white; font-weight: bold; padding: 8px; background-color: rgba(253, 98, 98, 0.8); border-radius: 3px;")
        preview_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(preview_header)
        
        # Preview area
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px;")
        self.preview_text.setPlaceholderText("Select a file from the left panel to preview its contents...")
        preview_layout.addWidget(self.preview_text)
        
        # Document info
        info_layout = QHBoxLayout()
        self.file_info_label = QLabel("No file selected")
        self.file_info_label.setStyleSheet("color: white; padding: 5px;")
        info_layout.addWidget(self.file_info_label)
        info_layout.addStretch()
        
        # Download button
        self.download_btn = QPushButton("Download")
        self.download_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 5px 10px; border-radius: 3px;")
        self.download_btn.clicked.connect(self.download_file)
        self.download_btn.setEnabled(False)
        info_layout.addWidget(self.download_btn)
        
        preview_layout.addLayout(info_layout)
        
        parent_splitter.addWidget(preview_widget)
    
    def setup_tools_sidebar(self, parent_splitter):
        """Setup the right sidebar with generation and compliance tools."""
        tools_widget = QWidget()
        tools_layout = QVBoxLayout(tools_widget)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        tools_header = QLabel("Tools & Analysis")
        tools_header.setStyleSheet("color: white; font-weight: bold; padding: 8px; background-color: rgba(253, 98, 98, 0.8); border-radius: 3px;")
        tools_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tools_layout.addWidget(tools_header)
        
        # Document Analysis Section
        analysis_group = QLabel("Document Analysis")
        analysis_group.setStyleSheet("color: white; font-weight: bold; margin-top: 10px;")
        tools_layout.addWidget(analysis_group)
        
        # Analysis buttons
        self.analyze_btn = QPushButton("Analyze Document")
        self.analyze_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 8px; border-radius: 3px; margin: 2px;")
        self.analyze_btn.clicked.connect(self.analyze_document)
        self.analyze_btn.setEnabled(False)
        tools_layout.addWidget(self.analyze_btn)
        
        self.chunk_btn = QPushButton("Generate Chunks")
        self.chunk_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 8px; border-radius: 3px; margin: 2px;")
        self.chunk_btn.clicked.connect(self.generate_chunks)
        self.chunk_btn.setEnabled(False)
        tools_layout.addWidget(self.chunk_btn)
        
        # Compliance Section
        compliance_group = QLabel("Compliance Tools")
        compliance_group.setStyleSheet("color: white; font-weight: bold; margin-top: 15px;")
        tools_layout.addWidget(compliance_group)
        
        self.compliance_btn = QPushButton("Run Compliance Check")
        self.compliance_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 8px; border-radius: 3px; margin: 2px;")
        self.compliance_btn.clicked.connect(self.run_compliance_check)
        self.compliance_btn.setEnabled(False)
        tools_layout.addWidget(self.compliance_btn)
        
        # Results display
        results_label = QLabel("Results:")
        results_label.setStyleSheet("color: white; font-weight: bold; margin-top: 15px;")
        tools_layout.addWidget(results_label)
        
        self.results_display = QTextEdit()
        self.results_display.setReadOnly(True)
        self.results_display.setMaximumHeight(200)
        self.results_display.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px;")
        self.results_display.setPlaceholderText("Analysis results will appear here...")
        tools_layout.addWidget(self.results_display)
        
        # Add stretch to push everything to the top
        tools_layout.addStretch()
        
        parent_splitter.addWidget(tools_widget)
    
    def load_dropbox_files(self):
        """Load files from Dropbox into the tree view."""
        try:
            if hasattr(self, 'status_label'):
                self.status_label.setText("Loading files from Dropbox...")
            dbx = self.dropbox_client.get_client()
            
            # Get files from root directory
            result = dbx.files_list_folder("", recursive=False)
            files = []
            
            for entry in result.entries:
                if hasattr(entry, 'path_display'):
                    files.append({
                        'name': entry.name,
                        'path': entry.path_display,
                        'is_folder': isinstance(entry, files.FolderMetadata),
                        'size': getattr(entry, 'size', 0),
                        'modified': getattr(entry, 'server_modified', None)
                    })
            
            # Sort: folders first, then files
            files.sort(key=lambda x: (not x['is_folder'], x['name'].lower()))
            
            self.file_tree.clear()
            for file_info in files:
                icon = "ðŸ“" if file_info['is_folder'] else "ðŸ“„"
                item_text = f"{icon} {file_info['name']}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, file_info)
                self.file_tree.addItem(item)
            
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"Loaded {len(files)} items")
            
        except Exception as e:
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"Error loading files: {str(e)}")
            self.file_tree.addItem("Error loading files from Dropbox")
    
    def filter_files(self, search_text):
        """Filter files based on search text."""
        for i in range(self.file_tree.count()):
            item = self.file_tree.item(i)
            file_info = item.data(Qt.ItemDataRole.UserRole)
            if file_info and search_text.lower() in file_info['name'].lower():
                item.setHidden(False)
            else:
                item.setHidden(True)
    
    def on_file_selected(self, item):
        """Handle file selection in the tree."""
        file_info = item.data(Qt.ItemDataRole.UserRole)
        if not file_info:
            return
        
        self.selected_file = file_info
        self.file_info_label.setText(f"Selected: {file_info['name']}")
        
        # Enable relevant buttons
        self.analyze_btn.setEnabled(True)
        self.chunk_btn.setEnabled(True)
        self.compliance_btn.setEnabled(True)
        self.download_btn.setEnabled(True)
        
        # Load file preview if it's a text-based file
        if not file_info['is_folder']:
            self.load_file_preview(file_info)
    
    def load_file_preview(self, file_info):
        """Load and display file preview."""
        try:
            if hasattr(self, 'status_label'):
                self.status_label.setText("Loading file preview...")
            
            # Check if it's a text-based file
            text_extensions = {'.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml', '.csv'}
            file_ext = os.path.splitext(file_info['name'])[1].lower()
            
            if file_ext in text_extensions:
                # Download and read text content
                dbx = self.dropbox_client.get_client()
                temp_path = f"temp_{file_info['name']}"
                
                with open(temp_path, 'wb') as f:
                    metadata, response = dbx.files_download(file_info['path'])
                    f.write(response.content)
                
                with open(temp_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Clean up temp file
                os.remove(temp_path)
                
                # Display content (limit to first 1000 characters)
                preview_content = content[:1000]
                if len(content) > 1000:
                    preview_content += f"\n\n... (showing first 1000 characters of {len(content)} total)"
                
                self.preview_text.setPlainText(preview_content)
                if hasattr(self, 'status_label'):
                    self.status_label.setText("File preview loaded")
            else:
                self.preview_text.setPlainText(f"Preview not available for {file_ext} files.\nFile size: {file_info['size']} bytes")
                if hasattr(self, 'status_label'):
                    self.status_label.setText("Preview not available for this file type")
                
        except Exception as e:
            self.preview_text.setPlainText(f"Error loading file preview: {str(e)}")
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"Error: {str(e)}")
    
    def analyze_document(self):
        """Analyze the selected document."""
        if not hasattr(self, 'selected_file'):
            return
        
        try:
            if hasattr(self, 'status_label'):
                self.status_label.setText("Analyzing document...")
            self.results_display.setPlainText("Analysis in progress...")
            
            # Simple analysis - count words, lines, etc.
            content = self.preview_text.toPlainText()
            if content and not content.startswith("Preview not available"):
                word_count = len(content.split())
                line_count = len(content.split('\n'))
                char_count = len(content)
                
                analysis_result = f"""Document Analysis Results:
                
File: {self.selected_file['name']}
Size: {self.selected_file['size']} bytes
Characters: {char_count}
Words: {word_count}
Lines: {line_count}
Average words per line: {word_count/line_count:.1f if line_count > 0 else 0}

Content Summary:
{content[:200]}..."""
                
                self.results_display.setPlainText(analysis_result)
                if hasattr(self, 'status_label'):
                    self.status_label.setText("Analysis complete")
            else:
                self.results_display.setPlainText("Cannot analyze: No text content available")
                
        except Exception as e:
            self.results_display.setPlainText(f"Analysis error: {str(e)}")
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"Error: {str(e)}")
    
    def generate_chunks(self):
        """Generate text chunks from the document."""
        if not hasattr(self, 'selected_file'):
            return
        
        try:
            if hasattr(self, 'status_label'):
                self.status_label.setText("Generating chunks...")
            content = self.preview_text.toPlainText()
            
            if content and not content.startswith("Preview not available"):
                # Simple chunking by paragraphs
                paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
                chunks = []
                
                for i, para in enumerate(paragraphs[:10]):  # Limit to 10 chunks
                    if len(para) > 50:  # Only chunks with substantial content
                        chunks.append(f"Chunk {i+1}: {para[:100]}...")
                
                chunk_result = f"Generated {len(chunks)} chunks from {self.selected_file['name']}:\n\n"
                chunk_result += "\n\n".join(chunks)
                
                self.results_display.setPlainText(chunk_result)
                if hasattr(self, 'status_label'):
                    self.status_label.setText("Chunks generated")
            else:
                self.results_display.setPlainText("Cannot generate chunks: No text content available")
                
        except Exception as e:
            self.results_display.setPlainText(f"Chunking error: {str(e)}")
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"Error: {str(e)}")
    
    def run_compliance_check(self):
        """Run a basic compliance check on the document."""
        if not hasattr(self, 'selected_file'):
            return
        
        try:
            if hasattr(self, 'status_label'):
                self.status_label.setText("Running compliance check...")
            content = self.preview_text.toPlainText().lower()
            
            if content and not content.startswith("Preview not available"):
                # Simple keyword-based compliance check
                compliance_keywords = {
                    'fda': ['fda', 'food and drug administration', '21 cfr', '510k', 'pma'],
                    'iso': ['iso 13485', 'iso 14971', 'iso 27001'],
                    'gdpr': ['gdpr', 'general data protection regulation', 'personal data'],
                    'hipaa': ['hipaa', 'health insurance portability', 'privacy rule'],
                    'security': ['encryption', 'authentication', 'access control', 'audit trail']
                }
                
                results = []
                for category, keywords in compliance_keywords.items():
                    found_keywords = [kw for kw in keywords if kw in content]
                    if found_keywords:
                        results.append(f"âœ… {category.upper()}: Found {len(found_keywords)} relevant terms")
                    else:
                        results.append(f"âŒ {category.upper()}: No relevant terms found")
                
                compliance_result = f"Compliance Check Results for {self.selected_file['name']}:\n\n"
                compliance_result += "\n".join(results)
                compliance_result += "\n\nNote: This is a basic keyword-based check. For comprehensive compliance analysis, use the Compliance tab."
                
                self.results_display.setPlainText(compliance_result)
                if hasattr(self, 'status_label'):
                    self.status_label.setText("Compliance check complete")
            else:
                self.results_display.setPlainText("Cannot run compliance check: No text content available")
                
        except Exception as e:
            self.results_display.setPlainText(f"Compliance check error: {str(e)}")
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"Error: {str(e)}")
    
    def download_file(self):
        """Download the selected file."""
        if not hasattr(self, 'selected_file'):
            return
        
        try:
            from PyQt6.QtWidgets import QFileDialog
            
            # Get save location from user
            file_name = self.selected_file['name']
            save_path, _ = QFileDialog.getSaveFileName(
                self, "Save File As", file_name, "All Files (*.*)"
            )
            
            if save_path:
                if hasattr(self, 'status_label'):
                    self.status_label.setText("Downloading file...")
                
                # Download from Dropbox
                dbx = self.dropbox_client.get_client()
                with open(save_path, 'wb') as f:
                    metadata, response = dbx.files_download(self.selected_file['path'])
                    f.write(response.content)
                
                if hasattr(self, 'status_label'):
                    self.status_label.setText(f"File downloaded to {save_path}")
                self.results_display.setPlainText(f"File successfully downloaded to:\n{save_path}")
                
        except Exception as e:
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"Download error: {str(e)}")
            self.results_display.setPlainText(f"Download failed: {str(e)}")
    
    def refresh_files(self):
        """Refresh the file list from Dropbox."""
        self.load_dropbox_files()

class NoteTakingSystem(QWidget):
    def __init__(self, chat_handler):
        super().__init__()
        self.chat_handler = chat_handler
        self.db = DatabaseManager()
        self.db.init_notes_table()
        self.dropbox_client = DropboxClient()
        self.notes = []  # Temporary in-memory storage for notes
        self.organized = False
        self.context = None  # Add context attribute
        self.setup_ui()

    def setup_ui(self):
        layout = QHBoxLayout(self)
        
        # Left: Chat Window
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        
        # Add context input field
        context_label = QLabel("Context (what you're working on):")
        context_label.setStyleSheet("color: white; font-weight: bold;")
        chat_layout.addWidget(context_label)
        
        self.context_input = QLineEdit()
        self.context_input.setPlaceholderText("Enter context (e.g., 'Working on FDA protocol review')")
        self.context_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.5); padding: 5px;")
        self.context_input.returnPressed.connect(self.update_context)
        chat_layout.addWidget(self.context_input)
        
        # Create a custom QTextEdit subclass for proper key event handling
        class CustomTextEdit(QTextEdit):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.parent_widget = parent
            
            def keyPressEvent(self, event):
                from PyQt6.QtCore import Qt
                from PyQt6.QtGui import QKeyEvent
                
                if event.key() == Qt.Key.Key_Return and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    # Enter key pressed (without Shift)
                    if hasattr(self.parent_widget, 'process_note'):
                        self.parent_widget.process_note()
                        self.clear()
                    event.accept()
                else:
                    # Let the default QTextEdit handle other keys
                    super().keyPressEvent(event)
        
        self.chat_input = CustomTextEdit(self)
        self.chat_input.setPlaceholderText("Enter thoughts (e.g., 'Section 5 should be in the protocol; not this report')")
        chat_layout.addWidget(self.chat_input)
        layout.addWidget(chat_widget, stretch=1)

        # Right: Notes Pane
        notes_widget = QWidget()
        notes_layout = QVBoxLayout(notes_widget)
        self.notes_display = QTextEdit()
        self.notes_display.setReadOnly(True)
        self.notes_display.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        notes_layout.addWidget(self.notes_display)
        
        # Buttons
        export_btn = QPushButton("Export Notes")
        export_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        export_btn.clicked.connect(self.export_notes)
        notes_layout.addWidget(export_btn)
        
        layout.addWidget(notes_widget, stretch=1)
        self.setLayout(layout)

    def update_context(self):
        """Update the context and notify Navi."""
        self.context = self.context_input.text().strip()
        if self.context:
            self.context_input.clear()
            self.notes_display.append(f"<b>Context set:</b> {self.context}<br>")
            # Clear organized notes when context changes to allow fresh categorization
            self.organized = False
            self.db.clear_organized_notes()



    def process_note(self):
        content = self.chat_input.toPlainText().strip()
        if not content or len(content) < 10:
            return
        
        context_info = f"Context: {self.context}" if self.context else "No context set"
        prompt = f"""{context_info}. 

TASK: Take the user's note and format it into a clear, professional note.

USER'S NOTE: '{content}'

INSTRUCTIONS:
- Format the note to be clear and professional
- Keep the original meaning and intent
- Make it more readable and well-structured
- Do NOT add commentary about categorization or other notes
- Do NOT respond with meta-comments about the process

RESPONSE FORMAT: You must respond with ONLY valid JSON in this exact format:
{{"formatted": "Your formatted note text here"}}

Example: If user writes "need to check section 5", you should respond:
{{"formatted": "Need to review and verify Section 5 of the document"}}

IMPORTANT: Respond with ONLY the JSON. No other text or explanations."""
        response = self.chat_handler.get_response(
            prompt, session_id="notes_session", conversation_history=[]
        )
        try:
            # Try to extract JSON from the response if it's wrapped in other text
            response_clean = response.strip()
            if not response_clean.startswith('{'):
                # Try to find JSON in the response
                import re
                json_match = re.search(r'\{.*\}', response_clean, re.DOTALL)
                if json_match:
                    response_clean = json_match.group(0)
            
            note_data = json.loads(response_clean)
            formatted = note_data['formatted']
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.db.save_note(formatted, timestamp, self.context)
            self.notes.append(formatted)
            self.update_notes_display()
            self.chat_input.clear()
            
            # Always try to organize notes when we have 2 or more notes
            # This allows for dynamic categorization as you add more notes
            if len(self.notes) >= 2:
                self.try_organize_notes()
        except json.JSONDecodeError:
            self.notes_display.append("Error: Invalid response format")
            self.notes_display.append(f"Raw response: {response}")
        except Exception as e:
            self.notes_display.append(f"Error: {str(e)}")

    def try_organize_notes(self):
        if sum(len(note) for note in self.notes) > 7000:  # Approximate token limit check
            self.notes_display.append("Warning: Notes may exceed token limit; categorization skipped.")
            return
        
        context_info = f"Context: {self.context}" if self.context else "No context set"
        prompt = f"""{context_info}. 

TASK: Categorize the existing notes into logical groups.

EXISTING NOTES TO CATEGORIZE:
{chr(10).join([f"- {note}" for note in self.notes])}

INSTRUCTIONS:
- These are the actual notes that need to be categorized
- Look for common themes or topics among these specific notes
- If you can identify 2 or more clear categories, organize the notes accordingly
- If the notes are too diverse or no clear patterns emerge, return empty JSON
- Use the EXACT note text as provided - do not modify or summarize the notes
- Do NOT add commentary about the categorization process
- Do NOT respond with meta-comments about the notes
- Do NOT generate new content - only categorize the existing notes
- Even with just 2 notes, try to find a logical grouping if possible
RESPONSE FORMAT: You must respond with ONLY valid JSON in one of these formats:
If categories are found:
{{"categories": {{"Category Name": ["exact note text 1", "exact note text 2"], "Another Category": ["exact note text 3"]}}}}
If no clear patterns (return empty):
{{}}
Example categories might be: "Protocol Review", "Documentation", "Follow-up Tasks", "Questions", "Data Handling", "Requirements", etc.
IMPORTANT: 
- Use the exact note text as provided above
- Respond with ONLY the JSON. No other text or explanations."""
        response = self.chat_handler.get_response(
            prompt, session_id="notes_session", conversation_history=[]
        )
        try:
            # Try to extract JSON from the response if it's wrapped in other text
            response_clean = response.strip()
            if not response_clean.startswith('{'):
                # Try to find JSON in the response
                import re
                json_match = re.search(r'\{.*\}', response_clean, re.DOTALL)
                if json_match:
                    response_clean = json_match.group(0)
            
            # Check if response is truncated (ends with incomplete string)
            if response_clean.count('"') % 2 != 0 or not response_clean.endswith('}'):
                self.notes_display.append("Warning: Response appears to be truncated, skipping categorization.")
                return
            
            organized_data = json.loads(response_clean)
            if 'categories' in organized_data and organized_data['categories']:
                self.organized = True
                self.db.save_organized_notes(organized_data['categories'])
                self.notes_display.append(f"<i>Notes organized into {len(organized_data['categories'])} categories</i><br>")
                self.update_notes_display(organized=True)
            else:
                # No categories found, show unorganized notes
                self.notes_display.append("<i>No clear categories found, showing unorganized notes</i><br>")
                self.update_notes_display(organized=False)
        except json.JSONDecodeError:
            self.notes_display.append("Error: Invalid organization format")
            self.notes_display.append(f"Raw response: {response}")
        except Exception as e:
            self.notes_display.append(f"Error: {str(e)}")

    def update_notes_display(self, organized=False):
        self.notes_display.clear()
        
        # Display current context if set
        if self.context:
            self.notes_display.append(f"<b>Current Context:</b> {self.context}<br><br>")
        
        if not organized:
            for note in self.notes:
                self.notes_display.append(f"{note}<br>")
        else:
            organized_notes = self.db.get_organized_notes()
            if organized_notes and len(organized_notes) > 0:
                for category, notes_list in organized_notes.items():
                    self.notes_display.append(f"<b>{category}</b>:<br>")
                    for note in notes_list:
                        self.notes_display.append(f"  â€¢ {note}<br>")
                    self.notes_display.append("<br>")
            else:
                # Fallback to showing unorganized notes if no organized notes found
                self.notes_display.append("<b>Notes (Unorganized):</b><br>")
                for note in self.notes:
                    self.notes_display.append(f"  â€¢ {note}<br>")

    def export_notes(self):
        organized_notes = self.db.get_organized_notes() or {"Uncategorized": self.notes}
        if not organized_notes:
            self.notes_display.append("No notes to export.")
            return
        
        # Export as TXT
        txt_path = "notes_export.txt"
        with open(txt_path, "w", encoding='utf-8') as f:
            if self.context:
                f.write(f"Context: {self.context}\n\n")
            for category, notes_list in organized_notes.items():
                f.write(f"{category}:\n")
                for note in notes_list:
                    f.write(f"- {note}\n")
                f.write("\n")
        
        # Export as Word (.docx)
        doc = Document()
        if self.context:
            doc.add_heading(f"Context: {self.context}", level=1)
            doc.add_paragraph("")  # Add some space
        for category, notes_list in organized_notes.items():
            doc.add_heading(category, level=1)
            for note in notes_list:
                doc.add_paragraph(note, style='ListBullet')
        docx_path = "notes_export.docx"
        doc.save(docx_path)

        # Export as PDF
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        if self.context:
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, f"Context: {self.context}", ln=True)
            pdf.ln(5)
        for category, notes_list in organized_notes.items():
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, category, ln=True)
            pdf.set_font("Arial", size=12)
            for note in notes_list:
                pdf.cell(0, 10, f"- {note}", ln=True)
            pdf.ln(5)
        pdf_path = "notes_export.pdf"
        pdf.output(pdf_path)

        # Upload to Dropbox
        try:
            # Upload TXT file
            with open(txt_path, "rb") as f:
                self.dropbox_client.get_client().files_upload(
                    f.read(), 
                    f"/notes_export.txt",
                    mode=files.WriteMode.overwrite
                )
            
            # Upload DOCX file
            with open(docx_path, "rb") as f:
                self.dropbox_client.get_client().files_upload(
                    f.read(), 
                    f"/notes_export.docx",
                    mode=files.WriteMode.overwrite
                )
            
            # Upload PDF file
            with open(pdf_path, "rb") as f:
                self.dropbox_client.get_client().files_upload(
                    f.read(), 
                    f"/notes_export.pdf",
                    mode=files.WriteMode.overwrite
                )
            
            self.notes_display.append(f"Exported to {txt_path}, {docx_path}, {pdf_path} and uploaded to Dropbox.")
        except Exception as e:
            self.notes_display.append(f"Exported to {txt_path}, {docx_path}, {pdf_path} but Dropbox upload failed: {str(e)}")

class ChatWindow(QMainWindow):

    class ComplianceThread(QThread):
        result_signal = pyqtSignal(dict)  # Emits results dict

        def __init__(self, compliance_checker, ref_items, assess_items, session_id, conversation_history):
            super().__init__()
            self.compliance_checker = compliance_checker
            self.ref_items = ref_items
            self.assess_items = assess_items
            self.session_id = session_id
            self.conversation_history = conversation_history

        def run(self):
            result = self.compliance_checker.run_compliance_check(
                self.ref_items, self.assess_items, self.session_id, self.conversation_history
            )
            self.result_signal.emit(result)

    def __init__(self):
        logger.info("Initializing ChatWindow...")
        super().__init__()
        
        # Load stylesheet early to ensure splash screen styling works
        self.loadStylesheet("styles.qss")
        
        # Create data directory if it doesn't exist
        self.data_dir = 'C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/data'
        os.makedirs(self.data_dir, exist_ok=True)
        
        logger.info("Loading enhanced splash screen...")
        pixmap = QPixmap("assets/logo v2.png")
        self.splash = EnhancedSplashScreen(pixmap)
        self.splash.show()
        
        # Start initialization with progress tracking
        self.initialize_with_progress()

    def initialize_with_progress(self):
        """Initialize the application with progress tracking on the splash screen."""
        self.splash.update_progress(5, "Starting initialization...", "Application startup initiated")
        
        # Initialize chat handler
        self.splash.update_progress(15, "Initializing chat handler...", "Setting up chat management system")
        logger.info("Initializing chat handler...")
        self.chat_handler = ChatManager(self)
        self.db = self.chat_handler.db
        
        # Create data directories
        self.splash.update_progress(25, "Creating data directories...", "Setting up data storage structure")
        os.makedirs('data', exist_ok=True)
        self.session_id = f"SESSION_GUI_{hash(str(self))}"
        self.conversation_history = []
        
        # Create workspace tables
        self.splash.update_progress(35, "Setting up database tables...", "Initializing workspace database")
        self.chat_handler.chat_handler.db.create_workspace_tables()
        
        # Initialize todo list
        self.splash.update_progress(45, "Loading todo list...", "Initializing task management system")
        logger.info("Initializing todo list...")
        self.todoList = QListWidget(self)
        self.todo_list = TodoList(self)
        self.todo_list.loadTasksFromDB()  # Load existing tasks
        
        # Setup UI
        self.splash.update_progress(55, "Building user interface...", "Creating application interface")
        logger.info("Setting up UI...")
        self.initUI()
        
        # Initialize response handler
        self.splash.update_progress(65, "Setting up response handling...", "Configuring chat response system")
        self.response_handler = ResponseHandler(self.chatDisplay, self.chatInput, self.sendButton, self.chat_handler, self.session_id, self.conversation_history)
        
        # Connect the task signal
        self.splash.update_progress(75, "Connecting signals...", "Setting up event handlers")
        self.chat_handler.task_added_signal.connect(self.addTaskFromChat)
        
        # Load existing data
        self.splash.update_progress(85, "Loading existing data...", "Loading saved leads and documents")
        self.load_existing_data()
        
        # Final setup
        self.splash.update_progress(95, "Finalizing setup...", "Completing initialization")
        logger.info("ChatWindow initialization complete")
        
        # Show main window after a brief delay
        self.splash.update_progress(100, "Ready!", "Application initialization complete")
        QTimer.singleShot(1000, self.show_main_window)

    def load_existing_data(self):
        """Load existing data with error handling."""
        try:
            # Load existing leads
            leads_file = os.path.join(self.data_dir, 'leads.json')
            if os.path.exists(leads_file):
                with open(leads_file, 'r') as f:
                    leads = json.load(f)
                self.update_leads_table(leads)
                logger.info(f"Loaded {len(leads)} existing leads")
                self.splash.update_progress(90, "Loading existing data...", f"Loaded {len(leads)} existing leads")
        except Exception as e:
            logger.error(f"Error loading existing data: {e}")
            self.splash.update_progress(90, "Loading existing data...", f"Warning: Error loading some data: {str(e)}")

    def show_main_window(self):
        logger.info("Showing main window...")
        self.splash.update_progress(100, "Launching application...", "Displaying main interface")
        self.splash.finish(self)
        self.show()
        logger.info("Main window shown")

    def search_leads(self):
        """Run Grok 4 API search for leads based on system message."""
        try:
            # Load system message from config
            config_path = 'C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/config/lead_gen_config.json'
            if not os.path.exists(config_path):
                logger.error("Lead gen config not found.")
                return
            with open(config_path, 'r') as f:
                config = json.load(f)
            user_system_message = config.get('system_message', '')
            
            # If no user system message, use default context
            if not user_system_message:
                user_system_message = "You are a lead generation assistant for a medical device regulatory consulting firm. Focus on companies in the AI SaMD and/or IVD/LDT space."

            # Create the system message for Grok
            system_message = f"""{user_system_message}

IMPORTANT: When processing search results:
1. Verify each company's current status and leadership team
2. Include a clear rationale for why each lead is relevant
3. Generate a personalized LinkedIn message for each lead based on your research
4. Return results as a JSON array with the following fields for each lead:
   - name: Full name of the key decision maker
   - company: Company name
   - title: Their current title
   - rationale: Why this person/company is a good lead
   - linkedin_url: Their LinkedIn profile URL (if found)
   - message: A personalized LinkedIn message referencing their specific regulatory needs and how NaviSure can help
Only include leads that have been verified through the search results.

"""

            # Initialize Grok API call
            api_key = os.getenv('GROK_API_KEY', '')
            if not api_key:
                logger.error("Grok API key not found.")
                return

            # Prepare the API request
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_system_message}
                ],
                "model": "grok-4-latest",
                "stream": False
            }

            # Make the API call
            try:
                response = requests.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=120
                )
                response.raise_for_status()
                response_data = response.json()
                
                # Extract the response content
                response_content = response_data['choices'][0]['message']['content']
                
                # Log the response
                logger.info("Grok API Response:")
                logger.info(f"Response content: {response_content}")

                # Write raw response to file for inspection
                response_file = os.path.join(self.data_dir, 'grok_response.txt')
                with open(response_file, 'w', encoding='utf-8') as f:
                    f.write("Response content:\n")
                    f.write(response_content + "\n")
                logger.info(f"Raw response written to {response_file}")

                # Try to find JSON array in the response
                json_str = None
                text = response_content.strip()
                logger.info(f"Processing response text: {text}")
                
                # Look for JSON array pattern
                start_idx = text.find('[')
                end_idx = text.rfind(']') + 1
                if start_idx != -1 and end_idx > 0:
                    json_str = text[start_idx:end_idx]
                    logger.info(f"Found JSON string: {json_str}")

                if json_str:
                    try:
                        # Clean up the JSON string
                        json_str = json_str.strip()
                        # Remove any markdown code block markers
                        json_str = json_str.replace('```json', '').replace('```', '')
                        logger.info(f"Cleaned JSON string: {json_str}")
                        
                        new_leads = json.loads(json_str)
                        logger.info(f"Parsed leads: {new_leads}")
                        
                        if isinstance(new_leads, list):
                            # Successfully parsed JSON array
                            logger.info(f"Successfully parsed JSON array with {len(new_leads)} leads")
                            
                            # Load existing leads
                            leads_file = os.path.join(self.data_dir, 'leads.json')
                            existing_leads = []
                            if os.path.exists(leads_file):
                                with open(leads_file, 'r') as f:
                                    existing_leads = json.load(f)
                            
                            # Create a set of existing lead identifiers (name + company)
                            existing_identifiers = {(lead['name'], lead['company']) for lead in existing_leads}
                            
                            # Add new leads to the beginning of the list, avoiding duplicates
                            for lead in new_leads:
                                if not all(k in lead for k in ['name', 'company', 'title', 'rationale', 'message']):
                                    logger.warning(f"Skipping lead with missing required fields: {lead}")
                                    continue
                                lead['contacted'] = False
                                lead['contact_date'] = None
                                lead['linkedin_url'] = lead.get('linkedin_url', '')
                                
                                # Check for duplicates
                                if (lead['name'], lead['company']) not in existing_identifiers:
                                    existing_leads.insert(0, lead)
                                    existing_identifiers.add((lead['name'], lead['company']))
                                    logger.info(f"Added new lead: {lead['name']} from {lead['company']}")
                            
                            # Save updated leads
                            with open(leads_file, 'w') as f:
                                json.dump(existing_leads, f, indent=2)
                            
                            # Update table
                            self.update_leads_table(existing_leads)
                            logger.info(f"Successfully loaded {len(new_leads)} new leads")
                            return
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON: {e}")
                        logger.error(f"Raw JSON string: {json_str}")
                else:
                    logger.error("No JSON array found in response")
                    logger.error(f"Raw response: {response_content}")
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"Grok API error: {e}")
                QMessageBox.warning(self, "API Error", "The Grok API is currently experiencing issues. Please try again in a few minutes.")
            except Exception as e:
                logger.error(f"Search leads error: {e}")
        except Exception as e:
            logger.error(f"Search leads error: {e}")

    def update_leads_table(self, leads):
        """Update the leads table with the provided leads data."""
        self.leadsTable.setRowCount(len(leads))
        for row, lead in enumerate(leads):
            # Set row height to accommodate buttons - increased for better spacing
            self.leadsTable.setRowHeight(row, 40)  # Increased row height for better vertical centering
            
            # Name (as hyperlink if LinkedIn URL exists)
            name_item = QTableWidgetItem(lead.get('name', ''))
            if lead.get('linkedin_url'):
                name_item.setData(Qt.ItemDataRole.UserRole, lead['linkedin_url'])
                name_item.setData(Qt.ItemDataRole.UserRole + 1, "linkedin")
                name_item.setForeground(QColor("#0077B5"))  # LinkedIn blue
                font = name_item.font()
                font.setUnderline(True)
                name_item.setFont(font)
            self.leadsTable.setItem(row, 0, name_item)
            
            # Company
            self.leadsTable.setItem(row, 1, QTableWidgetItem(lead.get('company', '')))
            # Title
            self.leadsTable.setItem(row, 2, QTableWidgetItem(lead.get('title', '')))
            
            # Contacted checkbox
            contacted_cb = QCheckBox()
            contacted_cb.setChecked(lead.get('contacted', False))
            contacted_cb.stateChanged.connect(lambda state, r=row: self.on_contacted_changed(r, state))
            self.leadsTable.setCellWidget(row, 3, contacted_cb)
            
            # Contact date
            contact_date = lead.get('contact_date')
            date_item = QTableWidgetItem(contact_date if contact_date else '')
            self.leadsTable.setItem(row, 4, date_item)
            
            # Message button - with container for vertical centering
            message_button = QPushButton("View Message")
            message_button.clicked.connect(lambda _, r=row: self.generate_message(r))
            message_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(253, 98, 98, 0.8);
                    color: white;
                    border: none;
                    padding: 0px;
                    font-size: 10px;
                    border-radius: 3px;
                    min-width: 80px; /* Increased from 60px to make buttons wider */
                    min-height: 28px; /* Increased from 20px to make buttons taller */
                    max-height: 32px; /* Increased from 24px to allow taller buttons */
                }
            """)
            # Create container widget with layout for vertical centering
            message_container = QWidget()
            message_layout = QVBoxLayout(message_container)
            message_layout.addWidget(message_button, alignment=Qt.AlignmentFlag.AlignCenter)
            message_layout.setContentsMargins(0, 0, 0, 0)
            message_layout.setSpacing(0)
            self.leadsTable.setCellWidget(row, 5, message_container)
            
            # Delete button - with container for vertical centering
            delete_button = QPushButton("Delete")
            delete_button.clicked.connect(lambda _, r=row: self.delete_lead(r))
            delete_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(253, 98, 98, 0.8);
                    color: white;
                    border: none;
                    padding: 0px;
                    font-size: 10px;
                    border-radius: 3px;
                    min-width: 80px; /* Increased from 60px to make buttons wider */
                    min-height: 28px; /* Increased from 20px to make buttons taller */
                    max-height: 32px; /* Increased from 24px to allow taller buttons */
                }
            """)
            # Create container widget with layout for vertical centering
            delete_container = QWidget()
            delete_layout = QVBoxLayout(delete_container)
            delete_layout.addWidget(delete_button, alignment=Qt.AlignmentFlag.AlignCenter)
            delete_layout.setContentsMargins(0, 0, 0, 0)
            delete_layout.setSpacing(0)
            self.leadsTable.setCellWidget(row, 6, delete_container)
            
            # Rationale (with view button) - with container for vertical centering
            view_rationale_button = QPushButton("View")
            view_rationale_button.clicked.connect(lambda _, r=row: self.show_rationale(r))
            view_rationale_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(253, 98, 98, 0.8);
                    color: white;
                    border: none;
                    padding: 0px;
                    font-size: 10px;
                    border-radius: 3px;
                    min-width: 80px; /* Increased from 60px to make buttons wider */
                    min-height: 28px; /* Increased from 20px to make buttons taller */
                    max-height: 32px; /* Increased from 24px to allow taller buttons */
                }
            """)
            # Create container widget with layout for vertical centering
            view_container = QWidget()
            view_layout = QVBoxLayout(view_container)
            view_layout.addWidget(view_rationale_button, alignment=Qt.AlignmentFlag.AlignCenter)
            view_layout.setContentsMargins(0, 0, 0, 0)
            view_layout.setSpacing(0)
            self.leadsTable.setCellWidget(row, 7, view_container)
        
        # Connect cell click event for LinkedIn links
        self.leadsTable.cellClicked.connect(self.handle_cell_click)

    def handle_cell_click(self, row, column):
        """Handle cell clicks, specifically for LinkedIn links."""
        if column == 0:  # Name column
            item = self.leadsTable.item(row, column)
            if item and item.data(Qt.ItemDataRole.UserRole + 1) == "linkedin":
                url = item.data(Qt.ItemDataRole.UserRole)
                if url:
                    # Disconnect the signal temporarily to prevent multiple triggers
                    self.leadsTable.cellClicked.disconnect(self.handle_cell_click)
                    QDesktopServices.openUrl(QUrl(url))
                    # Reconnect the signal
                    self.leadsTable.cellClicked.connect(self.handle_cell_click)

    def show_rationale(self, row):
        """Show the rationale in a popup dialog."""
        leads_file = os.path.join(self.data_dir, 'leads.json')
        if os.path.exists(leads_file):
            with open(leads_file, 'r') as f:
                leads = json.load(f)
            
            if 0 <= row < len(leads):
                rationale = leads[row].get('rationale', 'No rationale available')
                
                dialog = QDialog(self)
                dialog.setWindowTitle("Lead Rationale")
                dialog.setMinimumWidth(500)
                dialog.setMinimumHeight(300)
                # dialog.setStyleSheet("""
                #     QDialog {
                #         background-color: rgb(27, 28, 30);
                #         color: white;
                #     }
                #     QTextEdit {
                #         background-color: rgba(27, 28, 30, 0.8);
                #         color: white;
                #         border: 1px solid rgba(253, 98, 98, 0.8);
                #         padding: 10px;
                #     }
                # """)
                
                layout = QVBoxLayout()
                text_edit = QTextEdit()
                text_edit.setPlainText(rationale)
                text_edit.setReadOnly(True)
                layout.addWidget(text_edit)
                
                close_button = QPushButton("Close")
                # close_button.setStyleSheet("""
                #     QPushButton {
                #         background-color: rgba(253, 98, 98, 0.8);
                #         color: white;
                #         border: none;
                #         padding: 5px 15px;
                #     }
                #     QPushButton:hover {
                #         background-color: rgba(253, 98, 98, 1);
                #     }
                # """)
                close_button.clicked.connect(dialog.accept)
                layout.addWidget(close_button)
                
                dialog.setLayout(layout)
                dialog.exec()

    def on_contacted_changed(self, row, state):
        """Handle contact checkbox state change."""
        leads_file = os.path.join(self.data_dir, 'leads.json')
        if os.path.exists(leads_file):
            with open(leads_file, 'r') as f:
                leads = json.load(f)
            
            if 0 <= row < len(leads):
                leads[row]['contacted'] = state == Qt.CheckState.Checked.value
                leads[row]['contact_date'] = datetime.now().strftime('%Y-%m-%d') if state == Qt.CheckState.Checked.value else None
                
                with open(leads_file, 'w') as f:
                    json.dump(leads, f, indent=2)
                
                # Update contact date in table
                self.leadsTable.setItem(row, 4, QTableWidgetItem(leads[row]['contact_date'] or ''))

    def delete_lead(self, row):
        """Delete a lead after confirmation."""
        reply = QMessageBox.question(
            self, 'Confirm Deletion',
            'Are you sure you want to delete this lead?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            leads_file = os.path.join(self.data_dir, 'leads.json')
            if os.path.exists(leads_file):
                with open(leads_file, 'r') as f:
                    leads = json.load(f)
                
                if 0 <= row < len(leads):
                    leads.pop(row)
                    
                    with open(leads_file, 'w') as f:
                        json.dump(leads, f, indent=2)
                    
                    self.update_leads_table(leads)

    def generate_message(self, row):
        """Show the pre-generated message for the lead in the given row."""
        try:
            leads_file = os.path.join(self.data_dir, 'leads.json')
            if not os.path.exists(leads_file):
                logger.error("Leads file not found")
                return
                
            with open(leads_file, 'r') as f:
                leads = json.load(f)
            
            if row >= len(leads):
                logger.error(f"Lead at row {row} not found in leads file")
                return
                
            lead = leads[row]
            message = lead.get('message', 'No message available')
            
            # Show message in a dialog
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Message for {lead['name']}")
            # dialog.setStyleSheet("""
            #     QDialog {
            #         background-color: rgb(27, 28, 30);
            #         color: white;
            #     }
            #     QTextEdit {
            #         background-color: rgba(27, 28, 30, 0.8);
            #         color: white;
            #         border: 1px solid rgba(253, 98, 98, 0.8);
            #     }
            # """)
            layout = QVBoxLayout()
            text_edit = QTextEdit()
            text_edit.setPlainText(message)
            text_edit.setReadOnly(True)
            layout.addWidget(text_edit)
            
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            # buttons.setStyleSheet("""
            #     QPushButton {
            #         background-color: rgba(253, 98, 98, 0.8);
            #         color: white;
            #         border: none;
            #         padding: 5px 15px;
            #     }
            #     QPushButton:hover {
            #         background-color: rgba(253, 98, 98, 1);
            #     }
            # """)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            
            dialog.setLayout(layout)
            dialog.exec()
            
        except Exception as e:
            logger.error(f"Show message error: {e}")
            QMessageBox.critical(self, "Error", f"Failed to show message: {str(e)}")

    def open_settings(self):
        """Open settings dialog to edit Grok system message."""
        dialog = SettingsDialog(self)
        if dialog.exec():
            try:
                system_message = dialog.system_message_input.toPlainText()
                config = {"system_message": system_message}
                config_path = 'C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/config/lead_gen_config.json'
                with open(config_path, 'w') as f:
                    json.dump(config, f)
                logger.info("Lead gen settings saved.")
            except Exception as e:
                logger.error(f"Save settings error: {e}")

    # Existing methods (unchanged)
    def refresh_leads(self):
        print("Weekly lead refresh TBD (Grok 3 API pending)")

    def save_document(self):
        # Example: Save to crm.py with schema {lead: str, issue: str, action: str}
        # Use DatabaseManager to insert results
        pass

    def start_recording(self):
        import sounddevice as sd
        import scipy.io.wavfile as wavfile
        import os
        import time

        self.recordButton.setEnabled(False)
        self.stopButton.setEnabled(True)
        self.recording = True
        self.sample_rate = 44100
        self.audio_data = []
        self.recording_start_time = time.time()
        
        def callback(indata, frames, time, status):
            if self.recording:
                self.audio_data.extend(indata.copy())

        self.stream = sd.InputStream(samplerate=self.sample_rate, channels=1, callback=callback)
        self.stream.start()

    def stop_recording(self):
        import scipy.io.wavfile as wavfile
        import os
        import numpy as np

        self.recording = False
        self.stream.stop()
        self.stream.close()
        self.stopButton.setEnabled(False)
        self.transcribeButton.setEnabled(True)
        
        self.audio_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_recording.wav")
        audio_array = np.array(self.audio_data)
        wavfile.write(self.audio_file_path, self.sample_rate, audio_array)

    def select_file(self):
        from PyQt6.QtWidgets import QFileDialog
        import os

        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Select File", 
            "", 
            "Media Files (*.mp4 *.m4v *.mp3 *.wav *.m4a);;All Files (*)"
        )
        
        if file_path:
            self.selected_file_path = file_path
            self.transcribeButton.setEnabled(True)
            self.meetingTranscript.setText(f"Selected file: {file_path}")
            
            if file_path.lower().endswith(('.mp4', '.m4v')):
                self.meetingTranscript.append("Extracting audio from video file...")
                self.extract_audio_from_video(file_path)
            else:
                self.selected_audio_path = file_path
                self.meetingTranscript.append("Audio file selected. Click 'Generate Transcript' to process.")
        else:
            self.meetingTranscript.setText("No file selected.")

    def extract_audio_from_video(self, video_path):
        import os
        import subprocess
        import math

        try:
            temp_audio_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio.mp3")
            self.meetingTranscript.append(f"Saving temporary audio to {temp_audio_path}")

            subprocess.run(['ffmpeg', '-i', video_path, '-vn', '-acodec', 'libmp3lame', '-ab', '128k', temp_audio_path], check=True)
            self.meetingTranscript.append("Audio extraction completed. Checking file size...")

            file_size_mb = os.path.getsize(temp_audio_path) / (1024 * 1024)
            if file_size_mb > 25:
                self.meetingTranscript.append(f"Audio file size ({file_size_mb:.2f} MB) exceeds 25 MB limit. Compressing...")
                compressed_audio_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio_compressed.mp3")
                subprocess.run(['ffmpeg', '-i', temp_audio_path, '-acodec', 'libmp3lame', '-ab', '64k', compressed_audio_path], check=True)
                os.remove(temp_audio_path)
                temp_audio_path = compressed_audio_path
                self.meetingTranscript.append("Audio compression completed. Ready for transcription.")
            else:
                self.meetingTranscript.append(f"Audio file size ({file_size_mb:.2f} MB) is within limit. Ready for transcription.")

            self.selected_audio_path = temp_audio_path
        except Exception as e:
            self.meetingTranscript.setText(f"Error extracting audio: {str(e)}")
            self.transcribeButton.setEnabled(False)
    def transcribe_meeting(self):
        import os
        import requests
        import time
        from datetime import datetime, timedelta

        self.transcribeButton.setEnabled(False)
        print("Transcribing audio...")
        
        api_key = os.getenv('ASSEMBLYAI_API_KEY', '')
        if not api_key:
            self.meetingTranscript.setText("Error: AssemblyAI API key not found.")
            self.saveTranscriptButton.setEnabled(False)
            return

        try:
            if hasattr(self, 'selected_audio_path') and os.path.exists(self.selected_audio_path):
                self.meetingTranscript.setText("Uploading audio file...")
                
                headers = {'authorization': api_key}
                with open(self.selected_audio_path, 'rb') as f:
                    response = requests.post('https://api.assemblyai.com/v2/upload', headers=headers, data=f)
                upload_url = response.json()['upload_url']
                self.meetingTranscript.append("File uploaded successfully. Starting transcription...")
                
                endpoint = "https://api.assemblyai.com/v2/transcript"
                json = {
                    "audio_url": upload_url,
                    "speaker_labels": True,
                    "speakers_expected": 16,
                    "auto_highlights": True,
                    "iab_categories": True,
                    "auto_chapters": True
                }
                headers = {"authorization": api_key, "content-type": "application/json"}
                response = requests.post(endpoint, json=json, headers=headers)
                transcript_id = response.json()['id']
                self.meetingTranscript.append(f"Transcription job started. ID: {transcript_id}")
                
                start_time = datetime.now()
                timeout = timedelta(minutes=10)
                last_status = None
                last_progress = 0
                
                while True:
                    if datetime.now() - start_time > timeout:
                        raise TimeoutError("Transcription timed out after 10 minutes")
                    
                    response = requests.get(f"{endpoint}/{transcript_id}", headers=headers)
                    status = response.json()['status']
                    progress = response.json().get('confidence', 0) or 0
                    
                    if status != last_status or (progress > 0 and progress != last_progress):
                        status_message = f"Status: {status}"
                        if progress > 0:
                            status_message += f" (Progress: {progress:.1%})"
                        self.meetingTranscript.append(status_message)
                        last_status = status
                        last_progress = progress
                    
                    if status == 'completed':
                        transcript = response.json()['text']
                        utterances = response.json()['utterances']
                        formatted_transcript = ["Note: Speakers who only spoke briefly may not be detected separately.",
                                             "----------------------------------------\n"]
                        for utterance in utterances:
                            speaker = f"Speaker {utterance['speaker']}"
                            text = utterance['text']
                            formatted_transcript.append(f"{speaker}: {text}")
                        final_transcript = "\n\n".join(formatted_transcript)
                        self.meetingTranscript.setText(final_transcript)
                        self.saveTranscriptButton.setEnabled(True)
                        self.meetingTranscript.append("\n\nTranscription completed.")
                        break
                    elif status == 'error':
                        error_msg = response.json().get('error', 'Unknown error')
                        raise Exception(f"Transcription failed: {error_msg}")
                    elif status == 'queued':
                        time.sleep(5)
                    else:
                        time.sleep(3)
            else:
                self.meetingTranscript.setText("Error: No file found for transcription.")
                self.saveTranscriptButton.setEnabled(False)
        except TimeoutError as e:
            self.meetingTranscript.setText(f"Error: {str(e)}\nThe transcription is still processing.")
            self.transcribeButton.setEnabled(True)
        except Exception as e:
            self.meetingTranscript.setText(f"Error during transcription: {str(e)}")
            self.transcribeButton.setEnabled(True)
        finally:
            self.saveTranscriptButton.setEnabled(False)

    def save_transcript(self):
        from PyQt6.QtWidgets import QFileDialog
        import os
        import time

        transcript_text = self.meetingTranscript.toPlainText()
        if not transcript_text or transcript_text.startswith("Error"):
            return

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        default_filename = f"transcript_{timestamp}.txt"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Transcript", default_filename, "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(transcript_text)
                self.saveTranscriptButton.setEnabled(False)
                self.meetingTranscript.append(f"<i>Transcript saved to {file_path}</i>")
            except Exception as e:
                self.meetingTranscript.append(f"<i>Error saving transcript: {e}</i>")

    def sendMessage(self):
        """Send a message to the chat."""
        if self.is_sending:
            return
            
        message = self.chatInput.text().strip()
        if not message:
            return
            
        self.is_sending = True
        self.sendButton.setEnabled(False)
        self.sendButton.setText("Sending...")
        self.update_status("Sending message...")
        
        # Display user message
        user_html = f'<div style="text-align: left;"><b>Me:</b> <i>{message}</i></div><br>'
        self.chatDisplay.append(user_html)
        
        # Clear input
        self.chatInput.clear()
        
        # Start chat thread with all required arguments
        self.chat_thread = ChatThread(self.chat_handler, message, self.session_id, self.conversation_history)
        self.chat_thread.response_signal.connect(self.onResponseReceived)
        self.chat_thread.finished.connect(self.onThreadFinished)
        self.chat_thread.start()

    def onThreadFinished(self):
        """Handle thread completion."""
        self.is_sending = False
        self.sendButton.setEnabled(True)
        self.sendButton.setText("Send")
        self.update_status("Message sent successfully")
    
    def addTaskFromChat(self, task_text, due_date):
        self.todo_list.addTaskFromChat(task_text, due_date)

    def addTask(self):
        self.todo_list.addTask()    

    @pyqtSlot(str)  
    def onResponseReceived(self, response):
        # Strip leading newlines to prevent extra spacing after "Navi:"
        response = response.lstrip('\n')
        
        # First try markdown processing for HTML-formatted content
        html_content = markdown.markdown(response, extensions=['extra'])
        
        # Remove leading p tag to prevent block-level formatting
        html_content = html_content[3:]  # Remove <p>
        
        # If the content doesn't contain any HTML tags, replace newlines with br tags
        if not any(tag in html_content for tag in ['<ul>', '<li>', '<p>', '<h']):
            html_content = response.replace('\n', '<br>')
        
        # Ensure the response ends with proper HTML to close any open lists
        if html_content.endswith('<li>'):
            html_content += '</li></ul>'  # Close last list item and the list itself
        elif '<li>' in html_content and not html_content.endswith('</ul>'):
            html_content += '</ul>'  # If there's an <li> but no closing </ul>
        
        self.chatDisplay.append(f'<div style="text-align: left;"><b>Navi:</b> {html_content}</div>')
        self.chatDisplay.append('<br>')  # Add spacing after Navi response
        self.conversation_history.append({"role": "assistant", "content": response})
        self.chat_handler.save_message(self.session_id, "assistant", response)
        self.sendButton.setEnabled(True)
        self.chatInput.setEnabled(True)
        self.chatInput.clear()
        self.chatInput.setFocus()

    def archiveCompletedTasks(self):
        self.todo_list.archiveCompletedTasks()

    def loadStylesheet(self, filename):
        try:
            with open(filename, "r") as f:
                self.setStyleSheet(f.read())
        except FileNotFoundError:
            pass
        except Exception as e:
            pass

    def closeEvent(self, event):
        super().closeEvent(event)

    def initUI(self):
        """Initialize the user interface."""
        # Load stylesheet early to ensure splash screen styling works
        self.loadStylesheet("styles.qss")
        
        # Create data directory if it doesn't exist
        self.data_dir = 'C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/data'
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Set up keyboard shortcuts
        self.setup_shortcuts()
        
        # Create status bar
        self.setup_status_bar()
        
        self.setWindowTitle('NaviSsurance')
        self.setGeometry(300, 300, 1600, 900)  # Increased window size for Compliance Tab
        
        # Center the window on the screen
        screen = QApplication.primaryScreen().geometry()
        window_size = self.geometry()
        x = (screen.width() - window_size.width()) // 2
        y = (screen.height() - window_size.height()) // 2
        self.move(x, y)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Left side - Chat Panel
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with other tabs
        chat_layout.setSpacing(0)  # No spacing to allow header to touch chat display
        
        # Add header to match tab bar height
        chat_header = QLabel("Navi Chat")
        chat_header.setStyleSheet("""
            QLabel {
                background-color: rgb(20, 20, 22);
                color: white;
                padding: 8px;
                font-size: 12px;
                font-weight: bold;
                border-bottom: 1px solid #404040;
            }
        """)
        chat_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chat_layout.addWidget(chat_header)
        
        self.chatDisplay = QTextBrowser(self)
        # self.chatDisplay.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.chatDisplay.setOpenExternalLinks(True)
        self.chatDisplay.setReadOnly(True)
        # Set document margins to 0 to remove internal spacing
        self.chatDisplay.document().setDocumentMargin(0)
        chat_layout.addWidget(self.chatDisplay)
        
        # Add spacing between chat display and input area
        chat_layout.addSpacing(5)
        
        chat_input_layout = QHBoxLayout()
        chat_input_layout.setContentsMargins(0, 0, 0, 0)  # No extra margins for input area
        chat_input_layout.setSpacing(5)  # Consistent spacing between input and button
        
        self.chatInput = QLineEdit(self)
        self.chatInput.setPlaceholderText("Type your message here...")
        self.chatInput.returnPressed.connect(self.sendMessage)
        self.chatInput.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chatInput.customContextMenuRequested.connect(self.show_chat_context_menu)
        chat_input_layout.addWidget(self.chatInput)
        
        self.sendButton = QPushButton("Send", self)
        self.sendButton.clicked.connect(self.sendMessage)
        self.sendButton.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sendButton.customContextMenuRequested.connect(self.show_button_context_menu)
        self.sendButton.setToolTip("Send your message (Ctrl+Return)")
        chat_input_layout.addWidget(self.sendButton)
        
        # Add context menu to chat display
        self.chatDisplay.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chatDisplay.customContextMenuRequested.connect(self.show_chat_display_context_menu)
        
        self.is_sending = False
        chat_layout.addLayout(chat_input_layout)
        
        # Add spacer at bottom to shrink chat content area vertically
        chat_layout.addSpacing(4)
        
        main_layout.addWidget(chat_widget, stretch=25)  # Reverted from 20 to 25

        # Right side - Tab Widget
        tabs = QTabWidget()
        # tabs.setStyleSheet("QTabBar::tab { color: white; background-color: rgb(20, 20, 22); } "
        #                   "QTabBar::tab:selected { background-color: rgba(253, 98, 98, 0.8); }")
        main_layout.addWidget(tabs, stretch=75)  # Reverted from 80 to 75

        # Tasks Tab
        tasks_tab = QWidget()
        tasks_layout = QVBoxLayout(tasks_tab)
        tasks_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        tasks_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        # self.todoList.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.todoList.setSpacing(5)  # Add consistent spacing between list items
        tasks_layout.addWidget(self.todoList)
        add_task_layout = QHBoxLayout()
        self.taskInput = QLineEdit(self)
        self.taskInput.setPlaceholderText("Enter a task...")
        # self.taskInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        add_task_layout.addWidget(self.taskInput)
        self.dueDateInput = QDateEdit(self)
        self.dueDateInput.setCalendarPopup(True)
        self.dueDateInput.setDate(QDate.currentDate())
        # self.dueDateInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        add_task_layout.addWidget(self.dueDateInput)
        self.addTaskButton = QPushButton("Add Task", self)
        self.addTaskButton.clicked.connect(self.addTask)
        self.addTaskButton.setToolTip("Add a new task to your list (Ctrl+T)")
        add_task_layout.addWidget(self.addTaskButton)
        tasks_layout.addLayout(add_task_layout)
        self.archiveButton = QPushButton("Archive Completed Tasks", self)
        self.archiveButton.clicked.connect(self.archiveCompletedTasks)
        self.archiveButton.setToolTip("Move completed tasks to archive")
        tasks_layout.addWidget(self.archiveButton)
        tabs.addTab(tasks_tab, "Tasks")

        # Leads Tab (modified)
        leads_tab = QWidget()
        leads_layout = QVBoxLayout(leads_tab)
        leads_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        leads_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        leads_button_layout = QHBoxLayout()
        self.settingsButton = QPushButton("Settings", self)
        self.settingsButton.clicked.connect(self.open_settings)
        self.settingsButton.setToolTip("Open application settings (Ctrl+,)")
        leads_button_layout.addWidget(self.settingsButton)
        self.runSearchButton = QPushButton("Run Search", self)
        self.runSearchButton.clicked.connect(self.search_leads)
        self.runSearchButton.setToolTip("Search for new leads (F5)")
        leads_button_layout.addWidget(self.runSearchButton)
        leads_layout.addLayout(leads_button_layout)
        
        # Configure the leads table
        self.leadsTable = QTableWidget(0, 8)  # Added column for rationale
        self.leadsTable.setHorizontalHeaderLabels([
            "Name", "Company", "Title", "Contacted", "Contact Date", "Message", "Delete", "Rationale"
        ])
        # self.leadsTable.setStyleSheet("""
        #     QTableWidget {
        #         background-color: rgba(27, 28, 30, 0.8);
        #         color: white;
        #         gridline-color: rgba(253, 98, 98, 0.3);
        #     }
        #     QTableWidget::item {
        #         padding: 5px;
        #     }
        #     QHeaderView::section {
        #         background-color: rgba(253, 98, 98, 0.8);
        #         color: white;
        #         padding: 5px;
        #         border: none;
        #     }
        #     QPushButton {
        #         background-color: rgba(253, 98, 98, 0.8);
        #         color: white;
        #         border: none;
        #         padding: 5px 10px;
        #     }
        #     QPushButton:hover {
        #         background-color: rgba(253, 98, 98, 1);
        #     }
        #     QCheckBox {
        #         color: white;
        #     }
        #     QTableWidget::item[linkedin="true"] {
        #         color: #0077B5;
        #         text-decoration: underline;
        #         cursor: pointer;
        #     }
        #     QTableWidget::item[linkedin="true"]:hover {
        #         color: #005582;
        #     }
        # """)
        
        # Set column widths and behavior
        self.leadsTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.leadsTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Company
        self.leadsTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Title
        self.leadsTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # Contacted
        self.leadsTable.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # Contact Date
        self.leadsTable.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)  # Message
        self.leadsTable.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)  # Delete
        self.leadsTable.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)  # Rationale
        
        self.leadsTable.setColumnWidth(3, 80)  # Contacted
        self.leadsTable.setColumnWidth(4, 100)  # Contact Date
        self.leadsTable.setColumnWidth(5, 120)  # Message
        self.leadsTable.setColumnWidth(6, 90)  # Delete - increased to prevent button overlap
        
        # Enable word wrap for cells
        self.leadsTable.setWordWrap(True)
        
        leads_layout.addWidget(self.leadsTable)
        tabs.addTab(leads_tab, "Leads")
        
        # Load existing leads
        leads_file = os.path.join(self.data_dir, 'leads.json')
        if os.path.exists(leads_file):
            try:
                with open(leads_file, 'r') as f:
                    leads = json.load(f)
                self.update_leads_table(leads)
                logger.info(f"Loaded {len(leads)} existing leads")
            except Exception as e:
                logger.error(f"Error loading leads: {e}")

        # Docs Tab
        docs_tab = QWidget()
        docs_layout = QHBoxLayout(docs_tab)
        docs_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        docs_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        docs_layout.addWidget(splitter)

        # Column 1: Information Reference
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_label = QLabel("Information Reference")
        # info_label.setStyleSheet("color: white;")
        info_layout.addWidget(info_label)

        self.info_url_input = QLineEdit()
        self.info_url_input.setPlaceholderText("Enter URL for reference information")
        # self.info_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.info_url_input.returnPressed.connect(self.add_info_url)
        info_layout.addWidget(self.info_url_input)

        info_upload_btn = QPushButton("Upload Reference")
        # info_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        info_upload_btn.clicked.connect(self.upload_info_file)
        info_layout.addWidget(info_upload_btn)

        self.info_list = QListWidget()
        # self.info_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.info_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.info_list.customContextMenuRequested.connect(self.show_info_context_menu)
        info_layout.addWidget(self.info_list)
        splitter.addWidget(info_widget)

        # Column 2: Document Reference
        doc_widget = QWidget()
        doc_layout = QVBoxLayout(doc_widget)
        doc_label = QLabel("Document Reference")
        # doc_label.setStyleSheet("color: white;")
        doc_layout.addWidget(doc_label)

        self.doc_url_input = QLineEdit()
        self.doc_url_input.setPlaceholderText("Enter URL for document template")
        # self.doc_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.doc_url_input.returnPressed.connect(self.add_doc_url)
        doc_layout.addWidget(self.doc_url_input)

        doc_upload_btn = QPushButton("Upload Document")
        # doc_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        doc_upload_btn.clicked.connect(self.upload_doc_file)
        doc_layout.addWidget(doc_upload_btn)

        self.doc_list = QListWidget()
        # self.doc_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.doc_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.doc_list.customContextMenuRequested.connect(self.show_doc_context_menu)
        doc_layout.addWidget(self.doc_list)


        # Column 3: Generated Document
        output_widget = QWidget()
        output_layout = QVBoxLayout(output_widget)
        output_label = QLabel("Generated Document")
        # output_label.setStyleSheet("color: white;")
        output_layout.addWidget(output_label)

        self.doc_output = QTextEdit()
        self.doc_output.setReadOnly(True)
        # self.doc_output.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        output_layout.addWidget(self.doc_output)

        generate_btn = QPushButton("Generate Document")
        # generate_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        generate_btn.clicked.connect(self.generate_document)
        output_layout.addWidget(generate_btn)

        save_btn = QPushButton("Save Document")
        # save_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        save_btn.clicked.connect(self.save_generated_document)
        output_layout.addWidget(save_btn)

        splitter.addWidget(output_widget)
        tabs.addTab(docs_tab, "Docs")

        # Meetings Tab (unchanged)
        meetings_tab = QWidget()
        meetings_layout = QVBoxLayout(meetings_tab)
        meetings_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        meetings_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        self.recordButton = QPushButton("Start Recording", self)
        self.recordButton.clicked.connect(self.start_recording)
        # self.recordButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        meetings_layout.addWidget(self.recordButton)
        self.stopButton = QPushButton("Stop Recording", self)
        self.stopButton.clicked.connect(self.stop_recording)
        # self.stopButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.stopButton.setEnabled(False)
        meetings_layout.addWidget(self.stopButton)
        self.transcribeButton = QPushButton("Generate Transcript", self)
        self.transcribeButton.clicked.connect(self.transcribe_meeting)
        # self.transcribeButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.transcribeButton.setEnabled(False)
        meetings_layout.addWidget(self.transcribeButton)
        self.selectFileButton = QPushButton("Load File", self)
        self.selectFileButton.clicked.connect(self.select_file)
        # self.selectFileButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        meetings_layout.addWidget(self.selectFileButton)
        self.meetingTranscript = QTextEdit(self)
        # self.meetingTranscript.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.meetingTranscript.setReadOnly(True)
        meetings_layout.addWidget(self.meetingTranscript)
        self.saveTranscriptButton = QPushButton("Save Transcript", self)
        self.saveTranscriptButton.clicked.connect(self.save_transcript)
        # self.saveTranscriptButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.saveTranscriptButton.setEnabled(False)
        meetings_layout.addWidget(self.saveTranscriptButton)
        tabs.addTab(meetings_tab, "Meetings")

        # Compliance Tab (moved to last position)
        compliance_tab = QWidget()
        self.setup_compliance_tab(compliance_tab)
        tabs.addTab(compliance_tab, "Compliance")

        # Dashboard Tab
        dashboard_tab = QWidget()
        self.setup_dashboard_tab(dashboard_tab)
        tabs.addTab(dashboard_tab, "Dashboard")

        # Workspace Tab
        workspace_tab = WorkspaceTab(self.chat_handler.chat_handler.db)
        tabs.addTab(workspace_tab, "Workspace")

        # Notes Tab
        notes_tab = NoteTakingSystem(self.chat_handler)
        tabs.addTab(notes_tab, "Notes")

    def setup_compliance_tab(self, tab):
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        layout.setSpacing(5)  # Consistent spacing with chat widget
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Column 1: Reference Documents
        ref_widget = QWidget()
        ref_layout = QVBoxLayout(ref_widget)
        ref_label = QLabel("Reference Documents (Regulations/Standards)")
        # ref_label.setStyleSheet("color: white;")
        ref_layout.addWidget(ref_label)

        self.ref_url_input = QLineEdit()
        self.ref_url_input.setPlaceholderText("Enter URL (e.g., https://www.ecfr.gov/21-cfr-820.3)")
        # self.ref_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.ref_url_input.returnPressed.connect(self.add_ref_url)
        ref_layout.addWidget(self.ref_url_input)

        ref_upload_btn = QPushButton("Upload Reference")
        # ref_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        ref_upload_btn.clicked.connect(self.upload_ref_file)
        ref_layout.addWidget(ref_upload_btn)

        self.ref_list = QListWidget()
        # self.ref_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        # Add context menu for removing items
        self.ref_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ref_list.customContextMenuRequested.connect(self.show_ref_context_menu)
        ref_layout.addWidget(self.ref_list)
        splitter.addWidget(ref_widget)

        # Column 2: Documents to Assess
        assess_widget = QWidget()
        assess_layout = QVBoxLayout(assess_widget)
        assess_label = QLabel("Documents to Assess (e.g., SOPs)")
        # assess_label.setStyleSheet("color: white;")
        assess_layout.addWidget(assess_label)

        self.assess_url_input = QLineEdit()
        self.assess_url_input.setPlaceholderText("Enter URL (e.g., https://navisure.com/sop.pdf)")
        # self.assess_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.assess_url_input.returnPressed.connect(self.add_assess_url)
        assess_layout.addWidget(self.assess_url_input)

        assess_upload_btn = QPushButton("Upload Document")
        # assess_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        assess_upload_btn.clicked.connect(self.upload_assess_file)
        assess_layout.addWidget(assess_upload_btn)

        self.assess_list = QListWidget()
        # self.assess_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        # Add context menu for removing items
        self.assess_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.assess_list.customContextMenuRequested.connect(self.show_assess_context_menu)
        assess_layout.addWidget(self.assess_list)
        splitter.addWidget(assess_widget)

        # Column 3: Results
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_label = QLabel("Compliance Results")
        # results_label.setStyleSheet("color: white;")
        results_layout.addWidget(results_label)

        self.results_text = QTextEdit()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate mode (spinning)
        self.progress_bar.hide()  # Hidden initially
        results_layout.addWidget(self.progress_bar)
        self.results_text.setReadOnly(True)
        # self.results_text.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        results_layout.addWidget(self.results_text)

        run_btn = QPushButton("Run Compliance Check")
        # run_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        run_btn.clicked.connect(self.run_compliance_check)
        results_layout.addWidget(run_btn)

        save_btn = QPushButton("Save Report")
        # save_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        save_btn.clicked.connect(self.save_compliance_report)
        results_layout.addWidget(save_btn)

        clear_dataset_btn = QPushButton("Clear Dataset")
        # clear_dataset_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        clear_dataset_btn.clicked.connect(self.clear_dataset)
        results_layout.addWidget(clear_dataset_btn)
        
        crm_btn = QPushButton("Link to CRM")
        # crm_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
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
            self.db.store_dataset_entry(file_path)  # Add for fine-tuning dataset

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
            self.db.store_dataset_entry(file_path)  # Add for fine-tuning dataset

    def save_document_lists(self):
        """Save the current state of document lists to persist them."""
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
        """Load saved document lists when the application starts."""
        config_path = os.path.join(self.data_dir, "compliance_documents.json")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = json.load(f)
            for item in data.get("reference_documents", []):
                self.ref_list.addItem(item)
            for item in data.get("assessed_documents", []):
                self.assess_list.addItem(item)

    def show_ref_context_menu(self, position):
        """Show context menu for reference documents list."""
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.ref_list.mapToGlobal(position))
        if action == remove_action:
            item = self.ref_list.itemAt(position)
            if item:
                self.ref_list.takeItem(self.ref_list.row(item))
                self.save_document_lists()

    def show_assess_context_menu(self, position):
        """Show context menu for assessment documents list."""
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

        # Show progress and disable button
        self.progress_bar.show()
        self.results_text.setText("Running compliance check...")
        run_btn = self.sender()  # The button that triggered this
        run_btn.setEnabled(False)

        # Start thread
        compliance_checker = ComplianceChecker(self.chat_handler)
        self.compliance_thread = self.ComplianceThread(
            compliance_checker, ref_items, assess_items, self.session_id, self.conversation_history
        )
        self.compliance_thread.result_signal.connect(self.on_compliance_complete)
        self.compliance_thread.start()

    def on_compliance_complete(self, result):
        self.progress_bar.hide()  # Hide progress
        if result["success"]:
            data = result["data"]
            formatted_results = []
            
            # Overview (if present or from fallback)
            if 'overview' in data and data['overview'].strip():
                overview = data['overview'].strip().replace('\n', '<br>')
                formatted_results.append(f"<b>Overview:</b><br>{overview}<br><br>")
            
            # Key Alignments
            if 'key_alignments' in data and data['key_alignments'].strip():
                alignments = data['key_alignments'].strip().replace('\n', '<br>')
                formatted_results.append(f"<b>Key Alignments:</b><br>{alignments}<br><br>")
            
            # Improvements (main list, from JSON or fallback)
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
            
            # Recommendations
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
        # Placeholder: Integrate with crm.py (SQLite)
        self.results_text.append("CRM integration TBD: Save compliance issues to leads.")
        # Example: Save to crm.py with schema {lead: str, issue: str, action: str}
        # Use DatabaseManager to insert results

    def add_info_url(self):
        url = self.info_url_input.text().strip()
        if url:
            self.info_list.addItem(url)
            self.info_url_input.clear()

    def add_doc_url(self):
        url = self.doc_url_input.text().strip()
        if url:
            self.doc_list.addItem(url)
            self.doc_url_input.clear()

    def upload_info_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Information Reference File",
            "",
            "All Files (*.*)"
        )
        if file_name:
            self.info_list.addItem(file_name)

    def upload_doc_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Document Template",
            "",
            "All Files (*.*)"
        )
        if file_name:
            self.doc_list.addItem(file_name)

    def show_info_context_menu(self, position):
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.info_list.mapToGlobal(position))
        if action == remove_action:
            item = self.info_list.itemAt(position)
            if item:
                self.info_list.takeItem(self.info_list.row(item))

    def show_doc_context_menu(self, position):
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.doc_list.mapToGlobal(position))
        if action == remove_action:
            item = self.doc_list.itemAt(position)
            if item:
                self.doc_list.takeItem(self.doc_list.row(item))

    def generate_document(self):
        # Get template and context from UI
        template_text = "Document template placeholder"  # This would come from UI
        context_docs = []  # This would come from UI lists
        parameters = {}  # This would come from UI inputs
        
        # Use the DocumentGenerator class
        doc_generator = DocumentGenerator(self.chat_handler)
        result = doc_generator.generate_document(template_text, context_docs, parameters)
        
        if result["success"]:
            self.doc_output.setText(result["data"])
        else:
            self.doc_output.setText(f"Error: {result['error']}")

    def save_generated_document(self):
        if not self.doc_output.toPlainText():
            QMessageBox.warning(self, "Warning", "No document to save.")
            return

        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Save Generated Document",
            "",
            "Text Files (*.txt);;All Files (*.*)"
        )
        if file_name:
            try:
                with open(file_name, 'w') as f:
                    f.write(self.doc_output.toPlainText())
                QMessageBox.information(self, "Success", "Document saved successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save document: {str(e)}")

    def setup_shortcuts(self):
        """Set up keyboard shortcuts for common actions."""
        # Chat shortcuts
        send_action = QAction("Send Message", self)
        send_action.setShortcut("Ctrl+Return")
        send_action.triggered.connect(self.sendMessage)
        self.addAction(send_action)
        
        # Tab navigation shortcuts
        next_tab_action = QAction("Next Tab", self)
        next_tab_action.setShortcut("Ctrl+Tab")
        next_tab_action.triggered.connect(self.next_tab)
        self.addAction(next_tab_action)
        
        prev_tab_action = QAction("Previous Tab", self)
        prev_tab_action.setShortcut("Ctrl+Shift+Tab")
        prev_tab_action.triggered.connect(self.previous_tab)
        self.addAction(prev_tab_action)
        
        # Task shortcuts
        add_task_action = QAction("Add Task", self)
        add_task_action.setShortcut("Ctrl+T")
        add_task_action.triggered.connect(self.addTask)
        self.addAction(add_task_action)
        
        # Search shortcuts
        search_action = QAction("Search Leads", self)
        search_action.setShortcut("Ctrl+F")
        search_action.triggered.connect(self.focus_search)
        self.addAction(search_action)
        
        # Refresh shortcuts
        refresh_action = QAction("Refresh", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_leads)
        self.addAction(refresh_action)
        
        # Settings shortcut
        settings_action = QAction("Settings", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.open_settings)
        self.addAction(settings_action)
        
        # Help shortcut
        help_action = QAction("Help", self)
        help_action.setShortcut("F1")
        help_action.triggered.connect(self.show_help)
        self.addAction(help_action)
        
        # Exit shortcut
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        self.addAction(exit_action)
    
    def setup_status_bar(self):
        """Set up status bar with various indicators."""
        self.statusBar = self.statusBar()
        
        # Main status label
        self.status_label = QLabel("Ready")
        self.statusBar.addWidget(self.status_label)
        
        # Add spacer
        self.statusBar.addPermanentWidget(QLabel("|"))
        
        # Connection status
        self.connection_label = QLabel("ðŸŸ¢ Connected")
        self.connection_label.setStyleSheet("color: #4CAF50;")
        self.statusBar.addPermanentWidget(self.connection_label)
        
        # Add spacer
        self.statusBar.addPermanentWidget(QLabel("|"))
        
        # Task counter
        self.task_counter = QLabel("Tasks: 0")
        self.statusBar.addPermanentWidget(self.task_counter)
        
        # Add spacer
        self.statusBar.addPermanentWidget(QLabel("|"))
        
        # Leads counter
        self.leads_counter = QLabel("Leads: 0")
        self.statusBar.addPermanentWidget(self.leads_counter)
        
        # Add spacer
        self.statusBar.addPermanentWidget(QLabel("|"))
        
        # Time display
        self.time_label = QLabel()
        self.statusBar.addPermanentWidget(self.time_label)
        
        # Update time every second
        self.time_timer = QTimer()
        self.time_timer.timeout.connect(self.update_time)
        self.time_timer.start(1000)
        self.update_time()
    
    def update_time(self):
        """Update the time display in status bar."""
        current_time = datetime.now().strftime("%H:%M:%S")
        self.time_label.setText(current_time)
    
    def update_status(self, message, timeout=3000):
        """Update status bar message with optional timeout."""
        self.status_label.setText(message)
        if timeout > 0:
            QTimer.singleShot(timeout, lambda: self.status_label.setText("Ready"))
    
    def update_task_counter(self, count):
        """Update task counter in status bar."""
        self.task_counter.setText(f"Tasks: {count}")
    
    def update_leads_counter(self, count):
        """Update leads counter in status bar."""
        self.leads_counter.setText(f"Leads: {count}")
    
    def set_connection_status(self, connected):
        """Update connection status indicator."""
        if connected:
            self.connection_label.setText("ðŸŸ¢ Connected")
            self.connection_label.setStyleSheet("color: #4CAF50;")
        else:
            self.connection_label.setText("ðŸ”´ Disconnected")
            self.connection_label.setStyleSheet("color: #F44336;")

    def next_tab(self):
        """Navigate to next tab."""
        current_index = self.tabs.currentIndex()
        next_index = (current_index + 1) % self.tabs.count()
        self.tabs.setCurrentIndex(next_index)
    
    def previous_tab(self):
        """Navigate to previous tab."""
        current_index = self.tabs.currentIndex()
        prev_index = (current_index - 1) % self.tabs.count()
        self.tabs.setCurrentIndex(prev_index)
    
    def focus_search(self):
        """Focus on the search input field."""
        if hasattr(self, 'searchInput'):
            self.searchInput.setFocus()
            self.searchInput.selectAll()
    
    def show_help(self):
        """Show help dialog with keyboard shortcuts."""
        help_text = """
        <h2>Keyboard Shortcuts</h2>
        <table>
            <tr><td><b>Ctrl+Return</b></td><td>Send chat message</td></tr>
            <tr><td><b>Ctrl+Tab</b></td><td>Next tab</td></tr>
            <tr><td><b>Ctrl+Shift+Tab</b></td><td>Previous tab</td></tr>
            <tr><td><b>Ctrl+T</b></td><td>Add new task</td></tr>
            <tr><td><b>Ctrl+F</b></td><td>Focus search field</td></tr>
            <tr><td><b>F5</b></td><td>Refresh leads</td></tr>
            <tr><td><b>Ctrl+,</b></td><td>Open settings</td></tr>
            <tr><td><b>F1</b></td><td>Show this help</td></tr>
            <tr><td><b>Ctrl+Q</b></td><td>Exit application</td></tr>
        </table>
        
        <h3>Tips</h3>
        <ul>
            <li>Use Tab to navigate between form fields</li>
            <li>Press Enter to activate buttons</li>
            <li>Use arrow keys to navigate lists and tables</li>
            <li>Right-click for context menus</li>
        </ul>
        """
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Help - Keyboard Shortcuts")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(help_text)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def show_chat_context_menu(self, position):
        """Show context menu for chat input."""
        menu = QMenu(self)
        
        # Standard text editing actions
        cut_action = menu.addAction("Cut")
        cut_action.triggered.connect(lambda: self.chatInput.cut())
        
        copy_action = menu.addAction("Copy")
        copy_action.triggered.connect(lambda: self.chatInput.copy())
        
        paste_action = menu.addAction("Paste")
        paste_action.triggered.connect(lambda: self.chatInput.paste())
        
        menu.addSeparator()
        
        # Chat-specific actions
        clear_action = menu.addAction("Clear")
        clear_action.triggered.connect(lambda: self.chatInput.clear())
        
        select_all_action = menu.addAction("Select All")
        select_all_action.triggered.connect(lambda: self.chatInput.selectAll())
        
        menu.exec(self.chatInput.mapToGlobal(position))
    
    def show_button_context_menu(self, position):
        """Show context menu for send button."""
        menu = QMenu(self)
        
        # Button-specific actions
        send_action = menu.addAction("Send Message")
        send_action.triggered.connect(self.sendMessage)
        
        menu.addSeparator()
        
        # Quick message templates
        templates_menu = menu.addMenu("Quick Messages")
        
        template1 = templates_menu.addAction("Hello, how can I help you today?")
        template1.triggered.connect(lambda: self.insert_template("Hello, how can I help you today?"))
        
        template2 = templates_menu.addAction("Thank you for your inquiry.")
        template2.triggered.connect(lambda: self.insert_template("Thank you for your inquiry."))
        
        template3 = templates_menu.addAction("I'll get back to you shortly.")
        template3.triggered.connect(lambda: self.insert_template("I'll get back to you shortly."))
        
        menu.exec(self.sendButton.mapToGlobal(position))
    
    def show_chat_display_context_menu(self, position):
        """Show context menu for chat display."""
        menu = QMenu(self)
        
        # Text actions
        copy_action = menu.addAction("Copy Selected Text")
        copy_action.triggered.connect(lambda: self.chatDisplay.copy())
        
        select_all_action = menu.addAction("Select All")
        select_all_action.triggered.connect(lambda: self.chatDisplay.selectAll())
        
        menu.addSeparator()
        
        # Chat history actions
        save_chat_action = menu.addAction("Save Chat History")
        save_chat_action.triggered.connect(self.save_chat_history)
        
        clear_chat_action = menu.addAction("Clear Chat")
        clear_chat_action.triggered.connect(self.clear_chat_history)
        
        menu.addSeparator()
        
        # Export actions
        export_menu = menu.addMenu("Export")
        
        export_text_action = export_menu.addAction("Export as Text")
        export_text_action.triggered.connect(self.export_chat_as_text)
        
        export_html_action = export_menu.addAction("Export as HTML")
        export_html_action.triggered.connect(self.export_chat_as_html)
        
        menu.exec(self.chatDisplay.mapToGlobal(position))
    
    def insert_template(self, template_text):
        """Insert a template message into the chat input."""
        self.chatInput.setText(template_text)
        self.chatInput.setFocus()
        self.chatInput.selectAll()
    
    def save_chat_history(self):
        """Save current chat history to file."""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save Chat History", "", "Text Files (*.txt);;HTML Files (*.html)"
            )
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.chatDisplay.toPlainText())
                QMessageBox.information(self, "Success", "Chat history saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save chat history: {str(e)}")
    
    def clear_chat_history(self):
        """Clear the chat display."""
        reply = QMessageBox.question(
            self, "Clear Chat", "Are you sure you want to clear the chat history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.chatDisplay.clear()
    
    def export_chat_as_text(self):
        """Export chat as plain text."""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Chat as Text", "chat_export.txt", "Text Files (*.txt)"
            )
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.chatDisplay.toPlainText())
                QMessageBox.information(self, "Success", "Chat exported as text successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export chat: {str(e)}")
    
    def export_chat_as_html(self):
        """Export chat as HTML."""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Chat as HTML", "chat_export.html", "HTML Files (*.html)"
            )
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.chatDisplay.toHtml())
                QMessageBox.information(self, "Success", "Chat exported as HTML successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export chat: {str(e)}")

    def loadStylesheet(self, filename):
        try:
            with open(filename, "r") as f:
                self.setStyleSheet(f.read())
        except FileNotFoundError:
            pass
        except Exception as e:
            pass

    def closeEvent(self, event):
        super().closeEvent(event)

    def initUI(self):
        """Initialize the user interface."""
        # Load stylesheet early to ensure splash screen styling works
        self.loadStylesheet("styles.qss")
        
        # Create data directory if it doesn't exist
        self.data_dir = 'C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/data'
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Set up keyboard shortcuts
        self.setup_shortcuts()
        
        # Create status bar
        self.setup_status_bar()
        
        self.setWindowTitle('NaviSsurance')
        self.setGeometry(300, 300, 1600, 900)  # Increased window size for Compliance Tab
        
        # Center the window on the screen
        screen = QApplication.primaryScreen().geometry()
        window_size = self.geometry()
        x = (screen.width() - window_size.width()) // 2
        y = (screen.height() - window_size.height()) // 2
        self.move(x, y)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Left side - Chat Panel
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with other tabs
        chat_layout.setSpacing(0)  # No spacing to allow header to touch chat display
        
        # Add header to match tab bar height
        chat_header = QLabel("Navi Chat")
        chat_header.setStyleSheet("""
            QLabel {
                background-color: rgb(20, 20, 22);
                color: white;
                padding: 8px;
                font-size: 12px;
                font-weight: bold;
                border-bottom: 1px solid #404040;
            }
        """)
        chat_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chat_layout.addWidget(chat_header)
        
        self.chatDisplay = QTextBrowser(self)
        # self.chatDisplay.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.chatDisplay.setOpenExternalLinks(True)
        self.chatDisplay.setReadOnly(True)
        # Set document margins to 0 to remove internal spacing
        self.chatDisplay.document().setDocumentMargin(0)
        chat_layout.addWidget(self.chatDisplay)
        
        # Add spacing between chat display and input area
        chat_layout.addSpacing(5)
        
        chat_input_layout = QHBoxLayout()
        chat_input_layout.setContentsMargins(0, 0, 0, 0)  # No extra margins for input area
        chat_input_layout.setSpacing(5)  # Consistent spacing between input and button
        
        self.chatInput = QLineEdit(self)
        self.chatInput.setPlaceholderText("Type your message here...")
        self.chatInput.returnPressed.connect(self.sendMessage)
        self.chatInput.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chatInput.customContextMenuRequested.connect(self.show_chat_context_menu)
        chat_input_layout.addWidget(self.chatInput)
        
        self.sendButton = QPushButton("Send", self)
        self.sendButton.clicked.connect(self.sendMessage)
        self.sendButton.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sendButton.customContextMenuRequested.connect(self.show_button_context_menu)
        self.sendButton.setToolTip("Send your message (Ctrl+Return)")
        chat_input_layout.addWidget(self.sendButton)
        
        # Add context menu to chat display
        self.chatDisplay.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chatDisplay.customContextMenuRequested.connect(self.show_chat_display_context_menu)
        
        self.is_sending = False
        chat_layout.addLayout(chat_input_layout)
        
        # Add spacer at bottom to shrink chat content area vertically
        chat_layout.addSpacing(4)
        
        main_layout.addWidget(chat_widget, stretch=25)  # Reverted from 20 to 25

        # Right side - Tab Widget
        tabs = QTabWidget()
        # tabs.setStyleSheet("QTabBar::tab { color: white; background-color: rgb(20, 20, 22); } "
        #                   "QTabBar::tab:selected { background-color: rgba(253, 98, 98, 0.8); }")
        main_layout.addWidget(tabs, stretch=75)  # Reverted from 80 to 75

        # Tasks Tab
        tasks_tab = QWidget()
        tasks_layout = QVBoxLayout(tasks_tab)
        tasks_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        tasks_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        # self.todoList.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.todoList.setSpacing(5)  # Add consistent spacing between list items
        tasks_layout.addWidget(self.todoList)
        add_task_layout = QHBoxLayout()
        self.taskInput = QLineEdit(self)
        self.taskInput.setPlaceholderText("Enter a task...")
        # self.taskInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        add_task_layout.addWidget(self.taskInput)
        self.dueDateInput = QDateEdit(self)
        self.dueDateInput.setCalendarPopup(True)
        self.dueDateInput.setDate(QDate.currentDate())
        # self.dueDateInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        add_task_layout.addWidget(self.dueDateInput)
        self.addTaskButton = QPushButton("Add Task", self)
        self.addTaskButton.clicked.connect(self.addTask)
        self.addTaskButton.setToolTip("Add a new task to your list (Ctrl+T)")
        add_task_layout.addWidget(self.addTaskButton)
        tasks_layout.addLayout(add_task_layout)
        self.archiveButton = QPushButton("Archive Completed Tasks", self)
        self.archiveButton.clicked.connect(self.archiveCompletedTasks)
        self.archiveButton.setToolTip("Move completed tasks to archive")
        tasks_layout.addWidget(self.archiveButton)
        tabs.addTab(tasks_tab, "Tasks")

        # Leads Tab (modified)
        leads_tab = QWidget()
        leads_layout = QVBoxLayout(leads_tab)
        leads_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        leads_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        leads_button_layout = QHBoxLayout()
        self.settingsButton = QPushButton("Settings", self)
        self.settingsButton.clicked.connect(self.open_settings)
        self.settingsButton.setToolTip("Open application settings (Ctrl+,)")
        leads_button_layout.addWidget(self.settingsButton)
        self.runSearchButton = QPushButton("Run Search", self)
        self.runSearchButton.clicked.connect(self.search_leads)
        self.runSearchButton.setToolTip("Search for new leads (F5)")
        leads_button_layout.addWidget(self.runSearchButton)
        leads_layout.addLayout(leads_button_layout)
        
        # Configure the leads table
        self.leadsTable = QTableWidget(0, 8)  # Added column for rationale
        self.leadsTable.setHorizontalHeaderLabels([
            "Name", "Company", "Title", "Contacted", "Contact Date", "Message", "Delete", "Rationale"
        ])
        # self.leadsTable.setStyleSheet("""
        #     QTableWidget {
        #         background-color: rgba(27, 28, 30, 0.8);
        #         color: white;
        #         gridline-color: rgba(253, 98, 98, 0.3);
        #     }
        #     QTableWidget::item {
        #         padding: 5px;
        #     }
        #     QHeaderView::section {
        #         background-color: rgba(253, 98, 98, 0.8);
        #         color: white;
        #         padding: 5px;
        #         border: none;
        #     }
        #     QPushButton {
        #         background-color: rgba(253, 98, 98, 0.8);
        #         color: white;
        #         border: none;
        #         padding: 5px 10px;
        #     }
        #     QPushButton:hover {
        #         background-color: rgba(253, 98, 98, 1);
        #     }
        #     QCheckBox {
        #         color: white;
        #     }
        #     QTableWidget::item[linkedin="true"] {
        #         color: #0077B5;
        #         text-decoration: underline;
        #         cursor: pointer;
        #     }
        #     QTableWidget::item[linkedin="true"]:hover {
        #         color: #005582;
        #     }
        # """)
        
        # Set column widths and behavior
        self.leadsTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.leadsTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Company
        self.leadsTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Title
        self.leadsTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # Contacted
        self.leadsTable.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # Contact Date
        self.leadsTable.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)  # Message
        self.leadsTable.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)  # Delete
        self.leadsTable.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)  # Rationale
        
        self.leadsTable.setColumnWidth(3, 80)  # Contacted
        self.leadsTable.setColumnWidth(4, 100)  # Contact Date
        self.leadsTable.setColumnWidth(5, 120)  # Message
        self.leadsTable.setColumnWidth(6, 90)  # Delete - increased to prevent button overlap
        
        # Enable word wrap for cells
        self.leadsTable.setWordWrap(True)
        
        leads_layout.addWidget(self.leadsTable)
        tabs.addTab(leads_tab, "Leads")
        
        # Load existing leads
        leads_file = os.path.join(self.data_dir, 'leads.json')
        if os.path.exists(leads_file):
            try:
                with open(leads_file, 'r') as f:
                    leads = json.load(f)
                self.update_leads_table(leads)
                logger.info(f"Loaded {len(leads)} existing leads")
            except Exception as e:
                logger.error(f"Error loading leads: {e}")

        # Docs Tab
        docs_tab = QWidget()
        docs_layout = QHBoxLayout(docs_tab)
        docs_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        docs_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        docs_layout.addWidget(splitter)

        # Column 1: Information Reference
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_label = QLabel("Information Reference")
        # info_label.setStyleSheet("color: white;")
        info_layout.addWidget(info_label)

        self.info_url_input = QLineEdit()
        self.info_url_input.setPlaceholderText("Enter URL for reference information")
        # self.info_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.info_url_input.returnPressed.connect(self.add_info_url)
        info_layout.addWidget(self.info_url_input)

        info_upload_btn = QPushButton("Upload Reference")
        # info_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        info_upload_btn.clicked.connect(self.upload_info_file)
        info_layout.addWidget(info_upload_btn)

        self.info_list = QListWidget()
        # self.info_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.info_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.info_list.customContextMenuRequested.connect(self.show_info_context_menu)
        info_layout.addWidget(self.info_list)
        splitter.addWidget(info_widget)

        # Column 2: Document Reference
        doc_widget = QWidget()
        doc_layout = QVBoxLayout(doc_widget)
        doc_label = QLabel("Document Reference")
        # doc_label.setStyleSheet("color: white;")
        doc_layout.addWidget(doc_label)

        self.doc_url_input = QLineEdit()
        self.doc_url_input.setPlaceholderText("Enter URL for document template")
        # self.doc_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.doc_url_input.returnPressed.connect(self.add_doc_url)
        doc_layout.addWidget(self.doc_url_input)

        doc_upload_btn = QPushButton("Upload Document")
        # doc_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        doc_upload_btn.clicked.connect(self.upload_doc_file)
        doc_layout.addWidget(doc_upload_btn)

        self.doc_list = QListWidget()
        # self.doc_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.doc_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.doc_list.customContextMenuRequested.connect(self.show_doc_context_menu)
        doc_layout.addWidget(self.doc_list)


        # Column 3: Generated Document
        output_widget = QWidget()
        output_layout = QVBoxLayout(output_widget)
        output_label = QLabel("Generated Document")
        # output_label.setStyleSheet("color: white;")
        output_layout.addWidget(output_label)

        self.doc_output = QTextEdit()
        self.doc_output.setReadOnly(True)
        # self.doc_output.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        output_layout.addWidget(self.doc_output)

        generate_btn = QPushButton("Generate Document")
        # generate_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        generate_btn.clicked.connect(self.generate_document)
        output_layout.addWidget(generate_btn)

        save_btn = QPushButton("Save Document")
        # save_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        save_btn.clicked.connect(self.save_generated_document)
        output_layout.addWidget(save_btn)

        splitter.addWidget(output_widget)
        tabs.addTab(docs_tab, "Docs")

        # Meetings Tab (unchanged)
        meetings_tab = QWidget()
        meetings_layout = QVBoxLayout(meetings_tab)
        meetings_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        meetings_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        self.recordButton = QPushButton("Start Recording", self)
        self.recordButton.clicked.connect(self.start_recording)
        # self.recordButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        meetings_layout.addWidget(self.recordButton)
        self.stopButton = QPushButton("Stop Recording", self)
        self.stopButton.clicked.connect(self.stop_recording)
        # self.stopButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.stopButton.setEnabled(False)
        meetings_layout.addWidget(self.stopButton)
        self.transcribeButton = QPushButton("Generate Transcript", self)
        self.transcribeButton.clicked.connect(self.transcribe_meeting)
        # self.transcribeButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.transcribeButton.setEnabled(False)
        meetings_layout.addWidget(self.transcribeButton)
        self.selectFileButton = QPushButton("Load File", self)
        self.selectFileButton.clicked.connect(self.select_file)
        # self.selectFileButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        meetings_layout.addWidget(self.selectFileButton)
        self.meetingTranscript = QTextEdit(self)
        # self.meetingTranscript.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.meetingTranscript.setReadOnly(True)
        meetings_layout.addWidget(self.meetingTranscript)
        self.saveTranscriptButton = QPushButton("Save Transcript", self)
        self.saveTranscriptButton.clicked.connect(self.save_transcript)
        # self.saveTranscriptButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.saveTranscriptButton.setEnabled(False)
        meetings_layout.addWidget(self.saveTranscriptButton)
        tabs.addTab(meetings_tab, "Meetings")

        # Compliance Tab (moved to last position)
        compliance_tab = QWidget()
        self.setup_compliance_tab(compliance_tab)
        tabs.addTab(compliance_tab, "Compliance")

        # Dashboard Tab
        dashboard_tab = QWidget()
        self.setup_dashboard_tab(dashboard_tab)
        tabs.addTab(dashboard_tab, "Dashboard")

        # Workspace Tab
        workspace_tab = WorkspaceTab(self.chat_handler.chat_handler.db)
        tabs.addTab(workspace_tab, "Workspace")

        # Notes Tab
        notes_tab = NoteTakingSystem(self.chat_handler)
        tabs.addTab(notes_tab, "Notes")
    def setup_compliance_tab(self, tab):
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        layout.setSpacing(5)  # Consistent spacing with chat widget
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Column 1: Reference Documents
        ref_widget = QWidget()
        ref_layout = QVBoxLayout(ref_widget)
        ref_label = QLabel("Reference Documents (Regulations/Standards)")
        # ref_label.setStyleSheet("color: white;")
        ref_layout.addWidget(ref_label)

        self.ref_url_input = QLineEdit()
        self.ref_url_input.setPlaceholderText("Enter URL (e.g., https://www.ecfr.gov/21-cfr-820.3)")
        # self.ref_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.ref_url_input.returnPressed.connect(self.add_ref_url)
        ref_layout.addWidget(self.ref_url_input)

        ref_upload_btn = QPushButton("Upload Reference")
        # ref_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        ref_upload_btn.clicked.connect(self.upload_ref_file)
        ref_layout.addWidget(ref_upload_btn)

        self.ref_list = QListWidget()
        # self.ref_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        # Add context menu for removing items
        self.ref_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ref_list.customContextMenuRequested.connect(self.show_ref_context_menu)
        ref_layout.addWidget(self.ref_list)
        splitter.addWidget(ref_widget)

        # Column 2: Documents to Assess
        assess_widget = QWidget()
        assess_layout = QVBoxLayout(assess_widget)
        assess_label = QLabel("Documents to Assess (e.g., SOPs)")
        # assess_label.setStyleSheet("color: white;")
        assess_layout.addWidget(assess_label)

        self.assess_url_input = QLineEdit()
        self.assess_url_input.setPlaceholderText("Enter URL (e.g., https://navisure.com/sop.pdf)")
        # self.assess_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.assess_url_input.returnPressed.connect(self.add_assess_url)
        assess_layout.addWidget(self.assess_url_input)

        assess_upload_btn = QPushButton("Upload Document")
        # assess_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        assess_upload_btn.clicked.connect(self.upload_assess_file)
        assess_layout.addWidget(assess_upload_btn)

        self.assess_list = QListWidget()
        # self.assess_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        # Add context menu for removing items
        self.assess_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.assess_list.customContextMenuRequested.connect(self.show_assess_context_menu)
        assess_layout.addWidget(self.assess_list)
        splitter.addWidget(assess_widget)

        # Column 3: Results
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_label = QLabel("Compliance Results")
        # results_label.setStyleSheet("color: white;")
        results_layout.addWidget(results_label)

        self.results_text = QTextEdit()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate mode (spinning)
        self.progress_bar.hide()  # Hidden initially
        results_layout.addWidget(self.progress_bar)
        self.results_text.setReadOnly(True)
        # self.results_text.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        results_layout.addWidget(self.results_text)

        run_btn = QPushButton("Run Compliance Check")
        # run_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        run_btn.clicked.connect(self.run_compliance_check)
        results_layout.addWidget(run_btn)

        save_btn = QPushButton("Save Report")
        # save_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        save_btn.clicked.connect(self.save_compliance_report)
        results_layout.addWidget(save_btn)

        clear_dataset_btn = QPushButton("Clear Dataset")
        # clear_dataset_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        clear_dataset_btn.clicked.connect(self.clear_dataset)
        results_layout.addWidget(clear_dataset_btn)
        
        crm_btn = QPushButton("Link to CRM")
        # crm_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        crm_btn.clicked.connect(self.link_to_crm)
        results_layout.addWidget(crm_btn)
        splitter.addWidget(results_widget)

        # Load existing documents
        self.load_document_lists()

    def setup_dashboard_tab(self, tab):
        """Setup the dashboard tab with new layout: news feed on right, schedule middle top, task list middle bottom."""
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Header - styled as a label, not a button
        dashboard_header = QLabel("Dashboard - Overview")
        dashboard_header.setStyleSheet("color: white; font-weight: bold; font-size: 16px; padding: 10px; background-color: transparent; border: none;")
        dashboard_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(dashboard_header)
        
        # Create main horizontal layout for left and right columns
        main_layout = QHBoxLayout()
        main_layout.setSpacing(10)
        
        # Left column: Schedule and Task List
        left_column = QVBoxLayout()
        left_column.setSpacing(10)
        
        # Top: Schedule
        schedule_widget = self.create_dashboard_schedule_widget()
        left_column.addWidget(schedule_widget)
        
        # Bottom: Task List
        task_widget = self.create_dashboard_task_widget()
        left_column.addWidget(task_widget)
        
        # Right column: News Feed (mirrors chat window style)
        news_widget = self.create_dashboard_news_widget()
        
        # Add columns to main layout
        main_layout.addLayout(left_column, 2)  # Left column takes 2/3 of space
        main_layout.addWidget(news_widget, 1)  # Right column takes 1/3 of space
        
        layout.addLayout(main_layout)
        
        # Add refresh button at bottom
        refresh_layout = QHBoxLayout()
        refresh_layout.addStretch()
        
        refresh_news_btn = QPushButton("Refresh News")
        refresh_news_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 8px 15px; border-radius: 3px;")
        refresh_news_btn.clicked.connect(self.refresh_news_feed)
        refresh_layout.addWidget(refresh_news_btn)
        
        layout.addLayout(refresh_layout)
        
        # Setup auto-refresh timer for schedule (every 15 minutes)
        self.schedule_timer = QTimer()
        self.schedule_timer.timeout.connect(self.load_dashboard_schedule)
        self.schedule_timer.start(900000)  # 15 minutes in milliseconds
    

    
    def create_dashboard_task_widget(self):
        """Create the task list widget for the dashboard."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header - styled as a label, not a button
        task_header = QLabel("Task List")
        task_header.setStyleSheet("color: white; font-weight: bold; padding: 3px; background-color: transparent; border: none; font-size: 11px;")
        task_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        task_header.setMaximumHeight(25)
        layout.addWidget(task_header)
        
        # Task list - use proper TodoList integration with better text handling
        self.dashboard_task_list = QListWidget()
        self.dashboard_task_list.setStyleSheet("""
            QListWidget {
                background-color: rgba(27, 28, 30, 0.8); 
                color: white; 
                border: 1px solid rgba(253, 98, 98, 0.3); 
                border-radius: 3px;
                font-size: 10px;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid rgba(253, 98, 98, 0.2);
                min-height: 20px;
            }
            QListWidget::item:selected {
                background-color: rgba(253, 98, 98, 0.3);
            }
        """)
        self.dashboard_task_list.setWordWrap(True)  # Enable word wrapping
        self.dashboard_task_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.dashboard_task_list.itemDoubleClicked.connect(self.on_task_double_clicked)
        layout.addWidget(self.dashboard_task_list)
        
        # Quick add task
        add_layout = QHBoxLayout()
        self.dashboard_task_input = QLineEdit()
        self.dashboard_task_input.setPlaceholderText("Quick task...")
        self.dashboard_task_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.5); padding: 3px; border-radius: 3px;")
        self.dashboard_task_input.returnPressed.connect(self.add_dashboard_task)
        add_layout.addWidget(self.dashboard_task_input)
        
        add_btn = QPushButton("Add")
        add_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 3px 8px; border-radius: 3px;")
        add_btn.clicked.connect(self.add_dashboard_task)
        add_layout.addWidget(add_btn)
        
        layout.addLayout(add_layout)
        
        # Load recent tasks
        self.load_dashboard_tasks()
        
        return widget
    
    def create_dashboard_schedule_widget(self):
        """Create the schedule widget for the dashboard."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header - styled as a label, not a button
        schedule_header = QLabel("Today's Schedule")
        schedule_header.setStyleSheet("color: white; font-weight: bold; padding: 3px; background-color: transparent; border: none; font-size: 11px;")
        schedule_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        schedule_header.setMaximumHeight(25)
        layout.addWidget(schedule_header)
        
        # Schedule display - no height restriction
        self.dashboard_schedule_display = QTextBrowser()
        self.dashboard_schedule_display.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px;")
        self.dashboard_schedule_display.setReadOnly(True)
        self.dashboard_schedule_display.setPlaceholderText("Loading schedule...")
        layout.addWidget(self.dashboard_schedule_display)
        
        # Load initial schedule
        self.load_dashboard_schedule()
        
        return widget
    
    def create_dashboard_news_widget(self):
        """Create the news feed widget for the dashboard - styled like a chat window."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header - styled as a label, not a button
        news_header = QLabel("News Feed")
        news_header.setStyleSheet("color: white; font-weight: bold; padding: 3px; background-color: transparent; border: none; font-size: 11px;")
        news_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        news_header.setMaximumHeight(25)
        layout.addWidget(news_header)
        
        # News display - no height restriction, show full content
        self.dashboard_news_display = QTextBrowser()
        self.dashboard_news_display.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px; font-size: 10px;")
        self.dashboard_news_display.setReadOnly(True)
        self.dashboard_news_display.setPlaceholderText("Loading news...")
        self.dashboard_news_display.setOpenExternalLinks(True)  # Enable hyperlink clicking
        layout.addWidget(self.dashboard_news_display)
        
        # Auto-refresh timer (every hour)
        self.news_timer = QTimer()
        self.news_timer.timeout.connect(self.refresh_news_feed)
        self.news_timer.start(3600000)  # 1 hour in milliseconds
        
        # Load initial news
        self.load_dashboard_news()
        
        # Setup news cleanup timer (clean up old news every 24 hours)
        self.news_cleanup_timer = QTimer()
        self.news_cleanup_timer.timeout.connect(self.cleanup_old_news)
        self.news_cleanup_timer.start(86400000)  # 24 hours in milliseconds
        
        return widget
    

    
    def add_dashboard_task(self):
        """Add a quick task from the dashboard using proper TodoList integration."""
        task_text = self.dashboard_task_input.text().strip()
        if not task_text:
            return
        
        # Add to main task list using TodoList
        if hasattr(self, 'todo_list'):
            self.todo_list.addTaskFromChat(task_text, datetime.now().strftime('%Y-%m-%d'))
            # Refresh dashboard display
            self.load_dashboard_tasks()
        
        # Clear input
        self.dashboard_task_input.clear()
    
    def load_dashboard_tasks(self):
        """Load recent tasks for the dashboard using proper TodoList integration."""
        try:
            # Use the same database connection and method as main TodoList
            if hasattr(self, 'todo_list'):
                # Clear current display
                self.dashboard_task_list.clear()
                
                # Get tasks from database using TodoList's method
                with sqlite3.connect(self.chat_handler.chat_handler.db.db_name) as conn:
                    cursor = conn.execute("""
                        SELECT task, due_date FROM tasks 
                        WHERE completed = 0 
                        ORDER BY created_at DESC 
                        LIMIT 10
                    """)
                    tasks = cursor.fetchall()
                
                # Display tasks in a simple, clean format
                for task, due_date in tasks:
                    # Create a simple text item with checkbox
                    item_text = f"â˜ {task}"
                    if due_date:
                        item_text += f" (Due: {due_date})"
                    
                    item = QListWidgetItem(item_text)
                    item.setData(Qt.ItemDataRole.UserRole, task)  # Store original task text
                    self.dashboard_task_list.addItem(item)
                    
        except Exception as e:
            self.dashboard_task_list.addItem(f"Error loading tasks: {str(e)}")
    
    def update_dashboard_task_status(self, task_text, completed):
        """Update task status in database when checkbox is clicked."""
        try:
            if hasattr(self, 'todo_list'):
                # Use TodoList's method to update task status
                with sqlite3.connect(self.chat_handler.chat_handler.db.db_name) as conn:
                    conn.execute("""
                        UPDATE tasks SET completed = ? WHERE task = ?
                    """, (1 if completed else 0, task_text))
                    conn.commit()
                
                # Refresh display
                self.load_dashboard_tasks()
        except Exception as e:
            print(f"Error updating task status: {e}")
    
    def on_task_double_clicked(self, item):
        """Handle double-click on task item to mark as complete."""
        try:
            # Get the original task text from item data
            task_text = item.data(Qt.ItemDataRole.UserRole)
            if task_text:
                # Mark task as completed
                with sqlite3.connect(self.chat_handler.chat_handler.db.db_name) as conn:
                    conn.execute("""
                        UPDATE tasks SET completed = 1 WHERE task = ?
                    """, (task_text,))
                    conn.commit()
                
                # Refresh the task list
                self.load_dashboard_tasks()
        except Exception as e:
            print(f"Error completing task: {e}")
    
    def load_dashboard_schedule(self):
        """Load today's schedule for the dashboard."""
        try:
            # Get today's events from data fetcher
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow = today + timedelta(days=1)
            time_min = today.strftime('%Y-%m-%dT%H:%M:%SZ')
            time_max = tomorrow.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            events = self.chat_handler.chat_handler.data_fetcher.get_calendar_events(time_min, time_max)
            
            if events:
                schedule_text = "Today's Events:\n\n"
                for event in events[:5]:  # Limit to 5 events
                    start_time = event['start'].get('dateTime', event['start'].get('date'))
                    summary = event.get('summary', 'No title')
                    schedule_text += f"- {start_time}: {summary}\n"
            else:
                schedule_text = "No events scheduled for today"
            
            self.dashboard_schedule_display.setPlainText(schedule_text)
            
        except Exception as e:
            self.dashboard_schedule_display.setPlainText(f"Error loading schedule: {str(e)}")
    
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
            self.dashboard_news_display.setPlainText(f"Error loading news: {str(e)}")
    
    def process_and_store_news(self, news_results):
        """Process news results and store them in the database, avoiding duplicates."""
        try:
            # Split news results into individual items (assuming they're separated by newlines or other delimiters)
            # This is a simplified approach - in practice, you might want more sophisticated parsing
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
                news_text = "<div style='color: white; font-family: Arial, sans-serif;'>"
                news_text += "<h3 style='color: #fd6262; margin-bottom: 15px;'>Latest News</h3>"
                
                for title, content, url, source, published_date, created_at in recent_news:
                    news_text += "<div style='margin-bottom: 20px; padding: 10px; background-color: rgba(253, 98, 98, 0.1); border-radius: 5px;'>"
                    news_text += f"<h4 style='color: #fd6262; margin: 0 0 8px 0;'>{title}</h4>"
                    if content:
                        news_text += f"<p style='margin: 0 0 8px 0; line-height: 1.4;'>{content}</p>"
                    if url:
                        news_text += f'<p style="margin: 0 0 5px 0;"><a href="{url}" style="color: #4fc3f7; text-decoration: underline;">🔗 Read full article</a></p>'
                    if published_date:
                        news_text += f"<small style='color: #888;'>Published: {published_date}</small>"
                    news_text += "</div>"
                
                news_text += "</div>"
                
                # Set HTML content to enable hyperlinks
                self.dashboard_news_display.setHtml(news_text)
            else:
                self.dashboard_news_display.setPlainText("No recent news available. Check back later.")
                
        except Exception as e:
            self.dashboard_news_display.setPlainText(f"Error displaying news: {str(e)}")
    
    def refresh_schedule(self):
        """Refresh the schedule display."""
        self.load_dashboard_schedule()
    
    def refresh_news_feed(self):
        """Refresh the news feed."""
        self.load_dashboard_news()
    
    def cleanup_old_news(self):
        """Clean up old news items from the database."""
        try:
            if hasattr(self, 'db'):
                self.db.cleanup_old_news(days=7)
        except Exception as e:
            print(f"Error cleaning up old news: {e}")

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
            self.db.store_dataset_entry(file_path)  # Add for fine-tuning dataset

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
            self.db.store_dataset_entry(file_path)  # Add for fine-tuning dataset

    def save_document_lists(self):
        """Save the current state of document lists to persist them."""
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
        """Load saved document lists when the application starts."""
        config_path = os.path.join(self.data_dir, "compliance_documents.json")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = json.load(f)
            for item in data.get("reference_documents", []):
                self.ref_list.addItem(item)
            for item in data.get("assessed_documents", []):
                self.assess_list.addItem(item)

    def show_ref_context_menu(self, position):
        """Show context menu for reference documents list."""
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.ref_list.mapToGlobal(position))
        if action == remove_action:
            item = self.ref_list.itemAt(position)
            if item:
                self.ref_list.takeItem(self.ref_list.row(item))
                self.save_document_lists()

    def show_assess_context_menu(self, position):
        """Show context menu for assessment documents list."""
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

        # Show progress and disable button
        self.progress_bar.show()
        self.results_text.setText("Running compliance check...")
        run_btn = self.sender()  # The button that triggered this
        run_btn.setEnabled(False)

        # Start thread
        compliance_checker = ComplianceChecker(self.chat_handler)
        self.compliance_thread = self.ComplianceThread(
            compliance_checker, ref_items, assess_items, self.session_id, self.conversation_history
        )
        self.compliance_thread.result_signal.connect(self.on_compliance_complete)
        self.compliance_thread.start()

    def on_compliance_complete(self, result):
        self.progress_bar.hide()  # Hide progress
        if result["success"]:
            data = result["data"]
            formatted_results = []
            
            # Overview (if present or from fallback)
            if 'overview' in data and data['overview'].strip():
                overview = data['overview'].strip().replace('\n', '<br>')
                formatted_results.append(f"<b>Overview:</b><br>{overview}<br><br>")
            
            # Key Alignments
            if 'key_alignments' in data and data['key_alignments'].strip():
                alignments = data['key_alignments'].strip().replace('\n', '<br>')
                formatted_results.append(f"<b>Key Alignments:</b><br>{alignments}<br><br>")
            
            # Improvements (main list, from JSON or fallback)
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
            
            # Recommendations
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
        # Placeholder: Integrate with crm.py (SQLite)
        self.results_text.append("CRM integration TBD: Save compliance issues to leads.")
        # Example: Save to crm.py with schema {lead: str, issue: str, action: str}
        # Use DatabaseManager to insert results

    def add_info_url(self):
        url = self.info_url_input.text().strip()
        if url:
            self.info_list.addItem(url)
            self.info_url_input.clear()

    def add_doc_url(self):
        url = self.doc_url_input.text().strip()
        if url:
            self.doc_list.addItem(url)
            self.doc_url_input.clear()

    def upload_info_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Information Reference File",
            "",
            "All Files (*.*)"
        )
        if file_name:
            self.info_list.addItem(file_name)

    def upload_doc_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Document Template",
            "",
            "All Files (*.*)"
        )
        if file_name:
            self.doc_list.addItem(file_name)

    def show_info_context_menu(self, position):
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.info_list.mapToGlobal(position))
        if action == remove_action:
            item = self.info_list.itemAt(position)
            if item:
                self.info_list.takeItem(self.info_list.row(item))

    def show_doc_context_menu(self, position):
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.doc_list.mapToGlobal(position))
        if action == remove_action:
            item = self.doc_list.itemAt(position)
            if item:
                self.doc_list.takeItem(self.doc_list.row(item))

    def generate_document(self):
        # Get template and context from UI
        template_text = "Document template placeholder"  # This would come from UI
        context_docs = []  # This would come from UI lists
        parameters = {}  # This would come from UI inputs
        
        # Use the DocumentGenerator class
        doc_generator = DocumentGenerator(self.chat_handler)
        result = doc_generator.generate_document(template_text, context_docs, parameters)
        
        if result["success"]:
            self.doc_output.setText(result["data"])
        else:
            self.doc_output.setText(f"Error: {result['error']}")

    def save_generated_document(self):
        if not self.doc_output.toPlainText():
            QMessageBox.warning(self, "Warning", "No document to save.")
            return

        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Save Generated Document",
            "",
            "Text Files (*.txt);;All Files (*.*)"
        )
        if file_name:
            try:
                with open(file_name, 'w') as f:
                    f.write(self.doc_output.toPlainText())
                QMessageBox.information(self, "Success", "Document saved successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save document: {str(e)}")
    def setup_shortcuts(self):
        """Set up keyboard shortcuts for common actions."""
        # Chat shortcuts
        send_action = QAction("Send Message", self)
        send_action.setShortcut("Ctrl+Return")
        send_action.triggered.connect(self.sendMessage)
        self.addAction(send_action)
        
        # Tab navigation shortcuts
        next_tab_action = QAction("Next Tab", self)
        next_tab_action.setShortcut("Ctrl+Tab")
        next_tab_action.triggered.connect(self.next_tab)
        self.addAction(next_tab_action)
        
        prev_tab_action = QAction("Previous Tab", self)
        prev_tab_action.setShortcut("Ctrl+Shift+Tab")
        prev_tab_action.triggered.connect(self.previous_tab)
        self.addAction(prev_tab_action)
        
        # Task shortcuts
        add_task_action = QAction("Add Task", self)
        add_task_action.setShortcut("Ctrl+T")
        add_task_action.triggered.connect(self.addTask)
        self.addAction(add_task_action)
        
        # Search shortcuts
        search_action = QAction("Search Leads", self)
        search_action.setShortcut("Ctrl+F")
        search_action.triggered.connect(self.focus_search)
        self.addAction(search_action)
        
        # Refresh shortcuts
        refresh_action = QAction("Refresh", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_leads)
        self.addAction(refresh_action)
        
        # Settings shortcut
        settings_action = QAction("Settings", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.open_settings)
        self.addAction(settings_action)
        
        # Help shortcut
        help_action = QAction("Help", self)
        help_action.setShortcut("F1")
        help_action.triggered.connect(self.show_help)
        self.addAction(help_action)
        
        # Exit shortcut
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        self.addAction(exit_action)
    
    def setup_status_bar(self):
        """Set up status bar with various indicators."""
        self.statusBar = self.statusBar()
        
        # Main status label
        self.status_label = QLabel("Ready")
        self.statusBar.addWidget(self.status_label)
        
        # Add spacer
        self.statusBar.addPermanentWidget(QLabel("|"))
        
        # Connection status
        self.connection_label = QLabel("ðŸŸ¢ Connected")
        self.connection_label.setStyleSheet("color: #4CAF50;")
        self.statusBar.addPermanentWidget(self.connection_label)
        
        # Add spacer
        self.statusBar.addPermanentWidget(QLabel("|"))
        
        # Task counter
        self.task_counter = QLabel("Tasks: 0")
        self.statusBar.addPermanentWidget(self.task_counter)
        
        # Add spacer
        self.statusBar.addPermanentWidget(QLabel("|"))
        
        # Leads counter
        self.leads_counter = QLabel("Leads: 0")
        self.statusBar.addPermanentWidget(self.leads_counter)
        
        # Add spacer
        self.statusBar.addPermanentWidget(QLabel("|"))
        
        # Time display
        self.time_label = QLabel()
        self.statusBar.addPermanentWidget(self.time_label)
        
        # Update time every second
        self.time_timer = QTimer()
        self.time_timer.timeout.connect(self.update_time)
        self.time_timer.start(1000)
        self.update_time()
    
    def update_time(self):
        """Update the time display in status bar."""
        current_time = datetime.now().strftime("%H:%M:%S")
        self.time_label.setText(current_time)
    
    def update_status(self, message, timeout=3000):
        """Update status bar message with optional timeout."""
        self.status_label.setText(message)
        if timeout > 0:
            QTimer.singleShot(timeout, lambda: self.status_label.setText("Ready"))
    
    def update_task_counter(self, count):
        """Update task counter in status bar."""
        self.task_counter.setText(f"Tasks: {count}")
    
    def update_leads_counter(self, count):
        """Update leads counter in status bar."""
        self.leads_counter.setText(f"Leads: {count}")
    
    def set_connection_status(self, connected):
        """Update connection status indicator."""
        if connected:
            self.connection_label.setText("ðŸŸ¢ Connected")
            self.connection_label.setStyleSheet("color: #4CAF50;")
        else:
            self.connection_label.setText("ðŸ”´ Disconnected")
            self.connection_label.setStyleSheet("color: #F44336;")

    def next_tab(self):
        """Navigate to next tab."""
        current_index = self.tabs.currentIndex()
        next_index = (current_index + 1) % self.tabs.count()
        self.tabs.setCurrentIndex(next_index)
    
    def previous_tab(self):
        """Navigate to previous tab."""
        current_index = self.tabs.currentIndex()
        prev_index = (current_index - 1) % self.tabs.count()
        self.tabs.setCurrentIndex(prev_index)
    
    def focus_search(self):
        """Focus on the search input field."""
        if hasattr(self, 'searchInput'):
            self.searchInput.setFocus()
            self.searchInput.selectAll()
    
    def show_help(self):
        """Show help dialog with keyboard shortcuts."""
        help_text = """
        <h2>Keyboard Shortcuts</h2>
        <table>
            <tr><td><b>Ctrl+Return</b></td><td>Send chat message</td></tr>
            <tr><td><b>Ctrl+Tab</b></td><td>Next tab</td></tr>
            <tr><td><b>Ctrl+Shift+Tab</b></td><td>Previous tab</td></tr>
            <tr><td><b>Ctrl+T</b></td><td>Add new task</td></tr>
            <tr><td><b>Ctrl+F</b></td><td>Focus search field</td></tr>
            <tr><td><b>F5</b></td><td>Refresh leads</td></tr>
            <tr><td><b>Ctrl+,</b></td><td>Open settings</td></tr>
            <tr><td><b>F1</b></td><td>Show this help</td></tr>
            <tr><td><b>Ctrl+Q</b></td><td>Exit application</td></tr>
        </table>
        
        <h3>Tips</h3>
        <ul>
            <li>Use Tab to navigate between form fields</li>
            <li>Press Enter to activate buttons</li>
            <li>Use arrow keys to navigate lists and tables</li>
            <li>Right-click for context menus</li>
        </ul>
        """
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Help - Keyboard Shortcuts")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(help_text)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def show_chat_context_menu(self, position):
        """Show context menu for chat input."""
        menu = QMenu(self)
        
        # Standard text editing actions
        cut_action = menu.addAction("Cut")
        cut_action.triggered.connect(lambda: self.chatInput.cut())
        
        copy_action = menu.addAction("Copy")
        copy_action.triggered.connect(lambda: self.chatInput.copy())
        
        paste_action = menu.addAction("Paste")
        paste_action.triggered.connect(lambda: self.chatInput.paste())
        
        menu.addSeparator()
        
        # Chat-specific actions
        clear_action = menu.addAction("Clear")
        clear_action.triggered.connect(lambda: self.chatInput.clear())
        
        select_all_action = menu.addAction("Select All")
        select_all_action.triggered.connect(lambda: self.chatInput.selectAll())
        
        menu.exec(self.chatInput.mapToGlobal(position))
    
    def show_button_context_menu(self, position):
        """Show context menu for send button."""
        menu = QMenu(self)
        
        # Button-specific actions
        send_action = menu.addAction("Send Message")
        send_action.triggered.connect(self.sendMessage)
        
        menu.addSeparator()
        
        # Quick message templates
        templates_menu = menu.addMenu("Quick Messages")
        
        template1 = templates_menu.addAction("Hello, how can I help you today?")
        template1.triggered.connect(lambda: self.insert_template("Hello, how can I help you today?"))
        
        template2 = templates_menu.addAction("Thank you for your inquiry.")
        template2.triggered.connect(lambda: self.insert_template("Thank you for your inquiry."))
        
        template3 = templates_menu.addAction("I'll get back to you shortly.")
        template3.triggered.connect(lambda: self.insert_template("I'll get back to you shortly."))
        
        menu.exec(self.sendButton.mapToGlobal(position))
    
    def show_chat_display_context_menu(self, position):
        """Show context menu for chat display."""
        menu = QMenu(self)
        
        # Text actions
        copy_action = menu.addAction("Copy Selected Text")
        copy_action.triggered.connect(lambda: self.chatDisplay.copy())
        
        select_all_action = menu.addAction("Select All")
        select_all_action.triggered.connect(lambda: self.chatDisplay.selectAll())
        
        menu.addSeparator()
        
        # Chat history actions
        save_chat_action = menu.addAction("Save Chat History")
        save_chat_action.triggered.connect(self.save_chat_history)
        
        clear_chat_action = menu.addAction("Clear Chat")
        clear_chat_action.triggered.connect(self.clear_chat_history)
        
        menu.addSeparator()
        
        # Export actions
        export_menu = menu.addMenu("Export")
        
        export_text_action = export_menu.addAction("Export as Text")
        export_text_action.triggered.connect(self.export_chat_as_text)
        
        export_html_action = export_menu.addAction("Export as HTML")
        export_html_action.triggered.connect(self.export_chat_as_html)
        
        menu.exec(self.chatDisplay.mapToGlobal(position))
    
    def insert_template(self, template_text):
        """Insert a template message into the chat input."""
        self.chatInput.setText(template_text)
        self.chatInput.setFocus()
        self.chatInput.selectAll()
    
    def save_chat_history(self):
        """Save current chat history to file."""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save Chat History", "", "Text Files (*.txt);;HTML Files (*.html)"
            )
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.chatDisplay.toPlainText())
                QMessageBox.information(self, "Success", "Chat history saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save chat history: {str(e)}")
    
    def clear_chat_history(self):
        """Clear the chat display."""
        reply = QMessageBox.question(
            self, "Clear Chat", "Are you sure you want to clear the chat history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.chatDisplay.clear()
    
    def export_chat_as_text(self):
        """Export chat as plain text."""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Chat as Text", "chat_export.txt", "Text Files (*.txt)"
            )
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.chatDisplay.toPlainText())
                QMessageBox.information(self, "Success", "Chat exported as text successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export chat: {str(e)}")
    
    def export_chat_as_html(self):
        """Export chat as HTML."""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Chat as HTML", "chat_export.html", "HTML Files (*.html)"
            )
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.chatDisplay.toHtml())
                QMessageBox.information(self, "Success", "Chat exported as HTML successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export chat: {str(e)}")

    def loadStylesheet(self, filename):
        try:
            with open(filename, "r") as f:
                self.setStyleSheet(f.read())
        except FileNotFoundError:
            pass
        except Exception as e:
            pass

    def closeEvent(self, event):
        super().closeEvent(event)

    def initUI(self):
        """Initialize the user interface."""
        # Load stylesheet early to ensure splash screen styling works
        self.loadStylesheet("styles.qss")
        
        # Create data directory if it doesn't exist
        self.data_dir = 'C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/data'
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Set up keyboard shortcuts
        self.setup_shortcuts()
        
        # Create status bar
        self.setup_status_bar()
        
        self.setWindowTitle('NaviSsurance')
        self.setGeometry(300, 300, 1600, 900)  # Increased window size for Compliance Tab
        
        # Center the window on the screen
        screen = QApplication.primaryScreen().geometry()
        window_size = self.geometry()
        x = (screen.width() - window_size.width()) // 2
        y = (screen.height() - window_size.height()) // 2
        self.move(x, y)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Left side - Chat Panel
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with other tabs
        chat_layout.setSpacing(0)  # No spacing to allow header to touch chat display
        
        # Add header to match tab bar height
        chat_header = QLabel("Navi Chat")
        chat_header.setStyleSheet("""
            QLabel {
                background-color: rgb(20, 20, 22);
                color: white;
                padding: 8px;
                font-size: 12px;
                font-weight: bold;
                border-bottom: 1px solid #404040;
            }
        """)
        chat_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chat_layout.addWidget(chat_header)
        
        self.chatDisplay = QTextBrowser(self)
        # self.chatDisplay.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.chatDisplay.setOpenExternalLinks(True)
        self.chatDisplay.setReadOnly(True)
        # Set document margins to 0 to remove internal spacing
        self.chatDisplay.document().setDocumentMargin(0)
        chat_layout.addWidget(self.chatDisplay)
        
        # Add spacing between chat display and input area
        chat_layout.addSpacing(5)
        
        chat_input_layout = QHBoxLayout()
        chat_input_layout.setContentsMargins(0, 0, 0, 0)  # No extra margins for input area
        chat_input_layout.setSpacing(5)  # Consistent spacing between input and button
        
        self.chatInput = QLineEdit(self)
        self.chatInput.setPlaceholderText("Type your message here...")
        self.chatInput.returnPressed.connect(self.sendMessage)
        self.chatInput.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chatInput.customContextMenuRequested.connect(self.show_chat_context_menu)
        chat_input_layout.addWidget(self.chatInput)
        
        self.sendButton = QPushButton("Send", self)
        self.sendButton.clicked.connect(self.sendMessage)
        self.sendButton.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sendButton.customContextMenuRequested.connect(self.show_button_context_menu)
        self.sendButton.setToolTip("Send your message (Ctrl+Return)")
        chat_input_layout.addWidget(self.sendButton)
        
        # Add context menu to chat display
        self.chatDisplay.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chatDisplay.customContextMenuRequested.connect(self.show_chat_display_context_menu)
        
        self.is_sending = False
        chat_layout.addLayout(chat_input_layout)
        
        # Add spacer at bottom to shrink chat content area vertically
        chat_layout.addSpacing(4)
        
        main_layout.addWidget(chat_widget, stretch=25)  # Reverted from 20 to 25

        # Right side - Tab Widget
        tabs = QTabWidget()
        # tabs.setStyleSheet("QTabBar::tab { color: white; background-color: rgb(20, 20, 22); } "
        #                   "QTabBar::tab:selected { background-color: rgba(253, 98, 98, 0.8); }")
        main_layout.addWidget(tabs, stretch=75)  # Reverted from 80 to 75

        # Tasks Tab
        tasks_tab = QWidget()
        tasks_layout = QVBoxLayout(tasks_tab)
        tasks_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        tasks_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        # self.todoList.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.todoList.setSpacing(5)  # Add consistent spacing between list items
        tasks_layout.addWidget(self.todoList)
        add_task_layout = QHBoxLayout()
        self.taskInput = QLineEdit(self)
        self.taskInput.setPlaceholderText("Enter a task...")
        # self.taskInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        add_task_layout.addWidget(self.taskInput)
        self.dueDateInput = QDateEdit(self)
        self.dueDateInput.setCalendarPopup(True)
        self.dueDateInput.setDate(QDate.currentDate())
        # self.dueDateInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        add_task_layout.addWidget(self.dueDateInput)
        self.addTaskButton = QPushButton("Add Task", self)
        self.addTaskButton.clicked.connect(self.addTask)
        self.addTaskButton.setToolTip("Add a new task to your list (Ctrl+T)")
        add_task_layout.addWidget(self.addTaskButton)
        tasks_layout.addLayout(add_task_layout)
        self.archiveButton = QPushButton("Archive Completed Tasks", self)
        self.archiveButton.clicked.connect(self.archiveCompletedTasks)
        self.archiveButton.setToolTip("Move completed tasks to archive")
        tasks_layout.addWidget(self.archiveButton)
        tabs.addTab(tasks_tab, "Tasks")

        # Leads Tab (modified)
        leads_tab = QWidget()
        leads_layout = QVBoxLayout(leads_tab)
        leads_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        leads_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        leads_button_layout = QHBoxLayout()
        self.settingsButton = QPushButton("Settings", self)
        self.settingsButton.clicked.connect(self.open_settings)
        self.settingsButton.setToolTip("Open application settings (Ctrl+,)")
        leads_button_layout.addWidget(self.settingsButton)
        self.runSearchButton = QPushButton("Run Search", self)
        self.runSearchButton.clicked.connect(self.search_leads)
        self.runSearchButton.setToolTip("Search for new leads (F5)")
        leads_button_layout.addWidget(self.runSearchButton)
        leads_layout.addLayout(leads_button_layout)
        
        # Configure the leads table
        self.leadsTable = QTableWidget(0, 8)  # Added column for rationale
        self.leadsTable.setHorizontalHeaderLabels([
            "Name", "Company", "Title", "Contacted", "Contact Date", "Message", "Delete", "Rationale"
        ])
        # self.leadsTable.setStyleSheet("""
        #     QTableWidget {
        #         background-color: rgba(27, 28, 30, 0.8);
        #         color: white;
        #         gridline-color: rgba(253, 98, 98, 0.3);
        #     }
        #     QTableWidget::item {
        #         padding: 5px;
        #     }
        #     QHeaderView::section {
        #         background-color: rgba(253, 98, 98, 0.8);
        #         color: white;
        #         padding: 5px;
        #         border: none;
        #     }
        #     QPushButton {
        #         background-color: rgba(253, 98, 98, 0.8);
        #         color: white;
        #         border: none;
        #         padding: 5px 10px;
        #     }
        #     QPushButton:hover {
        #         background-color: rgba(253, 98, 98, 1);
        #     }
        #     QCheckBox {
        #         color: white;
        #     }
        #     QTableWidget::item[linkedin="true"] {
        #         color: #0077B5;
        #         text-decoration: underline;
        #         cursor: pointer;
        #     }
        #     QTableWidget::item[linkedin="true"]:hover {
        #         color: #005582;
        #     }
        # """)
        
        # Set column widths and behavior
        self.leadsTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.leadsTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Company
        self.leadsTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Title
        self.leadsTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # Contacted
        self.leadsTable.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # Contact Date
        self.leadsTable.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)  # Message
        self.leadsTable.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)  # Delete
        self.leadsTable.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)  # Rationale
        
        self.leadsTable.setColumnWidth(3, 80)  # Contacted
        self.leadsTable.setColumnWidth(4, 100)  # Contact Date
        self.leadsTable.setColumnWidth(5, 120)  # Message
        self.leadsTable.setColumnWidth(6, 90)  # Delete - increased to prevent button overlap
        
        # Enable word wrap for cells
        self.leadsTable.setWordWrap(True)
        
        leads_layout.addWidget(self.leadsTable)
        tabs.addTab(leads_tab, "Leads")
        
        # Load existing leads
        leads_file = os.path.join(self.data_dir, 'leads.json')
        if os.path.exists(leads_file):
            try:
                with open(leads_file, 'r') as f:
                    leads = json.load(f)
                self.update_leads_table(leads)
                logger.info(f"Loaded {len(leads)} existing leads")
            except Exception as e:
                logger.error(f"Error loading leads: {e}")

        # Docs Tab
        docs_tab = QWidget()
        docs_layout = QHBoxLayout(docs_tab)
        docs_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        docs_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        docs_layout.addWidget(splitter)

        # Column 1: Information Reference
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_label = QLabel("Information Reference")
        # info_label.setStyleSheet("color: white;")
        info_layout.addWidget(info_label)

        self.info_url_input = QLineEdit()
        self.info_url_input.setPlaceholderText("Enter URL for reference information")
        # self.info_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.info_url_input.returnPressed.connect(self.add_info_url)
        info_layout.addWidget(self.info_url_input)

        info_upload_btn = QPushButton("Upload Reference")
        # info_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        info_upload_btn.clicked.connect(self.upload_info_file)
        info_layout.addWidget(info_upload_btn)

        self.info_list = QListWidget()
        # self.info_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.info_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.info_list.customContextMenuRequested.connect(self.show_info_context_menu)
        info_layout.addWidget(self.info_list)
        splitter.addWidget(info_widget)

        # Column 2: Document Reference
        doc_widget = QWidget()
        doc_layout = QVBoxLayout(doc_widget)
        doc_label = QLabel("Document Reference")
        # doc_label.setStyleSheet("color: white;")
        doc_layout.addWidget(doc_label)

        self.doc_url_input = QLineEdit()
        self.doc_url_input.setPlaceholderText("Enter URL for document template")
        # self.doc_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.doc_url_input.returnPressed.connect(self.add_doc_url)
        doc_layout.addWidget(self.doc_url_input)

        doc_upload_btn = QPushButton("Upload Document")
        # doc_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        doc_upload_btn.clicked.connect(self.upload_doc_file)
        doc_layout.addWidget(doc_upload_btn)

        self.doc_list = QListWidget()
        # self.doc_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.doc_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.doc_list.customContextMenuRequested.connect(self.show_doc_context_menu)
        doc_layout.addWidget(self.doc_list)


        # Column 3: Generated Document
        output_widget = QWidget()
        output_layout = QVBoxLayout(output_widget)
        output_label = QLabel("Generated Document")
        # output_label.setStyleSheet("color: white;")
        output_layout.addWidget(output_label)

        self.doc_output = QTextEdit()
        self.doc_output.setReadOnly(True)
        # self.doc_output.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        output_layout.addWidget(self.doc_output)

        generate_btn = QPushButton("Generate Document")
        # generate_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        generate_btn.clicked.connect(self.generate_document)
        output_layout.addWidget(generate_btn)

        save_btn = QPushButton("Save Document")
        # save_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        save_btn.clicked.connect(self.save_generated_document)
        output_layout.addWidget(save_btn)

        splitter.addWidget(output_widget)
        tabs.addTab(docs_tab, "Docs")

        # Meetings Tab (unchanged)
        meetings_tab = QWidget()
        meetings_layout = QVBoxLayout(meetings_tab)
        meetings_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        meetings_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        self.recordButton = QPushButton("Start Recording", self)
        self.recordButton.clicked.connect(self.start_recording)
        # self.recordButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        meetings_layout.addWidget(self.recordButton)
        self.stopButton = QPushButton("Stop Recording", self)
        self.stopButton.clicked.connect(self.stop_recording)
        # self.stopButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.stopButton.setEnabled(False)
        meetings_layout.addWidget(self.stopButton)
        self.transcribeButton = QPushButton("Generate Transcript", self)
        self.transcribeButton.clicked.connect(self.transcribe_meeting)
        # self.transcribeButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.transcribeButton.setEnabled(False)
        meetings_layout.addWidget(self.transcribeButton)
        self.selectFileButton = QPushButton("Load File", self)
        self.selectFileButton.clicked.connect(self.select_file)
        # self.selectFileButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        meetings_layout.addWidget(self.selectFileButton)
        self.meetingTranscript = QTextEdit(self)
        # self.meetingTranscript.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.meetingTranscript.setReadOnly(True)
        meetings_layout.addWidget(self.meetingTranscript)
        self.saveTranscriptButton = QPushButton("Save Transcript", self)
        self.saveTranscriptButton.clicked.connect(self.save_transcript)
        # self.saveTranscriptButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.saveTranscriptButton.setEnabled(False)
        meetings_layout.addWidget(self.saveTranscriptButton)
        tabs.addTab(meetings_tab, "Meetings")

        # Compliance Tab (moved to last position)
        compliance_tab = QWidget()
        self.setup_compliance_tab(compliance_tab)
        tabs.addTab(compliance_tab, "Compliance")

        # Dashboard Tab
        dashboard_tab = QWidget()
        self.setup_dashboard_tab(dashboard_tab)
        tabs.addTab(dashboard_tab, "Dashboard")

        # Workspace Tab
        workspace_tab = WorkspaceTab(self.chat_handler.chat_handler.db)
        tabs.addTab(workspace_tab, "Workspace")

        # Notes Tab
        notes_tab = NoteTakingSystem(self.chat_handler)
        tabs.addTab(notes_tab, "Notes")

    def setup_compliance_tab(self, tab):
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        layout.setSpacing(5)  # Consistent spacing with chat widget
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Column 1: Reference Documents
        ref_widget = QWidget()
        ref_layout = QVBoxLayout(ref_widget)
        ref_label = QLabel("Reference Documents (Regulations/Standards)")
        # ref_label.setStyleSheet("color: white;")
        ref_layout.addWidget(ref_label)

        self.ref_url_input = QLineEdit()
        self.ref_url_input.setPlaceholderText("Enter URL (e.g., https://www.ecfr.gov/21-cfr-820.3)")
        # self.ref_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.ref_url_input.returnPressed.connect(self.add_ref_url)
        ref_layout.addWidget(self.ref_url_input)

        ref_upload_btn = QPushButton("Upload Reference")
        # ref_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        ref_upload_btn.clicked.connect(self.upload_ref_file)
        ref_layout.addWidget(ref_upload_btn)

        self.ref_list = QListWidget()
        # self.ref_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        # Add context menu for removing items
        self.ref_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ref_list.customContextMenuRequested.connect(self.show_ref_context_menu)
        ref_layout.addWidget(self.ref_list)
        splitter.addWidget(ref_widget)

        # Column 2: Documents to Assess
        assess_widget = QWidget()
        assess_layout = QVBoxLayout(assess_widget)
        assess_label = QLabel("Documents to Assess (e.g., SOPs)")
        # assess_label.setStyleSheet("color: white;")
        assess_layout.addWidget(assess_label)

        self.assess_url_input = QLineEdit()
        self.assess_url_input.setPlaceholderText("Enter URL (e.g., https://navisure.com/sop.pdf)")
        # self.assess_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.assess_url_input.returnPressed.connect(self.add_assess_url)
        assess_layout.addWidget(self.assess_url_input)

        assess_upload_btn = QPushButton("Upload Document")
        # assess_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        assess_upload_btn.clicked.connect(self.upload_assess_file)
        assess_layout.addWidget(assess_upload_btn)

        self.assess_list = QListWidget()
        # self.assess_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        # Add context menu for removing items
        self.assess_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.assess_list.customContextMenuRequested.connect(self.show_assess_context_menu)
        assess_layout.addWidget(self.assess_list)
        splitter.addWidget(assess_widget)

        # Column 3: Results
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_label = QLabel("Compliance Results")
        # results_label.setStyleSheet("color: white;")
        results_layout.addWidget(results_label)

        self.results_text = QTextEdit()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate mode (spinning)
        self.progress_bar.hide()  # Hidden initially
        results_layout.addWidget(self.progress_bar)
        self.results_text.setReadOnly(True)
        # self.results_text.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        results_layout.addWidget(self.results_text)

        run_btn = QPushButton("Run Compliance Check")
        # run_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        run_btn.clicked.connect(self.run_compliance_check)
        results_layout.addWidget(run_btn)

        save_btn = QPushButton("Save Report")
        # save_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        save_btn.clicked.connect(self.save_compliance_report)
        results_layout.addWidget(save_btn)

        clear_dataset_btn = QPushButton("Clear Dataset")
        # clear_dataset_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        clear_dataset_btn.clicked.connect(self.clear_dataset)
        results_layout.addWidget(clear_dataset_btn)
        
        crm_btn = QPushButton("Link to CRM")
        # crm_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        crm_btn.clicked.connect(self.link_to_crm)
        results_layout.addWidget(crm_btn)
        splitter.addWidget(results_widget)

        # Load existing documents
        self.load_document_lists()
    def setup_dashboard_tab(self, tab):
        """Setup the dashboard tab with new layout: news feed on right, schedule middle top, task list middle bottom."""
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Header - styled as a label, not a button
        dashboard_header = QLabel("Dashboard - Overview")
        dashboard_header.setStyleSheet("color: white; font-weight: bold; font-size: 16px; padding: 10px; background-color: transparent; border: none;")
        dashboard_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(dashboard_header)
        
        # Create main horizontal layout for left and right columns
        main_layout = QHBoxLayout()
        main_layout.setSpacing(10)
        
        # Left column: Schedule and Task List
        left_column = QVBoxLayout()
        left_column.setSpacing(10)
        
        # Top: Schedule
        schedule_widget = self.create_dashboard_schedule_widget()
        left_column.addWidget(schedule_widget)
        
        # Bottom: Task List
        task_widget = self.create_dashboard_task_widget()
        left_column.addWidget(task_widget)
        
        # Right column: News Feed (mirrors chat window style)
        news_widget = self.create_dashboard_news_widget()
        
        # Add columns to main layout
        main_layout.addLayout(left_column, 2)  # Left column takes 2/3 of space
        main_layout.addWidget(news_widget, 1)  # Right column takes 1/3 of space
        
        layout.addLayout(main_layout)
        
        # Add refresh button at bottom
        refresh_layout = QHBoxLayout()
        refresh_layout.addStretch()
        
        refresh_news_btn = QPushButton("Refresh News")
        refresh_news_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 8px 15px; border-radius: 3px;")
        refresh_news_btn.clicked.connect(self.refresh_news_feed)
        refresh_layout.addWidget(refresh_news_btn)
        
        layout.addLayout(refresh_layout)
        
        # Setup auto-refresh timer for schedule (every 15 minutes)
        self.schedule_timer = QTimer()
        self.schedule_timer.timeout.connect(self.load_dashboard_schedule)
        self.schedule_timer.start(900000)  # 15 minutes in milliseconds
    

    
    def create_dashboard_task_widget(self):
        """Create the task list widget for the dashboard."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header - styled as a label, not a button
        task_header = QLabel("Task List")
        task_header.setStyleSheet("color: white; font-weight: bold; padding: 3px; background-color: transparent; border: none; font-size: 11px;")
        task_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        task_header.setMaximumHeight(25)
        layout.addWidget(task_header)
        
        # Task list - use proper TodoList integration with better text handling
        self.dashboard_task_list = QListWidget()
        self.dashboard_task_list.setStyleSheet("""
            QListWidget {
                background-color: rgba(27, 28, 30, 0.8); 
                color: white; 
                border: 1px solid rgba(253, 98, 98, 0.3); 
                border-radius: 3px;
                font-size: 10px;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid rgba(253, 98, 98, 0.2);
                min-height: 20px;
            }
            QListWidget::item:selected {
                background-color: rgba(253, 98, 98, 0.3);
            }
        """)
        self.dashboard_task_list.setWordWrap(True)  # Enable word wrapping
        self.dashboard_task_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.dashboard_task_list.itemDoubleClicked.connect(self.on_task_double_clicked)
        layout.addWidget(self.dashboard_task_list)
        
        # Quick add task
        add_layout = QHBoxLayout()
        self.dashboard_task_input = QLineEdit()
        self.dashboard_task_input.setPlaceholderText("Quick task...")
        self.dashboard_task_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.5); padding: 3px; border-radius: 3px;")
        self.dashboard_task_input.returnPressed.connect(self.add_dashboard_task)
        add_layout.addWidget(self.dashboard_task_input)
        
        add_btn = QPushButton("Add")
        add_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 3px 8px; border-radius: 3px;")
        add_btn.clicked.connect(self.add_dashboard_task)
        add_layout.addWidget(add_btn)
        
        layout.addLayout(add_layout)
        
        # Load recent tasks
        self.load_dashboard_tasks()
        
        return widget
    
    def create_dashboard_schedule_widget(self):
        """Create the schedule widget for the dashboard."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header - styled as a label, not a button
        schedule_header = QLabel("Today's Schedule")
        schedule_header.setStyleSheet("color: white; font-weight: bold; padding: 3px; background-color: transparent; border: none; font-size: 11px;")
        schedule_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        schedule_header.setMaximumHeight(25)
        layout.addWidget(schedule_header)
        
        # Schedule display - no height restriction
        self.dashboard_schedule_display = QTextBrowser()
        self.dashboard_schedule_display.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px;")
        self.dashboard_schedule_display.setReadOnly(True)
        self.dashboard_schedule_display.setPlaceholderText("Loading schedule...")
        layout.addWidget(self.dashboard_schedule_display)
        
        # Load initial schedule
        self.load_dashboard_schedule()
        
        return widget
    
    def create_dashboard_news_widget(self):
        """Create the news feed widget for the dashboard - styled like a chat window."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header - styled as a label, not a button
        news_header = QLabel("News Feed")
        news_header.setStyleSheet("color: white; font-weight: bold; padding: 3px; background-color: transparent; border: none; font-size: 11px;")
        news_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        news_header.setMaximumHeight(25)
        layout.addWidget(news_header)
        
        # News display - no height restriction, show full content
        self.dashboard_news_display = QTextBrowser()
        self.dashboard_news_display.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px; font-size: 10px;")
        self.dashboard_news_display.setReadOnly(True)
        self.dashboard_news_display.setPlaceholderText("Loading news...")
        self.dashboard_news_display.setOpenExternalLinks(True)  # Enable hyperlink clicking
        layout.addWidget(self.dashboard_news_display)
        
        # Auto-refresh timer (every hour)
        self.news_timer = QTimer()
        self.news_timer.timeout.connect(self.refresh_news_feed)
        self.news_timer.start(3600000)  # 1 hour in milliseconds
        
        # Load initial news
        self.load_dashboard_news()
        
        # Setup news cleanup timer (clean up old news every 24 hours)
        self.news_cleanup_timer = QTimer()
        self.news_cleanup_timer.timeout.connect(self.cleanup_old_news)
        self.news_cleanup_timer.start(86400000)  # 24 hours in milliseconds
        
        return widget
    

    
    def add_dashboard_task(self):
        """Add a quick task from the dashboard using proper TodoList integration."""
        task_text = self.dashboard_task_input.text().strip()
        if not task_text:
            return
        
        # Add to main task list using TodoList
        if hasattr(self, 'todo_list'):
            self.todo_list.addTaskFromChat(task_text, datetime.now().strftime('%Y-%m-%d'))
            # Refresh dashboard display
            self.load_dashboard_tasks()
        
        # Clear input
        self.dashboard_task_input.clear()
    
    def load_dashboard_tasks(self):
        """Load recent tasks for the dashboard using proper TodoList integration."""
        try:
            # Use the same database connection and method as main TodoList
            if hasattr(self, 'todo_list'):
                # Clear current display
                self.dashboard_task_list.clear()
                
                # Get tasks from database using TodoList's method
                with sqlite3.connect(self.chat_handler.chat_handler.db.db_name) as conn:
                    cursor = conn.execute("""
                        SELECT task, due_date FROM tasks 
                        WHERE completed = 0 
                        ORDER BY created_at DESC 
                        LIMIT 10
                    """)
                    tasks = cursor.fetchall()
                
                # Display tasks in a simple, clean format
                for task, due_date in tasks:
                    # Create a simple text item with checkbox
                    item_text = f"â˜ {task}"
                    if due_date:
                        item_text += f" (Due: {due_date})"
                    
                    item = QListWidgetItem(item_text)
                    item.setData(Qt.ItemDataRole.UserRole, task)  # Store original task text
                    self.dashboard_task_list.addItem(item)
                    
        except Exception as e:
            self.dashboard_task_list.addItem(f"Error loading tasks: {str(e)}")
    
    def update_dashboard_task_status(self, task_text, completed):
        """Update task status in database when checkbox is clicked."""
        try:
            if hasattr(self, 'todo_list'):
                # Use TodoList's method to update task status
                with sqlite3.connect(self.chat_handler.chat_handler.db.db_name) as conn:
                    conn.execute("""
                        UPDATE tasks SET completed = ? WHERE task = ?
                    """, (1 if completed else 0, task_text))
                    conn.commit()
                
                # Refresh display
                self.load_dashboard_tasks()
        except Exception as e:
            print(f"Error updating task status: {e}")
    
    def load_dashboard_schedule(self):
        """Load today's schedule for the dashboard."""
        try:
            # Get today's events from data fetcher
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow = today + timedelta(days=1)
            time_min = today.strftime('%Y-%m-%dT%H:%M:%SZ')
            time_max = tomorrow.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            events = self.chat_handler.chat_handler.data_fetcher.get_calendar_events(time_min, time_max)
            
            if events:
                schedule_text = "Today's Events:\n\n"
                for event in events[:5]:  # Limit to 5 events
                    start_time = event['start'].get('dateTime', event['start'].get('date'))
                    summary = event.get('summary', 'No title')
                    schedule_text += f"- {start_time}: {summary}\n"
            else:
                schedule_text = "No events scheduled for today"
            
            self.dashboard_schedule_display.setPlainText(schedule_text)
            
        except Exception as e:
            self.dashboard_schedule_display.setPlainText(f"Error loading schedule: {str(e)}")
    
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
            self.dashboard_news_display.setPlainText(f"Error loading news: {str(e)}")
    
    def process_and_store_news(self, news_results):
        """Process news results and store them in the database, avoiding duplicates."""
        try:
            # Split news results into individual items (assuming they're separated by newlines or other delimiters)
            # This is a simplified approach - in practice, you might want more sophisticated parsing
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
                news_text = "<div style='color: white; font-family: Arial, sans-serif;'>"
                news_text += "<h3 style='color: #fd6262; margin-bottom: 15px;'>Latest News</h3>"
                
                for title, content, url, source, published_date, created_at in recent_news:
                    news_text += "<div style='margin-bottom: 20px; padding: 10px; background-color: rgba(253, 98, 98, 0.1); border-radius: 5px;'>"
                    news_text += f"<h4 style='color: #fd6262; margin: 0 0 8px 0;'>{title}</h4>"
                    if content:
                        news_text += f"<p style='margin: 0 0 8px 0; line-height: 1.4;'>{content}</p>"
                    if url:
                        news_text += f'<p style="margin: 0 0 5px 0;"><a href="{url}" style="color: #4fc3f7; text-decoration: underline;">🔗 Read full article</a></p>'
                    if published_date:
                        news_text += f"<small style='color: #888;'>Published: {published_date}</small>"
                    news_text += "</div>"
                
                news_text += "</div>"
                
                # Set HTML content to enable hyperlinks
                self.dashboard_news_display.setHtml(news_text)
            else:
                self.dashboard_news_display.setPlainText("No recent news available. Check back later.")
                
        except Exception as e:
            self.dashboard_news_display.setPlainText(f"Error displaying news: {str(e)}")
    
    def refresh_schedule(self):
        """Refresh the schedule display."""
        self.load_dashboard_schedule()
    
    def refresh_news_feed(self):
        """Refresh the news feed."""
        self.load_dashboard_news()
    
    def cleanup_old_news(self):
        """Clean up old news items from the database."""
        try:
            if hasattr(self, 'db'):
                self.db.cleanup_old_news(days=7)
        except Exception as e:
            print(f"Error cleaning up old news: {e}")

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
            self.db.store_dataset_entry(file_path)  # Add for fine-tuning dataset

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
            self.db.store_dataset_entry(file_path)  # Add for fine-tuning dataset

    def save_document_lists(self):
        """Save the current state of document lists to persist them."""
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
        """Load saved document lists when the application starts."""
        config_path = os.path.join(self.data_dir, "compliance_documents.json")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = json.load(f)
            for item in data.get("reference_documents", []):
                self.ref_list.addItem(item)
            for item in data.get("assessed_documents", []):
                self.assess_list.addItem(item)

    def show_ref_context_menu(self, position):
        """Show context menu for reference documents list."""
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.ref_list.mapToGlobal(position))
        if action == remove_action:
            item = self.ref_list.itemAt(position)
            if item:
                self.ref_list.takeItem(self.ref_list.row(item))
                self.save_document_lists()

    def show_assess_context_menu(self, position):
        """Show context menu for assessment documents list."""
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

        # Show progress and disable button
        self.progress_bar.show()
        self.results_text.setText("Running compliance check...")
        run_btn = self.sender()  # The button that triggered this
        run_btn.setEnabled(False)

        # Start thread
        compliance_checker = ComplianceChecker(self.chat_handler)
        self.compliance_thread = self.ComplianceThread(
            compliance_checker, ref_items, assess_items, self.session_id, self.conversation_history
        )
        self.compliance_thread.result_signal.connect(self.on_compliance_complete)
        self.compliance_thread.start()

    def on_compliance_complete(self, result):
        self.progress_bar.hide()  # Hide progress
        if result["success"]:
            data = result["data"]
            formatted_results = []
            
            # Overview (if present or from fallback)
            if 'overview' in data and data['overview'].strip():
                overview = data['overview'].strip().replace('\n', '<br>')
                formatted_results.append(f"<b>Overview:</b><br>{overview}<br><br>")
            
            # Key Alignments
            if 'key_alignments' in data and data['key_alignments'].strip():
                alignments = data['key_alignments'].strip().replace('\n', '<br>')
                formatted_results.append(f"<b>Key Alignments:</b><br>{alignments}<br><br>")
            
            # Improvements (main list, from JSON or fallback)
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
            
            # Recommendations
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
        # Placeholder: Integrate with crm.py (SQLite)
        self.results_text.append("CRM integration TBD: Save compliance issues to leads.")
        # Example: Save to crm.py with schema {lead: str, issue: str, action: str}
        # Use DatabaseManager to insert results

    def add_info_url(self):
        url = self.info_url_input.text().strip()
        if url:
            self.info_list.addItem(url)
            self.info_url_input.clear()

    def add_doc_url(self):
        url = self.doc_url_input.text().strip()
        if url:
            self.doc_list.addItem(url)
            self.doc_url_input.clear()

    def upload_info_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Information Reference File",
            "",
            "All Files (*.*)"
        )
        if file_name:
            self.info_list.addItem(file_name)

    def upload_doc_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Document Template",
            "",
            "All Files (*.*)"
        )
        if file_name:
            self.doc_list.addItem(file_name)

    def show_info_context_menu(self, position):
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.info_list.mapToGlobal(position))
        if action == remove_action:
            item = self.info_list.itemAt(position)
            if item:
                self.info_list.takeItem(self.info_list.row(item))

    def show_doc_context_menu(self, position):
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.doc_list.mapToGlobal(position))
        if action == remove_action:
            item = self.doc_list.itemAt(position)
            if item:
                self.doc_list.takeItem(self.doc_list.row(item))

    def generate_document(self):
        # Get template and context from UI
        template_text = "Document template placeholder"  # This would come from UI
        context_docs = []  # This would come from UI lists
        parameters = {}  # This would come from UI inputs
        
        # Use the DocumentGenerator class
        doc_generator = DocumentGenerator(self.chat_handler)
        result = doc_generator.generate_document(template_text, context_docs, parameters)
        
        if result["success"]:
            self.doc_output.setText(result["data"])
        else:
            self.doc_output.setText(f"Error: {result['error']}")

    def save_generated_document(self):
        if not self.doc_output.toPlainText():
            QMessageBox.warning(self, "Warning", "No document to save.")
            return

        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Save Generated Document",
            "",
            "Text Files (*.txt);;All Files (*.*)"
        )
        if file_name:
            try:
                with open(file_name, 'w') as f:
                    f.write(self.doc_output.toPlainText())
                QMessageBox.information(self, "Success", "Document saved successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save document: {str(e)}")

    def setup_shortcuts(self):
        """Set up keyboard shortcuts for common actions."""
        # Chat shortcuts
        send_action = QAction("Send Message", self)
        send_action.setShortcut("Ctrl+Return")
        send_action.triggered.connect(self.sendMessage)
        self.addAction(send_action)
        
        # Tab navigation shortcuts
        next_tab_action = QAction("Next Tab", self)
        next_tab_action.setShortcut("Ctrl+Tab")
        next_tab_action.triggered.connect(self.next_tab)
        self.addAction(next_tab_action)
        
        prev_tab_action = QAction("Previous Tab", self)
        prev_tab_action.setShortcut("Ctrl+Shift+Tab")
        prev_tab_action.triggered.connect(self.previous_tab)
        self.addAction(prev_tab_action)
        
        # Task shortcuts
        add_task_action = QAction("Add Task", self)
        add_task_action.setShortcut("Ctrl+T")
        add_task_action.triggered.connect(self.addTask)
        self.addAction(add_task_action)
        
        # Search shortcuts
        search_action = QAction("Search Leads", self)
        search_action.setShortcut("Ctrl+F")
        search_action.triggered.connect(self.focus_search)
        self.addAction(search_action)
        
        # Refresh shortcuts
        refresh_action = QAction("Refresh", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_leads)
        self.addAction(refresh_action)
        
        # Settings shortcut
        settings_action = QAction("Settings", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.open_settings)
        self.addAction(settings_action)
        
        # Help shortcut
        help_action = QAction("Help", self)
        help_action.setShortcut("F1")
        help_action.triggered.connect(self.show_help)
        self.addAction(help_action)
        
        # Exit shortcut
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        self.addAction(exit_action)
    
    def setup_status_bar(self):
        """Set up status bar with various indicators."""
        self.statusBar = self.statusBar()
        
        # Main status label
        self.status_label = QLabel("Ready")
        self.statusBar.addWidget(self.status_label)
        
        # Add spacer
        self.statusBar.addPermanentWidget(QLabel("|"))
        
        # Connection status
        self.connection_label = QLabel("ðŸŸ¢ Connected")
        self.connection_label.setStyleSheet("color: #4CAF50;")
        self.statusBar.addPermanentWidget(self.connection_label)
        
        # Add spacer
        self.statusBar.addPermanentWidget(QLabel("|"))
        
        # Task counter
        self.task_counter = QLabel("Tasks: 0")
        self.statusBar.addPermanentWidget(self.task_counter)
        
        # Add spacer
        self.statusBar.addPermanentWidget(QLabel("|"))
        
        # Leads counter
        self.leads_counter = QLabel("Leads: 0")
        self.statusBar.addPermanentWidget(self.leads_counter)
        
        # Add spacer
        self.statusBar.addPermanentWidget(QLabel("|"))
        
        # Time display
        self.time_label = QLabel()
        self.statusBar.addPermanentWidget(self.time_label)
        
        # Update time every second
        self.time_timer = QTimer()
        self.time_timer.timeout.connect(self.update_time)
        self.time_timer.start(1000)
        self.update_time()
    
    def update_time(self):
        """Update the time display in status bar."""
        current_time = datetime.now().strftime("%H:%M:%S")
        self.time_label.setText(current_time)
    
    def update_status(self, message, timeout=3000):
        """Update status bar message with optional timeout."""
        self.status_label.setText(message)
        if timeout > 0:
            QTimer.singleShot(timeout, lambda: self.status_label.setText("Ready"))
    
    def update_task_counter(self, count):
        """Update task counter in status bar."""
        self.task_counter.setText(f"Tasks: {count}")
    
    def update_leads_counter(self, count):
        """Update leads counter in status bar."""
        self.leads_counter.setText(f"Leads: {count}")
    
    def set_connection_status(self, connected):
        """Update connection status indicator."""
        if connected:
            self.connection_label.setText("ðŸŸ¢ Connected")
            self.connection_label.setStyleSheet("color: #4CAF50;")
        else:
            self.connection_label.setText("ðŸ”´ Disconnected")
            self.connection_label.setStyleSheet("color: #F44336;")

    def next_tab(self):
        """Navigate to next tab."""
        current_index = self.tabs.currentIndex()
        next_index = (current_index + 1) % self.tabs.count()
        self.tabs.setCurrentIndex(next_index)
    
    def previous_tab(self):
        """Navigate to previous tab."""
        current_index = self.tabs.currentIndex()
        prev_index = (current_index - 1) % self.tabs.count()
        self.tabs.setCurrentIndex(prev_index)
    
    def focus_search(self):
        """Focus on the search input field."""
        if hasattr(self, 'searchInput'):
            self.searchInput.setFocus()
            self.searchInput.selectAll()
    def show_help(self):
        """Show help dialog with keyboard shortcuts."""
        help_text = """
        <h2>Keyboard Shortcuts</h2>
        <table>
            <tr><td><b>Ctrl+Return</b></td><td>Send chat message</td></tr>
            <tr><td><b>Ctrl+Tab</b></td><td>Next tab</td></tr>
            <tr><td><b>Ctrl+Shift+Tab</b></td><td>Previous tab</td></tr>
            <tr><td><b>Ctrl+T</b></td><td>Add new task</td></tr>
            <tr><td><b>Ctrl+F</b></td><td>Focus search field</td></tr>
            <tr><td><b>F5</b></td><td>Refresh leads</td></tr>
            <tr><td><b>Ctrl+,</b></td><td>Open settings</td></tr>
            <tr><td><b>F1</b></td><td>Show this help</td></tr>
            <tr><td><b>Ctrl+Q</b></td><td>Exit application</td></tr>
        </table>
        
        <h3>Tips</h3>
        <ul>
            <li>Use Tab to navigate between form fields</li>
            <li>Press Enter to activate buttons</li>
            <li>Use arrow keys to navigate lists and tables</li>
            <li>Right-click for context menus</li>
        </ul>
        """
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Help - Keyboard Shortcuts")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(help_text)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def show_chat_context_menu(self, position):
        """Show context menu for chat input."""
        menu = QMenu(self)
        
        # Standard text editing actions
        cut_action = menu.addAction("Cut")
        cut_action.triggered.connect(lambda: self.chatInput.cut())
        
        copy_action = menu.addAction("Copy")
        copy_action.triggered.connect(lambda: self.chatInput.copy())
        
        paste_action = menu.addAction("Paste")
        paste_action.triggered.connect(lambda: self.chatInput.paste())
        
        menu.addSeparator()
        
        # Chat-specific actions
        clear_action = menu.addAction("Clear")
        clear_action.triggered.connect(lambda: self.chatInput.clear())
        
        select_all_action = menu.addAction("Select All")
        select_all_action.triggered.connect(lambda: self.chatInput.selectAll())
        
        menu.exec(self.chatInput.mapToGlobal(position))
    
    def show_button_context_menu(self, position):
        """Show context menu for send button."""
        menu = QMenu(self)
        
        # Button-specific actions
        send_action = menu.addAction("Send Message")
        send_action.triggered.connect(self.sendMessage)
        
        menu.addSeparator()
        
        # Quick message templates
        templates_menu = menu.addMenu("Quick Messages")
        
        template1 = templates_menu.addAction("Hello, how can I help you today?")
        template1.triggered.connect(lambda: self.insert_template("Hello, how can I help you today?"))
        
        template2 = templates_menu.addAction("Thank you for your inquiry.")
        template2.triggered.connect(lambda: self.insert_template("Thank you for your inquiry."))
        
        template3 = templates_menu.addAction("I'll get back to you shortly.")
        template3.triggered.connect(lambda: self.insert_template("I'll get back to you shortly."))
        
        menu.exec(self.sendButton.mapToGlobal(position))
    
    def show_chat_display_context_menu(self, position):
        """Show context menu for chat display."""
        menu = QMenu(self)
        
        # Text actions
        copy_action = menu.addAction("Copy Selected Text")
        copy_action.triggered.connect(lambda: self.chatDisplay.copy())
        
        select_all_action = menu.addAction("Select All")
        select_all_action.triggered.connect(lambda: self.chatDisplay.selectAll())
        
        menu.addSeparator()
        
        # Chat history actions
        save_chat_action = menu.addAction("Save Chat History")
        save_chat_action.triggered.connect(self.save_chat_history)
        
        clear_chat_action = menu.addAction("Clear Chat")
        clear_chat_action.triggered.connect(self.clear_chat_history)
        
        menu.addSeparator()
        
        # Export actions
        export_menu = menu.addMenu("Export")
        
        export_text_action = export_menu.addAction("Export as Text")
        export_text_action.triggered.connect(self.export_chat_as_text)
        
        export_html_action = export_menu.addAction("Export as HTML")
        export_html_action.triggered.connect(self.export_chat_as_html)
        
        menu.exec(self.chatDisplay.mapToGlobal(position))
    
    def insert_template(self, template_text):
        """Insert a template message into the chat input."""
        self.chatInput.setText(template_text)
        self.chatInput.setFocus()
        self.chatInput.selectAll()
    
    def save_chat_history(self):
        """Save current chat history to file."""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save Chat History", "", "Text Files (*.txt);;HTML Files (*.html)"
            )
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.chatDisplay.toPlainText())
                QMessageBox.information(self, "Success", "Chat history saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save chat history: {str(e)}")
    
    def clear_chat_history(self):
        """Clear the chat display."""
        reply = QMessageBox.question(
            self, "Clear Chat", "Are you sure you want to clear the chat history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.chatDisplay.clear()
    
    def export_chat_as_text(self):
        """Export chat as plain text."""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Chat as Text", "chat_export.txt", "Text Files (*.txt)"
            )
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.chatDisplay.toPlainText())
                QMessageBox.information(self, "Success", "Chat exported as text successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export chat: {str(e)}")
    
    def export_chat_as_html(self):
        """Export chat as HTML."""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Chat as HTML", "chat_export.html", "HTML Files (*.html)"
            )
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.chatDisplay.toHtml())
                QMessageBox.information(self, "Success", "Chat exported as HTML successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export chat: {str(e)}")

    def loadStylesheet(self, filename):
        try:
            with open(filename, "r") as f:
                self.setStyleSheet(f.read())
        except FileNotFoundError:
            pass
        except Exception as e:
            pass

    def closeEvent(self, event):
        super().closeEvent(event)

    def initUI(self):
        """Initialize the user interface."""
        # Load stylesheet early to ensure splash screen styling works
        self.loadStylesheet("styles.qss")
        
        # Create data directory if it doesn't exist
        self.data_dir = 'C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/data'
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Set up keyboard shortcuts
        self.setup_shortcuts()
        
        # Create status bar
        self.setup_status_bar()
        
        self.setWindowTitle('NaviSsurance')
        self.setGeometry(300, 300, 1600, 900)  # Increased window size for Compliance Tab
        
        # Center the window on the screen
        screen = QApplication.primaryScreen().geometry()
        window_size = self.geometry()
        x = (screen.width() - window_size.width()) // 2
        y = (screen.height() - window_size.height()) // 2
        self.move(x, y)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Left side - Chat Panel
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with other tabs
        chat_layout.setSpacing(0)  # No spacing to allow header to touch chat display
        
        # Add header to match tab bar height
        chat_header = QLabel("Navi Chat")
        chat_header.setStyleSheet("""
            QLabel {
                background-color: rgb(20, 20, 22);
                color: white;
                padding: 8px;
                font-size: 12px;
                font-weight: bold;
                border-bottom: 1px solid #404040;
            }
        """)
        chat_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chat_layout.addWidget(chat_header)
        
        self.chatDisplay = QTextBrowser(self)
        # self.chatDisplay.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.chatDisplay.setOpenExternalLinks(True)
        self.chatDisplay.setReadOnly(True)
        # Set document margins to 0 to remove internal spacing
        self.chatDisplay.document().setDocumentMargin(0)
        chat_layout.addWidget(self.chatDisplay)
        
        # Add spacing between chat display and input area
        chat_layout.addSpacing(5)
        
        chat_input_layout = QHBoxLayout()
        chat_input_layout.setContentsMargins(0, 0, 0, 0)  # No extra margins for input area
        chat_input_layout.setSpacing(5)  # Consistent spacing between input and button
        
        self.chatInput = QLineEdit(self)
        self.chatInput.setPlaceholderText("Type your message here...")
        self.chatInput.returnPressed.connect(self.sendMessage)
        self.chatInput.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chatInput.customContextMenuRequested.connect(self.show_chat_context_menu)
        chat_input_layout.addWidget(self.chatInput)
        
        self.sendButton = QPushButton("Send", self)
        self.sendButton.clicked.connect(self.sendMessage)
        self.sendButton.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sendButton.customContextMenuRequested.connect(self.show_button_context_menu)
        self.sendButton.setToolTip("Send your message (Ctrl+Return)")
        chat_input_layout.addWidget(self.sendButton)
        
        # Add context menu to chat display
        self.chatDisplay.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chatDisplay.customContextMenuRequested.connect(self.show_chat_display_context_menu)
        
        self.is_sending = False
        chat_layout.addLayout(chat_input_layout)
        
        # Add spacer at bottom to shrink chat content area vertically
        chat_layout.addSpacing(4)
        
        main_layout.addWidget(chat_widget, stretch=25)  # Reverted from 20 to 25

        # Right side - Tab Widget
        tabs = QTabWidget()
        # tabs.setStyleSheet("QTabBar::tab { color: white; background-color: rgb(20, 20, 22); } "
        #                   "QTabBar::tab:selected { background-color: rgba(253, 98, 98, 0.8); }")
        main_layout.addWidget(tabs, stretch=75)  # Reverted from 80 to 75

        # Tasks Tab
        tasks_tab = QWidget()
        tasks_layout = QVBoxLayout(tasks_tab)
        tasks_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        tasks_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        # self.todoList.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.todoList.setSpacing(5)  # Add consistent spacing between list items
        tasks_layout.addWidget(self.todoList)
        add_task_layout = QHBoxLayout()
        self.taskInput = QLineEdit(self)
        self.taskInput.setPlaceholderText("Enter a task...")
        # self.taskInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        add_task_layout.addWidget(self.taskInput)
        self.dueDateInput = QDateEdit(self)
        self.dueDateInput.setCalendarPopup(True)
        self.dueDateInput.setDate(QDate.currentDate())
        # self.dueDateInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        add_task_layout.addWidget(self.dueDateInput)
        self.addTaskButton = QPushButton("Add Task", self)
        self.addTaskButton.clicked.connect(self.addTask)
        self.addTaskButton.setToolTip("Add a new task to your list (Ctrl+T)")
        add_task_layout.addWidget(self.addTaskButton)
        tasks_layout.addLayout(add_task_layout)
        self.archiveButton = QPushButton("Archive Completed Tasks", self)
        self.archiveButton.clicked.connect(self.archiveCompletedTasks)
        self.archiveButton.setToolTip("Move completed tasks to archive")
        tasks_layout.addWidget(self.archiveButton)
        tabs.addTab(tasks_tab, "Tasks")

        # Leads Tab (modified)
        leads_tab = QWidget()
        leads_layout = QVBoxLayout(leads_tab)
        leads_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        leads_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        leads_button_layout = QHBoxLayout()
        self.settingsButton = QPushButton("Settings", self)
        self.settingsButton.clicked.connect(self.open_settings)
        self.settingsButton.setToolTip("Open application settings (Ctrl+,)")
        leads_button_layout.addWidget(self.settingsButton)
        self.runSearchButton = QPushButton("Run Search", self)
        self.runSearchButton.clicked.connect(self.search_leads)
        self.runSearchButton.setToolTip("Search for new leads (F5)")
        leads_button_layout.addWidget(self.runSearchButton)
        leads_layout.addLayout(leads_button_layout)
        
        # Configure the leads table
        self.leadsTable = QTableWidget(0, 8)  # Added column for rationale
        self.leadsTable.setHorizontalHeaderLabels([
            "Name", "Company", "Title", "Contacted", "Contact Date", "Message", "Delete", "Rationale"
        ])
        # self.leadsTable.setStyleSheet("""
        #     QTableWidget {
        #         background-color: rgba(27, 28, 30, 0.8);
        #         color: white;
        #         gridline-color: rgba(253, 98, 98, 0.3);
        #     }
        #     QTableWidget::item {
        #         padding: 5px;
        #     }
        #     QHeaderView::section {
        #         background-color: rgba(253, 98, 98, 0.8);
        #         color: white;
        #         padding: 5px;
        #         border: none;
        #     }
        #     QPushButton {
        #         background-color: rgba(253, 98, 98, 0.8);
        #         color: white;
        #         border: none;
        #         padding: 5px 10px;
        #     }
        #     QPushButton:hover {
        #         background-color: rgba(253, 98, 98, 1);
        #     }
        #     QCheckBox {
        #         color: white;
        #     }
        #     QTableWidget::item[linkedin="true"] {
        #         color: #0077B5;
        #         text-decoration: underline;
        #         cursor: pointer;
        #     }
        #     QTableWidget::item[linkedin="true"]:hover {
        #         color: #005582;
        #     }
        # """)
        
        # Set column widths and behavior
        self.leadsTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.leadsTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Company
        self.leadsTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Title
        self.leadsTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # Contacted
        self.leadsTable.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # Contact Date
        self.leadsTable.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)  # Message
        self.leadsTable.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)  # Delete
        self.leadsTable.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)  # Rationale
        
        self.leadsTable.setColumnWidth(3, 80)  # Contacted
        self.leadsTable.setColumnWidth(4, 100)  # Contact Date
        self.leadsTable.setColumnWidth(5, 120)  # Message
        self.leadsTable.setColumnWidth(6, 90)  # Delete - increased to prevent button overlap
        
        # Enable word wrap for cells
        self.leadsTable.setWordWrap(True)
        
        leads_layout.addWidget(self.leadsTable)
        tabs.addTab(leads_tab, "Leads")
        
        # Load existing leads
        leads_file = os.path.join(self.data_dir, 'leads.json')
        if os.path.exists(leads_file):
            try:
                with open(leads_file, 'r') as f:
                    leads = json.load(f)
                self.update_leads_table(leads)
                logger.info(f"Loaded {len(leads)} existing leads")
            except Exception as e:
                logger.error(f"Error loading leads: {e}")

        # Docs Tab
        docs_tab = QWidget()
        docs_layout = QHBoxLayout(docs_tab)
        docs_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        docs_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        docs_layout.addWidget(splitter)

        # Column 1: Information Reference
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_label = QLabel("Information Reference")
        # info_label.setStyleSheet("color: white;")
        info_layout.addWidget(info_label)

        self.info_url_input = QLineEdit()
        self.info_url_input.setPlaceholderText("Enter URL for reference information")
        # self.info_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.info_url_input.returnPressed.connect(self.add_info_url)
        info_layout.addWidget(self.info_url_input)

        info_upload_btn = QPushButton("Upload Reference")
        # info_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        info_upload_btn.clicked.connect(self.upload_info_file)
        info_layout.addWidget(info_upload_btn)

        self.info_list = QListWidget()
        # self.info_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.info_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.info_list.customContextMenuRequested.connect(self.show_info_context_menu)
        info_layout.addWidget(self.info_list)
        splitter.addWidget(info_widget)

        # Column 2: Document Reference
        doc_widget = QWidget()
        doc_layout = QVBoxLayout(doc_widget)
        doc_label = QLabel("Document Reference")
        # doc_label.setStyleSheet("color: white;")
        doc_layout.addWidget(doc_label)

        self.doc_url_input = QLineEdit()
        self.doc_url_input.setPlaceholderText("Enter URL for document template")
        # self.doc_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.doc_url_input.returnPressed.connect(self.add_doc_url)
        doc_layout.addWidget(self.doc_url_input)

        doc_upload_btn = QPushButton("Upload Document")
        # doc_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        doc_upload_btn.clicked.connect(self.upload_doc_file)
        doc_layout.addWidget(doc_upload_btn)

        self.doc_list = QListWidget()
        # self.doc_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.doc_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.doc_list.customContextMenuRequested.connect(self.show_doc_context_menu)
        doc_layout.addWidget(self.doc_list)


        # Column 3: Generated Document
        output_widget = QWidget()
        output_layout = QVBoxLayout(output_widget)
        output_label = QLabel("Generated Document")
        # output_label.setStyleSheet("color: white;")
        output_layout.addWidget(output_label)

        self.doc_output = QTextEdit()
        self.doc_output.setReadOnly(True)
        # self.doc_output.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        output_layout.addWidget(self.doc_output)

        generate_btn = QPushButton("Generate Document")
        # generate_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        generate_btn.clicked.connect(self.generate_document)
        output_layout.addWidget(generate_btn)

        save_btn = QPushButton("Save Document")
        # save_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        save_btn.clicked.connect(self.save_generated_document)
        output_layout.addWidget(save_btn)

        splitter.addWidget(output_widget)
        tabs.addTab(docs_tab, "Docs")

        # Meetings Tab (unchanged)
        meetings_tab = QWidget()
        meetings_layout = QVBoxLayout(meetings_tab)
        meetings_layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        meetings_layout.setSpacing(5)  # Consistent spacing with chat widget
        
        self.recordButton = QPushButton("Start Recording", self)
        self.recordButton.clicked.connect(self.start_recording)
        # self.recordButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        meetings_layout.addWidget(self.recordButton)
        self.stopButton = QPushButton("Stop Recording", self)
        self.stopButton.clicked.connect(self.stop_recording)
        # self.stopButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.stopButton.setEnabled(False)
        meetings_layout.addWidget(self.stopButton)
        self.transcribeButton = QPushButton("Generate Transcript", self)
        self.transcribeButton.clicked.connect(self.transcribe_meeting)
        # self.transcribeButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.transcribeButton.setEnabled(False)
        meetings_layout.addWidget(self.transcribeButton)
        self.selectFileButton = QPushButton("Load File", self)
        self.selectFileButton.clicked.connect(self.select_file)
        # self.selectFileButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        meetings_layout.addWidget(self.selectFileButton)
        self.meetingTranscript = QTextEdit(self)
        # self.meetingTranscript.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.meetingTranscript.setReadOnly(True)
        meetings_layout.addWidget(self.meetingTranscript)
        self.saveTranscriptButton = QPushButton("Save Transcript", self)
        self.saveTranscriptButton.clicked.connect(self.save_transcript)
        # self.saveTranscriptButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.saveTranscriptButton.setEnabled(False)
        meetings_layout.addWidget(self.saveTranscriptButton)
        tabs.addTab(meetings_tab, "Meetings")

        # Compliance Tab (moved to last position)
        compliance_tab = QWidget()
        self.setup_compliance_tab(compliance_tab)
        tabs.addTab(compliance_tab, "Compliance")

        # Dashboard Tab
        dashboard_tab = QWidget()
        self.setup_dashboard_tab(dashboard_tab)
        tabs.addTab(dashboard_tab, "Dashboard")

        # Workspace Tab
        workspace_tab = WorkspaceTab(self.chat_handler.chat_handler.db)
        tabs.addTab(workspace_tab, "Workspace")

        # Notes Tab
        notes_tab = NoteTakingSystem(self.chat_handler)
        tabs.addTab(notes_tab, "Notes")

    def setup_compliance_tab(self, tab):
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)  # Consistent margins with chat widget
        layout.setSpacing(5)  # Consistent spacing with chat widget
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Column 1: Reference Documents
        ref_widget = QWidget()
        ref_layout = QVBoxLayout(ref_widget)
        ref_label = QLabel("Reference Documents (Regulations/Standards)")
        # ref_label.setStyleSheet("color: white;")
        ref_layout.addWidget(ref_label)

        self.ref_url_input = QLineEdit()
        self.ref_url_input.setPlaceholderText("Enter URL (e.g., https://www.ecfr.gov/21-cfr-820.3)")
        # self.ref_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.ref_url_input.returnPressed.connect(self.add_ref_url)
        ref_layout.addWidget(self.ref_url_input)

        ref_upload_btn = QPushButton("Upload Reference")
        # ref_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        ref_upload_btn.clicked.connect(self.upload_ref_file)
        ref_layout.addWidget(ref_upload_btn)

        self.ref_list = QListWidget()
        # self.ref_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        # Add context menu for removing items
        self.ref_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ref_list.customContextMenuRequested.connect(self.show_ref_context_menu)
        ref_layout.addWidget(self.ref_list)
        splitter.addWidget(ref_widget)

        # Column 2: Documents to Assess
        assess_widget = QWidget()
        assess_layout = QVBoxLayout(assess_widget)
        assess_label = QLabel("Documents to Assess (e.g., SOPs)")
        # assess_label.setStyleSheet("color: white;")
        assess_layout.addWidget(assess_label)

        self.assess_url_input = QLineEdit()
        self.assess_url_input.setPlaceholderText("Enter URL (e.g., https://navisure.com/sop.pdf)")
        # self.assess_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.assess_url_input.returnPressed.connect(self.add_assess_url)
        assess_layout.addWidget(self.assess_url_input)

        assess_upload_btn = QPushButton("Upload Document")
        # assess_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        assess_upload_btn.clicked.connect(self.upload_assess_file)
        assess_layout.addWidget(assess_upload_btn)

        self.assess_list = QListWidget()
        # self.assess_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        # Add context menu for removing items
        self.assess_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.assess_list.customContextMenuRequested.connect(self.show_assess_context_menu)
        assess_layout.addWidget(self.assess_list)
        splitter.addWidget(assess_widget)

        # Column 3: Results
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_label = QLabel("Compliance Results")
        # results_label.setStyleSheet("color: white;")
        results_layout.addWidget(results_label)

        self.results_text = QTextEdit()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate mode (spinning)
        self.progress_bar.hide()  # Hidden initially
        results_layout.addWidget(self.progress_bar)
        self.results_text.setReadOnly(True)
        # self.results_text.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        results_layout.addWidget(self.results_text)

        run_btn = QPushButton("Run Compliance Check")
        # run_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        run_btn.clicked.connect(self.run_compliance_check)
        results_layout.addWidget(run_btn)

        save_btn = QPushButton("Save Report")
        # save_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        save_btn.clicked.connect(self.save_compliance_report)
        results_layout.addWidget(save_btn)

        clear_dataset_btn = QPushButton("Clear Dataset")
        # clear_dataset_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        clear_dataset_btn.clicked.connect(self.clear_dataset)
        results_layout.addWidget(clear_dataset_btn)
        
        crm_btn = QPushButton("Link to CRM")
        # crm_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        crm_btn.clicked.connect(self.link_to_crm)
        results_layout.addWidget(crm_btn)
        splitter.addWidget(results_widget)

        # Load existing documents
        self.load_document_lists()

    def setup_dashboard_tab(self, tab):
        """Setup the dashboard tab with new layout: news feed on right, schedule middle top, task list middle bottom."""
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Header - styled as a label, not a button
        dashboard_header = QLabel("Dashboard - Overview")
        dashboard_header.setStyleSheet("color: white; font-weight: bold; font-size: 16px; padding: 10px; background-color: transparent; border: none;")
        dashboard_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(dashboard_header)
        
        # Create main horizontal layout for left and right columns
        main_layout = QHBoxLayout()
        main_layout.setSpacing(10)
        
        # Left column: Schedule and Task List
        left_column = QVBoxLayout()
        left_column.setSpacing(10)
        
        # Top: Schedule
        schedule_widget = self.create_dashboard_schedule_widget()
        left_column.addWidget(schedule_widget)
        
        # Bottom: Task List
        task_widget = self.create_dashboard_task_widget()
        left_column.addWidget(task_widget)
        
        # Right column: News Feed (mirrors chat window style)
        news_widget = self.create_dashboard_news_widget()
        
        # Add columns to main layout
        main_layout.addLayout(left_column, 2)  # Left column takes 2/3 of space
        main_layout.addWidget(news_widget, 1)  # Right column takes 1/3 of space
        
        layout.addLayout(main_layout)
        
        # Add refresh button at bottom
        refresh_layout = QHBoxLayout()
        refresh_layout.addStretch()
        
        refresh_news_btn = QPushButton("Refresh News")
        refresh_news_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 8px 15px; border-radius: 3px;")
        refresh_news_btn.clicked.connect(self.refresh_news_feed)
        refresh_layout.addWidget(refresh_news_btn)
        
        layout.addLayout(refresh_layout)
        
        # Setup auto-refresh timer for schedule (every 15 minutes)
        self.schedule_timer = QTimer()
        self.schedule_timer.timeout.connect(self.load_dashboard_schedule)
        self.schedule_timer.start(900000)  # 15 minutes in milliseconds
    

    
    def create_dashboard_task_widget(self):
        """Create the task list widget for the dashboard."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header - styled as a label, not a button
        task_header = QLabel("Task List")
        task_header.setStyleSheet("color: white; font-weight: bold; padding: 3px; background-color: transparent; border: none; font-size: 11px;")
        task_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        task_header.setMaximumHeight(25)
        layout.addWidget(task_header)
        
        # Task list - use proper TodoList integration with better text handling
        self.dashboard_task_list = QListWidget()
        self.dashboard_task_list.setStyleSheet("""
            QListWidget {
                background-color: rgba(27, 28, 30, 0.8); 
                color: white; 
                border: 1px solid rgba(253, 98, 98, 0.3); 
                border-radius: 3px;
                font-size: 10px;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid rgba(253, 98, 98, 0.2);
                min-height: 20px;
            }
            QListWidget::item:selected {
                background-color: rgba(253, 98, 98, 0.3);
            }
        """)
        self.dashboard_task_list.setWordWrap(True)  # Enable word wrapping
        self.dashboard_task_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.dashboard_task_list.itemDoubleClicked.connect(self.on_task_double_clicked)
        layout.addWidget(self.dashboard_task_list)
        
        # Quick add task
        add_layout = QHBoxLayout()
        self.dashboard_task_input = QLineEdit()
        self.dashboard_task_input.setPlaceholderText("Quick task...")
        self.dashboard_task_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.5); padding: 3px; border-radius: 3px;")
        self.dashboard_task_input.returnPressed.connect(self.add_dashboard_task)
        add_layout.addWidget(self.dashboard_task_input)
        
        add_btn = QPushButton("Add")
        add_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 3px 8px; border-radius: 3px;")
        add_btn.clicked.connect(self.add_dashboard_task)
        add_layout.addWidget(add_btn)
        
        layout.addLayout(add_layout)
        
        # Load recent tasks
        self.load_dashboard_tasks()
        
        return widget
    
    def create_dashboard_schedule_widget(self):
        """Create the schedule widget for the dashboard."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header - styled as a label, not a button
        schedule_header = QLabel("Today's Schedule")
        schedule_header.setStyleSheet("color: white; font-weight: bold; padding: 3px; background-color: transparent; border: none; font-size: 11px;")
        schedule_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        schedule_header.setMaximumHeight(25)
        layout.addWidget(schedule_header)
        
        # Schedule display - no height restriction
        self.dashboard_schedule_display = QTextBrowser()
        self.dashboard_schedule_display.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px;")
        self.dashboard_schedule_display.setReadOnly(True)
        self.dashboard_schedule_display.setPlaceholderText("Loading schedule...")
        layout.addWidget(self.dashboard_schedule_display)
        
        # Load initial schedule
        self.load_dashboard_schedule()
        
        return widget
    def create_dashboard_news_widget(self):
        """Create the news feed widget for the dashboard - styled like a chat window."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header - styled as a label, not a button
        news_header = QLabel("News Feed")
        news_header.setStyleSheet("color: white; font-weight: bold; padding: 3px; background-color: transparent; border: none; font-size: 11px;")
        news_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        news_header.setMaximumHeight(25)
        layout.addWidget(news_header)
        
        # News display - no height restriction, show full content
        self.dashboard_news_display = QTextBrowser()
        self.dashboard_news_display.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px; font-size: 10px;")
        self.dashboard_news_display.setReadOnly(True)
        self.dashboard_news_display.setPlaceholderText("Loading news...")
        self.dashboard_news_display.setOpenExternalLinks(True)  # Enable hyperlink clicking
        layout.addWidget(self.dashboard_news_display)
        
        # Auto-refresh timer (every hour)
        self.news_timer = QTimer()
        self.news_timer.timeout.connect(self.refresh_news_feed)
        self.news_timer.start(3600000)  # 1 hour in milliseconds
        
        # Load initial news
        self.load_dashboard_news()
        
        # Setup news cleanup timer (clean up old news every 24 hours)
        self.news_cleanup_timer = QTimer()
        self.news_cleanup_timer.timeout.connect(self.cleanup_old_news)
        self.news_cleanup_timer.start(86400000)  # 24 hours in milliseconds
        
        return widget





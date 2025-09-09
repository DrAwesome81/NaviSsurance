import sqlite3
import logging
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QSplashScreen,
    QTextBrowser, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QDateEdit, QTableWidget,
    QTableWidgetItem, QCheckBox, QComboBox, QLabel, QSplitter, QTextEdit, QDialog, QDialogButtonBox,
    QHeaderView, QMessageBox, QFileDialog, QMenu, QProgressBar, QApplication
)
from PyQt6.QtCore import Qt, QDate, QTimer, pyqtSlot, QUrl, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction, QDesktopServices, QColor
from core.db import DatabaseManager
from gui.chat_window import ChatThread, ResponseHandler, sendMessage, saveChat, loadChat
from gui.todo_list import TodoList
from core.chat import ChatManager
import os
import json
from datetime import datetime, timedelta
from dateutil import parser
import PyPDF2
from bs4 import BeautifulSoup
import markdown
from core.compliance import ComplianceChecker, DocumentGenerator
from core.api import DropboxClient
from docx import Document
from fpdf import FPDF
from dropbox import files
import re
import requests
from gui.notes_tab import NoteTakingSystem, NoteProcessingThread
from gui.dashboard_tab import DashboardTab
from gui.compliance_tab import ComplianceTab, ComplianceThread
from gui.meetings_tab import MeetingsTab
from gui.leads_tab import LeadsTab
from gui.workspace_tab import WorkspaceTab
from gui.utils import *

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

        # Start background thread for formatting
        self.note_thread = NoteProcessingThread(self.chat_handler, prompt, "notes_session")
        self.note_thread.result_signal.connect(self.handle_note_formatted)
        self.note_thread.error_signal.connect(self.handle_note_error)
        self.note_thread.start()

        # Disable input while processing
        self.chat_input.setEnabled(False)
        self.notes_display.append("<i>Formatting note...</i><br>")

    def handle_note_formatted(self, response):
        try:
            response_clean = response.strip()
            if not response_clean.startswith('{'):
                json_match = re.search(r'\\{.*\\}', response_clean, re.DOTALL)
                if json_match:
                    response_clean = json_match.group(0)
            
            note_data = json.loads(response_clean)
            formatted = note_data['formatted']
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.db.save_note(formatted, timestamp, self.context)
            self.notes.append(formatted)
            self.update_notes_display()
            
            # Re-enable input
            self.chat_input.setEnabled(True)
            self.chat_input.clear()
            self.chat_input.setFocus()
            
            # Trigger organization if enough notes
            if len(self.notes) >= 2:
                self.try_organize_notes()
        except json.JSONDecodeError:
            self.notes_display.append("Error: Invalid response format")
            self.notes_display.append(f"Raw response: {response}")
        except Exception as e:
            self.notes_display.append(f"Error: {str(e)}")
        finally:
            self.chat_input.setEnabled(True)

    def handle_note_error(self, error):
        self.notes_display.append(f"Error processing note: {error}")
        self.chat_input.setEnabled(True)

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

        # Start background thread for organization
        self.organize_thread = NoteProcessingThread(self.chat_handler, prompt, "notes_session")
        self.organize_thread.result_signal.connect(self.handle_organization_result)
        self.organize_thread.error_signal.connect(self.handle_organization_error)
        self.organize_thread.start()

        # Disable UI while processing
        self.chat_input.setEnabled(False)
        self.notes_display.append("<i>Organizing notes...</i><br>")

    def handle_organization_result(self, response):
        try:
            response_clean = response.strip()
            print(f"DEBUG: Original response length: {len(response)}")
            print(f"DEBUG: Cleaned response: '{response_clean}'")
            
            if not response_clean.startswith('{'):
                json_match = re.search(r'\\{.*\\}', response_clean, re.DOTALL)
                if json_match:
                    response_clean = json_match.group(0)
                    print(f"DEBUG: Extracted JSON: '{response_clean}'")
            
            if response_clean.count('"') % 2 != 0 or not response_clean.endswith('}'):
                self.notes_display.append("Warning: Response appears to be truncated, skipping categorization.")
                print(f"DEBUG: Response appears truncated - quote count: {response_clean.count('"')}, ends with '}}': {response_clean.endswith('}')}")
                self.chat_input.setEnabled(True)
                return
            
            try:
                organized_data = json.loads(response_clean)
                print(f"DEBUG: Successfully parsed JSON: {organized_data}")
            except json.JSONDecodeError as json_err:
                print(f"DEBUG: JSON decode error: {json_err}")
                response_clean = response_clean.replace("\n", " ").replace("\r", " ")
                response_clean = re.sub(r'\s+', ' ', response_clean)
                response_clean = re.sub(r',\s*}', '}', response_clean)
                response_clean = re.sub(r'"\s*}', '}', response_clean)
                response_clean = response_clean.rstrip("'\"")
                print(f"DEBUG: Attempting to fix JSON: '{response_clean}'")
                organized_data = json.loads(response_clean)
                print(f"DEBUG: Successfully parsed fixed JSON: {organized_data}")
            
            if 'categories' in organized_data and organized_data['categories']:
                self.organized = True
                self.db.save_organized_notes(organized_data['categories'])
                self.notes_display.append(f"<i>Notes organized into {len(organized_data['categories'])} categories</i><br>")
                self.update_notes_display(organized=True)
            else:
                self.notes_display.append("<i>No clear categories found, showing unorganized notes</i><br>")
                self.update_notes_display(organized=False)
        except json.JSONDecodeError as json_err:
            self.notes_display.append("Error: Invalid organization format")
            self.notes_display.append(f"Raw response: {response}")
            print(f"DEBUG: Final JSON decode error: {json_err}")
        except Exception as e:
            self.notes_display.append(f"Error: {str(e)}")
            print(f"DEBUG: Unexpected error: {e}")
        finally:
            self.chat_input.setEnabled(True)

    def handle_organization_error(self, error):
        self.notes_display.append(f"Error organizing notes: {error}")
        self.chat_input.setEnabled(True)

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
                        self.notes_display.append(f"  • {note}<br>")
                    self.notes_display.append("<br>")
            else:
                # Fallback to showing unorganized notes if no organized notes found
                self.notes_display.append("<b>Notes (Unorganized):</b><br>")
                for note in self.notes:
                    self.notes_display.append(f"  • {note}<br>")

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
    task_added_signal = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.db = DatabaseManager()
        self.chat_handler = ChatManager(self.db)
        self.todoList = QListWidget()
        self.todo_list = TodoList(self)
        self.initUI()
        self.response_handler = ResponseHandler(self.chat_display, self.chat_input, self.send_button, self.chat_handler, "main_session", [])
        self.task_added_signal.connect(self.response_handler.handle_task_added)
        
        # Create tabs after response_handler is initialized
        self.create_tabs()
        
        self.load_chat_history()

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
        self.setGeometry(300, 300, 1600, 900)  # Increased window size for better layout
        
        # Center the window on the screen
        screen = QApplication.primaryScreen().geometry()
        window_size = self.geometry()
        x = (screen.width() - window_size.width()) // 2
        y = (screen.height() - window_size.height()) // 2
        self.move(x, y)

        # Load the main application stylesheet
        self.loadStylesheet("styles.qss")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)  # Changed to horizontal layout

        # Left side - Chat Panel
        chat_panel = QWidget()
        chat_layout = QVBoxLayout(chat_panel)
        chat_layout.setContentsMargins(5, 5, 5, 5)
        chat_layout.setSpacing(0)

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
        
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type your message here...")
        self.chat_input.returnPressed.connect(self.sendMessage)
        input_layout.addWidget(self.chat_input)

        self.send_button = QPushButton('Send')
        self.send_button.clicked.connect(self.sendMessage)
        input_layout.addWidget(self.send_button)

        chat_layout.addLayout(input_layout)
        chat_layout.addSpacing(4)
        
        main_layout.addWidget(chat_panel, stretch=25)  # Chat panel gets 25% width

        # Right side - Tab Widget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget, stretch=75)  # Tabs get 75% width
        
        setup_shortcuts(self)
        setup_status_bar(self)

    def create_tabs(self):
        """Create and add all tabs after the chat handler is fully initialized."""
        self.dashboard_tab = DashboardTab(self.chat_handler, self.todo_list, self.db)
        self.tab_widget.addTab(self.dashboard_tab, "Dashboard")
        
        self.workspace_tab = WorkspaceTab(self.db)
        self.tab_widget.addTab(self.workspace_tab, "Workspace")
        
        self.compliance_tab = ComplianceTab(self.db, self.chat_handler, [])
        self.tab_widget.addTab(self.compliance_tab, "Compliance")
        
        self.meetings_tab = MeetingsTab(self.chat_handler)
        self.tab_widget.addTab(self.meetings_tab, "Meetings")
        
        self.leads_tab = LeadsTab(self.chat_handler, 'data', self)
        self.tab_widget.addTab(self.leads_tab, "Leads")
        
        self.notes_tab = NoteTakingSystem(self.chat_handler)
        self.tab_widget.addTab(self.notes_tab, "Notes")

    def sendMessage(self):
        message = self.chat_input.text().strip()
        if message:
            self.chat_display.append(f"<b>You:</b> {message}<br>")
            self.chat_input.clear()
            
            self.chat_thread = ChatThread(self.chat_handler, message, "main_session", [])
            self.chat_thread.response_signal.connect(self.handle_response)
            self.chat_thread.start()

    def handle_response(self, response):
        self.chat_display.append(f"<b>Navi:</b> {response}<br>")

    def load_chat_history(self):
        history = self.db.get_chat_history()
        for sender, message in history:
            self.chat_display.append(f"<b>{sender}:</b> {message}<br>")

    def closeEvent(self, event):
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
                schedule_html = "<div style='font-family: Arial; color: white;'>"
                schedule_html += "<h3 style='color: #fd6262;'>Today's Events</h3><ul style='list-style-type: none; padding: 0;'>"
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
                schedule_html = "<div style='color: white;'>No events scheduled for today</div>"
                print("No events found")
        except Exception as e:
            schedule_html = f"<div style='color: white;'>Error loading schedule: {str(e)}</div>"
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
                print(f"News displayed: {len(recent_news)} items")
            else:
                news_text = "<div style='color: white;'>No recent news available</div>"
                print("No news items found")
        except Exception as e:
            news_text = f"<div style='color: white;'>Error displaying news: {str(e)}</div>"
            print(f"Error displaying news: {str(e)}")

    def refresh_news_feed(self):
        """Refresh the news feed."""
        self.load_dashboard_news()
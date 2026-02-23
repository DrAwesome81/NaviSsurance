import sqlite3
import logging
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QSplashScreen,
    QTextBrowser, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QDateEdit, QTableWidget,
    QTableWidgetItem, QCheckBox, QComboBox, QLabel, QSplitter, QTextEdit, QDialog, QDialogButtonBox,
    QHeaderView, QMessageBox, QFileDialog, QMenu, QProgressBar, QApplication
)
from PyQt6.QtCore import Qt, QDate, QTimer, pyqtSlot, QUrl, QThread, pyqtSignal, QMetaObject, Q_ARG
from PyQt6.QtGui import QPixmap, QAction, QDesktopServices, QColor, QPainter
from core.db import DatabaseManager
from gui.chat_window import ChatThread, sendMessage, saveChat, loadChat
from core.response_handler import ResponseHandler
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

def robust_json_parse(response_text, logger=None):
    """
    Robust JSON parsing that handles various API response formats.
    
    Args:
        response_text: Raw response text from API
        logger: Optional logger for debug messages
    
    Returns:
        tuple: (parsed_json_data, success_flag)
    """
    if logger is None:
        logger = print  # Fallback to print for debug messages
    
    # Step 1: Try direct JSON parsing first
    try:
        clean_response = response_text.strip()
        data = json.loads(clean_response)
        logger(f"Direct JSON parsing successful")
        return data, True
    except json.JSONDecodeError:
        logger(f"Direct JSON parsing failed, attempting extraction...")
    
    # Step 2: Try extracting JSON from markdown code blocks
    try:
        # Look for ```json...``` blocks
        json_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
        match = re.search(json_pattern, response_text, re.DOTALL | re.IGNORECASE)
        if match:
            json_str = match.group(1).strip()
            data = json.loads(json_str)
            logger(f"JSON extraction from code block successful")
            return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Code block extraction failed")
    
    # Step 3: Try regex extraction of JSON object
    try:
        # Look for first complete JSON object
        json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        match = re.search(json_pattern, response_text, re.DOTALL)
        if match:
            json_str = match.group(0).strip()
            data = json.loads(json_str)
            logger(f"Regex JSON extraction successful")
            return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Regex extraction failed")
    
    # Step 4: Try fixing common JSON issues
    try:
        clean_response = response_text.strip()
        
        # Remove common prefixes/suffixes
        clean_response = re.sub(r'^[^{]*', '', clean_response)  # Remove text before {
        clean_response = re.sub(r'[^}]*$', '', clean_response)  # Remove text after }
        
        # Fix common issues
        clean_response = re.sub(r',\s*}', '}', clean_response)  # Remove trailing commas
        clean_response = re.sub(r',\s*]', ']', clean_response)  # Remove trailing commas in arrays
        clean_response = re.sub(r'"\s*}', '}', clean_response)  # Remove trailing quotes
        clean_response = re.sub(r'"\s*]', ']', clean_response)  # Remove trailing quotes in arrays
        clean_response = re.sub(r'\s+', ' ', clean_response)   # Normalize whitespace
        
        # Ensure it starts and ends with braces
        if not clean_response.startswith('{'):
            clean_response = '{' + clean_response
        if not clean_response.endswith('}'):
            clean_response = clean_response + '}'
        
        data = json.loads(clean_response)
        logger(f"Fixed JSON parsing successful")
        return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Fixed JSON parsing failed")
    
    # Step 5: Try extracting partial JSON for truncated responses
    try:
        clean_response = response_text.strip()
        
        # Find the first { and last }
        start_idx = clean_response.find('{')
        end_idx = clean_response.rfind('}')
        
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = clean_response[start_idx:end_idx + 1]
            
            # Try to complete truncated JSON
            if json_str.count('{') > json_str.count('}'):
                json_str += '}' * (json_str.count('{') - json_str.count('}'))
            if json_str.count('"') % 2 != 0:
                json_str += '"'
            
            data = json.loads(json_str)
            logger(f"Partial JSON extraction successful")
            return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Partial JSON extraction failed")
    
    logger(f"All JSON parsing attempts failed")
    return None, False
from gui.dashboard_tab import DashboardTab
from gui.compliance_tab import ComplianceTab, ComplianceThread
from gui.meetings_tab import MeetingsTab
from gui.leads_tab import LeadsTab
from gui.workspace_tab import WorkspaceTab
from gui.projects_tab import ProjectsTab
from gui.chief_of_staff_tab import ChiefOfStaffTab
from gui.utils import *

logger = logging.getLogger(__name__)

# Try to import TasksTab - handle import errors gracefully
try:
    from gui.tasks_tab import TasksTab
    TASKS_TAB_AVAILABLE = True
    logger.info("TasksTab imported successfully")
except (ImportError, SyntaxError) as e:
    logger.warning(f"TasksTab not available: {e}")
    TASKS_TAB_AVAILABLE = False
    TasksTab = None

class EnhancedSplashScreen(QSplashScreen):
    """Enhanced splash screen with progress bar and status updates."""
    
    def __init__(self, pixmap):
        super().__init__(pixmap)
        self.setStyleSheet("""
            QSplashScreen {
                background-color: transparent;
                color: #e8eaed;
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
                border: 2px solid #2e2f32;
                border-radius: 5px;
                text-align: center;
                background-color: #1c1e24;
                color: #e8eaed;
            }
            QProgressBar::chunk {
                background-color: #FD6262;
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
                color: #e8eaed;
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
                background-color: rgba(28, 30, 36, 0.75);
                color: #e8eaed;
                border: 1px solid rgba(46, 47, 50, 0.6);
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
        from config import CONFIG_DIR
        config_path = os.path.join(CONFIG_DIR, "lead_gen_config.json")
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

    def accept(self):
        """Persist lead-gen settings to config/lead_gen_config.json."""
        try:
            from config import CONFIG_DIR
            os.makedirs(CONFIG_DIR, exist_ok=True)
            config_path = os.path.join(CONFIG_DIR, "lead_gen_config.json")
            payload = {"system_message": (self.system_message_input.toPlainText() or "").strip()}
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            try:
                QMessageBox.warning(self, "Save Error", f"Could not save lead gen settings:\n{e}")
            except Exception:
                pass
            return
        super().accept()

class ChatWindow(QMainWindow):
    task_added_signal = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.db = DatabaseManager()
        self.chat_handler = ChatManager(self)  # Pass self (ChatWindow) to ChatManager
        self.todoList = QListWidget()
        self.todoList.setStyleSheet("QListWidget::item { border: none; padding: 0; }")
        self.todo_list = TodoList(self)
        self.initUI()
        # Create tabs first so tasks_tab is available
        self.create_tabs()
        
        # Reuse ChatManager's ResponseHandler to avoid spawning duplicate llama_worker subprocess
        self.response_handler = self.chat_handler.response_handler
        self.chat_handler.task_added_signal.connect(self.response_handler.handle_task_added)
        
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
        
        # Set minimum size for responsive layout
        self.setMinimumSize(800, 600)
        
        # Use smart geometry based on screen size
        screen = QApplication.primaryScreen().geometry()
        window_width = min(1600, screen.width() - 100)  # Leave margin
        window_height = min(900, screen.height() - 100)  # Leave margin
        x = (screen.width() - window_width) // 2
        y = (screen.height() - window_height) // 2
        self.setGeometry(x, y, window_width, window_height)

        # Load the main application stylesheet
        self.loadStylesheet("styles.qss")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)  # Changed to horizontal layout

        # Left side - Chat Panel (hidden when Chief of Staff tab is active)
        self.chat_panel = QWidget()
        chat_layout = QVBoxLayout(self.chat_panel)
        chat_layout.setContentsMargins(5, 5, 5, 5)
        chat_layout.setSpacing(0)

        # Add header to match tab bar height
        chat_header = QLabel("Navi Chat")
        chat_header.setStyleSheet("""
            QLabel {
                background-color: #15171c;
                color: #e8eaed;
                padding: 8px 12px;
                font-size: 13px;
                font-weight: 600;
                border-bottom: 1px solid #2e2f32;
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
        
        # Use proper stretch factors instead of fixed percentages
        main_layout.addWidget(self.chat_panel, 1)  # Chat panel gets 1/4 of space

        # Right side - Tab Widget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget, 3)  # Tabs get 3/4 of space
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        setup_shortcuts(self)
        setup_status_bar(self)

    def create_tabs(self):
        """Create and add all tabs after the chat handler is fully initialized."""
        logger.info("Creating tabs...")
        self.dashboard_tab = DashboardTab(self.chat_handler, self.todo_list, self.db, self)
        self.tab_widget.addTab(self.dashboard_tab, "Dashboard")
        logger.info("Dashboard tab added")
        
        # Try to create Tasks tab - handle errors gracefully
        logger.info(f"TASKS_TAB_AVAILABLE={TASKS_TAB_AVAILABLE}, TasksTab={TasksTab}")
        if TASKS_TAB_AVAILABLE and TasksTab is not None:
            try:
                logger.info("Attempting to create TasksTab...")
                self.tasks_tab = TasksTab(self)
                self.tab_widget.addTab(self.tasks_tab, "Tasks")
                logger.info("Tasks tab added successfully")
            except Exception as e:
                logger.error(f"Failed to create Tasks tab: {e}", exc_info=True)
                # Create a placeholder tab with error message
                error_widget = QWidget()
                error_layout = QVBoxLayout()
                error_label = QLabel(f"Tasks tab unavailable:\n{str(e)}")
                error_label.setWordWrap(True)
                error_layout.addWidget(error_label)
                error_widget.setLayout(error_layout)
                self.tab_widget.addTab(error_widget, "Tasks (Error)")
                logger.info("Tasks error tab added")
        else:
            # TasksTab import failed - create placeholder
            logger.warning("TasksTab not available, creating error placeholder")
            error_widget = QWidget()
            error_layout = QVBoxLayout()
            error_label = QLabel("Tasks tab unavailable: TasksTab could not be imported.\nCheck logs for details.")
            error_label.setWordWrap(True)
            error_layout.addWidget(error_label)
            error_widget.setLayout(error_layout)
            self.tab_widget.addTab(error_widget, "Tasks (Error)")
            logger.info("Tasks error placeholder tab added")
        
        self.workspace_tab = WorkspaceTab(self.db, self.chat_handler)
        self.tab_widget.addTab(self.workspace_tab, "Workspace")
        
        self.projects_tab = ProjectsTab(self.db)
        self.tab_widget.addTab(self.projects_tab, "AI Projects")
        
        self.compliance_tab = ComplianceTab(self.db, self.chat_handler)
        self.tab_widget.addTab(self.compliance_tab, "Compliance")
        
        self.meetings_tab = MeetingsTab(self.chat_handler)
        self.tab_widget.addTab(self.meetings_tab, "Meetings")
        
        self.leads_tab = LeadsTab(self.chat_handler, 'data', self)
        self.tab_widget.addTab(self.leads_tab, "Leads")
        
        self.notes_tab = NoteTakingSystem(self.chat_handler)
        self.tab_widget.addTab(self.notes_tab, "Notes")
        
        self.chief_of_staff_tab = ChiefOfStaffTab(self.db)
        self.tab_widget.addTab(self.chief_of_staff_tab, "Chief of Staff")
        self._on_tab_changed(self.tab_widget.currentIndex())  # Apply visibility for initial tab

    def _on_tab_changed(self, index):
        """Hide Navi chat panel when Chief of Staff tab is active; show it for other tabs."""
        tab_name = self.tab_widget.tabText(index) if index >= 0 else ""
        if tab_name == "Chief of Staff":
            self.chat_panel.hide()
            self.tab_widget.setStyleSheet("")  # ensure tab widget can expand
        else:
            self.chat_panel.show()

    def _get_dashboard_cos_chat_id(self) -> int:
        """Return a stable cos_chat id used by the Dashboard chat panel."""
        try:
            existing = self.db.get_setting("cos_dashboard_chat_id", "") if hasattr(self.db, "get_setting") else ""
            if existing:
                try:
                    cid = int(str(existing).strip())
                    if cid > 0:
                        return cid
                except Exception:
                    pass
        except Exception:
            pass

        # Create a chat record and persist it.
        cid = self.db.cos_create_chat(title="Dashboard", project=None)
        try:
            if hasattr(self.db, "set_setting"):
                self.db.set_setting("cos_dashboard_chat_id", str(cid))
        except Exception:
            pass
        return cid

    def _dashboard_session_id(self) -> str:
        return f"cos_{self._get_dashboard_cos_chat_id()}"

    def sendMessage(self):
        message = self.chat_input.text().strip()
        if message:
            self.chat_display.append(f"<b>You:</b> {message}<br>")
            self.chat_input.clear()

            # Chief of Staff replaces Navi in the dashboard chat.
            session_id = self._dashboard_session_id()
            try:
                self.db.save_message(session_id, "user", message)
            except Exception:
                pass
            history = []
            try:
                history = self.db.get_chat_history(session_id, limit=50)
            except Exception:
                history = []

            self.chat_thread = ChatThread(self.chat_handler, message, session_id, history)
            self.chat_thread.response_signal.connect(self.handle_response)
            self.chat_thread.start()

    def handle_response(self, response):
        # Use thread-safe UI update
        QTimer.singleShot(0, lambda: self._handle_response_safe(response))
    
    def _handle_response_safe(self, response):
        """Thread-safe version of handle_response."""
        self.chat_display.append(f"<b>Navi:</b> {response}<br>")
        # If Navi added tasks via CoS chat, refresh the Dashboard task table immediately.
        try:
            if isinstance(response, str) and re.search(r"\bAdded\s+\d+\s+task", response):
                if hasattr(self, "dashboard_tab") and hasattr(self.dashboard_tab, "load_tasks_filtered"):
                    QTimer.singleShot(0, self.dashboard_tab.load_tasks_filtered)
        except Exception:
            pass

    def load_chat_history(self):
        # Load Dashboard chat history from the persistent CoS session.
        session_id = self._dashboard_session_id()
        history = self.db.get_chat_history(session_id, limit=100)
        for role, message in history:
            label = "You" if role == "user" else "Navi"
            self.chat_display.append(f"<b>{label}:</b> {message}<br>")

    def closeEvent(self, event):
        if hasattr(self, "projects_tab") and hasattr(self.projects_tab, "save_state"):
            self.projects_tab.save_state()
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
                schedule_html = "<div style='font-family: Segoe UI, Arial, sans-serif; color: #e8eaed;'>"
                schedule_html += "<h3 style='color: #6b8cae; margin-bottom: 8px;'>Today's Events</h3><ul style='list-style-type: none; padding: 0;'>"
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
                schedule_html = "<div style='color: #e8eaed;'>No events scheduled for today</div>"
                print("No events found")
        except Exception as e:
            schedule_html = f"<div style='color: #e8eaed;'>Error loading schedule: {str(e)}</div>"
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
                news_text = "<div style='color: #e8eaed; font-family: Segoe UI, Arial, sans-serif;'>"
                news_text += "<h3 style='color: #6b8cae; margin-bottom: 15px;'>Latest News</h3>"
                
                for title, content, url, source, published_date, created_at in recent_news:
                    news_text += "<div style='margin-bottom: 20px; padding: 12px; background-color: #22252c; border: 1px solid #2e2f32; border-radius: 6px;'>"
                    news_text += f"<h4 style='color: #e8eaed; margin: 0 0 8px 0; font-size: 13px;'>{title}</h4>"
                    if content:
                        news_text += f"<p style='margin: 0 0 8px 0; line-height: 1.5; color: #9aa0a6;'>{content}</p>"
                    if url:
                        news_text += f'<p style="margin: 0 0 5px 0;"><a href="{url}" style="color: #6b8cae; text-decoration: underline;">🔗 Read full article</a></p>'
                    if published_date:
                        news_text += f"<small style='color: #5f6368;'>Published: {published_date}</small>"
                    news_text += "</div>"
                
                news_text += "</div>"
                print(f"News displayed: {len(recent_news)} items")
            else:
                news_text = "<div style='color: #e8eaed;'>No recent news available</div>"
                print("No news items found")
        except Exception as e:
            news_text = f"<div style='color: #e8eaed;'>Error displaying news: {str(e)}</div>"
            print(f"Error displaying news: {str(e)}")

    def refresh_news_feed(self):
        """Refresh the news feed."""
        self.load_dashboard_news()
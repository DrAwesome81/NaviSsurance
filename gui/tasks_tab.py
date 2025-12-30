"""
Tasks tab - Vikunja integration for task management.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QMessageBox, QGroupBox, QFormLayout, QSpinBox, QDateEdit, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate
import logging

logger = logging.getLogger(__name__)

# Try to import VikunjaClient, but handle import errors gracefully
try:
    from core.vikunja_client import VikunjaClient
    VIKUNJA_AVAILABLE = True
except (ImportError, SyntaxError) as e:
    logger.warning(f"VikunjaClient not available: {e}")
    VIKUNJA_AVAILABLE = False
    VikunjaClient = None


class TasksTab(QWidget):
    """Tasks tab with Vikunja integration."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = None
        self.current_project_id = None
        self.init_ui()
        
        # Try to load saved connection settings from config
        # For now, default to local dev instance
        self.url_input.setText("http://localhost:3456")
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()
        
        # Show error message if VikunjaClient is not available
        if not VIKUNJA_AVAILABLE:
            error_label = QLabel(
                "⚠️ Vikunja client not available. Please check that core/vikunja_client.py is valid.\n"
                "The Tasks tab will not function until this is fixed."
            )
            error_label.setStyleSheet("color: red; padding: 10px;")
            error_label.setWordWrap(True)
            layout.addWidget(error_label)
            self.setLayout(layout)
            return
        
        # Connection panel
        conn_group = QGroupBox("Vikunja Connection")
        conn_layout = QFormLayout()
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("http://localhost:3456")
        conn_layout.addRow("Server URL:", self.url_input)
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("username")
        conn_layout.addRow("Username:", self.username_input)
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("password")
        conn_layout.addRow("Password:", self.password_input)
        
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("email (for registration)")
        conn_layout.addRow("Email:", self.email_input)
        
        button_layout = QHBoxLayout()
        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self.test_connection)
        button_layout.addWidget(self.test_btn)
        
        self.login_btn = QPushButton("Login")
        self.login_btn.clicked.connect(self.login)
        button_layout.addWidget(self.login_btn)
        
        self.register_btn = QPushButton("Register")
        self.register_btn.clicked.connect(self.register)
        button_layout.addWidget(self.register_btn)
        
        conn_layout.addRow(button_layout)
        
        self.conn_status = QLabel("Not connected")
        self.conn_status.setStyleSheet("color: orange;")
        conn_layout.addRow("Status:", self.conn_status)
        
        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)
        
        # Project selector
        project_layout = QHBoxLayout()
        project_layout.addWidget(QLabel("Project:"))
        self.project_combo = QComboBox()
        self.project_combo.currentIndexChanged.connect(self.load_tasks)
        project_layout.addWidget(self.project_combo, 1)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.load_projects)
        self.refresh_btn.setEnabled(False)
        project_layout.addWidget(self.refresh_btn)
        
        self.new_project_btn = QPushButton("New Project")
        self.new_project_btn.clicked.connect(self.create_project)
        self.new_project_btn.setEnabled(False)
        project_layout.addWidget(self.new_project_btn)
        
        layout.addLayout(project_layout)
        
        # Task creation panel
        create_group = QGroupBox("Create Task")
        create_layout = QVBoxLayout()
        
        title_layout = QHBoxLayout()
        title_layout.addWidget(QLabel("Title:"))
        self.task_title_input = QLineEdit()
        title_layout.addWidget(self.task_title_input, 1)
        create_layout.addLayout(title_layout)
        
        priority_layout = QHBoxLayout()
        priority_layout.addWidget(QLabel("Priority:"))
        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(0, 5)
        self.priority_spin.setValue(0)
        priority_layout.addWidget(self.priority_spin)
        priority_layout.addStretch()
        create_layout.addLayout(priority_layout)
        
        self.create_task_btn = QPushButton("Create Task")
        self.create_task_btn.clicked.connect(self.create_task)
        self.create_task_btn.setEnabled(False)
        create_layout.addWidget(self.create_task_btn)
        
        create_group.setLayout(create_layout)
        layout.addWidget(create_group)
        
        # Task list
        self.task_table = QTableWidget()
        self.task_table.setColumnCount(5)
        self.task_table.setHorizontalHeaderLabels(["ID", "Title", "Priority", "Done", "Actions"])
        self.task_table.setColumnHidden(0, True)  # Hide ID column
        self.task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.task_table, 1)
        
        self.setLayout(layout)
    
    def test_connection(self):
        """Test connection to Vikunja."""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "Please enter a server URL")
            return
        
        try:
            client = VikunjaClient(base_url=url)
            if client.test_connection():
                self.conn_status.setText("Connection OK (not authenticated)")
                self.conn_status.setStyleSheet("color: blue;")
                QMessageBox.information(self, "Success", "Connection test successful!")
            else:
                self.conn_status.setText("Connection failed")
                self.conn_status.setStyleSheet("color: red;")
                QMessageBox.warning(self, "Error", "Connection test failed")
        except Exception as e:
            self.conn_status.setText("Connection error")
            self.conn_status.setStyleSheet("color: red;")
            QMessageBox.critical(self, "Error", f"Connection error: {e}")
    
    def login(self):
        """Login to Vikunja."""
        url = self.url_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()
        
        if not all([url, username, password]):
            QMessageBox.warning(self, "Error", "Please fill in all fields")
            return
        
        try:
            self.client = VikunjaClient(base_url=url)
            self.client.login(username, password)
            self.conn_status.setText(f"Connected as {username}")
            self.conn_status.setStyleSheet("color: green;")
            self.refresh_btn.setEnabled(True)
            self.new_project_btn.setEnabled(True)
            self.create_task_btn.setEnabled(True)
            self.load_projects()
            QMessageBox.information(self, "Success", "Login successful!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Login failed: {e}")
    
    def register(self):
        """Register a new Vikunja user."""
        url = self.url_input.text().strip()
        username = self.username_input.text().strip()
        email = self.email_input.text().strip()
        password = self.password_input.text()
        
        if not all([url, username, email, password]):
            QMessageBox.warning(self, "Error", "Please fill in all fields (including email)")
            return
        
        try:
            self.client = VikunjaClient(base_url=url)
            self.client.register(username, email, password)
            self.conn_status.setText(f"Connected as {username}")
            self.conn_status.setStyleSheet("color: green;")
            self.refresh_btn.setEnabled(True)
            self.new_project_btn.setEnabled(True)
            self.create_task_btn.setEnabled(True)
            self.load_projects()
            QMessageBox.information(self, "Success", f"Registration successful! Logged in as {username}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Registration failed: {e}")
    
    def load_projects(self):
        """Load projects from Vikunja."""
        if not self.client:
            return
        
        try:
            projects = self.client.get_projects()
            self.project_combo.clear()
            for proj in projects:
                self.project_combo.addItem(proj.get("title", "Untitled"), proj.get("id"))
            
            if projects:
                self.load_tasks()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load projects: {e}")
    
    def create_project(self):
        """Create a new project."""
        from PyQt6.QtWidgets import QInputDialog
        
        if not self.client:
            return
        
        title, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if ok and title:
            try:
                self.client.create_project(title)
                self.load_projects()
                QMessageBox.information(self, "Success", f"Project '{title}' created!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create project: {e}")
    
    def load_tasks(self):
        """Load tasks for the selected project."""
        if not self.client:
            return
        
        project_id = self.project_combo.currentData()
        if not project_id:
            self.task_table.setRowCount(0)
            return
        
        self.current_project_id = project_id
        
        try:
            tasks = self.client.get_tasks(project_id)
            self.task_table.setRowCount(len(tasks))
            
            for row, task in enumerate(tasks):
                # ID (hidden)
                id_item = QTableWidgetItem(str(task.get("id", "")))
                self.task_table.setItem(row, 0, id_item)
                
                # Title
                title_item = QTableWidgetItem(task.get("title", ""))
                self.task_table.setItem(row, 1, title_item)
                
                # Priority
                priority_item = QTableWidgetItem(str(task.get("priority", 0)))
                self.task_table.setItem(row, 2, priority_item)
                
                # Done status
                done = task.get("done", False)
                done_item = QTableWidgetItem("✓" if done else "")
                done_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.task_table.setItem(row, 3, done_item)
                
                # Actions
                action_btn = QPushButton("Toggle Done")
                action_btn.clicked.connect(lambda checked, tid=task.get("id"), d=done: self.toggle_task(tid, not d))
                self.task_table.setCellWidget(row, 4, action_btn)
            
            self.task_table.resizeColumnsToContents()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load tasks: {e}")
    
    def create_task(self):
        """Create a new task."""
        if not self.client or not self.current_project_id:
            QMessageBox.warning(self, "Error", "Please select a project first")
            return
        
        title = self.task_title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "Error", "Please enter a task title")
            return
        
        priority = self.priority_spin.value()
        
        try:
            self.client.create_task(self.current_project_id, title, priority=priority)
            self.task_title_input.clear()
            self.load_tasks()
            QMessageBox.information(self, "Success", f"Task '{title}' created!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create task: {e}")
    
    def toggle_task(self, task_id: int, done: bool):
        """Toggle task done status."""
        if not self.client:
            return
        
        try:
            self.client.toggle_task_done(task_id, done)
            self.load_tasks()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to update task: {e}")


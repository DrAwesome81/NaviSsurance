"""
Tasks tab - Vikunja integration for task management.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QMessageBox, QGroupBox, QFormLayout, QSpinBox, QDateEdit, QTextEdit, QDialog, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate, QSettings
from datetime import datetime
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

# Try to import DatabaseManager for custom task metadata
try:
    from core.db import DatabaseManager
    DB_AVAILABLE = True
except (ImportError, SyntaxError) as e:
    logger.warning(f"DatabaseManager not available: {e}")
    DB_AVAILABLE = False
    DatabaseManager = None


class TasksTab(QWidget):
    """Tasks tab with Vikunja integration."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = None
        self.current_project_id = None
        self.settings = QSettings("NaviSsurance", "TasksTab")
        # Initialize DatabaseManager for custom task metadata
        self.db = DatabaseManager() if DB_AVAILABLE else None
        self.init_ui()
        
        # Load saved connection settings
        self.url_input.setText(self.settings.value("vikunja_url", "http://localhost:3456"))
        self.username_input.setText(self.settings.value("vikunja_username", ""))
        self.password_input.setText(self.settings.value("vikunja_password", ""))
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Show error message if VikunjaClient is not available
        if not VIKUNJA_AVAILABLE:
            error_label = QLabel(
                "⚠️ Vikunja client not available. Please check that core/vikunja_client.py is valid.\n"
                "The Tasks tab will not function until this is fixed."
            )
            error_label.setStyleSheet("color: #e07a7a; padding: 10px; font-size: 13px;")
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
        self.username_input.returnPressed.connect(self.login)  # Enter key triggers login
        conn_layout.addRow("Username:", self.username_input)
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("password")
        self.password_input.returnPressed.connect(self.login)  # Enter key triggers login
        conn_layout.addRow("Password:", self.password_input)
        
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("email (for registration)")
        conn_layout.addRow("Email:", self.email_input)
        
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)
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
        self.conn_status.setStyleSheet("color: #9aa0a6; font-size: 13px;")
        conn_layout.addRow("Status:", self.conn_status)
        
        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)
        
        # Project selector
        project_layout = QHBoxLayout()
        project_layout.setContentsMargins(0, 0, 0, 0)
        project_layout.setSpacing(8)
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
        create_layout.setContentsMargins(8, 8, 8, 8)
        create_layout.setSpacing(8)
        
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)
        title_layout.addWidget(QLabel("Title:"))
        self.task_title_input = QLineEdit()
        title_layout.addWidget(self.task_title_input, 1)
        create_layout.addLayout(title_layout)
        
        priority_layout = QHBoxLayout()
        priority_layout.setContentsMargins(0, 0, 0, 0)
        priority_layout.setSpacing(8)
        priority_layout.addWidget(QLabel("Priority:"))
        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(0, 5)
        self.priority_spin.setValue(0)
        priority_layout.addWidget(self.priority_spin)
        priority_layout.addStretch()
        create_layout.addLayout(priority_layout)
        
        # Estimated Duration (in minutes)
        duration_layout = QHBoxLayout()
        duration_layout.setContentsMargins(0, 0, 0, 0)
        duration_layout.setSpacing(8)
        duration_layout.addWidget(QLabel("Est. Duration (minutes):"))
        self.estimated_duration_spin = QSpinBox()
        self.estimated_duration_spin.setRange(0, 10080)  # 0 to 7 days (in minutes)
        self.estimated_duration_spin.setValue(0)
        self.estimated_duration_spin.setSuffix(" min")
        duration_layout.addWidget(self.estimated_duration_spin)
        duration_layout.addStretch()
        create_layout.addLayout(duration_layout)
        
        self.create_task_btn = QPushButton("Create Task")
        self.create_task_btn.clicked.connect(self.create_task)
        self.create_task_btn.setEnabled(False)
        create_layout.addWidget(self.create_task_btn)
        
        create_group.setLayout(create_layout)
        layout.addWidget(create_group)
        
        # Task list
        self.task_table = QTableWidget()
        # Columns: ID, Title, Description, Priority, Due Date, Start Date, End Date, Percent Done, Done, Favorite, Estimated Duration, Actions
        self.task_table.setColumnCount(12)
        self.task_table.setHorizontalHeaderLabels([
            "ID", "Title", "Description", "Priority", "Due Date", 
            "Start Date", "End Date", "% Done", "Done", "Favorite", 
            "Est. Duration", "Actions"
        ])
        self.task_table.setColumnHidden(0, True)  # Hide ID column
        self.task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # Enable horizontal scrolling for wide tables
        self.task_table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        # Store task data for editing
        self.task_data = {}  # Maps task_id to full task data
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
                self.conn_status.setStyleSheet("color: #6b8cae;")
                QMessageBox.information(self, "Success", "Connection test successful!")
            else:
                self.conn_status.setText("Connection failed")
                self.conn_status.setStyleSheet("color: #e07a7a;")
                QMessageBox.warning(self, "Error", "Connection test failed")
        except Exception as e:
            self.conn_status.setText("Connection error")
            self.conn_status.setStyleSheet("color: #e07a7a;")
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
            self.conn_status.setStyleSheet("color: #6bae6b;")
            self.refresh_btn.setEnabled(True)
            self.new_project_btn.setEnabled(True)
            self.create_task_btn.setEnabled(True)
            self.load_projects()
            # Save credentials for next session (no success popup - only show errors)
            self.settings.setValue("vikunja_url", url)
            self.settings.setValue("vikunja_username", username)
            self.settings.setValue("vikunja_password", password)
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
            self.conn_status.setStyleSheet("color: #6bae6b;")
            self.refresh_btn.setEnabled(True)
            self.new_project_btn.setEnabled(True)
            self.create_task_btn.setEnabled(True)
            self.load_projects()
            # Save credentials for next session (no success popup - only show errors)
            self.settings.setValue("vikunja_url", url)
            self.settings.setValue("vikunja_username", username)
            self.settings.setValue("vikunja_password", password)
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
                QMessageBox.information(self, "Success", f"Project ''{title}'' created!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create project: {e}")
    
    def _format_date(self, date_str):
        """Format ISO date string to readable format."""
        if not date_str:
            return ""
        try:
            # Handle ISO format with or without timezone
            date_str = date_str.replace('Z', '+00:00')
            date_obj = datetime.fromisoformat(date_str)
            return date_obj.strftime("%Y-%m-%d")
        except Exception:
            return str(date_str)
    
    def _get_estimated_duration(self, task_id):
        """Get estimated duration in minutes from database."""
        if not self.db or not task_id:
            return None
        try:
            import sqlite3
            conn = sqlite3.connect(self.db.db_name)
            cursor = conn.execute(
                "SELECT estimated_duration_minutes FROM vikunja_task_metadata WHERE vikunja_task_id = ?",
                (task_id,)
            )
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else None
        except Exception as e:
            logger.warning(f"Failed to load estimated duration for task {task_id}: {e}")
            return None
    
    def _save_estimated_duration(self, task_id, estimated_duration_minutes):
        """Save estimated duration to database."""
        if not self.db or not task_id:
            return
        try:
            import sqlite3
            conn = sqlite3.connect(self.db.db_name)
            # Use INSERT OR REPLACE to handle both new and existing records
            conn.execute('''INSERT OR REPLACE INTO vikunja_task_metadata 
                          (vikunja_task_id, estimated_duration_minutes, updated_at) 
                          VALUES (?, ?, CURRENT_TIMESTAMP)''',
                       (task_id, estimated_duration_minutes if estimated_duration_minutes > 0 else None))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to save estimated duration for task {task_id}: {e}")
    
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
                task_id = task.get("id")
                if task_id:
                    # Store full task data for editing
                    self.task_data[task_id] = task
                
                col = 0
                
                # ID (hidden)
                id_item = QTableWidgetItem(str(task_id or ""))
                self.task_table.setItem(row, col, id_item)
                col += 1
                
                # Title
                title_item = QTableWidgetItem(task.get("title", ""))
                self.task_table.setItem(row, col, title_item)
                col += 1
                
                # Description
                description = task.get("description", "")
                # Truncate long descriptions for display
                if len(description) > 100:
                    description = description[:97] + "..."
                desc_item = QTableWidgetItem(description)
                self.task_table.setItem(row, col, desc_item)
                col += 1
                
                # Priority
                priority_item = QTableWidgetItem(str(task.get("priority", 0)))
                priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.task_table.setItem(row, col, priority_item)
                col += 1
                
                # Due Date
                due_date = self._format_date(task.get("due_date"))
                due_item = QTableWidgetItem(due_date)
                self.task_table.setItem(row, col, due_item)
                col += 1
                
                # Start Date
                start_date = self._format_date(task.get("start_date"))
                start_item = QTableWidgetItem(start_date)
                self.task_table.setItem(row, col, start_item)
                col += 1
                
                # End Date
                end_date = self._format_date(task.get("end_date"))
                end_item = QTableWidgetItem(end_date)
                self.task_table.setItem(row, col, end_item)
                col += 1
                
                # Percent Done
                percent_done = task.get("percent_done", 0)
                percent_item = QTableWidgetItem(f"{percent_done}%")
                percent_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.task_table.setItem(row, col, percent_item)
                col += 1
                
                # Done status
                done = task.get("done", False)
                done_item = QTableWidgetItem("Yes" if done else "")
                done_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.task_table.setItem(row, col, done_item)
                col += 1
                
                # Favorite
                is_favorite = task.get("is_favorite", False)
                favorite_item = QTableWidgetItem("*" if is_favorite else "")
                favorite_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.task_table.setItem(row, col, favorite_item)
                col += 1
                
                # Estimated Duration (from local database)
                est_duration = self._get_estimated_duration(task_id)
                if est_duration:
                    # Format as hours and minutes if >= 60 minutes
                    if est_duration >= 60:
                        hours = est_duration // 60
                        minutes = est_duration % 60
                        if minutes > 0:
                            duration_str = f"{hours}h {minutes}m"
                        else:
                            duration_str = f"{hours}h"
                    else:
                        duration_str = f"{est_duration}m"
                else:
                    duration_str = ""
                duration_item = QTableWidgetItem(duration_str)
                duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.task_table.setItem(row, col, duration_item)
                col += 1
                
                # Actions - create button layout with Edit, Delete, and Toggle
                actions_widget = QWidget()
                actions_layout = QHBoxLayout()
                actions_layout.setContentsMargins(2, 2, 2, 2)
                actions_layout.setSpacing(2)
                
                edit_btn = QPushButton("Edit")
                edit_btn.setMaximumWidth(60)
                edit_btn.clicked.connect(lambda checked, tid=task_id: self.edit_task(tid))
                actions_layout.addWidget(edit_btn)
                
                delete_btn = QPushButton("Delete")
                delete_btn.setMaximumWidth(60)
                delete_btn.clicked.connect(lambda checked, tid=task_id: self.delete_task(tid))
                actions_layout.addWidget(delete_btn)
                
                toggle_btn = QPushButton("Toggle")
                toggle_btn.setMaximumWidth(60)
                toggle_btn.clicked.connect(lambda checked, tid=task_id, d=done: self.toggle_task(tid, not d))
                actions_layout.addWidget(toggle_btn)
                
                actions_widget.setLayout(actions_layout)
                self.task_table.setCellWidget(row, col, actions_widget)
            
            # Resize columns to fit content, but set minimum widths for readability
            self.task_table.resizeColumnsToContents()
            # Set minimum column widths for better readability
            self.task_table.setColumnWidth(1, max(150, self.task_table.columnWidth(1)))  # Title
            self.task_table.setColumnWidth(2, max(200, self.task_table.columnWidth(2)))  # Description
            self.task_table.setColumnWidth(4, max(100, self.task_table.columnWidth(4)))  # Due Date
            self.task_table.setColumnWidth(5, max(100, self.task_table.columnWidth(5)))  # Start Date
            self.task_table.setColumnWidth(6, max(100, self.task_table.columnWidth(6)))  # End Date
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
        estimated_duration = self.estimated_duration_spin.value()
        
        try:
            # Create task via API
            task_result = self.client.create_task(self.current_project_id, title, priority=priority)
            
            # Save estimated duration to local database if provided
            task_id = task_result.get("id") if isinstance(task_result, dict) else None
            if task_id and estimated_duration > 0:
                self._save_estimated_duration(task_id, estimated_duration)
            
            # Clear inputs
            self.task_title_input.clear()
            self.estimated_duration_spin.setValue(0)
            
            # Reload tasks to show the new task
            self.load_tasks()
            # No success popup - only show errors
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
    
    def edit_task(self, task_id: int):
        """Edit an existing task."""
        if not self.client or not task_id:
            return
        
        # Get task data
        task = self.task_data.get(task_id)
        if not task:
            QMessageBox.warning(self, "Error", "Task data not found")
            return
        
        # Create edit dialog
        dialog = TaskEditDialog(self, task)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                # Get updated values from dialog
                updates = dialog.get_task_data()
                
                # Convert dates to ISO format if provided
                due_date = None
                if updates.get('due_date'):
                    due_date = updates['due_date'].toString(Qt.DateFormat.ISODate)
                
                # Update task via API
                self.client.update_task(
                    task_id=task_id,
                    title=updates.get('title'),
                    description=updates.get('description'),
                    priority=updates.get('priority'),
                    due_date=due_date,
                    done=updates.get('done', False)
                )
                
                # Save estimated duration to local database if provided
                estimated_duration = updates.get('estimated_duration', 0)
                if estimated_duration > 0:
                    self._save_estimated_duration(task_id, estimated_duration)
                else:
                    # If set to 0, remove the record (optional - could keep it)
                    self._save_estimated_duration(task_id, None)
                
                # Reload tasks to show updates
                self.load_tasks()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to update task: {e}")
    
    def delete_task(self, task_id: int):
        """Delete a task."""
        if not self.client or not task_id:
            return
        
        # Get task title for confirmation
        task = self.task_data.get(task_id)
        task_title = task.get('title', 'this task') if task else 'this task'
        
        # Confirm deletion
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete task '{task_title}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.client.delete_task(task_id)
                # Remove from local cache
                if task_id in self.task_data:
                    del self.task_data[task_id]
                # Reload tasks
                self.load_tasks()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete task: {e}")


class TaskEditDialog(QDialog):
    """Dialog for editing a task."""
    
    def __init__(self, parent=None, task_data=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Task")
        self.task_data = task_data or {}
        self.parent_tab = parent  # Store reference to parent TasksTab
        self.init_ui()
    
    def init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout()
        
        form_layout = QFormLayout()
        
        # Title
        self.title_input = QLineEdit()
        self.title_input.setText(self.task_data.get('title', ''))
        form_layout.addRow("Title:", self.title_input)
        
        # Description
        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(100)
        self.description_input.setPlainText(self.task_data.get('description', ''))
        form_layout.addRow("Description:", self.description_input)
        
        # Priority
        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(0, 5)
        self.priority_spin.setValue(self.task_data.get('priority', 0))
        form_layout.addRow("Priority:", self.priority_spin)
        
        # Due date
        self.due_date_input = QDateEdit()
        self.due_date_input.setCalendarPopup(True)
        due_date_str = self.task_data.get('due_date')
        if due_date_str:
            try:
                # Try to parse ISO date format
                from datetime import datetime
                date_obj = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
                self.due_date_input.setDate(QDate(date_obj.year, date_obj.month, date_obj.day))
            except:
                self.due_date_input.setDate(QDate.currentDate())
        else:
            self.due_date_input.setDate(QDate.currentDate())
        form_layout.addRow("Due Date:", self.due_date_input)
        
        # Done status
        from PyQt6.QtWidgets import QCheckBox
        self.done_checkbox = QCheckBox()
        self.done_checkbox.setChecked(self.task_data.get('done', False))
        form_layout.addRow("Completed:", self.done_checkbox)
        
        # Estimated Duration (in minutes)
        # Load existing estimated duration from database if available
        task_id = self.task_data.get('id')
        existing_duration = None
        if task_id and self.parent_tab and hasattr(self.parent_tab, '_get_estimated_duration'):
            existing_duration = self.parent_tab._get_estimated_duration(task_id)
        
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("Est. Duration (minutes):"))
        self.estimated_duration_spin = QSpinBox()
        self.estimated_duration_spin.setRange(0, 10080)  # 0 to 7 days (in minutes)
        self.estimated_duration_spin.setValue(existing_duration if existing_duration else 0)
        self.estimated_duration_spin.setSuffix(" min")
        duration_layout.addWidget(self.estimated_duration_spin)
        duration_layout.addStretch()
        form_layout.addRow("", duration_layout)  # Empty label since we have label in layout
        
        layout.addLayout(form_layout)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def get_task_data(self):
        """Get the task data from the dialog."""
        return {
            'title': self.title_input.text().strip(),
            'description': self.description_input.toPlainText().strip(),
            'priority': self.priority_spin.value(),
            'due_date': self.due_date_input.date(),
            'done': self.done_checkbox.isChecked(),
            'estimated_duration': self.estimated_duration_spin.value()
        }
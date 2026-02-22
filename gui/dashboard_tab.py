from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QCheckBox, QComboBox, QInputDialog, QMessageBox, QDateEdit, QHeaderView, QAbstractItemView, QSizePolicy
from PyQt6.QtCore import Qt, QTimer, QDate, QThread, pyqtSignal, QMetaObject, Q_ARG
from datetime import datetime, timedelta
from dateutil import parser
import sqlite3
import sys
import os
import time

# Import centralized database path
from config import DATABASE_PATH

class NewsWorker(QThread):
    """Worker thread for loading news without blocking the UI."""
    news_loaded = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, chat_handler):
        super().__init__()
        self.chat_handler = chat_handler
    
    def run(self):
        try:
            print(f"NewsWorker: Loading news... chat_handler type: {type(self.chat_handler)}")
            
            # Use a direct search query to avoid multiple API calls
            direct_search_query = "recent MedTech news AI machine learning IVD SaMD FDA regulations guidances medical devices EHR electronic health records clinical decision support generative AI"

            # Optional: seed relevance from Gmail label "News" subjects
            try:
                subjects = []
                if hasattr(self.chat_handler, "chat_handler") and hasattr(self.chat_handler.chat_handler, "data_fetcher"):
                    df = self.chat_handler.chat_handler.data_fetcher
                    if hasattr(df, "get_gmail_news_seeds"):
                        subjects = df.get_gmail_news_seeds(days=3, max_messages=15) or []
                if subjects:
                    # Light keyword extraction: take frequent tokens
                    import re
                    counts = {}
                    for s in subjects:
                        for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\\-]{2,}", s or ""):
                            lw = w.lower()
                            if lw in {"the","and","for","with","your","from","this","that","news","update","weekly","daily"}:
                                continue
                            counts[lw] = counts.get(lw, 0) + 1
                    keywords = [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:6]]
                    if keywords:
                        direct_search_query = direct_search_query + " " + " ".join(keywords)
            except Exception:
                pass
            
            # Use the chat handler to get news
            if hasattr(self.chat_handler, 'get_response'):
                print("NewsWorker: Chat handler has get_response method")
                
                # Single API call with direct search query
                news_query = self.chat_handler.get_response(
                    f"WEB_SEARCH:{direct_search_query}", 
                    session_id="dashboard_news_query", 
                    conversation_history=[]
                )
                
                # Clean up the query if it contains WEB_SEARCH: prefix
                if "WEB_SEARCH:" in news_query:
                    news_query = news_query.split("WEB_SEARCH:")[1].strip()
                else:
                    news_query = news_query.strip()
                
                print(f"NewsWorker: Got news response: {news_query[:100]}...")
                self.news_loaded.emit(news_query)
            else:
                self.error_occurred.emit("Chat handler does not have get_response method")
                
        except Exception as e:
            print(f"NewsWorker: Error loading news: {e}")
            self.error_occurred.emit(f"Error loading news: {str(e)}")


class BriefingWorker(QThread):
    """Worker thread for loading daily briefing without blocking the UI."""
    briefing_loaded = pyqtSignal(str, object)  # Emits (briefing_text, chat_handler_obj)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, chat_handler):
        super().__init__()
        self.chat_handler = chat_handler
    
    def run(self):
        try:
            print(f"BriefingWorker: Loading briefing... chat_handler type: {type(self.chat_handler)}")
            
            # Get briefing from chat_handler - handle both ChatManager and ChatHandler
            briefing = None
            chat_handler_obj = None
            
            if hasattr(self.chat_handler, 'start_briefing'):
                # It's a ChatManager
                briefing = self.chat_handler.start_briefing()
                chat_handler_obj = self.chat_handler.chat_handler if hasattr(self.chat_handler, 'chat_handler') else None
            elif hasattr(self.chat_handler, 'chat_handler') and hasattr(self.chat_handler.chat_handler, 'start_briefing'):
                # Nested ChatManager
                briefing = self.chat_handler.chat_handler.start_briefing()
                chat_handler_obj = self.chat_handler.chat_handler.chat_handler if hasattr(self.chat_handler.chat_handler, 'chat_handler') else None
            elif hasattr(self.chat_handler, 'daily_briefing'):
                # It's a ChatHandler directly
                chat_handler_obj = self.chat_handler
                briefing = self.chat_handler.daily_briefing()
            
            if briefing:
                print(f"BriefingWorker: Got briefing ({len(briefing)} chars)")
                self.briefing_loaded.emit(briefing, chat_handler_obj)
            else:
                self.error_occurred.emit("Briefing already shown today or not available")
                
        except Exception as e:
            print(f"BriefingWorker: Error loading briefing: {e}")
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(f"Error loading briefing: {str(e)}")

import re

class DashboardTab(QWidget):
    def __init__(self, chat_handler, todo_list, db, parent=None):
        super().__init__(parent)
        self.chat_handler = chat_handler
        self.todo_list = todo_list
        self.db = db
        # Update TodoList's parent to point to this dashboard tab
        if self.todo_list:
            self.todo_list.parent = self
            # Set up the todo list filters in the dashboard
            self.setup_todo_filters()
        self.setup_ui()
        print("DEBUG: DashboardTab initialized, about to call load_tasks_filtered")

    def setup_todo_filters(self):
        """Set up the todo list filter controls in the dashboard."""
        if not self.todo_list:
            return

        # Get the filter layout from TodoList
        filter_layout = QHBoxLayout()
        self.category_filter = QComboBox()
        self.category_filter.addItems(["All", "Business", "Personal"])
        self.category_filter.currentTextChanged.connect(self.load_tasks_filtered)
        filter_layout.addWidget(QLabel("Category:"))
        filter_layout.addWidget(self.category_filter)

        self.date_filter = QComboBox()
        self.date_filter.addItems(["All", "Today", "Overdue", "No Date", "Specific Date"])
        self.date_filter.currentTextChanged.connect(self.load_tasks_filtered)
        filter_layout.addWidget(QLabel("Due Date:"))
        filter_layout.addWidget(self.date_filter)

        self.date_range = QDateEdit()
        self.date_range.setCalendarPopup(True)
        self.date_range.setDate(QDate.currentDate())
        self.date_range.dateChanged.connect(self.load_tasks_filtered)
        filter_layout.addWidget(QLabel("Specific Date:"))
        filter_layout.addWidget(self.date_range)
        filter_layout.addStretch()

        # Add the filter layout to the dashboard's left column layout
        # We'll store it for later use in setup_ui
        self.filter_layout = filter_layout

    def load_tasks_filtered(self):
        """Load tasks with current filter settings using batch optimization."""
        try:
            category_filter = self.category_filter.currentText()
            date_filter = self.date_filter.currentText()
            specific_date = self.date_range.date().toString("MM-dd-yyyy") if date_filter == "Specific Date" else None

            print(f"DEBUG: Filter values - category: '{category_filter}', date_filter: '{date_filter}', specific_date: '{specific_date}'")

            # Get filtered tasks from database
            tasks = self.db.get_tasks(
                category=category_filter if category_filter != "All" else None,
                date_filter=date_filter,
                specific_date=specific_date
            )

            print(f"DEBUG: Retrieved {len(tasks)} tasks from database")

            # Clear current tasks
            self.task_list.setRowCount(0)

            if tasks:
                print(f"DEBUG: Loading {len(tasks)} tasks with batch optimization...")
                
                # CRITICAL: Disable auto-repaint to prevent widget detachment during loading
                self.task_list.setUpdatesEnabled(False)
                
                try:
                    # BATCH OPTIMIZATION: Load all rows first, then style in one pass
                    # Step 1: Create all rows and widgets without styling
                    styling_data_list = []
                    for task_id, task_text, due_date, category, recurrence, completed in tasks:
                        row_position = self.task_list.rowCount()
                        self.task_list.insertRow(row_position)
                        print(f"DEBUG: Creating row {row_position} for task {task_id}: {task_text[:30]}...")
                        
                        # Create and set widgets without styling
                        self._create_task_row_widgets(row_position, task_id, task_text, due_date, category, recurrence, completed)
                        
                        # Store styling data for batch processing
                        styling_data_list.append((row_position, due_date, completed))
                    
                finally:
                    # CRITICAL: Re-enable auto-repaint after all operations complete
                    self.task_list.setUpdatesEnabled(True)
                    print("DEBUG: Re-enabled table updates")
                
                # Step 2: Apply styling to all rows AFTER updates are enabled
                for row_position, due_date, completed in styling_data_list:
                    self.apply_task_styling_css(row_position, due_date, completed)
                
                # Step 3: Final UI refresh
                print("DEBUG: Performing final UI refresh...")
                from PyQt6.QtWidgets import QApplication
                QApplication.processEvents()
                    
            print(f"DEBUG: Finished loading {len(tasks)} tasks")

        except Exception as e:
            print(f"Error loading filtered tasks: {e}")
            import traceback
            traceback.print_exc()

    def _create_task_row_widgets(self, row_position, task_id, task_text, due_date, category, recurrence, completed):
        """Create task row widgets without applying styling (for batch loading)."""
        try:
            # Create task widget with checkbox and label
            task_widget = QWidget()
            task_widget.setStyleSheet("QWidget { background-color: transparent; }")
            task_layout = QHBoxLayout(task_widget)
            task_layout.setContentsMargins(5, 5, 5, 5)
            task_layout.setSpacing(8)

            # Checkbox
            checkbox = QCheckBox()
            checkbox.setChecked(completed)
            checkbox.setStyleSheet("""
                QCheckBox {
                    background-color: transparent;
                    color: #e8eaed;
                    font-weight: 500;
                    padding: 2px;
                }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                    background-color: #22252c;
                    border: 1px solid #2e2f32;
                    border-radius: 3px;
                }
                QCheckBox::indicator:checked {
                    background-color: #FD6262;
                    border: 1px solid #FD6262;
                }
            """)
            checkbox.stateChanged.connect(lambda state, tid=task_id: self.update_task_status(tid, state == Qt.CheckState.Checked.value))
            task_layout.addWidget(checkbox)

            # Task label
            task_label = QLabel(f"  {task_text}")  # Add spaces at the beginning for left alignment
            task_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            task_label.setStyleSheet("""
                QLabel {
                    color: #e8eaed;
                    font-size: 13px;
                    padding-left: 5px;
                    text-align: left;
                    margin: 0px;
                    background-color: transparent;
                    font-weight: normal;
                }
            """)
            task_layout.addWidget(task_label)

            # CRITICAL: Set parent before adding to table to prevent widget detachment
            task_widget.setParent(self.task_list)
            self.task_list.setCellWidget(row_position, 0, task_widget)

            # Category item (column 1)
            category_item = QTableWidgetItem(category)
            category_item.setFlags(category_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.task_list.setItem(row_position, 1, category_item)

            # Due date item (column 2)
            due_date_display = due_date if due_date else "No due date"
            due_date_item = QTableWidgetItem(due_date_display)
            due_date_item.setFlags(due_date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.task_list.setItem(row_position, 2, due_date_item)

            # Actions widget (column 3)
            actions_widget = QWidget()
            actions_widget.setStyleSheet("QWidget { background-color: transparent; }")
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            actions_layout.setSpacing(5)

            # Edit button
            edit_btn = QPushButton("Edit")
            edit_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            edit_btn.setMinimumSize(50, 35)
            edit_btn.setMaximumSize(80, 45)
            edit_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FD6262;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-weight: 500;
                    font-size: 12px;
                    margin: 2px;
                    min-width: 60px;
                }
                QPushButton:hover {
                    background-color: #e85555;
                }
            """)
            edit_btn.clicked.connect(lambda checked, r=row_position, tid=task_id: self.edit_task(r, tid))
            actions_layout.addWidget(edit_btn)

            # Delete button
            delete_btn = QPushButton("Delete")
            delete_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            delete_btn.setMinimumSize(60, 35)
            delete_btn.setMaximumSize(90, 45)
            delete_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3a3b3e;
                    color: #e8eaed;
                    border: 1px solid #2e2f32;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-weight: 500;
                    font-size: 12px;
                    margin: 2px;
                    min-width: 60px;
                }
                QPushButton:hover {
                    background-color: #4a4a4e;
                }
            """)
            delete_btn.clicked.connect(lambda checked, r=row_position, tid=task_id: self.delete_task(r, tid))
            actions_layout.addWidget(delete_btn)

            # CRITICAL: Set parent before adding to table to prevent widget detachment
            actions_widget.setParent(self.task_list)
            self.task_list.setCellWidget(row_position, 3, actions_widget)

            # Store task data for later use
            task_widget.task_data = {
                'id': task_id,
                'text': task_text,
                'due_date': due_date,
                'category': category,
                'recurrence': recurrence,
                'completed': completed
            }

            print(f"DEBUG: Created widgets for row {row_position}, task: {task_text[:30]}...")

        except Exception as e:
            print(f"Error creating task row widgets: {e}")

    def add_task_to_table(self, task_id, task_text, due_date, category, recurrence, completed):
        """Add an existing task to the table (single task version)."""
        try:
            print(f"DEBUG: add_task_to_table called with task_id={task_id}, task_text='{task_text}', category='{category}'")
            row_position = self.task_list.rowCount()
            self.task_list.insertRow(row_position)

            # Create widgets without styling
            self._create_task_row_widgets(row_position, task_id, task_text, due_date, category, recurrence, completed)

            # Apply styling immediately for single task
            self.apply_task_styling_css(row_position, due_date, completed)

        except Exception as e:
            print(f"Error adding task to table: {e}")

    def add_task(self):
        """Add a new task from the input field."""
        task_text = self.taskInput.text().strip()
        if not task_text:
            return

        # Get the selected due date
        due_date = self.dueDateInput.date().toString("MM-dd-yyyy")

        # Get the selected category and recurrence
        category = self.categoryInput.currentText()
        recurrence = self.recurrenceInput.currentText()

        try:
            # Use the database method to add the task
            task_id = self.db.add_task(
                session_id=f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                task_text=task_text,
                due_date=due_date,
                category=category,
                recurrence=recurrence,
                completed=0
            )

            # Add to table display
            print(f"DEBUG: About to call add_task_to_table with task_id={task_id}, task_text='{task_text}', due_date='{due_date}', category='{category}'")
            self.add_task_to_table(task_id, task_text, due_date, category, recurrence, 0)

            # Clear input fields
            self.taskInput.clear()

        except Exception as e:
            print(f"Error adding task: {e}")
            QMessageBox.critical(self, "Error", f"Failed to add task: {str(e)}")

    def setup_ui(self):
        # Set the overall dark theme for the dashboard (professional palette)
        self.setStyleSheet("""
            QWidget {
                background-color: #15171c;
                color: #e8eaed;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Header
        dashboard_header = QLabel("Dashboard - Overview")
        dashboard_header.setStyleSheet("color: #e8eaed; font-weight: 600; font-size: 16px; padding: 10px; background-color: transparent; border: none;")
        dashboard_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(dashboard_header)
        
        # Daily Briefing Widget (top of dashboard)
        briefing_widget = self.create_briefing_widget()
        layout.addWidget(briefing_widget)
        
        # Main horizontal layout for left and right columns
        main_layout = QHBoxLayout()
        main_layout.setSpacing(10)
        
        # Left column: Schedule and Task List
        left_column = QVBoxLayout()
        left_column.setSpacing(10)
        
        # Top: Schedule
        schedule_widget = self.create_schedule_widget()
        left_column.addWidget(schedule_widget)
        
        # Bottom: Task List
        task_widget = self.create_task_widget()
        left_column.addWidget(task_widget)
        
        # Right column: News Feed
        news_widget = self.create_news_widget()
        
        # Add columns to main layout
        main_layout.addLayout(left_column, 2)  # Left column takes 2/3 of space
        main_layout.addWidget(news_widget, 1)  # Right column takes 1/3 of space
        
        layout.addLayout(main_layout)
        
        # Add refresh button at bottom
        refresh_layout = QHBoxLayout()
        refresh_layout.addStretch()
        
        refresh_news_btn = QPushButton("Refresh News")
        refresh_news_btn.setStyleSheet("background-color: #FD6262; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 500;")
        refresh_news_btn.clicked.connect(self.refresh_news_feed)
        refresh_layout.addWidget(refresh_news_btn)
        
        layout.addLayout(refresh_layout)
        
        # Setup auto-refresh timer for schedule (every 15 minutes)
        self.schedule_timer = QTimer()
        self.schedule_timer.timeout.connect(self.load_schedule)
        self.schedule_timer.start(900000)  # 15 minutes
        
        # Initial loads
        self.load_schedule()
        self.load_news()
        # Load daily briefing if available (with delay to let other components initialize)
        try:
            from config import BRIEFING_AND_EMAIL_DISABLED
        except ImportError:
            BRIEFING_AND_EMAIL_DISABLED = False
        if not BRIEFING_AND_EMAIL_DISABLED:
            QTimer.singleShot(2000, self.load_daily_briefing)
        else:
            QTimer.singleShot(500, self._show_briefing_disabled)

    def create_task_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header
        task_header = QLabel("Task List")
        task_header.setStyleSheet("color: #e8eaed; font-weight: 600; padding: 3px; background-color: transparent; border: none; font-size: 13px;")
        task_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        task_header.setMaximumHeight(25)
        layout.addWidget(task_header)
        
        # Task list - back to QTableWidget but with custom delegate for row coloring
        self.task_list = QTableWidget()
        self.task_list.setColumnCount(4)
        self.task_list.setHorizontalHeaderLabels(["Task", "Category", "Due Date", "Actions"])
        self.task_list.setAlternatingRowColors(False)  # We'll handle colors manually
        self.task_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.task_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Professional dark table styling
        self.task_list.setStyleSheet("""
            QTableWidget {
                background-color: #1c1e24;
                color: #e8eaed;
                gridline-color: #2e2f32;
            }
            QHeaderView::section {
                background-color: #22252c;
                color: #e8eaed;
                padding: 8px;
                border: 1px solid #2e2f32;
                font-weight: 600;
                font-size: 13px;
                min-height: 30px;
            }
            QTableWidget::item {
                padding: 8px;
                border: none;
                color: #e8eaed;
                background-color: transparent;
            }
        """)
        
        # Configure columns
        header = self.task_list.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Task column stretches
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)  # Category fixed width
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)  # Due Date fixed width
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # Actions fixed width
        header.resizeSection(1, 100)  # Set Category column to 100px width
        header.resizeSection(2, 100)  # Set Due Date column to 100px width
        header.resizeSection(3, 200)  # Set Actions column to 200px width
        
        # Enable sorting
        self.task_list.setSortingEnabled(True)
        
        # QTableWidget handles clicks automatically
        
        # Enable context menu
        self.task_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.task_list.customContextMenuRequested.connect(self.show_task_context_menu)
        
        # Disable double-click to prevent errors with QTableWidgetItem
        # self.task_list.itemDoubleClicked.connect(self.edit_task)
        
        
        # Set default sorting by due date (column 1) in ascending order
        # self.task_list.sortByColumn(1, Qt.SortOrder.AscendingOrder)  # Disabled to prevent widget loss
        
        # Store task styling data
        self.task_styling = {}

        # Add filter controls if available
        if hasattr(self, 'filter_layout'):
            layout.addLayout(self.filter_layout)

        layout.addWidget(self.task_list)
        
        # Quick add task
        add_layout = QHBoxLayout()
        self.taskInput = QLineEdit()
        self.taskInput.setPlaceholderText("Quick task...")
        self.taskInput.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; padding: 8px 12px; border-radius: 6px;")
        self.taskInput.returnPressed.connect(self.add_task)
        add_layout.addWidget(self.taskInput)
        
        # Add due date input
        self.dueDateInput = QDateEdit()
        self.dueDateInput.setCalendarPopup(True)
        self.dueDateInput.setDate(QDate.currentDate())
        self.dueDateInput.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; padding: 8px; border-radius: 6px;")
        add_layout.addWidget(self.dueDateInput)

        # Add category input
        self.categoryInput = QComboBox()
        self.categoryInput.addItems(["Business", "Personal"])
        self.categoryInput.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; padding: 8px; border-radius: 6px;")
        add_layout.addWidget(self.categoryInput)

        # Add recurrence input
        self.recurrenceInput = QComboBox()
        self.recurrenceInput.addItems(["None", "Daily", "Weekly"])
        self.recurrenceInput.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; padding: 8px; border-radius: 6px;")
        add_layout.addWidget(self.recurrenceInput)
        
        add_btn = QPushButton("Add")
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #FD6262;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #e85555;
            }
        """)
        add_btn.clicked.connect(self.add_task)
        add_layout.addWidget(add_btn)
        
        layout.addLayout(add_layout)
        
        # Archive completed tasks button
        archive_btn = QPushButton("Archive Completed Tasks")
        archive_btn.setStyleSheet("""
            QPushButton {
                background-color: #FD6262;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #e85555;
            }
        """)
        archive_btn.clicked.connect(self.archive_completed_tasks)
        layout.addWidget(archive_btn)
        
        # Load initial tasks
        self.load_tasks_filtered()
        
        return widget


    def edit_task(self, row, column=None):
        """Edit a task using a custom dialog with calendar."""
        try:
            # Get task data from the task widget
            task_widget = self.task_list.cellWidget(row, 0)
            if not task_widget or not hasattr(task_widget, 'task_data'):
                return
            
            task_data = task_widget.task_data
            task_text = task_data['text']  # Changed from 'task_text' to 'text'
            due_date = task_data['due_date']
            
            # Create custom edit dialog
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QDateEdit
            from PyQt6.QtCore import QDate
            
            edit_dialog = QDialog(self)
            edit_dialog.setWindowTitle("Edit Task")
            edit_dialog.setModal(True)
            edit_dialog.setStyleSheet("""
                QDialog {
                    background-color: #15171c;
                    color: #e8eaed;
                }
                QLabel {
                    color: #e8eaed;
                    font-weight: 600;
                }
                QLineEdit {
                    background-color: #22252c;
                    color: #e8eaed;
                    border: 1px solid #2e2f32;
                    padding: 8px;
                    border-radius: 6px;
                    font-size: 13px;
                }
                QDateEdit {
                    background-color: #22252c;
                    color: #e8eaed;
                    border: 1px solid #2e2f32;
                    padding: 8px;
                    border-radius: 6px;
                    font-size: 13px;
                    min-height: 30px;
                }
                QPushButton {
                    background-color: #FD6262;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-size: 13px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: #e85555;
                }
                QPushButton#cancelButton {
                    background-color: #3a3b3e;
                }
                QPushButton#cancelButton:hover {
                    background-color: #4a4a4e;
                }
            """)
            
            # Set responsive dialog size and center it
            edit_dialog.setMinimumSize(400, 320)
            edit_dialog.resize(450, 350)
            
            layout = QVBoxLayout(edit_dialog)
            layout.setSpacing(15)
            layout.setContentsMargins(20, 20, 20, 20)
            
            # Task text input
            task_label = QLabel("Task:")
            layout.addWidget(task_label)
            
            task_input = QLineEdit()
            task_input.setText(task_text)
            task_input.setPlaceholderText("Enter task description...")
            layout.addWidget(task_input)
            
            # Due date input with calendar
            date_label = QLabel("Due Date:")
            layout.addWidget(date_label)
            
            date_input = QDateEdit()
            date_input.setCalendarPopup(True)
            if due_date and due_date != "No due date":
                try:
                    # Parse the existing date
                    date_obj = datetime.strptime(due_date, "%m-%d-%Y")
                    date_input.setDate(QDate(date_obj.year, date_obj.month, date_obj.day))
                except ValueError:
                    date_input.setDate(QDate.currentDate())
            else:
                date_input.setDate(QDate.currentDate())
            layout.addWidget(date_input)
            
            # Category input
            category_label = QLabel("Category:")
            layout.addWidget(category_label)
            
            category_input = QComboBox()
            category_input.addItems(["Business", "Personal"])
            # Set current category
            current_category = task_data.get('category', 'Business')
            if current_category == "Personal":
                category_input.setCurrentIndex(1)
            else:
                category_input.setCurrentIndex(0)
            layout.addWidget(category_input)
            
            # Buttons
            button_layout = QHBoxLayout()
            button_layout.addStretch()
            
            cancel_btn = QPushButton("Cancel")
            cancel_btn.setObjectName("cancelButton")
            cancel_btn.clicked.connect(edit_dialog.reject)
            button_layout.addWidget(cancel_btn)
            
            save_btn = QPushButton("Save Changes")
            save_btn.clicked.connect(edit_dialog.accept)
            button_layout.addWidget(save_btn)
            
            layout.addLayout(button_layout)
            
            # Set focus to task input and select all text
            task_input.setFocus()
            task_input.selectAll()
            
            # Show dialog and handle result
            if edit_dialog.exec() == QDialog.DialogCode.Accepted:
                new_text = task_input.text().strip()
                new_date = date_input.date().toString("MM-dd-yyyy")
                new_category = category_input.currentText()
                
                if not new_text:
                    QMessageBox.warning(self, "Error", "Task text cannot be empty")
                    return
                
                # Update the task in the database
                try:
                    db_name = DATABASE_PATH
                    task_id = task_data['id']
                    with sqlite3.connect(db_name) as conn:
                        conn.execute("""
                            UPDATE tasks SET task_text = ?, due_date = ?, category = ? WHERE id = ?
                        """, (new_text, new_date, new_category, task_id))
                        conn.commit()
                    
                    # Update the task widget and refresh the display
                    task_data['text'] = new_text
                    task_data['due_date'] = new_date
                    task_data['category'] = new_category
                    task_widget.task_data = task_data
                    
                    # Refresh the entire task list to show changes
                    print(f"DEBUG: About to call load_tasks() from edit_task at {time.time():.6f}")
                    self.load_tasks_filtered()
                    
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to update task: {str(e)}")
                    
        except Exception as e:
            print(f"Error editing task: {e}")
            QMessageBox.critical(self, "Error", f"Failed to edit task: {str(e)}")

    def delete_task(self, row, column=None):
        """Delete a task."""
        try:
            # Get task data from the task widget
            task_widget = self.task_list.cellWidget(row, 0)
            if not task_widget or not hasattr(task_widget, 'task_data'):
                return
            
            task_data = task_widget.task_data
            task_text = task_data['text']  # Changed from 'task_text' to 'text'
            
            reply = QMessageBox.question(self, "Delete Task",
                                       f"Are you sure you want to delete '{task_text}'?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                db_name = DATABASE_PATH
                task_id = task_data['id']
                with sqlite3.connect(db_name) as conn:
                    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                    conn.commit()
                
                # Remove the row from the table
                self.task_list.removeRow(row)
                    
        except Exception as e:
            print(f"Error deleting task: {e}")
            QMessageBox.critical(self, "Error", f"Failed to delete task: {str(e)}")

    def show_task_context_menu(self, position):
        """Show context menu for task items."""
        item = self.task_list.itemAt(position)
        if item is None:
            return
            
        # Check if it's a valid task item (not error messages)
        task_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not task_data:
            return
        
        # Get row index (item may be in any column)
        row = item.row()
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        
        context_menu = QMenu(self)
        
        # Edit action
        edit_action = QAction("Edit Task", self)
        edit_action.triggered.connect(lambda: self.edit_task(row, 0))
        context_menu.addAction(edit_action)
        
        # Delete action
        delete_action = QAction("Delete Task", self)
        delete_action.triggered.connect(lambda: self.delete_task(row, 0))
        context_menu.addAction(delete_action)
        
        # Show menu
        context_menu.exec(self.task_list.mapToGlobal(position))


    def archive_completed_tasks(self):
        """Archive completed tasks."""
        try:
            db_name = DATABASE_PATH
            with sqlite3.connect(db_name) as conn:
                # Get completed tasks with all fields
                cursor = conn.execute("SELECT task_text, due_date, category, recurrence, completed, session_id FROM tasks WHERE completed = 1")
                completed_tasks = cursor.fetchall()
                
                if completed_tasks:
                    # Archive each task using the database method
                    for task_text, due_date, category, recurrence, completed, session_id in completed_tasks:
                        # Use the database method to archive
                        self.db.archive_task(task_text, due_date, category, recurrence, completed)
                    
                    # Delete from active tasks
                    conn.execute("DELETE FROM tasks WHERE completed = 1")
                    conn.commit()
                    
                    print(f"Archived {len(completed_tasks)} completed tasks")
                    self.load_tasks_filtered()  # Refresh the display
                else:
                    print("No completed tasks to archive")
        except Exception as e:
            print(f"Error archiving tasks: {e}")

    def update_task_status(self, task_id, completed, row=None):
        """Update task completion status in database."""
        start_time = time.time()
        print(f"TIMING: update_task_status START for task_id {task_id}, completed {completed}, row {row} at {start_time:.6f}")
        
        # Skip if we're currently loading tasks to prevent widget conflicts
        if hasattr(self, '_loading_tasks') and self._loading_tasks:
            print(f"TIMING: Skipping update_task_status during loading at {time.time():.6f}")
            return
            
        try:
            db_name = DATABASE_PATH
            with sqlite3.connect(db_name) as conn:
                conn.execute("UPDATE tasks SET completed = ? WHERE id = ?", (completed, task_id))
                conn.commit()
            
            # Find the row with this task and update styling
            print(f"TIMING: About to search for task_id {task_id} at {time.time():.6f}")
            for row in range(self.task_list.rowCount()):
                task_widget = self.task_list.cellWidget(row, 0)
                if task_widget and hasattr(task_widget, 'task_data') and task_widget.task_data['id'] == task_id:
                    due_date_item = self.task_list.item(row, 2)  # Column 2 is the due date column
                    if due_date_item:
                        due_date = due_date_item.text()
                        print(f"TIMING: About to call apply_task_styling_css from update_task_status for row {row} at {time.time():.6f}")
                        self.apply_task_styling_css(row, due_date, completed)
                        break
        except Exception as e:
            print(f"Error updating task status: {e}")

    def on_task_double_clicked(self, item):
        task_text = item.data(Qt.ItemDataRole.UserRole)
        if task_text:
            # Use the same database path as the main application
            db_name = DATABASE_PATH
                
            with sqlite3.connect(db_name) as conn:
                conn.execute("""
                    UPDATE tasks SET completed = 1 WHERE task = ?
                """, (task_text,))
                conn.commit()
            self.load_tasks_filtered()

    def create_briefing_widget(self):
        """Create the daily briefing widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header with refresh button
        header_layout = QHBoxLayout()
        briefing_header = QLabel("Daily Briefing")
        briefing_header.setStyleSheet("color: #e8eaed; font-weight: 600; padding: 3px; background-color: transparent; border: none; font-size: 13px;")
        header_layout.addWidget(briefing_header)
        header_layout.addStretch()
        
        refresh_briefing_btn = QPushButton("Refresh")
        refresh_briefing_btn.setStyleSheet("background-color: #FD6262; color: white; border: none; padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 500;")
        refresh_briefing_btn.clicked.connect(self.refresh_daily_briefing)
        header_layout.addWidget(refresh_briefing_btn)
        layout.addLayout(header_layout)
        
        # Briefing display
        self.briefing_display = QTextBrowser()
        self.briefing_display.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; border-radius: 6px; font-size: 13px;")
        self.briefing_display.setReadOnly(True)
        self.briefing_display.setPlaceholderText("Loading daily briefing...")
        self.briefing_display.setOpenExternalLinks(True)
        layout.addWidget(self.briefing_display)
        
        return widget

    def create_schedule_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header
        schedule_header = QLabel("Today's Schedule")
        schedule_header.setStyleSheet("color: #e8eaed; font-weight: 600; padding: 3px; background-color: transparent; border: none; font-size: 13px;")
        schedule_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        schedule_header.setMaximumHeight(25)
        layout.addWidget(schedule_header)
        
        # Schedule display
        self.schedule_display = QTextBrowser()
        self.schedule_display.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; border-radius: 6px;")
        self.schedule_display.setReadOnly(True)
        self.schedule_display.setPlaceholderText("Loading schedule...")
        layout.addWidget(self.schedule_display)
        
        return widget

    def create_news_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header
        news_header = QLabel("News Feed")
        news_header.setStyleSheet("color: #e8eaed; font-weight: 600; padding: 3px; background-color: transparent; border: none; font-size: 13px;")
        news_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        news_header.setMaximumHeight(25)
        layout.addWidget(news_header)

        # Settings row
        settings_row = QHBoxLayout()
        settings_row.setContentsMargins(0, 0, 0, 0)
        settings_row.setSpacing(6)
        settings_label = QLabel("Hide repeats:")
        settings_label.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        settings_row.addWidget(settings_label)

        self.news_suppress_combo = QComboBox()
        self.news_suppress_combo.addItems(["1 day", "2 days", "3 days", "7 days"])
        self.news_suppress_combo.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; border-radius: 4px; padding: 2px 6px; font-size: 11px;")
        settings_row.addWidget(self.news_suppress_combo)

        max_label = QLabel("Max items:")
        max_label.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        settings_row.addWidget(max_label)

        self.news_max_items_combo = QComboBox()
        self.news_max_items_combo.addItems(["5", "8", "10"])
        self.news_max_items_combo.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; border-radius: 4px; padding: 2px 6px; font-size: 11px;")
        settings_row.addWidget(self.news_max_items_combo)
        settings_row.addStretch()
        layout.addLayout(settings_row)

        # Load persisted setting
        try:
            val = self.db.get_setting("news_suppress_days", "2")
            days = int(val) if val is not None else 2
        except Exception:
            days = 2
        self.news_suppress_days = days
        idx_map = {1: 0, 2: 1, 3: 2, 7: 3}
        self.news_suppress_combo.setCurrentIndex(idx_map.get(days, 1))

        # Load max items setting (default 8)
        try:
            val = self.db.get_setting("news_display_limit", "8")
            max_items = int(val) if val is not None else 8
        except Exception:
            max_items = 8
        if max_items not in (5, 8, 10):
            max_items = 8
        self.news_display_limit = max_items
        idx_map2 = {5: 0, 8: 1, 10: 2}
        self.news_max_items_combo.setCurrentIndex(idx_map2.get(max_items, 1))

        def _on_suppress_changed(_text):
            try:
                text = self.news_suppress_combo.currentText()
                d = int(text.split()[0])
                self.news_suppress_days = d
                self.db.set_setting("news_suppress_days", str(d))
                self.display_stored_news()
            except Exception:
                pass

        self.news_suppress_combo.currentTextChanged.connect(_on_suppress_changed)

        def _on_max_items_changed(_text):
            try:
                d = int(self.news_max_items_combo.currentText().strip())
                if d not in (5, 8, 10):
                    d = 8
                self.news_display_limit = d
                self.db.set_setting("news_display_limit", str(d))
                self.display_stored_news()
            except Exception:
                pass

        self.news_max_items_combo.currentTextChanged.connect(_on_max_items_changed)
        
        # News display
        self.news_display = QTextBrowser()
        self.news_display.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; border-radius: 6px; font-size: 13px;")
        self.news_display.setReadOnly(True)
        self.news_display.setPlaceholderText("Loading news...")
        self.news_display.setOpenExternalLinks(True)
        layout.addWidget(self.news_display)
        
        # Auto-refresh timer (every hour)
        self.news_timer = QTimer()
        self.news_timer.timeout.connect(self.load_news)
        self.news_timer.start(3600000)  # 1 hour
        
        # Cleanup timer (every 24 hours)
        self.news_cleanup_timer = QTimer()
        self.news_cleanup_timer.timeout.connect(self.cleanup_old_news)
        self.news_cleanup_timer.start(86400000)  # 24 hours
        
        return widget

    def load_tasks(self):
        start_time = time.time()
        print(f"TIMING: load_tasks START at {start_time:.6f}")
        # Flag to prevent update_task_status from running during loading
        self._loading_tasks = True
        try:
            self.task_list.setRowCount(0)  # Clear all rows
            print(f"TIMING: setRowCount(0) at {time.time():.6f}")
            
            # Use the same database path as the main application
            db_name = DATABASE_PATH
            
            # Check if database file exists
            import os
            if not os.path.exists(db_name):
                self.task_list.setRowCount(1)
                item = QTableWidgetItem("Database file not found")
                self.task_list.setItem(0, 0, item)
                return
            
            with sqlite3.connect(db_name) as conn:
                # Check if tasks table exists and has data
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks';")
                if cursor.fetchone():
                    # Get all tasks (both complete and incomplete) ordered by due date (nearest first), then by creation date
                    cursor = conn.execute("""
                        SELECT id, task_text, due_date, category, recurrence, completed, session_id FROM tasks
                        ORDER BY 
                            CASE 
                                WHEN due_date IS NULL THEN 1 
                                ELSE 0 
                            END,
                            due_date ASC,
                            created_at DESC
                    """)
                    tasks = cursor.fetchall()
                    
                    if tasks:
                        for task_id, task_text, due_date, category, recurrence, completed, session_id in tasks:
                            # Add new row to table
                            row_position = self.task_list.rowCount()
                            self.task_list.insertRow(row_position)
                            print(f"TIMING: Processing task {task_id} at row {row_position} at {time.time():.6f}: {task_text[:30]}...")
                            
                            # Create task widget with checkbox and text for first column
                            task_widget = QWidget()
                            task_widget.setStyleSheet("QWidget { background-color: transparent; }")
                            task_layout = QHBoxLayout(task_widget)
                            task_layout.setContentsMargins(8, 0, 0, 0)
                            task_layout.setSpacing(8)
                            
                            # Add checkbox to task widget
                            checkbox = QCheckBox()
                            print(f"TIMING: About to setChecked for row {row_position} at {time.time():.6f}")
                            # Temporarily disconnect the signal to prevent update_task_status from running during loading
                            checkbox.blockSignals(True)
                            checkbox.setChecked(completed == 1)
                            checkbox.blockSignals(False)
                            print(f"TIMING: setChecked completed for row {row_position} at {time.time():.6f}")
                            checkbox.setStyleSheet("""
                                QCheckBox {
                                    color: #e8eaed;
                                    background-color: transparent;
                                }
                                QCheckBox::indicator {
                                    width: 16px;
                                    height: 16px;
                                    background-color: #22252c;
                                    border: 1px solid #2e2f32;
                                    border-radius: 3px;
                                }
                                QCheckBox::indicator:checked {
                                    background-color: #FD6262;
                                    border: 1px solid #FD6262;
                                }
                            """)
                            checkbox.stateChanged.connect(lambda state, tid=task_id, r=row_position: self.update_task_status(tid, state == Qt.CheckState.Checked.value, r))
                            task_layout.addWidget(checkbox)
                            
                            # Add task text label
                            task_label = QLabel(f"   {task_text}")
                            task_label.setStyleSheet("color: #e8eaed; background-color: transparent; border: none; font-size: 13px;")
                            task_layout.addWidget(task_label)
                            task_layout.addStretch()
                            
                            # Set task widget in first column
                            self.task_list.setCellWidget(row_position, 0, task_widget)
                            
                            # Set due date in second column
                            due_date_display = due_date if due_date else "No due date"
                            due_date_item = QTableWidgetItem(due_date_display)
                            due_date_item.setFlags(due_date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                            self.task_list.setItem(row_position, 1, due_date_item)
                            
                            # Create action buttons widget
                            print(f"DEBUG: Creating actions widget for row {row_position}")
                            actions_widget = QWidget()
                            actions_widget.setStyleSheet("QWidget { background-color: transparent; }")
                            actions_widget.setObjectName(f"actions_widget_row_{row_position}_task_{task_id}")
                            actions_layout = QHBoxLayout(actions_widget)
                            actions_layout.setContentsMargins(0, 0, 0, 0)  # Remove all margins
                            actions_layout.setSpacing(8)
                            actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                            
                            # Edit button
                            edit_btn = QPushButton("Edit")
                            edit_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                            edit_btn.setMinimumSize(70, 35)
                            edit_btn.setMaximumSize(90, 45)
                            edit_btn.setStyleSheet("""
                                QPushButton {
                                    background-color: #FD6262;
                                    color: white;
                                    border: none;
                                    border-radius: 6px;
                                    font-size: 12px;
                                    font-weight: 500;
                                }
                                QPushButton:hover {
                                    background-color: #e85555;
                                }
                            """)
                            # Capture the row position by value to avoid lambda closure issues
                            edit_btn.clicked.connect(lambda checked, r=row_position: self.edit_task(r, 0))
                            
                            # Delete button
                            delete_btn = QPushButton("Delete")
                            delete_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                            delete_btn.setMinimumSize(80, 35)
                            delete_btn.setMaximumSize(110, 45)
                            delete_btn.setStyleSheet("""
                                QPushButton {
                                    background-color: #3a3b3e;
                                    color: #e8eaed;
                                    border: 1px solid #2e2f32;
                                    border-radius: 6px;
                                    font-size: 12px;
                                    font-weight: 500;
                                }
                                QPushButton:hover {
                                    background-color: #4a4a4e;
                                }
                            """)
                            # Capture the row position by value to avoid lambda closure issues
                            delete_btn.clicked.connect(lambda checked, r=row_position: self.delete_task(r, 0))
                            
                            actions_layout.addWidget(edit_btn)
                            actions_layout.addWidget(delete_btn)
                            actions_layout.addStretch()
                            
                            # Set the actions widget in the third column
                            print(f"TIMING: About to set actions widget for row {row_position} at {time.time():.6f}")
                            # Ensure the widget has the table as its parent
                            actions_widget.setParent(self.task_list)
                            self.task_list.setCellWidget(row_position, 2, actions_widget)
                            print(f"TIMING: Set actions widget for row {row_position} at {time.time():.6f}, task: {task_text[:30]}...")
                            # Verify the widget was actually set
                            verify_widget = self.task_list.cellWidget(row_position, 2)
                            print(f"TIMING: Verification - widget exists after set: {verify_widget is not None} at {time.time():.6f}")
                            
                            # Store task data in the task widget for later use
                            task_widget.task_data = {
                                'id': task_id,
                                'task_text': task_text,
                                'due_date': due_date,
                                'category': category,
                                'recurrence': recurrence,
                                'completed': completed,
                                'session_id': session_id
                            }
                            
                            # Apply color coding after item is fully set up
                            print(f"TIMING: About to apply_task_styling_css for row {row_position} at {time.time():.6f}")
                            self.apply_task_styling_css(row_position, due_date, completed)
                            print(f"TIMING: apply_task_styling_css completed for row {row_position} at {time.time():.6f}")
                            
                            # Process events to ensure UI updates
                            from PyQt6.QtWidgets import QApplication
                            QApplication.processEvents()
                            
                            # Check if widget still exists after processEvents
                            verify_after_events = self.task_list.cellWidget(row_position, 2)
                            print(f"TIMING: Widget exists after processEvents for row {row_position}: {verify_after_events is not None} at {time.time():.6f}")
                            
                    else:
                        self.task_list.setRowCount(1)
                        item = QTableWidgetItem("No tasks found")
                        self.task_list.setItem(0, 0, item)
                else:
                    print("Tasks table does not exist!")
                    self.task_list.setRowCount(1)
                    item = QTableWidgetItem("Tasks table not found in database")
                    self.task_list.setItem(0, 0, item)
        except Exception as e:
            print(f"Error loading tasks: {e}")
            import traceback
            traceback.print_exc()
            self.task_list.setRowCount(1)
            item = QTableWidgetItem(f"Error loading tasks: {str(e)}")
            self.task_list.setItem(0, 0, item)
        
        # Sort by due date after all tasks are loaded
        print(f"TIMING: About to sort table at {time.time():.6f}")
        print(f"DEBUG: Before sorting - checking all widgets:")
        for row in range(self.task_list.rowCount()):
            task_widget = self.task_list.cellWidget(row, 0)
            actions_widget = self.task_list.cellWidget(row, 2)
            due_date_item = self.task_list.item(row, 1)
            due_date = due_date_item.text() if due_date_item else "No date"
            task_id = task_widget.task_data['id'] if task_widget and hasattr(task_widget, 'task_data') else "No ID"
            print(f"  Row {row}: task_widget={task_widget is not None}, actions_widget={actions_widget is not None}, due_date={due_date}, task_id={task_id}")

        # Sort the table
        self.task_list.sortByColumn(1, Qt.SortOrder.AscendingOrder)

        print(f"TIMING: After sorting - checking all widgets at {time.time():.6f}")
        for row in range(self.task_list.rowCount()):
            task_widget = self.task_list.cellWidget(row, 0)
            actions_widget = self.task_list.cellWidget(row, 2)
            due_date_item = self.task_list.item(row, 1)
            due_date = due_date_item.text() if due_date_item else "No date"
            task_id = task_widget.task_data['id'] if task_widget and hasattr(task_widget, 'task_data') else "No ID"
            print(f"  Row {row}: task_widget={task_widget is not None}, actions_widget={actions_widget is not None}, due_date={due_date}, task_id={task_id}")

        print(f"TIMING: Sorting complete at {time.time():.6f}")
        
        # Clear the loading flag
        self._loading_tasks = False
        
        # Debug: Check if all rows have their widgets
        self.debug_check_widgets()
    
    def debug_check_widgets(self):
        """Debug method to check if all rows have their widgets properly set."""
        start_time = time.time()
        print(f"TIMING: debug_check_widgets START at {start_time:.6f}")
        print(f"DEBUG: Checking widgets for {self.task_list.rowCount()} rows...")
        for row in range(self.task_list.rowCount()):
            task_widget = self.task_list.cellWidget(row, 0)
            actions_widget = self.task_list.cellWidget(row, 2)
            due_date_item = self.task_list.item(row, 1)

            task_id = task_widget.task_data['id'] if task_widget and hasattr(task_widget, 'task_data') else "No ID"
            due_date = due_date_item.text() if due_date_item else "No date"
            print(f"Row {row}: task_widget={task_widget is not None}, actions_widget={actions_widget is not None}, due_date_item={due_date_item is not None}, task_id={task_id}, due_date={due_date} at {time.time():.6f}")
    
    def is_overdue(self, due_date_str):
        """Check if a due date is overdue."""
        if not due_date_str or due_date_str == "No due date":
            return False
        try:
            from PyQt6.QtCore import QDate
            due_date = QDate.fromString(due_date_str, "MM-dd-yyyy")
            return due_date < QDate.currentDate()
        except:
            return False
    
    def apply_task_styling_css(self, row, due_date, completed):
        """Apply minimal styling to ensure proper row spacing."""
        # Just set row height for proper button and text spacing
        self.task_list.setRowHeight(row, 50)

    def apply_task_styling(self, item, due_date, completed):
        """Apply color coding to task items based on due date and completion status."""
        from PyQt6.QtGui import QColor, QBrush
        
        # Debug print to see if this function is being called
        # print(f"Applying styling: due_date={due_date}, completed={completed}")
        
        # Store color info in the item data for debugging
        color_info = ""
        
        if completed == 1:
            # Completed tasks - grayed out with white text
            color_info = "completed"
            for i in range(3):
                item.setBackground(i, QBrush(QColor(80, 80, 80)))  # Medium gray background
                item.setForeground(i, QBrush(QColor(200, 200, 200)))  # Light gray text
        elif due_date:
            try:
                # Parse the due date
                if due_date != "No due date":
                    due_date_obj = datetime.strptime(due_date, "%m-%d-%Y")
                    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    due_date_start = due_date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                    
                    if due_date_start < today:
                        # Overdue - dark red background with white text
                        color_info = "overdue"
                        for i in range(3):
                            item.setBackground(i, QBrush(QColor(150, 50, 50)))  # Bright red background
                            item.setForeground(i, QBrush(QColor(255, 255, 255)))  # White text
                    elif due_date_start == today:
                        # Due today - orange background with WHITE text
                        color_info = "due_today"
                        for i in range(3):
                            item.setBackground(i, QBrush(QColor(255, 165, 0)))  # Bright orange background
                            item.setForeground(i, QBrush(QColor(255, 255, 255)))  # WHITE text for readability
                    else:
                        # Future date - default styling with white text
                        color_info = "future"
                        for i in range(3):
                            item.setBackground(i, QBrush(QColor(50, 50, 50)))  # Dark gray background
                            item.setForeground(i, QBrush(QColor(255, 255, 255)))  # White text
                else:
                    # No due date - default styling
                    color_info = "no_date"
                    for i in range(3):
                        item.setBackground(i, QBrush(QColor(50, 50, 50)))
                        item.setForeground(i, QBrush(QColor(255, 255, 255)))
            except ValueError:
                # Invalid date format - default styling
                color_info = "invalid_date"
                for i in range(3):
                    item.setBackground(i, QBrush(QColor(50, 50, 50)))
                    item.setForeground(i, QBrush(QColor(255, 255, 255)))
        else:
            # No due date - default styling
            color_info = "no_date_default"
            for i in range(3):
                item.setBackground(i, QBrush(QColor(50, 50, 50)))
                item.setForeground(i, QBrush(QColor(255, 255, 255)))
        
        # Store color info for debugging
        item.setData(1, Qt.ItemDataRole.UserRole + 1, color_info)

    def load_schedule(self):
        try:
            # Check if we have access to calendar data
            if hasattr(self.chat_handler, 'data_fetcher'):
                data_fetcher = self.chat_handler.data_fetcher
            elif hasattr(self.chat_handler, 'chat_handler') and hasattr(self.chat_handler.chat_handler, 'data_fetcher'):
                data_fetcher = self.chat_handler.chat_handler.data_fetcher
            else:
                raise AttributeError("No data_fetcher found in chat_handler")
            
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
                self.schedule_display.setHtml(schedule_html)
            else:
                self.schedule_display.setHtml("<div style='color: #e8eaed;'>No events scheduled for today</div>")
        except Exception as e:
            self.schedule_display.setHtml(f"<div style='color: #e8eaed;'>Error loading schedule: {str(e)}</div>")

    def load_news(self):
        try:
            print(f"Loading news... chat_handler type: {type(self.chat_handler)}")
            
            # Check if news widget exists before using it
            if not hasattr(self, 'news_display'):
                print("News widget not yet created, skipping load_news")
                return
            
            # Check if news was updated within the last hour
            from datetime import datetime, timezone, timedelta
            last_news_update = self.db.get_last_news_update()
            current_time = datetime.now(timezone.utc).timestamp()
            one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()
            
            
            # If no timestamp exists (first run), proceed with update
            if last_news_update == 0:
                print("First run detected - proceeding with news update.")
            elif last_news_update > one_hour_ago:
                print(f"News was last updated {int((current_time - last_news_update) / 60)} minutes ago. Skipping update.")
                # Just display existing news instead of loading new
                self.display_stored_news()
                return
            else:
                print(f"News is older than 1 hour ({int((current_time - last_news_update) / 60)} minutes ago). Proceeding with update.")
            
            # Update timestamp immediately when starting news fetch
            self.db.update_last_news_update()
            
            # Show loading message
            self.news_display.setHtml("<div style='color: #e8eaed; text-align: center; padding: 20px;'>Loading latest news...</div>")
            
            # Use QThread to make API call without blocking UI
            self.news_thread = NewsWorker(self.chat_handler)
            self.news_thread.news_loaded.connect(self.on_news_loaded)
            self.news_thread.error_occurred.connect(self.on_news_error)
            self.news_thread.start()
                
        except Exception as e:
            print(f"Error starting news thread: {e}")
            if hasattr(self, 'news_display'):
                self.news_display.setHtml(f"<div style='color: #e8eaed;'>Error loading news: {str(e)}</div>")
    
    def _show_briefing_disabled(self):
        """Show disabled message in briefing widget (when BRIEFING_AND_EMAIL_DISABLED is True)."""
        try:
            if hasattr(self, 'briefing_display'):
                self.briefing_display.setHtml(
                    "<div style='color: #9aa0a6; text-align: center; padding: 20px;'>Daily briefing and email checking are currently disabled.</div>"
                )
        except Exception as e:
            print(f"Error showing briefing disabled: {e}")

    def load_daily_briefing(self):
        """Load and display daily briefing if it hasn't been shown today (runs in background thread)."""
        try:
            from config import BRIEFING_AND_EMAIL_DISABLED
            if BRIEFING_AND_EMAIL_DISABLED:
                self._show_briefing_disabled()
                return
            # Check if briefing widget exists
            if not hasattr(self, 'briefing_display'):
                print("Briefing widget not yet created, skipping load_daily_briefing")
                return
            
            # Show loading message
            self.briefing_display.setHtml("<div style='color: #e8eaed; text-align: center; padding: 20px;'>Loading daily briefing... (this may take a moment)</div>")
            
            # Use QThread to make briefing generation non-blocking
            if not hasattr(self, 'briefing_thread') or not self.briefing_thread.isRunning():
                self.briefing_thread = BriefingWorker(self.chat_handler)
                self.briefing_thread.briefing_loaded.connect(self.on_briefing_loaded)
                self.briefing_thread.error_occurred.connect(self.on_briefing_error)
                self.briefing_thread.start()
                
        except Exception as e:
            print(f"Error starting briefing thread: {e}")
            import traceback
            traceback.print_exc()
            if hasattr(self, 'briefing_display'):
                self.briefing_display.setHtml(f"<div style='color: #e8eaed;'>Error loading briefing: {str(e)}</div>")
    
    def on_briefing_loaded(self, briefing, chat_handler_obj):
        """Called when briefing is loaded successfully in the worker thread."""
        # Use thread-safe UI update
        QTimer.singleShot(0, lambda: self._on_briefing_loaded_safe(briefing, chat_handler_obj))
    
    def _on_briefing_loaded_safe(self, briefing, chat_handler_obj):
        """Thread-safe version of on_briefing_loaded."""
        try:
            if not hasattr(self, 'briefing_display'):
                return
            
            # Format the briefing using response_handler
            try:
                from core.response_handler import ResponseHandler
                response_handler = ResponseHandler(chat_handler_obj, None)
                
                # Format the briefing with LLM
                formatted_briefing = response_handler.chat_with_llama(
                    [
                        {
                            "role": "user",
                            "content": (
                                "Turn this briefing into a concise, helpful rundown in Navi's tone (direct, professional, calm; no snark). "
                                "Use <br><br> between sections and keep it skimmable. "
                                "Suggest concrete next actions for urgent items. "
                                f"Briefing:\n\n{briefing}"
                            ),
                        }
                    ],
                    "briefing_session",
                )
                
                # Clean up formatting
                formatted_briefing = re.sub(r'\n+', '\n', formatted_briefing)
                formatted_briefing = re.sub(r'^#+\s*', '', formatted_briefing, flags=re.MULTILINE)
                lines = formatted_briefing.split('\n')
                formatted_lines = [line.strip() for line in lines if line.strip()]
                formatted_briefing = '\n'.join(formatted_lines)
                formatted_briefing = formatted_briefing.replace('\n\n', '<br><br>').replace('\n', '<br>')
                formatted_briefing = re.sub(r'^<br><br>', '', formatted_briefing.strip())
                
                # Display formatted briefing
                self.briefing_display.setHtml(f"<div style='color: #e8eaed; padding: 10px; line-height: 1.5;'>{formatted_briefing}</div>")
            except Exception as e:
                print(f"Error formatting briefing: {e}")
                import traceback
                traceback.print_exc()
                # Fallback: display raw briefing
                briefing_html = briefing.replace('\n', '<br>')
                self.briefing_display.setHtml(f"<div style='color: #e8eaed; padding: 10px; line-height: 1.5;'>{briefing_html}</div>")
        except Exception as e:
            print(f"Error in briefing display: {e}")
            import traceback
            traceback.print_exc()
    
    def on_briefing_error(self, error_message):
        """Called when briefing loading fails in the worker thread."""
        # Use thread-safe UI update
        QTimer.singleShot(0, lambda: self._on_briefing_error_safe(error_message))
    
    def _on_briefing_error_safe(self, error_message):
        """Thread-safe version of on_briefing_error."""
        try:
            if not hasattr(self, 'briefing_display'):
                return
            
            if "already shown today" in error_message:
                self.briefing_display.setHtml("<div style='color: #e8eaed; text-align: center; padding: 20px;'>Daily briefing has already been shown today. Click 'Refresh' to generate a new one.</div>")
            else:
                self.briefing_display.setHtml(f"<div style='color: #e8eaed;'>Error loading briefing: {error_message}</div>")
        except Exception as e:
            print(f"Error displaying briefing error: {e}")

    def refresh_daily_briefing(self):
        """Force refresh the daily briefing (bypasses date check, runs in background thread)."""
        try:
            from config import BRIEFING_AND_EMAIL_DISABLED
            if BRIEFING_AND_EMAIL_DISABLED:
                self._show_briefing_disabled()
                return
            # Check if briefing widget exists
            if not hasattr(self, 'briefing_display'):
                return
            
            # Show loading message
            self.briefing_display.setHtml("<div style='color: #e8eaed; text-align: center; padding: 20px;'>Generating new briefing... (this may take a moment)</div>")
            
            # Create a worker that forces new briefing (calls daily_briefing directly, not start_briefing)
            if not hasattr(self, 'briefing_refresh_thread') or not self.briefing_refresh_thread.isRunning():
                # Create a custom worker for forced refresh
                class RefreshBriefingWorker(QThread):
                    briefing_loaded = pyqtSignal(str, object)
                    error_occurred = pyqtSignal(str)
                    
                    def __init__(self, chat_handler):
                        super().__init__()
                        self.chat_handler = chat_handler
                    
                    def run(self):
                        try:
                            briefing = None
                            chat_handler_obj = None
                            
                            # Force new briefing by calling daily_briefing directly
                            if hasattr(self.chat_handler, 'chat_handler') and hasattr(self.chat_handler.chat_handler, 'daily_briefing'):
                                chat_handler_obj = self.chat_handler.chat_handler
                                briefing = self.chat_handler.chat_handler.daily_briefing()
                            elif hasattr(self.chat_handler, 'daily_briefing'):
                                chat_handler_obj = self.chat_handler
                                briefing = self.chat_handler.daily_briefing()
                            
                            if briefing:
                                self.briefing_loaded.emit(briefing, chat_handler_obj)
                            else:
                                self.error_occurred.emit("Unable to generate briefing")
                        except Exception as e:
                            self.error_occurred.emit(f"Error: {str(e)}")
                
                self.briefing_refresh_thread = RefreshBriefingWorker(self.chat_handler)
                self.briefing_refresh_thread.briefing_loaded.connect(self.on_briefing_loaded)
                self.briefing_refresh_thread.error_occurred.connect(self.on_briefing_error)
                self.briefing_refresh_thread.start()
                
        except Exception as e:
            print(f"Error starting briefing refresh thread: {e}")
            import traceback
            traceback.print_exc()
            if hasattr(self, 'briefing_display'):
                self.briefing_display.setHtml(f"<div style='color: #e8eaed;'>Error loading briefing: {str(e)}</div>")

    def on_news_loaded(self, news_query):
        """Called when news is loaded successfully in the worker thread."""
        # Use thread-safe UI update
        QTimer.singleShot(0, lambda: self._on_news_loaded_safe(news_query))
    
    def _on_news_loaded_safe(self, news_query):
        """Thread-safe version of on_news_loaded."""
        try:
            print(f"on_news_loaded: Got news response: {news_query[:100]}...")
            
            # Process and store the news
            self.process_and_store_news(news_query)
            
            # Display the stored news
            self.display_stored_news()
            
        except Exception as e:
            print(f"Error processing loaded news: {e}")
            if hasattr(self, 'news_display'):
                self.news_display.setHtml(f"<div style='color: #e8eaed;'>Error processing news: {str(e)}</div>")
    
    def on_news_error(self, error_message):
        """Called when there's an error loading news in the worker thread."""
        # Use thread-safe UI update
        QTimer.singleShot(0, lambda: self._on_news_error_safe(error_message))
    
    def _on_news_error_safe(self, error_message):
        """Thread-safe version of on_news_error."""
        print(f"News error: {error_message}")
        if hasattr(self, 'news_display'):
            # Check if it's a credit limit error
            if "credit" in error_message.lower() or "spending limit" in error_message.lower():
                self.news_display.setHtml(
                    "<div style='color: #e8eaed; text-align: center; padding: 20px;'>"
                    "<span style='color: #d4a84b;'>⚠️ Grok API credits exhausted</span><br>"
                    "Please add credits to your xAI account to continue fetching news.<br>"
                    "<small style='color: #9aa0a6;'>Showing cached news below...</small></div>"
                )
                # Still try to show cached news
                self.display_stored_news()
            else:
                self.news_display.setHtml(f"<div style='color: #e8eaed;'>{error_message}</div>")

    def parse_published_date(self, date_str):
        """Parse published date string into datetime object."""
        if not date_str:
            return None
            
        try:
            # Try to parse with dateutil first (handles many formats)
            from dateutil import parser
            return parser.parse(date_str, fuzzy=True)
        except:
            pass
            
        try:
            # Try common date formats
            from datetime import datetime
            formats = [
                '%Y-%m-%d',
                '%Y-%m-%d %H:%M:%S',
                '%B %d, %Y',
                '%b %d, %Y',
                '%d %B %Y',
                '%d %b %Y',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%dT%H:%M:%SZ'
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
        except:
            pass
            
        return None

    def is_likely_recent_by_heuristics(self, date_str):
        """Use heuristics to determine if a date string likely represents recent news."""
        if not date_str:
            return True  # No date means we keep it
            
        date_str_lower = date_str.lower()
        
        # Check for recent indicators
        recent_indicators = [
            'today', 'yesterday', 'this week', 'this month',
            'recent', 'latest', 'new', 'just', 'now'
        ]
        
        for indicator in recent_indicators:
            if indicator in date_str_lower:
                return True
        
        # Check for vague recent dates
        vague_recent = [
            'approximately', 'around', 'about', 'roughly'
        ]
        
        for vague in vague_recent:
            if vague in date_str_lower:
                # If it's vague but mentions recent time periods, include it
                if any(period in date_str_lower for period in ['week', 'day', 'ago', '2025']):
                    return True
        
        # Check for 2025 dates (current year)
        if '2025' in date_str:
            return True
            
        # Check for September 2025 (current month)
        if 'september' in date_str_lower and '2025' in date_str:
            return True
            
        # Check for August 2025 (previous month, still recent)
        if 'august' in date_str_lower and '2025' in date_str:
            return True
        
        # Exclude clearly old dates
        old_indicators = ['2023', '2024', '2022', '2021', '2020']
        for old in old_indicators:
            if old in date_str:
                return False
                
        # If we can't determine, err on the side of including it
        return True

    def format_display_date(self, date_str):
        """Format a date string for better display."""
        if not date_str:
            return "Unknown"
            
        # Try to parse the date first
        parsed_date = self.parse_published_date(date_str)
        if parsed_date:
            # If we can parse it, show a clean format
            return parsed_date.strftime('%B %d, %Y')
        
        # If we can't parse it, clean up the original string
        cleaned = date_str.strip()
        
        # Remove common prefixes that make dates look messy
        prefixes_to_remove = [
            'Published: ', 'Date: ', 'Posted: ', 'Updated: ',
            'approximately ', 'around ', 'about ', 'roughly '
        ]
        
        for prefix in prefixes_to_remove:
            if cleaned.lower().startswith(prefix.lower()):
                cleaned = cleaned[len(prefix):].strip()
        
        # Capitalize first letter
        if cleaned:
            cleaned = cleaned[0].upper() + cleaned[1:]
        
        return cleaned

    def sort_news_by_date(self, news_items):
        """Sort news items by published date (newest first)."""
        def get_sort_key(item):
            # Support both shapes:
            # - legacy: (title, content, url, source, published_date, created_at)
            # - dashboard (suppressed): (id, title, content, url, source, published_date, created_at)
            if len(item) == 7:
                _, title, content, url, source, published_date, created_at = item
            else:
                title, content, url, source, published_date, created_at = item
            
            if published_date:
                # Try to parse the published date
                parsed_date = self.parse_published_date(published_date)
                if parsed_date:
                    # Use parsed date for sorting (newest first = negative timestamp)
                    return -parsed_date.timestamp()
                else:
                    # If we can't parse, use heuristics to estimate recency
                    if self.is_likely_recent_by_heuristics(published_date):
                        # Recent items get higher priority (lower negative number)
                        return -999999999  # Very recent
                    else:
                        # Older items get lower priority
                        return -1
            else:
                # No published date, use created_at as fallback
                try:
                    from datetime import datetime
                    created_dt = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
                    return -created_dt.timestamp()
                except:
                    # If we can't parse created_at either, put it at the end
                    return 0
        
        # Sort by the key (newest first)
        sorted_items = sorted(news_items, key=get_sort_key)
        
        # News items sorted by date (newest first)
        
        return sorted_items

    def is_valid_news_item(self, title, content):
        """Validate that a news item is properly formatted and not malformed."""
        if not title or not content:
            return False
            
        # Check for malformed titles
        malformed_patterns = [
            r'^```',  # Starts with ```
            r'^\* ',   # Starts with * (bullet point)
            r'^\[',    # Starts with [ (JSON array start)
            r'^\{',    # Starts with { (JSON object start)
            r'^null$', # Just "null"
            r'^undefined$', # Just "undefined"
        ]
        
        for pattern in malformed_patterns:
            if re.match(pattern, title.strip(), re.IGNORECASE):
                print(f"Rejecting malformed title: '{title[:50]}...' (matches pattern: {pattern})")
                return False
        
        # Check for very short titles (likely not real news)
        if len(title.strip()) < 10:
            print(f"Rejecting title too short: '{title[:50]}...'")
            return False
            
        # Check for very short content (likely not real news)
        if len(content.strip()) < 20:
            print(f"Rejecting content too short: '{content[:50]}...'")
            return False
            
        return True

    def process_and_store_news(self, news_results):
        # Processing news results
        
        stored_count = 0
        
        try:
            # First, try to parse as JSON
            import json
            
            # Clean the response to extract JSON
            response_clean = news_results.strip()
            
            # Look for JSON array in the response
            json_match = re.search(r'\[.*\]', response_clean, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                try:
                    news_items = json.loads(json_str)
                    print(f"Successfully parsed JSON with {len(news_items)} items")
                    
                    for item in news_items:
                        if isinstance(item, dict) and 'title' in item:
                            title = item.get('title', '').strip()
                            content = item.get('content', '').strip()
                            url = item.get('url', '').strip() or None
                            source = item.get('source', '').strip() or None
                            published_date = item.get('published_date', '').strip() or None
                            
                            # Validate the news item before storing
                            if self.is_valid_news_item(title, content):
                                print(f"Processing news item: '{title[:50]}...'")
                                
                                # Clean URL if provided
                                if url:
                                    # Remove extra text in parentheses from URLs
                                    url = re.sub(r'\s*\([^)]*\)', '', url).strip()
                                    # Validate URL after cleaning
                                    if not self.is_valid_news_url(url):
                                        print(f"Invalid URL detected after cleaning, removing: {url}")
                                        url = None
                                    else:
                                        # Canonicalize URLs early (strip tracking params/fragments) for better dedup.
                                        try:
                                            from core.news_dedup import canonicalize_url
                                            url = canonicalize_url(url) or url
                                        except Exception:
                                            pass
                                        print(f"Cleaned URL: {url}")
                                
                                if not self.db.check_news_exists(title, url):
                                    success = self.db.store_news_item(title, content, url, source, published_date)
                                    if success:
                                        stored_count += 1
                                        print(f"Stored news item: '{title[:50]}...'")
                                    else:
                                        print(f"Failed to store news item: '{title[:50]}...'")
                                else:
                                    print(f"News item already exists: '{title[:50]}...'")
                    
                    # News items stored successfully
                    return
                    
                except json.JSONDecodeError as e:
                    print(f"JSON parsing failed: {e}")
                    # Fall back to text parsing
                    
        except Exception as e:
            print(f"Error in JSON parsing: {e}")
            # Fall back to text parsing
            
        # Fallback: Parse as text (original method)
        # Falling back to text parsing
        news_items = news_results.split('\n\n')
        
        for item in news_items:
            if item.strip():
                lines = item.strip().split('\n')
                if len(lines) >= 2:
                    title = lines[0].strip()
                    content = '\n'.join(lines[1:]).strip()
                    
                    url_match = re.search(r'https?://[^\s]+', content)
                    if url_match:
                        url = url_match.group(0)
                        content = re.sub(r'https?://[^\s]+', '', content).strip()
                    else:
                        url = None
                    if url:
                        try:
                            from core.news_dedup import canonicalize_url
                            url = canonicalize_url(url) or url
                        except Exception:
                            pass
                    
                    print(f"Processing news item: '{title[:50]}...'")
                    if not self.db.check_news_exists(title, url):
                        success = self.db.store_news_item(title, content, url)
                        if success:
                            stored_count += 1
                            print(f"Stored news item: '{title[:50]}...'")
                        else:
                            print(f"Failed to store news item: '{title[:50]}...'")
                    else:
                        print(f"News item already exists: '{title[:50]}...'")
        
        # News items stored successfully

    def _get_news_seed_keywords(self, max_keywords: int = 8) -> list[str]:
        """Best-effort personalization keywords for news relevance."""
        subjects = []
        try:
            if hasattr(self.chat_handler, "chat_handler") and hasattr(self.chat_handler.chat_handler, "data_fetcher"):
                df = self.chat_handler.chat_handler.data_fetcher
                if hasattr(df, "get_gmail_news_seeds"):
                    subjects = df.get_gmail_news_seeds(days=3, max_messages=20) or []
        except Exception:
            subjects = []

        import re
        stop = {
            "fda", "and", "the", "for", "with", "your", "from", "this", "that",
            "you", "are", "new", "update", "updates", "weekly", "daily",
            "newsletter", "news",
        }
        counts = {}
        for s in subjects:
            for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\\-]{2,}", s or ""):
                lw = w.lower()
                if lw in stop:
                    continue
                counts[lw] = counts.get(lw, 0) + 1
        return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:max_keywords]]

    def _score_news_item(self, title: str, content: str, keywords: list[str]) -> int:
        text = f"{title or ''} {content or ''}".lower()
        score = 0
        # Always-relevant domain boosts
        for kw in ("fda", "guidance", "draft", "ivd", "samd", "samd", "pccp", "clinical", "medtech", "medical device"):
            if kw in text:
                score += 1
        # Personalization boosts
        for kw in keywords:
            if kw and kw.lower() in text:
                score += 3
        return score

    def display_stored_news(self):
        try:
            
            # Check if news widget exists before using it
            if not hasattr(self, 'news_display'):
                # News widget not yet created, skipping display_stored_news
                return
            
            # Clean up old news items first
            self.db.cleanup_old_news(days=7)
            # Suppress repeats that have been shown recently
            suppress_days = getattr(self, "news_suppress_days", 2) or 2
            # Pull more candidates than we display so suppression + rerank still yields a full set.
            recent_news = self.db.get_news_for_dashboard(days=7, suppress_days=int(suppress_days), limit=200)
            
            # Filter out items with old published dates (older than 7 days)
            from datetime import datetime, timedelta
            cutoff_date = datetime.now() - timedelta(days=7)
            filtered_news = []
            
            for item in recent_news:
                # DB returns id + fields
                news_id, title, content, url, source, published_date, created_at = item
                should_include = False
                
                if published_date:
                    # Try to parse the published date more intelligently
                    parsed_date = self.parse_published_date(published_date)
                    if parsed_date:
                        # If we successfully parsed a date, check if it's recent
                        if parsed_date >= cutoff_date:
                            should_include = True
                            # Including item with parsed date
                    else:
                        # If we can't parse the date, use heuristics
                        should_include = self.is_likely_recent_by_heuristics(published_date)
                else:
                    # If no published date, keep the item (it was recently created)
                    should_include = True
                
                if should_include:
                    filtered_news.append(item)
            
            recent_news = filtered_news
            # Retrieved news items from database
            
            if recent_news:
                # Sort news items by published date (newest first)
                display_news = self.sort_news_by_date(recent_news)

                # Stable re-rank by relevance (keeps date order within same score)
                seed_keywords = self._get_news_seed_keywords()
                display_news.sort(
                    key=lambda it: -self._score_news_item(
                        it[1] if len(it) == 7 else it[0],
                        it[2] if len(it) == 7 else it[1],
                        seed_keywords,
                    )
                )

                # Apply display limit (default 8; user-configurable)
                lim = int(getattr(self, "news_display_limit", 8) or 8)
                if lim < 1:
                    lim = 8
                display_news = display_news[:lim]
                
                news_text = "<div style='color: #e8eaed; font-family: Segoe UI, Arial, sans-serif;'>"
                news_text += "<h3 style='color: #6b8cae; margin-bottom: 15px;'>Latest News</h3>"
                
                shown_ids = []
                for news_id, title, content, url, source, published_date, created_at in display_news:
                    shown_ids.append(news_id)
                    news_text += "<div style='margin-bottom: 15px; padding: 12px; background-color: #22252c; border: 1px solid #2e2f32; border-radius: 6px;'>"
                    news_text += f"<h4 style='color: #e8eaed; margin: 0 0 8px 0; font-size: 13px; line-height: 1.3;'>{title}</h4>"
                    if content:
                        # Truncate content if too long
                        display_content = content[:200] + "..." if len(content) > 200 else content
                        news_text += f"<p style='margin: 0 0 8px 0; line-height: 1.5; font-size: 12px; color: #9aa0a6;'>{display_content}</p>"
                    if url:
                        news_text += f'<p style="margin: 0 0 5px 0;"><a href="{url}" style="color: #6b8cae; text-decoration: underline; font-size: 12px;">🔗 Read full article</a></p>'
                    if source:
                        news_text += f"<small style='color: #5f6368; font-size: 11px;'>Source: {source}</small>"
                    if published_date:
                        # Try to format the date better
                        formatted_date = self.format_display_date(published_date)
                        news_text += f"<br><small style='color: #5f6368; font-size: 11px;'>Published: {formatted_date}</small>"
                    news_text += "</div>"
                
                news_text += "</div>"
                self.news_display.setHtml(news_text)
                # Mark items as shown so they won't repeat for the suppression window
                try:
                    self.db.mark_news_shown(shown_ids)
                except Exception:
                    pass
                # News display updated successfully
            else:
                self.news_display.setPlainText("No recent news available. Check back later.")
                # No recent news found in database
        except Exception as e:
            print(f"Error in display_stored_news: {e}")
            self.news_display.setPlainText(f"Error displaying news: {str(e)}")

    def refresh_news_feed(self):
        self.load_news()

    def cleanup_old_news(self):
        self.db.cleanup_old_news(days=7)
    
    def is_valid_news_url(self, url):
        """Validate that a URL is a proper web address."""
        if not url or not isinstance(url, str):
            return False
        
        # Check if it's a valid URL format
        if not url.startswith(('http://', 'https://')):
            return False
        
        # Basic URL format validation - must have domain and be reasonable length
        if '.' not in url or len(url) < 10:
            return False
        
        # That's it - if it's a proper URL, accept it
        return True

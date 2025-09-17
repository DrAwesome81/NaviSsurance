from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QCheckBox, QComboBox, QInputDialog, QMessageBox, QDateEdit, QHeaderView, QAbstractItemView
from PyQt6.QtCore import Qt, QTimer, QDate, QThread, pyqtSignal
from datetime import datetime, timedelta
from dateutil import parser
import sqlite3
import sys
import os
import time

# Import config for database path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
        self.date_filter.addItems(["All", "Today", "Overdue", "No Date"])
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
        """Load tasks with current filter settings."""
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

            # Load filtered tasks
            for task_id, task_text, due_date, category, recurrence, completed in tasks:
                print(f"DEBUG: Adding task: {task_text} (ID: {task_id})")
                self.add_task_to_table(task_id, task_text, due_date, category, recurrence, completed)

            print(f"DEBUG: Finished loading {len(tasks)} tasks")

        except Exception as e:
            print(f"Error loading filtered tasks: {e}")
            import traceback
            traceback.print_exc()

    def add_task_to_table(self, task_id, task_text, due_date, category, recurrence, completed):
        """Add an existing task to the table."""
        try:
            print(f"DEBUG: add_task_to_table called with task_id={task_id}, task_text='{task_text}', category='{category}'")
            row_position = self.task_list.rowCount()
            self.task_list.insertRow(row_position)

            # Create task widget with checkbox and label
            task_widget = QWidget()
            task_layout = QHBoxLayout(task_widget)
            task_layout.setContentsMargins(5, 5, 5, 5)
            task_layout.setSpacing(8)

            # Checkbox
            checkbox = QCheckBox()
            checkbox.setChecked(completed)
            checkbox.stateChanged.connect(lambda state, tid=task_id: self.update_task_status(tid, state == Qt.CheckState.Checked.value))
            task_layout.addWidget(checkbox)

            # Task label with left alignment and proper spacing
            task_label = QLabel(f"  {task_text}")  # Add spaces at the beginning for left alignment
            task_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            task_label.setStyleSheet("""
                QLabel {
                    padding-left: 5px;
                    margin: 0px;
                    background-color: transparent;
                }
            """)
            task_layout.addWidget(task_label)

            # Set task widget to column 0
            self.task_list.setCellWidget(row_position, 0, task_widget)

            # Set category to column 1
            category_item = QTableWidgetItem(category or "Business")
            self.task_list.setItem(row_position, 1, category_item)

            # Set due date to column 2
            due_date_item = QTableWidgetItem(due_date or "No Date")
            self.task_list.setItem(row_position, 2, due_date_item)

            # Create actions widget with edit and delete buttons
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            actions_layout.setSpacing(5)

            # Edit button
            edit_btn = QPushButton("Edit")
            edit_btn.setFixedSize(60, 40)
            edit_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(253, 98, 98, 0.8);
                    color: white;
                    border: none;
                    border-radius: 3px;
                    padding: 10px;
                    font-weight: bold;
                    font-size: 11px;
                    margin: 2px;
                }
                QPushButton:hover {
                    background-color: rgba(253, 98, 98, 1.0);
                }
            """)
            edit_btn.clicked.connect(lambda checked, r=row_position, tid=task_id: self.edit_task(r, tid))
            actions_layout.addWidget(edit_btn)

            # Delete button
            delete_btn = QPushButton("Delete")
            delete_btn.setFixedSize(70, 40)
            delete_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(253, 98, 98, 0.8);
                    color: white;
                    border: none;
                    border-radius: 3px;
                    padding: 10px;
                    font-weight: bold;
                    font-size: 11px;
                    margin: 2px;
                }
                QPushButton:hover {
                    background-color: rgba(253, 98, 98, 1.0);
                }
            """)
            delete_btn.clicked.connect(lambda checked, r=row_position, tid=task_id: self.delete_task(r, tid))
            actions_layout.addWidget(delete_btn)

            # Set actions widget to column 3
            self.task_list.setCellWidget(row_position, 3, actions_widget)
            print(f"DEBUG: Set actions widget for NEW task row {row_position}, task: {task_text}")

            # Store task data for later use
            task_widget.task_data = {
                'id': task_id,
                'text': task_text,
                'due_date': due_date,
                'category': category,
                'recurrence': recurrence,
                'completed': completed
            }

            # Apply styling
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
        # Set the overall dark theme for the dashboard
        self.setStyleSheet("""
            QWidget {
                background-color: rgb(27, 28, 30);
                color: white;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Header
        dashboard_header = QLabel("Dashboard - Overview")
        dashboard_header.setStyleSheet("color: white; font-weight: bold; font-size: 16px; padding: 10px; background-color: transparent; border: none;")
        dashboard_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(dashboard_header)
        
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
        refresh_news_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 8px 15px; border-radius: 3px;")
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

    def create_task_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header
        task_header = QLabel("Task List")
        task_header.setStyleSheet("color: white; font-weight: bold; padding: 3px; background-color: transparent; border: none; font-size: 11px;")
        task_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        task_header.setMaximumHeight(25)
        layout.addWidget(task_header)
        
        # Task list - converted to QTableWidget with columns
        self.task_list = QTableWidget()
        self.task_list.setColumnCount(4)
        self.task_list.setHorizontalHeaderLabels(["Task", "Category", "Due Date", "Actions"])
        self.task_list.setAlternatingRowColors(False)  # We'll handle colors manually
        self.task_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.task_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.task_list.verticalHeader().setDefaultSectionSize(75)  # Set row height - increased for buttons
        self.task_list.setStyleSheet("""
            QTableWidget {
                background-color: rgba(27, 28, 30, 0.8); 
                color: white; 
                border: 1px solid rgba(253, 98, 98, 0.3); 
                border-radius: 3px;
                font-size: 13px;
                gridline-color: rgba(253, 98, 98, 0.2);
            }
            QTableWidget::item {
                padding: 15px 8px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: rgba(253, 98, 98, 0.02);
            }
            QHeaderView::section {
                background-color: rgba(253, 98, 98, 0.8);
                color: white;
                padding: 8px;
                border: 1px solid rgba(253, 98, 98, 0.3);
                font-weight: bold;
                font-size: 13px;
                min-height: 25px;
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
        self.taskInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.5); padding: 3px; border-radius: 3px;")
        self.taskInput.returnPressed.connect(self.add_task)
        add_layout.addWidget(self.taskInput)

        # Add due date input
        self.dueDateInput = QDateEdit()
        self.dueDateInput.setCalendarPopup(True)
        self.dueDateInput.setDate(QDate.currentDate())
        self.dueDateInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.5); padding: 3px; border-radius: 3px;")
        add_layout.addWidget(self.dueDateInput)

        # Add category input
        self.categoryInput = QComboBox()
        self.categoryInput.addItems(["Business", "Personal"])
        self.categoryInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.5); padding: 3px; border-radius: 3px;")
        add_layout.addWidget(self.categoryInput)

        # Add recurrence input
        self.recurrenceInput = QComboBox()
        self.recurrenceInput.addItems(["None", "Daily", "Weekly"])
        self.recurrenceInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.5); padding: 3px; border-radius: 3px;")
        add_layout.addWidget(self.recurrenceInput)

        add_btn = QPushButton("Add")
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(253, 98, 98, 0.8);
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: rgba(253, 98, 98, 1.0);
            }
        """)
        add_btn.clicked.connect(self.add_task)
        add_layout.addWidget(add_btn)
        
        layout.addLayout(add_layout)
        
        # Archive completed tasks button
        archive_btn = QPushButton("Archive Completed Tasks")
        archive_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(253, 98, 98, 0.8);
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: rgba(253, 98, 98, 1.0);
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
                    background-color: rgb(27, 28, 30);
                    color: white;
                }
                QLabel {
                    color: white;
                    font-weight: bold;
                }
                QLineEdit {
                    background-color: rgba(27, 28, 30, 0.8);
                    color: white;
                    border: 1px solid rgba(253, 98, 98, 0.5);
                    padding: 8px;
                    border-radius: 3px;
                    font-size: 12px;
                }
                            QDateEdit {
                background-color: rgba(27, 28, 30, 0.8);
                color: white;
                border: 1px solid rgba(253, 98, 98, 0.5);
                padding: 8px;
                border-radius: 3px;
                font-size: 12px;
                min-height: 30px;
            }
                QPushButton {
                    background-color: rgba(253, 98, 98, 0.8);
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 3px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: rgba(253, 98, 98, 1.0);
                }
                QPushButton#cancelButton {
                    background-color: rgba(100, 100, 100, 0.8);
                }
                QPushButton#cancelButton:hover {
                    background-color: rgba(100, 100, 100, 1.0);
                }
            """)
            
            # Set dialog size and center it
            edit_dialog.resize(400, 320)
            edit_dialog.setFixedSize(400, 320)
            
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
        
        # Create context menu
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        
        context_menu = QMenu(self)
        
        # Edit action
        edit_action = QAction("Edit Task", self)
        edit_action.triggered.connect(lambda: self.edit_task(item, 0))
        context_menu.addAction(edit_action)
        
        # Delete action
        delete_action = QAction("Delete Task", self)
        delete_action.triggered.connect(lambda: self.delete_task(item, 0))
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
                    due_date_item = self.task_list.item(row, 1)
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

    def create_schedule_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header
        schedule_header = QLabel("Today's Schedule")
        schedule_header.setStyleSheet("color: white; font-weight: bold; padding: 3px; background-color: transparent; border: none; font-size: 11px;")
        schedule_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        schedule_header.setMaximumHeight(25)
        layout.addWidget(schedule_header)
        
        # Schedule display
        self.schedule_display = QTextBrowser()
        self.schedule_display.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px;")
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
        news_header.setStyleSheet("color: white; font-weight: bold; padding: 3px; background-color: transparent; border: none; font-size: 11px;")
        news_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        news_header.setMaximumHeight(25)
        layout.addWidget(news_header)
        
        # News display
        self.news_display = QTextBrowser()
        self.news_display.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px; font-size: 10px;")
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
                                    color: white;
                                                    background-color: transparent;
                                }
                                QCheckBox::indicator {
                                    width: 18px;
                                    height: 18px;
                                    background-color: rgba(255, 255, 255, 0.2);
                                    border: 2px solid rgba(253, 98, 98, 0.8);
                                                border-radius: 3px;
                                            }
                                QCheckBox::indicator:checked {
                                    background-color: rgba(253, 98, 98, 0.8);
                                    border: 2px solid rgba(253, 98, 98, 1.0);
                                        }
                                    """)
                            checkbox.stateChanged.connect(lambda state, tid=task_id, r=row_position: self.update_task_status(tid, state == Qt.CheckState.Checked.value, r))
                            task_layout.addWidget(checkbox)
                            
                            # Add task text label
                            task_label = QLabel(f"   {task_text}")
                            task_label.setStyleSheet("color: white; background-color: transparent; border: none;")
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
                            actions_widget.setObjectName(f"actions_widget_row_{row_position}_task_{task_id}")
                            actions_layout = QHBoxLayout(actions_widget)
                            actions_layout.setContentsMargins(0, 0, 0, 0)  # Remove all margins
                            actions_layout.setSpacing(8)
                            actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                            
                            # Edit button
                            edit_btn = QPushButton("Edit")
                            edit_btn.setFixedWidth(80)
                            edit_btn.setFixedHeight(40)
                            edit_btn.setStyleSheet("""
                                QPushButton {
                                    background-color: rgba(253, 98, 98, 0.8);
                                    color: white;
                                    border: none;
                                    border-radius: 3px;
                                    font-size: 11px;
                                    font-weight: bold;
                                }
                                QPushButton:hover {
                                    background-color: rgba(253, 98, 98, 1.0);
                                }
                                QPushButton:pressed {
                                    background-color: rgba(253, 98, 98, 0.6);
                                }
                            """)
                            # Capture the row position by value to avoid lambda closure issues
                            edit_btn.clicked.connect(lambda checked, r=row_position: self.edit_task(r, 0))
                            
                            # Delete button
                            delete_btn = QPushButton("Delete")
                            delete_btn.setFixedWidth(100)
                            delete_btn.setFixedHeight(40)
                            delete_btn.setStyleSheet("""
                                QPushButton {
                                    background-color: rgba(253, 98, 98, 0.8);
                                    color: white;
                                    border: none;
                                    border-radius: 3px;
                                    font-size: 11px;
                                    font-weight: bold;
                                }
                                QPushButton:hover {
                                    background-color: rgba(253, 98, 98, 1.0);
                                }
                                QPushButton:pressed {
                                    background-color: rgba(253, 98, 98, 0.6);
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
    
    def apply_task_styling_css(self, row, due_date, completed):
        """Apply color coding to task rows using programmatic colors."""
        from PyQt6.QtGui import QColor, QBrush
        from datetime import datetime
        
        start_time = time.time()
        print(f"TIMING: apply_task_styling_css START for row {row} at {start_time:.6f}")
        try:
            # Determine the styling based on due date and completion
            if completed == 1:
                bg_color = QColor(80, 80, 80)  # Medium gray
                fg_color = QColor(200, 200, 200)  # Light gray
                status = "completed"
            else:
                if due_date and due_date != "No due date":
                    # Parse the due date
                    due_date_obj = datetime.strptime(due_date, "%m-%d-%Y")
                    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    due_date_start = due_date_obj.replace(hour=0, minute=0, second=0, microsecond=0)

                    if due_date_start < today:
                        # Overdue - red background with white text
                        bg_color = QColor(150, 50, 50)  # Red
                        fg_color = QColor(255, 255, 255)  # White
                        status = "overdue"
                    elif due_date_start == today:
                        # Due today - subtle amber background with white text
                        bg_color = QColor(120, 90, 60)  # Dark amber/brown
                        fg_color = QColor(255, 255, 255)  # White
                        status = "due_today"
                    else:
                        # Future date - dark background with white text
                        bg_color = QColor(50, 50, 50)  # Dark gray
                        fg_color = QColor(255, 255, 255)  # White
                        status = "future"
                else:
                    # No due date - default styling
                    bg_color = QColor(50, 50, 50)  # Dark gray
                    fg_color = QColor(255, 255, 255)  # White
                    status = "future"
            
            # Apply row-based coloring using programmatic approach

            # Convert colors to CSS format for widgets
            css_bg_color = f"rgb({bg_color.red()}, {bg_color.green()}, {bg_color.blue()})"
            css_fg_color = f"rgb({fg_color.red()}, {fg_color.green()}, {fg_color.blue()})"

            # Create unified stylesheet for widgets
            widget_stylesheet = f"""
                QWidget {{
                    background-color: {css_bg_color};
                }}
                QLabel {{
                    background-color: transparent;
                    color: {css_fg_color};
                }}
                QCheckBox {{
                    background-color: transparent;
                    color: {css_fg_color};
                }}
                QCheckBox::indicator {{
                    background-color: rgba(255, 255, 255, 0.2);
                    border: 2px solid rgba(253, 98, 98, 0.8);
                }}
                QCheckBox::indicator:checked {{
                    background-color: rgba(253, 98, 98, 0.8);
                    border: 2px solid rgba(253, 98, 98, 1.0);
                }}
                QPushButton {{
                    background-color: rgba(253, 98, 98, 0.8);
                    color: white;
                    border: none;
                    border-radius: 3px;
                }}
                QPushButton:hover {{
                    background-color: rgba(253, 98, 98, 1.0);
                }}
            """

            # Apply to task widget (column 0)
            task_widget = self.task_list.cellWidget(row, 0)
            print(f"TIMING: apply_task_styling_css row {row} - task_widget exists: {task_widget is not None} at {time.time():.6f}")
            if task_widget:
                task_widget.setStyleSheet(widget_stylesheet)
                print(f"TIMING: Applied unified styling to task widget for row {row} at {time.time():.6f}")

            # Apply to actions widget (column 3)
            actions_widget = self.task_list.cellWidget(row, 3)
            print(f"TIMING: apply_task_styling_css row {row} - actions_widget exists: {actions_widget is not None} at {time.time():.6f}")
            if actions_widget:
                actions_widget.setStyleSheet(widget_stylesheet)
                print(f"TIMING: Applied unified styling to actions widget for row {row} at {time.time():.6f}")

            # Set row background color using table's visual properties
            # This colors the empty space in the row
            from PyQt6.QtWidgets import QTableWidgetItem
            for col in range(self.task_list.columnCount()):
                # Skip columns with widgets (0 and 3) - only color item columns (1 and 2)
                if col in [0, 3]:  # Task and Actions columns have widgets
                    continue
                    
                # Create or update items in columns 1 and 2 to have the background color
                item = self.task_list.item(row, col)
                if item is None:
                    # Create a dummy item just to set the background color
                    item = QTableWidgetItem("")
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
                    self.task_list.setItem(row, col, item)
                item.setBackground(QBrush(bg_color))
                item.setForeground(QBrush(fg_color))
                print(f"TIMING: Applied background color {bg_color.name()} to column {col}, row {row} at {time.time():.6f}")

            print(f"TIMING: Row {row} styling completed at {time.time():.6f}")
            
            # Colors applied successfully
            
        except ValueError:
            # Invalid date format - use default styling
            bg_color = QColor(50, 50, 50)
            fg_color = QColor(255, 255, 255)
            status = "error"

            # Apply fallback styling using programmatic approach
            css_bg_color = f"rgb({bg_color.red()}, {bg_color.green()}, {bg_color.blue()})"
            css_fg_color = f"rgb({fg_color.red()}, {fg_color.green()}, {fg_color.blue()})"

            fallback_stylesheet = f"""
                QWidget {{
                    background-color: {css_bg_color};
                }}
                QLabel {{
                    background-color: transparent;
                    color: {css_fg_color};
                }}
                QCheckBox {{
                    background-color: transparent;
                    color: {css_fg_color};
                }}
                QPushButton {{
                    background-color: rgba(253, 98, 98, 0.8);
                    color: white;
                    border: none;
                    border-radius: 3px;
                }}
            """

            task_widget = self.task_list.cellWidget(row, 0)
            if task_widget:
                task_widget.setStyleSheet(fallback_stylesheet)

            actions_widget = self.task_list.cellWidget(row, 2)
            if actions_widget:
                actions_widget.setStyleSheet(fallback_stylesheet)

            # Set item backgrounds for all table cells
            from PyQt6.QtWidgets import QTableWidgetItem
            for col in range(self.task_list.columnCount()):
                item = self.task_list.item(row, col)
                if item is None:
                    item = QTableWidgetItem("")
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
                    self.task_list.setItem(row, col, item)
                item.setBackground(QBrush(bg_color))
                item.setForeground(QBrush(fg_color))

        except Exception as e:
            print(f"Error applying task styling: {e}")
            # Fallback to default styling
            bg_color = QColor(50, 50, 50)
            fg_color = QColor(255, 255, 255)
            status = "error"

            # Apply fallback styling using programmatic approach
            css_bg_color = f"rgb({bg_color.red()}, {bg_color.green()}, {bg_color.blue()})"
            css_fg_color = f"rgb({fg_color.red()}, {fg_color.green()}, {fg_color.blue()})"

            fallback_stylesheet = f"""
                QWidget {{
                    background-color: {css_bg_color};
                }}
                QLabel {{
                    background-color: transparent;
                    color: {css_fg_color};
                }}
                QCheckBox {{
                    background-color: transparent;
                    color: {css_fg_color};
                }}
                QPushButton {{
                    background-color: rgba(253, 98, 98, 0.8);
                    color: white;
                    border: none;
                    border-radius: 3px;
                }}
            """

            task_widget = self.task_list.cellWidget(row, 0)
            if task_widget:
                task_widget.setStyleSheet(fallback_stylesheet)

            actions_widget = self.task_list.cellWidget(row, 2)
            if actions_widget:
                actions_widget.setStyleSheet(fallback_stylesheet)

            # Set item backgrounds for all table cells
            from PyQt6.QtWidgets import QTableWidgetItem
            for col in range(self.task_list.columnCount()):
                item = self.task_list.item(row, col)
                if item is None:
                    item = QTableWidgetItem("")
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
                    self.task_list.setItem(row, col, item)
                item.setBackground(QBrush(bg_color))
                item.setForeground(QBrush(fg_color))

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
                self.schedule_display.setHtml(schedule_html)
            else:
                self.schedule_display.setHtml("<div style='color: white;'>No events scheduled for today</div>")
        except Exception as e:
            self.schedule_display.setHtml(f"<div style='color: white;'>Error loading schedule: {str(e)}</div>")

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
            self.news_display.setHtml("<div style='color: white; text-align: center; padding: 20px;'>Loading latest news...</div>")
            
            # Use QThread to make API call without blocking UI
            self.news_thread = NewsWorker(self.chat_handler)
            self.news_thread.news_loaded.connect(self.on_news_loaded)
            self.news_thread.error_occurred.connect(self.on_news_error)
            self.news_thread.start()
                
        except Exception as e:
            print(f"Error starting news thread: {e}")
            if hasattr(self, 'news_display'):
                self.news_display.setHtml(f"<div style='color: white;'>Error loading news: {str(e)}</div>")
    
    def on_news_loaded(self, news_query):
        """Called when news is loaded successfully in the worker thread."""
        try:
            print(f"on_news_loaded: Got news response: {news_query[:100]}...")
            
            # Process and store the news
            self.process_and_store_news(news_query)
            
            # Display the stored news
            self.display_stored_news()
            
        except Exception as e:
            print(f"Error processing loaded news: {e}")
            if hasattr(self, 'news_display'):
                self.news_display.setHtml(f"<div style='color: white;'>Error processing news: {str(e)}</div>")
    
    def on_news_error(self, error_message):
        """Called when there's an error loading news in the worker thread."""
        print(f"News error: {error_message}")
        if hasattr(self, 'news_display'):
            # Check if it's a credit limit error
            if "credit" in error_message.lower() or "spending limit" in error_message.lower():
                self.news_display.setHtml(
                    "<div style='color: #ffcc00; text-align: center; padding: 20px;'>"
                    "⚠️ Grok API credits exhausted<br>"
                    "Please add credits to your xAI account to continue fetching news.<br>"
                    "<small>Showing cached news below...</small></div>"
                )
                # Still try to show cached news
                self.display_stored_news()
            else:
                self.news_display.setHtml(f"<div style='color: white;'>{error_message}</div>")

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

    def display_stored_news(self):
        try:
            
            # Check if news widget exists before using it
            if not hasattr(self, 'news_display'):
                # News widget not yet created, skipping display_stored_news
                return
            
            # Clean up old news items first
            self.db.cleanup_old_news(days=7)
            recent_news = self.db.get_recent_news(days=7)
            
            # Filter out items with old published dates (older than 7 days)
            from datetime import datetime, timedelta
            cutoff_date = datetime.now() - timedelta(days=7)
            filtered_news = []
            
            for item in recent_news:
                title, content, url, source, published_date, created_at = item
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
                
                news_text = "<div style='color: white; font-family: Arial, sans-serif;'>"
                news_text += "<h3 style='color: #fd6262; margin-bottom: 15px;'>Latest News</h3>"
                
                for title, content, url, source, published_date, created_at in display_news:
                    news_text += "<div style='margin-bottom: 15px; padding: 10px; background-color: rgba(253, 98, 98, 0.1); border-radius: 5px; border-left: 3px solid #fd6262;'>"
                    news_text += f"<h4 style='color: #fd6262; margin: 0 0 8px 0; font-size: 12px; line-height: 1.3;'>{title}</h4>"
                    if content:
                        # Truncate content if too long
                        display_content = content[:200] + "..." if len(content) > 200 else content
                        news_text += f"<p style='margin: 0 0 8px 0; line-height: 1.4; font-size: 11px;'>{display_content}</p>"
                    if url:
                        news_text += f'<p style="margin: 0 0 5px 0;"><a href="{url}" style="color: #4fc3f7; text-decoration: underline; font-size: 10px;">🔗 Read full article</a></p>'
                    if source:
                        news_text += f"<small style='color: #888; font-size: 10px;'>Source: {source}</small>"
                    if published_date:
                        # Try to format the date better
                        formatted_date = self.format_display_date(published_date)
                        news_text += f"<br><small style='color: #888; font-size: 10px;'>Published: {formatted_date}</small>"
                    news_text += "</div>"
                
                news_text += "</div>"
                self.news_display.setHtml(news_text)
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

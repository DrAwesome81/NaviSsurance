from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QCheckBox, QInputDialog, QMessageBox, QDateEdit
from PyQt6.QtCore import Qt, QTimer, QDate, QThread, pyqtSignal
from datetime import datetime, timedelta
from dateutil import parser
import sqlite3
import sys
import os

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
            direct_search_query = "recent MedTech news AI machine learning IVD SaMD FDA regulations medical devices"
            
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
    def __init__(self, chat_handler, todo_list, db):
        super().__init__()
        self.chat_handler = chat_handler
        self.todo_list = todo_list
        self.db = db
        self.setup_ui()

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
        
        # Task list - use the proper TodoList integration
        self.task_list = QListWidget()
        self.task_list.setStyleSheet("""
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
        self.task_list.setWordWrap(True)
        self.task_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        layout.addWidget(self.task_list)
        
        # Quick add task
        add_layout = QHBoxLayout()
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("Quick task...")
        self.task_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.5); padding: 3px; border-radius: 3px;")
        self.task_input.returnPressed.connect(self.add_task)
        add_layout.addWidget(self.task_input)
        
        # Add due date input
        self.due_date_input = QDateEdit()
        self.due_date_input.setCalendarPopup(True)
        self.due_date_input.setDate(QDate.currentDate())
        self.due_date_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.5); padding: 3px; border-radius: 3px;")
        add_layout.addWidget(self.due_date_input)
        
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
        self.load_tasks()
        
        return widget

    def update_task_status(self, task_text, completed):
        """Update the completion status of a task."""
        try:

            db_name = DATABASE_PATH
            with sqlite3.connect(db_name) as conn:
                conn.execute("""
                    UPDATE tasks SET completed = ? WHERE task = ?
                """, (completed, task_text))
                conn.commit()
            self.load_tasks()  # Refresh the display
        except Exception as e:
            print(f"Error updating task status: {e}")

    def edit_task(self, task_widget):
        """Edit a task using a custom dialog with calendar."""
        try:
            # Get task text from the label (item 1)
            task_text = task_widget.layout().itemAt(1).widget().text()
            # Get due date from the label (item 3, after stretch)
            due_date = task_widget.layout().itemAt(3).widget().text()
            
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
            edit_dialog.resize(400, 250)
            edit_dialog.setFixedSize(400, 250)
            
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
                
                if not new_text:
                    QMessageBox.warning(self, "Error", "Task text cannot be empty")
                    return
                
                # Update the task in the database
                try:
                    db_name = DATABASE_PATH
                    with sqlite3.connect(db_name) as conn:
                        conn.execute("""
                            UPDATE tasks SET task = ?, due_date = ? WHERE task = ?
                        """, (new_text, new_date, task_text))
                        conn.commit()
                    
                    # Refresh the display
                    self.load_tasks()
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to update task: {str(e)}")
                    
        except Exception as e:
            print(f"Error editing task: {e}")
            QMessageBox.critical(self, "Error", f"Failed to edit task: {str(e)}")

    def delete_task(self, task_widget):
        """Delete a task."""
        try:
            # Get task text from the label (item 1)
            task_text = task_widget.layout().itemAt(1).widget().text()
            
            reply = QMessageBox.question(self, "Delete Task",
                                       "Are you sure you want to delete this task?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                db_name = DATABASE_PATH
                with sqlite3.connect(db_name) as conn:
                    conn.execute("DELETE FROM tasks WHERE task = ?", (task_text,))
                    conn.commit()
                
                # Refresh the display
                self.load_tasks()
        except Exception as e:
            print(f"Error deleting task: {e}")
            QMessageBox.critical(self, "Error", f"Failed to delete task: {str(e)}")

    def add_task(self):
        """Add a new task from the input field."""
        task_text = self.task_input.text().strip()
        if not task_text:
            return
            
        # Get the selected due date
        due_date = self.due_date_input.date().toString("MM-dd-yyyy")
            
        try:
            db_name = DATABASE_PATH
            with sqlite3.connect(db_name) as conn:
                conn.execute("""
                    INSERT INTO tasks (session_id, task, due_date, completed) 
                    VALUES (?, ?, ?, ?)
                """, (f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}", task_text, due_date, 0))
                conn.commit()
            
            self.task_input.clear()
            self.load_tasks()  # Refresh the display
        except Exception as e:
            print(f"Error adding task: {e}")

    def archive_completed_tasks(self):
        """Archive completed tasks."""
        try:
            db_name = DATABASE_PATH
            with sqlite3.connect(db_name) as conn:
                # Get completed tasks
                cursor = conn.execute("SELECT task, due_date, completed, session_id FROM tasks WHERE completed = 1")
                completed_tasks = cursor.fetchall()
                
                if completed_tasks:
                    # Move to archived_tasks table
                    for task, due_date, completed, session_id in completed_tasks:
                        conn.execute("""
                            INSERT INTO archived_tasks (task, due_date, completed, session_id, created_at)
                            VALUES (?, ?, ?, ?, datetime('now'))
                        """, (task, due_date, completed, session_id))
                    
                    # Delete from active tasks
                    conn.execute("DELETE FROM tasks WHERE completed = 1")
                    conn.commit()
                    
                    print(f"Archived {len(completed_tasks)} completed tasks")
                    self.load_tasks()  # Refresh the display
                else:
                    print("No completed tasks to archive")
        except Exception as e:
            print(f"Error archiving tasks: {e}")

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
            self.load_tasks()

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
        try:
            self.task_list.clear()
            
            # Use the same database path as the main application
            db_name = DATABASE_PATH
            print(f"Loading tasks from database: {db_name}")
            
            # Check if database file exists
            import os
            if os.path.exists(db_name):
                print(f"Database file exists, size: {os.path.getsize(db_name)} bytes")
            else:
                print("Database file does not exist!")
                self.task_list.addItem("Database file not found")
                return
            
            with sqlite3.connect(db_name) as conn:
                # Check what tables exist
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = cursor.fetchall()
                print(f"Database tables: {[table[0] for table in tables]}")
                
                # Check if tasks table exists and has data
                if ('tasks',) in tables:
                    cursor = conn.execute("SELECT COUNT(*) FROM tasks")
                    total_tasks = cursor.fetchone()[0]
                    print(f"Total tasks in database: {total_tasks}")
                    
                    cursor = conn.execute("SELECT COUNT(*) FROM tasks WHERE completed = 0")
                    active_tasks = cursor.fetchone()[0]
                    print(f"Active tasks (not completed): {active_tasks}")
                    
                    cursor = conn.execute("SELECT COUNT(*) FROM tasks WHERE completed = 1")
                    completed_tasks = cursor.fetchone()[0]
                    print(f"Completed tasks: {completed_tasks}")
                    
                    # Get all tasks (both complete and incomplete) ordered by due date (nearest first), then by creation date
                    cursor = conn.execute("""
                        SELECT task, due_date, completed, session_id FROM tasks 
                        ORDER BY 
                            CASE 
                                WHEN due_date IS NULL THEN 1 
                                ELSE 0 
                            END,
                            due_date ASC,
                            created_at DESC
                    """)
                    tasks = cursor.fetchall()
                    print(f"Found {len(tasks)} total tasks")
                    
                    if tasks:
                        for task, due_date, completed, session_id in tasks:
                            # Create custom widget for each task with columns
                            item_widget = QWidget()
                            layout = QHBoxLayout(item_widget)
                            layout.setContentsMargins(5, 5, 5, 5)
                            layout.setSpacing(5)
                            item_widget.setMinimumHeight(40)
                            
                            # Apply color coding based on due date
                            if due_date:
                                try:
                                    # Parse the due date
                                    if due_date != "No due date":
                                        due_date_obj = datetime.strptime(due_date, "%m-%d-%Y")
                                        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                                        due_date_start = due_date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                                        
                                        if due_date_start < today:
                                            # Overdue - dark red background
                                            item_widget.setStyleSheet("""
                                                QWidget {
                                                    background-color: rgba(139, 0, 0, 0.3);
                                                    border: 1px solid rgba(139, 0, 0, 0.5);
                                                    border-radius: 3px;
                                                }
                                            """)
                                        elif due_date_start == today:
                                            # Due today - gold background
                                            item_widget.setStyleSheet("""
                                                QWidget {
                                                    background-color: rgba(255, 215, 0, 0.2);
                                                    border: 1px solid rgba(255, 215, 0, 0.4);
                                                    border-radius: 3px;
                                                }
                                            """)
                                        else:
                                            # Future date - transparent background
                                            item_widget.setStyleSheet("""
                                                QWidget {
                                                    background-color: transparent;
                                                    border: 1px solid rgba(253, 98, 98, 0.2);
                                                    border-radius: 3px;
                                                }
                                            """)
                                    else:
                                        # No due date - transparent background
                                        item_widget.setStyleSheet("""
                                            QWidget {
                                                background-color: transparent;
                                                border: 1px solid rgba(253, 98, 98, 0.2);
                                                border-radius: 3px;
                                            }
                                        """)
                                except ValueError:
                                    # Invalid date format - transparent background
                                    item_widget.setStyleSheet("""
                                        QWidget {
                                            background-color: transparent;
                                            border: 1px solid rgba(253, 98, 98, 0.2);
                                            border-radius: 3px;
                                        }
                                    """)
                            else:
                                # No due date - transparent background
                                item_widget.setStyleSheet("""
                                    QWidget {
                                        background-color: transparent;
                                        border: 1px solid rgba(253, 98, 98, 0.2);
                                        border-radius: 3px;
                                    }
                                """)
                            
                            # Checkbox for completion
                            checkbox = QCheckBox()
                            checkbox.setChecked(True if completed == 1 else False)
                            checkbox.stateChanged.connect(lambda state, t=task: self.update_task_status(t, state == Qt.CheckState.Checked.value))
                            layout.addWidget(checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
                            
                            # Task text
                            task_label = QLabel(task)
                            task_label.setWordWrap(True)
                            task_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                            
                            # Apply completed task styling
                            if completed == 1:
                                task_label.setStyleSheet("color: #888; text-decoration: line-through;")
                                # Also style the entire widget to show it's completed
                                item_widget.setStyleSheet("""
                                    QWidget {
                                        background-color: rgba(100, 100, 100, 0.2);
                                        border: 1px solid rgba(100, 100, 100, 0.4);
                                        border-radius: 3px;
                                    }
                                """)
                            
                            layout.addWidget(task_label)
                            
                            layout.addStretch(1)
                            
                            # Due date
                            due_date_label = QLabel(due_date if due_date else "No due date")
                            due_date_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
                            layout.addWidget(due_date_label)
                            
                            # Edit button with proper styling
                            edit_button = QPushButton("Edit")
                            edit_button.setFixedWidth(80)
                            edit_button.setStyleSheet("""
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
                            edit_button.clicked.connect(lambda checked, w=item_widget: self.edit_task(w))
                            edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
                            layout.addWidget(edit_button)
                            
                            # Delete Button
                            delete_button = QPushButton("Delete")
                            delete_button.setFixedWidth(80)
                            delete_button.setStyleSheet("""
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
                            delete_button.clicked.connect(lambda checked, w=item_widget: self.delete_task(w))
                            delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
                            layout.addWidget(delete_button)
                            
                            # Create list item and set the custom widget
                            item = QListWidgetItem()
                            item.setSizeHint(item_widget.sizeHint())
                            self.task_list.addItem(item)
                            self.task_list.setItemWidget(item, item_widget)
                    else:
                        self.task_list.addItem("No tasks found")
                else:
                    print("Tasks table does not exist!")
                    self.task_list.addItem("Tasks table not found in database")
        except Exception as e:
            print(f"Error loading tasks: {e}")
            import traceback
            traceback.print_exc()
            self.task_list.addItem(f"Error loading tasks: {str(e)}")

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
        
        # Print sorting debug info
        print("News items sorted by date (newest first):")
        for i, item in enumerate(sorted_items[:5]):  # Show first 5
            title, content, url, source, published_date, created_at = item
            parsed_date = self.parse_published_date(published_date) if published_date else None
            date_str = parsed_date.strftime('%Y-%m-%d') if parsed_date else published_date or "No date"
            print(f"  {i+1}. {title[:50]}... - {date_str}")
        
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
        print(f"Processing news results: {len(news_results)} characters")
        
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
                    
                    print(f"Total news items stored: {stored_count}")
                    return
                    
                except json.JSONDecodeError as e:
                    print(f"JSON parsing failed: {e}")
                    # Fall back to text parsing
                    
        except Exception as e:
            print(f"Error in JSON parsing: {e}")
            # Fall back to text parsing
            
        # Fallback: Parse as text (original method)
        print("Falling back to text parsing...")
        news_items = news_results.split('\n\n')
        print(f"Found {len(news_items)} news items")
        
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
        
        print(f"Total news items stored: {stored_count}")
        print("Now calling display_stored_news()...")

    def display_stored_news(self):
        try:
            print("Displaying stored news...")
            
            # Check if news widget exists before using it
            if not hasattr(self, 'news_display'):
                print("News widget not yet created, skipping display_stored_news")
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
                            print(f"Including item with parsed date {parsed_date.strftime('%Y-%m-%d')}: {title[:50]}...")
                        else:
                            print(f"Excluding old item with date {parsed_date.strftime('%Y-%m-%d')}: {title[:50]}...")
                    else:
                        # If we can't parse the date, use heuristics
                        should_include = self.is_likely_recent_by_heuristics(published_date)
                        if should_include:
                            print(f"Including item by heuristics: {title[:50]}... (date: {published_date})")
                        else:
                            print(f"Excluding item by heuristics: {title[:50]}... (date: {published_date})")
                else:
                    # If no published date, keep the item (it was recently created)
                    should_include = True
                    print(f"Including item with no published date: {title[:50]}...")
                
                if should_include:
                    filtered_news.append(item)
            
            recent_news = filtered_news
            print(f"Retrieved {len(recent_news)} news items from database")
            
            if recent_news:
                # Sort news items by published date (newest first)
                display_news = self.sort_news_by_date(recent_news)
                
                # Show the first few items for debugging
                for i, (title, content, url, source, published_date, created_at) in enumerate(display_news):
                    print(f"News item {i+1}: '{title[:50]}...' - Created: {created_at}")
                
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
                print("News display updated successfully")
            else:
                self.news_display.setPlainText("No recent news available. Check back later.")
                print("No recent news found in database")
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

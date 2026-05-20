from PyQt6.QtWidgets import (QListWidgetItem, QWidget, QHBoxLayout, QCheckBox, 
                            QLabel, QPushButton, QSizePolicy, QListWidget, 
                            QMessageBox, QInputDialog, QComboBox, QDateEdit, QVBoxLayout)
from PyQt6.QtCore import Qt, QDate
import sqlite3
from core.db import DatabaseManager
from datetime import datetime, timedelta

class TodoList:
    # Intelligence pillar coordination: tasks here integrate with Pulse/Intel raised items via CoS (private memory themes + 🛡️ security-relevant triage surface in planning)
    # New: todo list now explicitly supports Pulse private memory for Shield (additional todo list spot)
    # Pulse/Shield: private memory + compliance (todo list)
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.db = DatabaseManager()
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Reference the DashboardTab's task_list (QTableWidget)
        self.task_list = parent.task_list if hasattr(parent, 'task_list') else None
        # Don't call setup_ui here - it will be called by the DashboardTab

    def setup_ui(self):
        """This method is no longer used - filters are now handled by DashboardTab"""
        pass

    def addTask(self):
        task_text = self.parent.taskInput.text().strip()
        due_date = self.parent.dueDateInput.date().toString("MM-dd-yyyy") if self.parent.dueDateInput.date() else None
        category = self.parent.categoryInput.currentText() if hasattr(self.parent, 'categoryInput') else "Business"
        recurrence = self.parent.recurrenceInput.currentText() if hasattr(self.parent, 'recurrenceInput') else "None"

        if not task_text:
            QMessageBox.warning(self.parent, "Error", "Task text cannot be empty")
            return
            
        try:
            self.insertTaskIntoDB(task_text, due_date, category, recurrence)
            self.loadTasksFromDB()
            if hasattr(self.parent, 'taskInput'):
                self.parent.taskInput.clear()
            if hasattr(self.parent, 'dueDateInput'):
                self.parent.dueDateInput.setDate(QDate.currentDate())
        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to add task: {str(e)}")

    def addTaskFromChat(self, task_text, due_date, category="Personal", recurrence="None"):
        try:
            self.insertTaskIntoDB(task_text, due_date, category, recurrence)
            self.loadTasksFromDB()
        except Exception as e:
            pass

    def insertTaskIntoDB(self, task_text, due_date, category, recurrence):
        try:
            self.db.add_task(self.session_id, task_text, due_date, category, recurrence)
        except sqlite3.Error as e:
            QMessageBox.critical(self.parent, "Database Error", f"Database issue while adding task: {str(e)}")
            return False
        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to add task: {str(e)}")
            return False
        return True

    def updateUIWithTask(self, task_text, due_date, category, recurrence, completed=False, task_id=None):
        # Check for duplicates
        for i in range(self.todoList.count()):
            item = self.todoList.item(i)
            widget = self.todoList.itemWidget(item)
            if widget:
                layout = widget.layout()
                if layout.count() > 2:
                    task_label = layout.itemAt(1).widget()
                    date_label = layout.itemAt(3).widget()
                    if task_label.text() == task_text and date_label.text() == (due_date or "No Date"):
                        return
                        
        item_widget = QWidget()
        item_widget.setObjectName(f"task_{task_id}")  # Unique identifier for task
        layout = QHBoxLayout(item_widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        item_widget.setMinimumHeight(40)

        # Checkbox
        checkbox = QCheckBox()
        checkbox.setChecked(completed)
        checkbox.stateChanged.connect(lambda state: self.updateTaskStatus(task_text, state == Qt.CheckState.Checked.value, recurrence))
        layout.addWidget(checkbox, alignment=Qt.AlignmentFlag.AlignCenter)

        # Task Label
        label = QLabel(task_text)
        label.setWordWrap(True)
        layout.addWidget(label)

        # Category Label
        category_label = QLabel(category)
        layout.addWidget(category_label)

        layout.addStretch(1)

        # Due Date Label
        due_date_label = QLabel(due_date or "No Date")
        due_date_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        layout.addWidget(due_date_label)

        # Actions Widget
        actions_widget = QWidget()
        actions_widget.setObjectName(f"actions_{task_id}")  # Unique identifier
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)

        edit_button = QPushButton("Edit")
        edit_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        edit_button.setMinimumSize(70, 35)
        edit_button.setMaximumSize(90, 45)
        edit_button.clicked.connect(lambda: self.editTask(item_widget, task_id))
        actions_layout.addWidget(edit_button)

        delete_button = QPushButton("Delete")
        delete_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        delete_button.setMinimumSize(70, 35)
        delete_button.setMaximumSize(90, 45)
        delete_button.clicked.connect(lambda: self.deleteTask(item_widget, task_id))
        actions_layout.addWidget(delete_button)

        layout.addWidget(actions_widget)

        # Store task data in the widget for easy access
        item_widget.task_data = {
            'id': task_id,
            'text': task_text,
            'due_date': due_date,
            'category': category,
            'recurrence': recurrence,
            'completed': completed
        }

        item_widget.setLayout(layout)

        list_item = QListWidgetItem(self.todoList)
        list_item.setSizeHint(item_widget.sizeHint())
        list_item.setData(Qt.ItemDataRole.UserRole, task_id)  # Store task_id for sorting
        self.todoList.addItem(list_item)
        self.todoList.setItemWidget(list_item, item_widget)

        self.updateTaskStyle(item_widget)

    def updateTaskStatus(self, task_text, completed, recurrence):
        try:
            self.db.update_task_status(task_text, completed)
            if completed and recurrence != "None":
                self.handle_recurrence(task_text, recurrence)
            self.loadTasksFromDB()
        except sqlite3.Error as e:
            QMessageBox.critical(self.parent, "Database Error", f"Database issue while updating task: {str(e)}")
        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to update task status: {str(e)}")

    def handle_recurrence(self, task_text, recurrence):
        due_date = None
        if recurrence == "Daily":
            due_date = (datetime.now() + timedelta(days=1)).strftime("%m-%d-%Y")
        elif recurrence == "Weekly":
            due_date = (datetime.now() + timedelta(weeks=1)).strftime("%m-%d-%Y")
        if due_date:
            self.insertTaskIntoDB(task_text, due_date, self.db.get_task_category(task_text), recurrence)

    def editTask(self, widget, task_id):
        try:
            # Get task data from the widget's stored data instead of parsing layout
            if hasattr(widget, 'task_data'):
                task_text = widget.task_data.get('text', '')
                due_date = widget.task_data.get('due_date', '')
                category = widget.task_data.get('category', 'Business')
            else:
                # Fallback to parsing layout if no task_data stored
                layout = widget.layout()
                task_text = layout.itemAt(1).widget().text() if layout.count() > 1 else ""
                due_date = layout.itemAt(3).widget().text() if layout.count() > 3 else ""
                category = layout.itemAt(2).widget().text() if layout.count() > 2 else "Business"
            
            recurrence = self.db.get_task_recurrence(task_id)
            
            new_text, ok = QInputDialog.getText(self.parent, "Edit Task", "Task:", text=task_text)
            if ok and new_text:
                new_date, ok = QInputDialog.getText(self.parent, "Edit Due Date", 
                                                  "Due Date (MM-DD-YYYY, leave empty for none):", text=due_date if due_date != "No Date" else "")
                if ok:
                    new_category, ok = QInputDialog.getItem(self.parent, "Edit Category", 
                                                           "Category:", ["Business", "Personal"], 0, False)
                    if ok:
                        new_recurrence, ok = QInputDialog.getItem(self.parent, "Edit Recurrence", 
                                                                 "Recurrence:", ["None", "Daily", "Weekly"], 0, False)
                        if ok:
                            try:
                                if new_date:
                                    datetime.strptime(new_date, "%m-%d-%Y")
                                self.db.delete_task(task_text)
                                self.insertTaskIntoDB(new_text, new_date or None, new_category, new_recurrence)
                                self.loadTasksFromDB()
                            except ValueError:
                                QMessageBox.warning(self.parent, "Error", "Invalid date format. Use MM-DD-YYYY")
        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to edit task: {str(e)}")

    def deleteTask(self, widget, task_id):
        try:
            reply = QMessageBox.question(self.parent, "Delete Task",
                                       "Are you sure you want to delete this task?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                task_text = widget.layout().itemAt(1).widget().text()
                self.db.delete_task(task_text)
                self.loadTasksFromDB()
        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to delete task: {str(e)}")

    def archiveCompletedTasks(self):
        try:
            archived_count = 0
            tasks_to_archive = []
            
            for i in range(self.todoList.count()):
                item = self.todoList.item(i)
                widget = self.todoList.itemWidget(item)
                if not widget or not widget.layout():
                    continue
                layout = widget.layout()
                if layout.count() < 4:
                    continue
                checkbox = layout.itemAt(0).widget()
                label = layout.itemAt(1).widget()
                due_date_label = layout.itemAt(3).widget()
                if not all([checkbox, label, due_date_label]):
                    continue
                task_text = label.text()
                due_date = due_date_label.text()
                is_completed = checkbox.checkState() == Qt.CheckState.Checked
                if is_completed:
                    # Get category and recurrence from widget data or layout
                    category = "Business"  # Default
                    recurrence = "None"  # Default
                    
                    # Try to get from task_data first
                    if hasattr(widget, 'task_data'):
                        category = widget.task_data.get('category', category)
                        recurrence = widget.task_data.get('recurrence', recurrence)
                    else:
                        # Fallback to layout parsing
                        if layout.count() > 2:
                            category_label = layout.itemAt(2).widget()
                            if category_label:
                                category = category_label.text()
                        # Get recurrence from database
                        # We need task_id to get recurrence, but we can try to find it
                        try:
                            with sqlite3.connect(self.db.db_name) as conn:
                                cursor = conn.execute(
                                    'SELECT id FROM tasks WHERE task_text = ? ORDER BY created_at DESC LIMIT 1',
                                    (task_text,)
                                )
                                task_id_result = cursor.fetchone()
                                if task_id_result:
                                    recurrence = self.db.get_task_recurrence(task_id_result[0])
                        except Exception:
                            pass  # Keep default if we can't get it
                    
                    tasks_to_archive.append((task_text, due_date, category, recurrence))
            
            for task_text, due_date, category, recurrence in tasks_to_archive:
                self.db.archive_task(task_text, due_date, category, recurrence, True)
                archived_count += 1
                for i in range(self.todoList.count()):
                    item = self.todoList.item(i)
                    widget = self.todoList.itemWidget(item)
                    if widget and widget.layout():
                        label = widget.layout().itemAt(1).widget()
                        if label and label.text() == task_text:
                            self.todoList.takeItem(i)
                            break
            
            if archived_count > 0:
                self.db.clear_tasks()
                for i in range(self.todoList.count()):
                    item = self.todoList.item(i)
                    widget = self.todoList.itemWidget(item)
                    if widget and hasattr(widget, 'task_data'):
                        # Use stored task data to preserve all metadata
                        task_data = widget.task_data
                        self.db.add_task(
                            task_data.get('session_id', self.session_id),
                            task_data.get('text', ''),
                            task_data.get('due_date', ''),
                            task_data.get('category', 'Business'),
                            task_data.get('recurrence', 'None'),
                            task_data.get('completed', 0)
                        )
                    elif widget and widget.layout():
                        # Fallback to parsing layout if no task_data stored
                        label = widget.layout().itemAt(1).widget()
                        due_date_label = widget.layout().itemAt(3).widget()
                        category_label = widget.layout().itemAt(2).widget()
                        if label and due_date_label and category_label:
                            self.db.add_task(self.session_id, label.text(), due_date_label.text(), category_label.text(), "None")
                QMessageBox.information(self.parent, "Success", f"Archived {archived_count} completed task(s)")
            else:
                QMessageBox.information(self.parent, "Info", "No completed tasks to archive")
                
        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to archive tasks: {str(e)}")

    def loadTasksFromDB(self):
        try:
            # Get filter values from parent (DashboardTab)
            category_filter = self.parent.category_filter.currentText() if hasattr(self.parent, 'category_filter') else "All"
            date_filter = self.parent.date_filter.currentText() if hasattr(self.parent, 'date_filter') else "All"
            specific_date = self.parent.date_range.date().toString("MM-dd-yyyy") if date_filter == "Specific Date" and hasattr(self.parent, 'date_range') else None
            
            tasks = self.db.get_tasks(category_filter if category_filter != "All" else None, 
                                    date_filter, specific_date)
            for task_id, task_text, due_date, category, recurrence, completed in tasks:
                self.updateUIWithTask(task_text, due_date, category, recurrence, completed, task_id)
            
            # Note: No client-side sorting needed - db.get_tasks() already returns tasks 
            # sorted by due_date ASC (with NULL dates last) via SQL ORDER BY clause
        except sqlite3.Error as e:
            QMessageBox.critical(self.parent, "Database Error", f"Database issue while loading tasks: {str(e)}")
            return []
        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to load tasks: {str(e)}")
            return []

    def updateTaskStyle(self, widget):
        try:
            layout = widget.layout()
            checkbox = layout.itemAt(0).widget()
            label = layout.itemAt(1).widget()
            due_date_label = layout.itemAt(3).widget()

            if checkbox and label and due_date_label:
                if checkbox.isChecked():
                    label.setStyleSheet("color: #9aa0a6; text-decoration: line-through;")
                    widget.setStyleSheet("QWidget { background-color: #22252c; border: none; }")
                else:
                    due_date = due_date_label.text()
                    if due_date != "No Date" and QDate.fromString(due_date, "MM-dd-yyyy") < QDate.currentDate():
                        label.setStyleSheet("color: #e07a7a;")
                        widget.setStyleSheet("QWidget { background-color: #2a2224; border: none; }")
                    else:
                        label.setStyleSheet("color: #e8eaed;")
                        widget.setStyleSheet("QWidget { background-color: #1c1e24; border: none; }")
        except Exception as e:
            print(f"Error updating task style: {str(e)}")
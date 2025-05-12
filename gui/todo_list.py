from PyQt6.QtWidgets import (QListWidgetItem, QWidget, QHBoxLayout, QCheckBox, 
                            QLabel, QPushButton, QSizePolicy, QListWidget, 
                            QMessageBox, QInputDialog)
from PyQt6.QtCore import Qt, QDate
import sqlite3
from core.db import DatabaseManager
from datetime import datetime

class TodoList:
    def __init__(self, parent):
        self.parent = parent
        self.db = DatabaseManager()
        self.todoList = parent.todoList

    def addTask(self):
        task_text = self.parent.taskInput.text().strip()
        due_date = self.parent.dueDateInput.date().toString("MM-dd-yyyy")
        
        if not task_text:
            QMessageBox.warning(self.parent, "Error", "Task text cannot be empty")
            return
            
        try:
            self.insertTaskIntoDB(task_text, due_date)
            self.loadTasksFromDB()
            self.parent.taskInput.clear()
            self.parent.dueDateInput.setDate(QDate.currentDate())
        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to add task: {str(e)}")

    def addTaskFromChat(self, task_text, due_date):
        try:
            print(f"To-do list adding: {task_text} due {due_date}")
            self.insertTaskIntoDB(task_text, due_date)
            self.loadTasksFromDB()
            print(f"To-do list refreshed with {self.todoList.count()} items")
        except Exception as e:
            print(f"Error adding task from chat: {str(e)}")

    def insertTaskIntoDB(self, task_text, due_date):
        try:
            self.db.add_task(None, task_text, due_date)
        except Exception as e:
            raise Exception(f"Database error: {str(e)}")

    def updateUIWithTask(self, task_text, due_date, completed=False):
        # Check for duplicates
        for i in range(self.todoList.count()):
            item = self.todoList.item(i)
            widget = self.todoList.itemWidget(item)
            if widget:
                layout = widget.layout()
                if layout.count() > 2:
                    task_label = layout.itemAt(1).widget()
                    date_label = layout.itemAt(2).widget()
                    if task_label and date_label and task_label.text() == task_text and date_label.text() == due_date:
                        return
                        
        item_widget = QWidget()
        layout = QHBoxLayout(item_widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # Checkbox
        checkbox = QCheckBox()
        checkbox.setChecked(completed)
        checkbox.stateChanged.connect(lambda state: self.updateTaskStatus(task_text, state == Qt.CheckState.Checked.value))
        layout.addWidget(checkbox, alignment=Qt.AlignmentFlag.AlignCenter)

        # Task Label
        label = QLabel(task_text)
        label.setWordWrap(True)
        label.setStyleSheet("max-width: 300px; color: white;")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(label)

        layout.addStretch(1)

        # Due Date Label
        due_date_label = QLabel(due_date)
        due_date_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        layout.addWidget(due_date_label)

        # Edit Button
        edit_button = QPushButton("Edit")
        edit_button.setFixedWidth(60)
        edit_button.clicked.connect(lambda: self.editTask(item_widget))
        edit_button.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(edit_button)

        # Delete Button
        delete_button = QPushButton("Delete")
        delete_button.setFixedWidth(60)
        delete_button.clicked.connect(lambda: self.deleteTask(item_widget))
        delete_button.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(delete_button)

        item_widget.setLayout(layout)

        list_item = QListWidgetItem(self.todoList)
        list_item.setSizeHint(item_widget.sizeHint())
        self.todoList.addItem(list_item)
        self.todoList.setItemWidget(list_item, item_widget)

        self.updateTaskStyle(item_widget)

    def updateTaskStatus(self, task_text, completed):
        try:
            self.db.update_task_status(task_text, completed)
            self.loadTasksFromDB()
        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to update task status: {str(e)}")

    def editTask(self, widget):
        try:
            task_text = widget.layout().itemAt(1).widget().text()
            due_date = widget.layout().itemAt(2).widget().text()
            
            new_text, ok = QInputDialog.getText(self.parent, "Edit Task", 
                                              "Task:", text=task_text)
            if ok and new_text:
                new_date, ok = QInputDialog.getText(self.parent, "Edit Due Date",
                                                  "Due Date (MM-DD-YYYY):", text=due_date)
                if ok and new_date:
                    # Validate date format
                    try:
                        datetime.strptime(new_date, "%m-%d-%Y")
                        self.db.delete_task(task_text)
                        self.db.add_task(None, new_text, new_date)
                        self.loadTasksFromDB()
                    except ValueError:
                        QMessageBox.warning(self.parent, "Error", "Invalid date format. Use MM-DD-YYYY")
        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to edit task: {str(e)}")

    def deleteTask(self, widget):
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
            for i in reversed(range(self.todoList.count())):
                list_item = self.todoList.item(i)
                widget = self.todoList.itemWidget(list_item)
                checkbox = widget.layout().itemAt(0).widget()
                label = widget.layout().itemAt(1).widget()
                due_date_label = widget.layout().itemAt(2).widget()

                if checkbox.isChecked():
                    task_text = label.text()
                    due_date = due_date_label.text()
                    self.db.archive_task(task_text, due_date, True)
                    self.todoList.takeItem(i)
        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to archive tasks: {str(e)}")

    def loadTasksFromDB(self):
        try:
            self.todoList.clear()
            tasks = self.db.get_tasks()
            for task_text, due_date, completed in tasks:
                self.updateUIWithTask(task_text, due_date, completed)
        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to load tasks: {str(e)}")

    def updateTaskStyle(self, widget):
        try:
            layout = widget.layout()
            checkbox = layout.itemAt(0).widget()
            label = layout.itemAt(1).widget()
            due_date_label = layout.itemAt(2).widget()

            if checkbox and label and due_date_label:
                if checkbox.isChecked():
                    label.setStyleSheet("color: gray; text-decoration: line-through;")
                else:
                    due_date = QDate.fromString(due_date_label.text(), "MM-dd-yyyy")
                    if due_date < QDate.currentDate():
                        label.setStyleSheet("color: red;")
                    else:
                        label.setStyleSheet("color: white;")
        except Exception as e:
            print(f"Error updating task style: {str(e)}")
   
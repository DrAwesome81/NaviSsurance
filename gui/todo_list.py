from PyQt6.QtWidgets import QListWidgetItem, QWidget, QHBoxLayout, QCheckBox, QLabel, QPushButton, QSizePolicy, QListWidget
from PyQt6.QtCore import Qt, QDate
import sqlite3
from core.db import DatabaseManager

class TodoList:
    def __init__(self, parent):
        self.parent = parent
        self.db = DatabaseManager()
        self.todoList = parent.todoList

    def addTask(self):
        task_text = self.parent.taskInput.text().strip()
        due_date = self.parent.dueDateInput.date().toString("MM-dd-yyyy")
        if task_text:
            self.insertTaskIntoDB(task_text, due_date)
            self.loadTasksFromDB()
            self.parent.taskInput.clear()
            self.parent.dueDateInput.setDate(QDate.currentDate())

    def addTaskFromChat(self, task_text, due_date):
            print(f"To-do list adding: {task_text} due {due_date}")
            self.loadTasksFromDB()
            print(f"To-do list refreshed with {self.todoList.count()} items")

    def insertTaskIntoDB(self, task_text, due_date):
        self.db.add_task(None, task_text, due_date) # No session ID needed here

    def updateUIWithTask(self, task_text, due_date):
        # Check for duplicates
        for i in range(self.todoList.count()):
            item = self.todoList.item(i)
            widget = self.todoList.itemWidget(item)
            if widget:
                layout = widget.layout()
                if layout.count() > 2:  # Ensure due date label exists
                    task_label = layout.itemAt(1).widget()  # Task text
                    date_label = layout.itemAt(2).widget()  # Due date
                    if task_label and date_label and task_label.text() == task_text and date_label.text() == due_date:
                        return  # Skip if both match
                        
        item_widget = QWidget()
        layout = QHBoxLayout(item_widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5) # Adjust spacing between widgets within a row

        # Checkbox first
        checkbox = QCheckBox()
        checkbox.stateChanged.connect(self.updateTaskStyle)
        layout.addWidget(checkbox, alignment=Qt.AlignmentFlag.AlignCenter)

        # Task Label
        label = QLabel(task_text)
        label.setWordWrap(True)  # Enable word wrapping
        label.setStyleSheet("max-width: 300px;")  # Adjust this width for less aggressive wrapping
        label.setStyleSheet("color: white;")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        label.setAlignment(Qt.AlignmentFlag.AlignTop)  # Ensure left and top alignment
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignTop)  # Align label to top for matching with checkbox

        layout.addStretch(1)  # Adjust stretch to control space between elements

        # Due Date Label
        due_date_label = QLabel(due_date)
        due_date_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)  # Align to top and right
        layout.addWidget(due_date_label, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        # Delete Button
        delete_button = QPushButton("Delete")
        delete_button.setFixedWidth(100)  # Adjusted width to fit "Delete" text
        delete_button.clicked.connect(lambda: self.deleteTask(item_widget))
        delete_button.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(delete_button, alignment=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignRight)

        item_widget.setLayout(layout)

        list_item = QListWidgetItem(self.todoList)
        list_item.setSizeHint(item_widget.sizeHint())
        self.todoList.addItem(list_item)
        self.todoList.setItemWidget(list_item, item_widget)

        self.updateTaskStyle()  # Adjust task styles for overdue/completed tasks         

    def updateTaskStyle(self):
        for i in range(self.todoList.count()):
            list_item = self.todoList.item(i)
            widget = self.todoList.itemWidget(list_item)
            if widget:
                layout = widget.layout()
                checkbox = layout.itemAt(0).widget()
                label = layout.itemAt(1).widget()
                due_date_label = layout.itemAt(2).widget() if layout.count() > 2 else None

                if checkbox and label and due_date_label:
                    if checkbox.isChecked():
                        label.setStyleSheet("color: gray; text-decoration: line-through;")
                    else:
                        label.setStyleSheet("")
                    
                        if due_date_label:
                            due_date = QDate.fromString(due_date_label.text(), "MM-dd-yyyy")
                        if due_date < QDate.currentDate():
                            label.setStyleSheet("color: red;")

                        # Set vertical alignment for the due date label
                        layout.setAlignment(due_date_label, Qt.AlignmentFlag.AlignVCenter)
                        due_date_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)  

    def deleteTask(self, widget):
        for i in range(self.todoList.count()):
            list_item = self.todoList.item(i)
            if self.todoList.itemWidget(list_item) == widget:
                task_text = widget.layout().itemAt(1).widget().text()
                self.db.delete_task(task_text)
                self.todoList.takeItem(i)
                break                       

    def archiveCompletedTasks(self):
        for i in reversed(range(self.todoList.count())):
            list_item = self.todoList.item(i)
            widget = self.todoList.itemWidget(list_item)
            checkbox = widget.layout().itemAt(0).widget()
            label = widget.layout().itemAt(1).widget()
            due_date_label = widget.layout().itemAt(2).widget()

            if checkbox.isChecked():
                task_text = label.text()
                due_date = due_date_label.text()
                self.cursor.execute("INSERT INTO archived_tasks (task, due_date) VALUES (?, ?)", (task_text, due_date))
                self.conn.commit()
                self.todoList.takeItem(i)

    def loadTasksFromDB(self):
        self.todoList.clear()
        tasks = self.db.get_tasks()
        for task_text, due_date in tasks:
            self.updateUIWithTask(task_text, due_date)
   
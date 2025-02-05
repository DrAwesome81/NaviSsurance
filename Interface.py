import sys
import json
import sqlite3
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QPushButton, 
    QLineEdit, QTextEdit, QScrollArea, QMessageBox, QFileDialog, QListWidget, 
    QListWidgetItem, QHBoxLayout, QCheckBox, QDateEdit, QSplitter
)
from PyQt6.QtCore import Qt, QDate, QThread, pyqtSignal, pyqtSlot
import PyQt6.QtGui
from PyQt6.QtGui import QAction
from grok_chat import ChatHandler
import os
import markdown
import re
from dateutil import parser

class ChatThread(QThread):
    response_signal = pyqtSignal(str)

    def __init__(self, chatHandler, message, session_id, history):
        super().__init__()
        self.chat_handler = chatHandler
        # comment out: print(f"ChatHandler type: {type(self.chat_handler)}")  # Debug to confirm type
        self.message = message
        self.session_id = session_id
        self.history = history

    def run(self):
        try:
            # comment out: print(f"[DEBUG] In ChatThread.run(), self is of type: {type(self)}")  # Confirm type
            # comment out: print(f"ChatThread started for session {self.session_id}")  # Debug statement

            # This step triggers the task addition logic
            response = self.chat_handler.get_response(self.message, self.session_id, self.history)
            # comment out: print(f"Received response: {response}")  # Debug statement

            if response:
                if "I've added the task" in response:
                    task_match = re.search(r"'([^']*)'", response)
                    date_match = re.search(r'due on (\d{2}-\d{2}-\d{4})', response)

                    if task_match and date_match:
                        task_text = task_match.group(1)
                        due_date = date_match.group(1)

                        # Ensure task_added_signal is emitted from ChatThread, not ChatHandler
                        # comment out: print("[DEBUG] Emitting task_added_signal from ChatThread")  # Debug
                        self.chat_handler.task_added_signal.emit(task_text, due_date)  # Emit from ChatThread instance directly
                self.response_signal.emit(response)
            else:
                print("ChatThread: No response received.")  # Debug statement
                self.response_signal.emit("Error: No response received.")
        except Exception as e:
            print(f"ChatThread: Exception occurred: {e}")
            self.response_signal.emit(f"Error: {str(e)}")




class ChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.chat_handler = ChatHandler(self)
        # comment out: print(f"task_added_signal exists: {hasattr(self.chat_handler, 'task_added_signal')}")
        self.session_id = f"SESSION_GUI_{hash(str(self))}"
        self.conversation_history = []
        self.initDatabase()
        # comment out: print("Database initialized")
        self.initUI()

    def initDatabase(self):
        self.conn = sqlite3.connect("todo.db")
        self.cursor = self.conn.cursor()
        try:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT,
                    due_date TEXT
                )
            """)
            # comment out: print("Tasks table created or already exists")

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS archived_tasks (
                    id INTEGER PRIMARY KEY,
                    task TEXT,
                    due_date TEXT
                )
            """)
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"An error occurred while creating tables: {e}")

    def closeEvent(self, event):
        self.conn.close()
        super().closeEvent(event)

    def initUI(self):
        # comment out: print("Starting initUI")
        self.setWindowTitle('NaviSsurance')
        self.setGeometry(300, 300, 1000, 600)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        self.chatThread = ChatThread(self.chat_handler, "", self.session_id, self.conversation_history)
        self.chatThread.response_signal.connect(self.onResponseReceived)
        self.chat_handler.task_added_signal.connect(self.addTaskFromChat)  # Connect the new signal

        # Splitter for dividing chat and to-do list
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Chat panel
        chatWidget = QWidget()
        chatWidget.setMinimumSize(400, 600)
        chat_layout = QVBoxLayout(chatWidget)

        self.chatDisplay = QTextEdit(self)
        self.chatDisplay.setReadOnly(True)
        chat_layout.addWidget(self.chatDisplay)

        self.userInput = QLineEdit(self)
        self.userInput.setPlaceholderText("Type your message here...")
        self.userInput.returnPressed.connect(self.sendMessage)
        chat_layout.addWidget(self.userInput)

        self.sendButton = QPushButton("Send", self)
        self.sendButton.clicked.connect(self.sendMessage)
        chat_layout.addWidget(self.sendButton)

        splitter.addWidget(chatWidget)

        # To-do list panel
        todoWidget = QWidget()
        todoWidget.setMinimumSize(350, 600)
        todo_layout = QVBoxLayout(todoWidget)

        self.todoList = QListWidget(self)
        todo_layout.addWidget(self.todoList)

        add_task_layout = QHBoxLayout()
        self.taskInput = QLineEdit(self)
        self.taskInput.setPlaceholderText("Enter a task...")
        add_task_layout.addWidget(self.taskInput)

        self.dueDateInput = QDateEdit(self)
        self.dueDateInput.setCalendarPopup(True)
        self.dueDateInput.setDate(QDate.currentDate())
        add_task_layout.addWidget(self.dueDateInput)

        self.addTaskButton = QPushButton("Add Task", self)
        self.addTaskButton.clicked.connect(self.addTask)
        add_task_layout.addWidget(self.addTaskButton)

        todo_layout.addLayout(add_task_layout)

        self.archiveButton = QPushButton("Archive Completed Tasks", self)
        self.archiveButton.clicked.connect(self.archiveCompletedTasks)
        todo_layout.addWidget(self.archiveButton)

        splitter.addWidget(todoWidget)

        self.loadTasksFromDB()
        # comment out: print("Finished loading tasks from DB")

        splitter.setSizes([7, 3])  # Chat: 70%, To-do: 30%
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)

        layout = QVBoxLayout(central_widget)
        layout.addWidget(splitter)

        # Menu Bar
        menubar = self.menuBar()
        fileMenu = menubar.addMenu('File')

        saveAction = QAction('Save Chat', self)
        saveAction.triggered.connect(self.saveChat)
        fileMenu.addAction(saveAction)

        loadAction = QAction('Load Chat', self)
        loadAction.triggered.connect(self.loadChat)
        fileMenu.addAction(loadAction)

    def loadTasksFromDB(self):
        self.todoList.clear()
        self.cursor.execute("""
        SELECT task, due_date 
        FROM tasks
        ORDER BY date(due_date, 'start of day') ASC
        """)
        tasks = self.cursor.fetchall()

        for task_text, due_date in tasks:
            # Convert due_date to QDate for easier comparison
            due_date_qt = QDate.fromString(due_date, "MM-dd-yyyy")

            # Sort tasks in Python if SQLite can't handle the date format
            sorted_tasks = sorted(tasks, key=lambda x: QDate.fromString(x[1], "MM-dd-yyyy"))

            # Clear the list to ensure we start with a clean slate before adding sorted tasks
            self.todoList.clear()

            for task_text, due_date in sorted_tasks:
                self.updateUIWithTask(task_text, due_date)
    
    def addTask(self):
        task_text = self.taskInput.text().strip()
        due_date = self.dueDateInput.date().toString("MM-dd-yyyy")

        if task_text:
            # comment out: print("Starting to insert task into DB")
            self.insertTaskIntoDB(task_text, due_date)  # Insert the task into the database
            # comment out: print("Finished inserting task into DB")

            # comment out: print("Refreshing tasks from DB to update UI")
            self.loadTasksFromDB()  # Refresh the UI by loading tasks from the database
            # comment out: print("UI refreshed with tasks from DB")

            # Clear input fields
            self.taskInput.clear()
            self.dueDateInput.setDate(QDate.currentDate())
    
    def addTaskFromChat(self, task_text, due_date):
        # comment out: print(f"Adding task from chat: {task_text}")
        self.insertTaskIntoDB(task_text, due_date)  # Add to DB
        self.loadTasksFromDB() # Refresh the UI by loading tasks from the database

    def insertTaskIntoDB(self, task_text, due_date):
        try:
            self.cursor.execute("""
                INSERT INTO tasks (task, due_date) VALUES (?, ?)
            """, (task_text, due_date))
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"Database error: {3}")
    
    def updateUIWithTask(self, task_text, due_date):
        # Check for duplicates before adding
        for i in range(self.todoList.count()):
            item = self.todoList.item(i)
            widget = self.todoList.itemWidget(item)
            if widget:
                layout = widget.layout()
                if layout.count() > 1:  # Ensure we have at least two items in the layout
                    label = layout.itemAt(1).widget()
                    if label and label.text() == task_text:
                        return  # Task already exists, skip

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
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)  # Ensure left and top alignment
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
        delete_button.setStyleSheet("text-align: center;")  # Right align text inside button
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
                        # comment out: print("Parsed due date:", due_date.toString("MM-dd-yyyy"))
                        #comment out: print("Is overdue:", due_date < QDate.currentDate())
                        if due_date < QDate.currentDate():
                            label.setStyleSheet("color: red;")

    def deleteTask(self, widget):
        for i in range(self.todoList.count()):
            list_item = self.todoList.item(i)
            if self.todoList.itemWidget(list_item) == widget:
                task_text = widget.layout().itemAt(1).widget().text()
                self.cursor.execute("DELETE FROM tasks WHERE task = ?", (task_text,))
                self.conn.commit()
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

    def sendMessage(self):
        user_message = self.userInput.text()
        if not user_message.strip():
            return

        self.chatDisplay.append(f"<b>You:</b> {user_message}")
        self.sendButton.setEnabled(False)
        self.userInput.setEnabled(False)
        self.conversation_history.append({"role": "user", "content": user_message})
        self.chat_handler.save_message(self.session_id, "user", user_message)

        self.chatThread = ChatThread(self.chat_handler, user_message, self.session_id, self.conversation_history)
        self.chatThread.response_signal.connect(self.onResponseReceived)
        self.chatThread.start()

    @pyqtSlot(str)
    def onResponseReceived(self, response):
        # comment out: print(f"Response received: {response}")  # Debug statement
        html_content = markdown.markdown(response)

        # Ensure the response ends with proper HTML to close any open lists
        if html_content.endswith('<li>'):
            html_content += '</li></ul>'  # Close last list item and the list itself
        elif '<li>' in html_content and not html_content.endswith('</ul>'):
            html_content += '</ul>'  # If there's an <li> but no closing </ul>

        self.chatDisplay.append(f"<b>Navi:</b> {html_content}")
        self.conversation_history.append({"role": "assistant", "content": response})
        self.chat_handler.save_message(self.session_id, "assistant", response)
        self.sendButton.setEnabled(True)
        self.userInput.setEnabled(True)
        self.userInput.clear()
        self.userInput.setFocus()

    def saveChat(self):
        fileName, _ = QFileDialog.getSaveFileName(self, "Save Chat History", "", "JSON Files (*.json)")
        if fileName:
            with open(fileName, 'w') as file:
                json.dump(self.conversation_history, file)

    def loadChat(self):
        fileName, _ = QFileDialog.getOpenFileName(self, "Load Chat History", "", "JSON Files (*.json)")
        if fileName:
            with open(fileName, 'r') as file:
                self.conversation_history = json.load(file)
                self.chatDisplay.clear()
                for entry in self.conversation_history:
                    role = "You" if entry["role"] == "user" else "Navi"
                    self.chatDisplay.append(f"<b>{role}:</b> {entry['content']}")

    def closeEvent(self, event):
        self.conn.close()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Load styles
    with open("styles.qss", "r") as f:
        stylesheet = f.read()  # Assign the read content to a variable
        app.setStyleSheet(stylesheet)  # Apply the stylesheet
        

    chatWindow = ChatWindow()
    chatWindow.show()
    sys.exit(app.exec())




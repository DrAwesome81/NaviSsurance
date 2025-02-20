# interface.py (top unchanged)
import sqlite3
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QSplashScreen, QTextBrowser, QLineEdit, QPushButton, QListWidget, QDateEdit
from PyQt6.QtCore import Qt, QDate, QTimer, pyqtSlot
from PyQt6.QtGui import QPixmap, QAction
from core.db import DatabaseManager
from gui.chat_window import ChatThread, onResponseReceived, sendMessage, saveChat, loadChat
from gui.todo_list import TodoList
from core.chat import ChatHandler

class ChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        pixmap = QPixmap("logo v2.png")
        self.splash = QSplashScreen(pixmap)
        self.splash.show()
        QTimer.singleShot(2000, self.show_main_window)

        self.chat_handler = ChatHandler(self)
        self.session_id = f"SESSION_GUI_{hash(str(self))}"
        self.conversation_history = []
        self.todoList = QListWidget(self)  # Create the widget early
        self.todo_list = TodoList(self)    # Pass ChatWindow with todoList set
        self.initUI()

    def show_main_window(self):
        self.splash.finish(self)
        self.show()

    def initUI(self):
        self.setWindowTitle('NaviSsurance')
        self.setGeometry(300, 300, 1000, 600)
        self.loadStylesheet("styles.qss")

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        self.chat_handler.task_added_signal.connect(self.addTaskFromChat)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        main_layout.addWidget(splitter)

        # Chat panel
        chatWidget = QWidget()
        chatWidget.setMinimumSize(400, 600)
        chatWidget.setStyleSheet("background-color: rgb(20, 20, 22);")
        chat_layout = QVBoxLayout(chatWidget)

        self.chatDisplay = QTextBrowser(self)
        self.chatDisplay.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.chatDisplay.setOpenExternalLinks(True)
        self.chatDisplay.setReadOnly(True)
        chat_layout.addWidget(self.chatDisplay)

        self.userInput = QLineEdit(self)
        self.userInput.setPlaceholderText("Type your message here...")
        self.userInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.userInput.returnPressed.connect(self.sendMessage)
        chat_layout.addWidget(self.userInput)

        self.sendButton = QPushButton("Send", self)
        self.sendButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.sendButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sendButton.clicked.connect(self.sendMessage)
        chat_layout.addWidget(self.sendButton)

        splitter.addWidget(chatWidget)

        # To-do list panel
        todoWidget = QWidget()
        todoWidget.setMinimumSize(350, 600)
        todoWidget.setStyleSheet("background-color: rgb(20, 20, 22);")
        todo_layout = QVBoxLayout(todoWidget)

        # Use the existing self.todoList from __init__
        self.todoList.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")  # Line 96
        todo_layout.addWidget(self.todoList)

        add_task_layout = QHBoxLayout()
        self.taskInput = QLineEdit(self)
        self.taskInput.setPlaceholderText("Enter a task...")
        self.taskInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        add_task_layout.addWidget(self.taskInput)

        self.dueDateInput = QDateEdit(self)
        self.dueDateInput.setCalendarPopup(True)
        self.dueDateInput.setDate(QDate.currentDate())
        self.dueDateInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        add_task_layout.addWidget(self.dueDateInput)

        self.addTaskButton = QPushButton("Add Task", self)
        self.addTaskButton.clicked.connect(self.addTask)
        self.addTaskButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.addTaskButton.setCursor(Qt.CursorShape.PointingHandCursor)
        add_task_layout.addWidget(self.addTaskButton)

        todo_layout.addLayout(add_task_layout)

        self.archiveButton = QPushButton("Archive Completed Tasks", self)
        self.archiveButton.clicked.connect(self.archiveCompletedTasks)
        self.archiveButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.archiveButton.setCursor(Qt.CursorShape.PointingHandCursor)
        todo_layout.addWidget(self.archiveButton)

        splitter.addWidget(todoWidget)

        splitter.setSizes([7, 3])
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)

        # Menu Bar
        menubar = self.menuBar()
        fileMenu = menubar.addMenu('File')
        saveAction = QAction('Save Chat', self)
        saveAction.triggered.connect(lambda: saveChat(self))
        fileMenu.addAction(saveAction)
        loadAction = QAction('Load Chat', self)
        loadAction.triggered.connect(lambda: loadChat(self))
        fileMenu.addAction(loadAction)

        # Load tasks at the end
        self.todo_list.loadTasksFromDB()

    def sendMessage(self):
        user_message = self.userInput.text()
        if not user_message.strip():
            return
        self.chatDisplay.append(f"<b>You:</b> {user_message}<br><br>")
        self.sendButton.setEnabled(False)
        self.userInput.setEnabled(False)
        self.conversation_history.append({"role": "user", "content": user_message})
        self.chat_handler.save_message(self.session_id, "user", user_message)
        self.chatThread = ChatThread(self.chat_handler, user_message, self.session_id, self.conversation_history)
        self.chatThread.response_signal.connect(self.onResponseReceived)
        self.chatThread.start()
        self.chatThread.finished.connect(lambda: print("Thread finished"))

    def addTaskFromChat(self, task_text, due_date):
        print(f"Signal received: {task_text} due {due_date}")
        self.todo_list.addTaskFromChat(task_text, due_date)

    def addTask(self):
        self.todo_list.addTask()

    @pyqtSlot(str)  # Add this decorator to handle the signal
    def onResponseReceived(self, response):
        self.chatDisplay.append(f"<b>Navi:</b> {response}<br><br>")
        self.conversation_history.append({"role": "assistant", "content": response})
        self.chat_handler.save_message(self.session_id, "assistant", response)
        self.sendButton.setEnabled(True)  # Turn button back on
        self.userInput.setEnabled(True)   # Turn input back on
        self.userInput.clear()            # Clear the input
        self.userInput.setFocus()         # Put cursor back in input

    def archiveCompletedTasks(self):
        self.todo_list.archiveCompletedTasks()

    def loadStylesheet(self, filename):
        try:
            with open(filename, "r") as f:
                self.setStyleSheet(f.read())
        except FileNotFoundError:
            print(f"Stylesheet '{filename}' not found.")
        except Exception as e:
            print(f"Error loading stylesheet: {e}")

    def closeEvent(self, event):
        super().closeEvent(event)
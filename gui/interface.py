import sqlite3
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QSplashScreen, 
                            QTextBrowser, QLineEdit, QPushButton, QListWidget, QDateEdit, QTableWidget, 
                            QTableWidgetItem, QCheckBox, QComboBox, QLabel, QSplitter, QTextEdit)
from PyQt6.QtCore import Qt, QDate, QTimer, pyqtSlot
from PyQt6.QtGui import QPixmap, QAction
from core.db import DatabaseManager
from gui.chat_window import ChatThread, onResponseReceived, sendMessage, saveChat, loadChat
from gui.todo_list import TodoList
from core.chat import ChatManager

class ChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        pixmap = QPixmap("logo v2.png")
        self.splash = QSplashScreen(pixmap)
        self.splash.show()
        QTimer.singleShot(2000, self.show_main_window)

        self.chat_handler = ChatManager(self)
        self.session_id = f"SESSION_GUI_{hash(str(self))}"
        self.conversation_history = []
        self.todoList = QListWidget(self)
        self.todo_list = TodoList(self)
        self.initUI()
        self.chat_handler.start_briefing()

    def show_main_window(self):
        self.splash.finish(self)
        self.show()

    # Define all methods before initUI
    def search_leads(self):
        print("Lead search TBD")

    def refresh_leads(self):
        print("Weekly lead refresh TBD (Grok 3 API pending)")

    def generate_document(self):
        print("Doc generation TBD")

    def save_document(self):
        print("Doc save TBD")

    def start_recording(self):
        print("Recording TBD")

    def stop_recording(self):
        print("Stop recording TBD")

    def transcribe_meeting(self):
        print("Transcription TBD")

    def save_transcript(self):
        print("Transcript save TBD")

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

    @pyqtSlot(str)  
    def onResponseReceived(self, response):
        self.chatDisplay.append(f"<b>Navi:</b> {response}<br><br>")
        self.conversation_history.append({"role": "assistant", "content": response})
        self.chat_handler.save_message(self.session_id, "assistant", response)
        self.sendButton.setEnabled(True)
        self.userInput.setEnabled(True)
        self.userInput.clear()
        self.userInput.setFocus()

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

    def initUI(self):
        self.setWindowTitle('NaviSsurance')
        self.setGeometry(300, 300, 1200, 700)
        self.loadStylesheet("styles.qss")

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        self.chat_handler.task_added_signal.connect(self.addTaskFromChat)

        # Tab widget with white text
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabBar::tab { color: white; background-color: rgb(20, 20, 22); } "
                          "QTabBar::tab:selected { background-color: rgba(253, 98, 98, 0.8); }")
        main_layout.addWidget(tabs)

        # Chat & Tasks Tab (Splitter)
        chat_tasks_tab = QWidget()
        chat_tasks_layout = QVBoxLayout(chat_tasks_tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Chat Panel
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        self.chatDisplay = QTextBrowser(self)
        self.chatDisplay.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.chatDisplay.setOpenExternalLinks(True)
        self.chatDisplay.setReadOnly(True)
        chat_layout.addWidget(self.chatDisplay)
        chat_input_layout = QHBoxLayout()
        self.userInput = QLineEdit(self)
        self.userInput.setPlaceholderText("Type your message here...")
        self.userInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.userInput.returnPressed.connect(self.sendMessage)
        chat_input_layout.addWidget(self.userInput)
        self.sendButton = QPushButton("Send", self)
        self.sendButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.sendButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sendButton.clicked.connect(self.sendMessage)
        chat_input_layout.addWidget(self.sendButton)
        chat_layout.addLayout(chat_input_layout)
        splitter.addWidget(chat_widget)

        # Tasks Sidebar
        tasks_widget = QWidget()
        tasks_layout = QVBoxLayout(tasks_widget)
        self.todoList.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        tasks_layout.addWidget(self.todoList)
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
        tasks_layout.addLayout(add_task_layout)
        self.archiveButton = QPushButton("Archive Completed Tasks", self)
        self.archiveButton.clicked.connect(self.archiveCompletedTasks)
        self.archiveButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.archiveButton.setCursor(Qt.CursorShape.PointingHandCursor)
        tasks_layout.addWidget(self.archiveButton)
        splitter.addWidget(tasks_widget)
        
        splitter.setSizes([700, 300])
        chat_tasks_layout.addWidget(splitter)
        tabs.addTab(chat_tasks_tab, "Chat & Tasks")

        # Leads Tab
        leads_tab = QWidget()
        leads_layout = QVBoxLayout(leads_tab)
        leads_search_layout = QHBoxLayout()
        self.leadSearchInput = QLineEdit(self)
        self.leadSearchInput.setPlaceholderText("Search leads (e.g., 'AI startup')...")
        self.leadSearchInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        leads_search_layout.addWidget(self.leadSearchInput)
        self.leadSearchButton = QPushButton("Search Leads", self)
        self.leadSearchButton.clicked.connect(self.search_leads)
        self.leadSearchButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        leads_search_layout.addWidget(self.leadSearchButton)
        self.refreshLeadsButton = QPushButton("Refresh Leads (Weekly)", self)
        self.refreshLeadsButton.clicked.connect(self.refresh_leads)  # Now defined
        self.refreshLeadsButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.refreshLeadsButton.setEnabled(False)
        leads_search_layout.addWidget(self.refreshLeadsButton)
        leads_layout.addLayout(leads_search_layout)
        self.leadFilters = QWidget()
        filters_layout = QHBoxLayout(self.leadFilters)
        self.emailFilter = QCheckBox("Emails", checked=True)
        self.dropboxFilter = QCheckBox("Dropbox", checked=True)
        self.unrepliedFilter = QCheckBox("Unreplied")
        filters_layout.addWidget(self.emailFilter)
        filters_layout.addWidget(self.dropboxFilter)
        filters_layout.addWidget(self.unrepliedFilter)
        leads_layout.addWidget(self.leadFilters)
        self.leadsTable = QTableWidget(0, 4)
        self.leadsTable.setHorizontalHeaderLabels(["Source", "Sender/Filename", "Snippet", "Action"])
        self.leadsTable.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        leads_layout.addWidget(self.leadsTable)
        tabs.addTab(leads_tab, "Leads")

        # Docs Tab (Placeholder)
        docs_tab = QWidget()
        docs_layout = QVBoxLayout(docs_tab)
        docs_layout.addWidget(QLabel("Document generation coming soon!"))
        tabs.addTab(docs_tab, "Docs")

        # Meetings Tab
        meetings_tab = QWidget()
        meetings_layout = QVBoxLayout(meetings_tab)
        self.recordButton = QPushButton("Start Recording", self)
        self.recordButton.clicked.connect(self.start_recording)
        self.recordButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        meetings_layout.addWidget(self.recordButton)
        self.stopButton = QPushButton("Stop Recording", self)
        self.stopButton.clicked.connect(self.stop_recording)
        self.stopButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.stopButton.setEnabled(False)
        meetings_layout.addWidget(self.stopButton)
        self.transcribeButton = QPushButton("Generate Transcript", self)
        self.transcribeButton.clicked.connect(self.transcribe_meeting)  # Now defined
        self.transcribeButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.transcribeButton.setEnabled(False)
        meetings_layout.addWidget(self.transcribeButton)
        self.meetingTranscript = QTextEdit(self)
        self.meetingTranscript.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.meetingTranscript.setReadOnly(True)
        meetings_layout.addWidget(self.meetingTranscript)
        self.saveTranscriptButton = QPushButton("Save Transcript", self)
        self.saveTranscriptButton.clicked.connect(self.save_transcript)
        self.saveTranscriptButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.saveTranscriptButton.setEnabled(False)
        meetings_layout.addWidget(self.saveTranscriptButton)
        tabs.addTab(meetings_tab, "Meetings")

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

    @pyqtSlot(str)  
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
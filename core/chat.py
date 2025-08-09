from PyQt6.QtCore import QObject, pyqtSignal
from core.chat_handler import ChatHandler
from core.response_handler import ResponseHandler

class ChatManager(QObject):  # Inherit QObject for signals
    task_added_signal = pyqtSignal(str, str)  # Define the signal here

    def __init__(self, chat_window=None):
        super().__init__()
        self.chat_handler = ChatHandler(chat_window)
        self.db = self.chat_handler.db
        self.response_handler = ResponseHandler(self.chat_handler)
        # Connect ChatHandler's signal to ChatManager's signal properly
        self.chat_handler.task_added_signal.connect(self.task_added_signal)

    def start_briefing(self):
        # Daily briefing disabled - only runs when explicitly requested
        pass

    def get_response(self, message, session_id, conversation_history):
        return self.response_handler.get_response(message, session_id, conversation_history)

    def save_message(self, session_id, role, content):
        self.chat_handler.save_message(session_id, role, content)

    def get_chat_history(self, session_id):
        return self.chat_handler.get_chat_history(session_id)
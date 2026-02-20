from PyQt6.QtCore import QObject, pyqtSignal
from core.chat_handler import ChatHandler
from core.response_handler import ResponseHandler
from datetime import datetime, timezone

class ChatManager(QObject):  # Inherit QObject for signals
    task_added_signal = pyqtSignal(str, str)  # Define the signal here

    def __init__(self, chat_window=None):
        super().__init__()
        # chat_window can be ChatWindow instance or DatabaseManager (for backward compatibility)
        if hasattr(chat_window, 'db'):
            # It's a ChatWindow instance
            self.chat_handler = ChatHandler(chat_window)
            self.db = self.chat_handler.db
            self.response_handler = ResponseHandler(self.chat_handler, chat_window)
        else:
            # It's a DatabaseManager (old signature)
            self.chat_handler = ChatHandler(None)
            self.db = chat_window if chat_window else self.chat_handler.db
            self.response_handler = ResponseHandler(self.chat_handler, None)
        # Set up task added callback to emit our signal
        self.chat_handler.task_added_callback = self.task_added_signal.emit

    def start_briefing(self):
        """Generate daily briefing if it hasn't been shown today."""
        try:
            last_run_timestamp = self.db.get_last_run()
            
            # Check if briefing was already generated today
            if last_run_timestamp:
                last_run_date = datetime.fromtimestamp(last_run_timestamp, tz=timezone.utc).date()
                today = datetime.now(timezone.utc).date()
                
                # If briefing was already generated today, return None
                if last_run_date == today:
                    return None
            
            # Generate new briefing
            briefing = self.chat_handler.daily_briefing()
            return briefing
            
        except Exception as e:
            print(f"Error in start_briefing: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_response(self, message, session_id, conversation_history):
        return self.response_handler.get_response(message, session_id, conversation_history)

    def save_message(self, session_id, role, content):
        self.chat_handler.save_message(session_id, role, content)

    def get_chat_history(self, session_id):
        return self.chat_handler.get_chat_history(session_id)
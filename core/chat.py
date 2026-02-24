from PyQt6.QtCore import QObject, pyqtSignal
from core.chat_handler import ChatHandler
from core.db import DatabaseManager
from core.response_handler import ResponseHandler
from datetime import datetime, timezone

class ChatManager(QObject):  # Inherit QObject for signals
    task_added_signal = pyqtSignal(str, str)  # Define the signal here

    def __init__(self, chat_window=None):
        super().__init__()
        # chat_window can be ChatWindow instance or DatabaseManager (for backward compatibility)
        # DatabaseManager has no 'db' attribute; ChatWindow has self.db
        if isinstance(chat_window, DatabaseManager):
            self.chat_handler = ChatHandler(None, db=chat_window)
            self.db = chat_window
            self.response_handler = ResponseHandler(self.chat_handler, None)
            self.chat_handler.task_added_callback = None  # No UI to update in backward compat
        elif chat_window is not None and hasattr(chat_window, 'db'):
            self.chat_handler = ChatHandler(chat_window)
            self.db = self.chat_handler.db
            self.response_handler = ResponseHandler(self.chat_handler, chat_window)
            self.chat_handler.task_added_callback = self.task_added_signal.emit
        else:
            self.chat_handler = ChatHandler(None)
            self.db = self.chat_handler.db
            self.response_handler = ResponseHandler(self.chat_handler, None)
            self.chat_handler.task_added_callback = None

    def start_briefing(self):
        """Generate daily briefing if it hasn't been shown today."""
        try:
            last_run_timestamp = self.db.get_last_run()
            
            # Check if briefing was already generated today
            if last_run_timestamp:
                last_run_date = datetime.fromtimestamp(last_run_timestamp, tz=timezone.utc).date()
                today = datetime.now(timezone.utc).date()
                
                # If briefing was already generated today, return cached content.
                if last_run_date == today:
                    today_str = today.strftime("%Y-%m-%d")
                    try:
                        if hasattr(self.chat_handler, "get_cached_daily_briefing"):
                            cached = self.chat_handler.get_cached_daily_briefing(for_utc_date=today_str)
                        else:
                            cached_date = str(self.db.get_setting("daily_briefing_latest_date", "") or "").strip()
                            cached = str(self.db.get_setting("daily_briefing_latest_text", "") or "").strip() if cached_date == today_str else ""
                        if cached:
                            return cached
                    except Exception:
                        pass
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
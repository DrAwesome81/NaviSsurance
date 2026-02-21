import sys
import os
import pytest
from unittest.mock import Mock, patch

if not os.getenv("RUN_GUI_TESTS"):
    pytest.skip("GUI-dependent tests are disabled by default (set RUN_GUI_TESTS=1 to enable).", allow_module_level=True)

pytest.importorskip("PyQt6")
from core.chat_handler import ChatHandler

def test_daily_briefing():
    print("Running test_daily_briefing")
    handler = ChatHandler(None)
    handler.data_fetcher = Mock()
    handler.data_fetcher.DB_FILE = "test.db"
    handler.data_fetcher.get_calendar_events.return_value = [{"summary": "Test", "start": {"date": "2025-02-26"}}]
    handler.data_fetcher.get_new_emails.return_value = []
    handler.data_fetcher.get_email_details.return_value = {"payload": {"headers": [{"name": "From", "value": "test@example.com"}, {"name": "Subject", "value": "Test"}]}}
    handler.data_fetcher.get_sent_emails.return_value = []
    handler.db = Mock(db_name="test.db")
    handler.db.get_last_run.return_value = 1740595995
    handler.db.update_last_run.return_value = None
    # Mock sqlite3.connect for all DB calls
    with patch('sqlite3.connect') as mock_connect:
        mock_conn = mock_connect.return_value
        mock_conn.__enter__.return_value = mock_conn
        mock_cursor = Mock()
        mock_conn.execute.return_value = mock_cursor
        # Mock tasks query
        mock_cursor.fetchall.side_effect = [
            [("Test task", "2025-02-26")],  # Tasks
            [],  # New emails (empty for now)
            [("test@example.com", "Test email", 1740595000)]  # Unreplied
        ]
        briefing = handler.daily_briefing()
    print(f"Briefing: {briefing}")
    assert "Daily Briefing" in briefing
    
from PyQt6.QtCore import QObject, pyqtSignal
import sqlite3
from datetime import datetime, timedelta, UTC
from dateutil import parser
from core.db import DatabaseManager
from core.data_fetch import DataFetcher

class ChatHandler(QObject):
    task_added_signal = pyqtSignal(str, str)

    def __init__(self, chat_window=None):
        super().__init__()
        self.chat_window = chat_window
        self.db = DatabaseManager()
        self.db.init_email_calendar_tables()
        self.db.init_last_run_table()
        self.data_fetcher = DataFetcher()
        self.last_search_results = []

    def start_briefing(self):
        last_run = self.db.get_last_run()
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        last_run_date = datetime.fromtimestamp(last_run, UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        print(f"Last run: {last_run} ({last_run_date}), Today: {today}")
        if last_run_date < today:
            print("Running daily briefing—new day detected")
            briefing = self.daily_briefing()
            self.chat_window.chatDisplay.append(f"<b>Navi:</b> {briefing}<br><br>")
        else:
            print("Skipping daily briefing—already ran today")

    def daily_briefing(self):
        last_run = self.db.get_last_run()
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        cutoff = int((datetime.now(UTC) - timedelta(hours=48)).timestamp())

        # Events
        time_min = today.strftime('%Y-%m-%dT%H:%M:%SZ')
        time_max = tomorrow.strftime('%Y-%m-%dT%H:%M:%SZ')
        events = self.data_fetcher.get_calendar_events(time_min, time_max)
        events_str = "\n".join([f"- {e['summary']} at {e['start'].get('dateTime', e['start'].get('date'))}"
                              for e in events]) if events else "- No meetings—slacker!"

        # Tasks
        with sqlite3.connect(self.data_fetcher.DB_FILE) as conn:
            cursor = conn.execute("SELECT task, due_date FROM tasks WHERE date(due_date) <= date('now')")
            tasks = cursor.fetchall()
        tasks_str = "\n".join([f"- {t[0]} (due {t[1]})" for t in tasks]) if tasks else "- No tasks—living the dream!"

        # Emails
        emails = self.data_fetcher.get_new_emails(last_run)
        email_summaries = []
        with sqlite3.connect(self.data_fetcher.DB_FILE) as conn:
            for msg in emails[:5]:
                details = self.data_fetcher.get_email_details(msg['id'])
                sender = next(h['value'] for h in details['payload']['headers'] if h['name'] == 'From')
                subject = next(h['value'] for h in details['payload']['headers'] if h['name'] == 'Subject')
                timestamp = int(details['internalDate']) // 1000
                snippet = details.get('snippet', '')
                email_summaries.append(f"- {sender} - {subject} - {snippet}")
                conn.execute("INSERT OR IGNORE INTO emails (id, sender, subject, timestamp, content, source)"
                            "VALUES (?, ?, ?, ?, ?, ?)", (msg['id'], sender, subject, timestamp, snippet, 'gmail'))
                if any(kw in subject.lower() or kw in snippet.lower() for kw in ['urgent', 'asap', 'meeting']):
                    due_date = today.strftime('%Y-%m-%d')
                    conn.execute("INSERT INTO tasks (session_id, task, due_date) VALUES (?, ?, ?)",
                                (self.chat_window.session_id, f"Reply to {sender} re: {subject}", due_date))
                    self.task_added_signal.emit(f"Reply to {sender} re: {subject}", due_date)
        emails_str = "\n".join(email_summaries) if email_summaries else "- No new emails—quiet day!"

        # Unreplied
        with sqlite3.connect(self.data_fetcher.DB_FILE) as conn:
            cursor = conn.execute("SELECT sender, subject, timestamp FROM emails WHERE timestamp < ? AND replied = 0", (cutoff,))
            unreplied = cursor.fetchall()
        unreplied_str = "\n".join([f"- {u[0]} - \"{u[1]}\" (sent {datetime.fromtimestamp(u[2]).strftime('%Y-%m-%d %H:%M')})"
                                for u in unreplied]) if unreplied else "- No ignored emails—caught up, huh?"

        # Scheduling
        scheduling_str = "- No scheduling nudges today—lazy day!"

        briefing = f"Daily Briefing for {today.strftime('%Y-%m-%d')}:\n" \
                  f"[SECTION:Meetings]\n{events_str}\n\n" \
                  f"[SECTION:Tasks]\n{tasks_str}\n\n" \
                  f"[SECTION:New Emails]\n{emails_str}\n\n" \
                  f"[SECTION:Unreplied Emails]\n{unreplied_str}\n\n" \
                  f"[SECTION:Scheduling Suggestions]\n{scheduling_str}"
        self.db.update_last_run()
        return briefing  # Caller formats and appends

    def save_message(self, session_id, role, content):
        self.db.save_message(session_id, role, content)

    def get_chat_history(self, session_id):
        return self.db.get_chat_history(session_id)

    def _add_task_from_chat(self, task_text, due_date, session_id):
        print(f"Adding to DB: {task_text} due {due_date}")
        self.db.add_task(session_id, task_text, due_date)
        print(f"Emitting signal: {task_text} due {due_date}")
        self.task_added_signal.emit(task_text, due_date)
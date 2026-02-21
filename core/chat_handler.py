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
            # Replace \n with <br> for HTML
            formatted_briefing = briefing.replace('\n', '<br>')
            self.chat_window.chatDisplay.append(f"<b>Navi:</b> {formatted_briefing}<br><br>")
        else:
            print("Skipping daily briefing—already ran today")

    def daily_briefing(self):
        last_run = self.db.get_last_run()
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        cutoff = int((datetime.now(UTC) - timedelta(hours=48)).timestamp())

        # Check for sent emails to update replied status before briefing
        self.update_replied_status_from_sent_emails(last_run)

        # Events
        time_min = today.strftime('%Y-%m-%dT%H:%M:%SZ')
        time_max = tomorrow.strftime('%Y-%m-%dT%H:%M:%SZ')
        events = self.data_fetcher.get_calendar_events(time_min, time_max)
        events_str = "\n".join([
            f"- {e['summary']} at {e['start'].get('dateTime', e['start'].get('date'))} ({e.get('calendarName', 'Primary Calendar')})"
            for e in events
        ]) if events else "- No meetings—slacker!"

        # Tasks
        with sqlite3.connect(self.db.db_name) as conn:
            cursor = conn.execute(
                "SELECT task, due_date FROM tasks WHERE completed = 0 AND due_date <= date('now')"
            )
            tasks = cursor.fetchall()
            print(f"[DEBUG] Raw tasks from query: {tasks}")
        tasks_str = "\n".join([f"- {t[0]} (due {t[1]})" for t in tasks]) if tasks else "- No tasks—living the dream!"
        print(f"[DEBUG] tasks_str: '{tasks_str}'")

        # Emails
        print("Fetching new emails...")
        emails = self.data_fetcher.get_new_emails(last_run)
        print(f"Found {len(emails)} new emails")
        email_summaries = []
        with sqlite3.connect(self.db.db_name) as conn:
            for msg in emails[:5]:  # Limit to 5 most recent emails
                details = self.data_fetcher.get_email_details(msg['id'], msg['source'])
                if not details:
                    continue
                    
                sender = next(h['value'] for h in details['payload']['headers'] if h['name'] == 'From')
                subject = next(h['value'] for h in details['payload']['headers'] if h['name'] == 'Subject')
                timestamp = int(details['internalDate']) // 1000
                snippet = details.get('snippet', '')
                
                # Filter out marketing and non-essential emails
                if any(kw in subject.lower() or kw in str(snippet).lower() for kw in [
                    'unsubscribe', 'newsletter', 'promotion', 'sale', 'discount',
                    'marketing', 'advertisement', 'spam', 'junk', 'notification',
                    'alert', 'update', 'digest', 'summary', 'report'
                ]):
                    continue
                    
                # Check if email is from a client or potential client
                is_client = any(domain in sender.lower() for domain in [
                    'goldbugstrategies.com', 'dovahealth.ca', 'navisure.co'
                ])
                is_potential = any(kw in subject.lower() or kw in str(snippet).lower() for kw in [
                    'consulting', 'project', 'proposal', 'quote', 'estimate',
                    'opportunity', 'partnership', 'collaboration'
                ])
                
                email_summaries.append(f"- {sender} - {subject} - {snippet}")
                conn.execute("INSERT OR IGNORE INTO emails (id, sender, subject, timestamp, content, source, is_client, is_potential)"
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (msg['id'], sender, subject, timestamp, snippet, msg['source'], is_client, is_potential))
                
                # Only suggest tasks for client or potential client emails
                if is_client or is_potential:
                    if any(kw in subject.lower() or kw in str(snippet).lower() for kw in ['urgent', 'asap', 'meeting', 'follow up', 'action required']):
                        # Emit signal to show confirmation dialog
                        self.task_added_signal.emit(
                            f"Reply to {sender} re: {subject}",
                            today.strftime('%Y-%m-%d')
                            # "Would you like to add this as a task?"  # Commented out for now
                        )
                        
        emails_str = "\n".join(email_summaries) if email_summaries else "- No new emails—quiet day!"

        # Unreplied
        with sqlite3.connect(self.db.db_name) as conn:
            cursor = conn.execute("""
                SELECT sender, subject, timestamp 
                FROM emails 
                WHERE timestamp < ? 
                AND replied = 0 
                AND (is_client = 1 OR is_potential = 1)
            """, (cutoff,))
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

    def update_replied_status(self, sent_email_id, source):
        """
        Update the replied status of an email in the database based on a sent email.
        This method should be called when a reply is sent to mark the original email as replied.
        Uses 'In-Reply-To' header for more accurate matching if available.
        """
        try:
            with sqlite3.connect(self.data_fetcher.DB_FILE) as conn:
                # Fetch details of the sent email to get subject or thread information
                try:
                    sent_details = self.data_fetcher.get_email_details(sent_email_id, source)
                except Exception as e:
                    print(f"Error fetching details for sent email {sent_email_id} from {source}: {e}")
                    return

                # Try to find 'In-Reply-To' header for direct reply matching
                in_reply_to = next((h['value'] for h in sent_details['payload']['headers'] if h['name'] == 'In-Reply-To'), None)
                if in_reply_to:
                    # Look for the original email by its Message-ID in the database
                    cursor = conn.execute("SELECT id FROM emails WHERE id = ? AND replied = 0", (in_reply_to,))
                    matching_email = cursor.fetchone()
                    if matching_email:
                        email_id = matching_email[0]
                        conn.execute("UPDATE emails SET replied = 1 WHERE id = ?", (email_id,))
                        conn.commit()
                        print(f"Updated replied status for email ID {email_id} based on In-Reply-To header of sent email {sent_email_id}")
                        return

                # Fallback to subject matching if In-Reply-To is not available or no match found
                sent_subject = next((h['value'] for h in sent_details['payload']['headers'] if h['name'] == 'Subject'), '')
                original_subject = sent_subject.replace('Re: ', '').strip()
                cursor = conn.execute("SELECT id FROM emails WHERE subject LIKE ? AND replied = 0", ('%' + original_subject + '%',))
                matching_emails = cursor.fetchall()
                if matching_emails:
                    email_id = matching_emails[0][0]
                    conn.execute("UPDATE emails SET replied = 1 WHERE id = ?", (email_id,))
                    conn.commit()
                    print(f"Updated replied status for email ID {email_id} based on subject match with sent email {sent_email_id}")
                else:
                    print(f"No matching email found for sent email {sent_email_id} from {source}")
        except Exception as e:
            print(f"Error updating replied status for sent email {sent_email_id}: {e}")

    def update_replied_status_from_sent_emails(self, last_run):
        """
        Check for sent emails since last_run and update the replied status of corresponding received emails.
        """
        sent_emails = self.data_fetcher.get_sent_emails(last_run)
        for email in sent_emails:
            self.update_replied_status(email['id'], email['source'])
        print(f"Checked {len(sent_emails)} sent emails for replied status updates.")

    def search_conversations(self, search_terms, date_range=None):
        """
        Search conversations using the database manager.
        
        Args:
            search_terms (str): The search query
            date_range (tuple, optional): (start_date, end_date) for filtering results
            
        Returns:
            list: List of tuples (role, content, timestamp) matching the search
        """
        return self.db.search_conversations(search_terms, date_range)

    def get_chat_history_by_date_range(self, session_id, date_query: str):
        """
        Return messages for a session over a natural-language day query.

        Supported:
        - YYYY-MM-DD (or any dateutil-parseable date)
        - today / yesterday
        - last <weekday> (e.g., 'last thursday')
        """
        q = (date_query or "").strip().lower()
        now = datetime.now(UTC)

        if q in {"today"}:
            day = now.date()
        elif q in {"yesterday"}:
            day = (now - timedelta(days=1)).date()
        elif q.startswith("last "):
            weekday_name = q.replace("last ", "", 1).strip()
            weekdays = {
                "monday": 0,
                "tuesday": 1,
                "wednesday": 2,
                "thursday": 3,
                "friday": 4,
                "saturday": 5,
                "sunday": 6,
            }
            if weekday_name not in weekdays:
                raise ValueError(f"Unsupported weekday in history query: {weekday_name}")
            target = weekdays[weekday_name]
            # How many days ago was the most recent target weekday (excluding today if same weekday)?
            delta = (now.weekday() - target) % 7
            delta = 7 if delta == 0 else delta
            day = (now - timedelta(days=delta)).date()
        else:
            # Fall back to dateutil parsing (date-only queries recommended)
            dt = parser.parse(q, default=now)
            day = dt.date()

        start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        end = start + timedelta(days=1)
        return self.db.get_messages_by_date_range(session_id, start.isoformat(), end.isoformat())
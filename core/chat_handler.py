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
        if last_run_date < today:
            briefing = self.daily_briefing()
            # Replace \n with <br> for HTML
            formatted_briefing = briefing.replace('\n', '<br>')
            self.chat_window.chatDisplay.append(f'<div style="text-align: left;"><b>Navi:</b> {formatted_briefing}</div>')

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
        ]) if events else ""

        # Tasks
        with sqlite3.connect(self.data_fetcher.DB_FILE) as conn:
            cursor = conn.execute("SELECT task, due_date FROM tasks WHERE due_date <= strftime('%m-%d-%Y', 'now')")
            tasks = cursor.fetchall()
        tasks_str = "\n".join([f"- {t[0]} (due {t[1]})" for t in tasks]) if tasks else ""

        # Emails - collect all emails for LLM analysis
        emails = self.data_fetcher.get_new_emails(last_run)
        all_email_data = []
        with sqlite3.connect(self.data_fetcher.DB_FILE) as conn:
            for msg in emails[:10]:  # Increased limit to give LLM more data to work with
                details = self.data_fetcher.get_email_details(msg['id'], msg['source'])
                if not details:
                    continue
                    
                sender = next(h['value'] for h in details['payload']['headers'] if h['name'] == 'From')
                subject = next(h['value'] for h in details['payload']['headers'] if h['name'] == 'Subject')
                timestamp = int(details['internalDate']) // 1000
                snippet = details.get('snippet', '')
                
                # Store all email data for LLM analysis
                email_data = {
                    'sender': sender,
                    'subject': subject,
                    'snippet': snippet,
                    'timestamp': timestamp,
                    'source': msg['source']
                }
                all_email_data.append(email_data)
                
                # Still store in database for tracking
                conn.execute("INSERT OR IGNORE INTO emails (id, sender, subject, timestamp, content, source, is_client, is_potential)"
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (msg['id'], sender, subject, timestamp, snippet, msg['source'], 0, 0))
        
        # Let LLM analyze and filter emails intelligently
        if all_email_data:
            email_analysis_prompt = f"""Analyze these emails and determine which ones are relevant for Dr. Odeh's daily briefing. 

Context: Dr. Odeh is a MedTech consultant focused on AI/ML, IVDs, SaMD, DTC devices. He works with startups and needs to stay on top of:
- Client communications (goldbugstrategies.com, dovahealth.ca)
- Business opportunities and partnerships
- Industry news and regulatory updates
- Urgent matters requiring immediate attention

Email data:
{chr(10).join([f"From: {email['sender']} | Subject: {email['subject']} | Content: {email['snippet']}" for email in all_email_data])}

Instructions:
1. Filter out obvious spam, marketing, newsletters, and irrelevant emails
2. Identify emails that are important for a MedTech consultant
3. Flag urgent emails that need immediate attention
4. Group related emails if any
5. Return ONLY the relevant emails in this format:
RELEVANT_EMAILS:
- [Sender] - [Subject] - [Brief summary of why it's relevant]
- [Next relevant email...]

URGENT_EMAILS:
- [Urgent email details if any]

Return only the relevant emails, nothing else."""

            # Get LLM analysis
            try:
                from core.response_handler import ResponseHandler
                response_handler = ResponseHandler(None, None, None, self, "briefing_analysis", [])
                email_analysis = response_handler.chat_with_llama([{"role": "user", "content": email_analysis_prompt}], "email_analysis")
                
                # Extract relevant emails from LLM response
                if "RELEVANT_EMAILS:" in email_analysis:
                    relevant_section = email_analysis.split("RELEVANT_EMAILS:")[1]
                    if "URGENT_EMAILS:" in relevant_section:
                        relevant_section = relevant_section.split("URGENT_EMAILS:")[0]
                    emails_str = relevant_section.strip()
                else:
                    emails_str = ""
            except Exception as e:
                print(f"Error in LLM email analysis: {e}")
                emails_str = ""
        else:
            emails_str = ""

        # Unreplied
        with sqlite3.connect(self.data_fetcher.DB_FILE) as conn:
            cursor = conn.execute("""
                SELECT sender, subject, timestamp 
                FROM emails 
                WHERE timestamp < ? 
                AND replied = 0 
                AND (is_client = 1 OR is_potential = 1)
            """, (cutoff,))
            unreplied = cursor.fetchall()
        unreplied_str = "\n".join([f"- {u[0]} - \"{u[1]}\" (sent {datetime.fromtimestamp(u[2]).strftime('%Y-%m-%d %H:%M')})"
                                for u in unreplied]) if unreplied else ""

        # Scheduling
        scheduling_str = ""

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
        self.db.add_task(session_id, task_text, due_date)
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
        except Exception as e:
            pass

    def update_replied_status_from_sent_emails(self, last_run):
        """
        Check for sent emails since last_run and update the replied status of corresponding received emails.
        """
        sent_emails = self.data_fetcher.get_sent_emails(last_run)
        for email in sent_emails:
            self.update_replied_status(email['id'], email['source'])

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
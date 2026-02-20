from PyQt6.QtCore import QObject, pyqtSignal
import sqlite3
from datetime import datetime, timedelta, UTC
from dateutil import parser
from core.db import DatabaseManager
from core.data_fetch import DataFetcher

class ChatHandler(QObject):
    # Email analysis prompt template (static content)
    EMAIL_ANALYSIS_PROMPT_TEMPLATE = """Analyze these emails and determine which ones are relevant for Dr. Odeh's daily briefing. 

Context: Dr. Odeh is a MedTech consultant focused on AI/ML, IVDs, SaMD, DTC devices. He works with startups and needs to stay on top of:
- Client communications (goldbugstrategies.com, dovahealth.ca)
- Business opportunities and partnerships
- Industry news and regulatory updates
- Urgent matters requiring immediate attention

Email data:
{email_data}

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

    def __init__(self, chat_window=None, db=None):
        super().__init__()
        self.chat_window = chat_window
        self.db = db if db is not None else DatabaseManager()
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
            if self.chat_window is not None and hasattr(self.chat_window, 'chatDisplay'):
                self.chat_window.chatDisplay.append(f'<div style="text-align: left;"><b>Navi:</b> {formatted_briefing}</div>')

    def daily_briefing(self):
        """Generate comprehensive daily briefing with improved data collection and formatting."""
        from config import BRIEFING_AND_EMAIL_DISABLED
        if BRIEFING_AND_EMAIL_DISABLED:
            self.db.update_last_run()  # Update timestamp even when disabled to avoid repeated calls
            return "Daily briefing and email checking are currently disabled."
        last_run = self.db.get_last_run()
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        cutoff = int((datetime.now(UTC) - timedelta(hours=48)).timestamp())
        
        # Limit email fetching to last 7 days maximum (avoid fetching year-old emails)
        max_lookback_days = 7
        max_lookback_timestamp = int((datetime.now(UTC) - timedelta(days=max_lookback_days)).timestamp())
        
        # If last_run is 0 (first run) or older than 7 days, use 7 days ago instead
        if last_run == 0 or last_run < max_lookback_timestamp:
            last_run = max_lookback_timestamp
            lookback_date = datetime.fromtimestamp(last_run, tz=UTC).strftime('%Y-%m-%d')
            print(f"Limiting email fetch to last {max_lookback_days} days (since {lookback_date})")
        
        # Pass the limited last_run to get_new_emails
        # This ensures we only fetch emails from the last 7 days

        # Check for sent emails to update replied status before briefing
        try:
            self.update_replied_status_from_sent_emails(last_run)
        except Exception as e:
            print(f"Warning: Could not update replied email status: {e}")
            # Continue with briefing even if this fails

        # ========== EVENTS ==========
        try:
            time_min = today.strftime('%Y-%m-%dT%H:%M:%SZ')
            time_max = tomorrow.strftime('%Y-%m-%dT%H:%M:%SZ')
            events = self.data_fetcher.get_calendar_events(time_min, time_max)
            
            if events:
                # Format events with better time display
                events_list = []
                for e in events:
                    start = e['start'].get('dateTime', e['start'].get('date'))
                    try:
                        if 'T' in start:
                            parsed = parser.parse(start)
                            time_str = parsed.strftime('%I:%M %p')
                        else:
                            time_str = "All Day"
                        summary = e.get('summary', 'Untitled Event')
                        calendar = e.get('calendarName', 'Primary Calendar')
                        events_list.append(f"- {time_str}: {summary} ({calendar})")
                    except:
                        events_list.append(f"- {e.get('summary', 'Untitled Event')}")
                events_str = "\n".join(events_list)
            else:
                events_str = "No meetings scheduled for today."
        except Exception as e:
            print(f"Error loading events for briefing: {e}")
            events_str = "Unable to load calendar events."

        # ========== TASKS ==========
        try:
            # FIX: Use correct date format and get more relevant tasks
            today_str = today.strftime('%m-%d-%Y')  # Match database format
            
            with sqlite3.connect(self.db.db_name) as conn:  # Use self.db.db_name instead of data_fetcher.DB_FILE
                # Get overdue tasks
                cursor = conn.execute("""
                    SELECT task_text, due_date, category, completed 
                    FROM tasks 
                    WHERE due_date < ? AND completed = 0
                    ORDER BY due_date ASC
                """, (today_str,))
                overdue = cursor.fetchall()
                
                # Get tasks due today
                cursor = conn.execute("""
                    SELECT task_text, due_date, category, completed 
                    FROM tasks 
                    WHERE due_date = ? AND completed = 0
                    ORDER BY category, task_text
                """, (today_str,))
                due_today = cursor.fetchall()
                
                # Get upcoming tasks (next 3 days)
                upcoming_dates = [
                    (today + timedelta(days=i)).strftime('%m-%d-%Y') 
                    for i in range(1, 4)
                ]
                placeholders = ','.join(['?' for _ in upcoming_dates])
                cursor = conn.execute(f"""
                    SELECT task_text, due_date, category, completed 
                    FROM tasks 
                    WHERE due_date IN ({placeholders}) AND completed = 0
                    ORDER BY due_date ASC, category
                """, upcoming_dates)
                upcoming = cursor.fetchall()
                
                # Get tasks without due dates (high priority)
                cursor = conn.execute("""
                    SELECT task_text, due_date, category, completed 
                    FROM tasks 
                    WHERE due_date IS NULL AND completed = 0
                    ORDER BY category, task_text
                    LIMIT 5
                """)
                no_date = cursor.fetchall()
            
            # Format tasks with better organization
            tasks_parts = []
            
            if overdue:
                tasks_parts.append("OVERDUE:")
                for t in overdue:
                    tasks_parts.append(f"  ⚠️ {t[0]} (was due {t[1]}) [{t[2]}]")
            
            if due_today:
                tasks_parts.append("\nDUE TODAY:")
                for t in due_today:
                    tasks_parts.append(f"  • {t[0]} [{t[2]}]")
            
            if upcoming:
                tasks_parts.append("\nUPCOMING (next 3 days):")
                for t in upcoming:
                    tasks_parts.append(f"  • {t[0]} (due {t[1]}) [{t[2]}]")
            
            if no_date:
                tasks_parts.append("\nNO DUE DATE (consider scheduling):")
                for t in no_date:
                    tasks_parts.append(f"  • {t[0]} [{t[2]}]")
            
            tasks_str = "\n".join(tasks_parts) if tasks_parts else "No active tasks found. Great job staying on top of things!"
            
        except sqlite3.Error as e:
            print(f"Database error loading tasks for briefing: {e}")
            tasks_str = "Unable to load tasks from database."
        except Exception as e:
            print(f"Error loading tasks for briefing: {e}")
            import traceback
            traceback.print_exc()
            tasks_str = "Error loading tasks."

        # ========== EMAILS ==========
        emails_str = ""
        urgent_emails_str = ""
        
        try:
            # Use the limited last_run (max 7 days) to fetch only recent emails
            emails = self.data_fetcher.get_new_emails(last_run, max_emails=30)  # Reduced from 50 to 30 for faster processing
            all_email_data = []
            
            if emails:
                print(f"Found {len(emails)} new emails (limited to last 7 days)")
            
            if emails:
                # Group emails by source for batch processing
                emails_by_source = {}
                for msg in emails:
                    source = msg['source']
                    if source not in emails_by_source:
                        emails_by_source[source] = []
                    emails_by_source[source].append(msg)
                
                # Process emails in batches by source
                all_email_details = {}
                for source, source_emails in emails_by_source.items():
                    try:
                        email_ids = [msg['id'] for msg in source_emails]
                        batch_details = self.data_fetcher.get_email_details_batch(email_ids, source)
                        all_email_details.update(batch_details)
                    except ImportError as e:
                        print(f"Warning: Email batch processing unavailable for {source} (missing dependencies): {e}")
                        # Continue with other email sources or skip this batch
                        continue
                    except Exception as e:
                        print(f"Warning: Error processing email batch from {source}: {e}")
                        # Continue with other sources
                        continue
                
                with sqlite3.connect(self.db.db_name) as conn:
                    for msg in emails:
                        details = all_email_details.get(msg['id'])
                        if not details:
                            continue
                        
                        try:
                            sender = next(h['value'] for h in details['payload']['headers'] if h['name'] == 'From')
                            subject = next(h['value'] for h in details['payload']['headers'] if h['name'] == 'Subject')
                            timestamp = int(details['internalDate']) // 1000
                            snippet = details.get('snippet', '')
                            
                            email_data = {
                                'sender': sender,
                                'subject': subject,
                                'snippet': snippet,
                                'timestamp': timestamp,
                                'source': msg['source']
                            }
                            all_email_data.append(email_data)
                            
                            # Store in database
                            conn.execute("INSERT OR IGNORE INTO emails (id, sender, subject, timestamp, content, source, is_client, is_potential)"
                                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                        (msg['id'], sender, subject, timestamp, snippet, msg['source'], 0, 0))
                        except (KeyError, StopIteration) as e:
                            print(f"Skipping email due to missing data: {e}")
                            continue
                    conn.commit()
                
                # LLM analysis of emails
                if all_email_data:
                    email_data_str = "\n".join([
                        f"From: {email['sender']} | Subject: {email['subject']} | Content: {email['snippet'][:200]}"
                        for email in all_email_data
                    ])
                    
                    email_analysis_prompt = self.EMAIL_ANALYSIS_PROMPT_TEMPLATE.format(email_data=email_data_str)
                    
                    try:
                        # Use Grok directly to avoid spawning llama_worker subprocess for a single call
                        from core.grok_client import grok_available, grok_completion
                        ok, _ = grok_available()
                        if ok:
                            email_analysis = grok_completion(
                                system="You analyze emails for a MedTech consultant's daily briefing. Return RELEVANT_EMAILS: and URGENT_EMAILS: sections.",
                                user=email_analysis_prompt,
                                model="grok-4-1-fast"
                            )
                        else:
                            email_analysis = None

                        if not email_analysis:
                            raise ValueError("Grok unavailable for email analysis")

                        # Extract relevant and urgent emails
                        if "RELEVANT_EMAILS:" in email_analysis:
                            relevant_section = email_analysis.split("RELEVANT_EMAILS:")[1]
                            if "URGENT_EMAILS:" in relevant_section:
                                emails_str = relevant_section.split("URGENT_EMAILS:")[0].strip()
                                urgent_section = email_analysis.split("URGENT_EMAILS:")[1].strip()
                                urgent_emails_str = urgent_section if urgent_section else ""
                            else:
                                emails_str = relevant_section.strip()
                        else:
                            emails_str = "No relevant emails identified."
                    except Exception as e:
                        print(f"Error in LLM email analysis: {e}")
                        import traceback
                        traceback.print_exc()
                        # Fallback: show count of new emails
                        emails_str = f"Received {len(all_email_data)} new emails (AI analysis unavailable)."
            else:
                emails_str = "No new emails since last briefing."
                
        except ImportError as e:
            print(f"Warning: Email processing unavailable (missing dependencies): {e}")
            emails_str = "Email processing unavailable due to missing dependencies. Please check your email API configuration."
        except Exception as e:
            print(f"Error processing emails for briefing: {e}")
            import traceback
            traceback.print_exc()
            emails_str = f"Unable to process emails: {str(e)}"

        # ========== UNREPLIED EMAILS ==========
        try:
            # Only show unreplied emails from the last 30 days (to avoid showing year-old emails)
            # But exclude emails from the last 48 hours (those are in "new emails")
            max_unreplied_age = int((datetime.now(UTC) - timedelta(days=30)).timestamp())
            min_unreplied_age = cutoff  # 48 hours ago - older than this but newer than 30 days
            
            with sqlite3.connect(self.db.db_name) as conn:
                cursor = conn.execute("""
                    SELECT sender, subject, timestamp 
                    FROM emails 
                    WHERE timestamp < ? 
                    AND timestamp > ?
                    AND replied = 0 
                    AND (is_client = 1 OR is_potential = 1)
                    ORDER BY timestamp DESC
                    LIMIT 10
                """, (min_unreplied_age, max_unreplied_age))
                unreplied = cursor.fetchall()
            
            if unreplied:
                unreplied_list = []
                for u in unreplied:
                    date_str = datetime.fromtimestamp(u[2]).strftime('%Y-%m-%d %H:%M')
                    # Extract sender name (email addresses are often in "Name <email>" format)
                    sender_name = u[0].split('<')[0].strip().strip('"').strip("'")
                    if not sender_name or '@' in sender_name:
                        sender_name = u[0].split('<')[1].strip('>').split('@')[0] if '<' in u[0] else u[0].split('@')[0]
                    unreplied_list.append(f"- {sender_name} - \"{u[1]}\" (sent {date_str})")
                unreplied_str = "\n".join(unreplied_list)
            else:
                unreplied_str = "No unreplied client emails from the last 30 days. Excellent!"
        except Exception as e:
            print(f"Error loading unreplied emails: {e}")
            import traceback
            traceback.print_exc()
            unreplied_str = "Unable to load unreplied emails."

        # ========== SCHEDULING SUGGESTIONS ==========
        try:
            # Generate intelligent scheduling suggestions based on tasks and events
            suggestions = []
            
            # Check if there are overdue tasks that need attention
            if overdue:
                suggestions.append(f"⚠️ You have {len(overdue)} overdue task(s) that need immediate attention.")
            
            # Check if there are many tasks due today
            if due_today and len(due_today) > 3:
                suggestions.append(f"📋 You have {len(due_today)} tasks due today - consider prioritizing or rescheduling some.")
            
            # Check if there are tasks without due dates
            if no_date:
                suggestions.append(f"📅 Consider scheduling {len(no_date)} task(s) without due dates to improve planning.")
            
            # Check if there are urgent emails
            if urgent_emails_str:
                suggestions.append("🚨 You have urgent emails that may need immediate response.")
            
            # Check if there are many meetings today
            if events and len(events) > 5:
                suggestions.append(f"📅 You have {len(events)} meetings today - ensure you have time for focused work.")
            
            scheduling_str = "\n".join(suggestions) if suggestions else "Your schedule looks balanced today!"
            
        except Exception as e:
            print(f"Error generating scheduling suggestions: {e}")
            scheduling_str = ""

        # ========== BUILD BRIEFING ==========
        briefing = f"Daily Briefing for {today.strftime('%B %d, %Y')}:\n\n" \
                  f"[SECTION:Meetings]\n{events_str}\n\n" \
                  f"[SECTION:Tasks]\n{tasks_str}\n\n" \
                  f"[SECTION:New Emails]\n{emails_str}\n"
        
        if urgent_emails_str:
            briefing += f"[SECTION:Urgent Emails]\n{urgent_emails_str}\n\n"
        
        briefing += f"[SECTION:Unreplied Emails]\n{unreplied_str}\n\n" \
                  f"[SECTION:Scheduling Suggestions]\n{scheduling_str}"
        
        self.db.update_last_run()
        return briefing

    def save_message(self, session_id, role, content):
        self.db.save_message(session_id, role, content)

    def get_chat_history(self, session_id):
        return self.db.get_chat_history(session_id)

    def _add_task_from_chat(self, task_text, due_date, session_id):
        self.db.add_task(session_id, task_text, due_date)
        if hasattr(self, 'task_added_callback') and self.task_added_callback:
            self.task_added_callback(task_text, due_date)

    def update_replied_status(self, sent_email_id, source):
        """
        Update the replied status of an email in the database based on a sent email.
        This method should be called when a reply is sent to mark the original email as replied.
        Uses 'In-Reply-To' header for more accurate matching if available.
        """
        try:
            with sqlite3.connect(self.db.db_name) as conn:
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
        Uses batch processing for efficiency.
        """
        sent_emails = self.data_fetcher.get_sent_emails(last_run)
        
        if sent_emails:
            # Group sent emails by source for batch processing
            emails_by_source = {}
            for email in sent_emails:
                source = email['source']
                if source not in emails_by_source:
                    emails_by_source[source] = []
                emails_by_source[source].append(email)
            
            # Process sent emails in batches by source
            all_sent_details = {}
            for source, source_emails in emails_by_source.items():
                email_ids = [email['id'] for email in source_emails]
                batch_details = self.data_fetcher.get_email_details_batch(email_ids, source)
                all_sent_details.update(batch_details)
            
            # Update replied status using batch-fetched details
            for email in sent_emails:
                sent_details = all_sent_details.get(email['id'])
                if sent_details:
                    self.update_replied_status_with_details(email['id'], email['source'], sent_details)

    def update_replied_status_with_details(self, sent_email_id, source, sent_details):
        """
        Update the replied status of an email in the database based on a sent email.
        Uses pre-fetched email details to avoid additional API calls.
        """
        try:
            with sqlite3.connect(self.db.db_name) as conn:
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
from dropbox import Dropbox
from core.api import get_dropbox_client
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import pickle
import os
from google.auth.transport.requests import Request
import imaplib
import email
from datetime import datetime, timedelta, timezone
from exchangelib import Account, Configuration, OAuth2Credentials, DELEGATE
from oauthlib.oauth2.rfc6749.tokens import OAuth2Token
from pathlib import Path
from dotenv import load_dotenv
import json

class DataFetcher:
    def __init__(self):
        self.dropbox = get_dropbox_client()
        self.SCOPES = [
            'https://www.googleapis.com/auth/gmail.readonly',
            'https://www.googleapis.com/auth/calendar.readonly'
        ]
        self.CRED_FILE = r"C:\Users\adamo\Dropbox\_Consulting\NaviSsurance\config\client_secret.json"
        self.TOKEN_FILE = r"C:\Users\adamo\Dropbox\_Consulting\NaviSsurance\config\navi_token.pkl"
        # Import config for database path
        import sys
        import os
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from config import DATABASE_PATH
        self.DB_FILE = DATABASE_PATH
        self.gmail, self.calendar = self.get_services()
        # Yahoo account with IMAP credentials
        self.yahoo_account = {
            'user': 'adamodeh81@yahoo.com',
            'pwd': os.getenv('YAHOO_APP_PASSWORD', '')
        }
        # Outlook/Office365 accounts
        env_path = Path('config') / '.env'
        load_dotenv(env_path)
        self.outlook_accounts = [
            os.getenv('MSN_EMAIL_1'),
            os.getenv('MSN_EMAIL_2')
        ]
        self.mailbird_token_path = Path('config/mailbird_tokens.json')
        # Conversation tracking
        self.conversation_map = {}
        self.conversation_threads = {}

    def get_services(self):
        creds = None
        if os.path.exists(self.TOKEN_FILE):
            with open(self.TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(self.TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
        elif not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(self.CRED_FILE, self.SCOPES)
            creds = flow.run_local_server(port=0)
            with open(self.TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
        gmail = build('gmail', 'v1', credentials=creds)
        calendar = build('calendar', 'v3', credentials=creds)
        return gmail, calendar

    def get_available_calendars(self):
        """
        Get a list of all available calendars, including shared calendars.
        Returns a list of calendar objects with id, summary, and description.
        """
        try:
            calendar_list = self.calendar.calendarList().list().execute()
            return calendar_list.get('items', [])
        except Exception as e:
            print(f"Error fetching calendar list: {e}")
            return []

    def get_calendar_events(self, time_min, time_max):
        """
        Get events from primary calendar and all shared calendars.
        Returns a list of events with their calendar source.
        """
        all_events = []
        
        # Get all available calendars
        calendars = self.get_available_calendars()
        
        for cal in calendars:
            try:
                # Skip calendars that are hidden or not selected
                if cal.get('selected', False) and not cal.get('hidden', False):
                    events = self.calendar.events().list(
                        calendarId=cal['id'],
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True
                    ).execute().get('items', [])
                    
                    # Add calendar info to each event
                    for event in events:
                        event['calendarName'] = cal.get('summary', 'Unknown Calendar')
                        event['calendarColor'] = cal.get('backgroundColor', '#000000')
                    
                    all_events.extend(events)
            except Exception as e:
                print(f"Error fetching events from calendar {cal.get('summary', 'Unknown')}: {e}")
                continue
        
        # Sort events by start time
        all_events.sort(key=lambda x: x['start'].get('dateTime', x['start'].get('date')))
        return all_events

    def get_mailbird_token(self, email):
        """Get OAuth token from Mailbird's stored configuration for a specific email address"""
        try:
            if not self.mailbird_token_path.exists():
                print("No token file found. Please run read_mailbird_config.py first.")
                return None
            with open(self.mailbird_token_path, 'r') as f:
                tokens = json.load(f)
            for token in tokens:
                if str(token.get('email', '')).strip().lower() != email.strip().lower():
                    continue
                expires_at = datetime.fromisoformat(token['expires_at'].replace('Z', '+00:00'))
                current_time = datetime.now(timezone.utc)
                if expires_at > current_time:
                    return token
            return None
        except Exception as e:
            print(f"Error getting Mailbird token: {e}")
            return None

    def fetch_recent_ews_emails(self, email, hours=24):
        """Fetch recent emails using Mailbird's OAuth token via EWS"""
        token_data = self.get_mailbird_token(email)
        if not token_data:
            print(f"Could not get valid token for {email}")
            return []
        try:
            token_obj = OAuth2Token({
                'access_token': token_data['access_token'],
                'token_type': 'Bearer',
                'expires_in': 3600,
            })
            oauth2_creds = OAuth2Credentials(
                client_id=None,
                client_secret=None,
                tenant_id=None,
                access_token=token_obj,
            )
            config = Configuration(
                credentials=oauth2_creds,
                server='outlook.office365.com',
            )
            account = Account(
                primary_smtp_address=email,
                config=config,
                autodiscover=False,
                access_type=DELEGATE,
            )
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=hours)
            messages = list(account.inbox.filter(datetime_received__gte=start_time).order_by('-datetime_received')[:10])
            results = []
            for msg in messages:
                results.append({
                    'id': msg.message_id,
                    'source': 'outlook',
                    'subject': msg.subject,
                    'from': msg.sender.email_address if msg.sender else 'Unknown',
                    'received': msg.datetime_received.isoformat() if msg.datetime_received else '',
                    'snippet': msg.text_body[:100] if msg.text_body else '',
                    'folder': 'INBOX',
                })
            return results
        except Exception as e:
            print(f"Error in fetch_recent_ews_emails for {email}: {e}")
            return []

    def get_new_emails(self, last_run):
        emails = []
        # Gmail
        folders = ['INBOX', 'News', 'NaviSure Admin']
        for folder in folders:
            query = f"after:{last_run}"
            if folder != 'INBOX':
                query += f' label:"{folder}"'
            try:
                results = self.gmail.users().messages().list(userId='me', q=query).execute()
                emails.extend({'id': msg['id'], 'source': 'gmail', 'folder': folder} for msg in results.get('messages', []))
            except Exception as e:
                continue

        # Yahoo IMAP
        try:
            mail = imaplib.IMAP4_SSL('imap.mail.yahoo.com')
            mail.login(self.yahoo_account['user'], self.yahoo_account['pwd'])
            mail.select('inbox')
            
            # Use last 30 days instead of last_run if last_run is too old
            search_date = datetime.now() - timedelta(days=30)
            if last_run > 0:
                last_run_date = datetime.fromtimestamp(last_run)
                if last_run_date > search_date:
                    search_date = last_run_date
            
            since_date = search_date.strftime('%d-%b-%Y')
            _, data = mail.search(None, f'SINCE {since_date}')
            for num in data[0].split():
                _, msg_data = mail.fetch(num, '(RFC822)')
                emails.append({'id': num.decode(), 'source': 'yahoo', 'raw': msg_data[0][1], 'folder': 'INBOX'})
            mail.logout()
        except Exception as e:
            pass

        # Outlook/Office365 via EWS
        for outlook_email in self.outlook_accounts:
            if not outlook_email:
                continue
            try:
                ews_emails = self.fetch_recent_ews_emails(outlook_email)
                emails.extend(ews_emails)
            except Exception as e:
                pass

        return emails

    def get_sent_emails(self, last_run):
        """
        Fetch sent emails from Gmail since last_run timestamp.
        Returns a list of email objects with id and source.
        """
        sent_emails = []
        # Gmail sent emails
        results = self.gmail.users().messages().list(userId='me', q=f"after:{last_run} in:sent").execute()
        sent_emails.extend({'id': msg['id'], 'source': 'gmail'} for msg in results.get('messages', []))
        return sent_emails

    def extract_conversation_info(self, headers):
        """
        Extract conversation tracking information from email headers.
        Returns a tuple of (message_id, in_reply_to, references, conversation_id)
        """
        message_id = headers.get('Message-ID', '').strip('<>')
        in_reply_to = headers.get('In-Reply-To', '').strip('<>')
        references = [ref.strip('<>') for ref in headers.get('References', '').split() if ref.strip('<>')]
        thread_index = headers.get('Thread-Index', '')
        
        # Generate a conversation ID based on the most reliable available information
        if in_reply_to:
            conversation_id = in_reply_to
        elif references:
            conversation_id = references[0]  # First reference is usually the original message
        else:
            conversation_id = message_id  # Fallback to message ID if no conversation info
        
        return message_id, in_reply_to, references, conversation_id

    def update_conversation_tracking(self, message_id, in_reply_to, references, conversation_id):
        """
        Update conversation tracking maps with new message information.
        """
        # Update conversation map
        self.conversation_map[message_id] = conversation_id
        
        # Update conversation threads
        if conversation_id not in self.conversation_threads:
            self.conversation_threads[conversation_id] = []
        
        # Add message to conversation thread if not already present
        if message_id not in self.conversation_threads[conversation_id]:
            self.conversation_threads[conversation_id].append(message_id)
        
        # Add referenced messages to conversation thread
        for ref_id in references:
            if ref_id not in self.conversation_threads[conversation_id]:
                self.conversation_threads[conversation_id].append(ref_id)

    def get_email_details(self, msg_id, source='gmail'):
        """
        Get email details and update conversation tracking.
        """
        print(f"\nGetting details for email {msg_id} from {source}")
        if source == 'gmail':
            msg = self.gmail.users().messages().get(userId='me', id=msg_id, format='full').execute()
            headers = {h['name']: h['value'] for h in msg['payload']['headers']}
        elif source == 'yahoo':
            try:
                mail = imaplib.IMAP4_SSL('imap.mail.yahoo.com')
                mail.login(self.yahoo_account['user'], self.yahoo_account['pwd'])
                mail.select('inbox')
                _, data = mail.fetch(msg_id, '(RFC822)')
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)
                mail.logout()
                headers = [{'name': h, 'value': v} for h, v in msg.items()]
                
                # Handle email content properly
                if msg.is_multipart():
                    content_parts = []
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            content_parts.append(part.get_payload(decode=True).decode('utf-8', errors='ignore'))
                    content = ' '.join(content_parts)
                else:
                    content = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                
                # Ensure snippet is a string and not too long
                snippet = str(content)[:100] if content else ''
                
                return {
                    'id': msg_id, 
                    'payload': {'headers': headers}, 
                    'snippet': snippet, 
                    'internalDate': int(datetime.now().timestamp() * 1000),
                    'content': content
                }
            except Exception as e:
                print(f"Error fetching Yahoo email details: {e}")
                return None

        # Extract conversation information
        message_id, in_reply_to, references, conversation_id = self.extract_conversation_info(headers)
        
        # Update conversation tracking
        self.update_conversation_tracking(message_id, in_reply_to, references, conversation_id)
        
        # Add conversation information to the message
        msg['conversation_id'] = conversation_id
        msg['in_reply_to'] = in_reply_to
        msg['references'] = references
        msg['thread_messages'] = self.conversation_threads.get(conversation_id, [])
        
        return msg

    def get_conversation_thread(self, conversation_id):
        """
        Get all messages in a conversation thread.
        """
        return self.conversation_threads.get(conversation_id, [])

    def get_message_conversation(self, message_id):
        """
        Get the conversation ID for a message.
        """
        return self.conversation_map.get(message_id)

    def search_dropbox(self, query):
        # Placeholder—replace with your Dropbox search logic if different
        return self.dropbox.files_search_v2(query).matches
from dropbox import Dropbox
from core.api import get_dropbox_client
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import pickle
import os
from google.auth.transport.requests import Request
import imaplib
import email
from datetime import datetime

class DataFetcher:
    def __init__(self):
        self.dropbox = get_dropbox_client()
        self.SCOPES = [
            'https://www.googleapis.com/auth/gmail.readonly',
            'https://www.googleapis.com/auth/calendar.readonly'
        ]
        self.CRED_FILE = r"C:\Users\adamo\Dropbox\_Consulting\NaviSsurance\config\client_secret.json"
        self.TOKEN_FILE = r"C:\Users\adamo\Dropbox\_Consulting\NaviSsurance\config\navi_token.pkl"
        self.DB_FILE = r"F:\naviSsurance_index.db"
        self.gmail, self.calendar = self.get_services()
        # Yahoo account with IMAP credentials
        self.yahoo_account = {
            'user': 'adamodeh81@yahoo.com',
            'pwd': os.getenv('YAHOO_APP_PASSWORD', '')
        }
        # Conversation tracking
        self.conversation_map = {}  # Maps message IDs to conversation IDs
        self.conversation_threads = {}  # Maps conversation IDs to lists of message IDs

    def get_services(self):
        creds = None
        if os.path.exists(self.TOKEN_FILE):
            print(f"Loading token from {self.TOKEN_FILE}")
            with open(self.TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
        if creds and creds.expired and creds.refresh_token:
            print("Token expired, refreshing...")
            creds.refresh(Request())
            with open(self.TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
            print("Token refreshed and saved.")
        elif not creds or not creds.valid:
            print("No valid token, re-authenticating...")
            flow = InstalledAppFlow.from_client_secrets_file(self.CRED_FILE, self.SCOPES)
            creds = flow.run_local_server(port=0)
            with open(self.TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
            print("New token saved.")
        else:
            print("Token still valid.")
        gmail = build('gmail', 'v1', credentials=creds)
        calendar = build('calendar', 'v3', credentials=creds)
        return gmail, calendar

    def get_calendar_events(self, time_min, time_max):
        return self.calendar.events().list(calendarId='primary', timeMin=time_min, timeMax=time_max, singleEvents=True).execute().get('items', [])

    def get_new_emails(self, last_run):
        emails = []
        # Gmail
        results = self.gmail.users().messages().list(userId='me', q=f"after:{last_run}").execute()
        emails.extend({'id': msg['id'], 'source': 'gmail'} for msg in results.get('messages', []))

        # Yahoo IMAP
        try:
            mail = imaplib.IMAP4_SSL('imap.mail.yahoo.com')
            mail.login(self.yahoo_account['user'], self.yahoo_account['pwd'])
            mail.select('inbox')
            since_date = datetime.fromtimestamp(last_run).strftime('%d-%b-%Y')
            _, data = mail.search(None, f'SINCE {since_date}')
            for num in data[0].split():
                _, msg_data = mail.fetch(num, '(RFC822)')
                emails.append({'id': num.decode(), 'source': 'yahoo', 'raw': msg_data[0][1]})
            mail.logout()
            print("Successfully fetched new emails from Yahoo")
        except Exception as e:
            print(f"Failed to fetch Yahoo emails: {e}")

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
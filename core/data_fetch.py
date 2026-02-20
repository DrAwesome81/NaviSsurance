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
import logging
from core.secure_logging import secure_function_logger, safe_log

logger = logging.getLogger(__name__)

class DataFetcher:
    def __init__(self):
        self.dropbox = get_dropbox_client()
        self.SCOPES = [
            'https://www.googleapis.com/auth/gmail.readonly',
            'https://www.googleapis.com/auth/calendar.readonly'
        ]
        from config import CONFIG_DIR
        self.CRED_FILE = os.path.join(CONFIG_DIR, "client_secret.json")
        self.TOKEN_FILE = os.path.join(CONFIG_DIR, "navi_token.pkl")
        # Import config for database path
        from config import DATABASE_PATH
        self.DB_FILE = DATABASE_PATH
        self.gmail, self.calendar = self.get_services()
        # Yahoo account with IMAP credentials
        self.yahoo_account = {
            'user': 'adamodeh81@yahoo.com',
            'pwd': os.getenv('YAHOO_APP_PASSWORD', '')
        }
        # Outlook/Office365 accounts (env loaded from config/.env)
        load_dotenv(os.path.join(CONFIG_DIR, ".env"))
        self.outlook_accounts = [
            os.getenv('MSN_EMAIL_1'),
            os.getenv('MSN_EMAIL_2')
        ]
        from config import CONFIG_DIR
        self.mailbird_token_path = Path(CONFIG_DIR) / 'mailbird_tokens.json'
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
                    
                    # Add calendar info to each event and filter out "free" events
                    for event in events:
                        # Skip events marked as "show as free" (transparency = "transparent")
                        if event.get('transparency') == 'transparent':
                            continue
                            
                        event['calendarName'] = cal.get('summary', 'Unknown Calendar')
                        event['calendarColor'] = cal.get('backgroundColor', '#000000')
                        all_events.append(event)
            except Exception as e:
                print(f"Error fetching events from calendar {cal.get('summary', 'Unknown')}: {e}")
                continue
        
        # Sort events by start time
        all_events.sort(key=lambda x: x['start'].get('dateTime', x['start'].get('date')))
        return all_events

    @secure_function_logger
    def get_mailbird_token(self, email):
        """Get OAuth token directly from Mailbird's Store database for a specific email address"""
        try:
            import sqlite3
            # Mailbird stores its database in LOCALAPPDATA
            store_path = Path(os.environ.get('LOCALAPPDATA', '')) / 'Mailbird' / 'Store' / 'Store.db'
            
            if not store_path.exists():
                safe_log(logger, logging.WARNING, f"Mailbird Store.db not found at {store_path}")
                return None
            
            conn = sqlite3.connect(str(store_path))
            cursor = conn.cursor()
            
            # Get Microsoft OAuth credentials for the specific email, joining with Accounts to get the email
            cursor.execute("""
                SELECT 
                    oauth.Id,
                    oauth.AccessToken,
                    oauth.AccessTokenExpiresAt_UTC,
                    oauth.RefreshToken,
                    oauth.ManagerScope,
                    oauth.ProviderScope,
                    acc.Username as Email
                FROM OAuth2Credentials oauth
                JOIN Accounts acc ON acc.OAuth2CredentialsId = oauth.Id
                WHERE LOWER(acc.Username) = LOWER(?)
            """, (email,))
            
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                safe_log(logger, logging.WARNING, f"No Mailbird token found for email: {email}")
                return None
            
            # Check if it's a Microsoft/Outlook token
            provider_scope = row[5] or ''
            if not any(x in provider_scope.lower() for x in ['outlook', 'office', 'microsoft']):
                safe_log(logger, logging.WARNING, f"Token for {email} is not a Microsoft/Outlook token")
                return None
            
            # Check if token is still valid
            expires_at_str = row[2]  # AccessTokenExpiresAt_UTC
            if expires_at_str:
                try:
                    # Parse the expires_at timestamp (it's stored as a timestamp, not ISO string)
                    expires_at = datetime.fromtimestamp(float(expires_at_str) / 1000000.0, tz=timezone.utc)
                except (ValueError, TypeError):
                    # Try parsing as ISO string if timestamp parsing fails
                    expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                
                current_time = datetime.now(timezone.utc)
                if expires_at <= current_time:
                    safe_log(logger, logging.WARNING, f"Token for {email} has expired (expired at {expires_at})")
                    return None
            
            # Return token data in the expected format
            token_data = {
                'id': row[0],
                'access_token': row[1],
                'expires_at': expires_at_str,
                'refresh_token': row[3],
                'manager_scope': row[4],
                'provider_scope': row[5],
                'email': row[6]
            }
            
            safe_log(logger, logging.INFO, f"Successfully retrieved valid Mailbird token for email: {email}")
            return token_data
            
        except sqlite3.Error as e:
            safe_log(logger, logging.ERROR, f"SQLite error getting Mailbird token for {email}: {e}")
            return None
        except Exception as e:
            safe_log(logger, logging.ERROR, f"Error getting Mailbird token for {email}: {e}")
            import traceback
            traceback.print_exc()
            return None

    @secure_function_logger
    def fetch_recent_ews_emails(self, email, hours=24):
        """Fetch recent emails using Mailbird's OAuth token via EWS"""
        token_data = self.get_mailbird_token(email)
        if not token_data:
            safe_log(logger, logging.WARNING, f"Could not get valid token for {email}")
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
            # Increase limit to 50 emails per account to match max_emails parameter
            messages = list(account.inbox.filter(datetime_received__gte=start_time).order_by('-datetime_received')[:50])
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

    def get_new_emails(self, last_run, max_emails=50):
        """
        Get new emails since last_run.
        
        Args:
            last_run: Timestamp of last run (should be limited to max 7 days ago by caller)
            max_emails: Maximum number of emails to fetch (default 50 to avoid rate limits)
        """
        emails = []
        
        # Ensure we don't fetch emails older than 7 days (safety check)
        max_lookback_days = 7
        max_lookback_timestamp = int((datetime.now(timezone.utc) - timedelta(days=max_lookback_days)).timestamp())
        if last_run < max_lookback_timestamp:
            last_run = max_lookback_timestamp
        
        # Gmail
        folders = ['INBOX', 'News', 'NaviSure Admin']
        emails_per_folder = max(1, max_emails // len(folders))  # Distribute limit across folders
        
        for folder in folders:
            if len(emails) >= max_emails:
                break
                
            # Gmail's 'after:' query accepts date in YYYY/MM/DD format
            # Convert timestamp to date string for more reliable querying
            lookback_date = datetime.fromtimestamp(last_run, tz=timezone.utc)
            query = f"after:{lookback_date.strftime('%Y/%m/%d')}"
            if folder != 'INBOX':
                query += f' label:"{folder}"'
            try:
                results = self.gmail.users().messages().list(
                    userId='me', 
                    q=query,
                    maxResults=min(emails_per_folder, max_emails - len(emails))
                ).execute()
                emails.extend({'id': msg['id'], 'source': 'gmail', 'folder': folder} for msg in results.get('messages', [])[:emails_per_folder])
            except Exception as e:
                continue

        # Yahoo IMAP
        try:
            mail = imaplib.IMAP4_SSL('imap.mail.yahoo.com')
            mail.login(self.yahoo_account['user'], self.yahoo_account['pwd'])
            mail.select('inbox')
            
            # Limit to last 7 days maximum for Yahoo (use UTC for consistent comparison)
            search_date = datetime.now(timezone.utc) - timedelta(days=7)
            if last_run > 0:
                last_run_date = datetime.fromtimestamp(last_run, tz=timezone.utc)
                # Use the more recent of: last_run or 7 days ago (both UTC)
                if last_run_date > search_date:
                    search_date = last_run_date
            
            since_date = search_date.strftime('%d-%b-%Y')
            _, data = mail.search(None, f'SINCE {since_date}')
            # Limit Yahoo emails to avoid processing too many old emails
            yahoo_limit = max_emails // 3  # Use 1/3 of limit for Yahoo
            yahoo_email_nums = data[0].split()[:yahoo_limit] if data[0] else []
            for num in yahoo_email_nums:
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
                # Calculate hours from last_run to now (max 7 days = 168 hours)
                if last_run > 0:
                    hours_ago = (datetime.now(timezone.utc).timestamp() - last_run) / 3600
                    hours_ago = min(hours_ago, 168)  # Cap at 7 days
                else:
                    hours_ago = 24  # Default to 24 hours if no last_run
                
                ews_emails = self.fetch_recent_ews_emails(outlook_email, hours=int(hours_ago))
                if ews_emails:
                    print(f"Fetched {len(ews_emails)} emails from {outlook_email}")
                emails.extend(ews_emails)
            except Exception as e:
                print(f"Error fetching emails from {outlook_email}: {e}")
                import traceback
                traceback.print_exc()
                continue

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

    def get_email_details_batch(self, email_ids, source='gmail'):
        """
        Get email details for multiple emails efficiently using batch requests.
        Returns a dict mapping email_id to email details.
        """
        if not email_ids:
            return {}
        
        print(f"\nGetting details for {len(email_ids)} emails from {source}")
        email_details = {}
        
        if source == 'gmail':
            # Use Google API client's batch request functionality with rate limiting
            # Gmail has limits: max 100 requests per batch, and rate limits on concurrent requests
            import json
            import time
            from googleapiclient.errors import HttpError
            
            # Deduplicate email IDs to avoid "request with this ID already exists" errors
            email_ids = list(dict.fromkeys(email_ids))  # Preserves order while removing duplicates
            
            def callback(request_id, response, exception):
                if exception is None:
                    email_details[request_id] = response
                else:
                    # Handle rate limit errors gracefully
                    if isinstance(exception, HttpError):
                        if exception.resp.status == 429:
                            print(f"Rate limit hit for email {request_id[:8]}... - will retry later")
                        else:
                            print(f"Error fetching email {request_id[:8]}...: {exception.resp.status}")
                    else:
                        # Check for duplicate request ID error
                        error_str = str(exception)
                        if "already exists" in error_str.lower():
                            print(f"Skipping duplicate email {request_id[:8]}...")
                        else:
                            print(f"Error fetching email {request_id[:8]}...: {exception}")
            
            # Split into smaller batches to avoid rate limits
            # Gmail allows ~100 per batch, but rate limits are stricter on concurrent requests
            # Use smaller chunks (10) and add delays to avoid hitting rate limits
            batch_size = 10
            delay_between_batches = 2.0  # 2 second delay between batches
            max_retries = 3
            
            i = 0
            retry_count = {}
            
            while i < len(email_ids):
                batch_chunk = email_ids[i:i + batch_size]
                chunk_key = i // batch_size
                
                try:
                    # Create batch request for this chunk
                    batch = self.gmail.new_batch_http_request(callback=callback)
                    
                    # Add each email request to the batch (deduplicated)
                    seen_in_batch = set()
                    for email_id in batch_chunk:
                        if email_id not in seen_in_batch:
                            seen_in_batch.add(email_id)
                            request = self.gmail.users().messages().get(userId='me', id=email_id, format='full')
                            batch.add(request, request_id=email_id)
                    
                    # Execute batch request
                    batch.execute()
                    
                    # Success - move to next batch
                    retry_count[chunk_key] = 0
                    i += batch_size
                    
                    # Add delay between batches to avoid rate limits
                    if i < len(email_ids):
                        time.sleep(delay_between_batches)
                        
                except HttpError as e:
                    if e.resp.status == 429:
                        retry_count[chunk_key] = retry_count.get(chunk_key, 0) + 1
                        if retry_count[chunk_key] >= max_retries:
                            print(f"Max retries ({max_retries}) exceeded for batch {chunk_key}. Skipping and continuing...")
                            retry_count[chunk_key] = 0
                            i += batch_size  # Skip this batch
                            continue
                        
                        # Exponential backoff: wait 2^retry_count * 5 seconds
                        wait_time = (2 ** retry_count[chunk_key]) * 5
                        print(f"Rate limit exceeded (batch {chunk_key}, attempt {retry_count[chunk_key]}/{max_retries}). Waiting {wait_time} seconds...")
                        time.sleep(wait_time)
                        # Retry same batch - don't increment i
                        continue
                    else:
                        print(f"HTTP error in batch {chunk_key}: {e.resp.status} - {e}")
                        # Skip this batch and continue
                        i += batch_size
                except Exception as e:
                    error_str = str(e)
                    if "already exists" in error_str.lower():
                        print(f"Duplicate request ID error in batch {chunk_key}. Skipping duplicates and continuing...")
                        # Skip this batch and continue
                        i += batch_size
                    else:
                        print(f"Error executing batch {chunk_key}: {e}")
                        # Skip this batch and continue
                        i += batch_size
            
        elif source == 'yahoo':
            # For Yahoo, open one IMAP connection and fetch all emails in one session
            # This is much faster than opening/closing connections for each email
            # Limit to reasonable number to avoid slow processing
            max_yahoo_batch = 20  # Don't process more than 20 Yahoo emails at once
            email_ids = email_ids[:max_yahoo_batch]
            
            print(f"Fetching {len(email_ids)} Yahoo emails in one batch...")
            try:
                mail = imaplib.IMAP4_SSL('imap.mail.yahoo.com')
                mail.login(self.yahoo_account['user'], self.yahoo_account['pwd'])
                mail.select('inbox')
                
                # Fetch all emails in one session
                for idx, msg_id in enumerate(email_ids, 1):
                    if idx % 5 == 0:
                        print(f"  Processed {idx}/{len(email_ids)} Yahoo emails...")
                    try:
                        _, data = mail.fetch(str(msg_id), '(RFC822)')
                        if data and data[0]:
                            raw_email = data[0][1]
                            msg = email.message_from_bytes(raw_email)
                            headers = [{'name': h, 'value': v} for h, v in msg.items()]
                            
                            # Handle email content properly
                            if msg.is_multipart():
                                content_parts = []
                                for part in msg.walk():
                                    if part.get_content_type() == "text/plain":
                                        payload = part.get_payload(decode=True)
                                        if payload:
                                            content_parts.append(payload.decode('utf-8', errors='ignore'))
                                content = ' '.join(content_parts)
                            else:
                                payload = msg.get_payload(decode=True)
                                content = payload.decode('utf-8', errors='ignore') if payload else ''
                            
                            # Extract common headers
                            from_addr = msg.get('From', 'Unknown')
                            subject = msg.get('Subject', 'No Subject')
                            date_str = msg.get('Date', '')
                            
                            # Convert date to timestamp if possible
                            try:
                                from email.utils import parsedate_to_datetime
                                dt = parsedate_to_datetime(date_str)
                                timestamp = int(dt.timestamp()) if dt else 0
                            except:
                                timestamp = 0
                            
                            # Format to match Gmail API structure
                            email_details[msg_id] = {
                                'payload': {
                                    'headers': headers
                                },
                                'snippet': content[:200] if content else '',
                                'internalDate': str(timestamp * 1000) if timestamp else '0'
                            }
                    except Exception as e:
                        print(f"Error fetching Yahoo email {msg_id}: {e}")
                        continue
                
                mail.logout()
            except Exception as e:
                print(f"Error connecting to Yahoo IMAP: {e}")
                # Try individual fetches as fallback
                for msg_id in email_ids[:10]:  # Limit fallback to first 10 emails
                    try:
                        details = self.get_email_details(msg_id, source)
                        if details:
                            email_details[msg_id] = details
                    except:
                        continue
        
        return email_details

    def get_email_details(self, msg_id, source='gmail'):
        """
        Get email details and update conversation tracking.
        Note: For Yahoo emails, use get_email_details_batch instead for better performance.
        """
        # Only print for Gmail to reduce noise (Yahoo should use batch method)
        if source == 'gmail':
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
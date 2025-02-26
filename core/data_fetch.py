from dropbox import Dropbox
from core.api import get_dropbox_client
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import pickle
import os
from google.auth.transport.requests import Request

class DataFetcher:
    def __init__(self):
        self.dropbox = get_dropbox_client()
        self.SCOPES = [
            'https://www.googleapis.com/auth/gmail.readonly',
            'https://www.googleapis.com/auth/calendar.readonly'
        ]
        self.CRED_FILE = r"C:\Users\adamo\Dropbox\_Consulting\NaviSsurance\client_secret.json"
        self.TOKEN_FILE = r"C:\Users\adamo\Dropbox\_Consulting\NaviSsurance\navi_token.pkl"
        self.DB_FILE = r"F:\naviSsurance_index.db"
        self.gmail, self.calendar = self.get_services()

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
        return self.calendar.events().list(
            calendarId='primary', timeMin=time_min, timeMax=time_max, singleEvents=True
        ).execute().get('items', [])

    def get_new_emails(self, last_run):
        return self.gmail.users().messages().list(
            userId='me', q=f"after:{last_run}"
        ).execute().get('messages', [])

    def get_email_details(self, msg_id):
        return self.gmail.users().messages().get(userId='me', id=msg_id, format='full').execute()

    def search_dropbox(self, query):
        # Placeholder—replace with your Dropbox search logic if different
        return self.dropbox.files_search_v2(query).matches
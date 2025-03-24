import requests
from dotenv import load_dotenv, set_key
import os
from dropbox import Dropbox
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv("C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/config/.env", override=True)

# Load from environment variables
DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN")
DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY")
DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET")
BRAVE_API_URL = os.getenv("BRAVE_API_URL")
BRAVE_TOKEN = os.getenv("BRAVE_TOKEN")

# Path to the .env file (assumes it’s in the root directory)
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")

class DropboxClient:
    """Manages a Dropbox client with token refresh."""
    def __init__(self):
        self.client = None
        self.access_token = None
        self.expires_at = None

    def get_client(self) -> Dropbox:
        """Get or refresh the Dropbox client."""
        if self.client is None or datetime.now() >= self.expires_at:
            self.refresh()
        return self.client

    def refresh(self):
        """Refresh the Dropbox access token and update .env."""
        new_access_token, new_refresh_token = refresh_dropbox_token()
        self.access_token = new_access_token
        self.client = Dropbox(new_access_token)
        self.expires_at = datetime.now() + timedelta(hours=4)
        # Update the .env file with the new tokens
        set_key(ENV_FILE, "DROPBOX_ACCESS_TOKEN", new_access_token)
        set_key(ENV_FILE, "DROPBOX_REFRESH_TOKEN", new_refresh_token)

dropbox_client = DropboxClient()

def refresh_dropbox_token():
    response = requests.post("https://api.dropbox.com/oauth2/token", data={
        "grant_type": "refresh_token",
        "refresh_token": DROPBOX_REFRESH_TOKEN,
        "client_id": DROPBOX_APP_KEY,
        "client_secret": DROPBOX_APP_SECRET
    })
    print(f"Request Data: {response.request.body}")
    print(f"Status: {response.status_code}, Response: {response.text}")
    if response.status_code == 200:
        data = response.json()
        return data["access_token"], data.get("refresh_token", DROPBOX_REFRESH_TOKEN)
    else:
        response.raise_for_status()

def get_dropbox_client() -> Dropbox:
    """Creates a Dropbox client with the current or refreshed access token."""
    return dropbox_client.get_client()

def brave_search(query: str) -> dict | None:
    """Perform a search using the Brave Search API."""
    headers = {"Accept": "application/json", "X-Subscription-Token": BRAVE_TOKEN}
    params = {"q": query, "count": 10}
    try:
        response = requests.get(BRAVE_API_URL, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Brave search failed for query '{query}': {str(e)}")
        raise RuntimeError(f"Search failed: {str(e)}")
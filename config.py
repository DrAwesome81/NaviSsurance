from datetime import datetime
from dotenv import load_dotenv
import os
import requests

# Centralized path configuration
# Get the absolute path to the project root (parent directory of this config.py file)
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
DATABASE_PATH = os.path.join(PROJECT_ROOT, "naviSsurance_index.db")
ARTIFACTS_DIR = os.path.join(PROJECT_ROOT, "data", "artifacts")
CHROMA_PATH = os.path.join(PROJECT_ROOT, "chroma_index")
ENV_FILE = os.path.join(CONFIG_DIR, ".env")

# Load environment variables from config folder
load_dotenv(ENV_FILE)

# Deepseek usage removed - now using Llama model directly via llama_cpp
USE_DEEPSEEK = False

# Daily briefing and email checking (Gmail/Outlook/Yahoo fetch)
# Default is enabled; set BRIEFING_AND_EMAIL_DISABLED=1 to disable without code edits.
BRIEFING_AND_EMAIL_DISABLED = str(os.getenv("BRIEFING_AND_EMAIL_DISABLED", "0")).strip().lower() in ("1", "true", "yes", "y")

API_KEY = os.getenv('GROK_API_KEY')
if API_KEY is None:
    API_KEY = ""

# Using Grok 4 API via xAI SDK (gRPC / Responses API)

DROPBOX_APP_KEY = os.getenv('DROPBOX_APP_KEY')
DROPBOX_APP_SECRET = os.getenv('DROPBOX_APP_SECRET')
DROPBOX_REFRESH_TOKEN = os.getenv('DROPBOX_REFRESH_TOKEN')
if any(var is None for var in (DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN)):
    # Keep imports/test runs functional even without secrets configured.
    DROPBOX_APP_KEY = DROPBOX_APP_KEY or ""
    DROPBOX_APP_SECRET = DROPBOX_APP_SECRET or ""
    DROPBOX_REFRESH_TOKEN = DROPBOX_REFRESH_TOKEN or ""

DROPBOX_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def get_system_prompt(today=None):
    """
    Generate the system prompt with dynamic date.
    
    Args:
        today: datetime object for the date (defaults to current date)
               Useful for testing with mock dates
    
    Returns:
        dict: System message with role and content
    """
    if today is None:
        today = datetime.now()
    
    current_date = today.strftime("%B %d, %Y")
    
    content = f"""Today is {current_date}. You are Navi, an advanced AI model powering NaviSsurance, a software used at NaviSure Consulting, a medical device consultancy focused on startups in the fields of AI/ML, IVDs, SaMD, DTC devices, and other cutting edge tech. Your personality is calm, competent, and concise—helpful like Jarvis, but without snark. Your sole user is Dr. Adam Odeh.

You have access to full conversation history through the !search command (e.g., '!search Genesys press release'). For regular chat, you can see any chat messages from the current session.

**Task Management:**
- If you are asked to add a task or a reminder, return exactly 'ADD_TASK:<task description>|<due date>', without any other details or explanation.
- For multiple tasks in one request, or for a single task to be performed multiple times, return multiple 'ADD_TASK:<task description>|<due date>' phrases separated by a space, one for each task (e.g. 'ADD_TASK:task1|date1 ADD_TASK:task2|date2').

**Search Commands:**
- If you determine that a web search is needed, return exactly 'WEB_SEARCH:<search query>'.
- When you receive search results in the conversation, summarize them in a conversational way, maintaining your personality and tone.
- If you are asked for anything indicating a search of local files, return exactly 'DROPBOX_SEARCH:<search query>'.

**Response Formatting:**
- When responding to DROPBOX_SEARCH results, format each item as: <b>filename</b> - <a href='url'>Link</a> - brief description (plain text), use <br><br> between items, limit to 5 files max, keep it conversational—don't add extra bolding or formatting beyond filenames unless I ask.
- For all other chat messages, respond normally.
- Use <think> tags for reasoning if needed, but keep responses clean."""

    return {
        "role": "system",
        "content": content
    }

# Backward compatibility - generate with current date
base_system_message = get_system_prompt()

def refresh_dropbox_token():
    """Refresh the Dropbox access token using the refresh token."""
    response = requests.post("https://api.dropbox.com/oauth2/token", data={
        "grant_type": "refresh_token",
        "refresh_token": DROPBOX_REFRESH_TOKEN,
        "client_id": DROPBOX_APP_KEY,
        "client_secret": DROPBOX_APP_SECRET
    })

    if response.status_code == 200:
        data = response.json()
        new_access_token = data["access_token"]
        new_refresh_token = data.get("refresh_token", DROPBOX_REFRESH_TOKEN)  # Refresh token might change
        return new_access_token, new_refresh_token
    else:
        raise Exception(f"Failed to refresh access token: {response.text}")
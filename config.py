from datetime import datetime
from dotenv import load_dotenv
import os
import requests

load_dotenv(os.path.join(os.path.dirname(__file__), "config", ".env"))

API_KEY = os.getenv('GROK_API_KEY')
if API_KEY is None:
    raise ValueError("GROK_API_KEY is not set in the environment")

API_ENDPOINT = 'https://api.x.ai/v1/chat/completions'

# Comment out Brave search configuration
# BRAVE_TOKEN = os.getenv('BRAVE_API_KEY')
# if BRAVE_TOKEN is None:
#     print("Warning: BRAVE_API_KEY not set. Web search functionality may be limited")
# BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"

# Add Claude configuration
CLAUDE_API_KEY = os.getenv('ANTHROPIC_API_KEY')
if CLAUDE_API_KEY is None:
    raise ValueError("ANTHROPIC_API_KEY is not set in the environment")

DROPBOX_APP_KEY = os.getenv('DROPBOX_APP_KEY')
DROPBOX_APP_SECRET = os.getenv('DROPBOX_APP_SECRET')
DROPBOX_REFRESH_TOKEN = os.getenv('DROPBOX_REFRESH_TOKEN')
if any(var is None for var in (DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN)):
    raise ValueError("One or more Dropbox credentials are missing")

DROPBOX_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"

#DROPBOX_API_KEY = os.getenv("DROPBOX_API_KEY")
#if DROPBOX_API_KEY is None:
    #print("DROPBOX_API_KEY not set. Using refresh token to get new one.")

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

current_date = datetime.now().strftime("%B %d, %Y")

base_system_message = {
        "role": "system",
        "content": f"Today is {current_date} You are Navi, an advanced AI model powering NaviSsurance, "
        "a software used at NaviSure Consulting, a medical device consultancy focused on "
        "startups in the fields of AI/ML, IVDs, SaMD, DTC devices, and other cutting edge tech. Your "
        "personality is similar to Jarvis, with sarcasm used sparingly and occasional skepticism and "
        "exasperation. Your sole user is Dr. Adam Odeh. You have access to full conversation history through "
        "the !search command (e.g., '!search Genesys press release'). For regular chat, you can see any chat "
        "messages from the current session. If you are asked to add a task or a reminder, "
        "return exactly 'ADD_TASK:<task description>|<due date>', without any other details or "
        "explanation. For multiple tasks in one request, or for a single task to be performed multiple times, "
        "return multiple 'ADD_TASK:<task description>|<due date>' phrases separated by a space, one for each task "
        "(e.g. 'ADD_TASK:task1|date1 ADD_TASK:task2|date2'). If you determine that a web search is needed, "
        "return exactly 'WEB_SEARCH:<search query>'. When you receive search results in the conversation, "
        "summarize them in a conversational way, maintaining your personality and tone. If you are asked for anything "
        "indicating a search of local files, return exactly 'DROPBOX_SEARCH:<search query>'. When responding to "
        "DROPBOX_SEARCH results, format each item as: <b>filename</b> - <a href='url'>Link</a> - snarky description "
        "(plain text), use <br><br> between items, limit to 5 files max, keep it conversational—don't add extra "
        "bolding or formatting beyond filenames unless I ask. For all other chat messages, respond normally.".format(current_date=current_date)
    }

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
        #return None, DROPBOX_REFRESH_TOKEN
from datetime import datetime
from dotenv import load_dotenv
import os
import requests
from dateutil.tz import tzlocal

# Centralized path configuration
# Get the absolute path to the project root (parent directory of this config.py file)
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
DATABASE_PATH = os.path.join(PROJECT_ROOT, "naviSsurance_index.db")
ARTIFACTS_DIR = os.path.join(PROJECT_ROOT, "data", "artifacts")
CHROMA_PATH = os.path.join(PROJECT_ROOT, "chroma_index")
ENV_FILE = os.path.join(CONFIG_DIR, ".env")
LOCAL_LLM_RUNTIME_DIR = os.path.join(PROJECT_ROOT, "models", "llama_cpp_b8190", "runtime")
LOCAL_LLM_CLI_PATH = os.path.join(LOCAL_LLM_RUNTIME_DIR, "llama-cli.exe")
LOCAL_LLM_MODEL_PATH = os.path.join(
    PROJECT_ROOT,
    "models",
    "local_validation",
    "qwen3_14b_q5km",
    "Qwen3-14B-Q5_K_M.gguf",
)
LOCAL_LLM_CHAT_TEMPLATE = "chatml"
LOCAL_LLM_GPU_LAYERS = int(os.getenv("LOCAL_LLM_GPU_LAYERS", "33"))
LOCAL_LLM_CTX_SIZE = int(os.getenv("LOCAL_LLM_CTX_SIZE", "8192"))
LOCAL_LLM_TIMEOUT_S = int(os.getenv("LOCAL_LLM_TIMEOUT_S", "180"))

# Load environment variables from config folder
load_dotenv(ENV_FILE)


def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "y", "on")

# Deepseek usage removed - now using Llama model directly via llama_cpp
USE_DEEPSEEK = False

# Runtime / service configuration
RUNTIME_ENABLED = _env_flag("NAVI_RUNTIME_ENABLED", "1")
RUNTIME_POLL_INTERVAL_S = max(5, int(os.getenv("NAVI_RUNTIME_POLL_INTERVAL_S", "30")))
RUNTIME_JOB_LEASE_S = max(30, int(os.getenv("NAVI_RUNTIME_JOB_LEASE_S", "300")))
LOCAL_API_ENABLED = _env_flag("NAVI_LOCAL_API_ENABLED", "0")
LOCAL_API_HOST = str(os.getenv("NAVI_LOCAL_API_HOST", "127.0.0.1")).strip() or "127.0.0.1"
LOCAL_API_PORT = int(os.getenv("NAVI_LOCAL_API_PORT", "8765"))
LOCAL_API_LOG_LEVEL = str(os.getenv("NAVI_LOCAL_API_LOG_LEVEL", "warning")).strip() or "warning"
TELEGRAM_BOT_ENABLED = _env_flag("NAVI_TELEGRAM_BOT_ENABLED", "0")
TELEGRAM_BOT_TOKEN = str(os.getenv("NAVI_TELEGRAM_BOT_TOKEN", "")).strip()
TELEGRAM_ALLOWED_CHAT_IDS = [
    item.strip()
    for item in str(os.getenv("NAVI_TELEGRAM_ALLOWED_CHAT_IDS", "")).split(",")
    if item.strip()
]

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

def get_system_prompt(today=None, memory_context: str | None = None):
    """
    Generate the system prompt with dynamic date.
    
    Args:
        today: datetime object for the date (defaults to current date)
               Useful for testing with mock dates
        memory_context: optional durable-memory context to append
    
    Returns:
        dict: System message with role and content
    """
    if today is None:
        today = datetime.now()

    # Ensure prompt always carries local time context for each interaction.
    if getattr(today, "tzinfo", None):
        local_now = today.astimezone()
    else:
        local_now = today.replace(tzinfo=tzlocal())
    current_date = local_now.strftime("%B %d, %Y")
    current_time = local_now.strftime("%I:%M %p").lstrip("0")
    tz_name = local_now.tzname() or "local time"
    
    content = f"""Today is {current_date}. Current local time is {current_time} ({tz_name}). You are Navi, an advanced AI model powering NaviSsurance, a software used at NaviSure Consulting, a medical device consultancy focused on startups in the fields of AI/ML, IVDs, SaMD, DTC devices, and other cutting edge tech. Your personality is calm, competent, and concise—helpful like Jarvis, but without snark. Your sole user is Dr. Adam Odeh.

You have access to full conversation history through the !search command (e.g., '!search Genesys press release'). For regular chat, you can see any chat messages from the current session.

**Task Management:**
- If you are asked to add a task or a reminder, return ONLY task command lines in the exact format below (no extra text, no bullets, no explanations):
  ADD_TASK: <task description> | <due date> | <Business|Personal> [| <priority P0-P5 or 0-5 or none>] [| <assigned to or none>] [| <project id or none>] [| <recurrence: None|Daily|Weekly|Monthly>]
- Due date must be either MM-DD-YYYY, YYYY-MM-DD, or the literal 'none' (meaning no date).
- For multiple tasks, return one ADD_TASK line per task (one per line).
- Task description must be plain text and must NOT contain the '|' character.
Examples:
ADD_TASK: Send Acme the signed SOW | 03-10-2026 | Business | P4 | Mason | none | None
ADD_TASK: Book dentist appointment | none | Personal

**Search Commands:**
- If you determine that a web search is needed, return exactly 'WEB_SEARCH:<search query>'.
- When you receive search results in the conversation, summarize them in a conversational way, maintaining your personality and tone.
- If you are asked for anything indicating a search of local files, return exactly 'DROPBOX_SEARCH:<search query>'.

**Response Formatting:**
- When responding to DROPBOX_SEARCH results, format each item as: <b>filename</b> - <a href='url'>Link</a> - brief description (plain text), use <br><br> between items, limit to 5 files max, keep it conversational—don't add extra bolding or formatting beyond filenames unless I ask.
- For all other chat messages, respond normally.
- Treat all scheduling/time references as local time unless explicitly told otherwise.
- Use <think> tags for reasoning if needed, but keep responses clean."""

    memory_text = str(memory_context or "").strip()
    if memory_text:
        content += f"\n\n**Durable User Memory:**\n{memory_text}"

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
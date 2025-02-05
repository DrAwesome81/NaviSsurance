from PyQt6.QtCore import QObject, pyqtSignal, QDate
import sqlite3
import uuid
import requests
import re
import json
from dotenv import load_dotenv
import os
from dropbox import Dropbox, files
from dropbox.files import SearchMatch, FileMetadata, SearchOptions
from dropbox.exceptions import AuthError
from datetime import datetime
from dateutil import parser
from docx import Document # for DOCX text extraction
import fitz # PyMuPDF for PDF text extraction
import pandas as pd # For reading Excel files

load_dotenv()

API_KEY = os.getenv('GROK_API_KEY')
if API_KEY is None:
    raise ValueError("GOK_API_KEY is not set in the environment")

API_ENDPOINT = 'https://api.x.ai/v1/chat/completions'

BRAVE_TOKEN = os.getenv('BRAVE_API_KEY')
if BRAVE_TOKEN is None:
    print("Warning: BRAVE_API_KEY not set. Web search functionality may be limited")

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"

DROPBOX_APP_KEY = os.getenv('DROPBOX_APP_KEY')
DROPBOX_APP_SECRET = os.getenv('DROPBOX_APP_SECRET')
DROPBOX_REFRESH_TOKEN = os.getenv('DROPBOX_REFRESH_TOKEN')
if any(var is None for var in (DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN)):
    raise ValueError("One or more Dropbox credentials are missing")

DROPBOX_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"

DROPBOX_API_KEY = os.getenv("DROPBOX_API_KEY")
if DROPBOX_API_KEY is None:
    print("DROPBOX_API_KEY not set. Using refresh token to get new one.")

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
        "exasperation. Your sole user is Dr. Adam Odeh. If you are asked to add a task or a reminder, "
        "return exactly 'ADD_TASK:<task description>|<due date>', without any other details or "
        "explanation. If you are asked anything that would require a web search, return exactly "
        "'WEB_SEARCH:<search query>'. If you are asked for anything indicating a search of local files, "
        "return exactly 'DROPBOX_SEARCH:<search query>'. For all other chat messages, respond "
        "normally.".format(current_date=current_date)
    }

def refresh_dropbox_token():
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
        print(f"Failed to refresh token: {response.text}")
        return None, DROPBOX_REFRESH_TOKEN

def get_dropbox_client():
    """Creates a Dropbox client with the current or refreshed access token."""
    new_access_token, new_refresh_token = refresh_dropbox_token()
    if new_access_token:
        os.environ["DROPBOX_API_KEY"] = new_access_token
        os.environ["DROPBOX_REFRESH_TOKEN"] = new_refresh_token
        return Dropbox(new_access_token)
    else:
        raise Exception("Failed to refresh access token")

def brave_search(query):
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": BRAVE_TOKEN
    }
    params = {
        "q": query,
        "count": 10 # Number of results to return
    }
    
    # comment out: print(f"Query sent to Brave Search API: {params['q']}")  # Debug print to see the exact query

    try:
        response = requests.get(BRAVE_API_URL, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Search failed: {e}")
        return None

class ChatHandler(QObject):
    task_added_signal = pyqtSignal(str, str)  # Signal to add tasks (task_text, due_date)

    def __init__(self, chat_window=None):
        super().__init__()
        self.db_name = 'navissurance.db'
        self.conn = sqlite3.connect(self.db_name)
        self.cursor = self.conn.cursor()
        self.chat_window = chat_window  # Store reference to ChatWindow
        self.dropbox = get_dropbox_client()  # Initialize Dropbox client here

    def close(self):
        self.conn.close()

    def extract_text_from_pdf(pdf_path):
        document = fitz.open(pdf_path)
        text = ""
        for page_num in range(len(document)):
            page = document.load_page(page_num)
            text += page.get_text()
        return text
    
    def extract_text_from_docx(docx_path):
        doc = Document(docx_path)
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)
        return '\n'.join(full_text)
    
    def extract_text_from_txt(txt_path):
        with open(txt_path, 'r', encoding='utf-8') as file:
            return file.read()
    
    def _summarize_search_results(self, search_results):
        summary_request = {
            "role": "system",
            "content": "Summarize these search results, using bullet points when appropriate."
        }
        summary_data = {
            "messages": [summary_request, {"role": "user", "content": json.dumps(search_results)}],
            "model": "grok-2-latest",
            "stream": False
        }
        try:
            summary_response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(summary_data))
            summary_response.raise_for_status()
            return summary_response.json()['choices'][0]['message']['content']
        except requests.exceptions.RequestException as e:
            print(f"API call for summary failed: {e}")
            return "An error occurred while summarizing search results."
    
    def get_chat_history(self, session_id):
        conn = sqlite3.connect('navissurance.db')
        c = conn.cursor()
        c.execute('''
            SELECT role, content, timestamp 
            FROM conversation 
            WHERE session_id = ? 
            ORDER BY timestamp DESC LIMIT 20
        ''', (session_id,))
        history = c.fetchall()
        conn.close()
        return history

    def save_message(self, session_id, role, content):
        conn = sqlite3.connect('navissurance.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO conversation (session_id, role, content) VALUES (?, ?, ?)
        ''', (session_id, role, content))
        conn.commit()
        conn.close()

    def get_response(self, message, session_id, conversation_history):
        
        conversation_history.append({"role": "user", "content": message})

        try:
            grok_response = chat_with_grok(conversation_history, session_id)
            # comment out: print(grok_response)
            
            # Check for specific phrases
            if grok_response.startswith("ADD_TASK:"):
                task_info = grok_response.split("ADD_TASK:")[1].split("|")
                task_description = task_info[0] 

                 # Parse the due date
                try:
                    due_date_obj = parser.parse(task_info[1])
                    due_date = due_date_obj.strftime("%m-%d-%Y")  # Convert to the format you're using
                except ValueError:
                    print(f"Failed to parse date: {task_info[1]}")
                    due_date = "unknown"  # or set a default date or ask for clarification

                self._add_task_from_chat(task_info[0], task_info[1], session_id)
                # Prepare a new message for Grok to confirm the task addition
                new_system_message = {
                    "role": "system",
                    "content": f"{base_system_message['content']} You've just added '{task_description}' to "
                    "Dr. Odeh's task list, due on {due_date}. Inform him about this addition in your "
                    "characteristic manner."
                }
                
                # Combine the messages for the new request
                confirm_data = {
                    "messages": [new_system_message],
                    "model": "grok-2-latest",
                    "stream": False
                }
                
                # Send this new request to get a personality-based response
                try:
                    confirm_response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(confirm_data))
                    confirm_response.raise_for_status()
                    return confirm_response.json()['choices'][0]['message']['content']
                except requests.exceptions.RequestException as e:
                    print(f"API call for task confirmation failed: {e}")
                    return f"Task '{task_description}' has been added to your list, due on {due_date}, but I couldn't get a confirmation message from Grok."

            elif grok_response.startswith("WEB_SEARCH:"):
                query = grok_response.split("WEB_SEARCH:")[1]
                search_results = brave_search(query)
                if search_results:
                    # Send search results to Grok for summarization
                    combined_system_message = {
                        "role": "system",
                        "content": base_system_message["content"] + " Summarize these search results, using bullet "
                        "points when appropriate. Keep your responses in line with your established personality."
                    }
                
                    summary_data = {
                        "messages": [combined_system_message, {"role": "user", "content": json.dumps(search_results)}],
                        "model": "grok-2-latest",
                        "stream": False
                    }
                    try:
                        summary_response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(summary_data))
                        summary_response.raise_for_status()
                        summary = summary_response.json()['choices'][0]['message']['content']
                        return summary
                    except requests.exceptions.RequestException as e:
                        print(f"API call for summary failed: {e}")
                        return "An error occurred while summarizing search results."
                else:
                    return "No relevant search results found."
            elif grok_response.startswith("DROPBOX_SEARCH:"):
                search_query = grok_response.split("DROPBOX_SEARCH:")[1]
                dropbox_search_result = self._search_dropbox(search_query)
                
                # Prepare a new message for Grok with the search results
                new_system_message = {
                    "role": "system",
                    "content": base_system_message['content'] + " Here are the Dropbox search results for '{search_query}'. "
                    "Summarize or format these results for Dr. Odeh in your characteristic manner, using bullet "
                    "points for the file names and links when available.".format(search_query=search_query)
                }
                
                search_result_message = {
                    "role": "assistant",
                    "content": json.dumps(dropbox_search_result)
                }
                
                # Combine the messages for the new request
                confirm_data = {
                    "messages": [base_system_message, new_system_message, search_result_message],
                    "model": "grok-2-latest",
                    "stream": False
                }
                
                try:
                    confirm_response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(confirm_data))
                    confirm_response.raise_for_status()
                    return confirm_response.json()['choices'][0]['message']['content']
                except requests.exceptions.RequestException as e:
                    print(f"API call for Dropbox result processing failed: {e}")
                    return "I couldn't process the Dropbox search results, but they include: " + str(dropbox_search_result)[:200] + "..."
            else:
                # If it's neither, return the response directly
                return grok_response

        except Exception as e:
            print(f"Error in get_response: {e}")
            return "I encountered an issue while processing your request. Please try again."

    def _process_task_response(self, grok_response):
        task_pattern = r"I've added the task '(.*?)' for '(\d{2}-\d{2}-\d{4})'\."
        match = re.search(task_pattern, grok_response)

        if match:
            task_text = match.group(1)
            due_date = match.group(2)
            # comment out: print(f"Adding extracted task: {task_text}, Due Date: {due_date}")

            if self.task_added_signal:
                self.task_added_signal.emit(task_text, due_date)
        else:
            print("No task found in Navi's response")
    
    def _search_dropbox(self, query, folder_path="/"):
        dbx = get_dropbox_client()
        
        try:
            search_options = files.SearchOptions(max_results=1000, path=folder_path)
            search_results = dbx.files_search_v2(query=query, options=search_options)
            print(f"Query: {query}")
            
            print(f"Number of matches found: {len(search_results.matches)}")
            
            results = []
            for match in search_results.matches:
                if isinstance(match.metadata, files.MetadataV2):
                    inner_metadata = match.metadata.get_metadata()
                    if isinstance(inner_metadata, files.FileMetadata):
                        # Generate a shared link for each file
                        try:
                            shared_link = dbx.sharing_create_shared_link(inner_metadata.path_lower).url
                            results.append({
                                "name": inner_metadata.name,
                                "path": inner_metadata.path_display,
                                "link": shared_link
                            })
                        except Exception as link_error:
                            print(f"Failed to create shared link for {inner_metadata.name}: {link_error}")
                            results.append({
                                "name": inner_metadata.name,
                                "path": inner_metadata.path_display,
                                "link": None
                            })
            return results
        
        except Exception as e:
            print(f"An error occurred while searching Dropbox: {e}")
            return []
    
    def _add_task_from_chat(self, task_text, due_date, session_id):
        # comment out: print(f"Adding task: {task_text}, Due Date: {due_date}")
        if self.task_added_signal:
            self.task_added_signal.emit(task_text, due_date)  # Emit the task-added signal
        else:
            # comment out: print(f"Task to add: {task_text}, Due Date: {due_date}")  # Fallback for debugging
            return f"I've added the task '{task_text}' with a due date of {due_date}."

    def get_chat_history(self, session_id):
        self.cursor.execute(
            '''
            SELECT role, content, timestamp 
            FROM conversation 
            WHERE session_id = ? 
            ORDER BY timestamp DESC LIMIT 20
            ''', (session_id,)
        )
        return self.cursor.fetchall()


def chat_with_grok(messages, session_id, intent=None):
    
    messages = [base_system_message] + messages

    data = {
        "messages": messages,
        "model": "grok-2-latest",
        "stream": False
    }

    try:
        response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        response_json = response.json()
        grok_response = response_json['choices'][0]['message']['content']
        return grok_response
    except requests.exceptions.RequestException as e:
        print(f"API call failed: {e}")
        return "Sorry, I'm having trouble connecting to the server."

def detect_task_request(user_message):
    task_keywords = ["Navi, remind", "Navi, add a task", "Navi, schedule", "Navi, don't let me forget"]
    return any(keyword in user_message.lower() for keyword in task_keywords) or re.search(r"\b(due|on|by)\b", user_message.lower())

# Initialize database
def setup_db():
    conn = sqlite3.connect('navissurance.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS conversation (...);''')
    conn.commit()
    conn.close()

def initDatabase(self):
    self.conn = sqlite3.connect("todo.db")
    self.cursor = self.conn.cursor()
    self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT,
            due_date TEXT
        )
    """)
    self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS archived_tasks (
            id INTEGER PRIMARY KEY,
            task TEXT,
            due_date TEXT
        )
    """)

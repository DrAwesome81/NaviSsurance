from datetime import datetime
from PyQt6.QtCore import QObject, pyqtSignal
import sqlite3
import requests
import json
import re
import sys
from dateutil import parser
from dropbox import Dropbox
from core.api import get_dropbox_client, brave_search
from config import headers, API_ENDPOINT, base_system_message
from core.db import DatabaseManager
from core.file_handler import search_dropbox

class ChatHandler(QObject):
    task_added_signal = pyqtSignal(str, str)  

    def __init__(self, chat_window=None):
        super().__init__()
        self.chat_window = chat_window  
        self.dropbox = get_dropbox_client()
        self.db = DatabaseManager()
        self.last_search_results = [] # Store search results  

    def close(self):
        self.conn.close()
        self.cursor.close()
    
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

    def save_message(self, session_id, role, content):
        self.db.save_message(session_id, role, content)

    def get_response(self, message, session_id, conversation_history):
        conversation_history.append({"role": "user", "content": message})
        try:
            grok_response = chat_with_grok(conversation_history, session_id)
            print(f"Grok response: {grok_response}")
            task_segments = [seg for seg in grok_response.split("ADD_TASK:") if seg.strip()]
            added_tasks = []
            if task_segments and "ADD_TASK:" in grok_response:   
                for segment in task_segments:
                    task_info = segment.split("|", 1)
                    if len(task_info) != 2:
                        print(f"Skipping malformed segment: {segment}")
                        continue
                    task_description = task_info[0].strip()
                    try:
                        due_date_obj = parser.parse(task_info[1].strip(), default=datetime.now())
                        due_date = due_date_obj.strftime("%m-%d-%Y")
                    except ValueError:
                        print(f"Failed to parse date: {task_info[1]}")
                        due_date = "unknown"
                    self._add_task_from_chat(task_description, due_date, session_id)
                    added_tasks.append(f"'{task_description}' due on {due_date}")               
            elif "added" in grok_response.lower() or "remind" in message.lower() or "forget" in message.lower():
                task_match = re.search(r"'([^']+)'", grok_response) or re.search(r"(?:to|forget)\s+(.+?)(?:\s+(?:on|due|for))", message)
                task_description = task_match.group(1) if task_match else "unknown task"
                date_matches = re.findall(r"(?:on|due)\s+([A-Za-z]+(?: \d{1,2}, \d{4})?)", grok_response + " " + message)
                if not date_matches:
                    due_date = "unknown"
                    self._add_task_from_chat(task_description, due_date, session_id)
                    added_tasks.append(f"'{task_description}' due on {due_date}")
                for date_str in date_matches:
                    try:
                        due_date_obj = parser.parse(date_str.strip(), default=datetime.now())
                        due_date = due_date_obj.strftime("%m-%d-%Y")
                    except ValueError:
                        print(f"Failed to parse date: {date_str}")
                        due_date = "unknown"
                    self._add_task_from_chat(task_description, due_date, session_id)
                    added_tasks.append(f"'{task_description}' due on {due_date}")

            elif grok_response.startswith("DROPBOX_SEARCH:") or "search dropbox" in message.lower():
                search_query = grok_response.split("DROPBOX_SEARCH:")[1] if grok_response.startswith("DROPBOX_SEARCH:") else message.split("search dropbox for", 1)[1].strip()
                print(f"Processing smart Dropbox search for: {search_query}")
                dropbox_files = search_dropbox(self.dropbox, search_query)  # Pass self.dropbox
                if not dropbox_files:
                    return f"No Dropbox files found for '{search_query}', Dr. Odeh—empty or glitchy?"
                files_summary = "\n".join([f"- {file['name']}: {file['content']}" for file in dropbox_files])
                self.last_search_results = dropbox_files  # Store for doc generation
                smart_query = {
                    "role": "user",
                    "content": f"Search query: '{search_query}'. Here’s a list of Dropbox files with snippets:\n{files_summary}\n"
                            f"Pick the most relevant files, provide clickable links if available, and explain why in your characteristic manner."
                }
                confirm_data = {
                    "messages": [base_system_message, smart_query],
                    "model": "grok-2-latest",
                    "stream": False
                }
                try:
                    confirm_response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(confirm_data))
                    confirm_response.raise_for_status()
                    return confirm_response.json()['choices'][0]['message']['content']
                except requests.RequestException as e:
                    print(f"API call for smart Dropbox search failed: {e}")
                    files_list = "\n".join([f"- {file['name']} ({file['link']})" if file['link'] else f"- {file['name']}" for file in dropbox_files])
                    return f"Couldn’t refine the search for '{search_query}', Dr. Odeh—here’s the raw list:\n{files_list}"

            if added_tasks:    
                confirmation_message = {
                    "role": "assistant",
                    "content": f"I've added {', and '.join(added_tasks)} to your task list, Dr. Odeh."
                }
                updated_history = conversation_history + [confirmation_message]
                new_system_message = {
                    "role": "system",
                    "content": f"{base_system_message['content']} You've just added {', and '.join(added_tasks)} to "
                           "Dr. Odeh's task list. Inform him about this in your "
                           "characteristic manner."
                }
                confirm_data = {
                    "messages": [new_system_message] + updated_history,
                    "model": "grok-2-latest",
                    "stream": False
                } 
                try:
                    confirm_response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(confirm_data))
                    confirm_response.raise_for_status()
                    return confirm_response.json()['choices'][0]['message']['content']
                except requests.exceptions.RequestException as e:
                    print(f"API call for task confirmation failed: {e}")
                    if "429" in str(e):
                        return f"Added {', and '.join(added_tasks)}, Grok is rate limited, but you're set."
                    return f"Added {', and '.join(added_tasks)} but I couldn't get a confirmation message from Grok."
            
            elif message.lower().startswith("generate document"):
                if not self.last_search_results:
                    return "No files to generate from yet, Dr. Odeh—run a Dropbox search first!"
                user_input = message.split("generate document", 1)[1].strip() if "generate document" in message.lower() else ""
                files_to_use = self.last_search_results  # Could add file selection logic later
                content = "\n\n".join([f"{file['name']}:\n{file['content']}" for file in files_to_use])
                doc_query = {
                    "role": "user",
                    "content": f"User input: '{user_input}'. File contents:\n{content}\n"
                            f"Generate a document summary combining these, formatted for LibreOffice ODT."
                }
                confirm_data = {
                    "messages": [base_system_message, doc_query],
                    "model": "grok-2-latest",
                    "stream": False
                }
                try:
                    confirm_response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(confirm_data))
                    confirm_response.raise_for_status()
                    doc_text = confirm_response.json()['choices'][0]['message']['content']
                    self.last_search_results = dropbox_files # Store for later use
                    # Placeholder for ODT generation
                    print(f"Generated document text:\n{doc_text}")
                    return f"Document generated, Dr. Odeh—here’s the text (ODT coming soon):\n{doc_text}"
                except requests.RequestException as e:
                    print(f"Document generation failed: {e}")
                    return "Couldn’t generate the document, Dr. Odeh—Grok’s sulking!"
            
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

                files_list = ""
                for file in dropbox_search_result:
                    if file['link']:  # If there's a link
                        files_list += f"- **{file['name']}** ([link]({file['link']}))\n"
                    else:  # If there's no link
                        files_list += f"- {file['name']}\n"
                
                # Prepare a new message for Grok with the search results
                new_system_message = {
                    "role": "system",
                    "content": base_system_message['content'] + " Here are the Dropbox search results for '{search_query}':\n{files_list}. "
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

    def get_chat_history(self, session_id):
        return self.db.get_chat_history(session_id)
    
    def _add_task_from_chat(self, task_text, due_date, session_id):
        print(f"Adding to DB: {task_text} due {due_date}")
        self.db.add_task(session_id, task_text, due_date)
        print(f"Emitting signal: {task_text} due {due_date}")
        self.task_added_signal.emit(task_text, due_date)
    
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
        if hasattr(response, 'text'):
            print(f"Response content: {response.text}")
        return "Sorry, I'm having trouble connecting to the server."
    
def detect_task_request(user_message):
    task_keywords = ["Navi, remind", "Navi, add a task", "Navi, schedule", "Navi, don't let me forget"]
    return any(keyword in user_message.lower() for keyword in task_keywords) or re.search(r"\b(due|on|by)\b", user_message.lower())
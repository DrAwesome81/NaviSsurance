from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot, QTimer
from PyQt6.QtWidgets import QTextBrowser, QLineEdit, QPushButton, QFileDialog
from PyQt6.QtGui import QMouseEvent, QDesktopServices
import markdown
import re
import json
import time
from datetime import datetime
from dateutil import parser
from gui.notifications import notify_chat_response

PIPE_TASK_PATTERN = re.compile(
    r"(?:^|[\r\n]|(?:\s[-*•]\s))(?P<task>[^|\r\n]+?)\s*\|\s*(?P<due>\d{2}-\d{2}-\d{4}|none)\s*\|\s*(?P<category>Business|Personal)\b",
    re.IGNORECASE,
)


def extract_pipe_tasks(response: str) -> list[tuple[str, str]]:
    """
    Extract task tuples from compact prose/bullet format:
    - Task text | MM-DD-YYYY | Business|Personal
    Returns (task_text, due_date_mmddyyyy_or_today_for_none).
    """
    out: list[tuple[str, str]] = []
    if not (response or "").strip():
        return out
    seen: set[tuple[str, str]] = set()
    for m in PIPE_TASK_PATTERN.finditer(response):
        task_text = (m.group("task") or "").strip().strip(" -*•\t\r\n")
        # Remove priority heading remnants from one-line blobs.
        task_text = re.sub(
            r"^(?:#{1,6}\s*)?(?:high|medium|low)\s+priority(?:\s*\([^)]+\))?\s*[-:]\s*",
            "",
            task_text,
            flags=re.IGNORECASE,
        ).strip()
        task_text = re.sub(r"^.*\)\s*-\s*", "", task_text).strip()
        due_raw = (m.group("due") or "").strip()
        due_date = datetime.now().strftime("%m-%d-%Y") if due_raw.lower() == "none" else due_raw
        if not task_text:
            continue
        key = (task_text.casefold(), due_date)
        if key in seen:
            continue
        seen.add(key)
        out.append((task_text, due_date))
    return out


class ChatThread(QThread):
    response_signal = pyqtSignal(str)

    def __init__(self, chat_manager, message, session_id, history):
        super().__init__()
        self.chat_handler = chat_manager
        self.message = message
        self.session_id = session_id
        self.history = history

    def run(self):
        try:
            sid = str(self.session_id or "")

            # Dashboard/main chat and dedicated CoS chats share the same persistence layer.
            # Route through the main chat router so dashboard can use a safe local-fast lane,
            # while other CoS sessions keep the full CoS/Grok behavior.
            if sid.startswith("cos_") or sid == "main_session":
                try:
                    from core.main_chat_router import run_main_chat_turn
                    response = run_main_chat_turn(self.chat_handler, self.message, sid, self.history)
                    self.response_signal.emit(response or "")
                    return
                except Exception as e:
                    self.response_signal.emit(f"Error: {str(e)}")
                    return

            # Legacy Navi pipeline (non-CoS sessions)
            response = self.chat_handler.get_response(self.message, self.session_id, self.history)
            
            if response:
                print(f"DEBUG: Raw LLM response: '{response}'")
                
                # First try to parse the "Added..." format (processed by ResponseHandler)
                if "Added" in response and "due on" in response:
                    # Split the response into individual task entries
                    task_entries = response.replace("Added ", "").split(", ")
                    print(f"DEBUG: Found {len(task_entries)} task entries in 'Added' format: {task_entries}")
                    
                    for i, entry in enumerate(task_entries):
                        # More robust task parsing - handle different quote styles and formats
                        task_match = re.search(r"'([^']*)'|\"([^\"]*)\"", entry)
                        
                        # More flexible date parsing - look for "due on" followed by anything
                        date_match = re.search(r'due on (.+?)(?:\s*$|,|\s)', entry)
                        
                        if task_match:
                            # Get task text from either single or double quotes
                            task_text = task_match.group(1) if task_match.group(1) else task_match.group(2)
                            
                            # Handle date - if it's "unknown" or invalid, use today's date
                            if date_match:
                                due_date_raw = date_match.group(1).strip()
                                print(f"DEBUG: Raw date from LLM: '{due_date_raw}'")
                                
                                # Try to parse the date, fallback to today if it fails
                                try:
                                    if due_date_raw.lower() in ['unknown', 'none', 'n/a', '']:
                                        due_date = datetime.now().strftime('%m-%d-%Y')
                                        print(f"DEBUG: Using today's date for unknown date")
                                    else:
                                        # Try to parse various date formats
                                        from dateutil import parser
                                        parsed_date = parser.parse(due_date_raw, default=datetime.now())
                                        due_date = parsed_date.strftime('%m-%d-%Y')
                                        print(f"DEBUG: Parsed date: {due_date}")
                                except Exception as e:
                                    print(f"DEBUG: Date parsing failed, using today: {e}")
                                    due_date = datetime.now().strftime('%m-%d-%Y')
                            else:
                                # No date found, use today
                                due_date = datetime.now().strftime('%m-%d-%Y')
                                print(f"DEBUG: No date found, using today: {due_date}")
                            
                            print(f"DEBUG: Adding task {i+1}: '{task_text}' due {due_date}")
                            
                            # Emit the signal through the chat_manager (which is actually a ChatManager)
                            # The ChatManager will forward it to the interface
                            print(f"DEBUG: Emitting signal for task {i+1}")
                            self.chat_handler.task_added_signal.emit(task_text, due_date)
                            print(f"DEBUG: Signal emitted for task {i+1}")
                            
                            # Add a small delay between signal emissions to prevent race conditions
                            if i < len(task_entries) - 1:  # Don't delay after the last task
                                print(f"DEBUG: Waiting 100ms before next task...")
                                time.sleep(0.1)  # 100ms delay
                        else:
                            print(f"DEBUG: Failed to parse task entry: '{entry}'")
                            print(f"  task_match: {task_match}")
                            print(f"  date_match: {date_match}")
                            
                            # Try alternative parsing if the first attempt failed
                            if not task_match:
                                # Look for task text without quotes
                                alt_task_match = re.search(r'^(.+?)\s+due on', entry)
                                if alt_task_match and date_match:
                                    task_text = alt_task_match.group(1).strip()
                                    due_date = date_match.group(1)
                                    print(f"DEBUG: Alternative parsing successful: '{task_text}' due {due_date}")
                                    print(f"DEBUG: Emitting signal for alternative task {i+1}")
                                    self.chat_handler.task_added_signal.emit(task_text, due_date)
                                    print(f"DEBUG: Alternative signal emitted for task {i+1}")
                                    if i < len(task_entries) - 1:
                                        print(f"DEBUG: Waiting 100ms before next task...")
                                        time.sleep(0.1)
                
                # Fallback: Also try to parse ADD_TASK: format directly (in case ResponseHandler didn't process it)
                elif "ADD_TASK:" in response:
                    print(f"DEBUG: Found ADD_TASK: format in response, parsing directly...")
                    task_segments = [seg for seg in response.split("ADD_TASK:") if seg.strip()]
                    
                    for i, segment in enumerate(task_segments):
                        if "|" in segment:
                            task_info = segment.split("|", 1)
                            if len(task_info) == 2:
                                task_description = task_info[0].strip()
                                due_date_raw = task_info[1].strip()
                                
                                # Parse the date
                                try:
                                    if due_date_raw.lower() in ['unknown', 'none', 'n/a', '']:
                                        due_date = datetime.now().strftime('%m-%d-%Y')
                                    else:
                                        from dateutil import parser
                                        parsed_date = parser.parse(due_date_raw, default=datetime.now())
                                        due_date = parsed_date.strftime('%m-%d-%Y')
                                except Exception as e:
                                    print(f"DEBUG: Date parsing failed for ADD_TASK, using today: {e}")
                                    due_date = datetime.now().strftime('%m-%d-%Y')
                                
                                print(f"DEBUG: ADD_TASK parsing - task {i+1}: '{task_description}' due {due_date}")
                                self.chat_handler.task_added_signal.emit(task_description, due_date)
                                
                                if i < len(task_segments) - 1:
                                    time.sleep(0.1)
                else:
                    # Fallback: parse compact rich format lines:
                    # "- task text | MM-DD-YYYY | Business"
                    pipe_tasks = extract_pipe_tasks(response)
                    if pipe_tasks:
                        print(f"DEBUG: Found {len(pipe_tasks)} pipe-format task(s), emitting signals...")
                        for i, (task_text, due_date) in enumerate(pipe_tasks):
                            self.chat_handler.task_added_signal.emit(task_text, due_date)
                            if i < len(pipe_tasks) - 1:
                                time.sleep(0.1)
                
                self.response_signal.emit(response)
            else:
                self.response_signal.emit("Error: No response received.")
        except Exception as e:
            print(f"DEBUG: Error in ChatThread: {e}")
            self.response_signal.emit(f"Error: {str(e)}")

class ResponseHandler:
    def __init__(self, chat_display, user_input, send_button, chat_handler, session_id, conversation_history):
        self.chatDisplay = chat_display
        self.chatInput = user_input
        self.sendButton = send_button
        self.chat_handler = chat_handler
        self.session_id = session_id
        self.conversation_history = conversation_history

    @pyqtSlot(str)
    def onResponseReceived(self, response):
        # First try markdown processing for HTML-formatted content
        html_content = markdown.markdown(response, extensions=['extra'])
        
        # If the content doesn't contain any HTML tags, replace newlines with br tags
        if not any(tag in html_content for tag in ['<ul>', '<li>', '<p>', '<h']):
            html_content = response.replace('\n', '<br>')
        
        # Ensure the response ends with proper HTML to close any open lists
        if html_content.endswith('<li>'):
            html_content += '</li></ul>'  # Close last list item and the list itself
        elif '<li>' in html_content and not html_content.endswith('</ul>'):
            html_content += '</ul>'  # If there's an <li> but no closing </ul>
        
        self.chatDisplay.append(f'<div style="text-align: left;"><b>Navi:</b> {html_content}</div>')
        self.chatDisplay.append('<br>')  # Add spacing after Navi response
        self.conversation_history.append({"role": "assistant", "content": response})
        self.chat_handler.save_message(self.session_id, "assistant", response)
        self.sendButton.setEnabled(True)
        self.chatInput.setEnabled(True)
        self.chatInput.clear()
        self.chatInput.setFocus()
        notify_chat_response(self.chatDisplay, "Navi")

    def handle_task_added(self, task_text, due_date):
        if hasattr(self, 'window') and hasattr(self.window, 'addTaskFromChat'):
            self.window.addTaskFromChat(task_text, due_date)

def sendMessage(self):
    user_message = self.chatInput.text()
    if not user_message.strip():
        return

    self.chatDisplay.append(f'<div style="text-align: left;"><b>Me:</b> <i>{user_message}</i></div><br>')
    self.sendButton.setEnabled(False)
    self.chatInput.setEnabled(False)
    self.conversation_history.append({"role": "user", "content": user_message})
    self.chat_handler.save_message(self.session_id, "user", user_message)

    self.chatThread = ChatThread(self.chat_handler, user_message, self.session_id, self.conversation_history)
    self.chatThread.response_signal.connect(self.onResponseReceived)
    self.chatThread.start()

def saveChat(self):
        fileName, _ = QFileDialog.getSaveFileName(self, "Save Chat History", "", "JSON Files (*.json)")
        if fileName:
            with open(fileName, 'w') as file:
                json.dump(self.conversation_history, file)

def loadChat(self):
        fileName, _ = QFileDialog.getOpenFileName(self, "Load Chat History", "", "JSON Files (*.json)")
        if fileName:
            with open(fileName, 'r') as file:
                self.conversation_history = json.load(file)
                self.chatDisplay.clear()
                for entry in self.conversation_history:
                    role = "Me" if entry["role"] == "user" else "Navi"
                    if role == "Navi":
                        self.chatDisplay.append(f'<div style="text-align: left;"><b>{role}:</b> {entry["content"]}</div><br>')
                    else:
                        self.chatDisplay.append(f'<div style="text-align: left;"><b>{role}:</b> <i>{entry["content"]}</i></div><br>')
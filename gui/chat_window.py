from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QTextBrowser, QLineEdit, QPushButton, QFileDialog
from PyQt6.QtGui import QMouseEvent, QDesktopServices
import markdown
import re
import json

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
            print("[DEBUG] ChatThread: Starting response processing")
            # This step triggers the task addition logic
            response = self.chat_handler.get_response(self.message, self.session_id, self.history)
            print(f"[DEBUG] ChatThread: Got response: {response}")
            
            if response:
                if "Added" in response and "due on" in response:
                    print("[DEBUG] ChatThread: Task detected in response")
                    # Split the response into individual task entries
                    task_entries = response.replace("Added ", "").split(", ")
                    for entry in task_entries:
                        task_match = re.search(r"'([^']*)'", entry)
                        date_match = re.search(r'due on (\d{2}-\d{2}-\d{4})', entry)
                        print(f"[DEBUG] ChatThread: Task match: {task_match.group(1) if task_match else 'None'}")
                        print(f"[DEBUG] ChatThread: Date match: {date_match.group(1) if date_match else 'None'}")

                        if task_match and date_match:
                            task_text = task_match.group(1)
                            due_date = date_match.group(1)
                            print(f"[DEBUG] ChatThread: Emitting task signal with text: {task_text}, date: {due_date}")
                            # Emit the signal through the chat_manager instead of chat_handler
                            self.chat_handler.task_added_signal.emit(task_text, due_date)
                            print("[DEBUG] ChatThread: Task signal emitted")
                self.response_signal.emit(response)
            else:
                print("[DEBUG] ChatThread: No response received.")
                self.response_signal.emit("Error: No response received.")
        except Exception as e:
            print(f"[DEBUG] ChatThread: Exception occurred: {e}")
            self.response_signal.emit(f"Error: {str(e)}")

class ResponseHandler:
    def __init__(self, chat_display, user_input, send_button, chat_handler, session_id, conversation_history):
        self.chatDisplay = chat_display
        self.userInput = user_input
        self.sendButton = send_button
        self.chat_handler = chat_handler
        self.session_id = session_id
        self.conversation_history = conversation_history

    @pyqtSlot(str)
    def onResponseReceived(self, response):
        print("[DEBUG] onResponseReceived in chat_window.py called")
        print(f"[DEBUG] Raw response: {response}")
        
        # First try markdown processing for HTML-formatted content
        print("[DEBUG] Attempting markdown processing")
        html_content = markdown.markdown(response, extensions=['extra'])
        print(f"[DEBUG] After markdown: {html_content}")
        
        # If the content doesn't contain any HTML tags, replace newlines with br tags
        if not any(tag in html_content for tag in ['<ul>', '<li>', '<p>', '<h']):
            print("[DEBUG] No HTML tags found, replacing newlines with br tags")
            html_content = response.replace('\n', '<br>')
        else:
            print("[DEBUG] HTML tags found, keeping markdown processing")
        
        # Ensure the response ends with proper HTML to close any open lists
        if html_content.endswith('<li>'):
            print("[DEBUG] Adding closing list tags")
            html_content += '</li></ul>'  # Close last list item and the list itself
        elif '<li>' in html_content and not html_content.endswith('</ul>'):
            print("[DEBUG] Adding closing ul tag")
            html_content += '</ul>'  # If there's an <li> but no closing </ul>
        
        print(f"[DEBUG] Final HTML content: {html_content}")
        self.chatDisplay.append(f"<b>Navi: {html_content}")
        self.conversation_history.append({"role": "assistant", "content": response})
        self.chat_handler.save_message(self.session_id, "assistant", response)
        self.sendButton.setEnabled(True)
        self.userInput.setEnabled(True)
        self.userInput.clear()
        self.userInput.setFocus()

def sendMessage(self):
    user_message = self.userInput.text()
    if not user_message.strip():
        return

    self.chatDisplay.append(f"<b>You:</b> {user_message}")
    self.sendButton.setEnabled(False)
    self.userInput.setEnabled(False)
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
                    role = "You" if entry["role"] == "user" else "Navi"
                    self.chatDisplay.append(f"<b>{role}:</b> {entry['content']}")
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QTextBrowser, QLineEdit, QPushButton, QFileDialog
from PyQt6.QtGui import QMouseEvent, QDesktopServices
import markdown
import re
import json

class ChatThread(QThread):
    response_signal = pyqtSignal(str)

    def __init__(self, chatHandler, message, session_id, history):
        super().__init__()
        self.chat_handler = chatHandler
        self.message = message
        self.session_id = session_id
        self.history = history

    def run(self):
        try:
            # This step triggers the task addition logic
            response = self.chat_handler.get_response(self.message, self.session_id, self.history)
            if response:
                if "I've added the task" in response:
                    task_match = re.search(r"'([^']*)'", response)
                    date_match = re.search(r'due on (\d{2}-\d{2}-\d{4})', response)

                    if task_match and date_match:
                        task_text = task_match.group(1)
                        due_date = date_match.group(1)

                        # Ensure task_added_signal is emitted from ChatThread, not ChatHandler
                        self.chat_handler.task_added_signal.emit(task_text, due_date)  # Emit from ChatThread instance directly
                self.response_signal.emit(response)
            else:
                print("ChatThread: No response received.")  # Debug statement
                self.response_signal.emit("Error: No response received.")
        except Exception as e:
            print(f"ChatThread: Exception occurred: {e}")
            self.response_signal.emit(f"Error: {str(e)}")

@pyqtSlot(str)
def onResponseReceived(self, response):

    html_content = markdown.markdown(response, extensions=['extra'])
    
    # Ensure the response ends with proper HTML to close any open lists
    if html_content.endswith('<li>'):
        html_content += '</li></ul>'  # Close last list item and the list itself
    elif '<li>' in html_content and not html_content.endswith('</ul>'):
        html_content += '</ul>'  # If there's an <li> but no closing </ul>
    print(f"HTML content: {html_content}")
    self.chatDisplay.append(f"<b>Navi:</b> {html_content}")
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
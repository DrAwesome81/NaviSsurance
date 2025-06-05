import sqlite3
import logging
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QSplashScreen, 
                            QTextBrowser, QLineEdit, QPushButton, QListWidget, QDateEdit, QTableWidget, 
                            QTableWidgetItem, QCheckBox, QComboBox, QLabel, QSplitter, QTextEdit, QDialog, QDialogButtonBox, QHeaderView, QMessageBox, QFileDialog, QMenu)
from PyQt6.QtCore import Qt, QDate, QTimer, pyqtSlot, QUrl
from PyQt6.QtGui import QPixmap, QAction, QDesktopServices, QColor
from core.db import DatabaseManager
from gui.chat_window import ChatThread, ResponseHandler, sendMessage, saveChat, loadChat
from gui.todo_list import TodoList
from core.chat import ChatManager
import os
import json
from anthropic import Anthropic, AnthropicError
from anthropic.types import ToolUseBlock
from datetime import datetime
from PyQt6.QtWidgets import QApplication
import PyPDF2
from bs4 import BeautifulSoup
import requests
import markdown

logger = logging.getLogger(__name__)

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QVBoxLayout()
        
        # Style for the dialog
        self.setStyleSheet("""
            QDialog {
                background-color: rgb(27, 28, 30);
                color: white;
            }
            QTextEdit {
                background-color: rgba(27, 28, 30, 0.8);
                color: white;
                border: 1px solid rgba(253, 98, 98, 0.8);
            }
            QLabel {
                color: white;
            }
        """)
        
        self.system_message_input = QTextEdit(self)
        
        # Load existing system message from config
        config_path = 'C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/config/lead_gen_config.json'
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                self.system_message_input.setText(config.get('system_message', ''))
            except Exception as e:
                logger.error(f"Error loading system message: {e}")
                self.system_message_input.setText("")  # Default empty if load fails
        
        layout.addWidget(QLabel("Claude System Message:"))
        layout.addWidget(self.system_message_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.setStyleSheet("""
            QPushButton {
                background-color: rgba(253, 98, 98, 0.8);
                color: white;
                border: none;
                padding: 5px 15px;
            }
            QPushButton:hover {
                background-color: rgba(253, 98, 98, 1);
            }
        """)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)

class ChatWindow(QMainWindow):
    def __init__(self):
        logger.info("Initializing ChatWindow...")
        super().__init__()
        
        # Create data directory if it doesn't exist
        self.data_dir = 'C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/data'
        os.makedirs(self.data_dir, exist_ok=True)
        
        logger.info("Loading splash screen...")
        pixmap = QPixmap("assets/logo v2.png")
        self.splash = QSplashScreen(pixmap)
        self.splash.show()
        QTimer.singleShot(2000, self.show_main_window)

        logger.info("Initializing chat handler...")
        self.chat_handler = ChatManager(self)
        self.session_id = f"SESSION_GUI_{hash(str(self))}"
        self.conversation_history = []
        
        logger.info("Initializing todo list...")
        self.todoList = QListWidget(self)
        self.todo_list = TodoList(self)
        self.todo_list.loadTasksFromDB()  # Load existing tasks
        
        logger.info("Setting up UI...")
        self.initUI()
        
        # Initialize response handler
        self.response_handler = ResponseHandler(self.chatDisplay, self.userInput, self.sendButton, self.chat_handler, self.session_id, self.conversation_history)
        
        # Connect the task signal
        self.chat_handler.task_added_signal.connect(self.addTaskFromChat)
        
        logger.info("ChatWindow initialization complete")

    def show_main_window(self):
        logger.info("Showing main window...")
        self.splash.finish(self)
        self.show()
        logger.info("Main window shown")

    def search_leads(self):
        """Run Claude API search for leads based on system message."""
        try:
            # Load system message from config
            config_path = 'C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/config/lead_gen_config.json'
            if not os.path.exists(config_path):
                logger.error("Lead gen config not found.")
                return
            with open(config_path, 'r') as f:
                config = json.load(f)
            user_system_message = config.get('system_message', '')
            
            # If no user system message, use default context
            if not user_system_message:
                user_system_message = "You are a lead generation assistant for a medical device regulatory consulting firm. Focus on companies in the AI SaMD and/or IVD/LDT space."

            # Append required format and verification instructions
            system_message = f"""{user_system_message}

IMPORTANT: When processing search results:
1. Verify each company's current status and leadership team
2. Include a clear rationale for why each lead is relevant
3. Generate a personalized LinkedIn message for each lead based on your research
4. Return results as a JSON array with the following fields for each lead:
   - name: Full name of the key decision maker
   - company: Company name
   - title: Their current title
   - rationale: Why this person/company is a good lead
   - linkedin_url: Their LinkedIn profile URL (if found)
   - message: A personalized LinkedIn message referencing their specific regulatory needs and how NaviSure can help
Only include leads that have been verified through the search results.

"""

            # Initialize Claude client
            api_key = os.getenv('ANTHROPIC_API_KEY', '')
            if not api_key:
                logger.error("Anthropic API key not found.")
                return
            client = Anthropic(api_key=api_key)

            # Start the conversation with the system message
            messages = [
                {
                    "role": "user",
                    "content": user_system_message
                }
            ]

            # Make the initial API call
            try:
                response = client.messages.create(
                    model="claude-3-7-sonnet-20250219",
                    max_tokens=10000,
                    system=system_message,
                    messages=messages,
                    tools=[{
                        "type": "web_search_20250305",
                        "name": "web_search"
                    }]
                )
            except AnthropicError as e:
                if "overloaded_error" in str(e):
                    logger.error("API is currently overloaded. Please try again in a few minutes.")
                    QMessageBox.warning(self, "API Overloaded", "The API is currently experiencing high load. Please try again in 5-10 minutes.")
                    return
                raise e

            # Log the initial response
            logger.info("Initial Claude API Response:")
            logger.info(f"Response type: {type(response)}")
            logger.info(f"Response content: {response.content}")

            # Write raw response to file for inspection
            response_file = os.path.join(self.data_dir, 'claude_response.txt')
            with open(response_file, 'w', encoding='utf-8') as f:
                f.write("Response type: " + str(type(response)) + "\n\n")
                f.write("Response content:\n")
                for block in response.content:
                    if hasattr(block, 'text'):
                        f.write(block.text + "\n")
                    else:
                        f.write(str(block) + "\n")
            logger.info(f"Raw response written to {response_file}")

            # Add the response to the conversation
            messages.append({
                "role": "assistant",
                "content": response.content
            })

            # Check if there's a tool use in the response
            if response.content and any(isinstance(block, ToolUseBlock) for block in response.content):
                # Find the tool use block
                tool_use = next(block for block in response.content if isinstance(block, ToolUseBlock))
                
                # Make another API call to get the final response after tool use
                response = client.messages.create(
                    model="claude-3-7-sonnet-20250219",
                    max_tokens=1000,
                    system=system_message,
                    messages=messages
                )

                # Log the final response
                logger.info("Final Claude API Response:")
                logger.info(f"Response type: {type(response)}")
                logger.info(f"Response content: {response.content}")

            # Write raw response to file for inspection
            response_file = os.path.join(self.data_dir, 'claude_response.txt')
            with open(response_file, 'w', encoding='utf-8') as f:
                f.write("Response type: " + str(type(response)) + "\n\n")
                f.write("Response content:\n")
                for block in response.content:
                    if hasattr(block, 'text'):
                        f.write(block.text + "\n")
                    else:
                        f.write(str(block) + "\n")
            logger.info(f"Raw response written to {response_file}")

            # Try to find JSON array in the response
            json_str = None
            for block in response.content:
                if hasattr(block, 'text'):
                    text = block.text.strip()
                    logger.info(f"Processing block text: {text}")
                    # Look for JSON array pattern
                    start_idx = text.find('[')
                    end_idx = text.rfind(']') + 1
                    if start_idx != -1 and end_idx > 0:
                        json_str = text[start_idx:end_idx]
                        logger.info(f"Found JSON string: {json_str}")
                        break

            if json_str:
                try:
                    # Clean up the JSON string
                    json_str = json_str.strip()
                    # Remove any markdown code block markers
                    json_str = json_str.replace('```json', '').replace('```', '')
                    logger.info(f"Cleaned JSON string: {json_str}")
                    
                    new_leads = json.loads(json_str)
                    logger.info(f"Parsed leads: {new_leads}")
                    
                    if isinstance(new_leads, list):
                        # Successfully parsed JSON array
                        logger.info(f"Successfully parsed JSON array with {len(new_leads)} leads")
                        
                        # Load existing leads
                        leads_file = os.path.join(self.data_dir, 'leads.json')
                        existing_leads = []
                        if os.path.exists(leads_file):
                            with open(leads_file, 'r') as f:
                                existing_leads = json.load(f)
                        
                        # Create a set of existing lead identifiers (name + company)
                        existing_identifiers = {(lead['name'], lead['company']) for lead in existing_leads}
                        
                        # Add new leads to the beginning of the list, avoiding duplicates
                        for lead in new_leads:
                            if not all(k in lead for k in ['name', 'company', 'title', 'rationale', 'message']):
                                logger.warning(f"Skipping lead with missing required fields: {lead}")
                                continue
                            lead['contacted'] = False
                            lead['contact_date'] = None
                            lead['linkedin_url'] = lead.get('linkedin_url', '')
                            
                            # Check for duplicates
                            if (lead['name'], lead['company']) not in existing_identifiers:
                                existing_leads.insert(0, lead)
                                existing_identifiers.add((lead['name'], lead['company']))
                                logger.info(f"Added new lead: {lead['name']} from {lead['company']}")
                        
                        # Save updated leads
                        with open(leads_file, 'w') as f:
                            json.dump(existing_leads, f, indent=2)
                        
                        # Update table
                        self.update_leads_table(existing_leads)
                        logger.info(f"Successfully loaded {len(new_leads)} new leads")
                        return
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON: {e}")
                    logger.error(f"Raw JSON string: {json_str}")
            else:
                logger.error("No JSON array found in response blocks")
                logger.error(f"Raw response blocks: {[block.text if hasattr(block, 'text') else str(block) for block in response.content]}")
                
        except AnthropicError as e:
            logger.error(f"Claude API error: {e}")
        except Exception as e:
            logger.error(f"Search leads error: {e}")

    def update_leads_table(self, leads):
        """Update the leads table with the provided leads data."""
        self.leadsTable.setRowCount(len(leads))
        for row, lead in enumerate(leads):
            # Name (as hyperlink if LinkedIn URL exists)
            name_item = QTableWidgetItem(lead.get('name', ''))
            if lead.get('linkedin_url'):
                name_item.setData(Qt.ItemDataRole.UserRole, lead['linkedin_url'])
                name_item.setData(Qt.ItemDataRole.UserRole + 1, "linkedin")
                name_item.setForeground(QColor("#0077B5"))  # LinkedIn blue
                font = name_item.font()
                font.setUnderline(True)
                name_item.setFont(font)
            self.leadsTable.setItem(row, 0, name_item)
            
            # Company
            self.leadsTable.setItem(row, 1, QTableWidgetItem(lead.get('company', '')))
            # Title
            self.leadsTable.setItem(row, 2, QTableWidgetItem(lead.get('title', '')))
            
            # Contacted checkbox
            contacted_cb = QCheckBox()
            contacted_cb.setChecked(lead.get('contacted', False))
            contacted_cb.stateChanged.connect(lambda state, r=row: self.on_contacted_changed(r, state))
            self.leadsTable.setCellWidget(row, 3, contacted_cb)
            
            # Contact date
            contact_date = lead.get('contact_date')
            date_item = QTableWidgetItem(contact_date if contact_date else '')
            self.leadsTable.setItem(row, 4, date_item)
            
            # Message button
            message_button = QPushButton("View Message")
            message_button.clicked.connect(lambda _, r=row: self.generate_message(r))
            self.leadsTable.setCellWidget(row, 5, message_button)
            
            # Delete button
            delete_button = QPushButton("Delete")
            delete_button.clicked.connect(lambda _, r=row: self.delete_lead(r))
            self.leadsTable.setCellWidget(row, 6, delete_button)
            
            # Rationale (with view button)
            view_rationale_button = QPushButton("View")
            view_rationale_button.clicked.connect(lambda _, r=row: self.show_rationale(r))
            self.leadsTable.setCellWidget(row, 7, view_rationale_button)
            
        # Connect cell click event for LinkedIn links
        self.leadsTable.cellClicked.connect(self.handle_cell_click)

    def handle_cell_click(self, row, column):
        """Handle cell clicks, specifically for LinkedIn links."""
        if column == 0:  # Name column
            item = self.leadsTable.item(row, column)
            if item and item.data(Qt.ItemDataRole.UserRole + 1) == "linkedin":
                url = item.data(Qt.ItemDataRole.UserRole)
                if url:
                    # Disconnect the signal temporarily to prevent multiple triggers
                    self.leadsTable.cellClicked.disconnect(self.handle_cell_click)
                    QDesktopServices.openUrl(QUrl(url))
                    # Reconnect the signal
                    self.leadsTable.cellClicked.connect(self.handle_cell_click)

    def show_rationale(self, row):
        """Show the rationale in a popup dialog."""
        leads_file = os.path.join(self.data_dir, 'leads.json')
        if os.path.exists(leads_file):
            with open(leads_file, 'r') as f:
                leads = json.load(f)
            
            if 0 <= row < len(leads):
                rationale = leads[row].get('rationale', 'No rationale available')
                
                dialog = QDialog(self)
                dialog.setWindowTitle("Lead Rationale")
                dialog.setMinimumWidth(500)
                dialog.setMinimumHeight(300)
                dialog.setStyleSheet("""
                    QDialog {
                        background-color: rgb(27, 28, 30);
                        color: white;
                    }
                    QTextEdit {
                        background-color: rgba(27, 28, 30, 0.8);
                        color: white;
                        border: 1px solid rgba(253, 98, 98, 0.8);
                        padding: 10px;
                    }
                """)
                
                layout = QVBoxLayout()
                text_edit = QTextEdit()
                text_edit.setPlainText(rationale)
                text_edit.setReadOnly(True)
                layout.addWidget(text_edit)
                
                close_button = QPushButton("Close")
                close_button.setStyleSheet("""
                    QPushButton {
                        background-color: rgba(253, 98, 98, 0.8);
                        color: white;
                        border: none;
                        padding: 5px 15px;
                    }
                    QPushButton:hover {
                        background-color: rgba(253, 98, 98, 1);
                    }
                """)
                close_button.clicked.connect(dialog.accept)
                layout.addWidget(close_button)
                
                dialog.setLayout(layout)
                dialog.exec()

    def on_contacted_changed(self, row, state):
        """Handle contact checkbox state change."""
        leads_file = os.path.join(self.data_dir, 'leads.json')
        if os.path.exists(leads_file):
            with open(leads_file, 'r') as f:
                leads = json.load(f)
            
            if 0 <= row < len(leads):
                leads[row]['contacted'] = state == Qt.CheckState.Checked.value
                leads[row]['contact_date'] = datetime.now().strftime('%Y-%m-%d') if state == Qt.CheckState.Checked.value else None
                
                with open(leads_file, 'w') as f:
                    json.dump(leads, f, indent=2)
                
                # Update contact date in table
                self.leadsTable.setItem(row, 4, QTableWidgetItem(leads[row]['contact_date'] or ''))

    def delete_lead(self, row):
        """Delete a lead after confirmation."""
        reply = QMessageBox.question(
            self, 'Confirm Deletion',
            'Are you sure you want to delete this lead?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            leads_file = os.path.join(self.data_dir, 'leads.json')
            if os.path.exists(leads_file):
                with open(leads_file, 'r') as f:
                    leads = json.load(f)
                
                if 0 <= row < len(leads):
                    leads.pop(row)
                    
                    with open(leads_file, 'w') as f:
                        json.dump(leads, f, indent=2)
                    
                    self.update_leads_table(leads)

    def generate_message(self, row):
        """Show the pre-generated message for the lead in the given row."""
        try:
            leads_file = os.path.join(self.data_dir, 'leads.json')
            if not os.path.exists(leads_file):
                logger.error("Leads file not found")
                return
                
            with open(leads_file, 'r') as f:
                leads = json.load(f)
            
            if row >= len(leads):
                logger.error(f"Lead at row {row} not found in leads file")
                return
                
            lead = leads[row]
            message = lead.get('message', 'No message available')
            
            # Show message in a dialog
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Message for {lead['name']}")
            dialog.setStyleSheet("""
                QDialog {
                    background-color: rgb(27, 28, 30);
                    color: white;
                }
                QTextEdit {
                    background-color: rgba(27, 28, 30, 0.8);
                    color: white;
                    border: 1px solid rgba(253, 98, 98, 0.8);
                }
            """)
            layout = QVBoxLayout()
            text_edit = QTextEdit()
            text_edit.setPlainText(message)
            text_edit.setReadOnly(True)
            layout.addWidget(text_edit)
            
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.setStyleSheet("""
                QPushButton {
                    background-color: rgba(253, 98, 98, 0.8);
                    color: white;
                    border: none;
                    padding: 5px 15px;
                }
                QPushButton:hover {
                    background-color: rgba(253, 98, 98, 1);
                }
            """)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            
            dialog.setLayout(layout)
            dialog.exec()
            
        except Exception as e:
            logger.error(f"Show message error: {e}")
            QMessageBox.critical(self, "Error", f"Failed to show message: {str(e)}")

    def open_settings(self):
        """Open settings dialog to edit Claude system message."""
        dialog = SettingsDialog(self)
        if dialog.exec():
            try:
                system_message = dialog.system_message_input.toPlainText()
                config = {"system_message": system_message}
                config_path = 'C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/config/lead_gen_config.json'
                with open(config_path, 'w') as f:
                    json.dump(config, f)
                logger.info("Lead gen settings saved.")
            except Exception as e:
                logger.error(f"Save settings error: {e}")

    # Existing methods (unchanged)
    def refresh_leads(self):
        print("Weekly lead refresh TBD (Grok 3 API pending)")

    def save_document(self):
        # Example: Save to crm.py with schema {lead: str, issue: str, action: str}
        # Use DatabaseManager to insert results
        pass

    def start_recording(self):
        import sounddevice as sd
        import scipy.io.wavfile as wavfile
        import os
        import time

        self.recordButton.setEnabled(False)
        self.stopButton.setEnabled(True)
        print("Starting recording...")
        self.recording = True
        self.sample_rate = 44100
        self.audio_data = []
        self.recording_start_time = time.time()
        
        def callback(indata, frames, time, status):
            if status:
                print(status)
            if self.recording:
                self.audio_data.extend(indata.copy())

        self.stream = sd.InputStream(samplerate=self.sample_rate, channels=1, callback=callback)
        self.stream.start()

    def stop_recording(self):
        import scipy.io.wavfile as wavfile
        import os
        import numpy as np

        self.recording = False
        self.stream.stop()
        self.stream.close()
        self.stopButton.setEnabled(False)
        self.transcribeButton.setEnabled(True)
        print("Recording stopped")
        
        self.audio_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_recording.wav")
        audio_array = np.array(self.audio_data)
        wavfile.write(self.audio_file_path, self.sample_rate, audio_array)
        print(f"Audio saved to {self.audio_file_path}")

    def select_file(self):
        from PyQt6.QtWidgets import QFileDialog
        import os

        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Select File", 
            "", 
            "Media Files (*.mp4 *.m4v *.mp3 *.wav *.m4a);;All Files (*)"
        )
        
        if file_path:
            self.selected_file_path = file_path
            self.transcribeButton.setEnabled(True)
            self.meetingTranscript.setText(f"Selected file: {file_path}")
            print(f"Selected file: {file_path}")
            
            if file_path.lower().endswith(('.mp4', '.m4v')):
                self.meetingTranscript.append("Extracting audio from video file...")
                self.extract_audio_from_video(file_path)
            else:
                self.selected_audio_path = file_path
                self.meetingTranscript.append("Audio file selected. Click 'Generate Transcript' to process.")
        else:
            self.meetingTranscript.setText("No file selected.")
            print("No file selected")

    def extract_audio_from_video(self, video_path):
        import os
        import subprocess
        import math

        try:
            temp_audio_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio.mp3")
            print(f"Extracting audio to {temp_audio_path}")
            self.meetingTranscript.append(f"Saving temporary audio to {temp_audio_path}")

            subprocess.run(['ffmpeg', '-i', video_path, '-vn', '-acodec', 'libmp3lame', '-ab', '128k', temp_audio_path], check=True)
            print("Audio extraction completed")
            self.meetingTranscript.append("Audio extraction completed. Checking file size...")

            file_size_mb = os.path.getsize(temp_audio_path) / (1024 * 1024)
            if file_size_mb > 25:
                self.meetingTranscript.append(f"Audio file size ({file_size_mb:.2f} MB) exceeds 25 MB limit. Compressing...")
                compressed_audio_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio_compressed.mp3")
                subprocess.run(['ffmpeg', '-i', temp_audio_path, '-acodec', 'libmp3lame', '-ab', '64k', compressed_audio_path], check=True)
                os.remove(temp_audio_path)
                temp_audio_path = compressed_audio_path
                self.meetingTranscript.append("Audio compression completed. Ready for transcription.")
            else:
                self.meetingTranscript.append(f"Audio file size ({file_size_mb:.2f} MB) is within limit. Ready for transcription.")

            self.selected_audio_path = temp_audio_path
            print(f"Audio file ready for transcription: {temp_audio_path}")
        except Exception as e:
            self.meetingTranscript.setText(f"Error extracting audio: {str(e)}")
            self.transcribeButton.setEnabled(False)
            print(f"Audio extraction error: {e}")

    def transcribe_meeting(self):
        import os
        import requests
        import time
        from datetime import datetime, timedelta

        self.transcribeButton.setEnabled(False)
        print("Transcribing audio...")
        
        api_key = os.getenv('ASSEMBLYAI_API_KEY', '')
        if not api_key:
            self.meetingTranscript.setText("Error: AssemblyAI API key not found.")
            self.saveTranscriptButton.setEnabled(False)
            return

        try:
            if hasattr(self, 'selected_audio_path') and os.path.exists(self.selected_audio_path):
                self.meetingTranscript.setText("Uploading audio file...")
                print(f"Transcribing audio file: {self.selected_audio_path}")
                
                headers = {'authorization': api_key}
                with open(self.selected_audio_path, 'rb') as f:
                    response = requests.post('https://api.assemblyai.com/v2/upload', headers=headers, data=f)
                upload_url = response.json()['upload_url']
                self.meetingTranscript.append("File uploaded successfully. Starting transcription...")
                
                endpoint = "https://api.assemblyai.com/v2/transcript"
                json = {
                    "audio_url": upload_url,
                    "speaker_labels": True,
                    "speakers_expected": 16,
                    "auto_highlights": True,
                    "iab_categories": True,
                    "auto_chapters": True
                }
                headers = {"authorization": api_key, "content-type": "application/json"}
                response = requests.post(endpoint, json=json, headers=headers)
                transcript_id = response.json()['id']
                self.meetingTranscript.append(f"Transcription job started. ID: {transcript_id}")
                
                start_time = datetime.now()
                timeout = timedelta(minutes=10)
                last_status = None
                last_progress = 0
                
                while True:
                    if datetime.now() - start_time > timeout:
                        raise TimeoutError("Transcription timed out after 10 minutes")
                    
                    response = requests.get(f"{endpoint}/{transcript_id}", headers=headers)
                    status = response.json()['status']
                    progress = response.json().get('confidence', 0) or 0
                    
                    if status != last_status or (progress > 0 and progress != last_progress):
                        status_message = f"Status: {status}"
                        if progress > 0:
                            status_message += f" (Progress: {progress:.1%})"
                        self.meetingTranscript.append(status_message)
                        last_status = status
                        last_progress = progress
                    
                    if status == 'completed':
                        transcript = response.json()['text']
                        utterances = response.json()['utterances']
                        formatted_transcript = ["Note: Speakers who only spoke briefly may not be detected separately.",
                                             "----------------------------------------\n"]
                        for utterance in utterances:
                            speaker = f"Speaker {utterance['speaker']}"
                            text = utterance['text']
                            formatted_transcript.append(f"{speaker}: {text}")
                        final_transcript = "\n\n".join(formatted_transcript)
                        self.meetingTranscript.setText(final_transcript)
                        self.saveTranscriptButton.setEnabled(True)
                        print("Transcription completed")
                        self.meetingTranscript.append("\n\nTranscription completed.")
                        break
                    elif status == 'error':
                        error_msg = response.json().get('error', 'Unknown error')
                        raise Exception(f"Transcription failed: {error_msg}")
                    elif status == 'queued':
                        time.sleep(5)
                    else:
                        time.sleep(3)
            else:
                self.meetingTranscript.setText("Error: No file found for transcription.")
                self.saveTranscriptButton.setEnabled(False)
        except TimeoutError as e:
            self.meetingTranscript.setText(f"Error: {str(e)}\nThe transcription is still processing.")
            self.transcribeButton.setEnabled(True)
            print(f"Transcription timeout: {e}")
        except Exception as e:
            self.meetingTranscript.setText(f"Error during transcription: {str(e)}")
            self.transcribeButton.setEnabled(True)
            print(f"Transcription error: {e}")
        finally:
            self.saveTranscriptButton.setEnabled(False)

    def save_transcript(self):
        from PyQt6.QtWidgets import QFileDialog
        import os
        import time

        transcript_text = self.meetingTranscript.toPlainText()
        if not transcript_text or transcript_text.startswith("Error"):
            print("No valid transcript to save")
            return

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        default_filename = f"transcript_{timestamp}.txt"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Transcript", default_filename, "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(transcript_text)
                print(f"Transcript saved to {file_path}")
                self.saveTranscriptButton.setEnabled(False)
                self.meetingTranscript.append(f"<i>Transcript saved to {file_path}</i>")
            except Exception as e:
                print(f"Error saving transcript: {e}")
                self.meetingTranscript.append(f"<i>Error saving transcript: {e}</i>")

    def sendMessage(self):
        user_message = self.userInput.text()
        if not user_message.strip():
            return
        self.chatDisplay.append(f"<b>You:</b> {user_message}<br><br>")
        self.sendButton.setEnabled(False)
        self.userInput.setEnabled(False)
        self.conversation_history.append({"role": "user", "content": user_message})
        self.chat_handler.save_message(self.session_id, "user", user_message)
        self.chatThread = ChatThread(self.chat_handler, user_message, self.session_id, self.conversation_history)
        self.chatThread.response_signal.connect(self.onResponseReceived)
        self.chatThread.start()
        self.chatThread.finished.connect(lambda: print("Thread finished"))

    def addTaskFromChat(self, task_text, due_date):
        print(f"[DEBUG] ChatWindow: Signal received with task: {task_text}, date: {due_date}")
        self.todo_list.addTaskFromChat(task_text, due_date)
        print("[DEBUG] ChatWindow: Called todo_list.addTaskFromChat")

    def addTask(self):
        self.todo_list.addTask()    

    @pyqtSlot(str)  
    def onResponseReceived(self, response):
        print("[DEBUG] onResponseReceived in interface.py called")
        print(f"[DEBUG] Response received in interface: {response}")
        
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
        self.chatDisplay.append(f"<b>Navi:</b> {html_content}")
        self.conversation_history.append({"role": "assistant", "content": response})
        self.chat_handler.save_message(self.session_id, "assistant", response)
        self.sendButton.setEnabled(True)
        self.userInput.setEnabled(True)
        self.userInput.clear()
        self.userInput.setFocus()

    def archiveCompletedTasks(self):
        self.todo_list.archiveCompletedTasks()

    def loadStylesheet(self, filename):
        try:
            with open(filename, "r") as f:
                self.setStyleSheet(f.read())
        except FileNotFoundError:
            print(f"Stylesheet '{filename}' not found.")
        except Exception as e:
            print(f"Error loading stylesheet: {e}")

    def closeEvent(self, event):
        super().closeEvent(event)

    def initUI(self):
        self.setWindowTitle('NaviSsurance')
        self.setGeometry(300, 300, 1600, 900)  # Increased window size for Compliance Tab
        
        # Center the window on the screen
        screen = QApplication.primaryScreen().geometry()
        window_size = self.geometry()
        x = (screen.width() - window_size.width()) // 2
        y = (screen.height() - window_size.height()) // 2
        self.move(x, y)
        
        self.loadStylesheet("styles.qss")

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Left side - Chat Panel
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        self.chatDisplay = QTextBrowser(self)
        self.chatDisplay.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.chatDisplay.setOpenExternalLinks(True)
        self.chatDisplay.setReadOnly(True)
        chat_layout.addWidget(self.chatDisplay)
        chat_input_layout = QHBoxLayout()
        self.userInput = QLineEdit(self)
        self.userInput.setPlaceholderText("Type your message here...")
        self.userInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.userInput.returnPressed.connect(self.sendMessage)
        chat_input_layout.addWidget(self.userInput)
        self.sendButton = QPushButton("Send", self)
        self.sendButton.setStyleSheet("""
            QPushButton {
                background-color: rgba(253, 98, 98, 0.8);
            }
            QPushButton:hover {
                background-color: rgba(253, 98, 98, 1.0);
            }
        """)
        self.sendButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sendButton.clicked.connect(self.sendMessage)
        chat_input_layout.addWidget(self.sendButton)
        chat_layout.addLayout(chat_input_layout)
        main_layout.addWidget(chat_widget, stretch=30)

        # Right side - Tab Widget
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabBar::tab { color: white; background-color: rgb(20, 20, 22); } "
                          "QTabBar::tab:selected { background-color: rgba(253, 98, 98, 0.8); }")
        main_layout.addWidget(tabs, stretch=70)

        # Tasks Tab
        tasks_tab = QWidget()
        tasks_layout = QVBoxLayout(tasks_tab)
        self.todoList.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        self.todoList.setSpacing(5)  # Add consistent spacing between list items
        tasks_layout.addWidget(self.todoList)
        add_task_layout = QHBoxLayout()
        self.taskInput = QLineEdit(self)
        self.taskInput.setPlaceholderText("Enter a task...")
        self.taskInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        add_task_layout.addWidget(self.taskInput)
        self.dueDateInput = QDateEdit(self)
        self.dueDateInput.setCalendarPopup(True)
        self.dueDateInput.setDate(QDate.currentDate())
        self.dueDateInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        add_task_layout.addWidget(self.dueDateInput)
        self.addTaskButton = QPushButton("Add Task", self)
        self.addTaskButton.clicked.connect(self.addTask)
        self.addTaskButton.setStyleSheet("""
            QPushButton {
                background-color: rgba(253, 98, 98, 0.8);
            }
            QPushButton:hover {
                background-color: rgba(253, 98, 98, 1.0);
            }
        """)
        self.addTaskButton.setCursor(Qt.CursorShape.PointingHandCursor)
        add_task_layout.addWidget(self.addTaskButton)
        tasks_layout.addLayout(add_task_layout)
        self.archiveButton = QPushButton("Archive Completed Tasks", self)
        self.archiveButton.clicked.connect(self.archiveCompletedTasks)
        self.archiveButton.setStyleSheet("""
            QPushButton {
                background-color: rgba(253, 98, 98, 0.8);
            }
            QPushButton:hover {
                background-color: rgba(253, 98, 98, 1.0);
            }
        """)
        self.archiveButton.setCursor(Qt.CursorShape.PointingHandCursor)
        tasks_layout.addWidget(self.archiveButton)
        tabs.addTab(tasks_tab, "Tasks")

        # Leads Tab (modified)
        leads_tab = QWidget()
        leads_layout = QVBoxLayout(leads_tab)
        leads_button_layout = QHBoxLayout()
        self.settingsButton = QPushButton("Settings", self)
        self.settingsButton.clicked.connect(self.open_settings)
        self.settingsButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        leads_button_layout.addWidget(self.settingsButton)
        self.runSearchButton = QPushButton("Run Search", self)
        self.runSearchButton.clicked.connect(self.search_leads)
        self.runSearchButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        leads_button_layout.addWidget(self.runSearchButton)
        leads_layout.addLayout(leads_button_layout)
        
        # Configure the leads table
        self.leadsTable = QTableWidget(0, 8)  # Added column for rationale
        self.leadsTable.setHorizontalHeaderLabels([
            "Name", "Company", "Title", "Contacted", "Contact Date", "Message", "Delete", "Rationale"
        ])
        self.leadsTable.setStyleSheet("""
            QTableWidget {
                background-color: rgba(27, 28, 30, 0.8);
                color: white;
                gridline-color: rgba(253, 98, 98, 0.3);
            }
            QTableWidget::item {
                padding: 5px;
            }
            QHeaderView::section {
                background-color: rgba(253, 98, 98, 0.8);
                color: white;
                padding: 5px;
                border: none;
            }
            QPushButton {
                background-color: rgba(253, 98, 98, 0.8);
                color: white;
                border: none;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: rgba(253, 98, 98, 1);
            }
            QCheckBox {
                color: white;
            }
            QTableWidget::item[linkedin="true"] {
                color: #0077B5;
                text-decoration: underline;
                cursor: pointer;
            }
            QTableWidget::item[linkedin="true"]:hover {
                color: #005582;
            }
        """)
        
        # Set column widths and behavior
        self.leadsTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.leadsTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Company
        self.leadsTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Title
        self.leadsTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # Contacted
        self.leadsTable.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # Contact Date
        self.leadsTable.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)  # Message
        self.leadsTable.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)  # Delete
        self.leadsTable.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)  # Rationale
        
        self.leadsTable.setColumnWidth(3, 80)  # Contacted
        self.leadsTable.setColumnWidth(4, 100)  # Contact Date
        self.leadsTable.setColumnWidth(5, 120)  # Message
        self.leadsTable.setColumnWidth(6, 80)  # Delete
        
        # Enable word wrap for cells
        self.leadsTable.setWordWrap(True)
        
        leads_layout.addWidget(self.leadsTable)
        tabs.addTab(leads_tab, "Leads")
        
        # Load existing leads
        leads_file = os.path.join(self.data_dir, 'leads.json')
        if os.path.exists(leads_file):
            try:
                with open(leads_file, 'r') as f:
                    leads = json.load(f)
                self.update_leads_table(leads)
                logger.info(f"Loaded {len(leads)} existing leads")
            except Exception as e:
                logger.error(f"Error loading leads: {e}")

        # Docs Tab
        docs_tab = QWidget()
        docs_layout = QHBoxLayout(docs_tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        docs_layout.addWidget(splitter)

        # Column 1: Information Reference
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_label = QLabel("Information Reference")
        info_label.setStyleSheet("color: white;")
        info_layout.addWidget(info_label)

        self.info_url_input = QLineEdit()
        self.info_url_input.setPlaceholderText("Enter URL for reference information")
        self.info_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.info_url_input.returnPressed.connect(self.add_info_url)
        info_layout.addWidget(self.info_url_input)

        info_upload_btn = QPushButton("Upload Reference")
        info_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        info_upload_btn.clicked.connect(self.upload_info_file)
        info_layout.addWidget(info_upload_btn)

        self.info_list = QListWidget()
        self.info_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.info_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.info_list.customContextMenuRequested.connect(self.show_info_context_menu)
        info_layout.addWidget(self.info_list)
        splitter.addWidget(info_widget)

        # Column 2: Document Reference
        doc_widget = QWidget()
        doc_layout = QVBoxLayout(doc_widget)
        doc_label = QLabel("Document Reference")
        doc_label.setStyleSheet("color: white;")
        doc_layout.addWidget(doc_label)

        self.doc_url_input = QLineEdit()
        self.doc_url_input.setPlaceholderText("Enter URL for document template")
        self.doc_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.doc_url_input.returnPressed.connect(self.add_doc_url)
        doc_layout.addWidget(self.doc_url_input)

        doc_upload_btn = QPushButton("Upload Document")
        doc_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        doc_upload_btn.clicked.connect(self.upload_doc_file)
        doc_layout.addWidget(doc_upload_btn)

        self.doc_list = QListWidget()
        self.doc_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.doc_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.doc_list.customContextMenuRequested.connect(self.show_doc_context_menu)
        doc_layout.addWidget(self.doc_list)
        splitter.addWidget(doc_widget)

        # Column 3: Generated Document
        output_widget = QWidget()
        output_layout = QVBoxLayout(output_widget)
        output_label = QLabel("Generated Document")
        output_label.setStyleSheet("color: white;")
        output_layout.addWidget(output_label)

        self.doc_output = QTextEdit()
        self.doc_output.setReadOnly(True)
        self.doc_output.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        output_layout.addWidget(self.doc_output)

        generate_btn = QPushButton("Generate Document")
        generate_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        generate_btn.clicked.connect(self.generate_document)
        output_layout.addWidget(generate_btn)

        save_btn = QPushButton("Save Document")
        save_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        save_btn.clicked.connect(self.save_generated_document)
        output_layout.addWidget(save_btn)

        splitter.addWidget(output_widget)
        tabs.addTab(docs_tab, "Docs")

        # Meetings Tab (unchanged)
        meetings_tab = QWidget()
        meetings_layout = QVBoxLayout(meetings_tab)
        self.recordButton = QPushButton("Start Recording", self)
        self.recordButton.clicked.connect(self.start_recording)
        self.recordButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        meetings_layout.addWidget(self.recordButton)
        self.stopButton = QPushButton("Stop Recording", self)
        self.stopButton.clicked.connect(self.stop_recording)
        self.stopButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.stopButton.setEnabled(False)
        meetings_layout.addWidget(self.stopButton)
        self.transcribeButton = QPushButton("Generate Transcript", self)
        self.transcribeButton.clicked.connect(self.transcribe_meeting)
        self.transcribeButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.transcribeButton.setEnabled(False)
        meetings_layout.addWidget(self.transcribeButton)
        self.selectFileButton = QPushButton("Load File", self)
        self.selectFileButton.clicked.connect(self.select_file)
        self.selectFileButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        meetings_layout.addWidget(self.selectFileButton)
        self.meetingTranscript = QTextEdit(self)
        self.meetingTranscript.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.meetingTranscript.setReadOnly(True)
        meetings_layout.addWidget(self.meetingTranscript)
        self.saveTranscriptButton = QPushButton("Save Transcript", self)
        self.saveTranscriptButton.clicked.connect(self.save_transcript)
        self.saveTranscriptButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.saveTranscriptButton.setEnabled(False)
        meetings_layout.addWidget(self.saveTranscriptButton)
        tabs.addTab(meetings_tab, "Meetings")

        # Compliance Tab (moved to last position)
        compliance_tab = QWidget()
        self.setup_compliance_tab(compliance_tab)
        tabs.addTab(compliance_tab, "Compliance")

    def setup_compliance_tab(self, tab):
        layout = QHBoxLayout(tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Column 1: Reference Documents
        ref_widget = QWidget()
        ref_layout = QVBoxLayout(ref_widget)
        ref_label = QLabel("Reference Documents (Regulations/Standards)")
        ref_label.setStyleSheet("color: white;")
        ref_layout.addWidget(ref_label)

        self.ref_url_input = QLineEdit()
        self.ref_url_input.setPlaceholderText("Enter URL (e.g., https://www.ecfr.gov/21-cfr-820.3)")
        self.ref_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.ref_url_input.returnPressed.connect(self.add_ref_url)
        ref_layout.addWidget(self.ref_url_input)

        ref_upload_btn = QPushButton("Upload Reference")
        ref_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        ref_upload_btn.clicked.connect(self.upload_ref_file)
        ref_layout.addWidget(ref_upload_btn)

        self.ref_list = QListWidget()
        self.ref_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        # Add context menu for removing items
        self.ref_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ref_list.customContextMenuRequested.connect(self.show_ref_context_menu)
        ref_layout.addWidget(self.ref_list)
        splitter.addWidget(ref_widget)

        # Column 2: Documents to Assess
        assess_widget = QWidget()
        assess_layout = QVBoxLayout(assess_widget)
        assess_label = QLabel("Documents to Assess (e.g., SOPs)")
        assess_label.setStyleSheet("color: white;")
        assess_layout.addWidget(assess_label)

        self.assess_url_input = QLineEdit()
        self.assess_url_input.setPlaceholderText("Enter URL (e.g., https://navisure.com/sop.pdf)")
        self.assess_url_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        self.assess_url_input.returnPressed.connect(self.add_assess_url)
        assess_layout.addWidget(self.assess_url_input)

        assess_upload_btn = QPushButton("Upload Document")
        assess_upload_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        assess_upload_btn.clicked.connect(self.upload_assess_file)
        assess_layout.addWidget(assess_upload_btn)

        self.assess_list = QListWidget()
        self.assess_list.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        # Add context menu for removing items
        self.assess_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.assess_list.customContextMenuRequested.connect(self.show_assess_context_menu)
        assess_layout.addWidget(self.assess_list)
        splitter.addWidget(assess_widget)

        # Column 3: Results
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_label = QLabel("Compliance Results")
        results_label.setStyleSheet("color: white;")
        results_layout.addWidget(results_label)

        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        results_layout.addWidget(self.results_text)

        run_btn = QPushButton("Run Compliance Check")
        run_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        run_btn.clicked.connect(self.run_compliance_check)
        results_layout.addWidget(run_btn)

        save_btn = QPushButton("Save Report")
        save_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        save_btn.clicked.connect(self.save_compliance_report)
        results_layout.addWidget(save_btn)

        crm_btn = QPushButton("Link to CRM")
        crm_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        crm_btn.clicked.connect(self.link_to_crm)
        results_layout.addWidget(crm_btn)
        splitter.addWidget(results_widget)

        # Load existing documents
        self.load_document_lists()

    def add_ref_url(self):
        url = self.ref_url_input.text().strip()
        if url:
            self.ref_list.addItem(url)
            self.save_document_lists()
            self.ref_url_input.clear()

    def upload_ref_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Reference File", "", "Documents (*.pdf *.docx *.txt);;All Files (*)"
        )
        if file_path:
            self.ref_list.addItem(file_path)
            self.save_document_lists()

    def add_assess_url(self):
        url = self.assess_url_input.text().strip()
        if url:
            self.assess_list.addItem(url)
            self.save_document_lists()
            self.assess_url_input.clear()

    def upload_assess_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Document to Assess", "", "Documents (*.pdf *.docx *.txt);;All Files (*)"
        )
        if file_path:
            self.assess_list.addItem(file_path)
            self.save_document_lists()

    def save_document_lists(self):
        """Save the current state of document lists to persist them."""
        ref_items = [self.ref_list.item(i).text() for i in range(self.ref_list.count())]
        assess_items = [self.assess_list.item(i).text() for i in range(self.assess_list.count())]
        data = {
            "reference_documents": ref_items,
            "assessed_documents": assess_items
        }
        config_path = os.path.join(self.data_dir, "compliance_documents.json")
        with open(config_path, "w") as f:
            json.dump(data, f, indent=2)

    def load_document_lists(self):
        """Load saved document lists when the application starts."""
        config_path = os.path.join(self.data_dir, "compliance_documents.json")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = json.load(f)
            for item in data.get("reference_documents", []):
                self.ref_list.addItem(item)
            for item in data.get("assessed_documents", []):
                self.assess_list.addItem(item)

    def show_ref_context_menu(self, position):
        """Show context menu for reference documents list."""
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.ref_list.mapToGlobal(position))
        if action == remove_action:
            item = self.ref_list.itemAt(position)
            if item:
                self.ref_list.takeItem(self.ref_list.row(item))
                self.save_document_lists()

    def show_assess_context_menu(self, position):
        """Show context menu for assessment documents list."""
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.assess_list.mapToGlobal(position))
        if action == remove_action:
            item = self.assess_list.itemAt(position)
            if item:
                self.assess_list.takeItem(self.assess_list.row(item))
                self.save_document_lists()

    def run_compliance_check(self):
        ref_items = [self.ref_list.item(i).text() for i in range(self.ref_list.count())]
        assess_items = [self.assess_list.item(i).text() for i in range(self.assess_list.count())]
        if not ref_items or not assess_items:
            self.results_text.setText("Error: Please add at least one reference and one assessed document.")
            return

        self.results_text.setText("Running compliance check...")
        documents = []
        for item in ref_items + assess_items:
            if item.startswith("http"):
                try:
                    response = requests.get(item, timeout=10)
                    soup = BeautifulSoup(response.text, "html.parser")
                    text = soup.get_text()
                    documents.append({"type": "url", "content": text, "source": item})
                except Exception as e:
                    self.results_text.setText(f"Error fetching URL {item}: {str(e)}")
                    return
            else:
                try:
                    with open(item, "rb") as f:
                        pdf = PyPDF2.PdfReader(f)
                        text = "".join(page.extract_text() for page in pdf.pages)
                        documents.append({"type": "file", "content": text, "source": item})
                except Exception as e:
                    self.results_text.setText(f"Error reading file {item}: {str(e)}")
                    return

        ref_docs = [d for d in documents if d["source"] in ref_items]
        assess_docs = [d for d in documents if d["source"] in assess_items]
        prompt = (
            f"Compare the following assessed documents against the reference documents. "
            f"Identify non-compliant sections or areas for improvement, citing specific clauses. "
            f"Return a JSON array: [{{\"section\": str, \"issue\": str, \"fix\": str, \"reference\": str}}].\n\n"
            f"Reference Documents:\n"
        )
        
        # Add reference document content
        for doc in ref_docs:
            prompt += f"\nDocument: {doc['source']}\nContent:\n{doc['content']}\n"
        
        prompt += f"\nAssessed Documents:\n"
        
        # Add assessed document content
        for doc in assess_docs:
            prompt += f"\nDocument: {doc['source']}\nContent:\n{doc['content']}\n"
        
        prompt += "\nIMPORTANT: Do not perform any Dropbox searches. Only analyze the documents provided above."

        # Call Grok via chat.py
        response = self.chat_handler.get_response(prompt, self.session_id, self.conversation_history)
        try:
            # Original JSON parsing code - commented out
            # results = json.loads(response)
            # if isinstance(results, dict):
            #     if 'non_compliances' in results:
            #         results = results['non_compliances']
            #     elif 'issues' in results:
            #         results = results['issues']
            # if not isinstance(results, list):
            #     raise ValueError("Response is not a JSON array")

            # New JSON extraction and parsing code
            json_str = None
            # Look for JSON array pattern
            start_idx = response.find('[')
            end_idx = response.rfind(']') + 1
            if start_idx != -1 and end_idx > 0:
                json_str = response[start_idx:end_idx]
                logger.info(f"Found JSON string: {json_str}")
                
                # Clean up the JSON string
                json_str = json_str.strip()
                # Remove any markdown code block markers
                json_str = json_str.replace('```json', '').replace('```', '')
                logger.info(f"Cleaned JSON string: {json_str}")
                
                results = json.loads(json_str)
                logger.info(f"Parsed results: {results}")
                
                if not isinstance(results, list):
                    raise ValueError("Response is not a JSON array")
            else:
                raise ValueError("No JSON array found in response")
            
            formatted_results = []
            for r in results:
                formatted_results.append(
                    f"<b>Section {r['section']}:</b> {r['issue']}<br>"
                    f"<b>Fix:</b> {r['fix']}<br>"
                    f"<b>Reference:</b> {r['reference']}<br><br>"
                )
            self.results_text.setHtml("".join(formatted_results))
        except Exception as e:
            self.results_text.setText(f"Error processing results: {str(e)}")
            logger.error(f"Error processing results: {e}")
            logger.error(f"Raw response: {response}")

    def save_compliance_report(self):
        if not self.results_text.toPlainText():
            self.results_text.setText("No results to save.")
            return
        timestamp = QDate.currentDate().toString("yyyyMMdd")
        default_filename = f"compliance_report_{timestamp}.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Compliance Report", default_filename, "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            results = []
            for i in range(self.results_text.document().blockCount()):
                block = self.results_text.document().findBlockByNumber(i).text()
                if block:
                    results.append(block)
            try:
                with open(file_path, "w") as f:
                    json.dump(results, f, indent=2)
                self.results_text.append(f"Saved to {file_path}")
            except Exception as e:
                self.results_text.setText(f"Error saving report: {str(e)}")

    def link_to_crm(self):
        # Placeholder: Integrate with crm.py (SQLite)
        self.results_text.append("CRM integration TBD: Save compliance issues to leads.")
        # Example: Save to crm.py with schema {lead: str, issue: str, action: str}
        # Use DatabaseManager to insert results

    def add_info_url(self):
        url = self.info_url_input.text().strip()
        if url:
            self.info_list.addItem(url)
            self.info_url_input.clear()

    def add_doc_url(self):
        url = self.doc_url_input.text().strip()
        if url:
            self.doc_list.addItem(url)
            self.doc_url_input.clear()

    def upload_info_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Information Reference File",
            "",
            "All Files (*.*)"
        )
        if file_name:
            self.info_list.addItem(file_name)

    def upload_doc_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Document Template",
            "",
            "All Files (*.*)"
        )
        if file_name:
            self.doc_list.addItem(file_name)

    def show_info_context_menu(self, position):
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.info_list.mapToGlobal(position))
        if action == remove_action:
            item = self.info_list.itemAt(position)
            if item:
                self.info_list.takeItem(self.info_list.row(item))

    def show_doc_context_menu(self, position):
        menu = QMenu()
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.doc_list.mapToGlobal(position))
        if action == remove_action:
            item = self.doc_list.itemAt(position)
            if item:
                self.doc_list.takeItem(self.doc_list.row(item))

    def generate_document(self):
        # Placeholder for document generation
        self.doc_output.setText("Document generation will be implemented here.")

    def save_generated_document(self):
        if not self.doc_output.toPlainText():
            QMessageBox.warning(self, "Warning", "No document to save.")
            return

        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Save Generated Document",
            "",
            "Text Files (*.txt);;All Files (*.*)"
        )
        if file_name:
            try:
                with open(file_name, 'w') as f:
                    f.write(self.doc_output.toPlainText())
                QMessageBox.information(self, "Success", "Document saved successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save document: {str(e)}")
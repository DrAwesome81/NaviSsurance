import sqlite3
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QSplashScreen, 
                            QTextBrowser, QLineEdit, QPushButton, QListWidget, QDateEdit, QTableWidget, 
                            QTableWidgetItem, QCheckBox, QComboBox, QLabel, QSplitter, QTextEdit)
from PyQt6.QtCore import Qt, QDate, QTimer, pyqtSlot
from PyQt6.QtGui import QPixmap, QAction
from core.db import DatabaseManager
from gui.chat_window import ChatThread, onResponseReceived, sendMessage, saveChat, loadChat
from gui.todo_list import TodoList
from core.chat import ChatManager

class ChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        pixmap = QPixmap("assets/logo v2.png")
        self.splash = QSplashScreen(pixmap)
        self.splash.show()
        QTimer.singleShot(2000, self.show_main_window)

        self.chat_handler = ChatManager(self)
        self.session_id = f"SESSION_GUI_{hash(str(self))}"
        self.conversation_history = []
        self.todoList = QListWidget(self)
        self.todo_list = TodoList(self)
        self.initUI()
        self.chat_handler.start_briefing()

    def show_main_window(self):
        self.splash.finish(self)
        self.show()

    # Define all methods before initUI
    def search_leads(self):
        print("Lead search TBD")

    def refresh_leads(self):
        print("Weekly lead refresh TBD (Grok 3 API pending)")

    def generate_document(self):
        print("Doc generation TBD")

    def save_document(self):
        print("Doc save TBD")

    def start_recording(self):
        """
        Start recording audio using sounddevice.
        Saves to a temporary WAV file.
        """
        import sounddevice as sd
        import scipy.io.wavfile as wavfile
        import os
        import time

        self.recordButton.setEnabled(False)
        self.stopButton.setEnabled(True)
        print("Starting recording...")
        self.recording = True
        self.sample_rate = 44100  # Hz
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
        """
        Stop recording audio and save to a temporary WAV file.
        """
        import scipy.io.wavfile as wavfile
        import os
        import numpy as np

        self.recording = False
        self.stream.stop()
        self.stream.close()
        self.stopButton.setEnabled(False)
        self.transcribeButton.setEnabled(True)
        print("Recording stopped")
        
        # Save the recorded audio to a temporary file
        self.audio_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_recording.wav")
        audio_array = np.array(self.audio_data)
        wavfile.write(self.audio_file_path, self.sample_rate, audio_array)
        print(f"Audio saved to {self.audio_file_path}")

    def select_file(self):
        """
        Open a file dialog to select a video or audio file for transcription.
        Extract audio if the file is a video format.
        """
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
            
            # Check if it's a video file
            if file_path.lower().endswith(('.mp4', '.m4v')):
                self.meetingTranscript.append("Extracting audio from video file...")
                self.extract_audio_from_video(file_path)
            else:
                # For audio files, just set the path
                self.selected_audio_path = file_path
                self.meetingTranscript.append("Audio file selected. Click 'Generate Transcript' to process.")
        else:
            self.meetingTranscript.setText("No file selected.")
            print("No file selected")

    def extract_audio_from_video(self, video_path):
        """
        Extract audio from a video file using ffmpeg directly and save as a temporary MP3 file.
        If the audio file is larger than 25MB, compress it to fit within the limit.
        """
        import os
        import subprocess
        import math

        try:
            # Define temporary audio file path
            temp_audio_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio.mp3")
            print(f"Extracting audio to {temp_audio_path}")
            self.meetingTranscript.append(f"Saving temporary audio to {temp_audio_path}")

            # Use ffmpeg to extract audio directly
            subprocess.run(['ffmpeg', '-i', video_path, '-vn', '-acodec', 'libmp3lame', '-ab', '128k', temp_audio_path], check=True)
            print("Audio extraction completed")
            self.meetingTranscript.append("Audio extraction completed. Checking file size...")

            # Check file size (25MB limit for OpenAI Whisper API)
            file_size_mb = os.path.getsize(temp_audio_path) / (1024 * 1024)
            if file_size_mb > 25:
                self.meetingTranscript.append(f"Audio file size ({file_size_mb:.2f} MB) exceeds 25 MB limit. Compressing...")
                # Compress the audio file to fit within the limit
                compressed_audio_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio_compressed.mp3")
                subprocess.run(['ffmpeg', '-i', temp_audio_path, '-acodec', 'libmp3lame', '-ab', '64k', compressed_audio_path], check=True)
                os.remove(temp_audio_path)  # Remove the original file
                temp_audio_path = compressed_audio_path  # Use the compressed file
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
        """
        Transcribe the recorded audio file or a selected audio/video file using AssemblyAI's API.
        Display the transcript with speaker separation in the meetingTranscript text area.
        """
        import os
        import requests
        import time
        from datetime import datetime, timedelta

        self.transcribeButton.setEnabled(False)
        print("Transcribing audio...")
        
        # Load AssemblyAI API key from environment
        api_key = os.getenv('ASSEMBLYAI_API_KEY', '')
        if not api_key:
            self.meetingTranscript.setText("Error: AssemblyAI API key not found. Please set ASSEMBLYAI_API_KEY in config/.env.")
            self.saveTranscriptButton.setEnabled(False)
            return

        try:
            # Check if we have an audio file to transcribe
            if hasattr(self, 'selected_audio_path') and os.path.exists(self.selected_audio_path):
                self.meetingTranscript.setText("Uploading audio file...")
                print(f"Transcribing audio file: {self.selected_audio_path}")
                
                # Upload the audio file
                headers = {'authorization': api_key}
                with open(self.selected_audio_path, 'rb') as f:
                    response = requests.post('https://api.assemblyai.com/v2/upload',
                                          headers=headers,
                                          data=f)
                upload_url = response.json()['upload_url']
                self.meetingTranscript.append("File uploaded successfully. Starting transcription...")
                
                # Start transcription with speaker diarization
                endpoint = "https://api.assemblyai.com/v2/transcript"
                json = {
                    "audio_url": upload_url,
                    "speaker_labels": True,
                    "speakers_expected": 16,  # Increased to handle up to 16 speakers
                    "auto_highlights": True,  # Added to help identify important parts
                    "iab_categories": True,  # Added to help with context
                    "auto_chapters": True    # Added to help with structure
                }
                headers = {
                    "authorization": api_key,
                    "content-type": "application/json"
                }
                response = requests.post(endpoint, json=json, headers=headers)
                transcript_id = response.json()['id']
                self.meetingTranscript.append(f"Transcription job started. ID: {transcript_id}")
                
                # Poll for completion with timeout
                self.meetingTranscript.append("Processing audio...")
                start_time = datetime.now()
                timeout = timedelta(minutes=10)  # Increased timeout to 10 minutes
                last_status = None
                last_progress = 0
                
                while True:
                    # Check for timeout
                    if datetime.now() - start_time > timeout:
                        raise TimeoutError("Transcription timed out after 10 minutes")
                    
                    response = requests.get(f"{endpoint}/{transcript_id}", headers=headers)
                    status = response.json()['status']
                    progress = response.json().get('confidence', 0) or 0  # Ensure progress is never None
                    
                    # Update status message if it changed
                    if status != last_status or (progress > 0 and progress != last_progress):
                        status_message = f"Status: {status}"
                        if progress > 0:
                            status_message += f" (Progress: {progress:.1%})"
                        self.meetingTranscript.append(status_message)
                        last_status = status
                        last_progress = progress
                    
                    if status == 'completed':
                        # Format transcript with speaker labels
                        transcript = response.json()['text']
                        utterances = response.json()['utterances']
                        formatted_transcript = []
                        
                        # Add a note about speaker detection
                        formatted_transcript.append("Note: Speakers who only spoke briefly may not be detected separately.")
                        formatted_transcript.append("----------------------------------------\n")
                        
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
                        time.sleep(5)  # Longer wait for queued status
                    else:
                        time.sleep(3)  # Normal polling interval
                        
            else:
                self.meetingTranscript.setText("Error: No file found for transcription.")
                self.saveTranscriptButton.setEnabled(False)
                return
        except TimeoutError as e:
            self.meetingTranscript.setText(f"Error: {str(e)}\nThe transcription is still processing on AssemblyAI's servers.\nYou can try again later to retrieve the completed transcript.")
            self.transcribeButton.setEnabled(True)
            print(f"Transcription timeout: {e}")
        except Exception as e:
            self.meetingTranscript.setText(f"Error during transcription: {str(e)}")
            self.transcribeButton.setEnabled(True)
            print(f"Transcription error: {e}")
        finally:
            self.saveTranscriptButton.setEnabled(False)

    def save_transcript(self):
        """
        Save the transcript text to a file using a file dialog.
        """
        from PyQt6.QtWidgets import QFileDialog
        import os
        import time

        transcript_text = self.meetingTranscript.toPlainText()
        if not transcript_text or transcript_text.startswith("Error"):
            print("No valid transcript to save")
            return

        # Get the default filename with timestamp
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        default_filename = f"transcript_{timestamp}.txt"
        
        # Open file dialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Transcript",
            default_filename,
            "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:  # If user didn't cancel
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
        print(f"Signal received: {task_text} due {due_date}")
        self.todo_list.addTaskFromChat(task_text, due_date)

    def addTask(self):
        self.todo_list.addTask()    

    @pyqtSlot(str)  
    def onResponseReceived(self, response):
        self.chatDisplay.append(f"<b>Navi:</b> {response}<br><br>")
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
        self.setGeometry(300, 300, 1200, 700)
        self.loadStylesheet("styles.qss")

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        self.chat_handler.task_added_signal.connect(self.addTaskFromChat)

        # Tab widget with white text
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabBar::tab { color: white; background-color: rgb(20, 20, 22); } "
                          "QTabBar::tab:selected { background-color: rgba(253, 98, 98, 0.8); }")
        main_layout.addWidget(tabs)

        # Chat & Tasks Tab (Splitter)
        chat_tasks_tab = QWidget()
        chat_tasks_layout = QVBoxLayout(chat_tasks_tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Chat Panel
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
        self.sendButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.sendButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sendButton.clicked.connect(self.sendMessage)
        chat_input_layout.addWidget(self.sendButton)
        chat_layout.addLayout(chat_input_layout)
        splitter.addWidget(chat_widget)

        # Tasks Sidebar
        tasks_widget = QWidget()
        tasks_layout = QVBoxLayout(tasks_widget)
        self.todoList.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
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
        self.addTaskButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.addTaskButton.setCursor(Qt.CursorShape.PointingHandCursor)
        add_task_layout.addWidget(self.addTaskButton)
        tasks_layout.addLayout(add_task_layout)
        self.archiveButton = QPushButton("Archive Completed Tasks", self)
        self.archiveButton.clicked.connect(self.archiveCompletedTasks)
        self.archiveButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.archiveButton.setCursor(Qt.CursorShape.PointingHandCursor)
        tasks_layout.addWidget(self.archiveButton)
        splitter.addWidget(tasks_widget)
        
        splitter.setSizes([700, 300])
        chat_tasks_layout.addWidget(splitter)
        tabs.addTab(chat_tasks_tab, "Chat & Tasks")

        # Leads Tab
        leads_tab = QWidget()
        leads_layout = QVBoxLayout(leads_tab)
        leads_search_layout = QHBoxLayout()
        self.leadSearchInput = QLineEdit(self)
        self.leadSearchInput.setPlaceholderText("Search leads (e.g., 'AI startup')...")
        self.leadSearchInput.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        leads_search_layout.addWidget(self.leadSearchInput)
        self.leadSearchButton = QPushButton("Search Leads", self)
        self.leadSearchButton.clicked.connect(self.search_leads)
        self.leadSearchButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        leads_search_layout.addWidget(self.leadSearchButton)
        self.refreshLeadsButton = QPushButton("Refresh Leads (Weekly)", self)
        self.refreshLeadsButton.clicked.connect(self.refresh_leads)  # Now defined
        self.refreshLeadsButton.setStyleSheet("background-color: rgba(253, 98, 98, 0.8);")
        self.refreshLeadsButton.setEnabled(False)
        leads_search_layout.addWidget(self.refreshLeadsButton)
        leads_layout.addLayout(leads_search_layout)
        self.leadFilters = QWidget()
        filters_layout = QHBoxLayout(self.leadFilters)
        self.emailFilter = QCheckBox("Emails", checked=True)
        self.dropboxFilter = QCheckBox("Dropbox", checked=True)
        self.unrepliedFilter = QCheckBox("Unreplied")
        filters_layout.addWidget(self.emailFilter)
        filters_layout.addWidget(self.dropboxFilter)
        filters_layout.addWidget(self.unrepliedFilter)
        leads_layout.addWidget(self.leadFilters)
        self.leadsTable = QTableWidget(0, 4)
        self.leadsTable.setHorizontalHeaderLabels(["Source", "Sender/Filename", "Snippet", "Action"])
        self.leadsTable.setStyleSheet("background-color: rgba(27, 28, 30, 0.8);")
        leads_layout.addWidget(self.leadsTable)
        tabs.addTab(leads_tab, "Leads")

        # Docs Tab (Placeholder)
        docs_tab = QWidget()
        docs_layout = QVBoxLayout(docs_tab)
        docs_layout.addWidget(QLabel("Document generation coming soon!"))
        tabs.addTab(docs_tab, "Docs")

        # Meetings Tab
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
        print(f"Signal received: {task_text} due {due_date}")
        self.todo_list.addTaskFromChat(task_text, due_date)

    def addTask(self):
        self.todo_list.addTask()    

    @pyqtSlot(str)  
    def onResponseReceived(self, response):
        self.chatDisplay.append(f"<b>Navi:</b> {response}<br><br>")
        self.conversation_history.append({"role": "assistant", "content": response})
        self.chat_handler.save_message(self.session_id, "assistant", response)
        self.sendButton.setEnabled(True)
        self.userInput.setEnabled(True)
        self.userInput.clear()
        self.userInput.setFocus()

    def on_index_button(self): # Placeholder for when we figure out where to put the button
        from core.index_dropbox import manual_index
        from core.api import get_dropbox_client
        dbx = get_dropbox_client()
        manual_index(dbx)
        self.chatDisplay.append("<b>Navi:</b> Dropbox index updated—fresh data inbound!")   
    
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
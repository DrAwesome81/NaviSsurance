from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QTextEdit, QFileDialog, QMessageBox
from PyQt6.QtCore import Qt
import os
import requests
from PyQt6.QtCore import QTimer

class MeetingsTab(QWidget):
    def __init__(self, chat_handler):
        super().__init__()
        self.chat_handler = chat_handler
        self.recording = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        self.recordButton = QPushButton("Start Recording", self)
        self.recordButton.clicked.connect(self.start_recording)
        layout.addWidget(self.recordButton)
        
        self.stopButton = QPushButton("Stop Recording", self)
        self.stopButton.clicked.connect(self.stop_recording)
        self.stopButton.setEnabled(False)
        layout.addWidget(self.stopButton)
        
        self.transcribeButton = QPushButton("Generate Transcript", self)
        self.transcribeButton.clicked.connect(self.transcribe_meeting)
        self.transcribeButton.setEnabled(False)
        layout.addWidget(self.transcribeButton)
        
        self.selectFileButton = QPushButton("Load File", self)
        self.selectFileButton.clicked.connect(self.select_file)
        layout.addWidget(self.selectFileButton)
        
        self.meetingTranscript = QTextEdit(self)
        self.meetingTranscript.setReadOnly(True)
        layout.addWidget(self.meetingTranscript)
        
        self.saveTranscriptButton = QPushButton("Save Transcript", self)
        self.saveTranscriptButton.clicked.connect(self.save_transcript)
        self.saveTranscriptButton.setEnabled(False)
        layout.addWidget(self.saveTranscriptButton)

    def start_recording(self):
        # Placeholder for starting recording
        self.recording = True
        self.recordButton.setEnabled(False)
        self.stopButton.setEnabled(True)
        self.meetingTranscript.setPlainText("Recording started...")

    def stop_recording(self):
        # Placeholder for stopping recording
        self.recording = False
        self.recordButton.setEnabled(True)
        self.stopButton.setEnabled(False)
        self.transcribeButton.setEnabled(True)
        self.meetingTranscript.append("Recording stopped. Ready to transcribe.")

    def transcribe_meeting(self):
        # Placeholder for transcription logic using AssemblyAI or similar
        self.meetingTranscript.setPlainText("Transcription in progress...")
        # Simulate transcription
        QTimer.singleShot(2000, lambda: self.meetingTranscript.setPlainText("Sample transcript: This is a test meeting transcription."))
        self.saveTranscriptButton.setEnabled(True)

    def select_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Select Audio File", "", "Audio Files (*.mp3 *.wav);;All Files (*)"
        )
        if file_name:
            self.transcribeButton.setEnabled(True)
            self.meetingTranscript.setPlainText(f"File selected: {file_name}")

    def save_transcript(self):
        if not self.meetingTranscript.toPlainText():
            QMessageBox.warning(self, "Warning", "No transcript to save.")
            return
        
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Save Transcript", "transcript.txt", "Text Files (*.txt);;All Files (*)"
        )
        if file_name:
            with open(file_name, 'w') as f:
                f.write(self.meetingTranscript.toPlainText())
            QMessageBox.information(self, "Success", "Transcript saved successfully.")

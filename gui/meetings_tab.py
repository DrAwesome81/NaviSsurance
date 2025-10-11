from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QTextEdit, QFileDialog, QMessageBox
from PyQt6.QtCore import Qt
import os
import requests
from PyQt6.QtCore import QTimer
import numpy as np

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
        print("Recording TBD")
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
        print("Stop recording TBD")
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

    def transcribe_meeting(self):
        print("Transcription TBD")
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

    def save_transcript(self):
        print("Transcript save TBD")
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

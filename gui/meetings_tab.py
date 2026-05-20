from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QFileDialog,
    QMessageBox,
    QDialog,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QDateEdit,
    QDialogButtonBox,
    QLabel,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate
import logging
import json
import os
import requests
import numpy as np
from datetime import datetime
from docx import Document

from core.task_extract import SuggestedTask, parse_suggested_tasks
from gui.task_import_dialog import TaskImportDialog

logger = logging.getLogger(__name__)


def _safe_filename_part(value: str, *, fallback: str = "unknown") -> str:
    v = (value or "").strip()
    if not v:
        return fallback
    keep = []
    for ch in v:
        if ch.isalnum() or ch in ("-", "_", " "):
            keep.append(ch)
    out = "".join(keep).strip().replace(" ", "_")
    return out[:80] if out else fallback


class MeetingMetadataDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        default_date: QDate | None = None,
        db=None,
        initial_client_id: int | None = None,
        initial_cos_project_id: int | None = None,
    ):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Label meeting")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.date_edit = QDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(default_date or QDate.currentDate())

        self.with_edit = QLineEdit(self)
        self.with_edit.setPlaceholderText("e.g., Acme — John Smith (Reg Affairs)")

        self.notes_edit = QTextEdit(self)
        self.notes_edit.setPlaceholderText("Key decisions, action items, follow-ups…")
        self.notes_edit.setMinimumHeight(140)

        self.client_combo = QComboBox(self)
        self.client_combo.addItem("None", None)
        self.project_combo = QComboBox(self)
        self.project_combo.addItem("None", None)

        try:
            clients = db.clients_list(active_only=True) if db is not None and hasattr(db, "clients_list") else []
        except Exception:
            clients = []
        try:
            from core.intel import IntelService
            isvc = IntelService(db)
        except Exception:
            isvc = None
        for client in clients:
            try:
                client_id = int(client.get("id"))
                client_name = str(client.get("name") or "").strip()
            except Exception:
                continue
            if isvc:
                try:
                    w_list = [w for w in (isvc.list_watch_topics() or []) if getattr(w, 'client_id', None) == client_id]
                    has_r = bool(isvc.list_findings(client_id=client_id, raised_only=True, limit=1))
                    if w_list or has_r:
                        client_name += " 📡"
                        tip = "Pulse: " + ", ".join([getattr(w,'topic','')[:20] for w in w_list[:2]]) if w_list else "Recent raised Pulse intel for client"
                        idx = self.client_combo.count()
                        self.client_combo.setItemData(idx, tip, Qt.ToolTipRole)
                except Exception:
                    pass
            self.client_combo.addItem(client_name or f"Client {client_id}", client_id)
            if initial_client_id is not None and client_id == int(initial_client_id):
                self.client_combo.setCurrentIndex(self.client_combo.count() - 1)

        try:
            projects = db.cos_get_projects() if db is not None and hasattr(db, "cos_get_projects") else []
        except Exception:
            projects = []
        for project in projects:
            try:
                project_id = int(project[0])
                project_name = str(project[1] or "").strip()
            except Exception:
                continue
            self.project_combo.addItem(project_name or f"Project {project_id}", project_id)
            if initial_cos_project_id is not None and project_id == int(initial_cos_project_id):
                self.project_combo.setCurrentIndex(self.project_combo.count() - 1)

        self.client_combo.currentIndexChanged.connect(self._update_pulse_note)
        self._update_pulse_note()  # initial

        form.addRow("Meeting date", self.date_edit)
        form.addRow("Meeting with", self.with_edit)
        form.addRow("Client", self.client_combo)
        form.addRow("Project", self.project_combo)
        self.pulse_note = QLabel("", self)
        self.pulse_note.setStyleSheet("font-size: 9px; color: #7aa0d6;")
        pulse_container = QWidget()
        ph = QHBoxLayout(pulse_container)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.addWidget(self.pulse_note, 1)
        self.view_pulse_btn = QPushButton("View")
        self.view_pulse_btn.setStyleSheet("font-size: 8px; padding: 1px 3px;")
        self.view_pulse_btn.clicked.connect(self._view_pulse_intel)
        ph.addWidget(self.view_pulse_btn)
        form.addRow("Pulse Intel", pulse_container)
        form.addRow("Notes", self.notes_edit)

        layout.addLayout(form)

        hint = QLabel("This will be saved with the transcript for later reference.", self)
        hint.setStyleSheet("color: #888;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str, str, int | None, int | None]:
        meeting_date = self.date_edit.date().toString("yyyy-MM-dd")
        meeting_with = (self.with_edit.text() or "").strip()
        notes = (self.notes_edit.toPlainText() or "").strip()
        client_id = self.client_combo.currentData()
        project_id = self.project_combo.currentData()
        return meeting_date, meeting_with, notes, client_id, project_id

    def _update_pulse_note(self):
        """Tiny: show Pulse Intel summary for selected client in meeting dialog (actionable at-a-glance in creation flow)."""
        try:
            cid = self.client_combo.currentData()
            if not cid or not self.db:
                self.pulse_note.setText("")
                return
            from core.intel import IntelService
            isvc = IntelService(self.db)
            w_list = [w for w in (isvc.list_watch_topics() or []) if getattr(w, 'client_id', None) == cid]
            recent = isvc.list_findings(client_id=cid, raised_only=True, limit=1)
            txt = ""
            if w_list:
                txt = f"👤 {len(w_list)} watches"
            if recent:
                txt += ("; " if txt else "") + f"recent: {getattr(recent[0],'title','')[:25]}"
            self.pulse_note.setText("📡 " + txt if txt else "")
            if hasattr(self, 'view_pulse_btn'):
                self.view_pulse_btn.setVisible(bool(txt))
            self.notes_edit.setToolTip(f"Pulse for client: {txt}" if txt else "Key decisions, action items, follow-ups…")
            # tiny extra: hint in with_edit placeholder when Pulse active for the client
            base_ph = "e.g., Acme — John Smith (Reg Affairs)"
            self.with_edit.setPlaceholderText(base_ph + (f"  📡 Pulse active 🛡️ Shield for sec-relevant" if txt else ""))
        except Exception:
            self.pulse_note.setText("")
            if hasattr(self, 'view_pulse_btn'):
                self.view_pulse_btn.setVisible(False)
            self.notes_edit.setToolTip("Key decisions, action items, follow-ups…")
            self.with_edit.setPlaceholderText("e.g., Acme — John Smith (Reg Affairs)")

    def _view_pulse_intel(self):
        """Tiny: View in Intel filtered to current client from the meeting dialog Pulse note."""
        try:
            cid = self.client_combo.currentData()
            if cid and hasattr(self.parent(), "focus_intel_tab"):
                self.parent().focus_intel_tab(client_id=cid)
                # seamless: confirm in the note area after jumping (stays until client changes or dialog closes)
                txt = self.pulse_note.text()
                if txt and "✓ viewed" not in txt:
                    self.pulse_note.setText(txt + " ✓ viewed")
        except Exception:
            pass


class AssemblyAITranscriptionWorker(QThread):
    status = pyqtSignal(str)
    started_job = pyqtSignal(str)  # transcript_id
    completed = pyqtSignal(str, str)  # formatted_text, transcript_id
    failed = pyqtSignal(str)

    def __init__(self, *, audio_path: str, api_key: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.audio_path = str(audio_path)
        self.api_key = str(api_key)

    def run(self) -> None:
        import time
        from datetime import datetime as _dt, timedelta

        try:
            if not os.path.exists(self.audio_path):
                self.failed.emit("Audio file not found.")
                return

            self.status.emit("Uploading audio file to AssemblyAI…")
            headers = {"authorization": self.api_key}
            with open(self.audio_path, "rb") as f:
                up = requests.post("https://api.assemblyai.com/v2/upload", headers=headers, data=f, timeout=120)
            up.raise_for_status()
            upload_url = up.json().get("upload_url", "")
            if not upload_url:
                self.failed.emit("AssemblyAI upload failed (no upload_url returned).")
                return

            self.status.emit("Starting transcription job…")
            endpoint = "https://api.assemblyai.com/v2/transcript"
            payload = {
                "audio_url": upload_url,
                "speaker_labels": True,
                "speakers_expected": 16,
                "auto_highlights": True,
                "iab_categories": True,
                "auto_chapters": True,
            }
            headers = {"authorization": self.api_key, "content-type": "application/json"}
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            transcript_id = resp.json().get("id", "")
            if not transcript_id:
                self.failed.emit("AssemblyAI transcript creation failed (no id returned).")
                return
            self.started_job.emit(transcript_id)

            start = _dt.now()
            timeout = timedelta(minutes=12)
            last_status = ""

            while True:
                if _dt.now() - start > timeout:
                    self.failed.emit("Transcription timed out after 12 minutes (still processing on AssemblyAI).")
                    return

                r = requests.get(f"{endpoint}/{transcript_id}", headers=headers, timeout=60)
                r.raise_for_status()
                data = r.json()
                status = (data.get("status") or "").strip()
                if status and status != last_status:
                    self.status.emit(f"Status: {status}")
                    last_status = status

                if status == "completed":
                    utterances = data.get("utterances") or []
                    formatted = []
                    formatted.append("Note: speakers who only spoke briefly may not be detected separately.")
                    formatted.append("----------------------------------------\n")
                    if utterances:
                        for u in utterances:
                            speaker = f"Speaker {u.get('speaker')}"
                            text = (u.get("text") or "").strip()
                            if text:
                                formatted.append(f"{speaker}: {text}")
                        final_text = "\n\n".join(formatted).strip()
                    else:
                        final_text = (data.get("text") or "").strip()
                    self.completed.emit(final_text, transcript_id)
                    return

                if status == "error":
                    msg = data.get("error") or "Unknown error"
                    self.failed.emit(f"Transcription failed: {msg}")
                    return

                time.sleep(4 if status == "queued" else 3)

        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class MeetingTaskExtractionWorker(QThread):
    completed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        *,
        response_handler,
        transcript_text: str,
        meeting_date: str | None = None,
        meeting_with: str | None = None,
        notes: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.response_handler = response_handler
        self.transcript_text = str(transcript_text or "")
        self.meeting_date = str(meeting_date or "")
        self.meeting_with = str(meeting_with or "")
        self.notes = str(notes or "")

    def run(self) -> None:
        try:
            if self.response_handler is None or not hasattr(self.response_handler, "chat_with_llama"):
                self.failed.emit("Task extraction is unavailable because the local response handler is not ready.")
                return

            meeting_context = []
            if self.meeting_date:
                meeting_context.append(f"Meeting date: {self.meeting_date}")
            if self.meeting_with:
                meeting_context.append(f"Meeting with: {self.meeting_with}")
            if self.notes:
                meeting_context.append(f"Meeting notes: {self.notes}")

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You extract actionable tasks from meeting transcripts for NaviSsurance. "
                        "Return only a markdown section in this exact format:\n"
                        "## Suggested Tasks (importable)\n"
                        "- [ ] <task title> | due: <MM-DD-YYYY or none> | category: <Business or Personal> | priority: <P0-P5>\n\n"
                        "Rules:\n"
                        "- Include only concrete action items, follow-ups, deliverables, or commitments.\n"
                        "- Do not include vague topics, discussion summaries, or non-actionable ideas.\n"
                        "- Prefer category Business unless the transcript clearly indicates Personal.\n"
                        "- Use due: none unless an actual date or deadline is stated.\n"
                        "- Use P0 for low priority, P3 for normal priority, and P5 only for clearly urgent items.\n"
                        "- Keep titles concise and imperative.\n"
                        "- If there are no actionable tasks, return exactly:\n"
                        "## Suggested Tasks (importable)\n"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "\n".join(meeting_context)
                        + ("\n\n" if meeting_context else "")
                        + "Transcript:\n"
                        + self.transcript_text
                    ).strip(),
                },
            ]
            result = self.response_handler.chat_with_llama(messages, "meeting_task_extract")
            self.completed.emit(str(result or "").strip())
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class MeetingsTab(QWidget):
    def __init__(self, chat_handler):
        super().__init__()
        self.chat_handler = chat_handler
        self.recording = False
        self._transcription_worker: AssemblyAITranscriptionWorker | None = None
        self._current_meeting_id: int | None = None
        self._current_meeting_date: str | None = None
        self._current_meeting_with: str | None = None
        self._current_meeting_notes: str | None = None
        self._current_client_id: int | None = None
        self._current_cos_project_id: int | None = None
        self._current_audio_path: str | None = None
        self._current_transcript_text: str | None = None
        self._task_extraction_worker: MeetingTaskExtractionWorker | None = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        self.recordButton = QPushButton("Start Recording", self)
        self.recordButton.clicked.connect(self.start_recording)
        controls.addWidget(self.recordButton)
        
        self.stopButton = QPushButton("Stop Recording", self)
        self.stopButton.clicked.connect(self.stop_recording)
        self.stopButton.setEnabled(False)
        controls.addWidget(self.stopButton)
        
        self.transcribeButton = QPushButton("Generate Transcript", self)
        self.transcribeButton.clicked.connect(self.transcribe_meeting)
        self.transcribeButton.setEnabled(False)
        controls.addWidget(self.transcribeButton)

        controls.addStretch(1)
        
        self.selectFileButton = QPushButton("Load File", self)
        self.selectFileButton.clicked.connect(self.select_file)
        controls.addWidget(self.selectFileButton)

        self.saveTranscriptButton = QPushButton("Save Transcript", self)
        self.saveTranscriptButton.clicked.connect(self.save_transcript)
        self.saveTranscriptButton.setEnabled(False)
        controls.addWidget(self.saveTranscriptButton)

        self.extractTasksButton = QPushButton("Draft Tasks", self)
        self.extractTasksButton.clicked.connect(self.extract_tasks_from_transcript)
        self.extractTasksButton.setEnabled(False)
        controls.addWidget(self.extractTasksButton)

        layout.addLayout(controls)
        
        self.meetingTranscript = QTextEdit(self)
        self.meetingTranscript.setReadOnly(True)
        layout.addWidget(self.meetingTranscript, 1)
        self._check_recording_deps()

    def _check_recording_deps(self):
        """Show a hint if sounddevice is not installed."""
        try:
            import sounddevice as sd  # noqa: F401
        except ImportError:
            self.meetingTranscript.setPlainText(
                "Recording is unavailable: the 'sounddevice' package is not installed.\n\n"
                "To enable recording, run in a terminal:\n  pip install sounddevice\n\n"
                "You can still use 'Load File' to transcribe an existing audio or video file."
            )

    def start_recording(self):
        """
        Start recording audio using sounddevice.
        Saves to a temporary WAV file.
        """
        import time
        self.recordButton.setEnabled(False)
        self.stopButton.setEnabled(True)
        self._stream = None
        try:
            import sounddevice as sd
            print("Starting recording...")
            self.recording = True
            self.sample_rate = 44100  # Hz
            self.audio_data = []
            self.recording_start_time = time.time()

            def callback(indata, frames, time_info, status):
                if status:
                    print("Recording status:", status)
                if self.recording and hasattr(self, "audio_data"):
                    self.audio_data.append(indata.copy())

            self._stream = sd.InputStream(
                samplerate=self.sample_rate, channels=1, callback=callback, blocksize=1024
            )
            self._stream.start()
        except Exception as e:
            self.recording = False
            self.recordButton.setEnabled(True)
            self.stopButton.setEnabled(False)
            print(f"Recording start error: {e}")
            QMessageBox.critical(
                self,
                "Recording error",
                f"Could not start recording.\n\n{type(e).__name__}: {e}\n\nCheck that a microphone is available and sounddevice is installed.",
            )

    def stop_recording(self):
        """
        Stop recording audio and save to a temporary WAV file.
        """
        import time
        self.recording = False
        stream = getattr(self, "_stream", None)
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                print(f"Stream stop/close error: {e}")
            self._stream = None
        self.recordButton.setEnabled(True)
        self.stopButton.setEnabled(False)
        if not getattr(self, "audio_data", None):
            self.meetingTranscript.setText("Error: No audio data. Recording may not have started correctly.")
            return
        try:
            import scipy.io.wavfile as wavfile
            self.transcribeButton.setEnabled(True)
            print("Recording stopped")
            from config import ARTIFACTS_DIR

            meetings_dir = os.path.join(ARTIFACTS_DIR, "meetings")
            os.makedirs(meetings_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.audio_file_path = os.path.join(meetings_dir, f"meeting_{timestamp}.wav")
            # audio_data is list of chunks; concatenate
            audio_array = np.concatenate(self.audio_data, axis=0)
            if audio_array.dtype != np.int16:
                audio_array = (np.clip(audio_array, -1.0, 1.0) * 32767).astype(np.int16)
            wavfile.write(self.audio_file_path, self.sample_rate, audio_array)
            print(f"Audio saved to {self.audio_file_path}")
            logger.info(
                "Meeting recording WAV saved: path=%s sample_rate=%s samples=%s",
                self.audio_file_path,
                self.sample_rate,
                int(audio_array.shape[0]) if getattr(audio_array, "shape", None) else 0,
            )
            self.selected_audio_path = self.audio_file_path
            self.meetingTranscript.setText("Recording saved. Sending for transcription…")
            self._begin_meeting_transcription_flow(
                audio_path=self.selected_audio_path,
                source="recording",
                default_date=QDate.currentDate(),
                prompt_for_metadata=True,
            )
        except Exception as e:
            print(f"Stop/save error: {e}")
            logger.exception("Meeting recording save failed")
            QMessageBox.critical(
                self,
                "Save recording error",
                f"Recording stopped but saving failed.\n\n{type(e).__name__}: {e}",
            )
            self.meetingTranscript.setText(f"Error saving recording: {e}")

    def transcribe_meeting(self):
        """
        Transcribe the recorded audio file or a selected audio/video file using AssemblyAI's API.
        Prompts for meeting label/notes and saves the transcript + metadata automatically.
        """
        audio_path = getattr(self, "selected_audio_path", "") or ""
        if not audio_path or not os.path.exists(audio_path):
            self.meetingTranscript.setText("Error: No file found for transcription.")
            self.saveTranscriptButton.setEnabled(False)
            return
        self._begin_meeting_transcription_flow(
            audio_path=audio_path,
            source="file",
            default_date=QDate.currentDate(),
            prompt_for_metadata=True,
        )

    def _begin_meeting_transcription_flow(
        self,
        *,
        audio_path: str,
        source: str,
        default_date: QDate,
        prompt_for_metadata: bool,
    ) -> None:
        # Load AssemblyAI API key from environment early (avoid popping dialogs when we can't proceed).
        api_key = os.getenv("ASSEMBLYAI_API_KEY", "").strip()
        if not api_key:
            self.meetingTranscript.setText(
                "Error: AssemblyAI API key not found. Please set ASSEMBLYAI_API_KEY in config/.env."
            )
            self.saveTranscriptButton.setEnabled(False)
            return

        if self._transcription_worker is not None and self._transcription_worker.isRunning():
            self.meetingTranscript.append("A transcription is already running. Please wait for it to finish.")
            return

        meeting_date = None
        meeting_with = ""
        notes = ""
        client_id = None
        cos_project_id = None
        if prompt_for_metadata:
            dlg = MeetingMetadataDialog(
                self,
                default_date=default_date,
                db=getattr(self.chat_handler, "db", None),
            )
            if dlg.exec() == QDialog.DialogCode.Accepted:
                meeting_date, meeting_with, notes, client_id, cos_project_id = dlg.values()
            else:
                meeting_date = default_date.toString("yyyy-MM-dd")
        else:
            meeting_date = default_date.toString("yyyy-MM-dd")

        self._current_meeting_date = meeting_date
        self._current_meeting_with = meeting_with
        self._current_meeting_notes = notes
        self._current_client_id = int(client_id) if client_id is not None else None
        self._current_cos_project_id = int(cos_project_id) if cos_project_id is not None else None
        self._current_audio_path = str(audio_path)
        self._current_transcript_text = None

        meeting_id = None
        try:
            if getattr(self.chat_handler, "db", None) is not None:
                meeting_id = self.chat_handler.db.create_meeting_record(
                    meeting_date=meeting_date,
                    meeting_with=meeting_with,
                    notes=notes,
                    source=source,
                    audio_file_path=str(audio_path),
                    transcription_provider="assemblyai",
                    status="uploading",
                    client_id=self._current_client_id,
                    cos_project_id=self._current_cos_project_id,
                )
        except Exception:
            meeting_id = None

        self._current_meeting_id = meeting_id

        header_lines = [
            f"Meeting date: {meeting_date}",
            f"Meeting with: {meeting_with or '(unlabeled)'}",
        ]
        if self._current_client_id is not None:
            header_lines.append(f"Client ID: {self._current_client_id}")
        if self._current_cos_project_id is not None:
            header_lines.append(f"Project ID: {self._current_cos_project_id}")
        if notes:
            header_lines.append("Notes:\n" + notes)
        header_lines.append("\nTranscription started…\n")
        self.meetingTranscript.setPlainText("\n".join(header_lines))

        self.transcribeButton.setEnabled(False)
        self.saveTranscriptButton.setEnabled(False)

        worker = AssemblyAITranscriptionWorker(audio_path=str(audio_path), api_key=api_key, parent=self)
        self._transcription_worker = worker
        worker.status.connect(lambda msg: self.meetingTranscript.append(msg))
        worker.started_job.connect(self._on_transcription_started)
        worker.completed.connect(self._on_transcription_completed)
        worker.failed.connect(self._on_transcription_failed)
        worker.start()

    def _on_transcription_started(self, transcript_id: str) -> None:
        mid = self._current_meeting_id
        if mid is not None and getattr(self.chat_handler, "db", None) is not None:
            try:
                self.chat_handler.db.update_meeting_record(
                    mid, status="processing", provider_transcript_id=str(transcript_id)
                )
            except Exception:
                pass
        self.meetingTranscript.append(f"Transcription job ID: {transcript_id}")

    def _on_transcription_completed(self, formatted_text: str, transcript_id: str) -> None:
        # Persist transcript to disk for easy re-use.
        transcript_path = None
        try:
            from config import ARTIFACTS_DIR

            meetings_dir = os.path.join(ARTIFACTS_DIR, "meetings")
            os.makedirs(meetings_dir, exist_ok=True)
            mid = self._current_meeting_id or 0
            date_s = _safe_filename_part(self._current_meeting_date or "", fallback="date")
            with_s = _safe_filename_part(self._current_meeting_with or "", fallback="unlabeled")
            transcript_path = os.path.join(meetings_dir, f"meeting_{mid}_{date_s}_{with_s}_transcript.txt")
            with open(transcript_path, "w", encoding="utf-8") as f:
                f.write(formatted_text or "")
        except Exception:
            transcript_path = None

        mid = self._current_meeting_id
        if mid is not None and getattr(self.chat_handler, "db", None) is not None:
            try:
                self.chat_handler.db.update_meeting_record(
                    mid,
                    status="completed",
                    provider_transcript_id=str(transcript_id),
                    transcript_text=formatted_text,
                    transcript_file_path=transcript_path,
                    error_message=None,
                )
            except Exception:
                pass

        header = []
        if self._current_meeting_date:
            header.append(f"Meeting date: {self._current_meeting_date}")
        header.append(f"Meeting with: {self._current_meeting_with or '(unlabeled)'}")
        if self._current_client_id is not None:
            header.append(f"Client ID: {self._current_client_id}")
        if self._current_cos_project_id is not None:
            header.append(f"Project ID: {self._current_cos_project_id}")
        if self._current_meeting_notes:
            header.append("Notes:\n" + self._current_meeting_notes)
        header.append("\n--- Transcript ---\n")
        self._current_transcript_text = formatted_text or ""
        self.meetingTranscript.setPlainText("\n".join(header) + (formatted_text or ""))
        self.saveTranscriptButton.setEnabled(True)
        self.extractTasksButton.setEnabled(bool((formatted_text or "").strip()))
        self.transcribeButton.setEnabled(True)
        self.extract_tasks_from_transcript(auto=True)

    def _on_transcription_failed(self, error_message: str) -> None:
        mid = self._current_meeting_id
        if mid is not None and getattr(self.chat_handler, "db", None) is not None:
            try:
                self.chat_handler.db.update_meeting_record(mid, status="error", error_message=str(error_message))
            except Exception:
                pass
        self.meetingTranscript.append(f"\nError during transcription: {error_message}")
        self.transcribeButton.setEnabled(True)
        self.saveTranscriptButton.setEnabled(False)
        self.extractTasksButton.setEnabled(False)

    def extract_tasks_from_transcript(self, *, auto: bool = False):
        transcript_text = (self._current_transcript_text or "").strip()
        if not transcript_text:
            if not auto:
                QMessageBox.information(self, "Draft Tasks", "No completed transcript is available yet.")
            return

        if self._task_extraction_worker is not None and self._task_extraction_worker.isRunning():
            if not auto:
                self.meetingTranscript.append("Task extraction is already running. Please wait.")
            return

        response_handler = getattr(self.chat_handler, "response_handler", None)
        if response_handler is None or not hasattr(response_handler, "chat_with_llama"):
            if not auto:
                QMessageBox.warning(self, "Draft Tasks", "Task extraction is unavailable right now.")
            return

        self.extractTasksButton.setEnabled(False)
        if not auto:
            self.meetingTranscript.append("\nExtracting draft tasks from transcript…")

        worker = MeetingTaskExtractionWorker(
            response_handler=response_handler,
            transcript_text=transcript_text,
            meeting_date=self._current_meeting_date,
            meeting_with=self._current_meeting_with,
            notes=self._current_meeting_notes,
            parent=self,
        )
        self._task_extraction_worker = worker
        worker.completed.connect(lambda markdown: self._on_task_extraction_completed(markdown, auto=auto))
        worker.failed.connect(lambda err: self._on_task_extraction_failed(err, auto=auto))
        worker.start()

    def _on_task_extraction_completed(self, markdown: str, *, auto: bool) -> None:
        self._task_extraction_worker = None
        self.extractTasksButton.setEnabled(bool((self._current_transcript_text or "").strip()))

        tasks, warnings = parse_suggested_tasks(markdown or "")
        if not tasks:
            if not auto:
                QMessageBox.information(
                    self,
                    "Draft Tasks",
                    "No actionable tasks were detected in this transcript.",
                )
            return

        dlg = TaskImportDialog(tasks, warnings=warnings, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected = dlg.selected_tasks()
        if not selected:
            return

        db = getattr(self.chat_handler, "db", None)
        if db is None or not hasattr(db, "add_task"):
            QMessageBox.warning(self, "Draft Tasks", "Tasks database is unavailable.")
            return

        meeting_label = self._meeting_task_source_label()
        added = 0
        for task in selected:
            due = None if str(task.due_mmddyyyy).strip().lower() == "none" else task.due_mmddyyyy
            task_id = db.add_task(
                f"meeting_transcript_{self._current_meeting_id or 'manual'}",
                task.title,
                due,
                category=task.category,
            )
            if hasattr(db, "update_task_by_id"):
                try:
                    tags = ["meeting_transcript", "draft_import"]
                    if self._current_meeting_id is not None:
                        tags.append(f"meeting_{int(self._current_meeting_id)}")
                    db.update_task_by_id(
                        int(task_id),
                        priority=int(task.priority or 0),
                        blockers=meeting_label,
                        tags_json=json.dumps(tags),
                    )
                except Exception:
                    pass
            added += 1

        self._refresh_task_views()
        self.meetingTranscript.append(f"\nImported {added} draft task(s) from this transcript.")

    def _on_task_extraction_failed(self, error_message: str, *, auto: bool) -> None:
        self._task_extraction_worker = None
        self.extractTasksButton.setEnabled(bool((self._current_transcript_text or "").strip()))
        if not auto:
            QMessageBox.warning(self, "Draft Tasks", f"Could not extract tasks:\n{error_message}")

    def _meeting_task_source_label(self) -> str:
        parts = ["Drafted from meeting transcript"]
        if self._current_meeting_date:
            parts.append(f"on {self._current_meeting_date}")
        if self._current_meeting_with:
            parts.append(f"with {self._current_meeting_with}")
        if self._current_meeting_notes:
            parts.append(f"Notes: {self._current_meeting_notes}")
        return " | ".join(parts)

    def _refresh_task_views(self) -> None:
        try:
            win = self.window()
            if hasattr(win, "tasks_tab") and hasattr(win.tasks_tab, "refresh_tasks"):
                win.tasks_tab.refresh_tasks()
            if hasattr(win, "dashboard_tab") and hasattr(win.dashboard_tab, "load_tasks_filtered"):
                win.dashboard_tab.load_tasks_filtered()
        except Exception:
            pass

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
        """
        Save the transcript text to a file using a file dialog.
        """
        import os
        import time

        transcript_text = self.meetingTranscript.toPlainText()
        if not transcript_text or transcript_text.startswith("Error"):
            print("No valid transcript to save")
            return

        # Get the default filename with timestamp
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        if self._current_meeting_date or self._current_meeting_with:
            date_s = _safe_filename_part(self._current_meeting_date or "", fallback="date")
            with_s = _safe_filename_part(self._current_meeting_with or "", fallback="unlabeled")
            default_stem = f"meeting_{date_s}_{with_s}_transcript_{timestamp}"
        else:
            default_stem = f"transcript_{timestamp}"
        
        # Open file dialog
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Transcript",
            f"{default_stem}.txt",
            "Text Files (*.txt);;Word Documents (*.docx);;All Files (*)"
        )
        
        if file_path:  # If user didn't cancel
            try:
                is_docx = file_path.lower().endswith(".docx") or "docx" in (selected_filter or "").lower()
                if is_docx:
                    if not file_path.lower().endswith(".docx"):
                        file_path += ".docx"
                    doc = Document()
                    for line in transcript_text.splitlines():
                        doc.add_paragraph(line)
                    doc.save(file_path)
                else:
                    if not os.path.splitext(file_path)[1]:
                        file_path += ".txt"
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(transcript_text)
                print(f"Transcript saved to {file_path}")
                self.saveTranscriptButton.setEnabled(False)
                self.meetingTranscript.append(f"<i>Transcript saved to {file_path}</i>")
            except Exception as e:
                print(f"Error saving transcript: {e}")
                self.meetingTranscript.append(f"<i>Error saving transcript: {e}</i>")

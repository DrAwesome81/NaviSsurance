"""
Qt/UI tests for Meetings tab local behaviors.

Disabled by default. Enable with RUN_QT_TESTS=1.
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from unittest.mock import Mock

import numpy as np
import pytest
from docx import Document

if not os.getenv("RUN_QT_TESTS"):
    pytest.skip(
        "Qt/UI tests are disabled by default (set RUN_QT_TESTS=1 to enable).",
        allow_module_level=True,
    )

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PyQt6.QtWidgets import QDialog

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gui.meetings_tab import MeetingsTab


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def meetings_tab(qapp):
    return MeetingsTab(chat_handler=Mock())


def test_select_file_cancel_sets_message(monkeypatch, meetings_tab):
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )
    meetings_tab.select_file()
    assert meetings_tab.meetingTranscript.toPlainText() == "No file selected."


def test_select_audio_file_enables_transcribe(monkeypatch, meetings_tab, tmp_path):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFF")

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(audio_path), "Media Files (*.wav)"),
    )
    meetings_tab.select_file()

    assert meetings_tab.transcribeButton.isEnabled() is True
    assert getattr(meetings_tab, "selected_audio_path", "") == str(audio_path)
    assert "Audio file selected" in meetings_tab.meetingTranscript.toPlainText()


def test_select_video_file_routes_to_audio_extractor(monkeypatch, meetings_tab, tmp_path):
    video_path = tmp_path / "meeting.mp4"
    video_path.write_bytes(b"\x00\x00\x00\x18ftyp")
    called = {"path": None}

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(video_path), "Media Files (*.mp4)"),
    )

    def _extract(path):
        called["path"] = path

    monkeypatch.setattr(meetings_tab, "extract_audio_from_video", _extract)
    meetings_tab.select_file()

    assert called["path"] == str(video_path)
    assert meetings_tab.transcribeButton.isEnabled() is True


def test_stop_recording_without_audio_sets_error(meetings_tab):
    meetings_tab.audio_data = []
    meetings_tab.stop_recording()
    assert "No audio data" in meetings_tab.meetingTranscript.toPlainText()


def test_save_transcript_writes_file(monkeypatch, meetings_tab, tmp_path):
    out_path = tmp_path / "transcript.txt"
    meetings_tab.meetingTranscript.setPlainText("Speaker 1: Hello")
    meetings_tab.saveTranscriptButton.setEnabled(True)

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(out_path), "Text Files (*.txt)"),
    )

    meetings_tab.save_transcript()

    assert out_path.exists()
    assert out_path.read_text(encoding="utf-8") == "Speaker 1: Hello"
    assert meetings_tab.saveTranscriptButton.isEnabled() is False


def test_save_transcript_writes_docx(monkeypatch, meetings_tab, tmp_path):
    out_path = tmp_path / "transcript.docx"
    meetings_tab.meetingTranscript.setPlainText("Speaker 1: Hello\nSpeaker 2: Hi")
    meetings_tab.saveTranscriptButton.setEnabled(True)

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(out_path), "Word Documents (*.docx)"),
    )

    meetings_tab.save_transcript()

    assert out_path.exists()
    doc = Document(str(out_path))
    assert [p.text for p in doc.paragraphs] == ["Speaker 1: Hello", "Speaker 2: Hi"]
    assert meetings_tab.saveTranscriptButton.isEnabled() is False


def test_save_transcript_skips_invalid_text(monkeypatch, meetings_tab):
    meetings_tab.meetingTranscript.setPlainText("Error during transcription: timeout")

    called = {"value": False}

    def _fake_dialog(*args, **kwargs):
        called["value"] = True
        return ("ignored.txt", "Text Files (*.txt)")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", _fake_dialog)
    meetings_tab.save_transcript()

    assert called["value"] is False


def test_save_transcript_cancel_keeps_button_enabled(monkeypatch, meetings_tab):
    meetings_tab.meetingTranscript.setPlainText("Valid transcript")
    meetings_tab.saveTranscriptButton.setEnabled(True)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: ("", ""))

    meetings_tab.save_transcript()

    assert meetings_tab.saveTranscriptButton.isEnabled() is True


def test_transcribe_meeting_without_api_key_sets_error(monkeypatch, meetings_tab, tmp_path):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFF")
    meetings_tab.selected_audio_path = str(audio_path)
    meetings_tab.transcribeButton.setEnabled(True)

    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)
    meetings_tab.transcribe_meeting()

    text = meetings_tab.meetingTranscript.toPlainText()
    assert "AssemblyAI API key not found" in text
    assert meetings_tab.saveTranscriptButton.isEnabled() is False


def test_transcribe_meeting_without_selected_file_sets_error(monkeypatch, meetings_tab):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "dummy")
    if hasattr(meetings_tab, "selected_audio_path"):
        delattr(meetings_tab, "selected_audio_path")

    meetings_tab.transcribe_meeting()

    assert "No file found for transcription." in meetings_tab.meetingTranscript.toPlainText()
    assert meetings_tab.saveTranscriptButton.isEnabled() is False


def test_start_recording_failure_resets_controls(monkeypatch, meetings_tab):
    fake_sd = types.SimpleNamespace(
        InputStream=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("mic unavailable"))
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    calls = {"critical": 0}
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda *args, **kwargs: calls.__setitem__("critical", calls["critical"] + 1),
    )

    meetings_tab.start_recording()

    assert calls["critical"] == 1
    assert meetings_tab.recording is False
    assert meetings_tab.recordButton.isEnabled() is True
    assert meetings_tab.stopButton.isEnabled() is False


def test_stop_recording_save_error_sets_transcript_error(monkeypatch, meetings_tab):
    scipy_mod = types.ModuleType("scipy")
    scipy_io_mod = types.ModuleType("scipy.io")
    scipy_wav_mod = types.ModuleType("scipy.io.wavfile")

    def _write_raises(*args, **kwargs):
        raise RuntimeError("write failure")

    scipy_wav_mod.write = _write_raises
    scipy_io_mod.wavfile = scipy_wav_mod
    scipy_mod.io = scipy_io_mod

    monkeypatch.setitem(sys.modules, "scipy", scipy_mod)
    monkeypatch.setitem(sys.modules, "scipy.io", scipy_io_mod)
    monkeypatch.setitem(sys.modules, "scipy.io.wavfile", scipy_wav_mod)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)

    meetings_tab.audio_data = [np.zeros((16, 1), dtype=np.float32)]
    meetings_tab.sample_rate = 44100
    meetings_tab._stream = None

    meetings_tab.stop_recording()

    assert "Error saving recording" in meetings_tab.meetingTranscript.toPlainText()


def test_extract_audio_from_video_failure_disables_transcribe(monkeypatch, meetings_tab, tmp_path):
    video_path = tmp_path / "meeting.mp4"
    video_path.write_bytes(b"\x00\x00\x00\x18ftyp")

    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "ffmpeg")

    monkeypatch.setattr("subprocess.run", _raise)

    meetings_tab.transcribeButton.setEnabled(True)
    meetings_tab.extract_audio_from_video(str(video_path))

    assert meetings_tab.transcribeButton.isEnabled() is False
    assert "Error extracting audio" in meetings_tab.meetingTranscript.toPlainText()


def test_on_transcription_completed_enables_task_drafting_and_autostarts(monkeypatch, meetings_tab):
    called = {"count": 0, "auto": None}
    monkeypatch.setattr(
        meetings_tab,
        "extract_tasks_from_transcript",
        lambda auto=False: (called.__setitem__("count", called["count"] + 1), called.__setitem__("auto", auto)),
    )

    meetings_tab._current_meeting_date = "2026-03-07"
    meetings_tab._current_meeting_with = "Acme"
    meetings_tab._current_meeting_notes = "Discuss follow-up items"

    meetings_tab._on_transcription_completed("Speaker 1: Do the draft.", "tr_123")

    assert meetings_tab.extractTasksButton.isEnabled() is True
    assert meetings_tab._current_transcript_text == "Speaker 1: Do the draft."
    assert called["count"] == 1
    assert called["auto"] is True


def test_task_extraction_completed_imports_selected_tasks(monkeypatch, meetings_tab):
    class _Db:
        def __init__(self):
            self.added = []
            self.updated = []

        def add_task(self, session_id, task_text, due_date, category="Business", recurrence="None", completed=0):
            self.added.append((session_id, task_text, due_date, category))
            return len(self.added)

        def update_task_by_id(self, task_id, **kwargs):
            self.updated.append((task_id, kwargs))

    class _Dialog:
        def __init__(self, tasks, warnings=None, parent=None):
            self._tasks = list(tasks)

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_tasks(self):
            return self._tasks[:1]

    db = _Db()
    meetings_tab.chat_handler.db = db
    meetings_tab._current_meeting_id = 7
    meetings_tab._current_meeting_date = "2026-03-07"
    meetings_tab._current_meeting_with = "Acme"
    meetings_tab._current_meeting_notes = "Capture follow-up items"
    meetings_tab._current_transcript_text = "Transcript body"
    meetings_tab.extractTasksButton.setEnabled(False)

    monkeypatch.setattr("gui.meetings_tab.TaskImportDialog", _Dialog)

    meetings_tab._on_task_extraction_completed(
        "## Suggested Tasks (importable)\n- [ ] Send follow-up memo | due: 03-10-2026 | category: Business | priority: P4\n",
        auto=False,
    )

    assert meetings_tab.extractTasksButton.isEnabled() is True
    assert len(db.added) == 1
    assert db.added[0][1] == "Send follow-up memo"
    assert db.added[0][2] == "03-10-2026"
    assert db.added[0][3] == "Business"
    assert db.updated and db.updated[0][0] == 1
    assert db.updated[0][1]["priority"] == 4
    assert "Imported 1 draft task" in meetings_tab.meetingTranscript.toPlainText()


def test_task_extraction_completed_with_no_tasks_shows_message(monkeypatch, meetings_tab):
    info = {"count": 0}
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: info.__setitem__("count", info["count"] + 1),
    )
    meetings_tab._current_transcript_text = "Transcript body"
    meetings_tab.extractTasksButton.setEnabled(False)

    meetings_tab._on_task_extraction_completed("## Suggested Tasks (importable)\n", auto=False)

    assert meetings_tab.extractTasksButton.isEnabled() is True
    assert info["count"] == 1

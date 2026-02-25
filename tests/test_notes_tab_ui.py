"""
Qt/UI tests for current NoteTakingSystem local behaviors.
"""

from __future__ import annotations

import os
import sys

import pytest

if not os.getenv("RUN_QT_TESTS"):
    pytest.skip(
        "Qt/UI tests are disabled by default (set RUN_QT_TESTS=1 to enable).",
        allow_module_level=True,
    )

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QDialog

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gui.notes_tab import NoteTakingSystem


class _DbStub:
    def __init__(self):
        self._next_id = 3
        self.notes = [
            {
                "id": 1,
                "timestamp": "2026-02-20 10:00:00",
                "context": "FDA review",
                "category": "Regulatory",
                "state": "ready",
                "pinned": 0,
                "raw_note": "raw one",
                "formatted_note": "formatted one",
                "error_text": None,
            },
            {
                "id": 2,
                "timestamp": "2026-02-21 11:00:00",
                "context": "FDA review",
                "category": "Uncategorized",
                "state": "error",
                "pinned": 1,
                "raw_note": "raw two",
                "formatted_note": "",
                "error_text": "formatting failed",
            },
        ]
        self.cleared_organized = 0
        self.added_tasks = []
        self.deleted_ids = []
        self.memory_calls = []

    def init_notes_table(self):
        return None

    def clear_organized_notes(self):
        self.cleared_organized += 1

    def list_notes(self, context=None, limit=5000):
        rows = list(self.notes)
        if context:
            rows = [n for n in rows if (n.get("context") or "") == context]
        return rows[:limit]

    def search_notes(self, query, context=None, limit=5000):
        q = (query or "").lower()
        rows = self.list_notes(context=context, limit=limit)
        return [n for n in rows if q in (n.get("formatted_note") or "").lower() or q in (n.get("raw_note") or "").lower()]

    def update_note_by_id(self, note_id, **kwargs):
        for n in self.notes:
            if int(n["id"]) == int(note_id):
                n.update(kwargs)
                return

    def delete_note_by_id(self, note_id):
        self.deleted_ids.append(int(note_id))
        self.notes = [n for n in self.notes if int(n["id"]) != int(note_id)]

    def add_task(self, session_id, task_text, due, category="Business"):
        self.added_tasks.append((session_id, task_text, due, category))

    def create_note_draft(self, raw_note, timestamp, context):
        note_id = self._next_id
        self._next_id += 1
        self.notes.append(
            {
                "id": note_id,
                "timestamp": timestamp,
                "context": context or "",
                "category": "Uncategorized",
                "state": "pending",
                "pinned": 0,
                "raw_note": raw_note,
                "formatted_note": "",
                "error_text": None,
            }
        )
        return note_id

    def save_organized_notes(self, _cats):
        return None

    def cos_memory_add(self, **_kwargs):
        self.memory_calls.append(dict(_kwargs))
        return None


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def notes_system(monkeypatch, qapp):
    db = _DbStub()
    monkeypatch.setattr("gui.notes_tab.DatabaseManager", lambda: db)
    chat_handler = type("_Handler", (), {"get_response": lambda *args, **kwargs: '{"formatted":"ok"}'})()
    system = NoteTakingSystem(chat_handler=chat_handler)
    return system


def test_update_context_sets_value_clears_input_and_resets_organized(notes_system):
    notes_system.context_input.setText("Submission package review")
    notes_system.update_context()
    assert notes_system.context == "Submission package review"
    assert notes_system.context_input.text() == ""
    assert notes_system.db.cleared_organized == 1


def test_set_action_buttons_for_error_note_enables_retry(notes_system):
    note = next(n for n in notes_system.db.notes if n["state"] == "error")
    notes_system._set_action_buttons_enabled(note)
    assert notes_system.retry_btn.isEnabled() is True
    assert notes_system.edit_btn.isEnabled() is False
    assert notes_system.task_btn.isEnabled() is False


def test_delete_selected_note_confirmation_paths(monkeypatch, notes_system):
    notes_system._selected_note_id = 1
    monkeypatch.setattr("gui.notes_tab.QMessageBox.question", lambda *args, **kwargs: 65536)  # No
    notes_system.delete_selected_note()
    assert notes_system.db.deleted_ids == []

    notes_system._selected_note_id = 1
    monkeypatch.setattr("gui.notes_tab.QMessageBox.question", lambda *args, **kwargs: 16384)  # Yes
    notes_system.delete_selected_note()
    assert notes_system.db.deleted_ids == [1]


def test_export_notes_markdown_writes_file(monkeypatch, notes_system, tmp_path):
    out = tmp_path / "notes_export.md"
    monkeypatch.setattr(
        "gui.notes_tab.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(out), "Markdown (*.md)"),
    )
    monkeypatch.setattr("gui.notes_tab.QMessageBox.information", lambda *args, **kwargs: None)
    notes_system.export_notes()
    assert out.exists()
    assert out.read_text(encoding="utf-8").strip() != ""


def test_create_task_from_selected_adds_task_on_accept(monkeypatch, notes_system):
    # Ensure a selectable ready note exists.
    notes_system._selected_note_id = 1
    # Accept any dialog opened by create_task_from_selected.
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr("gui.notes_tab.QMessageBox.information", lambda *args, **kwargs: None)
    notes_system.create_task_from_selected()
    assert len(notes_system.db.added_tasks) == 1
    session_id, task_text, due, category = notes_system.db.added_tasks[0]
    assert session_id == "notes_session"
    assert "formatted one" in task_text
    assert due is None
    assert category == "Business"


def test_copy_selected_note_sets_clipboard_text(monkeypatch, notes_system):
    notes_system._selected_note_id = 1

    class _Clipboard:
        def __init__(self):
            self.value = ""

        def setText(self, text):
            self.value = text

    clip = _Clipboard()
    monkeypatch.setattr("PyQt6.QtWidgets.QApplication.clipboard", lambda: clip)
    monkeypatch.setattr("gui.notes_tab.QMessageBox.information", lambda *args, **kwargs: None)
    notes_system.copy_selected_note()
    assert clip.value == "formatted one"


def test_remember_selected_note_persists_memory_payload(monkeypatch, notes_system):
    notes_system._selected_note_id = 1
    monkeypatch.setattr("gui.notes_tab.QMessageBox.information", lambda *args, **kwargs: None)
    notes_system.remember_selected_note()
    assert len(notes_system.db.memory_calls) == 1
    call = notes_system.db.memory_calls[0]
    assert call.get("kind") == "note"
    assert "formatted one" in (call.get("content") or "")

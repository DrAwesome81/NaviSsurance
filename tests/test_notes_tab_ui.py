"""
Qt/UI tests for the context-document Notes workspace.
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

from PyQt6.QtWidgets import QApplication

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
                "category": "Merged",
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
                "category": "Merged",
                "state": "error",
                "pinned": 0,
                "raw_note": "raw two",
                "formatted_note": "formatted two",
                "error_text": "formatting failed",
            },
        ]
        self.documents = {
            "FDA review": {
                "id": 1,
                "context": "FDA review",
                "title": "FDA review",
                "document_text": "## Regulatory\n- formatted one",
                "state": "ready",
                "error_text": None,
                "source_note_count": 1,
                "created_at": "2026-02-20 10:00:00",
                "updated_at": "2026-02-20 10:30:00",
            }
        }

    def init_notes_table(self):
        return None

    def list_notes(self, context=None, limit=5000):
        rows = list(self.notes)
        if context:
            rows = [n for n in rows if (n.get("context") or "") == context]
        return rows[:limit]

    def create_note_draft(self, raw_note, timestamp, context, category="Captured"):
        note_id = self._next_id
        self._next_id += 1
        self.notes.append(
            {
                "id": note_id,
                "timestamp": timestamp,
                "context": context or "",
                "category": category,
                "state": "pending",
                "pinned": 0,
                "raw_note": raw_note,
                "formatted_note": "",
                "error_text": None,
            }
        )
        return note_id

    def update_note_by_id(self, note_id, **kwargs):
        for n in self.notes:
            if int(n["id"]) == int(note_id):
                n.update(kwargs)
                return

    def count_ready_notes_for_context(self, context):
        return len([n for n in self.notes if (n.get("context") or "") == (context or "") and (n.get("state") or "") == "ready"])

    def list_note_documents(self, query=None, limit=500):
        docs = list(self.documents.values())
        docs.sort(key=lambda d: ((d.get("updated_at") or ""), (d.get("context") or "")), reverse=True)
        return docs[:limit]

    def get_note_document(self, context, create=False):
        key = (context or "").strip() or "General Notes"
        doc = self.documents.get(key)
        if doc is None and create:
            doc = {
                "id": len(self.documents) + 1,
                "context": key,
                "title": key,
                "document_text": "",
                "state": "ready",
                "error_text": None,
                "source_note_count": 0,
                "created_at": "2026-02-20 10:00:00",
                "updated_at": "2026-02-20 10:00:00",
            }
            self.documents[key] = doc
        return dict(doc) if doc else None

    def save_note_document(self, context, *, document_text, title=None, state="ready", error_text=None, source_note_count=None):
        key = (context or "").strip() or "General Notes"
        current = self.get_note_document(key, create=True) or {}
        current.update(
            {
                "context": key,
                "title": (title or key),
                "document_text": document_text,
                "state": state,
                "error_text": error_text,
                "source_note_count": self.count_ready_notes_for_context(key)
                if source_note_count is None
                else int(source_note_count),
                "updated_at": "2026-02-20 11:00:00",
            }
        )
        self.documents[key] = current


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
    chat_handler = type("_Handler", (), {"get_response": lambda *args, **kwargs: '{"document":"## Updated\\n- merged"}'})()
    return NoteTakingSystem(chat_handler=chat_handler)


def test_update_context_sets_value_clears_input_and_creates_document(notes_system):
    notes_system.context_input.setText("Submission package review")
    notes_system.update_context()
    assert notes_system.context == "Submission package review"
    assert notes_system.context_input.text() == ""
    assert notes_system.active_context_label.text() == "Current document: Submission package review"
    assert notes_system.db.get_note_document("Submission package review", create=False) is not None


def test_update_context_blank_clears_active_context(notes_system):
    notes_system.context = "Old context"
    notes_system.context_input.setText("")
    notes_system.update_context()
    assert notes_system.context is None
    assert notes_system.active_context_label.text() == "Current document: (none)"


def test_refresh_loads_existing_document(notes_system):
    notes_system.context = "FDA review"
    notes_system.refresh_notes()
    assert "formatted one" in notes_system.document_editor.toPlainText()
    assert "Source captures: 1" in notes_system.doc_meta_label.text()


def test_save_current_document_persists_text(notes_system):
    notes_system.context = "FDA review"
    notes_system.refresh_notes()
    notes_system.document_editor.setPlainText("## Regulatory\n- Saved manually")
    notes_system.save_current_document()
    doc = notes_system.db.get_note_document("FDA review")
    assert "Saved manually" in (doc or {}).get("document_text", "")
    assert notes_system.save_btn.isEnabled() is False


def test_process_note_merges_into_current_document(monkeypatch, notes_system):
    notes_system.context = "FDA review"
    notes_system.refresh_notes()

    def _instant_update(*, note_id, raw_text, context, current_document, retry_count=0):
        notes_system._handle_note_formatted_safe('{"document":"## Regulatory\\n- merged into doc"}', note_id, raw_text, context)

    monkeypatch.setattr(notes_system, "_start_document_update_for_note", _instant_update)
    notes_system.chat_input.setPlainText("Need to check section 5")
    notes_system.process_note()

    doc = notes_system.db.get_note_document("FDA review")
    assert "merged into doc" in (doc or {}).get("document_text", "")
    assert notes_system.chat_input.toPlainText() == ""


def test_reorganize_notes_updates_current_document(notes_system):
    notes_system.context = "FDA review"
    notes_system.refresh_notes()
    notes_system._handle_reorganization_result_safe('{"document":"## Refined\\n- tighter bullet"}', "FDA review")
    doc = notes_system.db.get_note_document("FDA review")
    assert "tighter bullet" in (doc or {}).get("document_text", "")


def test_reorganize_worker_fallback_retries_only_once(monkeypatch, notes_system):
    notes_system.context = "FDA review"
    notes_system.refresh_notes()
    retried = []

    def _retry(*, retry_count=0):
        retried.append(retry_count)

    notes_system._reorganize_in_progress = True
    monkeypatch.setattr(notes_system, "reorganize_notes", _retry)
    monkeypatch.setattr("gui.notes_tab.QTimer.singleShot", lambda _ms, fn: fn())
    notes_system._handle_reorganization_result_safe(
        "Local AI's acting up—try again.",
        "FDA review",
        "## Regulatory\n- formatted one",
        0,
    )

    assert retried == [1]


def test_worker_fallback_string_retries_once(monkeypatch, notes_system):
    notes_system.context = "FDA review"
    notes_system.refresh_notes()
    retried = []

    def _retry(**kwargs):
        retried.append(kwargs)

    monkeypatch.setattr(notes_system, "_start_document_update_for_note", _retry)
    monkeypatch.setattr("gui.notes_tab.QTimer.singleShot", lambda _ms, fn: fn())
    notes_system._handle_note_formatted_safe(
        "Local AI's acting up—try again.",
        1,
        "Need to check section 5",
        "FDA review",
        "## Regulatory\n- formatted one",
        0,
    )
    assert len(retried) == 1
    assert retried[0]["retry_count"] == 1


def test_worker_fallback_string_does_not_replace_document_after_retry(monkeypatch, notes_system):
    notes_system.context = "FDA review"
    notes_system.refresh_notes()
    original = notes_system.document_editor.toPlainText()
    monkeypatch.setattr("gui.notes_tab.QMessageBox.warning", lambda *args, **kwargs: None)
    notes_system._handle_note_formatted_safe(
        "Local AI's acting up—try again.",
        1,
        "Need to check section 5",
        "FDA review",
        original,
        1,
    )
    doc = notes_system.db.get_note_document("FDA review")
    assert (doc or {}).get("document_text", "") == original
    note_row = next(n for n in notes_system.db.notes if int(n["id"]) == 1)
    assert note_row["state"] == "error"


def test_export_notes_markdown_writes_file(monkeypatch, notes_system, tmp_path):
    notes_system.context = "FDA review"
    notes_system.refresh_notes()
    out = tmp_path / "notes_export.md"
    monkeypatch.setattr(
        "gui.notes_tab.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(out), "Markdown (*.md)"),
    )
    monkeypatch.setattr("gui.notes_tab.QMessageBox.information", lambda *args, **kwargs: None)
    notes_system.export_notes()
    assert out.exists()
    exported = out.read_text(encoding="utf-8")
    assert "# FDA review" in exported
    assert "formatted one" in exported

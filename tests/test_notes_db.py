from __future__ import annotations

import sqlite3

from core.db import DatabaseManager


def test_notes_draft_update_and_search(tmp_path):
    db = DatabaseManager()
    db.db_name = str(tmp_path / "test_notes.db")
    db.setup_db()

    note_id = db.create_note_draft(raw_note="raw thought about FDA", timestamp="2026-02-22 10:00:00", context="Project X")
    assert note_id > 0

    db.update_note_by_id(note_id, formatted_note="Formatted note about FDA guidance", state="ready", category="Regulatory")

    notes = db.list_notes(context="Project X", limit=10)
    assert any(n["id"] == note_id for n in notes)

    hits = db.search_notes(query="guidance", context="Project X", limit=10)
    assert any(n["id"] == note_id for n in hits)


def test_notes_pin_and_delete(tmp_path):
    db = DatabaseManager()
    db.db_name = str(tmp_path / "test_notes2.db")
    db.setup_db()

    note_id = db.create_note_draft(raw_note="hello world", timestamp="2026-02-22 10:00:00", context=None)
    db.update_note_by_id(note_id, state="ready")
    db.update_note_by_id(note_id, pinned=1)

    notes = db.list_notes(limit=10)
    row = next(n for n in notes if n["id"] == note_id)
    assert row["pinned"] == 1

    db.delete_note_by_id(note_id)
    notes2 = db.list_notes(limit=10)
    assert all(n["id"] != note_id for n in notes2)


def test_notes_documents_save_and_list(tmp_path):
    db = DatabaseManager()
    db.db_name = str(tmp_path / "test_notes_documents.db")
    db.setup_db()

    db.save_note_document(
        "Project X",
        document_text="## Regulatory\n- Review Section 5\n",
        source_note_count=2,
    )

    doc = db.get_note_document("Project X")
    assert doc is not None
    assert doc["context"] == "Project X"
    assert "Review Section 5" in doc["document_text"]

    docs = db.list_note_documents(limit=10)
    assert any(d["context"] == "Project X" for d in docs)


def test_list_notes_backfills_legacy_updated_at_column(tmp_path):
    db_path = tmp_path / "legacy_notes.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                formatted_note TEXT NOT NULL,
                category TEXT NOT NULL,
                context TEXT,
                raw_note TEXT,
                state TEXT NOT NULL DEFAULT 'ready',
                error_text TEXT,
                pinned INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO notes (formatted_note, category, context, raw_note, state, error_text, pinned, timestamp, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            ("Legacy note", "General", "Project X", "Legacy note", "ready", None, 0, "2026-03-10 10:00:00"),
        )
        conn.commit()

    db = DatabaseManager(db_name=str(db_path))
    notes = db.list_notes(limit=10)

    assert len(notes) == 1
    assert notes[0]["formatted_note"] == "Legacy note"
    assert "updated_at" in notes[0]


def test_legacy_ready_notes_backfill_to_context_document(tmp_path):
    db_path = tmp_path / "legacy_notes_docs.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                formatted_note TEXT NOT NULL,
                category TEXT NOT NULL,
                context TEXT,
                raw_note TEXT,
                state TEXT NOT NULL DEFAULT 'ready',
                error_text TEXT,
                pinned INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME
            )
            """
        )
        conn.execute(
            """
            INSERT INTO notes (formatted_note, category, context, raw_note, state, error_text, pinned, timestamp, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            ("Need to verify Section 5", "Regulatory", "Project X", "raw", "ready", None, 0, "2026-03-10 10:00:00"),
        )
        conn.commit()

    db = DatabaseManager(db_name=str(db_path))
    doc = db.get_note_document("Project X", create=False)

    assert doc is not None
    assert doc["context"] == "Project X"
    assert "## Regulatory" in doc["document_text"]
    assert "Need to verify Section 5" in doc["document_text"]


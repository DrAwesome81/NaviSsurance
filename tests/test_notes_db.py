from __future__ import annotations

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


import os
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from core.user_memory import build_user_memory_context, parse_teach_navi_command


def test_parse_teach_navi_command():
    assert parse_teach_navi_command("Teach Navi: I prefer concise bullets.") == "I prefer concise bullets."
    assert parse_teach_navi_command("hello") is None


def test_user_memory_add_search_recent_and_schema():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        import config as config_mod
        import core.db as core_db

        with patch.object(config_mod, "DATABASE_PATH", path):
            with patch.object(core_db, "DATABASE_PATH", path):
                db = core_db.DatabaseManager()
                assert db.current_schema_version >= 18

                mid = db.user_memory_add(
                    kind="preference",
                    content="Dr. Adam prefers concise bullets.",
                    source="teach_navi",
                    confidence=1.0,
                )
                assert mid

                hits = db.user_memory_search(query="concise bullets", limit=10)
                assert len(hits) >= 1
                assert any("concise bullets" in (row[2] or "").lower() for row in hits)

                recent = db.user_memory_recent(limit=5)
                assert recent
                assert recent[0][1] == "preference"

                with sqlite3.connect(path) as conn:
                    tables = {
                        row[0]
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
                        ).fetchall()
                    }
                assert "user_memory" in tables
                assert "user_memory_fts" in tables
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_build_user_memory_context_combines_search_and_recent():
    db = SimpleNamespace(
        user_memory_search=lambda **kw: [
            (1, "preference", "Prefer concise bullets.", "teach_navi", 1.0, None, "now", "now"),
        ],
        user_memory_recent=lambda **kw: [
            (2, "alias", "Q-sub means quality submission.", "auto_chat", 0.65, None, "now", "now"),
        ],
    )

    out = build_user_memory_context(db, "draft a reply", limit=5, recent_limit=2)

    assert "Relevant durable user memory" in out
    assert "Prefer concise bullets." in out
    assert "Q-sub means quality submission." in out


def test_user_memory_delete_removes_entry():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        import config as config_mod
        import core.db as core_db

        with patch.object(config_mod, "DATABASE_PATH", path):
            with patch.object(core_db, "DATABASE_PATH", path):
                db = core_db.DatabaseManager()
                mid = db.user_memory_add(
                    kind="fact",
                    content="Adam prefers local-first tools.",
                    source="teach_navi",
                )
                assert mid
                assert db.user_memory_delete(mid) is True
                assert not db.user_memory_recent(limit=10)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_user_memory_update_persists_changes():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        import config as config_mod
        import core.db as core_db

        with patch.object(config_mod, "DATABASE_PATH", path):
            with patch.object(core_db, "DATABASE_PATH", path):
                db = core_db.DatabaseManager()
                mid = db.user_memory_add(
                    kind="fact",
                    content="Adam prefers local-first tools.",
                    source="teach_navi",
                    confidence=1.0,
                )
                assert mid
                ok = db.user_memory_update(
                    mid,
                    kind="preference",
                    content="Adam prefers concise bullets.",
                    source="manual",
                    confidence=0.8,
                    json_data='{"edited": true}',
                )
                assert ok is True
                row = db.user_memory_recent(limit=1)[0]
                assert row[1] == "preference"
                assert row[2] == "Adam prefers concise bullets."
                assert row[3] == "manual"
                assert float(row[4]) == 0.8
                assert "edited" in (row[5] or "")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

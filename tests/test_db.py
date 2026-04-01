import os
import sqlite3
import tempfile
from unittest.mock import patch


def _db_for_temp_path(path: str):
    import config as config_mod
    import core.db as core_db

    with patch.object(config_mod, "DATABASE_PATH", path):
        with patch.object(core_db, "DATABASE_PATH", path):
            return core_db.DatabaseManager()


def test_current_schema_and_core_tables_exist():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        assert db.current_schema_version >= 22
        with sqlite3.connect(path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
                ).fetchall()
            }
        assert "user_memory" in tables
        assert "conversation_chunks" in tables
        assert "conversation_chunk_summaries" in tables
        assert "memory_reflections" in tables
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_save_message_and_search_conversations():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        db.save_message("main_session", "user", "Let's discuss Jeff Cunningham and the quote timeline.")
        db.save_message("main_session", "assistant", "We agreed to send Jeff the quote tomorrow morning.")

        rows = db.search_conversations("Jeff")
        assert len(rows) >= 1
        assert any("Jeff Cunningham" in str(content) for _role, content, _ts in rows)

        scoped = db.search_chat_history("main_session", "quote timeline", limit=5)
        assert len(scoped) >= 1
        assert any("quote" in str(content).lower() for _role, content, _ts in scoped)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_memory_reflection_round_trip():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        reflection_id = db.memory_reflection_upsert(
            scope="daily",
            reflection_key="2026-03-30",
            summary_text="Navi learned two durable preferences.",
            highlights_json=["Prefer concise bullets.", "Q-sub means quality submission."],
            source_counts_json={"approved_memory_rows": 2},
        )
        assert reflection_id > 0
        row = db.memory_reflection_get(scope="daily", reflection_key="2026-03-30")
        assert row is not None
        assert "durable preferences" in str(row.get("summary_text") or "").lower()
        recent = db.memory_reflection_recent(scope="daily", limit=5)
        assert len(recent) == 1
        assert recent[0]["id"] == reflection_id
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

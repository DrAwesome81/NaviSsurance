import os
import tempfile
from unittest.mock import patch


def test_cos_memory_add_and_search():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        import config as config_mod
        import core.db as core_db

        with patch.object(config_mod, "DATABASE_PATH", path):
            with patch.object(core_db, "DATABASE_PATH", path):
                db = core_db.DatabaseManager()

                mid = db.cos_memory_add(chat_id=1, kind="fact", content="Adam prefers deep work mornings.")
                assert mid

                rows = db.cos_memory_search(query="deep work", limit=10)
                assert len(rows) >= 1
                assert any("deep work" in (r[3] or "").lower() for r in rows)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


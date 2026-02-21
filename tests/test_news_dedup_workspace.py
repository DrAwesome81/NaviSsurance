import os
import sqlite3
import tempfile
from unittest.mock import patch


def test_store_news_item_dedups_tracking_params():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        import config as config_mod
        import core.db as core_db

        with patch.object(config_mod, "DATABASE_PATH", path):
            with patch.object(core_db, "DATABASE_PATH", path):
                db = core_db.DatabaseManager()

                ok1 = db.store_news_item(
                    "FDA issues draft guidance",
                    "summary",
                    "https://example.com/a?utm_source=x&gclid=1",
                    "Example",
                    "2026-02-21",
                )
                ok2 = db.store_news_item(
                    "FDA issues draft guidance",
                    "summary",
                    "https://example.com/a",
                    "Example",
                    "2026-02-21",
                )
                assert ok1 is True
                assert ok2 is False

                rows = db.get_recent_news(days=7)
                assert len(rows) == 1

                with sqlite3.connect(db.db_name) as conn:
                    (dedup_count,) = conn.execute("SELECT COUNT(*) FROM news_dedup").fetchone()
                # Two keys per item: URL-based key and title-based key
                assert dedup_count == 2
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_store_news_item_dedups_same_title_different_url():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        import config as config_mod
        import core.db as core_db

        with patch.object(config_mod, "DATABASE_PATH", path):
            with patch.object(core_db, "DATABASE_PATH", path):
                db = core_db.DatabaseManager()
                ok1 = db.store_news_item(
                    "FDA issues draft guidance on PCCP",
                    "summary",
                    "https://site-a.example.com/story",
                    "SiteA",
                    "2026-02-21",
                )
                ok2 = db.store_news_item(
                    "FDA issues draft guidance on PCCP",
                    "summary",
                    "https://site-b.example.com/story",
                    "SiteB",
                    "2026-02-21",
                )
                assert ok1 is True
                assert ok2 is False
                rows = db.get_recent_news(days=7)
                assert len(rows) == 1
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

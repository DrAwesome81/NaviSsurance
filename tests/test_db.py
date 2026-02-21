import sqlite3


def test_due_date_is_normalized_to_iso(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVISSURANCE_DB_PATH", str(tmp_path / "test.db"))

    from core.db import DatabaseManager

    db = DatabaseManager()
    db.add_task("S1", "Legacy date task", "02-21-2026")
    db.add_task("S1", "ISO date task", "2026-02-22")

    tasks = db.get_tasks()
    due_dates = [t[2] for t in tasks]
    assert "2026-02-21" in due_dates
    assert "2026-02-22" in due_dates


def test_archived_tasks_table_is_not_dropped_on_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVISSURANCE_DB_PATH", str(tmp_path / "test.db"))

    from core.db import DatabaseManager

    db1 = DatabaseManager()
    db1.archive_task("Archived", "2026-02-21", True)

    # New instance should not wipe archived_tasks
    db2 = DatabaseManager()

    with sqlite3.connect(db2.db_name) as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM archived_tasks").fetchone()
    assert count >= 1

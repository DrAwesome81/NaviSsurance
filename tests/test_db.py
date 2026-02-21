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


def test_archive_task_by_id_moves_row(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVISSURANCE_DB_PATH", str(tmp_path / "test.db"))

    from core.db import DatabaseManager

    db = DatabaseManager()
    db.add_task("S1", "To archive", "2026-02-21")
    task_id = db.get_tasks()[0][0]

    assert db.archive_task_by_id(task_id) is True
    assert db.archive_task_by_id(task_id) is False  # already gone

    with sqlite3.connect(db.db_name) as conn:
        (tasks_count,) = conn.execute("SELECT COUNT(*) FROM tasks WHERE id = ?", (task_id,)).fetchone()
        (archived_count,) = conn.execute("SELECT COUNT(*) FROM archived_tasks WHERE task = ?", ("To archive",)).fetchone()
    assert tasks_count == 0
    assert archived_count == 1

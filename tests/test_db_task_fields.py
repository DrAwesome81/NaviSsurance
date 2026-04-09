import sqlite3

from core.db import DatabaseManager, bump_task_due_date_mmddyyyy


def _task_columns(db_path: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("PRAGMA table_info(tasks)").fetchall()
    # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
    return {str(r[1]) for r in rows}


def test_tasks_schema_has_project_management_columns(tmp_path):
    db_path = str(tmp_path / "tasks_fields.db")
    db = DatabaseManager(db_name=db_path)
    cols = _task_columns(db.db_name)
    assert "start_date" in cols
    assert "estimate_minutes" in cols
    assert "blockers" in cols
    assert "depends_on_json" in cols


def test_add_update_list_tasks_roundtrip_new_fields(tmp_path):
    db_path = str(tmp_path / "tasks_fields_roundtrip.db")
    db = DatabaseManager(db_name=db_path)

    tid = db.add_task(
        session_id="t",
        task_text="Write protocol",
        due_date="03-20-2026",
        category="Business",
        recurrence="None",
        completed=0,
        start_date="03-10-2026",
        estimate_minutes=120,
        blockers="Waiting on client inputs",
        depends_on_json="[1, 2, 3]",
    )

    rows = db.list_tasks_rich(include_completed=True, include_snoozed=True, limit=50)
    r = next((x for x in rows if int(x.get("id") or 0) == int(tid)), None)
    assert r is not None
    assert (r.get("start_date") or "").strip() == "03-10-2026"
    assert int(r.get("estimate_minutes") or 0) == 120
    assert (r.get("blockers") or "").strip() == "Waiting on client inputs"
    assert (r.get("depends_on_json") or "").strip() == "[1, 2, 3]"

    db.update_task_by_id(
        int(tid),
        start_date="03-11-2026",
        estimate_minutes=45,
        blockers="",
        depends_on_json="[]",
    )

    rows2 = db.list_tasks_rich(include_completed=True, include_snoozed=True, limit=50)
    r2 = next((x for x in rows2 if int(x.get("id") or 0) == int(tid)), None)
    assert r2 is not None
    assert (r2.get("start_date") or "").strip() == "03-11-2026"
    assert int(r2.get("estimate_minutes") or 0) == 45
    # blockers is COALESCE'd to '' in list_tasks_rich
    assert (r2.get("blockers") or "") == ""
    assert (r2.get("depends_on_json") or "").strip() == "[]"


def test_add_task_defaults_new_fields_when_not_provided(tmp_path):
    db_path = str(tmp_path / "tasks_fields_defaults.db")
    db = DatabaseManager(db_name=db_path)

    tid = db.add_task(
        session_id="t",
        task_text="No extra fields",
        due_date="",
        category="Business",
        recurrence="None",
        completed=0,
    )

    rows = db.list_tasks_rich(include_completed=True, include_snoozed=True, limit=50)
    r = next((x for x in rows if int(x.get("id") or 0) == int(tid)), None)
    assert r is not None
    assert r.get("start_date") in (None, "")
    assert int(r.get("estimate_minutes") or 0) == 0
    assert (r.get("blockers") or "") == ""
    assert (r.get("depends_on_json") or "").strip() == "[]"


def test_bump_task_due_date_mmddyyyy():
    assert bump_task_due_date_mmddyyyy("04-07-2026", days=1) == "04-08-2026"
    assert bump_task_due_date_mmddyyyy("04-07-2026", days=3) == "04-10-2026"
    assert bump_task_due_date_mmddyyyy("12-31-2026", days=1) == "01-01-2027"


from __future__ import annotations

import json

from core.db import DatabaseManager


def test_tasks_rich_schema_and_filtering(tmp_path):
    db = DatabaseManager()
    db.db_name = str(tmp_path / "tasks_rich.db")
    db.setup_db()

    # Insert a few tasks using legacy add_task (should populate defaults)
    t1 = db.add_task("t", "Task A", "02-20-2026", category="Business")
    t2 = db.add_task("t", "Task B", None, category="Personal")
    assert int(t1) > 0 and int(t2) > 0

    # Enrich one task
    db.update_task_by_id(int(t2), priority=4, tags_json=json.dumps(["lead", "urgent"]), next_action_date="02-23-2026")

    rows = db.list_tasks_rich(include_completed=True, include_snoozed=True, limit=50)
    by_id = {int(r["id"]): r for r in rows}
    assert int(t2) in by_id
    assert int(by_id[int(t2)]["priority"]) == 4


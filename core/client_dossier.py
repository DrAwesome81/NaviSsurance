from __future__ import annotations

import json
from typing import Any

from core.db import DatabaseManager

# Column order must match DatabaseManager.cos_get_projects SELECT list.
_COS_PROJECT_ROW_KEYS = (
    "id",
    "name",
    "client",
    "description",
    "status",
    "priority",
    "deadline",
    "next_action",
    "blockers",
    "tags",
    "last_touched",
    "created_at",
    "updated_at",
    "notes",
    "blockers_json",
    "priority_tier",
    "suggested_next_action",
    "suggested_blockers_json",
    "suggested_priority_tier",
    "suggested_why",
    "suggested_at",
    "accepted_at",
    "client_id",
)


def _cos_project_row_to_dict(p: Any) -> dict[str, Any]:
    """cos_get_projects returns raw sqlite tuples; dossier code expects dict-like rows."""
    if isinstance(p, dict):
        return p
    if isinstance(p, (list, tuple)) and len(p) == len(_COS_PROJECT_ROW_KEYS):
        return dict(zip(_COS_PROJECT_ROW_KEYS, p))
    if isinstance(p, (list, tuple)) and len(p) > 0:
        return {"id": p[0]}
    return {}


def _parse_json_field(val: str | None) -> list | dict | None:
    if not val:
        return None
    try:
        return json.loads(val)
    except Exception:
        return val


def get_client_dossier_snapshot(
    db: DatabaseManager,
    client_id: int,
    *,
    memory_limit: int = 15,
    assignment_limit: int = 20,
    email_limit: int = 10,
    meeting_limit: int = 5,
    project_limit: int = 50,
) -> dict[str, Any]:
    """
    Build a unified dossier snapshot for a client.

    Uses existing normalized clients table and entity-linked memory.
    Assignments resolved via cos_projects.client_id → source_project_id.
    """
    cid = int(client_id)
    client = db.client_get(cid)
    if not client:
        return {"client_id": cid, "error": "client_not_found"}

    # Profile
    profile = {
        "id": client.get("id"),
        "name": client.get("name"),
        "aliases": _parse_json_field(client.get("aliases_json")) or [],
        "domain_rules": _parse_json_field(client.get("domain_rules_json")) or [],
        "notes": client.get("notes"),
        "is_active": bool(client.get("is_active", 1)),
    }

    # Memory (entity-linked)
    mem_rows = db.user_memory_search_by_entity(
        entity_type="client",
        entity_key=str(cid),
        approval_status="approved",
        limit=memory_limit,
    )
    memories = []
    for r in mem_rows:
        memories.append({
            "id": r[0],
            "kind": r[1],
            "content": r[2],
            "source": r[3],
            "confidence": r[4],
            "created_at": r[7],
        })

    # Projects for this client (DB returns tuples; normalize to dicts)
    raw_projects = db.cos_get_projects(client_id=cid) or []
    projects = [_cos_project_row_to_dict(p) for p in raw_projects]
    projects = [p for p in projects if p.get("id") is not None]
    if len(projects) > project_limit:
        projects = projects[:project_limit]
    project_ids = {int(p["id"]) for p in projects}

    # Assignments linked via source_project_id
    all_assignments = db.agent_list_assignments(limit=200) or []
    assignments = []
    for a in all_assignments:
        sp = a.get("source_project_id")
        if sp is not None and int(sp) in project_ids:
            assignments.append(a)
    if len(assignments) > assignment_limit:
        assignments = assignments[:assignment_limit]

    # Tasks linked via cos_project_id on tasks
    # Reuse get_tasks and filter (lightweight)
    try:
        all_tasks = db.get_tasks() or []
    except Exception:
        all_tasks = []
    tasks = []
    for t in all_tasks:
        pid = t.get("cos_project_id") if isinstance(t, dict) else None
        if pid is not None and int(pid) in project_ids:
            tasks.append(t)
    # Cap tasks too
    if len(tasks) > 50:
        tasks = tasks[:50]

    # Recent emails with direct client_id
    emails: list[dict] = []
    try:
        with __import__("sqlite3").connect(db.db_name) as conn:
            conn.row_factory = __import__("sqlite3").Row
            rows = conn.execute(
                """
                SELECT id, sender, subject, timestamp, content, replied, source, folder, account
                FROM emails
                WHERE client_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (cid, int(email_limit)),
            ).fetchall()
            emails = [dict(r) for r in rows]
    except Exception:
        emails = []

    # Recent meetings
    meetings: list[dict] = []
    try:
        with __import__("sqlite3").connect(db.db_name) as conn:
            conn.row_factory = __import__("sqlite3").Row
            rows = conn.execute(
                """
                SELECT id, meeting_date, meeting_with, notes, source, status
                FROM meeting_records
                WHERE client_id = ?
                ORDER BY meeting_date DESC
                LIMIT ?
                """,
                (cid, int(meeting_limit)),
            ).fetchall()
            meetings = [dict(r) for r in rows]
    except Exception:
        meetings = []

    return {
        "client_id": cid,
        "profile": profile,
        "memory": memories,
        "projects": projects,
        "tasks": tasks,
        "assignments": assignments,
        "recent_emails": emails,
        "recent_meetings": meetings,
    }

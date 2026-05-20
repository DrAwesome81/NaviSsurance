from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, UTC

from core.agent_execution import bootstrap_assignment_execution
from core.billing.autorun import next_autorun_date, run_monthly_autodraft, should_autorun
from core.chat_handler import ChatHandler
from core.db import DatabaseManager

logger = logging.getLogger(__name__)


def _json_payload(payload_json: str | None) -> dict:
    text = str(payload_json or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def enqueue_assignment_bootstrap(db: DatabaseManager, *, assignment_id: int, thread_id: int | None = None) -> int:
    return db.runtime_job_enqueue(
        job_type="assignment_bootstrap",
        payload_json={"assignment_id": int(assignment_id), "thread_id": int(thread_id) if thread_id is not None else None},
        priority=90,
        max_attempts=2,
        unique_key=f"assignment_bootstrap:{int(assignment_id)}",
    )


def enqueue_daily_briefing_refresh(db: DatabaseManager, *, run_at: str | None = None) -> int:
    key = f"daily_briefing_refresh:{datetime.now(UTC).strftime('%Y-%m-%d')}"
    return db.runtime_job_enqueue(
        job_type="daily_briefing_refresh",
        payload_json={},
        priority=40,
        max_attempts=2,
        run_at=run_at,
        unique_key=key,
    )


def enqueue_assignment_followup_scan(db: DatabaseManager, *, run_at: str | None = None) -> int:
    key = f"assignment_followup_scan:{datetime.now(UTC).strftime('%Y-%m-%dT%H')}"
    return db.runtime_job_enqueue(
        job_type="assignment_followup_scan",
        payload_json={},
        priority=30,
        max_attempts=1,
        run_at=run_at,
        unique_key=key,
    )


def enqueue_billing_autorun(db: DatabaseManager, *, run_at: str | None = None) -> int:
    target = next_autorun_date(db)
    if run_at is None:
        run_at = f"{target.strftime('%Y-%m-%d')}T12:00:00Z"
    key = f"billing_autorun:{target.strftime('%Y-%m')}"
    return db.runtime_job_enqueue(
        job_type="billing_autorun",
        payload_json={},
        priority=20,
        max_attempts=1,
        run_at=run_at,
        unique_key=key,
    )


def enqueue_intel_monitoring(db: DatabaseManager, *, run_at: str | None = None) -> int:
    """Enqueue a periodic Intel / Pulse monitoring cycle."""
    # Run every 2 hours by default (can be made configurable later)
    if run_at is None:
        now = datetime.now(UTC)
        run_at = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    key = f"intel_monitoring:{datetime.now(UTC).strftime('%Y-%m-%dT%H')}"
    return db.runtime_job_enqueue(
        job_type="intel_monitoring",
        payload_json={},
        priority=25,
        max_attempts=2,
        run_at=run_at,
        unique_key=key,
    )


def _handle_assignment_bootstrap(db: DatabaseManager, payload: dict) -> dict:
    assignment_id = int(payload.get("assignment_id") or 0)
    thread_id = payload.get("thread_id")
    if assignment_id <= 0:
        return {"ok": False, "reason": "missing_assignment_id"}
    out = bootstrap_assignment_execution(
        db,
        assignment_id=assignment_id,
        thread_id=int(thread_id) if thread_id is not None else None,
    )
    return {"ok": True, "result": out}


def _handle_daily_briefing_refresh(db: DatabaseManager, payload: dict) -> dict:
    _ = payload
    handler = ChatHandler(None, db=db)
    briefing = handler.daily_briefing()
    return {"ok": True, "briefing_chars": len(str(briefing or ""))}


def _handle_assignment_followup_scan(db: DatabaseManager, payload: dict) -> dict:
    _ = payload
    rows = db.agent_list_assignments(limit=500)
    nudged = 0
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=24)
    for row in rows:
        status = str(row.get("status") or "").strip().lower()
        if status not in {"queued", "in_progress", "blocked", "awaiting_review"}:
            continue
        due_date = str(row.get("due_date") or "").strip()
        overdue = False
        if due_date:
            try:
                overdue = datetime.strptime(due_date, "%Y-%m-%d").date() <= now.date()
            except Exception:
                overdue = False
        if not overdue and status not in {"blocked", "awaiting_review"}:
            continue
        events = db.agent_get_assignment_events(assignment_id=int(row.get("id") or 0), limit=20)
        recent_nudge = False
        for event in events:
            if str(event.get("event_type") or "") != "runtime_nudge":
                continue
            created = str(event.get("created_at") or "").strip()
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except Exception:
                continue
            if created_dt >= cutoff:
                recent_nudge = True
                break
        if recent_nudge:
            continue
        note = "Runtime follow-up: assignment is overdue or waiting for attention."
        db.agent_add_event(
            assignment_id=int(row.get("id") or 0),
            event_type="runtime_nudge",
            actor_code="navi",
            note=note,
        )
        nudged += 1
    return {"ok": True, "nudged": nudged}


def _handle_billing_autorun(db: DatabaseManager, payload: dict) -> dict:
    _ = payload
    if not should_autorun(db):
        return {"ok": True, "ran": False, "reason": "not_due"}
    result = run_monthly_autodraft(db)
    return {
        "ok": True,
        "ran": bool(getattr(result, "ran", False)),
        "draft_ids": list(getattr(result, "draft_ids", []) or []),
        "notes": str(getattr(result, "notes", "") or ""),
    }


def _handle_intel_monitoring(db: DatabaseManager, payload: dict) -> dict:
    """Run a monitoring cycle for the Intel (Pulse) agent. (Phase 2 Intelligence & Coordination COMPLETE: private theme reflections active + matured raising + cross-links; [Security-Relevant] tags now feed Shield.)"""
    _ = payload
    try:
        from core.intel import IntelService
        intel = IntelService(db)

        # Run the actual monitoring logic defined in IntelService
        result = intel.run_monitoring_cycle()

        return {
            "ok": True,
            **result
        }
    except Exception as e:
        logger.exception("Intel monitoring failed: %s", e)
        return {"ok": False, "error": str(e)}


JOB_HANDLERS = {
    "assignment_bootstrap": _handle_assignment_bootstrap,
    "daily_briefing_refresh": _handle_daily_briefing_refresh,
    "assignment_followup_scan": _handle_assignment_followup_scan,
    "billing_autorun": _handle_billing_autorun,
    "intel_monitoring": _handle_intel_monitoring,
}


def execute_runtime_job(db: DatabaseManager, *, job_type: str, payload_json: str | None) -> dict:
    handler = JOB_HANDLERS.get(str(job_type or "").strip())
    if handler is None:
        raise ValueError(f"Unknown runtime job type: {job_type}")
    payload = _json_payload(payload_json)
    logger.info("RUNTIME_JOB_EXECUTE type=%s payload_keys=%s", job_type, sorted(payload.keys()))
    return handler(db, payload)

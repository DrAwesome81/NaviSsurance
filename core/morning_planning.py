"""
Morning Planning orchestrator (replaces legacy daily briefing).

Reuses AM Sweep context gathering and produces a structured daily plan
with proposed time blocks (ADD_CAL_BLOCK), triage, and agent actions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any

from core.db import DatabaseManager
from core.chief_of_staff_service import cos_am_sweep, _now_local


def run_morning_planning(
    db: DatabaseManager,
    *,
    force: bool = False,
    chat_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run the morning planning sweep.

    Returns a dict with keys:
      - summary: str
      - proposed_blocks: list
      - triage: dict
      - raw_output: str
      - plan_date: str
    """
    now = _now_local()
    plan_date = now.strftime("%Y-%m-%d")

    # Reuse the existing AM Sweep for rich context + action parsing
    raw = cos_am_sweep(db, conversation_history=None, chat_id=chat_id) or ""

    # For MVP we treat the raw CoS output as the plan.
    # Later phases will parse time blocks and build structured plan_json.
    result = {
        "plan_date": plan_date,
        "raw_output": raw,
        "summary": raw[:800] if raw else "No plan generated.",
        "proposed_blocks": [],
        "triage": {"Dispatch": [], "Prep": [], "Yours": [], "Skip": []},
    }

    # Persist basic record (plan_json can be extended later)
    db.save_daily_plan(plan_date, {
        "status": "proposed",
        "plan_json": None,
        "visual_html": None,
    })

    return result

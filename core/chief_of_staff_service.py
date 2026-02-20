"""
Chief of Staff service: plain-text in, plain-text out.
Supports multi-turn; can read dashboard tasks and add tasks via ADD_TASK lines in the response.
"""

import json
import logging
import re
from datetime import datetime
from typing import List, Tuple

from core.db import DatabaseManager
from core.grok_client import grok_completion, grok_completion_messages, MODEL_COS

logger = logging.getLogger(__name__)

# Pattern for CoS to add a task: ADD_TASK: text | due_date (MM-DD-YYYY or none) | category (Business or Personal)
ADD_TASK_PATTERN = re.compile(r"ADD_TASK:\s*(.+?)\s*\|\s*([^|]+?)\s*\|\s*(Business|Personal)", re.IGNORECASE)


def _now_local():
    return datetime.now()


def _tasks_context(db: DatabaseManager) -> str:
    """Format current dashboard tasks for CoS context. Uses same list as dashboard (all, no date filter)."""
    try:
        tasks = db.get_tasks(category=None, date_filter=None, specific_date=None)
        if not tasks:
            return "**Dashboard tasks:** (none)"
        lines = []
        for task_id, task_text, due_date, category, recurrence, completed in tasks:
            done = " [DONE]" if completed else ""
            due = f" due {due_date}" if due_date else ""
            lines.append(f"- {task_text}{due} ({category}){done}")
        return "**Dashboard tasks:**\n" + "\n".join(lines[:50])  # cap at 50
    except Exception as e:
        logger.warning("Could not load tasks for CoS context: %s", e)
        return "**Dashboard tasks:** (unable to load)"


def _preferences_context(prefs_row) -> str:
    if not prefs_row:
        return ""
    operating_system_md, blocked_times_json, deep_work_hours, behavior_prefs_json, _ = prefs_row
    parts = []
    if operating_system_md:
        parts.append("Operating system / constraints:\n" + operating_system_md)
    if blocked_times_json:
        try:
            blocks = json.loads(blocked_times_json)
            parts.append("Blocked times (recurring): " + json.dumps(blocks))
        except Exception:
            parts.append("Blocked times: " + blocked_times_json)
    if deep_work_hours is not None:
        parts.append(f"Default deep work hours per day: {deep_work_hours}")
    if behavior_prefs_json:
        try:
            prefs = json.loads(behavior_prefs_json)
            parts.append("Behavior prefs: " + json.dumps(prefs))
        except Exception:
            parts.append("Behavior prefs: " + behavior_prefs_json)
    return "\n\n".join(parts) if parts else ""


def cos_response(
    db: DatabaseManager,
    user_message: str,
    conversation_history: List[Tuple[str, str]] = None,
) -> str:
    """
    Chief of Staff: you say what you're working on and what's come up; model responds.
    If conversation_history is provided (list of (role, content)), uses multi-turn context.
    """
    now = _now_local()
    today = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    prefs = db.cos_get_preferences()
    prefs_ctx = _preferences_context(prefs)

    tasks_ctx = _tasks_context(db)
    system = """You are an AI Chief of Staff for Adam. He tells you in plain text what he's working on and what has come up that needs to be dealt with. You help him plan, prioritize, and reduce cognitive load. You respect his constraints: time freedom, low context switching, family boundaries. You give direct, concise advice and challenge assumptions when useful. You do not take autonomous actions—only recommend and advise. Respond in whatever form is most helpful; no required format.

You can see his current dashboard task list and may add tasks to it. To add a task, write one or more lines in this exact format (one task per line):
ADD_TASK: <task description> | <due date as MM-DD-YYYY or "none"> | <Business or Personal>
Example: ADD_TASK: Send follow-up to client | 02-25-2026 | Business
Omit ADD_TASK lines if you are not adding any tasks."""

    if not conversation_history or len(conversation_history) == 0:
        # Single turn
        user = f"""Today is {today}, current time {time_str} (user's local time)."""
        if prefs_ctx:
            user += f"""

**His stated preferences / constraints (optional context):**
{prefs_ctx}"""
        user += f"""

{tasks_ctx}

**What he says (main input):**
{user_message or "What should I focus on right now?"}"""
        try:
            out = grok_completion(system, user, model=MODEL_COS)
            return _parse_and_add_tasks(db, out)
        except Exception as e:
            logger.exception("CoS response failed: %s", e)
            return f"Error: {e}"

    # Multi-turn: build messages list. Caller must have saved the current user message and included it in conversation_history.
    time_ctx = f"Today is {today}, current time {time_str} (user's local time)."
    if prefs_ctx:
        time_ctx += f"\n\n**His stated preferences / constraints:**\n{prefs_ctx}"
    time_ctx += f"\n\n{tasks_ctx}"
    messages = [{"role": "system", "content": system + "\n\n" + time_ctx}]
    for role, content in conversation_history:
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    try:
        out = grok_completion_messages(messages, model=MODEL_COS)
        return _parse_and_add_tasks(db, (out or "").strip())
    except Exception as e:
        logger.exception("CoS response failed: %s", e)
        return f"Error: {e}"


def _parse_and_add_tasks(db: DatabaseManager, response: str) -> str:
    """Parse ADD_TASK lines from the model response, insert tasks into the dashboard task list, return cleaned response."""
    if not response:
        return response
    session_id = f"dashboard_cos_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    added = 0
    cleaned_lines = []
    for line in response.splitlines():
        m = ADD_TASK_PATTERN.search(line.strip())
        if m:
            task_text = m.group(1).strip()
            due_part = m.group(2).strip().lower()
            category = m.group(3).strip()
            due_date = None if due_part == "none" or not due_part else due_part
            # Normalize to MM-DD-YYYY if we got YYYY-MM-DD
            if due_date and len(due_date) == 10 and due_date[4] == "-":
                parts = due_date.split("-")
                if len(parts) == 3:
                    due_date = f"{parts[1]}-{parts[2]}-{parts[0]}"
            try:
                db.add_task(
                    session_id=session_id,
                    task_text=task_text,
                    due_date=due_date or "",
                    category=category,
                    recurrence="None",
                    completed=0,
                )
                added += 1
            except Exception as e:
                logger.warning("CoS add_task failed: %s", e)
            continue
        cleaned_lines.append(line)
    out = "\n".join(cleaned_lines).strip()
    if added:
        out += f"\n\n— *Added {added} task(s) to your dashboard.*"
    return out

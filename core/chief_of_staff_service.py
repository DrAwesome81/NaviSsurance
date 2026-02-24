"""
Chief of Staff service: plain-text in, plain-text out.
Supports multi-turn; can read dashboard tasks and add tasks via ADD_TASK lines in the response.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional

from core.db import DatabaseManager
from core.grok_client import (
    grok_completion,
    grok_completion_messages,
    grok_web_search,
    grok_available,
    MODEL_COS,
    MODEL_FAST,
)
from core.cos_calendar import (
    calendar_available,
    create_calendar_event,
    format_events_brief,
    get_calendar_events,
)
from core.cos_doc_search import doc_search, format_hits

logger = logging.getLogger(__name__)

# Pattern for CoS to add a task: ADD_TASK: text | due_date (MM-DD-YYYY or none) | category (Business or Personal)
ADD_TASK_PATTERN = re.compile(r"ADD_TASK:\s*(.+?)\s*\|\s*([^|]+?)\s*\|\s*(Business|Personal)", re.IGNORECASE)
# Pattern for CoS to schedule a calendar block:
# ADD_CAL_BLOCK: title | start_datetime | end_datetime | optional_calendar_id
ADD_CAL_BLOCK_PATTERN = re.compile(
    r"ADD_CAL_BLOCK:\s*(.+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)(?:\s*\|\s*([^|]+?)\s*)?$",
    re.IGNORECASE,
)
# Pattern for CoS delegation action:
# ASSIGN: agent | title | brief | P1..P5 | due_date_or_none
ASSIGN_PATTERN = re.compile(r"^\s*ASSIGN:\s*(.+?)\s*$", re.IGNORECASE)
# Pattern for CoS assignment status updates:
# UPDATE_ASSIGNMENT_STATUS: assignment_ref | status | optional_note
UPDATE_ASSIGNMENT_STATUS_PATTERN = re.compile(
    r"^\s*UPDATE_ASSIGNMENT_STATUS:\s*(.+?)\s*$", re.IGNORECASE
)
# Pattern for CoS assignment reassignment:
# REASSIGN: assignment_ref | assignee_name | optional_note
REASSIGN_PATTERN = re.compile(r"^\s*REASSIGN:\s*(.+?)\s*$", re.IGNORECASE)
# Pattern for CoS assignment summary updates:
# UPDATE_ASSIGNMENT_SUMMARY: assignment_ref | summary markdown
UPDATE_ASSIGNMENT_SUMMARY_PATTERN = re.compile(
    r"^\s*UPDATE_ASSIGNMENT_SUMMARY:\s*(.+?)\s*$", re.IGNORECASE
)
# Pattern for CoS assignment priority updates:
# UPDATE_ASSIGNMENT_PRIORITY: assignment_ref | P1..P5 | optional_note
UPDATE_ASSIGNMENT_PRIORITY_PATTERN = re.compile(
    r"^\s*UPDATE_ASSIGNMENT_PRIORITY:\s*(.+?)\s*$", re.IGNORECASE
)
# Pattern for CoS assignment due-date updates:
# UPDATE_ASSIGNMENT_DUE: assignment_ref | YYYY-MM-DD or none | optional_note
UPDATE_ASSIGNMENT_DUE_PATTERN = re.compile(
    r"^\s*UPDATE_ASSIGNMENT_DUE:\s*(.+?)\s*$", re.IGNORECASE
)
# Pattern for CoS assignment retitle:
# RETITLE_ASSIGNMENT: assignment_ref | new_title | optional_note
RETITLE_ASSIGNMENT_PATTERN = re.compile(
    r"^\s*RETITLE_ASSIGNMENT:\s*(.+?)\s*$", re.IGNORECASE
)
# Pattern for CoS assignment brief updates:
# UPDATE_ASSIGNMENT_BRIEF: assignment_ref | new_brief_markdown | optional_note
UPDATE_ASSIGNMENT_BRIEF_PATTERN = re.compile(
    r"^\s*UPDATE_ASSIGNMENT_BRIEF:\s*(.+?)\s*$", re.IGNORECASE
)
# Pattern for CoS bulk assignment status updates:
# BULK_UPDATE_ASSIGNMENT_STATUS: status | assignee_name_or_all | optional_open_or_all | optional_note
BULK_UPDATE_ASSIGNMENT_STATUS_PATTERN = re.compile(
    r"^\s*BULK_UPDATE_ASSIGNMENT_STATUS:\s*(.+?)\s*$", re.IGNORECASE
)
# Pattern for CoS bulk assignment priority updates:
# BULK_UPDATE_ASSIGNMENT_PRIORITY: P1..P5 | assignee_name_or_all | optional_open_or_all | optional_note
BULK_UPDATE_ASSIGNMENT_PRIORITY_PATTERN = re.compile(
    r"^\s*BULK_UPDATE_ASSIGNMENT_PRIORITY:\s*(.+?)\s*$", re.IGNORECASE
)
# Pattern for CoS bulk assignment due updates:
# BULK_UPDATE_ASSIGNMENT_DUE: YYYY-MM-DD_or_none | assignee_name_or_all | optional_open_or_all | optional_note
BULK_UPDATE_ASSIGNMENT_DUE_PATTERN = re.compile(
    r"^\s*BULK_UPDATE_ASSIGNMENT_DUE:\s*(.+?)\s*$", re.IGNORECASE
)
# Pattern for CoS bulk reassignment:
# BULK_REASSIGN_ASSIGNMENTS: from_assignee_or_all | to_assignee | optional_open_or_all | optional_note
BULK_REASSIGN_ASSIGNMENTS_PATTERN = re.compile(
    r"^\s*BULK_REASSIGN_ASSIGNMENTS:\s*(.+?)\s*$", re.IGNORECASE
)
# Pattern for CoS assignment artifact creation:
# ADD_ASSIGNMENT_ARTIFACT: assignment_ref | artifact_type | title | content_markdown
ADD_ASSIGNMENT_ARTIFACT_PATTERN = re.compile(
    r"^\s*ADD_ASSIGNMENT_ARTIFACT:\s*(.+?)\s*$", re.IGNORECASE
)
# Pattern for CoS conversion of assignment into dashboard task:
# ADD_TASK_FROM_ASSIGNMENT: assignment_ref | due_date_mmddyyyy_or_none | Business|Personal
ADD_TASK_FROM_ASSIGNMENT_PATTERN = re.compile(
    r"^\s*ADD_TASK_FROM_ASSIGNMENT:\s*(.+?)\s*$",
    re.IGNORECASE,
)
# Pattern for dashboard tasks that are derived from assignments:
# [A-0007] Task title
ASSIGNMENT_TASK_REF_PATTERN = re.compile(r"^\s*\[A-(\d{1,10})\]", re.IGNORECASE)
# Pattern for CoS bulk conversion of assignments into dashboard tasks:
# BULK_ADD_TASKS_FROM_ASSIGNMENTS: assignee_name_or_all | Business|Personal | optional_open_or_all
BULK_ADD_TASKS_FROM_ASSIGNMENTS_PATTERN = re.compile(
    r"^\s*BULK_ADD_TASKS_FROM_ASSIGNMENTS:\s*(.+?)\s*$",
    re.IGNORECASE,
)

# CoS tool triggers (tool loop)
WEB_SEARCH_TRIGGER = re.compile(r"^\s*WEB_SEARCH:\s*(.+?)\s*$", re.IGNORECASE)
DOC_SEARCH_TRIGGER = re.compile(r"^\s*DOC_SEARCH:\s*(.+?)\s*$", re.IGNORECASE)
MEMORY_SEARCH_TRIGGER = re.compile(r"^\s*MEMORY_SEARCH:\s*(.+?)\s*$", re.IGNORECASE)


def _now_local():
    return datetime.now()


def _parse_calendar_datetime(value: str) -> Optional[datetime]:
    """
    Parse common datetime inputs and return timezone-aware datetime when possible.
    Accepted examples:
    - 2026-02-25T13:00:00-05:00
    - 2026-02-25T13:00
    - 2026-02-25 1:00 PM
    - 02-25-2026 13:00
    """
    s = (value or "").strip().strip('"').strip("'")
    if not s:
        return None

    local_tz = datetime.now().astimezone().tzinfo or timezone.utc

    # Handle UTC "Z" suffix explicitly because fromisoformat expects "+00:00".
    if s.endswith("Z"):
        try:
            return datetime.fromisoformat(s[:-1] + "+00:00")
        except Exception:
            pass

    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=local_tz)
        return dt
    except Exception:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M %p",
        "%m-%d-%Y %H:%M",
        "%m-%d-%Y %I:%M %p",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=local_tz)
        except Exception:
            continue

    return None


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


def _assignments_context(db: DatabaseManager) -> str:
    """Format open delegation assignments for CoS context."""
    try:
        rows = db.agent_list_assignments(limit=300)
        if not rows:
            return "**Delegated assignments:** (none)"
        open_rows = []
        for r in rows:
            st = str(r.get("status") or "").strip().lower()
            if st in {"done", "cancelled"}:
                continue
            open_rows.append(r)
        if not open_rows:
            return "**Delegated assignments:** (all closed)"

        lines = []
        for r in open_rows[:60]:
            aid = int(r.get("id") or 0)
            title = str(r.get("title") or "Untitled")
            assignee = str(r.get("assignee_code") or "agent")
            st = str(r.get("status") or "queued")
            pr = int(r.get("priority") or 3)
            due = str(r.get("due_date") or "")
            due_part = f" due {due}" if due else ""
            lines.append(f"- A-{aid:04d} [{st}] P{pr} {title} -> {assignee}{due_part}")
        return "**Delegated assignments (open):**\n" + "\n".join(lines)
    except Exception as e:
        logger.warning("Could not load assignments for CoS context: %s", e)
        return "**Delegated assignments:** (unable to load)"


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


def _calendar_context() -> str:
    """
    Read-only calendar context. Avoids triggering OAuth flows by requiring an existing token file.
    """
    ok, msg = calendar_available()
    if not ok:
        return "**Calendar:** (unavailable) " + msg

    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    week_end = today + timedelta(days=7)
    time_min_today = today.strftime("%Y-%m-%dT%H:%M:%SZ")
    time_max_today = tomorrow.strftime("%Y-%m-%dT%H:%M:%SZ")
    time_min_week = today.strftime("%Y-%m-%dT%H:%M:%SZ")
    time_max_week = week_end.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        todays = get_calendar_events(time_min=time_min_today, time_max=time_max_today)
        upcoming = get_calendar_events(time_min=time_min_week, time_max=time_max_week)
        return (
            "**Calendar (today):**\n"
            + format_events_brief(todays, tz=timezone.utc)
            + "\n\n**Calendar (next 7 days):**\n"
            + format_events_brief(upcoming, tz=timezone.utc)
        )
    except Exception as e:
        return "**Calendar:** (error loading) " + str(e)


def _memory_context(db: DatabaseManager, user_message: str, chat_id: Optional[int]) -> str:
    """
    Retrieve relevant memory (structured + raw conversation) to ground responses.
    """
    q = (user_message or "").strip()
    if not q:
        return ""
    parts = []
    try:
        mem_rows = db.cos_memory_search(query=q, chat_id=chat_id, limit=6)
    except Exception:
        mem_rows = []
    if mem_rows:
        lines = []
        for _id, _chat_id, kind, content, _json_data, created_at in mem_rows[:6]:
            lines.append(f"- ({kind}) {content}")
        parts.append("**Relevant memory (structured):**\n" + "\n".join(lines))

    # Also pull raw conversation snippets (across all sessions)
    try:
        conv_rows = db.search_conversations(q)[:6]
    except Exception:
        conv_rows = []
    if conv_rows:
        lines = []
        for role, content, ts in conv_rows[:6]:
            excerpt = (content or "").strip()
            if len(excerpt) > 180:
                excerpt = excerpt[:177] + "..."
            lines.append(f"- ({role}) {excerpt}")
        parts.append("**Relevant past chat snippets (FTS):**\n" + "\n".join(lines))

    return "\n\n".join(parts)


def _extract_and_store_memory(db: DatabaseManager, *, chat_id: Optional[int], user_message: str, assistant_message: str) -> None:
    ok, _msg = grok_available()
    if not ok:
        return
    try:
        system = (
            "You extract durable memory for a Chief of Staff assistant. "
            "Return ONLY valid JSON. No markdown."
        )
        user = f"""
Extract durable memory items from the interaction.

Input:
- user_message: {user_message}
- assistant_message: {assistant_message}

Return JSON with keys:
- summary: string (1-2 sentences)
- facts: [string] (stable facts/preferences/relationships)
- tags: [string] (projects, people, topics)
- open_loops: [string] (unfinished commitments/questions)
- decisions: [string] (explicit decisions)

Hard rules:
- Do not invent facts not present.
- Keep each item short.
""".strip()
        raw = grok_completion(system, user, model=MODEL_FAST)
        if not raw:
            return
        data = json.loads(raw)
        items = []
        summary = (data.get("summary") or "").strip()
        if summary:
            items.append({"kind": "summary", "content": summary, "json_data": data})
        for k in ("facts", "tags", "open_loops", "decisions"):
            arr = data.get(k) or []
            if isinstance(arr, list):
                for s in arr[:15]:
                    ss = str(s).strip()
                    if ss:
                        items.append({"kind": k[:-1] if k.endswith("s") else k, "content": ss})
        if items:
            db.cos_memory_add_many(chat_id=chat_id, items=items)
    except Exception:
        return


def _parse_assignment_ref(value: str) -> Optional[int]:
    """Parse assignment reference forms like 'A-0007', '7', or 'assignment A-0007'."""
    s = (value or "").strip().upper()
    if not s:
        return None
    m = re.match(r"^A-(\d+)$", s)
    if m:
        try:
            aid = int(m.group(1))
            return aid if aid > 0 else None
        except Exception:
            return None
    if s.isdigit():
        try:
            aid = int(s)
            return aid if aid > 0 else None
        except Exception:
            return None
    # More forgiving parsing for natural command strings.
    m_any = re.search(r"\bA-(\d+)\b", s)
    if m_any:
        try:
            aid = int(m_any.group(1))
            return aid if aid > 0 else None
        except Exception:
            return None
    m_num = re.search(r"\b(\d{1,9})\b", s)
    if m_num:
        try:
            aid = int(m_num.group(1))
            return aid if aid > 0 else None
        except Exception:
            return None
    return None


def _normalize_assignment_status(value: str) -> str:
    """Normalize common status variants to canonical assignment states."""
    s = (value or "").strip().lower()
    if not s:
        return ""
    normalized = s.replace("-", "_").replace(" ", "_")
    aliases = {
        "queue": "queued",
        "queued": "queued",
        "backlog": "queued",
        "in_progress": "in_progress",
        "progress": "in_progress",
        "started": "in_progress",
        "doing": "in_progress",
        "awaiting_review": "awaiting_review",
        "awaitingreview": "awaiting_review",
        "review": "awaiting_review",
        "for_review": "awaiting_review",
        "blocked": "blocked",
        "block": "blocked",
        "done": "done",
        "complete": "done",
        "completed": "done",
        "cancel": "cancelled",
        "canceled": "cancelled",
        "cancelled": "cancelled",
    }
    return aliases.get(normalized, normalized)


def _parse_priority_value(value: str) -> Optional[int]:
    """Parse priority input like P1 or 1 into 1..5."""
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return None
    try:
        p = int(digits)
    except Exception:
        return None
    if p < 1:
        p = 1
    if p > 5:
        p = 5
    return p


def _normalize_due_date_input(value: str) -> tuple[bool, Optional[str]]:
    """
    Parse due-date input into canonical storage form.
    Returns (ok, due_date_or_none). Accepts:
    - YYYY-MM-DD
    - MM-DD-YYYY
    - none/null/n/a/blank -> None
    """
    raw = (value or "").strip()
    if not raw or raw.lower() in {"none", "null", "n/a"}:
        return True, None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return True, raw
    if re.match(r"^\d{2}-\d{2}-\d{4}$", raw):
        mm, dd, yyyy = raw.split("-")
        return True, f"{yyyy}-{mm}-{dd}"
    return False, None


def _resolve_bulk_scope(db: DatabaseManager, scope_raw: str) -> tuple[bool, Optional[str], str]:
    """
    Resolve a bulk-update scope value into (ok, assignee_code_or_none, display_label).
    - "all" or "*" => assignee_code None
    - agent name/alias => concrete assignee_code
    """
    scope = (scope_raw or "").strip()
    if not scope or scope.lower() in {"all", "*"}:
        return True, None, "all"
    agent = db.agent_resolve_by_name(scope)
    if not agent:
        return False, None, scope
    assignee_code = str(agent.get("code") or "").strip().lower()
    label = str(agent.get("display_name") or assignee_code).strip()
    return bool(assignee_code), assignee_code or None, label or scope


def _parse_bulk_mode_value(value: str) -> Optional[str]:
    """Parse bulk command mode token into canonical 'open' or 'all'."""
    raw = (value or "").strip().lower()
    if raw in {"", "all", "*", "include_closed", "with_closed", "closed"}:
        return "all"
    if raw in {"open", "open_only", "active", "pending"}:
        return "open"
    return None


def _parse_bulk_mode_and_note(parts: list[str], *, start_index: int = 2) -> tuple[bool, str, Optional[str]]:
    """
    Parse optional bulk mode + optional note with backward compatibility.
    Examples:
    - [..., "<note>"] -> mode='all', note=<note>
    - [..., "open"] -> mode='open', note=None
    - [..., "open", "<note>"] -> mode='open', note=<note>
    Returns (ok, mode, note).
    """
    mode = "all"
    note: Optional[str] = None
    if len(parts) <= start_index:
        return True, mode, note

    token = (parts[start_index] or "").strip()
    if len(parts) == (start_index + 1):
        parsed = _parse_bulk_mode_value(token)
        if parsed is None:
            note = token or None
        else:
            mode = parsed
        return True, mode, note

    parsed = _parse_bulk_mode_value(token)
    if parsed is None:
        return False, mode, note
    mode = parsed
    note = (parts[start_index + 1] or "").strip() or None
    return True, mode, note


def cos_response(
    db: DatabaseManager,
    user_message: str,
    conversation_history: List[Tuple[str, str]] = None,
    chat_id: Optional[int] = None,
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
    assignments_ctx = _assignments_context(db)
    cal_ctx = _calendar_context()
    mem_ctx = _memory_context(db, user_message, chat_id)

    system = """You are an AI Chief of Staff for Adam. He tells you in plain text what he's working on and what has come up that needs to be dealt with. You help him plan, prioritize, and reduce cognitive load. You respect his constraints: time freedom, low context switching, family boundaries. You give direct, concise advice and challenge assumptions when useful. You do not take autonomous actions—only recommend and advise. Respond in whatever form is most helpful; no required format.

You can see his current dashboard task list and may add tasks to it. To add a task, write one or more lines in this exact format (one task per line):
ADD_TASK: <task description> | <due date as MM-DD-YYYY or "none"> | <Business or Personal>
Example: ADD_TASK: Send follow-up to client | 02-25-2026 | Business
Omit ADD_TASK lines if you are not adding any tasks.

You may also schedule calendar blocks when he explicitly asks for it. To schedule a block, write one or more lines in this exact format (one block per line):
ADD_CAL_BLOCK: <title> | <start datetime> | <end datetime> | <calendar id or "primary">
Example: ADD_CAL_BLOCK: Deep work - client report | 2026-02-25T13:00:00-05:00 | 2026-02-25T14:30:00-05:00 | primary
Prefer ISO-8601 datetimes with timezone offsets.
Omit ADD_CAL_BLOCK lines if you are not scheduling calendar blocks.

You may also delegate work to named team members by writing one or more lines in this exact format:
ASSIGN: <AgentName> | <Title> | <Brief> | <P1-P5> | <YYYY-MM-DD or none>
Example: ASSIGN: Atlas | FDA PCCP research brief | Research latest guidance and summarize with citations. | P1 | 2026-03-01
Available agent names: Atlas, Quill, Sentinel, Lex, Scout, Mason, Ledger, Archive, Pulse, Shield.
Omit ASSIGN lines if you are not delegating work.

You may update assignment status:
UPDATE_ASSIGNMENT_STATUS: <A-0007 or 7> | <queued|in_progress|awaiting_review|blocked|done|cancelled> | <optional note>
Example: UPDATE_ASSIGNMENT_STATUS: A-0007 | in_progress | Atlas has started.
Omit UPDATE_ASSIGNMENT_STATUS lines if you are not changing assignment status.

You may bulk-update assignment status:
BULK_UPDATE_ASSIGNMENT_STATUS: <status> | <AgentName or all> | <open or all (optional)> | <optional note>
Example: BULK_UPDATE_ASSIGNMENT_STATUS: blocked | Atlas | open | Waiting on input.
This updates matching assignments currently in the system.
Omit BULK_UPDATE_ASSIGNMENT_STATUS lines if you are not doing bulk updates.

You may bulk-update assignment priority:
BULK_UPDATE_ASSIGNMENT_PRIORITY: <P1-P5> | <AgentName or all> | <open or all (optional)> | <optional note>
Example: BULK_UPDATE_ASSIGNMENT_PRIORITY: P1 | all | open | Quarterly planning sweep.
Omit BULK_UPDATE_ASSIGNMENT_PRIORITY lines if you are not doing bulk updates.

You may bulk-update assignment due date:
BULK_UPDATE_ASSIGNMENT_DUE: <YYYY-MM-DD or none> | <AgentName or all> | <open or all (optional)> | <optional note>
Example: BULK_UPDATE_ASSIGNMENT_DUE: 2026-04-15 | Atlas | open | Align with milestone.
Omit BULK_UPDATE_ASSIGNMENT_DUE lines if you are not doing bulk updates.

You may reassign work:
REASSIGN: <A-0007 or 7> | <AgentName> | <optional note>
Example: REASSIGN: A-0007 | Quill | Move drafting to writer.
Omit REASSIGN lines if you are not reassigning work.

You may bulk-reassign work:
BULK_REASSIGN_ASSIGNMENTS: <AgentName or all> | <AgentName target> | <open or all (optional)> | <optional note>
Example: BULK_REASSIGN_ASSIGNMENTS: Atlas | Quill | open | Move drafting queue to writer.
Omit BULK_REASSIGN_ASSIGNMENTS lines if you are not bulk reassigning work.

You may update assignment result summary:
UPDATE_ASSIGNMENT_SUMMARY: <A-0007 or 7> | <summary markdown>
Example: UPDATE_ASSIGNMENT_SUMMARY: A-0007 | Atlas completed research and delivered sources.
Omit UPDATE_ASSIGNMENT_SUMMARY lines if you are not updating summaries.

You may update assignment priority:
UPDATE_ASSIGNMENT_PRIORITY: <A-0007 or 7> | <P1-P5> | <optional note>
Example: UPDATE_ASSIGNMENT_PRIORITY: A-0007 | P1 | Escalated after client request.
Omit UPDATE_ASSIGNMENT_PRIORITY lines if you are not updating priorities.

You may update assignment due date:
UPDATE_ASSIGNMENT_DUE: <A-0007 or 7> | <YYYY-MM-DD or none> | <optional note>
Example: UPDATE_ASSIGNMENT_DUE: A-0007 | 2026-03-15 | Aligned with revised timeline.
Omit UPDATE_ASSIGNMENT_DUE lines if you are not updating due dates.

You may retitle an assignment:
RETITLE_ASSIGNMENT: <A-0007 or 7> | <new title> | <optional note>
Example: RETITLE_ASSIGNMENT: A-0007 | Finalize FDA evidence packet | Clarified scope.
Omit RETITLE_ASSIGNMENT lines if you are not retitling assignments.

You may update assignment brief:
UPDATE_ASSIGNMENT_BRIEF: <A-0007 or 7> | <new brief markdown> | <optional note>
Example: UPDATE_ASSIGNMENT_BRIEF: A-0007 | Focus only on competitor benchmark section. | Reduced scope.
Omit UPDATE_ASSIGNMENT_BRIEF lines if you are not updating briefs.

You may attach an artifact to an assignment:
ADD_ASSIGNMENT_ARTIFACT: <A-0007 or 7> | <artifact_type> | <title> | <content markdown>
Example: ADD_ASSIGNMENT_ARTIFACT: A-0007 | summary_note | Final recommendation | Atlas recommends option B due to timeline.
Omit ADD_ASSIGNMENT_ARTIFACT lines if you are not attaching artifacts.

You may also create a dashboard task from an assignment:
ADD_TASK_FROM_ASSIGNMENT: <A-0007 or 7> | <MM-DD-YYYY or none> | <Business or Personal>
Example: ADD_TASK_FROM_ASSIGNMENT: A-0007 | 03-18-2026 | Business
This adds a task using the assignment title as the task text.
If a dashboard task already exists for that assignment id, it will be skipped.
Omit ADD_TASK_FROM_ASSIGNMENT lines if you are not creating tasks from assignments.

You may bulk-create dashboard tasks from assignments:
BULK_ADD_TASKS_FROM_ASSIGNMENTS: <AgentName or all> | <Business or Personal> | <open or all (optional, defaults to open)>
Example: BULK_ADD_TASKS_FROM_ASSIGNMENTS: Atlas | Business | open
This adds one dashboard task per matching assignment using assignment titles.
Assignments that already have dashboard tasks are skipped automatically.
Omit BULK_ADD_TASKS_FROM_ASSIGNMENTS lines if you are not bulk-creating tasks from assignments.

If you need more information to answer well, you may request one of these tools by returning EXACTLY ONE line with one of:
- WEB_SEARCH:<query>
- DOC_SEARCH:<query>   (searches local docs/notes and optional RAG index)
- MEMORY_SEARCH:<query> (searches stored CoS memory)

If you request a tool, you must return only that single tool line (no other text)."""

    def _tool_results_for_trigger(out: str) -> Optional[tuple[str, str]]:
        """
        If out is a tool trigger, return (tool_name, tool_result_text). Else None.
        """
        out = (out or "").strip()
        m_web = WEB_SEARCH_TRIGGER.match(out)
        m_doc = DOC_SEARCH_TRIGGER.match(out)
        m_mem = MEMORY_SEARCH_TRIGGER.match(out)
        if m_web:
            query = m_web.group(1).strip()
            ok, _msg = grok_available()
            results = ""
            if ok and query:
                try:
                    results = grok_web_search(query, model=MODEL_FAST)
                except Exception:
                    results = ""
            return "WEB_SEARCH_RESULTS", "WEB_SEARCH_RESULTS (untrusted):\n" + (results or "(no results)")
        if m_doc:
            query = m_doc.group(1).strip()
            hits = []
            try:
                hits = doc_search(db.db_name, query, limit=10)
            except Exception:
                hits = []
            return "DOC_SEARCH_RESULTS", "DOC_SEARCH_RESULTS (untrusted):\n" + format_hits(hits)
        if m_mem:
            query = m_mem.group(1).strip()
            rows = []
            try:
                rows = db.cos_memory_search(query=query, chat_id=chat_id, limit=10)
            except Exception:
                rows = []
            lines = []
            for _id, _chat_id, kind, content, _json_data, created_at in rows[:10]:
                lines.append(f"- ({kind}) {content}")
            return "MEMORY_SEARCH_RESULTS", "MEMORY_SEARCH_RESULTS (untrusted):\n" + ("\n".join(lines) if lines else "(no matches)")
        return None

    def _run_tool_loop_single(system_text: str, user_text: str) -> str:
        """
        Tool loop for single-turn. Uses grok_completion (keeps unit tests stable).
        """
        user_aug = user_text
        out = ""
        for _ in range(3):
            out = grok_completion(system_text, user_aug, model=MODEL_COS)
            out = (out or "").strip()
            if not out:
                return out
            tool = _tool_results_for_trigger(out)
            if not tool:
                return out
            _, tool_text = tool
            user_aug = user_text + "\n\n" + tool_text
        return out

    def _run_tool_loop_messages(messages: list[dict]) -> str:
        """
        Tool loop for multi-turn. Uses grok_completion_messages.
        """
        msgs = list(messages)
        out = ""
        for _ in range(3):
            out = grok_completion_messages(msgs, model=MODEL_COS)
            out = (out or "").strip()
            if not out:
                return out
            tool = _tool_results_for_trigger(out)
            if not tool:
                return out
            _, tool_text = tool
            msgs.append({"role": "user", "content": tool_text})
        return out

    if not conversation_history or len(conversation_history) == 0:
        # Single turn
        user = f"""Today is {today}, current time {time_str} (user's local time)."""
        if prefs_ctx:
            user += f"""

**His stated preferences / constraints (optional context):**
{prefs_ctx}"""
        if cal_ctx:
            user += f"""

{cal_ctx}"""
        if mem_ctx:
            user += f"""

{mem_ctx}"""
        user += f"""

{tasks_ctx}

{assignments_ctx}

**What he says (main input):**
{user_message or "What should I focus on right now?"}"""
        try:
            out = _run_tool_loop_single(system, user)
            cleaned = _parse_and_add_tasks(db, out, chat_id=chat_id)
            _extract_and_store_memory(db, chat_id=chat_id, user_message=user_message, assistant_message=cleaned)
            return cleaned
        except Exception as e:
            logger.exception("CoS response failed: %s", e)
            return f"Error: {e}"

    # Multi-turn: build messages list. Caller must have saved the current user message and included it in conversation_history.
    time_ctx = f"Today is {today}, current time {time_str} (user's local time)."
    if prefs_ctx:
        time_ctx += f"\n\n**His stated preferences / constraints:**\n{prefs_ctx}"
    if cal_ctx:
        time_ctx += f"\n\n{cal_ctx}"
    if mem_ctx:
        time_ctx += f"\n\n{mem_ctx}"
    time_ctx += f"\n\n{tasks_ctx}\n\n{assignments_ctx}"
    messages = [{"role": "system", "content": system + "\n\n" + time_ctx}]
    for role, content in conversation_history:
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    try:
        out = _run_tool_loop_messages(messages)
        cleaned = _parse_and_add_tasks(db, (out or "").strip(), chat_id=chat_id)
        _extract_and_store_memory(db, chat_id=chat_id, user_message=user_message, assistant_message=cleaned)
        return cleaned
    except Exception as e:
        logger.exception("CoS response failed: %s", e)
        return f"Error: {e}"


def _parse_and_add_tasks(db: DatabaseManager, response: str, *, chat_id: Optional[int] = None) -> str:
    """
    Parse action lines from the model response:
    - ADD_TASK: add dashboard tasks
    - ADD_CAL_BLOCK: create Google Calendar events
    - ASSIGN: create delegation assignments
    Return cleaned response text with action lines removed.
    """
    if not response:
        return response
    session_id = f"dashboard_cos_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    added_tasks = 0
    added_tasks_from_assignments = 0
    added_blocks = 0
    created_assignments: list[str] = []
    updated_assignments: list[str] = []
    updated_assignment_priorities: list[str] = []
    updated_assignment_due_dates: list[str] = []
    retitled_assignments: list[str] = []
    updated_assignment_briefs: list[str] = []
    bulk_updated_assignments: list[str] = []
    bulk_updated_assignment_priorities: list[str] = []
    bulk_updated_assignment_due_dates: list[str] = []
    bulk_reassigned_assignments: list[str] = []
    reassigned_assignments: list[str] = []
    summarized_assignments: list[str] = []
    added_assignment_artifacts: list[str] = []
    bulk_created_tasks_from_assignments: list[str] = []
    skipped_existing_assignment_tasks: list[str] = []
    assignment_failures: list[str] = []
    block_failures = 0
    block_failure_reasons: list[str] = []
    cleaned_lines = []
    existing_assignment_task_ids_cache: set[int] | None = None

    def _existing_assignment_task_ids() -> set[int]:
        nonlocal existing_assignment_task_ids_cache
        if existing_assignment_task_ids_cache is None:
            ids: set[int] = set()
            try:
                tasks = db.get_tasks(category=None, date_filter=None, specific_date=None)
                for t in tasks:
                    text = str(t[1] or "").strip()
                    m_ref = ASSIGNMENT_TASK_REF_PATTERN.match(text)
                    if not m_ref:
                        continue
                    try:
                        ids.add(int(m_ref.group(1)))
                    except Exception:
                        continue
            except Exception:
                ids = set()
            existing_assignment_task_ids_cache = ids
        return existing_assignment_task_ids_cache

    def _ensure_assignment_thread_matches_assignee(assignment_id: int, assignee_code: str, reason: str) -> None:
        """Best-effort: ensure source_thread_id belongs to current assignee."""
        try:
            row = db.agent_get_assignment(int(assignment_id)) or {}
            source_thread_id = row.get("source_thread_id")
            relink = True
            if source_thread_id:
                src = db.agent_get_thread(int(source_thread_id))
                if src and str(src[1] or "").strip().lower() == assignee_code:
                    relink = False
            if relink:
                title = str(row.get("title") or f"A-{int(assignment_id):04d}")
                tid = db.agent_create_thread(
                    agent_code=assignee_code,
                    title=title,
                    context_json={"source": reason, "assignment_id": int(assignment_id)},
                )
                if tid:
                    db.agent_link_assignment_thread(
                        assignment_id=int(assignment_id),
                        thread_id=int(tid),
                        actor_code="navi",
                        note=f"Thread relinked after {reason.replace('_', ' ')}",
                    )
        except Exception:
            return

    for line in response.splitlines():
        stripped = line.strip()

        m = ADD_TASK_PATTERN.search(stripped)
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
                added_tasks += 1
            except Exception as e:
                logger.warning("CoS add_task failed: %s", e)
            continue

        m_task_from_asg = ADD_TASK_FROM_ASSIGNMENT_PATTERN.match(stripped)
        if m_task_from_asg:
            payload = (m_task_from_asg.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 2)]
            if len(parts) < 3:
                assignment_failures.append("invalid ADD_TASK_FROM_ASSIGNMENT format")
                logger.warning("CoS ADD_TASK_FROM_ASSIGNMENT invalid format: %r", stripped)
                continue
            assignment_ref = parts[0]
            due_raw = parts[1]
            category = parts[2]
            if category not in {"Business", "Personal"}:
                assignment_failures.append(f"invalid category '{category}'")
                logger.warning("CoS ADD_TASK_FROM_ASSIGNMENT invalid category: %r", category)
                continue
            aid = _parse_assignment_ref(assignment_ref)
            if aid is None:
                assignment_failures.append(f"invalid assignment id '{assignment_ref}'")
                logger.warning("CoS ADD_TASK_FROM_ASSIGNMENT invalid id: %r", assignment_ref)
                continue
            row = db.agent_get_assignment(int(aid))
            if not row:
                assignment_failures.append(f"unknown assignment A-{int(aid):04d}")
                continue
            existing_ids = _existing_assignment_task_ids()
            if int(aid) in existing_ids:
                skipped_existing_assignment_tasks.append(f"A-{int(aid):04d}")
                continue
            title = str(row.get("title") or "").strip() or f"Assignment A-{int(aid):04d}"
            task_text = f"[A-{int(aid):04d}] {title}"
            due_date = (due_raw or "").strip()
            if due_date.lower() in {"none", "null", "n/a", ""}:
                due_date = None
            elif len(due_date) == 10 and due_date[4] == "-":
                # Normalize YYYY-MM-DD -> MM-DD-YYYY for tasks UI consistency.
                parts_d = due_date.split("-")
                if len(parts_d) == 3:
                    due_date = f"{parts_d[1]}-{parts_d[2]}-{parts_d[0]}"
            try:
                db.add_task(
                    session_id=session_id,
                    task_text=task_text,
                    due_date=due_date or "",
                    category=category,
                    recurrence="None",
                    completed=0,
                )
                added_tasks += 1
                added_tasks_from_assignments += 1
                existing_ids.add(int(aid))
                try:
                    db.agent_add_event(
                        assignment_id=int(aid),
                        event_type="task_created",
                        actor_code="navi",
                        note=f"Created dashboard task from assignment: {task_text}",
                    )
                except Exception:
                    pass
            except Exception as e:
                assignment_failures.append(f"failed creating task from A-{int(aid):04d}")
                logger.warning("CoS ADD_TASK_FROM_ASSIGNMENT failed: %s", e)
            continue

        m_bulk_task_from_asg = BULK_ADD_TASKS_FROM_ASSIGNMENTS_PATTERN.match(stripped)
        if m_bulk_task_from_asg:
            payload = (m_bulk_task_from_asg.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 2)]
            if len(parts) < 2:
                assignment_failures.append("invalid BULK_ADD_TASKS_FROM_ASSIGNMENTS format")
                logger.warning("CoS BULK_ADD_TASKS_FROM_ASSIGNMENTS invalid format: %r", stripped)
                continue
            scope = parts[0]
            category = parts[1]
            mode_raw = (parts[2] if len(parts) > 2 else "open").strip().lower()
            if category not in {"Business", "Personal"}:
                assignment_failures.append(f"invalid category '{category}'")
                logger.warning("CoS BULK_ADD_TASKS_FROM_ASSIGNMENTS invalid category: %r", category)
                continue

            include_closed = False
            if mode_raw in {"", "open", "open_only", "active", "pending"}:
                include_closed = False
            elif mode_raw in {"all", "include_closed", "with_closed", "closed"}:
                include_closed = True
            else:
                assignment_failures.append(f"invalid mode '{mode_raw}'")
                logger.warning("CoS BULK_ADD_TASKS_FROM_ASSIGNMENTS invalid mode: %r", mode_raw)
                continue

            ok_scope, assignee_code, scope_label = _resolve_bulk_scope(db, scope)
            if not ok_scope:
                assignment_failures.append(f"unknown agent '{scope}'")
                logger.warning("CoS BULK_ADD_TASKS_FROM_ASSIGNMENTS unknown agent: %r", scope)
                continue

            rows = db.agent_list_assignments(assignee_code=assignee_code, limit=500)
            if not rows:
                assignment_failures.append(f"no assignments found for scope '{scope_label}'")
                continue

            existing_ids = _existing_assignment_task_ids()

            created_count = 0
            skipped_existing = 0
            skipped_closed = 0
            for row in rows:
                aid = int(row.get("id") or 0)
                if aid <= 0:
                    continue
                st = str(row.get("status") or "").strip().lower()
                if (not include_closed) and st in {"done", "cancelled"}:
                    skipped_closed += 1
                    continue
                title = str(row.get("title") or "").strip() or f"Assignment A-{aid:04d}"
                task_text = f"[A-{aid:04d}] {title}"
                if aid in existing_ids:
                    skipped_existing += 1
                    continue
                due_iso = str(row.get("due_date") or "").strip()
                due_date = ""
                if len(due_iso) == 10 and due_iso[4] == "-":
                    y, m, d = due_iso.split("-")
                    due_date = f"{m}-{d}-{y}"
                try:
                    db.add_task(
                        session_id=session_id,
                        task_text=task_text,
                        due_date=due_date,
                        category=category,
                        recurrence="None",
                        completed=0,
                    )
                    existing_ids.add(aid)
                    added_tasks += 1
                    added_tasks_from_assignments += 1
                    created_count += 1
                    try:
                        db.agent_add_event(
                            assignment_id=aid,
                            event_type="task_created",
                            actor_code="navi",
                            note=f"Created dashboard task from assignment (bulk): {task_text}",
                        )
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning("CoS BULK_ADD_TASKS_FROM_ASSIGNMENTS failed for A-%04d: %s", aid, e)
            summary = (
                f"{scope_label}: {created_count} created"
                f"{f' ({skipped_existing} skipped existing' if skipped_existing else ''}"
                f"{', ' if skipped_existing and skipped_closed else ''}"
                f"{f'{skipped_closed} skipped closed' if skipped_closed else ''}"
                f"{')' if (skipped_existing or skipped_closed) else ''}"
            )
            if created_count <= 0 and skipped_existing <= 0 and skipped_closed <= 0:
                assignment_failures.append(
                    f"no dashboard tasks created for scope '{scope_label}'"
                )
            else:
                bulk_created_tasks_from_assignments.append(summary)
            continue

        m_block = ADD_CAL_BLOCK_PATTERN.search(stripped)
        if m_block:
            title = (m_block.group(1) or "").strip()
            start_raw = (m_block.group(2) or "").strip()
            end_raw = (m_block.group(3) or "").strip()
            calendar_id = (m_block.group(4) or "primary").strip() or "primary"

            start_dt = _parse_calendar_datetime(start_raw)
            end_dt = _parse_calendar_datetime(end_raw)
            if not start_dt or not end_dt or end_dt <= start_dt:
                block_failures += 1
                block_failure_reasons.append("invalid start/end datetime")
                logger.warning(
                    "CoS ADD_CAL_BLOCK rejected due to invalid times: start=%r end=%r",
                    start_raw,
                    end_raw,
                )
                continue

            ok, msg, _created = create_calendar_event(
                summary=title,
                start_dt=start_dt,
                end_dt=end_dt,
                calendar_id=calendar_id,
            )
            if ok:
                added_blocks += 1
            else:
                block_failures += 1
                block_failure_reasons.append((msg or "unknown error").strip())
                logger.warning("CoS ADD_CAL_BLOCK failed: %s", msg or "unknown error")
            continue

        m_assign = ASSIGN_PATTERN.match(stripped)
        if m_assign:
            payload = (m_assign.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 4)]
            if len(parts) != 5:
                assignment_failures.append("invalid ASSIGN format")
                logger.warning("CoS ASSIGN rejected due to invalid format: %r", stripped)
                continue

            assignee_name, title, brief, priority_raw, due_raw = parts
            if not assignee_name or not title or not brief:
                assignment_failures.append("missing assignee/title/brief")
                logger.warning("CoS ASSIGN rejected due to missing required fields: %r", stripped)
                continue

            priority_digits = "".join(ch for ch in str(priority_raw) if ch.isdigit())
            try:
                priority = int(priority_digits) if priority_digits else 3
            except Exception:
                priority = 3
            if priority < 1:
                priority = 1
            if priority > 5:
                priority = 5

            due_date = (due_raw or "").strip()
            if due_date.lower() in ("none", "null", "n/a", ""):
                due_date = None

            agent = db.agent_resolve_by_name(assignee_name)
            if not agent:
                assignment_failures.append(f"unknown agent '{assignee_name}'")
                logger.warning("CoS ASSIGN failed: unknown agent %r", assignee_name)
                continue

            context_obj = {"source": "chief_of_staff"}
            if chat_id is not None:
                context_obj["cos_chat_id"] = int(chat_id)
            assignee_code = str(agent.get("code") or "").strip().lower()
            source_thread_id = None
            try:
                source_thread_id = db.agent_create_thread(
                    agent_code=assignee_code,
                    title=title,
                    context_json=context_obj,
                )
            except Exception:
                source_thread_id = None
            try:
                assignment_id = db.agent_create_assignment(
                    title=title,
                    brief_md=brief,
                    requester_code="navi",
                    assignee_code=assignee_code,
                    priority=priority,
                    due_date=due_date,
                    status="queued",
                    source_thread_id=(int(source_thread_id) if source_thread_id else None),
                    context_json=context_obj,
                )
            except Exception as e:
                assignment_id = 0
                logger.warning("CoS ASSIGN create failed: %s", e)

            if assignment_id:
                disp = str(agent.get("display_name") or agent.get("code") or assignee_name).strip()
                created_assignments.append(f"{disp} (A-{int(assignment_id):04d})")
            else:
                assignment_failures.append(f"failed creating assignment for {assignee_name}")
            continue

        m_upd = UPDATE_ASSIGNMENT_STATUS_PATTERN.match(stripped)
        if m_upd:
            payload = (m_upd.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 2)]
            if len(parts) < 2:
                assignment_failures.append("invalid UPDATE_ASSIGNMENT_STATUS format")
                logger.warning("CoS UPDATE_ASSIGNMENT_STATUS invalid format: %r", stripped)
                continue
            assignment_ref = parts[0]
            to_status = _normalize_assignment_status(parts[1] or "")
            note = (parts[2] if len(parts) > 2 else "").strip() or None
            aid = _parse_assignment_ref(assignment_ref)
            if aid is None:
                assignment_failures.append(f"invalid assignment id '{assignment_ref}'")
                logger.warning("CoS UPDATE_ASSIGNMENT_STATUS invalid id: %r", assignment_ref)
                continue
            ok = False
            try:
                ok = db.agent_update_assignment_status(
                    assignment_id=int(aid),
                    to_status=to_status,
                    actor_code="navi",
                    note=note,
                )
            except Exception as e:
                ok = False
                logger.warning("CoS UPDATE_ASSIGNMENT_STATUS failed: %s", e)
            if ok:
                updated_assignments.append(f"A-{int(aid):04d} -> {to_status}")
            else:
                assignment_failures.append(f"failed updating A-{int(aid):04d} to {to_status}")
            continue

        m_bulk = BULK_UPDATE_ASSIGNMENT_STATUS_PATTERN.match(stripped)
        if m_bulk:
            payload = (m_bulk.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 3)]
            if len(parts) < 1:
                assignment_failures.append("invalid BULK_UPDATE_ASSIGNMENT_STATUS format")
                logger.warning("CoS BULK_UPDATE_ASSIGNMENT_STATUS invalid format: %r", stripped)
                continue
            to_status = _normalize_assignment_status(parts[0] or "")
            scope = (parts[1] if len(parts) > 1 else "all").strip()
            ok_mode, bulk_mode, note = _parse_bulk_mode_and_note(parts)
            if not ok_mode:
                assignment_failures.append("invalid mode in BULK_UPDATE_ASSIGNMENT_STATUS")
                logger.warning("CoS BULK_UPDATE_ASSIGNMENT_STATUS invalid mode: %r", stripped)
                continue
            if not to_status:
                assignment_failures.append("missing status in BULK_UPDATE_ASSIGNMENT_STATUS")
                continue

            ok_scope, assignee_code, scope_label = _resolve_bulk_scope(db, scope)
            if not ok_scope:
                assignment_failures.append(f"unknown agent '{scope}'")
                logger.warning("CoS BULK_UPDATE_ASSIGNMENT_STATUS unknown agent: %r", scope)
                continue

            rows = db.agent_list_assignments(assignee_code=assignee_code, limit=500)
            if not rows:
                assignment_failures.append(f"no assignments found for scope '{scope_label}'")
                continue

            updated_count = 0
            skipped_closed = 0
            for r in rows:
                aid = int(r.get("id") or 0)
                if aid <= 0:
                    continue
                current_status = str(r.get("status") or "").strip().lower()
                if bulk_mode == "open" and current_status in {"done", "cancelled"}:
                    skipped_closed += 1
                    continue
                if current_status == to_status:
                    continue
                ok = False
                try:
                    ok = db.agent_update_assignment_status(
                        assignment_id=aid,
                        to_status=to_status,
                        actor_code="navi",
                        note=note or "Bulk update via CoS action",
                    )
                except Exception:
                    ok = False
                if ok:
                    updated_count += 1
            summary = (
                f"{scope_label}: {updated_count} -> {to_status}"
                f"{f' ({skipped_closed} skipped closed)' if skipped_closed else ''}"
            )
            if updated_count <= 0 and skipped_closed <= 0:
                assignment_failures.append(
                    f"no assignments updated for scope '{scope_label}' to {to_status}"
                )
            else:
                bulk_updated_assignments.append(summary)
            continue

        m_bulk_pri = BULK_UPDATE_ASSIGNMENT_PRIORITY_PATTERN.match(stripped)
        if m_bulk_pri:
            payload = (m_bulk_pri.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 3)]
            if len(parts) < 1:
                assignment_failures.append("invalid BULK_UPDATE_ASSIGNMENT_PRIORITY format")
                logger.warning("CoS BULK_UPDATE_ASSIGNMENT_PRIORITY invalid format: %r", stripped)
                continue
            priority = _parse_priority_value(parts[0] or "")
            scope = (parts[1] if len(parts) > 1 else "all").strip()
            ok_mode, bulk_mode, note = _parse_bulk_mode_and_note(parts)
            if not ok_mode:
                assignment_failures.append("invalid mode in BULK_UPDATE_ASSIGNMENT_PRIORITY")
                logger.warning("CoS BULK_UPDATE_ASSIGNMENT_PRIORITY invalid mode: %r", stripped)
                continue
            if priority is None:
                assignment_failures.append(f"invalid priority '{parts[0]}'")
                continue
            ok_scope, assignee_code, scope_label = _resolve_bulk_scope(db, scope)
            if not ok_scope:
                assignment_failures.append(f"unknown agent '{scope}'")
                logger.warning("CoS BULK_UPDATE_ASSIGNMENT_PRIORITY unknown agent: %r", scope)
                continue
            rows = db.agent_list_assignments(assignee_code=assignee_code, limit=500)
            if not rows:
                assignment_failures.append(f"no assignments found for scope '{scope_label}'")
                continue
            updated_count = 0
            skipped_closed = 0
            for r in rows:
                aid = int(r.get("id") or 0)
                if aid <= 0:
                    continue
                current_status = str(r.get("status") or "").strip().lower()
                if bulk_mode == "open" and current_status in {"done", "cancelled"}:
                    skipped_closed += 1
                    continue
                current_priority = int(r.get("priority") or 3)
                if current_priority == int(priority):
                    continue
                ok = False
                try:
                    ok = db.agent_update_assignment_fields(
                        assignment_id=aid,
                        actor_code="navi",
                        priority=int(priority),
                        note=note or "Bulk priority update via CoS action",
                    )
                except Exception:
                    ok = False
                if ok:
                    updated_count += 1
            summary = (
                f"{scope_label}: {updated_count} -> P{int(priority)}"
                f"{f' ({skipped_closed} skipped closed)' if skipped_closed else ''}"
            )
            if updated_count <= 0 and skipped_closed <= 0:
                assignment_failures.append(
                    f"no assignments updated for scope '{scope_label}' to P{int(priority)}"
                )
            else:
                bulk_updated_assignment_priorities.append(summary)
            continue

        m_bulk_due = BULK_UPDATE_ASSIGNMENT_DUE_PATTERN.match(stripped)
        if m_bulk_due:
            payload = (m_bulk_due.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 3)]
            if len(parts) < 1:
                assignment_failures.append("invalid BULK_UPDATE_ASSIGNMENT_DUE format")
                logger.warning("CoS BULK_UPDATE_ASSIGNMENT_DUE invalid format: %r", stripped)
                continue
            due_ok, due_date = _normalize_due_date_input(parts[0] or "")
            scope = (parts[1] if len(parts) > 1 else "all").strip()
            ok_mode, bulk_mode, note = _parse_bulk_mode_and_note(parts)
            if not ok_mode:
                assignment_failures.append("invalid mode in BULK_UPDATE_ASSIGNMENT_DUE")
                logger.warning("CoS BULK_UPDATE_ASSIGNMENT_DUE invalid mode: %r", stripped)
                continue
            if not due_ok:
                assignment_failures.append(f"invalid due date '{parts[0]}'")
                continue
            ok_scope, assignee_code, scope_label = _resolve_bulk_scope(db, scope)
            if not ok_scope:
                assignment_failures.append(f"unknown agent '{scope}'")
                logger.warning("CoS BULK_UPDATE_ASSIGNMENT_DUE unknown agent: %r", scope)
                continue
            rows = db.agent_list_assignments(assignee_code=assignee_code, limit=500)
            if not rows:
                assignment_failures.append(f"no assignments found for scope '{scope_label}'")
                continue
            updated_count = 0
            skipped_closed = 0
            for r in rows:
                aid = int(r.get("id") or 0)
                if aid <= 0:
                    continue
                current_status = str(r.get("status") or "").strip().lower()
                if bulk_mode == "open" and current_status in {"done", "cancelled"}:
                    skipped_closed += 1
                    continue
                current_due = str(r.get("due_date") or "").strip() or None
                if current_due == (due_date or None):
                    continue
                ok = False
                try:
                    ok = db.agent_update_assignment_fields(
                        assignment_id=aid,
                        actor_code="navi",
                        due_date=due_date,
                        note=note or "Bulk due-date update via CoS action",
                    )
                except Exception:
                    ok = False
                if ok:
                    updated_count += 1
            summary = (
                f"{scope_label}: {updated_count} -> {due_date or '(none)'}"
                f"{f' ({skipped_closed} skipped closed)' if skipped_closed else ''}"
            )
            if updated_count <= 0 and skipped_closed <= 0:
                assignment_failures.append(
                    f"no assignments updated for scope '{scope_label}' due date"
                )
            else:
                bulk_updated_assignment_due_dates.append(summary)
            continue

        m_bulk_reassign = BULK_REASSIGN_ASSIGNMENTS_PATTERN.match(stripped)
        if m_bulk_reassign:
            payload = (m_bulk_reassign.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 3)]
            if len(parts) < 2:
                assignment_failures.append("invalid BULK_REASSIGN_ASSIGNMENTS format")
                logger.warning("CoS BULK_REASSIGN_ASSIGNMENTS invalid format: %r", stripped)
                continue
            from_scope = parts[0]
            to_name = parts[1]
            ok_mode, bulk_mode, note = _parse_bulk_mode_and_note(parts)
            if not ok_mode:
                assignment_failures.append("invalid mode in BULK_REASSIGN_ASSIGNMENTS")
                logger.warning("CoS BULK_REASSIGN_ASSIGNMENTS invalid mode: %r", stripped)
                continue

            ok_scope, from_assignee_code, from_scope_label = _resolve_bulk_scope(db, from_scope)
            if not ok_scope:
                assignment_failures.append(f"unknown agent '{from_scope}'")
                logger.warning("CoS BULK_REASSIGN_ASSIGNMENTS unknown from-scope: %r", from_scope)
                continue
            to_agent = db.agent_resolve_by_name(to_name)
            if not to_agent:
                assignment_failures.append(f"unknown agent '{to_name}'")
                logger.warning("CoS BULK_REASSIGN_ASSIGNMENTS unknown target: %r", to_name)
                continue
            to_assignee_code = str(to_agent.get("code") or "").strip().lower()
            to_label = str(to_agent.get("display_name") or to_assignee_code).strip()

            rows = db.agent_list_assignments(assignee_code=from_assignee_code, limit=500)
            if not rows:
                assignment_failures.append(f"no assignments found for scope '{from_scope_label}'")
                continue
            updated_count = 0
            skipped_closed = 0
            for r in rows:
                aid = int(r.get("id") or 0)
                if aid <= 0:
                    continue
                current_status = str(r.get("status") or "").strip().lower()
                if bulk_mode == "open" and current_status in {"done", "cancelled"}:
                    skipped_closed += 1
                    continue
                current_assignee = str(r.get("assignee_code") or "").strip().lower()
                if current_assignee == to_assignee_code:
                    continue
                ok = False
                try:
                    ok = db.agent_reassign_assignment(
                        assignment_id=aid,
                        new_assignee_code=to_assignee_code,
                        actor_code="navi",
                        note=note or "Bulk reassignment via CoS action",
                    )
                except Exception:
                    ok = False
                if ok:
                    _ensure_assignment_thread_matches_assignee(
                        assignment_id=aid,
                        assignee_code=to_assignee_code,
                        reason="chief_of_staff_bulk_reassign",
                    )
                    updated_count += 1
            summary = (
                f"{from_scope_label} -> {to_label}: {updated_count}"
                f"{f' ({skipped_closed} skipped closed)' if skipped_closed else ''}"
            )
            if updated_count <= 0 and skipped_closed <= 0:
                assignment_failures.append(
                    f"no assignments reassigned from '{from_scope_label}' to '{to_label}'"
                )
            else:
                bulk_reassigned_assignments.append(summary)
            continue

        m_reassign = REASSIGN_PATTERN.match(stripped)
        if m_reassign:
            payload = (m_reassign.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 2)]
            if len(parts) < 2:
                assignment_failures.append("invalid REASSIGN format")
                logger.warning("CoS REASSIGN invalid format: %r", stripped)
                continue
            assignment_ref = parts[0]
            assignee_name = (parts[1] or "").strip()
            note = (parts[2] if len(parts) > 2 else "").strip() or None

            aid = _parse_assignment_ref(assignment_ref)
            if aid is None:
                assignment_failures.append(f"invalid assignment id '{assignment_ref}'")
                logger.warning("CoS REASSIGN invalid id: %r", assignment_ref)
                continue
            agent = db.agent_resolve_by_name(assignee_name)
            if not agent:
                assignment_failures.append(f"unknown agent '{assignee_name}'")
                logger.warning("CoS REASSIGN unknown agent: %r", assignee_name)
                continue
            assignee_code = str(agent.get("code") or "").strip().lower()

            ok = False
            try:
                ok = db.agent_reassign_assignment(
                    assignment_id=int(aid),
                    new_assignee_code=assignee_code,
                    actor_code="navi",
                    note=note or "Reassigned via CoS action",
                )
            except Exception as e:
                ok = False
                logger.warning("CoS REASSIGN failed: %s", e)
            if not ok:
                assignment_failures.append(f"failed reassigning A-{int(aid):04d}")
                continue

            _ensure_assignment_thread_matches_assignee(
                assignment_id=int(aid),
                assignee_code=assignee_code,
                reason="chief_of_staff_reassign",
            )

            disp = str(agent.get("display_name") or assignee_code).strip()
            reassigned_assignments.append(f"A-{int(aid):04d} -> {disp}")
            continue

        m_summary = UPDATE_ASSIGNMENT_SUMMARY_PATTERN.match(stripped)
        if m_summary:
            payload = (m_summary.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 1)]
            if len(parts) < 2:
                assignment_failures.append("invalid UPDATE_ASSIGNMENT_SUMMARY format")
                logger.warning("CoS UPDATE_ASSIGNMENT_SUMMARY invalid format: %r", stripped)
                continue
            assignment_ref = parts[0]
            summary_md = (parts[1] or "").strip()
            aid = _parse_assignment_ref(assignment_ref)
            if aid is None:
                assignment_failures.append(f"invalid assignment id '{assignment_ref}'")
                logger.warning("CoS UPDATE_ASSIGNMENT_SUMMARY invalid id: %r", assignment_ref)
                continue
            ok = False
            try:
                ok = db.agent_set_assignment_result_summary(
                    assignment_id=int(aid),
                    summary_md=summary_md,
                    actor_code="navi",
                    note="Updated via CoS action",
                )
            except Exception as e:
                ok = False
                logger.warning("CoS UPDATE_ASSIGNMENT_SUMMARY failed: %s", e)
            if ok:
                summarized_assignments.append(f"A-{int(aid):04d}")
            else:
                assignment_failures.append(f"failed updating summary for A-{int(aid):04d}")
            continue

        m_pri = UPDATE_ASSIGNMENT_PRIORITY_PATTERN.match(stripped)
        if m_pri:
            payload = (m_pri.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 2)]
            if len(parts) < 2:
                assignment_failures.append("invalid UPDATE_ASSIGNMENT_PRIORITY format")
                logger.warning("CoS UPDATE_ASSIGNMENT_PRIORITY invalid format: %r", stripped)
                continue
            assignment_ref = parts[0]
            priority_raw = parts[1]
            note = (parts[2] if len(parts) > 2 else "").strip() or None
            aid = _parse_assignment_ref(assignment_ref)
            if aid is None:
                assignment_failures.append(f"invalid assignment id '{assignment_ref}'")
                logger.warning("CoS UPDATE_ASSIGNMENT_PRIORITY invalid id: %r", assignment_ref)
                continue
            priority = _parse_priority_value(priority_raw)
            if priority is None:
                assignment_failures.append(f"invalid priority '{priority_raw}'")
                logger.warning("CoS UPDATE_ASSIGNMENT_PRIORITY invalid priority: %r", priority_raw)
                continue
            ok = False
            try:
                ok = db.agent_update_assignment_fields(
                    assignment_id=int(aid),
                    actor_code="navi",
                    priority=int(priority),
                    note=note or "Updated via CoS action",
                )
            except Exception as e:
                ok = False
                logger.warning("CoS UPDATE_ASSIGNMENT_PRIORITY failed: %s", e)
            if ok:
                updated_assignment_priorities.append(f"A-{int(aid):04d} -> P{int(priority)}")
            else:
                assignment_failures.append(f"failed updating priority for A-{int(aid):04d}")
            continue

        m_due = UPDATE_ASSIGNMENT_DUE_PATTERN.match(stripped)
        if m_due:
            payload = (m_due.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 2)]
            if len(parts) < 2:
                assignment_failures.append("invalid UPDATE_ASSIGNMENT_DUE format")
                logger.warning("CoS UPDATE_ASSIGNMENT_DUE invalid format: %r", stripped)
                continue
            assignment_ref = parts[0]
            due_raw = parts[1]
            note = (parts[2] if len(parts) > 2 else "").strip() or None
            aid = _parse_assignment_ref(assignment_ref)
            if aid is None:
                assignment_failures.append(f"invalid assignment id '{assignment_ref}'")
                logger.warning("CoS UPDATE_ASSIGNMENT_DUE invalid id: %r", assignment_ref)
                continue
            due_ok, due_date = _normalize_due_date_input(due_raw)
            if not due_ok:
                assignment_failures.append(f"invalid due date '{due_raw}'")
                logger.warning("CoS UPDATE_ASSIGNMENT_DUE invalid date: %r", due_raw)
                continue
            ok = False
            try:
                ok = db.agent_update_assignment_fields(
                    assignment_id=int(aid),
                    actor_code="navi",
                    due_date=due_date,
                    note=note or "Updated via CoS action",
                )
            except Exception as e:
                ok = False
                logger.warning("CoS UPDATE_ASSIGNMENT_DUE failed: %s", e)
            if ok:
                updated_assignment_due_dates.append(
                    f"A-{int(aid):04d} -> {due_date or '(none)'}"
                )
            else:
                assignment_failures.append(f"failed updating due date for A-{int(aid):04d}")
            continue

        m_title = RETITLE_ASSIGNMENT_PATTERN.match(stripped)
        if m_title:
            payload = (m_title.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 2)]
            if len(parts) < 2:
                assignment_failures.append("invalid RETITLE_ASSIGNMENT format")
                logger.warning("CoS RETITLE_ASSIGNMENT invalid format: %r", stripped)
                continue
            assignment_ref = parts[0]
            new_title = (parts[1] or "").strip()
            note = (parts[2] if len(parts) > 2 else "").strip() or None
            if not new_title:
                assignment_failures.append("empty title in RETITLE_ASSIGNMENT")
                continue
            aid = _parse_assignment_ref(assignment_ref)
            if aid is None:
                assignment_failures.append(f"invalid assignment id '{assignment_ref}'")
                logger.warning("CoS RETITLE_ASSIGNMENT invalid id: %r", assignment_ref)
                continue
            ok = False
            try:
                ok = db.agent_update_assignment_fields(
                    assignment_id=int(aid),
                    actor_code="navi",
                    title=new_title,
                    note=note or "Updated via CoS action",
                )
            except Exception as e:
                ok = False
                logger.warning("CoS RETITLE_ASSIGNMENT failed: %s", e)
            if ok:
                retitled_assignments.append(f"A-{int(aid):04d}")
            else:
                assignment_failures.append(f"failed retitling A-{int(aid):04d}")
            continue

        m_brief = UPDATE_ASSIGNMENT_BRIEF_PATTERN.match(stripped)
        if m_brief:
            payload = (m_brief.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 2)]
            if len(parts) < 2:
                assignment_failures.append("invalid UPDATE_ASSIGNMENT_BRIEF format")
                logger.warning("CoS UPDATE_ASSIGNMENT_BRIEF invalid format: %r", stripped)
                continue
            assignment_ref = parts[0]
            new_brief = (parts[1] or "").strip()
            note = (parts[2] if len(parts) > 2 else "").strip() or None
            if not new_brief:
                assignment_failures.append("empty brief in UPDATE_ASSIGNMENT_BRIEF")
                continue
            aid = _parse_assignment_ref(assignment_ref)
            if aid is None:
                assignment_failures.append(f"invalid assignment id '{assignment_ref}'")
                logger.warning("CoS UPDATE_ASSIGNMENT_BRIEF invalid id: %r", assignment_ref)
                continue
            ok = False
            try:
                ok = db.agent_update_assignment_fields(
                    assignment_id=int(aid),
                    actor_code="navi",
                    brief_md=new_brief,
                    note=note or "Updated via CoS action",
                )
            except Exception as e:
                ok = False
                logger.warning("CoS UPDATE_ASSIGNMENT_BRIEF failed: %s", e)
            if ok:
                updated_assignment_briefs.append(f"A-{int(aid):04d}")
            else:
                assignment_failures.append(f"failed updating brief for A-{int(aid):04d}")
            continue

        m_art = ADD_ASSIGNMENT_ARTIFACT_PATTERN.match(stripped)
        if m_art:
            payload = (m_art.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 3)]
            if len(parts) < 4:
                assignment_failures.append("invalid ADD_ASSIGNMENT_ARTIFACT format")
                logger.warning("CoS ADD_ASSIGNMENT_ARTIFACT invalid format: %r", stripped)
                continue
            assignment_ref = parts[0]
            artifact_type = (parts[1] or "").strip() or "note"
            title = (parts[2] or "").strip() or "Untitled artifact"
            content_md = (parts[3] or "").strip()

            aid = _parse_assignment_ref(assignment_ref)
            if aid is None:
                assignment_failures.append(f"invalid assignment id '{assignment_ref}'")
                logger.warning("CoS ADD_ASSIGNMENT_ARTIFACT invalid id: %r", assignment_ref)
                continue
            row = db.agent_get_assignment(int(aid))
            if not row:
                assignment_failures.append(f"unknown assignment A-{int(aid):04d}")
                continue
            source_thread_id = row.get("source_thread_id")
            try:
                db.agent_add_artifact(
                    artifact_type=artifact_type,
                    assignment_id=int(aid),
                    thread_id=(int(source_thread_id) if source_thread_id else None),
                    title=title,
                    content_md=content_md,
                )
                added_assignment_artifacts.append(f"A-{int(aid):04d}")
            except Exception as e:
                assignment_failures.append(f"failed adding artifact to A-{int(aid):04d}")
                logger.warning("CoS ADD_ASSIGNMENT_ARTIFACT failed: %s", e)
            continue

        cleaned_lines.append(line)
    out = "\n".join(cleaned_lines).strip()
    action_notes = []
    if added_tasks:
        action_notes.append(f"— *Added {added_tasks} task(s) to your dashboard.*")
    if added_tasks_from_assignments:
        action_notes.append(
            f"— *Created {added_tasks_from_assignments} dashboard task(s) from assignment(s).*"
        )
    if skipped_existing_assignment_tasks:
        preview = ", ".join(skipped_existing_assignment_tasks[:3])
        more = " ..." if len(skipped_existing_assignment_tasks) > 3 else ""
        action_notes.append(
            f"— *Skipped {len(skipped_existing_assignment_tasks)} assignment task(s) already on dashboard: {preview}{more}.*"
        )
    if bulk_created_tasks_from_assignments:
        preview = ", ".join(bulk_created_tasks_from_assignments[:3])
        more = " ..." if len(bulk_created_tasks_from_assignments) > 3 else ""
        action_notes.append(
            f"— *Bulk-created dashboard tasks for {len(bulk_created_tasks_from_assignments)} scope(s): {preview}{more}.*"
        )
    if added_blocks:
        action_notes.append(f"— *Scheduled {added_blocks} calendar block(s).*")
    if block_failures:
        reason = block_failure_reasons[0] if block_failure_reasons else "unknown error"
        action_notes.append(
            f"— *Could not schedule {block_failures} calendar block(s): {reason}.*"
        )
    if created_assignments:
        preview = ", ".join(created_assignments[:3])
        more = " ..." if len(created_assignments) > 3 else ""
        action_notes.append(
            f"— *Created {len(created_assignments)} assignment(s): {preview}{more}.*"
        )
    if updated_assignments:
        preview = ", ".join(updated_assignments[:3])
        more = " ..." if len(updated_assignments) > 3 else ""
        action_notes.append(
            f"— *Updated {len(updated_assignments)} assignment(s): {preview}{more}.*"
        )
    if bulk_updated_assignments:
        preview = ", ".join(bulk_updated_assignments[:3])
        more = " ..." if len(bulk_updated_assignments) > 3 else ""
        action_notes.append(
            f"— *Bulk-updated {len(bulk_updated_assignments)} assignment scope(s): {preview}{more}.*"
        )
    if bulk_updated_assignment_priorities:
        preview = ", ".join(bulk_updated_assignment_priorities[:3])
        more = " ..." if len(bulk_updated_assignment_priorities) > 3 else ""
        action_notes.append(
            f"— *Bulk-updated priority for {len(bulk_updated_assignment_priorities)} scope(s): {preview}{more}.*"
        )
    if bulk_updated_assignment_due_dates:
        preview = ", ".join(bulk_updated_assignment_due_dates[:3])
        more = " ..." if len(bulk_updated_assignment_due_dates) > 3 else ""
        action_notes.append(
            f"— *Bulk-updated due date for {len(bulk_updated_assignment_due_dates)} scope(s): {preview}{more}.*"
        )
    if bulk_reassigned_assignments:
        preview = ", ".join(bulk_reassigned_assignments[:3])
        more = " ..." if len(bulk_reassigned_assignments) > 3 else ""
        action_notes.append(
            f"— *Bulk-reassigned {len(bulk_reassigned_assignments)} scope(s): {preview}{more}.*"
        )
    if updated_assignment_priorities:
        preview = ", ".join(updated_assignment_priorities[:3])
        more = " ..." if len(updated_assignment_priorities) > 3 else ""
        action_notes.append(
            f"— *Updated priority for {len(updated_assignment_priorities)} assignment(s): {preview}{more}.*"
        )
    if updated_assignment_due_dates:
        preview = ", ".join(updated_assignment_due_dates[:3])
        more = " ..." if len(updated_assignment_due_dates) > 3 else ""
        action_notes.append(
            f"— *Updated due date for {len(updated_assignment_due_dates)} assignment(s): {preview}{more}.*"
        )
    if retitled_assignments:
        preview = ", ".join(retitled_assignments[:3])
        more = " ..." if len(retitled_assignments) > 3 else ""
        action_notes.append(
            f"— *Retitled {len(retitled_assignments)} assignment(s): {preview}{more}.*"
        )
    if updated_assignment_briefs:
        preview = ", ".join(updated_assignment_briefs[:3])
        more = " ..." if len(updated_assignment_briefs) > 3 else ""
        action_notes.append(
            f"— *Updated brief for {len(updated_assignment_briefs)} assignment(s): {preview}{more}.*"
        )
    if reassigned_assignments:
        preview = ", ".join(reassigned_assignments[:3])
        more = " ..." if len(reassigned_assignments) > 3 else ""
        action_notes.append(
            f"— *Reassigned {len(reassigned_assignments)} assignment(s): {preview}{more}.*"
        )
    if summarized_assignments:
        preview = ", ".join(summarized_assignments[:3])
        more = " ..." if len(summarized_assignments) > 3 else ""
        action_notes.append(
            f"— *Updated summary for {len(summarized_assignments)} assignment(s): {preview}{more}.*"
        )
    if added_assignment_artifacts:
        preview = ", ".join(added_assignment_artifacts[:3])
        more = " ..." if len(added_assignment_artifacts) > 3 else ""
        action_notes.append(
            f"— *Added artifacts to {len(added_assignment_artifacts)} assignment(s): {preview}{more}.*"
        )
    if assignment_failures:
        action_notes.append(
            f"— *Could not process {len(assignment_failures)} assignment action(s): {assignment_failures[0]}.*"
        )
    if action_notes:
        if out:
            out += "\n\n"
        out += "\n".join(action_notes)
    return out

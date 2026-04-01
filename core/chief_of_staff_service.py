"""
Chief of Staff service: plain-text in, plain-text out.
Supports multi-turn; can read dashboard tasks and add tasks via ADD_TASK lines in the response.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional
from dateutil.tz import tzlocal

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
    calendar_write_available,
    create_calendar_event,
    format_events_brief,
    get_calendar_events,
)
from core.cos_doc_search import doc_search, format_hits
from core.chat_retrieval import build_long_term_retrieval_context, format_chat_history_tool_results
from core.user_memory import build_user_memory_context
from core.agent_chat_service import create_assignment_thread, prime_assignment_handoff
from core.tool_registry import invoke_tool

logger = logging.getLogger(__name__)


def _log_timing(event: str, t0: float, **fields) -> None:
    """Best-effort per-request timing log (INFO to file)."""
    try:
        elapsed_ms = int((time.monotonic() - float(t0)) * 1000)
        if fields:
            extra = " ".join(f"{k}={v}" for k, v in fields.items())
            logger.info("TIMING %s elapsed_ms=%s %s", event, elapsed_ms, extra)
        else:
            logger.info("TIMING %s elapsed_ms=%s", event, elapsed_ms)
    except Exception:
        return

# Pattern for CoS to add a task:
# ADD_TASK: text | due_date (MM-DD-YYYY or none) | category (Business or Personal) [| priority(P0-P5|0-5|none)] [| next_action(MM-DD-YYYY|none)] [| project_id|none] [| recurrence]
ADD_TASK_PATTERN = re.compile(r"^\s*ADD_TASK:\s*(.+?)\s*$", re.IGNORECASE)
# Fallback for rich prose task lists, e.g.:
# 1. **Task text** (Business) – Due Friday (03-06-2026).
RICH_TASK_LINE_PATTERN = re.compile(
    r"^\s*\d+\.\s*(?:\*\*)?(?P<task>.+?)(?:\*\*)?\s*\((?P<category>Business|Personal)\)\s*[–—-]\s*Due\b[^\(\n]*\((?P<due>\d{2}-\d{2}-\d{4})\)",
    re.IGNORECASE,
)
# Fallback for compact pipe format in prose/bullets, e.g.:
# - CoDentist: ... | 03-02-2026 | Business
RICH_PIPE_TASK_PATTERN = re.compile(
    r"(?:^|[\r\n]|(?:\s[-*•]\s))(?P<task>[^|\r\n]+?)\s*\|\s*(?P<due>\d{2}-\d{2}-\d{4}|none)\s*\|\s*(?P<category>Business|Personal)\b",
    re.IGNORECASE,
)
PRIORITY_SECTION_PATTERN = re.compile(r"(high|medium|low)\s+priority", re.IGNORECASE)
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

# Task update commands (for AM Sweep persistence)
# TASK_SET_TAGS: task_id | ["tag1","tag2"]
TASK_SET_TAGS_PATTERN = re.compile(r"^\s*TASK_SET_TAGS:\s*(.+?)\s*$", re.IGNORECASE)
# TASK_SET_ESTIMATE: task_id | minutes
TASK_SET_ESTIMATE_PATTERN = re.compile(r"^\s*TASK_SET_ESTIMATE:\s*(.+?)\s*$", re.IGNORECASE)

# Explicit command prefixes that should bypass model translation when the
# user message is already command-only.
ACTION_COMMAND_PREFIXES: tuple[str, ...] = (
    "ADD_TASK:",
    "ADD_CAL_BLOCK:",
    "ASSIGN:",
    "UPDATE_ASSIGNMENT_STATUS:",
    "BULK_UPDATE_ASSIGNMENT_STATUS:",
    "UPDATE_ASSIGNMENT_PRIORITY:",
    "BULK_UPDATE_ASSIGNMENT_PRIORITY:",
    "UPDATE_ASSIGNMENT_DUE:",
    "BULK_UPDATE_ASSIGNMENT_DUE:",
    "REASSIGN:",
    "BULK_REASSIGN_ASSIGNMENTS:",
    "UPDATE_ASSIGNMENT_SUMMARY:",
    "RETITLE_ASSIGNMENT:",
    "UPDATE_ASSIGNMENT_BRIEF:",
    "ADD_ASSIGNMENT_ARTIFACT:",
    "ADD_TASK_FROM_ASSIGNMENT:",
    "BULK_ADD_TASKS_FROM_ASSIGNMENTS:",
    "TASK_SET_TAGS:",
    "TASK_SET_ESTIMATE:",
)

# CoS tool triggers (tool loop)
WEB_SEARCH_TRIGGER = re.compile(r"^\s*WEB_SEARCH:\s*(.+?)\s*$", re.IGNORECASE)
DOC_SEARCH_TRIGGER = re.compile(r"^\s*DOC_SEARCH:\s*(.+?)\s*$", re.IGNORECASE)
MEMORY_SEARCH_TRIGGER = re.compile(r"^\s*MEMORY_SEARCH:\s*(.+?)\s*$", re.IGNORECASE)
CHAT_HISTORY_SEARCH_TRIGGER = re.compile(r"^\s*CHAT_HISTORY_SEARCH:\s*(.+?)\s*$", re.IGNORECASE)


def _now_local():
    return datetime.now()


def _local_time_context(now: Optional[datetime] = None) -> str:
    """
    Build stable local time context for every interaction.
    """
    dt = now or _now_local()
    if getattr(dt, "tzinfo", None):
        local_dt = dt.astimezone()
    else:
        local_dt = dt.replace(tzinfo=tzlocal())
    today = local_dt.strftime("%Y-%m-%d")
    time_str = local_dt.strftime("%I:%M %p").lstrip("0")
    tz_name = local_dt.tzname() or "local"
    offset = local_dt.strftime("%z")
    if len(offset) == 5:
        offset = f"{offset[:3]}:{offset[3:]}"
    return f"Today is {today}, current local time is {time_str} ({tz_name}, UTC{offset})."


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


def _compact_conversation_history(
    conversation_history: List[Tuple[str, str]] | None,
    *,
    max_messages: int = 6,
    max_chars_per_message: int = 1200,
) -> list[tuple[str, str]]:
    compact: list[tuple[str, str]] = []
    for item in conversation_history or []:
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            continue
        role = str(item[0] or "").strip().lower()
        content = str(item[1] or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if len(content) > max_chars_per_message:
            content = content[: max_chars_per_message - 3].rstrip() + "..."
        compact.append((role, content))
    if len(compact) <= max_messages:
        return compact
    return compact[-max_messages:]


def _chat_history_tool_result(
    db: DatabaseManager,
    query: str,
    *,
    chat_id: Optional[int] = None,
) -> tuple[str, str]:
    if not chat_id:
        return "CHAT_HISTORY_RESULTS", "CHAT_HISTORY_RESULTS (untrusted):\n(unavailable for this chat)"
    try:
        result_text = format_chat_history_tool_results(
            db,
            session_id=f"cos_{int(chat_id)}",
            query=query,
            chunk_limit=3,
            raw_turn_limit=8,
        )
    except Exception:
        result_text = "CHAT_HISTORY_RESULTS (untrusted):\n(no matches)"
    return "CHAT_HISTORY_RESULTS", result_text


def _tasks_context_rich(db: DatabaseManager, *, limit: int = 80) -> str:
    """
    Rich task context with IDs and fields so the model can emit TASK_SET_* updates safely.
    """
    try:
        rows = db.list_tasks_rich(
            category=None,
            date_filter="All",
            specific_date=None,
            include_completed=False,
            include_snoozed=False,
            search=None,
            cos_project_id=None,
            sort_by="priority",
            limit=int(limit),
        )
        if not rows:
            return "**Dashboard tasks (rich):** (none)"
        lines: list[str] = []
        for r in rows[: int(limit)]:
            tid = int(r.get("id") or 0)
            text = str(r.get("task_text") or "").strip() or "(empty task)"
            due = str(r.get("due_date") or "").strip()
            pr = int(r.get("priority") or 0)
            est = int(r.get("estimate_minutes") or 0)
            next_action = str(r.get("next_action_date") or "").strip()
            tags_json = str(r.get("tags_json") or "[]").strip()
            due_part = f" due {due}" if due else ""
            next_part = f" next {next_action}" if next_action else ""
            est_part = f" est {est}m" if est else ""
            lines.append(f"- #{tid} P{pr} {text}{due_part}{next_part}{est_part} tags={tags_json}")
        return "**Dashboard tasks (rich, open):**\n" + "\n".join(lines)
    except Exception as e:
        logger.warning("Could not load rich tasks for CoS context: %s", e)
        return "**Dashboard tasks (rich):** (unable to load)"


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
            if isinstance(blocks, list) and blocks:
                block_lines = []
                for raw in blocks:
                    if not isinstance(raw, dict):
                        continue
                    day = str(raw.get("day") or "").strip()
                    start = str(raw.get("start") or "").strip()
                    end = str(raw.get("end") or "").strip()
                    label = str(raw.get("label") or raw.get("title") or "").strip()
                    if not day or not start or not end:
                        continue
                    day_label = {
                        "daily": "Every day",
                        "weekday": "Weekdays",
                        "weekend": "Weekends",
                        "monday": "Monday",
                        "tuesday": "Tuesday",
                        "wednesday": "Wednesday",
                        "thursday": "Thursday",
                        "friday": "Friday",
                        "saturday": "Saturday",
                        "sunday": "Sunday",
                    }.get(day.lower(), day)
                    line = f"- {day_label}: {start}-{end}"
                    if label:
                        line += f" ({label})"
                    block_lines.append(line)
                if block_lines:
                    parts.append("Blocked times (recurring):\n" + "\n".join(block_lines))
                else:
                    parts.append("Blocked times (recurring): " + json.dumps(blocks))
        except Exception:
            parts.append("Blocked times: " + blocked_times_json)
    if deep_work_hours is not None:
        parts.append(f"Default deep work hours per day: {deep_work_hours}")
    if behavior_prefs_json:
        try:
            prefs = json.loads(behavior_prefs_json)
            if isinstance(prefs, dict) and prefs:
                behavior_lines = []
                tone = str(prefs.get("tone") or "").strip()
                if tone:
                    behavior_lines.append(f"- Preferred tone: {tone}")
                planning_detail = str(prefs.get("planning_detail") or "").strip()
                if planning_detail:
                    behavior_lines.append(f"- Planning detail: {planning_detail}")
                scheduling_autonomy = str(prefs.get("scheduling_autonomy") or "").strip()
                if scheduling_autonomy:
                    scheduling_label = {
                        "ask_first": "Always ask before scheduling.",
                        "draft_first": "Draft first, then confirm.",
                        "can_schedule_when_clear": "Go ahead and schedule when the request is clear.",
                    }.get(scheduling_autonomy, scheduling_autonomy)
                    behavior_lines.append(f"- Scheduling autonomy: {scheduling_label}")
                if bool(prefs.get("protect_evenings")):
                    behavior_lines.append("- Protect evenings from optional work.")
                if bool(prefs.get("protect_weekends")):
                    behavior_lines.append("- Protect weekends from optional work.")
                if bool(prefs.get("confirm_ambiguous_tasks")):
                    behavior_lines.append("- Ask before creating tasks when intent is ambiguous.")
                remaining = {
                    key: value
                    for key, value in prefs.items()
                    if key
                    not in {
                        "tone",
                        "planning_detail",
                        "scheduling_autonomy",
                        "protect_evenings",
                        "protect_weekends",
                        "confirm_ambiguous_tasks",
                    }
                }
                if remaining:
                    behavior_lines.append("- Additional behavior prefs: " + json.dumps(remaining))
                if behavior_lines:
                    parts.append("Behavior prefs:\n" + "\n".join(behavior_lines))
                else:
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

    local_tz, time_min_today, time_max_today, time_min_week, time_max_week = _calendar_query_windows()
    try:
        todays = get_calendar_events(time_min=time_min_today, time_max=time_max_today)
        upcoming = get_calendar_events(time_min=time_min_week, time_max=time_max_week)
        return (
            "**Calendar (today):**\n"
            + format_events_brief(todays, tz=local_tz)
            + "\n\n**Calendar (next 7 days):**\n"
            + format_events_brief(upcoming, tz=local_tz)
        )
    except Exception as e:
        return "**Calendar:** (error loading) " + str(e)


def _calendar_query_windows(now: Optional[datetime] = None) -> tuple[object, str, str, str, str]:
    """Return local tz plus UTC query windows anchored to local midnight."""
    base = now or datetime.now().astimezone()
    if getattr(base, "tzinfo", None):
        local_dt = base.astimezone(base.tzinfo)
    else:
        local_dt = base.replace(tzinfo=tzlocal())
    local_tz = local_dt.tzinfo or timezone.utc
    local_day_start = local_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    local_day_end = local_day_start + timedelta(days=1)
    local_week_end = local_day_start + timedelta(days=7)

    def _to_utc_z(value: datetime) -> str:
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return (
        local_tz,
        _to_utc_z(local_day_start),
        _to_utc_z(local_day_end),
        _to_utc_z(local_day_start),
        _to_utc_z(local_week_end),
    )


def _emails_context(db: DatabaseManager) -> str:
    """Format important emails (best-effort) for AM Sweep context."""
    try:
        rows = db.list_important_emails(limit=25, days=14, include_triaged=False)
    except Exception as e:
        logger.warning("Could not load important emails for CoS context: %s", e)
        return "**Important emails:** (unable to load)"

    if not rows:
        return "**Important emails (last 14 days):** (none)"

    from datetime import datetime, UTC

    now_utc = datetime.now(UTC)
    lines: list[str] = []
    for r in rows[:25]:
        sender = str(r.get("sender") or "").strip() or "(unknown sender)"
        subject = str(r.get("subject") or "").strip() or "(no subject)"
        ts = r.get("timestamp")
        age = ""
        try:
            if ts is not None:
                dt = datetime.fromtimestamp(int(ts), tz=UTC)
                delta = now_utc - dt
                days = int(delta.total_seconds() // 86400)
                if days <= 0:
                    age = " (today)"
                elif days == 1:
                    age = " (1d ago)"
                else:
                    age = f" ({days}d ago)"
        except Exception:
            age = ""

        flags: list[str] = []
        if str(r.get("client_name") or "").strip():
            flags.append(f"CLIENT:{r.get('client_name')}")
        if str(r.get("project_name") or "").strip():
            flags.append(f"PROJECT:{r.get('project_name')}")
        flag_str = f" [{'|'.join(flags)}]" if flags else ""

        folder = str(r.get("folder") or "").strip()
        account = str(r.get("account") or "").strip()
        src = str(r.get("source") or "").strip()
        meta = " / ".join(x for x in (account, folder, src) if x)
        meta_str = f" — {meta}" if meta else ""

        # Keep line compact; avoid dumping full email bodies into prompt.
        lines.append(f"- {sender}: {subject}{age}{flag_str}{meta_str}")

    return "**Important emails (needs attention, last 14 days):**\n" + "\n".join(lines)


def cos_am_sweep(
    db: DatabaseManager,
    *,
    conversation_history: List[Tuple[str, str]] | None = None,
    chat_id: Optional[int] = None,
) -> str:
    """
    AM Sweep: triage today's operational state into Dispatch/Prep/Yours/Skip and emit action lines.
    Reuses the same action parser as cos_response so ASSIGN/ADD_TASK/ADD_CAL_BLOCK side effects work.
    """
    t0 = time.monotonic()
    now = _now_local()
    local_time_ctx = _local_time_context(now)
    prefs = db.cos_get_preferences()
    prefs_ctx = _preferences_context(prefs)

    tasks_ctx = _tasks_context_rich(db)
    assignments_ctx = _assignments_context(db)
    cal_ctx = _calendar_context()
    emails_ctx = _emails_context(db)
    mem_ctx = _memory_context(db, "AM Sweep", chat_id)

    cal_ok, cal_reason = calendar_write_available()
    if cal_ok:
        calendar_instructions = """

Calendar scheduling is available, but it is OPTIONAL. If you include calendar blocks, only schedule blocks for \"Yours\" work and only when you are confident about the time window. To schedule a block, write one or more lines in this exact format (one block per line):
ADD_CAL_BLOCK: <title> | <start datetime> | <end datetime> | <calendar id or "primary">
Prefer ISO-8601 datetimes with timezone offsets.
Omit ADD_CAL_BLOCK lines if you are not scheduling calendar blocks.
""".rstrip()
    else:
        reason = (cal_reason or "").strip() or "not configured"
        calendar_instructions = f"""

Calendar scheduling is currently unavailable ({reason}). Do not output ADD_CAL_BLOCK lines or claim you scheduled anything. If time-blocking would help, propose a schedule in prose and/or add a dashboard task reminder instead.
""".rstrip()

    system = f"""You are an AI Chief of Staff running Adam's AM Sweep.

Purpose: take the current operational state (tasks, calendar, important emails, delegated assignments) and produce an action-ready plan for TODAY.

Priority semantics (critical—many systems use P0 for "highest"; we do not):
- Dashboard tasks: P0 = lowest urgency (background), P5 = highest urgency (urgent).
- When writing the executive summary or any prose, never call P0 or P1 "high priority".
- Reserve "high priority" / "urgent" for P4–P5 only. P0 often indicates unspecified or background work.

Hard boundaries:
- Never send email. You may draft, but drafts must be routed as assignments (Quill) or described as drafts for review.
- Do not make pricing decisions, relationship-sensitive decisions, or final regulatory strategy calls. If uncertain, choose PREP or YOURS.
- Prefer explicit, machine-parseable action lines for any change you want executed.

Classification buckets (exactly one per item):
- Dispatch: can be completed to review-ready output by an agent with minimal ambiguity.
- Prep: can be brought ~80% ready; requires Adam's judgment to finish.
- Yours: requires Adam's judgment/presence/sign-off.
- Skip: not actionable today (defer/snooze), waiting on inputs, or low value today.

Routing (use these agent names in ASSIGN lines):
- Quill: drafts/rewrites (emails, briefs, follow-ups). Never sends; produces drafts + variants + questions.
- Atlas: research with citations + gaps + recommended next queries.
- Lex: contract/policy extraction + obligations + decisions needed.
- Ledger: billing/invoice prep + anomalies/questions.
- Archive: notes/filing/timelines + links to source items.
- Sentinel: QA pass / risk flags / consistency checks.
- Scout: prospect/lead recon + outreach prep.
- Mason: task triage + command emission (use sparingly; you are already doing AM Sweep).
- Pulse: briefing/monitoring summaries (rare in AM Sweep).
- Shield: secrets/safety check.

Assignment brief templates (use these patterns so outputs are consistent):
- Quill brief must include: (1) the goal; (2) key facts to preserve; (3) 2 tone variants; (4) explicit questions for Adam; (5) a \"draft only\" reminder.
- Atlas brief must include: (1) exact research question; (2) scope limits; (3) must cite sources with URLs; (4) deliver: findings + gaps + recommended next queries.
- Lex brief must include: (1) document type; (2) extraction targets (obligations, deadlines, risks); (3) output: bullet list + decision points.
- Ledger brief must include: (1) time window; (2) client/project; (3) deliver: draft invoice inputs + anomalies + questions.
- Archive brief must include: (1) what to update; (2) structure; (3) output: clean notes + action items + links to source items.
- Sentinel brief must include: (1) what to QA; (2) checklist (clarity, missing info, contradictions, risky wording); (3) output: issues + suggested fixes.

Output format requirements:
1) Start with a short executive summary (3-6 bullets max).
2) Then four sections in this order with bullet lists: Dispatch, Prep, Yours, Skip.
3) Optionally include a short \"Time-block proposal\" paragraph after Skip (prose only). If calendar scheduling is unavailable, this is the ONLY scheduling output you should produce.
4) End with a final section titled exactly: \"## Actions (machine)\".
   Under that header, output ONLY machine-action lines (no bullets, no commentary).

Parallelism expectation:
- If there are multiple Dispatch/Prep items, emit MULTIPLE ASSIGN lines (one per item/agent) so work can run in parallel.

Action commands you may output:
- ADD_TASK: <task description> | <MM-DD-YYYY or none> | <Business or Personal> [| <priority P0-P5 or 0-5 or none>] [| <next action date MM-DD-YYYY or none>] [| <project id or none>] [| <recurrence: None|Daily|Weekly|Monthly>]
- TASK_SET_TAGS: <task_id> | <json array of tags>    (example: TASK_SET_TAGS: 123 | [\"triage:dispatch\",\"source:am_sweep\"])
- TASK_SET_ESTIMATE: <task_id> | <minutes>           (0-600, example: TASK_SET_ESTIMATE: 123 | 45)
- ASSIGN: <AgentName> | <Title> | <Brief> | <P1-P5> | <YYYY-MM-DD or none>
{calendar_instructions}

Do not use P0 as a placeholder for "unspecified." Include a real best-effort priority whenever you can infer it from urgency, due date, or surrounding High/Medium/Low context.

When generating ASSIGN briefs, be specific about expected output and include any needed context from the inputs below.
Always interpret and communicate schedule/time references in Adam's local timezone; include timezone offsets when scheduling.
""".strip()

    time_ctx = local_time_ctx
    if prefs_ctx:
        time_ctx += f"\n\n**His stated preferences / constraints:**\n{prefs_ctx}"
    if cal_ctx:
        time_ctx += f"\n\n{cal_ctx}"
    if emails_ctx:
        time_ctx += f"\n\n{emails_ctx}"
    if mem_ctx:
        time_ctx += f"\n\n{mem_ctx}"
    time_ctx += f"\n\n{tasks_ctx}\n\n{assignments_ctx}"

    user_prompt = (
        "Run AM Sweep now.\n\n"
        "Remember: put any command lines only under '## Actions (machine)'."
    )

    try:
        if conversation_history:
            messages = [{"role": "system", "content": system + "\n\n" + time_ctx}]
            for role, content in conversation_history:
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
            messages.append({"role": "user", "content": user_prompt})
            out = _cos_run_tool_loop_messages(db, messages, chat_id=chat_id)
        else:
            out = _cos_run_tool_loop_single(db, system + "\n\n" + time_ctx, user_prompt, chat_id=chat_id)
        cleaned = _parse_and_add_tasks(db, (out or "").strip(), chat_id=chat_id)
        _extract_and_store_memory(db, chat_id=chat_id, user_message="AM Sweep", assistant_message=cleaned)
        _log_timing(
            "cos_am_sweep",
            t0,
            chat_id=chat_id,
            history_len=len(conversation_history or []),
            out_chars=len(out or ""),
        )
        return cleaned
    except Exception as e:
        logger.exception("CoS AM Sweep failed: %s", e)
        _log_timing("cos_am_sweep_error", t0, chat_id=chat_id)
        return f"Error: {e}"

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

    session_id = f"cos_{int(chat_id)}" if chat_id is not None else None
    try:
        retrieval_context = build_long_term_retrieval_context(
            db,
            q,
            session_id=session_id,
            chunk_limit=3,
            raw_turn_limit=6,
        )
    except Exception:
        retrieval_context = ""
    if retrieval_context:
        parts.append(retrieval_context)
    else:
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

    try:
        global_memory = build_user_memory_context(db, q, limit=4, recent_limit=2)
    except Exception:
        global_memory = ""
    if global_memory:
        parts.append(global_memory)

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
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except Exception:
            return False, None
        return True, dt.strftime("%Y-%m-%d")
    if re.match(r"^\d{2}-\d{2}-\d{4}$", raw):
        try:
            dt = datetime.strptime(raw, "%m-%d-%Y")
        except Exception:
            return False, None
        return True, dt.strftime("%Y-%m-%d")
    return False, None


def _normalize_dashboard_mmddyyyy(value: str) -> tuple[bool, Optional[str]]:
    """
    Parse a dashboard-task date input into MM-DD-YYYY.
    Accepts:
    - MM-DD-YYYY
    - YYYY-MM-DD
    - none/null/n/a/blank -> None
    """
    raw = (value or "").strip()
    if not raw or raw.lower() in {"none", "null", "n/a"}:
        return True, None
    if re.match(r"^\d{2}-\d{2}-\d{4}$", raw):
        try:
            dt = datetime.strptime(raw, "%m-%d-%Y")
        except Exception:
            return False, None
        return True, dt.strftime("%m-%d-%Y")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except Exception:
            return False, None
        return True, dt.strftime("%m-%d-%Y")
    return False, None


def _parse_task_priority_value(value: str) -> Optional[int]:
    """Parse task priority like P0..P5 or 0..5 into int."""
    s = str(value or "").strip()
    if not s or s.lower() in {"none", "null", "n/a"}:
        return None
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits == "":
        return None
    try:
        p = int(digits)
    except Exception:
        return None
    if p < 0:
        p = 0
    if p > 5:
        p = 5
    return p


def _section_priority_value(label: str) -> Optional[int]:
    normalized = str(label or "").strip().lower()
    return {
        "high": 4,
        "medium": 2,
        "low": 1,
    }.get(normalized)


def _infer_priority_section_label(text: str) -> Optional[str]:
    hits = PRIORITY_SECTION_PATTERN.findall(str(text or ""))
    if not hits:
        return None
    return str(hits[-1] or "").strip().lower() or None


def _infer_task_priority(
    task_text: str,
    *,
    due_date: Optional[str] = None,
    section_label: Optional[str] = None,
    raw_context: Optional[str] = None,
) -> Optional[int]:
    """Infer dashboard task priority from explicit context before falling back to clarification."""
    sec = _section_priority_value(section_label or _infer_priority_section_label(raw_context or ""))
    if sec is not None:
        return sec

    hay = f"{task_text} {raw_context or ''}".strip().lower()
    if any(
        term in hay
        for term in (
            "critical",
            "urgent",
            "asap",
            "as soon as possible",
            "immediately",
            "right away",
            "blocker",
            "unblock",
            "today",
            "tonight",
        )
    ):
        return 4
    if any(
        term in hay
        for term in (
            "low priority",
            "background",
            "backlog",
            "someday",
            "when you can",
            "non-urgent",
        )
    ):
        return 1

    due_norm = None
    if due_date:
        ok_due, due_norm = _normalize_dashboard_mmddyyyy(due_date)
        if not ok_due:
            due_norm = None
    if due_norm:
        try:
            due_dt = datetime.strptime(due_norm, "%m-%d-%Y").date()
            today = datetime.now().date()
            delta = (due_dt - today).days
            if delta <= 0:
                return 4
            if delta <= 2:
                return 3
            if delta <= 7:
                return 2
        except Exception:
            pass
    return None


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


def _extract_explicit_action_lines(message: str) -> list[str]:
    """
    Return command lines when message is command-only.

    This enables deterministic execution for explicit user commands instead of
    relying on the model to re-emit tool syntax.
    """
    lines: list[str] = []
    for raw_line in (message or "").splitlines():
        line = (raw_line or "").strip()
        if not line:
            continue
        # Allow users to wrap commands in markdown code fences.
        if line.startswith("```"):
            continue
        lines.append(line)
    if not lines:
        return []
    for line in lines:
        up = line.upper()
        if not any(up.startswith(prefix) for prefix in ACTION_COMMAND_PREFIXES):
            return []
    return lines


def _cos_tool_results_for_trigger(db: DatabaseManager, out: str, *, chat_id: Optional[int] = None) -> Optional[tuple[str, str]]:
    """
    If out is a tool trigger, return (tool_name, tool_result_text). Else None.
    Shared by both AM Sweep and normal CoS responses.
    """
    out = (out or "").strip()
    m_web = WEB_SEARCH_TRIGGER.match(out)
    m_doc = DOC_SEARCH_TRIGGER.match(out)
    m_mem = MEMORY_SEARCH_TRIGGER.match(out)
    m_hist = CHAT_HISTORY_SEARCH_TRIGGER.match(out)
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
        try:
            result = invoke_tool(
                "doc_search",
                db=db,
                caller_type="cos",
                caller_id="chief_of_staff",
                session_id=f"cos_{int(chat_id)}" if chat_id is not None else None,
                query=query,
                limit=10,
            )
        except Exception:
            result = {"hits": []}
        hits = result.get("hits") or []
        formatted = format_hits([type("DocHitShim", (), hit)() for hit in hits]) if hits else "(no matches)"
        return "DOC_SEARCH_RESULTS", "DOC_SEARCH_RESULTS (untrusted):\n" + formatted
    if m_mem:
        query = m_mem.group(1).strip()
        try:
            result = invoke_tool(
                "memory_search",
                db=db,
                caller_type="cos",
                caller_id="chief_of_staff",
                session_id=f"cos_{int(chat_id)}" if chat_id is not None else None,
                query=query,
                chat_id=chat_id,
                limit=10,
            )
        except Exception:
            result = {"rows": []}
        rows = result.get("rows") or []
        lines = []
        for row in rows[:10]:
            lines.append(f"- ({row.get('kind')}) {row.get('content')}")
        return "MEMORY_SEARCH_RESULTS", "MEMORY_SEARCH_RESULTS (untrusted):\n" + ("\n".join(lines) if lines else "(no matches)")
    if m_hist:
        query = m_hist.group(1).strip()
        try:
            result = invoke_tool(
                "chat_history_search",
                db=db,
                caller_type="cos",
                caller_id="chief_of_staff",
                session_id=f"cos_{int(chat_id)}" if chat_id is not None else None,
                query=query,
                history_session_id=f"cos_{int(chat_id)}" if chat_id is not None else "",
            )
            return "CHAT_HISTORY_RESULTS", result.get("text") or "CHAT_HISTORY_RESULTS (untrusted):\n(no matches)"
        except Exception:
            return _chat_history_tool_result(db, query, chat_id=chat_id)
    return None


def _cos_run_tool_loop_single(
    db: DatabaseManager,
    system_text: str,
    user_text: str,
    *,
    chat_id: Optional[int] = None,
) -> str:
    """Tool loop for single-turn CoS flows using grok_completion."""
    user_aug = user_text
    out = ""
    for _ in range(3):
        out = grok_completion(system_text, user_aug, model=MODEL_COS)
        out = (out or "").strip()
        if not out:
            return out
        tool = _cos_tool_results_for_trigger(db, out, chat_id=chat_id)
        if not tool:
            return out
        _, tool_text = tool
        user_aug = user_text + "\n\n" + tool_text
    return out


def _cos_run_tool_loop_messages(
    db: DatabaseManager,
    messages: list[dict],
    *,
    chat_id: Optional[int] = None,
) -> str:
    """Tool loop for multi-turn CoS flows using grok_completion_messages."""
    msgs = list(messages)
    out = ""
    for _ in range(3):
        out = grok_completion_messages(msgs, model=MODEL_COS)
        out = (out or "").strip()
        if not out:
            return out
        tool = _cos_tool_results_for_trigger(db, out, chat_id=chat_id)
        if not tool:
            return out
        _, tool_text = tool
        msgs.append({"role": "user", "content": tool_text})
    return out


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
    t0 = time.monotonic()
    explicit_action_lines = _extract_explicit_action_lines(user_message or "")
    if explicit_action_lines:
        try:
            response = _parse_and_add_tasks(db, "\n".join(explicit_action_lines), chat_id=chat_id)
            _extract_and_store_memory(
                db,
                chat_id=chat_id,
                user_message=user_message,
                assistant_message=response,
            )
            _log_timing("cos_response", t0, mode="explicit", chat_id=chat_id, chars=len(user_message or ""))
            return response
        except Exception as e:
            logger.exception("CoS explicit command handling failed: %s", e)
            _log_timing("cos_response_error", t0, mode="explicit", chat_id=chat_id)
            return f"Error: {e}"

    now = _now_local()
    local_time_ctx = _local_time_context(now)
    prefs = db.cos_get_preferences()
    prefs_ctx = _preferences_context(prefs)

    tasks_ctx = _tasks_context(db)
    assignments_ctx = _assignments_context(db)
    cal_ctx = _calendar_context()
    mem_ctx = _memory_context(db, user_message, chat_id)

    cal_ok, cal_reason = calendar_write_available()
    if cal_ok:
        calendar_instructions = """

You may also schedule calendar blocks when he explicitly asks for it. To schedule a block, write one or more lines in this exact format (one block per line):
ADD_CAL_BLOCK: <title> | <start datetime> | <end datetime> | <calendar id or "primary">
Example: ADD_CAL_BLOCK: Deep work - client report | 2026-02-25T13:00:00-05:00 | 2026-02-25T14:30:00-05:00 | primary
Prefer ISO-8601 datetimes with timezone offsets.
Omit ADD_CAL_BLOCK lines if you are not scheduling calendar blocks.
""".rstrip()
    else:
        reason = (cal_reason or "").strip() or "not configured"
        calendar_instructions = f"""

Calendar scheduling is currently unavailable ({reason}). Do not output ADD_CAL_BLOCK lines or claim you scheduled anything. If the user asks to schedule, propose times and/or add a dashboard task reminder instead.
""".rstrip()

    system = f"""You are an AI Chief of Staff for Adam. He tells you in plain text what he's working on and what has come up that needs to be dealt with. You help him plan, prioritize, and reduce cognitive load. You respect his constraints: time freedom, low context switching, family boundaries. You give direct, concise advice and challenge assumptions when useful. You do not take autonomous actions—only recommend and advise. Respond in whatever form is most helpful; no required format.

Priority scale is numeric and consistent:
- Dashboard tasks: P0 (lowest urgency) … P5 (highest urgency).
- Delegation assignments: P1 (lowest urgency) … P5 (highest urgency).

You can see his current dashboard task list and may add tasks to it. To add a task, write one or more lines in this exact format (one task per line):
ADD_TASK: <task description> | <due date as MM-DD-YYYY or "none"> | <Business or Personal> [| <priority P0-P5 or 0-5 or none>] [| <next action date MM-DD-YYYY or none>] [| <project id or none>] [| <recurrence: None|Daily|Weekly|Monthly>]
Examples:
- ADD_TASK: Send follow-up to client | 02-25-2026 | Business | P3
- ADD_TASK: Draft DHF gap memo | 03-05-2026 | Business | P1 | 03-03-2026 | 12 | Weekly
When adding a task, include priority whenever you can infer it from urgency, timing, or the surrounding plan context. Do not use P0 as a placeholder for "unspecified." If the user asked you to add a task and priority is genuinely unclear, ask a short follow-up question instead of outputting an ADD_TASK line with no priority.
Omit ADD_TASK lines if you are not adding any tasks.
{calendar_instructions}

You may also delegate work to named team members by writing one or more lines in this exact format:
ASSIGN: <AgentName> | <Title> | <Brief> | <P1-P5> | <YYYY-MM-DD or none>
Example: ASSIGN: Atlas | FDA PCCP research brief | Research latest guidance and summarize with citations. | P5 | 2026-03-01
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

In ongoing chats, you may only see a compact recent window of the conversation by default. If older context matters, request chat history instead of guessing.

If you need more information to answer well, you may request one of these tools by returning EXACTLY ONE line with one of:
- WEB_SEARCH:<query>
- DOC_SEARCH:<query>   (searches local docs/notes and optional RAG index)
- MEMORY_SEARCH:<query> (searches stored CoS memory)
- CHAT_HISTORY_SEARCH:<query> (searches older messages from this chat only)

If you request a tool, you must return only that single tool line (no other text).

Always interpret and communicate schedule/time references in the user's local timezone provided in context, and include timezone for time-sensitive schedule updates."""

    def _tool_results_for_trigger(out: str) -> Optional[tuple[str, str]]:
        """
        If out is a tool trigger, return (tool_name, tool_result_text). Else None.
        """
        out = (out or "").strip()
        m_web = WEB_SEARCH_TRIGGER.match(out)
        m_doc = DOC_SEARCH_TRIGGER.match(out)
        m_mem = MEMORY_SEARCH_TRIGGER.match(out)
        m_hist = CHAT_HISTORY_SEARCH_TRIGGER.match(out)
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
            try:
                result = invoke_tool(
                    "doc_search",
                    db=db,
                    caller_type="cos",
                    caller_id="chief_of_staff",
                    session_id=f"cos_{int(chat_id)}" if chat_id is not None else None,
                    query=query,
                    limit=10,
                )
            except Exception:
                result = {"hits": []}
            hits = result.get("hits") or []
            formatted = format_hits([type("DocHitShim", (), hit)() for hit in hits]) if hits else "(no matches)"
            return "DOC_SEARCH_RESULTS", "DOC_SEARCH_RESULTS (untrusted):\n" + formatted
        if m_mem:
            query = m_mem.group(1).strip()
            try:
                result = invoke_tool(
                    "memory_search",
                    db=db,
                    caller_type="cos",
                    caller_id="chief_of_staff",
                    session_id=f"cos_{int(chat_id)}" if chat_id is not None else None,
                    query=query,
                    chat_id=chat_id,
                    limit=10,
                )
            except Exception:
                result = {"rows": []}
            rows = result.get("rows") or []
            lines = []
            for row in rows[:10]:
                lines.append(f"- ({row.get('kind')}) {row.get('content')}")
            return "MEMORY_SEARCH_RESULTS", "MEMORY_SEARCH_RESULTS (untrusted):\n" + ("\n".join(lines) if lines else "(no matches)")
        if m_hist:
            query = m_hist.group(1).strip()
            try:
                result = invoke_tool(
                    "chat_history_search",
                    db=db,
                    caller_type="cos",
                    caller_id="chief_of_staff",
                    session_id=f"cos_{int(chat_id)}" if chat_id is not None else None,
                    query=query,
                    history_session_id=f"cos_{int(chat_id)}" if chat_id is not None else "",
                )
                return "CHAT_HISTORY_RESULTS", result.get("text") or "CHAT_HISTORY_RESULTS (untrusted):\n(no matches)"
            except Exception:
                return _chat_history_tool_result(db, query, chat_id=chat_id)
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
        user = local_time_ctx
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
            _log_timing(
                "cos_response",
                t0,
                mode="llm_single",
                chat_id=chat_id,
                chars=len(user_message or ""),
                history_len=0,
                out_chars=len(out or ""),
            )
            return cleaned
        except Exception as e:
            logger.exception("CoS response failed: %s", e)
            _log_timing("cos_response_error", t0, mode="llm_single", chat_id=chat_id)
            return f"Error: {e}"

    # Multi-turn: build messages list. Caller must have saved the current user message and included it in conversation_history.
    time_ctx = local_time_ctx
    if prefs_ctx:
        time_ctx += f"\n\n**His stated preferences / constraints:**\n{prefs_ctx}"
    if cal_ctx:
        time_ctx += f"\n\n{cal_ctx}"
    if mem_ctx:
        time_ctx += f"\n\n{mem_ctx}"
    time_ctx += f"\n\n{tasks_ctx}\n\n{assignments_ctx}"
    recent_history = _compact_conversation_history(conversation_history)
    messages = [{"role": "system", "content": system + "\n\n" + time_ctx}]
    for role, content in recent_history:
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    try:
        out = _run_tool_loop_messages(messages)
        cleaned = _parse_and_add_tasks(db, (out or "").strip(), chat_id=chat_id)
        _extract_and_store_memory(db, chat_id=chat_id, user_message=user_message, assistant_message=cleaned)
        _log_timing(
            "cos_response",
            t0,
            mode="llm_multi",
            chat_id=chat_id,
            chars=len(user_message or ""),
            history_len=len(conversation_history or []),
            history_used_len=len(recent_history),
            out_chars=len(out or ""),
        )
        return cleaned
    except Exception as e:
        logger.exception("CoS response failed: %s", e)
        _log_timing("cos_response_error", t0, mode="llm_multi", chat_id=chat_id)
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
    updated_task_tags = 0
    updated_task_estimates = 0
    task_update_failures: list[str] = []
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
    ambiguous_task_priorities: list[str] = []
    assignment_failures: list[str] = []
    block_failures = 0
    block_failure_reasons: list[str] = []
    cleaned_lines = []
    existing_assignment_task_ids_cache: set[int] | None = None
    explicit_add_task_seen = False

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
                tid = create_assignment_thread(
                    db,
                    assignment_id=int(assignment_id),
                    assignee_code=assignee_code,
                    reason=reason,
                    actor_code="navi",
                    context_json={"source": reason},
                )
                if tid:
                    prime_assignment_handoff(
                        db,
                        assignment_id=int(assignment_id),
                        thread_id=int(tid),
                    )
        except Exception:
            return

    for line in response.splitlines():
        stripped = line.strip()

        m_set_tags = TASK_SET_TAGS_PATTERN.match(stripped)
        if m_set_tags:
            payload = (m_set_tags.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 1)]
            if len(parts) != 2:
                task_update_failures.append("invalid TASK_SET_TAGS format")
                logger.warning("CoS TASK_SET_TAGS invalid format: %r", stripped)
                continue
            task_id_raw, tags_raw = parts
            try:
                task_id = int("".join(ch for ch in task_id_raw if ch.isdigit()) or "0")
            except Exception:
                task_id = 0
            if task_id <= 0:
                task_update_failures.append(f"invalid task id '{task_id_raw}'")
                logger.warning("CoS TASK_SET_TAGS invalid task id: %r", task_id_raw)
                continue
            try:
                tags_obj = json.loads(tags_raw)
            except Exception:
                tags_obj = None
            if not isinstance(tags_obj, list):
                task_update_failures.append(f"TASK_SET_TAGS invalid json for task {task_id}")
                logger.warning("CoS TASK_SET_TAGS invalid json: %r", tags_raw)
                continue
            incoming: list[str] = []
            for t in tags_obj[:40]:
                s = str(t).strip()
                if not s:
                    continue
                incoming.append(s[:64] if len(s) > 64 else s)
            if not incoming:
                task_update_failures.append(f"TASK_SET_TAGS empty tags for task {task_id}")
                continue

            row = None
            try:
                row = db.get_task_by_id(int(task_id))  # type: ignore[attr-defined]
            except Exception:
                row = None
            if not row:
                task_update_failures.append(f"TASK_SET_TAGS task not found: {task_id}")
                continue

            existing_tags: list[str] = []
            try:
                existing_obj = json.loads(str(row.get("tags_json") or "[]"))
                if isinstance(existing_obj, list):
                    existing_tags = [str(x).strip() for x in existing_obj if str(x).strip()]
            except Exception:
                existing_tags = []

            merged: list[str] = []
            seen: set[str] = set()
            for t in (existing_tags + incoming):
                tt = str(t).strip()
                if not tt or tt in seen:
                    continue
                seen.add(tt)
                merged.append(tt)
            try:
                db.update_task_by_id(task_id=int(task_id), tags_json=json.dumps(merged, ensure_ascii=False))
                updated_task_tags += 1
            except Exception as e:
                task_update_failures.append(f"TASK_SET_TAGS update failed for task {task_id}: {e}")
            continue

        m_set_est = TASK_SET_ESTIMATE_PATTERN.match(stripped)
        if m_set_est:
            payload = (m_set_est.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|", 1)]
            if len(parts) != 2:
                task_update_failures.append("invalid TASK_SET_ESTIMATE format")
                logger.warning("CoS TASK_SET_ESTIMATE invalid format: %r", stripped)
                continue
            task_id_raw, minutes_raw = parts
            try:
                task_id = int("".join(ch for ch in task_id_raw if ch.isdigit()) or "0")
            except Exception:
                task_id = 0
            if task_id <= 0:
                task_update_failures.append(f"invalid task id '{task_id_raw}'")
                logger.warning("CoS TASK_SET_ESTIMATE invalid task id: %r", task_id_raw)
                continue
            try:
                minutes = int("".join(ch for ch in minutes_raw if ch.isdigit()) or "0")
            except Exception:
                minutes = 0
            if minutes < 0:
                minutes = 0
            if minutes > 600:
                minutes = 600
            row = None
            try:
                row = db.get_task_by_id(int(task_id))  # type: ignore[attr-defined]
            except Exception:
                row = None
            if not row:
                task_update_failures.append(f"TASK_SET_ESTIMATE task not found: {task_id}")
                continue
            try:
                db.update_task_by_id(task_id=int(task_id), estimate_minutes=int(minutes))
                updated_task_estimates += 1
            except Exception as e:
                task_update_failures.append(f"TASK_SET_ESTIMATE update failed for task {task_id}: {e}")
            continue

        m = ADD_TASK_PATTERN.match(stripped)
        if m:
            explicit_add_task_seen = True
            payload = (m.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|")]
            if len(parts) < 3:
                logger.warning("CoS ADD_TASK rejected due to invalid format: %r", stripped)
                continue

            task_text = (parts[0] or "").strip()
            due_raw = (parts[1] or "").strip()
            category = (parts[2] or "").strip().title()
            if not task_text or category not in {"Business", "Personal"}:
                logger.warning("CoS ADD_TASK rejected due to invalid task/category: %r", stripped)
                continue

            due_ok, due_norm = _normalize_dashboard_mmddyyyy(due_raw)
            if not due_ok:
                logger.warning("CoS ADD_TASK rejected due to invalid due date: %r", due_raw)
                continue

            priority = _parse_task_priority_value(parts[3] if len(parts) > 3 else "")
            if priority is None:
                priority = _infer_task_priority(task_text, due_date=due_norm, raw_context=stripped)
            if priority is None:
                ambiguous_task_priorities.append(task_text)
                logger.info("CoS ADD_TASK deferred pending priority clarification: %r", task_text)
                continue
            next_action_ok, next_action = _normalize_dashboard_mmddyyyy(parts[4] if len(parts) > 4 else "")
            if not next_action_ok:
                logger.warning("CoS ADD_TASK rejected due to invalid next-action date: %r", parts[4] if len(parts) > 4 else "")
                continue
            project_raw = (parts[5] if len(parts) > 5 else "").strip()
            recurrence_raw = (parts[6] if len(parts) > 6 else "").strip()
            recurrence = recurrence_raw if recurrence_raw else "None"
            if recurrence.lower() in {"none", "null", "n/a"}:
                recurrence = "None"
            # Keep recurrence constrained to known UI options unless explicitly custom.
            if recurrence not in {"None", "Daily", "Weekly", "Monthly"}:
                recurrence = "None"

            cos_project_id: Optional[int] = None
            if project_raw and project_raw.lower() not in {"none", "null", "n/a"}:
                try:
                    cos_project_id = int(project_raw)
                except Exception:
                    cos_project_id = None
            try:
                task_id = db.add_task(
                    session_id=session_id,
                    task_text=task_text,
                    due_date=due_norm,
                    category=category,
                    recurrence=recurrence,
                    completed=0,
                    cos_project_id=cos_project_id,
                )
                # Apply optional richer fields available in the Tasks table.
                if priority is not None or next_action is not None:
                    db.update_task_by_id(
                        task_id=int(task_id),
                        priority=priority if priority is not None else db._UNSET,  # type: ignore[attr-defined]
                        next_action_date=next_action if next_action is not None else db._UNSET,  # type: ignore[attr-defined]
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
                    due_date=due_date,
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

            due_ok, due_date = _normalize_due_date_input(due_raw or "")
            if not due_ok:
                assignment_failures.append(f"invalid due date '{due_raw}'")
                logger.warning("CoS ASSIGN invalid due date: %r", due_raw)
                continue

            agent = db.agent_resolve_by_name(assignee_name)
            if not agent:
                assignment_failures.append(f"unknown agent '{assignee_name}'")
                logger.warning("CoS ASSIGN failed: unknown agent %r", assignee_name)
                continue

            context_obj = {"source": "chief_of_staff"}
            if chat_id is not None:
                context_obj["cos_chat_id"] = int(chat_id)
            assignee_code = str(agent.get("code") or "").strip().lower()
            try:
                assignment_id = db.agent_create_assignment(
                    title=title,
                    brief_md=brief,
                    requester_code="navi",
                    assignee_code=assignee_code,
                    priority=priority,
                    due_date=due_date,
                    status="queued",
                    context_json=context_obj,
                )
            except Exception as e:
                assignment_id = 0
                logger.warning("CoS ASSIGN create failed: %s", e)

            if assignment_id:
                try:
                    source_thread_id = create_assignment_thread(
                        db,
                        assignment_id=int(assignment_id),
                        assignee_code=assignee_code,
                        reason="chief_of_staff_assign",
                        actor_code="navi",
                        context_json=context_obj,
                    )
                    if source_thread_id:
                        prime_assignment_handoff(
                            db,
                            assignment_id=int(assignment_id),
                            thread_id=int(source_thread_id),
                        )
                except Exception as e:
                    logger.warning("CoS ASSIGN thread prime failed for A-%04d: %s", int(assignment_id), e)
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

            matched_count = 0
            eligible_count = 0
            changed_count = 0
            unchanged_count = 0
            skipped_closed = 0
            failed_count = 0
            for r in rows:
                aid = int(r.get("id") or 0)
                if aid <= 0:
                    continue
                matched_count += 1
                current_status = str(r.get("status") or "").strip().lower()
                if bulk_mode == "open" and current_status in {"done", "cancelled"}:
                    skipped_closed += 1
                    continue
                eligible_count += 1
                if current_status == to_status:
                    unchanged_count += 1
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
                if not ok:
                    failed_count += 1
                    continue
                # Verify persisted state before counting as changed.
                verify_row = db.agent_get_assignment(int(aid)) or {}
                verify_status = str(verify_row.get("status") or "").strip().lower()
                if verify_status == to_status:
                    changed_count += 1
                else:
                    failed_count += 1
            summary = (
                f"{scope_label}: target={to_status}, matched={matched_count}, eligible={eligible_count}, "
                f"changed={changed_count}, unchanged={unchanged_count}, skipped closed={skipped_closed}, failed={failed_count}"
            )
            if matched_count <= 0:
                assignment_failures.append(
                    f"no assignments matched scope '{scope_label}'"
                )
            elif failed_count > 0 and changed_count <= 0:
                assignment_failures.append(
                    f"bulk status write failed for scope '{scope_label}' (changed=0, failed={failed_count})"
                )
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
            matched_count = 0
            eligible_count = 0
            changed_count = 0
            unchanged_count = 0
            skipped_closed = 0
            failed_count = 0
            for r in rows:
                aid = int(r.get("id") or 0)
                if aid <= 0:
                    continue
                matched_count += 1
                current_status = str(r.get("status") or "").strip().lower()
                if bulk_mode == "open" and current_status in {"done", "cancelled"}:
                    skipped_closed += 1
                    continue
                eligible_count += 1
                current_priority = int(r.get("priority") or 3)
                if current_priority == int(priority):
                    unchanged_count += 1
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
                if not ok:
                    failed_count += 1
                    continue
                # Verify persisted state before counting as changed.
                verify_row = db.agent_get_assignment(int(aid)) or {}
                verify_pri = int(verify_row.get("priority") or 0)
                if verify_pri == int(priority):
                    changed_count += 1
                else:
                    failed_count += 1
            summary = (
                f"{scope_label}: target=P{int(priority)}, matched={matched_count}, eligible={eligible_count}, "
                f"changed={changed_count}, unchanged={unchanged_count}, skipped closed={skipped_closed}, failed={failed_count}"
            )
            if matched_count <= 0:
                assignment_failures.append(
                    f"no assignments matched scope '{scope_label}'"
                )
            elif failed_count > 0 and changed_count <= 0:
                assignment_failures.append(
                    f"bulk priority write failed for scope '{scope_label}' (changed=0, failed={failed_count})"
                )
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
            matched_count = 0
            eligible_count = 0
            changed_count = 0
            unchanged_count = 0
            skipped_closed = 0
            failed_count = 0
            for r in rows:
                aid = int(r.get("id") or 0)
                if aid <= 0:
                    continue
                matched_count += 1
                current_status = str(r.get("status") or "").strip().lower()
                if bulk_mode == "open" and current_status in {"done", "cancelled"}:
                    skipped_closed += 1
                    continue
                eligible_count += 1
                current_due = str(r.get("due_date") or "").strip() or None
                if current_due == (due_date or None):
                    unchanged_count += 1
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
                if not ok:
                    failed_count += 1
                    continue
                # Verify persisted state before counting as changed.
                verify_row = db.agent_get_assignment(int(aid)) or {}
                verify_due = str(verify_row.get("due_date") or "").strip() or None
                if verify_due == (due_date or None):
                    changed_count += 1
                else:
                    failed_count += 1
            summary = (
                f"{scope_label}: target={due_date or '(none)'}, matched={matched_count}, eligible={eligible_count}, "
                f"changed={changed_count}, unchanged={unchanged_count}, skipped closed={skipped_closed}, failed={failed_count}"
            )
            if matched_count <= 0:
                assignment_failures.append(
                    f"no assignments matched scope '{scope_label}'"
                )
            elif failed_count > 0 and changed_count <= 0:
                assignment_failures.append(
                    f"bulk due-date write failed for scope '{scope_label}' (changed=0, failed={failed_count})"
                )
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
            matched_count = 0
            eligible_count = 0
            changed_count = 0
            unchanged_count = 0
            skipped_closed = 0
            failed_count = 0
            for r in rows:
                aid = int(r.get("id") or 0)
                if aid <= 0:
                    continue
                matched_count += 1
                current_status = str(r.get("status") or "").strip().lower()
                if bulk_mode == "open" and current_status in {"done", "cancelled"}:
                    skipped_closed += 1
                    continue
                eligible_count += 1
                current_assignee = str(r.get("assignee_code") or "").strip().lower()
                if current_assignee == to_assignee_code:
                    unchanged_count += 1
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
                if not ok:
                    failed_count += 1
                    continue
                _ensure_assignment_thread_matches_assignee(
                    assignment_id=aid,
                    assignee_code=to_assignee_code,
                    reason="chief_of_staff_bulk_reassign",
                )
                # Verify persisted state before counting as changed.
                verify_row = db.agent_get_assignment(int(aid)) or {}
                verify_assignee = str(verify_row.get("assignee_code") or "").strip().lower()
                if verify_assignee == to_assignee_code:
                    changed_count += 1
                else:
                    failed_count += 1
            summary = (
                f"{from_scope_label} -> {to_label}: matched={matched_count}, eligible={eligible_count}, "
                f"changed={changed_count}, unchanged={unchanged_count}, skipped closed={skipped_closed}, failed={failed_count}"
            )
            if matched_count <= 0:
                assignment_failures.append(
                    f"no assignments matched scope '{from_scope_label}'"
                )
            elif failed_count > 0 and changed_count <= 0:
                assignment_failures.append(
                    f"bulk reassignment failed for scope '{from_scope_label}' (changed=0, failed={failed_count})"
                )
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

    # Fallback parse for rich markdown output when model omitted ADD_TASK lines.
    # Keeps extraction strict (numbered line + category + explicit MM-DD-YYYY date).
    if added_tasks == 0 and not explicit_add_task_seen:
        try:
            seen_in_response: set[tuple[str, str, str]] = set()
            current_section_label: Optional[str] = None
            for line in response.splitlines():
                section_match = PRIORITY_SECTION_PATTERN.search((line or "").strip())
                if section_match:
                    current_section_label = str(section_match.group(1) or "").strip().lower() or None
                m_rich = RICH_TASK_LINE_PATTERN.match((line or "").strip())
                if not m_rich:
                    continue
                task_text = (m_rich.group("task") or "").strip().strip(" .-")
                # Don't let fallback parsing turn CoS action lines into dashboard tasks.
                if any(task_text.upper().startswith(prefix) for prefix in ACTION_COMMAND_PREFIXES):
                    continue
                category = (m_rich.group("category") or "").strip().title()
                due_date = (m_rich.group("due") or "").strip()
                if not task_text or category not in {"Business", "Personal"}:
                    continue
                dedupe_key = (task_text.casefold(), due_date, category)
                if dedupe_key in seen_in_response:
                    continue
                seen_in_response.add(dedupe_key)
                try:
                    task_id = db.add_task(
                        session_id=session_id,
                        task_text=task_text,
                        due_date=due_date,
                        category=category,
                        recurrence="None",
                        completed=0,
                    )
                    inferred_priority = _infer_task_priority(
                        task_text,
                        due_date=due_date,
                        section_label=current_section_label,
                        raw_context=line,
                    )
                    if inferred_priority is not None:
                        db.update_task_by_id(int(task_id), priority=int(inferred_priority))
                    added_tasks += 1
                except Exception as e:
                    logger.warning("CoS rich-task fallback add_task failed: %s", e)

            # Also parse compact "task | due | category" triplets from prose/bullets.
            for m_pipe in RICH_PIPE_TASK_PATTERN.finditer(response):
                raw_task_text = (m_pipe.group("task") or "").strip()
                task_text = raw_task_text.strip(" -*•\t\r\n")
                # Strip common section labels that may precede inline bullets.
                task_text = re.sub(
                    r"^(?:#{1,6}\s*)?(?:high|medium|low)\s+priority(?:\s*\([^)]+\))?\s*[-:]\s*",
                    "",
                    task_text,
                    flags=re.IGNORECASE,
                ).strip()
                # Strip trailing heading remnants from one-line formats:
                # "(... - ... ) - Actual task text"
                task_text = re.sub(r"^.*\)\s*-\s*", "", task_text).strip()
                # Don't let fallback parsing turn CoS action lines into dashboard tasks.
                if any(task_text.upper().startswith(prefix) for prefix in ACTION_COMMAND_PREFIXES):
                    continue
                due_raw = (m_pipe.group("due") or "").strip()
                category = (m_pipe.group("category") or "").strip().title()
                if not task_text or category not in {"Business", "Personal"}:
                    continue
                due_date = "" if due_raw.lower() == "none" else due_raw
                dedupe_key = (task_text.casefold(), due_date, category)
                if dedupe_key in seen_in_response:
                    continue
                seen_in_response.add(dedupe_key)
                try:
                    prefix_text = response[: m_pipe.start()]
                    section_label = _infer_priority_section_label(prefix_text) or _infer_priority_section_label(raw_task_text)
                    task_id = db.add_task(
                        session_id=session_id,
                        task_text=task_text,
                        due_date=due_date,
                        category=category,
                        recurrence="None",
                        completed=0,
                    )
                    inferred_priority = _infer_task_priority(
                        task_text,
                        due_date=due_date,
                        section_label=section_label,
                        raw_context=raw_task_text,
                    )
                    if inferred_priority is not None:
                        db.update_task_by_id(int(task_id), priority=int(inferred_priority))
                    added_tasks += 1
                except Exception as e:
                    logger.warning("CoS rich-pipe fallback add_task failed: %s", e)
        except Exception as e:
            logger.warning("CoS rich-task fallback parsing failed: %s", e)

    out = "\n".join(cleaned_lines).strip()
    action_notes = []
    if added_tasks:
        action_notes.append(f"— *Added {added_tasks} task(s) to your dashboard.*")
    if ambiguous_task_priorities:
        preview = ", ".join(ambiguous_task_priorities[:3])
        more = " ..." if len(ambiguous_task_priorities) > 3 else ""
        action_notes.append(
            f"— *Priority clarification needed before adding {len(ambiguous_task_priorities)} task(s): {preview}{more}. Reply with P0-P5 for each task or restate the urgency.*"
        )
    if updated_task_tags:
        action_notes.append(f"— *Updated tags on {updated_task_tags} task(s).*")
    if updated_task_estimates:
        action_notes.append(f"— *Updated time estimates on {updated_task_estimates} task(s).*")
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
            f"— *Bulk status command results for {len(bulk_updated_assignments)} scope(s): {preview}{more}.*"
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
    if task_update_failures:
        preview = "; ".join(task_update_failures[:3])
        more = " ..." if len(task_update_failures) > 3 else ""
        action_notes.append(
            f"— *Some task updates failed ({len(task_update_failures)}): {preview}{more}*"
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

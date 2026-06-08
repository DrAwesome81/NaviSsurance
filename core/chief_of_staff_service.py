"""
Chief of Staff service: plain-text in, plain-text out.
Supports multi-turn; can read dashboard tasks and add tasks via ADD_TASK lines in the response.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional, Callable
from dateutil.tz import tzlocal

from core.db import DatabaseManager
from core.grok_client import (
    grok_completion,
    grok_completion_messages,
    grok_web_search,
    grok_available,
    format_grok_user_facing_error,
    MODEL_COS,
    MODEL_FAST,
)
from core.model_router import ModelRole, get_model
from core.cos_calendar import (
    calendar_available,
    calendar_write_available,
    create_calendar_event,
    format_events_brief,
    get_calendar_events,
)
from core.cos_doc_search import doc_search, format_hits
from core.chat_retrieval import build_long_term_retrieval_context, format_chat_history_tool_results
from core.agent_memory import build_agent_memory_context, build_assignment_memory_context
from core.user_memory import build_user_memory_context, infer_entity_memory_refs
from core.agent_chat_service import create_assignment_thread, prime_assignment_handoff
from core.client_dossier import build_client_dossier_context, get_client_dossier_snapshot
from core.intel import IntelService
from core.local_llm import run_local_completion
from core.tool_registry import invoke_tool
from core.file_handler import get_relevant_past_documents  # Phase 1 retrieval core (VERIFIED COMPLETE): Relevant Past Work injected into CoS + Client Dossier + all surfaces; Phase 1 finished
from core.task_command_contract import (
    extract_first_duration_phrase,
    parse_optional_estimate_minutes_field,
)
from core.app_preferences import (
    get_cos_calendar_max_chars,
    get_cos_context_budget_chars,
    get_cos_history_max_chars_per_message,
    get_cos_history_max_messages,
    get_cos_max_assignment_lines,
    get_cos_max_output_tokens,
    get_cos_max_task_lines,
    get_cos_memory_context_max_chars,
    get_cos_memory_max_output_tokens,
    get_cos_preferences_max_chars,
    get_cos_emails_context_max_chars,
    is_cos_passive_memory_extraction_enabled,
)

logger = logging.getLogger(__name__)

# When memory context is injected below, nudge the model to acknowledge reliance in reasoning only (not in user-visible text).
_COS_MEMORY_REASONING_HINT = (
    "Memory (reasoning only):\n"
    "When a stored preference, fact, or alias from the memory/context blocks in this turn meaningfully shapes your answer, "
    "note that only in your private reasoning—prefix that sentence with `[Memory] `. "
    "Do this occasionally when it matters, not mechanically every time. "
    "Never put `[Memory]`, thinking tags, or meta-commentary about memory in what Adam reads; keep the delivered reply natural.\n"
)

# Optional GUI hook (registered from the main window) for lightweight toasts after CoS-related memory saves.
_cos_toast_callback: Optional[Callable[[str], None]] = None
_cos_task_change_serial = 0


def set_cos_toast_callback(fn: Optional[Callable[[str], None]]) -> None:
    """Register a notifier for short user-visible messages (e.g. main-window status toast). Cleared when fn is None."""
    # CoS toast callback for Pulse private memory + Shield awareness
    global _cos_toast_callback
    _cos_toast_callback = fn


def emit_cos_toast(message: str) -> None:
    """Invoke the registered toast callback; no-op if unset or on failure."""
    # CoS toast integrates Pulse private memory + Shield awareness
    fn = _cos_toast_callback
    text = (message or "").strip()
    if not fn or not text:
        return
    try:
        fn(text)
    except Exception:
        logger.debug("emit_cos_toast callback failed", exc_info=True)


def get_cos_task_change_serial() -> int:
    """Monotonic counter incremented whenever CoS confirmed dashboard task persistence."""
    # Pulse private memory + Shield CoS task serial tracking
    # get_cos_task_change_serial for Pulse private memory + Shield CoS task tracking
    return int(_cos_task_change_serial)


def _record_confirmed_task_persistence(parse_result: "CoSTaskActionParseResult") -> None:
    # _record_confirmed_task_persistence for Pulse private memory + Shield CoS task persistence
    global _cos_task_change_serial
    if int(parse_result.added_dashboard_tasks or 0) > 0:
        _cos_task_change_serial += 1


# Substrings that suggest the user is stating durable preferences/facts (always run memory extraction).
_MEMORY_HINT_SUBSTRINGS: tuple[str, ...] = (
    "teach navi",
    "teach atlas",
    "remember ",
    "remember:",
    "preference",
    "prefer not",
    "always schedule",
    "never book",
    "call me ",
    "don't forget",
    "dont forget",
    "going forward",
    "from now on",
    "i prefer",
    "we decided",
    "client prefers",
    "important to me",
    "note:",
    "learn that",
    "keep in mind",
)


def _log_timing(event: str, t0: float, **fields) -> None:
    """Best-effort per-request timing log (INFO to file)."""
    # _log_timing for Pulse private memory + Shield CoS performance
    try:
        elapsed_ms = int((time.monotonic() - float(t0)) * 1000)
        if fields:
            extra = " ".join(f"{k}={v}" for k, v in fields.items())
            logger.info("TIMING %s elapsed_ms=%s %s", event, elapsed_ms, extra)
        else:
            logger.info("TIMING %s elapsed_ms=%s", event, elapsed_ms)
    except Exception:
        return


def _truncate_cos_text(text: str, max_chars: int) -> str:
    # _truncate_cos_text for Pulse private memory + Shield CoS text handling
    t = (text or "").strip()
    if max_chars <= 0 or not t:
        return ""
    if len(t) <= max_chars:
        return t
    if max_chars <= 1:
        return "…"
    return t[: max_chars - 1].rstrip() + "…"


def _apply_cos_context_budget(
    prefs: str,
    cal: str,
    mem: str,
    tasks: str,
    assign: str,
    budget: int,
    *,
    emails: str = "",
) -> tuple[str, str, str, str, str, str]:
    # _apply_cos_context_budget for Pulse private memory + Shield CoS context
    """
    Keep total character count across CoS context blocks under `budget`.
    Shrinks lowest-priority blocks first (memory, AM Sweep emails, preferences, calendar,
    assignments, tasks). `emails` is empty for normal CoS chat (not AM Sweep).
    """
    cur: dict[str, str] = {
        "mem": (mem or "").strip(),
        "emails": (emails or "").strip(),
        "prefs": (prefs or "").strip(),
        "cal": (cal or "").strip(),
        "assign": (assign or "").strip(),
        "tasks": (tasks or "").strip(),
    }
    order = ["mem", "emails", "prefs", "cal", "assign", "tasks"]

    def total() -> int:
        return sum(len(s) for s in cur.values())

    safety = 0
    while total() > budget and safety < 300:
        safety += 1
        over = total() - budget
        if over <= 0:
            break
        progressed = False
        for k in order:
            if total() <= budget:
                break
            if len(cur[k]) <= 120:
                continue
            take = min(len(cur[k]), over + 80)
            new_max = max(0, len(cur[k]) - take)
            nxt = _truncate_cos_text(cur[k], new_max) if new_max > 0 else ""
            if nxt != cur[k]:
                cur[k] = nxt
                progressed = True
        if not progressed:
            cur["mem"] = ""
            cur["emails"] = _truncate_cos_text(cur["emails"], 800)
            cur["prefs"] = _truncate_cos_text(cur["prefs"], 600)
            if total() > budget:
                cur["cal"] = _truncate_cos_text(cur["cal"], 400)
            break
    if cur.get("mem"): logger.debug("budgeted CoS private memory final chars=%d (Shield consumption)", len(cur.get("mem") or ""))
    return (
        cur["prefs"],
        cur["cal"],
        cur["mem"],
        cur["emails"],
        cur["tasks"],
        cur["assign"],
    )

# ============================================================
# ROBUST TASK ADDITION PARSER — CoS ADD_TASK lines & fallbacks
# ============================================================
# ADD_TASK: text | due_date (MM-DD-YYYY or none) | category (Business or Personal)
#   [| priority] [| assigned_to | project_id | recurrence] [| estimate_minutes]
#   [| priority(P0-P5|0-5|none)] [| assigned_to|none] [| project_id|none] [| recurrence]
# search() allows leading text on the same line; payload is the rest of the line after ADD_TASK:
ADD_TASK_PATTERN = re.compile(r"ADD_TASK:\s*(.+)$", re.IGNORECASE)
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

# APPROVE_PROPOSAL: assignment_ref (e.g. P-0007, A-0007, or 7)
APPROVE_PROPOSAL_PATTERN = re.compile(r"^\s*APPROVE_PROPOSAL:\s*(.+?)\s*$", re.IGNORECASE)
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
    "APPROVE_PROPOSAL:",
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
    # _now_local for Pulse private memory + Shield CoS time handling
    return datetime.now()


def _local_time_context(now: Optional[datetime] = None) -> str:
    # _local_time_context for Pulse private memory + Shield CoS time
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
    # _parse_calendar_datetime for Pulse private memory + Shield CoS calendar
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


def _tasks_context(db: DatabaseManager, *, max_lines: int = 40) -> str:
    # _tasks_context for Pulse private memory + Shield CoS tasks
    """Format current dashboard tasks for CoS context. Uses same list as dashboard (all, no date filter)."""
    try:
        cap = max(5, min(80, int(max_lines)))
        tasks = db.get_tasks(category=None, date_filter=None, specific_date=None)
        if not tasks:
            return "**Dashboard tasks:** (none)"
        lines = []
        for task_id, task_text, due_date, category, recurrence, completed in tasks:
            done = " [DONE]" if completed else ""
            due = f" due {due_date}" if due_date else ""
            lines.append(f"- {task_text}{due} ({category}){done}")
        if lines: logger.debug("CoS tasks context chars=%d (Pulse private mem + Shield)", len("\n".join(lines[:cap])))
        return "**Dashboard tasks:**\n" + "\n".join(lines[:cap])
    except Exception as e:
        logger.warning("Could not load tasks for CoS context: %s", e)
        return "**Dashboard tasks:** (unable to load)"


def _compact_conversation_history(
    conversation_history: List[Tuple[str, str]] | None,
    *,
    max_messages: int = 6,
    max_chars_per_message: int = 1200,
) -> list[tuple[str, str]]:
    # _compact_conversation_history for Pulse private memory + Shield CoS history
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
    if compact: logger.debug("CoS compact history items=%d (Pulse private mem + Shield)", len(compact))
    return compact[-max_messages:]


def _chat_history_tool_result(
    db: DatabaseManager,
    query: str,
    *,
    chat_id: Optional[int] = None,
) -> tuple[str, str]:
    # _chat_history_tool_result for Pulse private memory + Shield CoS chat history
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
    if result_text: logger.debug("CoS chat history tool result chars=%d (Pulse private mem + Shield)", len(result_text))
    return "CHAT_HISTORY_RESULTS", result_text


def _tasks_context_rich(db: DatabaseManager, *, limit: int = 80) -> str:
    # _tasks_context_rich for Pulse private memory + Shield CoS rich tasks
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
        # Re-rank by heuristic score for CoS context (prioritization engine start)
        try:
            rows = sorted(rows, key=_compute_priority_score, reverse=True)
        except Exception:
            pass
        lines: list[str] = []
        for r in rows[: int(limit)]:
            tid = int(r.get("id") or 0)
            text = str(r.get("task_text") or "").strip() or "(empty task)"
            due = str(r.get("due_date") or "").strip()
            pr = int(r.get("priority") or 0)
            est = int(r.get("estimate_minutes") or 0)
            assigned_to = str(r.get("assigned_to") or "").strip()
            tags_json = str(r.get("tags_json") or "[]").strip()
            due_part = f" due {due}" if due else ""
            assigned_part = f" assigned_to {assigned_to}" if assigned_to else ""
            est_part = f" est {est}m" if est else ""
            sc = _compute_priority_score(r)
            lines.append(f"- #{tid} P{pr} s{sc} {text}{due_part}{assigned_part}{est_part} tags={tags_json}")
        if lines: logger.debug("CoS rich tasks context chars=%d (Pulse private mem + Shield)", len("\n".join(lines)))
        return "**Dashboard tasks (rich, open):**\n" + "\n".join(lines)
    except Exception as e:
        logger.warning("Could not load rich tasks for CoS context: %s", e)
        return "**Dashboard tasks (rich):** (unable to load)"


def _raised_intel_context(db: DatabaseManager, *, max_items: int = 6) -> str:
    """Format recent raised Intel/Pulse findings for CoS awareness (respects raised flag). # Security-relevant items tied to Shield for privacy triage in private memory and raising."""
    try:
        # _raised_intel_context for Pulse private memory + Shield CoS intel
        intel = IntelService(db)
        last_ts = " (last Pulse: " + intel.get_last_pulse_display() + ")"
        findings = intel.list_findings(raised_only=True, limit=max_items)
        if not findings:
            return "**Raised Intel (Pulse):** (no currently raised findings)" + last_ts
        # Short Pulse header always for daily briefing construction
        base = "**Pulse / Intel Updates (from private memory and project-scoped monitoring):**" + last_ts + "\n"
        lines = []
        for f in findings:
            clients = f" [clients: {f.linked_clients}]" if f.linked_clients else ""
            projs = f" [projects: {getattr(f, 'linked_projects', [])}]" if getattr(f, 'linked_projects', None) else ""
            short = (f.summary or f.title or "")[:200].replace("\n", " ").strip()
            imp = (f.importance or "medium").upper()
            tag = " [Theme-Continuous]" if "[Theme-Continuous]" in (f.title or "") else ""
            if "[Security-Relevant]" in (f.title or ""):
                tag += " 🛡️ [Security-Relevant]"
            src = f" ({f.source})" if getattr(f, 'source', None) else ""
            lines.append(f"- [{imp}]{tag} {f.title}{clients}{projs}{src}: {short}")
        header = "**Raised Intel from Pulse** (review these signals in planning):" + last_ts
        base = header + "\n" + "\n".join(lines)
        if any("[Theme-Continuous]" in (getattr(f, 'title', '') or "") for f in findings):
            base += "\n  (includes theme-continuous findings powered by Pulse private memory continuity scoring)"
        if any("[Security-Relevant]" in (getattr(f, 'title', '') or "") for f in findings):
            base += "\n  (includes [Security-Relevant] findings for Shield triage)"
        # Enrich with 1 highest-importance recent (tiny CoS briefing quality bump)
        try:
            high = [f for f in findings if (f.importance or "").lower() == "high"][:1]
            if high:
                base += f"\n  Top high: {high[0].title[:60]}"
                if "[Security-Relevant]" in (high[0].title or ""):
                    base += " 🛡️"
        except Exception:
            pass
        # Small "Project Intel Highlights" subsection when project-linked raised items exist (light context propagation for CoS)
        try:
            proj_linked = [f for f in findings if getattr(f, 'linked_projects', None)]
            if proj_linked:
                ex = proj_linked[0]
                base += f"\n  Project Intel Highlights: {ex.title[:50]} (linked to project(s) {getattr(ex, 'linked_projects', [])})"
                if "[Security-Relevant]" in (ex.title or ""):
                    base += " 🛡️ (use Shield for triage)"
                base += " (security context available via Shield for these projects)"
        except Exception:
            pass
        # Small "Recommended focus from Pulse this cycle" blending themes + top raised (proactive CoS content) - uses importance + actionable note
        try:
            if findings or refs:  # refs from earlier themes block
                top = findings[0] if findings else None
                imp = (top.importance or "medium").upper() if top else ""
                rec = f"Recommended focus [{imp}]: {top.title[:40] if top else 'Monitor themes'} - review in Intel tab or CoS chat"
                if refs:
                    rec += " (themes active)"
                if "[Security-Relevant]" in (getattr(top, 'title', '') or ""):
                    rec += " 🛡️ (Shield for security)"
                base += f"\n  {rec}"
        except Exception:
            pass

        # Phase 2: blend Phase 1 Document Memory (now complete incl Dossier) into intel briefing context for richer CoS awareness.
        # Smallest: for any linked clients in raised findings, pull 1-2 relevant past docs (reuses get_relevant + formatter).
        try:
            from core.file_handler import get_relevant_past_documents, format_compact_historical_context
            client_names = set()
            for f in findings:
                for cid in (getattr(f, 'linked_clients', None) or []):
                    try:
                        c = db.client_get(cid)
                        if c and c.get("name"):
                            client_names.add(str(c["name"]))
                    except Exception:
                        pass
            if client_names:
                docs = []
                for nm in list(client_names)[:2]:
                    docs.extend(get_relevant_past_documents(client_hint=nm, limit=2) or [])
                if docs:
                    hist = format_compact_historical_context(docs[:3], max_items=3, header="\n--- Historical docs for clients in raised Intel ---")
                    base += hist
                    base += " (security-relevant past docs inform Shield/Compliance triage)"
        except Exception:
            pass

        # Phase 2 maturation: pull Pulse private regulatory theme reflections for structured proactive "Regulatory Pulse Themes" section in CoS briefings.
        # Reuses the new get_recent_pulse_reflections helper (makes private memory visible to coordination layer).
        try:
            reflections = intel.get_recent_pulse_reflections(limit=3)
            if reflections:
                theme_lines = []
                for r in reflections:
                    c = str(r.get("content", ""))[:120].replace("\n", " ").strip()
                    if c:
                        theme_lines.append(f"- {c}")
                if theme_lines:
                    base += "\n\n**Pulse Regulatory Themes** (private memory, recent cycles — proactive context for planning; 🛡️ security-relevant for Shield triage):\n" + "\n".join(theme_lines)
                else:
                    base += "\n\n**Pulse Regulatory Themes** (private memory, recent cycles — proactive context for planning):\n- No recent themes recorded yet"
        except Exception:
            pass
        # Ensure Recommended focus and themes sections are always present and well-formatted (even on first load or partial data)
        if "Recommended focus" not in base:
            base += "\n  Recommended focus: Check latest Pulse themes and raised signals in Intel tab for current priorities (🛡️ security-relevant for Shield - prioritize high impact)"
        if "**Pulse Regulatory Themes**" not in base:
            base += "\n\n**Pulse Regulatory Themes** (private memory, recent cycles — proactive context for planning; 🛡️ security-relevant for Shield):\n- Monitor recent regulatory and market signals for active projects"
        # Ensure short Pulse header at top of the returned intel context for daily briefing
        if not base.startswith("**Pulse"):
            base = "**Pulse / Intel Updates (private memory + project monitoring; 🛡️ security-relevant for Shield):**\n" + base
        # Light high-level awareness: "Pulse has X active project-scoped watches"
        try:
            scoped = sum(1 for w in (intel.list_watch_topics() or []) if getattr(w, 'project_id', None))
            if scoped > 0:
                base += f"\n  (Pulse has {scoped} active project-scoped watches across your work) 🛡️ (security-relevant for Shield)"
            else:
                base += "\n  (No active project-scoped watches detected - create via Intel tab for active projects) 🛡️ (security-relevant watches for Shield)"
            # Small proactive client monitoring note (symmetric to project watches; for daily briefing/AM Sweep) - now with 1-2 high-signal specifics
            try:
                c_mon = 0
                examples = []
                watches = intel.list_watch_topics() or []
                contrib = 0.0
                max_contrib = 0.0
                max_cname = ""
                max_detail = ""
                for c in (db.list_clients(active_only=True, limit=50) or []):
                    cid = c.get('id')
                    cname = c.get('name', f'#{cid}')
                    has_watch = any(getattr(w, 'client_id', None) == cid for w in watches)
                    recent = intel.list_findings(client_id=cid, raised_only=True, limit=1)
                    has_raised = bool(recent)
                    if has_watch or has_raised:
                        c_mon += 1
                        if len(examples) < 2:
                            detail = ""
                            if has_watch:
                                w = next((w for w in watches if getattr(w, 'client_id', None) == cid), None)
                                if w: detail = getattr(w, 'topic', '')[:25]
                            elif has_raised and recent:
                                detail = getattr(recent[0], 'title', '')[:25]
                            examples.append(f"{cname}: {detail}")
                        try:
                            ents = db.time_entries_list(client_id=cid, limit=100) or []
                            p_ents = [e for e in ents if "Pulse-influenced" in str(e.get("description") or "") or "from Pulse" in str(e.get("description") or "")]
                            p_mins = sum(int(e.get("minutes") or 0) for e in p_ents)
                            prof = db.get_client_billing_profile(cid) or {}
                            r = float(prof.get("default_rate") or 0)
                            contrib_c = (p_mins / 60.0) * r
                            contrib += contrib_c
                            if contrib_c > max_contrib:
                                max_contrib = contrib_c
                                max_cname = cname
                                max_detail = detail
                        except Exception:
                            pass
                if c_mon > 0:
                    note = f"\n  (Pulse is actively monitoring {c_mon} of your clients)"
                    if examples:
                        note += f" e.g. {'; '.join(examples)}"
                    if contrib > 0:
                        note += f" | Pulse impact: ${contrib:.2f} in billable time"
                    if max_contrib > 0 and max_cname:
                        note += f" | Recommended: Prioritize {max_cname} (impact ${max_contrib:.2f} from {max_detail})"
                    note += " | 🛡️ security-relevant clients - triage in Shield tab"
                    if any("[Security-Relevant]" in ex for ex in examples):
                        note += " (🛡️ security-relevant in examples)"
                    base += note
            except Exception:
                pass
        except Exception:
            pass
        if base: logger.debug("raised intel context len=%d (Pulse private memory to Shield surface)", len(base))
        return base
    except Exception as e:
        logger.warning("Could not load raised Intel for CoS context: %s", e)
        return "**Raised Intel (Pulse):** (unable to load)"


def _consistency_context(db: DatabaseManager) -> str:
    """Phase 4 surface: now pulls actual persisted consistency reports (not just note) from workspace saved states.
    Uses the new extraction in db.workspace_state_list (related_set_consistency_report).
    Defensive, compact for context budgets. Ties to Sentinel for QA.
    """
    try:
        workspaces = db.workspace_state_list() or []
        report_lines = []
        for w in workspaces:
            rep = w.get("related_set_consistency_report")
            if rep:
                name = str(w.get("name") or "set")[:40]
                # Rough extract overall status from the markdown report (first line after header)
                status = ""
                try:
                    if "**Overall Status:**" in rep:
                        status = rep.split("**Overall Status:**", 1)[1].split("\n", 1)[0].strip()[:20]
                except Exception:
                    status = ""
                snippet = f"- {name}" + (f" ({status})" if status else "")
                report_lines.append(snippet)
                if len(report_lines) >= 3:
                    break
        if report_lines:
            return (
                "**Workspace Consistency Reports (Phase 4):** \n" +
                "\n".join(report_lines) +
                "\n(Full reports + artifacts in Workspace tab. Delegate fixes to Sentinel using its brief template.)"
            )
        # Fallback to note if none yet
        return (
            "**Workspace Consistency (Phase 4):** "
            "Related document set (and single-doc) consistency reports (status/issues/recommendations from checker) persist with saved workspaces and exports (also GDrive client folders when enabled). "
            "Review in Workspace tab (artifacts + cross-refs). Delegate QA/consistency passes to Sentinel (use its brief template for contradictions, refs, scope drift). "
            "Use on client deliverables for quality gate."
        )
    except Exception:
        return "**Workspace Consistency (Phase 4):** Consistency via Workspace related-sets + Sentinel QA. Reports available in generated artifacts."


def _compute_priority_score(row: dict, *, now: datetime | None = None) -> float:
    """Heuristic urgency/importance score (higher = prioritize in CoS contexts/briefings).
    Starts formal scoring engine (was raw priority + status order only). Smallest start per roadmap/TODO.
    Combines: explicit P (5 highest), due/overdue, needs_input/blockers, status, light age.
    """
    if now is None:
        now = datetime.now()
    pr = int(row.get("priority") or 3)
    score = float(max(0, min(5, pr))) * 12.0
    # Due/overdue (supports MM-DD-YYYY or iso-ish)
    due_str = str(row.get("due_date") or row.get("_due_dt") or "").strip()
    if due_str and due_str.lower() not in ("", "none", "9999-12-31"):
        try:
            if len(due_str) >= 8 and due_str[2] == "-" and due_str[5] == "-":
                due_dt = datetime.strptime(due_str[:10], "%m-%d-%Y")
            else:
                due_dt = datetime.fromisoformat(due_str[:10])
            delta = (due_dt.date() - now.date()).days
            if delta < 0:
                score += 25.0 + min(18.0, abs(delta) * 1.2)
            elif delta == 0:
                score += 16.0
            elif delta <= 2:
                score += 9.0
            elif delta <= 7:
                score += 3.5
        except Exception:
            pass
    # Needs input / blockers
    if row.get("needs_input") or bool(str(row.get("blockers") or "").strip()):
        score += 20.0
    # Status
    st = str(row.get("status") or "").lower()
    if st in ("in_progress",):
        score += 5.0
    elif st in ("awaiting_review", "proposed"):
        score += 2.5
    elif st == "blocked":
        score += 7.0
    elif st in ("done", "cancelled"):
        score -= 40.0
    # Light stale-open boost (don't lose track)
    try:
        upd = row.get("updated_at") or row.get("created_at")
        if isinstance(upd, str) and upd:
            u = upd.replace(" ", "T")[:19]
            u_dt = datetime.fromisoformat(u) if "T" in u or "-" in u else None
            if u_dt:
                age = max(0, (now - u_dt).days - 2)
                if age > 0:
                    score += min(6.0, age * 0.7)
    except Exception:
        pass
    return round(max(0.0, score), 1)


def _assignments_context(db: DatabaseManager, *, max_lines: int = 45) -> str:
    """Format open delegation assignments for CoS context. # Security/privacy assignments can use Shield with Pulse [Security-Relevant] context."""
    try:
        # _assignments_context for Pulse private memory + Shield CoS assignments
        cap = max(5, min(100, int(max_lines)))
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

        # Sort by heuristic score (starts prioritization engine; explicit P + due + signals)
        try:
            open_rows.sort(key=_compute_priority_score, reverse=True)
        except Exception:
            pass

        lines = []
        for r in open_rows[:cap]:
            aid = int(r.get("id") or 0)
            title = str(r.get("title") or "Untitled")
            assignee = str(r.get("assignee_code") or "agent")
            st = str(r.get("status") or "queued")
            pr = int(r.get("priority") or 3)
            due = str(r.get("due_date") or "")
            due_part = f" due {due}" if due else ""
            sc = _compute_priority_score(r)
            lines.append(f"- A-{aid:04d} [{st}] P{pr} s{sc} {title} -> {assignee}{due_part}")
        if lines: logger.debug("CoS assignments context chars=%d (Pulse private mem + Shield)", len("\n".join(lines)))
        return "**Delegated assignments (open):**\n" + "\n".join(lines)
    except Exception as e:
        logger.warning("Could not load assignments for CoS context: %s", e)
        return "**Delegated assignments:** (unable to load)"


def _preferences_context(prefs_row) -> str:
    # _preferences_context for Pulse private memory + Shield CoS prefs
    if not prefs_row:
        return ""
    (
        operating_system_md,
        blocked_times_json,
        deep_work_hours,
        behavior_prefs_json,
        energy_profile_json,
        _prefs_updated_at,
    ) = prefs_row
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
    if energy_profile_json:
        try:
            ep = json.loads(energy_profile_json)
            if isinstance(ep, dict) and ep:
                elines: list[str] = []
                peak = str(ep.get("peak_hours") or ep.get("peak") or "").strip()
                low = str(ep.get("low_energy_windows") or ep.get("low_energy") or "").strip()
                if peak:
                    elines.append(f"- Peak focus hours: {peak}")
                if low:
                    elines.append(f"- Low energy windows: {low}")
                if elines:
                    parts.append("Energy / working style:\n" + "\n".join(elines))
                elif ep:
                    parts.append("Energy / working style: " + json.dumps(ep, ensure_ascii=False))
        except Exception:
            parts.append("Energy / working style: " + str(energy_profile_json))
    if parts: logger.debug("CoS prefs context chars=%d (private mem/Shield consumption)", len("\n\n".join(parts) if parts else ""))
    return "\n\n".join(parts) if parts else ""


def _calendar_context() -> str:
    # _calendar_context for Pulse private memory + Shield CoS calendar
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
        cal_str = (
            "**Calendar (today):**\n"
            + format_events_brief(todays, tz=local_tz)
            + "\n\n**Calendar (next 7 days):**\n"
            + format_events_brief(upcoming, tz=local_tz)
        )
        if cal_str: logger.debug("CoS calendar context chars=%d (Pulse private mem + Shield)", len(cal_str))
        return cal_str
    except Exception as e:
        return "**Calendar:** (error loading) " + str(e)


def _calendar_query_windows(now: Optional[datetime] = None) -> tuple[object, str, str, str, str]:
    # _calendar_query_windows for Pulse private memory + Shield CoS calendar windows
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
    if lines: logger.debug("CoS emails context chars=%d (Pulse private mem + Shield surface)", len("\n".join(lines)))

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
    hist_max_msg = get_cos_history_max_messages(db)
    hist_max_ch = get_cos_history_max_chars_per_message(db)
    now = _now_local()
    local_time_ctx = _local_time_context(now)
    prefs = db.cos_get_preferences()
    prefs_ctx = _truncate_cos_text(
        _preferences_context(prefs),
        get_cos_preferences_max_chars(db),
    )
    tl = get_cos_max_task_lines(db)
    al = get_cos_max_assignment_lines(db)
    tasks_ctx = _tasks_context_rich(db, limit=tl)
    assignments_ctx = _assignments_context(db, max_lines=al)
    cal_ctx = _truncate_cos_text(_calendar_context(), get_cos_calendar_max_chars(db))
    emails_ctx = _truncate_cos_text(_emails_context(db), get_cos_emails_context_max_chars(db))
    mem_ctx = _memory_context(db, "AM Sweep", chat_id)
    prefs_ctx, cal_ctx, mem_ctx, emails_ctx, tasks_ctx, assignments_ctx = _apply_cos_context_budget(
        prefs_ctx,
        cal_ctx,
        mem_ctx,
        tasks_ctx,
        assignments_ctx,
        get_cos_context_budget_chars(db),
        emails=emails_ctx,
    )

    intel_ctx = _raised_intel_context(db, max_items=5)
    consistency_ctx = _consistency_context(db)

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
- Security/privacy tasks should route to Shield using Pulse [Security-Relevant] context for triage.

Use any "Pulse impact" or "Recommended from Pulse" notes from intel_ctx to suggest 1-2 specific revenue-generating actions (e.g., follow-up on highest-impact client) in Dispatch or Prep sections.

Routing (use these agent names in ASSIGN lines):
- Quill: drafts/rewrites (emails, briefs, follow-ups). Never sends; produces drafts + variants + questions.
- Atlas: research with citations + gaps + recommended next queries.
- Lex: contract/policy extraction + obligations + decisions needed.
- Ledger: billing/invoice prep + anomalies/questions.
- Archive: notes/filing/timelines + links to source items.
- Sentinel: QA pass / risk flags / consistency checks (review persisted workspace consistency reports from Phase 4 checker; use consistency_ctx for context).
- Scout: prospect/lead recon + outreach prep.
- Mason: task triage + command emission (use sparingly; you are already doing AM Sweep).
- Pulse: briefing/monitoring summaries (rare in AM Sweep).
- Shield: secrets/safety check (consult current Pulse findings/themes for regulatory-driven privacy/security risks when relevant in triage).
- Shield briefs must include: (1) security/privacy risks from Pulse [Security-Relevant]; (2) triage recommendations and Shield tab guidance.

Assignment brief templates (use these patterns so outputs are consistent):
- Quill brief must include: (1) the goal; (2) key facts to preserve; (3) 2 tone variants; (4) explicit questions for Adam; (5) a \"draft only\" reminder.
- Atlas brief must include: (1) exact research question; (2) scope limits; (3) must cite sources with URLs; (4) deliver: findings + gaps + recommended next queries.
- Lex brief must include: (1) document type; (2) extraction targets (obligations, deadlines, risks); (3) output: bullet list + decision points.
- Ledger brief must include: (1) time window; (2) client/project; (3) deliver: draft invoice inputs + anomalies + questions.
- Archive brief must include: (1) what to update; (2) structure; (3) output: clean notes + action items + links to source items.
- Sentinel brief must include: (1) what to QA; (2) checklist (clarity, missing info, contradictions, risky wording, cross-doc consistency from workspace reports); (3) output: issues + suggested fixes.

Use of sub-agent reflections for continuity in AM proposals: The injected memory context (above, from mem_ctx) will contain lines such as "Recent atlas reflection: ..." (or for quill, sentinel, lex, etc.). When emitting ASSIGN for an agent, incorporate 1-2 relevant points from that agent's matching "Recent <code> reflection" into the <Brief> for continuity (e.g. "Building on your recent reflection that the client prefers tables..."). This makes proposals leverage sub-agent self-awareness.

{_COS_MEMORY_REASONING_HINT}
Output format requirements:
1) Start with a short executive summary (3-6 bullets max).
2) Then four sections in this order with bullet lists: Dispatch, Prep, Yours, Skip.
3) Optionally include a short \"Time-block proposal\" paragraph after Skip (prose only). If calendar scheduling is unavailable, this is the ONLY scheduling output you should produce.
4) End with a final section titled exactly: \"## Actions (machine)\".
   Under that header, output ONLY machine-action lines (no bullets, no commentary).

Parallelism expectation:
- If there are multiple Dispatch/Prep items, emit MULTIPLE ASSIGN lines (one per item/agent) so work can run in parallel.

Action commands you may output:
- ADD_TASK: <task description> | <MM-DD-YYYY or none> | <Business or Personal> [| <priority P0-P5 or 0-5 or none>] [| <assigned to or none>] [| <project id or none>] [| <recurrence: None|Daily|Weekly|Monthly>] [| <estimate: minutes (e.g. 90) or duration (e.g. 1 hr 15 min) or none>]
- TASK_SET_TAGS: <task_id> | <json array of tags>    (example: TASK_SET_TAGS: 123 | [\"triage:dispatch\",\"source:am_sweep\"])
- TASK_SET_ESTIMATE: <task_id> | <minutes>           (0-600, example: TASK_SET_ESTIMATE: 123 | 45)
- ASSIGN: <AgentName> | <Title> | <Brief> | <P1-P5> | <YYYY-MM-DD or none>
  (Each ASSIGN creates a **proposal** for Adam to review in Suggested Assignments; it does not start agent work until approved.)
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
    if mem_ctx: logger.debug("AM Sweep private memory context chars=%d (Pulse + Shield surface consumption)", len(mem_ctx))
    time_ctx += f"\n\n{tasks_ctx}\n\n{assignments_ctx}\n\n{intel_ctx}\n\n{consistency_ctx}"

    user_prompt = (
        "Run AM Sweep now.\n\n"
        "Remember: put any command lines only under '## Actions (machine)'."
    )

    try:
        if conversation_history:
            recent_history = _compact_conversation_history(
                conversation_history,
                max_messages=hist_max_msg,
                max_chars_per_message=hist_max_ch,
            )
            messages = [{"role": "system", "content": system + "\n\n" + time_ctx}]
            for role, content in recent_history:
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
        return format_grok_user_facing_error(e)

def _memory_context(db: DatabaseManager, user_message: str, chat_id: Optional[int]) -> str:
    """
    Retrieve relevant memory (structured + raw conversation) to ground responses.
    """
    q = (user_message or "").strip()
    if not q:
        return ""
    light = len(q) < 96
    mem_limit = 4 if light else 6
    chunk_limit = 2 if light else 3
    raw_turn_limit = 4 if light else 6
    fts_limit = 4 if light else 6
    user_mem_limit = 3 if light else 4
    user_mem_recent = 1 if light else 2
    parts = []
    try:
        mem_rows = db.cos_memory_search(query=q, chat_id=chat_id, limit=mem_limit)
    except Exception:
        mem_rows = []
    if mem_rows:
        lines = []
        for _id, _chat_id, kind, content, _json_data, created_at in mem_rows[:mem_limit]:
            lines.append(f"- ({kind}) {content}")
        parts.append("**Relevant memory (structured):**\n" + "\n".join(lines))

    session_id = f"cos_{int(chat_id)}" if chat_id is not None else None
    try:
        retrieval_context = build_long_term_retrieval_context(
            db,
            q,
            session_id=session_id,
            chunk_limit=chunk_limit,
            raw_turn_limit=raw_turn_limit,
        )
    except Exception:
        retrieval_context = ""
    if retrieval_context:
        parts.append(retrieval_context)
    else:
        try:
            conv_rows = db.search_conversations(q)[:fts_limit]
        except Exception:
            conv_rows = []
        if conv_rows:
            lines = []
            for role, content, ts in conv_rows[:fts_limit]:
                excerpt = (content or "").strip()
                if len(excerpt) > 180:
                    excerpt = excerpt[:177] + "..."
                lines.append(f"- ({role}) {excerpt}")
            parts.append("**Relevant past chat snippets (FTS):**\n" + "\n".join(lines))

    try:
        global_memory = build_user_memory_context(
            db, q, limit=user_mem_limit, recent_limit=user_mem_recent
        )
    except Exception:
        global_memory = ""
    if global_memory:
        parts.append(global_memory)

    assignment_match = re.search(r"\bA-(\d{1,6})\b", q, re.IGNORECASE)
    if assignment_match:
        try:
            assignment_id = int(assignment_match.group(1))
        except Exception:
            assignment_id = None
        if assignment_id is not None:
            try:
                assignment_memory = build_assignment_memory_context(
                    db,
                    q,
                    assignment_id=assignment_id,
                    limit=4,
                    recent_limit=2,
                )
            except Exception:
                assignment_memory = ""
            if assignment_memory:
                parts.append(assignment_memory)
            # Surface assignment reflection too (smallest).
            try:
                refs = db.memory_reflection_recent(scope=f"assignment:{assignment_id}", limit=1)
                if refs and refs[0].get("summary_text"):
                    parts.append(f"Recent assignment reflection: {str(refs[0]['summary_text'])[:100]}")
            except Exception:
                pass

    try:
        agents = db.agents_list_active()
    except Exception:
        agents = []
    lowered_query = q.casefold()
    seen_agents: set[str] = set()
    agent_sections: list[str] = []
    for agent in agents:
        code = str(agent.get("code") or "").strip().lower()
        if not code or code in seen_agents:
            continue
        names = [
            code,
            str(agent.get("display_name") or "").strip(),
        ]
        try:
            aliases = json.loads(agent.get("aliases_json") or "[]")
        except Exception:
            aliases = []
        names.extend(str(alias or "").strip() for alias in aliases)
        if not any(name and name.casefold() in lowered_query for name in names):
            continue
        seen_agents.add(code)
        try:
            agent_context = build_agent_memory_context(db, code, q, limit=3, recent_limit=1)
        except Exception:
            agent_context = ""
        if agent_context:
            agent_sections.append(agent_context)
        if len(agent_sections) >= 2:
            break
    parts.extend(section for section in agent_sections if section.strip())

    # Surface agent reflections (new sub-agent support) in CoS context. Smallest-safe.
    for code in list(seen_agents)[:3]:
        try:
            refs = db.memory_reflection_recent(scope=f"agent:{code}", limit=1)
            if refs and refs[0].get("summary_text"):
                parts.append(f"Recent {code} reflection: {str(refs[0]['summary_text'])[:150]}")
        except Exception:
            pass

    joined = "\n\n".join(parts)
    if joined: logger.debug("CoS private memory consumption: %d chars (for Shield visibility)", len(joined))
    max_mc = get_cos_memory_context_max_chars(db)
    return _truncate_cos_text(joined, max_mc) if joined else ""


def _extract_and_store_memory(db: DatabaseManager, *, chat_id: Optional[int], user_message: str, assistant_message: str) -> None:
    if not is_cos_passive_memory_extraction_enabled(db):
        return
    if _should_skip_passive_memory_extraction(user_message, assistant_message):
        return
    ok, _msg = grok_available()
    if not ok:
        return
    try:
        system = (
            "You extract durable memory for a Chief of Staff assistant. "
            "Return ONLY valid JSON. No markdown."
        )
        um = _truncate_cos_text(user_message, 6000)
        am = _truncate_cos_text(assistant_message, 12000)
        user = f"""
Extract durable memory items from the interaction.

Input:
- user_message: {um}
- assistant_message: {am}

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
        raw = grok_completion(
            system,
            user,
            model=MODEL_FAST,
            max_tokens=get_cos_memory_max_output_tokens(db),
        )
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
            if items: logger.debug("CoS private memory items stored: %d (Shield actionable consumption)", len(items))
    except Exception:
        return


def _parse_assignment_ref(value: str) -> Optional[int]:
    """Parse assignment reference forms like 'A-0007', '7', or 'assignment A-0007'."""
    s = (value or "").strip().upper()
    if not s:
        return None
    m = re.match(r"^[AP]-(\d+)$", s)
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
        "proposal": "proposed",
        "proposed": "proposed",
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


_DASHBOARD_TASK_USER_INTENT_RE = re.compile(
    r"(?is)\b(?:add\s+(?:a\s+)?task\s+to|remind\s+me\s+(?:to\s+)?)(.+)$"
)

# Broader than synthesis regex: used only to detect when we should contradict model prose that claims a save.
_DASHBOARD_TASK_ADD_INTENT_FOR_HONESTY_RE = re.compile(
    r"(?is)\b("
    r"add\s+(?:a\s+)?task\b|"
    r"add\s+(?:these|those)\s+tasks\b|"
    r"put\s+(?:this|that|it)\s+on\s+(?:my\s+)?(?:task\s+)?list\b|"
    r"create\s+(?:a\s+)?task\b|"
    r"add\s+(?:this|that|it)\s+to\s+(?:my\s+)?dashboard\b|"
    r"new\s+task\b"
    r")"
)


def _user_requested_dashboard_task_add(user_message: str) -> bool:
    msg = (user_message or "").strip()
    if not msg:
        return False
    if re.search(r"(?im)^\s*ADD_TASK\s*:", msg):
        return True
    if synthesize_add_task_line_from_user_text(msg):
        return True
    return bool(_DASHBOARD_TASK_ADD_INTENT_FOR_HONESTY_RE.search(msg))


def _user_requested_direct_dashboard_task_add(user_message: str) -> bool:
    msg = (user_message or "").strip()
    if not msg:
        return False
    if re.search(r"(?im)^\s*ADD_TASK\s*:", msg):
        return True
    if synthesize_add_task_line_from_user_text(msg):
        return True
    if re.search(r"(?is)^\s*(?:add\s+(?:a\s+)?task\s+to|remind\s+me\s+(?:to\s+)?)\b", msg):
        return True
    if re.search(
        r"(?is)^\s*(?:create\s+(?:a\s+)?task|new\s+task|put\s+(?:this|that|it)\s+on\s+(?:my\s+)?(?:task\s+)?list|add\s+(?:this|that|it)\s+to\s+(?:my\s+)?dashboard)\b",
        msg,
    ):
        if re.search(r"\bfrom\s+(?:that\s+)?assignment\b", msg, flags=re.IGNORECASE):
            return False
        return True
    return False


_TASK_CAPTURE_CONFIRMATION_FAILURE_MESSAGE = (
    "I tried to add the task but didn't get confirmation from the backend — can you repeat the request?"
)
_TASK_CAPTURE_GROK_FAILURE_MESSAGE = (
    "Grok is temporarily unavailable. I couldn't create the task right now — please try again in a minute or tell me the details again."
)


@dataclass(frozen=True)
class CoSTaskActionParseResult:
    """Outcome of parsing machine-action lines (ADD_TASK, etc.) out of a model reply."""

    text: str
    added_dashboard_tasks: int
    ambiguous_priority_pending: bool
    added_task_items: tuple[tuple[str, Optional[str]], ...] = ()


def _format_dashboard_task_due_label(due_date: Optional[str]) -> str:
    return str(due_date or "none").strip() or "none"


def _merge_task_parse_results(
    base: CoSTaskActionParseResult, extra: CoSTaskActionParseResult
) -> CoSTaskActionParseResult:
    merged_text = base.text
    extra_text = (extra.text or "").strip()
    if extra_text and extra_text != merged_text:
        if merged_text:
            merged_text += "\n\n" + extra_text
        else:
            merged_text = extra_text
    return CoSTaskActionParseResult(
        text=merged_text,
        added_dashboard_tasks=int(base.added_dashboard_tasks) + int(extra.added_dashboard_tasks),
        ambiguous_priority_pending=bool(base.ambiguous_priority_pending or extra.ambiguous_priority_pending),
        added_task_items=tuple(base.added_task_items) + tuple(extra.added_task_items),
    )


def _maybe_prepend_no_dashboard_task_saved_notice(
    user_message: str, parse_result: CoSTaskActionParseResult
) -> str:
    """
    When the user clearly asked to add a dashboard task but nothing was persisted (and we are not
    waiting on priority clarification), prepend a truthful note so model hallucinated confirmations
    do not stand alone.
    """
    text = parse_result.text
    if not _user_requested_direct_dashboard_task_add(user_message):
        return text
    if parse_result.added_dashboard_tasks > 0:
        confirmations: list[str] = []
        seen: set[tuple[str, Optional[str]]] = set()
        for desc, due_date in parse_result.added_task_items:
            desc_text = str(desc or "").strip()
            if not desc_text:
                continue
            key = (desc_text.casefold(), due_date)
            if key in seen:
                continue
            seen.add(key)
            confirmations.append(
                f"Task added: {desc_text} (due {_format_dashboard_task_due_label(due_date)})"
            )
            if len(confirmations) >= 3:
                break
        if parse_result.added_dashboard_tasks > len(confirmations):
            confirmations.append(f"Added {parse_result.added_dashboard_tasks} task(s) total.")
        prefix = "\n".join(confirmations).strip()
        if not prefix:
            return text
        if text:
            return prefix + "\n\n" + text
        return prefix
    if parse_result.ambiguous_priority_pending:
        return text
    if text:
        return _TASK_CAPTURE_CONFIRMATION_FAILURE_MESSAGE + "\n\n" + text
    return _TASK_CAPTURE_CONFIRMATION_FAILURE_MESSAGE


def _next_named_weekday_mmddyyyy(name: str, base: datetime) -> Optional[str]:
    names = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    key = (name or "").strip().lower()
    target = names.get(key)
    if target is None:
        return None
    current = base.weekday()
    delta_days = (target - current) % 7
    d = base.date() + timedelta(days=delta_days)
    return d.strftime("%m-%d-%Y")


def synthesize_add_task_line_from_user_text(
    user_message: str, *, now: Optional[datetime] = None
) -> Optional[str]:
    """
    When the user asks in plain language to add a task or set a reminder, build one ADD_TASK line
    so _parse_and_add_tasks can persist it. Returns None if the message does not match.
    """
    text = (user_message or "").strip()
    if not text:
        return None
    if text.lstrip().upper().startswith("ADD_TASK:"):
        return None
    m = _DASHBOARD_TASK_USER_INTENT_RE.search(text)
    if not m:
        return None
    rest = (m.group(1) or "").strip()
    if not rest:
        return None

    base = now or _now_local()
    if getattr(base, "tzinfo", None):
        local_base = base
    else:
        local_base = base.replace(tzinfo=tzlocal())

    lower = rest.lower()
    category = "Personal" if re.search(r"\bpersonal\b", lower) else "Business"

    estimate_minutes, rest = extract_first_duration_phrase(rest)
    if estimate_minutes is not None:
        estimate_minutes = max(0, min(estimate_minutes, 100_000))

    priority_explicit: Optional[int] = None
    pm = re.search(r"(?i)\b(?:priority|prio\.?)\s*[:\s]*(?:p)?([0-5])\b", rest)
    if pm:
        priority_explicit = int(pm.group(1))
    if priority_explicit is None:
        pm2 = re.search(r"(?i)(?:^|[\s,;])\bp([0-5])\b", rest)
        if pm2:
            priority_explicit = int(pm2.group(1))

    due_norm: Optional[str] = None
    if re.search(r"\b(?:by|due)\s+(?:the\s+)?next\s+week\b", lower):
        due_norm = (local_base.date() + timedelta(days=7)).strftime("%m-%d-%Y")
    elif "tomorrow" in lower or re.search(r"\b(?:by|due)\s+tomorrow\b", lower):
        due_norm = (local_base.date() + timedelta(days=1)).strftime("%m-%d-%Y")
    elif re.search(r"\b(?:by|due)\s+today\b", lower) or re.search(
        r"(?:^|[\s,;])(?:today|tonight)\b", lower
    ):
        due_norm = local_base.strftime("%m-%d-%Y")
    else:
        dm = re.search(r"\b(\d{1,2}-\d{1,2}-\d{4})\b", rest)
        if dm:
            due_ok, parsed = _normalize_dashboard_mmddyyyy(dm.group(1))
            if due_ok:
                due_norm = parsed
        wdm = re.search(
            r"\b(?:by|due)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            lower,
        )
        if wdm and due_norm is None:
            due_norm = _next_named_weekday_mmddyyyy(wdm.group(1), local_base)

    desc = rest
    desc = re.sub(r"(?i)[,;]?\s*(?:priority|prio\.?)\s*[:\s]*(?:p)?[0-5]\b", "", desc)
    desc = re.sub(r"(?i)(?:^|[\s,;])\bp[0-5]\b(?=\s*(?:,|;|$))", "", desc)
    desc = re.sub(r"(?i)[,;]?\s*\b(?:by|due)\s+(?:the\s+)?next\s+week\b", "", desc)
    desc = re.sub(r"(?i)[,;]?\s*\b(?:by|due)\s+tomorrow\b", "", desc)
    desc = re.sub(r"(?i)[,;]?\s*\b(?:by|due)\s+today\b", "", desc)
    desc = re.sub(
        r"(?i)[,;]?\s*\b(?:by|due)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        "",
        desc,
    )
    desc = re.sub(r"(?i)\b(?:today|tonight)\b", "", desc)
    desc = re.sub(r"\b\d{1,2}-\d{1,2}-\d{4}\b", "", desc)
    desc = desc.strip(" ,.;-\t")
    desc = re.sub(r"\s+", " ", desc).strip()
    if len(desc) < 2:
        return None

    if priority_explicit is not None:
        p = priority_explicit
    else:
        inferred = _infer_task_priority(desc, due_date=due_norm, raw_context=text)
        p = inferred if inferred is not None else 3

    due_part = due_norm if due_norm else "none"
    line = f"ADD_TASK: {desc} | {due_part} | {category} | P{p}"
    if estimate_minutes is not None:
        line += f" | none | none | None | {int(estimate_minutes)}"
    return line


def _build_local_task_capture_messages(user_message: str) -> list[dict]:
    now = _now_local()
    current_date = now.strftime("%B %d, %Y")
    current_time = now.strftime("%I:%M %p").lstrip("0")
    tz_name = now.tzname() or "local time"
    return [
        {
            "role": "system",
            "content": (
                "You are a strict task-intake assistant for NaviSsurance. "
                "The user is asking to add one or more dashboard tasks or reminders. "
                "Return ONLY ADD_TASK lines in this exact format:\n"
                "ADD_TASK: <task description> | <MM-DD-YYYY or none> | <Business or Personal> | <P0-P5>\n"
                "Infer Business vs Personal and a best-effort priority from urgency and timing. "
                "If you truly cannot form a valid task line, return exactly TASK_CAPTURE_FAILED.\n\n"
                f"Current local date/time: {current_date}, {current_time} ({tz_name})."
            ),
        },
        {"role": "user", "content": str(user_message or "").strip()},
    ]


def _recover_partial_add_task_lines(user_message: str, raw_model_out: str) -> list[str]:
    """
    Best-effort salvage for truncated/partial ADD_TASK output.
    This only runs when the model already emitted ADD_TASK but strict parsing produced zero tasks.
    """
    text = str(raw_model_out or "")
    if "ADD_TASK:" not in text.upper():
        return []
    recovered: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"(?is)ADD_TASK:\s*(.+?)(?=(?:\n[A-Z_]+:)|(?:ADD_TASK:)|\Z)", text):
        payload = re.sub(r"\s+", " ", str(match.group(1) or "").strip())
        if not payload:
            continue
        parts = [p.strip() for p in payload.split("|")]
        desc = (parts[0] if parts else "").strip(" -*•\t\r\n")
        if not desc:
            continue
        due_part = "none"
        if len(parts) > 1:
            due_ok, due_norm = _normalize_dashboard_mmddyyyy(parts[1])
            if due_ok and due_norm:
                due_part = due_norm
        category = ""
        if len(parts) > 2:
            candidate = (parts[2] or "").strip().title()
            if candidate in {"Business", "Personal"}:
                category = candidate
        if not category:
            category = (
                "Personal"
                if re.search(r"\bpersonal\b", f"{payload}\n{user_message}", flags=re.IGNORECASE)
                else "Business"
            )
        priority = _parse_task_priority_value(parts[3] if len(parts) > 3 else "")
        if priority is None:
            priority = _infer_task_priority(
                desc,
                due_date=(None if due_part == "none" else due_part),
                raw_context=f"{payload}\n{user_message}",
            )
        line = f"ADD_TASK: {desc} | {due_part} | {category}"
        if priority is not None:
            line += f" | P{int(priority)}"
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        recovered.append(line)
    return recovered


def _apply_partial_add_task_recovery(
    db: DatabaseManager,
    user_message: str,
    raw_model_out: str,
    parse_result: CoSTaskActionParseResult,
    *,
    chat_id: Optional[int],
) -> CoSTaskActionParseResult:
    if parse_result.added_dashboard_tasks > 0:
        return parse_result
    recovered_lines = _recover_partial_add_task_lines(user_message, raw_model_out)
    if not recovered_lines:
        return parse_result
    recovered = _parse_task_actions(db, "\n".join(recovered_lines), chat_id=chat_id)
    return _merge_task_parse_results(parse_result, recovered)


def _log_task_capture_debug(
    source: str,
    user_message: str,
    raw_model_out: str,
    parse_result: CoSTaskActionParseResult,
) -> None:
    if not _user_requested_direct_dashboard_task_add(user_message):
        return
    if parse_result.added_dashboard_tasks > 0 or parse_result.ambiguous_priority_pending:
        return
    logger.debug(
        "TASK_CAPTURE_UNCONFIRMED source=%s raw_model_output=%r",
        source,
        raw_model_out,
    )


def _handle_direct_task_capture(
    db: DatabaseManager,
    user_message: str,
    *,
    chat_id: Optional[int],
) -> Optional[str]:
    """
    Local-first fast lane for direct task/reminder capture.
    Use deterministic synthesis first, then a strict local structured model prompt.
    """
    if chat_id is None:
        return None
    if not _user_requested_direct_dashboard_task_add(user_message):
        return None
    raw_out = synthesize_add_task_line_from_user_text(user_message)
    if raw_out is None:
        try:
            raw_out = run_local_completion(
                _build_local_task_capture_messages(user_message),
                "task_capture_structured",
            ).strip()
        except Exception as e:
            logger.warning("Local structured task capture failed: %s", e)
            return _TASK_CAPTURE_CONFIRMATION_FAILURE_MESSAGE
    if not raw_out or raw_out.strip().upper() == "TASK_CAPTURE_FAILED":
        return _TASK_CAPTURE_CONFIRMATION_FAILURE_MESSAGE
    parsed = _parse_task_actions(db, raw_out, chat_id=chat_id)
    parsed = _apply_partial_add_task_recovery(
        db,
        user_message,
        raw_out,
        parsed,
        chat_id=chat_id,
    )
    _record_confirmed_task_persistence(parsed)
    _log_task_capture_debug("local_task_capture", user_message, raw_out, parsed)
    return _maybe_prepend_no_dashboard_task_saved_notice(user_message, parsed)


def _cos_cleaned_indicates_dashboard_tasks_applied(cleaned: str) -> bool:
    """True when the parsed CoS reply already recorded tasks or is waiting on priority clarification."""
    t = cleaned or ""
    if len(t) > 0: logger.debug("cos cleaned task indicator len=%d (Pulse private mem + Shield)", len(t))
    if not t.strip():
        return False
    if re.search(r"(?is)—\s*\*added\s+\d+\s+task", t):
        return True
    if "Priority clarification needed" in t:
        return True
    lc = t.lower()
    if "dashboard task" in lc and re.search(
        r"(?is)—\s*\*(?:added|created|skipped|bulk-created)\s+\d+", t
    ):
        return True
    return False


def apply_dashboard_task_intent_fallback(
    db: DatabaseManager,
    user_message: str,
    raw_model_out: str,
    parse_result: CoSTaskActionParseResult,
    *,
    chat_id: Optional[int],
) -> CoSTaskActionParseResult:
    """
    If a CoS/dashboard turn clearly asked to add a task but nothing was persisted, append a
    synthesized ADD_TASK line and re-run the action parser once.
    """
    if chat_id is None:
        return parse_result
    if _cos_cleaned_indicates_dashboard_tasks_applied(parse_result.text):
        return parse_result
    line = synthesize_add_task_line_from_user_text(user_message)
    if not line:
        return parse_result
    return _parse_task_actions(
        db, (parse_result.text + "\n" + line).strip(), chat_id=chat_id
    )


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


def _is_cos_command_only_message(message: str) -> bool:
    return bool(_extract_explicit_action_lines(message))


def _memory_hints_in_message(text: str) -> bool:
    t = (text or "").strip().casefold()
    if not t:
        return False
    return any(s in t for s in _MEMORY_HINT_SUBSTRINGS)


def _should_skip_passive_memory_extraction(user_message: str, assistant_message: str) -> bool:
    """Avoid the extra MODEL_FAST round-trip when it is unlikely to yield durable memory."""
    if _is_cos_command_only_message(user_message or ""):
        return True
    um = (user_message or "").strip()
    am = (assistant_message or "").strip()
    if _memory_hints_in_message(um):
        return False
    skip = len(um) < 120 and len(am) < 72
    if skip or True: logger.debug("memory extraction skip um_len=%d am_len=%d (Pulse private + Shield)", len(um), len(am))
    return skip


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
    max_tokens: Optional[int] = None,
) -> str:
    """Tool loop for single-turn CoS flows using grok_completion."""
    user_aug = user_text
    out = ""
    mt = int(max_tokens) if max_tokens is not None else get_cos_max_output_tokens(db)
    for _ in range(3):
        out = grok_completion(system_text, user_aug, model=get_model(ModelRole.CHIEF_OF_STAFF), max_tokens=mt)
        out = (out or "").strip()
        if out: logger.debug("CoS tool loop single out chars=%d (Pulse private mem + Shield)", len(out))
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
    max_tokens: Optional[int] = None,
) -> str:
    """Tool loop for multi-turn CoS flows using grok_completion_messages."""
    msgs = list(messages)
    out = ""
    mt = int(max_tokens) if max_tokens is not None else get_cos_max_output_tokens(db)
    for _ in range(3):
        out = grok_completion_messages(msgs, model=get_model(ModelRole.CHIEF_OF_STAFF), max_tokens=mt)
        out = (out or "").strip()
        if out: logger.debug("CoS tool loop messages out chars=%d (Pulse private mem + Shield)", len(out))
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
            parsed = _parse_task_actions(db, "\n".join(explicit_action_lines), chat_id=chat_id)
            response = _maybe_prepend_no_dashboard_task_saved_notice(user_message, parsed)
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

    direct_task_response = _handle_direct_task_capture(db, user_message, chat_id=chat_id)
    if direct_task_response is not None:
        _extract_and_store_memory(
            db,
            chat_id=chat_id,
            user_message=user_message,
            assistant_message=direct_task_response,
        )
        _log_timing("cos_response", t0, mode="local_task_capture", chat_id=chat_id, chars=len(user_message or ""))
        return direct_task_response

    # === Staff Coordinator chat integration (primary way to drive the full CoS staff) ===
    # Note: The old pre-LLM keyword heuristic for detecting "broad goals" that
    # should auto-propose a Work Plan has been removed entirely (per user direction:
    # no more phrase/keyword triggers for intent).
    #
    # Planning proposals are now 100% LLM-driven: the model sees the full user
    # message + rich context and emits PROPOSE_STAFF_PLAN: <goal> in its output
    # when appropriate. That is caught by _handle_propose_staff_plan_from_llm
    # after the tool loop (in both single- and multi-turn paths below).
    #
    # Explicit user commands like "approve WP-xxx", "revise the plan", "checkpoint WP-xxx"
    # and plain-language redirections ("Delegate this to Atlas") are still handled
    # on the *user* message via the dedicated handlers below.

    # Handle "approve WP-42" / "delegate this plan" style commands in chat
    approval_response = _handle_work_plan_approval_command(db, user_message or "", chat_id=chat_id)
    if approval_response is not None:
        _extract_and_store_memory(db, chat_id=chat_id, user_message=user_message, assistant_message=approval_response)
        _log_timing("cos_response", t0, mode="staff_plan_approval", chat_id=chat_id, chars=len(user_message or ""))
        return approval_response

    # Plain language approval for the most recent proposed assignment (including those created via redirection)
    # Catches bare "Approve", "Yes", "Go ahead", "Approve that", etc.
    plain_approval_response = _handle_plain_proposal_approval(db, user_message or "", chat_id=chat_id)
    if plain_approval_response is not None:
        _extract_and_store_memory(db, chat_id=chat_id, user_message=user_message, assistant_message=plain_approval_response)
        _log_timing("cos_response", t0, mode="plain_proposal_approval", chat_id=chat_id, chars=len(user_message or ""))
        return plain_approval_response

    # Revision support: "revise WP-42: make Shield focus on X" or "revise the compliance plan to..."
    revision_response = _handle_work_plan_revision_command(db, user_message or "", chat_id=chat_id)
    if revision_response is not None:
        _extract_and_store_memory(db, chat_id=chat_id, user_message=user_message, assistant_message=revision_response)
        _log_timing("cos_response", t0, mode="staff_plan_revision", chat_id=chat_id, chars=len(user_message or ""))
        return revision_response

    # Plain language delegation redirections / overrides
    # e.g. "Delegate this to Atlas", "Give it to Atlas instead", "Assign the Medicai research to Atlas"
    redirection_response = _handle_delegation_redirection(db, user_message or "", chat_id=chat_id)
    if redirection_response is not None:
        _extract_and_store_memory(db, chat_id=chat_id, user_message=user_message, assistant_message=redirection_response)
        _log_timing("cos_response", t0, mode="delegation_redirection", chat_id=chat_id, chars=len(user_message or ""))
        return redirection_response

    # Also support explicit "checkpoint WP-42" or "status of the plan" for reporting
    import re as _re_plan
    chk = _re_plan.search(r"(?:checkpoint|status|report|where are we).*?(?:wp|plan)[^\d]*(\d+)", (user_message or "").lower())
    if chk:
        try:
            pid = int(chk.group(1))
            report = get_work_plan_checkpoint_report(db, pid)
            return f"**Checkpoint for WP-{pid}**\n\n{report}"
        except Exception:
            pass

    cos_out_tokens = get_cos_max_output_tokens(db)
    hist_max_msg = get_cos_history_max_messages(db)
    hist_max_ch = get_cos_history_max_chars_per_message(db)

    now = _now_local()
    local_time_ctx = _local_time_context(now)
    prefs = db.cos_get_preferences()
    prefs_ctx = _truncate_cos_text(
        _preferences_context(prefs),
        get_cos_preferences_max_chars(db),
    )
    tl = get_cos_max_task_lines(db)
    al = get_cos_max_assignment_lines(db)
    tasks_ctx = _tasks_context(db, max_lines=tl)
    assignments_ctx = _assignments_context(db, max_lines=al)
    # Inject active staff-level work plans so CoS can proactively report on delegated plans
    staff_plan_ctx = _get_active_work_plan_status_for_context(db)
    if staff_plan_ctx:
        assignments_ctx = (assignments_ctx or "") + "\n\n" + staff_plan_ctx
    cal_ctx = _truncate_cos_text(_calendar_context(), get_cos_calendar_max_chars(db))
    mem_ctx = _memory_context(db, user_message, chat_id)

    # Client dossier digest (rich, structured) when message or context resolves to a client.
    # This is the main integration point so CoS planning & delegation are client-aware.
    client_digest = ""
    try:
        refs = infer_entity_memory_refs(db, user_message or "")
        for ref in refs:
            if ref.get("entity_type") == "client":
                client_digest = build_client_dossier_context(
                    db,
                    int(ref.get("entity_key")),
                    max_memories=4,
                    max_projects=3,
                    max_assignments=3,
                    max_tasks=4,
                )
                break
    except Exception:
        client_digest = ""

    if client_digest:
        mem_ctx = (mem_ctx or "") + "\n\n" + client_digest
    if mem_ctx: logger.debug("cos_response final mem_ctx chars=%d (Pulse private memory + Shield surface)", len(mem_ctx or ""))

    # Phase 1: Relevant Past Work (DocumentRecords) — lightweight, optional, graceful
    # Only when we have a client context so the suggestions are actually useful.
    historical_docs_ctx = ""   # always initialize to avoid UnboundLocalError on non-client flows
    try:
        if client_digest:
            # Extract a simple client hint from the digest or user message
            client_name = None
            # Very lightweight extraction (reuses existing entity inference spirit)
            for line in (client_digest + "\n" + (user_message or "")).splitlines():
                if "client" in line.lower() and ":" in line:
                    client_name = line.split(":", 1)[-1].strip().split()[0]
                    break
            if client_name:
                # Strengthen bias using raw_context (full text with marker) so centralized extract_reference_terms
                # + ref scoring + _ref_match marking fire reliably (fixes the main integration gap in Issue 3).
                # query stays the clean search terms (inner or user_message); raw_context carries the injection marker.
                text_for_ref = (user_message or "") + "\n" + (client_digest or "")
                clean_query = ""
                try:
                    import re
                    m = re.search(r'\[Historical reference: ([^\]]+)', text_for_ref)
                    if m:
                        clean_query = m.group(1)[:120]
                    else:
                        clean_query = (user_message or "")[:120]
                except Exception:
                    clean_query = (user_message or "")[:120]
                past_docs = get_relevant_past_documents(
                    client_hint=client_name,
                    query=clean_query,
                    limit=4,
                    raw_context=text_for_ref  # key: lets extraction see the marker even when query is stripped inner text
                )
                if past_docs:
                    from core.file_handler import format_compact_historical_context
                    historical_docs_ctx = format_compact_historical_context(past_docs, max_items=3)
                    # Also keep the injection into mem_ctx for backward compatibility with existing context
                    if historical_docs_ctx:
                        mem_ctx = (mem_ctx or "") + "\n\n" + historical_docs_ctx
                else:
                    historical_docs_ctx = ""
            else:
                historical_docs_ctx = ""
    except Exception:
        historical_docs_ctx = ""
        pass  # Never break CoS flow

    prefs_ctx, cal_ctx, mem_ctx, _, tasks_ctx, assignments_ctx = _apply_cos_context_budget(
        prefs_ctx,
        cal_ctx,
        mem_ctx,
        tasks_ctx,
        assignments_ctx,
        get_cos_context_budget_chars(db),
        emails="",
    )

    intel_ctx = _raised_intel_context(db, max_items=5)
    consistency_ctx = _consistency_context(db)

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
ADD_TASK: <task description> | <due date as MM-DD-YYYY or "none"> | <Business or Personal> [| <priority P0-P5 or 0-5 or none>] [| <assigned to or none>] [| <project id or none>] [| <recurrence: None|Daily|Weekly|Monthly>] [| <estimate: 90 or 1 hr 15 min or none>]
Examples:
- ADD_TASK: Send follow-up to client | 02-25-2026 | Business | P3
- ADD_TASK: Draft DHF gap memo | 03-05-2026 | Business | P1 | Mason | 12 | Weekly | 90
When adding a task, include priority whenever you can infer it from urgency, timing, or the surrounding plan context. Do not use P0 as a placeholder for "unspecified." If the user asked you to add a task and priority is genuinely unclear, ask a short follow-up question instead of outputting an ADD_TASK line with no priority.
Omit ADD_TASK lines if you are not adding any tasks.
{calendar_instructions}

You may also propose delegation to named team members by writing one or more lines in this exact format (each line creates a **proposal** for review, not a live assignment):
ASSIGN: <AgentName> | <Title> | <Brief> | <P1-P5> | <YYYY-MM-DD or none>
Example: ASSIGN: Atlas | FDA PCCP research brief | Research latest guidance and summarize with citations. | P5 | 2026-03-01
Available agent names: Atlas, Quill, Sentinel, Lex, Scout, Mason, Ledger, Archive, Pulse, Shield.
Omit ASSIGN lines if you are not proposing delegation.
When crafting the <Brief> for any ASSIGN, if the provided context/memory includes a "Recent <AgentName> reflection: ..." line, reference 1 relevant point from it in the <Brief> to ensure continuity with the agent's prior self-reflection and your previous guidance.

**Important - User Delegation Style:**
Adam often gives plain-language delegation instructions instead of using the rigid ASSIGN format. Examples:
- "Delegate this to Atlas"
- "Give it to Atlas instead"
- "Assign the Medicai research to Atlas"
- "Have Atlas handle this"
- "Use Atlas for the company lookup"

When the user gives a direct instruction like this (especially right after you proposed a plan), do **not** try to emit an ASSIGN line yourself. The system has a dedicated handler (_handle_delegation_redirection) that will catch these natural instructions ("give this to Pulse", "assign the research to Atlas", etc.) and create a clean proposed assignment (P- id) carrying the substantive brief. You can simply acknowledge and let the handler do the work. When the user later says "approve" (or "approve P-xxx"), it activates the specialist: dedicated thread + handoff of the brief + bootstrap so the agent (Pulse for research/intel, etc.) actually performs the work, stores intel findings, and surfaces updates.

**Answering "what did Pulse find" or similar follow-ups on a specific request:**
When the user asks what Pulse found on a topic (especially one that was explicitly delegated via "give this to Pulse" or a recent assignment), retrieve and base your answer strictly on:
- The most recent saved intel_findings (kind="intel_finding" in pulse agent_memory, preferably raised or high importance, or those linked to the relevant assignment/client/project).
- Any recent assignment thread content or artifacts for Pulse on that topic (from the specific A-/P- id or the delegation brief).
Do **not** synthesize a new list of guidances from general knowledge or training data. Do **not** bleed in unrelated prior topics the user has asked about before (e.g. a previous Medtronic question has nothing to do with a new iQSurgical or client timeline ask). If there are no fresh dedicated findings for the exact request, say so clearly ("No new Pulse findings saved yet for this specific delegation — the assignment thread has the intake; want me to trigger fresh research?") and offer to re-delegate or run monitoring. Always cite the source (e.g. "from raised finding on assignment A-1234" or "from recent pulse intel"). This keeps answers grounded in actual executed work rather than hallucinated synthesis.

High-level Staff Plans (CoS coordinator): Use this when the user's request is a broad, multi-step goal that would benefit from structured coordination across specialists (research + drafting + QA + tracking), milestones, and an explicit user approval gate before work starts in parallel.

In that case, output *exactly* (as your primary/only response content for this turn):

PROPOSE_STAFF_PLAN: <clean, concise restatement of the goal>

The system will then run the full planning (Mason consultation for project structure, gather relevant intel/dossier, build rich briefs for the right mix of Pulse/Atlas for research, Quill for writing, Sentinel for review, Mason for coordination, etc.) and present a formatted "Staff Plan WP-xxx Proposed" for Adam to approve, revise, or redirect ("just give it to Atlas instead").

Criteria for using PROPOSE_STAFF_PLAN (vs. just answering or using ASSIGN):
- The work spans multiple specialists and would benefit from Mason milestone tracking.
- There is value in user seeing the full proposed team + scope before execution.
- Examples: building a substantial equivalence table with research + drafting + QA; launching a full regulatory strategy workstream with ongoing monitoring.

Do NOT use it for:
- Simple factual questions or client forwards about specific facts/timelines.
- Single lookups or one-off research.
- Things you can handle yourself with a tool (WEB_SEARCH) or by delegating to one person via ASSIGN: Pulse | ...

In normal conversation you can still reference active/proposed WP-IDs. The context will include recent progress on them.

**Follow-up questions after a plan proposal:**
If Adam asks a question after you propose a plan (e.g. "What does Atlas usually handle?", "How busy is Mason right now?", "Tell me more about the Medicai task"), answer the question helpfully while keeping the proposed plan visible and "pending". Do not assume the plan is rejected or approved unless he explicitly says so. You can remind him of the proposal and the approval command when appropriate.

You may approve a proposed assignment (queues it and routes work to the assignee). Use only when Adam has confirmed approval in chat:
APPROVE_PROPOSAL: <P-0007 or A-0007 or numeric id>
Example: APPROVE_PROPOSAL: P-0003
Omit APPROVE_PROPOSAL lines if you are not approving a proposal.

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

{_COS_MEMORY_REASONING_HINT}
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
            out = grok_completion(
                system_text,
                user_aug,
                model=get_model(ModelRole.CHIEF_OF_STAFF),
                max_tokens=cos_out_tokens,
            )
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
            out = grok_completion_messages(
                msgs,
                model=get_model(ModelRole.CHIEF_OF_STAFF),
                max_tokens=cos_out_tokens,
            )
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
        if historical_docs_ctx:
            user += f"""

{historical_docs_ctx}"""
        user += f"""

{tasks_ctx}

{assignments_ctx}

{intel_ctx}

**What he says (main input):**
{user_message or "What should I focus on right now?"}"""
        try:
            out = _run_tool_loop_single(system, user)
            # LLM-driven staff plan: if the model judges full coordination (milestones,
            # multiple specialists, Mason tracking, approval gate) is needed, it emits
            # PROPOSE_STAFF_PLAN: <goal>. We turn that into the rich proposal here.
            # This is the main path for nuanced intent instead of keyword pre-filters.
            staff_plan = _handle_propose_staff_plan_from_llm(db, out, chat_id=chat_id)
            if staff_plan:
                _extract_and_store_memory(db, chat_id=chat_id, user_message=user_message, assistant_message=staff_plan)
                _log_timing("cos_response", t0, mode="staff_plan_proposal_from_model", chat_id=chat_id, chars=len(user_message or ""))
                return staff_plan
            parsed = _parse_task_actions(db, out, chat_id=chat_id)
            parsed = _apply_partial_add_task_recovery(
                db, user_message, out, parsed, chat_id=chat_id
            )
            parsed = apply_dashboard_task_intent_fallback(
                db, user_message, out, parsed, chat_id=chat_id
            )
            _record_confirmed_task_persistence(parsed)
            _log_task_capture_debug("cos_grok_single", user_message, out, parsed)
            cleaned = _maybe_prepend_no_dashboard_task_saved_notice(user_message, parsed)
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
            if _user_requested_direct_dashboard_task_add(user_message):
                fallback = _handle_direct_task_capture(db, user_message, chat_id=chat_id)
                if fallback and fallback != _TASK_CAPTURE_CONFIRMATION_FAILURE_MESSAGE:
                    return fallback
                return _TASK_CAPTURE_GROK_FAILURE_MESSAGE
            return format_grok_user_facing_error(e)

    # Multi-turn: build messages list. Caller must have saved the current user message and included it in conversation_history.
    time_ctx = local_time_ctx
    if prefs_ctx:
        time_ctx += f"\n\n**His stated preferences / constraints:**\n{prefs_ctx}"
    if cal_ctx:
        time_ctx += f"\n\n{cal_ctx}"
    if mem_ctx:
        time_ctx += f"\n\n{mem_ctx}"
    if historical_docs_ctx:
        time_ctx += f"\n\n{historical_docs_ctx}"
    time_ctx += f"\n\n{tasks_ctx}\n\n{assignments_ctx}\n\n{intel_ctx}\n\n{consistency_ctx}"
    recent_history = _compact_conversation_history(
        conversation_history,
        max_messages=hist_max_msg,
        max_chars_per_message=hist_max_ch,
    )
    messages = [{"role": "system", "content": system + "\n\n" + time_ctx}]
    for role, content in recent_history:
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    try:
        out = _run_tool_loop_messages(messages)
        # LLM-driven staff plan (see single-turn comment).
        staff_plan = _handle_propose_staff_plan_from_llm(db, out, chat_id=chat_id)
        if staff_plan:
            _extract_and_store_memory(db, chat_id=chat_id, user_message=user_message, assistant_message=staff_plan)
            _log_timing("cos_response", t0, mode="staff_plan_proposal_from_model", chat_id=chat_id, chars=len(user_message or ""))
            return staff_plan
        parsed = _parse_task_actions(db, (out or "").strip(), chat_id=chat_id)
        parsed = _apply_partial_add_task_recovery(
            db, user_message, out, parsed, chat_id=chat_id
        )
        parsed = apply_dashboard_task_intent_fallback(
            db, user_message, out, parsed, chat_id=chat_id
        )
        _record_confirmed_task_persistence(parsed)
        _log_task_capture_debug("cos_grok_multi", user_message, out, parsed)
        cleaned = _maybe_prepend_no_dashboard_task_saved_notice(user_message, parsed)
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
        if _user_requested_direct_dashboard_task_add(user_message):
            fallback = _handle_direct_task_capture(db, user_message, chat_id=chat_id)
            if fallback and fallback != _TASK_CAPTURE_CONFIRMATION_FAILURE_MESSAGE:
                return fallback
            return _TASK_CAPTURE_GROK_FAILURE_MESSAGE
        return format_grok_user_facing_error(e)


def approve_assignment_proposal(
    db: DatabaseManager,
    proposal_id: int,
    *,
    actor_code: str = "navi",
) -> tuple[bool, str]:
    """
    Approve a proposed assignment: set status to queued, create assignee thread, prime handoff
    (kickoff + bootstrap). Falls back to execution-only bootstrap if thread creation fails.
    """
    pid = int(proposal_id)
    if not db.agent_approve_proposal(pid, actor_code=actor_code):
        return False, f"Failed to approve proposal P-{pid}."
    if True: logger.debug("approved proposal id=%d (Pulse private mem + Shield surface)", pid)

    row = db.agent_get_assignment(pid) or {}
    assignee = str(row.get("assignee_code") or "").strip().lower()
    if not assignee:
        return True, f"Proposal P-{pid} approved (queued) but assignee was missing; open the assignment to fix."

    # New preferred path: Create a real Task assigned to the agent (instead of relying only on agent_assignments)
    try:
        if db.agent_get(assignee):  # it's an agent
            task_id = db.add_task(
                session_id=None,
                task_text=f"[From CoS] {row.get('title', 'Work item')}",
                due_date=row.get("due_date"),
                category="Business",
                assigned_to=assignee,
                priority=int(row.get("priority", 3)),
                blockers=row.get("brief_md", "")[:500] if row.get("brief_md") else None,
            )
            if task_id:
                logger.info("Created task %s for agent %s from approved CoS proposal P-%s", task_id, assignee, pid)
    except Exception:
        logger.exception("Failed to create task for approved agent assignment P-%s", pid)

    try:
        tid = create_assignment_thread(
            db,
            assignment_id=pid,
            assignee_code=assignee,
            reason="proposal_approved",
            actor_code=actor_code,
            context_json={"source": "chief_of_staff", "proposal_approved": True},
        )
        if tid:
            prime_assignment_handoff(db, assignment_id=pid, thread_id=int(tid))
        else:
            from core.agent_execution import bootstrap_assignment_execution

            bootstrap_assignment_execution(db, assignment_id=pid)
    except Exception:
        logger.exception("Proposal approve: thread/handoff failed for P-%s", pid)
        try:
            from core.agent_execution import bootstrap_assignment_execution

            bootstrap_assignment_execution(db, assignment_id=pid)
        except Exception:
            logger.exception("Proposal approve: bootstrap fallback failed for P-%s", pid)

    ag = db.agent_get(assignee) or {}
    assignee_label = str(ag.get("display_name") or ag.get("code") or assignee).strip() or assignee
    return True, f"Proposal P-{pid} approved and routed to {assignee_label}."


class ChiefOfStaffService:
    """GUI-facing helpers for Chief of Staff workflows (e.g. proposal approval from the tab)."""

    def __init__(self, db: DatabaseManager, main_window: object | None = None):
        self.db = db
        # Pulse private memory + Shield surface in CoS orchestration
        self.main_window = main_window

    def approve_proposal(self, proposal_id: int) -> str:
        pid = int(proposal_id)
        # CoS proposal approval integrates Pulse private memory + Shield
        _ok, msg = approve_assignment_proposal(self.db, pid, actor_code="navi")
        mw = self.main_window
        if mw is not None and hasattr(mw, "show_toast"):
            if _ok:
                try:
                    mw.show_toast(
                        f"Assignment A-{pid:04d} approved and routed",
                        duration_ms=4000,
                        color="#22C55E",
                    )
                except TypeError:
                    try:
                        mw.show_toast(f"Proposal P-{pid} approved and routed", duration=4000)
                    except Exception:
                        pass
                except Exception:
                    pass
            else:
                brief = (msg or "Could not approve proposal").strip()
                try:
                    mw.show_toast(
                        f"Approve failed: {brief[:120]}",
                        duration_ms=6000,
                        color="#EF4444",
                    )
                except TypeError:
                    try:
                        mw.show_toast(f"Approve failed: {brief[:120]}", duration=6000)
                    except Exception:
                        pass
                except Exception:
                    pass
        return msg

    def reject_proposal(self, proposal_id: int) -> str:
        pid = int(proposal_id)
        # CoS reject integrates Pulse private memory + Shield triage
        row = self.db.agent_get_assignment(pid)
        if not row:
            return f"Proposal P-{pid} not found."
        if str(row.get("status") or "").strip().lower() != "proposed":
            return f"P-{pid} is not a proposed assignment."
        ok = self.db.agent_update_assignment_status(
            assignment_id=pid,
            to_status="cancelled",
            actor_code="navi",
            note="Proposal rejected",
        )
        if ok:
            return f"Proposal P-{pid} rejected (cancelled)."
        return f"Failed to reject proposal P-{pid}."


def _parse_task_actions(
    db: DatabaseManager, response: str, *, chat_id: Optional[int] = None
) -> CoSTaskActionParseResult:
    """
    Parse action lines from the model response:
    - ADD_TASK: add dashboard tasks
    - ADD_CAL_BLOCK: create Google Calendar events
    - ASSIGN: create proposed delegation assignments (user approves in Suggested Assignments)
    Return cleaned user-visible text (action lines removed) plus counts in CoSTaskActionParseResult.
    """
    # CoS task parsing integrates Pulse private memory + Shield
    if not response:
        return CoSTaskActionParseResult(
            text=response,
            added_dashboard_tasks=0,
            ambiguous_priority_pending=False,
        )
    if response: logger.debug("task actions parse response chars=%d (Pulse private mem + Shield)", len(response))
    session_id = f"dashboard_cos_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    added_tasks = 0
    added_task_items: list[tuple[str, Optional[str]]] = []
    added_tasks_from_assignments = 0
    added_blocks = 0
    updated_task_tags = 0
    updated_task_estimates = 0
    task_update_failures: list[str] = []
    created_assignments: list[str] = []
    proposed_assignments: list[str] = []
    proposal_detail_lines: list[str] = []
    approved_proposals: list[str] = []
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

        # --- ROBUST ADD_TASK HANDLER (.search allows leading text on the same line) ---
        # Rich numbered / pipe triplets are handled after this loop (see finditer below) so we do not
        # misclassify lines like ADD_TASK_FROM_ASSIGNMENT: ... | ... as pipe prose.
        m = ADD_TASK_PATTERN.search(stripped)
        if m:
            explicit_add_task_seen = True
            payload = (m.group(1) or "").strip()
            parts = [p.strip() for p in payload.split("|")]
            if len(parts) < 3:
                logger.warning("CoS ADD_TASK rejected - not enough parts: %r", stripped)
                continue

            task_text = (parts[0] or "").strip()
            due_raw = (parts[1] or "").strip()
            category = (parts[2] or "").strip().title()

            if not task_text or category not in {"Business", "Personal"}:
                logger.warning("CoS ADD_TASK rejected - bad task or category: %r", stripped)
                continue

            due_ok, due_norm = _normalize_dashboard_mmddyyyy(due_raw)
            if not due_ok:
                logger.warning("CoS ADD_TASK rejected - bad due date: %r", due_raw)
                continue

            priority = _parse_task_priority_value(parts[3] if len(parts) > 3 else "")
            if priority is None:
                priority = _infer_task_priority(task_text, due_date=due_norm, raw_context=stripped)
            if priority is None:
                ambiguous_task_priorities.append(task_text)
                logger.info("CoS ADD_TASK deferred pending priority clarification: %r", task_text)
                continue

            assigned_to: Optional[str] = None
            project_part_idx = 4
            recurrence_part_idx = 5
            legacy_next_ok, _legacy_next = _normalize_dashboard_mmddyyyy(parts[4] if len(parts) > 4 else "")
            if len(parts) > 4 and legacy_next_ok and (parts[4] or "").strip():
                project_part_idx = 5
                recurrence_part_idx = 6
            elif len(parts) > 4:
                assigned_to = (parts[4] or "").strip() or None
                if assigned_to and assigned_to.lower() in {"none", "null", "n/a"}:
                    assigned_to = None
            project_raw = (parts[project_part_idx] if len(parts) > project_part_idx else "").strip()
            recurrence_raw = (parts[recurrence_part_idx] if len(parts) > recurrence_part_idx else "").strip()
            recurrence = recurrence_raw if recurrence_raw else "None"
            if recurrence.lower() in {"none", "null", "n/a"}:
                recurrence = "None"
            if recurrence not in {"None", "Daily", "Weekly", "Monthly"}:
                recurrence = "None"

            estimate_minutes = parse_optional_estimate_minutes_field(
                parts[recurrence_part_idx + 1] if len(parts) > recurrence_part_idx + 1 else None
            )

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
                    assigned_to=assigned_to,
                    estimate_minutes=estimate_minutes,
                )
                if priority is not None:
                    db.update_task_by_id(
                        task_id=int(task_id),
                        priority=priority if priority is not None else db._UNSET,  # type: ignore[attr-defined]
                    )
                added_tasks += 1
                added_task_items.append((task_text, due_norm))
                logger.info("CoS added task via ADD_TASK: %s", task_text)
            except Exception as e:
                logger.error("Failed to add task from ADD_TASK: %s", e)
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
                added_task_items.append((task_text, due_date))
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
                if (not include_closed) and st in {"done", "cancelled", "proposed"}:
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

            context_obj = {"source": "chief_of_staff", "proposal": True}
            if chat_id is not None:
                context_obj["cos_chat_id"] = int(chat_id)
            assignee_code = str(agent.get("code") or "").strip().lower()
            proposal_id: int | None = None
            try:
                proposal_id = db.agent_create_proposed_assignment(
                    title=title,
                    brief_md=brief,
                    assignee_code=assignee_code,
                    priority=priority,
                    due_date=due_date,
                    proposed_by="navi",
                    context_json=context_obj,
                )
            except Exception as e:
                proposal_id = None
                logger.warning("CoS ASSIGN proposal create failed: %s", e)

            if proposal_id:
                disp = str(agent.get("display_name") or agent.get("code") or assignee_name).strip()
                proposed_assignments.append(f"{disp} (A-{int(proposal_id):04d})")
                brief_prev = (brief[:250] + "...") if len(brief) > 250 else brief
                proposal_detail_lines.append(
                    f"**{title.strip()}** (A-{int(proposal_id):04d}) — assignee **{disp}**; priority **P{priority}**; "
                    f"due **{due_date or 'none'}**.\nBrief: {brief_prev}"
                )
            else:
                assignment_failures.append(f"failed creating proposal for {assignee_name}")
            continue

        m_appr = APPROVE_PROPOSAL_PATTERN.match(stripped)
        if m_appr:
            payload = (m_appr.group(1) or "").strip()
            aid = _parse_assignment_ref(payload)
            if aid is None:
                assignment_failures.append(f"invalid proposal id '{payload}'")
                logger.warning("CoS APPROVE_PROPOSAL invalid id: %r", payload)
                continue
            ok_apr, apr_msg = approve_assignment_proposal(db, int(aid), actor_code="navi")
            if ok_apr:
                approved_proposals.append(f"P-{int(aid)}")
            else:
                assignment_failures.append(apr_msg or f"failed approving P-{int(aid)}")
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
                if bulk_mode == "open" and current_status in {"done", "cancelled", "proposed"}:
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
                if bulk_mode == "open" and current_status in {"done", "cancelled", "proposed"}:
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
                if bulk_mode == "open" and current_status in {"done", "cancelled", "proposed"}:
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
                if bulk_mode == "open" and current_status in {"done", "cancelled", "proposed"}:
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
                    added_task_items.append((task_text, due_date))
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
                    added_task_items.append((task_text, due_date))
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
    if proposal_detail_lines:
        body = "\n\n".join(proposal_detail_lines[:5])
        if len(proposal_detail_lines) > 5:
            body += "\n\n…"
        action_notes.append(
            "— *Proposal(s) created for review* — open **Suggested Assignments** to approve or edit:\n\n" + body
        )
    elif proposed_assignments:
        preview = ", ".join(proposed_assignments[:3])
        more = " ..." if len(proposed_assignments) > 3 else ""
        action_notes.append(
            f"— *Created {len(proposed_assignments)} proposal(s) for review: {preview}{more}. "
            "Review them in **Suggested Assignments** above the delegation board.*"
        )
    if approved_proposals:
        preview = ", ".join(approved_proposals[:5])
        more = " ..." if len(approved_proposals) > 5 else ""
        action_notes.append(
            f"— *Approved {len(approved_proposals)} proposal(s) and routed to agents: {preview}{more}.*"
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
    return CoSTaskActionParseResult(
        text=out,
        added_dashboard_tasks=added_tasks,
        ambiguous_priority_pending=bool(ambiguous_task_priorities),
        added_task_items=tuple(added_task_items),
    )


def _parse_and_add_tasks(db: DatabaseManager, response: str, *, chat_id: Optional[int] = None) -> str:
    """Parse action lines from the model response; returns visible text only (see _parse_task_actions for stats)."""
    return _parse_task_actions(db, response, chat_id=chat_id).text


# =============================================================================
# CoS Staff Coordinator — Work Plans (the real "chief of staff" orchestration)
# =============================================================================
#
# This is the high-level layer on top of the existing agent_assignments scaffolding.
# CoS is opinionated and proactive, but intent detection is LLM-driven:
#   - For broad multi-specialist goals the model emits PROPOSE_STAFF_PLAN: <goal>
#     (or user uses very explicit "draft a work plan for..." which the light trigger catches).
#   - CoS then proposes a complete, multi-agent WorkPlan with Mason consult.
#   - Rich context + high-quality briefs for the appropriate assignees.
#   - Explicit Mason consultation when project structure is unclear.
#   - Mason can autonomously handle milestones on *existing* projects; new projects require user sign-off.
#   - Once approved → CoS delegates (creates real assignments + threads + handoffs).
#   - CoS reports back on completion / attention-needed / full-plan completion (push notifications).
#
# Primary interaction is in chat; the CoS tab will also expose a structured "Work Plans" view.
# =============================================================================


@dataclass
class WorkPlanProposal:
    """Lightweight container returned by propose_work_plan for chat/UI rendering."""
    plan_id: int
    title: str
    goal: str
    summary_md: str
    assignments: list[dict]  # each has assignee_code, title, brief_md, priority, due_suggestion, context
    rationale: str
    mason_consultation: str | None = None
    status: str = "proposed"


def _consult_mason_for_project_structure(
    db: DatabaseManager,
    goal: str,
    client_context: str | None = None,
    existing_projects: list[dict] | None = None,
) -> dict:
    """
    Opinionated Mason consultation during planning.

    Mason is allowed to:
      - Propose new milestones on *existing* projects autonomously (CoS will accept)
      - Recommend a brand-new project (requires explicit user approval before creation)

    Returns a structured dict the planner can consume.
    """
    try:
        from core.grok_client import grok_completion
        from core.model_router import get_model, ModelRole

        model_name = get_model(ModelRole.CHIEF_OF_STAFF)

        existing = existing_projects or []
        existing_summary = "\n".join(
            f"- P-{p.get('id')} {p.get('name')} (client: {p.get('client_name', 'N/A')})"
            for p in existing[:8]
        ) or "No active projects found for this client/context."

        prompt = f"""You are Mason, the senior Project Manager for a consulting firm.

A goal has come in from the Chief of Staff:

GOAL: {goal}

CLIENT / CONTEXT:
{client_context or "General / internal work"}

EXISTING PROJECTS IN SCOPE:
{existing_summary}

Your job right now is ONLY to give project-structure advice for this goal:

1. Does this goal clearly belong to one of the existing projects above? If yes, name it and suggest 1-3 new milestones (with rough due dates and owners if obvious).
2. If it does NOT map cleanly to an existing project, propose a sensible new project name + 2-4 initial milestones.
3. Flag ONLY if there is a clear security, privacy, data-risk, or infosec/compliance-control angle that Shield (Security Steward) should own. Do not flag pure regulatory/FDA study-type or timeline questions for Shield.

Respond in clean JSON only with this exact shape:

{{
  "recommendation": "existing" | "new_project",
  "project_id": <int or null>,
  "project_name": "string (only if new)",
  "milestones": [
    {{"title": "...", "due_in_days": 14, "notes": "..."}},
    ...
  ],
  "risk_notes": "any security/privacy/dependency flags for Pulse or Shield (blank for pure regulatory research)",
  "rationale": "one paragraph explaining your reasoning"
}}

Be decisive. You are allowed to create new milestones on existing projects without further approval.
"""

        # Call correctly: grok_completion(system, user, model, max_tokens)
        system_prompt = prompt
        user_msg = "Respond ONLY with the exact JSON object, no extra text or markdown."
        content = grok_completion(system_prompt, user_msg, model=model_name, max_tokens=1200) or ""

        # Best-effort JSON extraction
        import re as _re
        m = _re.search(r"\{[\s\S]*\}", content)
        if m:
            parsed = json.loads(m.group(0))
            return parsed
        return {
            "recommendation": "new_project",
            "project_id": None,
            "project_name": "New Initiative: " + goal[:60],
            "milestones": [{"title": goal[:80], "due_in_days": 21, "notes": "Initial scope from CoS planning"}],
            "risk_notes": "",
            "rationale": "Mason consultation fallback",
        }
    except Exception as e:
        logger.warning("Mason consultation failed: %s", e)
        return {
            "recommendation": "new_project",
            "project_id": None,
            "project_name": None,
            "milestones": [],
            "risk_notes": "",
            "rationale": "Mason unavailable during planning — planner will proceed with lightweight structure.",
        }


def propose_work_plan(
    db: DatabaseManager,
    goal: str,
    *,
    client_id: int | None = None,
    thread_id: int | None = None,
    extra_context: str | None = None,
    force_agents: list[str] | None = None,
) -> WorkPlanProposal:
    """
    The core CoS Staff Coordinator planning engine.

    - Pulls rich context (Pulse intel, memory, dossier, prior work)
    - Consults Mason when project linkage is ambiguous
    - Produces an opinionated, complete multi-agent plan
    - Persists it as a 'proposed' work_plan with linked proposed assignments
    - Returns a rich proposal object ready for chat review or CoS-tab display

    This is deliberately proactive and opinionated — exactly as the user requested.
    """
    goal = (goal or "").strip()
    if not goal:
        raise ValueError("Cannot propose a work plan for an empty goal.")

    now = datetime.now().isoformat()

    # 1. Gather rich context (Pulse + memory + client dossier + documents)
    intel_context = ""
    try:
        intel = IntelService(db)
        findings = intel.get_relevant_intel(goal, limit=8)
        if findings:
            intel_context = "\n".join(
                f"- [{f.get('kind')}] {f.get('title')}: {f.get('summary','')[:200]}"
                for f in findings
            )
    except Exception:
        pass

    client_dossier = ""
    try:
        if client_id:
            snap = get_client_dossier_snapshot(db, client_id)
            client_dossier = snap.get("summary_md", "")[:1500] if snap else ""
    except Exception:
        pass

    # 2. Mason consultation (the two-tier rule the user specified)
    mason_advice = _consult_mason_for_project_structure(
        db,
        goal=goal,
        client_context=client_dossier or extra_context,
        existing_projects=[],  # could be expanded later via db
    )

    # 3. Decide which specialist agents should own pieces (opinionated defaults)
    # Default to Pulse (intel/research) + Mason (coord) for most goals.
    # Only pull Shield when Mason advice or goal text signals real security/privacy/risk angle.
    # This prevents over-scoping pure regulatory timeline/FDA study-type questions (e.g. iQSurgical)
    # to include Shield which is for security/privacy stewardship.
    agents = force_agents or ["pulse", "mason"]
    # Always include Mason for execution tracking on anything project-related
    if "mason" not in agents:
        agents.append("mason")

    # Conditional Shield only for real security/privacy angles (see Mason prompt update + risk_notes).
    if "shield" not in agents:
        risk = str((mason_advice or {}).get("risk_notes") or "").lower()
        gl = goal.lower()
        if ("shield" in risk) or any(w in risk for w in ["security", "privacy", "cyber", "data risk", "infosec"]) or any(w in gl for w in ["security", "privacy risk", "data breach", "hipaa", "cyber"]):
            agents.append("shield")

    # 4. Build the actual assignment specs (rich briefs + context packages)
    assignments_spec: list[dict] = []

    # Mason piece — always present for coordination / milestones
    mason_brief = f"""Goal: {goal}

You are the Project Manager. Using the Mason consultation below, create or extend the appropriate project and milestones.
Track all work, surface blockers early, and keep the CoS informed of progress.

Mason consultation result:
{json.dumps(mason_advice, indent=2)}

Deliver:
- Proper project + milestone structure (new project only if truly required)
- Weekly checkpoint summaries back to CoS
- Early flags for anything needing Shield or Pulse attention
"""
    assignments_spec.append({
        "assignee_code": "mason",
        "title": f"Project coordination & milestone tracking: {goal[:70]}",
        "brief_md": mason_brief,
        "priority": 2,
        "due_suggestion": None,
        "rich_context": {"mason_advice": mason_advice, "original_goal": goal},
    })

    # Pulse research / monitoring piece
    if "pulse" in agents:
        pulse_brief = f"""You are Pulse (Intelligence & Monitoring).

Goal from leadership: {goal}

Relevant recent intel:
{intel_context or "(no strong recent matches)"}

Task:
- Run targeted research / monitoring on the key topics implied by the goal
- Raise [Security-Relevant] or high-impact findings immediately
- Produce a concise intelligence package the other agents can use
- Watch for emerging risks or opportunities

Return findings as artifacts and keep CoS updated on material developments.
"""
        assignments_spec.append({
            "assignee_code": "pulse",
            "title": f"Intelligence & monitoring for: {goal[:70]}",
            "brief_md": pulse_brief,
            "priority": 3,
            "due_suggestion": None,
            "rich_context": {"intel_context": intel_context, "goal": goal},
        })

    # Shield piece (security/compliance/risk)
    if "shield" in agents:
        shield_brief = f"""You are Shield (Security, Compliance & Risk).

Goal: {goal}

Context from Pulse / dossier:
{intel_context[:800] if intel_context else "No specific intel yet."}

Your responsibilities:
- Identify regulatory, contractual, security, or reputational risks
- Propose concrete controls or review steps
- Flag anything that should block or slow other work
- Produce a short risk memo + recommended actions

Work closely with Mason on milestone integration and with Pulse on ongoing monitoring.
"""
        assignments_spec.append({
            "assignee_code": "shield",
            "title": f"Risk, security & compliance review: {goal[:70]}",
            "brief_md": shield_brief,
            "priority": 3,
            "due_suggestion": None,
            "rich_context": {"goal": goal, "mason_advice": mason_advice},
        })

    # 5. Persist the WorkPlan + the proposed assignments (linked via plan_id)
    plan_title = f"Plan: {goal[:80]}"
    # Note: format func prints the Goal header; summary starts with Mason rec to avoid duplicate "Goal:" lines in chat output.
    plan_summary = f"**Mason recommendation:** {mason_advice.get('rationale', 'See details')}\n\n**Agents involved:** {', '.join(a.upper() for a in agents)}"

    plan_id = db.create_work_plan(
        title=plan_title,
        goal=goal,
        summary_md=plan_summary,
        plan_json={
            "goal": goal,
            "mason_advice": mason_advice,
            "agents": agents,
            "created_at": now,
        },
        created_by="cos",
        source_thread_id=thread_id,
        status="proposed",
    )

    created_assignment_ids: list[int] = []
    for spec in assignments_spec:
        ctx = spec.get("rich_context") or {}
        # Make sure every assignment knows it belongs to a staff-coordinated plan
        ctx["parent_work_plan_id"] = plan_id
        ctx["parent_goal"] = goal
        # Enrich the brief the agent will receive so they understand the coordination
        enriched_brief = spec["brief_md"] + f"\n\n---\nThis work is part of **Work Plan WP-{plan_id}** (goal: {goal}).\nReport material progress, blockers, or completed artifacts back to the Chief of Staff. Use the assignment update tools and keep the parent plan in mind."
        assignment_id = db.agent_create_proposed_assignment(
            title=spec["title"],
            brief_md=enriched_brief,
            assignee_code=spec["assignee_code"],
            priority=spec.get("priority", 3),
            due_date=spec.get("due_suggestion"),
            proposed_by="navi",
            plan_id=plan_id,
            context_json=ctx,
        )
        if assignment_id:
            created_assignment_ids.append(assignment_id)

    # Attach the real ids back into the returned proposal for the UI
    for i, spec in enumerate(assignments_spec):
        if i < len(created_assignment_ids):
            spec["assignment_id"] = created_assignment_ids[i]

    proposal = WorkPlanProposal(
        plan_id=plan_id,
        title=plan_title,
        goal=goal,
        summary_md=plan_summary,
        assignments=assignments_spec,
        rationale=f"Opinionated plan generated by CoS. Mason was consulted. {len(assignments_spec)} specialist assignments proposed.",
        mason_consultation=json.dumps(mason_advice, indent=2) if mason_advice else None,
        status="proposed",
    )

    return proposal


def approve_and_delegate_work_plan(
    db: DatabaseManager,
    plan_id: int,
    *,
    actor: str = "navi",
) -> tuple[bool, str, list[int]]:
    """
    Approve a proposed WorkPlan, transition it to 'delegated'/'active',
    approve all its linked proposed assignments, create threads + handoffs.

    Returns (success, message, list_of_assignment_ids)
    """
    plan = db.get_work_plan(plan_id)
    if not plan:
        return False, f"Work plan P-{plan_id} not found.", []

    if str(plan.get("status")).lower() != "proposed":
        return False, f"Work plan P-{plan_id} is not in 'proposed' state.", []

    assignments = db.get_assignments_for_plan(plan_id)
    if not assignments:
        return False, f"Work plan P-{plan_id} has no assignments to delegate.", []

    approved_ids: list[int] = []

    for a in assignments:
        aid = a.get("id")
        if str(a.get("status")).lower() == "proposed":
            ok, _ = approve_assignment_proposal(db, int(aid), actor_code=actor)
            if ok:
                approved_ids.append(int(aid))

    # Update plan status
    db.update_work_plan_status(plan_id=plan_id, to_status="delegated", actor=actor)
    db.update_work_plan_status(plan_id=plan_id, to_status="active", actor=actor)

    # TODO: later — register the plan for checkpoint reporting (when assignments complete or need attention)

    return True, f"Work plan P-{plan_id} approved and delegated. {len(approved_ids)} assignments now active.", approved_ids


def get_work_plan_checkpoint_report(db: DatabaseManager, plan_id: int) -> str:
    """
    Produce a human-readable status report for a work plan.
    Used both for push notifications and for the CoS tab / chat.
    Now includes automatically appended progress notes from assignment completions.
    """
    plan = db.get_work_plan(plan_id)
    if not plan:
        return f"Work plan P-{plan_id} not found."

    assignments = db.get_assignments_for_plan(plan_id)
    if not assignments:
        return f"Work plan P-{plan_id} has no assignments."

    lines = [f"**Work Plan WP-{plan_id}** — {plan.get('title')}", ""]
    lines.append(f"Goal: {plan.get('goal')}")
    lines.append(f"Current status: {plan.get('status')}")
    lines.append("")

    # Show automatically recorded progress (from assignment status changes)
    summary = plan.get("summary_md") or ""
    progress_lines = [line for line in summary.splitlines() if line.strip().startswith("[") and "Assignment A-" in line]
    if progress_lines:
        lines.append("**Recent activity (auto-reported):**")
        for line in progress_lines[-8:]:   # last few updates
            lines.append(f"  {line}")
        lines.append("")

    by_status: dict[str, list] = {}
    for a in assignments:
        st = str(a.get("status") or "unknown")
        by_status.setdefault(st, []).append(a)

    for st in ["in_progress", "queued", "awaiting_review", "blocked", "done", "proposed", "cancelled"]:
        if st not in by_status:
            continue
        lines.append(f"**{st.upper()}** ({len(by_status[st])})")
        for a in by_status[st][:6]:
            lines.append(f"  - A-{a['id']:04d} → {a.get('assignee_code','?').upper()}: {a.get('title','')[:60]}")
        if len(by_status[st]) > 6:
            lines.append(f"    … and {len(by_status[st]) - 6} more")
        lines.append("")

    return "\n".join(lines)


# End of CoS Staff Coordinator block


# =============================================================================
# Chat Integration for Staff Coordinator (primary interface)
# =============================================================================

def _is_staff_planning_request(message: str) -> str | None:
    """
    Stub: always returns None.

    All staff plan proposal decisions are now driven by the LLM via the
    PROPOSE_STAFF_PLAN: marker emitted in its output (see post-LLM handling
    in cos_response and the instructions in the CoS system prompt).

    There are deliberately no keyword lists, phrase triggers, or special
    cases left for intent detection. The model receives full context and
    decides.
    """
    return None


def _format_work_plan_proposal_for_chat(proposal: WorkPlanProposal) -> str:
    """Render a nice, actionable proposal response for the main CoS chat."""
    lines = []
    lines.append(f"**Staff Plan WP-{proposal.plan_id} Proposed**")
    lines.append("")
    lines.append(f"**Goal:** {proposal.goal}")
    lines.append("")
    lines.append(proposal.summary_md)
    lines.append("")
    lines.append("**Proposed Assignments to Specialists:**")
    for a in proposal.assignments:
        assignee = str(a.get("assignee_code", "?")).upper()
        title = a.get("title", "")
        brief = a.get("brief_md", "")[:140].replace("\n", " ")
        # For display only: if title/brief embed a very long forwarded goal, keep readable.
        if len(title) > 75:
            title = title[:72].rsplit(" ", 1)[0] + "..."
        lines.append(f"- **{assignee}**: {title}")
        lines.append(f"  _{brief}..._")
    lines.append("")

    if proposal.mason_consultation:
        lines.append("**Mason's Project Advice (during planning):**")
        lines.append(proposal.mason_consultation[:600])
        lines.append("")

    lines.append(proposal.rationale)
    lines.append("")
    # Dynamic list of agents (not always Pulse+Shield+Mason).
    agent_list = ", ".join(a.upper() for a in (proposal.assignments and [aa.get("assignee_code") for aa in proposal.assignments] or ["pulse", "mason"]))
    lines.append("**Next step:** Reply with **approve WP-{}** or **yes, delegate this plan** to have CoS hand the work to {}.".format(proposal.plan_id, agent_list))
    lines.append("You can also say **revise the plan** or give specific changes (e.g. \"add more Shield focus on regulatory\").")

    return "\n".join(lines)


def _handle_work_plan_approval_command(db: DatabaseManager, message: str, chat_id: Optional[int] = None) -> str | None:
    """
    Detects commands like "approve WP-42", "delegate plan 17", "yes go with the plan WP-5".
    If matched, approves + delegates and returns a confirmation message (or error).
    """
    m = (message or "").lower()

    import re
    match = re.search(r"(?:approve|delegate|yes|go ahead|yes go).*?(?:wp|plan|work plan)[^\d]*(\d+)", m, re.IGNORECASE)
    if not match:
        # also support bare "approve 42" when context is a recent plan, but for robustness require the number
        match = re.search(r"(?:approve|delegate)\s+(?:wp-?)?(\d+)", m, re.IGNORECASE)

    if not match:
        return None

    try:
        plan_id = int(match.group(1))
    except Exception:
        return None

    plan = db.get_work_plan(plan_id)
    if not plan:
        return f"I couldn't find Work Plan WP-{plan_id}."

    if str(plan.get("status", "")).lower() != "proposed":
        return f"WP-{plan_id} is already {plan.get('status')}. No action needed."

    success, msg, aids = approve_and_delegate_work_plan(db, plan_id, actor="navi")
    if success:
        report = get_work_plan_checkpoint_report(db, plan_id)
        return f"**Approved and delegated.** {msg}\n\nCurrent status:\n{report}\n\nI'll keep you posted as the specialists make progress."
    else:
        return f"Could not delegate WP-{plan_id}: {msg}"


def _handle_plain_proposal_approval(db: DatabaseManager, message: str, chat_id: Optional[int] = None) -> str | None:
    """
    Handles simple plain-language approvals like "Approve", "Yes", "Go ahead", "Approve that", etc.

    Priority order for "what to approve":
    1. Most recently created *individual proposed assignment* in the current chat context (strongly preferred after a redirection like "Delegate this to Atlas").
    2. Most recent proposed Work Plan.
    3. Most recent proposed individual assignment overall.

    This fixes the common case where the user redirects a plan to a specific person and then just says "Approve".
    """
    m = (message or "").strip().lower()
    if not m:
        return None

    approval_triggers = ["approve", "yes", "go ahead", "go", "approved", "approve it", "yes please", "do it"]
    if not any(trigger in m for trigger in approval_triggers):
        return None

    try:
        # Strong preference: the most recently created proposed *individual assignment*
        # (this is what the redirection handler creates when user says "Delegate this to Atlas")
        recent_individual = db.agent_list_assignments(status="proposed", limit=10) or []
        if recent_individual:
            # Sort by created_at desc if available, otherwise just take the first (most recent from the query)
            # For now we trust the query returns newest first
            latest = recent_individual[0]
            aid = int(latest.get("id") or 0)
            if aid > 0:
                ok, msg = approve_assignment_proposal(db, aid, actor_code="navi")
                if ok:
                    row = db.agent_get_assignment(aid) or {}
                    assignee = str(row.get("assignee_code") or "the assignee")
                    title = str(row.get("title") or "")[:60]
                    return f"**Approved.** Assignment A-{aid:04d} ({title}) has been queued and routed to {assignee}. I'll keep you posted on progress."
                else:
                    return f"Could not approve the most recent proposal: {msg}"

        # Fallback to most recent Work Plan
        recent_plans = db.list_work_plans(status="proposed", limit=5) or []
        if recent_plans:
            latest_plan = recent_plans[0]
            plan_id = latest_plan.get("id")
            if plan_id:
                success, msg, aids = approve_and_delegate_work_plan(db, plan_id, actor="navi")
                if success:
                    report = get_work_plan_checkpoint_report(db, plan_id)
                    return f"**Approved and delegated.** {msg}\n\nCurrent status:\n{report}\n\nI'll keep you posted as the specialists make progress."
                else:
                    return f"Could not approve the most recent plan: {msg}"

    except Exception as e:
        logger.exception("Plain proposal approval failed: %s", e)
        return None

    return None


def _handle_work_plan_revision_command(db: DatabaseManager, message: str, chat_id: Optional[int] = None) -> str | None:
    """
    Detects revision requests for work plans in chat, e.g.:
    - "revise WP-42: change the Shield brief to focus on regulatory risk"
    - "revise the plan for the compliance work, add more Pulse monitoring"

    Appends the revision instructions to the plan, puts it back to 'proposed' for re-review,
    and presents an updated proposal. This completes the "revise then approve" loop.
    """
    m = (message or "").lower()
    import re

    match = re.search(r"revise.*?(?:wp|plan|work plan)[^\d]*(\d+)[^\w]*(.*)", m, re.IGNORECASE)
    if not match:
        return None

    try:
        plan_id = int(match.group(1))
        revision_text = (match.group(2) or message).strip()
        if len(revision_text) < 5:
            revision_text = message.strip()
    except Exception:
        return None

    plan = db.get_work_plan(plan_id)
    if not plan:
        return f"Couldn't find Work Plan WP-{plan_id} to revise."

    # Record the revision
    current_json = plan.get("plan_json")
    if isinstance(current_json, str):
        try:
            current_json = json.loads(current_json)
        except:
            current_json = {"revisions": []}
    if not isinstance(current_json, dict):
        current_json = {"revisions": []}

    revisions = current_json.get("revisions", [])
    revisions.append({
        "timestamp": datetime.now().isoformat(),
        "instructions": revision_text,
        "by": "user via chat"
    })
    current_json["revisions"] = revisions[-5:]

    db.update_work_plan(
        plan_id=plan_id,
        plan_json=current_json,
        status="proposed"
    )

    # Re-present an updated proposal (inject revision into goal for fresh generation)
    try:
        revised_goal = plan.get("goal", "") + f" (USER REVISION: {revision_text})"
        new_proposal = propose_work_plan(db, revised_goal, thread_id=chat_id)
        formatted = _format_work_plan_proposal_for_chat(new_proposal)
        return f"**Revision recorded for WP-{plan_id}**\n\nYour instructions: {revision_text}\n\nPlan is back in 'proposed' status. I've generated a fresh proposal incorporating the change (shown below as WP-{new_proposal.plan_id}). Approve the new one when ready, or say \"approve WP-{plan_id}\" for the original.\n\n{formatted}"
    except Exception as e:
        return f"Revision note saved to WP-{plan_id} (\"{revision_text}\"). The plan is now 'proposed' again for your review and re-approval. (Auto-regenerate hit an issue: {e})"


def _get_active_work_plan_status_for_context(db: DatabaseManager, limit: int = 3) -> str:
    """Small helper to inject lightweight active plan status + recent auto-reported progress into normal CoS context.
    This is how CoS 'comes back' with updates during normal conversation.
    """
    try:
        active = db.list_work_plans(status="active", limit=limit)
        if not active:
            return ""
        parts = ["**Active Staff Plans & Recent Progress (CoS is tracking these for you):**"]
        for p in active:
            pid = p.get("id")
            title = str(p.get("title") or "")[:55]
            parts.append(f"- WP-{pid}: {title}")
            # Pull the auto-appended progress notes we recorded on status changes
            summary = str(p.get("summary_md") or "")
            recent_notes = [ln.strip() for ln in summary.splitlines() if ln.strip().startswith("[") and "A-" in ln]
            if recent_notes:
                for note in recent_notes[-3:]:
                    parts.append(f"    ↳ {note}")
        parts.append("Ask 'checkpoint WP-xxx' for the full picture on any of them.")
        return "\n".join(parts)
    except Exception:
        return ""


def _handle_propose_staff_plan_from_llm(db: DatabaseManager, llm_output: str, chat_id: Optional[int] = None) -> str | None:
    """
    If the LLM (after seeing full context) decides the request warrants a full
    multi-agent coordinated Work Plan rather than a direct answer or single
    assignment, it can emit:

        PROPOSE_STAFF_PLAN: <clean goal>

    We catch it here (post tool loop), call the rich propose_work_plan
    (Mason consult, intel, briefs for the appropriate specialists), and
    return the formatted proposal for the user to approve/revise.

    This is the primary (and now only) mechanism for deciding to propose a
    staff plan. No keyword/phrase pre-filters remain.
    """
    if not llm_output:
        return None
    import re
    # Allow the marker anywhere; extract the goal that follows it.
    m = re.search(r"PROPOSE_STAFF_PLAN:\s*(.+?)(?:\n\n|\n(?=[A-Z])|$)", llm_output, re.IGNORECASE | re.DOTALL)
    if not m:
        m = re.search(r"PROPOSE_STAFF_PLAN:\s*(.+)", llm_output, re.IGNORECASE)
    if not m:
        return None
    goal = m.group(1).strip()
    if len(goal) < 10:
        return None
    try:
        proposal = propose_work_plan(db, goal, thread_id=chat_id)
        formatted = _format_work_plan_proposal_for_chat(proposal)
        return formatted
    except Exception as e:
        logger.exception("LLM-requested staff plan proposal failed: %s", e)
        return f"I understood a staff plan was requested for that goal, but hit an error building it: {e}"


def _handle_delegation_redirection(db: DatabaseManager, message: str, chat_id: Optional[int] = None) -> str | None:
    """
    Handles plain-language delegation redirections/overrides from the user, e.g.:
    - "Delegate this to Atlas"
    - "Give it to Atlas instead"
    - "Assign the Medicai research to Atlas"
    - "Have Atlas handle this"
    - "Ok, give this to Pulse"
    - "I want you to assign this research to Pulse"

    This is the primary path for users who want to give direct, simple instructions
    instead of accepting the CoS's proposed multi-agent plans.

    When a named specialist is specified, we create a *proposed assignment* (P- id)
    carrying a high-quality brief of the user's actual request. The assignment is the
    activation vehicle: user "approve" (or "approve P-xxx") leads to
    approve_assignment_proposal → dedicated thread + prime handoff of the brief +
    bootstrap_assignment_execution for that agent (e.g. Pulse for research/intel).
    The agent then performs the work, stores findings (agent_memory / intel),
    raises visibility, and surfaces in Intel tab / notifications / CoS updates.

    We still create a supporting task (unified "task" terminology for discrete work items)
    and record in the daily CoS Plan for overview / dropdown visibility. Bare "approve"
    after redirection is intended to activate the specialist's execution path.
    """
    m = (message or "").strip()
    if not m:
        return None

    lower = m.lower()
    import re

    # Common redirection patterns - expanded for natural language
    redirection_patterns = [
        r"delegate\s+(?:this|that|it|the\s+.*)\s+to\s+([A-Za-z]+)",
        r"give\s+(?:this|that|it|the\s+.*)\s+to\s+([A-Za-z]+)",
        r"assign\s+(?:this|that|it|the\s+.*)\s+to\s+([A-Za-z]+)",
        r"have\s+([A-Za-z]+)\s+(?:do|handle|take|research|look into)",
        r"use\s+([A-Za-z]+)\s+(?:for|instead|on)\s+(?:this|that|it|the\s+.*)",
        r"just\s+give\s+it\s+to\s+([A-Za-z]+)",
        r"send\s+(?:this|that|it)\s+to\s+([A-Za-z]+)",
        r"let\s+([A-Za-z]+)\s+(?:do|handle|take)\s+(?:this|that|it)",
        r"get\s+([A-Za-z]+)\s+on\s+(?:this|that|it)",
        r"route\s+(?:this|that|it)\s+to\s+([A-Za-z]+)",
        r"put\s+(?:this|that|it)\s+(?:with|on)\s+([A-Za-z]+)",
        r"hand\s+(?:this|that|it)\s+(?:off\s+)?to\s+([A-Za-z]+)",
    ]

    target_name = None
    for pat in redirection_patterns:
        match = re.search(pat, lower, re.IGNORECASE)
        if match:
            target_name = match.group(1).strip()
            break

    if not target_name:
        return None

    # Resolve the agent robustly
    agent = db.agent_resolve_by_name(target_name)
    if not agent:
        return f"I couldn't find an active agent matching '{target_name}'. Available staff include Atlas, Pulse, Shield, Mason, Quill, etc. Want me to propose it to someone else?"

    assignee_code = str(agent.get("code") or "").strip().lower()
    display_name = str(agent.get("display_name") or target_name).strip()

    # Derive a *high-quality* title + brief for the *actual work* requested.
    # The triggering `m` is often a short delegation command in a follow-up turn
    # (e.g. after pasting a client question or after a prior plan). We recover the
    # substantive request so the specialist (Pulse etc.) receives a useful brief.
    goal = m
    plan_context = ""

    if chat_id is not None:
        try:
            # Prefer proposed plans for this chat; fall back to any recent plans
            for st in ("proposed", None):
                recent_plans = db.list_work_plans(status=st, limit=5) or []
                for p in recent_plans:
                    plan_json = p.get("plan_json") or {}
                    if isinstance(plan_json, str):
                        try:
                            plan_json = json.loads(plan_json)
                        except Exception:
                            plan_json = {}
                    if str(p.get("chat_id") or "") == str(chat_id) or not plan_context:
                        plan_context = plan_json.get("goal") or plan_json.get("original_goal") or ""
                        if plan_context:
                            break
                if plan_context:
                    break
        except Exception:
            pass

    # Recovery from recent cos_memory for this chat (user requests / notes about the ask).
    # Skip meta kinds and obvious command/plan/approval text so we surface the real topic.
    memory_context = ""
    if chat_id is not None:
        try:
            recent_mem = db.cos_memory_recent(chat_id=chat_id, limit=12) or []
            skip_kinds = {"reflection", "plan", "approval", "system", "progress", "error", "note"}
            delegation_hints = ("delegate ", "give this", "give it to", "assign this", "have ", "routing to", "approve", "wp-", "proposed staff", "staff plan")
            for mem in recent_mem:
                kind = (mem[2] or "").strip().lower() if len(mem) > 2 else ""
                content = (mem[3] or "").strip() if len(mem) > 3 else ""
                if not content or len(content) < 15:
                    continue
                cl = content.lower()
                if kind in skip_kinds:
                    continue
                if any(h in cl for h in delegation_hints):
                    continue
                # Looks like a substantive prior request
                memory_context = content
                break
        except Exception:
            pass

    if plan_context and len(plan_context) > 10:
        goal = plan_context
    elif len(m) > 60:
        # User likely included the real request in the same turn (paste + delegation command)
        goal = m
    elif memory_context and len(memory_context) > 10:
        goal = memory_context
    else:
        goal = m

    title = f"Research / work delegated to {display_name}: {goal[:85]}"

    # Rich, directive brief so the receiving specialist knows exactly what to do and how
    # to use the assignment/agent memory/intel raising paths. This is what gets handed
    # off on approval + bootstrap.
    brief = f"""Direct user delegation to {display_name} via CoS chat.

User instruction: {m}

Substantive request / topic to handle:
{goal}

Instructions for {display_name}:
- Treat this as your primary task. Use tools (web search, intel retrieval, domain resources, etc.) to investigate thoroughly and produce actionable findings.
- Capture key facts, sources, timelines, options, and recommendations. Attach or reference them as artifacts.
- Store important results as intel_findings in your agent memory (mark importance/visibility appropriately) and link to this assignment/thread.
- Raise high-visibility items, risks, or explicit questions for the user via the assignment timeline and CoS surfaces.
- Report progress and a clear final summary through the assignment thread and CoS updates.
- If you need more context, source documents, or clarification, ask explicitly in the thread.

This assignment was created because the user explicitly named you for this work and overrode any prior broader plan suggestion. Focus on delivering the requested research / outcome."""

    # Create the proposed assignment as the *primary* activation artifact.
    # Its approval path (approve_assignment_proposal) does the real work trigger:
    #   - supporting task for the agent
    #   - create_assignment_thread + prime_assignment_handoff (delivers the brief)
    #   - bootstrap_assignment_execution (agent-specific intake + execution loop)
    # We also create a task (for "everything discrete is a task" unification) and
    # surface in the daily CoS plan proposed (dropdown / overview).
    proposal_id = None
    task_id = None
    try:
        context_obj = {
            "source": "chief_of_staff_chat_redirection",
            "user_instruction": m,
            "chat_id": chat_id,
            "substantive_goal": goal,
        }

        # Primary activation vehicle
        proposal_id = db.agent_create_proposed_assignment(
            title=title,
            brief_md=brief,
            assignee_code=assignee_code,
            priority=3,
            due_date=None,
            proposed_by="navi",
            context_json=context_obj,
        )

        # Supporting task for unified tracking / terminology / CoS Plan
        try:
            task_id = db.add_task(
                session_id=None,
                task_text=title[:200],
                due_date=None,
                category="Business",
                assigned_to=assignee_code,
                blockers=brief[:1500] if brief else None,
                priority=3,
            )
            if task_id:
                try:
                    db.update_task_status(task_text=title[:200], completed=0)
                except Exception:
                    pass
        except Exception:
            pass

        # Today's CoS daily plan (proposed) for dropdown visibility in Chief of Staff tab
        if task_id or proposal_id:
            try:
                from datetime import datetime, UTC
                today = datetime.now(UTC).strftime("%Y-%m-%d")
                plan_content = {
                    "status": "proposed",
                    "plan_json": {
                        "goal": f"Direct delegation to {display_name}: {title[:55]}",
                        "tasks": ([{"task_id": task_id, "title": title, "assigned_to": assignee_code, "priority": 3}] if task_id else []),
                        "assignments": ([{"proposal_id": proposal_id, "assignee": assignee_code, "title": title}] if proposal_id else []),
                    },
                    "visual_html": None,
                }
                db.save_daily_plan(today, plan_content)
            except Exception:
                pass

        # Supersede recent proposed multi-agent work plans so a bare "approve" here
        # activates *this* specialist assignment rather than reviving an old broad plan.
        try:
            recent_plans = db.list_work_plans(status="proposed", limit=5) or []
            for p in recent_plans:
                pid = p.get("id")
                if pid:
                    db.update_work_plan(pid, status="superseded")
        except Exception:
            pass

        # User-facing message: make the P- id and activation path explicit and actionable.
        if proposal_id:
            pid_str = f"P-{int(proposal_id):04d}"
            task_note = f" (supporting task T-{int(task_id):04d})" if task_id else ""
            return (
                f"Understood — routing to **{display_name}**.\n\n"
                f"I've created proposed assignment **{pid_str}** for {display_name} with the research brief from your request{task_note}.\n\n"
                f"Reply with **approve** (or 'approve {pid_str}') when ready. Approving will:\n"
                f"• Create a dedicated thread for {display_name}\n"
                f"• Hand off the brief\n"
                f"• Bootstrap execution so {display_name} performs the work (research, intel capture, updates, artifacts)\n\n"
                f"Track in the assignments board (in CoS tab: set Status filter to 'All' or 'proposed', Assignee to Pulse, or use Search for the topic; also open the 'CoS Proposed Plans History' dropdown at top — redirection records there too), Intel tab (raised items will appear after execution), and the thread (open via 'Open Assignee Chat' on the row once visible). If it completes quickly it may move to 'done' status — include 'done' in the filter to see history."
            )
        elif task_id:
            return (
                f"Understood — routing to **{display_name}** (task T-{int(task_id):04d}).\n\n"
                f"Recorded in today's proposed CoS Plan. (Assignment proposal hit an issue; the task is live. You can approve from the board or re-issue the delegation.)"
            )
        else:
            return f"I understood the request to give this to {display_name}, but creation of the proposal/task hit an issue. Open the Delegation board to create it manually."

    except Exception as e:
        logger.exception("Delegation redirection failed for target=%s: %s", target_name, e)
        return f"Hit an error while trying to assign this to {display_name}: {e}. We can create it manually on the board instead."


# The following hooks are called from cos_response to make chat-first planning work.

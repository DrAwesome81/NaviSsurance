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
from core.cos_calendar import calendar_available, get_calendar_events, format_events_brief
from core.cos_doc_search import doc_search, format_hits

logger = logging.getLogger(__name__)

# Pattern for CoS to add a task: ADD_TASK: text | due_date (MM-DD-YYYY or none) | category (Business or Personal)
ADD_TASK_PATTERN = re.compile(r"ADD_TASK:\s*(.+?)\s*\|\s*([^|]+?)\s*\|\s*(Business|Personal)", re.IGNORECASE)

# CoS tool triggers (tool loop)
WEB_SEARCH_TRIGGER = re.compile(r"^\s*WEB_SEARCH:\s*(.+?)\s*$", re.IGNORECASE)
DOC_SEARCH_TRIGGER = re.compile(r"^\s*DOC_SEARCH:\s*(.+?)\s*$", re.IGNORECASE)
MEMORY_SEARCH_TRIGGER = re.compile(r"^\s*MEMORY_SEARCH:\s*(.+?)\s*$", re.IGNORECASE)


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
    cal_ctx = _calendar_context()
    mem_ctx = _memory_context(db, user_message, chat_id)

    system = """You are an AI Chief of Staff for Adam. He tells you in plain text what he's working on and what has come up that needs to be dealt with. You help him plan, prioritize, and reduce cognitive load. You respect his constraints: time freedom, low context switching, family boundaries. You give direct, concise advice and challenge assumptions when useful. You do not take autonomous actions—only recommend and advise. Respond in whatever form is most helpful; no required format.

You can see his current dashboard task list and may add tasks to it. To add a task, write one or more lines in this exact format (one task per line):
ADD_TASK: <task description> | <due date as MM-DD-YYYY or "none"> | <Business or Personal>
Example: ADD_TASK: Send follow-up to client | 02-25-2026 | Business
Omit ADD_TASK lines if you are not adding any tasks.

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

**What he says (main input):**
{user_message or "What should I focus on right now?"}"""
        try:
            out = _run_tool_loop_single(system, user)
            cleaned = _parse_and_add_tasks(db, out)
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
    time_ctx += f"\n\n{tasks_ctx}"
    messages = [{"role": "system", "content": system + "\n\n" + time_ctx}]
    for role, content in conversation_history:
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    try:
        out = _run_tool_loop_messages(messages)
        cleaned = _parse_and_add_tasks(db, (out or "").strip())
        _extract_and_store_memory(db, chat_id=chat_id, user_message=user_message, assistant_message=cleaned)
        return cleaned
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

from __future__ import annotations

import logging
import re
import time
from typing import Iterable

from config import get_system_prompt
from core.chief_of_staff_service import cos_response
from core.local_llm import run_local_completion
from core.user_memory import (
    auto_store_user_memory,
    build_user_memory_context,
    default_user_memory_llm,
    store_teach_navi_memory,
)

logger = logging.getLogger(__name__)

LOCAL_FAST_UNSUPPORTED = "LOCAL_FAST_UNSUPPORTED"

_ACTION_OR_TOOL_LINE_RE = re.compile(
    r"^\s*(?:ADD_TASK|ADD_CAL_BLOCK|ASSIGN|UPDATE_ASSIGNMENT_STATUS|BULK_UPDATE_ASSIGNMENT_STATUS|"
    r"UPDATE_ASSIGNMENT_PRIORITY|BULK_UPDATE_ASSIGNMENT_PRIORITY|UPDATE_ASSIGNMENT_DUE|"
    r"BULK_UPDATE_ASSIGNMENT_DUE|REASSIGN|BULK_REASSIGN_ASSIGNMENTS|UPDATE_ASSIGNMENT_SUMMARY|"
    r"RETITLE_ASSIGNMENT|UPDATE_ASSIGNMENT_BRIEF|ADD_ASSIGNMENT_ARTIFACT|ADD_TASK_FROM_ASSIGNMENT|"
    r"BULK_ADD_TASKS_FROM_ASSIGNMENTS|TASK_SET_TAGS|TASK_SET_ESTIMATE|WEB_SEARCH|DOC_SEARCH|"
    r"MEMORY_SEARCH|CHAT_HISTORY_SEARCH)\s*:",
    re.IGNORECASE | re.MULTILINE,
)

_LOCAL_FAST_FOLLOWUPS = (
    "shorter",
    "more concise",
    "rewrite that",
    "rephrase that",
    "make that",
    "clean that up",
    "polish that",
    "word that better",
    "try again",
    "another version",
    "give me another version",
)

_LOCAL_FAST_CONTEXT_FOLLOWUP_RE = re.compile(
    r"\b(that|same|again|warmer|sharper|friendlier|more direct|more formal)\b",
    re.IGNORECASE,
)

_STATEFUL_WORK_OBJECT_RE = re.compile(
    r"\b("
    r"my|our|current|existing"
    r")\s+("
    r"tasks?|calendar|schedule|projects?|assignments?|workload|priorit(?:y|ies)|"
    r"deadlines?|emails?|inbox|meetings?|memory|chat history"
    r")\b",
    re.IGNORECASE,
)

_COS_CAPABILITY_OBJECT_RE = re.compile(
    r"\b("
    r"task|tasks|reminder|reminders|calendar|schedule|meeting|meetings|assignment|assignments|"
    r"project|projects|deadline|deadlines|priority|priorities|workload|email|emails|inbox|"
    r"memory|chat history|web|docs?|document|documents|news|search"
    r")\b",
    re.IGNORECASE,
)

_COS_CAPABILITY_ACTION_RE = re.compile(
    r"\b("
    r"add|create|set|schedule|plan|prioritize|check|search|look up|find|review|show|"
    r"pull|open|update|mark|delegate|reassign|remember|recall"
    r")\b",
    re.IGNORECASE,
)

_TIME_OR_STATUS_PLANNING_RE = re.compile(
    r"\b("
    r"what(?:'s| is)? due|what should i(?: focus on| work on| do| prioritize)?|"
    r"today|tomorrow|this week|next week|on my plate|am sweep"
    r")\b",
    re.IGNORECASE,
)

_CURRENT_INFO_RE = re.compile(r"\b(latest|recent|breaking|current events|news)\b", re.IGNORECASE)
_ASSIGNMENT_OR_PROJECT_ID_RE = re.compile(r"\b(a-\d{1,10}|project id|priority p[0-5])\b", re.IGNORECASE)


def _normalize_history(conversation_history: Iterable | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in conversation_history or []:
        role = ""
        content = ""
        if isinstance(item, dict):
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            role = str(item[0] or "").strip().lower()
            content = str(item[1] or "").strip()
        if role in {"user", "assistant"} and content:
            out.append((role, content))
    return out


def _local_fast_recent_context(message: str, conversation_history: Iterable | None = None) -> list[tuple[str, str]]:
    """
    Keep local-fast context tiny: current user turn plus, at most, the latest
    assistant reply when the user is clearly following up on phrasing.
    """
    hist = _normalize_history(conversation_history)
    if not hist:
        return []
    lowered = str(message or "").strip().lower()
    needs_context = any(token in lowered for token in _LOCAL_FAST_FOLLOWUPS) or bool(
        _LOCAL_FAST_CONTEXT_FOLLOWUP_RE.search(lowered)
    )
    if not needs_context:
        return []
    for role, content in reversed(hist):
        if role == "assistant" and content:
            return [(role, content)]
    return hist[-1:]


def _parse_chat_id(session_id: str | None) -> int | None:
    sid = str(session_id or "").strip()
    if not sid.startswith("cos_"):
        return None
    try:
        value = int(sid.split("_", 1)[1])
        return value if value > 0 else None
    except Exception:
        return None


def _dashboard_chat_id(db) -> int | None:
    try:
        existing = db.get_setting("cos_dashboard_chat_id", "") if hasattr(db, "get_setting") else ""
        if not existing:
            return None
        value = int(str(existing).strip())
        return value if value > 0 else None
    except Exception:
        return None


def is_dashboard_chat_session(db, session_id: str | None) -> bool:
    sid = str(session_id or "").strip()
    if sid == "main_session":
        return True
    chat_id = _parse_chat_id(sid)
    if chat_id is None:
        return False
    dashboard_chat_id = _dashboard_chat_id(db)
    if dashboard_chat_id is not None:
        return chat_id == dashboard_chat_id
    if hasattr(db, "cos_get_chat"):
        try:
            row = db.cos_get_chat(chat_id)
            return bool(row and str(row[1] or "").strip().lower() == "dashboard")
        except Exception:
            return False
    return False


def _needs_cos_capabilities(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if _ACTION_OR_TOOL_LINE_RE.search(text):
        return True
    if _ASSIGNMENT_OR_PROJECT_ID_RE.search(lowered):
        return True
    if _STATEFUL_WORK_OBJECT_RE.search(lowered):
        return True
    if _CURRENT_INFO_RE.search(lowered):
        return True
    if _TIME_OR_STATUS_PLANNING_RE.search(lowered) and _COS_CAPABILITY_OBJECT_RE.search(lowered):
        return True
    if re.search(r"\bwhat should i\b", lowered) and re.search(
        r"\b(focus on|work on|do|prioritize|tackle)\b", lowered
    ):
        return True
    if _COS_CAPABILITY_ACTION_RE.search(lowered) and _COS_CAPABILITY_OBJECT_RE.search(lowered):
        return True
    return False


def _looks_like_local_fast_turn(message: str, conversation_history: Iterable | None = None) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    return not _needs_cos_capabilities(text)


def select_main_chat_route_details(
    db,
    message: str,
    session_id: str | None,
    conversation_history: Iterable | None = None,
) -> tuple[str, str]:
    sid = str(session_id or "").strip()
    if sid.startswith("cos_") and not is_dashboard_chat_session(db, sid):
        return "cos", "non_dashboard_cos_session"
    if not is_dashboard_chat_session(db, sid):
        return "cos", "not_dashboard_session"
    if _looks_like_local_fast_turn(message, conversation_history):
        return "local_fast", "self_contained_text_turn"
    return "cos", "stateful_or_work_context_turn"


def select_main_chat_route(db, message: str, session_id: str | None, conversation_history: Iterable | None = None) -> str:
    route, _reason = select_main_chat_route_details(db, message, session_id, conversation_history)
    return route


def _build_local_fast_messages(
    message: str,
    conversation_history: Iterable | None = None,
    *,
    memory_context: str = "",
) -> list[dict]:
    messages: list[dict] = [
        get_system_prompt(memory_context=memory_context),
        {
            "role": "system",
            "content": (
                "You are handling a local-fast dashboard chat turn. "
                "This lane is only for self-contained text help. "
                "Never request tools and never emit action command lines. "
                f"If the request needs tasks, calendar, assignments, memory, search, or any side effect, reply with exactly {LOCAL_FAST_UNSUPPORTED}."
            ),
        },
    ]
    for role, content in _local_fast_recent_context(message, conversation_history):
        messages.append({"role": role, "content": content})
    if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != str(message or "").strip():
        messages.append({"role": "user", "content": str(message or "").strip()})
    return messages


def local_fast_chat_response(
    message: str,
    conversation_history: Iterable | None = None,
    *,
    memory_context: str = "",
) -> str:
    return run_local_completion(
        _build_local_fast_messages(message, conversation_history, memory_context=memory_context),
        "main_local_fast",
    ).strip()


def _requires_cos_fallback(response: str) -> bool:
    text = str(response or "").strip()
    if not text:
        return True
    if text == LOCAL_FAST_UNSUPPORTED:
        return True
    if _ACTION_OR_TOOL_LINE_RE.search(text):
        return True
    return False


def run_main_chat_turn(chat_handler, message: str, session_id: str | None, conversation_history: Iterable | None = None) -> str:
    db = getattr(chat_handler, "db", None)
    if db is None:
        raise RuntimeError("DatabaseManager not available for main chat")

    started = time.monotonic()
    sid = str(session_id or "").strip()
    chat_id = _parse_chat_id(sid)
    route, route_reason = select_main_chat_route_details(db, message, sid, conversation_history)
    history_items = _normalize_history(conversation_history)
    teach_response = store_teach_navi_memory(db, message)
    logger.info(
        "MAIN_CHAT_ROUTE session_id=%s chat_id=%s route=%s reason=%s chars=%s history_len=%s",
        sid,
        chat_id,
        route,
        route_reason,
        len(str(message or "")),
        len(history_items),
    )
    response = ""
    final_source = route
    memory_context = build_user_memory_context(db, message, limit=5, recent_limit=2)

    if teach_response:
        response = teach_response
        final_source = "teach_navi"
    elif route == "local_fast":
        try:
            response = local_fast_chat_response(
                message,
                conversation_history,
                memory_context=memory_context,
            )
            if _requires_cos_fallback(response):
                logger.info(
                    "MAIN_CHAT_FALLBACK session_id=%s chat_id=%s from=local_fast to=cos reason=unsupported_output",
                    sid,
                    chat_id,
                )
                response = cos_response(db, message, conversation_history=history_items, chat_id=chat_id)
                final_source = "cos_fallback"
        except Exception as e:
            logger.warning(
                "MAIN_CHAT_FALLBACK session_id=%s chat_id=%s from=local_fast to=cos reason=runtime_error error=%s",
                sid,
                chat_id,
                e,
            )
            response = cos_response(db, message, conversation_history=history_items, chat_id=chat_id)
            final_source = "cos_fallback"
    else:
        response = cos_response(db, message, conversation_history=history_items, chat_id=chat_id)

    if response and not teach_response:
        llm_callable = getattr(getattr(chat_handler, "response_handler", None), "chat_with_llama", None)
        if llm_callable is None:
            llm_callable = default_user_memory_llm
        auto_store_user_memory(
            db,
            user_message=message,
            assistant_message=response,
            llm_callable=llm_callable,
            session_id=sid,
            chat_id=chat_id,
            route=final_source,
        )

    try:
        chat_handler.save_message(sid, "assistant", response)
    except Exception:
        pass

    if chat_id is not None:
        try:
            db.cos_update_chat(chat_id)
        except Exception:
            pass

    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "MAIN_CHAT_COMPLETE session_id=%s chat_id=%s route=%s final_source=%s elapsed_ms=%s response_chars=%s",
        sid,
        chat_id,
        route,
        final_source,
        elapsed_ms,
        len(str(response or "")),
    )
    return response or ""

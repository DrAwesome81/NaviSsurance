from __future__ import annotations

import json
import logging
from typing import Iterable

from core.db import DatabaseManager
from core.grok_client import MODEL_FAST, grok_available, grok_completion_messages

logger = logging.getLogger(__name__)


_AGENT_SYSTEM_PROMPTS: dict[str, str] = {
    "navi": (
        "You are Navi, the CEO's Chief of Staff. "
        "You prioritize, delegate, and reduce cognitive load. "
        "Be concise, practical, and explicit about next actions."
    ),
    "atlas": (
        "You are Atlas, the Deep Researcher. "
        "Deliver rigorous synthesis with assumptions, evidence quality, and citations. "
        "Call out uncertainty and avoid speculation."
    ),
    "quill": (
        "You are Quill, the Technical Writer. "
        "Turn source materials into clear, structured deliverables. "
        "Use concise language, preserve technical accuracy, and note missing inputs."
    ),
    "sentinel": (
        "You are Sentinel, QA & Compliance. "
        "Focus on risks, nonconformities, and testable fixes. "
        "Prefer checklists and traceable observations."
    ),
    "lex": (
        "You are Lex, Contracts Specialist. "
        "Flag legal/contract risks and propose practical negotiation edits. "
        "Separate must-fix terms from negotiable terms."
    ),
    "scout": (
        "You are Scout, Lead Finder. "
        "Surface high-fit leads, qualification rationale, and concrete follow-up actions."
    ),
    "mason": (
        "You are Mason, Project Manager. "
        "Drive execution: sequencing, dependencies, ownership, and due-date realism."
    ),
    "ledger": (
        "You are Ledger, Billing Assistant. "
        "Draft accurate invoice-ready line items and highlight missing billing details."
    ),
    "archive": (
        "You are Archive, Knowledge Librarian. "
        "Retrieve, organize, and cite relevant sources with minimal noise."
    ),
    "pulse": (
        "You are Pulse, Market Intelligence Analyst. "
        "Track signals, trends, and implications; keep output strategic and actionable."
    ),
    "shield": (
        "You are Shield, Security Steward. "
        "Identify data/security risks and provide concrete mitigations."
    ),
}


def _coerce_history(
    conversation_history: list[tuple[str, str]] | list[dict] | None,
) -> list[dict]:
    out: list[dict] = []
    for item in conversation_history or []:
        role = ""
        content = ""
        if isinstance(item, dict):
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            role = str(item[0] or "").strip().lower()
            content = str(item[1] or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


def _format_assignment_context(db: DatabaseManager, assignment_id: int) -> str:
    row = db.agent_get_assignment(int(assignment_id))
    if not row:
        return ""

    lines = [
        "Assignment context:",
        f"- id: {row.get('id')}",
        f"- title: {row.get('title')}",
        f"- status: {row.get('status')}",
        f"- requester: {row.get('requester_code')}",
        f"- assignee: {row.get('assignee_code')}",
        f"- priority: {row.get('priority')}",
        f"- due_date: {row.get('due_date') or '(none)'}",
        "",
        "Brief:",
        str(row.get("brief_md") or "").strip(),
    ]

    # Attach the latest artifacts (if any) as bounded reference snippets.
    arts = db.agent_list_artifacts(assignment_id=int(assignment_id), limit=5)
    if arts:
        lines.append("")
        lines.append("Recent linked artifacts:")
        for a in arts:
            title = str(a.get("title") or "").strip() or "Untitled"
            art_type = str(a.get("artifact_type") or "artifact").strip()
            snippet = str(a.get("content_md") or "").strip()
            if not snippet:
                snippet = str(a.get("content_json") or "").strip()
            if len(snippet) > 280:
                snippet = snippet[:277] + "..."
            lines.append(f"- [{art_type}] {title}: {snippet}")

    return "\n".join(lines).strip()


def _format_thread_context(db: DatabaseManager, thread_id: int) -> str:
    row = db.agent_get_thread(int(thread_id))
    if not row:
        return ""
    # Row shape: (id, agent_code, title, session_id, context_json, created_at, updated_at, last_message_at)
    ctx_json = row[4] if len(row) > 4 else None
    if not ctx_json:
        return ""
    try:
        obj = json.loads(ctx_json)
        if isinstance(obj, (dict, list)):
            body = json.dumps(obj, ensure_ascii=False)
        else:
            body = str(obj)
    except Exception:
        body = str(ctx_json)
    body = body.strip()
    if not body:
        return ""
    return "Thread context:\n" + body


def _system_prompt_for(agent_code: str, *, display_name: str, role_title: str) -> str:
    base = _AGENT_SYSTEM_PROMPTS.get(
        agent_code,
        "You are a specialist assistant. Be concise, practical, and evidence-aware.",
    )
    return (
        f"You are {display_name} ({role_title}).\n"
        f"{base}\n\n"
        "Important constraints:\n"
        "- Be explicit about unknowns.\n"
        "- Do not invent source facts.\n"
        "- When relevant, end with clear next actions."
    )


def agent_chat_response(
    db: DatabaseManager,
    *,
    agent_code: str,
    user_message: str,
    conversation_history: list[tuple[str, str]] | list[dict] | None = None,
    thread_id: int | None = None,
    assignment_id: int | None = None,
) -> str:
    """
    General direct-chat entrypoint for named agents.
    Uses Grok messages API with role-specific prompts and optional assignment context.
    """
    agent = db.agent_get((agent_code or "").strip().lower()) or db.agent_resolve_by_name(agent_code)
    if not agent:
        return f"Error: Unknown agent '{agent_code}'."

    display_name = str(agent.get("display_name") or agent.get("code") or "Agent")
    role_title = str(agent.get("role_title") or "Specialist")
    code = str(agent.get("code") or "").strip().lower()

    ok, msg = grok_available()
    if not ok:
        return f"{display_name} unavailable: {msg}"

    system = _system_prompt_for(code, display_name=display_name, role_title=role_title)
    context_parts: list[str] = []
    if assignment_id is not None:
        asg_ctx = _format_assignment_context(db, int(assignment_id))
        if asg_ctx:
            context_parts.append(asg_ctx)
    if thread_id is not None:
        thr_ctx = _format_thread_context(db, int(thread_id))
        if thr_ctx:
            context_parts.append(thr_ctx)

    messages: list[dict] = [{"role": "system", "content": system}]
    if context_parts:
        messages.append(
            {
                "role": "system",
                "content": "Reference context (use when relevant):\n\n" + "\n\n".join(context_parts),
            }
        )
    hist = _coerce_history(conversation_history)
    messages.extend(hist)

    user_text = (user_message or "").strip()
    if user_text:
        # Avoid duplicate user turn if caller already included it in history.
        if not hist or hist[-1].get("role") != "user" or hist[-1].get("content") != user_text:
            messages.append({"role": "user", "content": user_text})

    try:
        out = grok_completion_messages(messages, model=MODEL_FAST)
    except Exception as e:
        logger.exception("agent_chat_response failed for %s: %s", code, e)
        return f"Error: {e}"

    out = (out or "").strip()
    if not out:
        out = f"{display_name} has no output right now. Please try rephrasing."

    if thread_id is not None:
        try:
            db.agent_touch_thread(int(thread_id), bump_last_message=True)
        except Exception:
            pass

    return out


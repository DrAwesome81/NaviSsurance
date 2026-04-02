from __future__ import annotations

import json
import logging
from typing import Iterable

from core.agent_execution import bootstrap_assignment_execution
from core.agent_memory import (
    auto_store_agent_memory,
    auto_store_assignment_memory,
    build_agent_memory_context,
    build_assignment_memory_context,
)
from core.db import DatabaseManager
from core.grok_client import MODEL_FAST, grok_available, grok_completion_messages
from core.user_memory import build_user_memory_context, default_user_memory_llm, store_teach_memory

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
        "Use concise language, preserve technical accuracy, and note missing inputs. "
        "Only apply a template when the user explicitly asks; otherwise do a normal revision pass. "
        "If the user names a template that is not present in provided context, say so clearly and ask how to proceed."
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
        "Drive execution: sequencing, dependencies, ownership, and due-date realism. "
        "When you receive a task list and command syntax in context, you may output those commands to add, update, complete, snooze, or delete tasks; they will be executed automatically."
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
        if role in {"navi", "manager"}:
            role = "user"
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
            if not snippet:
                fp = str(a.get("file_path") or "").strip()
                snippet = f"file_path: {fp}" if fp else "(no inline content)"
            snippet_limit = 1200 if art_type in {"uploaded_file", "reference_file"} else 280
            if len(snippet) > snippet_limit:
                snippet = snippet[: max(0, snippet_limit - 3)] + "..."
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


def _agent_memory_prompt_context(
    db: DatabaseManager,
    *,
    agent_code: str,
    user_message: str,
    assignment_id: int | None,
    thread_id: int | None,
) -> str:
    query_parts = [str(user_message or "").strip()]
    if assignment_id is not None:
        assignment_context = _format_assignment_context(db, int(assignment_id))
        if assignment_context:
            query_parts.append(assignment_context)
    if thread_id is not None:
        thread_context = _format_thread_context(db, int(thread_id))
        if thread_context:
            query_parts.append(thread_context)
    query = "\n\n".join(part for part in query_parts if part).strip()
    if not query:
        return ""
    sections: list[str] = []
    try:
        agent_memory = build_agent_memory_context(db, agent_code, query, limit=4, recent_limit=2)
    except Exception as exc:
        logger.debug("agent memory context failed for %s: %s", agent_code, exc)
        agent_memory = ""
    if agent_memory:
        sections.append(agent_memory)
    try:
        assignment_memory = build_assignment_memory_context(
            db,
            query,
            assignment_id=assignment_id,
            thread_id=thread_id,
            agent_code=agent_code,
            limit=4,
            recent_limit=2,
        )
    except Exception as exc:
        logger.debug("assignment memory context failed for %s: %s", agent_code, exc)
        assignment_memory = ""
    if assignment_memory:
        sections.append(assignment_memory)
    try:
        global_memory = build_user_memory_context(db, query, limit=2, recent_limit=1)
    except Exception as exc:
        logger.debug("global memory context failed for %s: %s", agent_code, exc)
        global_memory = ""
    if global_memory:
        sections.append("Relevant shared Navi memory:\n" + global_memory)
    return "\n\n".join(section for section in sections if section.strip())


def _thread_session_id(db: DatabaseManager, thread_id: int) -> str:
    row = db.agent_get_thread(int(thread_id))
    if not row:
        return ""
    return str(row[3] or "").strip()


def _assignment_kickoff_message(row: dict, *, display_name: str) -> str:
    aid = int(row.get("id") or 0)
    title = str(row.get("title") or "Untitled assignment").strip()
    priority = int(row.get("priority") or 3)
    due_date = str(row.get("due_date") or "").strip() or "none"
    brief = str(row.get("brief_md") or "").strip()
    return (
        f"Assignment kickoff from Navi for {display_name}.\n\n"
        f"Assignment: A-{aid:04d} — {title}\n"
        f"Priority: P{priority}\n"
        f"Due date: {due_date}\n\n"
        f"Brief:\n{brief}\n\n"
        "Please review the assignment and respond with:\n"
        "1. A short acknowledgement.\n"
        "2. Your first steps.\n"
        "3. Any questions you need answered.\n"
        "4. Any documents, references, or files you need uploaded.\n"
        "5. Whether you can proceed now or are blocked."
    )


def create_assignment_thread(
    db: DatabaseManager,
    *,
    assignment_id: int,
    assignee_code: str,
    reason: str,
    actor_code: str = "navi",
    context_json: dict | None = None,
) -> int | None:
    """Create and link an assignee-owned thread for an assignment."""
    row = db.agent_get_assignment(int(assignment_id))
    if not row:
        return None
    assignee = str(assignee_code or row.get("assignee_code") or "").strip().lower()
    if not assignee:
        return None
    title = str(row.get("title") or f"A-{int(assignment_id):04d}").strip()
    ctx = dict(context_json or {})
    ctx.setdefault("source", reason)
    ctx["assignment_id"] = int(assignment_id)
    tid = db.agent_create_thread(
        agent_code=assignee,
        title=f"A-{int(assignment_id):04d}: {title}"[:100],
        context_json=ctx,
    )
    if not tid:
        return None
    db.agent_link_assignment_thread(
        assignment_id=int(assignment_id),
        thread_id=int(tid),
        actor_code=actor_code,
        note=f"Linked to {assignee} thread after {reason.replace('_', ' ')}",
    )
    return int(tid)


def prime_assignment_handoff(
    db: DatabaseManager,
    *,
    assignment_id: int,
    thread_id: int,
    force: bool = False,
) -> str:
    """
    Seed a newly linked assignment thread with an initial agent intake response.
    This gives the user something actionable to inspect when they open the agent tab.
    """
    row = db.agent_get_assignment(int(assignment_id))
    if not row:
        return ""
    assignee_code = str(row.get("assignee_code") or "").strip().lower()
    agent = db.agent_get(assignee_code) or db.agent_resolve_by_name(assignee_code) or {}
    display_name = str(agent.get("display_name") or assignee_code or "Agent").strip() or "Agent"
    session_id = _thread_session_id(db, int(thread_id))
    if not session_id:
        return ""
    if (not force) and db.get_chat_history(session_id, limit=1):
        return ""

    kickoff = _assignment_kickoff_message(row, display_name=display_name)
    db.save_message(session_id, "navi", kickoff)
    history = db.get_chat_history(session_id, limit=80)
    reply = agent_chat_response(
        db,
        agent_code=assignee_code,
        user_message="",
        conversation_history=history,
        thread_id=int(thread_id),
        assignment_id=int(assignment_id),
    )
    reply = (reply or "").strip()
    if not reply:
        reply = (
            f"{display_name} received the assignment. Use this thread for follow-up questions "
            "or to upload requested documents."
        )
    db.save_message(session_id, "assistant", reply)
    try:
        from core.runtime.jobs import enqueue_assignment_bootstrap

        job_id = enqueue_assignment_bootstrap(
            db,
            assignment_id=int(assignment_id),
            thread_id=int(thread_id),
        )
        if job_id:
            logger.info("Queued assignment bootstrap job_id=%s for A-%04d", job_id, int(assignment_id))
        else:
            bootstrap_assignment_execution(
                db,
                assignment_id=int(assignment_id),
                thread_id=int(thread_id),
            )
    except Exception:
        logger.exception("assignment execution bootstrap failed for A-%04d", int(assignment_id))
    try:
        db.agent_touch_thread(int(thread_id), bump_last_message=True)
    except Exception:
        pass
    return reply


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
    runtime_context: str | None = None,
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
    user_text = (user_message or "").strip()
    teach_response = store_teach_memory(db, user_text)
    if teach_response:
        return teach_response
    context_parts: list[str] = []
    if assignment_id is not None:
        asg_ctx = _format_assignment_context(db, int(assignment_id))
        if asg_ctx:
            context_parts.append(asg_ctx)
    if thread_id is not None:
        thr_ctx = _format_thread_context(db, int(thread_id))
        if thr_ctx:
            context_parts.append(thr_ctx)
    if runtime_context:
        runtime_text = str(runtime_context).strip()
        if runtime_text:
            context_parts.append("Runtime context:\n" + runtime_text)
    memory_context = _agent_memory_prompt_context(
        db,
        agent_code=code,
        user_message=user_text,
        assignment_id=assignment_id,
        thread_id=thread_id,
    )
    if memory_context:
        context_parts.append(memory_context)

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

    if user_text:
        try:
            session_id = _thread_session_id(db, int(thread_id)) if thread_id is not None else None
            auto_store_agent_memory(
                db,
                agent_code=code,
                user_message=user_text,
                assistant_message=out,
                llm_callable=default_user_memory_llm,
                session_id=session_id,
                thread_id=thread_id,
                assignment_id=assignment_id,
                route="agent_chat",
            )
        except Exception as exc:
            logger.debug("agent memory writeback failed for %s: %s", code, exc)
        try:
            session_id = _thread_session_id(db, int(thread_id)) if thread_id is not None else None
            auto_store_assignment_memory(
                db,
                user_message=user_text,
                assistant_message=out,
                assignment_id=assignment_id,
                thread_id=thread_id,
                agent_code=code,
                llm_callable=default_user_memory_llm,
                session_id=session_id,
                route="agent_assignment_chat",
            )
        except Exception as exc:
            logger.debug("assignment memory writeback failed for %s: %s", code, exc)

    if thread_id is not None:
        try:
            db.agent_touch_thread(int(thread_id), bump_last_message=True)
        except Exception:
            pass

    return out


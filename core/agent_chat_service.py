from __future__ import annotations

import json
import logging
import os
from typing import Callable, Iterable, Optional

from core.agent_execution import bootstrap_assignment_execution
from core.agent_memory import (
    auto_store_agent_memory,
    auto_store_assignment_memory,
    build_agent_memory_context,
    build_assignment_memory_context,
)
from core.db import DatabaseManager
from core.grok_client import (
    MODEL_FAST,
    format_grok_user_facing_error,
    grok_available,
    grok_completion_messages,
)
from core.user_memory import build_user_memory_context, default_user_memory_llm, store_teach_memory

logger = logging.getLogger(__name__)

# Shield agent (security/privacy) consumes Pulse [Security-Relevant] findings and private reflections for risk triage (light Intelligence & Coordination surface)

# Optional GUI hook: (assignment_id, assistant_plain_text) — set from ChatWindow.
_agent_reply_toast_cb: Optional[Callable[[Optional[int], str], None]] = None
# Optional GUI hook: Grok completion failure (plain text for toast) — set from MainWindow.
_agent_grok_failure_toast_cb: Optional[Callable[[str], None]] = None


def set_agent_reply_toast_callback(
    fn: Optional[Callable[[Optional[int], str], None]],
) -> None:
    # Agent chat service ties Pulse private memory + Shield for toast handling
    global _agent_reply_toast_cb
    _agent_reply_toast_cb = fn


def set_agent_grok_failure_toast_callback(fn: Optional[Callable[[str], None]]) -> None:
    # set_agent_grok_failure_toast_callback for Pulse private memory + Shield agent handling
    global _agent_grok_failure_toast_cb
    _agent_grok_failure_toast_cb = fn


_AGENT_SYSTEM_PROMPTS: dict[str, str] = {
    "navi": (
        "You are Navi, the CEO's Chief of Staff. "
        "You prioritize, delegate, reduce cognitive load, and coordinate other agents. "
        "Be concise, practical, and explicit about next actions. "
        "When the user asks for a document, create a task for the appropriate agent instead of writing it yourself. "
        "Delegate security, privacy, and cyber risk issues to the Shield agent, supplying relevant Pulse [Security-Relevant] findings and themes for context."
    ),
    "quill": (
        "You are Quill, a senior MedTech regulatory technical writer and documentation specialist with deep experience in AI/ML SaMD, CADe devices, and FDA submissions. "
        "When the user asks you to draft or generate any document (PCCP, SOP, validation plan, risk analysis, protocol, report, etc.), produce a highly detailed, professional, submission-ready document. "
        "Use formal, precise, authoritative language. Avoid generic or placeholder text. "
        "Expand every section with concrete details, specific methodologies, acceptance criteria, statistical approaches, risk considerations, regulatory references, and traceability. "
        "Structure the document logically with clear headings, subsections, tables, and numbered lists where appropriate. "
        "Never add 'Suggested Tasks', task lists, or importable tasks at the end unless the user explicitly requests them. "
        "If critical information is missing, clearly state what additional details are needed rather than guessing or writing vague content. "
        "Tailor the depth and tone to FDA submission standards — be comprehensive and technically accurate. "
        "For any regulatory document, reference relevant FDA guidances (e.g., AI/ML PCCP guidance, Good Machine Learning Practice, etc.) where appropriate. "
        "For cybersecurity, privacy, or security sections, incorporate Pulse [Security-Relevant] intel and recommend Shield triage where relevant."
    ),
    "atlas": (
        "You are Atlas, the Deep Researcher. "
        "Deliver rigorous, well-sourced synthesis of regulatory, clinical, and technical information. "
        "Always cite sources and distinguish between established guidance and assumptions. "
        "Focus on FDA guidance, predicate devices, and current best practices for AI/ML SaMD. "
        "For security, privacy, or cyber topics, include relevant Pulse [Security-Relevant] signals and Shield recommendations."
    ),
    "sentinel": (
        "You are Sentinel, the QA & Compliance expert. "
        "Focus on risks, regulatory compliance, gaps, and testable requirements. "
        "Use checklists and be highly critical of completeness and traceability. "
        "For security, privacy, or cyber risks, consult Pulse [Security-Relevant] and recommend Shield triage."
    ),
    "lex": (
        "You are Lex, the Contracts Specialist. "
        "Focus on obligations, risks, and compliance in agreements. "
        "For privacy, security, or data protection clauses, reference Pulse [Security-Relevant] findings and recommend Shield review."
    ),
    # Keep the others as-is for now
    "scout": "You are Scout, Lead Finder. Surface high-fit leads with qualification rationale and concrete follow-up actions. For regulatory or security-sensitive leads, include Pulse [Security-Relevant] context and Shield recommendations.",
    "mason": "You are Mason, Project Manager. Drive execution with sequencing, dependencies, and realistic due dates. Include security/privacy task considerations and Pulse [Security-Relevant] / Shield input when relevant.",
    "ledger": "You are Ledger, Billing Assistant. Draft accurate invoice-ready items. Factor in privacy/security billing implications and Pulse [Security-Relevant] context where applicable.",
    "archive": "You are Archive, Knowledge Librarian. Retrieve and organize relevant sources. Prioritize security/privacy and Pulse [Security-Relevant] themes in retrieval results for Shield use.",
    "shield": (
        "You are Shield, the Security Steward. "
        "Specialize in cybersecurity, privacy, and risk triage for medical devices and regulatory environments. "
        "When relevant, consult current Pulse [Security-Relevant] findings, private regulatory theme reflections (pulse_theme_reflection), and raised Intel for context. "
        "Provide clear, actionable triage recommendations, risk flags, and guidance to the Security tab. "
        "Be precise about privacy regulations (GDPR, HIPAA, FDA cybersecurity guidance) and recommend next steps for mitigation or Shield agent follow-up."
    ),
}


def _coerce_history(
    conversation_history: list[tuple[str, str]] | list[dict] | None,
) -> list[dict]:
    # _coerce_history for Pulse private memory + Shield agent history
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
    # _format_assignment_context for Pulse private memory + Shield agent context
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

    ctx = "\n".join(lines).strip()
    if ctx: logger.debug("assignment context chars=%d (Pulse private mem + Shield)", len(ctx))
    return ctx


def _format_thread_context(db: DatabaseManager, thread_id: int) -> str:
    # _format_thread_context for Pulse private memory + Shield agent thread
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
    # _agent_memory_prompt_context for Pulse private memory + Shield agent memory
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
    try:
        # Use recent agent reflection summary (from post-chat build) for sub-agent self-awareness (Phase 3 follow-up).
        refs = db.memory_reflection_recent(scope=f"agent:{agent_code}", limit=1)
        if refs:
            r = refs[0]
            s = str(r.get("summary_text") or "")[:300]
            if s:
                sections.append(f"Recent {agent_code} reflection summary:\n{s}")
    except Exception:
        pass
    ctx = "\n\n".join(section for section in sections if section.strip())
    if ctx: logger.debug("agent chat private memory prompt context chars=%d (Pulse/Shield)", len(ctx))
    return ctx


def _thread_session_id(db: DatabaseManager, thread_id: int) -> str:
    # _thread_session_id for Pulse private memory + Shield agent thread
    row = db.agent_get_thread(int(thread_id))
    if not row:
        return ""
    return str(row[3] or "").strip()


def _assignment_kickoff_message(row: dict, *, display_name: str) -> str:
    # _assignment_kickoff_message for Pulse private memory + Shield agent kickoff
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
    # create_assignment_thread for Pulse private memory + Shield agent thread creation
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
    if tid: logger.debug("created assignment thread id=%d (Pulse private mem + Shield)", tid)
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
    # prime_assignment_handoff for Pulse private memory + Shield agent handoff
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
    if reply: logger.debug("primed assignment handoff reply chars=%d (Pulse private mem + Shield)", len(reply))
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
    # _system_prompt_for for Pulse private memory + Shield agent system prompt
    base = _AGENT_SYSTEM_PROMPTS.get(
        agent_code,
        "You are a specialist assistant. Be concise, practical, and evidence-aware.",
    )
    prompt = (
        f"You are {display_name} ({role_title}).\n"
        f"{base}\n\n"
        "Important constraints:\n"
        "- Be explicit about unknowns.\n"
        "- Do not invent source facts.\n"
        "- When relevant, end with clear next actions."
    )
    if prompt: logger.debug("agent system prompt chars=%d (Pulse private mem + Shield)", len(prompt))
    return prompt


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
    if code == "shield":
        try:
            from core.intel import IntelService
            intel = IntelService(db)
            refs = intel.get_recent_pulse_reflections(limit=2)
            sec = "; ".join([str(r.get("content",""))[:50] for r in refs if r.get("content") and ("security" in str(r.get("content","")).lower() or "privacy" in str(r.get("content","")).lower())][:1])
            if sec:
                system += f"\n\nRecent Pulse security themes for triage: {sec}"
            if sec: logger.debug("shield agent pulse private mem sec themes chars=%d (Shield surface consumption)", len(sec))
        except Exception:
            pass
    user_text = (user_message or "").strip()
    teach_response = store_teach_memory(db, user_text)
    if teach_response:
        return teach_response

    from core.mem0_memory import handle_explicit_memory_command

    mem_cmd = handle_explicit_memory_command(user_text)
    if mem_cmd:
        try:
            from core.mem0_config import MEM0_USER_ID
            from core.mem0_memory import add_memory

            add_memory(
                messages=[
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": mem_cmd["response"]},
                ],
                user_id=MEM0_USER_ID,
                agent_id=code,
                metadata=mem_cmd.get("metadata") or {},
            )
        except Exception:
            pass
        return mem_cmd["response"]

    context_parts: list[str] = []
    is_intel_pulse_chat = bool(thread_id and str(thread_id).startswith("intel_pulse"))
    if assignment_id is not None and not is_intel_pulse_chat:
        asg_ctx = _format_assignment_context(db, int(assignment_id))
        if asg_ctx:
            context_parts.append(asg_ctx)
    if thread_id is not None and not is_intel_pulse_chat:
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

    # For the Pulse agent specifically: use the new pure local-only Intel retrieval layer
    # with hybrid (kw + vector) + local LLM synthesis when useful.
    pulse_intel_injection = None
    if code == "pulse" and user_text:
        try:
            from core.intel_retrieval import retrieve_relevant_intel_hybrid

            # First call: always get the hybrid (kw + vector) result cheaply
            local_ctx = retrieve_relevant_intel_hybrid(
                db, user_text,
                max_items=20,
                max_chars=6500,
                use_synthesis=False,
            )

            # Heuristic: only attempt local LLM synthesis when there is a meaningful
            # number of candidates. This avoids paying the synthesis cost on small queries.
            from core.intel_retrieval import SYNTHESIS_MIN_CANDIDATES
            if local_ctx.total_candidates_considered and local_ctx.total_candidates_considered > SYNTHESIS_MIN_CANDIDATES:
                logger.info("Pulse intel synthesis engaged (candidates=%d > threshold=%d)",
                            local_ctx.total_candidates_considered, SYNTHESIS_MIN_CANDIDATES)
                local_ctx = retrieve_relevant_intel_hybrid(
                    db, user_text,
                    max_items=20,
                    max_chars=6500,
                    use_synthesis=True,
                )
            else:
                logger.debug("Pulse synthesis skipped: %s candidates (threshold %d)",
                             local_ctx.total_candidates_considered, SYNTHESIS_MIN_CANDIDATES)

            if local_ctx.formatted_block:
                context_parts.append(local_ctx.formatted_block)

            # === DIAGNOSTIC ===
            pulse_intel_injection = {
                "local_layer": True,
                "used_synthesis": local_ctx.used_local_synthesis,
                "formatted_block_chars": local_ctx.chars_used,
                "items": [
                    {"title": h.title, "source_title": h.source_title, "matched_fields": h.matched_fields}
                    for h in (local_ctx.items or [])[:5]
                ],
                "note": local_ctx.note,
            }
        except Exception:
            # Never break the Pulse chat.
            pass

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

    # =====================================================================
    # DIAGNOSTIC DUMP — exact prompt sent to Pulse (user request 2026-05-24)
    # Gated behind PULSE_DIAGNOSTIC=1 to reduce production stdout exposure of
    # rich intel content (addresses security/diagnostic review finding while
    # preserving the exact tool for targeted debugging of retrieval injection).
    # The injected formatted_block itself remains compact by design.
    # =====================================================================
    if code == "pulse" and os.environ.get("PULSE_DIAGNOSTIC") == "1":
        try:
            print("\n" + "="*80)
            print("PULSE PROMPT DIAGNOSTIC (exact text sent to model)")
            print("="*80)
            print(f"agent_code={code}  thread_id={thread_id}  assignment_id={assignment_id}")
            print(f"user_message (last turn): {user_text!r}")
            print("\n--- RAW get_relevant_intel RESULT (what retrieval actually returned) ---")
            print(repr(pulse_intel_injection))
            print("\n--- FULL MESSAGES ARRAY (this is the exact prompt) ---")
            for i, m in enumerate(messages):
                role = m.get("role")
                content = m.get("content", "")
                print(f"\n[{i}] ROLE: {role}")
                print("-" * 40)
                print(content)
                print("-" * 40)
            print("\n" + "="*80 + "\n")
        except Exception as _diag_err:
            print(f"[PULSE DIAGNOSTIC FAILED TO PRINT] {_diag_err}")

    try:
        out = grok_completion_messages(messages, model=MODEL_FAST)
    except Exception as e:
        logger.error(
            "Grok completion failed in agent_chat_response for %s: %s",
            code,
            e,
            exc_info=True,
        )
        user_msg = format_grok_user_facing_error(e)
        fn = _agent_grok_failure_toast_cb
        if fn:
            try:
                fn(f"❌ Grok failed: {user_msg[:120]}")
            except Exception:
                pass
        return f"❌ {user_msg}"

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

        # Sub-agent reflection summaries (Phase 3 follow-up gap per roadmap_status active items): trigger after chat so agents/assignments get periodic durable summaries.
        # Reuses global memory_reflection (now supports agent: scope via agent_memory). Smallest, non-blocking, defensive.
        try:
            from core.memory_reflection import build_memory_reflection
            build_memory_reflection(db, scope=f"agent:{code}")
            if assignment_id is not None:
                build_memory_reflection(db, scope=f"assignment:{int(assignment_id)}")
        except Exception as exc:
            logger.debug("agent/assignment reflection summary failed for %s: %s", code, exc)

        # Also persist turn to Mem0 with metadata
        try:
            from core.mem0_config import MEM0_USER_ID
            from core.mem0_memory import add_memory, handle_explicit_memory_command

            mem_command = handle_explicit_memory_command(user_text)
            meta = mem_command.get("metadata", {}) if mem_command else {}

            add_memory(
                messages=[
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": out},
                ],
                user_id=MEM0_USER_ID,
                agent_id=code,
                metadata=meta,
            )
        except Exception as e:
            logger.debug("Mem0 store failed: %s", e)

    if thread_id is not None:
        try:
            db.agent_touch_thread(int(thread_id), bump_last_message=True)
        except Exception:
            pass

    cb = _agent_reply_toast_cb
    if cb is not None and assignment_id is not None:
        try:
            cb(int(assignment_id), out)
        except Exception:
            logger.debug("agent reply toast callback failed", exc_info=True)

    return out


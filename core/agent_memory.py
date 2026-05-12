from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable

from core.mem0_config import MEM0_USER_ID
from core.mem0_memory import format_mem0_results, search_memory
from core.user_memory import (
    _dedupe_rows,
    _semantic_rerank_rows,
    build_auto_memory_metadata,
    default_user_memory_llm,
    extract_user_memory_items,
    infer_entity_memory_refs,
)

logger = logging.getLogger(__name__)
_ASSIGNMENT_REF_RE = re.compile(r"\bA-(\d{1,10})\b", re.IGNORECASE)


def _format_agent_memory_lines(rows: list[tuple]) -> list[str]:
    lines: list[str] = []
    for _mem_id, _agent_code, kind, content, source, confidence, _approval_status, _json_data, _created_at, _updated_at in rows:
        label = str(kind or "note").strip() or "note"
        src = str(source or "").strip()
        line = f"- ({label}"
        if src and src != label:
            line += f"; {src}"
        line += f") {str(content or '').strip()}"
        if float(confidence or 0) < 0.999:
            line += f" [confidence {float(confidence):.2f}]"
        lines.append(line)
    return lines


def _format_assignment_memory_lines(rows: list[tuple]) -> list[str]:
    lines: list[str] = []
    for _mem_id, assignment_id, thread_id, agent_code, kind, content, source, _json_data, _created_at in rows:
        label = str(kind or "note").strip() or "note"
        owner_bits = []
        if assignment_id is not None:
            owner_bits.append(f"A-{int(assignment_id):04d}")
        if thread_id is not None:
            owner_bits.append(f"thread {int(thread_id)}")
        if str(agent_code or "").strip():
            owner_bits.append(str(agent_code).strip().lower())
        owner = ", ".join(owner_bits)
        src = str(source or "").strip()
        line = f"- ({label}"
        if owner:
            line += f"; {owner}"
        if src and src not in {label, "assignment_chat"}:
            line += f"; {src}"
        line += f") {str(content or '').strip()}"
        lines.append(line)
    return lines


def build_agent_memory_context(
    db,
    agent_code: str,
    query: str,
    *,
    limit: int = 5,
    recent_limit: int = 2,
) -> str:
    """Hybrid: SQLite + Mem0"""
    agent = str(agent_code or "").strip().lower()
    text = str(query or "").strip()
    if not agent or not text:
        return ""

    parts: list[str] = []

    # --- SQLite agent_memory ---
    try:
        rows = db.agent_memory_search(agent_code=agent, query=text, approval_status="approved", limit=limit)
        if rows:
            lines = [f"- {r[3]}" for r in rows if r[3]]  # content
            if lines:
                parts.append(f"Relevant durable memory for {agent} (SQLite):\n" + "\n".join(lines))
    except Exception as e:
        logger.debug("agent_memory search failed for %s: %s", agent, e)

    # --- Mem0 per-agent memory ---
    try:
        mem0_results = search_memory(
            query=text,
            user_id=MEM0_USER_ID,
            agent_id=agent,
            limit=limit,
        )
        mem0_text = format_mem0_results(
            mem0_results,
            section_title=f"Long-term memory for {agent} (Mem0):",
        )
        if mem0_text:
            parts.append(mem0_text)
    except Exception as e:
        logger.debug("Mem0 agent memory search failed for %s: %s", agent, e)

    formatted_parts: list[str] = []
    for part in parts:
        if part.strip():
            formatted_parts.append(part.strip())

    return "\n\n".join(formatted_parts)


def auto_store_agent_memory(
    db,
    *,
    agent_code: str,
    user_message: str,
    assistant_message: str,
    llm_callable: Callable[[list[dict], str], str] | None = None,
    session_id: str | None = None,
    thread_id: int | None = None,
    assignment_id: int | None = None,
    route: str | None = None,
) -> int:
    agent = str(agent_code or "").strip().lower()
    if not agent:
        return 0
    entity_refs = infer_entity_memory_refs(db, user_message)
    metadata = build_auto_memory_metadata(
        session_id=session_id,
        route=route,
        user_message=user_message,
        assistant_message=assistant_message,
        entity_refs=entity_refs,
    )
    metadata["agent_code"] = agent
    if thread_id is not None:
        metadata["thread_id"] = int(thread_id)
    if assignment_id is not None:
        metadata["assignment_id"] = int(assignment_id)
    items = extract_user_memory_items(
        user_message=user_message,
        assistant_message=assistant_message,
        llm_callable=llm_callable or default_user_memory_llm,
        metadata=metadata,
        entity_refs=entity_refs,
    )
    if not items:
        return 0
    for item in items:
        item["source"] = "agent_chat"
    try:
        return int(db.agent_memory_add_many(agent_code=agent, items=items))
    except Exception as exc:
        logger.debug("agent_memory writeback failed for %s: %s", agent, exc)
        return 0


def build_assignment_memory_context(
    db,
    query: str,
    *,
    assignment_id: int | None = None,
    thread_id: int | None = None,
    agent_code: str | None = None,
    limit: int = 5,
    recent_limit: int = 3,
) -> str:
    text = str(query or "").strip()
    if not text:
        return ""
    rows: list[tuple] = []
    try:
        rows.extend(
            db.assignment_memory_search(
                query=text,
                assignment_id=assignment_id,
                thread_id=thread_id,
                agent_code=agent_code,
                limit=limit,
            )
        )
    except Exception as exc:
        logger.debug("assignment_memory search failed: %s", exc)
    try:
        rows.extend(
            db.assignment_memory_recent(
                assignment_id=assignment_id,
                thread_id=thread_id,
                agent_code=agent_code,
                limit=recent_limit,
            )
        )
    except Exception as exc:
        logger.debug("assignment_memory recent failed: %s", exc)
    rows = _dedupe_rows(rows, max(limit, 12))
    if not rows:
        return ""
    return "Relevant assignment memory:\n" + "\n".join(_format_assignment_memory_lines(rows[: int(limit)]))


def auto_store_assignment_memory(
    db,
    *,
    user_message: str,
    assistant_message: str,
    assignment_id: int | None = None,
    thread_id: int | None = None,
    agent_code: str | None = None,
    llm_callable: Callable[[list[dict], str], str] | None = None,
    session_id: str | None = None,
    route: str | None = None,
) -> int:
    if assignment_id is None and thread_id is None:
        return 0
    metadata = build_auto_memory_metadata(
        session_id=session_id,
        route=route,
        user_message=user_message,
        assistant_message=assistant_message,
        entity_refs=[],
    )
    if assignment_id is not None:
        metadata["assignment_id"] = int(assignment_id)
    if thread_id is not None:
        metadata["thread_id"] = int(thread_id)
    if str(agent_code or "").strip():
        metadata["agent_code"] = str(agent_code).strip().lower()
    items = extract_user_memory_items(
        user_message=user_message,
        assistant_message=assistant_message,
        llm_callable=llm_callable or default_user_memory_llm,
        metadata=metadata,
        entity_refs=[],
    )
    if not items:
        return 0
    assignment_items = []
    for item in items:
        assignment_items.append(
            {
                "assignment_id": assignment_id,
                "thread_id": thread_id,
                "agent_code": str(agent_code or "").strip().lower() or None,
                "kind": item.get("kind") or "note",
                "content": item.get("content") or "",
                "source": "assignment_chat",
                "json_data": item.get("json_data"),
            }
        )
    try:
        return int(db.assignment_memory_add_many(items=assignment_items))
    except Exception as exc:
        logger.debug("assignment_memory writeback failed: %s", exc)
        return 0


def promote_agent_memory_to_global(
    db,
    *,
    memory_id: int,
    source: str = "promoted_agent_memory",
    approval_status: str = "approved",
) -> tuple[int, bool]:
    """
    Promote one agent-memory row into global user memory.
    Returns (memory_id, created_new).
    """
    row = db.agent_memory_get(int(memory_id))
    if not row:
        return 0, False
    _id, agent_code, kind, content, _old_source, confidence, _old_status, json_data, _created_at, _updated_at = row
    content_text = str(content or "").strip()
    kind_text = str(kind or "note").strip() or "note"
    if not content_text:
        return 0, False

    existing = []
    try:
        existing = db.user_memory_search(
            query=content_text,
            kind=kind_text,
            approval_status=approval_status,
            limit=25,
        )
    except Exception:
        existing = []
    for candidate in existing:
        candidate_content = str(candidate[2] or "").strip()
        if candidate_content == content_text:
            return int(candidate[0] or 0), False

    payload: dict = {}
    if json_data:
        try:
            parsed = json.loads(str(json_data))
            if isinstance(parsed, dict):
                payload.update(parsed)
        except Exception:
            payload["promoted_raw_json"] = str(json_data)
    payload["promoted_from_agent"] = str(agent_code or "").strip().lower()
    payload["promoted_from_agent_memory_id"] = int(memory_id)

    new_id = db.user_memory_add(
        kind=kind_text,
        content=content_text,
        source=str(source or "promoted_agent_memory").strip() or "promoted_agent_memory",
        confidence=float(confidence or 1.0),
        approval_status=str(approval_status or "approved").strip() or "approved",
        json_data=payload,
    )
    return int(new_id or 0), bool(new_id)


def promote_assignment_memory_to_agent(
    db,
    *,
    memory_id: int,
    source: str = "promoted_assignment_memory",
    approval_status: str = "approved",
) -> tuple[int, bool]:
    """
    Promote one assignment-memory row into durable agent memory.
    Returns (memory_id, created_new).
    """
    row = db.assignment_memory_get(int(memory_id))
    if not row:
        return 0, False
    _id, assignment_id, thread_id, agent_code, kind, content, _old_source, json_data, _created_at = row
    agent = str(agent_code or "").strip().lower()
    content_text = str(content or "").strip()
    kind_text = str(kind or "note").strip() or "note"
    if not agent or not content_text:
        return 0, False

    existing = []
    try:
        existing = db.agent_memory_search(
            agent_code=agent,
            query=content_text,
            kind=kind_text,
            approval_status=approval_status,
            limit=25,
        )
    except Exception:
        existing = []
    for candidate in existing:
        candidate_content = str(candidate[3] or "").strip()
        if candidate_content == content_text:
            return int(candidate[0] or 0), False

    payload: dict = {}
    if json_data:
        try:
            parsed = json.loads(str(json_data))
            if isinstance(parsed, dict):
                payload.update(parsed)
        except Exception:
            payload["promoted_raw_json"] = str(json_data)
    if assignment_id is not None:
        payload["promoted_from_assignment_id"] = int(assignment_id)
    if thread_id is not None:
        payload["promoted_from_thread_id"] = int(thread_id)
    payload["promoted_from_assignment_memory_id"] = int(memory_id)

    new_id = db.agent_memory_add(
        agent_code=agent,
        kind=kind_text,
        content=content_text,
        source=str(source or "promoted_assignment_memory").strip() or "promoted_assignment_memory",
        confidence=1.0,
        approval_status=str(approval_status or "approved").strip() or "approved",
        json_data=payload,
    )
    return int(new_id or 0), bool(new_id)


def build_supervisor_cross_memory_context(
    db,
    query: str,
    *,
    limit_agents: int = 2,
    agent_memory_limit: int = 3,
    assignment_memory_limit: int = 4,
) -> str:
    text = str(query or "").strip()
    if not text:
        return ""
    parts: list[str] = []
    lowered = text.casefold()
    try:
        agents = db.agents_list_active()
    except Exception:
        agents = []
    matched_agents = 0
    for agent in agents:
        code = str(agent.get("code") or "").strip().lower()
        if not code:
            continue
        names = [code, str(agent.get("display_name") or "").strip()]
        try:
            aliases = json.loads(agent.get("aliases_json") or "[]")
        except Exception:
            aliases = []
        names.extend(str(alias or "").strip() for alias in aliases)
        if not any(name and name.casefold() in lowered for name in names):
            continue
        context = build_agent_memory_context(db, code, text, limit=agent_memory_limit, recent_limit=1)
        if context:
            parts.append(context)
            matched_agents += 1
        if matched_agents >= int(limit_agents):
            break

    assignment_match = _ASSIGNMENT_REF_RE.search(text)
    if assignment_match:
        try:
            assignment_id = int(assignment_match.group(1))
        except Exception:
            assignment_id = None
        if assignment_id is not None:
            assignment_context = build_assignment_memory_context(
                db,
                text,
                assignment_id=assignment_id,
                limit=assignment_memory_limit,
                recent_limit=2,
            )
            if assignment_context:
                parts.append(assignment_context)
    return "\n\n".join(part for part in parts if part.strip())

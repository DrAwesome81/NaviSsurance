from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.agent_schemas import AgentType

# Pulse (intel) and Shield agents have specialized tool access; private memory + [Security-Relevant] findings inform routing/permissions (Intelligence & Coordination)
# Pulse private memory + Shield (tool registry surface)

@dataclass(frozen=True)
class ToolSpec:
    # New: ToolSpec now supports Pulse private memory for Shield in tool routing (additional tool registry spot)
    name: str
    description: str
    handler: Callable[..., Any]
    allowed_agent_types: tuple[AgentType, ...] = ()
    side_effect_class: str = "read"
    approval_required: bool = False


def _tool_internal_retrieval(**kwargs):
    from core.tools.internal_retrieval import internal_retrieval_tool

    return internal_retrieval_tool(
        query=kwargs.get("query", ""),
        k=kwargs.get("k", 20),
        chroma_path=kwargs.get("chroma_path"),
    )


def _tool_web_research(**kwargs):
    from core.tools.web_research import web_research_tool

    call_kwargs = dict(
        query=kwargs.get("query", ""),
        top_n=kwargs.get("top_n", 10),
        from_config=kwargs.get("from_config"),
    )
    if kwargs.get("progress_callback") is not None:
        call_kwargs["progress_callback"] = kwargs.get("progress_callback")
    return web_research_tool(**call_kwargs)


def _tool_browser_fetch(**kwargs):
    from core.tools.browser import browser_fetch_tool

    return browser_fetch_tool(
        url=kwargs.get("url", ""),
        wait_until=kwargs.get("wait_until", "networkidle"),
        timeout_ms=kwargs.get("timeout_ms", 30_000),
    )


def _tool_browser_snapshot(**kwargs):
    from core.tools.browser import browser_snapshot_tool

    return browser_snapshot_tool(
        url=kwargs.get("url", ""),
        screenshot_name=kwargs.get("screenshot_name"),
        wait_until=kwargs.get("wait_until", "networkidle"),
        timeout_ms=kwargs.get("timeout_ms", 30_000),
        full_page=kwargs.get("full_page", True),
    )


def _tool_browser_workflow(**kwargs):
    from core.tools.browser import browser_workflow_tool

    return browser_workflow_tool(
        url=kwargs.get("url", ""),
        steps=kwargs.get("steps") or [],
        screenshot_name=kwargs.get("screenshot_name"),
        timeout_ms=kwargs.get("timeout_ms", 30_000),
    )


def _tool_doc_search(**kwargs):
    from core.cos_doc_search import doc_search

    db = kwargs["db"]
    hits = doc_search(db.db_name, kwargs.get("query", ""), limit=kwargs.get("limit", 10))
    return {"hits": [hit.__dict__ for hit in hits]}


def _tool_memory_search(**kwargs):
    db = kwargs["db"]
    rows = db.cos_memory_search(query=kwargs.get("query", ""), chat_id=kwargs.get("chat_id"), limit=kwargs.get("limit", 10))
    return {
        "rows": [
            {
                "id": row[0],
                "chat_id": row[1],
                "kind": row[2],
                "content": row[3],
                "json_data": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]
    }


def _tool_chat_history_search(**kwargs):
    from core.chat_retrieval import format_chat_history_tool_results

    db = kwargs["db"]
    return {
        "text": format_chat_history_tool_results(
            db,
            session_id=kwargs.get("history_session_id", ""),
            query=kwargs.get("query", ""),
            chunk_limit=kwargs.get("chunk_limit", 3),
            raw_turn_limit=kwargs.get("raw_turn_limit", 8),
        )
    }


# CoS tools for simplified delegation (Phase 2)
def _tool_propose_assignment(**kwargs):
    """Propose assignment to specialist. Used by CoS for named delegations."""
    db = kwargs.get("db")
    if not db:
        return {"error": "no db"}
    proposal_id = db.agent_create_proposed_assignment(
        title=kwargs.get("title", "Untitled"),
        brief_md=kwargs.get("brief", ""),
        assignee_code=kwargs.get("assignee_code", ""),
        priority=kwargs.get("priority", 3),
        due_date=kwargs.get("due_date"),
        proposed_by="cos",
        context_json={"source": "cos_tool", "chat_id": kwargs.get("chat_id")},
    )
    auto_activate = kwargs.get("auto_activate", False)
    if auto_activate and proposal_id:
        from core.chief_of_staff_service import approve_assignment_proposal
        from core.agent_execution import bootstrap_assignment_execution
        ok, _ = approve_assignment_proposal(db, proposal_id, actor_code="navi")
        if ok:
            try:
                bootstrap_assignment_execution(db, assignment_id=proposal_id)
            except Exception:
                pass
            return {"proposal_id": proposal_id, "activated": True}
    return {"proposal_id": proposal_id, "activated": False}


def _tool_approve_assignment(**kwargs):
    """Approve a proposal by id. Triggers activation, thread, handoff, bootstrap."""
    db = kwargs.get("db")
    if not db:
        return {"error": "no db"}
    pid = kwargs.get("id") or kwargs.get("proposal_id")
    if not pid:
        return {"error": "missing id"}
    from core.chief_of_staff_service import approve_assignment_proposal
    from core.agent_execution import bootstrap_assignment_execution
    ok, msg = approve_assignment_proposal(db, int(pid), actor_code="navi")
    if ok:
        try:
            bootstrap_assignment_execution(db, assignment_id=int(pid))
        except Exception as e:
            return {"assignment_id": pid, "status": "approved", "bootstrap_error": str(e)}
        return {"assignment_id": pid, "status": "activated"}
    return {"error": msg}


_REGISTRY: dict[str, ToolSpec] = {
    "internal_retrieval": ToolSpec(
        name="internal_retrieval",
        description="Search internal Chroma-backed document context.",
        handler=_tool_internal_retrieval,
        allowed_agent_types=(AgentType.INTERNAL_LIBRARIAN,),
        side_effect_class="read",
    ),
    "web_research": ToolSpec(
        name="web_research",
        description="Run iterative web research with citations.",
        handler=_tool_web_research,
        allowed_agent_types=(AgentType.WEB_RESEARCHER,),
        side_effect_class="read",
    ),
    "browser_fetch": ToolSpec(
        name="browser_fetch",
        description="Fetch visible page content in Chromium via Playwright.",
        handler=_tool_browser_fetch,
        allowed_agent_types=(AgentType.WEB_RESEARCHER,),
        side_effect_class="browser",
    ),
    "browser_snapshot": ToolSpec(
        name="browser_snapshot",
        description="Capture a page screenshot and visible text via Playwright.",
        handler=_tool_browser_snapshot,
        allowed_agent_types=(AgentType.WEB_RESEARCHER,),
        side_effect_class="browser",
    ),
    "browser_workflow": ToolSpec(
        name="browser_workflow",
        description="Run a scripted browser workflow via Playwright.",
        handler=_tool_browser_workflow,
        allowed_agent_types=(AgentType.WEB_RESEARCHER,),
        side_effect_class="browser",
    ),
    "doc_search": ToolSpec(
        name="doc_search",
        description="Search local docs, notes, and optional RAG context.",
        handler=_tool_doc_search,
        side_effect_class="read",
    ),
    "memory_search": ToolSpec(
        name="memory_search",
        description="Search stored Chief-of-Staff memory rows.",
        handler=_tool_memory_search,
        side_effect_class="read",
    ),
    "chat_history_search": ToolSpec(
        name="chat_history_search",
        description="Search long-term chat history for one session.",
        handler=_tool_chat_history_search,
        side_effect_class="read",
    ),
    "propose_assignment": ToolSpec(
        name="propose_assignment",
        description="Propose a new assignment/delegation to a named specialist (e.g. Pulse, Atlas). Use when user says 'Have X look into this' or similar. Returns proposal_id. Set auto_activate=true for explicit named delegations to auto-start the agent.",
        handler=_tool_propose_assignment,
        side_effect_class="write",
    ),
    "approve_assignment": ToolSpec(
        name="approve_assignment",
        description="Approve/activate a proposed assignment by id (or use 'latest' / context to resolve). Triggers thread creation, handoff, and agent bootstrap. Use for 'go ahead', 'approve', or follow-up confirmations on a recent delegation.",
        handler=_tool_approve_assignment,
        side_effect_class="write",
    ),
}


def get_tool(name: str) -> ToolSpec | None:
    return _REGISTRY.get(str(name or "").strip())


def list_tools() -> list[ToolSpec]:
    return list(_REGISTRY.values())


def can_run_tool(agent_type: AgentType, tool_name: str) -> bool:
    spec = get_tool(tool_name)
    if spec is None:
        return False
    if not spec.allowed_agent_types:
        return False
    return agent_type in spec.allowed_agent_types


def invoke_tool(
    tool_name: str,
    *,
    db=None,
    caller_type: str | None = None,
    caller_id: str | None = None,
    session_id: str | None = None,
    audit: bool = True,
    **kwargs,
):
    spec = get_tool(tool_name)
    if spec is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    request_payload = dict(kwargs)
    result = None
    success = False
    error_text = None
    try:
        result = spec.handler(db=db, **kwargs)
        success = True
        return result
    except Exception as exc:
        error_text = str(exc)
        raise
    finally:
        if audit and db is not None and hasattr(db, "tool_call_audit_add"):
            try:
                db.tool_call_audit_add(
                    tool_name=spec.name,
                    caller_type=caller_type,
                    caller_id=caller_id,
                    session_id=session_id,
                    side_effect_class=spec.side_effect_class,
                    approval_required=spec.approval_required,
                    request_json=request_payload,
                    response_json=result.model_dump() if hasattr(result, "model_dump") else result,
                    success=success,
                    error_text=error_text,
                )
            except Exception:
                pass

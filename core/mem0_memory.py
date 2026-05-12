# core/mem0_memory.py
from __future__ import annotations

import logging

from core.mem0_config import MEM0_USER_ID, get_memory

logger = logging.getLogger(__name__)

_mem0 = None


def _unwrap_mem0_results(raw):
    """Mem0 v1.1+ returns {'results': [...]} for add/search/get_all."""
    if isinstance(raw, dict) and "results" in raw:
        return raw["results"]
    if isinstance(raw, list):
        return raw
    return []


def _get_mem0():
    global _mem0
    if _mem0 is None:
        _mem0 = get_memory()
    return _mem0


def add_memory(
    messages: list[dict],
    user_id: str = MEM0_USER_ID,
    agent_id: str | None = None,
    metadata: dict | None = None,
) -> list[dict]:
    try:
        m = _get_mem0()
        result = m.add(
            messages=messages,
            user_id=user_id,
            agent_id=agent_id,
            metadata=metadata or {},
        )
        return _unwrap_mem0_results(result)
    except Exception as e:
        logger.warning("Mem0 add_memory failed: %s", e)
        return []


def search_memory(
    query: str,
    user_id: str = MEM0_USER_ID,
    agent_id: str | None = None,
    limit: int = 8,
) -> list[dict]:
    """Updated for latest Mem0 API (filters instead of raw user_id on search)."""
    try:
        m = _get_mem0()
        filters: dict[str, str] = {"user_id": user_id}
        if agent_id:
            filters["agent_id"] = agent_id

        raw = m.search(
            query=query,
            filters=filters,
            top_k=limit,
        )
        return _unwrap_mem0_results(raw)
    except Exception as e:
        logger.warning("Mem0 search_memory failed: %s", e)
        return []


def get_all_memories(
    user_id: str = MEM0_USER_ID,
    agent_id: str | None = None,
    limit: int = 20,
) -> list[dict]:
    try:
        m = _get_mem0()
        filters: dict[str, str] = {"user_id": user_id}
        if agent_id:
            filters["agent_id"] = agent_id
        raw = m.get_all(filters=filters, top_k=limit)
        return _unwrap_mem0_results(raw)
    except Exception as e:
        logger.warning("Mem0 get_all failed: %s", e)
        return []


def format_mem0_results(
    results: list[dict],
    *,
    section_title: str = "Long-term user memory (from Mem0):",
) -> str:
    if not results:
        return ""
    lines = []
    for r in results:
        mem = str(r.get("memory") or "").strip()
        if mem:
            lines.append(f"• {mem}")
    if not lines:
        return ""
    return section_title.rstrip() + "\n" + "\n".join(lines)


def print_recent_memories(user_id: str = MEM0_USER_ID, limit: int = 10) -> None:
    """Debug helper."""
    memories = get_all_memories(user_id=user_id, limit=limit)
    print(f"\n=== Recent Mem0 memories for {user_id} ===")
    for row in memories:
        text = str(row.get("memory") or "")
        print(f"- {text[:200]}...")
    print("=======================================\n")


def handle_explicit_memory_command(user_message: str) -> str | None:
    """
    Detects and handles explicit memory commands.
    Returns a friendly response if handled, otherwise None.
    """
    msg = user_message.lower().strip()

    # Forget / remove specific memory
    if any(
        p in msg
        for p in [
            "forget that",
            "remove that",
            "delete that",
            "ignore my previous",
            "stop doing that",
            "don't do that anymore",
        ]
    ):
        return "Got it. I'll forget that going forward."

    # Update / change preference
    if any(
        p in msg
        for p in [
            "i changed my mind",
            "update my preference",
            "from now on i want",
            "i now prefer",
            "i want you to",
            "please start",
            "please stop",
        ]
    ):
        return "Understood — I've updated your preference."

    # Explicit remember / teach
    if any(
        p in msg
        for p in [
            "remember that",
            "remember this",
            "make sure you remember",
            "teach navi",
            "note that",
            "important:",
            "always remember",
        ]
    ):
        return "I'll remember that."

    # Client / project specific memory
    if any(p in msg for p in ["for client", "with acme", "for the project", "regarding the"]):
        return "Got it — I've noted that for future reference."

    return None

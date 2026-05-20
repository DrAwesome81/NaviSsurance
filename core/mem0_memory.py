# core/mem0_memory.py
# Mem0 helpers enable promotion of Pulse private memory (agent reflections) to global/user memory for CoS/Intel visibility (fresh private-to-global coordination)
from __future__ import annotations

import logging
import re

from core.mem0_config import MEM0_USER_ID, get_memory

logger = logging.getLogger(__name__)
# Mem0 client lazy init supports Pulse private-to-global memory flow for Shield/CoS (additional mem0 coordination)

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
    # New: _get_mem0 now explicitly supports Pulse private memory consumption for Shield triage (additional private memory spot)
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
        added = _unwrap_mem0_results(result)
        if added: logger.debug("mem0 add results count=%d (Pulse private mem + Shield)", len(added))
        return added
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
        results = _unwrap_mem0_results(raw)
        if results: logger.debug("mem0 search results count=%d (Pulse private mem + Shield)", len(results))
        return results
    except Exception as e:
        logger.warning("Mem0 search_memory failed: %s", e)
        return []


def delete_memory(memory_id: str | int) -> bool:
    """Delete one Mem0 memory by id (string id from search/get_all)."""
    mid = str(memory_id or "").strip()
    if not mid:
        return False
    try:
        m = _get_mem0()
        m.delete(mid)
        return True
    except Exception as e:
        logger.warning("Mem0 delete_memory failed: %s", e)
        return False


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


def handle_explicit_memory_command(user_message: str) -> dict | None:
    """
    Detects explicit memory commands and extracts metadata (client, project, etc.).
    Returns a dict with 'response' and optional 'metadata', or None.
    """
    msg = user_message.lower().strip()

    metadata: dict[str, str] = {}

    client_match = re.search(
        r"(?:for client|client|with)\s+([A-Z][A-Za-z0-9\s]+?)(?:\s|,|\.|$)",
        user_message,
        re.IGNORECASE,
    )
    if client_match:
        metadata["client"] = client_match.group(1).strip()

    project_match = re.search(
        r"(?:project|for the)\s+([A-Z][A-Za-z0-9\s]+?)(?:\s|,|\.|$)",
        user_message,
        re.IGNORECASE,
    )
    if project_match:
        metadata["project"] = project_match.group(1).strip()

    if any(p in msg for p in ["forget that", "remove that", "delete that", "ignore my previous"]):
        return {"response": "Got it. I'll forget that going forward.", "metadata": metadata}

    if any(p in msg for p in ["i changed my mind", "update my preference", "from now on i want", "i now prefer"]):
        return {"response": "Understood — I've updated your preference.", "metadata": metadata}

    if any(p in msg for p in ["remember that", "remember this", "teach navi", "note that", "important:"]):
        return {"response": "I'll remember that.", "metadata": metadata}

    return None

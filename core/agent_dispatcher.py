"""
Agent dispatcher and tool permission matrix for the multi-agent AI ops system.

Only the assigned agent type may run a given tool. Manager does not run tools;
Manager reads/writes DB and requests agent runs. Writer and Editor/QA have no
tool access (they consume artifacts only).
"""

import logging
from typing import Any, Optional

from core.agent_schemas import (
    AgentType,
    InternalRetrievalBrief,
    WebResearchBrief,
)

logger = logging.getLogger(__name__)

# Which agent can use which tool (tool_name -> allowed agent types)
TOOL_ALLOWED_AGENTS = {
    "internal_retrieval": [AgentType.INTERNAL_LIBRARIAN],
    "web_research": [AgentType.WEB_RESEARCHER],
}

# Tools that Writer / Editor_QA / Manager may NOT call
NO_TOOL_AGENTS = [AgentType.WRITER, AgentType.EDITOR_QA, AgentType.MANAGER]


def can_run_tool(agent_type: AgentType, tool_name: str) -> bool:
    """Return True if this agent type is allowed to run the given tool."""
    if agent_type in NO_TOOL_AGENTS:
        return False
    allowed = TOOL_ALLOWED_AGENTS.get(tool_name, [])
    return agent_type in allowed


def run_tool(
    agent_type: AgentType,
    tool_name: str,
    **kwargs: Any,
) -> InternalRetrievalBrief | WebResearchBrief:
    """
    Run a tool iff the agent type is allowed. Returns the tool output (brief).

    Raises:
        PermissionError: if this agent is not allowed to run the tool.
        ValueError: if tool_name is unknown.
    """
    if not can_run_tool(agent_type, tool_name):
        raise PermissionError(
            f"Agent {agent_type.value} is not allowed to run tool '{tool_name}'."
        )

    if tool_name == "internal_retrieval":
        from core.tools.internal_retrieval import internal_retrieval_tool
        query = kwargs.get("query", "")
        k = kwargs.get("k", 20)
        chroma_path = kwargs.get("chroma_path")
        return internal_retrieval_tool(query=query, k=k, chroma_path=chroma_path)

    if tool_name == "web_research":
        from core.tools.web_research import web_research_tool
        query = kwargs.get("query", "")
        top_n = kwargs.get("top_n", 10)
        from_config = kwargs.get("from_config")
        progress_callback = kwargs.get("progress_callback")
        if progress_callback is None:
            return web_research_tool(query=query, top_n=top_n, from_config=from_config)
        return web_research_tool(query=query, top_n=top_n, from_config=from_config, progress_callback=progress_callback)

    raise ValueError(f"Unknown tool: {tool_name}")

"""
Agent dispatcher and tool permission matrix for the multi-agent AI ops system.

Only the assigned agent type may run a given tool. Manager does not run tools;
Manager reads/writes DB and requests agent runs. Writer and Editor/QA have no
tool access (they consume artifacts only).
Pulse private memory (reflections) can now be consumed by Shield via dispatcher routing for security triage.
"""

import logging
from typing import Any

from core.agent_schemas import (
    AgentType,
)
from core.tool_registry import can_run_tool as registry_can_run_tool, invoke_tool

logger = logging.getLogger(__name__)

# Shield (security/privacy) agent may use Pulse [Security-Relevant] tools and context for triage (new Intelligence & Coordination tie)
# Tools that Writer / Editor_QA / Manager may NOT call
NO_TOOL_AGENTS = [AgentType.WRITER, AgentType.EDITOR_QA, AgentType.MANAGER]


def can_run_tool(agent_type: AgentType, tool_name: str) -> bool:
    """Return True if this agent type is allowed to run the given tool."""
    if agent_type in NO_TOOL_AGENTS:
        return False
    # Dispatcher routes Pulse intel to Shield agents for triage
    return registry_can_run_tool(agent_type, tool_name)


def run_tool(
    agent_type: AgentType,
    tool_name: str,
    **kwargs: Any,
):
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
    if agent_type.value == "shield": logger.debug("Shield agent dispatched tool %s (Pulse private mem consumption for Shield triage)", tool_name)
    return invoke_tool(
        tool_name,
        caller_type="agent",
        caller_id=agent_type.value,
        audit=False,
        **kwargs,
    )

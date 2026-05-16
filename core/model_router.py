"""
Model Router - Single source of truth for which Grok model to use for different roles.

This allows us to use different models for different parts of the app:
- nav_chat: Lightweight, fast responses for the main left-side chat (Navi as personal assistant)
- chief_of_staff: Heavy multi-agent model for complex orchestration and planning
- deep_research, workspace, etc.: Can be tuned independently

Configuration is done via environment variables (e.g. MODEL_NAV_CHAT=grok-4.3).
"""

from __future__ import annotations
from enum import Enum
import os
import logging

logger = logging.getLogger(__name__)


class ModelRole(str, Enum):
    """Semantic roles within the application."""
    NAV_CHAT = "nav_chat"              # Left-side personal assistant chat
    CHIEF_OF_STAFF = "chief_of_staff"  # Heavy orchestration and planning
    DEEP_RESEARCH = "deep_research"    # Iterative web + file research
    WORKSPACE = "workspace"            # Document generation and collaboration
    INTEL = "intel"                    # Market and regulatory intelligence
    SECURITY = "security"              # Cybersecurity and privacy policy work


# Default model mapping
# These can be overridden via environment variables (e.g. MODEL_NAV_CHAT=grok-4.3)
_DEFAULT_MODELS: dict[ModelRole, str] = {
    ModelRole.NAV_CHAT:        "grok-latest",
    ModelRole.CHIEF_OF_STAFF:  "grok-4.20-multi-agent-beta-0309",
    ModelRole.DEEP_RESEARCH:   "grok-4.20-multi-agent-beta-0309",
    ModelRole.WORKSPACE:       "grok-4.20-multi-agent-beta-0309",
    ModelRole.INTEL:           "grok-latest",
    ModelRole.SECURITY:        "grok-latest",
}


def get_model(role: ModelRole) -> str:
    """
    Returns the model name to use for a given role.

    Environment variable overrides are supported:
        MODEL_NAV_CHAT=grok-4.3
        MODEL_CHIEF_OF_STAFF=grok-4.20-multi-agent-beta-0309

    If no override is set, the sensible default for that role is returned.
    """
    env_var = f"MODEL_{role.value.upper()}"
    model = os.getenv(env_var, _DEFAULT_MODELS[role])

    if model != _DEFAULT_MODELS[role]:
        logger.debug(f"Using overridden model for {role.value}: {model}")
    else:
        logger.debug(f"Using default model for {role.value}: {model}")

    return model


def get_nav_chat_model() -> str:
    """Convenience function for the left-side Navi chat."""
    return get_model(ModelRole.NAV_CHAT)


def get_chief_of_staff_model() -> str:
    """Convenience function for the Chief of Staff (always heavy by default)."""
    return get_model(ModelRole.CHIEF_OF_STAFF)

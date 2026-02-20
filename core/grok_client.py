"""
Grok API client using xAI SDK (gRPC / Responses API).

Replaces deprecated REST https://api.x.ai/v1/chat/completions (410 Gone).
Uses xai_sdk.Client for chat and optional web_search tool for live search.
"""

import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

# Default models (align with previous usage)
MODEL_CHAT = "grok-4-1-fast-reasoning-latest"
MODEL_FAST = "grok-4-1-fast"
MODEL_WEB = "grok-4-latest"
MODEL_COS = "grok-4-latest"  # Chief of Staff: flagship model, no forced output structure


def _get_api_key() -> Optional[str]:
    """Resolve xAI API key from env (XAI_API_KEY or GROK_API_KEY)."""
    return os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")


def grok_available() -> tuple:
    """Return (ok: bool, message: str). If not ok, message explains how to fix (e.g. pip install, API key)."""
    try:
        from xai_sdk import Client  # noqa: F401
    except ImportError as e:
        return False, "xAI SDK not installed. In your environment run: pip install xai-sdk"
    if not _get_api_key():
        return False, "XAI_API_KEY or GROK_API_KEY not set. Add it to config/.env or your environment."
    return True, ""


def _get_client():
    """Lazy singleton Client. Requires xai_sdk."""
    from xai_sdk import Client
    key = _get_api_key()
    if not key:
        raise ValueError("XAI_API_KEY or GROK_API_KEY not set")
    return Client(api_key=key, timeout=300)


def grok_completion(
    system: str,
    user: str,
    model: str = MODEL_CHAT,
    store: bool = False,
) -> str:
    """
    Single turn: system + user message, return assistant content.
    Uses xAI SDK (gRPC); no deprecated REST.
    """
    try:
        from xai_sdk import Client
        from xai_sdk.chat import system as sys_msg, user as user_msg
    except ImportError as e:
        logger.warning("xai_sdk not available: %s", e)
        return ""

    key = _get_api_key()
    if not key:
        logger.warning("Grok API key not available")
        return ""

    try:
        client = Client(api_key=key, timeout=300)
        chat = client.chat.create(
            model=model,
            messages=[sys_msg(system), user_msg(user)],
            store_messages=store,
        )
        response = chat.sample()
        return (response.content or "").strip()
    except Exception as e:
        logger.exception("Grok completion failed: %s", e)
        raise


def grok_completion_messages(
    messages: List[dict],
    model: str = MODEL_CHAT,
    store: bool = False,
) -> str:
    """
    Multi-message turn. messages = [{"role": "system", "content": "..."}, ...].
    Returns assistant content.
    """
    try:
        from xai_sdk import Client
        from xai_sdk.chat import system as sys_msg, user as user_msg
    except ImportError as e:
        logger.warning("xai_sdk not available: %s", e)
        return ""

    key = _get_api_key()
    if not key:
        logger.warning("Grok API key not available")
        return ""

    try:
        from xai_sdk.chat import assistant as assistant_msg
        client = Client(api_key=key, timeout=300)
        chat = client.chat.create(model=model, store_messages=store)
        for m in messages:
            role = (m.get("role") or "").strip().lower()
            content = (m.get("content") or "").strip()
            if not content:
                continue
            if role == "system":
                chat.append(sys_msg(content))
            elif role == "user":
                chat.append(user_msg(content))
            elif role == "assistant":
                chat.append(assistant_msg(content))
        response = chat.sample()
        return (response.content or "").strip()
    except Exception as e:
        logger.exception("Grok completion (messages) failed: %s", e)
        raise


def grok_web_search(
    user_prompt: str,
    model: str = MODEL_FAST,
) -> str:
    """
    Call Grok with web_search server-side tool. Returns response content.
    Include date range or other constraints in user_prompt if needed.
    """
    try:
        from xai_sdk import Client
        from xai_sdk.chat import user as user_msg
        from xai_sdk.tools import web_search
    except ImportError as e:
        logger.warning("xai_sdk or tools not available: %s", e)
        return ""

    key = _get_api_key()
    if not key:
        logger.warning("Grok API key not available")
        return ""

    try:
        client = Client(api_key=key, timeout=120)
        chat = client.chat.create(
            model=model,
            tools=[web_search()],
        )
        chat.append(user_msg(user_prompt))
        response = chat.sample()
        out = (response.content or "").strip()
        if getattr(response, "citations", None):
            out += "\n\nSources: " + ", ".join(response.citations[:15])
        return out
    except Exception as e:
        logger.exception("Grok web search failed: %s", e)
        raise

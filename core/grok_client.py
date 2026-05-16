"""
Grok API client using xAI SDK (gRPC / Responses API).

Replaces deprecated REST https://api.x.ai/v1/chat/completions (410 Gone).
Uses xai_sdk.Client for chat and optional web_search tool for live search.
"""

import logging
import os
import time
from typing import List, Optional, Any, Union

from core.model_router import ModelRole, get_model

logger = logging.getLogger(__name__)

# Default model (single shared xAI model across app call sites)
# Legacy constants (still used in many places).
# These now resolve through the model router for a smooth transition.
# New code should prefer: from core.model_router import ModelRole, get_model
MODEL_MULTI_AGENT = "grok-4.20-multi-agent-beta-0309"

MODEL_CHAT = get_model(ModelRole.NAV_CHAT)
MODEL_FAST = get_model(ModelRole.NAV_CHAT)
MODEL_WEB = get_model(ModelRole.NAV_CHAT)
MODEL_COS = get_model(ModelRole.CHIEF_OF_STAFF)


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


_TRANSIENT_GROK_MARKERS: tuple[str, ...] = (
    "service temporarily unavailable",
    "statuscode.internal",
    "statuscode.unavailable",
    "deadline exceeded",
    "deadline_exceeded",
    "resource exhausted",
    "dns resolution failed",
    "no such host is known",
    "socket is null",
)


def is_transient_grok_error(exc: BaseException) -> bool:
    """True when the exception string matches known flaky gRPC/network patterns."""
    error_str = str(exc).lower()
    return any(marker in error_str for marker in _TRANSIENT_GROK_MARKERS)


def format_grok_user_facing_error(exc: BaseException) -> str:
    """
    Map common gRPC/xAI failures to a short user-visible message.
    Used by agent chat and Chief of Staff when Grok raises after logging.
    """
    err_str = str(exc).lower()
    if "deadline exceeded" in err_str or "deadline_exceeded" in err_str:
        return "Request timed out. Try a shorter prompt or try again."
    if "resource_exhausted" in err_str or "resource exhausted" in err_str:
        return "Rate limit or quota reached. Check your xAI credits."
    if (
        "service temporarily unavailable" in err_str
        or "internal" in err_str
        or is_transient_grok_error(exc)
    ):
        return (
            "xAI/Grok service is temporarily unavailable. Please wait 1–2 minutes and try again."
        )
    msg = str(exc).strip()
    tail = msg[:150] if len(msg) > 150 else msg
    return f"Grok error: {tail}"


def is_user_facing_llm_failure_message(text: str | None) -> bool:
    """
    True when `text` is a standardized failure reply (not normal model prose).
    Used by GUI workers to route to error handling / avoid success notifications.
    """
    t = (text or "").strip()
    if not t:
        return False
    tl = t.lstrip().lower()
    if t.startswith("Failed to process request:"):
        return True
    if t.startswith("Could not complete the request"):
        return True
    if t.startswith("Grok error:"):
        return True
    if "xai/grok service is temporarily unavailable" in tl:
        return True
    if tl.startswith("request timed out"):
        return True
    if "rate limit or quota reached" in tl:
        return True
    if tl.startswith("error:") or tl.startswith("error "):
        return True
    if t.lstrip().startswith("❌"):
        return True
    return False


def _get_client():
    """Lazy singleton Client. Requires xai_sdk."""
    from xai_sdk import Client
    key = _get_api_key()
    if not key:
        raise ValueError("XAI_API_KEY or GROK_API_KEY not set")
    return Client(api_key=key, timeout=300)


def _grok_completion_max_attempts() -> int:
    raw = (os.getenv("GROK_COMPLETION_MAX_ATTEMPTS") or "5").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 5
    return max(1, min(n, 8))


def _grok_retry_sleep_s(attempt: int) -> float:
    """
    Exponential backoff for transient Grok failures.
    Defaults to a slightly slower curve than before to ride out short xAI outages.
    """
    base_raw = (os.getenv("GROK_RETRY_BASE_SECONDS") or "2.0").strip()
    try:
        base = float(base_raw)
    except ValueError:
        base = 2.0
    if base <= 0:
        base = 2.0
    cap_raw = (os.getenv("GROK_RETRY_MAX_SECONDS") or "20").strip()
    try:
        cap = float(cap_raw)
    except ValueError:
        cap = 20.0
    if cap <= 0:
        cap = 20.0
    return min(cap, base * (2**attempt))


def grok_completion(
    system: str,
    user: str,
    model: Union[str, ModelRole] = MODEL_CHAT,
    store: bool = False,
    max_tokens: Optional[int] = None,
) -> str:
    """
    Single turn: system + user message, return assistant content.
    Uses xAI SDK (gRPC); no deprecated REST.
    """
    # Resolve ModelRole to actual model string
    if isinstance(model, ModelRole):
        model = get_model(model)

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

    create_kw: dict[str, Any] = {
        "model": model,
        "messages": [sys_msg(system), user_msg(user)],
        "store_messages": store,
    }
    if max_tokens is not None:
        create_kw["max_tokens"] = int(max_tokens)

    attempts = _grok_completion_max_attempts()
    last_err: BaseException | None = None
    for attempt in range(attempts):
        try:
            client = Client(api_key=key, timeout=300)
            chat = client.chat.create(**create_kw)
            response = chat.sample()
            return (response.content or "").strip()
        except Exception as e:
            last_err = e
            if attempt < attempts - 1 and is_transient_grok_error(e):
                sleep_s = _grok_retry_sleep_s(attempt)
                logger.warning(
                    "Grok completion transient failure; retrying in %.1fs (%s/%s): %s",
                    sleep_s,
                    attempt + 1,
                    attempts,
                    e,
                )
                time.sleep(sleep_s)
                continue
            logger.exception("Grok completion failed: %s", e)
            raise
    if last_err:
        raise last_err
    return ""


def grok_completion_messages(
    messages: List[dict],
    model: Union[str, ModelRole] = MODEL_CHAT,
    store: bool = False,
    max_tokens: Optional[int] = None,
) -> str:
    """
    Multi-message turn. messages = [{"role": "system", "content": "..."}, ...].
    Returns assistant content.
    """
    # Resolve ModelRole to actual model string
    if isinstance(model, ModelRole):
        model = get_model(model)

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

    from xai_sdk.chat import assistant as assistant_msg

    create_kw: dict[str, Any] = {"model": model, "store_messages": store}
    if max_tokens is not None:
        create_kw["max_tokens"] = int(max_tokens)

    attempts = _grok_completion_max_attempts()
    last_err: BaseException | None = None
    for attempt in range(attempts):
        try:
            client = Client(api_key=key, timeout=300)
            chat = client.chat.create(**create_kw)
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
            last_err = e
            if attempt < attempts - 1 and is_transient_grok_error(e):
                sleep_s = _grok_retry_sleep_s(attempt)
                logger.warning(
                    "Grok completion (messages) transient failure; retrying in %.1fs (%s/%s): %s",
                    sleep_s,
                    attempt + 1,
                    attempts,
                    e,
                )
                time.sleep(sleep_s)
                continue
            logger.exception("Grok completion (messages) failed: %s", e)
            raise
    if last_err:
        raise last_err
    return ""


def grok_web_search(
    user_prompt: str,
    model: str = MODEL_FAST,
    timeout: int = 120,
    retries: int = 1,
    retry_backoff_s: float = 2.0,
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

    def _is_deadline_exceeded(err: Exception) -> bool:
        s = str(err).lower()
        return (
            "deadline_exceeded" in s
            or "deadline exceeded" in s
            or "statuscode.deadline_exceeded" in s
        )

    last_err: Exception | None = None
    attempts = max(1, int(retries) + 1)
    for attempt in range(attempts):
        try:
            client = Client(api_key=key, timeout=int(timeout))
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
            last_err = e
            # Retry on common transient gRPC timeouts.
            if attempt < attempts - 1 and _is_deadline_exceeded(e):
                sleep_s = float(retry_backoff_s) * (2**attempt)
                logger.warning(
                    "Grok web search deadline exceeded; retrying in %.1fs (attempt %s/%s)",
                    sleep_s,
                    attempt + 1,
                    attempts,
                )
                time.sleep(sleep_s)
                continue
            logger.exception("Grok web search failed: %s", e)
            raise

    # Defensive fallback (shouldn't happen due to raise above).
    if last_err:
        raise last_err
    return ""

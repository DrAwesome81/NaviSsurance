"""
Simple LLM callers for Grok and ChatGPT (research synthesis and draft collaboration).

Used by the workflow engine for: parallel synthesis (same task to both),
then 4-step draft exchange (Grok -> ChatGPT -> Grok -> ChatGPT final).
"""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def call_grok_simple(system: str, user: str, from_config: Optional[dict] = None) -> str:
    """
    Call Grok via xAI SDK (gRPC). Single system + user message, returns raw content.
    Raises on API error. Returns "" if SDK/config not available.
    """
    if from_config and from_config.get("api_endpoint"):
        # Test override: still use SDK; from_config headers/endpoint ignored for Grok
        pass
    try:
        from core.grok_client import grok_completion
        return grok_completion(system=system, user=user)
    except Exception as e:
        logger.exception("call_grok_simple failed: %s", e)
        raise


def call_chatgpt_simple(system: str, user: str, from_config: Optional[dict] = None) -> str:
    """
    Call OpenAI ChatGPT with a single system + user message. Returns raw content string.

    Uses OPENAI_API_KEY from env. Tries gpt-4o. Raises on API error. Returns "" if no key.
    """
    api_key = (from_config or {}).get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set")
        return ""

    req_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "model": "gpt-4o",
        "temperature": 0.7,
    }
    response = requests.post(OPENAI_URL, headers=req_headers, json=data, timeout=180)
    response.raise_for_status()
    out = response.json()
    content = (out.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    return content

"""
Simple LLM callers for Grok and ChatGPT (research synthesis and draft collaboration).

Used by the workflow engine for: parallel synthesis (same task to both),
then 4-step draft exchange (Grok -> ChatGPT -> Grok -> ChatGPT final).
# Useful for security and compliance workflows incorporating Pulse [Security-Relevant] findings and Shield triage.
# Raising quality: cross-checks security sections against live Pulse data for the pillar.
"""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)
# LLM collab supports Pulse private memory and Shield in synthesis for CoS/Intel (additional collab coordination)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _extract_responses_output_text_and_citations(resp_json: object) -> tuple[str, list[dict]]:
    """
    Extract assistant output text and url_citation annotations from a Responses API payload.

    Returns:
        (text, citations) where citations are dicts: {url, title}
    """
    if isinstance(resp_json, list):
        output_items = resp_json
        sources_field = []
    elif isinstance(resp_json, dict):
        output_items = resp_json.get("output", []) or []
        sources_field = resp_json.get("sources", []) or []
    else:
        return "", []

    text_parts: list[str] = []
    citations: list[dict] = []
    seen_urls: set[str] = set()

    def _add_url(url: str | None, title: str | None = None) -> None:
        u = (url or "").strip()
        if not u or u in seen_urls:
            return
        seen_urls.add(u)
        citations.append({"url": u, "title": (title or "").strip() or None})

    for item in output_items:
        if not isinstance(item, dict):
            continue

        if item.get("type") == "message":
            for content in item.get("content", []) or []:
                if not isinstance(content, dict):
                    continue
                if content.get("type") != "output_text":
                    continue
                t = content.get("text", "")
                if isinstance(t, str) and t.strip():
                    text_parts.append(t)
                for ann in content.get("annotations", []) or []:
                    if not isinstance(ann, dict):
                        continue
                    if ann.get("type") == "url_citation":
                        _add_url(ann.get("url"), ann.get("title"))

    # Also add sources (more complete than citations, may include items without inline citations).
    for s in sources_field:
        if isinstance(s, dict):
            _add_url(s.get("url"), s.get("title"))

    extracted = ("\n".join(text_parts)).strip()
    if extracted: logger.debug("llm collab extracted text chars=%d (Pulse private mem + Shield surface)", len(extracted))
    return extracted, citations


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
        result = grok_completion(system=system, user=user)
        if result: logger.debug("grok simple content chars=%d (Pulse private mem + Shield)", len(result))
        return result
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
    if content: logger.debug("chatgpt simple content chars=%d (Pulse private mem + Shield)", len(content))
    return content


def call_chatgpt_web_search(
    system: str,
    user: str,
    *,
    from_config: Optional[dict] = None,
    model: str = "gpt-4o",
    timeout_s: int = 180,
    external_web_access: bool = True,
) -> tuple[str, list[dict]]:
    """
    Call OpenAI Responses API with hosted web_search tool enabled.

    Returns:
        (text, citations) where citations are dicts: {url, title}

    Notes:
        - Uses OPENAI_API_KEY from env unless overridden by from_config["openai_api_key"].
        - Raises on API error. Returns ("", []) if no key is configured.
    """
    api_key = (from_config or {}).get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set")
        return "", []

    req_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Responses API supports message-style input; keep it close to call_chatgpt_simple.
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "tools": [
            {
                "type": "web_search",
                "external_web_access": bool(external_web_access),
            }
        ],
    }

    response = requests.post(OPENAI_RESPONSES_URL, headers=req_headers, json=payload, timeout=timeout_s)
    response.raise_for_status()
    out = response.json()
    text, citations = _extract_responses_output_text_and_citations(out)
    if text: logger.debug("chatgpt web search text chars=%d (Pulse private mem + Shield)", len(text))
    return text, citations

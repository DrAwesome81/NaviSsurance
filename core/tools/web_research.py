"""
Web research tool for the Web Researcher agent.

Uses ChatGPT to research the query and returns a structured WebResearchBrief.
Only the Web Researcher agent should call this; the Manager reads artifacts.
"""

import logging
import re
from datetime import datetime
from typing import Optional

from core.agent_schemas import Finding, WebResearchBrief, WebSource

logger = logging.getLogger(__name__)

# Web research uses ChatGPT (core.llm_collab.call_chatgpt_simple)


def _extract_urls(text: str) -> list[str]:
    """Extract URLs from text (simple regex)."""
    url_pattern = re.compile(
        r"https?://[^\s<>\"']+",
        re.IGNORECASE,
    )
    return list(dict.fromkeys(url_pattern.findall(text)))  # unique, order preserved


def web_research_tool(
    query: str,
    top_n: int = 10,
    from_config: Optional[dict] = None,
) -> WebResearchBrief:
    """
    Run web search via Grok live search and return a WebResearchBrief.

    Args:
        query: Search query.
        top_n: Hint for max sources (Grok returns what it returns; we structure it).
        from_config: Optional {api_endpoint, headers} to override config (e.g. for tests).

    Returns:
        WebResearchBrief with sources (from extracted URLs), findings (summary), notes.
    """
    now = datetime.now()
    retrieved_date_str = now.strftime("%Y-%m-%d %H:%M")

    system_prompt = (
        "You are a research assistant. Find and report relevant, reputable sources. "
        "For each source provide: title, publisher/site name, exact URL, and publish date if known. "
        "Include all key facts or quotes. Report everything relevant; do not limit or summarize the set of results. "
        "If there are conflicting claims across sources, note them."
    )
    user_prompt = (
        f"Find and report all relevant, reputable sources about: {query}. "
        "For each source, provide: title, publisher/site name, exact URL, and publish date if known. "
        "Include all key facts or quotes that answer the query. Report everything you find; do not limit or summarize the set of results. "
        "If there are conflicting claims across sources, note them."
    )

    try:
        from core.llm_collab import call_chatgpt_simple
        content = call_chatgpt_simple(system_prompt, user_prompt)
        if not content:
            raise ValueError("ChatGPT returned no content (check OPENAI_API_KEY).")
    except Exception as e:
        logger.exception("Web research request failed: %s", e)
        return WebResearchBrief(
            query=query,
            sources=[],
            findings=[],
            contradictions=[],
            notes=f"Web research failed: {e}",
        )

    urls = _extract_urls(content)
    sources_list = []
    for url in urls[:top_n]:
        sources_list.append(
            WebSource(
                title="Web result",
                publisher=None,
                url=url,
                publish_date=None,
                retrieved_date=retrieved_date_str,
            )
        )

    # One finding: the full response as the main "claim" so the Writer has the content (no cap)
    findings_list = [
        Finding(
            claim=content,
            supporting_sources=urls[:20],
            supporting_quotes=[],
        )
    ]

    return WebResearchBrief(
        query=query,
        sources=sources_list,
        findings=findings_list,
        contradictions=[],
        notes=f"ChatGPT web research ({retrieved_date_str}). Refine parsing for finer sources/findings/contradictions as needed.",
    )

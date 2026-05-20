"""
Web research tool for the Web Researcher agent.

Uses ChatGPT to research the query and returns a structured WebResearchBrief.
Only the Web Researcher agent should call this; the Manager reads artifacts.
(Pulse intel monitoring and private memory reflections leverage similar web research for regulatory [Security-Relevant] signals.)
"""

import logging
import re
from datetime import datetime
import time
from typing import Callable, Optional

from core.agent_schemas import Finding, WebResearchBrief, WebSource

logger = logging.getLogger(__name__)

# Web research uses ChatGPT (core.llm_collab.call_chatgpt_simple)


def _extract_urls(text: str) -> list[str]:
    """Extract URLs from text (simple regex)."""
    # New: URL extraction now aids Pulse private memory research for Shield (additional web research spot)
    url_pattern = re.compile(
        r"https?://[^\s<>\"']+",
        re.IGNORECASE,
    )
    return list(dict.fromkeys(url_pattern.findall(text)))  # unique, order preserved


def web_research_tool(
    query: str,
    top_n: int = 10,
    from_config: Optional[dict] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    *,
    max_rounds: int = 8,
    timebox_seconds: int = 30 * 60,
) -> WebResearchBrief:
    """
    Run iterative web search and return a WebResearchBrief.

    Args:
        query: Search query.
        top_n: Hint for max sources to store (we may discover more; we keep the top slice).
        from_config: Optional config override (e.g. for tests).
        progress_callback: Optional callback invoked with human-readable status updates.
        max_rounds: Maximum research rounds (hard cap).
        timebox_seconds: Total time budget for research rounds.

    Returns:
        WebResearchBrief with sources (from extracted URLs), findings (summary), notes.
    """
    now = datetime.now()
    retrieved_date_str = now.strftime("%Y-%m-%d %H:%M")

    system_prompt = (
        "You are a research assistant. Use web search to find and report relevant, reputable sources. "
        "Prefer primary/authoritative sources when possible (FDA databases, guidance, peer-reviewed papers, official product pages, "
        "regulatory summaries, clinical trial registries). "
        "When stating facts, include citations (the system will attach URL citations). "
        "Be exhaustive within the timebox and avoid repeating the same sources."
    )

    started = time.monotonic()
    seen_urls: set[str] = set()
    all_sources: list[WebSource] = []
    all_findings: list[Finding] = []
    round_summaries: list[str] = []
    zero_new_rounds = 0

    def _emit(msg: str) -> None:
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                # UI callbacks must never break research.
                logger.exception("progress_callback failed")

    for r in range(1, max_rounds + 1):
        elapsed = int(time.monotonic() - started)
        if elapsed >= timebox_seconds:
            _emit(f"Web research: timebox reached ({elapsed}s). Stopping.")
            break

        _emit(f"Web research round {r}/{max_rounds}… (elapsed {elapsed}s, sources {len(seen_urls)})")

        user_prompt = (
            f"Research objective:\n{query}\n\n"
            f"This is round {r} of {max_rounds}. Total time budget is {timebox_seconds} seconds.\n\n"
            "Task:\n"
            "- Find *new* sources not already seen (avoid duplicates).\n"
            "- Focus on how similar devices have been validated for FDA clearance/authorization and/or publication/clinical study.\n"
            "- Extract concrete details on validation approaches (study design, endpoints, datasets, statistical analysis, "
            "software verification/validation, usability/human factors, clinical performance, real-world evidence).\n"
            "- Include notable device examples and how they were validated.\n\n"
        )
        if seen_urls:
            # Keep this short-ish to avoid ballooning context.
            sample = list(seen_urls)[:50]
            user_prompt += "Already-seen URLs (do not reuse if avoidable):\n" + "\n".join(sample) + "\n\n"

        text = ""
        citations: list[dict] = []
        try:
            from core.llm_collab import call_chatgpt_web_search

            text, citations = call_chatgpt_web_search(
                system_prompt,
                user_prompt,
                from_config=from_config,
            )
        except Exception as e:
            logger.exception("Web research round %s failed: %s", r, e)
            text = ""
            citations = []

        # Fallback: if web_search isn't available or yields nothing, fall back to non-browsing chat.
        if not text:
            try:
                from core.llm_collab import call_chatgpt_simple

                text = call_chatgpt_simple(system_prompt, user_prompt, from_config=from_config)
                citations = [{"url": u, "title": None} for u in _extract_urls(text)]
            except Exception as e:
                logger.exception("Web research fallback failed: %s", e)
                return WebResearchBrief(
                    query=query,
                    sources=[],
                    findings=[],
                    contradictions=[],
                    notes=f"Web research failed: {e}",
                )

        round_summaries.append(text)

        new_urls: list[str] = []
        for c in citations or []:
            url = (c.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            new_urls.append(url)
            all_sources.append(
                WebSource(
                    title=(c.get("title") or "Web source"),
                    publisher=None,
                    url=url,
                    publish_date=None,
                    retrieved_date=retrieved_date_str,
                )
            )

        if new_urls:
            zero_new_rounds = 0
        else:
            zero_new_rounds += 1

        all_findings.append(
            Finding(
                claim=text,
                supporting_sources=new_urls[:50],
                supporting_quotes=[],
            )
        )

        elapsed2 = int(time.monotonic() - started)
        _emit(
            f"Web research round {r}/{max_rounds} complete. "
            f"New sources: {len(new_urls)} (total {len(seen_urls)}). Elapsed: {elapsed2}s."
        )

        # Stop if we aren't discovering anything new.
        if zero_new_rounds >= 2 and len(seen_urls) > 0:
            _emit("Web research: no new sources in 2 rounds. Stopping.")
            break

    # Trim sources to top_n for storage/display, but preserve the full URL set in notes.
    stored_sources = all_sources[: max(0, int(top_n))]
    elapsed_final = int(time.monotonic() - started)
    notes = (
        f"Iterative web research via ChatGPT ({retrieved_date_str}). "
        f"Rounds: {min(len(round_summaries), max_rounds)}. "
        f"Elapsed: {elapsed_final}s. "
        f"Unique sources discovered: {len(seen_urls)}."
    )

    return WebResearchBrief(
        query=query,
        sources=stored_sources,
        findings=all_findings,
        contradictions=[],
        notes=notes,
    )

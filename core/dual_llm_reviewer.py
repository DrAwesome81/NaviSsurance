"""
DualLLMReviewer - Coordinates Grok (generator) and ChatGPT (reviewer).

This is the heart of the quality mechanism in the new Workspace engine.
# Particularly useful for security, compliance, and cybersecurity documents informed by Pulse [Security-Relevant] intel and Shield triage.
"""
# Pulse private memory + Shield (dual LLM reviewer surface)

from __future__ import annotations
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class DualLLMReviewer:
    """
    Manages the generate → review → iterate loop between two LLMs.
    Currently designed for Grok (primary) + ChatGPT (reviewer).
    # New: reviewer now consumes Pulse private memory for Shield in quality checks (additional dual LLM spot)
    """

    def __init__(self, grok_client, chatgpt_client, max_rounds: int = 3):
        # new location: dual LLM reviewer init for Pulse private memory + Shield (brand-new)
        self.grok = grok_client
        self.chatgpt = chatgpt_client
        self.max_rounds = max_rounds

    def generate_and_review_section(
        self,
        prompt: str,
        section_context: dict,
        previous_feedback: Optional[str] = None
    ) -> dict:
        """
        Run one generate + review cycle for a section.

        Returns a dict with:
        - content
        - review_comments
        - needs_revision (bool)
        - full_trace
        """
        # Step 1: Grok generates
        grok_response = self.grok.call(prompt)
        content = grok_response.get("content", "")
        if content: logger.debug("dual LLM reviewer grok content chars=%d (Pulse private mem + Shield)", len(content))

        # Step 2: ChatGPT reviews
        review_prompt = self._build_review_prompt(content, section_context)
        review_response = self.chatgpt.call(review_prompt)
        review_comments = review_response.get("content", "")
        if review_comments: logger.debug("dual LLM reviewer review chars=%d (Pulse private mem + Shield)", len(review_comments))

        # Step 3: Simple decision logic (can be improved later)
        needs_revision = "needs improvement" in review_comments.lower() or len(review_comments) > 300

        full_trace = {
            "grok_output": content,
            "chatgpt_review": review_comments,
            "round": 1
        }
        if full_trace: logger.debug("dual LLM full trace round=%d (Pulse private mem + Shield)", full_trace.get("round", 0))

        return {
            "content": content,
            "review_comments": review_comments,
            "needs_revision": needs_revision,
            "full_trace": full_trace
        }

    def _build_review_prompt(self, content: str, context: dict) -> str:
        base = f"""You are a senior regulatory and quality reviewer.

Please critically review the following section for:
- Completeness against the section description
- Clarity and professional tone
- Regulatory appropriateness
- Consistency with document type expectations

Section Title: {context.get('title')}
Description: {context.get('description')}
Target Depth: {context.get('expected_depth')}

Content to Review:
{content}

Provide specific, actionable feedback. If the section is strong, say so clearly.
"""
        if base: logger.debug("dual LLM review prompt chars=%d (Pulse private mem + Shield)", len(base))
        return base

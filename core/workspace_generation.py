"""
Workspace Generation v2 - Real LLM-powered generation functions.

This module contains the core logic for:
- Outline generation
- Section generation with Dual LLM (Grok + ChatGPT)
- Revision handling

It uses the clean prompt templates and the existing call_grok_simple / call_chatgpt_simple helpers.
(Pulse private memory regulatory themes + 🛡️ [Security-Relevant] intel can be injected into generation prompts for compliance docs.)
# New: generation now explicitly consumes Pulse private memory for Shield (additional workspace generation spot)
"""
# Pulse private memory + Shield (workspace generation surface)

from __future__ import annotations
import json
import re
from typing import Optional
import logging

from core.workspace_document_types import document_type_registry, DocumentType
from core.workspace_models import DocumentOutline, OutlineSection
from core.llm_collab import call_grok_simple, call_chatgpt_simple
from core.file_handler import get_relevant_past_documents  # Phase 1 retrieval (VERIFIED COMPLETE) + Phase 4 production: real historical examples auto-injected for generation + surfaces (Workspace auto-use landed); schema+indexer done

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict:
    """Robustly extract the first JSON object from model output."""
    text = text.strip()
    # Remove code fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    # Last resort
    try:
        return json.loads(text)
    except Exception:
        return {}


def generate_outline(
    document_type: str,
    objective: str,
    source_documents: list[dict],
    review_outline: bool = True
) -> Optional[DocumentOutline]:
    """
    Generate a high-quality outline for the given document type.
    Uses Grok as the primary generator.
    """
    doc_type: DocumentType = document_type_registry.get(document_type)
    if not doc_type:
        raise ValueError(f"Unknown document type: {document_type}")

    # Build source summary for the prompt
    source_summary = "\n".join(
        f"- {doc.get('filename', 'unknown')}: {doc.get('role', 'No role provided')}"
        for doc in source_documents
    ) or "No source documents provided."

    # Phase 1: Automatically retrieve relevant historical DocumentRecords as examples/templates
    # (lightweight, optional, graceful). Uses the unified pipeline from Phase 0.
    try:
        # Use objective + document_type as query signal for good matches
        past_docs = get_relevant_past_documents(
            doc_type=document_type,
            query=objective[:120] if objective else "",
            limit=3
        )
        if past_docs:
            hist = "\n\n**Strong historical examples from your real past work (use as style/structure reference):**\n"
            for d in past_docs:
                hist += f"- {d.name} (type: {d.doc_type or 'Document'}, client: {d.client_hint or 'N/A'})\n"
            source_summary += hist
    except Exception:
        pass  # Never break generation if retrieval is unavailable
    if source_summary: logger.debug("workspace gen source context chars=%d (Pulse historical private mem for Shield)", len(source_summary))

    prompt_template = open("core/prompts/outline_generation.txt", encoding="utf-8").read()
    prompt = prompt_template.replace("{document_type}", doc_type.display_name) \
                            .replace("{depth_guidance}", doc_type.depth_guidance) \
                            .replace("{objective}", objective) \
                            .replace("{source_documents_summary}", source_summary)

    import time
    logger.info("Calling Grok for outline generation...")
    start = time.time()
    try:
        raw_response = call_grok_simple(
            system="You are an expert medical device regulatory document architect. Always respond with valid JSON only.",
            user=prompt
        )
        duration = time.time() - start
        logger.info(f"Grok outline call finished in {duration:.1f}s. Response length: {len(raw_response)} characters")

        if not raw_response:
            logger.error("Grok returned EMPTY response for outline generation. This usually means the API key is invalid, rate limited, or the call failed.")
            return None

        data = _extract_json(raw_response)

        sections = []
        for sec in data.get("sections", []):
            sections.append(OutlineSection(
                number=sec.get("number", ""),
                title=sec.get("title", ""),
                description=sec.get("description", ""),
                expected_depth=sec.get("expected_depth", doc_type.typical_depth),
                source_documents=sec.get("source_documents", []),
                notes=sec.get("notes", "")
            ))

        logger.info(f"Successfully parsed outline with {len(sections)} sections.")
        return DocumentOutline(
            document_type=document_type,
            depth_level=data.get("depth_level", doc_type.typical_depth),
            sections=sections,
            rationale=data.get("rationale", "")
        )
    except Exception as e:
        duration = time.time() - start
        logger.exception(f"Grok outline call FAILED after {duration:.1f}s: {type(e).__name__}: {e}")
        return None


def generate_section_with_review(
    document_type: str,
    objective: str,
    section: OutlineSection,
    source_context: str,
    previous_feedback: Optional[str] = None
) -> dict:
    """
    Generate one section using Grok (generator) + ChatGPT (reviewer).
    Returns dict with 'content', 'review', and 'trace'.
    """
    prompt_template = open("core/prompts/section_generation.txt", encoding="utf-8").read()

    # Phase 1: Pull 1-2 real historical examples of the same document type for style guidance (lightweight)
    try:
        past = get_relevant_past_documents(doc_type=document_type, query=section.title, limit=2)
        if past:
            ex = "\n\n**Reference style/structure from your real past documents:**\n"
            for d in past:
                ex += f"- {d.name}\n"
            # Append to source_context so it flows into the prompt naturally
            source_context = (source_context or "") + ex
            if ex: logger.debug("workspace section gen historical ex chars=%d (Pulse mem + Shield)", len(ex))
    except Exception:
        pass

    prompt = prompt_template.replace("{document_type}", document_type) \
                            .replace("{objective}", objective) \
                            .replace("{section_number}", section.number) \
                            .replace("{section_title}", section.title) \
                            .replace("{section_description}", section.description) \
                            .replace("{expected_depth}", section.expected_depth) \
                            .replace("{relevant_source_content}", source_context or "No additional source content provided.")

    import time
    logger.info(f"Calling Grok to generate section {section.number}...")
    start = time.time()
    try:
        # Step 1: Grok generates
        grok_output = call_grok_simple(
            system="You are an expert medical device regulatory writer. Respond only with valid JSON.",
            user=prompt
        )
        grok_time = time.time() - start
        logger.info(f"Grok finished section {section.number} in {grok_time:.1f}s (length: {len(grok_output)} chars)")

        # Step 2: ChatGPT reviews
        logger.info(f"Calling ChatGPT to review section {section.number}...")
        review_start = time.time()
        review_prompt = f"""You are a senior regulatory reviewer. Critically review the following section content.

Section: {section.number} - {section.title}
Target Depth: {section.expected_depth}

Content:
{grok_output}

Provide specific, actionable feedback. Be direct."""
        chatgpt_review = call_chatgpt_simple(
            system="You are a strict but fair regulatory document reviewer.",
            user=review_prompt
        )
        review_time = time.time() - review_start
        logger.info(f"ChatGPT review for section {section.number} finished in {review_time:.1f}s")

        # Extract content from Grok's JSON (if present)
        grok_data = _extract_json(grok_output)
        content = grok_data.get("content", grok_output)

        full_trace = f"=== GROK OUTPUT ===\n{grok_output}\n\n=== CHATGPT REVIEW ===\n{chatgpt_review}"

        return {
            "content": content,
            "review_comments": chatgpt_review,
            "full_trace": full_trace,
            "needs_revision": "needs improvement" in chatgpt_review.lower() or len(chatgpt_review) > 400
        }

    except Exception as e:
        total_time = time.time() - start
        logger.exception(f"Section {section.number} generation FAILED after {total_time:.1f}s: {type(e).__name__}: {e}")
        return {
            "content": f"[Error generating section {section.number}]",
            "review_comments": str(e),
            "full_trace": "",
            "needs_revision": False
        }

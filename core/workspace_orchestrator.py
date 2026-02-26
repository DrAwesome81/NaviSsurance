from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Callable, Any, Dict
import os
import requests
import logging
from datetime import datetime
from dotenv import load_dotenv
import json
import re
import hashlib

# Load environment variables
from config import CONFIG_DIR
load_dotenv(os.path.join(CONFIG_DIR, ".env"))

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Helpers: robust JSON contract parsing + reference pack
# -----------------------------------------------------------------------------

def _extract_first_json_object(text: str) -> str:
    """
    Best-effort extraction of the first JSON object from a model response.
    Handles code fences and leading/trailing commentary.
    """
    s = (text or "").strip()
    if not s:
        return ""
    # Strip common code fences
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    # Find first { ... } block
    m = re.search(r"\{[\s\S]*\}", s)
    return (m.group(0) if m else s).strip()


def _parse_round_result(text: str) -> dict:
    """
    Parse the strict JSON contract:
      {"explanation": str, "markdown": str, "feedback": str, "is_complete": bool}
    Returns a dict with all keys present (safe defaults).
    """
    base = {"explanation": "", "markdown": "", "feedback": "", "is_complete": False}
    raw = (text or "").strip()
    if not raw:
        return base
    try:
        obj = json.loads(_extract_first_json_object(raw))
        if isinstance(obj, dict):
            out = dict(base)
            out["explanation"] = str(obj.get("explanation") or "").strip()
            out["markdown"] = str(obj.get("markdown") or "").strip()
            out["feedback"] = str(obj.get("feedback") or "").strip()
            out["is_complete"] = bool(obj.get("is_complete") is True)
            return out
    except Exception:
        pass
    # Fallback: preserve previous behavior (markdown starts with '#')
    lines = raw.splitlines()
    md_start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("#"):
            md_start = i
            break
    if md_start is None:
        base["explanation"] = raw[:2000]
        return base
    base["explanation"] = "\n".join(lines[:md_start]).strip()
    base["markdown"] = "\n".join(lines[md_start:]).strip()
    # Heuristic complete markers
    if "COMPLETE:" in raw.upper():
        base["is_complete"] = True
    return base


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "you",
    "are", "was", "were", "be", "been", "being", "have", "has", "had", "will",
    "shall", "may", "might", "can", "could", "should", "a", "an", "to", "of",
    "in", "on", "at", "as", "by", "or", "is", "it", "we", "our", "their",
}


def _keywords(text: str, limit: int = 40) -> list[str]:
    toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9\\-]{2,}", text or "")
    out = []
    seen = set()
    for t in toks:
        tl = t.lower()
        if tl in _STOPWORDS:
            continue
        if tl in seen:
            continue
        seen.add(tl)
        out.append(tl)
        if len(out) >= limit:
            break
    return out


def _chunk_text(text: str, chunk_chars: int = 1800, overlap: int = 200) -> list[str]:
    s = (text or "").strip()
    if not s:
        return []
    if len(s) <= chunk_chars:
        return [s]
    chunks = []
    i = 0
    step = max(200, chunk_chars - overlap)
    while i < len(s):
        chunks.append(s[i : i + chunk_chars])
        i += step
        if len(chunks) > 2000:
            break
    return chunks


def build_reference_pack(
    *,
    task_spec: "WorkspaceTaskSpec",
    file_contents: Dict[str, str],
    goal: str,
    feedback: str | None,
    previous_markdown: str | None,
    max_total_chars: int = 60000,
    max_chunks_per_file: int = 6,
    include_small_files_full: bool = True,
    small_file_max_chars: int = 12000,
    return_stats: bool = False,
) -> str | tuple[str, dict]:
    """
    Build a compact, relevant, *verbatim* reference pack so both models can ground edits
    without re-sending entire documents every round.
    """
    kw = _keywords(" ".join([goal or "", feedback or "", previous_markdown or ""]))
    parts: list[str] = []
    parts.append("## Reference Pack (verbatim excerpts from selected files)")
    parts.append("Rules: Excerpts are verbatim. If something is not in the excerpts, treat it as unknown unless it appears in the draft.")
    parts.append("")
    total = 0
    file_stats: list[dict[str, Any]] = []
    excerpt_count = 0
    for wf in task_spec.files:
        p = os.path.abspath(wf.path)
        content = file_contents.get(p) or file_contents.get(wf.path) or ""
        fstat: dict[str, Any] = {
            "display_name": wf.display_name,
            "path": p,
            "file_type": wf.file_type,
            "content_chars": len(content or ""),
            "chunks_total": 0,
            "chunks_selected": 0,
            "included_chars": 0,
            "inclusion": "omitted",
        }
        if not content:
            fstat["inclusion"] = "empty"
            file_stats.append(fstat)
            continue
        header = f"### File: {wf.display_name} ({wf.file_type})"
        if total + len(header) > max_total_chars:
            fstat["inclusion"] = "omitted"
            file_stats.append(fstat)
            continue
        parts.append(header)
        total += len(header)
        # include full text for small files
        if include_small_files_full and len(content) <= small_file_max_chars:
            excerpt = content.strip()
            if total + len(excerpt) + 2 > max_total_chars:
                # Not enough budget for full inclusion; fall through to chunk mode.
                pass
            else:
                parts.append(excerpt)
                parts.append("")
                total += len(excerpt) + 2
                fstat["chunks_total"] = 1
                fstat["chunks_selected"] = 1
                fstat["included_chars"] = len(excerpt)
                fstat["inclusion"] = "full"
                excerpt_count += 1
                file_stats.append(fstat)
                continue

        chunks = _chunk_text(content)
        fstat["chunks_total"] = len(chunks)
        scored: list[tuple[int, int, str]] = []
        for idx, ch in enumerate(chunks):
            cl = ch.lower()
            score = 0
            for k in kw:
                if k in cl:
                    score += 1
            # small boosts
            if "section" in cl or "scope" in cl or "requirements" in cl:
                score += 1
            scored.append((score, idx, ch))
        scored.sort(key=lambda t: (-t[0], t[1]))

        # always include the first chunk as general context (if not already selected)
        selected = []
        if chunks:
            selected.append((0, chunks[0]))
        for score, idx, ch in scored:
            if len(selected) >= max_chunks_per_file:
                break
            if idx == 0:
                continue
            if score <= 0 and len(selected) >= 2:
                break
            selected.append((idx, ch))

        for idx, ch in selected:
            if total >= max_total_chars:
                break
            # stable chunk id for referencing
            cid = hashlib.sha1((wf.display_name + ":" + str(idx)).encode("utf-8")).hexdigest()[:8]
            block = f"[excerpt {cid} chunk={idx}]\n{ch.strip()}"
            if total + len(block) > max_total_chars:
                break
            parts.append(block)
            parts.append("")
            total += len(block) + 2
            fstat["chunks_selected"] += 1
            fstat["included_chars"] += len(ch.strip())
            excerpt_count += 1
        if fstat["included_chars"] == 0:
            # Remove file header if no excerpts were included.
            if parts and parts[-1] == header:
                parts.pop()
                total -= len(header)
            fstat["inclusion"] = "omitted"
        elif fstat["included_chars"] >= len(content.strip()):
            fstat["inclusion"] = "full"
            parts.append("")
        else:
            fstat["inclusion"] = "partial"
            parts.append("")

        file_stats.append(fstat)

    pack = "\n".join(parts).strip()
    if not return_stats:
        return pack

    selected_files_count = len(task_spec.files or [])
    files_with_content = sum(1 for s in file_stats if s.get("content_chars", 0) > 0)
    files_fully_included = sum(1 for s in file_stats if s.get("inclusion") == "full")
    files_partially_included = sum(1 for s in file_stats if s.get("inclusion") == "partial")
    files_omitted = sum(1 for s in file_stats if s.get("inclusion") in {"omitted", "empty"})
    coverage_stats = {
        "selected_files_count": selected_files_count,
        "files_with_content": files_with_content,
        "files_fully_included": files_fully_included,
        "files_partially_included": files_partially_included,
        "files_omitted": files_omitted,
        "excerpt_count": excerpt_count,
        "max_total_chars": int(max_total_chars),
        "used_chars": int(total),
        "pack_chars": len(pack),
        "files": file_stats,
    }
    return pack, coverage_stats


def format_reference_pack_summary(stats: dict | None) -> str:
    """Create a short human-readable coverage summary for UI/status display."""
    s = stats or {}
    selected = int(s.get("selected_files_count") or 0)
    full = int(s.get("files_fully_included") or 0)
    partial = int(s.get("files_partially_included") or 0)
    omitted = int(s.get("files_omitted") or 0)
    used = full + partial
    pack_chars = int(s.get("pack_chars") or 0)
    if selected <= 0:
        return ""
    return (
        f"Context coverage: used {used}/{selected} files "
        f"(full {full}, partial {partial}, omitted {omitted}; pack {pack_chars} chars)"
    )


@dataclass
class WorkspaceFile:
    """
    Represents a single file in the Workspace context.
    This is a lightweight description that can be passed to Grok / ChatGPT.
    """
    path: str
    display_name: str
    file_type: str = "unknown"  # e.g., 'pdf', 'docx', 'md'


@dataclass
class WorkspaceTaskSpec:
    """
    High-level description of what the Workspace AI should do.
    This is what the local Llama will conceptually "produce" and what the
    DualLLMOrchestrator will consume.
    """
    goal: str                         # e.g., "Draft Section 5 performance endpoints..."
    context: str = ""                 # extra instructions / background
    files: List[WorkspaceFile] = field(default_factory=list)

    # Optional future extensions:
    max_rounds: int = 3              # how many Grok <-> ChatGPT cycles to allow
    style: Optional[str] = None      # e.g., "regulatory", "clinical", "marketing"
    audience: Optional[str] = None   # e.g., "FDA reviewer", "internal team"


class DualLLMOrchestrator:
    """
    Coordinates Grok (Researcher) and ChatGPT (Reviewer) for a workspace task.

    For now this is a skeleton that does:
      - one 'Grok' pass to produce a research summary + initial markdown
      - one 'ChatGPT' pass to review and lightly refine that markdown

    Later we can:
      - plug in real API clients for Grok and ChatGPT
      - turn run_once into a loop until both models agree the markdown is 'done'
    """

    def __init__(
        self,
        logger: Optional[Any] = None,
        grok_call: Optional[Callable[[WorkspaceTaskSpec], Dict[str, str]]] = None,
        chatgpt_call: Optional[Callable[[WorkspaceTaskSpec, Dict[str, str]], Dict[str, str]]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        """
        Parameters:
            logger: optional logger with .info/.error methods; if None, uses print
            grok_call: optional override to call the real Grok API
            chatgpt_call: optional override to call the real ChatGPT/OpenAI API
            progress_callback: optional callback function called after each round with round data dict

        If grok_call or chatgpt_call is None, we use stub implementations.
        """
        if logger is None:
            self.logger = self._default_logger
        elif hasattr(logger, 'info'):
            # It's a proper logger object
            self.logger = lambda msg: logger.info(msg)
        else:
            # It's a callable
            self.logger = logger
        self._grok_call = grok_call
        self._chatgpt_call = chatgpt_call
        self._progress_callback = progress_callback

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run_once(self, task_spec: WorkspaceTaskSpec, file_contents: Dict[str, str] = None) -> Dict[str, str]:
        """
        Iterative collaboration workflow:
          The two models collaborate in rounds until they agree the result is correct and complete.
          
          Round structure:
          1) Grok creates/revises markdown based on goal and feedback
          2) ChatGPT reviews and provides feedback
          3) If ChatGPT indicates completion OR max_rounds reached, return result
          4) Otherwise, Grok revises based on feedback and loop continues

        Args:
            task_spec: The workspace task specification
            file_contents: Optional dict mapping file paths to their content (for Grok API)

        Returns a dict with:
          {
              "grok_output": str,           # Final Grok explanation
              "chatgpt_output": str,         # Final ChatGPT review
              "markdown": str,               # The final agreed-upon markdown document
              "collaboration_history": list, # List of round dicts with grok_output, chatgpt_output, round_num
              "rounds": int,                 # Number of collaboration rounds completed
              "status": str                  # "completed" or "max_rounds_reached"
          }
        """
        self.logger("DualLLMOrchestrator.run_once: starting iterative collaboration workflow")
        
        max_rounds = task_spec.max_rounds or 3
        collaboration_history = []
        current_markdown = ""
        chatgpt_feedback = None
        round_num = 0
        grok_output = ""
        chatgpt_output = ""
        
        while round_num < max_rounds:
            round_num += 1
            self.logger(f"DualLLMOrchestrator: Starting collaboration round {round_num}/{max_rounds}")
            
            # 1) Grok creates or revises markdown
            grok_result = self._call_grok(task_spec, file_contents, chatgpt_feedback, round_num, current_markdown)
            grok_output = grok_result.get("explanation", "")
            grok_markdown = grok_result.get("markdown", current_markdown)
            grok_feedback = grok_result.get("feedback", "")
            grok_is_complete = grok_result.get("is_complete", False)
            
            # Use Grok's markdown if provided, otherwise keep current
            if grok_markdown and grok_markdown != current_markdown:
                current_markdown = grok_markdown
                self.logger(f"DualLLMOrchestrator: Grok updated markdown in round {round_num}")
            
            # Check if Grok indicates completion
            if grok_is_complete:
                self.logger(f"DualLLMOrchestrator: Grok indicated completion at round {round_num}")
                # Still let ChatGPT review it one more time
                chatgpt_result = self._call_chatgpt(task_spec, grok_result, file_contents, round_num)
                chatgpt_output = chatgpt_result.get("explanation", "")
                chatgpt_markdown = chatgpt_result.get("markdown", current_markdown)
                chatgpt_is_complete = chatgpt_result.get("is_complete", False)
                
                # Use ChatGPT's markdown if provided
                if chatgpt_markdown and chatgpt_markdown != current_markdown:
                    current_markdown = chatgpt_markdown
                    self.logger(f"DualLLMOrchestrator: ChatGPT updated markdown in round {round_num}")
                
                # If both agree, we're done
                if chatgpt_is_complete or not chatgpt_result.get("feedback"):
                    round_data = {
                        "round": round_num,
                        "grok_output": grok_output,
                        "chatgpt_output": chatgpt_output,
                        "markdown": current_markdown,
                        "feedback": chatgpt_result.get("feedback", ""),
                        "is_complete": True
                    }
                    collaboration_history.append(round_data)
                    if self._progress_callback:
                        try:
                            self._progress_callback(round_data)
                        except Exception as e:
                            self.logger(f"Error in progress callback: {e}")
                    return {
                        "grok_output": grok_output,
                        "chatgpt_output": chatgpt_output,
                        "markdown": current_markdown,
                        "collaboration_history": collaboration_history,
                        "rounds": round_num,
                        "status": "completed"
                    }
            
            # 2) ChatGPT reviews and edits markdown
            chatgpt_result = self._call_chatgpt(task_spec, grok_result, file_contents, round_num)
            chatgpt_output = chatgpt_result.get("explanation", "")
            chatgpt_markdown = chatgpt_result.get("markdown", current_markdown)
            chatgpt_feedback = chatgpt_result.get("feedback", "")
            chatgpt_is_complete = chatgpt_result.get("is_complete", False)
            
            # Use ChatGPT's markdown if provided (this is the key change - ChatGPT can now edit)
            if chatgpt_markdown and chatgpt_markdown != current_markdown:
                current_markdown = chatgpt_markdown
                self.logger(f"DualLLMOrchestrator: ChatGPT updated markdown in round {round_num}")
            
            # Store this round's collaboration
            round_data = {
                "round": round_num,
                "grok_output": grok_output,
                "chatgpt_output": chatgpt_output,
                "markdown": current_markdown,
                "feedback": chatgpt_feedback or grok_feedback,  # Use feedback from either model
                "is_complete": chatgpt_is_complete or grok_is_complete,  # Complete if either agrees
                "reference_pack_stats": (
                    chatgpt_result.get("reference_pack_stats")
                    or grok_result.get("reference_pack_stats")
                    or {}
                ),
            }
            collaboration_history.append(round_data)
            
            # Emit progress update if callback provided
            if self._progress_callback:
                try:
                    self._progress_callback(round_data)
                except Exception as e:
                    self.logger(f"Error in progress callback: {e}")
            
            # 3) Check if ChatGPT indicates completion
            if chatgpt_is_complete:
                self.logger(f"DualLLMOrchestrator: ChatGPT indicated completion at round {round_num}")
                # Let Grok have one more chance to review ChatGPT's version
                if round_num < max_rounds:
                    round_num += 1
                    grok_review_result = self._call_grok(task_spec, file_contents, None, round_num, current_markdown)
                    # Note: grok_review_result doesn't need to be passed to ChatGPT since we already have the markdown
                    grok_review_output = grok_review_result.get("explanation", "")
                    grok_review_markdown = grok_review_result.get("markdown", current_markdown)
                    grok_review_complete = grok_review_result.get("is_complete", False)
                    
                    # Use Grok's final markdown if provided
                    if grok_review_markdown and grok_review_markdown != current_markdown:
                        current_markdown = grok_review_markdown
                    
                    # If Grok also agrees, we're done
                    if grok_review_complete or not grok_review_result.get("feedback"):
                        final_round_data = {
                            "round": round_num,
                            "grok_output": grok_review_output,
                            "chatgpt_output": "Agreed with previous version",
                            "markdown": current_markdown,
                            "feedback": "",
                            "is_complete": True,
                            "reference_pack_stats": grok_review_result.get("reference_pack_stats") or {},
                        }
                        collaboration_history.append(final_round_data)
                        if self._progress_callback:
                            try:
                                self._progress_callback(final_round_data)
                            except Exception as e:
                                self.logger(f"Error in progress callback: {e}")
                        return {
                            "grok_output": grok_review_output,
                            "chatgpt_output": chatgpt_output,
                            "markdown": current_markdown,
                            "collaboration_history": collaboration_history,
                            "rounds": round_num,
                            "status": "completed"
                        }
                    else:
                        # Grok wants more changes, continue
                        chatgpt_feedback = grok_review_result.get("feedback", "")
                        current_markdown = grok_review_markdown if grok_review_markdown else current_markdown
                        continue
            
            # If not complete and we have feedback, continue to next round
            # grok_feedback is already defined earlier in the round
            combined_feedback = chatgpt_feedback or grok_feedback
            if combined_feedback:
                self.logger(f"DualLLMOrchestrator: Round {round_num} feedback received, continuing collaboration")
                chatgpt_feedback = combined_feedback  # Pass combined feedback to next round
            else:
                # No feedback means both models are satisfied but didn't explicitly mark complete
                # Treat as completion
                self.logger(f"DualLLMOrchestrator: No feedback at round {round_num}, treating as complete")
                return {
                    "grok_output": grok_output,
                    "chatgpt_output": chatgpt_output,
                    "markdown": current_markdown,
                    "collaboration_history": collaboration_history,
                    "rounds": round_num,
                    "status": "completed"
                }
        
        # Max rounds reached
        self.logger(f"DualLLMOrchestrator: Max rounds ({max_rounds}) reached")
        return {
            "grok_output": grok_output,
            "chatgpt_output": chatgpt_output,
            "markdown": current_markdown,
            "collaboration_history": collaboration_history,
            "rounds": round_num,
            "status": "max_rounds_reached"
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _call_grok(self, task_spec: WorkspaceTaskSpec, file_contents: Dict[str, str] = None, 
                   feedback: str = None, round_num: int = 1, previous_markdown: str = None) -> Dict[str, str]:
        """
        Call Grok (or stub) as the 'Research Agent'.
        
        Args:
            task_spec: The workspace task specification
            file_contents: Dict mapping file paths to their content
            feedback: Optional feedback from ChatGPT for iterative refinement
            round_num: Current collaboration round number
            previous_markdown: The current markdown document to revise (for rounds > 1)
        
        Expected return dict keys:
          - "explanation": natural language explanation
          - "markdown": a markdown draft string
          - "feedback": optional feedback for the other model
          - "is_complete": boolean indicating completion
        """
        if self._grok_call is not None:
            self.logger(f"DualLLMOrchestrator._call_grok: using injected grok_call (round {round_num})")
            # Pass file_contents, feedback, and previous_markdown to the real API call
            return self._grok_call(task_spec, file_contents or {}, feedback, round_num, previous_markdown)

        # Stub implementation for now
        file_list = ", ".join(f.display_name for f in task_spec.files) or "no files"

        explanation = (
            f"[Grok stub] Researching goal: {task_spec.goal}\n"
            f"Context: {task_spec.context or '(none)'}\n"
            f"Files in workspace: {file_list}\n\n"
            "This is a placeholder Grok research summary. "
            "Replace this with a real Grok API call."
        )

        markdown = (
            f"# Draft for: {task_spec.goal}\n\n"
            "_This is a placeholder markdown draft generated by the Grok stub._\n\n"
            "## Context\n"
            f"{task_spec.context or 'No explicit context provided.'}\n\n"
            "## Considered Files\n"
            + "\n".join(f"- {f.display_name} ({f.file_type})" for f in task_spec.files)
            + "\n"
        )

        return {
            "explanation": explanation,
            "markdown": markdown,
            "feedback": "",
            "is_complete": False,
        }

    def _call_chatgpt(self, task_spec: WorkspaceTaskSpec, grok_result: Dict[str, str], 
                      file_contents: Dict[str, str] = None, round_num: int = 1) -> Dict[str, str]:
        """
        Call ChatGPT (or stub) as the 'Reviewer / Editor'.
        Receives:
          - task_spec
          - grok_result: the dict returned by _call_grok
          - file_contents: Dict mapping file paths to their content (for verification against source)
          - round_num: Current collaboration round number

        Expected return dict keys:
          - "explanation": natural language explanation of review
          - "markdown": refined markdown (or empty if no changes)
          - "feedback": specific feedback for Grok to improve (if not complete)
          - "is_complete": boolean indicating if document is ready
        """
        if self._chatgpt_call is not None:
            self.logger(f"DualLLMOrchestrator._call_chatgpt: using injected chatgpt_call (round {round_num})")
            return self._chatgpt_call(task_spec, grok_result, file_contents or {}, round_num)

        grok_markdown = grok_result.get("markdown", "")

        explanation = (
            f"[ChatGPT stub] Reviewing Grok's draft for goal: {task_spec.goal}\n"
            f"Grok markdown length: {len(grok_markdown)} characters.\n\n"
            "This is a placeholder ChatGPT review. Replace with a real ChatGPT/OpenAI API call."
        )

        refined_markdown = (
            grok_markdown
            + "\n\n"
            "> [ChatGPT stub] Suggested minor refinements here. "
            "In a real implementation, this would incorporate actual edits."
        )

        return {
            "explanation": explanation,
            "markdown": refined_markdown,
            "feedback": "This is a placeholder. In a real implementation, provide specific feedback for improvements.",
            "is_complete": False  # Stub always indicates more work needed
        }

    @staticmethod
    def _default_logger(msg: str):
        print(msg)


# ------------------------------------------------------------------
# Real API implementations
# ------------------------------------------------------------------

def call_grok_api(task_spec: WorkspaceTaskSpec, file_contents: Dict[str, str], 
                  feedback: str = None, round_num: int = 1, previous_markdown: str = None) -> Dict[str, str]:
    """
    Call Grok API as the 'Research Agent'.
    
    Args:
        task_spec: The workspace task specification
        file_contents: Dict mapping file paths to their extracted content
        feedback: Optional feedback from ChatGPT for iterative refinement
        round_num: Current collaboration round number
        previous_markdown: The current markdown document to revise (for rounds > 1)
    
    Returns:
        Dict with "explanation" and "markdown" keys
    """
    try:
        from core.grok_client import grok_completion

        # Get current date for context
        current_date = datetime.now().strftime("%B %d, %Y")
        
        # Build a compact, relevant reference pack for grounding (verbatim excerpts).
        ref_pack = build_reference_pack(
            return_stats=True,
            task_spec=task_spec,
            file_contents=file_contents or {},
            goal=task_spec.goal,
            feedback=feedback,
            previous_markdown=previous_markdown,
            max_total_chars=int(os.getenv("WORKSPACE_REF_PACK_MAX_CHARS", "60000") or 60000),
            max_chunks_per_file=int(os.getenv("WORKSPACE_REF_PACK_CHUNKS_PER_FILE", "8") or 8),
            include_small_files_full=True,
            small_file_max_chars=int(os.getenv("WORKSPACE_REF_PACK_SMALL_FILE_MAX_CHARS", "12000") or 12000),
        )
        ref_pack_text, ref_pack_stats = ref_pack
        has_files = bool(task_spec.files)
        has_files_content = bool(ref_pack_text and "### File:" in ref_pack_text)
        
        # Warn if files were expected but none were found
        if task_spec.files and not has_files_content:
            logger.warning(f"Grok: Expected {len(task_spec.files)} file(s) but none had content extracted")
        
        system_message = """You are a research agent creating or refining finished, publication-ready documents.

CRITICAL:
- Output must be STRICT JSON only (no markdown fences, no extra text).
- The JSON must have keys: explanation (string), markdown (string), feedback (string), is_complete (boolean).
- markdown must be a finished standalone document (no conversational text, no questions, no placeholders).
- If the document is ready, set is_complete=true and feedback="".
- If revisions are needed, set is_complete=false and put specific, actionable instructions in feedback.
"""

        user_message = f"""Goal: {task_spec.goal}
Context: {task_spec.context or 'No additional context provided.'}
Current Date: {current_date}
Collaboration Round: {round_num}

Reference Pack:
{ref_pack_text or "(no files provided)"}

Current Markdown (may be empty on round 1):
{previous_markdown or ""}

Reviewer Feedback (if any):
{feedback or ""}

Return STRICT JSON only with:
{{
  "explanation": "...",
  "markdown": "# ... finished markdown ...",
  "feedback": "",
  "is_complete": true
}}
"""

        logger.debug("Grok API request via xAI SDK (grok_completion)")
        raw = grok_completion(system_message, user_message, model="grok-4-1-fast-reasoning-latest")
        parsed = _parse_round_result(raw)
        if not parsed.get("markdown") and previous_markdown:
            parsed["markdown"] = previous_markdown
        parsed["reference_pack_stats"] = ref_pack_stats
        return parsed
        
    except Exception as e:
        logger.error(f"Error calling Grok API: {e}")
        return {
            "explanation": f"Error calling Grok API: {str(e)}",
            "markdown": previous_markdown or f"# Error\n\nFailed to generate document: {str(e)}",
            "feedback": str(e),
            "is_complete": False,
        }


def call_chatgpt_api(task_spec: WorkspaceTaskSpec, grok_result: Dict[str, str], 
                     file_contents: Dict[str, str] = None, round_num: int = 1) -> Dict[str, str]:
    """
    Call ChatGPT/OpenAI API as the 'Reviewer / Editor'.
    
    Args:
        task_spec: The workspace task specification
        grok_result: The result from Grok (contains "markdown" and "explanation")
        file_contents: Dict mapping file paths to their content (for verification against source)
        round_num: Current collaboration round number
    
    Returns:
        Dict with "explanation", "markdown", "feedback", and "is_complete" keys
        - "explanation": Review summary
        - "markdown": Refined markdown (if any changes)
        - "feedback": Specific feedback for Grok to improve (empty if complete)
        - "is_complete": Boolean indicating if document is ready
    """
    try:
        openai_api_key = os.getenv("OPENAI_API_KEY")
        
        if not openai_api_key:
            # Fallback to Grok if OpenAI not configured
            logger.info("OpenAI API key not found, using Grok for review")
            return call_grok_review(task_spec, grok_result, file_contents)
        
        grok_markdown = grok_result.get("markdown", "")
        grok_explanation = grok_result.get("explanation", "")
        
        ref_pack_text, ref_pack_stats = build_reference_pack(
            task_spec=task_spec,
            file_contents=file_contents or {},
            goal=task_spec.goal,
            feedback=grok_result.get("feedback"),
            previous_markdown=grok_markdown,
            max_total_chars=int(os.getenv("WORKSPACE_REF_PACK_MAX_CHARS_OPENAI", "60000") or 60000),
            max_chunks_per_file=int(os.getenv("WORKSPACE_REF_PACK_CHUNKS_PER_FILE_OPENAI", "8") or 8),
            include_small_files_full=True,
            small_file_max_chars=int(os.getenv("WORKSPACE_REF_PACK_SMALL_FILE_MAX_CHARS_OPENAI", "12000") or 12000),
            return_stats=True,
        )
        
        system_message = """You are a document reviewer and editor creating finished, publication-ready documents.

CRITICAL:
- Output must be STRICT JSON only (no markdown fences, no extra text).
- The JSON must have keys: explanation (string), markdown (string), feedback (string), is_complete (boolean).
- markdown must be a finished standalone document (no conversational text, no questions, no placeholders).
- If the document is ready, set is_complete=true and feedback="".
- If revisions are needed, set is_complete=false and put specific, actionable instructions in feedback.
"""
        
        # Get current date for context
        current_date = datetime.now().strftime("%B %d, %Y")
        
        user_message = f"""Original Goal: {task_spec.goal}
Context: {task_spec.context or 'No additional context provided.'}
Current Date: {current_date}
Collaboration Round: {round_num}

Research Agent's Explanation:
{grok_explanation}

Reference Pack:
{ref_pack_text or "(no files provided)"}

Draft Markdown Document:
{grok_markdown}

Return STRICT JSON only with:
{{
  "explanation": "...",
  "markdown": "# ... finished markdown ...",
  "feedback": "",
  "is_complete": true
}}
"""
        
        headers = {
            "Authorization": f"Bearer {openai_api_key}",
            "Content-Type": "application/json"
        }
        
        # Configurable models; defaults are conservative and widely available.
        primary_model = os.getenv("OPENAI_MODEL_PRIMARY") or "gpt-4o"
        fallback_model = os.getenv("OPENAI_MODEL_FALLBACK") or "gpt-4o-mini"
        models_to_try = [(primary_model, None), (fallback_model, None)]
        response = None
        last_error = None
        used_model = None

        timeout_s = int(os.getenv("OPENAI_TIMEOUT_S", "300") or 300)
        max_tokens = int(os.getenv("OPENAI_MAX_TOKENS_REVIEW", "6000") or 6000)
        
        for model_name, _cw in models_to_try:
            try:
                data = {
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": user_message}
                    ],
                    "model": model_name,
                    "temperature": float(os.getenv("OPENAI_TEMPERATURE_REVIEW", "0.3") or 0.3),
                    "max_tokens": max_tokens,
                }
                
                # Log the request for debugging
                logger.debug(f"OpenAI API request - Model: {model_name}, Endpoint: https://api.openai.com/v1/chat/completions")
                
                response = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=timeout_s
                )
                
                # Better error handling - capture actual API error message
                if response.status_code != 200:
                    error_detail = ""
                    try:
                        error_data = response.json()
                        error_detail = f" - Response: {error_data}"
                        logger.error(f"OpenAI API error {response.status_code} for {model_name}: {error_data}")
                    except:
                        error_detail = f" - Response text: {response.text[:500]}"
                        logger.error(f"OpenAI API error {response.status_code} for {model_name}: {response.text[:500]}")
                    error_msg = f"OpenAI API error {response.status_code}: {response.reason}{error_detail}"
                    
                    if response.status_code == 404:
                        # Model not found, try next one
                        logger.info(f"{model_name} not available: {error_msg}")
                        last_error = Exception(error_msg)
                        continue
                    else:
                        # Other error, raise it with details
                        raise Exception(error_msg)
                
                response.raise_for_status()
                used_model = model_name
                logger.info(f"Successfully used {model_name} for review")
                break  # Success, exit loop
                
            except requests.exceptions.HTTPError as e:
                # Capture error details
                error_detail = ""
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_data = e.response.json()
                        error_detail = f" - {error_data}"
                    except:
                        error_detail = f" - {e.response.text}"
                
                if e.response.status_code == 404:
                    # Model not found, try next one
                    logger.info(f"{model_name} not available: {str(e)}{error_detail}")
                    last_error = Exception(f"{str(e)}{error_detail}")
                    continue
                else:
                    # Other error, raise it with details
                    raise Exception(f"{str(e)}{error_detail}")
            except Exception as e:
                last_error = e
                continue
        
        if response is None:
            # All models failed
            raise Exception(f"All OpenAI models failed. Last error: {last_error}")
        
        response_data = response.json()
        
        if 'choices' not in response_data or len(response_data['choices']) == 0:
            raise Exception(f"Invalid OpenAI API response: {response_data}")
        
        content = (response_data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        parsed = _parse_round_result(content)
        if not parsed.get("markdown"):
            parsed["markdown"] = grok_markdown
        parsed["reference_pack_stats"] = ref_pack_stats
        return parsed
        
    except Exception as e:
        logger.error(f"Error calling ChatGPT API: {e}")
        # Fallback to Grok review
        logger.info("Falling back to Grok for review")
        return call_grok_review(task_spec, grok_result, file_contents)


def call_grok_review(task_spec: WorkspaceTaskSpec, grok_result: Dict[str, str], 
                     file_contents: Dict[str, str] = None) -> Dict[str, str]:
    """
    Fallback: Use Grok for review if OpenAI not available. Uses xAI SDK.
    """
    try:
        from core.grok_client import grok_completion

        grok_markdown = grok_result.get("markdown", "")

        ref_pack_text, ref_pack_stats = build_reference_pack(
            task_spec=task_spec,
            file_contents=file_contents or {},
            goal=task_spec.goal,
            feedback=grok_result.get("feedback"),
            previous_markdown=grok_markdown,
            max_total_chars=int(os.getenv("WORKSPACE_REF_PACK_MAX_CHARS", "60000") or 60000),
            max_chunks_per_file=int(os.getenv("WORKSPACE_REF_PACK_CHUNKS_PER_FILE", "8") or 8),
            include_small_files_full=True,
            small_file_max_chars=int(os.getenv("WORKSPACE_REF_PACK_SMALL_FILE_MAX_CHARS", "12000") or 12000),
            return_stats=True,
        )

        system_message = """You are a document reviewer and editor.

CRITICAL:
- Output must be STRICT JSON only (no markdown fences, no extra text).
- The JSON must have keys: explanation (string), markdown (string), feedback (string), is_complete (boolean).
- markdown must be a finished standalone document (no conversational text, no questions, no placeholders).
"""

        # Get current date for context
        current_date = datetime.now().strftime("%B %d, %Y")

        user_message = f"""Original Goal: {task_spec.goal}

Current Date: {current_date}
Reference Pack:
{ref_pack_text or "(no files provided)"}

Draft Markdown Document:
{grok_markdown}

Please review and refine this document. Make improvements for clarity, structure, and completeness. If original source files are provided above, verify the draft against them for accuracy. Remember: The current date is {current_date}. Use this as a reference for any time-sensitive information.

Return STRICT JSON only with:
{{
  "explanation": "...",
  "markdown": "# ... finished markdown ...",
  "feedback": "",
  "is_complete": true
}}
"""

        raw = grok_completion(system_message, user_message, model="grok-4-1-fast-reasoning-latest")
        parsed = _parse_round_result(raw)
        if not parsed.get("markdown"):
            parsed["markdown"] = grok_markdown
        parsed["reference_pack_stats"] = ref_pack_stats
        return parsed
        
    except Exception as e:
        logger.error(f"Error calling Grok for review: {e}")
        return {
            "explanation": f"Error during review: {str(e)}",
            "markdown": grok_result.get("markdown", ""),
            "feedback": str(e),
            "is_complete": False,
        }









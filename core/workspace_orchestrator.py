from dataclasses import dataclass, field
from typing import List, Optional, Callable, Any, Dict
import os
import requests
import logging
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
from config import CONFIG_DIR
load_dotenv(os.path.join(CONFIG_DIR, ".env"))

logger = logging.getLogger(__name__)


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
                "is_complete": chatgpt_is_complete or grok_is_complete  # Complete if either agrees
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
                            "is_complete": True
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
        
        # Build file content summary (if files are provided)
        # With Grok 4.1 Fast Reasoning's 2M token context window, we can send full file contents
        file_summaries = []
        for file in task_spec.files:
            # Normalize path for lookup
            normalized_path = os.path.abspath(file.path)
            content = file_contents.get(normalized_path, "")
            if not content:
                # Try original path as fallback
                content = file_contents.get(file.path, "")
            if content:
                logger.info(f"Grok: Including content from {file.display_name} ({len(content)} chars)")
                # No truncation needed - Grok 4.1 Fast Reasoning has 2M token context window
                # Only add a note if file is extremely large (as a safeguard)
                file_summaries.append(f"### {file.display_name} ({file.file_type})\n{content}\n")
            else:
                logger.warning(f"Grok: No content found for {file.display_name} (path: {file.path})")
                logger.debug(f"Available keys in file_contents: {list(file_contents.keys())}")
        
        files_text = "\n".join(file_summaries) if file_summaries else ""
        has_files = len(file_summaries) > 0
        
        # Warn if files were expected but none were found
        if task_spec.files and not has_files:
            logger.warning(f"Grok: Expected {len(task_spec.files)} file(s) but none had content")
        
        # Build the prompt for Grok as Research Agent
        if round_num == 1:
            # First round: initial creation
            if has_files:
                system_message = """You are a research agent creating finished, publication-ready documents. 

CRITICAL INSTRUCTIONS:
- The markdown document you create must be a FINISHED, COMPLETE document ready for immediate use
- DO NOT include any conversational text, questions, or instructions in the markdown
- DO NOT include phrases like "paste the document when ready" or "please provide" or "if you have questions"
- The document must stand alone - no meta-commentary, no explanations, no questions to users
- The markdown should read like a professional, finished document, not an AI draft

Your output format:
1. First, write a brief explanation (this will be removed before delivery)
2. Then, on a new line starting with "#", provide ONLY the finished markdown document
3. The markdown must be complete and ready to use - no placeholders, no questions, no conversational text"""
                
                user_message = f"""Goal: {task_spec.goal}

Context: {task_spec.context or 'No additional context provided.'}

Current Date: {current_date}

Files to analyze:
{files_text}

Create a FINISHED, PUBLICATION-READY markdown document that:
1. Fully addresses the goal without needing any clarification
2. Is well-structured with clear headings and sections
3. Includes all relevant information from the files
4. Uses the current date ({current_date}) as reference for time-sensitive information
5. Contains NO conversational text, questions, or instructions
6. Is ready for immediate use as a professional document

Remember: This is a FINISHED document, not a draft with questions. Write as if it's going directly to the end user."""
            else:
                # No files - pure research task
                system_message = """You are a research agent creating finished, publication-ready documents.

CRITICAL INSTRUCTIONS:
- The markdown document you create must be a FINISHED, COMPLETE document ready for immediate use
- DO NOT include any conversational text, questions, or instructions in the markdown
- DO NOT include phrases like "paste the document when ready" or "please provide" or "if you have questions"
- The document must stand alone - no meta-commentary, no explanations, no questions to users
- The markdown should read like a professional, finished document, not an AI draft

Your output format:
1. First, write a brief explanation (this will be removed before delivery)
2. Then, on a new line starting with "#", provide ONLY the finished markdown document
3. The markdown must be complete and ready to use - no placeholders, no questions, no conversational text"""
                
                user_message = f"""Goal: {task_spec.goal}

Context: {task_spec.context or 'No additional context provided.'}

Current Date: {current_date}

Create a FINISHED, PUBLICATION-READY markdown document that:
1. Fully addresses the goal without needing any clarification
2. Is well-structured with clear headings and sections
3. Includes relevant information, examples, and details from your research
4. Uses the current date ({current_date}) as reference for time-sensitive information (e.g., "the past year" means from {current_date} going back one year)
5. Contains NO conversational text, questions, or instructions
6. Is ready for immediate use as a professional document

Remember: This is a FINISHED document, not a draft with questions. Write as if it's going directly to the end user."""
        else:
            # Subsequent rounds: review and edit collaboratively
            system_message = """You are a research agent refining a finished, publication-ready document.

CRITICAL INSTRUCTIONS:
- The markdown document must be a FINISHED, COMPLETE document ready for immediate use
- DO NOT include any conversational text, questions, or instructions in the markdown
- DO NOT include phrases like "paste the document when ready" or "please provide" or "if you have questions"
- The document must stand alone - no meta-commentary, no explanations, no questions to users
- Remove any conversational artifacts that may have been introduced

Your role:
1. Review the current markdown document (which may have been edited by ChatGPT)
2. Remove any conversational text, questions, or instructions
3. Ensure the document is finished and publication-ready
4. Make edits to improve clarity, completeness, and professionalism

Your output format:
1. First, write a brief explanation (this will be removed before delivery)
2. Then, on a new line starting with "#", provide ONLY the finished, clean markdown document
3. End with "FEEDBACK: [your feedback]" if more work is needed, or "COMPLETE: Document is ready" if finished"""
            
            user_message = f"""Goal: {task_spec.goal}

Context: {task_spec.context or 'No additional context provided.'}

Current Date: {current_date}

Files to analyze:
{files_text}

Collaboration Round: {round_num}

Previous Feedback:
{feedback or 'No specific feedback from previous round.'}

Current Markdown Document (may have been edited by ChatGPT):
{previous_markdown or 'No previous document.'}

IMPORTANT: Clean this document to be publication-ready:
1. Remove ALL conversational text, questions, or instructions (e.g., "paste when ready", "please provide", "if you have questions")
2. Ensure it's a finished, standalone document with no meta-commentary
3. Make any improvements needed for clarity, completeness, and professionalism
4. Use the current date ({current_date}) as reference for time-sensitive information

The output must be a clean, finished markdown document ready for immediate use - no placeholders, no questions, no conversational artifacts.

If satisfied, end with "COMPLETE: Document is ready and meets all requirements".
If more work is needed, end with "FEEDBACK: [specific feedback]".

Provide your explanation first, then the cleaned/revised markdown document starting with "#", then your completion status."""

        logger.debug("Grok API request via xAI SDK (grok_completion)")
        content = grok_completion(system_message, user_message, model="grok-4-1-fast-reasoning-latest")

        # Parse response to extract: explanation, markdown, feedback, and completion status
        lines = content.split('\n')
        
        # Look for FEEDBACK: or COMPLETE: markers at the end
        feedback = ""
        is_complete = False
        feedback_start_idx = -1
        complete_start_idx = -1
        
        for i, line in enumerate(lines):
            if line.strip().upper().startswith("FEEDBACK:"):
                feedback_start_idx = i
                feedback = line.replace("FEEDBACK:", "").strip()
                # Continue reading feedback lines until COMPLETE or end
                for j in range(i + 1, len(lines)):
                    if lines[j].strip().upper().startswith("COMPLETE:"):
                        break
                    feedback += "\n" + lines[j]
                feedback = feedback.strip()
            elif line.strip().upper().startswith("COMPLETE:"):
                complete_start_idx = i
                is_complete = True
                break
        
        # Remove feedback/complete sections from content for parsing
        content_for_parsing = content
        if feedback_start_idx >= 0:
            content_for_parsing = '\n'.join(lines[:feedback_start_idx])
        elif complete_start_idx >= 0:
            content_for_parsing = '\n'.join(lines[:complete_start_idx])
        
        # Try to separate explanation from markdown
        parsing_lines = content_for_parsing.split('\n')
        markdown_start = 0
        for i, line in enumerate(parsing_lines):
            if line.strip().startswith('#'):
                markdown_start = i
                break
        
        if markdown_start > 0:
            explanation = '\n'.join(parsing_lines[:markdown_start]).strip()
            markdown = '\n'.join(parsing_lines[markdown_start:]).strip()
        else:
            # No markdown headers found, assume it's all explanation or all markdown
            if content_for_parsing.strip().startswith('#'):
                explanation = f"Created markdown document for: {task_spec.goal}"
                markdown = content_for_parsing.strip()
            else:
                explanation = content_for_parsing.strip() or f"Research completed for: {task_spec.goal}"
                markdown = previous_markdown if previous_markdown else ""  # Keep previous if no new markdown
        
        # If complete, no feedback needed
        if is_complete:
            feedback = ""
        
        return {
            "explanation": explanation or f"Research completed for: {task_spec.goal}",
            "markdown": markdown,
            "feedback": feedback,
            "is_complete": is_complete
        }
        
    except Exception as e:
        logger.error(f"Error calling Grok API: {e}")
        return {
            "explanation": f"Error calling Grok API: {str(e)}",
            "markdown": f"# Error\n\nFailed to generate document: {str(e)}"
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
        
        # Build original source files section for ChatGPT to verify against
        files_text = ""
        if file_contents and task_spec.files:
            file_summaries = []
            for file in task_spec.files:
                # Normalize path for lookup
                normalized_path = os.path.abspath(file.path)
                content = file_contents.get(normalized_path, "")
                if not content:
                    # Try original path as fallback
                    content = file_contents.get(file.path, "")
                if content:
                    logger.info(f"ChatGPT: Including content from {file.display_name} ({len(content)} chars) for verification")
                    file_summaries.append(f"### {file.display_name} ({file.file_type})\n{content}\n")
                else:
                    logger.warning(f"ChatGPT: No content found for {file.display_name} (path: {file.path})")
            if file_summaries:
                files_text = "\n\nOriginal Source Files (for verification):\n" + "\n".join(file_summaries)
        
        system_message = """You are a document reviewer and editor creating finished, publication-ready documents.

CRITICAL INSTRUCTIONS:
- The markdown document you output must be FINISHED, COMPLETE, and ready for immediate use
- DO NOT include any conversational text, questions, or instructions in the markdown
- DO NOT include phrases like "paste the document when ready" or "please provide" or "if you have questions"
- The document must stand alone - no meta-commentary, no explanations, no questions to users
- Remove ANY conversational artifacts from the draft before outputting

Your role:
1. Review the draft markdown document from the research agent
2. Remove all conversational text, questions, and instructions
3. Improve clarity, structure, and completeness
4. Ensure the document is publication-ready

Your output format:
1. Start with your review explanation (this will be removed before delivery)
2. On a new line starting with "#", provide ONLY the cleaned, finished markdown document
3. End with either:
   - "FEEDBACK: [specific feedback]" if revision is needed
   - "COMPLETE: The document is ready and meets all requirements" if finished"""
        
        # Get current date for context
        current_date = datetime.now().strftime("%B %d, %Y")
        
        user_message = f"""Original Goal: {task_spec.goal}

Context: {task_spec.context or 'No additional context provided.'}

Current Date: {current_date}

Collaboration Round: {round_num}

Research Agent's Explanation:
{grok_explanation}
{files_text}

Draft Markdown Document:
{grok_markdown}

IMPORTANT: Clean and refine this document to be publication-ready:
1. Remove ALL conversational text, questions, or instructions (e.g., "paste when ready", "please provide", "if you have questions")
2. Ensure it's a finished, standalone document with no meta-commentary
3. Check that it fully addresses the goal without needing clarification
4. Verify accuracy against the original source files (provided above) to ensure Grok's work is correct and complete
5. Improve clarity, structure, and completeness
6. Verify time-sensitive references are accurate (current date is {current_date}, so "the past year" means from {current_date} going back one year)

The output must be a clean, finished markdown document ready for immediate use - no placeholders, no questions, no conversational artifacts.

If complete and ready, end with "COMPLETE: The document is ready and meets all requirements".
If improvements are needed, end with "FEEDBACK: [specific feedback]".

Provide your review explanation first, then the cleaned/refined markdown document starting with "#", then your completion status."""
        
        headers = {
            "Authorization": f"Bearer {openai_api_key}",
            "Content-Type": "application/json"
        }
        
        # Try GPT-5.2 first (400k context window), fallback to GPT-4o (128k)
        # No output token limits - let models generate full quality responses
        models_to_try = [
            ("gpt-5.2", 400000),  # 400k context window
            ("gpt-4o", 128000)     # 128k context window (fallback)
        ]
        response = None
        last_error = None
        used_model = None
        
        for model_name, context_window in models_to_try:
            try:
                data = {
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": user_message}
                    ],
                    "model": model_name,
                    "temperature": 0.7
                    # No max_tokens/max_completion_tokens - let model generate full quality responses
                }
                
                # Log the request for debugging
                logger.debug(f"OpenAI API request - Model: {model_name}, Endpoint: https://api.openai.com/v1/chat/completions")
                
                response = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=180
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
                logger.info(f"Successfully used {model_name} for review ({context_window//1000}k context window, no output token limit)")
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
        
        content = response_data['choices'][0]['message']['content']
        
        # Parse response to extract: explanation, markdown, feedback, and completion status
        lines = content.split('\n')
        
        # Look for FEEDBACK: or COMPLETE: markers at the end
        feedback = ""
        is_complete = False
        feedback_start_idx = -1
        complete_start_idx = -1
        
        for i, line in enumerate(lines):
            if line.strip().upper().startswith("FEEDBACK:"):
                feedback_start_idx = i
                feedback = line.replace("FEEDBACK:", "").strip()
                # Continue reading feedback lines until COMPLETE or end
                for j in range(i + 1, len(lines)):
                    if lines[j].strip().upper().startswith("COMPLETE:"):
                        break
                    feedback += "\n" + lines[j]
                feedback = feedback.strip()
            elif line.strip().upper().startswith("COMPLETE:"):
                complete_start_idx = i
                is_complete = True
                break
        
        # Remove feedback/complete sections from content for parsing
        content_for_parsing = content
        if feedback_start_idx >= 0:
            content_for_parsing = '\n'.join(lines[:feedback_start_idx])
        elif complete_start_idx >= 0:
            content_for_parsing = '\n'.join(lines[:complete_start_idx])
        
        # Try to separate explanation from markdown
        parsing_lines = content_for_parsing.split('\n')
        markdown_start = 0
        for i, line in enumerate(parsing_lines):
            if line.strip().startswith('#'):
                markdown_start = i
                break
        
        if markdown_start > 0:
            explanation = '\n'.join(parsing_lines[:markdown_start]).strip()
            markdown = '\n'.join(parsing_lines[markdown_start:]).strip()
        else:
            # No markdown headers found, assume it's all explanation or all markdown
            if content_for_parsing.strip().startswith('#'):
                explanation = f"Reviewed document for: {task_spec.goal}"
                markdown = content_for_parsing.strip()
            else:
                explanation = content_for_parsing.strip() or f"Reviewed document for: {task_spec.goal}"
                markdown = grok_markdown  # Keep original if no markdown provided
        
        # If complete, no feedback needed
        if is_complete:
            feedback = ""
        
        return {
            "explanation": explanation or f"Review completed for: {task_spec.goal}",
            "markdown": markdown if markdown else grok_markdown,  # Use refined or keep original
            "feedback": feedback,
            "is_complete": is_complete
        }
        
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

        # Build original source files section if available
        files_text = ""
        if file_contents and task_spec.files:
            file_summaries = []
            for file in task_spec.files:
                normalized_path = os.path.abspath(file.path)
                content = file_contents.get(normalized_path, "") or file_contents.get(file.path, "")
                if content:
                    file_summaries.append(f"### {file.display_name} ({file.file_type})\n{content}\n")
            if file_summaries:
                files_text = "\n\nOriginal Source Files (for verification):\n" + "\n".join(file_summaries)

        system_message = """You are a document reviewer and editor. Review the draft markdown document and refine it for clarity, structure, and completeness."""

        # Get current date for context
        current_date = datetime.now().strftime("%B %d, %Y")

        user_message = f"""Original Goal: {task_spec.goal}

Current Date: {current_date}
{files_text}

Draft Markdown Document:
{grok_markdown}

Please review and refine this document. Make improvements for clarity, structure, and completeness. If original source files are provided above, verify the draft against them for accuracy. Remember: The current date is {current_date}. Use this as a reference for any time-sensitive information.

Respond with your review explanation first, followed by the refined markdown document."""

        content = grok_completion(system_message, user_message, model="grok-4-1-fast-reasoning-latest")
        
        # Try to separate explanation from markdown
        lines = content.split('\n')
        markdown_start = 0
        for i, line in enumerate(lines):
            if line.strip().startswith('#'):
                markdown_start = i
                break
        
        if markdown_start > 0:
            explanation = '\n'.join(lines[:markdown_start]).strip()
            markdown = '\n'.join(lines[markdown_start:]).strip()
        else:
            explanation = f"Reviewed document for: {task_spec.goal}"
            markdown = content
        
        return {
            "explanation": explanation or f"Review completed for: {task_spec.goal}",
            "markdown": markdown
        }
        
    except Exception as e:
        logger.error(f"Error calling Grok for review: {e}")
        return {
            "explanation": f"Error during review: {str(e)}",
            "markdown": grok_result.get("markdown", "")
        }









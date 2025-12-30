from dataclasses import dataclass, field
from typing import List, Optional, Callable, Any, Dict


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
    ):
        """
        Parameters:
            logger: optional logger with .info/.error methods; if None, uses print
            grok_call: optional override to call the real Grok API
            chatgpt_call: optional override to call the real ChatGPT/OpenAI API

        If grok_call or chatgpt_call is None, we use stub implementations.
        """
        self.logger = logger or self._default_logger
        self._grok_call = grok_call
        self._chatgpt_call = chatgpt_call

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run_once(self, task_spec: WorkspaceTaskSpec) -> Dict[str, str]:
        """
        One-shot workflow:
          1) Call Grok (or stub) to act as 'Research Agent'
          2) Call ChatGPT (or stub) to act as 'Reviewer / Editor'

        Returns a dict with:
          {
              "grok_output": str,     # Grok's explanation / research summary
              "chatgpt_output": str,  # ChatGPT's review / meta commentary
              "markdown": str,        # The resulting markdown document
          }

        Later we can expand this into a multi-round loop using task_spec.max_rounds.
        """
        self.logger("DualLLMOrchestrator.run_once: starting workflow")

        # 1) Ask Grok to research and propose initial markdown
        grok_result = self._call_grok(task_spec)
        grok_output = grok_result.get("explanation", "")
        initial_markdown = grok_result.get("markdown", "")

        # 2) Ask ChatGPT to review and refine the markdown
        chatgpt_result = self._call_chatgpt(task_spec, grok_result)
        chatgpt_output = chatgpt_result.get("explanation", "")
        refined_markdown = chatgpt_result.get("markdown", initial_markdown)

        self.logger("DualLLMOrchestrator.run_once: workflow completed")

        return {
            "grok_output": grok_output,
            "chatgpt_output": chatgpt_output,
            "markdown": refined_markdown or initial_markdown,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _call_grok(self, task_spec: WorkspaceTaskSpec) -> Dict[str, str]:
        """
        Call Grok (or stub) as the 'Research Agent'.
        Expected return dict keys:
          - "explanation": natural language explanation
          - "markdown": a markdown draft string
        """
        if self._grok_call is not None:
            self.logger("DualLLMOrchestrator._call_grok: using injected grok_call")
            return self._grok_call(task_spec)

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

    def _call_chatgpt(self, task_spec: WorkspaceTaskSpec, grok_result: Dict[str, str]) -> Dict[str, str]:
        """
        Call ChatGPT (or stub) as the 'Reviewer / Editor'.
        Receives:
          - task_spec
          - grok_result: the dict returned by _call_grok

        Expected return dict keys:
          - "explanation": natural language explanation of review
          - "markdown": refined markdown (or empty if no changes)
        """
        if self._chatgpt_call is not None:
            self.logger("DualLLMOrchestrator._call_chatgpt: using injected chatgpt_call")
            return self._chatgpt_call(task_spec, grok_result)

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
        }

    @staticmethod
    def _default_logger(msg: str):
        print(msg)







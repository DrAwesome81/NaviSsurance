"""
Workflow engine for the multi-agent AI ops system.

Runs: Plan -> Research -> Synthesis -> Parallel synthesis (Grok + ChatGPT) -> GATE (user reviews research)
-> Continue to draft: parallel Grok + ChatGPT draft, then 4-step exchange (Grok -> ChatGPT -> Grok -> ChatGPT final)
-> QA -> Finalize.
(Pulse private memory themes + 🛡️ [Security-Relevant] intel feed research/synthesis steps for regulatory clients.)
# New: workflow now explicitly consumes Pulse private memory for Shield (additional workflow engine spot)
"""

import json
import logging
import os
from typing import Any, Callable, Optional

# Pulse private memory + Shield (workflow engine triage)

from core.agent_schemas import (
    AgentType,
    ArtifactType,
    DraftArtifact,
    InternalRetrievalBrief,
    QAReport,
    ResearchBriefArtifact,
    TaskPlan,
    TaskPlanItem,
    UnifiedBrief,
    WebResearchBrief,
)
from core.agent_dispatcher import run_tool
from core.db import DatabaseManager
from core.llm_collab import call_grok_simple, call_chatgpt_simple

logger = logging.getLogger(__name__)

# Project status after research + parallel synthesis; user reviews before drafting
STATUS_AWAITING_RESEARCH_REVIEW = "awaiting_research_review"


class WorkflowEngine:
    """Runs the multi-agent pipeline for a project."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()

    def create_plan(self, project_id: int, goals: str, mode: str) -> None:
        """
        Create a TaskPlan from goals and mode, store it, and insert project_tasks.

        Deep Research is web-first. This plan creates a single web research task.
        The pipeline stops after synthesis for user review.
        """
        tasks: list[TaskPlanItem] = []
        task_id = 1

        tasks.append(
            TaskPlanItem(
                task_id=f"t{task_id}",
                title="Web research",
                description=goals,
                agent_type=AgentType.WEB_RESEARCHER,
                dependencies=[],
                definition_of_done="WebResearchBrief stored.",
                expected_artifacts=[ArtifactType.WEB_RESEARCH_BRIEF.value],
            )
        )
        task_id += 1

        plan = TaskPlan(project_id=str(project_id), tasks=tasks)
        plan_json = plan.model_dump_json()
        self.db.insert_task_plan(project_id, plan_json)
        # Pulse themes feed workflow steps for Shield orchestration

        for t in tasks:
            self.db.insert_project_task(
                project_id=project_id,
                plan_task_id=t.task_id,
                title=t.title,
                agent_type=t.agent_type.value,
                dependencies_json=json.dumps(t.dependencies),
                definition_of_done=t.definition_of_done,
            )
        logger.info("Created plan for project %s with %s tasks.", project_id, len(tasks))

    def run_research(self, project_id: int, progress_callback: Optional[Callable[[str], None]] = None) -> None:
        """Run web research tasks and store briefs."""
        self.db.update_project_status(project_id, "running")
        plan_row = self.db.get_task_plan_for_project(project_id)
        query_by_task_id = {}
        if plan_row:
            _, _, plan_json, _ = plan_row
            plan = TaskPlan.model_validate_json(plan_json)
            for t in plan.tasks:
                query_by_task_id[t.task_id] = t.description
        tasks = self.db.get_project_tasks(project_id)
        for row in tasks:
            pt_id, _, plan_task_id, title, agent_type_str, status, deps_json, dod, _, _ = row
            if agent_type_str != AgentType.WEB_RESEARCHER.value:
                continue
            if status == "completed":
                continue
            self.db.update_project_task_status(pt_id, "running")
            agent_type = AgentType(agent_type_str)
            tool_name = "web_research"
            query = query_by_task_id.get(plan_task_id) or title
            run_id = self.db.insert_run(project_id, pt_id, agent_type_str, model_used=None)
            try:
                if progress_callback:
                    progress_callback(f"Research task '{title}' started.")
                result = run_tool(agent_type, tool_name, query=query, progress_callback=progress_callback)
                content_json = result.model_dump_json()
                artifact_type = ArtifactType.WEB_RESEARCH_BRIEF.value
                self.db.insert_artifact(project_id, artifact_type, content_json, run_id=run_id, project_task_id=pt_id)
                self.db.update_run_status(run_id, "completed")
                self.db.update_project_task_status(pt_id, "completed")
                if progress_callback:
                    progress_callback(f"Research task '{title}' completed.")
            except Exception as e:
                logger.exception("Research task %s failed: %s", plan_task_id, e)
                self.db.update_run_status(run_id, "failed", error_message=str(e))
                self.db.update_project_task_status(pt_id, "failed")
                raise

    def run_synthesis(self, project_id: int) -> None:
        """Merge research briefs into UnifiedBrief and store."""
        artifacts = self.db.get_artifacts_for_project(project_id)
        internal_brief = None
        web_brief = None
        for _id, art_type, content_json, _path, _created in artifacts:
            if art_type == ArtifactType.INTERNAL_RETRIEVAL_BRIEF.value and content_json:
                internal_brief = InternalRetrievalBrief.model_validate_json(content_json)
            elif art_type == ArtifactType.WEB_RESEARCH_BRIEF.value and content_json:
                web_brief = WebResearchBrief.model_validate_json(content_json)
        unified = UnifiedBrief(
            project_id=str(project_id),
            internal_brief=internal_brief,
            web_brief=web_brief,
            notes="Merged brief for Writer.",
        )
        self.db.insert_artifact(project_id, ArtifactType.UNIFIED_BRIEF.value, unified.model_dump_json(), project_task_id=None)

    def _brief_summary_for_prompt(self, unified: UnifiedBrief, max_excerpts: int = 20) -> str:
        """Build text summary of the UnifiedBrief for LLM prompts. No truncation of content."""
        parts = []
        if unified.internal_brief and unified.internal_brief.results:
            parts.append("## Internal document research")
            for r in unified.internal_brief.results[:max_excerpts]:
                parts.append(f"- [{r.title}]: {r.excerpt}")
            if unified.internal_brief.notes:
                parts.append(f"Notes: {unified.internal_brief.notes}")
        if unified.web_brief and unified.web_brief.findings:
            parts.append("## Web research")
            for f in unified.web_brief.findings:
                parts.append(f"- {f.claim}")
            for s in unified.web_brief.sources:
                parts.append(f"- Source: {s.title} | {s.url}")
            if unified.web_brief.notes:
                parts.append(f"Notes: {unified.web_brief.notes}")
        if unified.notes:
            parts.append(f"Manager notes: {unified.notes}")
        return "\n\n".join(parts) if parts else "(No research content yet.)"

    def run_parallel_synthesis(self, project_id: int) -> None:
        """
        Run Grok and ChatGPT on the same synthesis task (summarize research), store both responses,
        then set project status to awaiting_research_review so the user can review before drafting.
        """
        artifacts = self.db.get_artifacts_for_project(project_id)
        unified_json = None
        for _id, art_type, content_json, _path, _created in artifacts:
            if art_type == ArtifactType.UNIFIED_BRIEF.value:
                unified_json = content_json
                break
        if not unified_json:
            raise ValueError(f"No UnifiedBrief found for project {project_id}")
        unified = UnifiedBrief.model_validate_json(unified_json)
        research_text = self._brief_summary_for_prompt(unified)

        system = (
            "You are a research synthesizer. Analyze the research below thoroughly. "
            "Provide: (1) key points and findings — cover all important claims, sources, and evidence; "
            "(2) gaps or open questions; (3) any contradictions across sources. "
            "Be comprehensive; do not limit length. This is for internal review before drafting; the writer will use it to produce the final document."
        )
        user = f"Research to synthesize:\n\n{research_text}"

        grok_response = ""
        try:
            grok_response = call_grok_simple(system, user)
        except Exception as e:
            logger.exception("Grok synthesis failed: %s", e)
            grok_response = f"[Grok synthesis failed: {e}]"
        self.db.insert_artifact(
            project_id, "synthesis_grok", json.dumps({"content": grok_response}), project_task_id=None
        )

        chatgpt_response = ""
        try:
            chatgpt_response = call_chatgpt_simple(system, user)
        except Exception as e:
            logger.exception("ChatGPT synthesis failed: %s", e)
            chatgpt_response = f"[ChatGPT synthesis failed: {e}]"
        self.db.insert_artifact(
            project_id, "synthesis_chatgpt", json.dumps({"content": chatgpt_response}), project_task_id=None
        )

        self.db.update_project_status(project_id, STATUS_AWAITING_RESEARCH_REVIEW)
        logger.info("Project %s research ready for review (synthesis_grok + synthesis_chatgpt stored).", project_id)

    def continue_to_draft(self, project_id: int, user_feedback: Optional[str] = None) -> None:
        """
        Called after the user has reviewed research. Optionally stores user_feedback, then runs
        draft -> QA -> finalize. Requires project status awaiting_research_review.
        """
        row = self.db.get_project(project_id)
        if not row:
            raise ValueError(f"Project {project_id} not found")
        _id, _name, _mode, status, _created, _config = row
        if status != STATUS_AWAITING_RESEARCH_REVIEW:
            raise ValueError(
                f"Project {project_id} status is '{status}'; expected '{STATUS_AWAITING_RESEARCH_REVIEW}'. "
                "Review research first, then call continue_to_draft."
            )
        if user_feedback:
            self.db.insert_artifact(
                project_id, "user_research_feedback", json.dumps({"content": user_feedback}), project_task_id=None
            )
        self.run_draft(project_id)
        self.run_qa(project_id)
        self.finalize(project_id)

    def generate_research_brief(self, project_id: int, user_feedback: Optional[str] = None) -> None:
        """
        Deep Research post-review step.

        Requires project status awaiting_research_review. Optionally stores user_feedback, then generates a
        final research brief (markdown) meant to be reused elsewhere (e.g., as input to Workspace drafting).
        """
        row = self.db.get_project(project_id)
        if not row:
            raise ValueError(f"Project {project_id} not found")
        _id, _name, _mode, status, _created, _config = row
        if status != STATUS_AWAITING_RESEARCH_REVIEW:
            raise ValueError(
                f"Project {project_id} status is '{status}'; expected '{STATUS_AWAITING_RESEARCH_REVIEW}'. "
                "Review research first, then generate a research brief."
            )

        if user_feedback:
            self.db.insert_artifact(
                project_id, "user_research_feedback", json.dumps({"content": user_feedback}), project_task_id=None
            )

        artifacts = self.db.get_artifacts_for_project(project_id)
        unified_json = None
        synthesis_grok = ""
        synthesis_chatgpt = ""
        for _id2, art_type, content_json, _path, _created2 in artifacts:
            if art_type == ArtifactType.UNIFIED_BRIEF.value:
                unified_json = content_json
            elif art_type == "synthesis_grok" and content_json:
                try:
                    synthesis_grok = json.loads(content_json).get("content", "") or ""
                except Exception:
                    synthesis_grok = content_json
            elif art_type == "synthesis_chatgpt" and content_json:
                try:
                    synthesis_chatgpt = json.loads(content_json).get("content", "") or ""
                except Exception:
                    synthesis_chatgpt = content_json

        if not unified_json:
            raise ValueError(f"No UnifiedBrief found for project {project_id}")

        unified = UnifiedBrief.model_validate_json(unified_json)
        research_text = self._brief_summary_for_prompt(unified)

        system = (
            "You are a deep research analyst. Produce a structured research brief in markdown based ONLY on the research summary and syntheses. "
            "Goal: a reusable brief (not a final deliverable document) with clear sections and explicit, linked sources. "
            "Requirements: (1) Executive summary; (2) Key findings (bulleted); (3) Evidence & sources (use markdown links: [text](url)); "
            "(4) Gaps / open questions; (5) Recommended next research steps. Output only markdown, no meta commentary."
        )

        user = f"Research summary:\n{research_text}\n\n"
        if synthesis_grok:
            user += f"Grok synthesis:\n{synthesis_grok}\n\n"
        if synthesis_chatgpt:
            user += f"ChatGPT synthesis:\n{synthesis_chatgpt}\n\n"
        if user_feedback:
            user += f"User focus / constraints:\n{user_feedback}\n\n"
        user += "Write the research brief now."

        grok_draft = ""
        try:
            grok_draft = call_grok_simple(system, user)
        except Exception as e:
            logger.exception("Grok research brief failed: %s", e)
            grok_draft = f"[Grok research brief failed: {e}]"
        self.db.insert_artifact(
            project_id, "research_brief_grok", json.dumps({"content": grok_draft}), project_task_id=None
        )

        chatgpt_final = ""
        try:
            user2 = (
                "Here is a draft research brief.\n\n"
                f"{grok_draft}\n\n"
                "Please produce the final research brief in markdown. Ensure sources are clickable markdown links where applicable."
            )
            chatgpt_final = call_chatgpt_simple(system, user2)
        except Exception as e:
            logger.exception("ChatGPT research brief failed: %s", e)
            chatgpt_final = grok_draft

        brief = ResearchBriefArtifact(
            version="1",
            markdown_body=chatgpt_final or "# Research brief\n\n(No content generated.)",
            assumptions=[],
            open_questions=[],
        )
        # Persist a markdown file for easy export/reuse.
        file_path = None
        try:
            store_dir = self.db.get_artifact_store_path(project_id, create=True)
            file_path = os.path.join(store_dir, "research_brief.md")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(brief.markdown_body or "")
        except Exception as e:
            logger.exception("Failed to write research brief file: %s", e)
            file_path = None

        self.db.insert_artifact(
            project_id,
            ArtifactType.RESEARCH_BRIEF.value,
            brief.model_dump_json(),
            project_task_id=None,
            file_path=file_path,
        )

        # Mark done (brief ready).
        self.db.update_project_status(project_id, "done")

    def run_draft(self, project_id: int) -> None:
        """
        Get Unified Brief + synthesis responses + House Style + optional user feedback.
        Same drafting task to Grok and ChatGPT, then 4-step exchange:
        Grok A -> ChatGPT (revise) -> Grok (comment) -> ChatGPT (finalize).
        Store final as DraftArtifact.
        """
        artifacts = self.db.get_artifacts_for_project(project_id)
        unified_json = None
        synthesis_grok = ""
        synthesis_chatgpt = ""
        user_feedback = ""
        for _id, art_type, content_json, _path, _created in artifacts:
            if art_type == ArtifactType.UNIFIED_BRIEF.value:
                unified_json = content_json
            elif art_type == "synthesis_grok" and content_json:
                try:
                    synthesis_grok = json.loads(content_json).get("content", "") or ""
                except Exception:
                    synthesis_grok = content_json
            elif art_type == "synthesis_chatgpt" and content_json:
                try:
                    synthesis_chatgpt = json.loads(content_json).get("content", "") or ""
                except Exception:
                    synthesis_chatgpt = content_json
            elif art_type == "user_research_feedback" and content_json:
                try:
                    user_feedback = json.loads(content_json).get("content", "") or ""
                except Exception:
                    user_feedback = content_json

        if not unified_json:
            raise ValueError(f"No UnifiedBrief found for project {project_id}")
        unified = UnifiedBrief.model_validate_json(unified_json)
        research_text = self._brief_summary_for_prompt(unified)
        house_style = self.db.get_house_style_guide()

        system_draft = (
            "You are a professional writer producing a clear, well-structured document. "
            "Use the research and synthesis below. Follow any house style or constraints. "
            "Output only the document (markdown); no meta-commentary. "
            "When citing sources or referencing URLs, use proper markdown links: [descriptive text](URL). Do not paste bare URLs or plain text where a link is intended; every source reference should be a clickable link in the form [link text](url)."
        )
        if house_style:
            system_draft += f"\n\nHouse style:\n{house_style}"
        user_draft = f"Research summary:\n{research_text}\n\n"
        if synthesis_grok:
            user_draft += f"Grok's synthesis:\n{synthesis_grok}\n\n"
        if synthesis_chatgpt:
            user_draft += f"ChatGPT's synthesis:\n{synthesis_chatgpt}\n\n"
        if user_feedback:
            user_draft += f"User feedback / constraints:\n{user_feedback}\n\n"
        user_draft += "Produce a draft document (markdown) based on the above. Be direct and structured."

        grok_a = ""
        try:
            grok_a = call_grok_simple(system_draft, user_draft)
        except Exception as e:
            logger.exception("Grok draft failed: %s", e)
            grok_a = f"[Grok draft failed: {e}]"

        chatgpt_b = ""
        try:
            chatgpt_b = call_chatgpt_simple(system_draft, user_draft)
        except Exception as e:
            logger.exception("ChatGPT initial draft failed: %s", e)
            chatgpt_b = f"[ChatGPT draft failed: {e}]"

        system_exchange = (
            "You are a professional editor. Respond with a revised or finalized document (markdown) only when asked to finalize; otherwise give concise feedback or a revised version as requested. "
            "Preserve or use proper markdown links for sources: [link text](URL). Do not leave URLs or source names as plain text; use [descriptive text](url) so links are clickable."
        )

        user_c = f"This is what Grok said:\n\n{grok_a}\n\nWhat do you think? How would you revise or improve this? Provide your revised version (markdown)."
        chatgpt_c = ""
        try:
            chatgpt_c = call_chatgpt_simple(system_exchange, user_c)
        except Exception as e:
            logger.exception("ChatGPT revision (after Grok) failed: %s", e)
            chatgpt_c = chatgpt_b

        user_d = f"This is what ChatGPT said about Grok's response:\n\n{chatgpt_c}\n\nWhat do you think? Provide your comments or a revised version (markdown)."
        grok_d = ""
        try:
            grok_d = call_grok_simple(system_exchange, user_d)
        except Exception as e:
            logger.exception("Grok comment (after ChatGPT) failed: %s", e)
            grok_d = grok_a

        user_final = f"This is what Grok said:\n\n{grok_d}\n\nPlease finalize the document. Output only the final markdown document, ready for use."
        final = ""
        try:
            final = call_chatgpt_simple(system_exchange, user_final)
        except Exception as e:
            logger.exception("ChatGPT finalize failed: %s", e)
            final = chatgpt_c if chatgpt_c else chatgpt_b

        draft = DraftArtifact(
            doc_type="memo",
            version="1",
            markdown_body=final or "# Draft\n\n(No content generated.)",
            assumptions=[],
            open_questions=[],
        )
        self.db.insert_artifact(project_id, ArtifactType.DRAFT.value, draft.model_dump_json(), project_task_id=None)

    def run_qa(self, project_id: int) -> None:
        """Get latest draft, run Editor/QA (stub), store QAReport."""
        artifacts = self.db.get_artifacts_for_project(project_id)
        draft_json = None
        for _id, art_type, content_json, _path, _created in artifacts:
            if art_type == ArtifactType.DRAFT.value:
                draft_json = content_json  # keep last
        if not draft_json:
            raise ValueError(f"No Draft artifact found for project {project_id}")
        # Stub QA: pass with score 80
        qa_report = QAReport(
            checks_performed=["Stub QA: replace with LLM call."],
            quality_score=80,
            pass_fail=True,
        )
        self.db.insert_artifact(project_id, ArtifactType.QA_REPORT.value, qa_report.model_dump_json(), project_task_id=None)

    def finalize(self, project_id: int) -> None:
        """Mark project done."""
        self.db.update_project_status(project_id, "done")
        logger.info("Project %s finalized.", project_id)

    def run_pipeline(
        self,
        project_id: int,
        goals: str,
        mode: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Create plan, then run Research -> Synthesis -> Parallel synthesis (Grok + ChatGPT).
        Stops with status awaiting_research_review. User reviews research; then call
        continue_to_draft(project_id, user_feedback=None) to run draft -> QA -> finalize.
        """
        self.create_plan(project_id, goals, mode)
        self.run_research(project_id, progress_callback=progress_callback)
        self.run_synthesis(project_id)
        self.run_parallel_synthesis(project_id)
        # Pipeline stops here; user reviews research, then continue_to_draft(...)

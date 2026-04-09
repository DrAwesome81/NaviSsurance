"""
Developer / demo orchestration: Deep Research → Workspace → draft → tasks → sample assignment.

Triggered from the main window (hidden shortcut). Runs live APIs and may take several minutes.
"""

from __future__ import annotations

import json
import logging

from PyQt6.QtCore import QThread, pyqtSignal

from core.db import DatabaseManager
from core.workflow_engine import STATUS_AWAITING_RESEARCH_REVIEW, WorkflowEngine

logger = logging.getLogger(__name__)

# Same substance as docs/demo_script_ceo_7min.md (condensed names for DB).
DEMO_RESEARCH_NAME = "CEO Demo — AI triage regulatory path"

DEMO_RESEARCH_GOALS = (
    "Regulatory path options for an AI triage tool that flags high-risk ECGs for clinician review; "
    "US first; likely De Novo vs 510(k); include competitor signals and evidence expectations."
)

# Workspace collaboration instruction: CEO memo + importable tasks (exact line format for parse_suggested_tasks).
DEMO_WORKSPACE_PROMPT = (
    "Draft a CEO strategy memo with: executive summary, recommended regulatory path (primary + fallback), "
    "evidence plan, timeline, top risks, and next 30/60/90 days.\n\n"
    "End with a section exactly titled:\n## Suggested Tasks (importable)\n\n"
    "Under that header, add at least three realistic tasks, one per line, using exactly this pattern "
    "(replace fields appropriately):\n"
    "- [ ] Short action-oriented title | due: MM-DD-YYYY or none | category: Business | priority: P3\n\n"
    "Use category Business for all demo tasks. Use priorities P3–P5 where appropriate."
)


def load_final_research_brief_markdown(db: DatabaseManager, project_id: int) -> str:
    """Return markdown body from the persisted research_brief artifact, if present."""
    arts = db.get_artifacts_for_project(int(project_id))
    for _aid, art_type, content_json, _path, _created in arts:
        if art_type == "research_brief" and content_json:
            try:
                data = json.loads(content_json)
                body = str(data.get("markdown_body") or "").strip()
                if body:
                    return body
            except Exception:
                continue
        if art_type == "research_brief_grok" and content_json:
            try:
                data = json.loads(content_json)
                c = str(data.get("content") or "").strip()
                if c:
                    return c
            except Exception:
                continue
    return ""


class DemoFullCycleResearchWorker(QThread):
    """Run create_project → pipeline → generate_research_brief in a background thread."""

    finished_ok = pyqtSignal(str, int)  # brief_markdown, project_id
    failed = pyqtSignal(str)
    status_message = pyqtSignal(str)

    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db

    def run(self):
        try:
            eng = WorkflowEngine(self.db)
            pid = int(self.db.create_project(DEMO_RESEARCH_NAME, "web_only"))
            self.status_message.emit(f"Deep research starting (project {pid})…")

            def _progress(msg: str) -> None:
                self.status_message.emit(str(msg or "").strip() or "Working…")

            eng.run_pipeline(pid, DEMO_RESEARCH_GOALS, "web_only", progress_callback=_progress)

            row = self.db.get_project(pid)
            if not row:
                self.failed.emit("Research project not found after pipeline.")
                return

            _id, _name, _mode, status, _created, _config = row
            if status != STATUS_AWAITING_RESEARCH_REVIEW:
                self.failed.emit(f"Unexpected project status after pipeline: {status!r}")
                return

            self.status_message.emit("Generating final research brief…")
            eng.generate_research_brief(pid, None)

            brief = load_final_research_brief_markdown(self.db, pid)
            if not brief.strip():
                self.failed.emit("Research finished but no brief markdown was found.")
                return

            self.finished_ok.emit(brief.strip(), pid)
        except Exception as e:
            logger.exception("Demo full cycle research phase failed: %s", e)
            self.failed.emit(str(e))

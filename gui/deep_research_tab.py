"""
Deep Research tab for the multi-step research workflow.

This tab is intentionally separate from the collaborative drafting workflow in the Workspace tab.
It runs research (internal and/or web), produces synthesis artifacts for review, then generates a
final *research brief* (markdown) that can be reused elsewhere.
"""

from __future__ import annotations

import json
import logging

from PyQt6.QtCore import Qt, QSettings, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.db import DatabaseManager
from core.workflow_engine import STATUS_AWAITING_RESEARCH_REVIEW, WorkflowEngine
from gui.agent_console import AgentConsole

logger = logging.getLogger(__name__)


class PipelineWorker(QThread):
    """Run run_pipeline(project_id, goals, mode) in background."""

    finished_signal = pyqtSignal(int)  # project_id on success
    error_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)

    def __init__(self, db: DatabaseManager, project_id: int, goals: str, mode: str):
        super().__init__()
        self.db = db
        self.project_id = project_id
        self.goals = goals
        self.mode = mode

    def run(self):
        try:
            self.status_signal.emit("Running research and synthesis...")
            eng = WorkflowEngine(self.db)
            eng.run_pipeline(self.project_id, self.goals, self.mode, progress_callback=self.status_signal.emit)
            self.status_signal.emit("Research ready for review.")
            self.finished_signal.emit(self.project_id)
        except Exception as e:
            logger.exception("Deep research pipeline failed: %s", e)
            self.error_signal.emit(str(e))


class ContinueBriefWorker(QThread):
    """Run generate_research_brief(project_id, user_feedback) in background."""

    finished_signal = pyqtSignal(int)  # project_id on success
    error_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)

    def __init__(self, db: DatabaseManager, project_id: int, user_feedback: str | None = None):
        super().__init__()
        self.db = db
        self.project_id = project_id
        self.user_feedback = user_feedback or ""

    def run(self):
        try:
            self.status_signal.emit("Generating final research brief...")
            eng = WorkflowEngine(self.db)
            eng.generate_research_brief(self.project_id, self.user_feedback or None)
            self.status_signal.emit("Done.")
            self.finished_signal.emit(self.project_id)
        except Exception as e:
            logger.exception("Generate research brief failed: %s", e)
            self.error_signal.emit(str(e))


def _format_artifact_for_display(artifact_type: str, content_json: str) -> str:
    """Turn stored JSON into readable text for the UI."""

    if not content_json:
        return "(No content)"

    try:
        data = json.loads(content_json)

        if artifact_type == "internal_retrieval_brief":
            results = data.get("results", [])
            lines = [f"Query: {data.get('query', '')}", ""]
            for i, r in enumerate(results[:15], 1):
                lines.append(f"--- Result {i}: {r.get('title', '')} ---")
                excerpt = r.get("excerpt", "") or ""
                lines.append(excerpt[:600] + ("..." if len(excerpt) > 600 else ""))
                lines.append("")
            if data.get("notes"):
                lines.append(f"Notes: {data['notes']}")
            if data.get("gaps_or_questions"):
                lines.append("")
                lines.append("Gaps / questions:")
                for g in data["gaps_or_questions"]:
                    lines.append(f"- {g}")
            return "\n".join(lines)

        if artifact_type == "web_research_brief":
            findings = data.get("findings", [])
            sources = data.get("sources", [])
            lines = [f"Query: {data.get('query', '')}", ""]
            for f in findings:
                claim = f.get("claim", "") or ""
                if claim:
                    lines.append(f"Finding: {claim}")
            if findings:
                lines.append("")
            for s in sources:
                lines.append(f"Source: {s.get('title', '')} | {s.get('url', '')}")
            if data.get("notes"):
                lines.append(f"Notes: {data['notes']}")
            if data.get("contradictions"):
                lines.append("")
                lines.append("Contradictions:")
                for c in data["contradictions"]:
                    topic = c.get("topic", "") or ""
                    lines.append(f"- {topic}")
            return "\n".join(lines)

        if artifact_type in ("synthesis_grok", "synthesis_chatgpt", "research_brief_grok"):
            return data.get("content", content_json)

        if artifact_type == "user_research_feedback":
            return data.get("content", content_json)

        if artifact_type == "research_brief":
            return data.get("markdown_body", content_json)

        # Legacy compatibility
        if artifact_type == "draft":
            return data.get("markdown_body", content_json)

        return content_json
    except Exception:
        return content_json


class DeepResearchTab(QWidget):
    """Tab for running deep research (research -> review -> final research brief)."""

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self._current_project_id: int | None = None
        self._pipeline_worker: PipelineWorker | None = None
        self._brief_worker: ContinueBriefWorker | None = None
        self._settings = QSettings("NaviSsurance", "DeepResearchTab")
        self.setup_ui()
        self._load_state()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("Deep Research")
        title.setStyleSheet("color: #e8eaed; font-weight: 700; font-size: 14px; margin: 0;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Use this to run web deep research and produce a final research brief (markdown). "
            "This is separate from the Workspace collaborative drafting workflow."
        )
        subtitle.setStyleSheet("color: #9aa0a6; font-size: 12px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # --- Form ---
        form_group = QGroupBox("New deep research run")
        form_layout = QVBoxLayout(form_group)

        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Research name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. EEG-cleared devices brief")
        name_layout.addWidget(self.name_edit)
        form_layout.addLayout(name_layout)

        form_layout.addWidget(QLabel("Research objective / question:"))
        self.goals_edit = QTextEdit()
        self.goals_edit.setPlaceholderText("e.g. cleared medical devices that analyze EEG data")
        self.goals_edit.setMaximumHeight(90)
        form_layout.addWidget(self.goals_edit)

        self.auto_generate_checkbox = QCheckBox("Auto-generate final research brief when research completes")
        self.auto_generate_checkbox.setChecked(True)
        form_layout.addWidget(self.auto_generate_checkbox)

        self.start_btn = QPushButton("Start deep research")
        self.start_btn.clicked.connect(self.on_start_project)
        form_layout.addWidget(self.start_btn)
        layout.addWidget(form_group)

        # --- Status ---
        self.status_label = QLabel("Deep research status: —")
        self.status_label.setStyleSheet("color: #6b8cae; font-weight: 600; font-size: 13px;")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate when running
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # --- Splitter: review area (top) and final brief (bottom) ---
        splitter = QSplitter(Qt.Orientation.Vertical)

        review_widget = QWidget()
        review_layout = QVBoxLayout(review_widget)
        review_layout.addWidget(QLabel("Research artifacts to review (after pipeline runs):"))

        self.artifact_tabs = QTabWidget()
        self.artifact_tabs.addTab(QTextBrowser(), "Web brief")
        self.artifact_tabs.addTab(QTextBrowser(), "Grok synthesis")
        self.artifact_tabs.addTab(QTextBrowser(), "ChatGPT synthesis")
        review_layout.addWidget(self.artifact_tabs)

        review_layout.addWidget(QLabel("Optional focus / constraints for the final brief:"))
        self.feedback_edit = QTextEdit()
        self.feedback_edit.setMaximumHeight(70)
        self.feedback_edit.setPlaceholderText("Optional: scope limits, emphasis, key questions to answer…")
        review_layout.addWidget(self.feedback_edit)

        self.continue_btn = QPushButton("Generate final research brief")
        self.continue_btn.clicked.connect(self.on_generate_brief)
        self.continue_btn.setEnabled(False)
        review_layout.addWidget(self.continue_btn)

        splitter.addWidget(review_widget)

        brief_group = QGroupBox("Final research brief (markdown)")
        brief_layout = QVBoxLayout(brief_group)
        self.brief_browser = QTextBrowser()
        self.brief_browser.setOpenExternalLinks(True)
        brief_layout.addWidget(self.brief_browser)
        splitter.addWidget(brief_group)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        self.atlas_chat_group = QGroupBox("Direct chat with Atlas (Deep Researcher)")
        self.atlas_chat_group.setCheckable(True)
        self.atlas_chat_group.setChecked(False)
        atlas_chat_layout = QVBoxLayout(self.atlas_chat_group)
        self.atlas_console = AgentConsole(self.db, agent_code="atlas", parent=self)
        self.atlas_console.setVisible(False)
        atlas_chat_layout.addWidget(self.atlas_console)
        self.atlas_chat_group.toggled.connect(lambda checked: self.atlas_console.setVisible(bool(checked)))
        layout.addWidget(self.atlas_chat_group)

    def _load_state(self):
        """Restore persisted field values from last session."""
        name = self._settings.value("research_name", "", type=str)
        goals = self._settings.value("goals", "", type=str)
        feedback = self._settings.value("feedback", "", type=str)
        auto_generate = self._settings.value("auto_generate", True, type=bool)
        last_project_id = self._settings.value("last_project_id", None, type=int)

        if name:
            self.name_edit.setText(name)
        if goals:
            self.goals_edit.setPlainText(goals)
        if feedback:
            self.feedback_edit.setPlainText(feedback)
        if hasattr(self, "auto_generate_checkbox"):
            self.auto_generate_checkbox.setChecked(bool(auto_generate))

        if last_project_id is not None:
            self._current_project_id = last_project_id
            row = self.db.get_project(last_project_id) if self.db else None
            if row:
                _id, name2, _mode2, status, _created, _config = row
                self.status_label.setText(f"Deep research status: Last run {last_project_id} ({name2}) — {status}.")
                if status == STATUS_AWAITING_RESEARCH_REVIEW:
                    self.continue_btn.setEnabled(True)
                    self.refresh_artifact_display(last_project_id)
                else:
                    self.refresh_artifact_display(last_project_id)
            else:
                self.status_label.setText(f"Deep research status: Last run {last_project_id} (not found in DB).")

    def save_state(self):
        """Persist current field values and last project id for next session."""
        self._settings.setValue("research_name", self.name_edit.text().strip())
        self._settings.setValue("goals", self.goals_edit.toPlainText().strip())
        self._settings.setValue("feedback", self.feedback_edit.toPlainText().strip())
        if hasattr(self, "auto_generate_checkbox"):
            self._settings.setValue("auto_generate", bool(self.auto_generate_checkbox.isChecked()))
        if self._current_project_id is not None:
            self._settings.setValue("last_project_id", self._current_project_id)

    def hideEvent(self, event):
        """Save state when tab is switched away."""
        self.save_state()
        super().hideEvent(event)

    def on_start_project(self):
        name = self.name_edit.text().strip() or "Unnamed research"
        goals = self.goals_edit.toPlainText().strip() or "No objective specified."
        mode = "web_only"
        self.save_state()

        try:
            pid = self.db.create_project(name, mode)
            self._current_project_id = pid
            self.status_label.setText(f"Deep research status: Running pipeline (run {pid})...")
            self.progress_bar.setVisible(True)
            self.start_btn.setEnabled(False)
            self.continue_btn.setEnabled(False)
            self._pipeline_worker = PipelineWorker(self.db, pid, goals, mode)
            self._pipeline_worker.finished_signal.connect(self.on_pipeline_finished)
            self._pipeline_worker.error_signal.connect(self.on_pipeline_error)
            self._pipeline_worker.status_signal.connect(self.on_status)
            self._pipeline_worker.start()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create research run: {e}")
            logger.exception("Start deep research failed: %s", e)

    def on_status(self, msg: str):
        self.status_label.setText(f"Deep research status: {msg}")

    def on_pipeline_finished(self, project_id: int):
        self._pipeline_worker = None
        self.progress_bar.setVisible(False)
        self.start_btn.setEnabled(True)
        self._current_project_id = project_id

        row = self.db.get_project(project_id)
        if not row:
            return

        _id, _name, _mode, status, _created, _config = row
        self.status_label.setText(f"Deep research status: Research ready for review (run {project_id}).")

        if status == STATUS_AWAITING_RESEARCH_REVIEW:
            self.continue_btn.setEnabled(True)
        else:
            self.continue_btn.setEnabled(False)

        self.refresh_artifact_display(project_id)

        # Fully automatic mode: immediately generate the final brief.
        if status == STATUS_AWAITING_RESEARCH_REVIEW and self.auto_generate_checkbox.isChecked():
            self.on_generate_brief()

    def on_pipeline_error(self, err: str):
        self._pipeline_worker = None
        self.progress_bar.setVisible(False)
        self.start_btn.setEnabled(True)
        self.continue_btn.setEnabled(False)
        self.status_label.setText("Deep research status: Pipeline failed.")
        QMessageBox.critical(self, "Deep research pipeline error", err)

    def refresh_artifact_display(self, project_id: int):
        """Load artifacts for run and fill the review tabs + final brief if present."""
        arts = self.db.get_artifacts_for_project(project_id)
        web_text = ""
        grok_text = ""
        chatgpt_text = ""
        brief_text = ""

        for _aid, art_type, content_json, _path, _created in arts:
            if art_type == "web_research_brief":
                web_text = _format_artifact_for_display(art_type, content_json)
            elif art_type == "synthesis_grok":
                grok_text = _format_artifact_for_display(art_type, content_json)
            elif art_type == "synthesis_chatgpt":
                chatgpt_text = _format_artifact_for_display(art_type, content_json)
            elif art_type in ("research_brief", "draft"):
                brief_text = _format_artifact_for_display(art_type, content_json)

        self.artifact_tabs.widget(0).setPlainText(web_text)
        self.artifact_tabs.widget(1).setPlainText(grok_text)
        self.artifact_tabs.widget(2).setPlainText(chatgpt_text)

        if brief_text:
            self.brief_browser.setPlainText(brief_text)

    def on_generate_brief(self):
        if self._current_project_id is None:
            QMessageBox.warning(self, "No research run", "Start deep research first.")
            return

        row = self.db.get_project(self._current_project_id)
        if not row:
            QMessageBox.warning(self, "No research run", "Research run not found.")
            return

        _id, _name, _mode, status, _created, _config = row
        if status != STATUS_AWAITING_RESEARCH_REVIEW:
            QMessageBox.warning(
                self,
                "Wrong status",
                f"Run status is '{status}'. Only runs awaiting review can generate a final brief.",
            )
            return

        feedback = self.feedback_edit.toPlainText().strip() or None
        self.continue_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Deep research status: Generating final brief...")

        self._brief_worker = ContinueBriefWorker(self.db, self._current_project_id, feedback)
        self._brief_worker.finished_signal.connect(self.on_brief_finished)
        self._brief_worker.error_signal.connect(self.on_brief_error)
        self._brief_worker.status_signal.connect(self.on_status)
        self._brief_worker.start()

    def on_brief_finished(self, project_id: int):
        self._brief_worker = None
        self.progress_bar.setVisible(False)
        self.continue_btn.setEnabled(False)
        self.status_label.setText(f"Deep research status: Done (run {project_id}).")
        self.refresh_artifact_display(project_id)

    def on_brief_error(self, err: str):
        self._brief_worker = None
        self.progress_bar.setVisible(False)
        self.continue_btn.setEnabled(True)
        self.status_label.setText("Deep research status: Brief generation failed.")
        QMessageBox.critical(self, "Research brief error", err)


# Backward-compatible aliases (older code/tests refer to ProjectsTab).
ProjectsTab = DeepResearchTab


"""
AI Projects tab for the multi-agent research workflow.

Create an AI project (research objective + mode), run pipeline
(research -> synthesis -> parallel Grok+ChatGPT), review artifacts,
then continue to draft (4-step exchange -> QA -> done) and view final draft.
"""

import json
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit, QPushButton,
    QComboBox, QTabWidget, QTextBrowser, QProgressBar, QMessageBox, QGroupBox,
    QSplitter, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QFont

from core.db import DatabaseManager
from core.workflow_engine import WorkflowEngine, STATUS_AWAITING_RESEARCH_REVIEW

logger = logging.getLogger(__name__)


class PipelineWorker(QThread):
    """Run run_pipeline(project_id, goals, mode) in background."""
    finished_signal = pyqtSignal(int)   # project_id on success
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
            eng.run_pipeline(self.project_id, self.goals, self.mode)
            self.status_signal.emit("Research ready for review.")
            self.finished_signal.emit(self.project_id)
        except Exception as e:
            logger.exception("Pipeline failed: %s", e)
            self.error_signal.emit(str(e))


class ContinueDraftWorker(QThread):
    """Run continue_to_draft(project_id, user_feedback) in background."""
    finished_signal = pyqtSignal(int)   # project_id on success
    error_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)

    def __init__(self, db: DatabaseManager, project_id: int, user_feedback: str = None):
        super().__init__()
        self.db = db
        self.project_id = project_id
        self.user_feedback = user_feedback or ""

    def run(self):
        try:
            self.status_signal.emit("Drafting (Grok + ChatGPT exchange)...")
            eng = WorkflowEngine(self.db)
            eng.continue_to_draft(self.project_id, self.user_feedback or None)
            self.status_signal.emit("Done.")
            self.finished_signal.emit(self.project_id)
        except Exception as e:
            logger.exception("Continue to draft failed: %s", e)
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
                lines.append(r.get("excerpt", "")[:600] + ("..." if len(r.get("excerpt", "")) > 600 else ""))
                lines.append("")
            if data.get("notes"):
                lines.append(f"Notes: {data['notes']}")
            return "\n".join(lines)
        if artifact_type == "web_research_brief":
            findings = data.get("findings", [])
            sources = data.get("sources", [])
            lines = [f"Query: {data.get('query', '')}", ""]
            for f in findings:
                claim = f.get("claim", "") or ""
                lines.append(f"Finding: {claim}")
            if findings:
                lines.append("")
            for s in sources:
                lines.append(f"Source: {s.get('title', '')} | {s.get('url', '')}")
            if data.get("notes"):
                lines.append(f"Notes: {data['notes']}")
            return "\n".join(lines)
        if artifact_type in ("synthesis_grok", "synthesis_chatgpt"):
            return data.get("content", content_json)
        if artifact_type == "user_research_feedback":
            return data.get("content", content_json)
        if artifact_type == "draft":
            return data.get("markdown_body", content_json)
        return content_json
    except Exception:
        return content_json


class ProjectsTab(QWidget):
    """Tab for creating and running AI research projects (research -> review -> draft)."""

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self._current_project_id = None
        self._pipeline_worker = None
        self._draft_worker = None
        self._settings = QSettings("NaviSsurance", "ProjectsTab")
        self.setup_ui()
        self._load_state()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("AI Projects (Research & Drafting Pipeline)")
        title.setStyleSheet("color: #e8eaed; font-weight: 700; font-size: 14px; margin: 0;")
        layout.addWidget(title)
        subtitle = QLabel(
            "Use this for multi-step AI research and draft generation. "
            "This is separate from task management."
        )
        subtitle.setStyleSheet("color: #9aa0a6; font-size: 12px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # --- Form ---
        form_group = QGroupBox("New AI research project")
        form_layout = QVBoxLayout(form_group)
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Project name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. EEG devices memo")
        name_layout.addWidget(self.name_edit)
        form_layout.addLayout(name_layout)
        form_layout.addWidget(QLabel("Research objective / question:"))
        self.goals_edit = QTextEdit()
        self.goals_edit.setPlaceholderText("e.g. cleared medical devices that analyze EEG data")
        self.goals_edit.setMaximumHeight(80)
        form_layout.addWidget(self.goals_edit)
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Research mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["internal_only", "internal_web", "web_only"])
        self.mode_combo.setToolTip("internal_only = RAG only; internal_web = RAG + web; web_only = web only")
        mode_layout.addWidget(self.mode_combo)
        form_layout.addLayout(mode_layout)
        self.start_btn = QPushButton("Start AI project")
        self.start_btn.clicked.connect(self.on_start_project)
        form_layout.addWidget(self.start_btn)
        layout.addWidget(form_group)

        # --- Status ---
        self.status_label = QLabel("AI project status: —")
        self.status_label.setStyleSheet("color: #6b8cae; font-weight: 600; font-size: 13px;")
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate when running
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # --- Splitter: review area (left) and draft / final (right) ---
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Review area (artifacts + continue to draft)
        review_widget = QWidget()
        review_layout = QVBoxLayout(review_widget)
        review_layout.addWidget(QLabel("Research artifacts to review (after pipeline runs):"))
        self.artifact_tabs = QTabWidget()
        self.artifact_tabs.addTab(QTextBrowser(), "Internal brief")
        self.artifact_tabs.addTab(QTextBrowser(), "Web brief")
        self.artifact_tabs.addTab(QTextBrowser(), "Grok synthesis")
        self.artifact_tabs.addTab(QTextBrowser(), "ChatGPT synthesis")
        review_layout.addWidget(self.artifact_tabs)
        review_layout.addWidget(QLabel("Optional draft instructions (e.g. emphasize FDA guidance):"))
        self.feedback_edit = QTextEdit()
        self.feedback_edit.setMaximumHeight(60)
        self.feedback_edit.setPlaceholderText("Optional instructions for the writer...")
        review_layout.addWidget(self.feedback_edit)
        self.continue_btn = QPushButton("Generate draft from research")
        self.continue_btn.clicked.connect(self.on_continue_to_draft)
        self.continue_btn.setEnabled(False)
        review_layout.addWidget(self.continue_btn)
        splitter.addWidget(review_widget)

        # Final draft area
        draft_group = QGroupBox("AI-generated draft")
        draft_layout = QVBoxLayout(draft_group)
        self.draft_browser = QTextBrowser()
        self.draft_browser.setOpenExternalLinks(True)
        draft_layout.addWidget(self.draft_browser)
        splitter.addWidget(draft_group)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

    def _load_state(self):
        """Restore persisted field values from last session."""
        name = self._settings.value("project_name", "", type=str)
        goals = self._settings.value("goals", "", type=str)
        mode = self._settings.value("mode", "web_only", type=str)
        feedback = self._settings.value("feedback", "", type=str)
        last_project_id = self._settings.value("last_project_id", None, type=int)
        if name:
            self.name_edit.setText(name)
        if goals:
            self.goals_edit.setPlainText(goals)
        if mode in ("internal_only", "internal_web", "web_only"):
            idx = self.mode_combo.findText(mode)
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
        if feedback:
            self.feedback_edit.setPlainText(feedback)
        if last_project_id is not None:
            self._current_project_id = last_project_id
            row = self.db.get_project(last_project_id) if self.db else None
            if row:
                _id, name, _mode, status, _created, _config = row
                self.status_label.setText(f"AI project status: Last project {last_project_id} ({name}) — {status}.")
                if status == STATUS_AWAITING_RESEARCH_REVIEW:
                    self.continue_btn.setEnabled(True)
                    self.refresh_artifact_display(last_project_id)
            else:
                self.status_label.setText(f"AI project status: Last project {last_project_id} (not found in DB).")

    def save_state(self):
        """Persist current field values and last project id for next session."""
        self._settings.setValue("project_name", self.name_edit.text().strip())
        self._settings.setValue("goals", self.goals_edit.toPlainText().strip())
        self._settings.setValue("mode", self.mode_combo.currentText())
        self._settings.setValue("feedback", self.feedback_edit.toPlainText().strip())
        if self._current_project_id is not None:
            self._settings.setValue("last_project_id", self._current_project_id)

    def hideEvent(self, event):
        """Save state when tab is switched away."""
        self.save_state()
        super().hideEvent(event)

    def on_start_project(self):
        name = self.name_edit.text().strip() or "Unnamed project"
        goals = self.goals_edit.toPlainText().strip() or "No goals specified."
        mode = self.mode_combo.currentText()
        self.save_state()
        try:
            pid = self.db.create_project(name, mode)
            self._current_project_id = pid
            self.status_label.setText(f"AI project status: Running pipeline for project {pid}...")
            self.progress_bar.setVisible(True)
            self.start_btn.setEnabled(False)
            self.continue_btn.setEnabled(False)
            self._pipeline_worker = PipelineWorker(self.db, pid, goals, mode)
            self._pipeline_worker.finished_signal.connect(self.on_pipeline_finished)
            self._pipeline_worker.error_signal.connect(self.on_pipeline_error)
            self._pipeline_worker.status_signal.connect(self.on_status)
            self._pipeline_worker.start()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create project: {e}")
            logger.exception("Start project failed: %s", e)

    def on_status(self, msg: str):
        self.status_label.setText(f"AI project status: {msg}")

    def on_pipeline_finished(self, project_id: int):
        self._pipeline_worker = None
        self.progress_bar.setVisible(False)
        self.start_btn.setEnabled(True)
        self._current_project_id = project_id
        row = self.db.get_project(project_id)
        if not row:
            return
        _id, name, mode, status, _created, _config = row
        self.status_label.setText(f"AI project status: Research ready for review (project {project_id}).")
        if status == STATUS_AWAITING_RESEARCH_REVIEW:
            self.continue_btn.setEnabled(True)
            self.refresh_artifact_display(project_id)
        else:
            self.continue_btn.setEnabled(False)

    def on_pipeline_error(self, err: str):
        self._pipeline_worker = None
        self.progress_bar.setVisible(False)
        self.start_btn.setEnabled(True)
        self.continue_btn.setEnabled(False)
        self.status_label.setText("AI project status: Pipeline failed.")
        QMessageBox.critical(self, "Pipeline error", err)

    def refresh_artifact_display(self, project_id: int):
        """Load artifacts for project and fill the review tabs + draft if done."""
        arts = self.db.get_artifacts_for_project(project_id)
        internal_text = ""
        web_text = ""
        grok_text = ""
        chatgpt_text = ""
        draft_text = ""
        for _aid, art_type, content_json, _path, _created in arts:
            if art_type == "internal_retrieval_brief":
                internal_text = _format_artifact_for_display(art_type, content_json)
            elif art_type == "web_research_brief":
                web_text = _format_artifact_for_display(art_type, content_json)
            elif art_type == "synthesis_grok":
                grok_text = _format_artifact_for_display(art_type, content_json)
            elif art_type == "synthesis_chatgpt":
                chatgpt_text = _format_artifact_for_display(art_type, content_json)
            elif art_type == "draft":
                draft_text = _format_artifact_for_display(art_type, content_json)
        self.artifact_tabs.widget(0).setPlainText(internal_text)
        self.artifact_tabs.widget(1).setPlainText(web_text)
        self.artifact_tabs.widget(2).setPlainText(grok_text)
        self.artifact_tabs.widget(3).setPlainText(chatgpt_text)
        if draft_text:
            self.draft_browser.setPlainText(draft_text)

    def on_continue_to_draft(self):
        if self._current_project_id is None:
            QMessageBox.warning(self, "No project", "Start a project first.")
            return
        row = self.db.get_project(self._current_project_id)
        if not row:
            QMessageBox.warning(self, "No project", "Project not found.")
            return
        _id, _name, _mode, status, _created, _config = row
        if status != STATUS_AWAITING_RESEARCH_REVIEW:
            QMessageBox.warning(
                self, "Wrong status",
                f"Project status is '{status}'. Only projects awaiting research review can continue to draft."
            )
            return
        feedback = self.feedback_edit.toPlainText().strip() or None
        self.continue_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("AI project status: Drafting...")
        self._draft_worker = ContinueDraftWorker(self.db, self._current_project_id, feedback)
        self._draft_worker.finished_signal.connect(self.on_draft_finished)
        self._draft_worker.error_signal.connect(self.on_draft_error)
        self._draft_worker.status_signal.connect(self.on_status)
        self._draft_worker.start()

    def on_draft_finished(self, project_id: int):
        self._draft_worker = None
        self.progress_bar.setVisible(False)
        self.continue_btn.setEnabled(False)
        self.status_label.setText(f"AI project status: Done (project {project_id}).")
        self.refresh_artifact_display(project_id)

    def on_draft_error(self, err: str):
        self._draft_worker = None
        self.progress_bar.setVisible(False)
        self.continue_btn.setEnabled(True)
        self.status_label.setText("AI project status: Draft failed.")
        QMessageBox.critical(self, "Draft error", err)

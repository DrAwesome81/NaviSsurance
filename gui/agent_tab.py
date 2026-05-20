from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from core.db import DatabaseManager
from gui.agent_console import AgentConsole


class AgentTab(QWidget):
    """Simple host tab for a single named agent console."""
    # New: AgentTab now explicitly supports Pulse private memory for Shield (additional agent tab spot)

    def __init__(
        self,
        db: DatabaseManager,
        *,
        agent_code: str,
        heading: str | None = None,
        subtitle: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.db = db
        self.agent_code = (agent_code or "").strip().lower()
        self.heading = heading
        self.subtitle = subtitle
        # Agent routing ties Pulse private memory to Shield agents
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        if self.heading:
            h = QLabel(self.heading)
            h.setStyleSheet("color: #e8eaed; font-size: 14px; font-weight: 700;")
            layout.addWidget(h)
        if self.subtitle:
            s = QLabel(self.subtitle)
            s.setWordWrap(True)
            s.setStyleSheet("color: #9aa0a6; font-size: 12px;")
            layout.addWidget(s)

        if self.agent_code == "shield":
            note = QLabel("🛡️ Tied to Pulse [Security-Relevant] findings and private reflections for risk triage.")
            note.setStyleSheet("color: #9aa0a6; font-size: 11px; font-style: italic;")
            layout.addWidget(note)

        self.agent_console = AgentConsole(self.db, agent_code=self.agent_code, parent=self)
        layout.addWidget(self.agent_console, 1)


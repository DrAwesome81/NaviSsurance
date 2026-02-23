from __future__ import annotations

import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTextBrowser,
    QPushButton,
)

from core.db import DatabaseManager


class TeamDirectoryTab(QWidget):
    """Read-only directory of named AI executive team members."""

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("AI Executive Team Directory")
        title.setStyleSheet("color: #e8eaed; font-size: 14px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        subtitle = QLabel(
            "Canonical names, aliases, and role capabilities used by Navi for delegation."
        )
        subtitle.setStyleSheet("color: #9aa0a6; font-size: 12px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        body = QHBoxLayout()
        self.agent_list = QListWidget()
        self.agent_list.itemClicked.connect(self._on_agent_clicked)
        body.addWidget(self.agent_list, 1)
        self.details = QTextBrowser()
        self.details.setPlaceholderText("Select a team member to view details.")
        body.addWidget(self.details, 2)
        layout.addLayout(body, 1)

    def _refresh(self):
        self.agent_list.clear()
        self._agents = self.db.agents_list_active()
        for a in self._agents:
            code = str(a.get("code") or "").strip().lower()
            name = str(a.get("display_name") or code)
            role = str(a.get("role_title") or "Specialist")
            item = QListWidgetItem(f"{name} — {role}")
            item.setData(Qt.ItemDataRole.UserRole, code)
            self.agent_list.addItem(item)
        if self._agents:
            first = self.agent_list.item(0)
            if first:
                self.agent_list.setCurrentItem(first)
                self._on_agent_clicked(first)
        else:
            self.details.setPlainText("No agents available.")

    def _on_agent_clicked(self, item: QListWidgetItem):
        code = str(item.data(Qt.ItemDataRole.UserRole) or "").strip().lower()
        if not code:
            return
        row = self.db.agent_get(code)
        if not row:
            self.details.setPlainText("Agent not found.")
            return

        aliases = []
        capabilities = []
        try:
            aliases = json.loads(row.get("aliases_json") or "[]")
        except Exception:
            aliases = []
        try:
            capabilities = json.loads(row.get("capabilities_json") or "[]")
        except Exception:
            capabilities = []

        lines = [
            f"Code: {row.get('code') or ''}",
            f"Display name: {row.get('display_name') or ''}",
            f"Role title: {row.get('role_title') or ''}",
            f"Home tab: {row.get('home_tab') or ''}",
            "",
            "Aliases:",
        ]
        if aliases:
            lines.extend([f"- {str(a)}" for a in aliases])
        else:
            lines.append("- (none)")
        lines.extend(["", "Capabilities:"])
        if capabilities:
            lines.extend([f"- {str(c)}" for c in capabilities])
        else:
            lines.append("- (none)")
        self.details.setPlainText("\n".join(lines).strip())


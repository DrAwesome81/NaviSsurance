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
    QMessageBox,
)

from core.db import DatabaseManager
from gui.agent_routing import route_for_agent

# Pulse private memory + Shield (team directory surface)
class TeamDirectoryTab(QWidget):
    """Read-only directory of named AI executive team members."""
    # Team includes Pulse (private memory intel) and Shield (security/privacy); directory can surface their coordination role (fresh note)
    # New: team directory now explicitly supports Pulse private memory for Shield (additional team directory spot)

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

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.open_workspace_btn = QPushButton("Open Agent Workspace")
        self.open_workspace_btn.clicked.connect(self._open_selected_agent_workspace)
        action_row.addWidget(self.open_workspace_btn)
        self.open_next_btn = QPushButton("Open Next Open Assignment")
        self.open_next_btn.clicked.connect(self._open_selected_agent_next_assignment)
        action_row.addWidget(self.open_next_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        body = QHBoxLayout()
        self.agent_list = QListWidget()
        self.agent_list.itemClicked.connect(self._on_agent_clicked)
        body.addWidget(self.agent_list, 1)
        self.details = QTextBrowser()
        self.details.setPlaceholderText("Select a team member to view details.")
        body.addWidget(self.details, 2)
        layout.addLayout(body, 1)
        self._selected_agent_code: str = ""

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
        self._selected_agent_code = code
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

        rows = self.db.agent_list_assignments(assignee_code=code, limit=200)
        open_rows = []
        closed_rows = []
        for r in rows:
            st = str(r.get("status") or "").strip().lower()
            if st in {"done", "cancelled"}:
                closed_rows.append(r)
            else:
                open_rows.append(r)

        lines = [
            f"Code: {row.get('code') or ''}",
            f"Display name: {row.get('display_name') or ''}",
            f"Role title: {row.get('role_title') or ''}",
            f"Home tab: {row.get('home_tab') or ''}",
            f"Assignments: {len(open_rows)} open, {len(closed_rows)} closed",
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
        lines.extend(["", "Open assignments:"])
        if open_rows:
            for r in open_rows[:8]:
                aid = int(r.get("id") or 0)
                st = str(r.get("status") or "")
                pr = int(r.get("priority") or 3)
                title = str(r.get("title") or "Untitled")
                lines.append(f"- A-{aid:04d} [{st}] P{pr} {title}")
        else:
            lines.append("- (none)")
        self.details.setPlainText("\n".join(lines).strip())

    def _open_selected_agent_workspace(self):
        code = (self._selected_agent_code or "").strip().lower()
        if not code:
            QMessageBox.information(self, "Team", "Select an agent first.")
            return
        host = self.parent()
        tw = getattr(host, "tab_widget", None) if host is not None else None
        if tw is None:
            QMessageBox.information(self, "Team", "Could not open agent workspace in this context.")
            return
        route = route_for_agent(code)
        if not route:
            QMessageBox.information(self, "Team", f"No workspace route available for '{code}'.")
            return
        tab_attr, group_attr, _console_attr, tab_label = route
        target_tab = getattr(host, tab_attr, None)
        if target_tab is None:
            QMessageBox.warning(self, "Team", f"Could not open tab: {tab_label}.")
            return
        idx = tw.indexOf(target_tab)
        if idx >= 0:
            tw.setCurrentIndex(idx)
        if group_attr:
            group = getattr(target_tab, group_attr, None)
            if group is not None and hasattr(group, "setChecked"):
                group.setChecked(True)

    def _open_selected_agent_next_assignment(self):
        code = (self._selected_agent_code or "").strip().lower()
        if not code:
            QMessageBox.information(self, "Team", "Select an agent first.")
            return
        rows = self.db.agent_list_assignments(assignee_code=code, limit=200)
        next_row = None
        for r in rows:
            st = str(r.get("status") or "").strip().lower()
            if st in {"done", "cancelled"}:
                continue
            next_row = r
            break
        if not next_row:
            QMessageBox.information(self, "Team", "No open assignments for this agent.")
            return

        self._open_selected_agent_workspace()
        aid = int(next_row.get("id") or 0)
        host = self.parent()
        route = route_for_agent(code)
        if aid <= 0 or route is None:
            return
        tab_attr, _group_attr, console_attr, _tab_label = route
        target_tab = getattr(host, tab_attr, None) if host is not None else None
        console = getattr(target_tab, console_attr, None) if target_tab is not None and console_attr else None
        if console is None or not hasattr(console, "focus_assignment"):
            return
        try:
            console.focus_assignment(aid)
        except Exception:
            return


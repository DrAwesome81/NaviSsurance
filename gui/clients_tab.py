from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QGroupBox,
    QLabel,
    QPushButton,
    QTextEdit,
    QSplitter,
    QInputDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QMessageBox,
)

from core.db import DatabaseManager
from core.client_dossier import get_client_dossier_snapshot


class ClientsTab(QWidget):
    """Clients tab providing list + unified dossier view per client."""

    dossier_loaded = pyqtSignal(int)

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self._current_client_id: int | None = None

        main_layout = QHBoxLayout(self)

        # Left: search + new (one row so the action stays visible in the narrow pane)
        left = QVBoxLayout()
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search clients...")
        self.search_edit.textChanged.connect(self._filter_clients)
        search_row.addWidget(self.search_edit, 1)
        btn_new = QPushButton("New client")
        btn_new.setToolTip("Add a client to the dossier list (links to projects, emails, meetings).")
        btn_new.setMinimumWidth(88)
        btn_new.clicked.connect(self._on_new_client)
        search_row.addWidget(btn_new)
        left.addLayout(search_row)

        self.client_list = QListWidget()
        self.client_list.currentItemChanged.connect(self._on_client_selected)
        left.addWidget(self.client_list, 1)

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMaximumWidth(320)

        # Right: dossier scroll area
        self.dossier_area = QScrollArea()
        self.dossier_area.setWidgetResizable(True)
        self.dossier_content = QWidget()
        self.dossier_layout = QVBoxLayout(self.dossier_content)
        self.dossier_area.setWidget(self.dossier_content)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(self.dossier_area)
        splitter.setSizes([300, 900])

        main_layout.addWidget(splitter)

        self._load_clients()

    def _on_new_client(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("New client")
        root = QVBoxLayout(dlg)
        form = QFormLayout()
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Company or client name (required)")
        form.addRow("Name:", name_edit)
        notes_edit = QTextEdit()
        notes_edit.setPlaceholderText("Optional notes")
        notes_edit.setMaximumHeight(120)
        form.addRow("Notes:", notes_edit)
        root.addLayout(form)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        root.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = (name_edit.text() or "").strip()
        if not name:
            QMessageBox.information(self, "Clients", "Client name is required.")
            return
        notes = (notes_edit.toPlainText() or "").strip() or None
        try:
            cid = self.db.client_create(name=name, notes=notes)
        except sqlite3.IntegrityError:
            QMessageBox.warning(
                self,
                "Clients",
                f'A client named "{name}" already exists. Names must be unique.',
            )
            return
        except Exception as e:
            QMessageBox.warning(self, "Clients", f"Could not create client:\n{type(e).__name__}: {e}")
            return
        self._load_clients()
        for i in range(self.client_list.count()):
            item = self.client_list.item(i)
            if item and int(item.data(Qt.ItemDataRole.UserRole)) == int(cid):
                self.client_list.setCurrentItem(item)
                break

    def _load_clients(self):
        self.client_list.clear()
        clients = self.db.list_clients(active_only=False, limit=500)
        for c in clients:
            item = QListWidgetItem(f"{c.get('name', 'Unnamed')} (#{c.get('id')})")
            item.setData(Qt.ItemDataRole.UserRole, int(c.get("id")))
            item.setData(Qt.ItemDataRole.UserRole + 1, c)
            self.client_list.addItem(item)

    def _filter_clients(self, text: str):
        text = text.lower().strip()
        for i in range(self.client_list.count()):
            item = self.client_list.item(i)
            name = item.text().lower()
            item.setHidden(text not in name)

    def _on_client_selected(self, current: QListWidgetItem | None, previous=None):
        if not current:
            self._clear_dossier()
            return
        cid = int(current.data(Qt.ItemDataRole.UserRole))
        self._current_client_id = cid
        self._render_dossier(cid)

    def _clear_dossier(self):
        for i in reversed(range(self.dossier_layout.count())):
            w = self.dossier_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        self.dossier_layout.addWidget(QLabel("Select a client from the list."))

    def _render_dossier(self, client_id: int):
        for i in reversed(range(self.dossier_layout.count())):
            w = self.dossier_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

        snap = get_client_dossier_snapshot(self.db, client_id)
        if "error" in snap:
            self.dossier_layout.addWidget(QLabel("Client not found."))
            return

        prof = snap.get("profile", {})
        self.dossier_layout.addWidget(self._section("Profile", self._profile_widget(prof)))

        mems = snap.get("memory", [])
        self.dossier_layout.addWidget(self._section("Memory", self._memory_widget(mems)))

        projs = snap.get("projects", [])
        self.dossier_layout.addWidget(self._section("Projects", self._simple_list_widget(projs, ["name", "status", "client_id"])))

        assigns = snap.get("assignments", [])
        self.dossier_layout.addWidget(self._section("Assignments", self._simple_list_widget(assigns, ["title", "assignee_code", "status", "priority"])))

        tasks = snap.get("tasks", [])
        self.dossier_layout.addWidget(self._section("Tasks", self._simple_list_widget(tasks, ["title", "status", "due_date"])))

        emails = snap.get("recent_emails", [])
        self.dossier_layout.addWidget(self._section("Recent Emails", self._simple_list_widget(emails, ["subject", "sender", "timestamp"])))

        meetings = snap.get("recent_meetings", [])
        self.dossier_layout.addWidget(self._section("Recent Meetings", self._simple_list_widget(meetings, ["meeting_with", "meeting_date", "status"])))

        # Quick actions
        qa = QHBoxLayout()
        btn_mem = QPushButton("Add to Memory")
        btn_mem.clicked.connect(lambda: self._quick_add_memory())
        qa.addWidget(btn_mem)
        btn_note = QPushButton("New Note")
        btn_note.clicked.connect(lambda: self._request_new_note())
        qa.addWidget(btn_note)
        btn_assign = QPushButton("New Assignment")
        btn_assign.clicked.connect(lambda: self._request_new_assignment())
        qa.addWidget(btn_assign)
        qa.addStretch()
        qa_w = QWidget()
        qa_w.setLayout(qa)
        self.dossier_layout.addWidget(qa_w)

        self.dossier_loaded.emit(client_id)

    def _section(self, title: str, content: QWidget) -> QGroupBox:
        box = QGroupBox(title)
        box.setCheckable(True)
        box.setChecked(True)
        lay = QVBoxLayout()
        lay.addWidget(content)
        box.setLayout(lay)
        return box

    def _profile_widget(self, prof: dict) -> QWidget:
        w = QTextEdit()
        w.setReadOnly(True)
        txt = f"<b>{prof.get('name')}</b> (#{prof.get('id')})<br>"
        if prof.get("aliases"):
            txt += f"Aliases: {', '.join(prof['aliases'])}<br>"
        if prof.get("notes"):
            txt += f"Notes: {prof['notes']}"
        w.setHtml(txt)
        w.setMaximumHeight(120)
        return w

    def _memory_widget(self, memories: list[dict]) -> QWidget:
        w = QTextEdit()
        w.setReadOnly(True)
        if not memories:
            w.setPlainText("No approved memory linked to this client.")
            return w
        lines = []
        for m in memories:
            lines.append(f"• [{m.get('kind')}] {m.get('content')[:200]}")
        w.setPlainText("\n".join(lines))
        w.setMaximumHeight(180)
        return w

    def _simple_list_widget(self, items: list[dict], keys: list[str]) -> QWidget:
        w = QTextEdit()
        w.setReadOnly(True)
        if not items:
            w.setPlainText("None.")
            return w
        lines = []
        for it in items:
            parts = []
            for k in keys:
                v = it.get(k)
                if v:
                    parts.append(f"{k}: {v}")
            lines.append(" | ".join(parts) or str(it))
        w.setPlainText("\n".join(lines[:30]))
        w.setMaximumHeight(160)
        return w

    def _quick_add_memory(self):
        if self._current_client_id is None:
            return
        text, ok = QInputDialog.getMultiLineText(self, "Add to Memory", "Client-specific fact or preference:")
        if not ok or not text.strip():
            return
        try:
            self.db.user_memory_add(
                kind="client_fact",
                content=text.strip(),
                source="clients_tab",
                confidence=1.0,
                approval_status="approved",
                entity_refs=[{"entity_type": "client", "entity_key": str(self._current_client_id)}],
            )
        except Exception:
            pass
        self._render_dossier(self._current_client_id)

    def refresh(self):
        """Public refresh hook."""
        self._load_clients()
        if self._current_client_id:
            self._render_dossier(self._current_client_id)

    def _request_new_note(self):
        # Emit or delegate to parent window to switch to Notes tab
        if hasattr(self.parent(), "tab_widget"):
            tw = self.parent().tab_widget
            for i in range(tw.count()):
                if tw.tabText(i) == "Notes":
                    tw.setCurrentIndex(i)
                    break

    def _request_new_assignment(self):
        # Switch to Chief of Staff for assignment creation
        if hasattr(self.parent(), "tab_widget"):
            tw = self.parent().tab_widget
            for i in range(tw.count()):
                if tw.tabText(i) == "Chief of Staff":
                    tw.setCurrentIndex(i)
                    break

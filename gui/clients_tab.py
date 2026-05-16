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
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QCheckBox,
)

from core.db import DatabaseManager
from core.client_dossier import get_client_dossier_snapshot
from core import app_preferences as ap


class ClientEditDialog(QDialog):
    """Edit basic client profile fields including aliases and domain rules."""

    def __init__(self, db: DatabaseManager, client: dict, parent=None):
        super().__init__(parent)
        self.db = db
        self.client_id = int(client.get("id"))
        self.setWindowTitle(f"Edit Client — {client.get('name', 'Unnamed')}")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(client.get("name") or "")
        form.addRow("Name:", self.name_edit)

        aliases = client.get("aliases") or client.get("aliases_json") or []
        if isinstance(aliases, str):
            aliases = []
        self.aliases_edit = QLineEdit(", ".join(aliases))
        self.aliases_edit.setPlaceholderText("Comma-separated aliases (e.g. Acme, ACME Med)")
        form.addRow("Aliases:", self.aliases_edit)

        domains = client.get("domains") or client.get("domain_rules_json") or []
        if isinstance(domains, str):
            domains = []
        self.domains_edit = QLineEdit(", ".join(domains))
        self.domains_edit.setPlaceholderText("Comma-separated domains (e.g. acme.com, acmeco.io)")
        form.addRow("Key Domains:", self.domains_edit)

        self.notes_edit = QTextEdit(client.get("notes") or "")
        self.notes_edit.setPlaceholderText("Internal notes about this client...")
        self.notes_edit.setMinimumHeight(80)
        form.addRow("Notes:", self.notes_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        name = (self.name_edit.text() or "").strip()
        if not name:
            QMessageBox.warning(self, "Client", "Name is required.")
            return

        aliases = [a.strip() for a in self.aliases_edit.text().split(",") if a.strip()]
        domains = [d.strip().lower() for d in self.domains_edit.text().split(",") if d.strip()]

        notes = (self.notes_edit.toPlainText() or "").strip() or None

        try:
            ok = self.db.client_update(
                self.client_id,
                name=name,
                aliases_json=aliases,
                domain_rules_json=domains,
                notes=notes,
            )
            if ok:
                self.accept()
            else:
                QMessageBox.warning(self, "Client", "Failed to save changes.")
        except Exception as e:
            QMessageBox.warning(self, "Client", f"Error saving client:\n{e}")


class UnlinkProjectsDialog(QDialog):
    """Table dialog to unlink projects from the current client."""

    def __init__(self, db: DatabaseManager, client_id: int, client_name: str = "", parent=None):
        super().__init__(parent)
        self.db = db
        self.client_id = int(client_id)
        self.client_name = client_name or f"Client #{client_id}"
        self.setWindowTitle(f"Unlink Projects from {self.client_name}")
        self.setMinimumSize(720, 420)

        layout = QVBoxLayout(self)

        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.textChanged.connect(self._filter_table)
        search_layout.addWidget(self.search_edit, 1)
        layout.addLayout(search_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["", "Project Name", "Status", "Deadline", "Next Action"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        btn_layout = QHBoxLayout()
        btn_unlink = QPushButton("Unlink Selected")
        btn_unlink.clicked.connect(self._unlink_selected)
        btn_layout.addWidget(btn_unlink)
        btn_layout.addWidget(QPushButton("Cancel", clicked=self.reject))
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._load_linked_projects()

    def _load_linked_projects(self):
        projects = self.db.cos_get_projects(client_id=self.client_id) or []
        self.linked_projects = projects
        self.table.setRowCount(len(projects))

        for i, row in enumerate(projects):
            proj_id = row[0]
            name = row[1] or "(unnamed)"
            status = row[4] or ""
            deadline = row[6] or ""
            next_action = row[7] or row[16] or ""

            chk = QCheckBox()
            self.table.setCellWidget(i, 0, chk)

            self.table.setItem(i, 1, QTableWidgetItem(name))
            self.table.setItem(i, 2, QTableWidgetItem(status))
            self.table.setItem(i, 3, QTableWidgetItem(deadline))
            self.table.setItem(i, 4, QTableWidgetItem(next_action[:80] if next_action else ""))

            for col in range(1, 5):
                if self.table.item(i, col):
                    self.table.item(i, col).setData(Qt.ItemDataRole.UserRole, proj_id)

    def _filter_table(self):
        text = self.search_edit.text().lower().strip()
        for row in range(self.table.rowCount()):
            match = any(
                text in (self.table.item(row, col).text().lower() if self.table.item(row, col) else "")
                for col in range(1, 5)
            )
            self.table.setRowHidden(row, not match)

    def _unlink_selected(self):
        ids_to_unlink = []
        for row in range(self.table.rowCount()):
            chk = self.table.cellWidget(row, 0)
            if isinstance(chk, QCheckBox) and chk.isChecked():
                item = self.table.item(row, 1)
                if item:
                    pid = item.data(Qt.ItemDataRole.UserRole)
                    if pid:
                        ids_to_unlink.append(int(pid))

        if not ids_to_unlink:
            QMessageBox.information(self, "Unlink", "No projects selected.")
            return

        count = 0
        for pid in ids_to_unlink:
            try:
                self.db.cos_update_project(pid, client_id=None)
                count += 1
            except Exception:
                pass

        if count:
            QMessageBox.information(self, "Unlink", f"Unlinked {count} project(s).")
            self.accept()
        else:
            self.reject()


class LinkProjectsDialog(QDialog):
    """Searchable table dialog to link multiple existing projects to a client."""

    def __init__(self, db: DatabaseManager, client_id: int, client_name: str = "", parent=None):
        super().__init__(parent)
        self.db = db
        self.client_id = int(client_id)
        self.client_name = client_name or f"Client #{client_id}"
        self.setWindowTitle(f"Link Projects to {self.client_name}")
        self.setMinimumSize(720, 480)
        self.selected_project_ids: list[int] = []

        layout = QVBoxLayout(self)

        # Search
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter by name, status, next action...")
        self.search_edit.textChanged.connect(self._filter_table)
        search_layout.addWidget(self.search_edit, 1)
        layout.addLayout(search_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["", "Project Name", "Status", "Deadline", "Next Action"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_link = QPushButton("Link Selected Projects")
        self.btn_link.clicked.connect(self._link_selected)
        btn_layout.addWidget(self.btn_link)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._load_projects()
        self._filter_table("")  # initial filter

    def _load_projects(self):
        """Load projects that are not yet linked to this client."""
        all_projects = self.db.cos_get_projects() or []
        self.unlinked_projects = []

        for row in all_projects:
            proj_id = row[0]
            # client_id is the last column in cos_get_projects SELECT
            proj_client_id = row[-1] if row else None

            # Include projects that are unlinked (NULL) or linked to a different client
            if proj_client_id is None or int(proj_client_id or 0) != self.client_id:
                self.unlinked_projects.append(row)

        # Build table rows
        self.table.setRowCount(len(self.unlinked_projects))
        for i, row in enumerate(self.unlinked_projects):
            proj_id = row[0]
            name = row[1] or "(unnamed)"
            status = row[4] or ""
            deadline = row[6] or ""
            next_action = row[7] or row[16] or ""

            chk = QCheckBox()
            chk.setChecked(False)
            self.table.setCellWidget(i, 0, chk)

            self.table.setItem(i, 1, QTableWidgetItem(name))
            self.table.setItem(i, 2, QTableWidgetItem(status))
            self.table.setItem(i, 3, QTableWidgetItem(deadline))
            self.table.setItem(i, 4, QTableWidgetItem(next_action[:80] if next_action else ""))

            for col in range(1, 5):
                item = self.table.item(i, col)
                if item:
                    item.setData(Qt.ItemDataRole.UserRole, proj_id)

        # Pre-check good candidates based on name/alias matching
        try:
            client_row = self.db.client_get(self.client_id) or {}
            candidates = {str(client_row.get("name", "")).lower()}
            for alias in (client_row.get("aliases") or client_row.get("aliases_json") or []):
                if alias:
                    candidates.add(str(alias).lower())

            for i, row in enumerate(self.unlinked_projects):
                name = (row[1] or "").lower()
                if any(cand and cand in name for cand in candidates if cand):
                    chk = self.table.cellWidget(i, 0)
                    if isinstance(chk, QCheckBox):
                        chk.setChecked(True)
        except Exception:
            pass

        self.table.setRowCount(len(self.unlinked_projects))

        for i, row in enumerate(self.unlinked_projects):
            proj_id = row[0]
            name = row[1] or "(unnamed)"
            status = row[4] or ""
            deadline = row[6] or ""
            next_action = row[7] or row[16] or ""  # next_action or suggested_next_action

            # Checkbox column
            chk = QCheckBox()
            chk.setChecked(False)
            self.table.setCellWidget(i, 0, chk)

            # Data columns
            self.table.setItem(i, 1, QTableWidgetItem(name))
            self.table.setItem(i, 2, QTableWidgetItem(status))
            self.table.setItem(i, 3, QTableWidgetItem(deadline))
            self.table.setItem(i, 4, QTableWidgetItem(next_action[:80] if next_action else ""))

            # Store project id
            for col in range(1, 5):
                item = self.table.item(i, col)
                if item:
                    item.setData(Qt.ItemDataRole.UserRole, proj_id)

    def _filter_table(self, text: str = ""):
        text = (text or self.search_edit.text()).lower().strip()
        for row in range(self.table.rowCount()):
            match = False
            for col in range(1, 5):  # skip checkbox column
                item = self.table.item(row, col)
                if item and text in item.text().lower():
                    match = True
                    break
            self.table.setRowHidden(row, not match)

    def _link_selected(self):
        selected_ids = set()

        for row in range(self.table.rowCount()):
            chk = self.table.cellWidget(row, 0)
            if isinstance(chk, QCheckBox) and chk.isChecked():
                item = self.table.item(row, 1)
                if item:
                    pid = item.data(Qt.ItemDataRole.UserRole)
                    if pid:
                        selected_ids.add(int(pid))

        if not selected_ids:
            QMessageBox.information(self, "Link Projects", "No projects selected.")
            return

        linked_count = 0
        for pid in selected_ids:
            try:
                self.db.cos_update_project(pid, client_id=self.client_id)
                linked_count += 1
            except Exception as e:
                print(f"Failed to link project {pid}: {e}")

        if linked_count > 0:
            QMessageBox.information(
                self, "Link Projects",
                f"Successfully linked {linked_count} project(s) to {self.client_name}."
            )
            self.accept()
        else:
            QMessageBox.warning(self, "Link Projects", "No projects were linked.")


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
        prof_widget = self._profile_widget(prof)
        self.dossier_layout.addWidget(self._section("Profile", prof_widget))

        # Edit button for profile (right after Profile section)
        edit_row = QHBoxLayout()
        btn_edit = QPushButton("Edit Client Profile…")
        btn_edit.clicked.connect(lambda: self._edit_current_client())
        edit_row.addWidget(btn_edit)
        edit_row.addStretch()
        edit_w = QWidget()
        edit_w.setLayout(edit_row)
        self.dossier_layout.addWidget(edit_w)

        mems = snap.get("memory", [])
        self.dossier_layout.addWidget(self._section("Memory", self._memory_widget(mems)))

        # Recent Activity (consolidated view — high value for "what's happening with this client")
        activity = self._build_recent_activity(snap)
        if activity:
            self.dossier_layout.addWidget(self._section("Recent Activity", self._activity_widget(activity)))

        projs = snap.get("projects", [])
        # Use interactive list for better per-item clickability
        projects_widget = self._projects_interactive_widget(projs) if projs else self._projects_widget(projs)
        self.dossier_layout.addWidget(self._section("Projects", projects_widget))

        # Project actions row (Link + Create + Unlink)
        proj_actions = QHBoxLayout()
        btn_link = QPushButton("Link existing projects…")
        btn_link.setToolTip("Attach projects from the Tasks / project board to this client")
        btn_link.clicked.connect(self._open_link_projects_dialog)
        proj_actions.addWidget(btn_link)

        btn_create = QPushButton("Create new project for this client")
        btn_create.setToolTip("Quickly create a new project linked to this client")
        btn_create.clicked.connect(self._create_new_project_for_client)
        proj_actions.addWidget(btn_create)

        btn_unlink = QPushButton("Manage linked projects…")
        btn_unlink.setToolTip("Unlink projects from this client")
        btn_unlink.clicked.connect(self._open_unlink_projects_dialog)
        proj_actions.addWidget(btn_unlink)

        btn_open_tasks = QPushButton("Open in Tasks tab")
        btn_open_tasks.setToolTip("Open this client's projects in the Tasks → Projects view")
        btn_open_tasks.clicked.connect(self._open_client_projects_in_tasks)
        proj_actions.addWidget(btn_open_tasks)

        proj_actions.addStretch()
        proj_actions_w = QWidget()
        proj_actions_w.setLayout(proj_actions)
        self.dossier_layout.addWidget(proj_actions_w)

        assigns = snap.get("assignments", [])
        # Use interactive list for per-assignment clickability when possible
        assignments_widget = self._assignments_interactive_widget(assigns) if assigns else self._assignments_widget(assigns)
        self.dossier_layout.addWidget(self._section("Assignments", assignments_widget))

        # Quick actions for Assignments
        asg_row = QHBoxLayout()
        btn_view_asg = QPushButton("View all in Chief of Staff")
        btn_view_asg.clicked.connect(self._open_chief_of_staff_for_client)
        asg_row.addWidget(btn_view_asg)
        asg_row.addStretch()
        asg_w = QWidget()
        asg_w.setLayout(asg_row)
        self.dossier_layout.addWidget(asg_w)

        tasks = snap.get("tasks", [])
        self.dossier_layout.addWidget(self._section("Tasks", self._tasks_widget(tasks)))

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
        name = prof.get("name") or "Unnamed"
        txt = f"<b>{name}</b> <span style='color:#8a8f98'>(#{prof.get('id')})</span><br>"

        aliases = prof.get("aliases") or []
        if aliases:
            alias_str = ", ".join(aliases)
            txt += f"<span style='color:#6b8cae'>Aliases:</span> {alias_str}<br>"

        domains = prof.get("domain_rules") or []
        if domains:
            dom_str = ", ".join(domains)
            txt += f"<span style='color:#6b8cae'>Key domains:</span> {dom_str}<br>"

        if prof.get("notes"):
            txt += f"<br><i>{prof['notes']}</i>"

        w.setHtml(txt)
        w.setMaximumHeight(140)
        return w

    def _memory_widget(self, memories: list[dict]) -> QWidget:
        w = QTextEdit()
        w.setReadOnly(True)
        if not memories:
            w.setPlainText(
                "No approved memory linked to this client yet.\n\n"
                "Use the 'Add to Memory' button below to teach client-specific facts, preferences, or constraints."
            )
            w.setMaximumHeight(100)
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

    def _build_recent_activity(self, snap: dict) -> list[dict]:
        """Merge recent emails, meetings, assignments, and tasks into a dated activity list."""
        items: list[dict] = []

        for e in snap.get("recent_emails", []) or []:
            ts = e.get("timestamp") or ""
            items.append({
                "date": ts[:10] if ts else "",
                "type": "Email",
                "title": e.get("subject") or "(no subject)",
                "subtitle": e.get("sender") or "",
                "detail": (e.get("content") or "")[:120],
            })

        for m in snap.get("recent_meetings", []) or []:
            d = m.get("meeting_date") or ""
            items.append({
                "date": d[:10] if d else "",
                "type": "Meeting",
                "title": m.get("meeting_with") or "Meeting",
                "subtitle": m.get("status") or "",
                "detail": (m.get("notes") or "")[:120],
            })

        for a in snap.get("assignments", []) or []:
            due = a.get("due_date") or a.get("due") or ""
            items.append({
                "date": due[:10] if due else "",
                "type": "Assignment",
                "title": a.get("title") or "(untitled)",
                "subtitle": f"{a.get('assignee_code','')} • {a.get('status','')}",
                "detail": "",
            })

        for t in snap.get("tasks", []) or []:
            due = t.get("due_date") or ""
            items.append({
                "date": due[:10] if due else "",
                "type": "Task",
                "title": t.get("title") or "(untitled)",
                "subtitle": t.get("status") or "",
                "detail": "",
            })

        # Sort by date descending (newest first), take top 12
        items.sort(key=lambda x: x.get("date") or "", reverse=True)
        return items[:12]

    def _activity_widget(self, activities: list[dict]) -> QWidget:
        w = QTextEdit()
        w.setReadOnly(True)
        if not activities:
            w.setPlainText("No recent activity.")
            return w

        lines = []
        for a in activities:
            date = a.get("date") or "—"
            typ = a.get("type", "")
            title = a.get("title", "")
            sub = a.get("subtitle", "")
            line = f"[{date}] {typ}: {title}"
            if sub:
                line += f"  — {sub}"
            lines.append(line)

        w.setPlainText("\n".join(lines))
        w.setMaximumHeight(200)
        return w

    def _assignments_widget(self, assignments: list[dict]) -> QWidget:
        """Fallback text view."""
        w = QTextEdit()
        w.setReadOnly(True)
        if not assignments:
            w.setPlainText(
                "No assignments for this client yet.\n\n"
                "→ Click 'View in Chief of Staff' below to delegate work.\n"
                "→ Use 'New Assignment' (from the quick actions at the bottom) to create one directly."
            )
            w.setMaximumHeight(110)
            return w

        lines = []
        for a in assignments[:12]:
            title = a.get("title") or "(untitled)"
            assignee = a.get("assignee_code") or "?"
            status = a.get("status") or ""
            prio = a.get("priority")
            due = a.get("due_date") or ""

            line = f"• {assignee}: {title}"
            meta = []
            if prio is not None:
                meta.append(f"P{prio}")
            if status:
                meta.append(status)
            if due:
                meta.append(f"due {due}")
            if meta:
                line += "  [" + " • ".join(meta) + "]"
            lines.append(line)

        lines.append("\n(Click 'View in Chief of Staff' below to manage these)")
        w.setPlainText("\n".join(lines))
        w.setMaximumHeight(200)
        return w

    def _assignments_interactive_widget(self, assignments: list[dict]) -> QWidget:
        """Interactive list with per-assignment 'Open' buttons for deeper clickability."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        list_widget = QListWidget()
        list_widget.setMaximumHeight(200)
        list_widget.setAlternatingRowColors(True)

        for a in assignments[:15]:
            aid = a.get("id")
            title = a.get("title") or "(untitled)"
            assignee = a.get("assignee_code") or "?"
            status = a.get("status") or ""
            prio = a.get("priority")

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, aid)
            text = f"{assignee}: {title}"
            if prio is not None:
                text += f"  [P{prio}]"
            if status:
                text += f"  [{status}]"
            item.setText(text)
            list_widget.addItem(item)

        def on_item_double_clicked(item):
            aid = item.data(Qt.ItemDataRole.UserRole)
            if aid:
                self._open_assignment_in_chief_of_staff(int(aid))

        list_widget.itemDoubleClicked.connect(on_item_double_clicked)

        btn_row = QHBoxLayout()
        btn_open = QPushButton("Open Selected in Chief of Staff")
        btn_open.clicked.connect(lambda: self._open_selected_assignment_from_list(list_widget))
        btn_row.addWidget(btn_open)
        btn_row.addStretch()

        layout.addWidget(list_widget)
        layout.addLayout(btn_row)

        return container

    def _open_selected_assignment_from_list(self, list_widget: QListWidget):
        current = list_widget.currentItem()
        if not current:
            QMessageBox.information(self, "Assignments", "Select an assignment first.")
            return
        aid = current.data(Qt.ItemDataRole.UserRole)
        if aid:
            self._open_assignment_in_chief_of_staff(int(aid))

    def _open_assignment_in_chief_of_staff(self, assignment_id: int):
        """Switch to Chief of Staff and attempt to focus the specific assignment (per-item clickability)."""
        if hasattr(self.parent(), "tab_widget"):
            tw = self.parent().tab_widget
            for i in range(tw.count()):
                if tw.tabText(i) == "Chief of Staff":
                    cos_tab = tw.widget(i)
                    tw.setCurrentIndex(i)
                    try:
                        if hasattr(cos_tab, "focus_on_assignment"):
                            cos_tab.focus_on_assignment(assignment_id)
                        else:
                            # Fallback to the existing client-focused behavior
                            client = self.db.client_get(self._current_client_id) if self._current_client_id else None
                            if client:
                                cos_tab.focus_on_client(self._current_client_id, client.get("name"))
                    except Exception as e:
                        logger.warning(f"Failed to focus assignment in CoS: {e}")
                    return

    def _tasks_widget(self, tasks: list[dict]) -> QWidget:
        w = QTextEdit()
        w.setReadOnly(True)
        if not tasks:
            w.setPlainText(
                "No tasks linked to this client's projects yet.\n\n"
                "Tasks created for linked projects will appear here automatically."
            )
            w.setMaximumHeight(90)
            return w

        lines = []
        for t in tasks[:15]:
            title = t.get("title") or "(untitled)"
            status = t.get("status") or ""
            due = t.get("due_date") or ""
            prio = t.get("priority")

            line = f"• {title}"
            meta = []
            if status:
                meta.append(status)
            if prio is not None:
                meta.append(f"P{prio}")
            if due:
                meta.append(f"due {due}")
            if meta:
                line += "  [" + " • ".join(meta) + "]"
            lines.append(line)

        w.setPlainText("\n".join(lines))
        w.setMaximumHeight(180)
        return w

    def _projects_widget(self, projects: list[dict]) -> QWidget:
        """Fallback text view (used when there are no projects)."""
        w = QTextEdit()
        w.setReadOnly(True)
        if not projects:
            w.setPlainText(
                "No projects linked to this client yet.\n\n"
                "→ Use 'Link existing projects…' to attach work from the Tasks tab.\n"
                "→ Use 'Create new project for this client' to start fresh."
            )
            w.setMaximumHeight(120)
            return w

        lines = []
        for p in projects[:10]:
            name = p.get("name") or "(unnamed)"
            status = p.get("status") or ""
            next_action = p.get("next_action") or p.get("suggested_next_action") or ""
            due = p.get("deadline") or ""

            line = f"• {name}"
            meta = []
            if status:
                meta.append(status)
            if due:
                meta.append(f"due {due}")
            if meta:
                line += "  [" + " • ".join(meta) + "]"
            if next_action:
                line += f"\n    → {next_action[:90]}"
            lines.append(line)

        lines.append("\n(Use the buttons below to link more or create new projects)")
        w.setPlainText("\n".join(lines))
        w.setMaximumHeight(200)
        return w

    def _projects_interactive_widget(self, projects: list[dict]) -> QWidget:
        """Interactive list with per-project 'Open' buttons for deeper clickability."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        list_widget = QListWidget()
        list_widget.setMaximumHeight(220)
        list_widget.setAlternatingRowColors(True)

        for p in projects[:15]:
            pid = p.get("id")
            name = p.get("name") or "(unnamed)"
            status = p.get("status") or ""
            due = (p.get("deadline") or "")[:10]

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, pid)
            item.setText(f"{name}  [{status}]" + (f"  due {due}" if due else ""))
            list_widget.addItem(item)

        def on_item_double_clicked(item):
            pid = item.data(Qt.ItemDataRole.UserRole)
            if pid:
                self._open_project_in_tasks(int(pid))

        list_widget.itemDoubleClicked.connect(on_item_double_clicked)

        # Buttons row for the currently selected item in the list
        btn_row = QHBoxLayout()
        btn_open = QPushButton("Open Selected in Tasks")
        btn_open.clicked.connect(lambda: self._open_selected_project_from_list(list_widget))
        btn_row.addWidget(btn_open)
        btn_row.addStretch()

        layout.addWidget(list_widget)
        layout.addLayout(btn_row)

        return container

    def _open_selected_project_from_list(self, list_widget: QListWidget):
        current = list_widget.currentItem()
        if not current:
            QMessageBox.information(self, "Projects", "Select a project first.")
            return
        pid = current.data(Qt.ItemDataRole.UserRole)
        if pid:
            self._open_project_in_tasks(int(pid))

    def _open_project_in_tasks(self, project_id: int):
        """Switch to Tasks tab and select the specific project (per-item clickability)."""
        if hasattr(self.parent(), "tab_widget"):
            tw = self.parent().tab_widget
            for i in range(tw.count()):
                if tw.tabText(i) == "Tasks":
                    tasks_tab = tw.widget(i)
                    tw.setCurrentIndex(i)
                    try:
                        if hasattr(tasks_tab, "show_and_select_project"):
                            success = tasks_tab.show_and_select_project(project_id)
                            if not success:
                                QMessageBox.information(self, "Projects", "Project opened in Tasks tab (could not auto-select).")
                    except Exception as e:
                        logger.warning(f"Failed to select project in Tasks: {e}")
                    return
            QMessageBox.information(self, "Projects", "Tasks tab not found.")

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

    def _edit_current_client(self):
        if self._current_client_id is None:
            return
        client = self.db.client_get(self._current_client_id)
        if not client:
            QMessageBox.warning(self, "Clients", "Could not load client for editing.")
            return

        dlg = ClientEditDialog(self.db, client, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load_clients()
            self._render_dossier(self._current_client_id)

    def refresh(self):
        """Public refresh hook."""
        self._load_clients()
        if self._current_client_id:
            self._render_dossier(self._current_client_id)

    def _request_new_note(self):
        """Switch to Notes tab and pre-fill context with the current client name."""
        if self._current_client_id is None:
            return
        client = self.db.client_get(self._current_client_id)
        client_name = (client or {}).get("name") or f"Client #{self._current_client_id}"

        if hasattr(self.parent(), "tab_widget"):
            tw = self.parent().tab_widget
            notes_tab = None
            for i in range(tw.count()):
                if tw.tabText(i) == "Notes":
                    tw.setCurrentIndex(i)
                    notes_tab = tw.widget(i)
                    break

            # Try to pre-fill the Notes context with the client name
            if notes_tab is not None:
                try:
                    if hasattr(notes_tab, "context_input"):
                        notes_tab.context_input.setText(client_name)
                    if hasattr(notes_tab, "update_context"):
                        # Fire the context update so the document loads/creates immediately
                        notes_tab.update_context()
                except Exception:
                    pass  # Non-fatal; user can still type the context manually

    def _request_new_assignment(self):
        """Open the assignment dialog pre-filled with this client (best UX from dossier)."""
        if self._current_client_id is None:
            return
        client = self.db.client_get(self._current_client_id)
        if not client:
            return

        # Import here to avoid circular import at module load
        from gui.chief_of_staff_tab import CosAssignmentDialog

        dlg = CosAssignmentDialog(
            self.db,
            self,
            client_id=self._current_client_id,
            client_name=client.get("name"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        vals = dlg.values()
        assignee = str(vals.get("assignee_code") or "").strip().lower()
        title = str(vals.get("title") or "").strip()
        brief = str(vals.get("brief_md") or "").strip()
        priority = int(vals.get("priority") or 3)
        due_date = vals.get("due_date")

        if not assignee or not title or not brief:
            QMessageBox.warning(self, "Assignments", "Missing required assignment fields.")
            return

        # Build rich context for the dossier
        context_obj = {
            "source": "clients_dossier",
            "client_id": int(self._current_client_id),
            "client_name": client.get("name"),
        }

        try:
            aid = self.db.agent_create_assignment(
                title=title,
                brief_md=brief,
                requester_code="navi",
                assignee_code=assignee,
                priority=priority,
                due_date=due_date,
                context_json=context_obj,
            )
            if not aid:
                QMessageBox.warning(self, "Assignments", "Could not create assignment.")
                return

            from core.agent_chat_service import create_assignment_thread, prime_assignment_handoff

            thread_id = create_assignment_thread(
                self.db,
                assignment_id=int(aid),
                assignee_code=assignee,
                reason="clients_dossier_assign",
                actor_code="navi",
                context_json=context_obj,
            )
            if thread_id:
                prime_assignment_handoff(
                    self.db,
                    assignment_id=int(aid),
                    thread_id=int(thread_id),
                )

            QMessageBox.information(
                self,
                "Assignments",
                f"Assignment created for {client.get('name')}.\n\nYou can view it in the Chief of Staff tab.",
            )
            # Refresh dossier so the new assignment appears
            self._render_dossier(self._current_client_id)

        except Exception as e:
            QMessageBox.warning(self, "Assignments", f"Failed to create assignment:\n{e}")

    def _open_link_projects_dialog(self):
        """Open a rich table dialog to link existing unlinked projects to this client."""
        if self._current_client_id is None:
            return

        client = self.db.client_get(self._current_client_id)
        client_name = (client or {}).get("name") or f"Client #{self._current_client_id}"

        dlg = LinkProjectsDialog(self.db, self._current_client_id, client_name, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # Refresh the dossier so newly linked projects appear
            self._render_dossier(self._current_client_id)
            self._load_clients()  # in case project names affect anything

    def _open_unlink_projects_dialog(self):
        """Open dialog to unlink currently linked projects from this client."""
        if self._current_client_id is None:
            return
        client = self.db.client_get(self._current_client_id)
        client_name = (client or {}).get("name") or f"Client #{self._current_client_id}"

        dlg = UnlinkProjectsDialog(self.db, self._current_client_id, client_name, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._render_dossier(self._current_client_id)

    def _open_client_projects_in_tasks(self):
        """Switch to the Tasks tab and show the Projects subtab (with this client's projects)."""
        if hasattr(self.parent(), "tab_widget"):
            tw = self.parent().tab_widget
            for i in range(tw.count()):
                if tw.tabText(i) == "Tasks":
                    tw.setCurrentIndex(i)
                    # Try to switch the inner tab to the Projects panel if TasksTab supports it
                    try:
                        tasks_tab = tw.widget(i)
                        if hasattr(tasks_tab, "switch_to_projects_tab"):
                            tasks_tab.switch_to_projects_tab()
                    except Exception:
                        pass
                    break

    def _open_chief_of_staff_for_client(self):
        """Switch to Chief of Staff tab. Behavior depends on user preference (light vs strong)."""
        if self._current_client_id is None:
            return

        client = self.db.client_get(self._current_client_id)
        client_name = (client or {}).get("name") or f"Client #{self._current_client_id}"

        mode = ap.get_client_dossier_navigation_mode(self.db)

        if hasattr(self.parent(), "tab_widget"):
            tw = self.parent().tab_widget
            cos_index = None
            cos_tab = None
            for i in range(tw.count()):
                if tw.tabText(i) == "Chief of Staff":
                    cos_index = i
                    cos_tab = tw.widget(i)
                    break

            if cos_index is None:
                return

            tw.setCurrentIndex(cos_index)

            # Strong mode: try to create/focus a client-specific CoS chat
            if mode == "strong" and cos_tab is not None:
                try:
                    # Try to create a new focused chat for this client if the CoS tab supports it
                    if hasattr(cos_tab, "_create_new_chat_for_client"):
                        cos_tab._create_new_chat_for_client(self._current_client_id, client_name)
                    else:
                        # Fallback: just switch and let the user start a chat
                        cos_tab.show_toast(f"Switched to Chief of Staff — client context for {client_name} is available", 4000)
                except Exception:
                    pass
            else:
                # Light mode: just switch + friendly toast
                try:
                    if cos_tab and hasattr(cos_tab, "show_toast"):
                        cos_tab.show_toast(f"Chief of Staff ready — mention '{client_name}' for full dossier context", 4500)
                except Exception:
                    pass

    def _create_new_project_for_client(self):
        """Open the project creation dialog pre-filled with this client."""
        if self._current_client_id is None:
            return

        client = self.db.client_get(self._current_client_id)
        client_name = (client or {}).get("name") or f"Client #{self._current_client_id}"

        try:
            from gui.project_management_panel import ProjectEditDialog
        except Exception as e:
            QMessageBox.warning(self, "Projects", f"Could not load project editor:\n{e}")
            return

        # Create dialog with client pre-selected
        dlg = ProjectEditDialog(self, project=None, db=self.db)
        # Pre-select the client in the combo if possible
        try:
            for i in range(dlg.client_combo.count()):
                if dlg.client_combo.itemData(i) == self._current_client_id:
                    dlg.client_combo.setCurrentIndex(i)
                    break
            if dlg.client_edit:
                dlg.client_edit.setText(client_name)
        except Exception:
            pass

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        vals = dlg.values()
        if not vals.get("name"):
            QMessageBox.warning(self, "Projects", "Project name is required.")
            return

        try:
            pid = self.db.cos_insert_project(
                name=vals["name"],
                client=vals.get("client") or client_name,
                status=vals.get("status", "Active"),
                deadline=vals.get("deadline"),
                client_id=self._current_client_id,
            )
            QMessageBox.information(
                self, "Projects",
                f"Project '{vals['name']}' created and linked to {client_name}."
            )
            self._render_dossier(self._current_client_id)
        except Exception as e:
            QMessageBox.warning(self, "Projects", f"Could not create project:\n{e}")

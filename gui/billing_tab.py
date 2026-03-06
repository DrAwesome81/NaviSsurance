from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QInputDialog,
)

from core.billing.invoice_service import generate_invoice_draft, previous_month_period
from core.billing.template_render import list_placeholders
from core.billing.ledger_bridge import notify_ledger_invoice_drafts
from core.billing.template_import import import_invoice_template_from_pdf, wire_invoice_placeholders_html
from core.db import DatabaseManager
from gui.agent_console import AgentConsole

logger = logging.getLogger(__name__)


_DEFAULT_TEMPLATE = """# Invoice

**Client:** {{client_name}}  
**Period:** {{period_start}} to {{period_end}}

## Line items

{{line_items_md}}

## Totals

- Total hours: **{{total_hours}}**
- Total amount: **{{total_amount}}**
"""


class BillingTab(QWidget):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db

        self._timer_running = False
        self._timer_start: datetime | None = None
        self._timer_ui = QTimer(self)
        self._timer_ui.setInterval(500)
        self._timer_ui.timeout.connect(self._tick_timer_label)

        self._setup_ui()
        self._ensure_default_template()
        self._refresh_clients()
        self._refresh_templates()
        self._load_autorun_settings()
        self._refresh_time_entries()
        self._refresh_drafts()

    # -------------------------
    # UI setup
    # -------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        title = QLabel("Billing")
        title.setStyleSheet("color: #e8eaed; font-weight: 700; font-size: 14px; margin: 0;")
        root.addWidget(title)

        subtitle = QLabel("Manual time entry + invoice draft generation (review before sending).")
        subtitle.setStyleSheet("color: #9aa0a6; font-size: 12px;")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        # Left: time entry
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        splitter.addWidget(left)

        # Client row
        client_row = QHBoxLayout()
        client_row.addWidget(QLabel("Client:"))
        self.client_combo = QComboBox()
        self.client_combo.currentIndexChanged.connect(lambda _i: self._on_client_changed())
        client_row.addWidget(self.client_combo, 1)
        new_client_btn = QPushButton("New client…")
        new_client_btn.clicked.connect(self._on_new_client)
        client_row.addWidget(new_client_btn)
        left_layout.addLayout(client_row)

        # Timer entry form
        timer_group = QGroupBox("Add time entry")
        timer_layout = QVBoxLayout(timer_group)

        desc_row = QHBoxLayout()
        desc_row.addWidget(QLabel("Description:"))
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("What did you do?")
        desc_row.addWidget(self.desc_edit, 1)
        timer_layout.addLayout(desc_row)

        btn_row = QHBoxLayout()
        self.billable_checkbox = QCheckBox("Billable")
        self.billable_checkbox.setChecked(True)
        btn_row.addWidget(self.billable_checkbox)

        self.timer_label = QLabel("Timer: —")
        self.timer_label.setStyleSheet("color: #6b8cae; font-weight: 600;")
        btn_row.addWidget(self.timer_label)
        btn_row.addStretch()

        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._start_timer)
        btn_row.addWidget(self.start_btn)
        self.stop_btn = QPushButton("Stop & Save")
        self.stop_btn.clicked.connect(self._stop_and_save_timer)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.stop_btn)

        manual_btn = QPushButton("Manual add…")
        manual_btn.clicked.connect(self._manual_add)
        btn_row.addWidget(manual_btn)

        timer_layout.addLayout(btn_row)
        left_layout.addWidget(timer_group)

        # Filters + table
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("From:"))
        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDate(date.today().replace(day=1))
        self.from_date.dateChanged.connect(lambda _d: self._refresh_time_entries())
        filter_row.addWidget(self.from_date)
        filter_row.addWidget(QLabel("To:"))
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDate(date.today())
        self.to_date.dateChanged.connect(lambda _d: self._refresh_time_entries())
        filter_row.addWidget(self.to_date)
        del_btn = QPushButton("Delete selected")
        del_btn.clicked.connect(self._delete_selected_entries)
        filter_row.addWidget(del_btn)
        left_layout.addLayout(filter_row)

        self.entries_table = QTableWidget(0, 6)
        self.entries_table.setHorizontalHeaderLabels(["Date", "Start", "End", "Minutes", "Hours", "Description"])
        self.entries_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.entries_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        left_layout.addWidget(self.entries_table, 1)

        # Right: invoices
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        splitter.addWidget(right)
        splitter.setSizes([650, 650])

        # Autorun settings
        autorun_group = QGroupBox("Monthly auto-draft (in-app)")
        autorun_layout = QHBoxLayout(autorun_group)
        self.autorun_enabled = QCheckBox("Enabled")
        self.autorun_enabled.setChecked(True)
        self.autorun_enabled.toggled.connect(lambda _b: self._save_autorun_settings())
        autorun_layout.addWidget(self.autorun_enabled)
        autorun_layout.addWidget(QLabel("Day of month:"))
        self.autorun_dom = QSpinBox()
        self.autorun_dom.setRange(1, 28)
        self.autorun_dom.setValue(1)
        self.autorun_dom.valueChanged.connect(lambda _v: self._save_autorun_settings())
        autorun_layout.addWidget(self.autorun_dom)
        autorun_layout.addStretch()
        right_layout.addWidget(autorun_group)

        template_group = QGroupBox("Invoice template")
        template_layout = QVBoxLayout(template_group)

        trow = QHBoxLayout()
        trow.addWidget(QLabel("Template:"))
        self.template_combo = QComboBox()
        self.template_combo.currentIndexChanged.connect(lambda _i: self._load_selected_template_into_editor())
        trow.addWidget(self.template_combo, 1)
        new_t_btn = QPushButton("New…")
        new_t_btn.clicked.connect(self._on_new_template)
        trow.addWidget(new_t_btn)
        import_t_btn = QPushButton("Import…")
        import_t_btn.clicked.connect(self._on_import_template)
        trow.addWidget(import_t_btn)
        save_t_btn = QPushButton("Save")
        save_t_btn.clicked.connect(self._on_save_template)
        trow.addWidget(save_t_btn)
        wire_btn = QPushButton("Auto-wire")
        wire_btn.setToolTip("Replace common fields with {{placeholders}} and insert {{line_items_html}}.")
        wire_btn.clicked.connect(self._on_wire_template_placeholders)
        trow.addWidget(wire_btn)
        set_default_btn = QPushButton("Set default")
        set_default_btn.clicked.connect(self._on_set_default_template)
        trow.addWidget(set_default_btn)
        template_layout.addLayout(trow)

        self.template_editor = QPlainTextEdit()
        self.template_editor.setPlaceholderText("Write your invoice template here (use {{placeholders}}).")
        self.template_editor.setMinimumHeight(140)
        template_layout.addWidget(self.template_editor, 1)
        right_layout.addWidget(template_group)

        gen_group = QGroupBox("Generate invoice drafts")
        gen_layout = QVBoxLayout(gen_group)
        gen_row = QHBoxLayout()
        self.gen_prev_btn = QPushButton("Generate previous month")
        self.gen_prev_btn.clicked.connect(self._generate_previous_month)
        gen_row.addWidget(self.gen_prev_btn)
        gen_row.addWidget(QLabel("Or period:"))
        self.inv_from = QDateEdit()
        self.inv_from.setCalendarPopup(True)
        self.inv_to = QDateEdit()
        self.inv_to.setCalendarPopup(True)
        ps, pe = previous_month_period()
        self.inv_from.setDate(ps)
        self.inv_to.setDate(pe)
        gen_row.addWidget(self.inv_from)
        gen_row.addWidget(self.inv_to)
        gen_range_btn = QPushButton("Generate")
        gen_range_btn.clicked.connect(self._generate_range)
        gen_row.addWidget(gen_range_btn)
        gen_force_btn = QPushButton("Force regenerate")
        gen_force_btn.setToolTip("Creates a new draft even if one already exists for that client and period.")
        gen_force_btn.clicked.connect(self._generate_range_force_new)
        gen_row.addWidget(gen_force_btn)
        gen_row.addStretch()
        gen_layout.addLayout(gen_row)
        right_layout.addWidget(gen_group)

        drafts_group = QGroupBox("Invoice drafts")
        drafts_layout = QVBoxLayout(drafts_group)
        drafts_split = QSplitter(Qt.Orientation.Horizontal)
        drafts_layout.addWidget(drafts_split, 1)

        self.drafts_list = QListWidget()
        self.drafts_list.itemClicked.connect(self._on_draft_selected)
        drafts_split.addWidget(self.drafts_list)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(6)
        self.draft_preview = QTextBrowser()
        self.draft_preview.setOpenExternalLinks(True)
        preview_layout.addWidget(self.draft_preview, 1)
        preview_btns = QHBoxLayout()
        open_file_btn = QPushButton("Open file…")
        open_file_btn.clicked.connect(self._open_selected_draft_file)
        preview_btns.addWidget(open_file_btn)
        save_as_btn = QPushButton("Save As…")
        save_as_btn.clicked.connect(self._save_selected_draft_as)
        preview_btns.addWidget(save_as_btn)
        mark_reviewed_btn = QPushButton("Mark reviewed")
        mark_reviewed_btn.clicked.connect(self._mark_selected_reviewed)
        preview_btns.addWidget(mark_reviewed_btn)
        preview_btns.addStretch()
        preview_layout.addLayout(preview_btns)
        drafts_split.addWidget(preview_panel)
        drafts_split.setSizes([260, 520])

        right_layout.addWidget(drafts_group, 1)

        ledger_group = QGroupBox("Optional: Ledger (billing assistant)")
        ledger_group.setCheckable(True)
        ledger_group.setChecked(False)
        ledger_layout = QVBoxLayout(ledger_group)
        self.ledger_console = AgentConsole(self.db, agent_code="ledger", parent=self)
        self.ledger_console.setVisible(False)
        ledger_layout.addWidget(self.ledger_console)
        ledger_group.toggled.connect(lambda checked: self.ledger_console.setVisible(bool(checked)))
        right_layout.addWidget(ledger_group)

    # -------------------------
    # Data helpers
    # -------------------------

    def _current_client_id(self) -> int | None:
        cid = self.client_combo.currentData()
        return int(cid) if cid is not None else None

    def _current_template_id(self) -> int | None:
        tid = self.template_combo.currentData()
        return int(tid) if tid is not None else None

    # -------------------------
    # Clients
    # -------------------------

    def _refresh_clients(self) -> None:
        self.client_combo.blockSignals(True)
        self.client_combo.clear()
        clients = self.db.billing_clients_list(active_only=True)
        for c in clients:
            self.client_combo.addItem(str(c.get("name") or f"Client {c.get('id')}"), int(c["id"]))
        if not clients:
            # Keep startup non-blocking: do not show modal prompts while app loads.
            self.client_combo.addItem("No clients yet (click New client…)", None)
        self.client_combo.blockSignals(False)

    def _on_new_client(self) -> None:
        name, ok = QInputDialog.getText(self, "New client", "Client name:")
        if not ok or not str(name).strip():
            return
        email, _ok2 = QInputDialog.getText(self, "New client", "Billing email (optional):")
        rate_s, _ok3 = QInputDialog.getText(self, "New client", "Default hourly rate (optional):")
        rate = None
        if str(rate_s or "").strip():
            try:
                rate = float(str(rate_s).strip())
            except Exception:
                rate = None
        self.db.billing_client_create(name=str(name).strip(), billing_email=(email or "").strip() or None, default_rate=rate)
        self._refresh_clients()

    def _on_client_changed(self) -> None:
        self._refresh_time_entries()
        self._refresh_drafts()

    # -------------------------
    # Time entry
    # -------------------------

    def _start_timer(self) -> None:
        if self._timer_running:
            return
        if self._current_client_id() is None:
            QMessageBox.information(self, "Billing", "Create/select a client first.")
            return
        self._timer_running = True
        self._timer_start = datetime.now()
        self._timer_ui.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._tick_timer_label()

    def _stop_and_save_timer(self) -> None:
        if not self._timer_running or not self._timer_start:
            return
        cid = self._current_client_id()
        if cid is None:
            return
        end = datetime.now()
        delta = end - self._timer_start
        minutes = max(1, int(delta.total_seconds() // 60))
        desc = self.desc_edit.text().strip()
        billable = 1 if self.billable_checkbox.isChecked() else 0
        self.db.time_entry_add(
            client_id=cid,
            start_ts=self._timer_start.isoformat(timespec="seconds"),
            end_ts=end.isoformat(timespec="seconds"),
            minutes=minutes,
            description=desc,
            is_billable=billable,
        )
        self._timer_running = False
        self._timer_start = None
        self._timer_ui.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.timer_label.setText("Timer: —")
        self._refresh_time_entries()

    def _manual_add(self) -> None:
        cid = self._current_client_id()
        if cid is None:
            QMessageBox.information(self, "Billing", "Create/select a client first.")
            return
        minutes_s, ok = QInputDialog.getText(self, "Manual time entry", "Minutes:")
        if not ok:
            return
        try:
            minutes = int(str(minutes_s).strip())
        except Exception:
            QMessageBox.warning(self, "Billing", "Invalid minutes.")
            return
        minutes = max(1, minutes)
        desc = self.desc_edit.text().strip()
        now = datetime.now()
        start = now - timedelta(minutes=minutes)
        billable = 1 if self.billable_checkbox.isChecked() else 0
        self.db.time_entry_add(
            client_id=cid,
            start_ts=start.isoformat(timespec="seconds"),
            end_ts=now.isoformat(timespec="seconds"),
            minutes=minutes,
            description=desc,
            is_billable=billable,
        )
        self._refresh_time_entries()

    def _tick_timer_label(self) -> None:
        if not self._timer_running or not self._timer_start:
            return
        delta = datetime.now() - self._timer_start
        minutes = int(delta.total_seconds() // 60)
        seconds = int(delta.total_seconds() % 60)
        self.timer_label.setText(f"Timer: {minutes:02d}:{seconds:02d}")

    def _refresh_time_entries(self) -> None:
        cid = self._current_client_id()
        self.entries_table.setRowCount(0)
        if cid is None:
            return
        start = self.from_date.date().toPyDate()
        end = self.to_date.date().toPyDate()
        start_iso = datetime(start.year, start.month, start.day).isoformat()
        end_iso = (datetime(end.year, end.month, end.day) + timedelta(days=1)).isoformat()
        rows = self.db.time_entries_list(client_id=cid, start_ts=start_iso, end_ts=end_iso, limit=1000)
        self.entries_table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            st = str(e.get("start_ts") or "")
            en = str(e.get("end_ts") or "")
            mins = int(e.get("minutes") or 0)
            hrs = mins / 60.0
            self.entries_table.setItem(r, 0, QTableWidgetItem(st[:10]))
            self.entries_table.setItem(r, 1, QTableWidgetItem(st[11:19] if len(st) >= 19 else st))
            self.entries_table.setItem(r, 2, QTableWidgetItem(en[11:19] if len(en) >= 19 else en))
            self.entries_table.setItem(r, 3, QTableWidgetItem(str(mins)))
            self.entries_table.setItem(r, 4, QTableWidgetItem(f"{hrs:.2f}"))
            self.entries_table.setItem(r, 5, QTableWidgetItem(str(e.get("description") or "")))
            # Store id on row
            self.entries_table.item(r, 0).setData(Qt.ItemDataRole.UserRole, int(e.get("id") or 0))

        self.entries_table.resizeColumnsToContents()

    def _selected_entry_ids(self) -> list[int]:
        ids: list[int] = []
        for idx in self.entries_table.selectionModel().selectedRows():
            item = self.entries_table.item(idx.row(), 0)
            if not item:
                continue
            eid = item.data(Qt.ItemDataRole.UserRole)
            if eid:
                ids.append(int(eid))
        return sorted(set(ids))

    def _delete_selected_entries(self) -> None:
        ids = self._selected_entry_ids()
        if not ids:
            return
        ok = QMessageBox.question(self, "Delete", f"Delete {len(ids)} time entry(s)?")
        if ok != QMessageBox.StandardButton.Yes:
            return
        for eid in ids:
            try:
                self.db.time_entry_delete(eid)
            except Exception:
                continue
        self._refresh_time_entries()

    # -------------------------
    # Templates
    # -------------------------

    def _ensure_default_template(self) -> None:
        tmpls = self.db.invoice_templates_list()
        if tmpls:
            return
        try:
            tid = self.db.invoice_template_create(
                name="Default invoice (v1)", template_body=_DEFAULT_TEMPLATE, engine="placeholder_v1"
            )
            self.db.set_setting("billing.default_template_id", str(tid))
        except Exception:
            return

    def _refresh_templates(self) -> None:
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        tmpls = self.db.invoice_templates_list()
        for t in tmpls:
            tid = int(t.get("id") or 0)
            name = str(t.get("name") or f"Template {tid}")
            eng = str(t.get("engine") or "")
            suffix = "HTML" if "html" in eng.lower() else "MD"
            body = str(t.get("template_body") or "")
            ph_n = len(list_placeholders(body))
            ph_flag = "wired" if ph_n > 0 else "NO placeholders"
            self.template_combo.addItem(f"{name} (#{tid}, {suffix}, {ph_flag})", tid)
        self.template_combo.blockSignals(False)
        if tmpls:
            self._load_selected_template_into_editor()

    def _load_selected_template_into_editor(self) -> None:
        tid = self._current_template_id()
        if tid is None:
            self.template_editor.setPlainText("")
            return
        row = self.db.invoice_template_get(tid)
        self.template_editor.setPlainText(str(row.get("template_body") or "") if row else "")

    def _on_new_template(self) -> None:
        name, ok = QInputDialog.getText(self, "New template", "Template name:")
        if not ok or not str(name).strip():
            return
        tid = self.db.invoice_template_create(
            name=str(name).strip(), template_body=_DEFAULT_TEMPLATE, engine="placeholder_v1"
        )
        self._refresh_templates()
        # Select the new template.
        for i in range(self.template_combo.count()):
            if int(self.template_combo.itemData(i)) == int(tid):
                self.template_combo.setCurrentIndex(i)
                break

    def _on_save_template(self) -> None:
        tid = self._current_template_id()
        if tid is None:
            return
        body = self.template_editor.toPlainText()
        self.db.invoice_template_update(tid, template_body=body)
        self._refresh_templates()

    def _on_wire_template_placeholders(self) -> None:
        tid = self._current_template_id()
        if tid is None:
            return
        body = self.template_editor.toPlainText()
        if not body.strip():
            return
        wired = wire_invoice_placeholders_html(body)
        if wired == body:
            body_no_comments = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
            already_wired = ("{{line_items_html}}" in body_no_comments) and (
                "{{client_name}}" in body_no_comments or "{{invoice_number}}" in body_no_comments
            )
            QMessageBox.information(
                self,
                "Billing",
                (
                    "Auto-wire made no changes because this template already looks wired.\n\n"
                    "Next step: click Force regenerate to create a fresh draft."
                    if already_wired
                    else "Auto-wire made no changes.\n\n"
                    "This usually means it couldn't find the expected invoice labels in the HTML.\n"
                    "Try re-importing the PDF (new imports are wired automatically), or manually replace literal fields "
                    "with placeholders like {{client_name}} and add {{line_items_html}}."
                ),
            )
            return
        self.template_editor.setPlainText(wired)
        # Save immediately to avoid any ambiguity.
        try:
            self.db.invoice_template_update(int(tid), template_body=wired)
            self._refresh_templates()
            for i in range(self.template_combo.count()):
                if int(self.template_combo.itemData(i)) == int(tid):
                    self.template_combo.setCurrentIndex(i)
                    break
            QMessageBox.information(
                self,
                "Billing",
                "Auto-wire created placeholders and saved the template.\n\nNow click Force regenerate to render a fresh draft.",
            )
        except Exception as e:
            QMessageBox.warning(self, "Billing", f"Auto-wire updated the editor, but couldn't save:\n{e}")

    def _on_set_default_template(self) -> None:
        tid = self._current_template_id()
        if tid is None:
            return
        self.db.set_setting("billing.default_template_id", str(tid))
        QMessageBox.information(self, "Billing", "Default template set.")

    # -------------------------
    # Draft generation + review
    # -------------------------

    def _generate_previous_month(self) -> None:
        ps, pe = previous_month_period()
        self._generate(ps, pe)

    def _generate_range(self) -> None:
        ps = self.inv_from.date().toPyDate()
        pe = self.inv_to.date().toPyDate()
        self._generate(ps, pe, force_new=False)

    def _generate_range_force_new(self) -> None:
        ps = self.inv_from.date().toPyDate()
        pe = self.inv_to.date().toPyDate()
        self._generate(ps, pe, force_new=True)

    def _generate(self, ps: date, pe: date, *, force_new: bool) -> None:
        cid = self._current_client_id()
        tid = self._current_template_id()
        if cid is None:
            QMessageBox.information(self, "Billing", "Select a client first.")
            return
        if tid is None:
            QMessageBox.information(self, "Billing", "Create/select a template first.")
            return
        # Warn early if the template appears to have no real placeholders (so it will keep sample text).
        try:
            row = self.db.invoice_template_get(int(tid))
            body = str((row or {}).get("template_body") or "")
            placeholders = list_placeholders(body)
            if not placeholders:
                QMessageBox.information(
                    self,
                    "Billing",
                    "This template has no {{placeholders}}, so it will render exactly as-is (including any example text).\n\n"
                    "Use Import… / Auto-wire, or manually replace literals with placeholders like {{client_name}}, "
                    "{{period_range}}, {{total_amount_display}}, and {{line_items_html}}.",
                )
        except Exception:
            pass
        try:
            res = generate_invoice_draft(
                self.db,
                client_id=cid,
                period_start=ps,
                period_end=pe,
                template_id=tid,
                force_new=bool(force_new),
            )
            try:
                notify_ledger_invoice_drafts(
                    self.db,
                    draft_ids=[int(res.draft_id)],
                    trigger="manual_generate",
                    period_start=ps,
                    period_end=pe,
                )
            except Exception:
                pass
            self._refresh_drafts()
            # Select the newly created draft.
            for i in range(self.drafts_list.count()):
                it = self.drafts_list.item(i)
                if it and int(it.data(Qt.ItemDataRole.UserRole)) == int(res.draft_id):
                    self.drafts_list.setCurrentItem(it)
                    self._on_draft_selected(it)
                    break
            if getattr(res, "reused_existing", False) and not force_new:
                QMessageBox.information(
                    self,
                    "Billing",
                    f"Reused existing draft #{int(res.draft_id)} for this client and period.\n\n"
                    "If you changed the template and want a fresh render, click Force regenerate.",
                )
        except Exception as e:
            QMessageBox.warning(self, "Billing", f"Could not generate draft:\n{e}")

    def _refresh_drafts(self) -> None:
        self.drafts_list.clear()
        cid = self._current_client_id()
        drafts = self.db.invoice_drafts_list(client_id=cid, limit=200) if cid is not None else []
        for d in drafts:
            did = int(d.get("id") or 0)
            st = str(d.get("status") or "draft")
            ps = str(d.get("period_start") or "")
            pe = str(d.get("period_end") or "")
            item = QListWidgetItem(f"#{did} [{st}] {ps} → {pe}")
            item.setData(Qt.ItemDataRole.UserRole, did)
            self.drafts_list.addItem(item)

    def _on_draft_selected(self, item: QListWidgetItem) -> None:
        did = item.data(Qt.ItemDataRole.UserRole)
        if did is None:
            return
        row = self.db.invoice_draft_get(int(did))
        if not row:
            return
        md = str(row.get("rendered_body_md") or "")
        try:
            if "<html" in md.lower() or "<!doctype html" in md.lower():
                self.draft_preview.setHtml(md)
            else:
                self.draft_preview.setMarkdown(md)
        except Exception:
            self.draft_preview.setPlainText(md)

    def _selected_draft_id(self) -> int | None:
        it = self.drafts_list.currentItem()
        if not it:
            return None
        did = it.data(Qt.ItemDataRole.UserRole)
        return int(did) if did is not None else None

    def _open_selected_draft_file(self) -> None:
        did = self._selected_draft_id()
        if did is None:
            return
        row = self.db.invoice_draft_get(did)
        path = str((row or {}).get("file_path") or "").strip()
        if not path or not os.path.exists(path):
            QMessageBox.information(self, "Billing", "Draft file not found (it may not have been written).")
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]  # Windows
        except Exception as e:
            QMessageBox.warning(self, "Billing", f"Could not open file:\n{e}")

    def _save_selected_draft_as(self) -> None:
        did = self._selected_draft_id()
        if did is None:
            return
        row = self.db.invoice_draft_get(did)
        md = str((row or {}).get("rendered_body_md") or "")
        if not md:
            return
        is_html = "<html" in md.lower() or "<!doctype html" in md.lower()
        default_name = f"invoice_{did}.html" if is_html else f"invoice_{did}.md"
        filt = "HTML (*.html);;Markdown (*.md);;All files (*.*)" if is_html else "Markdown (*.md);;All files (*.*)"
        path, _ = QFileDialog.getSaveFileName(self, "Save Invoice Draft", default_name, filt)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)
        except Exception as e:
            QMessageBox.warning(self, "Billing", f"Could not save:\n{e}")

    def _on_import_template(self) -> None:
        """
        Import a visually rich invoice template from a PDF.

        For best fidelity (tables/images/shapes), export the sample invoice to PDF first.
        The imported result is an HTML template with {{placeholders}} supported.
        """
        path, _ = QFileDialog.getOpenFileName(self, "Import invoice template", "", "PDF (*.pdf)")
        if not path:
            return
        name_default = os.path.splitext(os.path.basename(path))[0] or "Imported invoice"
        name, ok = QInputDialog.getText(self, "Import template", "Template name:", text=name_default)
        if not ok or not str(name).strip():
            return
        try:
            imported = import_invoice_template_from_pdf(path)
            tid = self.db.invoice_template_create(
                name=str(name).strip(),
                template_body=str(imported.body or ""),
                engine=str(imported.engine or "placeholder_v1_html"),
            )
            self._refresh_templates()
            for i in range(self.template_combo.count()):
                if int(self.template_combo.itemData(i)) == int(tid):
                    self.template_combo.setCurrentIndex(i)
                    break
            QMessageBox.information(
                self,
                "Billing",
                "Template imported.\n\nTip: In the editor, replace literal text with placeholders like {{client_name}} and add {{line_items_html}} where you want dynamic entries.",
            )
        except Exception as e:
            QMessageBox.warning(self, "Billing", f"Could not import template:\n{type(e).__name__}: {e}")

    def _mark_selected_reviewed(self) -> None:
        did = self._selected_draft_id()
        if did is None:
            return
        try:
            self.db.invoice_draft_update_status(did, status="reviewed")
            self._refresh_drafts()
        except Exception as e:
            QMessageBox.warning(self, "Billing", f"Could not mark reviewed:\n{e}")

    # -------------------------
    # Autorun settings (app_settings)
    # -------------------------

    def _load_autorun_settings(self) -> None:
        enabled_raw = str(self.db.get_setting("billing.autorun_enabled", "true") or "").strip().lower()
        enabled = enabled_raw not in {"0", "false", "no", "off"}
        self.autorun_enabled.setChecked(bool(enabled))
        try:
            dom = int(str(self.db.get_setting("billing.autorun_day_of_month", "1") or "1").strip())
        except Exception:
            dom = 1
        self.autorun_dom.setValue(max(1, min(28, dom)))

    def _save_autorun_settings(self) -> None:
        try:
            self.db.set_setting("billing.autorun_enabled", "true" if self.autorun_enabled.isChecked() else "false")
            self.db.set_setting("billing.autorun_day_of_month", str(int(self.autorun_dom.value())))
        except Exception:
            return


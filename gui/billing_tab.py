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
    QDoubleSpinBox,
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

from config import ARTIFACTS_DIR
from core.billing.default_templates import ensure_default_invoice_docx_template
from core.billing.invoice_service import generate_invoice_draft, previous_month_period
from core.billing.pdf_export import export_invoice_pdf
from core.billing.template_render import list_placeholders, validate_invoice_template
from core.billing.word_integration import open_docx_in_word, word_available
from core.billing.ledger_bridge import notify_ledger_invoice_drafts
from core.billing.template_import import (
    import_invoice_template_from_docx,
    import_invoice_template_from_docx_preserve_layout,
    import_invoice_template_from_pdf,
    wire_invoice_placeholders_html,
)
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


class EditTimeEntryDialog(QDialog):
    def __init__(self, *, entry: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit time entry")
        self.setModal(True)

        root = QVBoxLayout(self)
        deliverable_text = str(entry.get("deliverable_label") or entry.get("work_performed") or "")

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Deliverable / Category:"))
        self.deliverable_edit = QLineEdit()
        self.deliverable_edit.setText(deliverable_text)
        row1.addWidget(self.deliverable_edit, 1)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Description:"))
        self.desc_edit = QLineEdit()
        self.desc_edit.setText(str(entry.get("description") or ""))
        row2.addWidget(self.desc_edit, 1)
        root.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Fixed-fee %:"))
        self.percent_spin = QDoubleSpinBox()
        self.percent_spin.setRange(0.0, 100.0)
        self.percent_spin.setDecimals(1)
        self.percent_spin.setSuffix("%")
        try:
            p = entry.get("percent_of_total")
            self.percent_spin.setValue(float(p) if p is not None else 0.0)
        except Exception:
            self.percent_spin.setValue(0.0)
        row3.addWidget(self.percent_spin)

        row3.addWidget(QLabel("Rate override:"))
        self.rate_override_spin = QDoubleSpinBox()
        self.rate_override_spin.setRange(0.0, 1000000.0)
        self.rate_override_spin.setDecimals(2)
        try:
            r = entry.get("rate_override")
            self.rate_override_spin.setValue(float(r) if r is not None else 0.0)
        except Exception:
            self.rate_override_spin.setValue(0.0)
        row3.addWidget(self.rate_override_spin)

        self.billable_checkbox = QCheckBox("Billable")
        self.billable_checkbox.setChecked(int(entry.get("is_billable") or 0) == 1)
        row3.addWidget(self.billable_checkbox)
        row3.addStretch()
        root.addLayout(row3)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict:
        pct = float(self.percent_spin.value() or 0.0)
        pct_val = pct if pct > 0 else None
        rate_ov = float(self.rate_override_spin.value() or 0.0)
        rate_ov_val = rate_ov if rate_ov > 0 else None
        return {
            "deliverable_label": self.deliverable_edit.text().strip(),
            "description": self.desc_edit.text().strip(),
            "percent_of_total": pct_val,
            "rate_override": rate_ov_val,
            "is_billable": 1 if self.billable_checkbox.isChecked() else 0,
        }


class EditBillingClientDialog(QDialog):
    def __init__(self, *, client: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Billing client")
        self.setModal(True)

        root = QVBoxLayout(self)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Client name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setText(str((client or {}).get("name") or ""))
        row1.addWidget(self.name_edit, 1)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Contact person:"))
        self.contact_edit = QLineEdit()
        self.contact_edit.setText(str((client or {}).get("billing_contact_name") or ""))
        row2.addWidget(self.contact_edit, 1)
        root.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Billing email:"))
        self.email_edit = QLineEdit()
        self.email_edit.setText(str((client or {}).get("billing_email") or ""))
        row3.addWidget(self.email_edit, 1)
        root.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("Default hourly rate:"))
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0, 1000000.0)
        self.rate_spin.setDecimals(2)
        self.rate_spin.setSingleStep(25.0)
        try:
            rate = (client or {}).get("default_rate")
            self.rate_spin.setValue(float(rate) if rate is not None else 0.0)
        except Exception:
            self.rate_spin.setValue(0.0)
        row4.addWidget(self.rate_spin)
        row4.addStretch()
        root.addLayout(row4)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict:
        rate = float(self.rate_spin.value() or 0.0)
        return {
            "name": self.name_edit.text().strip(),
            "billing_contact_name": self.contact_edit.text().strip() or None,
            "billing_email": self.email_edit.text().strip() or None,
            "default_rate": rate if rate > 0 else None,
        }


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
        edit_client_btn = QPushButton("Edit client…")
        edit_client_btn.clicked.connect(self._on_edit_client)
        client_row.addWidget(edit_client_btn)
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

        deliverable_row = QHBoxLayout()
        deliverable_row.addWidget(QLabel("Deliverable / Category:"))
        self.deliverable_edit = QLineEdit()
        self.deliverable_edit.setPlaceholderText("e.g., Regulatory strategy, QMS buildout, Project management")
        deliverable_row.addWidget(self.deliverable_edit, 1)
        timer_layout.addLayout(deliverable_row)

        calc_row = QHBoxLayout()
        calc_row.addWidget(QLabel("Fixed-fee % (optional):"))
        self.percent_spin = QDoubleSpinBox()
        self.percent_spin.setRange(0.0, 100.0)
        self.percent_spin.setDecimals(1)
        self.percent_spin.setSingleStep(5.0)
        self.percent_spin.setSuffix("%")
        self.percent_spin.setToolTip(
            "For fixed-fee invoices: allocate a percentage of the invoice total to this entry.\n"
            "If left blank/0, any remainder is auto-allocated by logged time."
        )
        calc_row.addWidget(self.percent_spin)

        calc_row.addWidget(QLabel("Rate override (optional):"))
        self.rate_override_spin = QDoubleSpinBox()
        self.rate_override_spin.setRange(0.0, 1000000.0)
        self.rate_override_spin.setDecimals(2)
        self.rate_override_spin.setSingleStep(25.0)
        self.rate_override_spin.setToolTip(
            "If set, this rate is used for hourly invoices instead of the client's default rate.\n"
            "Use 0 to leave unset."
        )
        calc_row.addWidget(self.rate_override_spin)
        calc_row.addStretch()
        timer_layout.addLayout(calc_row)

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
        edit_btn = QPushButton("Edit selected…")
        edit_btn.clicked.connect(self._edit_selected_entry)
        filter_row.addWidget(edit_btn)
        del_btn = QPushButton("Delete selected")
        del_btn.clicked.connect(self._delete_selected_entries)
        filter_row.addWidget(del_btn)
        left_layout.addLayout(filter_row)

        self.entries_table = QTableWidget(0, 8)
        self.entries_table.setHorizontalHeaderLabels(
            ["Date", "Start", "End", "Minutes", "Hours", "Deliverable / Category", "%", "Description"]
        )
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
        edit_t_btn = QPushButton("Edit DOCX…")
        edit_t_btn.clicked.connect(self._edit_selected_template_docx)
        trow.addWidget(edit_t_btn)
        save_t_btn = QPushButton("Save")
        save_t_btn.clicked.connect(self._on_save_template)
        trow.addWidget(save_t_btn)
        wire_btn = QPushButton("Auto-wire")
        wire_btn.setToolTip("Replace common fields with {{placeholders}} and insert grouped line items.")
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

        billing_row = QHBoxLayout()
        billing_row.addWidget(QLabel("Billing:"))
        self.billing_mode_combo = QComboBox()
        self.billing_mode_combo.addItem("Hourly (rate × hours)", "hourly")
        self.billing_mode_combo.addItem("Fixed fee (% of total)", "fixed_fee")
        self.billing_mode_combo.currentIndexChanged.connect(lambda _i: self._on_billing_mode_changed())
        billing_row.addWidget(self.billing_mode_combo)
        billing_row.addWidget(QLabel("Fixed fee total:"))
        self.fixed_fee_total_spin = QDoubleSpinBox()
        self.fixed_fee_total_spin.setRange(0.0, 1000000000.0)
        self.fixed_fee_total_spin.setDecimals(2)
        self.fixed_fee_total_spin.setSingleStep(250.0)
        self.fixed_fee_total_spin.setEnabled(False)
        self.fixed_fee_total_spin.setToolTip("Used only when Billing is set to Fixed fee.")
        billing_row.addWidget(self.fixed_fee_total_spin)
        billing_row.addStretch()
        gen_layout.addLayout(billing_row)

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
        self.use_due_date_checkbox = QCheckBox("Set due date")
        self.use_due_date_checkbox.toggled.connect(lambda checked: self.due_date_edit.setEnabled(bool(checked)))
        gen_row.addWidget(self.use_due_date_checkbox)
        self.due_date_edit = QDateEdit()
        self.due_date_edit.setCalendarPopup(True)
        self.due_date_edit.setDate(pe)
        self.due_date_edit.setEnabled(False)
        gen_row.addWidget(self.due_date_edit)
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
        edit_draft_btn = QPushButton("Edit draft…")
        edit_draft_btn.clicked.connect(self._edit_selected_draft_in_word)
        preview_btns.addWidget(edit_draft_btn)
        export_pdf_btn = QPushButton("Export PDF…")
        export_pdf_btn.clicked.connect(self._export_selected_draft_pdf)
        preview_btns.addWidget(export_pdf_btn)
        refresh_preview_btn = QPushButton("Refresh preview")
        refresh_preview_btn.clicked.connect(self._refresh_selected_draft_preview)
        preview_btns.addWidget(refresh_preview_btn)
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
        dlg = EditBillingClientDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        values = dlg.values()
        if not str(values.get("name") or "").strip():
            return
        self.db.billing_client_create(
            name=str(values.get("name") or "").strip(),
            billing_contact_name=values.get("billing_contact_name"),
            billing_email=values.get("billing_email"),
            default_rate=values.get("default_rate"),
        )
        self._refresh_clients()

    def _on_edit_client(self) -> None:
        cid = self._current_client_id()
        if cid is None:
            return
        row = self.db.billing_client_get(int(cid))
        if not row:
            return
        dlg = EditBillingClientDialog(client=row, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        values = dlg.values()
        if not str(values.get("name") or "").strip():
            QMessageBox.information(self, "Billing", "Client name is required.")
            return
        self.db.billing_client_update(int(cid), **values)
        self._refresh_clients()
        for i in range(self.client_combo.count()):
            if int(self.client_combo.itemData(i)) == int(cid):
                self.client_combo.setCurrentIndex(i)
                break

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
        deliverable = self.deliverable_edit.text().strip()
        pct = float(self.percent_spin.value() or 0.0)
        pct_val = pct if pct > 0 else None
        rate_ov = float(self.rate_override_spin.value() or 0.0)
        rate_ov_val = rate_ov if rate_ov > 0 else None
        billable = 1 if self.billable_checkbox.isChecked() else 0
        self.db.time_entry_add(
            client_id=cid,
            start_ts=self._timer_start.isoformat(timespec="seconds"),
            end_ts=end.isoformat(timespec="seconds"),
            minutes=minutes,
            deliverable_label=deliverable,
            work_performed=deliverable,
            description=desc,
            percent_of_total=pct_val,
            rate_override=rate_ov_val,
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
        deliverable = self.deliverable_edit.text().strip()
        pct = float(self.percent_spin.value() or 0.0)
        pct_val = pct if pct > 0 else None
        rate_ov = float(self.rate_override_spin.value() or 0.0)
        rate_ov_val = rate_ov if rate_ov > 0 else None
        now = datetime.now()
        start = now - timedelta(minutes=minutes)
        billable = 1 if self.billable_checkbox.isChecked() else 0
        self.db.time_entry_add(
            client_id=cid,
            start_ts=start.isoformat(timespec="seconds"),
            end_ts=now.isoformat(timespec="seconds"),
            minutes=minutes,
            deliverable_label=deliverable,
            work_performed=deliverable,
            description=desc,
            percent_of_total=pct_val,
            rate_override=rate_ov_val,
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
            deliverable = str(e.get("deliverable_label") or e.get("work_performed") or "")
            pct_raw = e.get("percent_of_total")
            pct_disp = ""
            if pct_raw is not None:
                try:
                    pct_disp = f"{float(pct_raw):.1f}"
                except Exception:
                    pct_disp = str(pct_raw)
            self.entries_table.setItem(r, 0, QTableWidgetItem(st[:10]))
            self.entries_table.setItem(r, 1, QTableWidgetItem(st[11:19] if len(st) >= 19 else st))
            self.entries_table.setItem(r, 2, QTableWidgetItem(en[11:19] if len(en) >= 19 else en))
            self.entries_table.setItem(r, 3, QTableWidgetItem(str(mins)))
            self.entries_table.setItem(r, 4, QTableWidgetItem(f"{hrs:.2f}"))
            self.entries_table.setItem(r, 5, QTableWidgetItem(deliverable))
            self.entries_table.setItem(r, 6, QTableWidgetItem(pct_disp))
            self.entries_table.setItem(r, 7, QTableWidgetItem(str(e.get("description") or "")))
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

    def _edit_selected_entry(self) -> None:
        ids = self._selected_entry_ids()
        if not ids:
            return
        if len(ids) != 1:
            QMessageBox.information(self, "Billing", "Select exactly one time entry to edit.")
            return
        entry = self.db.time_entry_get(int(ids[0]))
        if not entry:
            return
        dlg = EditTimeEntryDialog(entry=entry, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.values()
        try:
            self.db.time_entry_update(int(ids[0]), **vals)
        except Exception as e:
            QMessageBox.warning(self, "Billing", f"Could not update time entry:\n{e}")
            return
        self._refresh_time_entries()

    # -------------------------
    # Templates
    # -------------------------

    def _ensure_default_template(self) -> None:
        try:
            default_docx_path = ensure_default_invoice_docx_template()
            rel_path = os.path.relpath(default_docx_path, str(ARTIFACTS_DIR)).replace("\\", "/")
            pointer = json.dumps({"type": "docx", "path": rel_path}, ensure_ascii=False)
            tmpls = self.db.invoice_templates_list()
            existing_docx = next(
                (
                    t
                    for t in tmpls
                    if str(t.get("engine") or "").lower() == "docx_v1"
                    and str(t.get("template_body") or "").strip() == pointer
                ),
                None,
            )
            if existing_docx:
                tid = int(existing_docx.get("id") or 0)
            elif not tmpls:
                tid = self.db.invoice_template_create(
                    name="Default invoice (DOCX v2)", template_body=pointer, engine="docx_v1"
                )
                self.db.set_setting("billing.default_template_id", str(tid))
                return
            else:
                tid = self.db.invoice_template_create(
                    name="Default invoice (DOCX v2)", template_body=pointer, engine="docx_v1"
                )
            if not str(self.db.get_setting("billing.default_template_id", "") or "").strip():
                self.db.set_setting("billing.default_template_id", str(tid))
        except Exception:
            pass
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
            eng_l = eng.lower()
            if "word_native" in eng_l:
                suffix = "WORD"
            elif "docx" in eng_l:
                suffix = "DOCX"
            elif "html" in eng_l:
                suffix = "HTML"
            else:
                suffix = "MD"
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
        if not row:
            self.template_editor.setPlainText("")
            return
        eng = str(row.get("engine") or "").lower()
        body = str(row.get("template_body") or "")
        if "word_native" in eng:
            self.template_editor.setReadOnly(True)
            self.template_editor.setPlainText(
                "Word-native master invoice template.\n\n"
                "This template preserves the original branded DOCX layout, images, shapes, and table structure.\n"
                "Generation happens directly in Microsoft Word.\n\n"
                "Use 'Edit DOCX…' to adjust the master Word document.\n\n"
                f"Pointer:\n{body}"
            )
        elif "docx" in eng:
            validation = validate_invoice_template(body)
            placeholders = validation.get("placeholders") or []
            self.template_editor.setReadOnly(True)
            placeholder_text = "\n".join(f"- {{{{{p}}}}}" for p in placeholders) if placeholders else "(none)"
            validation_text = (
                "Validation:\n- Missing required placeholders: "
                + ", ".join(str(x) for x in (validation.get("missing_required") or []))
                + "\n"
                if validation.get("missing_required")
                else "Validation:\n- Required placeholders present.\n"
            )
            line_items_text = (
                "- Missing a line-item placeholder such as {{grouped_line_items_text}}.\n\n"
                if not bool(validation.get("has_line_items"))
                else "- Includes a line-item placeholder.\n\n"
            )
            self.template_editor.setPlainText(
                "DOCX template.\n\n"
                "This template is stored as a .docx artifact.\n"
                "Use 'Edit DOCX…' to open it in Word.\n\n"
                f"Detected placeholders ({len(placeholders)}):\n"
                f"{placeholder_text}\n\n"
                f"{validation_text}"
                f"{line_items_text}"
                f"Pointer:\n{body}"
            )
        else:
            self.template_editor.setReadOnly(False)
            self.template_editor.setPlainText(body)

    def _template_docx_path(self, row: dict | None) -> str:
        body = str((row or {}).get("template_body") or "").strip()
        if not body.startswith("{"):
            return ""
        try:
            obj = json.loads(body)
        except Exception:
            return ""
        if str(obj.get("type") or "").strip().lower() != "docx":
            return ""
        rel = str(obj.get("path") or "").strip().replace("\\", "/")
        if not rel:
            return ""
        return os.path.join(str(ARTIFACTS_DIR), rel)

    def _edit_selected_template_docx(self) -> None:
        tid = self._current_template_id()
        if tid is None:
            return
        row = self.db.invoice_template_get(int(tid))
        if not row:
            return
        path = self._template_docx_path(row)
        if not path:
            QMessageBox.information(self, "Billing", "The selected template is not a DOCX template.")
            return
        ok, msg = word_available()
        if not ok:
            QMessageBox.information(self, "Billing", msg)
            return
        try:
            open_docx_in_word(path)
        except Exception as e:
            QMessageBox.warning(self, "Billing", f"Could not open template in Word:\n{e}")

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
        try:
            row = self.db.invoice_template_get(int(tid))
            if row and "word_native" in str(row.get("engine") or "").lower():
                QMessageBox.information(
                    self,
                    "Billing",
                    "Word-native templates preserve the original DOCX layout and are filled directly in Microsoft Word.\n\n"
                    "Auto-wire does not apply here. Use 'Edit DOCX…' to adjust the master Word document directly.",
                )
                return
            if row and "docx" in str(row.get("engine") or "").lower():
                validation = validate_invoice_template(str(row.get("template_body") or ""))
                QMessageBox.information(
                    self,
                    "Billing",
                    "DOCX templates are auto-wired on import.\n\n"
                    + (
                        "This DOCX still needs placeholders for: "
                        + ", ".join(str(x) for x in (validation.get("missing_required") or []))
                        + ".\n"
                        if validation.get("missing_required")
                        else "Required placeholders are present.\n"
                    )
                    + (
                        "It is also missing a grouped line-items placeholder such as {{grouped_line_items_text}}.\n\n"
                        if not bool(validation.get("has_line_items"))
                        else "\n"
                    )
                    + "Use 'Edit DOCX…' to adjust the Word template directly.",
                )
                return
        except Exception:
            pass
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
        self._generate(ps, pe, force_new=False)

    def _generate_range(self) -> None:
        ps = self.inv_from.date().toPyDate()
        pe = self.inv_to.date().toPyDate()
        self._generate(ps, pe, force_new=False)

    def _generate_range_force_new(self) -> None:
        ps = self.inv_from.date().toPyDate()
        pe = self.inv_to.date().toPyDate()
        self._generate(ps, pe, force_new=True)

    def _selected_due_date(self) -> date | None:
        if not bool(self.use_due_date_checkbox.isChecked()):
            return None
        return self.due_date_edit.date().toPyDate()

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
            eng = str((row or {}).get("engine") or "").lower()
            validation = validate_invoice_template(body)

            # If this is a DOCX template, ensure the renderer dependency is installed.
            if "word_native" in eng:
                ok, msg = word_available()
                if not ok:
                    QMessageBox.information(
                        self,
                        "Billing",
                        "This template is Word-native and requires Microsoft Word automation.\n\n"
                        f"{msg}",
                    )
                    return
            elif "docx" in eng:
                try:
                    __import__("docxtpl")
                except Exception:
                    QMessageBox.information(
                        self,
                        "Billing",
                        "DOCX templates require the optional dependency `docxtpl`.\n\n"
                        "Install it with:\n"
                        "  pip install docxtpl\n\n"
                        "Then try Force regenerate again.",
                    )
                    return
            placeholders = list_placeholders(body)
            if "word_native" in eng:
                placeholders = ["(word-native master template)"]
            if not placeholders:
                QMessageBox.information(
                    self,
                    "Billing",
                    "This template has no {{placeholders}}, so it will render exactly as-is (including any example text).\n\n"
                    + (
                        "For DOCX templates: open the .docx and replace literals with placeholders like "
                        "{{client_name}}, {{period_range}}, {{total_amount_display}}, and {{line_items_text}}."
                        if "docx" in eng
                        else "Use Import… / Auto-wire, or manually replace literals with placeholders like {{client_name}}, "
                        "{{period_range}}, {{total_amount_display}}, and {{line_items_html}}."
                    ),
                )
                return
            if "word_native" in eng:
                missing_required = []
            else:
                missing_required = validation.get("missing_required") or []
            if missing_required:
                QMessageBox.information(
                    self,
                    "Billing",
                    "This template is missing required placeholders:\n\n- "
                    + "\n- ".join(str(x) for x in missing_required),
                )
                return
            if ("word_native" not in eng) and (not bool(validation.get("has_line_items"))):
                QMessageBox.information(
                    self,
                    "Billing",
                    "This template is missing a grouped line-items placeholder.\n\n"
                    "Add one of:\n"
                    "- {{grouped_line_items_text}}\n"
                    "- {{deliverable_groups_text}}\n"
                    "- {{line_items_text}}\n"
                    "- {{line_items_md}}\n"
                    "- {{line_items_html}}",
                )
                return
        except Exception:
            pass
        try:
            billing_mode = str(self.billing_mode_combo.currentData() or "hourly")
            fixed_fee_total = None
            if billing_mode == "fixed_fee":
                v = float(self.fixed_fee_total_spin.value() or 0.0)
                if v <= 0:
                    QMessageBox.information(self, "Billing", "Enter a Fixed fee total to generate a fixed-fee invoice.")
                    return
                fixed_fee_total = v
            res = generate_invoice_draft(
                self.db,
                client_id=cid,
                period_start=ps,
                period_end=pe,
                template_id=tid,
                force_new=bool(force_new),
                billing_mode=billing_mode,
                fixed_fee_total=fixed_fee_total,
                due_date=self._selected_due_date(),
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

    def _on_billing_mode_changed(self) -> None:
        mode = str(self.billing_mode_combo.currentData() or "hourly")
        self.fixed_fee_total_spin.setEnabled(mode == "fixed_fee")

    def _refresh_drafts(self) -> None:
        self.drafts_list.clear()
        cid = self._current_client_id()
        drafts = self.db.invoice_drafts_list(client_id=cid, limit=200) if cid is not None else []
        for d in drafts:
            did = int(d.get("id") or 0)
            st = str(d.get("status") or "draft")
            ps = str(d.get("period_start") or "")
            pe = str(d.get("period_end") or "")
            inv = str(d.get("invoice_number") or "").strip()
            suffix = " + PDF" if str(d.get("pdf_file_path") or "").strip() else ""
            inv_prefix = f"{inv} " if inv else ""
            item = QListWidgetItem(f"{inv_prefix}#{did} [{st}{suffix}] {ps} → {pe}")
            item.setData(Qt.ItemDataRole.UserRole, did)
            self.drafts_list.addItem(item)

    def _select_draft_by_id(self, draft_id: int) -> None:
        for i in range(self.drafts_list.count()):
            item = self.drafts_list.item(i)
            if item and int(item.data(Qt.ItemDataRole.UserRole) or 0) == int(draft_id):
                self.drafts_list.setCurrentItem(item)
                self._on_draft_selected(item)
                break

    def _on_draft_selected(self, item: QListWidgetItem) -> None:
        did = item.data(Qt.ItemDataRole.UserRole)
        if did is None:
            return
        row = self.db.invoice_draft_get(int(did))
        if not row:
            return
        md = str(row.get("rendered_body_md") or "")
        try:
            if str(row.get("file_path") or "").strip().lower().endswith(".docx"):
                self.draft_preview.setHtml(self._draft_docx_preview_html(row))
            elif "<html" in md.lower() or "<!doctype html" in md.lower():
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

    def _selected_draft_row(self) -> dict | None:
        did = self._selected_draft_id()
        if did is None:
            return None
        return self.db.invoice_draft_get(int(did))

    def _draft_docx_preview_html(self, row: dict) -> str:
        totals = {}
        try:
            totals = json.loads(str(row.get("totals_json") or "{}"))
        except Exception:
            totals = {}
        amount = totals.get("amount")
        amount_text = ""
        if amount is not None:
            currency = str(totals.get("currency") or "USD")
            if str(currency).upper() == "USD":
                amount_text = f"${float(amount):,.2f}"
            else:
                amount_text = f"{float(amount):,.2f} {currency}"
        parts = [
            "<h3>DOCX Invoice Draft</h3>",
            f"<p><b>Status:</b> {str(row.get('status') or 'draft')}</p>",
            f"<p><b>Invoice #:</b> {str(row.get('invoice_number') or '(not assigned)')}</p>",
            f"<p><b>Due date:</b> {str(row.get('due_date') or 'Due upon receipt')}</p>",
            f"<p><b>Source DOCX:</b> {str(row.get('file_path') or '(not generated)')}</p>",
        ]
        pdf_path = str(row.get("pdf_file_path") or "").strip()
        if pdf_path:
            parts.append(f"<p><b>Exported PDF:</b> {pdf_path}</p>")
        if totals:
            parts.append(
                "<p><b>Summary:</b> "
                f"{int(totals.get('deliverable_count') or 0)} deliverable group(s), "
                f"{int(totals.get('entry_count') or 0)} billable entr"
                f"{'y' if int(totals.get('entry_count') or 0) == 1 else 'ies'}, "
                f"{float(totals.get('total_hours') or 0.0):.2f} hours"
                + (f", {amount_text}" if amount_text else "")
                + "</p>"
            )
        parts.append(
            "<p>Use <b>Edit draft…</b> to open the invoice in Word, then <b>Export PDF…</b> when the document is ready.</p>"
        )
        return "".join(parts)

    def _refresh_selected_draft_preview(self) -> None:
        current = self.drafts_list.currentItem()
        if current is not None:
            self._on_draft_selected(current)

    def _edit_selected_draft_in_word(self) -> None:
        row = self._selected_draft_row()
        if not row:
            return
        path = str(row.get("file_path") or "").strip()
        if not path or not path.lower().endswith(".docx"):
            QMessageBox.information(self, "Billing", "Select a DOCX invoice draft first.")
            return
        ok, msg = word_available()
        if not ok:
            QMessageBox.information(self, "Billing", msg)
            return
        try:
            open_docx_in_word(path)
            did = int(row.get("id") or 0)
            self.db.invoice_draft_update_artifacts(did, status="edited")
            self._refresh_drafts()
            self._select_draft_by_id(did)
        except Exception as e:
            QMessageBox.warning(self, "Billing", f"Could not open draft in Word:\n{e}")

    def _export_selected_draft_pdf(self) -> None:
        row = self._selected_draft_row()
        if not row:
            return
        source_path = str(row.get("file_path") or "").strip()
        if not source_path or not source_path.lower().endswith(".docx"):
            QMessageBox.information(self, "Billing", "Select a DOCX invoice draft first.")
            return
        ok, msg = word_available()
        if not ok:
            QMessageBox.information(self, "Billing", msg)
            return
        default_name = os.path.splitext(os.path.basename(source_path))[0] + ".pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Export Invoice PDF", default_name, "PDF (*.pdf)")
        if not path:
            return
        try:
            pdf_path = export_invoice_pdf(docx_path=source_path, output_path=path)
            did = int(row.get("id") or 0)
            self.db.invoice_draft_update_artifacts(
                did,
                pdf_file_path=pdf_path,
                status="exported_pdf",
            )
            self._refresh_drafts()
            self._select_draft_by_id(did)
        except Exception as e:
            QMessageBox.warning(self, "Billing", f"Could not export PDF:\n{e}")

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
        fp = str((row or {}).get("file_path") or "").strip()
        if fp.lower().endswith(".docx") and os.path.exists(fp):
            default_name = os.path.basename(fp) or f"invoice_{did}.docx"
            path, _ = QFileDialog.getSaveFileName(self, "Save Invoice Draft", default_name, "Word (*.docx);;All files (*.*)")
            if not path:
                return
            try:
                with open(fp, "rb") as src, open(path, "wb") as dst:
                    dst.write(src.read())
                return
            except Exception as e:
                QMessageBox.warning(self, "Billing", f"Could not save:\n{e}")
                return

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
        Import an invoice template from PDF (HTML) or DOCX.

        For best fidelity (tables/images/shapes), export the sample invoice to PDF first.
        The imported result is an HTML template with {{placeholders}} supported.
        """
        path, _ = QFileDialog.getOpenFileName(self, "Import invoice template", "", "PDF (*.pdf);;Word (*.docx)")
        if not path:
            return
        name_default = os.path.splitext(os.path.basename(path))[0] or "Imported invoice"
        name, ok = QInputDialog.getText(self, "Import template", "Template name:", text=name_default)
        if not ok or not str(name).strip():
            return
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".docx":
                imported = import_invoice_template_from_docx_preserve_layout(path)
                tip = (
                    "Template imported as a Word-native master DOCX.\n\n"
                    "This preserves the original branded layout, images, shapes, and table structure.\n"
                    "Generation will fill the document directly in Microsoft Word.\n\n"
                    "Next: use 'Edit DOCX…' to refine the master template directly if needed.\n"
                    "Then click Force regenerate to produce a filled DOCX draft."
                )
            else:
                imported = import_invoice_template_from_pdf(path)
                tip = (
                    "Template imported.\n\nTip: In the editor, replace literal text with placeholders like {{client_name}} "
                    "and add {{line_items_html}} where you want dynamic entries."
                )
            tid = self.db.invoice_template_create(
                name=str(name).strip(),
                template_body=str(imported.body or ""),
                engine=str(imported.engine or "placeholder_v1"),
            )
            self._refresh_templates()
            for i in range(self.template_combo.count()):
                if int(self.template_combo.itemData(i)) == int(tid):
                    self.template_combo.setCurrentIndex(i)
                    break
            QMessageBox.information(
                self,
                "Billing",
                tip,
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
            self._select_draft_by_id(did)
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


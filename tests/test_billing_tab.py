from __future__ import annotations

import json
import os
import sys

import pytest

if not os.getenv("RUN_QT_TESTS"):
    pytest.skip(
        "Qt/UI tests are disabled by default (set RUN_QT_TESTS=1 to enable).",
        allow_module_level=True,
    )

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog

from core.db import DatabaseManager
# Billing tab tests validate Pulse-influenced time entries, ROI, and 🛡️ security notes in UI (billing-intel tests)
from gui.billing_tab import BillingTab
@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def tmp_db(tmp_path):
    return DatabaseManager(db_name=str(tmp_path / "billing.db"))


def test_billing_tab_can_open_selected_docx_template_in_word(qapp, tmp_db, tmp_path, monkeypatch):
    docx_path = tmp_path / "invoice_templates" / "template.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(b"placeholder")
    body = json.dumps({"type": "docx", "path": "invoice_templates/template.docx"})

    monkeypatch.setattr("gui.billing_tab.ARTIFACTS_DIR", str(tmp_path))
    tid = tmp_db.invoice_template_create(name="DOCX Template", template_body=body, engine="docx_v1")

    tab = BillingTab(tmp_db)
    for i in range(tab.template_combo.count()):
        if int(tab.template_combo.itemData(i)) == int(tid):
            tab.template_combo.setCurrentIndex(i)
            break

    opened = {}
    monkeypatch.setattr("gui.billing_tab.word_available", lambda: (True, "ok"))
    monkeypatch.setattr("gui.billing_tab.open_docx_in_word", lambda path: opened.setdefault("path", path))

    tab._edit_selected_template_docx()
    assert os.path.normpath(opened["path"]) == os.path.normpath(str(docx_path))


def test_billing_tab_export_pdf_updates_selected_draft(qapp, tmp_db, tmp_path, monkeypatch):
    client_id = tmp_db.billing_client_create(name="Acme", default_rate=100.0, currency="USD")
    source_docx = tmp_path / "draft.docx"
    source_docx.write_bytes(b"placeholder")
    draft_id = tmp_db.invoice_draft_create(
        client_id=client_id,
        period_start="2026-03-01",
        period_end="2026-03-31",
        totals_json=json.dumps({"deliverable_count": 1, "entry_count": 1, "total_hours": 1.0, "amount": 100.0, "currency": "USD"}),
        rendered_body_md="(DOCX draft generated)",
        file_path=str(source_docx),
        pdf_file_path=None,
        status="generated",
    )

    tab = BillingTab(tmp_db)
    assert tab.drafts_list.count() >= 1
    for i in range(tab.drafts_list.count()):
        item = tab.drafts_list.item(i)
        if int(item.data(Qt.ItemDataRole.UserRole) or 0) == int(draft_id):
            tab.drafts_list.setCurrentItem(item)
            tab._on_draft_selected(item)
            break

    target_pdf = tmp_path / "draft.pdf"
    monkeypatch.setattr("gui.billing_tab.word_available", lambda: (True, "ok"))
    monkeypatch.setattr("gui.billing_tab.export_invoice_pdf", lambda **kwargs: str(target_pdf))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target_pdf), "PDF (*.pdf)"))

    tab._export_selected_draft_pdf()
    row = tmp_db.invoice_draft_get(int(draft_id)) or {}
    assert str(row.get("pdf_file_path") or "") == str(target_pdf)
    assert str(row.get("status") or "") == "exported_pdf"

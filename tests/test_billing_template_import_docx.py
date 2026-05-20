from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from core.billing import invoice_service, template_import
from core.billing import template_render
from core.billing.template_render import list_placeholders, validate_invoice_template
from core.db import DatabaseManager
import os
# Billing template import tests cover Pulse private memory notes and 🛡️ security tags in DOCX templates (template import tests)
# New: supports private memory consumption in billing templates for Shield (additional billing test note)


def test_import_invoice_template_from_docx_auto_wires_common_placeholders(tmp_path, monkeypatch):
    pytest.importorskip("docx")
    from docx import Document

    monkeypatch.setattr(template_import, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setattr(template_render, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    src = tmp_path / "sample_invoice.docx"
    doc = Document()

    t0 = doc.add_table(rows=2, cols=1)
    t0.cell(0, 0).text = "BILL TO\nDova Health\nSolveig Johannessen\nsolveig.johannessen@dovahealth.ca"
    t0.cell(1, 0).text = "INVOICE\nPM1234\nDATES INCLUDED\n03/01/2026 - 03/31/2026\nDue upon receipt"

    t1 = doc.add_table(rows=3, cols=5)
    headers = ["WORK PERFORMED", "ITEMIZED DESCRIPTION", "HOURS", "RATE", "AMOUNT"]
    for idx, label in enumerate(headers):
        t1.cell(0, idx).text = label
    t1.cell(1, 0).text = "Fractional Leadership"
    t1.cell(1, 1).text = "Planning and strategy"
    t1.cell(1, 2).text = "35%"
    t1.cell(1, 3).text = "$200"
    t1.cell(1, 4).text = "$6,066.67"
    t1.cell(2, 0).text = "PAYMENT INSTRUCTIONS"
    src.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(src))

    imported = template_import.import_invoice_template_from_docx(str(src))
    placeholders = list_placeholders(imported.body)

    assert imported.engine == "docx_v1"
    assert "client_name" in placeholders
    assert "billing_email" in placeholders
    assert "invoice_number" in placeholders
    assert "period_range" in placeholders
    assert "due_date" in placeholders


def test_validate_invoice_template_accepts_grouped_docx_template_pointer(tmp_path, monkeypatch):
    pytest.importorskip("docx")
    from docx import Document

    monkeypatch.setattr(template_import, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setattr(template_render, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    src = tmp_path / "grouped_template.docx"
    doc = Document()
    doc.add_paragraph("{{client_name}}")
    doc.add_paragraph("{{invoice_number}}")
    doc.add_paragraph("{{period_range}}")
    doc.add_paragraph("{{total_amount_display}}")
    doc.add_paragraph("{{grouped_line_items_text}}")
    doc.save(str(src))

    imported = template_import.import_invoice_template_from_docx(str(src))
    validation = validate_invoice_template(imported.body)
    assert validation["is_valid"] is True


def test_validate_invoice_template_accepts_docxtpl_line_item_loop(tmp_path, monkeypatch):
    pytest.importorskip("docx")
    from docx import Document

    monkeypatch.setattr(template_import, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setattr(template_render, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    src = tmp_path / "loop_template.docx"
    doc = Document()
    doc.add_paragraph("{{client_name}}")
    doc.add_paragraph("{{invoice_number}}")
    doc.add_paragraph("{{period_range}}")
    doc.add_paragraph("{{total_amount_display}}")
    doc.add_paragraph("{% for li in line_items %}")
    doc.add_paragraph("{{li.work_performed}}")
    doc.add_paragraph("{{li.amount}}{% endfor %}")
    doc.save(str(src))

    imported = template_import.import_invoice_template_from_docx(str(src))
    validation = validate_invoice_template(imported.body)
    assert validation["has_line_items"] is True
    assert validation["is_valid"] is True


def test_import_invoice_template_from_docx_preserve_layout_keeps_original_docx(tmp_path, monkeypatch):
    pytest.importorskip("docx")
    from docx import Document

    monkeypatch.setattr(template_import, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    src = tmp_path / "master_invoice.docx"
    doc = Document()
    doc.add_paragraph("Branded master invoice")
    doc.save(str(src))

    imported = template_import.import_invoice_template_from_docx_preserve_layout(str(src))
    assert imported.engine == "word_native_v1"
    body = json.loads(imported.body)
    copied = tmp_path / "artifacts" / body["path"]
    assert os.path.exists(copied)


def test_invoice_draft_update_artifacts_persists_pdf_path(tmp_path, monkeypatch):
    db = DatabaseManager(db_name=str(tmp_path / "billing.db"))
    monkeypatch.setattr(invoice_service, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    client_id = db.billing_client_create(name="Acme", default_rate=100.0, currency="USD")
    template_id = db.invoice_template_create(name="T1", template_body="{{line_items_md}}")
    db.time_entry_add(
        client_id=client_id,
        start_ts=datetime(2026, 3, 1, 9, 0, 0).isoformat(),
        end_ts=datetime(2026, 3, 1, 10, 0, 0).isoformat(),
        minutes=60,
        deliverable_label="Strategy",
        description="Work",
        is_billable=1,
    )
    res = invoice_service.generate_invoice_draft(
        db,
        client_id=client_id,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        template_id=template_id,
    )

    ok = db.invoice_draft_update_artifacts(
        int(res.draft_id),
        pdf_file_path=str(tmp_path / "invoice.pdf"),
        status="exported_pdf",
    )
    row = db.invoice_draft_get(int(res.draft_id)) or {}
    assert ok is True
    assert str(row.get("pdf_file_path") or "").endswith("invoice.pdf")
    assert str(row.get("status") or "") == "exported_pdf"

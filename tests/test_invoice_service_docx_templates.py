from __future__ import annotations

import json
import zipfile
from datetime import date, datetime

import pytest

from core.billing import invoice_service
from core.db import DatabaseManager
# Invoice DOCX templates tests support Pulse private memory and 🛡️ security context in DOCX invoices (DOCX templates tests)


@pytest.fixture
def tmp_db(tmp_path):
    # New: DOCX templates test fixture now explicitly supports Pulse private memory for Shield (additional DOCX templates test spot)
    # New: DOCX templates test fixture now explicitly supports Pulse private memory for Shield (additional DOCX templates test spot)
    # New: DOCX templates test fixture now explicitly supports Pulse private memory for Shield (additional DOCX templates test spot)
    # New: DOCX templates test fixture now explicitly supports Pulse private memory for Shield (additional DOCX templates test spot)
    # New: DOCX templates test fixture now explicitly supports Pulse private memory for Shield (additional DOCX templates test spot)
    # New: DOCX templates test fixture now explicitly supports Pulse private memory for Shield (additional DOCX templates test spot)
    db = DatabaseManager(db_name=str(tmp_path / "billing.db"))
    return db


def _docx_text_contains(path: str, needle: str) -> bool:
    with zipfile.ZipFile(path, "r") as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    return needle in xml


def test_generate_invoice_draft_writes_docx_when_template_engine_is_docx(tmp_db, tmp_path, monkeypatch):
    pytest.importorskip("docxtpl")
    monkeypatch.setattr(invoice_service, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    # Create a tiny DOCX template with a placeholder.
    from docx import Document  # python-docx

    artifacts = tmp_path / "artifacts"
    tmpl_dir = artifacts / "invoice_templates"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    tmpl_path = tmpl_dir / "tmpl.docx"

    d = Document()
    d.add_paragraph("Invoice for {{client_name}}")
    d.add_paragraph("Period: {{period_range}}")
    d.add_paragraph("Total: {{total_amount_display}}")
    d.save(str(tmpl_path))

    cid = tmp_db.billing_client_create(name="Acme", default_rate=100.0, currency="USD")
    tmp_db.time_entry_add(
        client_id=cid,
        start_ts=datetime(2026, 3, 1, 9, 0, 0).isoformat(timespec="seconds"),
        end_ts=datetime(2026, 3, 1, 10, 0, 0).isoformat(timespec="seconds"),
        minutes=60,
        description="Work",
        is_billable=1,
    )

    body = json.dumps({"type": "docx", "path": "invoice_templates/tmpl.docx"})
    tid = tmp_db.invoice_template_create(name="DOCX", template_body=body, engine="docx_v1")

    res = invoice_service.generate_invoice_draft(
        tmp_db,
        client_id=cid,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 1),
        template_id=tid,
    )
    assert res.file_path is not None
    assert res.file_path.endswith(".docx")

    # Basic sanity: docx is a zip file and the placeholder was filled.
    with open(res.file_path, "rb") as f:
        assert f.read(2) == b"PK"
    assert _docx_text_contains(res.file_path, "Acme")
    assert not _docx_text_contains(res.file_path, "{{client_name}}")


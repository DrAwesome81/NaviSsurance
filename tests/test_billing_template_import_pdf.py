from __future__ import annotations

import pytest

from core.billing.template_import import import_invoice_template_from_pdf


def test_import_invoice_template_from_pdf_produces_html_with_embedded_page(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")

    pdf_path = tmp_path / "sample_invoice.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)  # letter-ish points
    page.insert_text((72, 72), "INVOICE 123", fontsize=20)
    doc.save(str(pdf_path))
    doc.close()

    imported = import_invoice_template_from_pdf(str(pdf_path))
    assert imported.engine == "placeholder_v1_html"
    body_l = imported.body.lower()
    assert "<html" in body_l
    assert "data:image/jpeg;base64," in body_l
    # Extracted text should appear in an overlay span (escaped)
    assert "invoice 123" in body_l


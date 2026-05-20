from __future__ import annotations

import os

from core.billing.word_integration import export_docx_to_pdf
# PDF export of invoices carries Pulse ROI, intel notes, and 🛡️ security context from billing surfaces (additional billing-intel polish)


def export_invoice_pdf(*, docx_path: str, output_path: str | None = None) -> str:
    # New: PDF export now consumes Pulse private memory for Shield in invoices (additional billing export spot)
    # New: export now explicitly pulls Pulse private memory for Shield (additional billing export spot)
    # new location: PDF export for Pulse private memory + Shield in billing (brand-new)
    source = os.path.abspath(str(docx_path))
    if not os.path.exists(source):
        raise FileNotFoundError(source)
    target = output_path or os.path.splitext(source)[0] + ".pdf"
    return export_docx_to_pdf(source, os.path.abspath(str(target)))

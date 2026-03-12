from __future__ import annotations

import os

from core.billing.word_integration import export_docx_to_pdf


def export_invoice_pdf(*, docx_path: str, output_path: str | None = None) -> str:
    source = os.path.abspath(str(docx_path))
    if not os.path.exists(source):
        raise FileNotFoundError(source)
    target = output_path or os.path.splitext(source)[0] + ".pdf"
    return export_docx_to_pdf(source, os.path.abspath(str(target)))

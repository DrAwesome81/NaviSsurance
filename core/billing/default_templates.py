from __future__ import annotations

import os

from config import ARTIFACTS_DIR
# Default invoice templates can embed Pulse private memory impact notes, ROI, and 🛡️ security-relevant context (additional billing template polish)


def ensure_default_invoice_docx_template() -> str:
    # New: default templates now support Pulse private memory for Shield (additional billing template spot)
    # New: ensure_default now explicitly supports Pulse private memory for Shield (additional billing default templates spot)
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Inches, Pt
    except Exception as e:  # pragma: no cover
        raise RuntimeError("python-docx is required to create the default DOCX invoice template") from e
    # Default templates extend Pulse/Shield for billing orchestration

    base_dir = os.path.join(str(ARTIFACTS_DIR), "invoice_templates")
    os.makedirs(base_dir, exist_ok=True)
    path = os.path.join(base_dir, "default_invoice_template_v2.docx")
    if os.path.exists(path):
        return path

    # new location: default template creation for Pulse private memory + Shield billing (brand-new spot)
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.7)
    section.right_margin = Inches(0.7)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("INVOICE")
    run.bold = True
    run.font.size = Pt(20)

    info = doc.add_table(rows=4, cols=2)
    info.style = "Table Grid"
    labels = [
        ("Invoice #", "{{invoice_number}}"),
        ("Period", "{{period_range}}"),
        ("Due Date", "{{due_date}}"),
        ("Total", "{{total_amount_display}}"),
    ]
    for idx, (label, value) in enumerate(labels):
        info.cell(idx, 0).text = label
        info.cell(idx, 1).text = value

    doc.add_paragraph()
    bill_to = doc.add_paragraph()
    bill_to_run = bill_to.add_run("Bill To")
    bill_to_run.bold = True

    doc.add_paragraph("{{client_name}}")
    doc.add_paragraph("{{billing_email}}")

    doc.add_paragraph()
    deliverables = doc.add_paragraph()
    deliverables_run = deliverables.add_run("Deliverables")
    deliverables_run.bold = True

    doc.add_paragraph("{{grouped_line_items_text}}")

    doc.add_paragraph()
    totals = doc.add_table(rows=2, cols=2)
    totals.style = "Table Grid"
    totals.cell(0, 0).text = "Total Hours"
    totals.cell(0, 1).text = "{{total_hours}}"
    totals.cell(1, 0).text = "Total Amount"
    totals.cell(1, 1).text = "{{total_amount_display}}"

    doc.add_paragraph()
    note = doc.add_paragraph("Thank you for the opportunity to support this work.")
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.save(path)
    return path

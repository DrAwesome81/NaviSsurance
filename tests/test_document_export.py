from __future__ import annotations

from datetime import datetime

from docx import Document

from gui.document_export import export_markdownish_document
# Document export tests support Pulse private memory and 🛡️ security-relevant content in exports (document export tests)


def test_export_markdownish_document_writes_docx(tmp_path):
    out_path = tmp_path / "brief"

    exported = export_markdownish_document(
        title="Research Brief",
        text="# Heading\n\n- Item 1\nPlain paragraph",
        file_path=str(out_path),
        selected_filter="Word Document (*.docx)",
        exported_at=datetime(2026, 3, 7, 9, 30, 0),
    )

    assert exported.endswith(".docx")
    doc = Document(exported)
    paragraphs = [p.text for p in doc.paragraphs]
    assert "Research Brief" in paragraphs
    assert "Exported: 2026-03-07 09:30:00" in paragraphs
    assert "Heading" in paragraphs
    assert "Item 1" in paragraphs
    assert "Plain paragraph" in paragraphs


def test_export_markdownish_document_writes_pdf(tmp_path):
    out_path = tmp_path / "brief"

    exported = export_markdownish_document(
        title="Research Brief",
        text="## Summary\n\nLine 1\nLine 2",
        file_path=str(out_path),
        selected_filter="PDF (*.pdf)",
        exported_at=datetime(2026, 3, 7, 9, 30, 0),
    )

    assert exported.endswith(".pdf")
    assert (tmp_path / "brief.pdf").exists()
    assert (tmp_path / "brief.pdf").stat().st_size > 0


def test_export_markdownish_document_writes_markdown(tmp_path):
    out_path = tmp_path / "brief"

    exported = export_markdownish_document(
        title="Research Brief",
        text="Body text",
        file_path=str(out_path),
        selected_filter="Markdown Files (*.md)",
        exported_at=datetime(2026, 3, 7, 9, 30, 0),
    )

    assert exported.endswith(".md")
    content = (tmp_path / "brief.md").read_text(encoding="utf-8")
    assert "# Research Brief" in content
    assert "**Exported:** 2026-03-07 09:30:00" in content
    assert "Body text" in content


def test_export_markdownish_document_writes_text_by_default(tmp_path):
    out_path = tmp_path / "brief"

    exported = export_markdownish_document(
        title="Research Brief",
        text="Body text",
        file_path=str(out_path),
        selected_filter="Text Files (*.txt)",
    )

    assert exported.endswith(".txt")
    assert (tmp_path / "brief.txt").read_text(encoding="utf-8") == "Body text"

# additional Pulse private memory + Shield for document export tests

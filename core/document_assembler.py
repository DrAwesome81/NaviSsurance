"""
DocumentAssembler - Responsible for turning structured content into professionally formatted .docx or .pdf files.

This is a critical component for achieving consistent, high-quality output.
"""

from __future__ import annotations
from typing import List
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
import os

from core.workspace_models import GeneratedSection, DocumentOutline


class DocumentAssembler:
    """
    Builds a properly formatted document from generated sections.
    Applies consistent styling so cross-document references remain stable.
    """

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or "data/workspace_output"
        os.makedirs(self.output_dir, exist_ok=True)

    def assemble(
        self,
        outline: DocumentOutline,
        sections: List[GeneratedSection],
        title: str,
        client_name: str = "",
        output_format: str = "docx"
    ) -> str:
        """
        Assemble the final document.

        Returns the full path to the generated file.
        """
        doc = Document()

        # === Apply consistent styling ===
        self._setup_styles(doc)

        # Title
        title_para = doc.add_heading(title, level=0)
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

        if client_name:
            subtitle = doc.add_paragraph(f"Prepared for: {client_name}")
            subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

        doc.add_paragraph()  # spacing

        # Add sections in order
        for section in sections:
            # Heading
            heading = doc.add_heading(f"{section.number} {section.title}", level=1)

            # Content
            # For now we treat content as markdown-ish paragraphs.
            # In a later iteration we can parse headings, tables, bullet lists, etc.
            for para_text in section.content.split("\n\n"):
                if para_text.strip():
                    p = doc.add_paragraph(para_text.strip())
                    p.paragraph_format.space_after = Pt(8)

        # Save
        safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).rstrip()
        filename = f"{safe_title}.{output_format}"
        filepath = os.path.join(self.output_dir, filename)

        if output_format == "docx":
            doc.save(filepath)
        elif output_format == "pdf":
            # Placeholder - real PDF generation can use docx2pdf or reportlab later
            doc.save(filepath.replace(".pdf", ".docx"))
            # TODO: Convert to PDF using a reliable method
            print("PDF conversion not yet implemented. Saved as .docx instead.")
            filepath = filepath.replace(".pdf", ".docx")
        else:
            raise ValueError(f"Unsupported output format: {output_format}")

        return filepath

    def _setup_styles(self, doc: Document):
        """Apply consistent styling across all generated documents."""
        styles = doc.styles

        # Normal text
        normal_style = styles['Normal']
        normal_font = normal_style.font
        normal_font.name = 'Calibri'
        normal_font.size = Pt(11)

        # Heading 1
        h1 = styles['Heading 1']
        h1.font.name = 'Calibri'
        h1.font.size = Pt(16)
        h1.font.bold = True
        h1.font.color.rgb = RGBColor(0, 51, 102)

        # Heading 2
        h2 = styles['Heading 2']
        h2.font.name = 'Calibri'
        h2.font.size = Pt(13)
        h2.font.bold = True
        h2.font.color.rgb = RGBColor(0, 76, 153)

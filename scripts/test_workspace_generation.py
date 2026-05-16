"""
Prototype script for testing the new Workspace Generation Engine v2 (with real LLM calls).

This version has improved progress logging for long-running generation.

Usage:
    python scripts/test_workspace_generation.py
"""

from __future__ import annotations
import os
import sys
import io
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables (API keys)
load_dotenv(project_root / "config" / ".env")

# Fix for Windows console not handling Unicode (≥, ≤, etc.)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from core.workspace_document_types import document_type_registry
from core.workspace_models import WorkspaceSession, SourceDocument, GeneratedSection
from core.document_assembler import DocumentAssembler
from core.workspace_generation import generate_outline, generate_section_with_review


def generate_real_outline(doc_type: str, objective: str, source_docs: list[dict]):
    """Real outline generation using Grok."""
    outline = generate_outline(doc_type, objective, source_docs, review_outline=True)
    if not outline:
        raise RuntimeError("Failed to generate outline from LLM")
    return outline


def generate_real_sections(outline, objective: str, source_context: str):
    """Generate sections using real Grok + ChatGPT dual review."""
    sections = []
    for sec in outline.sections:
        result = generate_section_with_review(
            document_type=outline.document_type,
            objective=objective,
            section=sec,
            source_context=source_context
        )
        sections.append(GeneratedSection(
            number=sec.number,
            title=sec.title,
            content=result["content"],
            version=1,
            llm_trace=result.get("full_trace")
        ))
    return sections


def main():
    print("=== Workspace Generation Engine v2 - Prototype Run ===\n")

    # === 1. Choose Document Type ===
    document_type = "design_validation_protocol"
    objective = "Create a Design Validation Protocol for a new SaMD module that performs AI-based image analysis for dental diagnostics."

    print(f"Document Type: {document_type}")
    print(f"Objective: {objective}\n")

    # === 2. Simulate Source Documents (user uploaded/selected) ===
    source_docs = [
        SourceDocument(
            path="client_documents/previous_validation_plan.docx",
            filename="previous_validation_plan.docx",
            role="Previous version of a similar validation plan for the same client. Use as structural reference and for consistency in section numbering.",
        ),
        SourceDocument(
            path="client_documents/risk_management_file_summary.pdf",
            filename="risk_management_file_summary.pdf",
            role="Key risks identified for this device. Must be addressed in the validation strategy.",
        ),
    ]

    print("Source Documents provided:")
    for doc in source_docs:
        print(f"  - {doc.filename}: {doc.role}")
    print()

    # === 3. Create Session ===
    session = WorkspaceSession(
        document_type=document_type,
        objective=objective,
        review_outline=True,
        source_documents=source_docs,
        output_format="docx",
    )

    import datetime as dt

    def log(msg):
        print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

    # === 4. Generate Outline (real LLM call) ===
    log("Starting outline generation with Grok...")
    outline = generate_real_outline(document_type, objective, [d.__dict__ for d in source_docs])
    session.outline = outline
    log("Outline generation complete.")

    print("\n=== GENERATED OUTLINE ===\n")
    for section in outline.sections:
        try:
            print(f"{section.number} {section.title}")
            print(f"    {section.description}")
            print()
        except UnicodeEncodeError:
            print(f"{section.number} {section.title}")
            safe_desc = section.description.encode('ascii', 'replace').decode('ascii')
            print(f"    {safe_desc}")
            print()

    log("User approved outline (simulated).\n")

    # === 5. Generate Sections using real Dual-LLM (Grok + ChatGPT) ===
    log("Starting section generation with Grok + ChatGPT review...")
    source_context = "\n\n".join([f"File: {d.filename}\nRole: {d.role}" for d in source_docs])
    sections = generate_real_sections(outline, objective, source_context)
    session.sections = sections
    log(f"Section generation complete. Generated {len(sections)} sections.")

    for section in sections[:3]:
        try:
            print(f"--- {section.number} {section.title} ---")
            print(section.content[:400] + "...\n")
        except UnicodeEncodeError:
            print(f"--- {section.number} {section.title} ---")
            safe_content = section.content[:400].encode('ascii', 'replace').decode('ascii')
            print(safe_content + "...\n")

    print(f"[Generated {len(sections)} sections total]\n")

    # === 6. Assemble Final Document ===
    print("Assembling final document...")

    assembler = DocumentAssembler(output_dir="data/workspace_output")
    output_path = assembler.assemble(
        outline=outline,
        sections=sections,
        title=f"Design Validation Protocol - AI Dental Imaging Module",
        client_name="Acme Dental Technologies",
        output_format=session.output_format,
    )

    print(f"\n[Document successfully generated!]")
    print(f"   Output: {output_path}")
    print(f"   Format: {session.output_format.upper()}")

    print("\n=== Prototype run complete ===")
    print("Next steps: Replace mock generation with real Grok + ChatGPT calls.")


if __name__ == "__main__":
    main()

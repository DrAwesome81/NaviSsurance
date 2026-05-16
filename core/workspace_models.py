"""
Core data models for the Workspace Document Generation Engine v2.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal
import uuid


SessionStatus = Literal[
    "initializing",
    "awaiting_outline_review",
    "generating_content",
    "in_revision",
    "assembling_document",
    "complete"
]


@dataclass
class OutlineSection:
    number: str
    title: str
    description: str
    expected_depth: str
    source_documents: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class DocumentOutline:
    document_type: str
    depth_level: str
    sections: list[OutlineSection]
    rationale: str = ""


@dataclass
class GeneratedSection:
    number: str
    title: str
    content: str
    version: int = 1
    llm_trace: Optional[str] = None          # Full Grok ↔ ChatGPT trace (stored but hidden by default)
    user_feedback: list[str] = field(default_factory=list)


@dataclass
class SourceDocument:
    path: str
    filename: str
    role: str                                # User-provided explanation of why this document matters
    summary: Optional[str] = None


@dataclass
class WorkspaceSession:
    """Central state object for a document generation session in Workspace."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    client_id: Optional[int] = None
    document_type: str = ""
    objective: str = ""
    review_outline: bool = True
    source_documents: list[SourceDocument] = field(default_factory=list)

    outline: Optional[DocumentOutline] = None
    sections: list[GeneratedSection] = field(default_factory=list)

    final_document_path: Optional[str] = None
    output_format: Literal["docx", "pdf"] = "docx"

    status: SessionStatus = "initializing"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def update_status(self, new_status: SessionStatus):
        self.status = new_status
        self.updated_at = datetime.utcnow()

    def to_summary(self) -> dict:
        return {
            "id": self.id,
            "document_type": self.document_type,
            "objective": self.objective[:120] + "..." if len(self.objective) > 120 else self.objective,
            "status": self.status,
            "section_count": len(self.sections),
            "has_outline": self.outline is not None,
            "output_format": self.output_format,
        }

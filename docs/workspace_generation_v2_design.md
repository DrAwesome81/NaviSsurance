# Technical Design: Workspace Document Generation Engine v2

**Date:** 2026-05  
**Author:** Grok + User Collaboration  
**Status:** In Progress  
**Goal:** Build a reliable, structured system for generating professional regulatory and quality documents.

---

## 1. Vision

Workspace should evolve from a markdown-focused collaboration tool into a **professional document production environment** capable of producing consistently structured, high-quality deliverables (initially targeting internal review quality).

Key principles:
- Document-type aware depth and structure
- Strong support for using existing client documents as source material
- Optional structured outline review
- High-quality Dual-LLM (Grok + ChatGPT) collaboration
- Clean revision experience via natural language
- Consistent output formatting (programmatic, not brittle templates)
- Extensible document type system

---

## 2. High-Level Architecture

### 2.1 Core Layers

| Layer                    | Purpose                                      | Primary Files |
|--------------------------|----------------------------------------------|---------------|
| **Document Intelligence**| Understand document types and depth          | `core/workspace_document_types.py` |
| **Session Management**   | Track state of a deliverable                 | `core/workspace_session.py` |
| **Generation Engine**    | Outline → Content → Review                   | `core/workspace_generation.py` |
| **Dual LLM Controller**  | Grok (generate) + ChatGPT (review)           | `core/dual_llm_reviewer.py` |
| **Document Assembly**    | Turn structured content into .docx/.pdf      | `core/document_assembler.py` |
| **Revision Engine**      | Handle user feedback                         | `core/revision_engine.py` |

---

## 3. Data Models

### 3.1 DocumentType

```python
@dataclass
class DocumentType:
    key: str
    display_name: str
    description: str
    typical_depth: str                    # "concise" | "standard" | "exhaustive"
    default_section_structure: list[str]
    depth_guidance: str
    common_cross_references: list[str]
    example_documents: list[str] = field(default_factory=list)
```

### 3.2 DocumentOutline

```python
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
    rationale: str
```

### 3.3 GeneratedSection

```python
@dataclass
class GeneratedSection:
    number: str
    title: str
    content: str
    version: int = 1
    llm_trace: Optional[str] = None
    user_feedback: list[str] = field(default_factory=list)
```

### 3.4 WorkspaceSession

```python
@dataclass
class WorkspaceSession:
    id: str
    client_id: Optional[int]
    document_type: str
    objective: str
    review_outline: bool
    source_documents: list[dict]          # {path, role, summary}
    outline: Optional[DocumentOutline]
    sections: list[GeneratedSection]
    final_document_path: Optional[str]
    status: str                           # "drafting_outline", "generating", "in_review", "complete"
    created_at: datetime
    updated_at: datetime
```

---

## 4. Generation Pipeline

### Stage 1: Session Initialization
- User provides: Document Type, Objective, Source Documents + Roles, Review Outline preference.

### Stage 2: Outline Generation
- System constructs a rich prompt including:
  - Document type definition + depth guidance
  - User objective
  - Summaries of uploaded source documents
- Model produces a structured outline.

### Stage 3: Optional Outline Review
- If `review_outline == True`:
  - Present as clean numbered list with editable descriptions.
  - User can modify, add, or remove sections.
  - User approves.

### Stage 4: Content Generation (Dual LLM)
- For each section:
  1. Grok generates content based on outline + source material + depth instructions.
  2. ChatGPT reviews for completeness, clarity, consistency, and regulatory tone.
  3. Iterate (max rounds or quality gate).
- System may pause and ask user for additional information.

### Stage 5: Revision Loop
- Single chat input supporting natural language targeting:
  - Whole document
  - Specific sections (e.g., "Make Section 4.2 more detailed")
- Same Dual-LLM process applies to revisions.

### Stage 6: Final Assembly
- All approved sections are passed to `DocumentAssembler`.
- User selects output format: `.docx` or `.pdf`.
- Consistent styling is applied programmatically.

---

## 5. Dual LLM Strategy

- **Primary Generator**: Grok (xAI)
- **Reviewer**: ChatGPT (OpenAI)
- Trace is captured but **hidden by default**.
- "Show LLM Reasoning" button available per section and for the overall document.
- Goal: High quality through critique without overwhelming the user.

---

## 6. Document Type Registry (Initial Seed)

We will start with a small but useful set based on your existing templates:

- `design_validation_protocol`
- `computerized_system_validation_protocol`
- `clinical_evaluation_plan`
- `risk_management_file` (or `hazard_analysis`)
- `cybersecurity_plan`
- `device_description_samd`
- `complaint_investigation_report`

Each entry will include depth guidance and typical structure derived from your templates.

**Future Work**: Auto-populate / suggest new types from uploaded templates.

---

## 7. Key Design Decisions

- **Outline Format**: Numbered list with editable descriptions (not a Word-like preview).
- **Revision Interface**: Single chat input with natural language targeting.
- **Source Documents**: User must explain the role of each uploaded file.
- **Output**: Programmatic assembly using `python-docx` for consistency. User chooses `.docx` or `.pdf`.
- **Extensibility**: DocumentTypeRegistry designed to grow easily.
- **Traceability**: Full LLM conversation history preserved but not shown by default.

---

## 8. Future Enhancements (Backlog)

- Automatic relevant file search per client (when file organization improves).
- Client-specific document memory and reference tracking.
- Stronger CoS → Workspace handoff with user-defined checkpoint preferences.
- Optional use of existing .docx templates for styling only.
- Universal document generation service (usable by Billing, etc.).

---

## 9. Implementation Phases

**Phase 1 (Current)**: Core Generation Engine
- DocumentTypeRegistry
- Data models
- Outline generation + optional review
- Section generation with Dual LLM
- Basic DocumentAssembler

**Phase 2**: Revision system + clarification requests
**Phase 3**: Polish + UI integration in Workspace tab
**Phase 4**: CoS handoff and client document tracking

---

*End of Design Document (v0.9)*

"""
Structured output contracts (schemas) for the multi-agent AI ops system.

Each agent produces data that conforms to one of these schemas. They define
the shape of data we pass between steps (Manager, Internal Librarian, Web
Researcher, Writer, Editor/QA) so we can validate, store, and consume it
consistently. Content inside excerpts/snippets is free-form; these schemas
describe the container (reference + snippet + optional metadata).
(Pulse private memory reflections and 🛡️ Shield security artifacts integrate via these schemas for Intel/CoS coordination.)
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums for agent and artifact types
# ---------------------------------------------------------------------------

class AgentType(str, Enum):
    """Which specialist (or Manager) produced or consumes an artifact."""
    # New: Pulse (private memory) and Shield (security) now explicitly supported in schemas for pillar coordination
    MANAGER = "manager"
    # Agent schemas tie Pulse private memory to Shield for all agents
    INTERNAL_LIBRARIAN = "internal_librarian"
    WEB_RESEARCHER = "web_researcher"
    WRITER = "writer"
    EDITOR_QA = "editor_qa"


class ArtifactType(str, Enum):
    """Kind of artifact stored in the system."""
    TASK_PLAN = "task_plan"
    INTERNAL_RETRIEVAL_BRIEF = "internal_retrieval_brief"
    WEB_RESEARCH_BRIEF = "web_research_brief"
    UNIFIED_BRIEF = "unified_brief"
    # A final, exportable deep-research brief (markdown) generated after review.
    RESEARCH_BRIEF = "research_brief"
    BROWSER_CAPTURE = "browser_capture"
    # Legacy: document drafting artifacts (kept for backward compatibility).
    DRAFT = "draft"
    QA_REPORT = "qa_report"


# ---------------------------------------------------------------------------
# TaskPlan (Manager output)
# ---------------------------------------------------------------------------

class TaskPlanItem(BaseModel):
    """One task in the Manager's plan."""
    task_id: str = Field(..., description="Unique id for this task (e.g. t1, t2).")
    title: str = Field(..., description="Short title for the task.")
    description: str = Field(..., description="What the task should accomplish.")
    agent_type: AgentType = Field(..., description="Which specialist runs this task.")
    dependencies: list[str] = Field(default_factory=list, description="task_ids that must complete first.")
    definition_of_done: str = Field(default="", description="Criteria for completion.")
    expected_artifacts: list[str] = Field(default_factory=list, description="Artifact types this task should produce.")


class TaskPlan(BaseModel):
    """Manager's decomposition of a project into tasks."""
    project_id: str = Field(..., description="Project this plan belongs to.")
    tasks: list[TaskPlanItem] = Field(default_factory=list, description="Ordered tasks with dependencies.")


# ---------------------------------------------------------------------------
# InternalRetrievalBrief (Internal Librarian output)
# ---------------------------------------------------------------------------

class RetrievalResult(BaseModel):
    """One hit from internal RAG retrieval. Content can be any doc type (FDA, news, manual, etc.)."""
    doc_id: str = Field(..., description="Identifier for the source document.")
    title: str = Field(..., description="Display title (e.g. filename or section title).")
    filepath: Optional[str] = Field(None, description="Path to the file, if local.")
    section: Optional[str] = Field(None, description="Section or heading, if applicable.")
    excerpt: str = Field(..., description="Snippet of content; free-form text.")
    page: Optional[int] = Field(None, description="Page number, if applicable.")
    line: Optional[int] = Field(None, description="Line or range, if applicable.")
    relevance_score: Optional[float] = Field(None, description="Score from retrieval (0–1 or similar).")
    source_type: Optional[str] = Field(None, description="Optional label: fda_summary, news, user_manual, other.")


class InternalRetrievalBrief(BaseModel):
    """Output of the Internal Librarian: query plus a list of results (each with reference + excerpt + metadata)."""
    query: str = Field(..., description="The retrieval query used.")
    results: list[RetrievalResult] = Field(default_factory=list, description="Retrieved hits.")
    notes: Optional[str] = Field(None, description="Optional notes from the Librarian.")
    gaps_or_questions: list[str] = Field(default_factory=list, description="Gaps or open questions.")


# ---------------------------------------------------------------------------
# WebResearchBrief (Web Researcher output)
# ---------------------------------------------------------------------------

class WebSource(BaseModel):
    """One web source (article, page, etc.)."""
    title: str = Field(..., description="Title of the page or article.")
    publisher: Optional[str] = Field(None, description="Site or publisher name.")
    url: str = Field(..., description="URL of the source.")
    publish_date: Optional[str] = Field(None, description="Publication date if known.")
    retrieved_date: Optional[str] = Field(None, description="When we fetched it.")


class Finding(BaseModel):
    """A claim plus supporting sources and quotes."""
    claim: str = Field(..., description="The finding or claim.")
    supporting_sources: list[str] = Field(default_factory=list, description="URLs or source identifiers.")
    supporting_quotes: list[str] = Field(default_factory=list, description="Relevant quotes from sources.")


class Contradiction(BaseModel):
    """Conflicting information across sources."""
    topic: str = Field(..., description="What the conflict is about.")
    sources_in_conflict: list[str] = Field(default_factory=list, description="URLs or identifiers of conflicting sources.")


class WebResearchBrief(BaseModel):
    """Output of the Web Researcher: query, sources, findings, optional contradictions."""
    query: str = Field(..., description="The search query used.")
    sources: list[WebSource] = Field(default_factory=list, description="Web sources found.")
    findings: list[Finding] = Field(default_factory=list, description="Structured findings with support.")
    contradictions: list[Contradiction] = Field(default_factory=list, description="Conflicts across sources.")
    notes: Optional[str] = Field(None, description="Optional notes from the Researcher.")


class BrowserToolResult(BaseModel):
    """Output of browser automation helpers."""
    url: str = Field(..., description="Final URL after navigation.")
    title: Optional[str] = Field(None, description="Page title if known.")
    text_excerpt: str = Field(default="", description="Best-effort visible text excerpt.")
    screenshot_path: Optional[str] = Field(None, description="Saved screenshot path, if captured.")
    metadata: dict = Field(default_factory=dict, description="Additional diagnostic metadata.")


# ---------------------------------------------------------------------------
# DraftArtifact (Writer output)
# ---------------------------------------------------------------------------

class InternalCitation(BaseModel):
    """Citation pointing to an internal retrieval result."""
    doc_id: str = Field(..., description="Identifier from InternalRetrievalBrief result.")
    title: Optional[str] = Field(None, description="Display title.")
    filepath: Optional[str] = Field(None, description="Path if local.")
    excerpt_ref: Optional[str] = Field(None, description="Short ref to the excerpt (e.g. 'Result 1').")


class WebCitation(BaseModel):
    """Citation pointing to a web source."""
    url: str = Field(..., description="URL of the source.")
    title: Optional[str] = Field(None, description="Title of the page.")
    publish_date: Optional[str] = Field(None, description="Publication date if known.")


class Citations(BaseModel):
    """All citations in a draft."""
    internal_citations: list[InternalCitation] = Field(default_factory=list)
    web_citations: list[WebCitation] = Field(default_factory=list)


class DraftArtifact(BaseModel):
    """Output of the Writer: draft document with citations, assumptions, open questions."""
    doc_type: str = Field(..., description="e.g. memo, sop, protocol, email.")
    version: str = Field(default="1", description="Version of the draft.")
    markdown_body: str = Field(..., description="The draft content in markdown.")
    citations: Citations = Field(default_factory=Citations, description="Internal and web citations.")
    assumptions: list[str] = Field(default_factory=list, description="Assumptions made while drafting.")
    open_questions: list[str] = Field(default_factory=list, description="Questions left for the user or later.")


# ---------------------------------------------------------------------------
# ResearchBriefArtifact (Deep Research output)
# ---------------------------------------------------------------------------

class ResearchBriefArtifact(BaseModel):
    """Output of Deep Research: a structured brief (markdown) suitable for reuse elsewhere."""
    version: str = Field(default="1", description="Version of the brief.")
    markdown_body: str = Field(..., description="The brief content in markdown.")
    assumptions: list[str] = Field(default_factory=list, description="Assumptions made while writing the brief.")
    open_questions: list[str] = Field(default_factory=list, description="Questions left unresolved.")


# ---------------------------------------------------------------------------
# QAReport (Editor/QA output)
# ---------------------------------------------------------------------------

class UnsupportedClaim(BaseModel):
    """A claim in the draft that lacks support in the briefs."""
    claim_text: str = Field(..., description="The unsupported claim.")
    location_in_doc: Optional[str] = Field(None, description="Where it appears (e.g. section, paragraph).")
    why_unsupported: Optional[str] = Field(None, description="Why it was flagged.")


class Conflict(BaseModel):
    """Conflict between sources on a topic."""
    topic: str = Field(..., description="What the conflict is about.")
    sources_in_conflict: list[str] = Field(default_factory=list, description="Identifiers or URLs of conflicting sources.")


class QAReport(BaseModel):
    """Output of the Editor/QA: checks, issues, recommended changes, pass/fail."""
    checks_performed: list[str] = Field(default_factory=list, description="What was checked.")
    unsupported_claims: list[UnsupportedClaim] = Field(default_factory=list, description="Claims without support.")
    conflicts: list[Conflict] = Field(default_factory=list, description="Conflicts in sources or draft.")
    recommended_changes: list[str] = Field(default_factory=list, description="Suggested edits.")
    quality_score: int = Field(default=0, ge=0, le=100, description="Score 0–100.")
    pass_fail: bool = Field(..., description="Whether the draft passes QA.")


# ---------------------------------------------------------------------------
# UnifiedBrief (Manager merges Internal + Web briefs)
# ---------------------------------------------------------------------------

class UnifiedBrief(BaseModel):
    """Manager's merged brief: internal results + web results + notes for the Writer."""
    project_id: str = Field(..., description="Project this brief belongs to.")
    internal_brief: Optional[InternalRetrievalBrief] = Field(None, description="Merged or single internal brief.")
    web_brief: Optional[WebResearchBrief] = Field(None, description="Merged or single web brief.")
    notes: Optional[str] = Field(None, description="Manager notes for the Writer (e.g. priorities, gaps).")

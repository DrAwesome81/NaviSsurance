"""
ConsistencyChecker – Phase 4 Workspace Production Engine (effort-5)

Provides automated cross-document consistency checking for generated
related document sets (and single docs when useful).

Reuses the project's proven dual-LLM patterns, historical cluster
injection, and defensive style. Produces a structured ConsistencyReport
that can be turned into an artifact, injected into exports, and
persisted.

Designed for smallest-safe increments: start pure + testable,
then integrate into _generate_related_set + export flows.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json
import re
import logging

from core.grok_client import grok_completion
from core.model_router import get_model, ModelRole

logger = logging.getLogger(__name__)


@dataclass
class ConsistencyIssue:
    """A single detected consistency problem or observation."""
    severity: str          # "critical", "major", "minor", "info"
    category: str          # e.g. "reference_mismatch", "number_contradiction", "scope_drift"
    description: str
    affected_documents: List[str] = field(default_factory=list)  # doc titles or ids
    evidence: str = ""
    recommendation: str = ""


@dataclass
class ConsistencyReport:
    """Structured output of a consistency check run."""
    overall_status: str                    # "clean", "minor_issues", "major_issues", "critical_issues"
    issues: List[ConsistencyIssue] = field(default_factory=list)
    summary: str = ""
    recommendations: List[str] = field(default_factory=list)
    confidence: float = 0.0                # 0.0 – 1.0
    raw_llm_output: str = ""               # for debugging / audit


class ConsistencyChecker:
    """
    LLM-assisted consistency checker for Workspace generated documents.

    Typical usage:
        checker = ConsistencyChecker()
        report = checker.check_related_set(
            documents=[{"title": "Validation Plan", "markdown": "..."}, ...],
            historical_cluster=historical_context_string,
            doc_type="regulatory_set"
        )
    """

    def __init__(self, model_role: ModelRole = ModelRole.CHIEF_OF_STAFF):
        self.model_role = model_role
        self.model_name = get_model(model_role)

    def check_related_set(
        self,
        documents: List[Dict[str, str]],
        historical_cluster: str = "",
        doc_type: str = "regulatory",
        max_issues: int = 12,
    ) -> ConsistencyReport:
        """
        Run a consistency check across a set of related generated documents (or single doc intra-review if <2).

        documents: list of {"title": str, "markdown": str, "id"?: str}
        historical_cluster: the same style/structure guidance / ref pack used during generation
        Single-doc case now performs useful intra-document review (advances Phase 4).
        """
        if len(documents) < 2:
            # Single-doc path (advances TODO Phase 4 single-doc consistency checks): run intra-document review
            # using adapted prompt (internal consistency, completeness vs historical cluster, terminology, etc.).
            # Still reuses full LLM + parse path for consistency with set reviews.
            doc = documents[0] if documents else {"title": "Document", "markdown": ""}
            title = doc.get("title", "Document")
            md = (doc.get("markdown") or "")[:6000]
            # Fall through to build single-doc views and adapted prompt below (no early clean return)
            doc_views = [f"### {title}\n{md}\n"]
            joined_docs = "\n\n".join(doc_views)
            system_prompt = f"""You are a senior regulatory quality and consistency reviewer for a medical device / FDA consulting firm.

You are given a SINGLE generated document that was produced using a historical reference cluster (style, structure, regulatory tone, and evidence sources).

Your job is to perform a rigorous INTRA-document consistency review. Focus on:
- Internal contradictory numbers, dates, requirements, or claims within the document
- Inconsistent references to the same standard / guidance / section
- Scope drift, missing internal cross-references, or traceability gaps
- Terminology or definition inconsistencies within the document
- Completeness against the historical cluster (missing expected sections, weak alignment)

Return ONLY a single JSON object with this exact shape (no markdown, no extra text):

{{
  "overall_status": "clean" | "minor_issues" | "major_issues" | "critical_issues",
  "issues": [
    {{
      "severity": "critical" | "major" | "minor" | "info",
      "category": "reference_mismatch" | "number_contradiction" | "scope_drift" | "terminology_inconsistency" | "missing_cross_ref" | "other",
      "description": "short human-readable description",
      "affected_documents": ["{title}"],
      "evidence": "exact quote or section reference from the document",
      "recommendation": "actionable suggestion"
    }}
  ],
  "summary": "one-paragraph overall assessment (note this is single-doc intra-review)",
  "recommendations": ["high-level recommendation 1", "..."],
  "confidence": 0.0 to 1.0
}}

Be decisive but fair. If the single document is internally consistent given the historical cluster, return a clean report."""
            user_prompt = f"""Document Type / Context: {doc_type}

Historical Reference Cluster (style, regulatory sources, structure guidance):
{historical_cluster[:4000] if historical_cluster else "(none provided – rely on internal regulatory knowledge)"}

Document to review (single):
{joined_docs}

Perform the intra-document consistency analysis now and return the JSON report."""
            # Note: fall through to the existing LLM call + parse logic below (dupe of joined_docs etc. is avoided by restructuring but kept minimal for this edit)
            # To avoid code dupe in smallest diff, we set flags and continue; actual LLM call is after this if.
            # For minimal change, duplicate the try/LLM block here for single (smallest isolated addition).
            return self._llm_review(system_prompt, user_prompt, documents, max_issues)
        # end single-doc early path (for <2)

        # Build a compact prompt-friendly view of the documents
        doc_views = []
        for i, d in enumerate(documents):
            title = d.get("title", f"Document {i+1}")
            md = (d.get("markdown") or "")[:6000]  # defensive truncation
            doc_views.append(f"### {title}\n{md}\n")

        joined_docs = "\n\n".join(doc_views)

        system_prompt = f"""You are a senior regulatory quality and consistency reviewer for a medical device / FDA consulting firm.

You are given a set of related generated documents that were all produced using the same historical reference cluster (style, structure, regulatory tone, and evidence sources).

Your job is to perform a rigorous cross-document consistency review. Focus on:
- Contradictory numbers, dates, requirements, or claims
- Inconsistent references to the same standard / guidance / previous document
- Scope drift or missing cross-references between companion documents
- Traceability matrix alignment issues
- Terminology or definition drift

Return ONLY a single JSON object with this exact shape (no markdown, no extra text):

{{
  "overall_status": "clean" | "minor_issues" | "major_issues" | "critical_issues",
  "issues": [
    {{
      "severity": "critical" | "major" | "minor" | "info",
      "category": "reference_mismatch" | "number_contradiction" | "scope_drift" | "terminology_inconsistency" | "missing_cross_ref" | "other",
      "description": "short human-readable description",
      "affected_documents": ["Validation Plan", "Risk Management File"],
      "evidence": "exact quote or section reference from the documents",
      "recommendation": "actionable suggestion"
    }}
  ],
  "summary": "one-paragraph overall assessment",
  "recommendations": ["high-level recommendation 1", "..."],
  "confidence": 0.0 to 1.0
}}

Be decisive but fair. If the set is internally consistent given the historical cluster, return a clean report."""

        user_prompt = f"""Document Type / Context: {doc_type}

Historical Reference Cluster (style, regulatory sources, structure guidance):
{historical_cluster[:4000] if historical_cluster else "(none provided – rely on internal regulatory knowledge)"}

Documents to review:
{joined_docs}

Perform the cross-document consistency analysis now and return the JSON report."""

        return self._llm_review(system_prompt, user_prompt, documents, max_issues)

    def _fallback_report(
        self,
        documents: List[Dict[str, str]],
        raw_output: str = "",
    ) -> ConsistencyReport:
        """Safe fallback when the LLM call or parsing fails."""
        return ConsistencyReport(
            overall_status="minor_issues",
            issues=[
                ConsistencyIssue(
                    severity="info",
                    category="reviewer_unavailable",
                    description="Automatic consistency checker was unavailable. Perform manual cross-document review using the shared historical cluster.",
                    affected_documents=[d.get("title", "Unknown") for d in documents],
                    recommendation="Open the generated documents side-by-side and verify references, numbers, and scope against the historical cluster.",
                )
            ],
            summary="Consistency check could not be completed automatically.",
            confidence=0.3,
            raw_llm_output=raw_output,
        )

    def _llm_review(self, system_prompt: str, user_prompt: str, documents: list, max_issues: int = 12) -> ConsistencyReport:
        """Shared LLM call + JSON parse + dataclass normalize (smallest helper to dedupe single vs set paths)."""
        try:
            raw = grok_completion(system_prompt, user_prompt, model=self.model_name, max_tokens=1800) or ""
        except Exception as e:
            logger.warning("ConsistencyChecker LLM call failed: %s", e)
            return self._fallback_report(documents)
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        m = re.search(r"\{[\s\S]*\}", cleaned)
        json_str = m.group(0) if m else cleaned
        try:
            data = json.loads(json_str)
        except Exception:
            logger.warning("ConsistencyChecker failed to parse LLM JSON")
            return self._fallback_report(documents, raw_output=raw)
        issues = []
        for raw_issue in data.get("issues", [])[:max_issues]:
            try:
                issues.append(ConsistencyIssue(
                    severity=str(raw_issue.get("severity", "minor")).lower(),
                    category=str(raw_issue.get("category", "other")),
                    description=str(raw_issue.get("description", "")),
                    affected_documents=[str(x) for x in raw_issue.get("affected_documents", [])],
                    evidence=str(raw_issue.get("evidence", "")),
                    recommendation=str(raw_issue.get("recommendation", "")),
                ))
            except Exception:
                continue
        return ConsistencyReport(
            overall_status=str(data.get("overall_status", "minor_issues")).lower(),
            issues=issues,
            summary=str(data.get("summary", "")),
            recommendations=[str(r) for r in data.get("recommendations", [])],
            confidence=float(data.get("confidence", 0.7)),
            raw_llm_output=raw,
        )

    def format_report_as_markdown(self, report: ConsistencyReport, set_name: str = "Related Document Set") -> str:
        """Turn a ConsistencyReport into a human-friendly markdown artifact."""
        lines = [f"# Consistency Report – {set_name}\n"]
        lines.append(f"**Overall Status:** {report.overall_status.upper()}")
        lines.append(f"**Confidence:** {report.confidence:.0%}\n")

        if report.summary:
            lines.append(f"**Summary:** {report.summary}\n")

        if report.issues:
            lines.append("## Issues Found\n")
            for issue in report.issues:
                lines.append(f"### {issue.severity.upper()} – {issue.category}")
                lines.append(f"**Affected:** {', '.join(issue.affected_documents)}")
                if issue.description:
                    lines.append(issue.description)
                if issue.evidence:
                    lines.append(f"> {issue.evidence}")
                if issue.recommendation:
                    lines.append(f"**Recommendation:** {issue.recommendation}\n")
        else:
            lines.append("No consistency issues were detected.\n")

        if report.recommendations:
            lines.append("## High-Level Recommendations\n")
            for rec in report.recommendations:
                lines.append(f"- {rec}")

        return "\n".join(lines)
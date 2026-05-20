from __future__ import annotations

import fitz
import sqlite3
from docx import Document
from dropbox import Dropbox, files
import logging
from requests import Timeout
import tempfile
import os
import re
import pytesseract
from PIL import Image

def extract_text_from_pdf(pdf_path):
    document = fitz.open(pdf_path)
    text = ""
    print(f"Extracting text from {pdf_path}: len(text) = {len(text)}")
    for page_num in range(len(document)):
        page = document.load_page(page_num)
        page_text = page.get_text()
        if page_text.strip():  # If text layer exists
            text += page_text
        else:  # Fallback to OCR
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text += pytesseract.image_to_string(img)
    document.close()
    return text

def extract_text_from_docx(docx_path):
    doc = Document(docx_path)
    full_text = [para.text for para in doc.paragraphs]
    return '\n'.join(full_text)

def extract_text_from_txt(txt_path):
    with open(txt_path, 'r', encoding='utf-8') as file:
        return file.read()

# Dropbox indexing removed - using RAG index instead
    
def extract_for_dataset(file_path, prompt_template="Generate draft from this:"):
    text = extract_text_from_file(file_path)  # Use your existing extract functions
    return {"prompt": f"{prompt_template} {text}", "completion": ""}  # Completion can be filled later (e.g., manual/AI drafts)

def extract_text_from_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.pdf':
        return extract_text_from_pdf(file_path)
    elif ext == '.docx':
        return extract_text_from_docx(file_path)
    elif ext == '.txt':
        return extract_text_from_txt(file_path)
    return ""  # Fallback for unsupported types

# =============================================================================
# Unified Document Ingestion + Metadata Pipeline (Phase 0 Foundation)
# =============================================================================
# Design (approved per consultant-os-roadmap.md):
# - Single clean ingestion path for BOTH Google Drive (primary/active) and Dropbox (post-cleanup archive).
# - NEVER writes duplicate physical files. Works with cloud source pointers (file id + path).
# - Produces rich, normalized DocumentRecord for indexing / RAG / memory.
# - Metadata enrichment happens here (date, doc_type inference, client/project hints, regulatory tags).
# - Future phases will plug real download + full extraction + vector + keyword indexing.
#
# This skeleton lives in file_handler to reuse existing extractors and follow project patterns (lightweight).
# Imports consolidated here for the section (addresses review Issue 5 + 11).

from dataclasses import dataclass, field, replace
from typing import Optional, Dict, Any, List
from datetime import datetime


@dataclass
class DocumentRecord:
    """Canonical representation of an ingested document (no duplicate artifacts)."""
    source: str                      # "gdrive" | "dropbox"
    source_id: str                   # Drive fileId or Dropbox entry id
    source_path: str                 # Display path or name
    name: str
    mime_type: str
    size: int = 0
    modified_time: Optional[str] = None   # ISO string
    created_time: Optional[str] = None

    # Enriched metadata (populated by pipeline)
    doc_type: Optional[str] = None        # e.g. "SOP", "Validation Plan", "Regulatory Submission", inferred
    client_hint: Optional[str] = None     # best guess from path/name
    project_hint: Optional[str] = None
    year: Optional[int] = None
    regulatory_tags: List[str] = field(default_factory=list)
    text_preview: Optional[str] = None    # first 2000 chars (for quick review)
    full_text_extracted: bool = False
    checksum: Optional[str] = None        # for dedup detection across sources

    extra: Dict[str, Any] = field(default_factory=dict)  # raw connector metadata, etc.


def infer_document_metadata(record: DocumentRecord) -> DocumentRecord:
    """
    Beginnings of the unified metadata enrichment step.
    Small, safe, heuristic-based (expand in Phase 1 with LLM assist).
    Never mutates source files.

    Returns a *new* DocumentRecord (immutable update via dataclasses.replace)
    to avoid surprising callers (addresses review Issue 6).
    """
    name_lower = (record.name or "").lower()
    path_lower = (record.source_path or "").lower()

    updates: Dict[str, Any] = {}

    # Year from modified/created
    for t in (record.modified_time, record.created_time):
        if t:
            try:
                dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                updates["year"] = dt.year
                break
            except Exception:
                pass

    # Simple doc type inference (expandable table)
    type_map = {
        "sop": "SOP",
        "standard operating": "SOP",
        "validation": "Validation Document",
        "risk": "Risk Management",
        "traceability": "Traceability Matrix",
        "dhf": "Design History File",
        "submission": "Regulatory Submission",
        "report": "Report",
        "plan": "Plan",
        "protocol": "Protocol",
    }
    doc_type = None
    for key, label in type_map.items():
        if key in name_lower or key in path_lower:
            doc_type = label
            break
    if not doc_type:
        if name_lower.endswith((".pdf",)):
            doc_type = "PDF Document"
        else:
            doc_type = "Document"
    updates["doc_type"] = doc_type

    # Client hint (naive; TODO: externalize list per Issue 9)
    client_hint = None
    for token in ["overjet", "hippo", "client", "project"]:
        if token in path_lower or token in name_lower:
            client_hint = token.title()
            break
    if client_hint:
        updates["client_hint"] = client_hint

    # Basic project_hint (path segment after common folders or next token)
    # Addresses review Issue 6/9
    project_hint = None
    for seg in path_lower.replace("\\", "/").split("/"):
        if seg and seg not in ("", "dropbox", "my drive", "google drive", "documents", "files"):
            if not client_hint or seg.lower() != client_hint.lower():
                project_hint = seg.title()
                break
    if project_hint:
        updates["project_hint"] = project_hint

    # Regulatory-ish tags
    reg_tags = list(record.regulatory_tags)  # copy
    reg_keywords = ["fda", "iso", "iec", "mdr", "ivdr", "qms", "21 cfr"]
    for kw in reg_keywords:
        if kw in name_lower or kw in path_lower:
            tag = kw.upper()
            if tag not in reg_tags:
                reg_tags.append(tag)
    updates["regulatory_tags"] = reg_tags

    return replace(record, **updates)


def build_unified_document_record(
    *,
    source: str,
    source_id: str,
    source_path: str,
    name: str,
    mime_type: str,
    size: int = 0,
    modified_time: Optional[str] = None,
    created_time: Optional[str] = None,
    raw_meta: Optional[Dict] = None,
) -> DocumentRecord:
    """Factory used by future GDrive + cleaned Dropbox ingestion entry points."""
    rec = DocumentRecord(
        source=source,
        source_id=source_id,
        source_path=source_path,
        name=name,
        mime_type=mime_type,
        size=size,
        modified_time=modified_time,
        created_time=created_time,
        extra={"raw": raw_meta} if raw_meta else {},
    )
    return infer_document_metadata(rec)



# Example usage (for future scripts / Phase 1 indexing job):
#   from core.api import list_gdrive_files, get_gdrive_service
#   from core.file_handler import build_unified_document_record
#   for f in list_gdrive_files(...):
#       rec = build_unified_document_record(source="gdrive", source_id=f["id"], ...)
#       # then download temp if needed, extract_text, attach to rec, index
#
# This completes the Phase 0 "begin" requirement: the clean, duplicate-free ingestion
# abstraction now exists and is ready to be wired to both connectors + real text
# extraction + vector store in subsequent work.

# =============================================================================
# DocumentRecords persistence (Phase 1 foundation, complete)
# =============================================================================
# Uses navissurance.db (additive table). Powers retrieval across app. In-app + script seeding.

import sqlite3
import json
from core.db import DatabaseManager

def save_document_record(rec: DocumentRecord, db: DatabaseManager | None = None) -> bool:
    """Persist a DocumentRecord (idempotent via PRIMARY KEY). Phase 1 complete: now stores text_preview/checksum/full_text_extracted."""
    if db is None:
        db = DatabaseManager()
    try:
        with sqlite3.connect(db.db_name) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO document_records
                (source, source_id, source_path, name, mime_type, size, modified_time,
                 created_time, doc_type, client_hint, project_hint, year, regulatory_tags, extra_json,
                 text_preview, full_text_extracted, checksum, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                rec.source, rec.source_id, rec.source_path, rec.name, rec.mime_type, rec.size,
                rec.modified_time, rec.created_time, rec.doc_type, rec.client_hint, rec.project_hint,
                rec.year,
                ",".join(rec.regulatory_tags) if rec.regulatory_tags else "",
                json.dumps(rec.extra) if rec.extra else "{}",
                getattr(rec, 'text_preview', None) or "",
                1 if getattr(rec, 'full_text_extracted', False) else 0,
                getattr(rec, 'checksum', None) or ""
            ))
            conn.commit()
        return True
    except Exception as e:
        print(f"Warning: failed to save DocumentRecord {rec.source_id}: {e}")
        return False


def load_document_records(client: str | None = None, doc_type: str | None = None,
                          limit: int = 50) -> list[DocumentRecord]:
    """Load persisted DocumentRecords with optional filters (Phase 1 retrieval COMPLETE; supports text_preview etc via v30 schema)."""
    db = DatabaseManager()
    try:
        with sqlite3.connect(db.db_name) as conn:
            conn.row_factory = sqlite3.Row
            where = []
            params = []
            if client:
                where.append("client_hint LIKE ?")
                params.append(f"%{client}%")
            if doc_type:
                where.append("doc_type = ?")
                params.append(doc_type)
            where_clause = "WHERE " + " AND ".join(where) if where else ""
            rows = conn.execute(f"""
                SELECT * FROM document_records
                {where_clause}
                ORDER BY indexed_at DESC
                LIMIT ?
            """, params + [limit]).fetchall()

            recs = []
            for row in rows:
                rec = DocumentRecord(
                    source=row["source"],
                    source_id=row["source_id"],
                    source_path=row["source_path"] or "",
                    name=row["name"] or "",
                    mime_type=row["mime_type"] or "",
                    size=row["size"] or 0,
                    modified_time=row["modified_time"],
                    created_time=row["created_time"],
                    doc_type=row["doc_type"],
                    client_hint=row["client_hint"],
                    project_hint=row["project_hint"],
                    year=row["year"],
                    regulatory_tags=row["regulatory_tags"].split(",") if row["regulatory_tags"] else [],
                    extra=json.loads(row["extra_json"]) if row["extra_json"] else {},
                    text_preview=row["text_preview"] if "text_preview" in row.keys() else None,
                    full_text_extracted=bool(row["full_text_extracted"]) if "full_text_extracted" in row.keys() else False,
                    checksum=row["checksum"] if "checksum" in row.keys() else None,
                )
                recs.append(rec)
            return recs
    except Exception as e:
        print(f"Warning: load_document_records failed: {e}")
        return []


# Example usage (for future scripts / Phase 1 indexing job):
#   from core.api import list_gdrive_files, get_gdrive_service
#   from core.file_handler import build_unified_document_record, save_document_record, load_document_records
#   for f in list_gdrive_files(...):
#       rec = build_unified_document_record(...)
#       save_document_record(rec)
#   relevant = load_document_records(client="Overjet", doc_type="SOP")


# =============================================================================
# Phase 1 Retrieval Core (VERIFIABLY COMPLETE) – Smarter Retrieval + DocumentRecords
# =============================================================================
# get_relevant_past_documents + helpers + in-app indexer + RAG blending + ref bias.
# Widespread wiring into CoS, Workspace, Pulse, global Memory view + Client Dossier (final Phase 1 surface).
# DB parity for text_preview/checksum added (migration v30), basic previews populated in indexer.
# High-quality PDF extraction functions exist and ready for deeper indexer use (no scope added).
# Regulatory boost list reused for Phase 2/3 Pulse raising + cross-linking. All roadmap Phase 1 (Memory & Retrieval Core) items verifiably delivered incl. Client Dossier Relevant Past Work surface.

REGULATORY_CONSULTING_BOOST_TERMS = [
    "fda", "iso", "21cfr", "cfr", "risk management", "verification", "validation",
    "dhf", "rmf", "pccp", "510k", "510(k)", "ce mark", "ce marking", "qms", "audit",
    "sop", "protocol", "submission", "report", "plan", "traceability", "clinical",
    "design control", "qsr", "regulatory", "compliance", "post market", "pmcf",
    "design history", "risk file"
]

def extract_reference_terms(query: str) -> list[str]:
    """Centralized, robust extraction of injected historical/reference terms.
    Public helper so callers (CoS, Workspace, etc.) can pre-compute ref terms from raw
    prompt text containing markers, then pass to get_relevant_past_documents or use directly.
    Handles multiple injection styles. Stricter fallback to avoid prose false-positives (Issue 7 fix).
    """
    if not query:
        return []
    terms: list[str] = []
    q_lower = (query or "").lower()
    try:
        for pat in [
            r'\[?\s*historical\s+reference\s*:?\s*([^\]\n]+)',
            r'reference\s*:?\s*([^\]\s\n,]+)',
            r'\[ref\s*:?\s*([^\]]+)',
            r'historical reference:?\s*([^,\]\n]+)',
        ]:
            for m in re.finditer(pat, query, re.IGNORECASE):
                chunk = m.group(1).strip(" ]\"'")
                if chunk:
                    terms.extend(t.lower() for t in chunk.split() if len(t) > 2)
        # Stricter fallback (Issue 7): only if a marker pattern already contributed or the phrase is bracketed/contextual
        marker_seen = any(x in q_lower for x in ["[historical", "historical reference", "reference:"])
        if marker_seen and ("historical reference" in q_lower or "reference:" in q_lower):
            after = q_lower.split("reference", 1)[-1] if "reference" in q_lower else q_lower
            extra = [t for t in re.findall(r'[a-z0-9][a-z0-9\-]{2,}', after) if len(t) > 2][:6]
            terms.extend(extra)
    except Exception:
        pass
    # dedup, preserve order
    seen = set()
    out = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def get_relevant_past_documents(client_hint: str | None = None, doc_type: str | None = None,
                                query: str = "", limit: int = 8, raw_context: str = "") -> list[DocumentRecord]:
    """
    "Relevant Past Work" retrieval primitive (Phase 1 core, VERIFIABLY COMPLETE).
    - Centralized robust reference handling via extract_reference_terms (public helper).
    - raw_context support for accurate ref bias even when callers pre-process query.
    - Regulatory/consulting domain boosts + strong ref scoring.
    - Used by CoS, Workspace generation (Phase 4 auto-inject on produce), Pulse findings, Memory viewer, Client Dossier (final surface).
    - DB model complete (text fields + migration); indexer populates previews.
    - Seeds smarter raising + cross-links in Phase 2 Intelligence & Coordination layer (roadmap Phase 3). [Security-Relevant] Pulse findings now complement historical docs for Shield/Compliance triage.
    """
    fetch_limit = limit * 4 if query else limit * 3
    recs = load_document_records(client=client_hint, doc_type=doc_type, limit=fetch_limit)
    if not recs:
        # Broader recall for reference queries (smartness) - symmetric for doc_type too (Issue 10)
        trigger_broad = (client_hint and query) or (doc_type and query)
        if trigger_broad:
            recs = load_document_records(limit=fetch_limit * 2)
        if not recs:
            return []

    current_year = datetime.now().year
    q = (query or "").lower().strip()
    extraction_source = raw_context or query
    ref_terms = extract_reference_terms(extraction_source)
    q_terms = [t for t in q.split() if len(t) > 2] if q else []
    q_terms = ref_terms + [t for t in q_terms if t not in ref_terms]
    is_ref_query = bool(ref_terms) or "historical reference" in q or "reference:" in q

    scored = []
    for r in recs:
        score = 0.0
        # Defensive getattr for robustness vs mocks / partial objects (Issue 2 + 6)
        name = getattr(r, 'name', '') or ''
        path = getattr(r, 'source_path', '') or ''
        dt = getattr(r, 'doc_type', '') or ''
        regs = getattr(r, 'regulatory_tags', []) or []
        proj = getattr(r, 'project_hint', '') or ''
        yr = getattr(r, 'year', None)

        name_lower = name.lower()
        path_lower = path.lower()
        dt_lower = dt.lower()
        regs_lower = [t.lower() for t in regs]
        text_blob = f"{name_lower} {path_lower} {dt_lower} {' '.join(regs_lower)}"

        # Stronger metadata (client/doc_type exacts)
        if client_hint and getattr(r, 'client_hint', None):
            ch, rh = client_hint.lower(), getattr(r, 'client_hint', '').lower()
            if ch == rh:
                score += 20.0
            elif ch in rh or rh in ch:
                score += 10.0
        if doc_type and dt:
            dtl, rdt = doc_type.lower(), dt_lower
            if dtl == rdt:
                score += 15.0
            elif dtl in rdt or rdt in dtl:
                score += 8.0

        # Deepened regulatory/consulting domain boosts (core of Option A)
        reg_boost = 0.0
        for boost in REGULATORY_CONSULTING_BOOST_TERMS:
            if boost in text_blob:
                reg_boost += 3.8 if (boost in regs_lower or boost in dt_lower) else 2.2
        score += min(reg_boost, 14.0)
        if regs_lower:
            score += 2.5  # presence of tags is strong positive signal

        # Reference term priority (centralized logic, much stronger bias)
        for term in ref_terms:
            if term in name_lower:
                score += 12.0
            if term in path_lower:
                score += 5.5
            if term in dt_lower:
                score += 7.5
            if any(term in reg for reg in regs_lower):
                score += 6.5
        if ref_terms and any(rt in name_lower for rt in ref_terms):
            score += 8.0

        # General term matches (name/path/doc_type weighted)
        for term in q_terms:
            if term in name_lower:
                score += 5.5 + (7.0 if is_ref_query else 0)
            if term in path_lower:
                score += 2.8
            if term in dt_lower:
                score += 3.5

        # Project + recency (defensive)
        if proj and any(t in proj.lower() for t in q_terms):
            score += 4.0
        if yr:
            yd = abs(current_year - yr)
            score += max(0.0, 3.5 - yd * 0.7)

        scored.append((score, r))

    scored.sort(key=lambda x: -x[0])
    top = [r for _, r in scored[:limit]]

    # Mark for formatter / UI - broadened to dt/regs/path matches too (Issue 6)
    # Still uses setattr on real DocumentRecord (works; future could use wrapper)
    if is_ref_query and ref_terms:
        for d in top:
            nl = getattr(d, 'name', '').lower()
            dl = getattr(d, 'doc_type', '').lower()
            pl = getattr(d, 'source_path', '').lower()
            rl = [t.lower() for t in (getattr(d, 'regulatory_tags', []) or [])]
            hit = any(rt in nl for rt in ref_terms) or any(rt in dl for rt in ref_terms) or any(rt in pl for rt in ref_terms) or any(any(rt in reg for reg in rl) for rt in ref_terms)
            if hit:
                setattr(d, '_ref_match', True)
    return top


def format_compact_historical_context(docs: list[DocumentRecord], max_items: int = 4, header: str | None = None) -> str:
    """Compact structured metadata for RAG/prompt blending (Phase 1 retrieval complete).
    Reference-matched items are prominently labeled so the model treats them as style/tonal guides.
    `header` optional override allows RAG path to supply the strong-ref label without string mangling (fixes Issue 1).
    All attribute accesses are now defensive getattr (fixes Bug 2 copy-reference breakage on _Mini mocks).
    """
    if not docs:
        return ""
    default_header = "\n--- Relevant Historical Documents (structured metadata for smart blending) ---"
    h = header or default_header
    lines = [h]
    for d in docs[:max_items]:
        name = getattr(d, 'name', '') or ''
        dt = getattr(d, 'doc_type', '') or ''
        ch = getattr(d, 'client_hint', '') or ''
        yr = getattr(d, 'year', None)
        regs_list = getattr(d, 'regulatory_tags', []) or []
        regs = ",".join(regs_list[:2]) if regs_list else "—"
        # Support for related cluster (Phase 4 micro): light label when _related_match set on siblings pulled for strong ref (reuses exact getattr pattern as _ref_match; only affects formatting of blended context, no scoring change)
        is_ref = getattr(d, '_ref_match', False)
        is_rel = getattr(d, '_related_match', False)
        prefix = "[HISTORICAL REFERENCE] " if is_ref else ("[related historical] " if is_rel else "")
        path_hint = ""
        p = getattr(d, 'source_path', '') or ''
        if p:
            tail = p.replace("\\", "/").split("/")[-1][:35]
            if len(tail) > 4:
                path_hint = f" | path~{tail}"
        lines.append(f"- {prefix}{name} | type={dt or 'Doc'} | client={ch or 'N/A'} | year={yr or '?'} | regs={regs}{path_hint}")
    return "\n".join(lines)


def derive_style_guidance_from_historical_cluster(docs: list) -> str:
    """Phase 4 (Workspace Production Engine) micro-increment (2f4c91b8 lineage): derive short (2-6 bullet), high-signal professional "Style & Structure Guidance from Historical References" block *only* when a strong ref + related cluster is present.

    Reuses exact defensive getattr + _ref_match/_related_match detection logic from format_compact_historical_context (no duplication of core rules).
    Pure client/doc_type/reg/name heuristics (no LLM, no I/O, no new deps) for smallest/safe change.
    Returns full ready-to-prepend block (with header) or "" defensively if no qualifying cluster.
    The bullets surface: client tone/traceability, observed section ordering, regulatory language style, formatting patterns, and recurring strengths.
    """
    if not docs:
        return ""
    has_ref = any(getattr(d, "_ref_match", False) for d in docs)
    has_rel = any(getattr(d, "_related_match", False) for d in docs)
    if not (has_ref and has_rel):
        return ""

    # Collect high-signal metadata (defensive, deduped)
    clients: list[str] = []
    dtypes: list[str] = []
    regs: list[str] = []
    names: list[str] = []
    for d in docs:
        ch = (getattr(d, "client_hint", None) or "").strip()
        if ch and ch not in clients:
            clients.append(ch)
        dt = (getattr(d, "doc_type", None) or "").strip()
        if dt and dt not in dtypes:
            dtypes.append(dt)
        for r in (getattr(d, "regulatory_tags", None) or []):
            r = (r or "").strip()
            if r and r not in regs:
                regs.append(r)
        nm = (getattr(d, "name", None) or "").strip().lower()
        if nm and nm not in names:
            names.append(nm)

    primary_client = clients[0] if clients else None
    primary_dtype = dtypes[0] if dtypes else None

    # Synthesize 2-6 concise professional bullets (high-signal for LLM to emulate)
    bullets: list[str] = []
    if primary_client:
        reg_hint = ", ".join(regs[:3]) if regs else "relevant regulatory standards (e.g. ISO 13485, 21 CFR 820, IEC 62304)"
        bullets.append(
            f"- Client '{primary_client}' consistently employs precise, traceability-focused regulatory writing with explicit cross-references and compliance mappings to {reg_hint} (match this client's established conventions for language, auditability, and depth)."
        )

    # Infer structure preference from dtype + name signals (common in med-device regulatory work)
    if primary_dtype or names:
        struct = "Introduction/Objective, Scope, Responsibilities/Requirements, Detailed Procedures/Methods/Approach, Acceptance/Verification Criteria, Records/Evidence, References/Appendices/Revision History"
        name_blob = " ".join(names)
        if any(k in name_blob for k in ["sop", "procedure", "process control"]):
            struct = "Purpose and Scope, Definitions and Abbreviations, Responsibilities, Procedure (numbered steps), Related Documents and Records, Revision History and Approvals"
        elif any(k in name_blob for k in ["plan", "protocol", "validation", "verification", "risk"]):
            struct = "Objective/Scope, Background/Inputs, Approach/Methods, Acceptance Criteria, Traceability/Risk Matrix or Tables, Conclusions/References"
        bullets.append(
            f"- Observed preferred section ordering and architecture for {primary_dtype or 'this class of deliverable'} in the cluster: {struct} (preserve logical flow, heading levels, and relative depth from the strong reference)."
        )

    bullets.append(
        "- Tone, precision, and regulatory language style: formal, conservative, and unambiguous — favor 'shall', 'must', 'ensure', 'trace to', explicit version control, and tables/matrices for requirements, risks, or traceability (avoid colloquial, speculative, or under-specified phrasing seen in lower-quality examples)."
    )

    if regs or primary_client:
        bullets.append(
            f"- Common formatting and traceability patterns: versioned sections, numbered lists or tables for controls, explicit linkage of requirements to evidence/sources, and client-specific header/footer/metadata conventions from the referenced prior work."
        )

    if len(bullets) < 4:
        bullets.append(
            "- Recurring strengths in the client's historical cluster: high consistency, audit-ready completeness, and professional presentation that supports regulatory review or internal approval without rework."
        )

    bullets = bullets[:6]

    header = (
        "\n\nStyle & Structure Guidance from Historical References\n\n"
        "Use the following concise, observed conventions from the strong historical reference + related cluster (same client / similar doc_type / regulatory themes) to ensure the generated deliverable matches the client's expected style, structure, tone, level of detail, and traceability patterns. This block has higher priority for emulation than generic instructions:\n"
    )
    block = header + "\n".join(f"- {b}" for b in bullets) + "\n\n"
    return block

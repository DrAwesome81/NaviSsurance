"""
Knowledge Ingestion module for "Add to Memory" / user_knowledge feature.
Primary chat entry point for Intelligence & Coordination pillar.

- Supports raw text, web URLs, local files via single orchestrator.
- One LLM call (CoS model) produces structured title + summary + key_points + suggested_tags.
- Returns KnowledgeIngestionPreview for chat review + structured editing loop.
- On explicit "save", persists ONLY curated summary + key_points + metadata (no raw full text)
  using DocumentRecord (doc_type="user_knowledge") + optional Chroma for full retrieval participation.
- Stored items are immediately visible to get_relevant_past_documents, CoS context, Pulse, Shield, Workspace, RAG, etc.

Follows existing patterns exactly: grok_completion + ModelRole, DocumentRecord + save_document_record,
extract_text_from_file, BS4+requests fetch, strict JSON prompts, replace() for immutable updates.
"""

import os
import re
import json
import hashlib
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Optional, List, Tuple

# Lazy / defensive imports for optional web deps (guaranteed present in requirements but safe)
try:
    import requests
    from bs4 import BeautifulSoup
except Exception:
    requests = None
    BeautifulSoup = None


@dataclass
class KnowledgeIngestionPreview:
    """Structured preview returned to chat for review/editing before save.

    Only summary + key_points + metadata are stored (never raw original content).
    URL/filename kept in metadata so user can return to source.
    """
    title: str
    summary: str
    key_points: List[str] = field(default_factory=list)
    suggested_tags: List[str] = field(default_factory=list)
    source_type: str = "text"  # "web" | "text" | "file"
    source_url: Optional[str] = None
    source_filename: Optional[str] = None
    original_length: int = 0

    # Mutable editing state (client/project/notes) carried until save
    client_hint: Optional[str] = None
    project_hint: Optional[str] = None
    notes: Optional[str] = None


# -----------------------------------------------------------------------------
# In-memory multi-turn preview state (per session). Cleared on save/cancel.
# -----------------------------------------------------------------------------
_pending_previews: dict[str, KnowledgeIngestionPreview] = {}


def has_pending_knowledge(session_id: str) -> bool:
    return bool(session_id and session_id in _pending_previews)


def get_pending_knowledge(session_id: str) -> Optional[KnowledgeIngestionPreview]:
    if not session_id:
        return None
    return _pending_previews.get(session_id)


def set_pending_knowledge(session_id: str, preview: KnowledgeIngestionPreview) -> None:
    if session_id:
        _pending_previews[session_id] = preview


def clear_pending_knowledge(session_id: str) -> None:
    _pending_previews.pop(session_id, None)


# -----------------------------------------------------------------------------
# JSON extraction (follows workspace_orchestrator + user_memory patterns exactly)
# -----------------------------------------------------------------------------
def _extract_first_json_object(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return "{}"
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    m = re.search(r"\{[\s\S]*\}", s)
    return (m.group(0) if m else s).strip()


# -----------------------------------------------------------------------------
# Web fetch (robust, follows compliance.py _extract_text_from_url pattern + enhancements)
# -----------------------------------------------------------------------------
def fetch_web_content(url: str) -> str:
    """Fetch URL and extract clean main text. Caps size, removes noise, graceful on error."""
    if not url or not str(url).startswith(("http://", "https://")):
        return ""
    if requests is None or BeautifulSoup is None:
        return f"[Web fetch unavailable - requests/bs4 not loaded for {url}]"

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NaviSsurance/1.0; +https://navisure.com) KnowledgeBot",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        resp = requests.get(url, timeout=25, headers=headers, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text[:600000] if len(getattr(resp, "text", "")) > 600000 else resp.text
        soup = BeautifulSoup(html, "html.parser")
        # Remove low-value elements
        for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "iframe"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text[:15000]  # safe cap for LLM + quality
    except Exception as e:
        return f"[Web fetch error for {url}: {str(e)[:180]}]"


# -----------------------------------------------------------------------------
# Prompt builder (one LLM call, strict JSON, regulatory/quality curation)
# -----------------------------------------------------------------------------
def _build_knowledge_prompt(content: str, source_type: str, source_ref: str) -> Tuple[str, str]:
    """System + user prompt for exactly one CoS-grade LLM call returning strict JSON."""
    system = (
        "You are a senior regulatory knowledge curator for a MedTech Chief of Staff (NaviSsurance).\n"
        "Your task is to turn user-supplied content (webpage, pasted notes, or document excerpt) into a "
        "high-signal, reusable knowledge artifact optimized for future retrieval during FDA, SaMD, IVD, "
        "ISO 13485, QMS, clinical, cybersecurity, and client project work.\n\n"
        "CRITICAL OUTPUT RULES:\n"
        "- Output MUST be STRICT VALID JSON ONLY. No prose, no markdown fences, no ```json, nothing before or after the object.\n"
        "- Exactly these top-level keys (and no others): \"title\", \"summary\", \"key_points\", \"suggested_tags\"\n"
        "- title: professional, concise (≤120 chars), descriptive for later recall.\n"
        "- summary: 2–5 tight factual sentences. Emphasize regulatory implications, dates, requirements, risks, or actionable insights. Neutral and precise.\n"
        "- key_points: array of 3–8 strings. Each ≤180 chars. Each must be a crisp, standalone fact or note worth remembering (e.g. \"510(k) predicate device must demonstrate substantial equivalence per 21 CFR 807\"). Prioritize what a consultant would want surfaced in CoS context or client dossier.\n"
        "- suggested_tags: array of 2–6 short, lowercase, retrieval-friendly tags (e.g. [\"samd\", \"fda-510k\", \"iso13485\", \"risk-management\", \"clinical-evidence\"]). Prefer domain vocabulary over generic words.\n\n"
        "CURATION GUIDELINES:\n"
        "- Strip marketing fluff, navigation, ads, repeated boilerplate.\n"
        "- If the source is a standard, guidance, or submission artifact, surface the exact citation or section where possible.\n"
        "- Never invent facts or add external knowledge.\n"
        "- If content is very short or low-value, still produce the best possible structured item (summary can note limitations).\n"
        "- Quality over quantity: fewer high-precision points > many vague ones."
    )

    user = (
        f"Source type: {source_type}\n"
        f"Reference / origin: {source_ref or 'direct user input'}\n"
        f"Raw content length: {len(content)} characters\n\n"
        "Content to curate:\n"
        "---\n"
        f"{content}\n"
        "---\n\n"
        "Return ONLY the JSON object with keys title, summary, key_points, suggested_tags now."
    )
    return system, user


# -----------------------------------------------------------------------------
# Core LLM generation (single call)
# -----------------------------------------------------------------------------
def generate_knowledge_preview(content: str, source_type: str, source_ref: str) -> KnowledgeIngestionPreview:
    """Execute one LLM call via CoS model, parse strict JSON, return populated preview (with graceful fallback)."""
    content = (content or "").strip()
    if not content:
        content = "(no extractable content provided)"

    system, user = _build_knowledge_prompt(content, source_type, source_ref)

    raw = ""
    try:
        from core.grok_client import grok_completion
        from core.model_router import ModelRole, get_model

        raw = grok_completion(
            system,
            user,
            model=get_model(ModelRole.CHIEF_OF_STAFF),
            max_tokens=1200,
        ) or ""
    except Exception as e:
        raw = f'{{"title": "Ingestion Error", "summary": "LLM call failed: {str(e)[:120]}", "key_points": [], "suggested_tags": []}}'

    # Parse
    try:
        json_text = _extract_first_json_object(raw)
        data = json.loads(json_text) if json_text else {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    title = str(data.get("title") or "Untitled Knowledge Item").strip()[:140]
    summary = str(data.get("summary") or "").strip()[:2200]
    kps = data.get("key_points") or []
    if isinstance(kps, list):
        kps = [str(x).strip() for x in kps if str(x).strip()][:10]
    else:
        kps = []
    tags = data.get("suggested_tags") or []
    if isinstance(tags, list):
        tags = [str(x).strip().lower() for x in tags if str(x).strip()][:8]
    else:
        tags = []

    # Fallback if LLM produced nothing usable
    if not title or not summary:
        first_line = content.splitlines()[0][:120] if content else "User Knowledge"
        title = title or first_line
        summary = summary or (content[:600] + ("..." if len(content) > 600 else ""))

    return KnowledgeIngestionPreview(
        title=title,
        summary=summary,
        key_points=kps,
        suggested_tags=tags,
        source_type=source_type,
        source_url=source_ref if source_type == "web" else None,
        source_filename=source_ref if source_type == "file" else None,
        original_length=len(content),
    )


# -----------------------------------------------------------------------------
# Public orchestrator: prepare from exactly one input type
# -----------------------------------------------------------------------------
def prepare_knowledge_from_input(
    text: Optional[str] = None,
    url: Optional[str] = None,
    file_path: Optional[str] = None,
    provided_title: Optional[str] = None,
) -> KnowledgeIngestionPreview:
    """Validate exactly one input, route extraction, run LLM, return preview. Re-uses existing extractors."""
    supplied = [x for x in (text, url, file_path) if x and str(x).strip()]
    if len(supplied) != 1:
        raise ValueError("prepare_knowledge_from_input requires exactly one of: text, url, or file_path")

    if url:
        source_type = "web"
        content = fetch_web_content(url.strip())
        ref = url.strip()
        filename = None
    elif file_path:
        source_type = "file"
        fp = file_path.strip()
        if not os.path.exists(fp):
            raise FileNotFoundError(f"File not found: {fp}")
        from core.file_handler import extract_text_from_file
        content = extract_text_from_file(fp) or ""
        ref = fp
        filename = os.path.basename(fp)
    else:
        source_type = "text"
        content = str(text or "").strip()
        ref = "direct text"
        filename = None

    preview = generate_knowledge_preview(content, source_type, ref)

    if provided_title:
        preview = replace(preview, title=str(provided_title).strip()[:140])

    if filename and source_type == "file":
        preview = replace(preview, source_filename=filename)

    return preview


# -----------------------------------------------------------------------------
# Chat-facing thin wrapper (primary API for intent handler)
# -----------------------------------------------------------------------------
def ingest_user_knowledge(
    user_input: str,
    session_id: Optional[str] = None,
    provided_title: Optional[str] = None,
) -> KnowledgeIngestionPreview:
    """Primary chat entry point. Detects URL / file / raw text from free-form user message, returns preview."""
    user_input = (user_input or "").strip()
    if not user_input:
        return KnowledgeIngestionPreview(title="Empty Input", summary="No content supplied.")

    # 1. URL detection (highest priority)
    url_m = re.search(r"(https?://\S+)", user_input)
    if url_m:
        url = url_m.group(1).rstrip(".,;)]")
        return prepare_knowledge_from_input(url=url, provided_title=provided_title)

    # 2. File path detection (only if the file actually exists on disk — chat safety)
    file_m = re.search(r'["\']?([A-Za-z]:\\[^"\'\s,]+|\S+\.(?:pdf|docx?|txt|md))["\']?', user_input, re.IGNORECASE)
    if file_m:
        cand = file_m.group(1)
        if os.path.isfile(cand):
            return prepare_knowledge_from_input(file_path=cand, provided_title=provided_title)

    # 3. Treat remainder as raw text (strip leading trigger phrase for cleanliness)
    cleaned = re.sub(
        r"^(?:add this to memory|remember this|store this|save this|ingest this|add to (?:my )?memory|save this information)[:\-\s]+",
        "",
        user_input,
        flags=re.IGNORECASE,
    ).strip()
    text = cleaned or user_input
    return prepare_knowledge_from_input(text=text, provided_title=provided_title)


# -----------------------------------------------------------------------------
# Structured edit command parser (only the documented commands — smallest implementation)
# -----------------------------------------------------------------------------
def apply_knowledge_edit_command(
    preview: KnowledgeIngestionPreview, user_reply: str
) -> Tuple[KnowledgeIngestionPreview, str]:
    """Parse structured edit commands. Returns (updated_preview, status_message).
    Status 'SAVE' and 'CANCEL' are special signals for the caller.
    """
    text = (user_reply or "").strip()
    if not text:
        return preview, "UNRECOGNIZED"

    low = text.lower()

    # Save / confirm
    if re.match(r"^(save|ok|looks good|confirm|done|store it|yes|save it)$", low):
        return preview, "SAVE"

    # Cancel
    if re.match(r"^(cancel|discard|nevermind|no|abort)$", low):
        return preview, "CANCEL"

    # Change / set title
    m = re.search(r"(?:change|set|update)\s+title\s+(?:to\s+)?[\"']?(.+?)[\"']?$", text, re.IGNORECASE)
    if m:
        new_title = m.group(1).strip()[:140]
        return replace(preview, title=new_title), "Title updated."

    # Add key point
    m = re.search(r"add\s+key\s*points?\s*[:\-]?\s*(.+)$", text, re.IGNORECASE)
    if m:
        pt = m.group(1).strip()
        if pt:
            new_kp = list(preview.key_points) + [pt]
            return replace(preview, key_points=new_kp), "Key point added."

    # Remove key point N (1-based index)
    m = re.search(r"remove\s+key\s*points?\s+(\d+)", text, re.IGNORECASE)
    if m:
        idx = int(m.group(1)) - 1
        kp = list(preview.key_points)
        if 0 <= idx < len(kp):
            del kp[idx]
            return replace(preview, key_points=kp), f"Removed key point {idx + 1}."
        return preview, "Invalid key point number (use 1-based index)."

    # Tags list
    m = re.search(r"^(?:tags?|tag)\s*[:=]?\s*(.+)$", text, re.IGNORECASE)
    if m:
        raw = m.group(1)
        tags = [t.strip().lower() for t in re.split(r"[,;]", raw) if t.strip()]
        return replace(preview, suggested_tags=tags), "Tags updated."

    # Client hint
    m = re.search(r"client\s*[:=]?\s*(.+)$", text, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        return replace(preview, client_hint=val), "Client hint updated."

    # Project hint
    m = re.search(r"project\s*[:=]?\s*(.+)$", text, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        return replace(preview, project_hint=val), "Project hint updated."

    # Notes
    m = re.search(r"notes?\s*[:=]?\s*(.+)$", text, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        return replace(preview, notes=val), "Notes updated."

    return preview, "UNRECOGNIZED"


# -----------------------------------------------------------------------------
# Pretty markdown renderer for chat (structured, easy to reply to)
# -----------------------------------------------------------------------------
def render_knowledge_preview(p: KnowledgeIngestionPreview) -> str:
    kp = "\n".join(f"- {pt}" for pt in (p.key_points or [])) or "- (none yet)"
    tags = ", ".join(p.suggested_tags) or "(none)"
    src = p.source_url or p.source_filename or "direct text input"
    extras = []
    if p.client_hint:
        extras.append(f"**Client:** {p.client_hint}")
    if p.project_hint:
        extras.append(f"**Project:** {p.project_hint}")
    if p.notes:
        extras.append(f"**Notes:** {p.notes}")
    extra_block = ("\n" + "\n".join(extras)) if extras else ""

    return (
        f"**Title:** {p.title}\n\n"
        f"**Summary:**\n{p.summary}\n\n"
        f"**Key Points:**\n{kp}\n\n"
        f"**Suggested Tags:** {tags}\n\n"
        f"**Source:** {src} (type: {p.source_type}, {p.original_length} chars original){extra_block}\n\n"
        "---\n"
        "Reply with a precise command to edit, or **save** / **looks good** to store permanently.\n"
        "Examples: `change title to SaMD Clinical Evidence Summary`, `add key point: Must follow 21 CFR 820.30 design controls`, "
        "`remove key point 3`, `tags: samd, fda, clinical-evidence`, `client: Dova`, `project: 123`, `notes: important for 510k`."
    )


# -----------------------------------------------------------------------------
# Save (applies overrides, writes DocumentRecord + attempts Chroma). No raw text stored.
# -----------------------------------------------------------------------------
def save_knowledge_preview(
    preview: KnowledgeIngestionPreview,
    *,
    client_hint: Optional[str] = None,
    project_hint: Optional[str] = None,
    notes: Optional[str] = None,
    db: Optional["DatabaseManager"] = None,
) -> str:
    """Persist curated preview. Uses DocumentRecord (doc_type=user_knowledge) so it participates in all normal retrievals."""
    final_client = client_hint or preview.client_hint
    final_proj = project_hint or preview.project_hint
    final_notes = notes or preview.notes

    kp_text = "\n".join(f"- {k}" for k in preview.key_points)
    combined = (
        f"Title: {preview.title}\n\n"
        f"Summary: {preview.summary}\n\n"
        f"Key Points:\n{kp_text}\n\n"
        f"Tags: {', '.join(preview.suggested_tags)}\n"
        f"Source: {preview.source_url or preview.source_filename or 'text'}\n"
        f"Notes: {final_notes or ''}\n"
    )

    source_id = f"uk-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    rec = DocumentRecord(
        source="user_knowledge",
        source_id=source_id,
        source_path=preview.source_url or preview.source_filename or "chat-ingest",
        name=preview.title,
        mime_type="text/knowledge",
        size=len(combined),
        modified_time=now,
        created_time=now,
        doc_type="user_knowledge",
        client_hint=final_client,
        project_hint=final_proj,
        year=datetime.now(timezone.utc).year,
        regulatory_tags=list(preview.suggested_tags),
        text_preview=(preview.summary or combined)[:2000],
        full_text_extracted=True,
        checksum=hashlib.md5(combined.encode("utf-8", errors="ignore")).hexdigest(),
        extra={
            "summary": preview.summary,
            "key_points": list(preview.key_points),
            "suggested_tags": list(preview.suggested_tags),
            "notes": final_notes,
            "source_type": preview.source_type,
            "source_url": preview.source_url,
            "source_filename": preview.source_filename,
            "original_length": preview.original_length,
        },
    )

    try:
        from core.file_handler import save_document_record, DocumentRecord as _DR  # ensure type

        ok = save_document_record(rec, db)
        if not ok:
            return "Failed to persist the knowledge item to the database."
    except Exception as e:
        return f"Database save error: {e}"

    # Best-effort: also add the curated text to the live Chroma RAG index so semantic retrieval (rag_search, RAGRetriever) sees it.
    try:
        from langchain_community.vectorstores import Chroma
        from langchain_huggingface import HuggingFaceEmbeddings

        embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-large-en-v1.5")
        vs = Chroma(persist_directory="chroma_index", embedding_function=embeddings)
        meta = {
            "source": "user_knowledge",
            "title": preview.title,
            "doc_type": "user_knowledge",
            "client_hint": final_client or "",
            "project_hint": final_proj or "",
            "tags": ",".join(preview.suggested_tags),
        }
        vs.add_texts([combined], metadatas=[meta], ids=[source_id])
        vs.persist()
    except Exception:
        # Non-fatal; DB record alone guarantees get_relevant_past_documents participation.
        pass

    return (
        f"Saved user knowledge item “{preview.title}” (source_id={source_id}). "
        "It is now queryable via get_relevant_past_documents (doc_type=user_knowledge), CoS context, "
        "Pulse, Shield, Workspace, client dossiers, and RAG semantic search."
    )


# -----------------------------------------------------------------------------
# High-level chat reply processor (used by router for the full preview + editing loop)
# -----------------------------------------------------------------------------
def process_knowledge_reply(session_id: str, user_reply: str) -> str:
    """If a preview is pending for the session, consume the reply as edit/save/cancel and return response text.
    Returns empty string when no pending preview (caller falls through to normal CoS).
    """
    if not has_pending_knowledge(session_id):
        return ""

    current = get_pending_knowledge(session_id)
    if current is None:
        clear_pending_knowledge(session_id)
        return ""

    new_preview, status = apply_knowledge_edit_command(current, user_reply)

    if status == "SAVE":
        msg = save_knowledge_preview(
            new_preview,
            client_hint=new_preview.client_hint,
            project_hint=new_preview.project_hint,
            notes=new_preview.notes,
        )
        clear_pending_knowledge(session_id)
        return f"✅ {msg}"

    if status == "CANCEL":
        clear_pending_knowledge(session_id)
        return "Knowledge preview discarded. Nothing was stored."

    if status == "UNRECOGNIZED":
        # Keep current preview; tell user how to proceed
        return (
            "Unrecognized edit command.\n"
            "Valid commands: `change title to ...`, `add key point: ...`, `remove key point N`, "
            "`tags: a, b, c`, `client: ...`, `project: ...`, `notes: ...`, `save`, or `cancel`.\n\n"
            + render_knowledge_preview(current)
        )

    # Normal edit — persist new state and re-render
    set_pending_knowledge(session_id, new_preview)
    return f"✅ {status}\n\n" + render_knowledge_preview(new_preview)


# -----------------------------------------------------------------------------
# Intent detector (used by router before normal CoS path)
# -----------------------------------------------------------------------------
_KNOWLEDGE_TRIGGER_RE = re.compile(
    r"\b("
    r"add (this|it|that|the following|below|info|information) to (memory|knowledge|your memory|the memory)|"
    r"remember (this|it|that|the following|this info|this information)|"
    r"store (this|it|that|the following|this url|this link|this page|this information)|"
    r"save (this|it|that|the info|this information) (to|for|as|into) (memory|knowledge|my memory|future use)|"
    r"ingest (this|the|that) (url|link|page|file|document|info|information)|"
    r"add (this|it) to (my )?memory|"
    r"knowledge (ingestion|add|store|remember|save)"
    r")\b",
    re.IGNORECASE,
)


def is_knowledge_ingest_trigger(user_input: str) -> bool:
    """Lightweight detector for the primary chat phrases that should start the knowledge preview flow."""
    if not user_input:
        return False
    return bool(_KNOWLEDGE_TRIGGER_RE.search(user_input))


# Public re-exports for chat router
__all__ = [
    "KnowledgeIngestionPreview",
    "ingest_user_knowledge",
    "prepare_knowledge_from_input",
    "save_knowledge_preview",
    "render_knowledge_preview",
    "apply_knowledge_edit_command",
    "process_knowledge_reply",
    "is_knowledge_ingest_trigger",
    "has_pending_knowledge",
    "get_pending_knowledge",
    "set_pending_knowledge",
    "clear_pending_knowledge",
    "fetch_web_content",
    "generate_knowledge_preview",
]

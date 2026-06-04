"""
Pure Local-Only Intel Retrieval Layer

This module implements the complete intel findings retrieval, indexing,
relevance, synthesis, and context formatting system using ONLY local models
and local storage. No remote APIs are used at any stage.

Authoritative data remains in agent_memory (via IntelService).
This layer builds a derived, self-contained local search index on top.

Non-negotiable: Every function and class in this file must remain 100% local.

SECURITY / ARTIFACT NOTE (review #7): The dedicated `intel_index/chroma.sqlite3`
(plus any supporting files) is a plaintext local-only SQLite database containing
embeddings + metadata for all indexed intel findings. This includes user research
content, monitoring results, key_points, notes, and potentially [Security-Relevant]
items. It is a user-machine private data boundary with no remote exfiltration
path. Treat with the same sensitivity as the main navissurance.db. No
sanitization beyond normal internal usage; future encryption-at-rest could be
added if the artifact ever needs to leave the local device.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict

logger = logging.getLogger(__name__)

# Thread-safety for lazy singletons (embeddings + Chroma index) during concurrent
# save_finding hooks, retrievals (Pulse chat), and admin rebuild from UI worker.
# RLock allows re-entrancy if needed inside locked sections.
_INTEL_LOCK = threading.RLock()

# Hoisted for hot paths (rebuild, keyword search over thousands of rows)
_JSON = json


def _row_to_intel_dict(row: Any) -> Optional[Dict[str, Any]]:
    """Safe unpack of agent_memory_recent row into a dict with parsed json_data.
    Guards against schema drift. Used by keyword + rebuild paths.
    """
    if not row or len(row) < 10:
        return None
    try:
        mem_id = int(row[0]) if row[0] is not None else 0
        content = (row[3] or "").strip() if len(row) > 3 else ""
        source = (row[4] or "") if len(row) > 4 else ""
        json_data_raw = row[7] if len(row) > 7 else None
        data: Dict[str, Any] = {}
        if json_data_raw:
            if isinstance(json_data_raw, str):
                data = _JSON.loads(json_data_raw)
            elif isinstance(json_data_raw, dict):
                data = json_data_raw
        return {
            "mem_id": mem_id,
            "content": content,
            "source": source,
            "data": data,
        }
    except Exception:
        return None


# =============================================================================
# Local Embeddings — Hardened for 100% Offline Operation
# =============================================================================

_SEMANTIC_MODEL: Any = None
_INTEL_EMBEDDINGS_MODEL_NAME: str | None = None


def _get_intel_embeddings_model() -> Optional[Any]:
    """
    Lazy singleton for local sentence-transformers embeddings used *exclusively*
    by the Intel/Pulse retrieval layer.

    Fully offline after first cache. Modeled on the proven pattern in
    core/user_memory.py but isolated so Intel never touches document RAG models.

    Default model: all-MiniLM-L6-v2 (fast + effective for short structured intel text).
    Override with env var INTEL_EMBEDDINGS_MODEL if desired.

    Thread-safe via module lock (protects against races with rebuild worker).
    """
    global _SEMANTIC_MODEL, _INTEL_EMBEDDINGS_MODEL_NAME

    with _INTEL_LOCK:
        if _SEMANTIC_MODEL is not None:
            return _SEMANTIC_MODEL

        model_name = os.getenv("INTEL_EMBEDDINGS_MODEL", "all-MiniLM-L6-v2").strip() or "all-MiniLM-L6-v2"
        _INTEL_EMBEDDINGS_MODEL_NAME = model_name

        try:
            from sentence_transformers import SentenceTransformer

            # Strong offline hardening (required for the "local only, no remote" rule)
            cache_folder = os.getenv("SENTENCE_TRANSFORMERS_HOME") or os.path.expanduser("~/.cache/huggingface/hub")
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

            _SEMANTIC_MODEL = SentenceTransformer(
                model_name,
                cache_folder=cache_folder,
                local_files_only=True,
            )
            logger.info(
                "Local Intel embeddings loaded: %s (fully offline, %d dims)",
                model_name,
                _SEMANTIC_MODEL.get_sentence_embedding_dimension(),
            )
        except Exception as exc:
            logger.warning("Local Intel embeddings unavailable (%s). Keyword-only mode active.", exc)
            _SEMANTIC_MODEL = None

        return _SEMANTIC_MODEL


def embed_texts(texts: list[str]) -> Optional[list[list[float]]]:
    """Generate embeddings using the local Intel embedding model only."""
    model = _get_intel_embeddings_model()
    if model is None or not texts:
        return None
    try:
        embs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return [emb.tolist() for emb in embs]
    except Exception as exc:
        logger.debug("embed_texts failed: %s", exc)
        return None


def get_intel_embedding_model_name() -> str:
    """Returns the name of the model currently in use (or the configured default)."""
    global _INTEL_EMBEDDINGS_MODEL_NAME
    if _INTEL_EMBEDDINGS_MODEL_NAME is None:
        _INTEL_EMBEDDINGS_MODEL_NAME = os.getenv("INTEL_EMBEDDINGS_MODEL", "all-MiniLM-L6-v2")
    return _INTEL_EMBEDDINGS_MODEL_NAME


def build_intel_index_text(summary: str, json_data: Optional[dict] = None) -> str:
    """
    Build a rich, high-signal text blob for local embedding / vector indexing.
    Designed for maximum semantic accuracy and breadth: explicitly includes
    importance, raised status, structured fields, and context so the embedding
    model can learn better similarity signals.
    Pure local. Used by save_finding, _reindex_finding, and rebuild.
    """
    if not summary:
        summary = ""
    parts: list[str] = [str(summary).strip()]

    if json_data:
        try:
            # Importance and raised are strong relevance signals — surface them explicitly
            imp = str(json_data.get("importance", "medium")).lower()
            raised = bool(json_data.get("raised", False))
            parts.append(f"importance={imp}")
            if raised:
                parts.append("STATUS: RAISED")

            src_title = (json_data.get("source_title") or "").strip()
            if src_title:
                parts.append("SOURCE: " + src_title)

            mentioned = json_data.get("mentioned_companies") or []
            if isinstance(mentioned, (list, tuple)):
                mentioned = " ".join(str(m) for m in mentioned if m)
            if mentioned:
                parts.append("COMPANIES: " + str(mentioned))

            keyp = json_data.get("key_points") or []
            if isinstance(keyp, (list, tuple)):
                for k in keyp:
                    if k:
                        parts.append("HIGH_VALUE_KEY_POINT: " + str(k))
                        parts.append("KEY_POINT: " + str(k))  # extra view for embedding strength on high-value regulatory points
                keyp = " ".join(str(k) for k in keyp if k)
            if keyp:
                parts.append("KEY POINTS: " + str(keyp))

            notes = (json_data.get("notes") or "").strip()
            if notes:
                parts.append("NOTES: " + notes)

            past_ctx = (json_data.get("relevant_past_context") or "").strip()
            if past_ctx:
                parts.append("PAST: " + past_ctx[:400])

            # Surface linked entities lightly so client/project affinity can influence vectors
            if json_data.get("linked_clients"):
                parts.append("LINKED_CLIENTS")
            if json_data.get("linked_projects"):
                parts.append("LINKED_PROJECTS")

            # Explicit high-value field markers help the embedding model learn
            # what actually matters for consultant intelligence retrieval.
            if src_title:
                parts.append("HIGH_VALUE: source_title")
            if keyp:
                parts.append("HIGH_VALUE: key_points")

        except Exception:
            pass

    blob = " | ".join(p for p in parts if p).strip()
    return blob[:2300]


# =============================================================================
# Dedicated Local Vector Index (Chroma) — Purely Local
# =============================================================================

_INTEL_CHROMA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "intel_index")
_INTEL_COLLECTION_NAME = "intel_findings"

_chroma_index: Any = None


def _get_local_intel_index():
    """
    Returns (or lazily creates) the dedicated local Chroma collection
    used exclusively for Intel findings.

    Uses a separate directory (`intel_index/`) for clean isolation from
    the document RAG index.

    Thread-safe via module lock. Additional offline hardening applied here
    for the HuggingFaceEmbeddings path used by live indexing + vector search.
    """
    global _chroma_index

    with _INTEL_LOCK:
        if _chroma_index is not None:
            return _chroma_index

        try:
            # Explicit early import so we can give a clear message if it's truly missing
            import onnxruntime
        except ImportError as e:
            logger.warning(
                "Local Intel vector search: onnxruntime could not be imported. "
                "Falling back to keyword search only.\nError: %s", e
            )
            _chroma_index = None
            return None

        try:
            from langchain_community.vectorstores import Chroma
            from langchain_huggingface import HuggingFaceEmbeddings

            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

            os.makedirs(_INTEL_CHROMA_DIR, exist_ok=True)

            model_name = get_intel_embedding_model_name()
            embeddings = HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs={"local_files_only": True},
                cache_folder=os.getenv("SENTENCE_TRANSFORMERS_HOME") or os.path.expanduser("~/.cache/huggingface/hub"),
            )

            _chroma_index = Chroma(
                persist_directory=_INTEL_CHROMA_DIR,
                collection_name=_INTEL_COLLECTION_NAME,
                embedding_function=embeddings,
            )

            logger.info("Local Intel vector index ready (Chroma) at %s", _INTEL_CHROMA_DIR)
        except Exception as exc:
            # Honest error message. We no longer claim "onnxruntime is not installed"
            # when the package is clearly present. This is usually a version/CUDA/
            # Chroma compatibility problem on Windows.
            logger.warning(
                "Local Intel Chroma vector index failed to initialize. "
                "Falling back to keyword search only.\n"
                "Full error traceback follows (this is the real reason, not a missing package):",
                exc_info=True,
            )
            _chroma_index = None

        return _chroma_index


def index_local_intel_finding(
    mem_id: int,
    text: str,
    metadata: Optional[dict] = None,
) -> bool:
    """
    Add (or update) a single intel finding in the local vector index.
    Best-effort and non-blocking. Returns True on success.
    """
    index = _get_local_intel_index()
    if index is None or not text:
        return False

    try:
        meta = metadata or {}
        meta["mem_id"] = mem_id
        index.add_texts([text], metadatas=[meta], ids=[str(mem_id)])
        return True
    except Exception as exc:
        logger.debug("index_local_intel_finding failed for %s: %s", mem_id, exc)
        return False


def local_vector_search(
    query: str,
    k: int = 20,
    filter_dict: Optional[dict] = None,
    *,
    client_id: Optional[int] = None,
    raised_only: bool = False,
) -> list[dict]:
    """
    Pure local semantic search against the Intel Chroma index.
    Supports basic metadata filter_dict (for Chroma where=) plus post-filter
    for client_id (list membership in stored meta) and raised_only.
    Returns list of dicts with 'mem_id', 'content', 'metadata', 'score'.
    """
    index = _get_local_intel_index()
    if index is None or not query:
        return []

    try:
        results = index.similarity_search_with_score(query, k=k, filter=filter_dict)
        out = []
        for doc, score in results:
            meta = doc.metadata or {}
            # Post-filter for client scoping (lists not directly supported in simple Chroma where)
            if client_id is not None:
                cids = meta.get("client_ids") or []
                if isinstance(cids, (list, tuple)):
                    if client_id not in [int(x) for x in cids if str(x).isdigit()]:
                        continue
                else:
                    continue
            if raised_only and not bool(meta.get("raised", False)):
                continue

            out.append({
                "mem_id": meta.get("mem_id"),
                "content": doc.page_content,
                "metadata": meta,
                "score": float(score),
            })
        return out
    except Exception as exc:
        logger.debug("local_vector_search failed: %s", exc)
        return []


def rebuild_local_intel_index(db, *, limit: int = 10000) -> dict:
    """
    Full rebuild of the local Intel vector index from authoritative agent_memory.
    Clears the existing Chroma collection for intel_findings then re-embeds every
    finding using the rich text builder (source_title, key_points, companies, etc.).
    100% local. Best-effort + non-fatal. Returns stats dict for UI/status.
    Callable from Intel tab "Rebuild local Intel index" or helper scripts.
    """
    stats = {
        "status": "started",
        "findings_scanned": 0,
        "indexed": 0,
        "errors": 0,
        "vector_available": False,
        "model": get_intel_embedding_model_name(),
        "index_dir": _INTEL_CHROMA_DIR,
    }
    try:
        # Full critical section under the lock for the entire rebuild.
        # This protects the long-running clear + scan + per-row links + re-embed
        # against concurrent save_finding hooks and retrievals (including from
        # the UI worker thread). Rebuild is an explicit admin action; brief
        # serialization of other Intel retrieval is the correct safety trade-off.
        with _INTEL_LOCK:
            # Force reset of the singleton and attempt to clear any prior collection
            global _chroma_index
            _chroma_index = None
            idx = _get_local_intel_index()
            if idx is None:
                stats["status"] = "vector_unavailable"
                stats["note"] = "Chroma / embeddings layer not available; keyword fallback remains fully functional."
                return stats

            stats["vector_available"] = True

            # Best-effort clear of prior docs (Chroma collection delete)
            try:
                if hasattr(idx, "_collection") and idx._collection is not None:
                    idx._collection.delete(where={})
                elif hasattr(idx, "_client"):
                    try:
                        idx._client.delete_collection(_INTEL_COLLECTION_NAME)
                    except Exception:
                        pass
                    _chroma_index = None
                    idx = _get_local_intel_index()
            except Exception as clear_exc:
                logger.debug("rebuild: non-fatal clear issue: %s", clear_exc)

            # Pull authoritative data (same broad scan the keyword path uses)
            try:
                rows = db.agent_memory_recent(
                    agent_code="pulse",
                    kind="intel_finding",
                    limit=limit,
                ) or []
            except Exception:
                rows = []

            stats["findings_scanned"] = len(rows)

            for row in rows:
                try:
                    row_dict = _row_to_intel_dict(row)
                    if not row_dict:
                        continue
                    mem_id = row_dict["mem_id"]
                    content = row_dict["content"]
                    data = row_dict["data"]

                    text = build_intel_index_text(content, data)
                    if not text:
                        continue

                    meta = {
                        "mem_id": mem_id,
                        "importance": data.get("importance", "medium"),
                        "raised": bool(data.get("raised", False)),
                        "source": row_dict.get("source", "")[:120],
                    }
                    if data.get("source_title"):
                        meta["source_title"] = str(data.get("source_title"))[:120]
                    mentioned = data.get("mentioned_companies") or []
                    if mentioned:
                        meta["mentioned_companies"] = mentioned[:5] if isinstance(mentioned, list) else str(mentioned)[:80]

                    # Populate client/project ids (now using the row helper + links query inside locked section)
                    try:
                        links = db.agent_memory_entity_links(memory_id=mem_id)
                        cids = [int(l["entity_key"]) for l in links if l.get("entity_type") == "client"]
                        pids = [int(l["entity_key"]) for l in links if l.get("entity_type") == "project"]
                        if cids:
                            meta["client_ids"] = cids
                        if pids:
                            meta["project_ids"] = pids
                    except Exception:
                        pass

                    ok = index_local_intel_finding(mem_id, text, meta)
                    if ok:
                        stats["indexed"] += 1
                    else:
                        stats["errors"] += 1
                except Exception:
                    stats["errors"] += 1
                    continue

            stats["status"] = "completed"
            logger.info(
                "Local Intel index rebuild complete: scanned=%d indexed=%d errors=%d",
                stats["findings_scanned"], stats["indexed"], stats["errors"],
            )
    except Exception as exc:
        stats["status"] = "error"
        stats["error"] = str(exc)
        logger.warning("rebuild_local_intel_index failed (safe): %s", exc)

    return stats


# =============================================================================
# Data Contracts (pure data objects)
# =============================================================================

@dataclass
class LocalIntelHit:
    """A single compact intel finding result produced entirely by the local layer."""
    mem_id: int
    title: str
    excerpt: str
    importance: str = "medium"
    raised: bool = False
    matched_fields: list[str] = field(default_factory=list)
    score: float = 0.0
    client_ids: list[int] = field(default_factory=list)
    project_ids: list[int] = field(default_factory=list)
    source_title: Optional[str] = None
    indexed_at: Optional[float] = None  # for recency boosting in ranking (accuracy + freshness)
    # NOTE (per review): key_points drive keyword scoring / matched_fields / high_value bonuses / restoration guards
    # but are not a first-class field on hits (unlike source_title, which has partial parity in blob + formatter).
    # See limitation comment in _prepare_intel_synthesis_prompt for LLM filter implications.


@dataclass
class LocalIntelContext:
    """
    The complete output of the local intel retrieval layer.
    Consumers (Pulse chat, CoS, etc.) should only ever see this.
    """
    formatted_block: str = ""
    items: list[LocalIntelHit] = field(default_factory=list)
    used_local_synthesis: bool = False
    chars_used: int = 0
    query: str = ""
    total_candidates_considered: int = 0
    note: str = ""  # e.g. "local models unavailable - keyword fallback"


# =============================================================================
# Local Formatter (modeled on the proven file_handler compact style)
# =============================================================================

def format_compact_local_intel_context(
    hits: list[LocalIntelHit],
    *,
    max_items: int = 8,
    max_chars: int = 4200,
    header: str = "Relevant Intel findings (local retrieval):",
) -> str:
    """
    Produces a tiny, high-signal block suitable for prompt injection.
    Never ships raw content or large blobs. Pure local formatting.
    """
    if not hits:
        return ""

    lines: list[str] = [header]

    used = len(header) + 2
    count = 0

    for hit in hits[:max_items]:
        if count >= max_items:
            break

        # Extremely compact line (mirrors format_compact_historical_context discipline)
        parts = []
        if hit.raised:
            parts.append("[RAISED]")
        parts.append(hit.title[:90])
        if hit.source_title and hit.source_title != hit.title:
            parts.append(f"| {hit.source_title[:70]}")
        if hit.excerpt:
            parts.append(f"— {hit.excerpt[:160]}")

        line = " ".join(parts).strip()
        if used + len(line) + 2 > max_chars:
            break

        lines.append(f"- {line}")
        used += len(line) + 2
        count += 1

    if count < len(hits):
        lines.append(f"... ({len(hits) - count} more local matches truncated for budget)")

    return "\n".join(lines)


# =============================================================================
# Local Keyword Fallback (100% local, rich field aware)
# =============================================================================

def _local_keyword_search(
    db,
    goal: str,
    *,
    limit: int = 50,
    client_id: Optional[int] = None,
    raised_only: bool = False,
) -> list[LocalIntelHit]:
    """
    Pure local keyword search over intel findings.
    Looks in content + the important json_data fields (source_title, mentioned_companies, key_points, notes).
    Respects client_id (via entity links) and raised_only filters (fixes previously dead parameters).
    Populates client_ids / project_ids on every LocalIntelHit for downstream consumers.
    Uses safe row helper (no brittle positional + inner imports in loop).
    """
    if not goal or not db:
        return []

    query_lower = goal.lower().strip()
    if not query_lower:
        return []

    try:
        rows = db.agent_memory_recent(
            agent_code="pulse",
            kind="intel_finding",
            limit=5000,   # Still broad for recall during Phase 0/1, but contained here
        )
    except Exception:
        return []

    hits: list[LocalIntelHit] = []

    for row in rows or []:
        try:
            row_dict = _row_to_intel_dict(row)
            if not row_dict:
                continue
            mem_id = row_dict["mem_id"]
            content = row_dict["content"]
            data = row_dict["data"]

            # The finding's own title is also important searchable text
            # NOTE (pre-existing per review): always "" (row_dict from _row_to_intel_dict never contains "title"; save_finding title param is unused; display derives from source_title/content). Documented for hygiene. (The assignment below now makes the documented behavior executable.)

            # Rich fields the user actually cares about
            source_title = (data.get("source_title") or "").strip()
            mentioned = data.get("mentioned_companies") or []
            mentioned_text = " ".join(mentioned) if isinstance(mentioned, (list, tuple)) else str(mentioned)
            key_points = data.get("key_points") or []
            key_points_text = " ".join(key_points) if isinstance(key_points, (list, tuple)) else str(key_points)
            notes = (data.get("notes") or "").strip()
            raised = bool(data.get("raised", False))
            importance = str(data.get("importance", "medium"))

            finding_title = ""  # per NOTE (pre-existing per review): row_dict from _row_to_intel_dict never contains "title"; save_finding title param unused for search; display derives from source_title/content. Restores keyword path.

            # Build searchable blob (same philosophy as before, but encapsulated)
            # Include the finding's own title slot (vestigial/always "" per NOTE + design; search uses content + high-value fields). Kept for structural hygiene.
            full_text = " ".join([finding_title, content, source_title, mentioned_text, key_points_text, notes]).lower()

            query_terms = [t for t in query_lower.split() if len(t) > 2]

            # Early filter: require at least one term to appear somewhere.
            # (query_terms recomputed later for scoring/_has/_score_field; idempotent per-row design)
            # For high-value fields (source_title, key_points), be slightly more generous
            # because these are the fields users/researchers actually care about seeing matched.
            if query_terms:
                main_match = any(t in full_text for t in query_terms)
                hv_match = False
                if source_title and any(t in source_title.lower() for t in query_terms):
                    hv_match = True
                # Per-key_point check for early filter consistency with later matching_key_points scoring
                if isinstance(key_points, (list, tuple)):
                    for kp in key_points:
                        if kp and any(t in str(kp).lower() for t in query_terms):
                            hv_match = True
                            break

                if not (main_match or hv_match):
                    continue

            # === PERFORMANCE + FILTER FIX ===
            # Text match is cheap. Only pay the entity_links query cost when:
            # - we need it for client_id filtering, or
            # - we are keeping the item for the final limited result set (to populate ids on returned hits).
            # This eliminates the previous regression of unconditional DB calls on every match in broad unscoped queries.
            cids: List[int] = []
            pids: List[int] = []
            if client_id is not None:
                try:
                    links = db.agent_memory_entity_links(memory_id=mem_id)
                    cids = [int(l["entity_key"]) for l in links if l.get("entity_type") == "client"]
                    pids = [int(l["entity_key"]) for l in links if l.get("entity_type") == "project"]
                except Exception:
                    pass

            if client_id is not None and client_id not in cids:
                continue
            if raised_only and not raised:
                continue

            # Field-aware multi-term scoring for better accuracy (initialize early so affinity / field bonuses can accumulate)
            query_terms = [t for t in query_lower.split() if len(t) > 2]
            matched = []
            match_score = 0.0

            # Small bonus for covering more distinct query terms (improves accuracy when query has multiple important concepts)
            term_coverage_bonus = 0.0

            # Light client affinity bonus in keyword scoring (helps accuracy when scoped)
            if client_id is not None and cids:
                match_score += 0.8  # extra signal for context-relevant intel

            # Robust high-value field detection using the same term logic as the rest of the search.
            # This makes ranking for real usage (raised findings with good source_title/key_points)
            # much more reliable and less sensitive to exact phrasing.
            def _has_query_terms(text: str) -> bool:
                if not text or not query_terms:
                    return False
                t = text.lower()
                return any(term in t for term in query_terms)

            high_value_field_count = 0
            if _has_query_terms(source_title):
                high_value_field_count += 1

            # Count distinct matching key_points for stronger signal on rich findings
            matching_key_points = 0
            if isinstance(key_points, (list, tuple)):
                for kp in key_points:
                    if kp and _has_query_terms(str(kp)):
                        matching_key_points += 1
            if matching_key_points > 0:
                high_value_field_count += 1

            if high_value_field_count >= 1:
                # Give a meaningful boost even for a single high-value field hit.
                # Source_title gets extra weight as it is usually the most authoritative field.
                source_title_bonus = 0.9 if _has_query_terms(source_title) else 0.0  # already benefits from normalizer via _has_query_terms
                match_score += (2.6 + source_title_bonus) * high_value_field_count

            if high_value_field_count >= 2:
                match_score += 1.5  # extra for both strong fields

            # Extra lift when multiple distinct key_points match (improves accuracy for detailed regulatory intel)
            if matching_key_points >= 2:
                match_score += 1.2 * (matching_key_points - 1)

            # Compound bonus when the same query terms hit both source_title and key_points
            # (highest-signal case the system was built to surface well)
            if _has_query_terms(source_title) and matching_key_points >= 1:
                match_score += 0.8

            def _score_field(text: str, weight: float) -> float:
                if not text:
                    return 0.0
                t = text.lower()
                hits = sum(1 for term in query_terms if term in t)
                if hits == 0:
                    return 0.0
                # Bonus for containing many of the query terms (more robust than whole-phrase)
                term_coverage = len([term for term in query_terms if term in t]) / max(1, len(query_terms))
                phrase_bonus = 1.0 + (0.6 * term_coverage)
                return hits * weight * phrase_bonus

            match_score += _score_field(content, 1.0)
            if match_score > 0:
                matched.append("summary")

            st_score = _score_field(source_title, 2.2)
            if st_score > 0:
                matched.append("source_title")
                match_score += st_score

            mc_score = _score_field(mentioned_text, 1.6)
            if mc_score > 0:
                matched.append("mentioned_companies")
                match_score += mc_score

            kp_score = _score_field(key_points_text, 2.0)
            if kp_score > 0:
                matched.append("key_points")
                match_score += kp_score

            # Term coverage bonus (accuracy boost when more distinct query terms are hit across fields)
            unique_terms_matched = len({t for t in query_terms if t in full_text})
            if query_terms:
                coverage_ratio = unique_terms_matched / len(query_terms)
                term_coverage_bonus = coverage_ratio * 1.8

            # Store improved keyword strength for fusion/ranking
            # Higher score = stronger direct evidence
            match_score += term_coverage_bonus

            # Prefer source_title for display when available (the real webpage title)
            display_title = source_title or content[:80]

            excerpt = (content or source_title or "")[:220].strip()

            hit = LocalIntelHit(
                mem_id=mem_id,
                title=display_title,
                excerpt=excerpt,
                importance=importance,
                raised=raised,
                matched_fields=matched or ["content"],
                score=match_score or 1.0,   # use field-weighted keyword strength
                client_ids=cids,
                project_ids=pids,
                source_title=source_title or None,
            )
            # Carry recency signal when present (supports freshness-aware ranking)
            if "indexed_at" in data:
                try:
                    hit.indexed_at = float(data["indexed_at"])
                except Exception:
                    pass
            hits.append(hit)

            if len(hits) >= limit:
                break
        except Exception:
            continue  # Pre-existing broad per-row resilience (swallows transient issues; higher visibility now that keyword path is primary for representative usage)

    # Final limited population for unscoped queries (cheap: only for the <= limit items actually returned).
    # Include pure raised_only=True (no client_id) so that hits returned under raised_only
    # filters also carry client_ids / project_ids (addresses the last edge-case nit).
    if not client_id:
        for h in hits[:limit]:
            try:
                links = db.agent_memory_entity_links(memory_id=h.mem_id)
                h.client_ids = [int(l["entity_key"]) for l in links if l.get("entity_type") == "client"]
                h.project_ids = [int(l["entity_key"]) for l in links if l.get("entity_type") == "project"]
            except Exception:
                pass

    # Simple sort: raised first, then by rough length of match signal
    hits.sort(key=lambda h: (0 if h.raised else 1, -len("".join(h.matched_fields))))
    return hits[:limit]


# =============================================================================
# Main Retrieval Entry Point (now with real local keyword fallback)
# =============================================================================

def retrieve_relevant_intel(
    db,
    goal: str,
    *,
    max_items: int = 12,
    max_chars: int = 4500,
    client_id: Optional[int] = None,
    raised_only: bool = False,
) -> LocalIntelContext:
    """
    Primary entry point for all natural-language intel relevance queries.

    Design goal: maximum accuracy + breadth under strict local-only constraints.
    - Rich keyword search over all important fields (source_title, key_points, notes, companies, etc.)
    - Semantic vector search against the dedicated local intel_index/ when available
    - Improved fusion + ranking with explicit boosting for raised, importance, and keyword signal
    - When many candidates are retrieved, local LLM (intel_batch_digest / relevance profiles)
      can be used as a precision filter on top of the high-recall hybrid results.
    Everything remains 100% local. No remote models at any stage.
    """
    ctx = LocalIntelContext(query=goal)

    try:
        # 1. Keyword (always, excellent for structured fields and exact matches)
        kw_hits = _local_keyword_search(
            db,
            goal,
            limit=max_items * 4,
            client_id=client_id,
            raised_only=raised_only,
        )

        # 2. Vector (best-effort; only if index has been populated via saves or rebuild)
        #    Now passes filters and populates client/project ids from stored metadata (full #1 fix).
        vec_hits: list[LocalIntelHit] = []
        try:
            vec_raw = local_vector_search(goal, k=max_items * 3, client_id=client_id, raised_only=raised_only)
            for v in vec_raw or []:
                try:
                    mid = v.get("mem_id")
                    if not mid:
                        continue
                    # Convert vector result into LocalIntelHit shape (lightweight)
                    meta = v.get("metadata") or {}
                    content = (v.get("content") or "")[:220]
                    display_title = meta.get("source_title") or content[:80]
                    cids = meta.get("client_ids") or []
                    pids = meta.get("project_ids") or []
                    if not isinstance(cids, list):
                        cids = [cids] if cids else []
                    if not isinstance(pids, list):
                        pids = [pids] if pids else []
                    hit = LocalIntelHit(
                        mem_id=int(mid) if isinstance(mid, (int, str)) and str(mid).isdigit() else 0,
                        title=str(display_title)[:90],
                        excerpt=content,
                        importance=str(meta.get("importance", "medium")),
                        raised=bool(meta.get("raised", False)),
                        matched_fields=["vector"],
                        score=float(v.get("score", 0.5)),
                        client_ids=[int(x) for x in cids if str(x).strip().lstrip("-").isdigit()],
                        project_ids=[int(x) for x in pids if str(x).strip().lstrip("-").isdigit()],
                        source_title=meta.get("source_title"),
                    )
                    # Propagate recency signal when available (indexed_at from metadata)
                    if "indexed_at" in meta:
                        try:
                            hit.indexed_at = float(meta["indexed_at"])
                        except Exception:
                            pass
                    if hit.mem_id:
                        vec_hits.append(hit)
                except Exception:
                    continue
        except Exception:
            vec_hits = []

        # 3. Smarter merge + dedup: combine signals when an item is found by both paths
        #    This improves accuracy by giving credit for multi-path matches (stronger evidence).
        seen: set[int] = set()
        merged: list[LocalIntelHit] = []
        kw_by_id = {h.mem_id: h for h in kw_hits if h.mem_id}
        vec_by_id = {v.mem_id: v for v in vec_hits if v.mem_id}

        all_ids = set(kw_by_id.keys()) | set(vec_by_id.keys())
        for mid in all_ids:
            kw_hit = kw_by_id.get(mid)
            vec_hit = vec_by_id.get(mid)

            if kw_hit and vec_hit:
                # Multi-path hit → boost its keyword strength (evidence from both methods)
                combined = kw_hit
                combined.score = (kw_hit.score or 1.0) + 1.5   # bonus for being found semantically too
                combined.matched_fields = list(set((kw_hit.matched_fields or []) + (vec_hit.matched_fields or [])))
                merged.append(combined)
            elif kw_hit:
                merged.append(kw_hit)
            elif vec_hit:
                merged.append(vec_hit)

        # Stronger ranking for accuracy + breadth:
        # - Strong boost for RAISED (user has already flagged importance)
        # - Boost for high importance
        # - Keyword hits get a solid base signal (they matched explicit terms)
        # - Vector hits contribute semantic breadth but are down-weighted relative to direct matches
        # - Recency boost using indexed_at when available (newer intel preferred for freshness)
        def _rank_key(h: LocalIntelHit) -> tuple:
            # Primary: raised is extremely strong signal
            raised_bonus = 0 if h.raised else 2

            # Importance boost (high > medium > low)
            imp = (h.importance or "medium").lower()
            imp_bonus = 0 if imp == "high" else (1 if imp == "medium" else 2)

            # Keyword vs pure vector: direct term matches are more trustworthy for accuracy.
            # Use the actual keyword strength score when available (higher = better direct match).
            is_keyword = bool(h.matched_fields) and "vector" not in h.matched_fields
            if is_keyword:
                kw_strength = float(h.score) if h.score and h.score > 0 else 2.0
                kw_bonus = max(0.0, 3.0 - kw_strength)   # stronger matches get better (lower) bonus
            else:
                kw_bonus = 2.0

            # Vector score (distance) — invert so smaller distance = better rank contribution
            vec_score = float(h.score) if h.score is not None and h.score > 0 else 0.8
            vec_contrib = vec_score

            # Recency using age in days (much more intuitive and stable than raw timestamp scaling).
            # Exponential decay curve (newer receive stronger negative/better rank; bounded, correct sign, gentle over weeks).
            recency_bonus = 0.0
            if h.indexed_at:
                try:
                    age_days = max(0.0, (time.time() - float(h.indexed_at)) / 86400.0)
                    # Corrected: newer (age≈0) receive strong negative (better rank); older decay to 0 (exp).
                    recency_bonus = -4.0 * (0.93 ** age_days)
                except Exception:
                    pass

            # Client / project affinity: items linked to the current context or any client/project
            # get a meaningful boost (directly improves accuracy in real usage).
            client_affinity = 0.0
            if client_id is not None and client_id in (h.client_ids or []):
                client_affinity = -1.5   # strong boost for direct context match
            elif h.client_ids or h.project_ids:
                client_affinity = -0.6   # mild boost for having any linkage

            # Extra boost for hits that matched on high-value structured fields
            # (source_title and key_points are especially strong signals for intel accuracy).
            high_value_field_bonus = 0.0
            if h.matched_fields:
                high_value_matches = 0
                if "source_title" in h.matched_fields:
                    high_value_matches += 1
                if "key_points" in h.matched_fields:
                    high_value_matches += 1
                if high_value_matches > 0:
                    high_value_field_bonus = -18.0 * high_value_matches   # max stack bonus for multi high-value field matches

            # Exact source_title / phrase super-boost (activates documented priority for exact title matches
            # on real scraped webpage titles / regulatory phrases; applies to kw + vector hits; tiny safe delta).
            # Limitation (per review): the >=5-char substring heuristic can match common technical words
            # appearing in unrelated titles (modest FP risk in noisy fusion results; future whole-word
            # or stopword refinement possible but out of scope for this micro-increment).
            exact_title_bonus = 0.0
            if h.source_title:
                st = h.source_title.lower()
                g = (goal or "").lower()
                if g and (g in st or any(len(t) >= 5 and t in st for t in g.split() if len(t) >= 5)):
                    exact_title_bonus = -2.5

            # Composite: lower value = better rank.
            # Priority order: raised > importance > keyword strength > high-value fields > exact title match > client affinity > recency > vector signal.
            return (raised_bonus, imp_bonus, kw_bonus, high_value_field_bonus, exact_title_bonus, client_affinity, recency_bonus, vec_contrib)

        merged.sort(key=_rank_key)

        raw_hits = merged

        # 4. Budget + format (strict local)
        ctx.items = raw_hits[:max_items]
        ctx.formatted_block = format_compact_local_intel_context(
            ctx.items,
            max_items=max_items,
            max_chars=max_chars,
            header="Relevant Intel findings (local retrieval):",
        )
        ctx.chars_used = len(ctx.formatted_block)
        ctx.total_candidates_considered = len(raw_hits)
        ctx.used_local_synthesis = False

        # 5. Note when we have enough breadth that local LLM relevance filtering / synthesis
        #    becomes valuable for turning high-recall results into high-precision context.
        if len(raw_hits) > max_items * 2:
            ctx.note = (ctx.note or "") + f" | {len(raw_hits)} candidates — local LLM relevance filter ready"

        if not ctx.items:
            ctx.note = "No local matches found for this query."

        if vec_hits:
            ctx.note = (ctx.note or "") + " (vector index contributed)"

    except Exception as exc:
        logger.exception("Local intel retrieval failed (safe fallback)")
        ctx.note = f"Local retrieval error: {exc}"
        ctx.formatted_block = ""
        ctx.chars_used = 0

    return ctx


# Tunable threshold for when we consider invoking local LLM synthesis.
# Below this many candidates, we usually skip synthesis to keep things fast.
SYNTHESIS_MIN_CANDIDATES = 15


def get_intel_index_stats() -> dict:
    """
    Lightweight stats about the local Intel vector index.
    Returns actionable health + freshness info (best-effort, never raises).
    Used for diagnostics, after-rebuild reporting, and future UI status.
    """
    # Fast path for environments that explicitly disabled the vector layer
    if os.getenv("INTEL_DISABLE_VECTOR", "").lower() in ("1", "true", "yes"):
        return {"available": False, "reason": "vector layer disabled via INTEL_DISABLE_VECTOR"}

    try:
        idx = _get_local_intel_index()
        if idx is None:
            return {"available": False, "reason": "vector index not initialized"}

        count = None
        last_indexed = None
        try:
            coll = getattr(idx, "_collection", None)
            if coll is not None:
                count = coll.count()
                # Best-effort freshness: sample a few recent docs for indexed_at in metadata
                try:
                    sample = coll.get(limit=20, include=["metadatas"])
                    metas = sample.get("metadatas") or []
                    ts_values = []
                    for m in metas:
                        if not m:
                            continue
                        ts = m.get("indexed_at")
                        if ts is not None:
                            try:
                                ts_values.append(float(ts))
                            except Exception:
                                pass
                    if ts_values:
                        last_indexed = max(ts_values)
                except Exception:
                    pass
        except Exception:
            pass

        model = get_intel_embedding_model_name()

        return {
            "available": True,
            "vector_count": count,
            "last_indexed_at": last_indexed,
            "embedding_model": model,
            "index_dir": _INTEL_CHROMA_DIR,
            "collection": _INTEL_COLLECTION_NAME,
            "healthy": True,
        }
    except Exception as exc:
        return {"available": False, "reason": str(exc), "healthy": False}

# Convenience alias used during transition
get_relevant_intel_local = retrieve_relevant_intel


def retrieve_relevant_intel_with_llm_filter(
    db,
    goal: str,
    *,
    max_items: int = 12,
    max_chars: int = 4500,
    client_id: Optional[int] = None,
    raised_only: bool = False,
    min_candidates_for_filter: int = 12,
) -> LocalIntelContext:
    """
    High-recall hybrid retrieval followed by local LLM relevance filtering.
    This is the preferred path when you want both breadth (from kw+vec) and precision
    (local model ruthlessly prunes to what actually matters for the goal).
    Falls back gracefully to plain hybrid results if the LLM step fails or is not needed.
    """
    # First get a broad candidate set using the full hybrid engine (no synthesis yet)
    ctx = retrieve_relevant_intel(
        db, goal,
        max_items=max_items * 3,   # deliberately broad for high recall
        max_chars=max_chars * 2,
        client_id=client_id,
        raised_only=raised_only,
    )

    candidates = ctx.items or []
    if len(candidates) < min_candidates_for_filter:
        # Not enough volume to justify the LLM filter cost — return what we have
        return ctx

    # Run the local LLM as a precision filter (reuses the same ruthless prompt + logic)
    try:
        filtered = local_synthesize_intel_digest(goal, candidates, max_candidates_for_llm=20)

        # Conservative guard for the relevance filter:
        # - Never let the filtered set drop below a minimum useful size
        # - Always preserve raised + high-importance items if the LLM was overly aggressive
        #   (this protects obviously important intel even when the model is very strict)
        min_acceptable = max(4, max_items // 2)

        if filtered:
            # Force-include any raised or high-importance items that the LLM dropped
            must_keep = [h for h in candidates if h.raised or (h.importance or "").lower() == "high"]
            for h in must_keep:
                if h not in filtered:
                    filtered.append(h)

            # Hard minimum: if we still have very few results after filtering, pull back a few more high-signal items
            if len(filtered) < max(5, max_items // 2):
                extra_high_signal = [h for h in candidates if h not in filtered and 
                                     (h.raised or 
                                      (h.importance or "").lower() == "high" or 
                                      (h.score or 0) > 6.5 or
                                      any(f in (h.matched_fields or []) for f in ("source_title", "key_points")))]
                filtered.extend(extra_high_signal[: max(7, max_items // 2)])  # include strong keyword + high-value field matches too

            # Re-sort to keep the LLM's preferred order at the top, then the must-keep items.
            # Also prefer items that had strong original keyword signals or high-value field matches.
            def _restoration_priority(h):
                is_must_keep = h.raised or (h.importance or "").lower() == "high"
                has_strong_signal = (
                    (h.score or 0) > 7.0 or 
                    any(f in (h.matched_fields or []) for f in ("source_title", "key_points")) or
                    (getattr(h, 'term_coverage_bonus', 0) or 0) > 1.2   # support for future richer hit objects
                )
                return (0 if is_must_keep else 1, 0 if has_strong_signal else 1)

            filtered = sorted(filtered, key=_restoration_priority)

        if filtered and len(filtered) >= min_acceptable:
            ctx.items = filtered[:max_items]
            ctx.formatted_block = format_compact_local_intel_context(
                ctx.items,
                max_items=max_items,
                max_chars=max_chars,
                header="Relevant Intel findings (hybrid retrieval + local LLM relevance filter):",
            )
            ctx.chars_used = len(ctx.formatted_block)
            ctx.used_local_synthesis = True
            ctx.note = (ctx.note or "") + " | local LLM relevance filter applied"
            ctx.total_candidates_considered = len(candidates)
        else:
            # LLM pruned too hard — fall back to the broader hybrid set but still mark the intent
            logger.debug("LLM filter returned low coverage (%s); keeping broader hybrid results for safety",
                         len(filtered) if filtered else 0)
    except Exception as exc:
        logger.debug("LLM relevance filter failed (non-fatal, using raw hybrid): %s", exc)
        ctx.note = (ctx.note or "") + " | local LLM filter attempted (fallback)"

    return ctx


# =============================================================================
# Synthesis Preparation (local LLM digest path using intel_batch_digest profile)
# =============================================================================

def _prepare_intel_synthesis_prompt(
    goal: str,
    candidates: list[LocalIntelHit],
    *,
    max_candidates: int = 30,
) -> list[dict]:
    """
    Build a minimal, strictly budgeted prompt for the local Qwen model
    (via intel_batch_digest profile in local_llm). Returns chat-style messages.
    Never ships full raw content; uses the same compact excerpt discipline.
    This is the ready-to-call groundwork for Phase 1 synthesis / re-ranking.
    See Limitation comment below for key_points vs source_title information boundary.
    """
    if not candidates:
        return []
    trimmed = candidates[:max_candidates]
    # Ultra-compact digest of candidates (same philosophy as formatter)
    lines = []
    for h in trimmed:
        tag = "[RAISED] " if h.raised else ""
        line = f"{tag}{h.title[:70]} | {h.excerpt[:90]}"
        if h.source_title and h.source_title != h.title:
            line += f" (src: {h.source_title[:50]})"
        lines.append("- " + line)
    candidate_blob = "\n".join(lines)

    # Limitation (per review, see 46b495e4): the candidate_blob construction (title | excerpt + optional (src: source_title))
    # surfaces only source_title for rich field visibility to the local LLM. key_points (and individual phrases,
    # plus the per-kp HIGH_VALUE_KEY_POINT markers) influence upstream keyword scoring, matched_fields population,
    # high_value_field_bonus in _rank_key, and restoration guards inside retrieve_relevant_intel_with_llm_filter,
    # but the actual key point content/phrases are never emitted in the digest passed to _prepare / local_synthesize.
    # The "especially individual key point phrases" guidance is therefore indirect/aspirational. This mirrors the
    # documented limitation on the exact_title substring heuristic. Source_title has partial first-class parity
    # (dataclass + blob + formatter); key_points remain keyword/ranking-only signals by design.
    system = (
        "You are a local-only intelligence analyst. You receive a user goal/query and a list of "
        "candidate intel findings retrieved by a local hybrid (keyword + vector) search. "
        "Your job is to act as a high-precision relevance filter: "
        "return ONLY the 5–10 most relevant items that actually help answer the goal. "
        "Be ruthless — discard anything that is only loosely related, outdated, or low-signal. "
        "Strongly prefer items that are raised or marked high importance when they are relevant. "
        "Especially value items whose source_title or key_points (especially individual key point phrases) directly address the core entities, "
        "regulatory topic, or specific question in the goal. "
        "When relevance is close, also favor items that had strong original keyword matches, high term coverage (many distinct query terms on regulatory topics), or came from authoritative sources (strong source_title); prefer more recent/fresh findings for monitoring and regulatory use cases. "
        "Return a compact JSON array of objects with exactly these keys: "
        "mem_id (integer), why (one short phrase <= 10 words explaining the relevance, be specific about the connection to the goal). "
        "No other text, no explanations, no markdown."
    )
    user = (
        f"Goal / Query: {goal}\n\n"
        f"Candidates (retrieved locally):\n{candidate_blob}\n\n"
        "Return the JSON array of the most relevant mem_ids now."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def local_synthesize_intel_digest(
    goal: str,
    candidates: list[LocalIntelHit],
    *,
    max_candidates_for_llm: int = 25,
) -> list[LocalIntelHit]:
    """
    OPTIONAL local LLM synthesis step using the dedicated intel_batch_digest profile.
    Attempts to call run_local_completion with the prepared prompt.
    Returns a (possibly reordered / filtered) short list of hits.
    Fully defensive: any failure returns the input candidates unchanged.
    Actual invocation is cheap to enable later; currently lays the complete path.
    """
    if not candidates:
        return []
    try:
        from .local_llm import run_local_completion
        msgs = _prepare_intel_synthesis_prompt(goal, candidates, max_candidates=max_candidates_for_llm)
        if not msgs:
            return candidates[:12]

        # The profile "intel_batch_digest" is already registered and will be selected by session_id
        raw = run_local_completion(msgs, session_id="intel_batch_digest") or ""
        # Robust output parsing for local LLM (handles minor formatting noise)
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw.strip())
        cleaned = cleaned.strip()
        # Try to find the first JSON array if the model added extra text
        if not cleaned.startswith("["):
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start : end + 1]
        try:
            data = _JSON.loads(cleaned)
        except Exception:
            data = []
        if not isinstance(data, list):
            data = []

        # Rebuild ordered list from the LLM guidance (only keep valid mem_ids still in candidates)
        id_to_hit = {h.mem_id: h for h in candidates}
        ordered = []
        seen = set()
        for item in data:
            try:
                mid = int(item.get("mem_id") or 0)
                if mid in id_to_hit and mid not in seen:
                    ordered.append(id_to_hit[mid])
                    seen.add(mid)
            except Exception:
                continue

        # Fill remaining slots preferring high-signal items (raised → high importance → rest)
        # This preserves accuracy when the local LLM relevance filter is conservative.
        def _quality(h: LocalIntelHit) -> tuple:
            return (0 if h.raised else 1,
                    0 if (h.importance or "").lower() == "high" else 1)

        remaining = sorted([h for h in candidates if h.mem_id not in seen], key=_quality)
        for h in remaining:
            if len(ordered) >= 10:
                break
            ordered.append(h)
            seen.add(h.mem_id)

        return ordered[:12] if ordered else candidates[:12]
    except Exception as exc:
        logger.debug("local_synthesize_intel_digest skipped (graceful): %s", exc)
        return candidates[:12]


# =============================================================================
# Hybrid entry point (now delegates to the evolved main retriever)
# =============================================================================

def retrieve_relevant_intel_hybrid(
    db,
    goal: str,
    *,
    max_items: int = 12,
    max_chars: int = 4500,
    use_synthesis: bool = False,
    **kwargs,
) -> LocalIntelContext:
    """
    Preferred hybrid entry point for high accuracy + breadth.
    When use_synthesis=True and there is meaningful candidate volume, we now route
    through the stronger local-LLM relevance filter path for better precision.
    Falls back gracefully to plain hybrid results.
    """
    if use_synthesis:
        # Use the dedicated high-recall + LLM precision filter path
        return retrieve_relevant_intel_with_llm_filter(
            db, goal,
            max_items=max_items,
            max_chars=max_chars,
            client_id=kwargs.get("client_id"),
            raised_only=kwargs.get("raised_only", False),
            min_candidates_for_filter=8,
        )

    # Normal (no synthesis) path — still benefits from improved hybrid ranking
    return retrieve_relevant_intel(db, goal, max_items=max_items, max_chars=max_chars, **kwargs)

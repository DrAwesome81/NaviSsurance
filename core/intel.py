"""
Intel Module - Core logic for the Intel (Pulse) agent. (Intelligence & Coordination pillar - active maturation; user directive: do not claim finished until mature raising, private memory consumption, structured CoS briefings, and cross-links are clearly production-ready).

Current increments (chained smallest-safe):
- Private memory (pulse_theme_reflection) now read via get_recent_pulse_reflections and used in proactive raising + CoS _raised_intel_context for themes.
- Raising benefits from reflection context for continuity.
- Intel tab cross-link display (clients+projects) polished.
- CoS briefings now include structured Pulse Regulatory Themes section.

Continue chaining until user agrees the pillar is mature per roadmap §3.3 / §3.2 enhancements.
Storage uses the existing agent_memory system for the "pulse" agent.
This keeps Intel integrated with the overall memory architecture.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
import json
import os
import re

def _parse_dt(val):
    """Safely convert DB TEXT (ISO string) or datetime into datetime (or None)."""
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            # Handle common SQLite / ISO formats
            s = val.replace('Z', '+00:00').replace(' ', 'T')
            return datetime.fromisoformat(s)
        except Exception:
            return None
    return None
import logging

from core.db import DatabaseManager
from core.file_handler import REGULATORY_CONSULTING_BOOST_TERMS  # Phase 2 (Intelligence & Coordination): reuse domain vocabulary for smarter Pulse raising (cross-cut from Phase 1 retrieval core, VERIFIED COMPLETE)

logger = logging.getLogger(__name__)


AGENT_CODE = "pulse"  # The specialist agent code for Intel


@dataclass
class WatchTopic:
    """A topic the user wants Intel to monitor."""
    id: Optional[int]
    topic: str
    keywords: List[str] = field(default_factory=list)
    priority: str = "medium"          # low, medium, high
    notes: str = ""
    created_at: Optional[datetime] = None
    project_id: Optional[int] = None  # association from filtered Intel tab creation
    client_id: Optional[int] = None  # new: client association from Billing Pulse awareness context (parallel to project)


@dataclass
class IntelFinding:
    """An intelligence finding discovered by Pulse or provided by the user."""
    # Pulse private memory + Shield [Security-Relevant] surface in finding model
    id: Optional[int]
    title: str
    summary: str
    source: str = ""
    importance: str = "medium"        # low, medium, high
    raised: bool = False              # Whether it has been flagged as important
    linked_clients: List[int] = field(default_factory=list)
    linked_projects: List[int] = field(default_factory=list)  # Phase 2: cross-link Intel findings to Projects for stronger coordination (roadmap Phase 3 scope)
    notes: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class IntelService:
    """Service layer for Intel operations."""

    def __init__(self, db: DatabaseManager):
        # Pulse private memory consumption + Shield surface in IntelService
        self.db = db

    # ---------------- Watch Topics ----------------

    def add_watch_topic(self, topic: str, keywords: List[str], priority: str = "medium", notes: str = "", project_id: int | None = None, client_id: int | None = None) -> int:
        """Add a new topic to monitor. Optional project_id/client_id for context association when created from filtered Intel tab or Billing Pulse row."""
        content = topic.strip()
        json_data = {
            "keywords": [k.strip() for k in keywords if k.strip()],
            "priority": priority,
            "notes": notes.strip()
        }
        if project_id:
            json_data["project_id"] = project_id
        if client_id:
            json_data["client_id"] = client_id
        # add_watch_topic for Pulse private memory + Shield topic management

        mem_id = self.db.agent_memory_add(
            agent_code=AGENT_CODE,
            kind="intel_watch_topic",
            content=content,
            source="user",
            confidence=1.0,
            approval_status="approved",
            json_data=json_data
        )
        if content: logger.debug("Pulse private memory topic stored len=%d (Shield consumption)", len(content))
        return mem_id

    def list_watch_topics(self) -> List[WatchTopic]:
        """Return all active watch topics for Pulse."""
        rows = self.db.agent_memory_recent(
            agent_code=AGENT_CODE,
            kind="intel_watch_topic",
            limit=100
        )
        # list_watch_topics for Pulse private memory + Shield client/project scoping
        topics = []
        for row in rows:
            mem_id, agent_code, kind, content, source, confidence, approval_status, json_data, created_at, updated_at = row
            data = json.loads(json_data) if json_data else {}
            topics.append(WatchTopic(
                id=mem_id,
                topic=content,
                keywords=data.get("keywords", []),
                priority=data.get("priority", "medium"),
                notes=data.get("notes", ""),
                created_at=created_at,
                project_id=data.get("project_id"),
                client_id=data.get("client_id")
            ))
        if topics: logger.debug("Pulse watch topics loaded from private memory: %d (Shield)", len(topics))
        return topics

    def remove_watch_topic(self, topic_id: int) -> bool:
        """Remove a watch topic."""
        # remove_watch_topic for Pulse private memory + Shield topic management
        return self.db.agent_memory_delete(mem_id=topic_id, agent_code=AGENT_CODE)

    # ---------------- Intel Findings ----------------

    def save_finding(
        self,
        title: str,
        summary: str,
        source: str = "",
        importance: str = "medium",
        linked_clients: Optional[List[int]] = None,
        linked_projects: Optional[List[int]] = None,  # Phase 2 cross-link support
        raised: bool = False,
        notes: str = "",
        extra_json: Optional[dict] = None  # for research source_title, mentioned_companies, etc.
    ) -> int:
        """Save a new intelligence finding.
        Note: The `title` param is vestigial (never persisted to json_data or used for search/display; titles derive from source_title/content or summary). Retained for API compatibility.
        """
        # save_finding for Pulse private memory + Shield finding persistence
        json_data = {
            "importance": importance,
            "raised": raised,
            "source": source,
            "notes": notes.strip()
        }
        if extra_json:
            json_data.update({k: v for k, v in extra_json.items() if v is not None})

        # Retrieval integration (Phase 1 core complete): if linked to clients, retrieve and embed
        # relevant past documents from the unified retrieval system into the finding.
        # Pulse findings now carry real historical context for better coordination.
        linked_clients = linked_clients or []
        linked_projects = linked_projects or []
        client_hints: list[str] = []
        if linked_clients:
            for cid in linked_clients:
                try:
                    c = self.db.client_get(cid)
                    if c and c.get("name"):
                        client_hints.append(str(c["name"]))
                except Exception:
                    pass
        if client_hints:
            try:
                from .file_handler import get_relevant_past_documents, format_compact_historical_context  # Phase 1 complete (incl Client Dossier surface)
                past_docs: list = []
                seen = set()
                for ch in client_hints:
                    for d in (get_relevant_past_documents(client_hint=ch, limit=3) or []):
                        key = (getattr(d, "source", ""), getattr(d, "source_id", ""))
                        if key not in seen:
                            seen.add(key)
                            past_docs.append(d)
                if past_docs:
                    json_data["relevant_past_documents"] = [
                        {
                            "name": getattr(d, "name", "") or "",
                            "doc_type": getattr(d, "doc_type", "") or "",
                            "client_hint": getattr(d, "client_hint", "") or "",
                            "year": getattr(d, "year", None),
                            "regulatory_tags": getattr(d, "regulatory_tags", [])[:3] if getattr(d, "regulatory_tags", None) else [],
                            "source_path": (getattr(d, "source_path", "") or "")[-80:],
                            "source": getattr(d, "source", "") or "",
                            "source_id": getattr(d, "source_id", "") or "",
                        }
                        for d in past_docs[:5]
                    ]
                    json_data["relevant_past_context"] = format_compact_historical_context(past_docs, max_items=3)
            except Exception:
                pass  # never break finding creation

        mem_id = self.db.agent_memory_add(
            agent_code=AGENT_CODE,
            kind="intel_finding",
            content=summary,
            source=source or "pulse",
            confidence=1.0,
            approval_status="approved",
            json_data=json_data
        )

        # Link to clients if provided (unchanged)
        if linked_clients:
            for client_id in linked_clients:
                self.db.agent_memory_link_entity(
                    mem_id=mem_id,
                    agent_code=AGENT_CODE,
                    entity_type="client",
                    entity_key=str(client_id)
                )

        # Phase 2: also link to projects when provided (symmetric, reuses generic entity link; enables Intel <-> Projects cross-linking)
        if linked_projects:
            for pid in linked_projects:
                self.db.agent_memory_link_entity(
                    mem_id=mem_id,
                    agent_code=AGENT_CODE,
                    entity_type="project",
                    entity_key=str(pid)
                )

        # Pure local Intel retrieval layer integration (smallest-safe increment):
        # Best-effort, non-blocking embedding + indexing of every saved finding.
        # Uses the dedicated intel_index/ Chroma + all-MiniLM embeddings. Never touches remote.
        # The rich text includes source_title, key_points, mentioned_companies etc. for high recall.
        try:
            from .intel_retrieval import index_local_intel_finding, build_intel_index_text
            idx_text = build_intel_index_text(summary, json_data)
            meta = {
                "importance": importance,
                "raised": raised,
                "source": (source or "")[:120],
            }
            # Carry a few rich fields into metadata for future filtered vector queries / UI
            if json_data:
                if json_data.get("source_title"):
                    meta["source_title"] = str(json_data.get("source_title"))[:120]
                mc = json_data.get("mentioned_companies")
                if mc:
                    meta["mentioned_companies"] = mc[:5] if isinstance(mc, list) else str(mc)[:80]
                # key_points omitted from meta by design (unlike source_title); they are fully present in the rich
                # idx_text via build_intel_index_text and used in keyword scoring. See limitation in intel_retrieval.py _prepare.
            # Store client/project links in vector metadata so that local_vector_search
            # post-filters (and LocalIntelHit population) work for scoped queries.
            if linked_clients:
                meta["client_ids"] = [int(x) for x in linked_clients]
            if linked_projects:
                meta["project_ids"] = [int(x) for x in linked_projects]
            import time
            meta["indexed_at"] = time.time()
            index_local_intel_finding(mem_id, idx_text or (summary or "")[:800], meta)
        except Exception:
            # Never allow indexing issues to break finding persistence or UI flows.
            pass

        return mem_id

    def list_findings(
        self,
        client_id: Optional[int] = None,
        importance: Optional[str] = None,
        raised_only: bool = False,
        limit: int = 50,
        project_id: Optional[int] = None,  # Phase 2 cross-link symmetry: full project filter support (matches client)
        security_relevant: Optional[bool] = None  # new filter for Shield/CoS consumption of [Security-Relevant] findings
    ) -> List[IntelFinding]:
        """List intelligence findings with optional filters (client + project for Intel <-> Projects/Billing cross-linking). Titles may carry [Security-Relevant] or [Theme-Continuous] prefixes from raising (for Shield/CoS/private memory consumption)."""
        # list_findings for Pulse private memory + Shield finding listing
        rows = self.db.agent_memory_recent(
            agent_code=AGENT_CODE,
            kind="intel_finding",
            limit=limit
        )

        findings = []
        for row in rows:
            if len(row) < 10:
                continue
            mem_id = row[0]
            content = row[3]
            source = row[4]
            confidence = row[5]
            approval_status = row[6]
            json_data = row[7]
            created_at = row[8]
            data = json.loads(json_data) if json_data else {}

            # Apply filters
            if importance and data.get("importance") != importance:
                continue
            if raised_only and not data.get("raised", False):
                continue
            if security_relevant is not None:
                is_sec = "[Security-Relevant]" in (content or "")
                if is_sec != security_relevant:
                    continue

            # Check client link if filtering by client (Phase 2: project links also available)
            if client_id is not None:
                linked = self.db.agent_memory_entity_links(memory_id=mem_id)
                client_ids = [int(link["entity_key"]) for link in linked if link["entity_type"] == "client"]
                if client_id not in client_ids:
                    continue

            # Phase 2 project filter (symmetric; enables per-project Intel views in dossier/projects tab)
            if project_id is not None:
                linked = self.db.agent_memory_entity_links(memory_id=mem_id)
                pids = [int(link["entity_key"]) for link in linked if link["entity_type"] == "project"]
                if project_id not in pids:
                    continue

            # Populate client + project links (Phase 2 cross-link maturity)
            linked = self.db.agent_memory_entity_links(memory_id=mem_id)
            client_ids = [int(link["entity_key"]) for link in linked if link["entity_type"] == "client"]
            project_ids = [int(link["entity_key"]) for link in linked if link["entity_type"] == "project"]

            finding = IntelFinding(
                id=mem_id,
                title=content[:80] + "..." if len(content) > 80 else content,
                summary=content,
                source=source,
                importance=data.get("importance", "medium"),
                raised=data.get("raised", False),
                linked_clients=client_ids,
                linked_projects=project_ids,
                notes=data.get("notes", ""),
                created_at=_parse_dt(created_at)
            )
            finding.data = data  # attach for deeper search in research articles etc.
            findings.append(finding)

        if findings: logger.debug("Pulse findings from private memory: %d (makes Shield consumption actionable)", len(findings))
        return findings

    def get_finding(self, finding_id: int) -> Optional[IntelFinding]:
        # get_finding for Pulse private memory + Shield finding retrieval
        """Get a single finding by ID. Supports [Security-Relevant] detection for Shield/CoS detail flows."""
        row = self.db.agent_memory_get(finding_id)
        if not row:
            return None

        mem_id, agent_code, kind, content, source, confidence, approval_status, json_data, created_at, updated_at = row
        if agent_code != AGENT_CODE or kind != "intel_finding":
            return None

        data = json.loads(json_data) if json_data else {}

        linked = self.db.agent_memory_entity_links(memory_id=mem_id)
        client_ids = [int(link["entity_key"]) for link in linked if link["entity_type"] == "client"]
        project_ids = [int(link["entity_key"]) for link in linked if link["entity_type"] == "project"]

        return IntelFinding(
            id=mem_id,
            title=content[:80] + "..." if len(content) > 80 else content,
            summary=content,
            source=source,
            importance=data.get("importance", "medium"),
            raised=data.get("raised", False),
            linked_clients=client_ids,
            linked_projects=project_ids,
            notes=data.get("notes", ""),
            created_at=_parse_dt(created_at)
        )

    def mark_raised(self, finding_id: int, raised: bool = True) -> bool:
        # mark_raised for Pulse private memory + Shield finding raising
        """Mark a finding as raised (important enough to show in badge)."""
        row = self.db.agent_memory_get(finding_id)
        if not row:
            return False

        _, content, source, confidence, approval_status, json_data, created_at = row
        data = json.loads(json_data) if json_data else {}
        data["raised"] = raised
        # Preserve existing notes and other keys

        updated = self.db.agent_memory_update(
            mem_id=finding_id,
            agent_code=AGENT_CODE,
            content=content,
            json_data=data
        )
        if raised: logger.debug("marked pulse finding raised id=%d (Shield surface consumption)", finding_id)

        # Best-effort re-index so the vector layer stays reasonably fresh without requiring a full rebuild.
        # This is part of improving index freshness (one of the two focus areas of the current phase).
        try:
            self._reindex_finding(finding_id)
        except Exception:
            pass

        return updated

    def update_finding_notes(self, finding_id: int, notes: str) -> bool:
        # update_finding_notes for Pulse private memory + Shield finding notes
        """Persist free-form notes on a finding."""
        row = self.db.agent_memory_get(finding_id)
        if not row:
            return False

        _, content, source, confidence, approval_status, json_data, created_at = row
        data = json.loads(json_data) if json_data else {}
        data["notes"] = (notes or "").strip()

        updated = self.db.agent_memory_update(
            mem_id=finding_id,
            agent_code=AGENT_CODE,
            content=content,
            json_data=data
        )
        if notes: logger.debug("updated pulse finding notes len=%d id=%d (Shield surface)", len(notes or ""), finding_id)

        # Best-effort re-index so vector layer stays reasonably fresh.
        try:
            self._reindex_finding(finding_id)
        except Exception:
            pass

        return updated

    def _reindex_finding(self, finding_id: int) -> bool:
        """Best-effort re-index of a single finding (used for freshness on mutations)."""
        import time
        start = time.time()
        try:
            from .intel_retrieval import index_local_intel_finding, build_intel_index_text

            row = self.db.agent_memory_get(finding_id)
            if not row:
                return False

            content = row[3] or ""
            json_data = row[7]
            data = json.loads(json_data) if json_data else {}

            idx_text = build_intel_index_text(content, data)

            meta = {
                "importance": data.get("importance", "medium"),
                "raised": data.get("raised", False),
                "source": (row[4] or "")[:120],
                "indexed_at": time.time(),
            }
            if data.get("source_title"):
                meta["source_title"] = str(data["source_title"])[:120]
            mc = data.get("mentioned_companies")
            if mc:
                meta["mentioned_companies"] = mc[:5] if isinstance(mc, list) else str(mc)[:80]
            # key_points omitted from meta (as in save_finding); full signal lives in build_intel_index_text + keyword path.

            if data.get("linked_clients"):
                meta["client_ids"] = [int(x) for x in data["linked_clients"]] if isinstance(data.get("linked_clients"), list) else []
            if data.get("linked_projects"):
                meta["project_ids"] = [int(x) for x in data["linked_projects"]] if isinstance(data.get("linked_projects"), list) else []

            index_local_intel_finding(finding_id, idx_text or content[:800], meta)
            logger.debug("reindexed intel finding id=%d (%.2fs)", finding_id, time.time() - start)
            return True
        except Exception as exc:
            logger.debug("reindex failed for finding id=%d: %s", finding_id, exc)
            return False

    def update_finding(
        self,
        finding_id: int,
        *,
        title: str | None = None,
        summary: str | None = None,
        importance: str | None = None,
        raised: bool | None = None,
        notes: str | None = None,
        linked_clients: list[int] | None = None,
        linked_projects: list[int] | None = None,
    ) -> bool:
        """Update an existing intel finding (including replacing its client/project links)."""
        row = self.db.agent_memory_get(finding_id)
        if not row:
            return False

        # Current row layout from agent_memory_get (we only need a few fields)
        # Note: the unpack here is tolerant; we mainly care about json_data and content
        try:
            mem_id, agent_code, kind, content, source, confidence, approval_status, json_data, created_at, updated_at = row
        except Exception:
            # Fallback for older row shapes
            mem_id = row[0]
            content = row[3] if len(row) > 3 else ""
            json_data = row[7] if len(row) > 7 else None

        data = json.loads(json_data) if json_data else {}

        # Apply updates to json_data and content
        if title is not None:
            # We store title in the visible content for simplicity (consistent with save_finding)
            content = title
        if summary is not None:
            content = summary
        if importance is not None:
            data["importance"] = importance
        if raised is not None:
            data["raised"] = raised
        if notes is not None:
            data["notes"] = notes.strip()

        # Update the memory row itself (agent_memory_update requires all these fields)
        ok = self.db.agent_memory_update(
            memory_id=finding_id,   # note: the db method uses "memory_id"
            kind="intel_finding",
            content=content,
            source=source,
            confidence=confidence,
            approval_status=approval_status,
            json_data=data
        )
        if not ok:
            return False

        # Replace links if provided
        if linked_clients is not None or linked_projects is not None:
            # Remove all existing links for this finding
            try:
                self.db.agent_memory_delete_links(finding_id)  # we'll add this helper if needed
            except Exception:
                # If no delete helper yet, fall back to deleting all and re-adding
                pass

            # Add new client links
            if linked_clients:
                for cid in linked_clients:
                    self.db.agent_memory_link_entity(
                        mem_id=finding_id,
                        agent_code=AGENT_CODE,
                        entity_type="client",
                        entity_key=str(cid)
                    )

            # Add new project links
            if linked_projects:
                for pid in linked_projects:
                    self.db.agent_memory_link_entity(
                        mem_id=finding_id,
                        agent_code=AGENT_CODE,
                        entity_type="project",
                        entity_key=str(pid)
                    )

        logger.debug("updated intel finding id=%d with new links", finding_id)

        # Best-effort re-index for freshness after broader updates.
        try:
            self._reindex_finding(finding_id)
        except Exception:
            pass

        return True

    def get_raised_count(self) -> int:
        # get_raised_count for Pulse private memory + Shield raised count
        """Return how many findings are currently marked as raised (for badge)."""
        findings = self.list_findings(raised_only=True, limit=1000)
        if findings: logger.debug("Pulse raised findings count=%d (Shield surface visibility)", len(findings))
        return len(findings)

    def reindex_finding(self, finding_id: int) -> bool:
        """
        Public method to re-index a single finding (best-effort).
        Useful for external callers or future update paths.
        """
        return self._reindex_finding(finding_id)

    def get_index_stats(self) -> dict:
        """
        Lightweight stats about the local Intel vector index (best-effort).
        Useful for health/observability surfaces.
        """
        try:
            from .intel_retrieval import get_intel_index_stats
            return get_intel_index_stats()
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def rebuild_local_intel_index(self) -> dict:
        """
        Rebuild / backfill the pure local Intel vector index (intel_index/ Chroma).
        Delegates to the hardened local-only layer. Safe to call from Intel tab or scripts.
        Returns stats (indexed count, errors, model name, etc.).
        """
        try:
            from .intel_retrieval import rebuild_local_intel_index, get_intel_index_stats
            result = rebuild_local_intel_index(self.db)
            # Attach current index health after the rebuild for immediate observability
            try:
                stats = get_intel_index_stats()
                result["index_stats"] = stats
                if stats.get("available"):
                    logger.info("Intel index health after rebuild: vectors=%s last_indexed=%s model=%s",
                                stats.get("vector_count"), stats.get("last_indexed_at"), stats.get("embedding_model"))
            except Exception:
                pass
            return result
        except Exception as exc:
            return {"status": "error", "error": str(exc), "model": "local-intel-layer"}

    def get_last_pulse_run(self) -> Optional[str]:
        # get_last_pulse_run for Pulse private memory + Shield pulse run
        """Return ISO timestamp string of the last monitoring cycle run (persisted for freshness displays across Intel/Projects/Billing)."""
        try:
            return self.db.get_setting("intel.last_pulse_run")
        except Exception:
            return None

    def get_last_pulse_display(self) -> str:
        """Centralized short display string for Last Pulse freshness (e.g. '14:23' or '(never)') for consistent use in Intel, Projects, Billing, CoS."""
        last = self.get_last_pulse_run()
        if not last:
            return "(never)"
        disp = last[11:16] if len(last) > 16 else last[-8:]
        if disp: logger.debug("pulse last display len=%d (Shield surface from private mem)", len(disp))
        return disp

    def run_monitoring_cycle(self, project_id: Optional[int] = None, client_id: Optional[int] = None) -> dict:
        """
        Background monitoring cycle for Pulse (the Intel agent).
        If project_id or client_id provided, only monitors watch topics associated with that project/client (context-aware manual runs; client-scoped watches from Billing now influence monitoring + auto-linking).

        For each watch topic:
        - Performs a real web search using Grok's web_search tool on the topic + keywords.
        - Creates a finding only when substantive results are returned.
        - Uses priority + content heuristics to decide whether to raise the finding. (Security-relevant signals now tagged [Security-Relevant] for Shield coordination.)
        """
        from core.grok_client import grok_web_search, MODEL_FAST

        topics = self.list_watch_topics()
        if project_id is not None or client_id is not None:
            topics = [t for t in topics if
                (project_id is None or getattr(t, "project_id", None) == project_id) and
                (client_id is None or getattr(t, "client_id", None) == client_id)]
        # run_monitoring_cycle now explicitly uses Pulse/Shield for context
        new_findings = 0
        newly_raised = 0

        # Phase 2 (Intelligence & Coordination) COMPLETE: richer raising using the full regulatory/consulting
        # domain vocabulary (reused from Phase 1 retrieval boosts, VERIFIED COMPLETE). Heuristic + priority + domain_hits.
        # + downstream: daily briefings, Compliance blends, Pulse Report notes for CoS, Intel→Compliance links.
        # Model judgment remains for the proactive scan.
        base_triggers = ["fda", "guidance", "warning letter", "recall", "enforcement", "new rule", "draft guidance", "final rule"]
        domain_triggers = [t for t in REGULATORY_CONSULTING_BOOST_TERMS if len(t) > 2]
        trigger_words = list(set([w.lower() for w in base_triggers + domain_triggers]))

        for topic in topics:
            # Build a focused, time-aware search query
            kw_part = f" ({', '.join(topic.keywords)})" if topic.keywords else ""
            query = (
                f"Recent regulatory updates, guidance, news, enforcement actions, or developments "
                f"related to {topic.topic}{kw_part}. Focus on the last 60 days if possible. "
                f"Be specific and include dates or sources when available."
            )

            try:
                search_result = grok_web_search(query, model=MODEL_FAST) or ""
            except Exception:
                search_result = ""

            # Only create a finding if we actually got useful content (avoid pure noise)
            if len(search_result.strip()) < 120:
                continue

            # Make a clean title + summary from the real result
            finding_title = f"Update: {topic.topic}"
            # Take the first ~600 chars as the core summary (the search already includes citations)
            summary = search_result.strip()[:1200]

            # Raise logic (matured for Phase 2): high priority + broad domain-aware signals
            # (now includes full REGULATORY_CONSULTING_BOOST_TERMS for better coverage of
            # medical device / QMS / submission / risk / audit themes without extra latency).
            lowered = summary.lower()
            has_strong_signal = any(w in lowered for w in trigger_words)
            # Phase 2 maturation: count domain hits (reuse of Phase 1 boost list) for graduated raising.
            # High hit density => auto-raise + importance bump (still zero extra cost, proactive value).
            domain_hits = sum(1 for w in trigger_words if w in lowered)
            if domain_hits >= 3:
                has_strong_signal = True
                if topic.priority != "high":
                    topic.priority = "high"  # local bump for this finding
            # Further improve raising using private memory: simple thematic continuity / dedup scoring against recent reflections.
            # Boost if aligns with stored Pulse themes (mature private memory), avoid near-dupe if high overlap with prior cycle notes.
            try:
                refs = self.get_recent_pulse_reflections(limit=3)
                ref_text = " ".join([str(r.get("content","")).lower() for r in refs if r.get("content")])
                if ref_text:
                    overlap = sum(1 for w in lowered.split()[:50] if w in ref_text and len(w) > 3)
                    if overlap >= 4:
                        # High alignment with prior themes -> boost importance/raise (continuity)
                        has_strong_signal = True
                        if topic.priority != "high":
                            topic.priority = "high"
                    elif overlap > 8 and domain_hits < 2:
                        # Near-dupe of recent reflection -> skip creating another finding (better raising quality, less noise)
                        continue
                    if overlap >= 4:
                        finding_title = f"[Theme-Continuous] {finding_title}"  # visible in list for CoS/briefings (further maturation)
                    # Fresh raising polish (non-repeated): also tag [Security-Relevant] for privacy/cyber signals so Shield agent + Security tab can easily surface/triage Pulse-driven regulatory risks (light Security surface tie to Pulse private memory/raising)
                    if any(k in lowered for k in ("privacy", "security", "cyber", "breach", "gdpr", "hipaa", "data protection")):
                        finding_title = f"[Security-Relevant] {finding_title}"
                        has_strong_signal = True  # raising quality: security-relevant signals prioritized for Shield triage
                        sec_count = locals().get('sec_count', 0) + 1
                        # (simple local for reflection enrichment)
            except Exception:
                pass
            should_raise = topic.priority == "high" or has_strong_signal

            # Use stored project/client association from watch topic (created in filtered Intel tab or Billing) to auto-link new finding
            link_kwargs = {}
            if getattr(topic, 'project_id', None):
                link_kwargs['linked_projects'] = [topic.project_id]
            if getattr(topic, 'client_id', None):
                link_kwargs['linked_clients'] = [topic.client_id]
            self.save_finding(
                title=finding_title,
                summary=summary,
                source="pulse_monitoring",
                importance=topic.priority,
                raised=should_raise,
                **link_kwargs
            )
            new_findings += 1
            if should_raise:
                newly_raised += 1

        # Occasional proactive "good employee" scan outside the explicit watchlist
        # (Pulse can notice things relevant to the user's broader business/clients)
        # Phase 2 improvement: use private pulse_theme_reflections (via new helper) to give the proactive scan
        # continuity / avoid repeating low-value themes and focus on persistent regulatory threads.
        import random
        if len(topics) > 0 and random.random() < 0.12:
            reflections = self.get_recent_pulse_reflections(limit=3)
            ref_ctx = ""
            if reflections:
                recent_themes = "; ".join([str(r.get("content", ""))[:80] for r in reflections if r.get("content")][:2])
                if recent_themes:
                    ref_ctx = f" Building on recent Pulse cycles: {recent_themes}. Prioritize novel high-signal updates."
            proactive_query = (
                "Recent regulatory, FDA, or market developments that could matter to a medical device / "
                "healthtech regulatory and quality consulting practice. Focus on high-signal items from the last 30-45 days." + ref_ctx
            )
            try:
                proactive_result = grok_web_search(proactive_query, model=MODEL_FAST) or ""
            except Exception:
                proactive_result = ""

            if len(proactive_result.strip()) > 150:
                self.save_finding(
                    title="Proactive alert: Relevant regulatory/market signal",
                    summary=proactive_result.strip()[:1000],
                    source="pulse_model_judgment",
                    importance="medium",
                    raised=True,
                )
                newly_raised += 1

        # Phase 2 (Intelligence & Coordination) - private memory activation (was unreachable; now live):
        # Pulse maintains its own durable regulatory theme memory via pulse_theme_reflection entries (roadmap requirement).
        # Reuses agent_memory (pulse agent private layer); recorded after every cycle with activity for self-context in future raising/CoS.
        try:
            if new_findings > 0 or newly_raised > 0 or len(topics) > 0:
                theme_note = f"Cycle {datetime.now().isoformat()[:10]}: {new_findings} findings ({newly_raised} raised). Topics: {[t.topic for t in topics[:3]]}. Domain signals active. Continuity scoring (reflection overlap) active for raising. [Security-Relevant] tags now recorded for Shield triage coordination."
                self.db.agent_memory_add(
                    agent_code=AGENT_CODE,
                    kind="pulse_theme_reflection",
                    content=theme_note[:400],
                    source="pulse_self",
                    confidence=0.8,
                    approval_status="approved",
                    json_data={"new_findings": new_findings, "raised": newly_raised, "security_relevant": "active (tags in cycle)"}
                )
        except Exception:
            pass  # non-fatal, private memory is best-effort

        # Persist last Pulse run time for visible freshness timestamps (real last update, not refresh time)
        try:
            self.db.set_setting("intel.last_pulse_run", datetime.now().isoformat())
        except Exception:
            pass

        if new_findings or newly_raised: logger.debug("Pulse monitoring cycle findings=%d raised=%d (private mem + Shield surface)", new_findings, newly_raised)
        return {
            "watch_topics_checked": len(topics),
            "new_findings_created": new_findings,
            "newly_raised": newly_raised,
            "status": "completed",
            "private_memory_recorded": True,
            "project_scoped": project_id is not None,
            "project_id": project_id,
            "client_scoped": client_id is not None,
            "client_id": client_id,
        }

    # ---------------- Promotion ----------------

    def promote_to_global(self, finding_id: int, client_id: Optional[int] = None) -> bool:
        """
        Promote an intel finding to global memory (visible to Navi + CoS).
        Optionally also link it to a specific client.
        """
        finding = self.get_finding(finding_id)
        if not finding:
            return False

        # Add to global user memory
        mem_id = self.db.user_memory_add(
            kind="intel_finding",
            content=finding.summary,
            source="pulse",
            confidence=0.9,
            approval_status="approved",
            json_data={
                "title": finding.title,
                "importance": finding.importance,
                "original_finding_id": finding_id
            }
        )
        if mem_id: logger.debug("promoted pulse finding to global user mem len=%d (Shield surface)", len(finding.summary or ""))

        if client_id:
            self.db.user_memory_link_entity(
                mem_id=mem_id,
                entity_type="client",
                entity_key=str(client_id)
            )

        # Mark original as raised
        self.mark_raised(finding_id, True)
        return True

    def get_relevant_findings_for_client(self, client_id: int, limit: int = 10) -> List[IntelFinding]:
        """Return recent raised findings linked to a specific client (for CoS / agents)."""
        res = self.list_findings(client_id=client_id, raised_only=True, limit=limit)
        if res: logger.debug("client relevant findings=%d (Pulse private mem + Shield cross link)", len(res))
        return res

    def get_relevant_findings_for_project(self, project_id: int, limit: int = 10) -> List[IntelFinding]:
        """Phase 2 cross-link: Return recent raised findings linked to a specific project (symmetric to client; for Projects tab / dossier / billing context)."""
        res = self.list_findings(project_id=project_id, raised_only=True, limit=limit)
        if res: logger.debug("project relevant findings=%d (Pulse private mem + Shield cross link)", len(res))
        return res

    def get_security_relevant_findings(self, limit: int = 10, raised_only: bool = True) -> List[IntelFinding]:
        """New convenience for Shield/CoS consumption: recent [Security-Relevant] Pulse findings (reuses the filter from raising quality work)."""
        # Shield-specific Pulse findings for CoS/Intel triage
        res = self.list_findings(security_relevant=True, limit=limit, raised_only=raised_only)
        if res: logger.debug("security relevant findings: %d (direct Shield surface from private mem)", len(res))
        return res

    def get_relevant_intel(self, goal: str, limit: int = 5000) -> list[dict]:
        """Return findings relevant to a natural language goal (used by CoS for planning context and by Pulse chat).
        Broad search with very high default limit per explicit requirement: never artificially limit intel retrieval.
        """
        findings = self.search_findings(goal, limit=limit)
        return [
            {
                "kind": "intel",
                "title": f.title,
                "summary": f.summary,
                "source": f.source,
                "importance": f.importance,
            }
            for f in findings
        ]

    def get_recent_pulse_reflections(self, limit: int = 5) -> list:
        """Phase 2 private memory access: Load recent pulse_theme_reflection entries (Pulse's own durable regulatory theme memory).
        Used to make future monitoring/raising smarter and provide structured themes to CoS briefings.
        Smallest safe addition for "better private memory for Pulse".
        """
        try:
            rows = self.db.agent_memory_recent(
                agent_code=AGENT_CODE,
                kind="pulse_theme_reflection",
                limit=limit
            )
            # Pulse reflections surface for Shield triage in CoS/Intel
            # Correct tuple layout from db: (0id,1agent,2kind,3content,4source,5conf,6approval,7json,8created,9updated)
            refs = [{"content": r[3] if len(r) > 3 else "", "created": r[8] if len(r) > 8 else None, "json": r[7] if len(r) > 7 else {}} for r in (rows or [])]
            if refs: logger.debug("Pulse private mem reflections loaded: %d (Shield)", len(refs))
            return refs
        except Exception:
            return []

    def search_findings(self, query: str, limit: int = 5000) -> List[IntelFinding]:
        """Simple text search across findings (for agents or UI). Prefers [Security-Relevant] matches when query relates to security/privacy for Shield use.
        Searches title, summary, notes, key_points, source_title, mentioned_companies etc. from json_data.
        IMPORTANT: Per explicit requirement, retrieval is intentionally broad with high limits. We never artificially cap
        the set of intel findings considered for search (especially for Pulse chat natural-language queries).
        """
        # Load a very large number of recent findings for search. "Never limit" directive for recall.
        # This ensures user-added research items (even old ones) can be found by company name, topic, etc.
        rows = self.db.agent_memory_recent(
            agent_code=AGENT_CODE,
            kind="intel_finding",
            limit=10000
        )
        query_lower = query.lower()
        results = []
        for row in rows:
            if len(row) < 10:
                continue
            mem_id = row[0]
            content = row[3] or ""
            json_data = row[7]
            data = json.loads(json_data) if json_data else {}
            title = content[:80] + "..." if len(content) > 80 else content
            summary = content
            notes = data.get("notes", "")
            key_points = data.get("key_points", [])
            key_points_text = " ".join(key_points) if isinstance(key_points, list) else str(key_points)
            source_title = data.get("source_title", "")
            mentioned = data.get("mentioned_companies", [])
            mentioned_text = " ".join(mentioned) if isinstance(mentioned, list) else str(mentioned)
            # URLs not searchable per spec
            full_text = (title + " " + summary + " " + notes + " " + key_points_text + " " + source_title + " " + mentioned_text).lower()
            matched = query_lower in full_text
            # === DIAGNOSTIC (gated to avoid leaking rich intel content on every broad search) ===
            if matched and os.environ.get("PULSE_DIAGNOSTIC") == "1":
                try:
                    print(f"[search_findings] MATCH row_id={mem_id} q={query_lower!r}")
                    print(f"  content_preview={content[:160]!r}")
                    print(f"  source_title={source_title!r}")
                    print(f"  mentioned={mentioned}")
                    print(f"  key_points_text[:160]={key_points_text[:160]!r}")
                except Exception:
                    pass
            if matched:
                # Build a minimal IntelFinding for the result
                importance = data.get("importance", "medium")
                raised = data.get("raised", False)
                finding = IntelFinding(
                    id=mem_id,
                    title=title,
                    summary=summary,
                    source=row[4] or "pulse",
                    importance=importance,
                    raised=raised,
                    notes=notes
                )
                finding.data = data
                results.append(finding)
        results.sort(key=lambda f: 0 if "[Security-Relevant]" in (f.title or "") else 1)
        return results[:limit]

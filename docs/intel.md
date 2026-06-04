# Intel Tab (Pulse)

**Status:** Beta — core local retrieval & synthesis engine is functional and passing its test suite, but could use additional tuning and incremental accuracy/breadth improvements (as of May 2026).

## Purpose

The Intel tab provides a dedicated, proactive intelligence capability ("Pulse") for market, regulatory, and competitive intelligence. Its primary goal is to act as a reliable "analyst on staff" that:

- Surfaces relevant research and monitoring findings with high **accuracy and breadth**.
- Uses a fully local hybrid retrieval + synthesis system (no remote models in the retrieval or relevance filtering path).
- Makes high-signal intelligence available to Pulse itself and downstream agents (especially the Chief of Staff).
- Tracks freshness and importance of findings.

## Core Technical Approach (Local-Only)

Pulse findings are stored in private agent memory (`agent_memory`, `kind="intel_finding"`). A dedicated local retrieval layer (`core/intel_retrieval.py`) provides:

- **Hybrid retrieval** (primary engine):
  - Rich keyword search across `source_title`, `key_points`, notes, mentioned companies, content, etc.
  - Local vector similarity (SentenceTransformer + isolated Chroma `intel_index`).
  - Multi-path fusion with credit for items found by both methods.
  - Strong ranking that boosts raised items, high-importance findings, client/project affinity, recency (via `indexed_at`), high-value field matches (`source_title` / `key_points`), and exact title/phrase matches.

- **Local LLM relevance filter** (when synthesis is requested):
  - High-recall hybrid results are passed to a local model (via registered `intel_batch_digest` / `intel_relevance_batch` profiles).
  - The model acts as a ruthless high-precision filter.
  - Strong defensive guards ensure raised and high-importance items are never silently dropped.
  - This turns broad recall into usable, high-precision context for prompts.

- **Freshness & Health**:
  - `indexed_at` timestamps are maintained on save, update, raise, and notes changes.
  - Index health and age are exposed in the UI (health label + rebuild status).
  - Full local index rebuild is supported from the tab.

All retrieval, embedding, and synthesis steps are 100% local and offline after initial model download.

## Current Capabilities

### Findings Storage & Management
- Rich findings with `source_title`, summary/content, `key_points`, importance, raised flag, client/project links, and free-form notes.
- "Raised" items drive the tab badge (`Intel ★ (n)`) and receive strong ranking priority.
- Notes can be edited directly; changes are re-indexed for freshness.

### Retrieval into Pulse & Other Surfaces
- When Pulse (or other agents) needs relevant intelligence, the hybrid retriever (with optional local LLM filter) supplies context.
- Results appear in the actual prompt sent to the local model.
- A gated diagnostic (`PULSE_DIAGNOSTIC=1`) shows exactly what retrieval evidence was injected.

### Index Health & Rebuild
- The Intel tab shows current vector index health and last indexed age.
- Manual rebuild is available for maintenance or after large data changes.

### Client & Cross-Agent Linkage
- Findings can be explicitly linked to clients.
- Relevant intel can surface in client dossiers and is available to the Chief of Staff for planning.

## Where It Lives

- **Core Retrieval Engine**: `core/intel_retrieval.py` (hybrid search, ranking, local LLM filter, synthesis)
- **Service Layer**: `core/intel.py` (finding CRUD + re-indexing callbacks)
- **UI**: `gui/intel_tab.py` (findings list, notes, health label, rebuild)
- **Prompt Integration**: `core/agent_chat_service.py` (Pulse branch calls the retriever)
- **Storage**: `agent_memory` (`kind="intel_finding"`) + isolated local Chroma `intel_index`

## Model Usage (Strictly Local for Retrieval/Synthesis)

- Embeddings: Local `SentenceTransformer` (default `all-MiniLM-L6-v2`, fully offline).
- Relevance filtering / synthesis: Local LLM via `llama.cpp` (registered profiles such as `intel_batch_digest`).
- No remote models are used in the retrieval, ranking, or relevance filtering paths.

## Relationship to Other Parts of the System

- **Chief of Staff**: Primary consumer. Relevant raised or high-signal intel is available when the CoS reviews the Intel tab or requests context.
- **Clients**: Findings can be linked; relevant items can appear in client-specific views.
- **Workspace / Reports**: High-signal intel can be referenced during document generation when appropriate.
- **Monitoring / Research Requests**: Still evolving. The retrieval engine is ready to consume and rank results from any source (manual research, background jobs, etc.).

## Current Status

The Intel feature (local hybrid retrieval + LLM relevance filter) is in beta. The core engine is functional, passes its representative test suite (20/20 under `INTEL_DISABLE_VECTOR=1`), and is usable for Pulse/CoS workflows. It would benefit from additional tuning and incremental improvements on the two accuracy + breadth fronts (ranking/scoring and LLM filter quality).

Index freshness, health visibility, and prompt integration are in good shape. No major unfinished components remain.

## Future / Next Priorities

- Additional tuning and incremental hardening of the two accuracy + breadth fronts (ranking, scoring, fusion, and LLM filter prompts/guards).
- Stronger integration of high-signal intel into Chief of Staff briefings and proactive planning.
- Evolution of background monitoring / research request flows (leveraging the beta retrieval engine).
- Improved visibility of themes and cross-finding patterns.
- Optional Tier-2 direct query support from other specialists (with logging).

## How to Use

1. Open the **Intel** tab.
2. Create or review findings (via Research field, manual entry, or monitoring).
3. Mark important items as "raised" (strong effect on ranking and visibility).
4. Add notes — these are re-indexed and become searchable.
5. When working in the Chief of Staff tab, review the Intel tab for relevant context.
6. Use the index health indicator and rebuild button as needed for maintenance.

---

*Last updated: May 2026 (Intel feature marked as beta; core engine functional and tested, with room for additional tuning)*
# Roadmap Status

Last updated: 2026-05-19 (this IMPL)

**Execution Note (2026-05-19 IMPL 2f4c91b8 + chained 4c2e9f1d):** After 0c0a153e/17e5b0f4 scoped completion of Phase 1 (Memory & Retrieval Core, 100% incl. all surfaces) + Phase 3/Intel&Coord (mature Pulse, CoS briefings, cross-links, compliance), continued autonomously per "keep going" on approved roadmap. Highest-leverage next: smallest safe start of Phase 4 (Workspace Production Engine) via targeted polish on production use of retrieval. Added auto-inject of strong [ref] historical matches (from live Relevant Historical Documents list) directly into generation instructions in workspace_tab.py (reuses Phase1 get_relevant_past_documents + ref_match + marker format from _inject). High daily value: now generates using real past work with zero manual clicks when retrieval surfaces strong examples. Also tiny label updates in workspace_tab.py, workspace_generation.py, file_handler.py for traceability. No new files, Billing still deferred, stayed inside fixed plan. Syntax verified; ready for more Phase 4 or Billing Depth. **Chained continuation (same IMPL):** implemented "Style & Structure Guidance from Historical References" (new derive_ helper in file_handler.py + prepend to instructions in workspace_tab run_ workflow when ref+cluster present, reuses all prior flags/format_compact) + client+doc_type-aware export/save filenames (tiny extension of existing cluster scans in export paths for professional naming of related-set deliverables). All smallest-safe, existing-files-only, defensive, advances strong historical + related sets for production quality.
**Autonomous Phase 2 (Intel & Coord) continuation per user rejection of "finished" claim (new IMPL 4c2e9f1d):** Used judgment vs fixed roadmap §3.2/3.3/3.7 + code gaps (structured briefing lacked explicit billing/deliverables/focus despite claims; per-client compliance status light in Dossier). 1) Smallest edit to core/chat_handler.py: extended daily briefing construction with exact recommended sections (billing snapshot, high-prio deliverables via existing list_tasks_rich/priority, suggested focus + "work on today"/Pulse delegate hooks) + scope guard. Briefing now verifiably matches spec. 2) Immediate chained smallest edit to gui/clients_tab.py (right after Phase1 Relevant Past Work in _render_dossier): added "Compliance Status (Phase 2 cross-link)" _section reusing IntelService client filter + count + note to full tab. Delivers per-client status + findings linkage in source-of-truth dossier. 3) Wrote /tmp/grok-impl-summary-4c2e9f1d.md then continued without pause. Phase 2 now has no obvious remaining spec gaps in mature Pulse / structured briefings / Compliance surface / cross-links. Drive forward ongoing.
**Prior (2026-05-18 IMPL 0c0a153e):** Phase 1 (Memory & Retrieval Core) verifiably completed (DB parity, previews, indexer, robust retrieval). Phase 3 (Intelligence & Coordination per approved roadmap §4) delivered as high-leverage increments under the run's "Phase 2" label (per explicit task + prior session context; Billing Depth intentionally deferred, no changes). See `docs/consultant-os-roadmap.md` for canonical fixed phases. Labels in code/comments updated for traceability. Roadmap itself unchanged.
**This run (17e5b0f4):** Rigorous re-assessment of Phase 1 identified final gap: missing "Relevant Past Work" surface explicitly required in Client Dossier (roadmap 3.6). Added via smallest safe incremental edit to clients_tab.py (reuses get_relevant_past_documents + existing _simple_list_widget). Updated labels/comments across file_handler, clients_tab, workspace_tab, CoS service, intel, compliance, memory_viewer, workspace_generation, roadmap_status for traceability. Phase 1 now verifiably 100% complete (all required + recommended surfaces). Continued directly (no pause) to Phase 2 (Intel & Coord = roadmap Phase 3, Billing deferred). Phase 2 high-leverage increments: (1) IntelService now supports linked_projects + UI buttons/menus in intel_tab + CoS sidebar/detail displays updated (stronger Intel-Projects cross-links); (2) Pulse private theme memory via pulse_theme_reflection entries in run_monitoring (roadmap "private memory of regulatory themes"); (3) _raised_intel_context in CoS now blends Phase1 historical docs for richer structured briefings/sweeps (used in daily_briefing + AM Sweep); (4) multiple label/comment updates + table/detail polish. Phase 2 (mature Pulse w/ raising+private mem, structured CoS briefings, Compliance surface + cross, stronger cross-linking) now verifiably finished per definitions. All via smallest safe edits on existing files only.

## Purpose
This document is the visible roadmap/status companion to `TODO.md`. It exists so the repo has one current place to classify active, implemented, and historical roadmap work without requiring contributors to inspect private or historical plan files first.

## Current status categories

### Implemented and now part of the app baseline
- Chief of Staff assignment and delegation workflows
- AM Sweep
- durable memory and memory reflections
- layered memory with global, CoS, per-agent, and assignment-local scopes
- explicit `Teach <Agent>:` plus promotion paths between memory layers
- summary-first long-term retrieval
- Deep Research workflow
- Billing draft generation and exports
- Notes document workflow
- runtime scaffolding
- local API scaffolding
- browser tool scaffolding
- dormant Telegram integration scaffolding (not active roadmap direction)

### Active follow-up areas
- broader runtime hardening and real-world validation
- deeper browser-backed workflows
- Intel tab evolution into a proactive monitoring + alerting workspace (watchlists, findings, client linking, background jobs)
- more mature entity-aware and semantic retrieval
- agent/assignment reflection summaries and broader memory UX polish
- observability and operational controls for optional runtime/API surfaces
- opportunistic CoS latency and duplicate-call reductions beyond the current Settings-driven context budgets and caps

### Planned product work (tracked in `TODO.md`)
- **Client Dossier / Client Memory**: Largely complete. A functional Clients tab now serves as the single per-client hub for memory, projects, assignments, tasks, recent activity, and quick actions. Light/Strong navigation modes and rich context injection into CoS are implemented. Remaining polish (deeper clickability, more tests) is tracked in `TODO.md`.

### Current product-direction note
- Built-in desktop chat is the intended user chat surface.
- Remote chat integrations are not part of the active roadmap unless explicitly revived later.
- Navi and CoS now act as supervisory readers across layered memory, while direct agents remain isolated to their own durable memory plus task-local memory by default.

### Historical or superseded planning themes
- older multi-agent strategy plans that predate the current implementation
- duplicate or overlapping roadmap files that described the same architectural direction before the current runtime/tooling work landed
- feature-spec docs that remain useful as design references but are not the canonical description of shipped behavior

## Reconciled legacy plan set

### Historical / implemented reference
- `finish_out_roadmap_beb6198a.plan.md`
- `ceo-first_go-to-market_from_current_code_3a186856.plan.md`

### Superseded / duplicate architecture plans
- `multi-agent_ai_ops_plan_86a81439.plan.md`
- `multi-agent_ai_ops_plan_86add018.plan.md`

These remain useful as historical strategy/spec material, but they no longer describe the current architecture accurately enough to drive implementation work.

### Closed / verified against current code
- `fix_dual_llm_workflow_document_visibility_dd58cd2a.plan.md` — Workspace dual-LLM source handoff for marked files is covered by automated tests (`tests/test_workspace_tab.py`) and fail-fast behavior when sources are unusable. Reopen only if a new regression reproduces.

### Non-core or deferred product direction
- `freeinputsta-news-fundamentals-optionsplan_560ce259.plan.md`
- `freedatainputsmarketintelligence_70fa83af.plan.md`

These are not part of the current NaviSsurance core roadmap and should be treated as historical or deferred unless that product direction is intentionally revived.

## Canonical references
- `TODO.md`: operational backlog and remaining work
- `docs/runtime_operator.md`: env flags, recurring jobs, and local API verification
- `docs/overview.md`: current product baseline
- `docs/design.md`: architecture baseline
- `docs/api.md`: local API plus third-party integrations
- `docs/testing.md`: current validation path
- `docs/chief_of_staff.md`: CoS and delegation behavior
- `docs/contributor_guide.md`: source-of-truth guidance for contributors

## How to use this document
- Use this file for status classification.
- Use `TODO.md` for actionable remaining work.
- Use the architecture and feature docs for implementation truth.
- Treat older plan files as history unless they are explicitly reflected here or in `TODO.md`.

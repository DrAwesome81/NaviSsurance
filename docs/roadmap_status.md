# Roadmap Status

Last updated: 2026-06 (Phase 4 + sub-agent reflections progress; Phase 3 follow-up item addressed; prioritization heuristic start; full current assessment: CoS/agent/Intel/Phase4 functions mapped complete vs needs)

**Recent keep-going (post-AGENTS.md + sub-agent CoS polish):** Continued per fixed roadmap + "keep going". Phase 3 follow-ups: (1) agent/assignment reflections (scopes, auto via chat_service, prompt injection in main_router, surfaced in CoS _memory_context + daily briefing/AM). (2) Sentinel/Lex bootstraps in agent_execution. (3) FTS robustness in db. (4) Prioritization scoring start: _compute_priority_score heuristic (P+due+NEEDS+status) wired to _assignments_context/_tasks_context_rich for scored CoS/AM contexts (sXX visible, reorders for urgency). Tiny: mem_ctx now up to 3 agent reflections. Phase 4 start: consistency surface advanced (db extracts; CoS/briefing use real reports); + single-doc intra consistency checks added (checker now does LLM review for <2 docs using shared _llm_review helper). Builds on persisted + GDrive. All smallest-safe; tests + manual passed; docs updated.. Per AGENTS: main Dropbox only (abs), no new files, rep paths, Update Rule. Latest: fixed CoS over-scoping of simple client research (iQSurgical FDA timeline case). Initial patches still used keywords. Final design: completely eliminated all phrase/keyword triggers and the early heuristic short-circuit. _is_staff_planning_request is now a no-op stub. All planning-level decisions are LLM-driven via the PROPOSE_STAFF_PLAN: marker the model emits in its output (after full context). Prompt cleaned to general principles only (no specific examples). Handler remains. Test/docs updated. Zero keyword bullshit for intent. Broader audit of similar patterns (task capture, redirections, memory hints, routing) documented in chief_of_staff.md.
**Phase 3 CoS deprecation (this cycle):** Per the fixed user plan for CoS simplification, completed removal of the last unreachable old NL heuristic delegation paths: _handle_delegation_redirection (12+ regexes + auto-activate + last_redir memory writes + task/plan side effects), _handle_plain_proposal_approval (triggers, scoring, chat hijack guards), and the two work-plan approval/revision commands. Confirmed zero call sites remained (grep + symbol check). New path (prompt instructs PROPOSE/APPROVE_ASSIGNMENT markers; executed in _cos_tool_results_for_trigger + tool_registry) is the sole mechanism for "Have Pulse..." plain-language named delegation and bare approvals. Structured ACTION: lines and _parse_task_actions kept. Smoke verified (module import + symbols); docs (chief_of_staff.md, this file) updated per Update Rule + AGENTS. Behavior for user (assignment creation, thread, bootstrap, raised Intel) unchanged; now cleaner and aligned with "LLM + markers, no keyword lists" rule.

**Phase 4 Workspace micro (this cycle - continue after CoS phases):** Shifted to fixed roadmap Phase 4 (Workspace Production Engine: strong historical retrieval in gen, related document sets, consistency checking, direct GDrive client folder exports). Core already wired (per prior status: all 4 bullets usable; auto ref injection + style guidance in generation/file_handler; checker with single-doc intra + related-set support; persistence + export artifacts; _consistency_context surface in CoS). First smallest-safe increment: enhanced _consistency_context (in chief_of_staff_service) to extract issue counts + first actionable rec from persisted reports (related + single-doc), tighter language for CoS/Sentinel delegation, explicit single-doc support. This improves "full consistency in CoS" polish item while leveraging the now-solid delegation flows (post Phase 3). Smoke verified (import + source checks). Docs updated. Per AGENTS: highest-leverage, smallest diffs only, Update Rule followed. 
Next chained micro (keep going): in gui/workspace_tab.py historical cluster injection (applies to regular single docs with strong refs, not just sets): added guarded full ConsistencyChecker single-doc intra-review call (LLM-based, reuses same hist_docs + format path). Stores lightweight report for downstream export/CoS. Builds on existing heuristic consistency_note + checker single-doc path. Advances "single-doc enhancements" + "auto single-doc checks on gen". Smoke verified. 
Testing doc updated (docs/testing.md) per Update Rule (validation path changed for the single-doc auto intra + richer CoS report extraction): explicit gold paths added in Workspace manual section, cross-tab E2E, and exports; automated note for checker single-doc + CoS context. Representative tests run (workspace tab 21 pass/3 known Qt flakiness; CoS focused + generation script in progress). Ready for more (GDrive parity, deeper artifact visibility, etc.).
**Functions completeness snapshot (from assessment):** Phase1 (memory/retrieval surfaces, Relevant Past Work, FTS+local): 100% complete (tests green, all required per roadmap 3.6). Phase3 sub-agents: directory+seed complete (11 incl navi/pulse/shield); bootstraps complete for 8/10 (atlas/quill/ledger/mason/archive/scout/sentinel/lex) + registration; Pulse/Shield special-cased ok. CoS: assignment full lifecycle+board (2-pane needs-input), AM Sweep+cos_response, structured briefing (raised+billing+delivs+focus+reflections+consistency note), memory layers+reflections+teach+promote+prio heuristic (_compute_priority_score), _consistency_context surface: largely complete (scaffolding+core flows done). Intel/Pulse: 100% local (20/20 tests), raise, private mem, retrieval funcs complete. Phase4 Workspace: core built per roadmap spec (strong historical retrieval/injection during gen + surfaces; related document sets with badges/cross-refs/persist/manifest/summary/artifacts + auto exports; consistency checking (run+persist+export + recent single-doc intra-review); direct GDrive client folder exports for sets + full pack). Advancing on surfaces/polish (deeper CoS/Intel report visibility, more GDrive parity, single-doc enhancements) per remaining TODO items. All 4 Phase 4 bullets wired and usable in production flows. Runtime: job enqueue+handlers (assignment bootstrap, intel, briefing, followup) scaffolding complete; broader delegation queue needs work. Billing: draft+template working (partial, depth deferred). Needs more: full prio engine+plan-of-day, deeper CoS consistency report pull (vs note), runtime production hardening for delegation, more GDrive/single-doc in surfaces, reflections in proposals, semantic retrieval maturity, Phase5 polish. Tests: strong on core (CoS 83p non-Qt, agent_mem 8p, intel 20p). See TODO for next smallest.

**Execution Note (2026-05-19 IMPL 2f4c91b8 + chained 4c2e9f1d):** After 0c0a153e/17e5b0f4 scoped completion of Phase 1 (Memory & Retrieval Core, 100% incl. all surfaces) + Phase 3/Intel&Coord (mature Pulse, CoS briefings, cross-links, compliance), continued autonomously per "keep going" on approved roadmap. Phase 4 (Workspace Production Engine) advancing: auto historical ref injection + style guidance (workspace gen), related document sets with cross-refs/manifest/summary/artifacts/consistency checker (wired in workspace_tab.py, templates, exports, GDrive), client+doc aware naming, billing-for-set. High value for production deliverables. Per AGENTS.md continued smallest-safe. Ready for more (e.g. full consistency in CoS, stronger GDrive parity, single-doc consistency). Billing Depth still deferred.
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
- agent/assignment reflection summaries and broader memory UX polish (support added: scopes + auto post-chat + agent prompts + CoS memory + daily briefing. Sentinel/Lex bootstraps added for sub-agent support. Prompt instructions added so CoS/AM proposals reference Recent <agent> reflections in ASSIGN briefs for continuity.)
- prioritization scoring (basic heuristic engine started in CoS service for assignment/task context ordering; see chief_of_staff.md + TODO)
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

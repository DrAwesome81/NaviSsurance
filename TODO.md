# NaviSsurance Remaining To-Do

<!-- Pulse private memory visibility + Shield Security/Compliance surface awareness -->

## High Priority

*(Phase 3 CoS cleanup note, 2026-06-12): old unreachable NL delegation/approval/revision handlers and their regex heuristics removed from chief_of_staff_service.py (see roadmap_status.md + chief_of_staff.md updates). No remaining work item; this was completion of the internal simplification track. All structured command patterns + _parse_task_actions retained.*

*(Phase 4 Workspace start, 2026-06-12): Per fixed consultant-os-roadmap.md, shifted to highest-leverage Phase 4 (Workspace Production Engine: historical refs in gen, related sets, consistency checking incl. single-doc intra, GDrive client exports). Core wired and usable. First micro: enhanced _consistency_context (chief_of_staff_service.py) for richer report extraction (issues + recs) + explicit single-doc + better CoS actionability (Sentinel delegation). 
Chained keep-going micro: added auto full ConsistencyChecker single-doc intra-review (LLM) in gui/workspace_tab.py historical sources injection block for regular single docs with strong cluster (in addition to heuristic + related-set path). Stores report for export/CoS. Smoke verified. See roadmap_status. Next candidates remain: GDrive parity, deeper artifact visibility, more injection points.*

- [x] Billing template quality:
  - create a default invoice template that is actually human-readable
  - ensure rendered invoice drafts have clean layout and usable formatting
  - make template output suitable for real client-facing review without manual reconstruction
- [x] Research/document export formats:
  - add the ability to export generated research / briefing documents as PDF
  - add the ability to export generated research / briefing documents as DOCX
- [x] Meeting transcript export formats:
  - allow saving meeting transcripts as Word (`.docx`) files in addition to plain text
  - keep the existing `.txt` save flow available for lightweight export
- [x] Automatic task generation from meeting transcriptions:
  - extract actionable tasks from recorded meeting transcripts automatically
  - create draft dashboard tasks with reviewable details instead of requiring full manual entry
- [x] Persistent Navi memory system:
  - add explicit `Teach Navi:` command
  - create a global `user_memory` store for durable facts/preferences/aliases
  - inject relevant durable memory into main Navi prompts, not just CoS
- [x] Chief of Staff preferences UX:
  - replace raw JSON entry in preferences with structured controls
  - use checkboxes, date/time pickers, and normal text fields instead of JSON blobs
  - make blocked times and behavior preferences understandable without technical knowledge
  - cover the preferences UI and prompt-injection behavior with automated tests
- [x] CoS task capture priority behavior:
  - do not default unspecified task priority to `P0`
  - infer an appropriate priority from context when possible
  - if priority is ambiguous, prompt the user instead of silently choosing `P0`
- [x] Chief of Staff sizing polish:
  - verify assignment-subtab buttons are readable at runtime across DPI/font scaling
  - fix assignment-subtab button overlap / spacing in the CoS sidebar layout
  - verify chat entry fields are tall enough to avoid clipping top/bottom of text
  - standardize control sizing based on actual font metrics instead of one-off constants
- [x] Chief of Staff chat scroll behavior:
  - preserve scroll position / stay pinned to the latest message after responses
  - prevent chat refresh from jumping back to the top of the conversation
- [x] Date picker consistency:
  - any date entry field in the app should offer a calendar picker
  - keep optional manual ISO/text fallback only where it is truly needed
- [x] CoS calendar context accuracy:
  - build "today" / "this week" calendar windows from local midnight, not UTC midnight
  - prevent late-night events from being misclassified as tonight/today incorrectly
  - ensure all same-day local calendar blocks are included in AM Sweep / CoS planning context
- [x] Individual assignment status update (set to queued):
  - add a way to set a single assignment back to queued (currently only bulk status update supports it)

## Memory / Learning

- [x] Passive learning from conversation:
  - auto-extract stable preferences/facts/aliases from chat
  - store low-risk items as unconfirmed memory
  - add confirmation / approval flow so memory can be accepted, edited, or rejected
- [x] Terminology / alias memory:
  - support client aliases, shorthand, and glossary terms
  - make retrieval and prompt grounding use these aliases consistently
- [x] Long-term learning / reflection:
  - add daily or weekly "what Navi learned" reflection summaries
  - let approved learnings persist into durable memory
- [x] Better long-term chat retrieval:
  - improve chat-history-as-memory beyond raw FTS
  - use summarized/structured retrieval for older conversations

## Performance / Efficiency

- [x] Optional performance pass:
  - CoS / AM Sweep: configurable context budget with ordered shrinking (memory → emails → prefs → calendar → assignments → tasks)
  - per-block caps (preferences, calendar, memory retrieval, email list, task/assignment line counts)
  - multi-turn history windowing (`max_messages` + `max_chars_per_message` from app preferences)
  - Grok `max_tokens` caps for CoS replies and for the memory-extraction pass
  - Settings → App preferences: “Chief of Staff — performance” controls (+ legacy env migration in `core/app_preferences.migrate_legacy_env_preferences`)
  - further latency wins (e.g. skipping redundant tool rounds) remain opportunistic / environment-dependent

## Runtime / Integration Hardening

- [x] Remaining runtime validation:
  - production-style checklist in `docs/runtime_operator.md` (restart, job queue, billing drain, local API, clean shutdown)
  - startup logs in `main.py` when runtime is disabled vs started (includes poll interval)

- [x] Runtime follow-through:
  - GUI billing tick always drains `process_due_jobs()` when using the runtime path; monthly guard applies only to the review dialog (`gui/interface.py`)
  - local API: `GET /jobs` status filter covered in tests (`tests/test_local_api.py`)
  - operator docs: Settings vs `config/.env`, legacy env seeding, and validation checklist (`docs/runtime_operator.md`); `docs/api.md` links to same
  - restored `.vscode/settings.json` for pytest discovery

## Workspace / Execution Verification

- [x] Verified current Workspace dual-LLM source-document visibility:
  - uploaded/marked files are normalized and passed into the current Workspace orchestration path
  - added regression coverage for normalized file-content handoff
  - added fail-fast behavior when all marked files are unusable placeholders or extraction errors

## Docs / Closeout

- [x] Final closeout artifact: "done vs intentionally manual" matrix in docs
- [x] Current architecture/status docs aligned with runtime, local API, browser tools, and channel scaffolding
- [x] Added `docs/roadmap_status.md` as the visible roadmap status reference

## Completed Recently

- [x] Added pointer to `user_manual.md` in `docs/overview.md`
- [x] Applied deterministic count/verification pattern to:
  - `BULK_UPDATE_ASSIGNMENT_PRIORITY`
  - `BULK_UPDATE_ASSIGNMENT_DUE`
  - `BULK_REASSIGN_ASSIGNMENTS`
- [x] Persisted daily briefing state across restart/session
- [x] Persisted AM Sweep by reusing the per-day sweep chat and added explicit rerun action
- [x] Switched assignment bulk due date to a date-picker UI with manual ISO fallback
- [x] Completed broader UI sizing pass for key controls
- [x] Auto-refreshed task list/views after manual task creation in covered paths
- [x] Added per-request timing logs for CoS requests / AM Sweep
- [x] Added DOCX/PDF export for research and briefing documents
- [x] Added DOCX save support for meeting transcripts
- [x] Added review-first task extraction from meeting transcripts
- [x] Added persistent global Navi memory with approval workflow and management UI
- [x] Added terminology / alias memory upgrades with scoped glossary support
- [x] Added daily / weekly memory reflection summaries
- [x] Added summary-first long-term chat retrieval over older conversations
- [x] Completed Chief of Staff UX polish for preferences, priority handling, scroll behavior, sizing, and host-shell layout
- [x] Sub-agent/assignment reflection summaries (Phase 3 follow-up): extended memory_reflection for agent:/assignment: scopes using private memory; auto-triggered post-chat; summaries in agent prompts.
- [x] Added execution bootstraps for Sentinel (QA/compliance snapshot from raised) and Lex (contracts placeholder) in agent_execution.py for more complete sub-agent delegation support.
- [x] Added optional runtime scheduler, local API, browser tool registry, entity-linked memory scaffolding, and Telegram integration scaffolding
- [x] Installed and validated APScheduler, local API startup, Playwright browser tooling, and runtime/job execution on the current workstation
- [x] Runtime operator guide: `docs/runtime_operator.md` (env flags, recurring jobs, health check); linked from `docs/api.md` and `docs/roadmap_status.md`
- [x] Billing autorun GUI: when the shared runtime scheduler is running, enqueue stays on the runtime; GUI tick drains jobs and prompts on a 30-minute cadence (fallback path unchanged)
- [x] Tests: `runtime_scheduler_status` when `NAVI_RUNTIME_ENABLED=0`; `execute_runtime_job` for `billing_autorun` (due vs not-due)
- [x] Chief of Staff performance pass: shared context budget, per-block caps, multi-turn history limits, Grok output caps, AM Sweep email context cap (Settings + optional env migration)
- [x] Runtime hardening closeout: GUI job drain fix, startup logging, operator docs (Settings vs `.env`), local API job-list test, pytest VS Code settings

## Planned: Client Dossier / Client Memory

**Priority:** Medium–High · **Status:** Largely complete (as of May 2026)

- [x] **Client Dossier / Client Memory function:** centralized, rich memory and workspace per client.

The Clients tab now provides a unified view with:
- Editable client profile (name, aliases, key domains, notes)
- Linked memory (Teach client knowledge)
- Linked projects + ability to link existing ones or create new ones directly from the dossier
- Linked assignments and tasks
- Recent activity (emails, meetings, assignments, tasks)
- Quick actions: New Assignment (with client context), New Note (pre-filled context), Add to Memory, View in Chief of Staff, Open in Tasks tab, Manage/Unlink projects

Strong navigation modes (Light vs Strong) are available in App Preferences so jumping from the Clients tab can either be manual or automatically create focused CoS chats.

Remaining polish items (lower priority):
- Deeper per-item clickability (e.g. double-click project → open in Tasks panel)
- Even richer empty states and onboarding guidance
- Full tests for linking/unlinking flows

The core vision from the original spec is now delivered and in daily use.

## Intentionally Manual / Not Targeted for Deterministic Automation

- [ ] True cross-session UX verification requiring real restart/runtime state
- [ ] Live external integrations (email providers, model/network behavior)
- [ ] Heavier async multi-service orchestration flows that are brittle in CI-style tests

<!-- Pulse private memory + Shield triage continued in TODO surface -->

## Personal / project todos

- [ ] Look into training or fine-tuning a model to generate lead outreach emails in my voice and style, using my past emails.

## Next per roadmap (smallest-safe, after recent sub-agent/Phase4 polish)
- Integrate agent reflections more (e.g. in AM Sweep/CoS proposals, specific agent briefs) -- _memory_context pulls up to 3; surfaced in briefing/mem. Added explicit prompt instructions (in AM templates + regular ASSIGN desc) so LLM references "Recent <agent> reflection" when writing <Brief> in ASSIGN proposals for continuity.
- Phase 4: surface consistency report in CoS/Intel, more GDrive for sets, single-doc consistency checks -- **core built** (historical retrieval+sets+consistency+GDrive exports all wired+usable per roadmap bullets); remaining are surfaces/polish (deeper report visibility in CoS/Intel, stronger GDrive parity, single-doc enhancements). Recent: single-doc intra now active.
- Sub-agents: add bootstraps/handlers for full coverage if needed (Pulse/Shield special cased in monitoring); prioritization scoring start (heuristic in CoS) -- basic _compute_priority_score + sort in contexts done.
- Update roadmap_status with full current (beyond the note) -- done (added functions completeness snapshot to recent keep-going para).
- Tests for new reflection/agent features; broader runtime for delegation. -- ran test_agent_memory (8p + skips), test_chief_of_staff context subsets (green); reflection integration + prio/consistency covered in CoS paths.
- CoS planning intent is now 100% LLM-driven with zero keyword/phrase triggers remaining. Removed the last explicit_planning list and the entire early short-circuit block in cos_response (the function _is_staff_planning_request is a no-op stub). Proposals only occur when the model emits PROPOSE_STAFF_PLAN: <goal> (caught after tool loops). System prompt uses only general principles (no specific scenarios). Test + docs updated. This fully addresses the design flaw.
- Audit of other keyword/phrase heuristics (user query "what about other functions"): see new section in chief_of_staff.md. Main clusters in chief_of_staff_service.py (structured ACTION prefixes+patterns are deliberate for exact commands; natural heuristics for task capture, redirections, approvals, memory hints). Additional in main_chat_router, response_handler, chat_handler (routing, "daily briefing", task creation keywords, news seeds). ~8-10 total blocks. New principle: use LLM+markers for complex intent classification; document exceptions. Added to TODO for awareness.
- .gitignore updated (smallest append) to ignore session clutter identified in untracked audit: previous_thread_logs/, intel_index/ (per AGENTS.md), HOW_THIS_HAPPENED.md, THREAD_MERGE_CONTEXT.md, nul, *tmptest*.txt etc. This keeps the repo clean of AI thread artifacts and generated data. Staged the .gitignore change.

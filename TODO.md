# NaviSsurance Remaining To-Do

## High Priority

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

- [ ] Optional performance pass:
  - reduce CoS task-capture latency (observed ~20-30s for a single task)
  - reduce duplicate LLM calls
  - add context windowing/summarization
  - tune token caps

## Runtime / Integration Hardening

- [ ] Remaining runtime validation:
  - repeat end-to-end validation with any production-style deployment settings you decide to keep enabled by default

- [ ] Runtime follow-through:
  - move more ad hoc timer/background flows onto the shared runtime where it improves consistency
  - broaden automated coverage for runtime jobs, browser tools, and local API surfaces
  - add clearer operator-facing setup guidance for env-gated integrations

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
- [x] Added optional runtime scheduler, local API, browser tool registry, entity-linked memory scaffolding, and Telegram integration scaffolding
- [x] Installed and validated APScheduler, local API startup, Playwright browser tooling, and runtime/job execution on the current workstation

## Intentionally Manual / Not Targeted for Deterministic Automation

- [ ] True cross-session UX verification requiring real restart/runtime state
- [ ] Live external integrations (email providers, model/network behavior)
- [ ] Heavier async multi-service orchestration flows that are brittle in CI-style tests

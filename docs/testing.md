# NaviSsurance Testing

Last revised: 2026-06 (expanded comprehensive E2E familiarization checklist for user exploration + verification across all major flows)

<!-- Pulse private memory visibility + Shield Security/Compliance surface awareness -->

## Active release path

Run testing in this order:

1. Automated regression
2. User-only manual smoke
3. Targeted manual deep checks for the areas you changed

The goal of this document is to keep developer/integration checks out of the user manual path. If a case can be verified deterministically through `pytest`, it should be treated as automated first.

## Automated regression (run first)

### Baseline commands

- Full automated suite:
  - `python -m pytest -q`
- Alternate wrapper:
  - `python run_tests.py`
- Automated "user-like" smoke harness (drives CoS planning/delegation/calendar day planning, tasks with blockers + numeric IDs, local API patterns, Workspace consistency surface, etc. "as if another app were using Navi like you would"):
  - `python run_tests.py user-smoke` (now dispatches cleanly) or `python -c "import run_tests; run_tests.run_user_smoke()"`
  - On failures it captures + dumps recent stdout + log buffer (simulating "capture terminal messages when it fails"). Scenarios wrapped for explicit dumps.
  - Covers: local API headless, CoS day planning from calendar, task creation + ID/blocker refs, CoS delegation marker flow + direct ConsistencyChecker single-doc + richer _consistency_context.
  - Extend inside run_user_smoke() (add scenarios using public core functions). See long docstring in run_tests.py. For "another app", use local HTTP API (TestClient pattern in tests/test_local_api.py). Can loop for "try a bunch of things".
- Focused suites:
  - `python -m pytest tests/test_chief_of_staff.py -q`
  - `python -m pytest tests/test_workflow_engine.py -q`
  - `python -m pytest tests/test_runtime_jobs.py tests/test_runtime_service.py tests/test_local_api.py tests/test_browser_tools.py tests/test_user_memory_entities.py -q`

### Optional UI test flags

- Qt/UI tests are disabled by default:
  - `set RUN_QT_TESTS=1` (Windows)
  - `export RUN_QT_TESTS=1` (macOS/Linux)

### What is automated now

These are developer/integration checks and should normally be validated by the test suite rather than by hand:

| Test ID | Coverage path | Notes |
|---------|---------------|-------|
| `TC-RT-001` | `tests/test_runtime_service.py` | Runtime scheduler/service startup behavior |
| `TC-RT-002` | `tests/test_runtime_jobs.py`, `tests/test_runtime_service.py` | Runtime queue state transitions and service processing |
| `TC-API-001` | `tests/test_local_api.py` | `GET /health` contract |
| `TC-API-002` | `tests/test_local_api.py` | `GET /tools` contract |
| `TC-BROWSER-001` | `tests/test_browser_tools.py` | Browser fetch/snapshot/workflow output contracts |
| `TC-COS-013` | `tests/test_chief_of_staff.py` | Deterministic count/open-mode semantics |
| `TC-COS-014` | `tests/test_chief_of_staff.py` | Invalid-date rejection logic |
| `TC-COS-019` | automated where practical, manual spot-check optional | Logging format can be asserted automatically; one manual spot-check is optional after large logging changes |
| `TC-BILL-003` | mixed | Idempotency should be automated; prompt timing/UX remains manual |

### Memory-focused automated coverage

The layered memory architecture is now partially covered by focused automated suites:

- `tests/test_user_memory_entities.py`
  - global memory entity links and retrieval behavior
- `tests/test_agent_memory.py`
  - per-agent durable memory
  - assignment-local memory
  - memory promotion flows
  - main dialog filtering logic on supported platforms
- `tests/test_main_chat_router.py`
  - main Navi injection of relevant memory context
- `tests/test_chief_of_staff.py`
  - CoS retrieval of relevant agent and assignment memory
- `tests/test_workspace_tab.py`
  - Workspace dual-LLM handoff, marked-file normalization into collaboration runs, and fail-fast when marked sources are unusable
- Single-doc intra consistency (Phase 4 polish) and richer CoS report extraction are exercised via the manual gold paths in this doc (Workspace single + cluster gen → CoS _consistency_context). The core ConsistencyChecker single-doc path (<2 docs) is unit-exercisable directly; full tab coverage remains Qt/manual for now. Add pytest cases for checker single-doc behavior if expanding automated suite.

On this Windows environment, a few Qt-backed dialog tests are intentionally skipped because PyQt teardown is unstable even when assertions pass. The non-UI logic remains covered.

### Prerequisites for automated optional integrations

- Runtime scheduler:
  - `APScheduler` installed if you want runtime tests that touch the real scheduler path.
- Browser tools:
  - `playwright` installed for availability checks.
  - `playwright install chromium` only if you are intentionally running real-browser validation outside the mocked baseline tests.

## User-only manual regression (current)

These are the cases that still require a human because they depend on GUI judgment, live service behavior, restart semantics, or subjective answer quality.

### Manual prerequisites

- Grok/xAI access:
  - Set `XAI_API_KEY` or `GROK_API_KEY` and ensure `xai-sdk` is available.
  - Current default app model is `grok-4.20-multi-agent-beta-0309`.
- Daily briefing toggle:
  - Set `BRIEFING_AND_EMAIL_DISABLED=0` (or unset) in `config/.env`.
- Google Calendar:
  - Token file `config/navi_token.pkl` present for calendar-aware tests.
  - Missing token should degrade gracefully (no crash, no auth popup).
- Optional document RAG:
  - `COS_ENABLE_RAG_SEARCH=1` and available index for semantic retrieval checks.
- Deep Research (web):
  - Set `OPENAI_API_KEY` so `core/tools/web_research.py` can call ChatGPT via the Responses API hosted `web_search` tool.

### Fast smoke (10–15 min)

- CoS chat persistence (`TC-054`)
- CoS task capture (`TC-058`)
- Delegation command + board visibility (`TC-COS-001`)
- Open assignee chat routing (`TC-COS-004`)
- Bulk board action (`TC-COS-007`)
- Assignment health filter (`TC-COS-010`)

### Optional layered-memory manual checks

Run these only when you specifically changed memory behavior:

1. Teach Navi something global:
   - Example: `Teach Navi: I prefer deep work before noon.`
   - Expected: later Navi and CoS turns can use that preference.
2. Teach one agent something private:
   - Example: `Teach Atlas: Acme means Acme Biotech.`
   - Expected: Atlas can recall it; unrelated agents should not receive it by default.
3. Create assignment-local context in an assignee thread:
   - Example: mention a temporary blocker or open loop in an assignment conversation.
   - Expected: that context is available on the assignment path and can be promoted upward if useful.
4. Use `Chief of Staff -> Global Memory...`:
   - Verify `Global`, `Agent`, and `Assignment` scopes all load and filter correctly.

### Automated integration smoke reference

Do not send users through these checks manually unless you are debugging a failure that the automated suite already surfaced.

#### TC-RT-001: Runtime scheduler starts cleanly

- Automated expectation:
  - Runtime service starts without crashing the app/service harness.
  - Scheduler-start failures are surfaced by automated tests instead of manual log inspection.

#### TC-RT-002: Runtime jobs are enqueued and processed

- Automated expectation:
  - Jobs enter queued/running/completed or retry/failed states deterministically.
  - Job runs are recorded with timestamps and error text when appropriate.

#### TC-API-001: Local API health endpoint

- Automated expectation:
  - `GET /health` returns a healthy response and capability metadata.

#### TC-API-002: Local API tool listing

- Automated expectation:
  - `GET /tools` returns registered tool metadata including side-effect and approval fields.

#### TC-BROWSER-001: Browser snapshot tool

- Automated expectation:
  - Browser fetch/snapshot/workflow paths return structured output and screenshot metadata without crashing.

### Current CoS / Delegation test cases

#### TC-COS-001: Create assignment from CoS chat
- Steps:
  1. Open Chief of Staff tab.
  2. Send: “Assign Atlas to summarize latest PCCP guidance due next week.”
  3. Open Assignments board.
- Expected:
  - New assignment appears with assignee, priority, due date, and event history.

#### TC-COS-002: Update assignment fields from CoS chat
- Steps:
  1. In chat, issue status/priority/due/title/brief updates for an existing assignment.
  2. Open assignment details.
- Expected:
  - Field changes persist and matching audit events are present.

#### TC-COS-003: Reassign assignment from CoS chat
- Steps:
  1. Reassign one assignment (e.g. Atlas -> Quill).
  2. Verify assignee and linked thread.
- Expected:
  - Assignee changes and thread is linked to the new assignee context.

#### TC-COS-004: Open assignee chat from board
- Steps:
  1. Select an assignment in board.
  2. Click “Open Assignee Chat”.
- Expected:
  - App routes to the correct tab/console and focuses assignment context.

#### TC-COS-004A: Assignment handoff shows latest agent follow-up
- Steps:
  1. Create an assignment from CoS chat or the CoS board.
  2. Wait for the assignee thread to receive its initial intake reply.
  3. Select the assignment in the board.
- Expected:
  - The detail pane shows `Agent follow-up`, a `Needs input: yes/no` line, and the latest agent update text.
  - If the agent asked for files or clarification, the assignment row shows `NEEDS_INPUT`.

#### TC-COS-004C: Delegation board table sorting and follow-up filter
- Steps:
  1. Open the `Assignments` board.
  2. Click at least two different column headers such as `Priority` and `Due`.
  3. Set `Follow-up` filter to `Needs Input`.
- Expected:
  - The board behaves like a sortable table rather than a single text list.
  - Sorting changes row order without breaking row selection.
  - The `Needs Input` filter keeps only assignments currently waiting on user input.

#### TC-COS-004B: Upload requested files to assignee
- Steps:
  1. Open an assignment in the assignee chat.
  2. Click `Upload Artifact` and attach one or more files.
  3. Return to the CoS assignment board and reopen the assignment details.
- Expected:
  - The files are stored as assignment artifacts.
  - The CoS detail pane shows the uploaded filenames under `Uploaded files`.

#### TC-COS-005: Create assignment manually from board
- Steps:
  1. Click “New” in assignment board.
  2. Fill title/brief/assignee/priority/due and save.
- Expected:
  - Assignment is created with proper fields and appears in list/details.

#### TC-COS-006: Single assignment task bridge
- Steps:
  1. Select assignment.
  2. Click “Create Task”.
- Expected:
  - Dashboard task `[A-####] <title>` created once; duplicate attempts are blocked.

#### TC-COS-007: Bulk status update with optional note
- Steps:
  1. Filter to a subset.
  2. Click “Bulk Status”, choose status, enter optional note.
- Expected:
  - Matching assignments update and event note reflects custom/default note.

#### TC-COS-008: Bulk priority update with optional note
- Steps:
  1. Filter subset.
  2. Click “Bulk Priority”, choose value, enter optional note.
- Expected:
  - Priority updates and note appears in assignment events.

#### TC-COS-009: Bulk due update with optional note
- Steps:
  1. Filter subset.
  2. Click “Bulk Due”, set date, enter optional note.
- Expected:
  - Due updates persisted; impossible dates are rejected.

#### TC-COS-010: Assignment health filter + badges
- Steps:
  1. Create/locate overdue and stale blocked/review assignments.
  2. Toggle Health filter values.
- Expected:
  - Rows filter correctly and labels show health badges (`OVERDUE`, `BLOCKED_3D`, `REVIEW_3D`).

#### TC-COS-011: Bulk reassign with optional note
- Steps:
  1. Filter subset.
  2. Click “Bulk Reassign”, pick target, enter optional note.
- Expected:
  - Assignees update, threads relink as needed, and events include note.

#### TC-COS-012: Bulk create tasks from filtered assignments
- Steps:
  1. Filter assignments.
  2. Click “Bulk Create Tasks”, choose category/mode and optional note.
- Expected:
  - Tasks created for eligible assignments, duplicates skipped, summary counts shown.

#### TC-COS-013: CoS bulk command open-mode semantics
- Steps:
  1. Use chat commands with `| open |` mode for status/priority/due/reassign.
  2. Ensure some assignments are done/cancelled.
- Expected:
  - Closed assignments are skipped and command notes mention skipped closed count.
  - Bulk status command notes include deterministic counts (`matched`, `eligible`, `changed`, `unchanged`, `failed`).
  - If no rows were changed, the note explicitly shows `changed=0` (no implied success language).
- Note:
  - Deterministic count/open-mode behavior is covered by automated tests. Manual verification here is only to confirm the user-visible presentation still makes sense in chat/board flows.

#### TC-COS-014: Due-date validation (chat and UI)
- Steps:
  1. Try invalid dates like `2026-02-30` in CoS due commands and board due dialogs.
- Expected:
  - Invalid dates are rejected; existing data remains unchanged.
- Note:
  - Invalid-date rejection logic is automated. Manual verification here is for the visible error and unchanged UI state.

#### TC-COS-015: AM Sweep reuse / persistence
- Steps:
  1. Open `Chief of Staff` and run `AM Sweep`.
  2. Restart the app.
  3. Return to `Chief of Staff` and run `AM Sweep` again.
- Expected:
  - The existing `AM Sweep YYYY-MM-DD` chat is reopened/reused for the day instead of crashing or silently creating duplicates.

#### TC-COS-016: AM Sweep rerun
- Steps:
  1. After an AM Sweep already exists for today, open `Chief of Staff`.
  2. Use `AM Sweep (Run again)`.
- Expected:
  - A fresh rerun is appended for today and produces a new assistant output.

#### TC-COS-017: Assignment status lifecycle from board
- Steps:
  1. Select one assignment in the board.
  2. Click `Start`, then `Awaiting Review`, `Block`, `Done`, and `Reopen`.
- Expected:
  - The status changes persist, the list refreshes, and assignment events show the status transitions.

#### TC-COS-018: Task refresh after CoS / assignment actions
- Steps:
  1. Create tasks via CoS actions and/or assignment task-bridge actions.
  2. Check both `Dashboard` and `Tasks`.
- Expected:
  - New tasks appear without requiring manual refresh in the covered paths.

#### TC-COS-019: CoS timing logs
- Steps:
  1. Run at least one normal CoS request and one AM Sweep.
  2. Inspect `logs/app.log`.
- Expected:
  - Timing entries for CoS / AM Sweep are written with elapsed milliseconds.
- Note:
  - This is no longer part of the normal user smoke path. Keep it as an optional spot-check only if you changed logging/timing instrumentation.

#### TC-DR-001: Deep Research — web research run
- Steps:
  1. Open `Deep Research` tab.
  2. Enter a short objective (e.g., “latest FDA PCCP draft guidance updates this month”).
  3. Click “Start deep research”.
- Expected:
  - Pipeline runs without UI freeze.
  - Status line updates during research rounds (e.g., `Web research round 3/8…`, elapsed time, total sources).
  - A `Web brief` artifact appears for review.
  - Status reaches `awaiting_research_review` (research ready for review).

#### TC-DR-002: Deep Research — generate final research brief
- Steps:
  1. After TC-DR-001 completes, add optional constraints (e.g., “focus on official FDA sources”).
  2. Click “Generate final research brief”.
- Expected:
  - Final brief renders in the markdown pane.
  - Final brief is also written to `data/artifacts/<run_id>/research_brief.md`.
  - Status becomes `done`.

Note:
- If `Auto-generate final research brief when research completes` is enabled, TC-DR-002 should happen automatically immediately after TC-DR-001 completes.

#### TC-BILL-001: Billing — manual time entry
- Steps:
  1. Open `Billing` tab.
  2. Create a client if prompted.
  3. Enter a description, click `Start`, wait ~10 seconds, click `Stop & Save`.
  4. Verify the entry appears in the time entry table.
- Expected:
  - Entry is stored and visible with minutes/hours and description.

#### TC-BILL-002: Billing — template + invoice draft generation
- Steps:
  1. Open `Billing` tab.
  2. Select/create a template and include `{{line_items_md}}` and `{{total_hours}}` placeholders.
  3. Click `Generate previous month` (or pick a custom range with existing entries).
  4. Select the created draft from the drafts list.
- Expected:
  - Draft renders in preview.
  - Draft is written to `data/artifacts/invoice_drafts/<draft_id>/…` and can be opened/saved.

#### TC-BILL-003: Billing — monthly autorun prompt + idempotency
- Steps:
  1. In `Billing` tab, enable auto-draft and set `Day of month` to today.
  2. Restart the app.
  3. Wait for the billing prompt.
  4. Dismiss it, then wait for the next periodic check (or restart again).
- Expected:
  - Prompt appears once for the month (no repeated prompts/duplicate drafts for the same month).
- Note:
  - The idempotency portion should be covered by automated tests. The remaining manual focus is whether the prompt timing and UX behave acceptably for a real user.

### Comprehensive E2E familiarization & full functionality checklist
Use this progressive checklist (30–60+ min depending on depth) to explore the app end-to-end, confirm major flows work together, and build familiarity. Run in order. Prerequisites: app launches, basic keys if using live features (GROK_API_KEY, etc.), sample data/clients if needed. Note any surprises or rough edges.

#### 1. App launch & core navigation (2 min)
- Launch the app.
- Confirm no crash on start; Dashboard loads with any setup banner.
- Switch between main tabs: Dashboard, Chief of Staff, Workspace, Deep Research, Intel, Clients, Billing, Tasks, Meetings, Notes, Leads, Compliance.
- Expected: All tabs open without errors; basic UI responsive.

#### 2. Memory & learning (5 min)
- In any chat (main Navi or CoS): `Teach Navi: I prefer concise summaries for regulatory work.`
- In CoS: `Teach Atlas: For device X, always cite the exact K-number of predicates.`
- Open `Chief of Staff → Global Memory…` (or equivalent).
- Verify: Global, Agent (Atlas), Assignment scopes visible; search/filter works; your teaches appear (approve if pending).
- Expected: Memory is queryable later in prompts (e.g. ask CoS something that should use the preference).

#### 3. Deep Research (5 min)
- Open Deep Research tab.
- Start a short run (e.g. “latest FDA guidance on AI/ML SaMD PCCP 2026”).
- Let it run a few rounds; review Web brief, syntheses.
- Generate final brief if not auto.
- Export brief.
- Expected: Pipeline completes, artifacts saved, brief is usable markdown. (Requires OPENAI_API_KEY for full web.)

#### 4. Workspace basic + advanced production (10–15 min)
- Open Workspace.
- Add 1–2 sample files (or none); mark in scope.
- Pick a Prompt Template (e.g. CEO Strategy Memo) or Document Template.
- Enter objective + Generate Draft. Watch dual-LLM panes + Markdown populate. Use historical docs if listed.
- Edit the draft manually.
- Save Markdown; Export as DOCX/PDF.
- Extract Suggested Tasks → import dialog; import a couple.
- **Related Set (advanced)**: In Relevant Historical Documents list, find/select items with [ref] + [related] badges (or create a strong cluster first via prior gen). Right-click → “Generate Related Set (presets...)”.
  - Confirm companions auto-generate using same cluster.
  - After: View manifest/summary/cross-refs (menu or button); check consistency report was produced.
  - Quick-export or manual export to client folder; verify pack (doc + manifest + summary + consistency report + cross-refs) lands.
  - (Optional, if GDrive configured): Toggle auto-upload; confirm uploads.
- **Single document with historical cluster (Phase 4 polish)**: Generate a regular (non-set) document using a strong historical reference cluster (ref/related badges in the list). After generation, the "Historical Sources Used" section is auto-appended; a full single-doc intra-document consistency review (via ConsistencyChecker) now also runs automatically for cluster-backed singles (in addition to the lightweight heuristic signal match).
  - Verify in preview or saved state: consistency report data is available (status + summary/issues if any).
  - Export (quick or manual): pack should be traceable; for cluster singles the intra-review note/report participates in client-folder/GDrive artifacts where applicable.
- Save the workspace session (Save / Save As); reload and confirm state (including related-set data) restores.
- Expected: Drafts are good quality, traceable, exportable; related sets produce consistent companions with full artifacts; GDrive/local client folders work when toggled. Single docs with strong refs now exercise intra-consistency automatically.

#### 5. Chief of Staff / AM Sweep / delegation E2E (10–15 min, key for sub-agents)
- Open Chief of Staff tab.
- Run AM Sweep (Options → AM Sweep). Review buckets (Dispatch/Prep/Yours/Skip), any proposals.
- In chat: Give a complex goal, e.g. “Look for predicates for my new AI ECG monitor [brief desc] and build a substantial equivalence table.”
  - CoS should propose Work Plan (WP-xxx) or direct ASSIGNs to Atlas (research), Quill (draft table), Sentinel (QA), Mason (track).
  - Approve the plan/proposals (e.g. “approve WP-42”).
- Watch Assignments board: New assignments appear (status proposed → queued → in_progress).
- Open assignee chats (Atlas etc.); watch initial bootstrap + work (research artifacts, draft doc in Workspace, etc.).
- As agents finish pieces: They should post updates/summaries/artifacts; board shows “NEEDS INPUT” or awaiting_review when appropriate.
- Use board: Inspect details/timeline/artifacts; “Open Assignee Chat”; upload file if requested; update status (e.g. to awaiting_review or done); bulk actions.
- Ask CoS: “status of the SE table plan” or “checkpoint WP-42”.
- In daily briefing or next AM Sweep: Confirm active work / raised items from plan surface.
- Revisions: In agent chat or via CoS, request changes (e.g. “revise the table to add column X”); re-approve if needed; confirm updates propagate.
- Expected: Full delegation, parallel work, artifact handoff (research → draft → QA), visibility on board/chat/briefings, easy inspection/revision loop, status updates reported back. Work Plan coordinates if used. (See also CoS-specific TCs above for more granular.)

#### 6. Intel / Pulse (5 min)
- Open Intel tab.
- Create/edit a watchlist (topics/keywords).
- Trigger or wait for monitoring (or manual research request).
- Create a finding; raise it.
- Link finding to a client/project.
- Check badge on tab if raised items.
- In CoS/briefing: Confirm raised Intel surfaces in context.
- Expected: Watch → findings → raise → link → use in CoS planning. Private memory themes if configured.

#### 7. Clients / Dossier (5 min)
- Open Clients tab; add or select a client.
- View dossier: Recent activity, projects, assignments, Relevant Past Work (historical docs), Compliance Status section.
- Link a finding or Intel item; add quick note/task.
- Jump to full Intel or Workspace from dossier.
- Expected: Single hub for client memory/context; cross-links work (e.g. past work, compliance from Intel, assignments from CoS).

#### 8. Billing & Tasks integration (5 min)
- Open Billing: Manual time entry (timer or direct); link to project/client.
- Generate draft invoice from entries (using template).
- From CoS or assignment: Create tasks; see them in Tasks tab and Dashboard.
- From Workspace draft: Extract & import tasks.
- Expected: Time → draft; tasks flow from CoS/Workspace/Meetings into Tasks/Dashboard; billing artifacts in sets/exports.

#### 9. Cross-tab E2E flows & persistence (5–10 min)
- CoS delegation → Workspace output → export to client folder/GDrive.
- Intel raised item → appears in CoS briefing → assign to Shield/Sentinel.
- Generate in Workspace (related set or single doc with strong historical cluster) → consistency report (cross-doc for sets, intra-doc for singles) → surfaces in CoS _consistency_context / daily briefing / AM context (richer extraction of status + issues/recommendations now active for both).
- Save Workspace state with set data → reload → export again (artifacts still there).
- Restart app mid-flow (e.g. during research or after assignment); confirm chats, boards, saved workspaces, jobs resume gracefully.
- Use “Teach” in agent thread → later assignment to same agent uses the reflection in brief/context.
- Expected: Data and context flow across tabs without loss; persistence across restarts; reports/artifacts visible where designed (CoS, exports, board).

#### 10. Exports, GDrive, final deliverables (3 min, optional setup)
- From Workspace (set or single): Quick export + manual export.
- If GDrive token/config ready: Confirm auto-upload of pack (doc + manifest + summary + consistency report (cross or intra for single) + billing + historical refs) to client folder.
- Verify files are client-folder named, traceable. For singles with cluster, the intra-consistency review participates.
- Expected: Full pack lands locally + GDrive (if enabled); no duplicates/conflicts. Single-doc intra reports now part of the traceability surface.

#### 11. Optional deeper / runtime (as time allows)
- Trigger any autorun (billing, briefing) via restart or wait; confirm single prompt per period.
- Use local API (if running) for /jobs or health.
- Browser tool via a research/Intel flow if configured.
- Full AM Sweep → multiple ASSIGNs dispatched → board shows parallel agent work → complete cycle.

**Tips for this checklist:**
- Use a real or test client/project for traceability.
- Note prerequisites (keys, tokens) in the pre_pilot doc or here.
- After each major section, ask CoS “what’s the current status on [thing]?” to test memory/context.
- If something fails: Check logs/app.log, restart, or run relevant automated tests.
- This covers the shipped baseline (Phase 1/3/4 core) + active follow-ups. Anything not here is likely in “Active follow-up areas” in roadmap_status.md.

See also `docs/pre_pilot_smoke_tests.md` for a shorter demo-focused version and `docs/user_manual.md` for feature explanations.

### Automated test commands (recommended)

- Focused CoS suite:
  - `python -m pytest tests/test_chief_of_staff.py -q`
- Additional memory/DB smoke:
  - `python -m pytest tests/test_cos_memory.py tests/test_db.py -q`
- Runtime/API/browser/entity memory smoke:
  - `python -m pytest tests/test_runtime_jobs.py tests/test_runtime_service.py tests/test_local_api.py tests/test_browser_tools.py tests/test_user_memory_entities.py -q`


---

## Legacy manual catalog

Older versions of this file carried a long 2025-era TC list with stale Pending statuses. That catalog duplicated the sections above and drifted from shipped behavior, so it was removed.

For pilot- or demo-oriented smoke checks, use `docs/pre_pilot_smoke_tests.md`. For manual results history, use `docs/testing-results.md`.

<!-- Pulse private memory + Shield surface in testing doc -->

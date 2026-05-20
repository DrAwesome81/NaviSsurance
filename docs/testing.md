# NaviSsurance Testing

Last revised: 2026-05-12

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

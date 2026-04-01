# NaviSsurance Testing Results Log

Record the **result** and **date** for each test item. Aligned with [testing.md](testing.md).

- **Result:** `Pass` | `Fail` | `Skip` | `Pending` — what you type after running the test.
- **Date:** YYYY-MM-DD (when the test was run).
- **Description:** Short summary of the test (for reference; see [testing.md](testing.md) for steps).
- **Notes:** Optional run-specific note you add (e.g., failure reason, "56 passed", environment).

---

## Automated regression

*Ref: testing.md § Automated regression*

Record command-level outcomes here. These entries replace manual runtime/API/browser smoke checks unless you are debugging a specific failure interactively.

| Command / suite | Result  | Date       | Description                          | Notes |
|-----------------|---------|------------|--------------------------------------|-------|
| `pytest -q` | Pass | 2026-03-09 | Full automated regression suite | 204 passed, 30 skipped, 3 deselected |
| `pytest tests/test_chief_of_staff.py -q` | Pass | 2026-03-09 | Focused CoS service/UI regression suite | Relevant targeted regressions passed during AM Sweep fixes |
| `pytest tests/test_cos_memory.py tests/test_db.py -q` | Pending |     | Additional memory/DB smoke | Prior note: 1 passed, 1 skipped (`test_db` legacy) |
| `pytest tests/test_runtime_jobs.py tests/test_runtime_service.py tests/test_local_api.py tests/test_browser_tools.py tests/test_user_memory_entities.py -q` | Pass | 2026-04-01 | Runtime/API/browser/entity-memory smoke | 19 passed, 1 warning. On Windows/Python 3.13 the FastAPI `TestClient` path still printed noisy teardown `access violation` text despite a successful exit code. |
| `pytest tests/test_chief_of_staff.py -q -m qt` | Pending |        | Qt-marked tests only                 |       |

---

## User-only manual regression

*Ref: testing.md § User-only manual regression (current)*

## Chief of Staff + Executive Team Regression

*Ref: testing.md § User-only manual regression (current)*

### Fast smoke (10–15 min)

| Test ID        | Result  | Date       | Description                          | Notes |
|----------------|---------|------------|--------------------------------------|-------|
| TC-054         | Pass    | 2026-03-09 | CoS chat persistence                 | Daily Briefing and AM Sweep persistence verified in current runtime pass |
| TC-055         | Pass    | 2026-03-09 | CoS preferences affect responses     | Preferences were reflected in CoS planning output |
| TC-057         | Pass    | 2026-03-09 | CoS tool loop (WEB_SEARCH / DOC_SEARCH) | Both web research and doc search behaved correctly in current runtime pass |
| TC-058         | Pass    | 2026-03-09 | CoS task capture                     | Worked end-to-end; observed slow runtime (~20-30s for a single task) |
| TC-059         | Pass    | 2026-03-09 | CoS structured memory                | CoS recalled previously stated preference during same chat |
| TC-COS-001     | Pass    | 2026-03-09 | Delegation command + board visibility | Chat-created assignment appeared correctly in board/details |
| TC-COS-004     | Pass    | 2026-03-09 | Open assignee chat routing           | Current runtime pass: routing/focus worked |
| TC-COS-005     | Pass    | 2026-03-09 | Create assignment manually from board | Manual board-created assignment appeared correctly in list/details |
| TC-COS-006     | Pass    | 2026-03-09 | Single assignment task bridge        | Assignment created one dashboard task and duplicate protection worked |
| TC-COS-007     | Pass    | 2026-03-09 | Bulk board action                    | Filtered bulk action worked and persisted correctly |
| TC-COS-010     | Pass    | 2026-03-09 | Assignment health filter             | Health filters and badges behaved correctly in current runtime pass |
| TC-COS-011     | Pass    | 2026-03-09 | Bulk reassign with optional note     | Reassignment, routing continuity, and event note all worked |
| TC-COS-012     | Pass    | 2026-03-09 | Bulk create tasks from filtered assignments | Worked perfectly; counts and duplicate handling looked correct |
| TC-COS-013     | Pass    | 2026-03-09 | CoS bulk command open-mode semantics | Manual pass looked correct; deterministic count/open-mode logic is also automated |
| TC-056         | Pass    | 2026-03-09 | CoS calendar read-only context       | Read-only context worked and degraded safely; separate accuracy bug remains logged (late-night/local-day window issue) |

### Current CoS / Delegation test cases

| Test ID        | Result  | Date       | Description                               | Notes |
|----------------|---------|------------|-------------------------------------------|-------|
| TC-COS-001     | Pass    | 2026-03-09 | Create assignment from CoS chat           | Re-verified in current runtime pass |
| TC-COS-002     | Pass    | 2/24/26    | Update assignment fields from CoS chat    |       |
| TC-COS-003     | Pass    | 2/24/26    | Reassign assignment from CoS chat         |       |
| TC-COS-004     | Pass    | 2026-03-09 | Open assignee chat from board             | Re-tested in current runtime pass; correct assignee tab routing/focus worked |
| TC-COS-005     | Pass    | 2026-03-09 | Create assignment manually from board     | Re-verified in current runtime pass |
| TC-COS-006     | Pass    | 2026-03-09 | Single assignment task bridge             | Re-verified in current runtime pass |
| TC-COS-011     | Pass    | 2026-03-09 | Bulk reassign with optional note          | Re-verified in current runtime pass |
| TC-COS-012     | Pass    | 2026-03-09 | Bulk create tasks from filtered assignments | Re-verified in current runtime pass |
| TC-COS-013     | Pass    | 2026-03-09 | CoS bulk command open-mode semantics      | Re-verified in current runtime pass |
| TC-COS-007     | Pass    | 2/24/26    | Bulk status update with optional note     |       |
| TC-COS-008     | Pass    | 2/24/26    | Bulk priority update with optional note   |       |
| TC-COS-009     | Pass    | 2/24/26    | Bulk due update with optional note        |       |
| TC-COS-010     | Pass    | 2/24/26    | Assignment health filter + badges         |       |
| TC-COS-011     | Pass    | 2/24/26    | Bulk reassign with optional note           |       |
| TC-COS-012     | Pass    | 2/24/26    | Bulk create tasks from filtered assignments |       |
| TC-COS-013     | Pass    | 2/24/26    | CoS bulk command open-mode semantics      |       |
| TC-055         | Pass    | 2026-03-09 | CoS preferences affect responses        | Re-verified in current runtime pass |
| TC-057         | Pass    | 2026-03-09 | CoS tool loop (WEB_SEARCH / DOC_SEARCH)  | Re-verified in current runtime pass |
| TC-059         | Pass    | 2026-03-09 | CoS structured memory                   | Re-verified in current runtime pass |
| TC-COS-014     | Pass    | 2/24/26    | Due-date validation (chat and UI)          |       |
| TC-COS-015     | Pass    | 2026-03-09 | AM Sweep reuse / persistence              | Existing daily sweep chat reused successfully |
| TC-COS-016     | Pass    | 2026-03-09 | AM Sweep rerun                             | `AM Sweep (Run again)` produced fresh output |
| TC-COS-017     | Pass    | 2026-03-09 | Assignment status lifecycle from board     | `Start`, `Awaiting Review`, `Block`, `Done`, `Reopen` all worked |
| TC-COS-018     | Pass    | 2026-03-09 | Task refresh after CoS / assignment actions | Dashboard and Tasks reflected new tasks without manual refresh |
| TC-COS-019     | Pass    | 2026-03-09 | CoS timing logs                            | Timing entries present in `logs/app.log` |

## Deep Research (web) regression

*Ref: testing.md § Deep Research test cases*

| Test ID   | Result  | Date | Description                         | Notes |
|-----------|---------|------|-------------------------------------|-------|
| TC-DR-001 | Pass    | 2026-03-09 | Deep Research — iterative web research run (round/status updates visible) | Run completed and behaved correctly in current runtime pass |
| TC-DR-002 | Pass    | 2026-03-09 | Deep Research — generate final brief (also writes `data/artifacts/<run_id>/research_brief.md`) | Final brief generated and artifact file written successfully |

---

## Billing regression

*Ref: testing.md § Billing test cases*

| Test ID     | Result  | Date | Description                                      | Notes |
|-------------|---------|------|--------------------------------------------------|-------|
| TC-BILL-001 | Pass    | 2026-03-09 | Billing — manual time entry                      | Manual timer/start-stop save flow worked and entry appeared correctly |
| TC-BILL-002 | Fail    | 2026-03-09 | Billing — template + invoice draft generation    | Draft generation worked, but template/output is not readable or acceptable yet |
| TC-BILL-003 | Pass    | 2026-03-09 | Billing — monthly autorun prompt + idempotency   | Manual prompt behavior passed; idempotency should also be covered by automation |

---

## Legacy manual catalog

*Ref: testing.md § Legacy manual catalog. These are archived reference cases rather than the active release gate.*

### Dashboard tab

| Test ID | Result  | Date       | Description                 | Notes |
|---------|---------|------------|-----------------------------|-------|
| TC-001  | Pass    | 2026-03-09 | Dashboard task list display | Dashboard task list rendered correctly and existing tasks were visible/readable |
| TC-002  | Pass    | 2026-03-07 | Dashboard task completion   | Done-column checkbox works; task status updates correctly |
| TC-003  | Pass    | 2026-03-10 | Dashboard schedule display   | Today's events displayed with readable formatted times |
| TC-004  | Pass    | 2026-03-10 | Dashboard news feed          | Feed items loaded and displayed cleanly |
| TC-005  | Skip    | 2026-03-10 | Dashboard auto-refresh       | No visible refresh observed in short runtime; dashboard remained stable. Test case likely stale/impractical for normal manual pass because documented timers are 15 min / 1 hour |

### Workspace tab

| Test ID | Result  | Date       | Description                  | Notes |
|---------|---------|------------|------------------------------|-------|
| TC-006  | Pass    | 2026-03-10 | Workspace file tree           | File tree displayed correctly and behaved normally |
| TC-007  | Pass    | 2026-03-10 | Workspace document preview    | Selected document loaded and displayed readably in preview pane |
| TC-008  | Pass    | 2026-03-10 | Workspace analysis tools      | Generate Draft workflow ran successfully and returned sensible output |

### Note-taking system

| Test ID | Result  | Date       | Description              | Notes |
|---------|---------|------------|--------------------------|-------|
| TC-009  | Pass    | 2026-03-10 | Context setting          | Rerun passed after legacy notes-schema fix and notes-tab redesign; context is now displayed as the active document |
| TC-010  | Pending |            | Note formatting          |       |
| TC-011  | Pending |            | Dynamic categorization   |       |
| TC-012  | Pending |            | Export functionality     |       |
| TC-013  | Pending |            | Robust JSON parsing      |       |
| TC-014  | Pending |            | Thread-safe UI updates   |       |
| TC-015  | Pending |            | Notes session routing    |       |

### Chat and task management

| Test ID | Result  | Date       | Description                          | Notes |
|---------|---------|------------|--------------------------------------|-------|
| TC-015  | Pending |            | Chat response (duplicate ID in source) |       |
| TC-016  | Pending |            | Chat search                          |       |
| TC-017  | Pending |            | Daily briefing                       |       |
| TC-018  | Pending |            | Add task from chat                   |       |
| TC-019  | Pending |            | Add multiple tasks from chat         |       |

### Task list

| Test ID | Result  | Date       | Description                        | Notes |
|---------|---------|------------|------------------------------------|-------|
| TC-020  | Pending |            | Task list edit button              |       |
| TC-021  | Pending |            | Task list delete button            |       |
| TC-022  | Pending |            | Task list archive completed        |       |
| TC-023  | Pending |            | Task list persistence              |       |
| TC-024  | Pending |            | Task list visibility in briefing   |       |

### Tasks tab (local)

| Test ID | Result  | Date       | Description                      | Notes |
|---------|---------|------------|----------------------------------|-------|
| TC-045  | Pass    | 2026-03-09 | Tasks tab initialization        | Search/filters, quick-add row, and local task table rendered correctly |
| TC-046  | Pass    | 2026-03-09 | Tasks tab quick add              | Quick-add worked and task appeared correctly |
| TC-047  | Pass    | 2026-03-09 | Tasks tab complete/undo + delete | Complete/undo/delete flow worked correctly |

### Leads tab

| Test ID | Result  | Date       | Description                     | Notes |
|---------|---------|------------|---------------------------------|-------|
| TC-025  | Pass    | 2026-03-09 | Leads run search                | Grok returned verifiable leads; table populated with score/status and stored leads had sources |
| TC-026  | Pass    | 2026-03-09 | Leads settings editing          | Settings persisted and affected the next lead search |
| TC-027  | Pass    | 2026-03-09 | Leads view message              | View Message dialog opened and Copy worked correctly after fix |
| TC-028  | Pass    | 2026-03-09 | Leads delete                    | Lead deleted successfully from the UI during manual regression pass |
| TC-029  | Pass    | 2026-03-09 | Leads sources/evidence viewer   | Sources dialog opened correctly and evidence/links were usable |
| TC-030  | Pass    | 2026-03-09 | Leads LinkedIn hyperlink        | LinkedIn hyperlink opened/worked correctly |
| TC-031  | Pass    | 2026-03-09 | Leads contacted checkbox and date | Contacted checkbox, date stamp, and hide/show behavior worked |

### Chief of Staff tab

This legacy subsection is superseded by the active `Chief of Staff + Executive Team Regression` section above. Do not duplicate status updates here.

### Workspace document generation

| Test ID | Result  | Date       | Description                    | Notes |
|---------|---------|------------|---------------------------------|-------|
| TC-032  | Pass    | 2026-03-09 | Workspace document/file addition | File was added successfully and appeared in the Workspace list |
| TC-033  | Pending |            | Workspace file removal/deletion  |       |
| TC-034  | Pass    | 2026-03-09 | Workspace document output        | Draft generation, `Export as...`, and `Save Markdown` worked; buttons lacked clear visual enabled-state change |

### Meetings tab

| Test ID | Result  | Date       | Description                   | Notes |
|---------|---------|------------|-------------------------------|-------|
| TC-035  | Pass    | 2026-03-09 | Meetings start recording      | Recording started successfully and the UI reflected active recording state |
| TC-036  | Pass    | 2026-03-09 | Meetings stop recording       | Recording stopped, audio was saved locally, and recorded audio was automatically sent for transcription |
| TC-037  | Pass    | 2026-03-09 | Meetings generate transcript  | Transcript generation completed successfully and appeared in the transcript pane |
| TC-038  | Pass    | 2026-03-09 | Meetings load file            | Audio/media file loaded successfully and the UI reflected readiness for transcription |
| TC-039  | Pass    | 2026-03-09 | Meetings save transcript     | Transcript saved successfully to disk |

### Compliance tab

| Test ID | Result  | Date       | Description                         | Notes |
|---------|---------|------------|-------------------------------------|-------|
| TC-040  | Pass    | 2026-03-09 | Compliance upload documents/URLs    | Document/URL added successfully to the first column |
| TC-041  | Pass    | 2026-03-09 | Compliance remove/delete document  | Document/URL removed successfully from the first column |
| TC-042  | Pass    | 2026-03-09 | Compliance run compliance check    | Passed after compliance pipeline fixes; results rendered successfully in the results pane |
| TC-043  | Pass    | 2026-03-09 | Compliance save report             | Report saved successfully in a readable format (`.txt`/`.docx`) |
| TC-044  | Fail    | 2026-03-09 | Compliance link to CRM             | No CRM linkage occurred; current handler is a placeholder/TBD rather than a working integration |

---

## How to use

1. Run the test (manual or automated) as described in [testing.md](testing.md).
2. In this file, set **Result** to `Pass`, `Fail`, `Skip`, or `Pending`.
3. Set **Date** to the run date (YYYY-MM-DD).
4. Optionally add a short **Notes** line for that run (e.g., "Fail: calendar token missing", "56 passed").
5. For automated suites, record the overall outcome and date in the *Automated test runs* table.

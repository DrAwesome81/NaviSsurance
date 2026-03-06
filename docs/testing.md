# NaviSsurance Testing

## Automated tests (recommended first)

- Full unit suite:
  - `python -m pytest -q`
- Focused suites:
  - `python -m pytest tests/test_chief_of_staff.py -q`
  - `python -m pytest tests/test_workflow_engine.py -q`

### Optional UI test flags
- Qt/UI tests are disabled by default:
  - `set RUN_QT_TESTS=1` (Windows)
  - `export RUN_QT_TESTS=1` (macOS/Linux)

## Chief of Staff + Executive Team Manual Regression (Current)

Last revised: 2026-02-23

### Prerequisites

- Grok/xAI access:
  - Set `XAI_API_KEY` or `GROK_API_KEY` and ensure `xai-sdk` is available.
- Daily briefing toggle:
  - Set `BRIEFING_AND_EMAIL_DISABLED=0` (or unset) in `config/.env`.
- Google Calendar:
  - Token file `config/navi_token.pkl` present for calendar-aware tests.
  - Missing token should degrade gracefully (no crash, no auth popup).
- Optional document RAG:
  - `COS_ENABLE_RAG_SEARCH=1` and available index for semantic retrieval checks.

### Deep Research (web) prerequisites
- Web research requires OpenAI access:
  - Set `OPENAI_API_KEY` so `core/tools/web_research.py` can call ChatGPT via the Responses API hosted `web_search` tool (with a fallback to non-browsing ChatGPT if needed).

### Fast smoke (10–15 min)

- CoS chat persistence (`TC-054`)
- CoS task capture (`TC-058`)
- Delegation command + board visibility (`TC-COS-001`)
- Open assignee chat routing (`TC-COS-004`)
- Bulk board action (`TC-COS-007`)
- Assignment health filter (`TC-COS-010`)

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

#### TC-COS-014: Due-date validation (chat and UI)
- Steps:
  1. Try invalid dates like `2026-02-30` in CoS due commands and board due dialogs.
- Expected:
  - Invalid dates are rejected; existing data remains unchanged.

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

### Automated test commands (recommended)

- Focused CoS suite:
  - `python -m pytest tests/test_chief_of_staff.py -q`
- Additional memory/DB smoke:
  - `python -m pytest tests/test_cos_memory.py tests/test_db.py -q`

---

## Legacy manual catalog (historical)

Dashboard Tab Tests (NEW - IMPLEMENTED)
TC-001: Dashboard Task List Display

Description: Verify the dashboard displays tasks correctly with interactive functionality.
Steps:
Open NaviSsurance (interface.py).
Navigate to Dashboard Tab.
Check if task list displays existing tasks.
Verify task text wrapping and formatting.

Expected Result: Tasks display properly without early text wrapping, with clean formatting.
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

TC-002: Dashboard Task Completion

Description: Verify double-clicking tasks marks them as complete.
Steps:
Open NaviSsurance (interface.py).
Navigate to Dashboard Tab.
Double-click on a task in the task list.
Check if task status updates.

Expected Result: Task is marked complete and removed from active list.
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

TC-003: Dashboard Schedule Display

Description: Verify Google Calendar integration displays today's events.
Steps:
Open NaviSsurance (interface.py).
Navigate to Dashboard Tab.
Check schedule window for today's events.
Verify time formatting (e.g., "9:15 AM" vs raw timestamps).

Expected Result: Events display with formatted times, no visible markup.
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

TC-004: Dashboard News Feed

Description: Verify AI-powered news feed with hyperlinks and persistence.
Steps:
Open NaviSsurance (interface.py).
Navigate to Dashboard Tab.
Check news feed for MedTech industry news.
Verify hyperlinks are clickable.
Set “Hide repeats” to 2 days (or another value) and click Refresh News.
Refresh again and verify recently shown items are suppressed (do not immediately repeat).
Check for duplicate prevention (tracking params / same title across sources).

Expected Result: News displays with clickable links, deduped items, and repeat suppression respects the “Hide repeats” setting. Items persist for ~7 days.
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

TC-005: Dashboard Auto-refresh

Description: Verify automatic refresh timers for schedule and news.
Steps:
Open NaviSsurance (interface.py).
Navigate to Dashboard Tab.
Wait for auto-refresh timers (15 min schedule, 1 hour news).
Verify updates occur automatically.

Expected Result: Schedule and news refresh automatically without manual intervention.
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

Workspace Tab Tests (NEW - IMPLEMENTED)
TC-006: Workspace File Tree

Description: Verify Dropbox file tree displays correctly in left panel.
Steps:
Open NaviSsurance (interface.py).
Navigate to Workspace Tab.
Check left panel for Dropbox file tree.
Verify file filtering and search functionality.

Expected Result: File tree displays with search and filtering capabilities.
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

TC-007: Workspace Document Preview

Description: Verify document preview functionality in center panel.
Steps:
Open NaviSsurance (interface.py).
Navigate to Workspace Tab.
Select a document from file tree.
Check center panel for document preview.

Expected Result: Document preview displays correctly for various formats (PDF, DOCX, TXT).
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

TC-008: Workspace Generate Draft Workflow

Description: Verify the single `Generate Draft` workflow starts correctly and reports progress/status.
Steps:
Open NaviSsurance (interface.py).
Navigate to Workspace Tab.
Add one or more files (or a folder via `Add Folder…`) and mark them in scope.
Click `Generate Draft`.
When prompted, cancel once and confirm the workflow exits cleanly.
Run again with a valid prompt and verify round/status updates.

Expected Result: `Generate Draft` starts collaboration, updates panes/status, and shows completion with context coverage note.
Actual Result: [Pending: Re-test on current Workspace], 2026-02-25.
Status: Pending

TC-008b: Workspace Extract Suggested Tasks

Description: Verify `Extract Suggested Tasks…` parses the importable section and inserts tasks only after review.
Steps:
Open NaviSsurance (interface.py).
Navigate to Workspace Tab.
Generate a draft that includes:
`## Suggested Tasks (importable)`
with at least 2 task lines.
Click `Extract Suggested Tasks…`.
Uncheck 1 task, edit 1 due date, click `Apply`.

Expected Result: Only checked tasks are inserted into SQLite tasks; edited fields persist; cancelled import creates nothing.
Actual Result: [Pending], 2026-02-27.
Status: Pending

Note-Taking System Tests
TC-009: Context Setting

Description: Verify the note-taking system allows setting context for note sessions.
Steps:
Open NaviSsurance (interface.py).
Navigate to Note-Taking System.
Enter context in context input field (e.g., "Working on FDA submission for new diagnostic device").
Press Enter.

Expected Result: Context is set and displayed in notes pane.
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

TC-010: Note Formatting

Description: Verify AI properly formats user notes for clarity and professionalism.
Steps:
Open NaviSsurance (interface.py).
Navigate to Note-Taking System.
Enter a raw note (e.g., "need to check section 5").
Press Enter to process.

Expected Result: Note is formatted professionally and displayed in notes pane.
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

TC-011: Dynamic Categorization

Description: Verify notes are automatically categorized when 2 or more notes exist.
Steps:
Open NaviSsurance (interface.py).
Navigate to Note-Taking System.
Add first note (e.g., "Review ISO 13485 requirements").
Add second note (e.g., "Check FDA guidance documents").

Expected Result: Notes are categorized into logical groups and displayed under category headings.
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

TC-012: Export Functionality

Description: Verify notes can be exported to DOCX format with Save As dialog.
Steps:
Open NaviSsurance (interface.py).
Navigate to Note-Taking System.
Add several notes with context.
Click "Export Notes" button.
Verify Save As dialog opens with default filename "notes_export.docx".
Choose location and filename (or use default).
Check generated DOCX file.

Expected Result: Save As dialog opens, DOCX file is created with context and notes as bullet points, success message displays file path.
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

TC-013: Robust JSON Parsing

Description: Verify system handles malformed or non-JSON AI responses gracefully.
Steps:
Open NaviSsurance (interface.py).
Navigate to Note-Taking System.
Add a note that triggers AI response with formatting issues (extra text, trailing commas, etc.).
Verify note is still processed correctly.

Expected Result: System uses robust JSON parsing with multiple fallback strategies, note is formatted and displayed correctly.
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

TC-014: Thread-Safe UI Updates

Description: Verify UI updates from background threads are handled safely.
Steps:
Open NaviSsurance (interface.py).
Navigate to Note-Taking System.
Rapidly add multiple notes.
Verify UI updates correctly without crashes or race conditions.

Expected Result: All notes are displayed correctly, no UI freezing or crashes, thread-safe updates via QTimer.
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

TC-015: Notes Session Routing

Description: Verify Notes tab bypasses task/news/!search routing.
Steps:
Open NaviSsurance (interface.py).
Navigate to Note-Taking System.
Add a note that might trigger task detection (e.g., contains "task" keyword).
Verify note is processed as a note, not routed to task handler.

Expected Result: Note is formatted and added to notes list, not processed as a task.
Actual Result: [Pending: Test not run], 2025-08-11.
Status: Pending

Chat and Task Management Tests
TC-015: Chat Response

Description: Verify chat functionality responds to user input.
Steps:
Open NaviSsurance (interface.py).
Type a message in chat (e.g., "Hello, Navi").

Expected Result: Navi responds with relevant text.
Actual Result: Pass: Navi responded, 2025-05-30.
Status: Pass

TC-016: Chat Search

Description: Verify chat performs a requested web search.
Steps:
Open NaviSsurance (interface.py).
Ask Navi a question requiring a web search (e.g., "What's in the news today?").

Expected Result: Navi performs search and provides accurate information.
Actual Result: Pass: Search performed, accurate information provided, 2025-05-30.
Status: Pass

TC-017: Daily Briefing

Description: Verify Navi provides a daily briefing.
Steps:
Open NaviSsurance (interface.py).
If daily briefing is disabled, set `BRIEFING_AND_EMAIL_DISABLED=0` (or unset) in `config/.env`, restart, and retry.

Email Fetching Configuration (Folders/Labels)

Email fetching runs as part of the daily briefing (and is capped to the last 7 days).
You can configure which folders/labels are included via environment variables in `config/.env`:
- `EMAIL_GMAIL_LABELS`: comma-separated Gmail labels to include. Use `INBOX` to include inbox.
  - Example: `EMAIL_GMAIL_LABELS=INBOX,News`
- `EMAIL_YAHOO_FOLDERS`: comma-separated IMAP folder names (Yahoo). Default: `INBOX`
  - Example: `EMAIL_YAHOO_FOLDERS=INBOX,Clients,Leads`
- `EMAIL_OUTLOOK_FOLDERS`: comma-separated folder names (best-effort via EWS). Default: `INBOX`
  - Example: `EMAIL_OUTLOOK_FOLDERS=INBOX,Clients,Leads`

Email Filtering Configuration (Client/Potential)

Unreplied emails are shown when they’re marked as client or potential-lead emails. You can configure this via `config/.env`:
- `EMAIL_CLIENT_DOMAINS`: comma-separated sender domains treated as clients (default includes `goldbugstrategies.com,dovahealth.ca`)
- `EMAIL_POTENTIAL_DOMAINS`: comma-separated sender domains treated as potential leads
- `EMAIL_CLIENT_LABELS`: comma-separated labels/folders treated as client mail (default `Clients,Client`)
- `EMAIL_POTENTIAL_LABELS`: comma-separated labels/folders treated as lead mail (default `Leads,Lead`)
Ask Navi via chat for the daily briefing (or use the Dashboard briefing widget if present).

Expected Result: Briefing includes tasks, meetings, emails, and a `[SECTION:News]` section (deduped/suppressed). If calendar/email credentials are missing, it degrades gracefully (no crash).
Actual Result: [Pending: Re-test on current Workspace], 2026-02-22.
Status: Pending

TC-018: Add Task from Chat

Description: Verify Navi adds a single task via chat.
Steps:
Open NaviSsurance (interface.py).
Ask Navi to add a task (e.g., "Add a task to go grocery shopping on Thursday").

Expected Result: Task is added to the task list with correct text and date.
Actual Result: Pass: Task added correctly, 2025-06-02.
Status: Pass

TC-019: Add Multiple Tasks from Chat

Description: Verify Navi adds multiple tasks from a single chat request.
Steps:
Open NaviSsurance (interface.py).
Ask Navi to add two tasks (e.g., "Remind me to call the office on Monday, and call the accountant on Wednesday").
Repeat with three or more tasks.

Expected Result: All tasks are parsed and added as separate items to the task list.
Actual Result: Fail: Only first task added, 2025-06-03 (Issue #19).
Status: Fail

Task List Tests
TC-020: Task List Edit Button

Description: Verify editing a task via the edit button.
Steps:
Open NaviSsurance (interface.py).
Navigate to Task List.
Add a task (e.g., "Meeting Monday").
Click "Edit" button, modify text (e.g., "Meeting Tuesday").

Expected Result: Task updates with new text in task list.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-021: Task List Delete Button

Description: Verify deleting a task via the delete button.
Steps:
Open NaviSsurance (interface.py).
Navigate to Task List.
Add a task.
Click "Delete" button.

Expected Result: Task is removed from task list.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-022: Task List Archive Completed Tasks Button

Description: Verify archiving completed tasks.
Steps:
Open NaviSsurance (interface.py).
Navigate to Task List.
Add a task, mark as completed.
Click "Archive Completed Tasks" button.

Expected Result: Completed task is archived, removed from active list.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-023: Task List Persistence Session-to-Session

Description: Verify tasks persist across sessions.
Steps:
Open NaviSsurance (interface.py).
Add a task to Task List.
Close and reopen NaviSsurance.

Expected Result: Task remains in task list.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-024: Task List Visibility for Daily Briefing

Description: Verify tasks are visible in daily briefing.
Steps:
Open NaviSsurance (interface.py).
Add a task to Task List.
Request daily briefing via chat.

Expected Result: Task appears in briefing output.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

Tasks Tab (Local) Tests

TC-045: Tasks Tab Initialization

Description: Verify Tasks tab initializes and renders a local task table.
Steps:
Open NaviSsurance (interface.py).
Navigate to Tasks Tab.

Expected Result: Search/filters + quick-add row + task table are visible.
Status: Pending

TC-046: Tasks Tab Quick Add

Description: Verify adding a task persists to SQLite and appears in the table.
Steps:
Open Tasks Tab.
Enter a new task and click Add.

Expected Result: Task is added to SQLite (`tasks` table) and appears in the list.
Status: Pending

TC-047: Tasks Tab Complete/Undo + Delete

Description: Verify completion toggling and deletion work.
Steps:
Create a task in Tasks Tab.
Click Complete, then Undo.
Click Delete and confirm.

Expected Result: Completion toggles update the row; deletion removes it.
Status: Pending

Leads Tab Tests
TC-025: Leads Tab Run Search Function

Description: Verify running a lead search.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Click "Run Search" button.

Expected Result:
- Grok returns verifiable leads and the app stores them in SQLite.
- Leads table populates with Score/Status and each stored lead has **Sources** available.
- Leads without sources are not stored.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-026: Leads Tab Settings Editing

Description: Verify editing lead search settings.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Modify settings (e.g., industry filter).
Save settings.
Run Search again.

Expected Result: Settings persist to `config/lead_gen_config.json` and affect the next lead search results.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-027: Leads Tab View Message Functionality

Description: Verify viewing a lead's message.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Click "View Message" for a lead.
Click “Copy”.

Expected Result: Personalized LinkedIn message displays and can be copied to clipboard.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-028: Leads Tab Delete Button Functionality

Description: Verify deleting a lead.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Click "Delete" button for a lead.

Expected Result: Lead is removed from the UI and deleted from the SQLite `leads` table.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-029: Leads Tab Sources/Evidence Viewer

Description: Verify viewing a lead's evidence sources and signals.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Click "Sources" for a lead.

Expected Result: A dialog shows signals + clickable sources (URLs). openFDA 510(k) query URL may appear when enrichment found matches.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-030: Leads Tab Hyperlink to LinkedIn Profile

Description: Verify LinkedIn profile hyperlink functionality.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Click the lead Name (row 0, column “Name”).

Expected Result: Browser opens to the lead's LinkedIn profile URL (if present).
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-031: Leads Tab Contacted Checkbox and Date Stamp

Description: Verify marking a lead as contacted.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Check "Contacted" box for a lead.
Toggle “Hide contacted” and verify the row hides/shows.

Expected Result: Lead is marked contacted with a date stamp, status updates to contacted, and filtering works.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

Chief of Staff Tab Tests

TC-054: Chief of Staff — New Chat + Persistence

Description: Verify CoS chat creation, persistence, and sidebar navigation.
Steps:
Open NaviSsurance.
Navigate to Chief of Staff tab.
Click “New chat”.
Send a message (e.g., “I’m working on client X; help me prioritize.”).
Close and reopen the app.
Return to Chief of Staff tab and click the chat in the sidebar.

Expected Result: Chat is saved and reloads with the previous messages.
Actual Result: [Pending: Test not run], 2026-02-22.
Status: Pending

TC-055: Chief of Staff — Preferences Affect Responses

Description: Verify CoS preferences are saved and used as context.
Steps:
Open Chief of Staff tab.
Open Options → Preferences.
Set deep work hours and add a constraint (e.g., “No meetings before 10am; family time 5–8pm”).
Save.
Ask CoS for a plan for today.

Expected Result: Response references the saved constraints (without taking autonomous actions).
Actual Result: [Pending: Test not run], 2026-02-22.
Status: Pending

TC-056: Chief of Staff — Calendar Read-Only Context (token present vs missing)

Description: Verify calendar-aware planning is read-only and degrades gracefully.
Steps:
If `config/navi_token.pkl` exists, ask: “What meetings do I have today?”
If it does not exist, ask the same question.

Expected Result:
- With token: CoS includes today’s schedule and upcoming week context in its advice.
- Without token: CoS reports calendar unavailable (no crash, no OAuth popups).
Actual Result: [Pending: Test not run], 2026-02-22.
Status: Pending

TC-057: Chief of Staff — Tool Loop (WEB_SEARCH / DOC_SEARCH)

Description: Verify CoS can use read-only tools when needed.
Steps:
Ask a question that should require web research (e.g., “What’s the latest FDA update on PCCP this month?”).
Ask a question that should require doc search (e.g., “What did our docs say about unified search?”).

Expected Result: CoS either answers directly or triggers tool use internally and returns an answer grounded in results. No side effects.
Actual Result: [Pending: Test not run], 2026-02-22.
Status: Pending

TC-058: Chief of Staff — Task Capture from CoS (`ADD_TASK`)

Description: Verify CoS can add tasks to the dashboard task list.
Steps:
In Chief of Staff tab, ask: “Add a task to follow up with Acme next Tuesday.”
Go to Dashboard → Task List and verify the task exists.

Expected Result: CoS inserts a task via `ADD_TASK` and it appears in the main tasks table.
Actual Result: [Pending: Test not run], 2026-02-22.
Status: Pending

TC-059: Chief of Staff — Structured Memory (facts/tags/open loops)

Description: Verify memory is extracted and can be recalled later.
Steps:
In a CoS chat, state a stable preference (e.g., “I prefer deep work before noon.”).
Continue conversation for 2–3 turns.
Later in the same chat, ask: “What preference did I mention about deep work?”

Expected Result: CoS recalls the preference (from structured memory) without you repeating it.
Actual Result: [Pending: Test not run], 2026-02-22.
Status: Pending

Document Generation Tab Tests
TC-032: Document Generation Tab Document Upload/URL Addition

Description: Verify uploading a document or adding a URL.
Steps:
Open NaviSsurance (interface.py).
Navigate to Document Generation Tab.
Upload a PDF or enter a URL (e.g., "https://www.fda.gov").

Expected Result: Document/URL is added to the tab.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

TC-033: Document Generation Tab Document Removal/Deletion

Description: Verify removing a document or URL.
Steps:
Open NaviSsurance (interface.py).
Navigate to Document Generation Tab.
Upload a PDF or add a URL.
Click "Remove" or "Delete" button.

Expected Result: Document/URL is removed from the tab.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

TC-034: Document Generation Tab Document Output

Description: Verify generating a document output.
Steps:
Open NaviSsurance (interface.py).
Navigate to Document Generation Tab.
Upload a PDF or add a URL.
Click "Generate Output".

Expected Result: Grok generates a PDF/JSON report based on input.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

Meetings Tab Tests
TC-035: Meetings Tab Start Recording

Description: Verify starting a meeting recording.
Steps:
Open NaviSsurance (interface.py).
Navigate to Meetings Tab.
Click "Start Recording".

Expected Result: Recording begins, indicated in UI.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-036: Meetings Tab Stop Recording

Description: Verify stopping a meeting recording.
Steps:
Open NaviSsurance (interface.py).
Navigate to Meetings Tab.
Start recording, then click "Stop Recording".

Expected Result: Recording stops, file saved locally.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-037: Meetings Tab Generate Transcript

Description: Verify generating a meeting transcript.
Steps:
Open NaviSsurance (interface.py).
Navigate to Meetings Tab.
Record a short meeting or upload audio.
Click "Generate Transcript".

Expected Result: AssemblyAI generates speaker-separated transcript.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-038: Meetings Tab Load File

Description: Verify loading an audio file for transcription.
Steps:
Open NaviSsurance (interface.py).
Navigate to Meetings Tab.
Click "Load File", select an audio file (e.g., meeting.wav).

Expected Result: File loads in UI for transcription.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-039: Meetings Tab Save Transcript

Description: Verify saving a meeting transcript.
Steps:
Open NaviSsurance (interface.py).
Navigate to Meetings Tab.
Generate a transcript.
Click "Save Transcript".

Expected Result: Transcript saved to database with client metadata.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

Compliance Tab Tests
TC-040: Compliance Tab Upload Documents/URLs

Description: Verify uploading documents or URLs in Compliance Tab.
Steps:
Open NaviSsurance (interface.py).
Navigate to Compliance Tab.
Upload a PDF (e.g., SOP.pdf) or enter a URL (e.g., "https://www.ecfr.gov").

Expected Result: Document/URL added to first column.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

TC-041: Compliance Tab Remove/Delete Document or URL

Description: Verify removing a document or URL.
Steps:
Open NaviSsurance (interface.py).
Navigate to Compliance Tab.
Upload a PDF or add a URL.
Click "Remove" or "Delete".

Expected Result: Document/URL removed from first column.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

TC-042: Compliance Tab Run Compliance Check

Description: Verify running a compliance check.
Steps:
Open NaviSsurance (interface.py).
Navigate to Compliance Tab.
Upload a PDF or add a URL.
Click "Run Compliance Check".

Expected Result: Grok returns JSON ([{section, issue, fix, reference}]) in third column.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

TC-043: Compliance Tab Save Report

Description: Verify saving a compliance report.
Steps:
Open NaviSsurance (interface.py).
Navigate to Compliance Tab.
Run a compliance check.
Click "Save Report".

Expected Result: Report saved as PDF/JSON to database.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

TC-044: Compliance Tab Link to CRM

Description: Verify linking compliance results to CRM.
Steps:
Open NaviSsurance (interface.py).
Navigate to Compliance Tab.
Run a compliance check.
Click "Link to CRM".

Expected Result: Results linked to client record in database ({client_id, issues}).
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

Traceability

Test Case
User Story (requirements.md)

TC-001, TC-002, TC-003, TC-004, TC-005
Dashboard Tab

TC-006, TC-007, TC-008
Workspace Tab

TC-009, TC-010, TC-011, TC-012, TC-013, TC-014, TC-015
Note-Taking System

TC-015, TC-016, TC-017, TC-018, TC-019
Chat and Task Management

TC-020, TC-021, TC-022, TC-023, TC-024
Task Management

TC-025, TC-026, TC-027, TC-028, TC-029, TC-030, TC-031
Lead Generation

TC-054, TC-055, TC-056, TC-057, TC-058, TC-059
Chief of Staff

TC-032, TC-033, TC-034
Document Generation

TC-035, TC-036, TC-037, TC-038, TC-039
Meeting Transcription

TC-040, TC-041, TC-042, TC-043, TC-044
Compliance Tab

TC-045, TC-046, TC-047, TC-048, TC-049, TC-050, TC-051, TC-052, TC-053
Tasks Tab (Local)

Notes

Tests are manual, executed via UI (interface.py) or scripts (e.g., fetch_all_emails.py).
Failures linked to GitHub Issues (e.g., #18, #19).
Update Actual Result and Status after testing, using ISO dates (YYYY-MM-DD).
New test cases (TC-054+) will be appended sequentially for future features (e.g., Chief of Staff, Lead Gen enhancements, Clinical Study Design).
Dashboard and Workspace tabs are newly implemented and require comprehensive testing.
Schedule display formatting has been improved to remove visible markup and improve readability.
News feed includes AI-powered query generation, duplicate prevention, and 7-day persistence.
Tasks are stored locally in SQLite and can be managed via Dashboard + Tasks tab. Optional UI automation can be enabled via `RUN_QT_TESTS=1`.



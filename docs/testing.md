NaviSsurance Testing
Test Cases

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
Check for duplicate prevention.

Expected Result: News displays with clickable links, no duplicates, 7-day persistence.
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

TC-008: Workspace Analysis Tools

Description: Verify right sidebar analysis tools function properly.
Steps:
Open NaviSsurance (interface.py).
Navigate to Workspace Tab.
Test compliance analysis, document chunking, and generation tools.
Verify tool outputs and status feedback.

Expected Result: Analysis tools function correctly with proper status feedback.
Actual Result: [Pending: Test not run], 2025-08-11.
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
Ask Navi via chat for the daily briefing.

Expected Result: Navi provides an update on tasks, meetings, and emails.
Actual Result: Fail: Error "ChatHandler.task_added_signal[str, str] signal has 2 argument(s) but 3 provided", 2025-06-02 (Issue #18).
Status: Fail

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

Tasks Tab - Vikunja Integration Tests (AUTOMATED - FULLY IMPLEMENTED)
TC-045: Tasks Tab Initialization

Description: Verify Tasks tab initializes correctly with all UI widgets.
Steps:
Open NaviSsurance (interface.py).
Navigate to Tasks Tab.
Check for connection panel, project selector, task creation panel, and task table.

Expected Result: All UI widgets are created and visible.
Actual Result: Pass: All widgets initialized correctly, 2025-01-XX.
Status: Pass (Automated Test)

TC-046: Tasks Tab Connection Testing

Description: Verify connection testing functionality.
Steps:
Open Tasks Tab.
Enter server URL.
Click "Test Connection" button.

Expected Result: Connection status updates with success/failure message.
Actual Result: Pass: Connection test logic verified, 2025-01-XX.
Status: Pass (Automated Test - 4 test cases)

TC-047: Tasks Tab Login

Description: Verify login functionality.
Steps:
Open Tasks Tab.
Enter URL, username, and password.
Click "Login" button.

Expected Result: User authenticated, projects loaded, buttons enabled.
Actual Result: Pass: Login flow verified, 2025-01-XX.
Status: Pass (Automated Test - 3 test cases)

TC-048: Tasks Tab Registration

Description: Verify user registration functionality.
Steps:
Open Tasks Tab.
Enter URL, username, email, and password.
Click "Register" button.

Expected Result: New account created, user logged in automatically.
Actual Result: Pass: Registration flow verified, 2025-01-XX.
Status: Pass (Automated Test - 3 test cases)

TC-049: Tasks Tab Project Management

Description: Verify project loading and creation.
Steps:
Open Tasks Tab.
Login successfully.
Click "Refresh" to load projects.
Click "New Project" to create project.

Expected Result: Projects display in dropdown, new projects can be created.
Actual Result: Pass: Project management verified, 2025-01-XX.
Status: Pass (Automated Test - 6 test cases)

TC-050: Tasks Tab Task Management

Description: Verify task loading, creation, editing, deletion, and status toggling.
Steps:
Open Tasks Tab.
Login and select a project.
Create a new task with title, priority, and estimated duration.
Verify all task fields are visible in table (description, dates, percent done, favorite, estimated duration).
Edit a task to update details.
Delete a task with confirmation.
Toggle task completion status.

Expected Result: Tasks display with all fields, can be created, edited, deleted, and updated.
Actual Result: Pass: Task management verified, 2025-01-XX.
Status: Pass (Automated Test - 13 test cases for basic operations, plus additional tests for editing/deletion)

TC-051: Tasks Tab Natural Language Task Creation

Description: Verify natural language task creation via chat window.
Steps:
Open Tasks Tab and login.
Ensure Tasks tab is active.
Type natural language task request in chat (e.g., "Add task to review FDA submission by next Friday, high priority, 2 hours").
Verify task is created with parsed details.

Expected Result: Task created in Vikunja with all parsed details (title, description, priority, due date, estimated duration).
Actual Result: Pass: Natural language parsing and task creation verified, 2025-01-XX.
Status: Pass (Automated Test - 13 test cases)

TC-052: Tasks Tab Task Field Visibility

Description: Verify all task fields are displayed in task table.
Steps:
Open Tasks Tab.
Login and select a project.
Load tasks.
Verify table shows: Title, Description, Priority, Due Date, Start Date, End Date, % Done, Done, Favorite, Estimated Duration, Actions.

Expected Result: All task fields are visible in table with proper formatting.
Actual Result: Pass: All fields displayed correctly, 2025-01-XX.
Status: Pass (Automated Test)

TC-053: Tasks Tab Estimated Duration

Description: Verify estimated duration input and storage.
Steps:
Open Tasks Tab.
Create a task with estimated duration (e.g., 90 minutes).
Edit the task and verify estimated duration is loaded.
Update estimated duration and save.
Verify estimated duration displays in task table.

Expected Result: Estimated duration is saved, loaded, and displayed correctly.
Actual Result: Pass: Estimated duration functionality verified, 2025-01-XX.
Status: Pass (Automated Test)

Note: All Tasks Tab tests (TC-045 through TC-053, 75 total test cases) are automated using pytest with mocking. Tests verify UI logic, error handling, user interactions, API integration, natural language task creation, task editing/deletion, and field visibility. VikunjaClient API is fully implemented and tested.

Leads Tab Tests
TC-025: Leads Tab Run Search Function

Description: Verify running a lead search.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Click "Run Search" button.

Expected Result: Claude generates JSON ({name, company, title, LinkedIn_url, rationale}).
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-026: Leads Tab Settings Editing

Description: Verify editing lead search settings.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Modify settings (e.g., industry filter).
Save settings.

Expected Result: Settings are updated and applied to next search.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-027: Leads Tab View Message Functionality

Description: Verify viewing a lead's message.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Click "View Message" for a lead.

Expected Result: Personalized LinkedIn message displays for copy/paste.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-028: Leads Tab Delete Button Functionality

Description: Verify deleting a lead.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Click "Delete" button for a lead.

Expected Result: Lead is removed from Leads Tab.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-029: Leads Tab View Rationale Functionality

Description: Verify viewing a lead's rationale.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Click "View Rationale" for a lead.

Expected Result: Rationale text displays explaining lead selection.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-030: Leads Tab Hyperlink to LinkedIn Profile

Description: Verify LinkedIn profile hyperlink functionality.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Click LinkedIn URL for a lead.

Expected Result: Browser opens to the lead's LinkedIn profile.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-031: Leads Tab Contacted Checkbox and Date Stamp

Description: Verify marking a lead as contacted.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Check "Contacted" box for a lead.

Expected Result: Lead is marked contacted with a date stamp in database.
Actual Result: [Pending: Test not run], 2025-06-03.
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

TC-032, TC-033, TC-034
Document Generation

TC-035, TC-036, TC-037, TC-038, TC-039
Meeting Transcription

TC-040, TC-041, TC-042, TC-043, TC-044
Compliance Tab

TC-045, TC-046, TC-047, TC-048, TC-049, TC-050, TC-051, TC-052, TC-053
Tasks Tab - Vikunja Integration (75 automated tests)

Notes

Tests are manual, executed via UI (interface.py) or scripts (e.g., fetch_all_emails.py), except Tasks Tab tests which are automated using pytest.
Failures linked to GitHub Issues (e.g., #18, #19).
Update Actual Result and Status after testing, using ISO dates (YYYY-MM-DD).
New test cases (TC-051+) will be appended sequentially for future features (e.g., Clinical Study Design).
Dashboard and Workspace tabs are newly implemented and require comprehensive testing.
Schedule display formatting has been improved to remove visible markup and improve readability.
News feed includes AI-powered query generation, duplicate prevention, and 7-day persistence.
Tasks Tab has comprehensive automated test coverage (75 tests) using pytest with mocking. Tests verify UI logic, error handling, API integration, natural language task creation, task editing/deletion, and field visibility. VikunjaClient API is fully implemented and tested.



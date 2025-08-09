NaviSsurance Testing
Test Cases

Note-Taking System Tests
TC-001: Context Setting

Description: Verify the note-taking system allows setting context for note sessions.
Steps:
Open NaviSsurance (interface.py).
Navigate to Note-Taking System.
Enter context in context input field (e.g., "Working on FDA submission for new diagnostic device").
Press Enter.

Expected Result: Context is set and displayed in notes pane.
Actual Result: [Pending: Test not run], 2025-01-XX.
Status: Pending

TC-002: Note Formatting

Description: Verify AI properly formats user notes for clarity and professionalism.
Steps:
Open NaviSsurance (interface.py).
Navigate to Note-Taking System.
Enter a raw note (e.g., "need to check section 5").
Press Enter to process.

Expected Result: Note is formatted professionally and displayed in notes pane.
Actual Result: [Pending: Test not run], 2025-01-XX.
Status: Pending

TC-003: Dynamic Categorization

Description: Verify notes are automatically categorized when 2 or more notes exist.
Steps:
Open NaviSsurance (interface.py).
Navigate to Note-Taking System.
Add first note (e.g., "Review ISO 13485 requirements").
Add second note (e.g., "Check FDA guidance documents").

Expected Result: Notes are categorized into logical groups and displayed under category headings.
Actual Result: [Pending: Test not run], 2025-01-XX.
Status: Pending

TC-004: Export Functionality

Description: Verify notes can be exported in multiple formats with context included.
Steps:
Open NaviSsurance (interface.py).
Navigate to Note-Taking System.
Add several notes with context.
Click "Export Notes" button.
Check generated files.

Expected Result: TXT, DOCX, and PDF files are created with context and categorized notes.
Actual Result: [Pending: Test not run], 2025-01-XX.
Status: Pending

TC-005: Dropbox Integration

Description: Verify exported files are automatically uploaded to Dropbox.
Steps:
Open NaviSsurance (interface.py).
Navigate to Note-Taking System.
Export notes in any format.
Check Dropbox folder.

Expected Result: Exported files appear in configured Dropbox folder.
Actual Result: [Pending: Test not run], 2025-01-XX.
Status: Pending

TC-006: Error Handling

Description: Verify system handles AI response errors gracefully.
Steps:
Open NaviSsurance (interface.py).
Navigate to Note-Taking System.
Simulate AI model failure or invalid response.
Attempt to process notes.

Expected Result: Clear error messages displayed, system continues to function.
Actual Result: [Pending: Test not run], 2025-01-XX.
Status: Pending

Chat and Task Management Tests
TC-001: Chat Response

Description: Verify chat functionality responds to user input.
Steps:
Open NaviSsurance (interface.py).
Type a message in chat (e.g., “Hello, Navi”).


Expected Result: Navi responds with relevant text.
Actual Result: Pass: Navi responded, 2025-05-30.
Status: Pass

TC-002: Chat Search

Description: Verify chat performs a requested web search.
Steps:
Open NaviSsurance (interface.py).
Ask Navi a question requiring a web search (e.g., “What’s in the news today?”).


Expected Result: Navi performs search and provides accurate information.
Actual Result: Pass: Search performed, accurate information provided, 2025-05-30.
Status: Pass

TC-003: Daily Briefing

Description: Verify Navi provides a daily briefing.
Steps:
Open NaviSsurance (interface.py).
Ask Navi via chat for the daily briefing.


Expected Result: Navi provides an update on tasks, meetings, and emails.
Actual Result: Fail: Error “ChatHandler.task_added_signal[str, str] signal has 2 argument(s) but 3 provided”, 2025-06-02 (Issue #18).
Status: Fail

TC-004: Add Task from Chat

Description: Verify Navi adds a single task via chat.
Steps:
Open NaviSsurance (interface.py).
Ask Navi to add a task (e.g., “Add a task to go grocery shopping on Thursday”).


Expected Result: Task is added to the task list with correct text and date.
Actual Result: Pass: Task added correctly, 2025-06-02.
Status: Pass

TC-005: Add Multiple Tasks from Chat

Description: Verify Navi adds multiple tasks from a single chat request.
Steps:
Open NaviSsurance (interface.py).
Ask Navi to add two tasks (e.g., “Remind me to call the office on Monday, and call the accountant on Wednesday”).
Repeat with three or more tasks.


Expected Result: All tasks are parsed and added as separate items to the task list.
Actual Result: Fail: Only first task added, 2025-06-03 (Issue #19).
Status: Fail

Task List Tests
TC-006: Task List Edit Button

Description: Verify editing a task via the edit button.
Steps:
Open NaviSsurance (interface.py).
Navigate to Task List.
Add a task (e.g., “Meeting Monday”).
Click “Edit” button, modify text (e.g., “Meeting Tuesday”).


Expected Result: Task updates with new text in task list.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-007: Task List Delete Button

Description: Verify deleting a task via the delete button.
Steps:
Open NaviSsurance (interface.py).
Navigate to Task List.
Add a task.
Click “Delete” button.


Expected Result: Task is removed from task list.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-008: Task List Archive Completed Tasks Button

Description: Verify archiving completed tasks.
Steps:
Open NaviSsurance (interface.py).
Navigate to Task List.
Add a task, mark as completed.
Click “Archive Completed Tasks” button.


Expected Result: Completed task is archived, removed from active list.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-009: Task List Persistence Session-to-Session

Description: Verify tasks persist across sessions.
Steps:
Open NaviSsurance (interface.py).
Add a task to Task List.
Close and reopen NaviSsurance.


Expected Result: Task remains in task list.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-010: Task List Visibility for Daily Briefing

Description: Verify tasks are visible in daily briefing.
Steps:
Open NaviSsurance (interface.py).
Add a task to Task List.
Request daily briefing via chat.


Expected Result: Task appears in briefing output.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

Leads Tab Tests
TC-011: Leads Tab Run Search Function

Description: Verify running a lead search.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Click “Run Search” button.


Expected Result: Claude generates JSON ({name, company, title, LinkedIn_url, rationale}).
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-012: Leads Tab Settings Editing

Description: Verify editing lead search settings.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Modify settings (e.g., industry filter).
Save settings.


Expected Result: Settings are updated and applied to next search.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-013: Leads Tab View Message Functionality

Description: Verify viewing a lead’s message.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Click “View Message” for a lead.


Expected Result: Personalized LinkedIn message displays for copy/paste.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-014: Leads Tab Delete Button Functionality

Description: Verify deleting a lead.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Click “Delete” button for a lead.


Expected Result: Lead is removed from Leads Tab.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-015: Leads Tab View Rationale Functionality

Description: Verify viewing a lead’s rationale.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Click “View Rationale” for a lead.


Expected Result: Rationale text displays explaining lead selection.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-016: Leads Tab Hyperlink to LinkedIn Profile

Description: Verify LinkedIn profile hyperlink functionality.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Click LinkedIn URL for a lead.


Expected Result: Browser opens to the lead’s LinkedIn profile.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-017: Leads Tab Contacted Checkbox and Date Stamp

Description: Verify marking a lead as contacted.
Steps:
Open NaviSsurance (interface.py).
Navigate to Leads Tab.
Run a search.
Check “Contacted” box for a lead.


Expected Result: Lead is marked contacted with a date stamp in crm.py.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

Document Generation Tab Tests
TC-018: Document Generation Tab Document Upload/URL Addition

Description: Verify uploading a document or adding a URL.
Steps:
Open NaviSsurance (interface.py).
Navigate to Document Generation Tab.
Upload a PDF or enter a URL (e.g., “https://www.fda.gov”).


Expected Result: Document/URL is added to the tab.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

TC-019: Document Generation Tab Document Removal/Deletion

Description: Verify removing a document or URL.
Steps:
Open NaviSsurance (interface.py).
Navigate to Document Generation Tab.
Upload a PDF or add a URL.
Click “Remove” or “Delete” button.


Expected Result: Document/URL is removed from the tab.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

TC-020: Document Generation Tab Document Output

Description: Verify generating a document output.
Steps:
Open NaviSsurance (interface.py).
Navigate to Document Generation Tab.
Upload a PDF or add a URL.
Click “Generate Output”.


Expected Result: Grok generates a PDF/JSON report based on input.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

Meetings Tab Tests
TC-021: Meetings Tab Start Recording

Description: Verify starting a meeting recording.
Steps:
Open NaviSsurance (interface.py).
Navigate to Meetings Tab.
Click “Start Recording”.


Expected Result: Recording begins, indicated in UI.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-022: Meetings Tab Stop Recording

Description: Verify stopping a meeting recording.
Steps:
Open NaviSsurance (interface.py).
Navigate to Meetings Tab.
Start recording, then click “Stop Recording”.


Expected Result: Recording stops, file saved locally.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-023: Meetings Tab Generate Transcript

Description: Verify generating a meeting transcript.
Steps:
Open NaviSsurance (interface.py).
Navigate to Meetings Tab.
Record a short meeting or upload audio.
Click “Generate Transcript”.


Expected Result: AssemblyAI generates speaker-separated transcript.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-024: Meetings Tab Load File

Description: Verify loading an audio file for transcription.
Steps:
Open NaviSsurance (interface.py).
Navigate to Meetings Tab.
Click “Load File”, select an audio file (e.g., meeting.wav).


Expected Result: File loads in UI for transcription.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

TC-025: Meetings Tab Save Transcript

Description: Verify saving a meeting transcript.
Steps:
Open NaviSsurance (interface.py).
Navigate to Meetings Tab.
Generate a transcript.
Click “Save Transcript”.


Expected Result: Transcript saved to crm.py with client metadata.
Actual Result: [Pending: Test not run], 2025-06-03.
Status: Pending

Compliance Tab Tests
TC-026: Compliance Tab Upload Documents/URLs

Description: Verify uploading documents or URLs in Compliance Tab.
Steps:
Open NaviSsurance (interface.py).
Navigate to Compliance Tab.
Upload a PDF (e.g., SOP.pdf) or enter a URL (e.g., “https://www.ecfr.gov”).


Expected Result: Document/URL added to first column.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

TC-027: Compliance Tab Remove/Delete Document or URL

Description: Verify removing a document or URL.
Steps:
Open NaviSsurance (interface.py).
Navigate to Compliance Tab.
Upload a PDF or add a URL.
Click “Remove” or “Delete”.


Expected Result: Document/URL removed from first column.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

TC-028: Compliance Tab Run Compliance Check

Description: Verify running a compliance check.
Steps:
Open NaviSsurance (interface.py).
Navigate to Compliance Tab.
Upload a PDF or add a URL.
Click “Run Compliance Check”.


Expected Result: Grok returns JSON ([{section, issue, fix, reference}]) in third column.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

TC-029: Compliance Tab Save Report

Description: Verify saving a compliance report.
Steps:
Open NaviSsurance (interface.py).
Navigate to Compliance Tab.
Run a compliance check.
Click “Save Report”.


Expected Result: Report saved as PDF/JSON to crm.py.
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

TC-030: Compliance Tab Link to CRM

Description: Verify linking compliance results to CRM.
Steps:
Open NaviSsurance (interface.py).
Navigate to Compliance Tab.
Run a compliance check.
Click “Link to CRM”.


Expected Result: Results linked to client record in crm.py ({client_id, issues}).
Actual Result: [Pending: Feature in development], 2025-06-03.
Status: Pending

Traceability



Test Case
User Story (requirements.md)



TC-001, TC-002, TC-003, TC-004, TC-005, TC-006, TC-007, TC-008, TC-009, TC-010
Task Management


TC-011, TC-012, TC-013, TC-014, TC-015, TC-016, TC-017
Lead Generation


TC-018, TC-019, TC-020
Document Generation


TC-021, TC-022, TC-023, TC-024, TC-025
Meeting Transcription


TC-026, TC-027, TC-028, TC-029, TC-030
Compliance Tab


Notes

Tests are manual, executed via UI (interface.py) or scripts (e.g., fetch_all_emails.py).
Failures linked to GitHub Issues (e.g., #18, #19).
Update Actual Result and Status after testing, using ISO dates (YYYY-MM-DD).
New test cases (TC-031+) will be appended sequentially for future features (e.g., Clinical Study Design).



NaviSsurance Requirements
Functional Requirements

Dashboard Tab (IMPLEMENTED)

User Story: As a consultant, I want a comprehensive dashboard that shows my tasks, schedule, and relevant news, so I can quickly assess my day and stay informed.
Acceptance Criteria:
Display interactive task list with double-click completion functionality.
Show today's schedule from Google Calendar with formatted time display.
Provide AI-powered MedTech news feed with 7-day persistence and clickable hyperlinks.
Auto-refresh schedule every 15 minutes and news every hour.
Handle task completion updates in real-time.
Support news item deduplication and cleanup.

Workspace Tab (IMPLEMENTED)

User Story: As a consultant, I want an advanced document workspace with file management and analysis tools, so I can efficiently organize and analyze client documents.
Acceptance Criteria:
Three-panel layout: Dropbox file tree (left), document preview (center), analysis tools (right).
Upload and manage documents from Dropbox with search and filtering.
Preview documents in various formats (PDF, DOCX, TXT).
Run compliance analysis, document chunking, and generation tools.
Download and manage files with status feedback.

Note-Taking System (IMPLEMENTED)

User Story: As a consultant, I want to take AI-powered notes with context-aware formatting and dynamic categorization, so I can efficiently organize my thoughts and work.
Acceptance Criteria:
Set context for note-taking sessions to provide AI with relevant background information.
Take notes that are automatically formatted for clarity and professionalism by the AI.
Have notes automatically categorized into logical groups when 2 or more notes are present.
Export notes in multiple formats (TXT, DOCX, PDF) with context included.
Upload exported files to Dropbox for cloud storage and sharing.
Handle AI response errors gracefully with fallback mechanisms and user feedback.
Support dynamic re-categorization as new notes are added to existing categories.

Compliance Tab (IMPLEMENTED)

User Story: As a consultant, I want to upload SOPs, PDFs, or URLs to check compliance with standards like ISO 13485 or 21 CFR 820, so I can provide actionable client recommendations.
Acceptance Criteria:
Upload PDF files or enter URLs as either reference standards or for comparison to reference standards.
Grok API analyzes documents, returning JSON ([{section, issue, fix, reference}]).
Display results with options to save to database or export as PDF.
Handle invalid files/URLs with error messages.

Lead Generation (IMPLEMENTED)

User Story: As a consultant, I want to generate leads for AI SaMD, IVD, or non-AI MedTech companies, so I can initiate outreach via LinkedIn or other methods.
Acceptance Criteria:
Grok 4 API outputs JSON ({name, company, title, LinkedIn_url, rationale}) in Leads Tab.
Display leads with copy/paste personalized LinkedIn messages.
Allow marking leads as contacted, saving status to database.
Send LinkedIn messages directly from the UI, or schedule them to be sent for later.

Clinical Study Design Optimizer (PLANNED)

User Story: As a consultant, I want to design 510(k), IDE, PMCF or other protocols for clients, so I can deliver cost-effective study plans.
Acceptance Criteria:
Input device specs and regulatory goals via UI (interface.py).
Grok generates protocol ({protocol_id, endpoints, sample_size, rationale}) in JSON/PDF, costing $3,000–$12,000.
Support Class I-II devices (e.g., SaMD, diagnostics).

Email Fetching and Filtering (PARTIALLY IMPLEMENTED)

User Story: As a consultant, I want to fetch and filter emails from multiple accounts, so I can efficiently manage personal assistance and planning tasks for clients.
Acceptance Criteria:
Fetch emails from Gmail, MSN/Outlook, and custom IMAP accounts, including folders ("Clients," "Leads") via fetch_all_emails.py.
Save emails to data/email_labels.csv for 8-class DistilBERT filtering (e.g., Response Needed, Personal, Meeting Request).
Display filtered emails in Briefing Pane (interface.py) to prioritize client-related tasks.
Handle invalid email accounts with error logging.

Meeting Transcription (IMPLEMENTED)

User Story: As a consultant, I want to transcribe client meetings, so I can reference discussions for compliance or planning.
Acceptance Criteria:
AssemblyAI transcribes audio files, outputting speaker-separated text (interface.py, lines 248–312).
Save transcripts to database with client metadata.

Task Management (IMPLEMENTED WITH ENHANCEMENTS)

User Story: As a consultant, I want to manage tasks manually or via chat, so I can track project priorities.
Acceptance Criteria:
Add, archive, and view tasks in UI (interface.py) or chat (core/chat.py).
Persist tasks in core.db.DatabaseManager.
Support interactive dashboard integration with double-click completion.
Real-time status updates and task counter display.

Tasks Tab - Vikunja Integration (FULLY IMPLEMENTED)

User Story: As a consultant, I want to manage tasks and projects using a professional task management system (Vikunja), so I can organize work across multiple projects with proper task tracking.
Acceptance Criteria:
✅ Connect to Vikunja server (self-hosted or cloud instance) via URL, username, and password.
✅ Test connection before authentication to verify server accessibility.
✅ Login with existing credentials or register new account via UI.
✅ Persistent credentials using QSettings (username/password remain populated across sessions).
✅ Enter key support for login from username or password fields.
✅ Load and display projects in hierarchical dropdown (supports nested projects with indentation).
✅ Create new projects with title and optional metadata.
✅ Load tasks for selected project with ALL fields visible:
   - ID (hidden), Title, Description, Priority, Due Date, Start Date, End Date, % Done, Done, Favorite, Estimated Duration, Actions
✅ Create tasks with title, priority, estimated duration, and optional fields (due date, description, etc.).
✅ Edit tasks with full dialog supporting all fields including estimated duration.
✅ Delete tasks with confirmation dialog.
✅ Toggle task completion status with real-time UI updates.
✅ Natural language task creation via chat window (when on Tasks tab):
   - Parse task details from plain language using local Llama model
   - Extract: title, description, priority, due date, estimated duration, project assignment
   - Prompt for missing required information before creating
   - Auto-assign to correct project based on context
✅ Support custom task fields (estimated duration) stored locally in SQLite and displayed in table.
✅ Handle errors gracefully with user-friendly messages (no success popups, only error messages).
Status: Fully implemented with comprehensive test coverage (75 automated tests passing). VikunjaClient API (core/vikunja_client.py) fully implemented and tested.

CRM Integration (PLANNED)

User Story: As a consultant, I want to unify leads, compliance results, and emails, so I can streamline client interactions.
Acceptance Criteria:
Store leads, compliance JSON, and filtered emails in SQLite (core/db.py).
Link data to client records (e.g., {client_id, lead_id, issues}).
Query data in UI.

Document Generation (PARTIALLY IMPLEMENTED)

User Story: As a consultant, I want to generate client-specific documentation (e.g., compliance reports, study protocols), so I can deliver professional deliverables.
Acceptance Criteria:
Generate PDF/JSON reports from Grok outputs (e.g., compliance JSON, study protocols) in UI (interface.py).
Use workspace documents as context for generation.
Save reports to database with client metadata.
Allow export or email sharing of reports.

Non-Functional Requirements

Security: GDPR/HIPAA-compliant data storage (core/db.py, AES encryption); API keys in .env.
Scalability: Support up to 50 simultaneous client workspaces, each with independent document access.
Reliability: 99% uptime for UI and API calls, with error logging.
Maintainability: Code in core/ and gui/ with GitHub versioning; docs in docs/.
Performance: Dashboard auto-refresh timers, efficient database queries with FTS5 indexing.


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
Fetch emails from Gmail, Yahoo (IMAP), and MSN/Outlook (EWS), including configurable folders/labels (e.g., "Clients", "Leads") via `core/data_fetch.py:get_new_emails()`.
Persist fetched emails into SQLite (`emails` table) and mark reply status best-effort.
Display filtered emails in the Daily Briefing (Dashboard) to prioritize client-related tasks.
Handle invalid email accounts with error logging.

Notes:
- Folders/labels are configured via `config/.env`:
  - `EMAIL_GMAIL_LABELS`, `EMAIL_YAHOO_FOLDERS`, `EMAIL_OUTLOOK_FOLDERS`
- Client/potential classification is configured via `EMAIL_CLIENT_DOMAINS`, `EMAIL_POTENTIAL_DOMAINS`, `EMAIL_CLIENT_LABELS`, `EMAIL_POTENTIAL_LABELS`.
- DistilBERT training/export to `data/email_labels.csv` is not implemented in the current Workspace branch.

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

Tasks Tab (LOCAL - IMPLEMENTED)

User Story: As a consultant, I want a dedicated tasks tab that uses NaviSsurance’s built-in task store, so I can manage tasks without relying on an external system.

Acceptance Criteria:
- View tasks stored in SQLite (`core.db.DatabaseManager`), same store used by Dashboard + CoS task capture.
- Filter by category and date (Today / Overdue / No Date).
- Search by task text.
- Add tasks quickly with optional due date.
- Mark tasks complete/incomplete and delete tasks.

Status: Implemented (no Vikunja required).

Deep Research (WEB-FIRST - IMPLEMENTED)

User Story: As a consultant, I want a dedicated deep web research workflow that produces a reusable research brief with citations, so I can quickly ground downstream drafting and decision-making.

Acceptance Criteria:
- Provide a `Deep Research` tab with:
  - research name and objective input
  - a run button that executes a web research pipeline asynchronously (no UI blocking)
  - an iterative web research loop (max 8 rounds, 30-minute timebox) that stops when it stops finding new sources
  - a visible “still working” indicator during long runs (status updates + progress bar)
  - a review gate (status becomes `awaiting_research_review`) with visible web research artifacts
  - a button to generate a final research brief (markdown), with an optional auto-generate toggle
- Persist artifacts to SQLite (`projects`, `task_plans`, `project_tasks`, `runs`, `artifacts` tables).
- Deep Research is web-only (not internal database/document scouring).
 - Final research brief is also written to `data/artifacts/<run_id>/research_brief.md`.

Billing (TIME TRACKING + INVOICE DRAFTS - IMPLEMENTED)

User Story: As a consultant, I want to log billable hours and generate monthly invoice drafts automatically on a set day, so I can review and send invoices efficiently.

Acceptance Criteria:
- Provide a `Billing` tab with:
  - manual time entry (timer + quick manual add) associated with a client
  - invoice template editor using safe placeholders (e.g., `{{client_name}}`, `{{line_items_md}}`, `{{total_hours}}`)
  - invoice draft generation for previous month and custom periods
  - invoice draft review and export (no auto-send)
- Monthly auto-draft runs (in-app, while running) on a configurable day-of-month (1–28) and prompts for review afterwards.
- Persist billing entities in SQLite: clients, time entries, templates, invoice drafts, and artifact file paths.

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


NaviSsurance Requirements
Functional Requirements
Compliance Tab

User Story: As a consultant, I want to upload SOPs, PDFs, or URLs to check compliance with standards like ISO 13485 or 21 CFR 820, so I can provide actionable client recommendations.
Acceptance Criteria:
Upload PDF files or enter URLs in a three-column UI (interface.py).
Grok API analyzes documents, returning JSON ([{section, issue, fix, reference}]).
Display results in the third column, with options to save to crm.py or export as PDF.
Handle invalid files/URLs with error messages.



Lead Generation

User Story: As a consultant, I want to generate leads for AI SaMD, IVD, or non-AI MedTech companies, so I can initiate outreach via LinkedIn.
Acceptance Criteria:
Claude 3.7 Sonnet outputs JSON ({name, company, title, LinkedIn_url, rationale}) in Leads Tab (interface.py).
Display leads with copy/paste personalized LinkedIn messages.
Allow marking leads as contacted, saving status to crm.py.



Clinical Study Design Optimizer

User Story: As a consultant, I want to design 510(k), IDE, or PMCF protocols for diagnostics or CRO clients, so I can deliver cost-effective study plans.
Acceptance Criteria:
Input device specs and regulatory goals via UI (interface.py).
Grok generates protocol ({protocol_id, endpoints, sample_size, rationale}) in JSON/PDF, costing $3,000–$12,000.
Deliver results in 1–3 days, saving to crm.py.
Support Class I-II devices (e.g., SaMD, diagnostics).



Email Fetching and Filtering

User Story: As a consultant, I want to fetch and filter emails from multiple accounts, so I can efficiently manage personal assistance and planning tasks for clients.
Acceptance Criteria:
Fetch emails from Gmail, MSN/Outlook, and custom IMAP accounts, including folders (“Clients,” “Leads”) via fetch_all_emails.py.
Save emails to data/email_labels.csv for 8-class DistilBERT filtering (e.g., Response Needed, Personal, Meeting Request).
Display filtered emails in Briefing Pane (interface.py) to prioritize client-related tasks.
Handle invalid email accounts with error logging.



Meeting Transcription

User Story: As a consultant, I want to transcribe client meetings, so I can reference discussions for compliance or planning.
Acceptance Criteria:
AssemblyAI transcribes audio files, outputting speaker-separated text (interface.py, lines 248–312).
Save transcripts to crm.py with client metadata.



Task Management

User Story: As a consultant, I want to manage tasks manually or via chat, so I can track project priorities.
Acceptance Criteria:
Add, archive, and view tasks in UI (interface.py) or chat (chat.py).
Persist tasks in core.db.DatabaseManager.



CRM Integration

User Story: As a consultant, I want to unify leads, compliance results, and emails, so I can streamline client interactions.
Acceptance Criteria:
Store leads, compliance JSON, and filtered emails in SQLite (crm.py).
Link data to client records (e.g., {client_id, lead_id, issues}).
Query data in UI.



Workspaces

User Story: As a consultant, I want to create client-specific workspaces to store and access documents, so I can generate tailored outputs for each client.
Acceptance Criteria:
Create and switch between client workspaces in UI (interface.py).
Upload PDFs, URLs, or CSVs to client-specific folders (data/clients/[client_name]).
Grok accesses workspace documents for compliance checks or study protocols, saving outputs to crm.py.
Isolate client data to prevent cross-access.



Document Generation

User Story: As a consultant, I want to generate client-specific documentation (e.g., compliance reports, study protocols), so I can deliver professional deliverables.
Acceptance Criteria:
Generate PDF/JSON reports from Grok outputs (e.g., compliance JSON, study protocols) in UI (interface.py).
Use workspace documents as context for generation.
Save reports to crm.py with client metadata.
Allow export or email sharing of reports.



Non-Functional Requirements

Security: GDPR/HIPAA-compliant data storage (crm.py, AES encryption); API keys in .env.
Scalability: Support up to 50 simultaneous client workspaces, each with independent document access.
Reliability: 99% uptime for UI and API calls, with error logging.
Maintainability: Code in src/ with GitHub versioning; docs in docs/.


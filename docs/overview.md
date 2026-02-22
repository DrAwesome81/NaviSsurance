# NaviSsurance Overview

## Purpose
NaviSsurance is an AI-powered medical device regulatory consulting platform, serving AI Software as a Medical Device (SaMD), In Vitro Diagnostics/Laboratory Developed Tests (IVD/LDT), and non-AI MedTech clients (e.g., diagnostics, implants, surgical devices). It automates compliance checking, lead generation, and clinical study design, delivering 60–80% cost savings ($3,750–$28,000 per project) compared to traditional consultancies (e.g., Emergo, RQM+), with results in hours or days versus weeks.

## Features
- **Dashboard Tab**: New comprehensive dashboard with task list, schedule display (Google Calendar integration), and news feed (AI-powered MedTech news with 7-day persistence and hyperlinks). Features auto-refresh timers and interactive task completion.
- **Workspace Tab**: Advanced document workspace with QSplitter layout: left panel (Dropbox file tree), center panel (document preview), and right sidebar (analysis tools for compliance, chunking, and document generation).
- **Note-Taking System**: AI-powered note-taking with context-aware formatting and dynamic categorization. Features include context setting, automatic note formatting with robust JSON parsing, intelligent categorization, thread-safe UI updates, and DOCX export via Save As dialog. Uses local Llama 3.1-8B-Instruct model with deterministic settings (temperature=0.2, top_p=0.7).
- **Compliance Checking**: Grok-powered three-column UI (`interface.py`) for analyzing SOPs, PDFs, or URLs against standards (e.g., ISO 13485, 21 CFR 801), outputting JSON results (`[{section, issue, fix, reference}]`) for client recommendations.
- **Lead Generation**: DB-backed Leads Tab (`gui/leads_tab.py`) runs a two-pass discover→verify pipeline with evidence links, openFDA 510(k) signals, scoring/filters, and one-click follow-up task creation (see `docs/lead_generation.md`).
- **Clinical Study Design (Planned)**: AI optimizer for 510(k), IDE, or PMCF protocols, costing $3,000–$12,000 versus $10,000–$40,000, targeting diagnostics (e.g., Abbott) and CROs, with 1–3 day delivery.
- **Email Fetching**: Fetches Gmail, MSN/Outlook, and custom IMAP inboxes (`fetch_all_emails.py`); planned folder access (e.g., "Clients," "Leads") for DistilBERT training to filter emails (8-class: Response Needed, Personal, etc.).
- **Meeting Transcription**: AssemblyAI processes speaker-separated transcripts (`interface.py`, lines 248–312).
- **Task Management**: Manual and chat-based task addition, archiving, and persistence (`core.db.DatabaseManager`), with interactive dashboard integration and double-click completion.
- **Tasks Tab (Local)**: SQLite-backed tasks manager (no external task system required). Provides search, filters, quick add, completion toggling, and deletion.
- **CRM Integration (Planned)**: SQLite-based (`crm.py`) to unify leads, compliance results, and filtered emails.

## Tech Stack
- **Core**: Python 3.12.7, PyQt6 (UI), SQLite (`core/db.py` for data storage).
- **AI Models**: Local Llama 3.1-8B-Instruct model for note-taking and chat interactions, with 1000-token response limits for comprehensive outputs.
- **APIs**: xAI Grok (compliance, document generation, lead generation), LinkedIn (Share, Sign In, Community Management), AssemblyAI (transcription).
- **Tools**: Cursor (IDE), Git/GitHub (version control), Dropbox (storage at `C:/Users/adamo/Dropbox/_Consulting/NaviSsurance`).

## Status
- **Fully Operational**: Dashboard tab with task management, schedule display, and news feed; Workspace tab with document management and analysis tools; Note-taking system with AI formatting and categorization; Lead generation and transcription are fully functional.
- **Operational with Improvements**: Task management is now functional with dashboard integration and interactive features; Email fetching is limited to inboxes, needing folder access.
- **In Development**: Clinical study design optimizer, CRM integration, and DistilBERT email filtering.
- **Next Steps**: Debug `fetch_all_emails.py` for folder access, launch clinical study design optimizer to expand client base (diagnostics, CROs), enhance CRM integration.
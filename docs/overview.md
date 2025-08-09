# NaviSsurance Overview

## Purpose
NaviSsurance is an AI-powered medical device regulatory consulting platform, serving AI Software as a Medical Device (SaMD), In Vitro Diagnostics/Laboratory Developed Tests (IVD/LDT), and non-AI MedTech clients (e.g., diagnostics, implants, surgical devices). It automates compliance checking, lead generation, and clinical study design, delivering 60–80% cost savings ($3,750–$28,000 per project) compared to traditional consultancies (e.g., Emergo, RQM+), with results in hours or days versus weeks.

## Features
- **Note-Taking System**: AI-powered note-taking with context-aware formatting and dynamic categorization. Features include context setting, automatic note formatting, intelligent categorization, and export capabilities (TXT, DOCX, PDF) with Dropbox integration.
- **Compliance Checking**: Grok-powered three-column UI (`interface.py`) for analyzing SOPs, PDFs, or URLs against standards (e.g., ISO 13485, 21 CFR 801), outputting JSON results (`[{section, issue, fix, reference}]`) for client recommendations.
- **Lead Generation**: Grok 4 API generates JSON-backed leads (name, company, title, LinkedIn URL, rationale) in the Leads Tab (`interface.py`), with personalized LinkedIn messages for manual outreach.
- **Clinical Study Design (Planned)**: AI optimizer for 510(k), IDE, or PMCF protocols, costing $3,000–$12,000 versus $10,000–$40,000, targeting diagnostics (e.g., Abbott) and CROs, with 1–3 day delivery.
- **Email Fetching**: Fetches Gmail, MSN/Outlook, and custom IMAP inboxes (`fetch_all_emails.py`); planned folder access (e.g., "Clients," "Leads") for DistilBERT training to filter emails (8-class: Response Needed, Personal, etc.).
- **Meeting Transcription**: AssemblyAI processes speaker-separated transcripts (`interface.py`, lines 248–312).
- **Task Management**: Manual and chat-based task addition, archiving, and persistence (`core.db.DatabaseManager`), needing UX improvements.
- **CRM Integration (Planned)**: SQLite-based (`crm.py`) to unify leads, compliance results, and filtered emails.

## Tech Stack
- **Core**: Python 3.12.7, PyQt6 (UI), SQLite (`crm.py` for data storage).
- **AI Models**: Local Llama 3.1-8B-Instruct model for note-taking and chat interactions, with 1000-token response limits for comprehensive outputs.
- **APIs**: xAI Grok (compliance, document generation, lead generation), LinkedIn (Share, Sign In, Community Management), AssemblyAI (transcription).
- **Tools**: Cursor (IDE), Git/GitHub (version control), Dropbox (storage at `C:/Users/adamo/Dropbox/_Consulting/NaviSsurance`).

## Status
- **Operational**: Note-taking system with AI formatting and categorization, lead generation and transcription are fully functional; task management is functional but clunky; email fetching is limited to inboxes, needing folder access.
- **In Development**: Compliance Tab UI (three-column, file/URL uploads), clinical study design optimizer, CRM integration, and DistilBERT email filtering.
- **Next Steps**: Debug `fetch_all_emails.py` for folder access, implement Compliance Tab in `interface.py`, launch clinical study design optimizer to expand client base (diagnostics, CROs).
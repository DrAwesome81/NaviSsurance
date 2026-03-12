# NaviSsurance Overview

## Purpose
NaviSsurance is an AI-powered medical device regulatory consulting platform, serving AI Software as a Medical Device (SaMD), In Vitro Diagnostics/Laboratory Developed Tests (IVD/LDT), and non-AI MedTech clients (e.g., diagnostics, implants, surgical devices). It automates compliance checking, lead generation, and clinical study design, delivering 60–80% cost savings ($3,750–$28,000 per project) compared to traditional consultancies (e.g., Emergo, RQM+), with results in hours or days versus weeks.

## Features
- **Dashboard Tab**: New comprehensive dashboard with task list, schedule display (Google Calendar integration), and news feed (AI-powered MedTech news with 7-day persistence and hyperlinks). Features auto-refresh timers and interactive task completion.
- **Chief of Staff Tab**: Planning, delegation, and operational triage. Supports an AM Sweep morning loop (Dispatch/Prep/Yours/Skip) and machine-action outputs for assignments and task updates.
- **Workspace Tab**: Document-centered drafting workflow: add files/folders, mark scope, run the dual-LLM collaboration to produce a markdown deliverable, then optionally extract a reviewable “Suggested Tasks (importable)” section and import accepted tasks into SQLite.
- **Deep Research Tab**: Web-first deep research workflow that runs iterative web research (max 8 rounds, 30-minute timebox) + synthesis and produces a reusable research brief (markdown) with linked sources. Uses OpenAI Responses API hosted `web_search` when configured, shows continuous “still working” status updates during rounds, and writes the final brief to `data/artifacts/<project_id>/research_brief.md`.
- **Billing Tab**: Manual time entry and template-based invoice drafting. Generates invoice drafts as markdown and prompts for review after monthly auto-draft runs (no auto-send).
- **Note-Taking System**: AI-powered context-document workspace. Each context becomes one living document that Navi continuously rewrites into coherent sections and bullets as new observations are added. Supports robust JSON parsing, thread-safe updates, and DOCX/Markdown/PDF export for the active document.
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
- **AI Models**: Local Llama 3.1-8B-Instruct model for note-taking and some chat interactions; OpenAI (ChatGPT) is used for web research where configured.
- **APIs**: xAI Grok (compliance, document generation, lead generation), OpenAI (web research), LinkedIn (Share, Sign In, Community Management), AssemblyAI (transcription).
- **Tools**: Cursor (IDE), Git/GitHub (version control), Dropbox (storage at `C:/Users/adamo/Dropbox/_Consulting/NaviSsurance`).

## Status
- **Fully Operational**: Dashboard tab with task management, schedule display, and news feed; Workspace tab with document management and analysis tools; Note-taking system with live context documents; Lead generation and transcription are fully functional.
- **Operational with Improvements**: Task management is now functional with dashboard integration and interactive features; Email fetching is limited to inboxes, needing folder access.
- **In Development**: Clinical study design optimizer, CRM integration, and DistilBERT email filtering.
- **Next Steps**: Debug `fetch_all_emails.py` for folder access, launch clinical study design optimizer to expand client base (diagnostics, CROs), enhance CRM integration.
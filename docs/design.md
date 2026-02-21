# NaviSsurance Design

## Architecture Overview
NaviSsurance is a Python 3.12.7-based desktop application using PyQt6 for the UI (`interface.py`), SQLite for data storage (`crm.py`), and APIs (Grok, Claude, LinkedIn, AssemblyAI) for AI-driven features. The system flow:
- UI (`interface.py`) handles user inputs (e.g., PDF uploads, lead searches).
- Backend (`chat.py`, `fetch_all_emails.py`) processes requests via APIs or local logic.
- Data persists in SQLite (`crm.py`) for leads, compliance results, and emails.
See `docs/diagrams/architecture.png` for a visual representation.

## Module Descriptions
- **Compliance Tab** (`interface.py`): Three-column UI for uploading SOPs/URLs, analyzing with Grok, and displaying JSON results (`[{section, issue, fix, reference}]`).
- **Leads Tab** (`interface.py`): Displays Claude-generated JSON leads (`{name, company, title, LinkedIn_url, rationale}`) with copy/paste messages.
- **Email Fetching** (`fetch_all_emails.py`): Fetches Gmail, MSN/Outlook, IMAP emails; planned folder access for DistilBERT filtering.
- **Task Management** (`core.db.DatabaseManager`): Stores tasks in SQLite, accessible via UI or chat.
- **Chief of Staff Orchestration** (`core/response_handler.py`, `config.py`): Parses assistant action commands (tasks, web search, local search, history) and routes to tools. Roadmap in `docs/chief_of_staff.md`.
- **Unified Document Search (Planned)**: A dedup-aware search layer across Dropbox + local + Google Drive (see `docs/unified_search.md`).
- **External News Briefing (Planned/Iterating)**: External headlines for daily briefing with dedup + cache (see `docs/news_briefing.md`).
- **Transcription** (`interface.py`, lines 248–312): Uses AssemblyAI for meeting transcripts.
- **CRM** (`crm.py`): SQLite-based, planned to unify leads, compliance, and emails.

## API Integrations
- **xAI Grok**: Compliance analysis, document generation; endpoints: `https://api.x.ai/grok` (`chat.py`).
- **Anthropic Claude 3.7 Sonnet**: Lead generation; endpoints: `https://api.anthropic.com` (`interface.py`).
- **LinkedIn (Share, Sign In, Community Management)**: Posts content, authenticates users; endpoints: `https://api.linkedin.com/v2` (`interface.py`).
- **AssemblyAI**: Meeting transcription; endpoints: `https://api.assemblyai.com` (`interface.py`).

## Diagram
See `docs/diagrams/architecture.png`.

## Issue Tracking
Tasks tracked in Github issues (see repo Issues tab)
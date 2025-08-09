# NaviSsurance Design

## Architecture Overview
NaviSsurance is a Python 3.12.7-based desktop application using PyQt6 for the UI (`interface.py`), SQLite for data storage (`crm.py`), and APIs (Grok, LinkedIn, AssemblyAI) for AI-driven features. The system flow:
- UI (`interface.py`) handles user inputs (e.g., PDF uploads, lead searches, note-taking).
- Backend (`chat.py`, `fetch_all_emails.py`) processes requests via APIs or local logic.
- Data persists in SQLite (`crm.py`) for leads, compliance results, emails, and notes.
- Local AI model (Llama 3.1-8B-Instruct) handles note formatting and categorization with 1000-token response limits.
See `docs/diagrams/architecture.png` for a visual representation.

## Module Descriptions
- **Note-Taking System** (`gui/interface.py`): AI-powered note-taking with context setting, automatic formatting, dynamic categorization, and export capabilities. Uses local Llama model for processing with robust JSON response handling.
- **Compliance Tab** (`interface.py`): Three-column UI for uploading SOPs/URLs, analyzing with Grok, and displaying JSON results (`[{section, issue, fix, reference}]`).
- **Leads Tab** (`interface.py`): Displays Grok-generated JSON leads (`{name, company, title, LinkedIn_url, rationale}`) with copy/paste messages.
- **Email Fetching** (`fetch_all_emails.py`): Fetches Gmail, MSN/Outlook, IMAP emails; planned folder access for DistilBERT filtering.
- **Task Management** (`core.db.DatabaseManager`): Stores tasks in SQLite, accessible via UI or chat.
- **Transcription** (`interface.py`, lines 248–312): Uses AssemblyAI for meeting transcripts.
- **CRM** (`crm.py`): SQLite-based, planned to unify leads, compliance, and emails.

## AI Model Configuration
- **Local Llama Model**: Llama 3.1-8B-Instruct-GGUF running locally with 8192-token context window
- **Response Limits**: 1000 tokens across all AI interactions for comprehensive outputs
- **Worker Processes**: Subprocess-based architecture for model loading and response generation
- **Error Handling**: Robust JSON parsing with fallback mechanisms for truncated responses

## API Integrations
- **xAI Grok**: Compliance analysis, document generation; endpoints: `https://api.x.ai/grok` (`chat.py`).
- **xAI Grok**: Lead generation; endpoints: `https://api.x.ai` (`interface.py`).
- **LinkedIn (Share, Sign In, Community Management)**: Posts content, authenticates users; endpoints: `https://api.linkedin.com/v2` (`interface.py`).
- **AssemblyAI**: Meeting transcription; endpoints: `https://api.assemblyai.com` (`interface.py`).

## Diagram
See `docs/diagrams/architecture.png`.

## Issue Tracking
Tasks tracked in Github issues (see repo Issues tab)
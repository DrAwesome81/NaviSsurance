# NaviSsurance Design

## Architecture Overview
NaviSsurance is a Python 3.12.7-based desktop application using PyQt6 for the UI (`interface.py`), SQLite for data storage (`core/db.py`), and APIs (Grok, LinkedIn, AssemblyAI) for AI-driven features. The system flow:
- UI (`interface.py`) handles user inputs (e.g., PDF uploads, lead searches, note-taking, dashboard interactions).
- Backend (`core/chat.py`, `core/fetch_all_emails.py`) processes requests via APIs or local logic.
- Data persists in SQLite (`core/db.py`) for leads, compliance results, emails, notes, tasks, and news items.
- Local AI model (Llama 3.1-8B-Instruct) handles note formatting and categorization with 1000-token response limits.
See `docs/diagrams/architecture.png` for a visual representation.

## Module Descriptions
- **Dashboard Tab** (`gui/interface.py`): Comprehensive dashboard with task list (interactive with double-click completion), schedule display (Google Calendar integration), and news feed (AI-powered MedTech news with 7-day persistence and hyperlinks). Features auto-refresh timers and real-time updates.
- **Workspace Tab** (`gui/interface.py`): Advanced document workspace with QSplitter layout: left panel (Dropbox file tree), center panel (document preview), and right sidebar (analysis tools for compliance, chunking, and document generation).
- **Note-Taking System** (`gui/interface.py`): AI-powered note-taking with context setting, automatic formatting, dynamic categorization, and export capabilities. Uses local Llama model for processing with robust JSON response handling.
- **Tasks Tab** (`gui/tasks_tab.py`): Professional task management with Vikunja API integration. Features connection management, project selection with hierarchical display, task creation and management with all fields visible (title, description, priority, due date, start date, end date, percent done, favorite, estimated duration), task editing and deletion, estimated duration input, and natural language task creation via chat. Fully implemented with comprehensive test coverage (75 automated tests passing). VikunjaClient API (`core/vikunja_client.py`) fully implemented and tested.
- **Compliance Tab** (`interface.py`): Three-column UI for uploading SOPs/URLs, analyzing with Grok, and displaying JSON results (`[{section, issue, fix, reference}]`).
- **Leads Tab** (`interface.py`): Displays Grok-generated JSON leads (`{name, company, title, LinkedIn_url, rationale}`) with copy/paste messages.
- **Email Fetching** (`core/fetch_all_emails.py`): Fetches Gmail, MSN/Outlook, IMAP emails; planned folder access for DistilBERT filtering.
- **Task Management** (`core/db.DatabaseManager`): Stores tasks in SQLite, accessible via UI, chat, or dashboard with interactive features.
- **Transcription** (`interface.py`, lines 248–312): Uses AssemblyAI for meeting transcripts.
- **CRM** (`crm.py`): SQLite-based, planned to unify leads, compliance, and emails.

## AI Model Configuration
- **Local Llama Model**: Llama 3.1-8B-Instruct-GGUF running locally with 8192-token context window
- **Response Limits**: 1000 tokens across all AI interactions for comprehensive outputs
- **Worker Processes**: Subprocess-based architecture for model loading and response generation
- **Error Handling**: Robust JSON parsing with fallback mechanisms for truncated responses

## API Integrations
- **xAI Grok**: Compliance analysis, document generation; endpoints: `https://api.x.ai/grok` (`core/chat.py`).
- **xAI Grok**: Lead generation; endpoints: `https://api.x.ai` (`interface.py`).
- **LinkedIn (Share, Sign In, Community Management)**: Posts content, authenticates users; endpoints: `https://api.linkedin.com/v2` (`interface.py`).
- **AssemblyAI**: Meeting transcription; endpoints: `https://api.assemblyai.com` (`interface.py`).
- **Vikunja API**: Task and project management; endpoints: Self-hosted instance (default: `http://localhost:3456/api/v1`). Fully implemented in `gui/tasks_tab.py` (UI) and `core/vikunja_client.py` (API client). Supports natural language task creation via chat, task editing/deletion, and custom fields (estimated duration) stored locally.

## Database Schema
- **Tasks**: `id`, `session_id`, `task`, `due_date`, `completed`, `created_at`
- **News Items**: `id`, `title`, `content`, `url`, `source`, `published_date`, `created_at` (with duplicate prevention)
- **Notes**: `id`, `formatted_note`, `category`, `context`, `timestamp`, `created_at`
- **Dropbox Files**: `id`, `name`, `path`, `link`, `modified_time`, `size`
- **Conversations**: FTS5 virtual table for full-text search
- **Vikunja Task Metadata**: `id`, `vikunja_task_id`, `estimated_duration_minutes`, `custom_fields_json`, `created_at`, `updated_at` (for custom task fields not supported by Vikunja API)

## Diagram
See `docs/diagrams/architecture.png`.

## Issue Tracking
Tasks tracked in Github issues (see repo Issues tab)
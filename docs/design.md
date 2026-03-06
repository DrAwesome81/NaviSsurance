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
- **Workspace Tab** (`gui/workspace_tab.py`): Document drafting workflow: add files/folders, mark scope, run Grok+ChatGPT iterative collaboration to produce a markdown draft, and optionally extract/import a parseable `## Suggested Tasks (importable)` section into SQLite tasks (with an approval/edit dialog).
- **Deep Research Tab** (`gui/deep_research_tab.py`): Web-first deep research pipeline. Runs iterative web research (max 8 rounds, 30-minute timebox) → synthesis → review gate → final research brief (markdown). The UI shows continuous “still working” status updates during research rounds. Artifacts persist to SQLite via `core/workflow_engine.py` + `core/db.py`, and the final brief is also written to `data/artifacts/<project_id>/research_brief.md`.
- **Billing Tab** (`gui/billing_tab.py`): Manual time entry + invoice draft generation. Uses SQLite tables for clients/time entries/templates/drafts. Drafts are generated from a user-defined template and written to `data/artifacts/invoice_drafts/<draft_id>/…` for review/export. Monthly auto-draft runs happen in-app (while the app is open) and prompt the user to review drafts.
- **Note-Taking System** (`gui/interface.py`): AI-powered note-taking with context setting, automatic formatting, dynamic categorization, and export capabilities. Uses local Llama model for processing with robust JSON response handling.
- **Tasks Tab** (`gui/tasks_tab.py`): Local (SQLite-backed) task manager. Uses the same task store as the Dashboard + CoS task capture. Supports search, filters, quick add, completion toggling, and deletion.
- **Compliance Tab** (`interface.py`): Three-column UI for uploading SOPs/URLs, analyzing with Grok, and displaying JSON results (`[{section, issue, fix, reference}]`).
- **Leads Tab** (`gui/leads_tab.py`): DB-backed lead generation with evidence-first web research, openFDA 510(k) enrichment, scoring/filters, and follow-up task creation (see `docs/lead_generation.md`).
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
- **Task storage (SQLite)**: Tasks are persisted in `core/db.py` (`tasks` table) and surfaced in Dashboard + Tasks tab. The Chief of Staff can create tasks via `ADD_TASK`.
- **Web research (OpenAI)**: Deep Research web research uses OpenAI (ChatGPT) via the Responses API + hosted `web_search` tool (`core.llm_collab.call_chatgpt_web_search`) and requires `OPENAI_API_KEY` when enabled. A fallback to non-browsing ChatGPT (`call_chatgpt_simple`) is used if web_search is unavailable.

## Database Schema
- **Tasks**: `id`, `session_id`, `task`, `due_date`, `completed`, `created_at`
- **News Items**: `id`, `title`, `content`, `url`, `source`, `published_date`, `created_at` (with duplicate prevention)
- **Notes**: `id`, `formatted_note`, `category`, `context`, `timestamp`, `created_at`
- **Dropbox Files**: `id`, `name`, `path`, `link`, `modified_time`, `size`
- **Conversations**: FTS5 virtual table for full-text search
- **Task Metadata**: Tasks are stored in SQLite with `id`, `task_text`, `due_date`, `category`, `recurrence`, `completed`, `created_at`.
- **Billing**:
  - `billing_clients`: clients, optional default rate/currency
  - `time_entries`: manual time entries (start/end/minutes/description/billable)
  - `invoice_templates`: user-editable template bodies with `{{placeholders}}`
  - `invoice_drafts`: rendered markdown drafts + totals + artifact file path

## Diagram
See `docs/diagrams/architecture.png`.

## Issue Tracking
Tasks tracked in Github issues (see repo Issues tab)
# NaviSsurance Overview

Last updated: 2026-04-03

## Purpose
NaviSsurance is a desktop-first MedTech consulting operations platform. It combines planning, delegation, drafting, research, billing, note-taking, compliance review, lead generation, and durable memory into one local application oriented around regulatory and client-service work.

The app is not just a chat shell. Its core value is domain workflow support for AI/ML, SaMD, IVD/LDT, and broader MedTech consulting.

## Current Product Surface

### Core user-facing areas
- **Dashboard**: Daily briefing, schedule, unreplied email triage, tasks, and news.
- **Chief of Staff**: Planning, delegation, AM Sweep, assignment board controls, and durable memory-aware triage.
- **Tasks**: Local SQLite-backed task and project management.
- **Workspace**: Document-centered drafting with multi-step collaboration and task extraction.
- **Deep Research**: Iterative web research plus synthesis into reusable markdown briefs.
- **Billing**: Time entry, invoice templates, draft generation, and review-first export.
- **Notes**: Long-running context documents with AI-assisted organization and export.
- **Leads**: Evidence-first MedTech lead generation with openFDA enrichment and scoring.
- **Compliance**: Grok-assisted compliance review of documents and URLs.
- **Meetings**: Audio transcription and downstream task/document workflows.

### Specialist-agent operating model
NaviSsurance includes a working Chief of Staff plus named specialists such as `Atlas`, `Quill`, `Scout`, `Ledger`, `Archive`, `Pulse`, and `Shield`. These agents are surfaced through assignment workflows, direct agent threads, artifacts, and board-level state rather than as abstract hidden subagents.

## Runtime And Integration Surface
The application now includes optional platform infrastructure beyond the PyQt UI:

- **Background runtime scheduler** via `core/runtime/`
- **Local HTTP API** via `api/app.py` and `core/service/local_api.py`
- **Shared typed tool registry** via `core/tool_registry.py`
- **Playwright browser tools** via `core/tools/browser.py`

These integrations are environment-gated. The desktop app and its built-in chat remain the intended user interface. The local API exists for internal/runtime integration paths rather than as a public or end-user remote chat surface.

## Memory And Retrieval
NaviSsurance now uses a layered memory system:
- `user_memory` for global Navi memory:
  - durable facts
  - preferences
  - aliases / glossary entries
- `cos_memory` for Chief of Staff planning, decisions, and open loops
- `agent_memory` for durable per-agent memory scoped to one named specialist
- `assignment_memory` for task-local, short-horizon memory tied to assignments and threads
- long-term chat retrieval with chunk summaries and raw-turn grounding
- daily/weekly memory reflections
- entity-scoped links for client and project-aware recall

The memory system remains SQLite-backed and auditable. Semantic retrieval is layered onto the structured stores rather than replacing them.

### Current memory behavior
- `Teach Navi:` writes approved memory into global Navi memory.
- `Teach <Agent>:` writes approved memory into that agent's private durable memory.
- Agent chats can passively learn into `agent_memory`.
- Assignment/thread work can passively write temporary memory into `assignment_memory`.
- Chief of Staff and Navi can supervise across memory layers through selective retrieval and promotion flows.
- Promotion paths currently exist for:
  - `agent_memory -> user_memory`
  - `assignment_memory -> agent_memory`

## Tech Stack
- **Application host**: Python, PyQt6, SQLite
- **Primary orchestration**: `core/main_chat_router.py`, `core/chief_of_staff_service.py`, `core/response_handler.py`
- **Local model path**: `Qwen3-14B-Q5_K_M.gguf` via the local runtime configured in `config.py`
- **Remote models/services**:
  - xAI Grok for CoS, compliance, lead-gen, and other shared remote flows
  - OpenAI Responses API hosted `web_search` for Deep Research when configured
  - AssemblyAI for transcription
- **Optional runtime infrastructure**:
  - APScheduler
  - FastAPI / uvicorn
  - Playwright
  - aiogram

## Current Status

### Implemented and active
- Chief of Staff planning and delegation
- assignment lifecycle and artifact workflows
- layered memory with global, CoS, agent, and assignment scopes
- local durable memory with approval and reflection layers
- Deep Research web workflow
- Billing drafts and exports
- Notes document workflow
- Leads scoring and evidence workflows
- background runtime scaffolding
- local API scaffolding
- browser automation scaffolding

### Implemented but still maturing
- runtime-backed follow-ups and recurring jobs
- entity-scoped and semantic memory retrieval
- service-boundary integrations that bypass the GUI
- browser-backed evidence capture workflows

### Still intentionally incomplete
- broad multi-channel parity
- fully generalized plugin ecosystem
- production-grade remote operations and observability
- clinical study design productization
- full CRM unification

## Related Docs
- `docs/user_manual.md` for user-facing workflows
- `docs/chief_of_staff.md` for CoS behavior, delegation, and memory
- `docs/design.md` for architecture
- `docs/api.md` for external integrations and the local API
- `docs/testing.md` for current validation flow
- `docs/roadmap_status.md` for active vs historical roadmap alignment
- `docs/contributor_guide.md` for source-of-truth guidance when docs, plans, and code diverge